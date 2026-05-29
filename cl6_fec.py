
# cl6_fec.py — FEC1 XOR parity over groups of RESIDUAL frames
import json, zlib

def build_fec_parity(group_id:int, parts:list[bytes])->bytes:
    """
    Create FEC1 parity over list of byte strings (same length).
    """
    if not parts: return b''
    L = max(len(p) for p in parts)
    buf = bytearray(L)
    for p in parts:
        q = p + b'\x00'*(L-len(p))
        for i in range(L):
            buf[i] ^= q[i]
    payload = json.dumps({"type":"FEC","v":1,"gid":int(group_id),"n":len(parts),"len":L}, separators=(',',':')).encode()
    return b"FEC1" + payload + bytes(buf)

def parse_fec(b:bytes):
    assert b[:4]==b"FEC1"
    s = b[4:]
    end = s.find(b'}')+1
    meta = json.loads(s[:end].decode())
    parity = s[end:]
    return meta, parity
