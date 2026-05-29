
import random, math
def l2(a,b): return sum((x-y)*(x-y) for x,y in zip(a,b))
def seg(v, start, length): return v[start:start+length]
def choose_M(dim:int)->int:
    for d in (16,12,24,8,32):
        if dim % d == 0: return dim//d
    return max(8, dim//16)
def train_pq(vectors, M:int, k:int):
    if not vectors: return {"method":"PQ","M":M,"k":k,"dim":0,"codebooks":[]}
    dim=len(vectors[0]); sub_d=dim//M; codebooks=[]
    for m in range(M):
        sv=[seg(v, m*sub_d, sub_d) for v in vectors]
        cent=random.sample(sv, min(k,len(sv)))
        for _ in range(3):
            groups=[[] for _ in cent]
            for v in sv:
                idx=min(range(len(cent)), key=lambda i: l2(v, cent[i]))
                groups[idx].append(v)
            for i,g in enumerate(groups):
                if g: cent[i]=[sum(col)/len(g) for col in zip(*g)]
        codebooks.append(cent)
    return {"method":"PQ","M":M,"k":k,"dim":dim,"sub_d":sub_d,"codebooks":codebooks}
