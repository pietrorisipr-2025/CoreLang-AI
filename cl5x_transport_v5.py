# CL5XTransportV5 — deadlines, backpressure, pub/sub topics, multistream-friendly I/O
import time
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any
from collections import defaultdict, deque
import struct, hashlib

MAGIC=b'CL5X'
VER=1
TYPE_CONTROL=0; TYPE_DATA=1; TYPE_ACK=2; TYPE_ERROR=3; TYPE_FEC=4
FLAG_COMPRESS=0x01; FLAG_CH_PRESENT=0x02; FLAG_SEQ_PRESENT=0x04; FLAG_MORE=0x08
FLAG_REF=0x10; FLAG_PRIO1=0x20; FLAG_PRIO2=0x40; FLAG_RESERVED=0x80

def priority_to_flags(p:int)->int: return (FLAG_PRIO1 if (p&1) else 0)|(FLAG_PRIO2 if ((p>>1)&1) else 0)
def enc_varint(x:int)->bytes:
    if x<0: raise ValueError('varint must be non-negative')
    out=bytearray()
    while True:
        b=x & 0x7F; x >>= 7
        out.append(b | (0x80 if x else 0))
        if not x: break
    return bytes(out)
def dec_varint(buf:bytes, off:int):
    shift=0; val=0; pos=off
    while True:
        if pos>=len(buf): raise ValueError('truncated varint')
        b=buf[pos]; pos+=1
        val |= (b & 0x7F) << shift
        if (b & 0x80)==0: return val,pos
        shift += 7
@dataclass
class Frame:
    type:int; flags:int; dict_id:int; payload:bytes; chid:int=None; seq:int=None
def _crc32(b:bytes)->int:
    import zlib; return zlib.crc32(b) & 0xFFFFFFFF
def encode_frame(f:Frame, compress_level:int=3)->bytes:
    flags=f.flags; payload=f.payload
    if flags & FLAG_COMPRESS:
        import zlib; payload=zlib.compress(payload, level=compress_level)
    head=bytearray(); head+=MAGIC; head+=bytes([VER, f.type & 0xFF, f.flags & 0xFF])
    if f.flags & FLAG_CH_PRESENT:
        head += enc_varint(f.chid if f.chid is not None else 0)
    head += enc_varint(f.dict_id)
    if f.flags & FLAG_SEQ_PRESENT:
        head += enc_varint(f.seq if f.seq is not None else 0)
    head += enc_varint(len(payload))
    body=bytes(head)+payload
    return body + struct.pack('>I', _crc32(body))
class StreamDecoder:
    def __init__(self): self.buf=bytearray()
    def feed(self, data:bytes): self.buf += data
    def _try_one(self):
        if len(self.buf) < 4+1+1+1+4: return None
        if self.buf[:4] != MAGIC:
            idx=self.buf.find(MAGIC, 1)
            if idx==-1: self.buf=self.buf[-3:]; return None
            self.buf=self.buf[idx:]
            if len(self.buf) < 4+1+1+1+4: return None
        ver=self.buf[4]
        if ver!=VER: self.buf=self.buf[1:]; return None
        t=self.buf[5]; flags=self.buf[6]; off=7
        try:
            chid=None
            if flags & FLAG_CH_PRESENT: chid,off=dec_varint(self.buf,off)
            dict_id,off=dec_varint(self.buf,off)
            seq=None
            if flags & FLAG_SEQ_PRESENT: seq,off=dec_varint(self.buf,off)
            length,off=dec_varint(self.buf,off)
        except Exception: return None
        need=off+length+4
        if len(self.buf) < need: return None
        payload=bytes(self.buf[off:off+length])
        body=bytes(self.buf[:off])+payload
        crc=int.from_bytes(self.buf[off+length:off+length+4],'big')
        if _crc32(body)!=crc: self.buf=self.buf[1:]; return None
        self.buf=self.buf[need:]
        return Frame(t, flags, dict_id, payload, chid, seq)
    def read(self):
        out=[]
        while True:
            f=self._try_one()
            if f is None: break
            out.append(f)
        return out

BLOCK=512; DICT_ID=0x1A3
def blake2s(b:bytes)->bytes: return hashlib.blake2s(b, digest_size=32).digest()
def pack_v5(msg_id:int, created_ms:int, topic:int, data:bytes)->bytes:
    created_ms = created_ms & 0xFFFFFFFF
    return struct.pack('>QI', msg_id, created_ms) + enc_varint(topic) + data
def unpack_v5(b:bytes):
    if len(b)<12: return -1,0,0,b
    mid=int.from_bytes(b[:8],'big'); c_ms=int.from_bytes(b[8:12],'big')
    topic, off = dec_varint(b, 12)
    return mid, c_ms, topic, b[off:]
