# cl5x_transport_v4.py
# CL5X v4 transport: block-aligned fragmentation (512B), SACK-in-ACK, adaptive FEC(1,K)
import hashlib, time
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict
from collections import defaultdict, deque

from cl5x_core import (
    Frame, StreamDecoder, encode_frame,
    TYPE_DATA, TYPE_ACK, TYPE_FEC,
    FLAG_CH_PRESENT, FLAG_SEQ_PRESENT, FLAG_MORE, FLAG_REF,
    priority_to_flags, enc_varint, dec_varint
)

BLOCK=512
DICT_ID=0x1A3

def blake2s(b:bytes)->bytes: return hashlib.blake2s(b, digest_size=32).digest()

def pack_payload(msg_id:int, created_ms:int, data:bytes)->bytes:
    import struct
    return struct.pack(">QI", msg_id, created_ms)+data

def unpack_payload(b:bytes)->Tuple[int,int,bytes]:
    import struct
    if len(b)<12: return -1,0,b
    return struct.unpack(">Q", b[:8])[0], struct.unpack(">I", b[8:12])[0], b[12:]

@dataclass
class Message:
    chid:int; data:bytes; priority:int

class Sender:
    def __init__(self):
        self.seq=defaultdict(int); self.window=defaultdict(lambda:10)
        self.unacked=defaultdict(list)  # list of dict(seq, raw, time_sent_ms)
        self.cache={}; self.cache_order=deque(); self.cache_cap=1024
        self.loss_ema=defaultdict(float)
        self.bytes_sent=0; self.frames_sent=0

    def _now(self)->int: return int(time.time()*1000)

    def lru_put(self, h:bytes, content:bytes):
        if h in self.cache: return
        self.cache[h]=content; self.cache_order.append(h)
        if len(self.cache_order)>self.cache_cap:
            old=self.cache_order.popleft(); self.cache.pop(old,None)

    def can_send(self, chid:int)->bool: return len(self.unacked[chid]) < self.window[chid]

    def k_for_loss(self, chid:int)->Tuple[bool,int]:
        r=self.loss_ema[chid]
        if r >= 0.05: return True, 4
        if r >= 0.02: return True, 5
        if r >= 0.01: return True, 6
        return False, 0

    def apply_sack(self, chid:int, ack:int, win:int, base:int, bitmap:int)->List[bytes]:
        # update loss EMA
        zeros = 32 - bin(bitmap).count("1")
        ratio = zeros/32.0
        self.loss_ema[chid] = 0.8*self.loss_ema[chid] + 0.2*ratio
        # drop acked
        self.unacked[chid] = [d for d in self.unacked[chid] if d["seq"] > ack]
        # fast rtx for holes
        out=[]
        for d in list(self.unacked[chid]):
            s=d["seq"]
            if s<=ack: continue
            if base <= s < base+32:
                bit=(s-base)
                if ((bitmap>>bit)&1)==0:
                    if d["time"]>0:
                        d["time"]=0; out.append(d["raw"])
        # AIMD-ish
        self.window[chid] = max(self.window[chid], win) + 1
        return out

    def _emit(self, f:Frame)->bytes:
        raw=encode_frame(f)
        self.bytes_sent += len(raw); self.frames_sent += 1
        if f.flags & FLAG_SEQ_PRESENT:
            self.unacked[f.chid].append({"seq":f.seq, "raw":raw, "time":0})
        return raw

    def build_frames_for_message(self, m:Message)->List[bytes]:
        frames_raw=[]
        full = m.data
        flags = FLAG_CH_PRESENT | FLAG_SEQ_PRESENT | priority_to_flags(m.priority)
        # Dedup: ignore 12B header for hash
        content = full[12:] if len(full)>=12 else full
        h=blake2s(content)
        if h in self.cache:
            ref = full[:12] + h
            f=Frame(TYPE_DATA, flags|FLAG_REF, DICT_ID, ref, chid=m.chid, seq=self.seq[m.chid]); self.seq[m.chid]+=1
            frames_raw.append(self._emit(f)); return frames_raw
        else:
            self.lru_put(h, content)

        # 512B block segmentation
        chunks = [full[i:i+BLOCK] for i in range(0, len(full), BLOCK)]
        use_fec, K = self.k_for_loss(m.chid)
        fec_bucket=[]
        for i,chunk in enumerate(chunks):
            fflags=flags
            if i < len(chunks)-1: fflags |= FLAG_MORE
            s=self.seq[m.chid]; self.seq[m.chid]+=1
            f=Frame(TYPE_DATA, fflags, DICT_ID, chunk, chid=m.chid, seq=s)
            frames_raw.append(self._emit(f))
            # FEC only for full-size chunks
            if use_fec and len(chunk)==BLOCK:
                fec_bucket.append((s,chunk))
                if len(fec_bucket)==K:
                    # XOR parity
                    parity=bytearray(BLOCK)
                    for _,ch in fec_bucket:
                        for j,b in enumerate(ch): parity[j]^=b
                    pld=enc_varint(fec_bucket[0][0]) + enc_varint(K) + enc_varint(BLOCK) + bytes(parity)
                    sf=Frame(TYPE_FEC, FLAG_CH_PRESENT|FLAG_SEQ_PRESENT, DICT_ID, pld, chid=m.chid, seq=self.seq[m.chid]); self.seq[m.chid]+=1
                    frames_raw.append(self._emit(sf)); fec_bucket=[]
        return frames_raw

