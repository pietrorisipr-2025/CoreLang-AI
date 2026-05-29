
import json, hashlib
def blake16(b:bytes)->bytes: 
    return hashlib.blake2s(b, digest_size=16).digest()
def build_anchor(summary_bin:bytes, anchor_id:int)->bytes:
    ref = blake16(summary_bin).hex()
    payload = json.dumps({"type":"RSYN","v":1,"mode":"ANCH","id":int(anchor_id),"ref":ref}, separators=(',',':')).encode()
    return b"RSYN1"+payload
def build_resync_request(ref_hex:str, want_n:int=3)->bytes:
    payload = json.dumps({"type":"RSYN","v":1,"mode":"REQ","ref":ref_hex,"want":int(want_n)}, separators=(',',':')).encode()
    return b"RSYN1"+payload
def parse_rs(b:bytes)->dict:
    assert b[:5]==b"RSYN1"
    return json.loads(b[5:].decode())
