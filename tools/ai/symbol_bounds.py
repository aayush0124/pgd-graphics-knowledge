"""PGD / Illustrator: re-probe the size of every symbol-based ai_preset item (extra.symbol_size_pt) from the live app.

    python symbol_bounds.py            probe every library (resumable: work/ai/symbol_bounds.json)
    python symbol_bounds.py --apply    write the probed sizes that differ into harvest/ai/ai_preset.json (+ the
                                       work/batches copies); prints the corrected ids

symbolItems.add() places an instance at the symbol's stored position. In some libraries (Dot Pattern / Florid Vector
Pack) that lies past the canvas edge, and there width / height read back wrong (Florid 08: 1157 x 232 pt; on the
artboard 160 x 232 pt, which a PNG export of the instance confirms). So each instance is moved onto the artboard first.
Library documents are opened by this script (refused if already open) and closed DONOTSAVECHANGES.
"""
import argparse, json, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
HARVEST = ROOT / "harvest" / "ai" / "ai_preset.json"
CKPT = ROOT / "work" / "ai" / "symbol_bounds.json"
TOL = 0.5  # pt
NOTE = ("; symbol_size_pt re-probed 2026-10-13 (tools/ai/symbol_bounds.py): instance moved onto the artboard before "
        "width / height were read (where symbolItems.add placed it, past the canvas edge, width x height read back as {old})")

JS = r'''(function(){var r={},uil=app.userInteractionLevel;app.userInteractionLevel=UserInteractionLevel.DONTDISPLAYALERTS;
var f=File(%(lib)s),d=null,seen={};
for(var i=0;i<app.documents.length;i++){if(app.documents[i].fullName.fsName==f.fsName){app.userInteractionLevel=uil;return '{"_err":"library already open in a document this script did not open"}';}}
try{d=app.open(f);var L=d.layers.add(),R=d.artboards[0].artboardRect;
 for(var i=0;i<d.symbols.length;i++){var n=d.symbols[i].name;seen[n]=(seen[n]||0)+1;var k=seen[n]>1?n+'#'+seen[n]:n;
  try{var si=L.symbolItems.add(d.symbols[i]),w0=si.width,h0=si.height;si.position=[R[0],R[1]];
   r[k]=[w0,h0,si.width,si.height];si.remove();}catch(e){r[k]=String(e);}}
}catch(e){r._err=String(e);}
try{if(d)d.close(SaveOptions.DONOTSAVECHANGES);}catch(e){r._close=String(e);}
app.userInteractionLevel=uil;
var s=[];for(var q in r)s.push('"'+q.replace(/\\/g,'\\\\').replace(/"/g,'\\"')+'":'+(typeof r[q]=='string'?'"'+r[q].replace(/"/g,"'")+'"':'['+r[q].join(',')+']'));
return '{'+s.join(',')+'}';})();'''


def libraries(items):
    libs = {}
    for it in items:
        if "symbol_size_pt" in (it.get("extra") or {}):
            libs.setdefault(it["invoke"]["file"], []).append(it)
    return libs


def probe():
    from aicom import js, js_watch
    items = json.loads(HARVEST.read_text("utf-8"))["items"]
    ck = json.loads(CKPT.read_text("utf-8")) if CKPT.exists() else {}
    for lib, its in libraries(items).items():
        if lib in ck and "_err" not in ck[lib]:
            continue
        t0 = time.time()
        r, e, seen = js_watch(JS % {"lib": json.dumps(lib)}, 120 + 3 * len(its), key="escape")
        ck[lib] = json.loads(r) if r else {"_err": e or "no result"}
        if seen:
            ck[lib]["_dialogs"] = seen
        CKPT.write_text(json.dumps(ck, indent=1, ensure_ascii=False), "utf-8")
        print(f"{Path(lib).name}: {len(its)} items {time.time() - t0:.0f}s {ck[lib].get('_err', '')}", flush=True)
        js("app.documents.length", 60)  # canary: the channel still takes scripts


def apply():
    ck = json.loads(CKPT.read_text("utf-8"))
    doc = json.loads(HARVEST.read_text("utf-8"))
    fix = {}
    for lib, its in libraries(doc["items"]).items():
        got = ck.get(lib) or {}
        for it in its:
            name = it["name"] + (f"#{it['extra']['duplicate_name_index']}" if "duplicate_name_index" in it["extra"] else "")
            v = got.get(name)
            if not isinstance(v, list):
                print("not probed:", it["id"], v if v is not None else got.get("_err"))
                continue
            old = it["extra"]["symbol_size_pt"]
            if old[0] is not None and (abs(v[0] - old[0]) > TOL or abs(v[1] - old[1]) > TOL):
                # the as-placed read must reproduce the harvested size, else this is not the same measurement (3D
                # symbols: bounds not computed yet, -32766, or a different value until the 3D art is drawn)
                print("kept (as-placed read does not reproduce the harvest):", it["id"], old, v)
                continue
            if old[0] is None or abs(v[2] - old[0]) > TOL or abs(v[3] - old[1]) > TOL:
                fix[it["id"]] = {"old": old, "new": [v[2], v[3]]}
                it["extra"]["symbol_size_pt"] = [v[2], v[3]]
                it["evidence"] = it.get("evidence", "") + NOTE.format(old=f"{old[0]:.1f} x {old[1]:.1f} pt" if old[0] else old)
    tmp = HARVEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", "utf-8")
    tmp.replace(HARVEST)
    byid = {it["id"]: it for it in doc["items"] if it["id"] in fix}
    for bf in sorted((ROOT / "work" / "batches").glob("ai_preset_*.json")):
        b = json.loads(bf.read_text("utf-8"))
        hit = [i for i, it in enumerate(b["items"]) if it["id"] in byid]
        for i in hit:
            b["items"][i] = byid[b["items"][i]["id"]]
        if hit:
            bf.write_text(json.dumps(b, indent=1, ensure_ascii=False), "utf-8")
    (ROOT / "work" / "ai" / "symbol_bounds_fixed.json").write_text(json.dumps(fix, indent=1, ensure_ascii=False), "utf-8")
    print(f"{len(fix)} items corrected")
    return fix


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    apply() if ap.parse_args().apply else probe()
