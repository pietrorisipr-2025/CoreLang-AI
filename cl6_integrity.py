
import hashlib
def _mic16(data:bytes, key:bytes)->bytes:
    h = hashlib.blake2s(key=key, digest_size=16); h.update(data); return h.digest()
def wrap_mic(payload:bytes, key:bytes)->bytes:
    return b"MIC1" + _mic16(payload, key) + payload
def unwrap_mic(frame:bytes, key:bytes)->bytes:
    if not frame.startswith(b"MIC1"): return frame
    tag = frame[4:20]; payload=frame[20:]
    if _mic16(payload, key)!=tag: raise ValueError("MIC1 check failed")
    return payload
