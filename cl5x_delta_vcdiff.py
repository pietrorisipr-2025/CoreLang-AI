# cl5x_delta_vcdiff.py — residual delta encoding (dictionary = summary_bin)
from typing import Tuple
import hashlib
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
def delta_encode(summary:bytes, full:bytes, min_match:int=16)->bytes:
    def hashes_of_dict(d:bytes, window:int=16):
        if len(d) < window: return {}
        table = {}
        for i in range(0, len(d)-window+1):
            chunk = d[i:i+window]
            hv = hashlib.blake2s(chunk, digest_size=4).digest()
            table.setdefault(hv, []).append(i)
        return table
    w = min_match
    dict_ht = hashes_of_dict(summary, window=w)
    out = bytearray(b"DLT1")
    out += enc_varint(w)
    i = 0
    ADD = 0
    def flush_add():
        nonlocal ADD, i, out, full
        if ADD>0:
            start = i-ADD
            out.append(0x00)
            out += enc_varint(ADD)
            out += full[start:i]
            ADD = 0
    while i < len(full):
        if i+w <= len(full):
            hv = hashlib.blake2s(full[i:i+w], digest_size=4).digest()
            cand = dict_ht.get(hv, None)
        else:
            cand = None
        best_len = 0; best_off = 0
        if cand:
            for off in cand[:8]:
                L = w
                while i+L < len(full) and off+L < len(summary) and full[i+L]==summary[off+L]:
                    L += 1
                if L > best_len:
                    best_len = L; best_off = off
        if best_len >= w:
            flush_add()
            out.append(0x01)
            out += enc_varint(best_off)
            out += enc_varint(best_len)
            i += best_len
        else:
            ADD += 1; i += 1
            if ADD >= 1024: flush_add()
    flush_add()
    out.append(0xFF)
    return bytes(out)
def delta_decode(summary:bytes, payload:bytes)->bytes:
    assert payload[:4] == b"DLT1", "bad delta magic"
    off = 4
    min_match, off = dec_varint(payload, off)
    out = bytearray()
    while off < len(payload):
        op = payload[off]; off+=1
        if op == 0x00:
            ln, off = dec_varint(payload, off)
            out += payload[off:off+ln]; off += ln
        elif op == 0x01:
            pos, off = dec_varint(payload, off)
            ln, off = dec_varint(payload, off)
            out += summary[pos:pos+ln]
        elif op == 0xFF: break
        else: raise ValueError(f'unknown op {op}')
    return bytes(out)