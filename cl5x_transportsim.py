# cl5x_transportsim.py
# Advanced CL5X transport (encode/decode + scheduler + retransmit) and simulator

import struct, zlib, io, hashlib, random, math
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any
from collections import deque, defaultdict

MAGIC = b"CL5X"
VER = 1

TYPE_CONTROL=0
TYPE_DATA=1
TYPE_ACK=2
TYPE_ERROR=3

FLAG_COMPRESS=0x01
FLAG_CH_PRESENT=0x02
FLAG_SEQ_PRESENT=0x04
FLAG_MORE=0x08
FLAG_REF=0x10
FLAG_PRIO1=0x20
FLAG_PRIO2=0x40
FLAG_RESERVED=0x80

def priority_to_flags(priority:int)->int:
    b0=(priority & 1); b1=(priority>>1)&1
    return (FLAG_PRIO1 if b0 else 0) | (FLAG_PRIO2 if b1 else 0)

def flags_to_priority(flags:int)->int:
    b0=1 if (flags & FLAG_PRIO1) else 0
    b1=1 if (flags & FLAG_PRIO2) else 0
    return (b1<<1)|b0

def enc_varint(x:int)->bytes:
    if x<0: raise ValueError("varint must be non-negative")
    out=bytearray()
    while True:
        b=x & 0x7F; x >>= 7
        out.append(b | (0x80 if x else 0))
        if not x: break
    return bytes(out)

def dec_varint(buf:bytes, offset:int):
    shift=0; val=0; pos=offset
    while True:
        if pos>=len(buf): raise ValueError("Truncated varint")
        b=buf[pos]; pos+=1
        val |= (b & 0x7F) << shift
        if (b & 0x80)==0: return val, pos
        shift += 7
        if shift>63: raise ValueError("varint too long")

@dataclass
class Frame:
    type:int
    flags:int
    dict_id:int
    payload:bytes
    chid:Optional[int]=None
    seq:Optional[int]=None

def _crc32(data:bytes)->int:
    return zlib.crc32(data) & 0xFFFFFFFF

def encode_frame(f:Frame, compress_level:int=3)->bytes:
    flags=f.flags; payload=f.payload
    if flags & FLAG_COMPRESS:
        payload = zlib.compress(payload, level=compress_level)
    head=bytearray()
    head += MAGIC
    head += struct.pack("B", VER)
    head += struct.pack("B", f.type & 0xFF)
    head += struct.pack("B", flags & 0xFF)
    if flags & FLAG_CH_PRESENT:
        if f.chid is None: raise ValueError("FLAG_CH_PRESENT set but chid is None")
        head += enc_varint(f.chid)
    head += enc_varint(f.dict_id)
    if flags & FLAG_SEQ_PRESENT:
        if f.seq is None: raise ValueError("FLAG_SEQ_PRESENT set but seq is None")
        head += enc_varint(f.seq)
    head += enc_varint(len(payload))
    body = bytes(head) + payload
    crc = struct.pack(">I", _crc32(body))
    return body + crc

