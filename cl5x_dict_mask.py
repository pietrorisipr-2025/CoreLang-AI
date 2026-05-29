# cl5x_dict_mask.py — helpers to decide which blocchid1 to announce, and build a mask
import json, hashlib

def version_digest(phrases)->str:
    return hashlib.blake2s(("|".join(phrases)).encode("utf-8"), digest_size=6).hexdigest()

def choose_blocks(manifest_json:str, needed:list)->dict:
    man = json.loads(open(manifest_json,"r",encoding="utf-8").read())
    blocks = man["D1"]["blocks"]
    mask = 0
    selected = []
    for b in blocks:
        name = b["block"]
        for want in needed:
            if want in name or want==name:
                mb = b.get("mask_bit", -1)
                if mb>=0: mask |= (1<<mb)
                selected.append(b)
                break
    return {"mask": mask, "blocks": selected}