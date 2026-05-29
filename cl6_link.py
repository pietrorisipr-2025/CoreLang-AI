# cl6_link.py — Corelang6 Link v6.10
# Adds: CAPA_NEG enforcement, RSYN ring buffer resend, pacing (token-bucket),
# D3 persistent phrases announce, CAS/REF helpers, and batch send API.
import os, json, time, hashlib
from typing import Dict, Any, List, Tuple

# tiny semantic codec (same as v6.x minimal)
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
            for _ in range(n): v,off=self.dec(buf,off,'val'); out.append(v)
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
            else: out[k]=_summarize(v)
        return out
    if isinstance(x,list):
        return [_summarize(i) for i in (x[:1]+(['...'] if len(x)>2 else [])+x[-1:])]
    if isinstance(x,str) and len(x)>256: return x[:256]
    return x

from cl6_sframe_bitpack import pack_sframe_bp, unpack_sframe_bp
from cl5x_delta_vcdiff import delta_encode, delta_decode
from cl5x_entropy import entropy_pack_auto, entropy_unpack, available_codecs, entropy_pack_stream_auto, entropy_unpack_stream
from cl5x_qos_profiles import publish_semantic
from cl5x_adaptive_d2 import suggest_phrases, make_ckb_update_frame
from cl5x_msd_delta2 import MSDDelta2
from cl5x_qprofile import build_qprofile_frame
from cl5x_qprofile_defaults import get as get_qp_default, best_for_dim as qp_best_for_dim

from cl6_integrity import wrap_mic, unwrap_mic
from cl6_capa import build_capa_frame, parse_capa_frame, negotiate
from cl6_resync import build_anchor, build_resync_request, parse_rs

STREAM_BATCH_TYPE = 0
STREAM_FULL_OBJECT_TYPE = 2
STREAM_BATCH_FLAGS = 0b111
STREAM_BATCH_MAGIC = b"CL6SB1"
CODEC_TO_LEN_KIND = {'raw':0,'huf':1,'z':2,'lz4':3,'zstd':4}
LEN_KIND_TO_CODEC = {0:'raw',1:'huf',2:'z',3:'lz4',4:'zstd'}

def _pack_stream_envelope(kind:str, original_len:int, payload:bytes, meta:dict|None=None)->bytes:
    header = json.dumps({"kind":kind, "original_len":int(original_len), "meta":meta or {}}, separators=(",",":")).encode("utf-8")
    return STREAM_BATCH_MAGIC + _enc_varint(len(header)) + header + payload

def _unpack_stream_envelope(payload:bytes):
    if not payload.startswith(STREAM_BATCH_MAGIC):
        raise ValueError("not a CL6 stream-batch envelope")
    off = len(STREAM_BATCH_MAGIC)
    n, off = _dec_varint(payload, off)
    header = json.loads(payload[off:off+n].decode("utf-8")); off += n
    return header, payload[off:]

