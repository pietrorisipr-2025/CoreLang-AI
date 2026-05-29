# cl5x_bench_v62.py — compare JSON/zlib vs S-Frames+delta+entropy (synthetic)
import json, random, zlib, hashlib
from typing import Any, Dict, List, Tuple
import pandas as pd

# Minimal semantic from v6
T_NIL=0; T_BOOL=1; T_INT=2; T_FLOAT=3; T_STR=4; T_BIN=5; T_LIST=6; T_MAP=7; T_ID=8
def enc_varint(x:int)->bytes:
    out=bytearray()
    while True:
        b=x & 0x7F; x >>= 7
        out.append(b | (0x80 if x else 0))
        if not x: break
    return bytes(out)
class Codebook:
    def __init__(self, keys, phrases, version=1):
        self.key_ids={k:i+1 for i,k in enumerate(keys)}
        self.phrase_ids={s:i+1 for i,s in enumerate(phrases)}
        self.version=version
    def key(self,k): return (k in self.key_ids, self.key_ids.get(k,0))
    def phrase(self,s): return (s in self.phrase_ids, self.phrase_ids.get(s,0))
def default_codebook():
    keys=['role','content','intent','tool','args','result','error','model','lang','format','n','temperature','top_p','tokens','cost','uri','hash','id','plan','steps','observation','action','reply','metadata','k','v','t','ts','summary','residual','delta','ref','parent','type','name']
    phrases=['assistant','user','system','json','text','tool_call','function','python','ok','yes','no','none','null','true','false','en','it','plan','step','observe','act','reflect','error','timeout','retry','complete']
    return Codebook(keys, phrases, 1)
class SEncoder:
    def __init__(self, cb): self.cb=cb
    def enc_any(self, x):
        if x is None: return bytes([T_NIL])
        if isinstance(x,bool): return bytes([T_BOOL, 1 if x else 0])
        if isinstance(x,int): return bytes([T_INT])+enc_varint((x<<1)^(x>>63))
        if isinstance(x,float): import struct; return bytes([T_FLOAT])+struct.pack('>d',x)
        if isinstance(x,(bytes,bytearray)): b=bytes(x); return bytes([T_BIN])+enc_varint(len(b))+b
        if isinstance(x,str):
            ok,pid=self.cb.phrase(x)
            if ok: return bytes([T_ID])+enc_varint(pid)
            b=x.encode('utf-8'); return bytes([T_STR])+enc_varint(len(b))+b
        if isinstance(x,list):
            out=bytearray([T_LIST])+enc_varint(len(x))
            for it in x: out+=self.enc_any(it)
            return bytes(out)
        if isinstance(x,dict):
            out=bytearray([T_MAP])+enc_varint(len(x))
            for k,v in x.items():
                ok,kid=self.cb.key(k)
                if ok: out+=bytes([T_ID])+enc_varint(kid)
                else: kb=k.encode('utf-8'); out+=bytes([T_STR])+enc_varint(len(kb))+kb
                out+=self.enc_any(v)
            return bytes(out)
        b=str(x).encode('utf-8'); return bytes([T_STR])+enc_varint(len(b))+b

# make summary/residual and then delta+entropy on residual
from cl5x_delta_vcdiff import delta_encode
from cl5x_entropy import entropy_pack_auto, entropy_pack_stream_auto
from cl6_sframe_bitpack import pack_sframe_bp

def summarize_obj(obj):
    def rec(x):
        if isinstance(x, dict):
            out={}
            for k,v in x.items():
                if k in ('content','result','observation','reply','summary'):
                    if isinstance(v,str): out[k]=v[:256]
                    else: out[k]=v
                else:
                    out[k]=rec(v)
            return out
        if isinstance(x,list):
            return [rec(i) for i in (x[:1]+(['...'] if len(x)>2 else [])+x[-1:])]
        if isinstance(x,str) and len(x)>256: return x[:256]
        return x
    return rec(obj)

def synthetic_messages(n=240, seed=19):
    random.seed(seed)
    roles=['user','assistant','system']
    intents=['tool_call','reply','plan','observe','act','reflect']
    msgs=[]
    for i in range(n):
        role=random.choice(roles); intent=random.choice(intents)
        content = ' '.join(random.choice(['ok','retry','complete','error','timeout','step','observe','plan','result']) for _ in range(random.randint(60,140)))
        msg={'role':role,'intent':intent,'content':content,'tokens':random.randint(50,800),'model':'gpt-x','lang':random.choice(['en','it']),'metadata':{'ts':i,'k':'v'}}
        if intent=='tool_call':
            msg['tool']='python'; msg['args']={'code':'print(\"hi\")','timeout':3}
        msgs.append(msg)
    return msgs

def run_bench():
    cb=default_codebook(); enc=SEncoder(cb)
    data=synthetic_messages()
    json_bytes=zlib_bytes=sum_bytes=res_bytes=0
    stream_inner = bytearray()
    for obj in data:
        js=json.dumps(obj, separators=(',',':')).encode('utf-8')
        json_bytes+=len(js); zlib_bytes+=len(zlib.compress(js,6))
        full_bin = enc.enc_any(obj)
        sum_obj = summarize_obj(obj)
        sum_bin = enc.enc_any(sum_obj)
        residual = delta_encode(sum_bin, full_bin)
        kind, packed = entropy_pack_auto(residual)
        sum_bytes += len(sum_bin) + 8   # + tiny header est.
        res_bytes += len(packed) + 12   # + tiny header est.
        # v6.10.2 batch/stream path: full semantic object S-Frames are built raw
        # first, then the whole stream is compressed once.  This deliberately
        # bypasses the old per-frame <300 byte raw shortcut.
        stream_inner += pack_sframe_bp(2, 0b000, cbv=cb.version, len_kind=0, ref_hash=b'', payload=full_bin)
    legacy_total = sum_bytes + res_bytes + 400  # + CKB-ish cost estimate
    stream_kind, stream_packed, stream_meta = entropy_pack_stream_auto(bytes(stream_inner), policy='auto-byte-min', project_root='.')
    # Estimate one outer stream-batch S-Frame + the same CKB-ish fixed cost.
    stream_outer = pack_sframe_bp(0, 0b111, cbv=cb.version, len_kind=0, ref_hash=b'', payload=stream_packed)
    stream_total = len(stream_outer) + 400
    return {'json_bytes':json_bytes, 'json_zlib_bytes':zlib_bytes,
            'sframes_total_bytes':stream_total,
            'legacy_sframes_total_bytes':legacy_total,
            'summary_bytes':sum_bytes, 'residual_bytes':res_bytes,
            'stream_inner_bytes':len(stream_inner), 'stream_packed_bytes':len(stream_packed),
            'stream_codec':stream_kind, 'stream_dict':bool(stream_meta.get('dict_id')),
            'messages':len(data)}

if __name__=='__main__':
    r=run_bench()
    import pandas as pd
    pd.DataFrame([r]).to_csv('/mnt/data/CL5X_v62_bench.csv', index=False)