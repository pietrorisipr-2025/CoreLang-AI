
# cl5x_entropy.py — extended entropy registry for CL6 v6.10
# Supports: raw, zlib ("z"), lz4 (if available), zstd (if available)
# v6.10.2 adds stream-level packing helpers for CL6 batch transport.
import os, glob, hashlib, zlib
from functools import lru_cache

try:
    import lz4.frame as _lz4
    _has_lz4 = True
except Exception:
    _has_lz4 = False
try:
    import zstandard as _zstd
    _has_zstd = True
except Exception:
    _has_zstd = False

def available_codecs():
    s = {"raw","z"}
    if _has_lz4: s.add("lz4")
    if _has_zstd: s.add("zstd")
    return s

def entropy_pack(kind:str, data:bytes, level:int=0)->bytes:
    if kind=="raw": return data
    if kind=="z": return zlib.compress(data, level if level else 6)
    if kind=="lz4":
        if not _has_lz4: raise RuntimeError("lz4 not available")
        # lz4 frame with fast compression
        return _lz4.compress(data, compression_level=0)
    if kind=="zstd":
        if not _has_zstd: raise RuntimeError("zstd not available")
        cctx = _zstd.ZstdCompressor(level if level else 2)
        return cctx.compress(data)
    raise ValueError(f"unknown kind {kind}")

def entropy_unpack(kind:str, data:bytes)->bytes:
    if kind=="raw": return data
    if kind=="z": return zlib.decompress(data)
    if kind=="lz4":
        if not _has_lz4: raise RuntimeError("lz4 not available")
        return _lz4.decompress(data)
    if kind=="zstd":
        if not _has_zstd: raise RuntimeError("zstd not available")
        dctx = _zstd.ZstdDecompressor()
        return dctx.decompress(data)
    raise ValueError(f"unknown kind {kind}")

def entropy_pack_auto(data:bytes, policy:str="auto-byte-min", allowed_codecs:set=None)->tuple[str,bytes]:
    """
    Choose best codec given size and policy. Returns (kind, payload).
    policy: "auto-byte-min" or "auto-latency-min"
    allowed_codecs: subset of {"raw","z","lz4","zstd"}; defaults to available_codecs()
    """
    if allowed_codecs is None:
        allowed_codecs = available_codecs()
    # Always allow raw
    allowed_codecs = set(allowed_codecs) | {"raw"}

    n = len(data)
    # small payloads -> raw
    if n < 300 or ("raw" in allowed_codecs and policy=="auto-latency-min" and n<600):
        return "raw", data

    # candidates
    cand = []
    # lz4 for mid-size if allowed
    if "lz4" in allowed_codecs and 300 <= n <= 1500:
        try:
            out = entropy_pack("lz4", data)
            cand.append(("lz4", out))
        except Exception:
            pass
    # zstd for larger if allowed
    if "zstd" in allowed_codecs and n > 500:
        try:
            out = entropy_pack("zstd", data, level=2 if policy=="auto-byte-min" else 1)
            cand.append(("zstd", out))
        except Exception:
            pass
    # zlib as safety
    if "z" in allowed_codecs:
        try:
            out = entropy_pack("z", data, level=6 if policy=="auto-byte-min" else 3)
            cand.append(("z", out))
        except Exception:
            pass

    if not cand:
        return "raw", data

    # choose best by size (or prefer lz4 under latency policy if close)
    if policy=="auto-latency-min":
        # prefer lz4 if within +8% of the minimum
        sizes = [(k,len(b)) for k,b in cand]
        best_kind, best_bytes = min(cand, key=lambda kv: len(kv[1]))
        lz4_item = next((kv for kv in cand if kv[0]=="lz4"), None)
        if lz4_item and len(lz4_item[1]) <= 1.08*len(best_bytes):
            return lz4_item
        return best_kind, best_bytes
    else:
        return min(cand, key=lambda kv: len(kv[1]))


# ---- stream-level entropy packing -------------------------------------------------
# The per-frame entropy_pack_auto intentionally leaves tiny payloads raw.  That is
# correct for individual residual frames, but wrong for a batch/stream made of many
# small S-Frames.  The helpers below bypass the small-payload threshold and train a
# deterministic zstd dictionary from the local CKB/codebook material when available.

