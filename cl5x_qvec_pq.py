# cl5x_qvec_pq.py — tiny PQ (Product Quantization) for float vectors
# Split vector into M subspaces, k centroids per subspace; encode indices.
# WARNING: toy implementation for moderate dims; training uses few iterations.
import random, struct, math
from typing import List, Tuple

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def kmeans(data:List[List[float]], k:int, iters:int=10)->List[List[float]]:
    # init by sampling
    random.seed(7)
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

def train_pq(vectors:List[List[float]], M:int=4, k:int=16, iters:int=8)->Tuple[List[List[List[float]]], int]:
    D = len(vectors[0])
    assert D%M==0, "D must be divisible by M"
    d = D//M
    codebooks = []
    for m in range(M):
        sub = [v[m*d:(m+1)*d] for v in vectors]
        cb = kmeans(sub, k, iters)
        codebooks.append(cb)
    return codebooks, d

def encode_pq(vec:List[float], codebooks:List[List[List[float]]], d_sub:int)->bytes:
    M = len(codebooks)
    out = bytearray(b"PQ1\0")
    for m in range(M):
        sub = vec[m*d_sub:(m+1)*d_sub]
        best, bi = 1e30, 0
        for i,c in enumerate(codebooks[m]):
            d = sum((a-b)*(a-b) for a,b in zip(sub,c))
            if d<best: best,bi=d,i
        out.append(bi & 0xFF)
    return bytes(out)

def decode_pq(b:bytes, codebooks:List[List[List[float]]], d_sub:int)->List[float]:
    assert b[:4]==b"PQ1\0"
    idxs = b[4:]
    vec = []
    for m,i in enumerate(idxs):
        vec += codebooks[m][i]
    return vec