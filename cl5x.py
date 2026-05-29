# CL5X reference encoder/decoder (spec-lite)
from dataclasses import dataclass
from typing import Optional, List, Tuple
import zlib, struct
from io import BytesIO

MAGIC = b'CL5X'
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
    import zlib
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
    def __init__(self): self.buf = bytearray()
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
        import struct as _s
        crc_expect = _s.unpack(">I", self.buf[offset+length:offset+length+4])[0]
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
class Reassembler:
    def __init__(self): self.state={}
    def feed(self, f:Frame, key=None):
        if not (f.flags & FLAG_SEQ_PRESENT): return f.payload
        key = key or (f.chid, f.dict_id)
        from io import BytesIO
        exp, buf, _ = self.state.get(key, (None, None, None))
        if exp is None:
            self.state[key] = (f.seq + 1, BytesIO(f.payload), None)
            if not (f.flags & FLAG_MORE):
                payload = self.state[key][1].getvalue()
                del self.state[key]
                return payload
            return None
        else:
            if f.seq != exp:
                self.state.pop(key, None)
                raise ValueError("Fragment out of order or missing")
            buf.write(f.payload)
            exp_next = f.seq + 1
            if f.flags & FLAG_MORE:
                self.state[key] = (exp_next, buf, None)
                return None
            payload = buf.getvalue()
            del self.state[key]
            return payload
def control_payload_negotiate(dict_id:int, max_frame:int=65535, compress:bool=True)->bytes:
    s = '{' + f'"type":"NEGOTIATE","dict_id":{dict_id},"ver":{VER},"max_frame":{max_frame},"compress":{str(compress).lower()}' + '}'
    return s.encode("utf-8")
