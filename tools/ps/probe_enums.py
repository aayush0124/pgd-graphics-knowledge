"""PGD / Photoshop: which harvested ps_api enum names exist as ExtendScript globals, and the run-time name when the
scripting dictionary's (omv.xml) name does not (PDFStandardType -> PDFStandard): candidates are the name without
'Type' and case variants of the global list. Needs the Photoshop this pipeline started (psdrv).

    python tools/ps/probe_enums.py      -> work/plans/ps_enum_probe.json and a list of the missing names
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ps"))
import psdrv  # noqa: E402

if psdrv._ps_pids() and not psdrv.owned_pid():
    sys.exit("Photoshop running is not ours")
h = json.loads((ROOT / "harvest/ps/ps_api.json").read_text(encoding="utf-8"))
names = [it["name"] for it in h["items"] if it["id"].startswith("enum:")]
src = """(function(){var N=%s,out={},g=[];
try{var p=$.global.reflect.properties;for(var i=0;i<p.length;i++)g.push(String(p[i].name));}catch(e){}
for(var i=0;i<N.length;i++){var n=N[i],t="undefined";try{t=typeof eval(n);}catch(e){}out[n]=t;}
return J({types:out,globals:g});})()""" % json.dumps(names)
r = json.loads(psdrv.js(src, timeout=120, tag="enum-probe"))
glob = r["globals"]
low = {g.lower(): g for g in glob}
res = {}
for n in names:
    if r["types"][n] != "undefined":
        res[n] = {"exists": True}
        continue
    cands = [n[:-4]] if n.endswith("Type") else []
    hit = next((c for c in cands if c in glob), None) or low.get(n.lower()) or next(
        (low[c.lower()] for c in cands if c.lower() in low), None)
    res[n] = {"exists": False, "runtime": hit}
out = ROOT / "work/plans/ps_enum_probe.json"
out.write_text(json.dumps({"globals": len(glob), "names": res}, indent=1), encoding="utf-8")
bad = {n: v for n, v in res.items() if not v["exists"]}
print(len(names), "enums;", len(glob), "globals;", len(bad), "missing at run time:")
for n, v in bad.items():
    print(" ", n, "->", v["runtime"])
