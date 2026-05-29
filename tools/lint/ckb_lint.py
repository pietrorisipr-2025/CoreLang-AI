#!/usr/bin/env python3
import sys, os, json, re, glob
from jsonschema import validate, ValidationError

def lint_d1(path):
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    for ent in obj.get("parametric", []):
        tpl = ent.get("template","")
        args = ent.get("args",[])
        if tpl.count("{}") != len(args):
            print(f"[D1] placeholder count mismatch: {ent.get('sym')} -> tpl has {tpl.count('{}')}, args {len(args)}")
            return 1
    return 0

def lint_d3(path):
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    for t in obj.get("templates", []):
        if t["template_key"].count("{}") != len(t.get("placeholders",[])):
            print(f"[D3] placeholder mismatch: {t.get('canonical')}")
            return 1
    return 0

def main():
    base=sys.argv[1] if len(sys.argv)>1 else "."
    bad=0
    for root,_,files in os.walk(base):
        for fn in files:
            if fn.endswith("_parametric.json"):
                bad |= lint_d1(os.path.join(root,fn))
            if fn == "templates.json":
                bad |= lint_d3(os.path.join(root,fn))
    if bad:
        sys.exit(1)
    print("OK")
if __name__=="__main__":
    main()
