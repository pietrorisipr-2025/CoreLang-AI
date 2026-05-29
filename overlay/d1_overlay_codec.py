
import json, re, os

def load_maps(base_path=None):
    base_path = base_path or os.path.dirname(__file__)
    with open(os.path.join(base_path, "d1_overlay_map.json"), "r", encoding="utf-8") as f:
        fwd = json.load(f)
    with open(os.path.join(base_path, "d1_overlay_reverse.json"), "r", encoding="utf-8") as f:
        rev = json.load(f)
    # sort keys by length desc to avoid partial overlaps
    keys = sorted(fwd.keys(), key=len, reverse=True)
    return fwd, rev, keys

def encode_text(s: str, fwd=None, keys=None):
    if not fwd or not keys:
        fwd, _, keys = load_maps()
    # replace whole-word or underscore-boundary tokens
    def repl(m):
        token = m.group(0)
        return fwd.get(token, token)
    # build a regex that matches any token boundary-wise
    pattern = r'\b(?:' + '|'.join(re.escape(k) for k in keys) + r')\b'
    return re.sub(pattern, repl, s)

def decode_text(s: str, rev=None):
    if not rev:
        _, rev, _ = load_maps()
    # replace aliases back
    def repl(m):
        alias = m.group(0)
        return rev.get(alias, alias)
    return re.sub(r'~k[0-9a-z]+', repl, s)