@dataclass
class Msg:
    chid:int; priority:int; deadline_ms:int; topic:int; full_payload:bytes; enqueued_ms:int
class V5Scheduler:
    def __init__(self, per_chid_tokens:int=8192, refill_per_ms:int=512):
        from collections import defaultdict, deque
        self.queues={3:deque(),2:deque(),1:deque(),0:deque()}
        self.tokens=defaultdict(lambda:per_chid_tokens)
        self.per_chid_cap=per_chid_tokens; self.refill_per_ms=refill_per_ms; self.last_refill_ms=0
    def refill(self, now_ms:int):
        delta=max(0, now_ms - self.last_refill_ms)
        if delta<=0: return
        add = delta * self.refill_per_ms
        for chid in list(self.tokens.keys()):
            self.tokens[chid] = min(self.per_chid_cap, self.tokens[chid] + add)
        self.last_refill_ms = now_ms
    def push(self, m:Msg): self.queues.get(m.priority, self.queues[1]).append(m)
    def pop(self, now_ms:int):
        for p in (3,2,1,0):
            q=self.queues[p]
            for m in list(q):
                if m.deadline_ms and now_ms > m.deadline_ms:
                    q.remove(m); continue
                if self.tokens[m.chid] >= BLOCK:
                    q.remove(m); return m
        return None
    def has(self)->bool:
        return any(self.queues[p] for p in self.queues)
class V5Sender:
    def __init__(self):
        from collections import defaultdict, deque
        self.seq=defaultdict(int); self.window=defaultdict(lambda:10)
        self.unacked=defaultdict(list)
        self.cache={}; self.cache_order=deque(); self.cache_cap=1024
        self.loss_ema=defaultdict(float)
        self.bytes_sent=0; self.frames_sent=0
        self.scheduler=V5Scheduler()
    def lru_put(self, h:bytes, content:bytes):
        if h in self.cache: return
        self.cache[h]=content; self.cache_order.append(h)
        if len(self.cache_order)>self.cache_cap:
            old=self.cache_order.popleft(); self.cache.pop(old,None)
    def can_send(self, chid:int)->bool: return len(self.unacked[chid]) < self.window[chid]
    def _emit(self, chid:int, f:Frame):
        raw=encode_frame(f)
        self.bytes_sent += len(raw); self.frames_sent += 1
        if f.flags & FLAG_SEQ_PRESENT:
            self.unacked[chid].append({'seq':f.seq,'raw':raw,'time':0,'chid':chid})
        return chid, raw
    def k_for_loss(self, chid:int):
        r=self.loss_ema[chid]
        if r>=0.05: return True,4
        if r>=0.02: return True,5
        if r>=0.01: return True,6
        return False,0
    def apply_sack(self, chid:int, ack:int, win:int, base:int, bitmap:int):
        zeros = 32 - bin(bitmap).count('1')
        ratio = zeros/32.0
        self.loss_ema[chid] = 0.8*self.loss_ema[chid] + 0.2*ratio
        self.unacked[chid] = [d for d in self.unacked[chid] if d['seq'] > ack]
        out=[]
        for d in list(self.unacked[chid]):
            s=d['seq']
            if s<=ack: continue
            if base <= s < base+32:
                bit=(s-base)
                if ((bitmap>>bit)&1)==0:
                    if d['time']>0:
                        d['time']=0; out.append((chid, d['raw']))
        self.window[chid] = max(self.window[chid], win) + 1
        return out
    def build_frames_for_message(self, m:Msg):
        out=[]; full=m.full_payload
        flags = FLAG_CH_PRESENT | FLAG_SEQ_PRESENT | priority_to_flags(m.priority)
        _,_,topic, content = unpack_v5(full)
        h=blake2s(content)
        if h in self.cache:
            ref = full[:12+len(enc_varint(topic))] + h
            s=self.seq[m.chid]; self.seq[m.chid]+=1
            f=Frame(TYPE_DATA, flags|FLAG_REF, DICT_ID, ref, chid=m.chid, seq=s)
            out.append(self._emit(m.chid, f)); return out
        else:
            self.lru_put(h, content)
        chunks=[full[i:i+BLOCK] for i in range(0,len(full),BLOCK)]
        use_fec,K=self.k_for_loss(m.chid); fec=[]
        for i,chunk in enumerate(chunks):
            fflags=flags
            if i < len(chunks)-1: fflags |= FLAG_MORE
            s=self.seq[m.chid]; self.seq[m.chid]+=1
            f=Frame(TYPE_DATA, fflags, DICT_ID, chunk, chid=m.chid, seq=s)
            out.append(self._emit(m.chid, f))
            if use_fec and len(chunk)==BLOCK:
                fec.append((s,chunk))
                if len(fec)==K:
                    parity=bytearray(BLOCK)
                    for _,ch in fec:
                        for j,b in enumerate(ch): parity[j]^=b
                    pld=enc_varint(fec[0][0])+enc_varint(K)+enc_varint(BLOCK)+bytes(parity)
                    s2=self.seq[m.chid]; self.seq[m.chid]+=1
                    sf=Frame(TYPE_FEC, FLAG_CH_PRESENT|FLAG_SEQ_PRESENT, DICT_ID, pld, chid=m.chid, seq=s2)
                    out.append(self._emit(m.chid, sf)); fec=[]
        return out
