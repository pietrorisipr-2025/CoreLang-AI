
import json
def build_cas_request(hex_hash:str)->bytes:
    return b"CASR1"+json.dumps({"type":"CASREQ","v":1,"h":hex_hash}, separators=(',',':')).encode()
def build_cas_data(hex_hash:str, blob:bytes)->bytes:
    head = json.dumps({"type":"CASDAT","v":1,"h":hex_hash,"n":len(blob)}, separators=(',',':')).encode()
    return b"CASR1"+head+blob
def parse_cas(b:bytes)->dict:
    s=b[5:]; end=s.find(b'}')+1; meta=json.loads(s[:end].decode()); meta["blob"]=s[end:]; return meta
