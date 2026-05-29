# cl5x_link.py — Orchestrator v6.6: dynamic residual policy (auto byte-min). PQ defaults via qprofile helpers.
import os, hashlib, json, time
from typing import Dict, Any

# --- Tiny semantic (encoder/decoder minimal) ---
T_NIL=0; T_BOOL=1; T_INT=2; T_FLOAT=3; T_STR=4; T_BIN=5; T_LIST=6; T_MAP=7; T_ID=8
def _enc_varint(x:int)->bytes:
    out=bytearray()
    while True:
        b=x & 0x7F; x >>= 7
        out.append(b | (0x80 if x else 0))
        if not x: break
    return bytes(out)
def _dec_varint(buf:bytes, off:int):
    shift=0; val=0; pos=off
    while True:
        b=buf[pos]; pos+=1
        val |= (b & 0x7F) << shift
        if (b & 0x80)==0: return val,pos
        shift += 7
def _unzigzag(u:int)->int: return (u>>1) ^ (-(u & 1))

class _Codebook:
    def __init__(self, keys, phrases, version=1):
        self.key_ids={k:i+1 for i,k in enumerate(keys)}
        self.phrase_ids={s:i+1 for i,s in enumerate(phrases)}
        self.rev_keys={v:k for k,v in self.key_ids.items()}
        self.rev_phr={v:s for s,v in self.phrase_ids.items()}
        self.version=version
    def key(self,k): return (k in self.key_ids, self.key_ids.get(k,0))
    def phrase(self,s): return (s in self.phrase_ids, self.phrase_ids.get(s,0))

def _default_codebook():
    keys=['role','content','intent','tool','args','result','error','model','lang','format','n','temperature','top_p','tokens','cost','uri','hash','id','plan','steps','observation','action','reply','metadata','k','v','t','ts','summary','residual','delta','ref','parent','type','name','log','deadline','priority','params','source','text','status','headers','body','url','method']
    phrases=['assistant','user','system','json','text','tool_call','function','python','ok','yes','no','none','null','true','false','en','it','plan','step','observe','act','reflect','error','timeout','retry','complete']
    return _Codebook(keys, phrases, 1)

class _SEncoder:
    def __init__(self, cb): self.cb=cb
    def enc(self, x):
        if x is None: return bytes([T_NIL])
        if isinstance(x,bool): return bytes([T_BOOL, 1 if x else 0])
        if isinstance(x,int): return bytes([T_INT])+_enc_varint((x<<1)^(x>>63))
        if isinstance(x,float): import struct; return bytes([T_FLOAT])+struct.pack('>d',x)
        if isinstance(x,(bytes,bytearray)): b=bytes(x); return bytes([T_BIN])+_enc_varint(len(b))+b
        if isinstance(x,str):
            ok,pid=self.cb.phrase(x)
            if ok: return bytes([T_ID])+_enc_varint(pid)
            b=x.encode('utf-8'); return bytes([T_STR])+_enc_varint(len(b))+b
        if isinstance(x,list):
            out=bytearray([T_LIST])+_enc_varint(len(x))
            for it in x: out+=self.enc(it)
            return bytes(out)
        if isinstance(x,dict):
            out=bytearray([T_MAP])+_enc_varint(len(x))
            for k,v in x.items():
                ok,kid=self.cb.key(k)
                if ok: out+=bytes([T_ID])+_enc_varint(kid)
                else: kb=k.encode('utf-8'); out+=bytes([T_STR])+_enc_varint(len(kb))+kb
                out+=self.enc(v)
            return bytes(out)
        b=str(x).encode('utf-8'); return bytes([T_STR])+_enc_varint(len(b))+b