class V5Receiver:
    def __init__(self):
        from collections import defaultdict, deque
        self.decoder=StreamDecoder(); self.reasm_state={}
        self.cache={}; self.cache_order=deque(); self.cache_cap=1024
        self.have=defaultdict(set); self.seen=defaultdict(lambda:-1); self.contig=defaultdict(lambda:-1)
        self._raw=defaultdict(bytes); self.fec_groups=defaultdict(dict)
    def lru_put(self, h:bytes, content:bytes):
        if h in self.cache: return
        self.cache[h]=content; self.cache_order.append(h)
        if len(self.cache_order)>self.cache_cap:
            old=self.cache_order.popleft(); self.cache.pop(old,None)
    def mark(self, chid:int, seq:int):
        sset=self.have[chid]; sset.add(seq)
        self.seen[chid]=max(self.seen[chid], seq)
        hc=self.contig[chid]
        while (hc+1) in sset: hc+=1
        self.contig[chid]=hc
    def add_fec(self, chid:int, start:int, K:int, L:int, parity:bytes):
        self.fec_groups[chid][start]={'K':K,'len':L,'parity':parity}
    def try_fec(self, chid:int, start:int):
        grp=self.fec_groups[chid].get(start)
        if not grp: return []
        K=grp['K']; L=grp['len']; parity=bytearray(grp['parity'])
        present=[s for s in range(start, start+K) if s in self.have[chid]]
        missing=[s for s in range(start, start+K) if s not in self.have[chid]]
        if len(missing)!=1: return []
        miss=missing[0]
        accum=bytearray(L)
        for s in present:
            chunk=self._raw[(chid,s)]
            if len(chunk)!=L: return []
            for i,b in enumerate(chunk): accum[i]^=b
        rec=bytes([parity[i]^accum[i] for i in range(L)])
        f=Frame(TYPE_DATA, FLAG_CH_PRESENT|FLAG_SEQ_PRESENT|FLAG_MORE, DICT_ID, rec, chid=chid, seq=miss)
        return [f]
    def reasm_feed(self, f:Frame):
        if not (f.flags & FLAG_SEQ_PRESENT): return f.payload
        key=(f.chid, f.dict_id)
        st=self.reasm_state.get(key)
        if st is None:
            st={'bufs':{}, 'start_seq':f.seq, 'next_seq':f.seq, 'final_seq':None}; self.reasm_state[key]=st
        st['bufs'][f.seq]=f.payload
        if not (f.flags & FLAG_MORE): st['final_seq']=f.seq
        while st['next_seq'] in st['bufs']: st['next_seq']+=1
        if st['final_seq'] is not None:
            if all(seq in st['bufs'] for seq in range(st['start_seq'], st['final_seq']+1)):
                ordered=[st['bufs'][i] for i in range(st['start_seq'], st['final_seq']+1)]
                payload=b''.join(ordered); del self.reasm_state[key]; return payload
        return None
    def handle(self, f:Frame):
        if f.type==TYPE_DATA:
            self._raw[(f.chid,f.seq)] = f.payload
            self.mark(f.chid, f.seq)
            if f.flags & FLAG_REF:
                off=12
                try:
                    _, off = dec_varint(f.payload, off)
                    h = f.payload[off:off+32]
                    content = self.cache.get(h, None)
                    if content is None:
                        base=self.contig[f.chid]+1; bm=0
                        return None, (f.chid, self.contig[f.chid], base, bm)
                    payload = f.payload[:off] + content
                except Exception:
                    base=self.contig[f.chid]+1; bm=0
                    return None, (f.chid, self.contig[f.chid], base, bm)
            else:
                payload=f.payload
            f2=Frame(TYPE_DATA, f.flags, f.dict_id, payload, chid=f.chid, seq=f.seq)
            hc=self.contig[f.chid]; base=hc+1; bm=0
            for i in range(32):
                s=base+i
                if s in self.have[f.chid]: bm |= (1<<i)
            return f2, (f.chid, hc, base, bm)
        elif f.type==TYPE_FEC:
            off=0; start,off=dec_varint(f.payload,off); K,off=dec_varint(f.payload,off); L,off=dec_varint(f.payload,off)
            parity=f.payload[off:off+L]; self.add_fec(f.chid, start, K, L, parity)
            new_frames=self.try_fec(f.chid, start)
            f2=None
            for nf in new_frames:
                self._raw[(nf.chid,nf.seq)] = nf.payload
                self.mark(nf.chid, nf.seq)
                f2=nf
            hc=self.contig[f.chid]; base=hc+1; bm=0
            for i in range(32):
                s=base+i
                if s in self.have[f.chid]: bm |= (1<<i)
            return f2, (f.chid, hc, base, bm)
        else:
            hc=self.contig[f.chid if f.chid is not None else 0]
            return None, (f.chid if f.chid is not None else 0, hc, hc+1, 0)
