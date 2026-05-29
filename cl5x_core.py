# cl5x_core.py
import struct, zlib
from dataclasses import dataclass
from typing import Optional, Tuple, List

MAGIC=b"CL5X"; VER=1

TYPE_CONTROL=0; TYPE_DATA=1; TYPE_ACK=2; TYPE_ERROR=3; TYPE_FEC=4
FLAG_COMPRESS=0x01; FLAG_CH_PRESENT=0x02; FLAG_SEQ_PRESENT=0x04; FLAG_MORE=0x08
FLAG_REF=0x10; FLAG_PRIO1=0x20; FLAG_PRIO2=0x40; FLAG_RESERVED=0x80

def priority_to_flags(p:int)->int: 
    return (FLAG_PRIO1 if (p&1) else 0)|(FLAG_PRIO2 if ((p>>1)&1) else 0)

def enc_varint(x:int)->bytes:
    if x<0: raise ValueError("varint must be non-negative")
    out=bytearray()
    while True:
        b=x & 0x7F; x >>= 7
        out.append(b | (0x80 if x else 0))
        if not x: break
    return bytes(out)

def dec_varint(buf:bytes, off:int)->Tuple[int,int]:
    shift=0; val=0; pos=off
    while True:
        if pos>=len(buf): raise ValueError("truncated varint")
        b=buf[pos]; pos+=1
        val |= (b & 0x7F) << shift
        if (b & 0x80)==0: return val,pos
        shift += 7

@dataclass
class Frame:
    type:int; flags:int; dict_id:int; payload:bytes; chid:Optional[int]=None; seq:Optional[int]=None

def _crc32(b:bytes)->int:
    return zlib.crc32(b) & 0xFFFFFFFF

def encode_frame(f:Frame, compress_level:int=3)->bytes:
    flags=f.flags; payload=f.payload
    if flags & FLAG_COMPRESS:
        payload=zlib.compress(payload, level=compress_level)
    head=bytearray()
    head += MAGIC
    head += struct.pack("B", VER)
    head += struct.pack("B", f.type & 0xFF)
    head += struct.pack("B", flags & 0xFF)
    if flags & FLAG_CH_PRESENT: head += enc_varint(f.chid if f.chid is not None else 0)
    head += enc_varint(f.dict_id)
    if flags & FLAG_SEQ_PRESENT: head += enc_varint(f.seq if f.seq is not None else 0)
    head += enc_varint(len(payload))
    body=bytes(head)+payload
    return body + struct.pack(">I", _crc32(body))

class StreamDecoder:
    def __init__(self): self.buf=bytearray()
    def feed(self, data:bytes): self.buf += data
    def _try_one(self)->Optional[Frame]:
        if len(self.buf) < 4+1+1+1+4: return None
        if self.buf[:4] != MAGIC:
            idx=self.buf.find(MAGIC, 1)
            if idx==-1: self.buf=self.buf[-3:]; return None
            self.buf=self.buf[idx:]
            if len(self.buf) < 4+1+1+1+4: return None
        ver=self.buf[4]; 
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
        crc=struct.unpack(">I", self.buf[off+length:off+length+4])[0]
        if _crc32(body)!=crc: self.buf=self.buf[1:]; return None
        self.buf=self.buf[need:]
        return Frame(t, flags, dict_id, payload, chid, seq)
    def read(self)->List[Frame]:
        out=[]
        while True:
            f=self._try_one()
            if f is None: break
            out.append(f)
        return out