class ReassemblerOOO:
    def __init__(self): self.state={}
    def feed(self, f:Frame, key=None)->Optional[bytes]:
        if not (f.flags & FLAG_SEQ_PRESENT): return f.payload
        key=key or (f.chid, f.dict_id)
        st=self.state.get(key)
        if st is None:
            st={"bufs":{}, "start_seq":f.seq, "next_seq":f.seq, "final_seq":None}; self.state[key]=st
        st["bufs"][f.seq]=f.payload
        if not (f.flags & FLAG_MORE): st["final_seq"]=f.seq
        while st["next_seq"] in st["bufs"]: st["next_seq"]+=1
        if st["final_seq"] is not None:
            if all(seq in st["bufs"] for seq in range(st["start_seq"], st["final_seq"]+1)):
                ordered=[st["bufs"][i] for i in range(st["start_seq"], st["final_seq"]+1)]
                payload=b"".join(ordered); del self.state[key]; return payload
        return None

class Receiver:
    def __init__(self):
        self.decoder=StreamDecoder(); self.reasm=ReassemblerOOO()
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
        self.fec_groups[chid][start]={"K":K,"len":L,"parity":parity}

    def try_fec(self, chid:int, start:int)->List[Frame]:
        grp=self.fec_groups[chid].get(start)
        if not grp: return []
        K=grp["K"]; L=grp["len"]; parity=bytearray(grp["parity"])
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

    def handle(self, f:Frame)->Tuple[Optional[Frame], Tuple[int,int,int,int]]:
        # returns (frame_for_reassembly_or_None, sack_tuple=(chid, hc, base, bitmap32))
        if f.type==TYPE_DATA:
            self._raw[(f.chid,f.seq)] = f.payload
            self.mark(f.chid, f.seq)
            # resolve REF
            if f.flags & FLAG_REF:
                if len(f.payload) < 12+32:
                    base=self.contig[f.chid]+1; bm=0
                    return None, (f.chid, self.contig[f.chid], base, bm)
                header=f.payload[:12]; h=f.payload[12:44]
                content=self.cache.get(h, None)
                if content is None:
                    base=self.contig[f.chid]+1; bm=0
                    return None, (f.chid, self.contig[f.chid], base, bm)
                payload=header+content
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

class CL5XTransport:
    """High-level transport object to plug into sockets/streams."""
    def __init__(self, on_message):
        self.sender=Sender(); self.receiver=Receiver()
        self.decoder=StreamDecoder()
        self.on_message=on_message
        self.pending_ack={}  # chid -> (hc, base, bm)
        self._msg_id=0; self._seen=set()

    def enqueue_message(self, chid:int, priority:int, data:bytes, now_ms:int)->None:
        # pack header (12B) inside; Sender dedups on content-only
        msg_id = (self._msg_id & ((1<<56)-1)); self._msg_id += 1
        full = pack_payload(msg_id, now_ms, data)
        m=Message(chid, full, priority)
        # store in scheduler by pushing directly (we reuse Sender internals via a small shim)
        if not hasattr(self.sender, "scheduler"):
            from collections import deque
            self.sender.scheduler = type("S", (), {"q":{3:deque(),2:deque(),1:deque(),0:deque()}})()
        self.sender.scheduler.q[priority].append(m)

    def _pop_scheduled(self, can_send)->Optional[Message]:
        for p in (3,2,1,0):
            q=self.sender.scheduler.q[p]
            for m in list(q):
                if can_send(m.chid): q.remove(m); return m
        return None

    def next_frames_to_send(self, now_ms:int)->List[bytes]:
        out=[]
        # retransmit timed-out oldest per chid
        for chid,lst in list(self.sender.unacked.items()):
            for d in list(lst):
                if d["time"]>0 and now_ms - d["time"] > 1500:  # 1.5s guard
                    self.sender.window[chid]=max(2, self.sender.window[chid]//2)
                    d["time"]=now_ms; out.append(d["raw"])
                    break
        # schedule new frames if window allows
        while True:
            m=self._pop_scheduled(self.sender.can_send)
            if not m: break
            raws=self.sender.build_frames_for_message(m)
            for raw in raws:
                # stamp send time
                for d in reversed(self.sender.unacked[m.chid]):
                    if d["time"]==0: d["time"]=now_ms; break
                out.append(raw)
        return out

    def feed_bytes(self, now_ms:int, data:bytes)->List[bytes]:
        """Feed incoming bytes; return any frames (ACKs/RTX) to send immediately."""
        out=[]
        self.decoder.feed(data)
        for f in self.decoder.read():
            if f.type==TYPE_ACK:
                off=0
                try:
                    ack,off=dec_varint(f.payload,off)
                    win,off=dec_varint(f.payload,off)
                    base,off=dec_varint(f.payload,off)
                    bm,off=dec_varint(f.payload,off)
                except Exception: 
                    continue
                out += self.sender.apply_sack(f.chid, ack, win, base, bm)
                continue
            # data/fec path
            f2, ackt = self.receiver.handle(f)
            if ackt:
                chid,hc,base,bm = ackt
                old = self.pending_ack.get(chid, (-1,0,0))
                agg_bm = (bm | old[2]) if base==old[1] else bm
                self.pending_ack[chid]=(max(old[0], hc), base, agg_bm)
                # flush ack immediately (could debounce)
                hc2, base2, bm2 = self.pending_ack.pop(chid)
                pld = enc_varint(hc2) + enc_varint(max(2, self.sender.window[chid])) + enc_varint(base2) + enc_varint(bm2)
                af = Frame(TYPE_ACK, FLAG_CH_PRESENT, DICT_ID, pld, chid=chid, seq=None)
                out.append(encode_frame(af))
            if f2:
                pay=self.receiver.reasm.feed(f2, key=(f2.chid, f2.dict_id))
                if pay:
                    mid, c_ms, content = unpack_payload(pay)
                    if c_ms>0 and mid not in self._seen:
                        self._seen.add(mid)
                        self.on_message(f2.chid, content)
        return out