class _SDecoder:
    def __init__(self, cb): self.cb=cb
    def dec(self, buf:bytes, off:int=0, ctx:str='val'):
        t=buf[off]; off+=1
        import struct
        if t==T_NIL: return None, off
        if t==T_BOOL: v=(buf[off]!=0); return v, off+1
        if t==T_INT: u,off=_dec_varint(buf,off); return _unzigzag(u), off
        if t==T_FLOAT: v=struct.unpack('>d', buf[off:off+8])[0]; return v, off+8
        if t==T_BIN: n,off=_dec_varint(buf,off); return buf[off:off+n], off+n
        if t==T_STR: n,off=_dec_varint(buf,off); return buf[off:off+n].decode('utf-8',errors='replace'), off+n
        if t==T_ID:
            pid,off=_dec_varint(buf,off)
            if ctx=='key': return self.cb.rev_keys.get(pid, f'k#{pid}'), off
            return self.cb.rev_phr.get(pid, f'id#{pid}'), off
        if t==T_LIST:
            n,off=_dec_varint(buf,off); out=[]
            for _ in range(n):
                v,off=self.dec(buf,off,'val'); out.append(v)
            return out, off
        if t==T_MAP:
            n,off=_dec_varint(buf,off); out={}
            for _ in range(n):
                k,off=self.dec(buf,off,'key')
                v,off=self.dec(buf,off,'val')
                out[k]=v
            return out, off
        raise ValueError('unknown tag')

def _summarize(x):
    if isinstance(x, dict):
        out={}
        for k,v in x.items():
            if k in ('content','result','observation','reply','summary','log'):
                if isinstance(v,str): out[k]=v[:256]
                else: out[k]=v
            else:
                out[k]=_summarize(v)
        return out
    if isinstance(x,list):
        return [_summarize(i) for i in (x[:1]+(['...'] if len(x)>2 else [])+x[-1:])]
    if isinstance(x,str) and len(x)>256: return x[:256]
    return x

from cl5x_sframe_bitpack import pack_sframe_bp, unpack_sframe_bp
from cl5x_delta_vcdiff import delta_encode, delta_decode
from cl5x_entropy import entropy_pack_auto, entropy_unpack
from cl5x_qos_profiles import publish_semantic
from cl5x_adaptive_d2 import suggest_phrases, make_ckb_update_frame
from cl5x_msd_delta2 import MSDDelta2
from cl5x_qprofile import build_qprofile_frame
from cl5x_qprofile_defaults import get as get_qp_default, best_for_dim as qp_best_for_dim

