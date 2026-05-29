# cl5x_msd.py — Message Schema Dictionary (MSD) for compact tool I/O
import json
from typing import List, Dict
def enc_varint(x:int)->bytes:
    out=bytearray()
    while True:
        b=x & 0x7F; x >>= 7
        out.append(b | (0x80 if x else 0))
        if not x: break
    return bytes(out)
def dec_varint(buf:bytes, off:int):
    shift=0; val=0; pos=off
    while True:
        b=buf[pos]; pos+=1
        val |= (b & 0x7F) << shift
        if (b & 0x80)==0: return val,pos
        shift += 7
class SchemaRegistry:
    def __init__(self):
        self.schemas={}; self.by_tuple={}; self.next_id=1
    def register(self, fields:List[str])->int:
        key=tuple(fields)
        if key in self.by_tuple: return self.by_tuple[key]
        sid=self.next_id; self.next_id+=1
        self.schemas[sid]=list(fields); self.by_tuple[key]=sid
        return sid
    def encode(self, sid:int, obj:Dict)->bytes:
        fields=self.schemas[sid]; present=0; vals=[]
        for i,f in enumerate(fields):
            if f in obj:
                present |= (1<<i); vals.append(obj[f])
        out=bytearray(b'MSD1'); out+=enc_varint(sid); out+=enc_varint(present)
        for i,f in enumerate(fields):
            if (present>>i)&1:
                v=obj[f]; vb=json.dumps(v, separators=(',',':')).encode('utf-8') if not isinstance(v,(bytes,bytearray)) else bytes(v)
                out += enc_varint(len(vb)); out += vb
        return bytes(out)
    def decode(self, b:bytes)->Dict:
        assert b[:4]==b'MSD1'; off=4; sid,off=dec_varint(b,off); fields=self.schemas[sid]; bitmap,off=dec_varint(b,off)
        out={'__schema_id':sid}
        for i,f in enumerate(fields):
            if (bitmap>>i)&1:
                ln,off=dec_varint(b,off); vb=b[off:off+ln]; off+=ln
                try: out[f]=json.loads(vb.decode('utf-8'))
                except Exception: out[f]=vb
        return out
# default schemas
REG = SchemaRegistry()
SCHEMA_TOOL_CALL = REG.register(['tool','args','timeout','id'])
SCHEMA_TOOL_RESULT = REG.register(['id','result','error','time_ms','log'])