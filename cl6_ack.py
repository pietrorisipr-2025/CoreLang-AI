
import json
def build_ack(ref_hex:str, ok:bool=True, info:str="")->bytes:
    return b"ACK1"+json.dumps({"type":"ACK","v":1,"ref":ref_hex,"ok":bool(ok),"info":info}, separators=(',',':')).encode()
def parse_ack(b:bytes)->dict:
    return json.loads(b[4:].decode())