def _split_samples(blob:bytes, chunk:int=2048, max_bytes:int=131072):
    blob = blob[:max_bytes]
    out = []
    for i in range(0, len(blob), chunk):
        part = blob[i:i+chunk]
        if len(part) >= 64:
            out.append(part)
    return out

def _candidate_dict_files(project_root:str):
    root = os.path.abspath(project_root or ".")
    patterns = [
        os.path.join(root, "dict", "*"),
        os.path.join(root, "clean_libs", "*.json"),
        os.path.join(root, "ckb_*.json"),
        os.path.join(root, "*CKB*.json"),
        os.path.join(root, "GLOBAL_MANIFEST_D*.json"),
    ]
    seen = set()
    for pat in patterns:
        for p in glob.glob(pat):
            if p in seen or not os.path.isfile(p):
                continue
            seen.add(p)
            yield p

@lru_cache(maxsize=8)
def _trained_zstd_dict(project_root:str=".", dict_size:int=8192):
    if not _has_zstd:
        return None, b""
    samples = []
    for p in _candidate_dict_files(project_root):
        try:
            data = open(p, "rb").read()
        except Exception:
            continue
        samples.extend(_split_samples(data))
        if len(samples) >= 512:
            break
    if len(samples) < 8:
        return None, b""
    try:
        d = _zstd.train_dictionary(int(dict_size), samples)
        raw = d.as_bytes()
        return d, hashlib.blake2s(raw, digest_size=8).digest()
    except Exception:
        return None, b""

def entropy_pack_stream_auto(data:bytes, policy:str="auto-byte-min", allowed_codecs:set=None,
                             project_root:str=".", use_zstd_dict:bool=True,
                             zstd_level:int|None=None):
    """
    Stream/batch compressor.  Unlike entropy_pack_auto(), this never applies the
    <300 byte raw shortcut to the whole stream.  Returns (kind, payload, meta).
    meta currently contains {"dict_id": hex} when zstd dictionary compression is used.
    """
    if allowed_codecs is None:
        allowed_codecs = available_codecs()
    allowed_codecs = set(allowed_codecs) | {"raw"}

    n = len(data)
    if n == 0:
        return "raw", data, {}

    cand = [("raw", data, {})]

    if "zstd" in allowed_codecs and _has_zstd:
        # Byte-min mode deliberately uses a strong level: the batch path exists for
        # amortized compression, not for per-message latency.
        lvl = int(zstd_level if zstd_level is not None else (19 if policy == "auto-byte-min" else 3))
        try:
            zd, zid = _trained_zstd_dict(os.path.abspath(project_root or ".")) if use_zstd_dict else (None, b"")
            cctx = _zstd.ZstdCompressor(level=lvl, dict_data=zd) if zd is not None else _zstd.ZstdCompressor(level=lvl)
            meta = {"dict_id": zid.hex()} if zid else {}
            cand.append(("zstd", cctx.compress(data), meta))
        except Exception:
            pass

    if "z" in allowed_codecs:
        try:
            cand.append(("z", zlib.compress(data, 6 if policy == "auto-byte-min" else 3), {}))
        except Exception:
            pass

    if "lz4" in allowed_codecs and _has_lz4:
        try:
            cand.append(("lz4", _lz4.compress(data, compression_level=0), {}))
        except Exception:
            pass

    return min(cand, key=lambda kv: len(kv[1]))

def entropy_unpack_stream(kind:str, data:bytes, meta:dict|None=None, project_root:str=".")->bytes:
    meta = meta or {}
    if kind == "zstd" and _has_zstd:
        dict_id = meta.get("dict_id")
        if dict_id:
            zd, zid = _trained_zstd_dict(os.path.abspath(project_root or "."))
            if zd is not None and zid.hex() == dict_id:
                return _zstd.ZstdDecompressor(dict_data=zd).decompress(data)
        return _zstd.ZstdDecompressor().decompress(data)
    return entropy_unpack(kind, data)
