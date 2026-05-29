# cl5x_qprofile_defaults.py — ready-to-use PQ default profiles for common dims
# Rationale: indices are stored 1 byte each (k=256), sub-d ≈ 16 → M = dim/16
# Codes size ≈ M bytes (plus tiny header), e.g. dim=768 → M=48 → ~48 bytes per vector.
from copy import deepcopy

PQ_DEFAULTS = {
    'pq-768':  {'method':'PQ','M':48,'k':256,'dim':768,'sub_d':16,'note':'pq-default-768'},
    'pq-1024': {'method':'PQ','M':64,'k':256,'dim':1024,'sub_d':16,'note':'pq-default-1024'},
    'pq-1536': {'method':'PQ','M':96,'k':256,'dim':1536,'sub_d':16,'note':'pq-default-1536'},
}

def get(name:str)->dict:
    if name in PQ_DEFAULTS:
        return deepcopy(PQ_DEFAULTS[name])
    raise KeyError(f'unknown PQ default: {name}')

def best_for_dim(dim:int)->dict:
    # Aim for sub_d≈16; ensure divisibility
    if dim % 16 == 0:
        M = dim // 16
    elif dim % 12 == 0:
        M = dim // 12
    else:
        # fallback: nearest divisor around 16
        for d in (16, 12, 24, 8, 32):
            if dim % d == 0:
                M = dim // d
                break
        else:
            M = max(8, dim // 16)
    return {'method':'PQ','M':int(M),'k':256,'dim':int(dim),'sub_d':int(dim//int(M)),'note':f'pq-default-{dim}'}