class CL5XLink:
    def __init__(self, tx, on_object, manifest_path='ckb_layers_manifest.json', needed_blocks=None, auto_handshake=True,
                 ttl_summary_sec=5.0, ttl_residual_sec=7.0, auto_d2=True, qprofile=None,
                 residual_policy:str='auto-byte-min'):
        self.tx = tx
        self.on_object = on_object
        self.cb = _default_codebook()
        self.enc = _SEncoder(self.cb); self.dec = _SDecoder(self.cb)
        # buffers
        self.summaries = {}      # ref_hash(bytes) -> (payload, ts)
        self.residuals = {}      # ref_hash(bytes) -> (kind, payload, ts)
        # MSD delta-of-delta instances per schema
        self.msd2_tx = {
            'TOOL_RESULT': MSDDelta2(['id','result','error','time_ms','log'], batch_max=6),
            'PLAN': MSDDelta2(['id','goal','steps','deadline','priority'], batch_max=4),
            'OBS':  MSDDelta2(['id','text','ts','source'], batch_max=6),
            'ACT':  MSDDelta2(['id','action','params','ts'], batch_max=6),
        }
        self.msd2_rx = { k: MSDDelta2(v.fields if hasattr(v,'fields') else ['id']) for k,v in self.msd2_tx.items() }
        # D2 live
        self.auto_d2 = auto_d2
        self.recent_texts = []
        self.last_d2_ts = 0.0
        # TTL & metrics
        self.ttl_summary = ttl_summary_sec
        self.ttl_residual = ttl_residual_sec
        self.metrics = {
            'rx_summary':0,'rx_residual':0,'reconstructed':0,
            'drops_summary_ttl':0,'drops_residual_ttl':0,
            'msd_frames_tx':0,'msd_frames_rx':0,
            'auto_choice':'', 'bytes_chosen':0, 'bytes_other':0
        }
        self.needed_blocks = needed_blocks or []
        self.manifest_path = manifest_path
        self.qprofile = self._resolve_qprofile(qprofile)
        self.residual_policy = residual_policy
        if auto_handshake:
            self.handshake()

    def _resolve_qprofile(self, qprofile):
        # Accept dict, string alias ('pq-768'), or tuple ('pq', dim)
        if isinstance(qprofile, dict): return qprofile
        if isinstance(qprofile, str):
            if qprofile.startswith('pq-'):
                try: return get_qp_default(qprofile)
                except Exception: return None
            return None
        if isinstance(qprofile, tuple) and len(qprofile)==2 and qprofile[0]=='pq':
            try: return qp_best_for_dim(int(qprofile[1]))
            except Exception: return None
        return None

    def handshake(self):
        d0 = 'ckb_D0_control.bin'
        if os.path.exists(d0):
            publish_semantic(self.tx, 'CKB', open(d0,'rb').read(), chid=1)
        # D1 blocks
        try:
            man = json.loads(open(self.manifest_path,'r',encoding='utf-8').read())
            blocks = man['D1']['blocks']
            for b in blocks:
                name=b['block']
                if any((want in name) or (want==name) for want in self.needed_blocks):
                    fpath = b['file']
                    if not os.path.exists(fpath):
                        basename = os.path.basename(fpath)
                        cand = os.path.join('dict','D1_blocks', basename)
                        if os.path.exists(cand): fpath = cand
                    if os.path.exists(fpath):
                        publish_semantic(self.tx, 'CKB', open(fpath,'rb').read(), chid=1)
        except Exception:
            pass
        # QPROFILE
        if isinstance(self.qprofile, dict):
            frame = build_qprofile_frame(self.qprofile)
            publish_semantic(self.tx, 'CKB', frame, chid=1)

    def _collect_texts(self, obj:Dict[str,Any]):
        if not isinstance(obj, dict): return
        for k in ('content','result','observation','reply','summary','log'):
            v = obj.get(k)
            if isinstance(v, str) and len(v) >= 20:
                self.recent_texts.append(v[:1024])

    def _maybe_update_d2(self):
        if not self.auto_d2: return
        now = time.time()
        if (now - self.last_d2_ts) < 2.0 or len(self.recent_texts) < 8:
            return
        phrases = suggest_phrases(self.recent_texts[-64:], max_phrases=120, gain_threshold=512)
        if not phrases:
            return
        frame = make_ckb_update_frame(phrases)
        publish_semantic(self.tx, 'CKB', frame, chid=1)
        self.last_d2_ts = now

    def _detect_msd_schema(self, obj:Dict[str,Any]):
        if not isinstance(obj, dict): return None, None, None
        if 'id' in obj and ('result' in obj or 'log' in obj or 'time_ms' in obj or 'error' in obj):
            schema='TOOL_RESULT'; fields=['id','result','error','time_ms','log']
        elif 'id' in obj and ('goal' in obj or 'steps' in obj or 'deadline' in obj or 'priority' in obj):
            schema='PLAN'; fields=['id','goal','steps','deadline','priority']
        elif 'id' in obj and ('text' in obj or 'source' in obj or 'ts' in obj):
            schema='OBS'; fields=['id','text','ts','source']
        elif 'id' in obj and ('action' in obj or 'params' in obj or 'ts' in obj):
            schema='ACT'; fields=['id','action','params','ts']
        else:
            return None, None, None
        sub = {k: obj.get(k) for k in fields if k in obj}
        return schema, self.msd2_tx.get(schema), sub

    def _build_residual_candidates(self, sum_bin:bytes, full_bin:bytes, obj:dict):
        # DLT1 candidate
        residual = delta_encode(sum_bin, full_bin)
        wire_dlt = b'DLT1' + residual
        kind_dlt, pack_dlt = entropy_pack_auto(wire_dlt)
        sz_dlt = len(pack_dlt)

        # MSD2 candidate (only if eligible and produces bytes now)
        schema, msd2, subset = self._detect_msd_schema(obj)
        wire_msd = None; kind_msd=None; pack_msd=b''; sz_msd=10**9
        if msd2 is not None:
            payload = msd2.encode(subset)
            if not payload:
                payload = msd2.flush(subset.get('id'))
            if payload:
                wire_msd = b'MSD2' + payload
                kind_msd, pack_msd = entropy_pack_auto(wire_msd)
                sz_msd = len(pack_msd)
        return (kind_dlt, pack_dlt, sz_dlt), (kind_msd, pack_msd, sz_msd)

    def send_object(self, obj, chid=1):
        full_bin = self.enc.enc(obj)
        sum_obj = _summarize(obj)
        sum_bin = self.enc.enc(sum_obj)
        ref = hashlib.blake2s(sum_bin, digest_size=16).digest()

        (kind_dlt, pack_dlt, sz_dlt), (kind_msd, pack_msd, sz_msd) = self._build_residual_candidates(sum_bin, full_bin, obj)

        choice_kind, choice_pack = kind_dlt, pack_dlt
        other_sz = sz_msd
        chosen = 'DLT1'
        if self.residual_policy == 'msd2-only' and sz_msd < 10**9:
            choice_kind, choice_pack = kind_msd, pack_msd; other_sz = sz_dlt; chosen='MSD2'
        elif self.residual_policy == 'delta-only':
            choice_kind, choice_pack = kind_dlt, pack_dlt; other_sz = sz_msd; chosen='DLT1'
        else:  # auto-byte-min
            if sz_msd < sz_dlt:
                choice_kind, choice_pack = kind_msd, pack_msd; other_sz = sz_dlt; chosen='MSD2'

        sf_sum = pack_sframe_bp(1, 0b101, cbv=self.cb.version, len_kind=0, ref_hash=b'', payload=sum_bin)
        sf_res = pack_sframe_bp(7, 0b010, cbv=self.cb.version, len_kind={'raw':0,'huf':1,'z':2}[choice_kind], ref_hash=ref, payload=choice_pack)
        publish_semantic(self.tx, 'SUMMARY', sf_sum, chid=chid)
        publish_semantic(self.tx, 'RESIDUAL', sf_res, chid=chid)

        # metrics & D2
        self.metrics['auto_choice']=chosen
        self.metrics['bytes_chosen']=len(choice_pack)
        self.metrics['bytes_other']=int(other_sz) if isinstance(other_sz,int) else 0
        self._collect_texts(obj); self._maybe_update_d2()

    def _try_reconstruct(self, ref:bytes, kind:int, payload:bytes):
        sum_entry = self.summaries.get(ref)
        if not sum_entry: return False
        sum_bin, _ = sum_entry
        wire = entropy_unpack({0:'raw',1:'huf',2:'z'}[kind], payload)
        obj = None; full_bin = None
        try:
            if wire[:4] == b'DLT1':
                residual = wire[4:]
                full_bin = delta_decode(sum_bin, residual)
                try: obj, _ = self.dec.dec(full_bin, 0, 'val')
                except Exception: obj = None
            elif wire[:4] == b'MSD2':
                msd_b = wire[4:]
                for name, msd in self.msd2_rx.items():
                    try:
                        cand = msd.decode(msd_b)
                        if isinstance(cand, dict) and 'id' in cand:
                            obj = cand; break
                    except Exception:
                        continue
                if obj is not None:
                    full_bin = self.enc.enc(obj)
                    self.metrics['msd_frames_rx'] += 1
        except Exception:
            obj = None

        self.on_object({
            "ref": ref.hex(),
            "summary_bin": sum_bin,
            "full_bin": full_bin if full_bin is not None else b'',
            "obj": obj
        })
        if ref in self.summaries: del self.summaries[ref]
        if ref in self.residuals: del self.residuals[ref]
        return True

    def feed_wire(self, data:bytes):
        self.gc_buffers()
        try:
            sf, _ = unpack_sframe_bp(data, 0)
            s_type = sf['s_type']; kind=sf['len_kind']
            ref = sf['ref_hash']; payload = sf['payload']
            now = time.time()
            if s_type == 1:
                self.metrics['rx_summary'] += 1
                r = hashlib.blake2s(payload, digest_size=16).digest()
                self.summaries[r] = (payload, now)
                if r in self.residuals:
                    rk, rp, _ = self.residuals[r]
                    self._try_reconstruct(r, rk, rp)
                    if r in self.residuals: del self.residuals[r]
            elif s_type == 7:
                self.metrics['rx_residual'] += 1
                r = ref
                if r in self.summaries:
                    self._try_reconstruct(r, kind, payload)
                else:
                    self.residuals[r] = (kind, payload, now)
        except Exception:
            pass

    def gc_buffers(self):
        now = time.time()
        for r, (p, ts) in list(self.summaries.items()):
            if (now - ts) > self.ttl_summary:
                del self.summaries[r]; self.metrics['drops_summary_ttl'] += 1
        for r, (k, p, ts) in list(self.residuals.items()):
            if (now - ts) > self.ttl_residual:
                del self.residuals[r]; self.metrics['drops_residual_ttl'] += 1

    def stats(self):
        return {
            **self.metrics,
            "pending_summaries": len(self.summaries),
            "pending_residuals": len(self.residuals),
            "ttl_summary_sec": self.ttl_summary,
            "ttl_residual_sec": self.ttl_residual,
        }