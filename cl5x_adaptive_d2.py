# cl5x_adaptive_d2.py — Adaptive phrasebook (D2) with CKB micro-updates
import json, re
from collections import Counter
def suggest_phrases(recent_texts, max_phrases=200, gain_threshold=512):
    ctr=Counter()
    for t in recent_texts:
        for w in t.split():
            if len(w)>=6 and w.isupper() and w.isalpha():
                ctr[w]+=1
        for m in re.finditer(r'"([a-zA-Z_][a-zA-Z0-9_]*)"\s*:', t):
            ctr[m.group(1)] += 1
    cands=[]
    for s,f in ctr.items():
        gain=max(0,(len(s)-2))*f
        if gain>=gain_threshold: cands.append((gain,s))
    cands.sort(reverse=True)
    return [s for _,s in cands[:max_phrases]]
def make_ckb_update_frame(phrases):
    payload=json.dumps({'type':'CKB_UPDATE','layer':'D2','phr':phrases}, separators=(',',':')).encode('utf-8')
    return b'CKB1'+payload