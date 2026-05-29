# cl5x_msd_delta.py — per-ID delta for MSD objects (field-level delta)
import json
from typing import Dict, Any

class MSDDelta:
    def __init__(self, schema_fields):
        self.fields = list(schema_fields)  # ordered
        self.cache: Dict[str, Dict[str, Any]] = {}

    def encode(self, obj:Dict[str,Any])->bytes:
        # requires 'id' field to key the cache
        oid = str(obj.get('id', ''))
        prev = self.cache.get(oid, {})
        # compute changes
        changed = 0
        vals = []
        for i,f in enumerate(self.fields):
            old = prev.get(f, None)
            new = obj.get(f, None)
            if new != old:
                changed |= (1<<i)
                vb = json.dumps(new, separators=(',',':')).encode('utf-8') if not isinstance(new,(bytes,bytearray)) else bytes(new)
                vals.append(vb)
        # write
        out = bytearray(b'MSDD')
        out += oid.encode('utf-8') + b'\x00'  # null-term id
        # varint
        def enc_varint(x:int)->bytes:
            out=bytearray()
            while True:
                b=x & 0x7F; x >>= 7
                out.append(b | (0x80 if x else 0))
                if not x: break
            return bytes(out)
        out += enc_varint(changed)
        for vb in vals:
            out += enc_varint(len(vb)); out += vb
        # update cache
        self.cache[oid] = dict(prev, **obj)
        return bytes(out)

    def decode(self, b:bytes)->Dict[str,Any]:
        assert b[:4]==b'MSDD'
        off=4
        # read null-term id
        end = b.index(0, off)
        oid = b[off:end].decode('utf-8'); off = end+1
        def dec_varint(buf, off):
            shift=0; val=0; pos=off
            while True:
                b=buf[pos]; pos+=1
                val |= (b & 0x7F) << shift
                if (b & 0x80)==0: return val,pos
                shift += 7
        changed, off = dec_varint(b, off)
        prev = self.cache.get(oid, {})
        out = dict(prev)
        for i,f in enumerate(self.fields):
            if (changed>>i)&1:
                ln, off = dec_varint(b, off)
                vb = b[off:off+ln]; off += ln
                try: out[f] = json.loads(vb.decode('utf-8'))
                except Exception: out[f] = vb
        self.cache[oid] = out
        return {"id": oid, **out}