class CL6Link:
    def __init__(self, tx, on_object, manifest_path='ckb_layers_manifest.json', needed_blocks=None, auto_handshake=True,
                 ttl_summary_sec=5.0, ttl_residual_sec=7.0, auto_d2=True, qprofile=None,
                 residual_policy:str='auto-byte-min', mic_key:bytes=None, anchor_every:int=8,
                 rate_limit_bps:int=0, burst_bytes:int=32768, d3_path:str='ckb_D3_phrases.json', rsyn_buffer:int=64,
                 batch_window:float=0.0, batch_max:int=0, stream_zstd_level:int|None=None):
        self.tx = tx
        self.on_object = on_object
        self.cb = _default_codebook()
        self.enc = _SEncoder(self.cb); self.dec = _SDecoder(self.cb)
        # buffers
        self.summaries = {}      # ref_hash(bytes) -> (payload, ts)
        self.residuals = {}      # ref_hash(bytes) -> (kind, payload, ts)
        # RSYN ring buffer
        self.ring = []           # [(ref, sf_sum_bytes, sf_res_bytes, ts)]
        self.ring_max = max(8, int(rsyn_buffer))
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
        self.recent_texts = []; self.last_d2_ts = 0.0
        # TTL & metrics
        self.ttl_summary = ttl_summary_sec; self.ttl_residual = ttl_residual_sec
        self.metrics = {'rx_summary':0,'rx_residual':0,'reconstructed':0,'drops_summary_ttl':0,'drops_residual_ttl':0,
                        'msd_frames_tx':0,'msd_frames_rx':0,'auto_choice':'','bytes_chosen':0,'bytes_other':0,
                        'anchors_tx':0,'anchors_rx':0,'resync_req_tx':0,'resync_req_rx':0,'mic_used':0,
                        'resends':0,'bundled':0,'pacing_drops':0,
                        'stream_batches_tx':0,'stream_batches_rx':0,'stream_objects_tx':0,'stream_objects_rx':0,
                        'stream_plain_bytes':0,'stream_packed_bytes':0,'stream_codec':''}
        self.needed_blocks = needed_blocks or []; self.manifest_path = manifest_path
        self.qprofile = self._resolve_qprofile(qprofile)
        self.residual_policy = residual_policy
        self.mic_key = mic_key
        self.anchor_every = max(1, int(anchor_every))
        self.allowed_codecs = available_codecs()
        self.entropy_policy = 'auto-byte-min'
        self._msg_counter = 0
        # CAPA
        self.local_capa = {"SFRAME":"bp1","DLT1":1,"MSD2":1,"MIC1":1,"RSYN1":1,"QPROF1":1,"STREAM_BATCH1":1}
        if "lz4" in self.allowed_codecs: self.local_capa["CMP_LZ41"] = 1
        if "zstd" in self.allowed_codecs: self.local_capa["CMP_ZSTD1"] = 1
        self.peer_capa = None; self.capa_neg = None
        # pacing
        self.rate_limit_bps = int(rate_limit_bps) if rate_limit_bps else 0
        self.burst_bytes = int(burst_bytes)
        self._tokens = self.burst_bytes
        self._last_refill = time.time()
        # D3 phrases
        self.d3_path = d3_path
        # Optional application-level batching for repeated send_object() calls.
        # No background timer is used: call flush_batch() at the end of a burst,
        # or set batch_max/batch_window so the next send_object() flushes naturally.
        self.batch_window = float(batch_window or 0.0)
        self.batch_max = int(batch_max or 0)
        self.stream_zstd_level = stream_zstd_level
        self._batch_queue: List[Tuple[dict,int]] = []
        self._batch_started = 0.0
        if auto_handshake:
            self.handshake()

    def _resolve_qprofile(self, qprofile):
        if isinstance(qprofile, dict): return qprofile
        if isinstance(qprofile, str) and qprofile.startswith('pq-'):
            try: return get_qp_default(qprofile)
            except Exception: return None
        if isinstance(qprofile, tuple) and len(qprofile)==2 and qprofile[0]=='pq':
            try: return qp_best_for_dim(int(qprofile[1]))
            except Exception: return None
        return None

    def _apply_capa_neg(self):
        # Disable features not present in negotiated set
        if not self.capa_neg: return
        feat = self.capa_neg.get("feat", {})
        if not feat.get("MSD2"): self.residual_policy = 'delta-only'
        if not feat.get("MIC1"): self.mic_key = None
        if not feat.get("QPROF1"): self.qprofile = None
        # RSYN toggle is implicit

        # Restrict codecs based on negotiated CAPA
        allowed = set(['raw','z'])  # always have zlib/raw
        feat = self.capa_neg.get("feat", {})
        if feat.get("CMP_LZ41"): allowed.add('lz4')
        if feat.get("CMP_ZSTD1"): allowed.add('zstd')
        self.allowed_codecs = allowed.intersection(available_codecs())

    def handshake(self):
        # CAPA
        cap = build_capa_frame(self.local_capa)
        publish_semantic(self.tx, 'CKB', cap, chid=1)
        # D0 + D1
        d0 = 'ckb_D0_control.bin'
        if os.path.exists(d0):
            publish_semantic(self.tx, 'CKB', open(d0,'rb').read(), chid=1)
        try:
            man = json.loads(open(self.manifest_path,'r',encoding='utf-8').read())
            blocks = man['D1']['blocks']
            for b in blocks:
                name=b['block']
                fpath = b['file']
                if not os.path.exists(fpath):
                    basename = os.path.basename(fpath)
                    cand = os.path.join('dict','D1_blocks', basename)
                    if os.path.exists(cand): fpath = cand
                if os.path.exists(fpath) and (not self.needed_blocks or any((want in name) or (want==name) for want in self.needed_blocks)):
                    publish_semantic(self.tx, 'CKB', open(fpath,'rb').read(), chid=1)
        except Exception:
            pass
        # QPROFILE
        if isinstance(self.qprofile, dict):
            publish_semantic(self.tx, 'CKB', build_qprofile_frame(self.qprofile), chid=1)
        # D3 persistent phrases (if present)
        if self.d3_path and os.path.exists(self.d3_path):
            try:
                d3 = json.loads(open(self.d3_path,'r',encoding='utf-8').read())
                if isinstance(d3, dict) and d3.get("phrases"):
                    from cl5x_adaptive_d2 import make_ckb_update_frame
                    publish_semantic(self.tx, 'CKB', make_ckb_update_frame(d3["phrases"]), chid=1)
            except Exception:
                pass

    # pacing (token bucket)
    def _refill_tokens(self):
        if self.rate_limit_bps <= 0: return
        now = time.time()
        add = (now - self._last_refill) * self.rate_limit_bps
        self._tokens = min(self.burst_bytes, self._tokens + add)
        self._last_refill = now

    def _consume_tokens(self, nbytes:int)->bool:
        if self.rate_limit_bps <= 0: return True
        self._refill_tokens()
        if self._tokens >= nbytes:
            self._tokens -= nbytes
            return True
        return False

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
        if not phrases: return
        publish_semantic(self.tx, 'CKB', make_ckb_update_frame(phrases), chid=1)
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
        # DLT1
        residual = delta_encode(sum_bin, full_bin)
        wire_dlt = b'DLT1' + residual
        kind_dlt, pack_dlt = entropy_pack_auto(wire_dlt, policy=self.entropy_policy, allowed_codecs=self.allowed_codecs)
        sz_dlt = len(pack_dlt)
        # MSD2
        schema, msd2, subset = self._detect_msd_schema(obj)
        wire_msd = None; kind_msd=None; pack_msd=b''; sz_msd=10**9
        if msd2 is not None and self.residual_policy != 'delta-only':
            payload = msd2.encode(subset) or msd2.flush(subset.get('id'))
            if payload:
                wire_msd = b'MSD2' + payload
                kind_msd, pack_msd = entropy_pack_auto(wire_msd, policy=self.entropy_policy, allowed_codecs=self.allowed_codecs)
                sz_msd = len(pack_msd)
        return (kind_dlt, pack_dlt, sz_dlt), (kind_msd, pack_msd, sz_msd)

    def _maybe_anchor(self, sum_bin:bytes, chid:int):
        self._msg_counter += 1
        if (self._msg_counter % self.anchor_every) == 0:
            anch = build_anchor(sum_bin, self._msg_counter//self.anchor_every)
            publish_semantic(self.tx, 'CKB', anch, chid=chid)
            self.metrics['anchors_tx'] += 1

    def _record_ring(self, ref:bytes, sf_sum:bytes, sf_res:bytes):
        self.ring.append((ref, sf_sum, sf_res, time.time()))
        if len(self.ring) > self.ring_max:
            self.ring.pop(0)

    def _publish_sf(self, sf_bytes:bytes, chid:int, approx_cost:int):
        if not self._consume_tokens(approx_cost):
            self.metrics['pacing_drops'] += 1
            return False
        publish_semantic(self.tx, 'SUMMARY' if sf_bytes[:1]==b'\x00' else 'RESIDUAL', sf_bytes, chid=chid)
        return True


    def _make_full_object_sframe(self, obj:dict):
        """Build an uncompressed inner S-Frame carrying a full semantic object.
        This is used only inside stream-batch envelopes: the whole concatenated
        stream is entropy-compressed once, so small frames share one dictionary/state.
        """
        full_bin = self.enc.enc(obj)
        ref = hashlib.blake2s(full_bin, digest_size=16).digest()
        return ref, pack_sframe_bp(STREAM_FULL_OBJECT_TYPE, 0b000, cbv=self.cb.version, len_kind=0, ref_hash=ref, payload=full_bin)

    def _publish_stream_batch(self, objs:List[dict], chid:int=1):
        self._apply_capa_neg()
        inner = bytearray()
        refs = []
        for obj in objs:
            ref, sf = self._make_full_object_sframe(obj)
            refs.append(ref)
            inner += sf
            self._collect_texts(obj)

        plain = bytes(inner)
        kind, packed, meta = entropy_pack_stream_auto(
            plain,
            policy='auto-byte-min',
            allowed_codecs=self.allowed_codecs,
            project_root=os.getcwd(),
            use_zstd_dict=True,
            zstd_level=self.stream_zstd_level,
        )
        envelope = _pack_stream_envelope(kind, len(plain), packed, meta)
        outer = pack_sframe_bp(STREAM_BATCH_TYPE, STREAM_BATCH_FLAGS, cbv=self.cb.version, len_kind=0, ref_hash=b'', payload=envelope)
        if not self._consume_tokens(len(outer)):
            self.metrics['pacing_drops'] += 1
            return False
        publish_semantic(self.tx, 'RESIDUAL', outer, chid=chid)
        self.metrics['stream_batches_tx'] += 1
        self.metrics['stream_objects_tx'] += len(objs)
        self.metrics['stream_plain_bytes'] += len(plain)
        self.metrics['stream_packed_bytes'] += len(packed)
        self.metrics['stream_codec'] = kind
        self.metrics['bundled'] += len(objs)
        self._maybe_update_d2()
        return True

    def flush_batch(self, chid:int|None=None):
        """Flush objects accumulated by send_object() when batch_max/batch_window is enabled."""
        if not self._batch_queue:
            return False
        if chid is None:
            chid = self._batch_queue[0][1]
        objs = [o for (o, _) in self._batch_queue]
        self._batch_queue.clear()
        self._batch_started = 0.0
        return self.send_batch(objs, chid=chid)

    def send_object(self, obj, chid=1):
        # Optional batching path for repeated send_object() calls.
        if self.batch_max > 0 or self.batch_window > 0:
            now = time.time()
            if not self._batch_queue:
                self._batch_started = now
            self._batch_queue.append((obj, chid))
            max_hit = self.batch_max > 0 and len(self._batch_queue) >= self.batch_max
            window_hit = self.batch_window > 0 and (now - self._batch_started) >= self.batch_window
            if max_hit or window_hit:
                return self.flush_batch(chid=chid)
            return True

        # Legacy single-object path: kept for wire compatibility with existing peers.
        self._apply_capa_neg()

        full_bin = self.enc.enc(obj)
        sum_obj = _summarize(obj); sum_bin = self.enc.enc(sum_obj)
        ref = hashlib.blake2s(sum_bin, digest_size=16).digest()

        (kind_dlt, pack_dlt, sz_dlt), (kind_msd, pack_msd, sz_msd) = self._build_residual_candidates(sum_bin, full_bin, obj)
        chosen_kind, chosen_pack, chosen = kind_dlt, pack_dlt, 'DLT1'
        other_sz = sz_msd

        if self.residual_policy == 'msd2-only' and sz_msd < 10**9:
            chosen_kind, chosen_pack, chosen = kind_msd, pack_msd, 'MSD2'; other_sz = sz_dlt
        elif self.residual_policy == 'delta-only':
            pass
        else:
            if sz_msd < sz_dlt:
                chosen_kind, chosen_pack, chosen = kind_msd, pack_msd, 'MSD2'; other_sz = sz_dlt
        # Optional MIC1
        sum_payload = sum_bin
        res_payload = chosen_pack
        if self.mic_key:
            sum_payload = wrap_mic(sum_payload, self.mic_key)
            res_payload = wrap_mic(res_payload, self.mic_key)
            self.metrics['mic_used'] += 1

        sf_sum = pack_sframe_bp(1, 0b101, cbv=self.cb.version, len_kind=0, ref_hash=b'', payload=sum_payload)
        sf_res = pack_sframe_bp(7, 0b010, cbv=self.cb.version, len_kind=CODEC_TO_LEN_KIND.get(chosen_kind,0), ref_hash=ref, payload=res_payload)

        # pacing-aware publish (coalesced in-order)
        ok1 = self._publish_sf(sf_sum, chid, len(sf_sum))
        ok2 = self._publish_sf(sf_res, chid, len(sf_res))
        if ok1 and ok2:
            self._record_ring(ref, sf_sum, sf_res)
        self.metrics['auto_choice']=chosen; self.metrics['bytes_chosen']=len(chosen_pack); self.metrics['bytes_other']=int(other_sz)
        self._collect_texts(obj); self._maybe_update_d2(); self._maybe_anchor(sum_bin, chid)
        return ok1 and ok2

    def send_batch(self, objs:List[dict], chid:int=1):
        # v6.10.2 stream-batch path: build all inner S-Frames uncompressed, then
        # compress the concatenated stream once.  This avoids the old per-frame
        # entropy reset and bypasses the <300-byte raw shortcut for tiny residuals.
        return self._publish_stream_batch(list(objs or []), chid=chid)

    def _request_resync(self, ref:bytes, chid:int=1):
        if not self.capa_neg or not self.capa_neg.get("feat",{}).get("RSYN1",1):
            return
        rq = build_resync_request(ref.hex(), want_n=3)
        publish_semantic(self.tx, 'CKB', rq, chid=chid)
        self.metrics['resync_req_tx'] += 1

    def _resend_by_ref(self, ref_hex:str, chid:int=1, extra:int=2):
        # find in ring and resend it + 'extra' previous
        for i in range(len(self.ring)-1, -1, -1):
            r, sf_sum, sf_res, ts = self.ring[i]
            if r.hex() == ref_hex:
                j0 = max(0, i-extra); items = self.ring[j0:i+1]
                for r2, ssum, sres, _ in items:
                    publish_semantic(self.tx, 'SUMMARY', ssum, chid=chid)
                    publish_semantic(self.tx, 'RESIDUAL', sres, chid=chid)
                    self.metrics['resends'] += 1
                return True
        return False

    def feed_wire(self, data:bytes):
        # control frames
        if data.startswith(b"CAPA1"):
            try:
                remote = parse_capa_frame(data); self.peer_capa = remote
                self.capa_neg = negotiate({"feat":self.local_capa}, remote)
                self._apply_capa_neg()
            except Exception: pass
            return
        if data.startswith(b"RSYN1"):
            try:
                rs = parse_rs(data)
                if rs.get("mode")=="REQ":
                    self.metrics['resync_req_rx'] += 1
                    self._resend_by_ref(rs.get("ref",""), chid=1, extra=int(rs.get("want",3))-1)
                elif rs.get("mode")=="ANCH":
                    self.metrics['anchors_rx'] += 1
            except Exception: pass
            return

        # data frames (S-Frame unpack)
        self.gc_buffers()
        try:
            sf, _ = unpack_sframe_bp(data, 0)
            self._handle_sframe(sf)
        except Exception:
            pass

    def _handle_sframe(self, sf:dict):
        s_type = sf['s_type']; flags = sf.get('flags', 0); kind = sf['len_kind']
        ref = sf['ref_hash']; payload = sf['payload']
        now = time.time()

        if s_type == STREAM_BATCH_TYPE and flags == STREAM_BATCH_FLAGS and payload.startswith(STREAM_BATCH_MAGIC):
            return self._feed_stream_batch(payload)

        if s_type == STREAM_FULL_OBJECT_TYPE:
            try:
                obj, off = self.dec.dec(payload, 0, 'val')
                full_bin = payload[:off]
            except Exception:
                return False
            self.on_object({"ref":ref.hex(),"summary_bin":b'',"full_bin":full_bin,"obj":obj})
            self.metrics['stream_objects_rx'] += 1
            self.metrics['reconstructed'] += 1
            return True

        # unwrap MIC on SUMMARY to compute ref
        if s_type == 1:
            if self.mic_key and payload.startswith(b"MIC1"):
                try: payload_checked = unwrap_mic(payload, self.mic_key)
                except Exception: return False
                ref_calc = hashlib.blake2s(payload_checked, digest_size=16).digest()
                payload = payload_checked
            else:
                ref_calc = hashlib.blake2s(payload, digest_size=16).digest()
            self.summaries[ref_calc] = (payload, now)
            self.metrics['rx_summary'] += 1
            if ref_calc in self.residuals:
                rk, rp, _ = self.residuals[ref_calc]
                self._try_reconstruct(ref_calc, rk, rp)
                if ref_calc in self.residuals: del self.residuals[ref_calc]
            return True
        elif s_type == 7:
            self.metrics['rx_residual'] += 1
            r = ref
            if r in self.summaries:
                self._try_reconstruct(r, kind, payload)
            else:
                self.residuals[r] = (kind, payload, now)
            return True
        return False

    def _feed_stream_batch(self, payload:bytes):
        try:
            header, packed = _unpack_stream_envelope(payload)
            kind = header.get("kind", "raw")
            meta = header.get("meta", {}) or {}
            plain = entropy_unpack_stream(kind, packed, meta=meta, project_root=os.getcwd())
            if int(header.get("original_len", len(plain))) != len(plain):
                return False
        except Exception:
            return False

        off = 0
        count = 0
        try:
            while off < len(plain):
                sf, off = unpack_sframe_bp(plain, off)
                self._handle_sframe(sf)
                count += 1
        except Exception:
            return False
        self.metrics['stream_batches_rx'] += 1
        self.metrics['stream_codec'] = kind
        return count > 0

    def _try_reconstruct(self, ref:bytes, kind:int, payload:bytes):
        sum_entry = self.summaries.get(ref)
        if not sum_entry: return False
        sum_bin, _ = sum_entry
        # Legacy compatibility: older frames are entropy-packed per residual.
        # If MIC wraps the packed bytes, verify before decompression.
        packed = payload
        if self.mic_key and packed.startswith(b"MIC1"):
            try: packed = unwrap_mic(packed, self.mic_key)
            except Exception: self._request_resync(ref); return False
        try:
            wire = entropy_unpack(LEN_KIND_TO_CODEC.get(kind,'raw'), packed)
        except Exception:
            self._request_resync(ref); return False

        obj=None; full_bin=None
        try:
            if wire[:4]==b'DLT1':
                residual = wire[4:]
                full_bin = delta_decode(sum_bin, residual)
                try: obj,_ = self.dec.dec(full_bin,0,'val')
                except Exception: obj=None
            elif wire[:4]==b'MSD2':
                msd_b = wire[4:]
                for _,msd in self.msd2_rx.items():
                    try:
                        cand = msd.decode(msd_b)
                        if isinstance(cand,dict) and 'id' in cand:
                            obj=cand; break
                    except Exception: continue
                if obj is not None:
                    full_bin = self.enc.enc(obj)
            else:
                self._request_resync(ref); return False
        except Exception:
            self._request_resync(ref); return False

        self.on_object({"ref":ref.hex(),"summary_bin":sum_bin,"full_bin":full_bin or b'',"obj":obj})
        if ref in self.summaries: del self.summaries[ref]
        if ref in self.residuals: del self.residuals[ref]
        self.metrics['reconstructed'] += 1
        return True

    def gc_buffers(self):
        now = time.time()
        for r,(p,ts) in list(self.summaries.items()):
            if (now - ts) > self.ttl_summary:
                del self.summaries[r]; self.metrics['drops_summary_ttl'] += 1
        for r,(k,p,ts) in list(self.residuals.items()):
            if (now - ts) > self.ttl_residual:
                del self.residuals[r]; self.metrics['drops_residual_ttl'] += 1

    # ---- CAS/REF helpers ----
    def cas_put(self, blob:bytes)->str:
        h = hashlib.blake2s(blob, digest_size=16).hexdigest()
        folder = "cl6_cas"; os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, h+".bin"), "wb") as f:
            f.write(blob)
        return h

    def cas_get(self, hex_hash:str)->bytes:
        p = os.path.join("cl6_cas", hex_hash+".bin")
        return open(p,"rb").read() if os.path.exists(p) else b""

    def send_ref(self, hex_hash:str, chid:int=1):
        frame = b"CAS1"+hex_hash.encode("ascii")
        publish_semantic(self.tx, 'CKB', frame, chid=chid)

    def feed_ref(self, data:bytes):
        if data.startswith(b"CAS1"):
            # placeholder: application can hook a fetch here
            pass

    def stats(self): 
        return {**self.metrics, "pending_summaries":len(self.summaries), "pending_residuals":len(self.residuals),
                "ring": len(self.ring), "rate_limit_bps": self.rate_limit_bps, "burst_bytes": self.burst_bytes}