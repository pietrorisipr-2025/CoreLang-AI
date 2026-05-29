
# cl5x_qvec_rvq.py — simple Residual Vector Quantization (multi-stage)
import random, math
from typing import List, Tuple

def _kmeans(data, k, iters=8):
    random.seed(11)
    centroids = [data[i%len(data)][:] for i in range(k)]
    for _ in range(iters):
        assigns = [[] for _ in range(k)]
        for v in data:
            best, bi = 1e30, 0
            for i,c in enumerate(centroids):
                d = sum((a-b)*(a-b) for a,b in zip(v,c))
                if d<best: best,bi=d,i
            assigns[bi].append(v)
        for i,grp in enumerate(assigns):
            if not grp: continue
            centroids[i] = [sum(vals)/len(vals) for vals in zip(*grp)]
    return centroids

def train_rvq(vectors:List[List[float]], stages:int=3, k:int=16, iters:int=6)->Tuple[List[List[List[float]]], int]:
    residuals = [v[:] for v in vectors]
    codebooks = []
    for s in range(stages):
        cb = _kmeans(residuals, k, iters)
        codebooks.append(cb)
        for i,v in enumerate(residuals):
            best, bi = 1e30, 0
            for j,c in enumerate(cb):
                d = sum((a-b)*(a-b) for a,b in zip(v,c))
                if d<best: best,bi=d,j
            residuals[i] = [a-b for a,b in zip(residuals[i], cb[bi])]
    return codebooks, len(codebooks[0][0])

def encode_rvq(vec:List[float], codebooks:List[List[List[float]]])->bytes:
    out = bytearray(b"RVQ1")
    res = vec[:]
    for cb in codebooks:
        best, bi = 1e30, 0
        for j,c in enumerate(cb):
            d = sum((a-b)*(a-b) for a,b in zip(res,c))
            if d<best: best,bi=d,j
        out.append(bi & 0xFF)
        res = [a-b for a,b in zip(res, cb[bi])]
    return bytes(out)

def decode_rvq(b:bytes, codebooks:List[List[List[float]]])->List[float]:
    assert b[:4]==b"RVQ1"
    idxs = list(b[4:])
    vec = [0.0]*len(codebooks[0][0])
    for cb,i in zip(codebooks, idxs):
        vec = [a+b for a,b in zip(vec, cb[i])]
    return vec
