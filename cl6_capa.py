
# cl6_capa.py — CAPA1 capability negotiation
import json

def build_capa_frame(features:dict)->bytes:
    """
    features example:
      {"DLT1":1,"MSD2":1,"MIC1":1,"RSYN1":1,"QPROF1":1,"SFRAME":"bp1"}
    """
    payload = json.dumps({"type":"CAPA","v":1,"feat":features}, separators=(',',':')).encode('utf-8')
    return b"CAPA1" + payload

def parse_capa_frame(b:bytes)->dict:
    assert b[:5]==b"CAPA1"
    return json.loads(b[5:].decode('utf-8'))

def negotiate(local:dict, remote:dict)->dict:
    # intersect keys; for numeric features pick min version, for strings pick equal-or-local
    out={}
    lf=local.get("feat", local); rf=remote.get("feat", remote)
    for k,v in lf.items():
        if k in rf:
            rv = rf[k]
            if isinstance(v,(int,float)) and isinstance(rv,(int,float)):
                out[k] = min(v, rv)
            elif isinstance(v,str) and isinstance(rv,str):
                out[k] = v if v==rv else v
            else:
                out[k] = v if v==rv else v
    return {"type":"CAPA_NEG","v":1,"feat":out}
