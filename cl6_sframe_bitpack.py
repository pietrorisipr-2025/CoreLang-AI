# cl5x_sframe_bitpack.py — bitpacked S-Frames header (v6.2)
# Header layout (2 bytes minimal):
#  bits: [ s_type(3) | flags(3) | cbv_small(4) | len_kind_low(2) | len_kind_high/reserved(4) ]
#  s_type: 0..7 (SUM, PLAN, REQ, ANS, OBS, EVAL, DELTA, CKB)
#  flags: bit0 lossy_ok, bit1 delta, bit2 urgent
#  cbv_small: 0..15 (0==extended: varint follows)
#  len_kind: 0=raw, 1=huf, 2=z, 3=lz4, 4=zstd.  v6.10.2 stores
#            len_kind_high in the formerly reserved low nibble, so old frames
#            with zero reserved bits still decode unchanged.
# After header:
#   if cbv_small==0: varint cbv
#   varint ref_hash_len, ref_hash bytes
#   varint payload_len, payload bytes
from typing import Tuple

def enc_varint(x:int)->bytes:
    out=bytearray()
    while True:
        b=x & 0x7F; x >>= 7
        out.append(b | (0x80 if x else 0))
        if not x: break
    return bytes(out)

def dec_varint(buf:bytes, off:int)->Tuple[int,int]:
    shift=0; val=0; pos=off
    while True:
        b=buf[pos]; pos+=1
        val |= (b & 0x7F) << shift
        if (b & 0x80)==0: return val,pos
        shift += 7

def pack_header(s_type:int, flags:int, cbv:int, len_kind:int)->bytes:
    cb_small = cbv if 1 <= cbv <= 15 else 0
    b0 = ((s_type & 0x7) << 5) | ((flags & 0x7) << 2) | ((cb_small >> 2) & 0x3)
    b1 = (((cb_small & 0x3) << 6) | ((len_kind & 0x3) << 4) | ((len_kind >> 2) & 0x0F))
    out = bytearray([b0, b1])
    if cb_small == 0:
        out += enc_varint(cbv)
    return bytes(out)

def unpack_header(buf:bytes, off:int=0)->Tuple[int,int,int,int,int]:
    b0 = buf[off]; b1 = buf[off+1]; off += 2
    s_type = (b0 >> 5) & 0x7
    flags = (b0 >> 2) & 0x7
    cb_small_hi = b0 & 0x3
    cb_small_lo = (b1 >> 6) & 0x3
    cb_small = (cb_small_hi << 2) | cb_small_lo
    len_kind = ((b1 & 0x0F) << 2) | ((b1 >> 4) & 0x3)
    if cb_small == 0:
        cbv, off = dec_varint(buf, off)
    else:
        cbv = cb_small
    return s_type, flags, cbv, len_kind, off

def pack_sframe_bp(s_type:int, flags:int, cbv:int, len_kind:int, ref_hash:bytes, payload:bytes)->bytes:
    out = bytearray()
    out += pack_header(s_type, flags, cbv, len_kind)
    out += enc_varint(len(ref_hash)); out += ref_hash
    out += enc_varint(len(payload)); out += payload
    return bytes(out)

def unpack_sframe_bp(buf:bytes, off:int=0)->Tuple[dict,int]:
    s_type, flags, cbv, len_kind, off = unpack_header(buf, off)
    rh_len, off = dec_varint(buf, off)
    ref_hash = buf[off:off+rh_len]; off += rh_len
    n, off = dec_varint(buf, off)
    payload = buf[off:off+n]; off += n
    return {"s_type":s_type, "flags":flags, "cbv":cbv, "len_kind":len_kind, "ref_hash":ref_hash, "payload":payload}, off