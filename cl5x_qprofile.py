
# cl5x_qprofile.py — announce/parse vector compression profiles (PQ/RVQ/etc.)
import json

def build_qprofile_frame(profile:dict)->bytes:
    """
    profile example:
      {'method':'RVQ','stages':3,'k':16,'dim':768,'note':'embeddings-v1'}
    """
    payload = json.dumps({'type':'QPROFILE','v':1,'profile':profile}, separators=(',',':')).encode('utf-8')
    return b'QPROF1'+payload

def parse_qprofile_frame(b:bytes)->dict:
    assert b[:6]==b'QPROF1'
    return json.loads(b[6:].decode('utf-8'))