class StreamDecoder:
    def __init__(self):
        self.buf = bytearray()
    def feed(self, data:bytes): self.buf += data
    def _try_parse_one(self):
        if len(self.buf) < 4+1+1+1+4: return None
        if self.buf[:4] != MAGIC:
            idx = self.buf.find(MAGIC, 1)
            if idx == -1: self.buf = self.buf[-3:]; return None
            else:
                self.buf = self.buf[idx:]
                if len(self.buf) < 4+1+1+1+4: return None
        ver=self.buf[4]
        if ver != VER: raise ValueError(f"Unsupported version {ver}")
        t=self.buf[5]; flags=self.buf[6]; offset=7
        try:
            if flags & FLAG_CH_PRESENT:
                chid, offset = dec_varint(self.buf, offset)
            else:
                chid = None
            dict_id, offset = dec_varint(self.buf, offset)
            if flags & FLAG_SEQ_PRESENT:
                seq, offset = dec_varint(self.buf, offset)
            else:
                seq = None
            length, offset = dec_varint(self.buf, offset)
        except ValueError:
            return None
        needed = offset + length + 4
        if len(self.buf) < needed: return None
        payload = bytes(self.buf[offset:offset+length])
        body = bytes(self.buf[:offset]) + payload
        crc_expect = struct.unpack(">I", self.buf[offset+length:offset+length+4])[0]
        if _crc32(body) != crc_expect:
            self.buf = self.buf[1:]
            raise ValueError("Bad CRC32 (stream may be desynced)")
        self.buf = self.buf[needed:]
        if flags & FLAG_COMPRESS:
            payload = zlib.decompress(payload)
        return Frame(type=t, flags=flags, dict_id=dict_id, payload=payload, chid=chid, seq=seq)
    def read(self)->List[Frame]:
        out=[]
        while True:
            f=self._try_parse_one()
            if f is None: break
            out.append(f)
        return out

class ReassemblerOOO:
    """Out-of-order tolerant reassembler keyed by (chid, dict_id)."""
    def __init__(self):
        self.state: Dict[Any, Dict[str, Any]] = {}
    def feed(self, f:Frame, key=None) -> Optional[bytes]:
        if not (f.flags & FLAG_SEQ_PRESENT):
            return f.payload
        key = key or (f.chid, f.dict_id)
        st = self.state.get(key)
        if st is None:
            st = {"bufs": {}, "start_seq": f.seq, "next_seq": f.seq, "final_seq": None}
            self.state[key] = st
        st["bufs"][f.seq] = f.payload
        if not (f.flags & FLAG_MORE):
            st["final_seq"] = f.seq
        while st["next_seq"] in st["bufs"]:
            st["next_seq"] += 1
        if st["final_seq"] is not None:
            if all(seq in st["bufs"] for seq in range(st["start_seq"], st["final_seq"] + 1)):
                ordered = [st["bufs"][seq] for seq in range(st["start_seq"], st["final_seq"] + 1)]
                payload = b"".join(ordered)
                del self.state[key]
                return payload
        return None

def compress_decision(data:bytes)->bool:
    if len(data) < 96: return False
    uniq = len(set(data[:256]))
    if uniq > 200: return False
    return True

def blake2s_hash(data:bytes)->bytes:
    return hashlib.blake2s(data, digest_size=32).digest()

@dataclass
class Message:
    chid:int
    data:bytes
    priority:int=1
    created_ms:int=0
    id:int=0

class Scheduler:
    def __init__(self):
        self.queues = {3:deque(), 2:deque(), 1:deque(), 0:deque()}
    def push(self, msg:Message):
        self.queues.get(msg.priority, self.queues[1]).append(msg)
    def pop(self)->Optional[Message]:
        for p in (3,2,1,0):
            if self.queues[p]:
                return self.queues[p].popleft()
        return None
    def has_pending(self)->bool:
        return any(self.queues[p] for p in self.queues)