class CL5XTransportV5:
    def __init__(self, on_message):
        self.sender=V5Sender(); self.receiver=V5Receiver(); self.decoder=StreamDecoder()
        self.on_message=on_message; self.pending_ack={}; self._msg_id=0; self._seen=set(); self.topic_handlers={}
    def subscribe(self, topic:int, handler): self.topic_handlers[topic]=handler
    def publish(self, topic:int, data:bytes, priority:int=2, ttl_ms:int=2000, chid:int=1, now_ms:int=None):
        now_ms = now_ms if now_ms is not None else int(time.time()*1000)
        deadline = now_ms + max(0, ttl_ms)
        msg_id = (self._msg_id & ((1<<56)-1)); self._msg_id += 1
        full = pack_v5(msg_id, now_ms, topic, data)
        m = Msg(chid=chid, priority=priority, deadline_ms=deadline, topic=topic, full_payload=full, enqueued_ms=now_ms)
        self.sender.scheduler.push(m)
    def next_frames_to_send(self, now_ms:int):
        out=[]; self.sender.scheduler.refill(now_ms)
        for chid,lst in list(self.sender.unacked.items()):
            for d in list(lst):
                if d['time']>0 and now_ms - d['time'] > 1500:
                    self.sender.window[chid]=max(2, self.sender.window[chid]//2)
                    d['time']=now_ms; out.append((chid, d['raw'])); break
        while True:
            if not self.sender.scheduler.has(): break
            m=self.sender.scheduler.pop(now_ms)
            if not m: break
            frames=self.sender.build_frames_for_message(m)
            self.sender.scheduler.tokens[m.chid] = max(0, self.sender.scheduler.tokens[m.chid] - BLOCK)
            for chid, raw in frames:
                for d in reversed(self.sender.unacked[chid]):
                    if d['time']==0: d['time']=now_ms; break
                out.append((chid, raw))
        return out
    def feed_bytes(self, from_stream_chid:int, now_ms:int, data:bytes):
        out=[]; self.decoder.feed(data)
        for f in self.decoder.read():
            if f.type==TYPE_ACK:
                off=0
                try:
                    ack,off=dec_varint(f.payload,off)
                    win,off=dec_varint(f.payload,off)
                    base,off=dec_varint(f.payload,off)
                    bm,off=dec_varint(f.payload,off)
                except Exception: continue
                out += self.sender.apply_sack(f.chid, ack, win, base, bm)
                continue
            f2, ackt = self.receiver.handle(f)
            if ackt:
                chid,hc,base,bm = ackt
                old = self.pending_ack.get(chid, (-1,0,0))
                agg_bm = (bm | old[2]) if base==old[1] else bm
                self.pending_ack[chid]=(max(old[0], hc), base, agg_bm)
                hc2, base2, bm2 = self.pending_ack.pop(chid)
                pld = enc_varint(hc2) + enc_varint(max(2, self.sender.window[chid])) + enc_varint(base2) + enc_varint(bm2)
                af = Frame(TYPE_ACK, FLAG_CH_PRESENT, DICT_ID, pld, chid=chid, seq=None)
                out.append((chid, encode_frame(af)))
            if f2:
                pay=self.receiver.reasm_feed(f2)
                if pay:
                    # v5 header
                    if len(pay)>=12:
                        # parse topic
                        mid = int.from_bytes(pay[:8],'big'); c_ms=int.from_bytes(pay[8:12],'big')
                        topic, off = dec_varint(pay, 12)
                        content = pay[off:]
                        if c_ms>0 and mid not in getattr(self, '_seen', set()):
                            self._seen = getattr(self, '_seen', set()); self._seen.add(mid)
                            h = self.topic_handlers.get(topic)
                            if h: h(topic, content)
                            else: self.on_message(f2.chid, content, topic)
        return out
