
# cl5x_msd_delta2.py — multi-step delta-of-delta over MSD objects (per id)
import json

def _enc_varint(x:int)->bytes:
    out=bytearray()
    while True:
        b=x & 0x7F; x >>= 7
        out.append(b | (0x80 if x else 0))
        if not x: break
    return bytes(out)

def _dec_varint(buf:bytes, off:int):
    shift=0; val=0; pos=off
    while True:
        b=buf[pos]; pos+=1
        val |= (b & 0x7F) << shift
        if (b & 0x80)==0: return val,pos
        shift += 7

class MSDDelta2:
    """
    Maintains last FULL state per id, but can encode short bursts as 'delta-of-delta'.
    Frame types:
      'F' full  : full JSON (for resync)
      'B' batch : run-length of consecutive 'delta' items (bitmap + values)
    """
    def __init__(self, fields, max_cache=4096, batch_max=8):
        self.fields = list(fields)
        self.cache = {}         # id -> last full dict
        self.order = []         # LRU for eviction
        self.max_cache = max_cache
        self.batch_max = batch_max
        self.pending = {}       # id -> [(changed_mask, [vals_bytes])]

    def _touch(self, oid):
        if oid in self.order:
            self.order.remove(oid)
        self.order.append(oid)
        if len(self.order) > self.max_cache:
            ev = self.order.pop(0); self.cache.pop(ev, None); self.pending.pop(ev, None)

    def encode(self, obj:dict)->bytes:
        oid = str(obj.get('id',''))
        prev = self.cache.get(oid, {})
        changed = 0; vals = []
        for i,f in enumerate(self.fields):
            old = prev.get(f, None); new = obj.get(f, None)
            if new != old:
                changed |= (1<<i)
                vb = json.dumps(new, separators=(',',':')).encode('utf-8') if not isinstance(new,(bytes,bytearray)) else bytes(new)
                vals.append(vb)
        # If no prev or too many fields changed -> send FULL
        changed_count = int(bin(changed).count('1'))
        if not prev or changed_count > max(1, len(self.fields)//2):
            payload = json.dumps(obj, separators=(',',':')).encode('utf-8')
            out = b'F' + _enc_varint(len(oid)) + oid.encode('utf-8') + _enc_varint(len(payload)) + payload
            self.cache[oid] = dict(obj); self._touch(oid)
            self.pending.pop(oid, None)
            return out
        # Otherwise, enqueue delta and maybe emit batch
        pend = self.pending.setdefault(oid, [])
        pend.append((changed, vals))
        if len(pend) >= self.batch_max:
            # build batch
            out = bytearray(b'B') + _enc_varint(len(oid)) + oid.encode('utf-8') + _enc_varint(len(pend))
            for mask, vlist in pend:
                out += _enc_varint(mask)
                out += _enc_varint(len(vlist))
                for vb in vlist:
                    out += _enc_varint(len(vb)) + vb
                # apply to cache as we go
                cur = self.cache.get(oid, {}).copy()
                idx=0
                for i,f in enumerate(self.fields):
                    if (mask>>i)&1:
                        try:
                            val = json.loads(vlist[idx].decode('utf-8'))
                        except Exception:
                            val = vlist[idx]
                        cur[f]=val; idx+=1
                self.cache[oid]=cur
            pend.clear()
            self._touch(oid)
            return bytes(out)
        # no emission yet (caller can flush() later); return empty
        return b''

    def flush(self, oid=None)->bytes:
        outs = []
        ids = [oid] if oid else list(self.pending.keys())
        for k in ids:
            pend = self.pending.get(k, [])
            if not pend: continue
            out = bytearray(b'B') + _enc_varint(len(k)) + k.encode('utf-8') + _enc_varint(len(pend))
            for mask, vlist in pend:
                out += _enc_varint(mask)
                out += _enc_varint(len(vlist))
                for vb in vlist:
                    out += _enc_varint(len(vb)) + vb
                # update cache
                cur = self.cache.get(k, {}).copy()
                idx=0
                for i,f in enumerate(self.fields):
                    if (mask>>i)&1:
                        try:
                            val = json.loads(vlist[idx].decode('utf-8'))
                        except Exception:
                            val = vlist[idx]
                        cur[f]=val; idx+=1
                self.cache[k]=cur
            pend.clear()
            outs.append(bytes(out))
            self._touch(k)
        return b''.join(outs)

    def decode(self, b:bytes)->dict:
        t = b[:1]
        off = 1
        def _dec_var(buf, off):
            shift=0; val=0; pos=off
            while True:
                b=buf[pos]; pos+=1
                val |= (b & 0x7F) << shift
                if (b & 0x80)==0: return val,pos
                shift += 7
        n, off = _dec_var(b, off)
        oid = b[off:off+n].decode('utf-8'); off += n
        if t == b'F':
            ln, off = _dec_var(b, off)
            payload = b[off:off+ln]; off += ln
            try: obj = json.loads(payload.decode('utf-8'))
            except Exception: obj = {"id": oid, "raw": payload}
            self.cache[oid] = dict(obj)
            self._touch(oid)
            return self.cache[oid]
        elif t == b'B':
            cnt, off = _dec_var(b, off)
            cur = self.cache.get(oid, {}).copy()
            for _ in range(cnt):
                mask, off = _dec_var(b, off)
                vnum, off = _dec_var(b, off)
                vals = []
                for _i in range(vnum):
                    ln, off = _dec_var(b, off)
                    vb = b[off:off+ln]; off += ln
                    vals.append(vb)
                idx=0
                for i,f in enumerate(self.fields):
                    if (mask>>i)&1:
                        try:
                            val = json.loads(vals[idx].decode('utf-8'))
                        except Exception:
                            val = vals[idx]
                        cur[f]=val; idx+=1
            cur['id'] = oid
            self.cache[oid] = cur
            self._touch(oid)
            return cur
        else:
            raise ValueError('unknown MSDDelta2 frame')