class Sender:
    def __init__(self, dict_id:int, max_payload:int=256, dedup_cache=256):
        self.dict_id=dict_id
        self.max_payload=max_payload
        self.seq_counter=defaultdict(int)
        self.window=defaultdict(lambda:4)
        self.unacked=defaultdict(list)  # dicts {seq,time,raw,size}
        self.scheduler=Scheduler()
        self.cache = {}  # hash->content
        self.cache_order = deque()
        self.cache_cap = dedup_cache
        self.bytes_sent = 0
        self.frames_sent = 0
    def lru_put(self, h:bytes, content:bytes):
        if h in self.cache: return
        self.cache[h]=content; self.cache_order.append(h)
        if len(self.cache_order) > self.cache_cap:
            old=self.cache_order.popleft()
            self.cache.pop(old, None)
    def can_send(self, chid:int)->bool:
        return len(self.unacked[chid]) < self.window[chid]
    def on_ack(self, chid:int, ack_seq:int, new_window:int, now_ms:int, enhanced:bool):
        self.unacked[chid] = [d for d in self.unacked[chid] if d["seq"] > ack_seq]
        if enhanced:
            self.window[chid] = max(self.window[chid], new_window) + 1
        else:
            self.window[chid] = new_window
    def timeouts(self, now_ms:int, rtt_ms:int)->List[Tuple[int, dict]]:
        res=[]
        for chid, lst in self.unacked.items():
            for d in lst:
                if now_ms - d["time"] > int(1.5*rtt_ms):
                    res.append((chid, d))
        return res
    def detect_timeout(self, chid:int, now_ms:int, rtt_ms:int, enhanced:bool):
        if not self.unacked[chid]: return
        oldest_time = min(d["time"] for d in self.unacked[chid])
        if now_ms - oldest_time > int(1.5*rtt_ms) and enhanced:
            self.window[chid] = max(2, self.window[chid]//2)
    def track_sent(self, chid:int, seq:int, now_ms:int, raw:bytes):
        self.unacked[chid].append({"seq":seq, "time":now_ms, "raw":raw, "size":len(raw)})
    def build_frames_for_message(self, msg:Message, enhanced:bool)->List[Frame]:
        frames=[]
        full = msg.data  # header(12)+content
        flags = FLAG_CH_PRESENT | FLAG_SEQ_PRESENT | priority_to_flags(msg.priority)
        # dedup
        if enhanced:
            header = full[:12] if len(full)>=12 else b""
            content = full[12:] if len(full)>=12 else full
            h = blake2s_hash(content)
            if h in self.cache:
                ref_payload = header + h
                f_flags = flags | FLAG_REF
                seq = self.seq_counter[msg.chid]; self.seq_counter[msg.chid]+=1
                f = Frame(type=TYPE_DATA, flags=f_flags, dict_id=self.dict_id,
                          payload=ref_payload, chid=msg.chid, seq=seq)
                frames.append(f); return frames
            else:
                self.lru_put(h, content)
        # compression heuristic on content
        if enhanced:
            content = full[12:] if len(full)>=12 else full
            if compress_decision(content): flags |= FLAG_COMPRESS
        # fragmentation of full payload
        pos=0
        while pos < len(full):
            chunk = full[pos:pos+self.max_payload]
            pos += len(chunk)
            f_flags = flags
            if pos < len(full): f_flags |= FLAG_MORE
            seq = self.seq_counter[msg.chid]; self.seq_counter[msg.chid]+=1
            f = Frame(type=TYPE_DATA, flags=f_flags, dict_id=self.dict_id,
                      payload=chunk, chid=msg.chid, seq=seq)
            frames.append(f)
        return frames

class Receiver:
    def __init__(self, dict_id:int, cache_cap=256):
        self.dict_id=dict_id
        self.decoder=StreamDecoder()
        self.reasm=ReassemblerOOO()
        self.cache={}       # hash(content)->content
        self.cache_order=deque()
        self.cache_cap=cache_cap
        self.bytes_recv=0
        self.frames_recv=0
    def lru_put(self, h:bytes, content:bytes):
        if h in self.cache: return
        self.cache[h]=content; self.cache_order.append(h)
        if len(self.cache_order) > self.cache_cap:
            old=self.cache_order.popleft()
            self.cache.pop(old, None)

@dataclass
class LinkParams:
    rtt_ms:int=100
    loss_pct:float=1.0
    jitter_ms:int=5

class EventLoop:
    def __init__(self):
        self.now=0
        self.events=[]; self._counter=0
    def call_later(self, delay_ms:int, fn):
        t=self.now+max(0, int(delay_ms))
        self._counter+=1
        self.events.append((t, self._counter, fn))
        self.events.sort(key=lambda x:(x[0], x[1]))
    def run(self, until_ms:int=60000):
        while self.events and self.now <= until_ms:
            t,_,fn = self.events.pop(0)
            self.now = t
            fn()

def pack_payload(msg_id:int, created_ms:int, data:bytes)->bytes:
    return struct.pack(">QI", msg_id, created_ms) + data
def unpack_payload(pay:bytes)->Tuple[int,int,bytes]:
    if len(pay) < 12: return -1, 0, pay
    mid = struct.unpack(">Q", pay[:8])[0]
    c_ms = struct.unpack(">I", pay[8:12])[0]
    return mid, c_ms, pay[12:]

class SimEndpoint:
    def __init__(self, name:str, loop:EventLoop, link:LinkParams, dict_id:int=0x1A3, enhanced:bool=False):
        self.name=name; self.loop=loop; self.link=link
        self.sender=Sender(dict_id=dict_id, max_payload=(512 if enhanced else 1024), dedup_cache=(512 if enhanced else 0))
        self.receiver=Receiver(dict_id=dict_id, cache_cap=(512 if enhanced else 0))
        self.enhanced=enhanced; self.peer=None
        self.msg_id_counter=0
        self.acks_pending = defaultdict(int)
        self.ack_debounce_ms = 10
        self.decoder = StreamDecoder()
        self.received_latencies: List[int] = []
    def set_peer(self, peer:'SimEndpoint'): self.peer=peer
    def send_bytes(self, raw:bytes):
        one_way = self.link.rtt_ms//2
        jitter = random.randint(-self.link.jitter_ms, self.link.jitter_ms)
        delay = max(0, one_way + jitter)
        if random.random()*100 < self.link.loss_pct: return
        def deliver(): self.peer.receive_bytes(raw)
        self.loop.call_later(delay, deliver)
    def receive_bytes(self, raw:bytes):
        self.decoder.feed(raw)
        frames = self.decoder.read()
        for f in frames:
            if f.type == TYPE_ACK:
                try:
                    ack_seq, off = dec_varint(f.payload, 0)
                    win, off2 = dec_varint(f.payload, off)
                except Exception: continue
                self.sender.on_ack(f.chid if f.chid is not None else 0, ack_seq, win, self.loop.now, self.enhanced)
                continue
            if f.type == TYPE_DATA:
                if f.flags & FLAG_COMPRESS:
                    try:
                        f.payload = zlib.decompress(f.payload)
                        f.flags &= ~FLAG_COMPRESS
                    except Exception: continue
                if f.flags & FLAG_REF:
                    if len(f.payload) < 12+32: continue
                    header = f.payload[:12]; h = f.payload[12:12+32]
                    content = self.receiver.cache.get(h, None)
                    if content is None: continue
                    reconstructed = header + content
                    faux = Frame(type=f.type, flags=f.flags & ~FLAG_REF, dict_id=f.dict_id,
                                 payload=reconstructed, chid=f.chid, seq=f.seq)
                    pay = self.receiver.reasm.feed(faux, key=(f.chid, f.dict_id))
                else:
                    pay = self.receiver.reasm.feed(f, key=(f.chid, f.dict_id))
                if f.seq is not None and f.chid is not None:
                    self.acks_pending[f.chid] = max(self.acks_pending[f.chid], f.seq)
                    self.schedule_ack(f.chid)
                if pay is not None:
                    mid, c_ms, content = unpack_payload(pay)
                    h = blake2s_hash(content); self.receiver.lru_put(h, content)
                    if c_ms>0: self.received_latencies.append(self.loop.now - c_ms)
    def schedule_ack(self, chid:int):
        def send_ack():
            seq = self.acks_pending.get(chid, None)
            if seq is None: return
            ack_payload = enc_varint(seq) + enc_varint(max(2, self.peer.sender.window[chid]))
            flags = FLAG_CH_PRESENT
            f = Frame(type=TYPE_ACK, flags=flags, dict_id=self.sender.dict_id, payload=ack_payload, chid=chid, seq=None)
            raw = encode_frame(f)
            self.send_bytes(raw)
            self.acks_pending.pop(chid, None)
        self.loop.call_later(self.ack_debounce_ms, send_ack)
    def process_app_queue(self):
        while True:
            found=None
            for p in (3,2,1,0):
                q=self.sender.scheduler.queues[p]
                for msg in list(q):
                    if self.sender.can_send(msg.chid):
                        found=msg; q.remove(msg); break
                if found: break
            if not found: break
            msg=found
            frames = self.sender.build_frames_for_message(msg, enhanced=self.enhanced)
            for f in frames:
                raw = encode_frame(f)
                self.sender.bytes_sent += len(raw); self.sender.frames_sent += 1
                self.sender.unacked[f.chid].append({"seq":f.seq, "time":self.loop.now, "raw":raw, "size":len(raw)})
                self.send_bytes(raw)
    def tick(self):
        # retransmit oldest timeout per chid
        for chid, lst in list(self.sender.unacked.items()):
            to_send=None
            for d in lst:
                if self.loop.now - d["time"] > int(1.5*self.link.rtt_ms):
                    to_send=d; break
            if to_send is not None:
                if self.enhanced:
                    self.sender.window[chid] = max(2, self.sender.window[chid]//2)
                to_send["time"]=self.loop.now; self.send_bytes(to_send["raw"])
        for chid in list(self.sender.window.keys()):
            self.sender.detect_timeout(chid, self.loop.now, self.link.rtt_ms, self.enhanced)
        self.process_app_queue()
    def app_send(self, chid:int, data:bytes, priority:int, now_ms:int):
        msg_id = id(data) & ((1<<56)-1)  # pseudo id
        full = pack_payload(msg_id, now_ms, data)
        m = Message(chid=chid, data=full, priority=priority, created_ms=now_ms, id=msg_id)
        self.sender.scheduler.push(m)

@dataclass
class ScenarioResult:
    name:str
    total_bytes_sent:int
    total_frames_sent:int
    delivered:int
    p50_latency_ms:float
    p95_latency_ms:float
    avg_latency_ms:float
    duration_ms:int

def run_scenario(name:str, enhanced:bool, link:LinkParams, messages:List[Tuple[int,bytes,int]])->ScenarioResult:
    loop=EventLoop()
    a=SimEndpoint("A", loop, link, enhanced=enhanced)
    b=SimEndpoint("B", loop, link, enhanced=enhanced)
    a.set_peer(b); b.set_peer(a)
    t0=0
    for (chid, data, prio) in messages:
        def schedule_send(chid=chid, data=data, prio=prio, t=t0):
            a.app_send(chid, data, prio, loop.now)
            a.tick(); b.tick()
        loop.call_later(t0, schedule_send)
        t0 += random.randint(1, 4)
    def tick_all():
        a.tick(); b.tick()
        loop.call_later(5, tick_all)
    loop.call_later(0, tick_all)
    loop.run(until_ms=120000)
    latencies=b.received_latencies[:]
    if len(latencies)==0:
        p50=p95=avg=math.nan
    else:
        latencies_sorted=sorted(latencies)
        p50 = latencies_sorted[len(latencies_sorted)//2]
        p95 = latencies_sorted[max(0, int(0.95*len(latencies_sorted))-1)]
        avg = sum(latencies_sorted)/len(latencies_sorted)
    return ScenarioResult(
        name=name,
        total_bytes_sent=a.sender.bytes_sent + b.sender.bytes_sent,
        total_frames_sent=a.sender.frames_sent + b.sender.frames_sent,
        delivered=len(latencies),
        p50_latency_ms=p50,
        p95_latency_ms=p95,
        avg_latency_ms=avg,
        duration_ms=loop.now
    )
