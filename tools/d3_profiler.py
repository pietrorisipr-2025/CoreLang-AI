import argparse, json, re, unicodedata, os
def norm(s):
    s = s.strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s)
    return s
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", default="dict/d3_packs", help="cartella con packs opzionali")
    ap.add_argument("--txt", required=True, help="log di testo osservato")
    ap.add_argument("--merge", required=True, help="D3 base da unire (json)")
    ap.add_argument("--out", required=True, help="D3 risultante (json)")
    args = ap.parse_args()
    base = {"phrases": []}
    if os.path.exists(args.merge):
        base = json.load(open(args.merge,"r",encoding="utf-8"))
    phrases = set(base.get("phrases", []))
    if os.path.exists(args.txt):
        for line in open(args.txt,"r",encoding="utf-8", errors="ignore"):
            line = norm(line)
            if len(line) >= 3 and " " in line:
                phrases.add(line)
    out = {"phrases": sorted(phrases)}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    json.dump(out, open(args.out,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
if __name__ == "__main__":
    main()