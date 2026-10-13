"""PGD / Illustrator: independent audit of harvest/ai/*.json against the live app -> work/ai/audit/audit_live.json

    python audit_live.py [stage ...]      stages: kys effects apply menus blend tools presets raster (default: all)

Every stage works in documents it creates and closes DONOTSAVECHANGES; results are checkpointed per item, so a
re-run skips what is already recorded (delete the key in audit_live.json to redo it). Samples are drawn with a fixed
seed (SEED) so a re-run checks the same items.
"""
import json, random, re, sys, time
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_effects as pe  # noqa: E402
from aicom import js, js_watch  # noqa: E402
from psdata import a85, decode  # noqa: E402

H = (PGD / "harvest/ai")
AUD = (PGD / "work/ai/audit")
OUT = AUD / "audit_live.json"
SEED = 20261004
pe.WORK = AUD  # probe files land in work/ai/audit/probes, not in the harvester's folder
pe.SHOTS = AUD / "dialogs"

KYS_EXTRA = ["ruler", "zoomin", "zoomin2", "Live PSAdapter_plugin_USMk", "Live Round3", "Live DropShadow2",
             "Live AddArrowHeads2", "DropShadow2", "ZigZag2", "Scribble3", "Roughen3", "Live Color Dialog"]


def load(kind):
    return json.loads((H / f"{kind}.json").read_text(encoding="utf-8"))["items"]


def ck():
    return json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}


def save(key, rec):
    d = ck()
    d[key] = rec
    OUT.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    print(key, "->", json.dumps(rec, ensure_ascii=False)[:400], flush=True)


def stored(rec):
    """{key: value} of the first stored live effect; Photoshop binary descriptor decoded into its own keys."""
    effs = [e for e in rec.get("effects") or [] if e["live_effect"] != "Adobe Stroke Offset"]
    if not effs:
        return None, {}
    e = effs[0]
    out = {}
    for p in e["params"]:
        if p["ai_type"] == "Binary" and p["key"] == "data":
            vals, _ = decode(a85(p["value_raw"]))
            out.update({v["key"]: v.get("value") for v in vals})
        elif "value" in p:
            out[p["key"]] = p["value"]
    return e["live_effect"], out


def same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= 1e-4 * max(1, abs(a))
    return a == b


_base = []


def BASE():
    """baseline live-effect blocks of a fresh probe document, made in THIS session (the harvester's baseline file
    came from an earlier Illustrator session and no longer subtracts the [Default] style's Stroke Offset block)."""
    if not _base:
        _base.append(pe.baseline())
    return _base[0]


# ------------------------------------------------------------------ stages
def st_kys():
    """kys /Menus ids that are in neither ai_menu nor ai_effect: what does executeMenuCommand do with them?"""
    base = BASE()
    for kid in KYS_EXTRA:
        key = "kys:" + kid
        if key in ck():
            continue
        z0 = js('var d=app.documents.add(); var r=d.views[0].zoom; d.close(SaveOptions.DONOTSAVECHANGES); r;', 60)
        rec = pe.probe({"path": "kys/" + kid, "name": kid, "invoke": {"ai_menu": kid}}, base, timeout=90)
        rec.pop("t", None)
        le, vals = stored(rec)
        save(key, {"via": rec.get("via"), "result": rec.get("result"), "error": rec.get("error"),
                   "dialogs": rec.get("dialogs"), "stored_effect": le, "stored": vals, "zoom_new_doc": z0})


def zoom_test():
    for kid in ("zoomin", "zoomin2"):
        key = "zoom:" + kid
        if key in ck():
            continue
        r = js('var d=app.documents.add(); var a=d.views[0].zoom; app.executeMenuCommand("%s"); var b=d.views[0].zoom;'
               ' d.close(SaveOptions.DONOTSAVECHANGES); a+" -> "+b;' % kid, 60)
        save(key, {"zoom": r})


def st_effects(n=12):
    items = [i for i in load("ai_effect") if (i.get("invoke") or {}).get("ai_menu")
             and i["name"] not in ("Apply Last Effect", "Last Effect", "Import SVG Filter")]
    base = BASE()
    for it in random.Random(SEED).sample(items, n):
        key = "effect:" + it["id"]
        if key in ck():
            continue
        rec = pe.probe(it, base, timeout=120)
        le, vals = stored(rec)
        hp = {p["key"]: p.get("default") for p in it.get("params") or [] if "default" in p}
        mism = {k: {"harvest": hp[k], "live": vals[k]} for k in hp if k in vals and not same(hp[k], vals[k])
                and k not in ("FlRs",)}
        save(key, {"name": it["name"], "dialogs": rec.get("dialogs"), "error": rec.get("error"),
                   "stored_effect": le, "harvest_live_effect": it["invoke"].get("ai_live_effect"),
                   "keys_live_not_harvest": sorted(set(vals) - set(hp) - {"data"}),
                   "keys_harvest_not_live": sorted(set(hp) - set(vals) - {"data_rest"}),
                   "default_mismatch": mism, "n_params": len(hp)})


APPLY_CASES = [  # (item path, key, test value): in-range value -> rendering must differ from the default rendering
    ("Effect/Distort & Transform/Roughen", "size", 30.0),
    ("Effect/Distort & Transform/Zig Zag", "ridges", 12.0),
    ("Effect/Stylize/Drop Shadow", "blur", 20.0),
    ("Effect/Path/Offset Path", "ofst", 40.0),
    ("Effect/Distort & Transform/Twist", "angle", 120.0),
    ("Effect/Blur/Gaussian Blur", "blur", 30.0),
]


def st_apply():
    from PIL import Image, ImageChops, ImageStat
    from render_check import render
    from verify_live import LETTER, value
    items = {i["path"]: i for i in load("ai_effect")}
    for path, k, v in APPLY_CASES:
        key = "apply:%s:%s" % (path, k)
        if key in ck():
            continue
        it = items[path]
        ps = [p for p in it.get("params") or [] if p.get("extra", {}).get("ai_type") in LETTER and "default" in p]
        if k not in [p["key"] for p in ps]:
            save(key, {"error": "key not in harvest params: %s" % [p["key"] for p in ps]})
            continue
        def data(over):
            out = []
            for p in ps:
                val = over.get(p["key"], value(p))
                if val is None or " " in p["key"]:
                    continue
                out.append("%s %s %s" % (LETTER[p["extra"]["ai_type"]], p["key"], val))
            return " ".join(out)
        name = it["invoke"]["ai_live_effect"]
        pngs = {}
        for tag, over in (("default", {}), ("test", {k: repr(float(v)) if isinstance(v, float) else str(v)})):
            xml = '<LiveEffect name="%s"><Dict data="%s"/></LiveEffect>' % (name, data(over))
            png = AUD / "render" / ("%s_%s_%s.png" % (re.sub(r"\W+", "_", path), k, tag))
            png.parent.mkdir(parents=True, exist_ok=True)
            r, e, seen = render(xml, png)
            pngs[tag] = (str(png), r, e)
        a, b = (Image.open(pngs[t][0]).convert("RGB") for t in ("default", "test"))
        diff = sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3
        save(key, {"live_effect": name, "renders": pngs, "mean_abs_diff_default_vs_test": round(diff, 3)})


def st_menus(n_dialog=7, n_plain=7):
    items = [i for i in load("ai_menu") if i.get("path") and not i.get("error")
             and i["path"].split("/")[0] in ("Edit", "Object", "Type", "Select", "View")]
    bad = re.compile(r"Exit|Quit|Close|Sign|Print|Save|Revert|Package|Export|Place|Open|Browse|Share|Bridge|Version|"
                     r"Generative|Mockup|Retype|Vector|Preferences|Keyboard|Workspace|Reset|Font|Spelling|Paste|"
                     r"Copy|Cut|Undo|Redo|Find|Recolor|Image Trace|Perspective|Proof|Overprint|Pixel|GPU|Trim View|"
                     r"Presentation|Full Screen|Screen Mode|New View|Edit Views|Rulers|Guides|Grid|Assign|Color Settings|"
                     r"Variables|Graph|Slice|Collect|Profile|Presets|Edit Original|Legacy|Gaps|Mode|Prompt|Mock|Pattern|Isolat")
    pool = [i for i in items if not bad.search(i["path"])]
    rnd = random.Random(SEED)
    dlg = [i for i in pool if i["name"].endswith("...")]
    plain = [i for i in pool if not i["name"].endswith("...")]
    state = ('var d=app.activeDocument; var s=d.selection; [d.pageItems.length, d.pathItems.length, d.groupItems.length,'
             ' d.compoundPathItems.length, (s ? s.length : 0), d.layers[0].pageItems[0].typename,'
             ' d.layers[0].pageItems[0].name, d.pageItems[0].locked, d.pageItems[0].hidden].join("|");')
    setup = ('var d=app.documents.add(DocumentColorSpace.RGB, 800, 600);'
             'var a=d.pathItems.rectangle(450,250,300,200); a.name="A";'
             'var b=d.pathItems.ellipse(400,350,250,250); b.name="B";'
             'var t=d.textFrames.add(); t.contents="PGD audit"; t.top=100; t.left=100; t.name="T";'
             'd.selection=null; a.selected=true; b.selected=true; d.name;')
    for it in rnd.sample(dlg, n_dialog) + rnd.sample(plain, n_plain):
        key = "menu:" + it["path"]
        if key in ck():
            continue
        name = js(setup, 60)
        before = js(state, 30)
        r, e, seen = js_watch('app.executeMenuCommand("%s"); "ok";' % it["invoke"]["ai_menu"], 60, key="escape",
                              shot_dir=str(AUD / "dialogs"))
        time.sleep(0.5)
        try:
            after = js(state, 30)
        except Exception as x:  # noqa: BLE001
            after = "state read failed: " + str(x)
        js('for (var i=app.documents.length-1;i>=0;i--) if (app.documents[i].name=="%s")'
           ' app.documents[i].close(SaveOptions.DONOTSAVECHANGES); app.documents.length;' % name, 60)
        save(key, {"id": it["id"], "label": it["name"], "match": it["extra"].get("id_match"), "result": r,
                   "error": e, "dialogs": seen, "before": before, "after": after})


def st_blend(n=4):
    for it in random.Random(SEED).sample(load("ai_blend_mode"), n):
        key = "blend:" + it["id"]
        if key in ck():
            continue
        r = js('var d=app.documents.add(); var p=d.pathItems.rectangle(300,100,200,100); var r;'
               'try { p.blendingMode = BlendModes.%s; r = String(p.blendingMode); } catch(e) { r = "ERR " + String(e); }'
               'd.close(SaveOptions.DONOTSAVECHANGES); r;' % it["id"], 60)
        save(key, {"name": it["name"], "readback": r, "ok": r == "BlendModes." + it["id"]})


def st_tools(n=4):
    pool = [i for i in load("ai_tool") if i.get("invoke")]
    for it in random.Random(SEED).sample(pool, n):
        key = "tool:" + it["id"]
        if key in ck():
            continue
        r, e, seen = js_watch('var d=app.documents.add(); var r; app.selectTool("%s");'
                              'try { r = app.getSelectedToolName(); } catch(e) { r = "ERR " + String(e); }'
                              'd.close(SaveOptions.DONOTSAVECHANGES); r;' % it["id"], 60, key="escape")
        save(key, {"name": it["name"], "readback": r, "error": e, "dialogs": seen, "ok": r == it["id"]})


LIB = r'''
var lv = app.userInteractionLevel; app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;
var d = app.open(new File(File("%(file)s").fsName)); var r = [];
try {
  r.push(d.%(coll)s.length);
  var p = d.pathItems.rectangle(500, 100, 120, 60); var msg = "applied";
  try { %(apply)s } catch (e) { msg = "ERR " + String(e); }
  r.push(msg);
} catch (e) { r.push("ERR " + String(e)); }
d.close(SaveOptions.DONOTSAVECHANGES); app.userInteractionLevel = lv;
r.join("|");'''


def st_presets():
    items = load("ai_preset")
    rnd = random.Random(SEED)
    for cat, coll, apply in (("Brush", "brushes", 'd.brushes.getByName(%s).applyTo(p);'),
                             ("Graphic Style", "graphicStyles", 'd.graphicStyles.getByName(%s).applyTo(p);'),
                             ("Symbol", "symbols", 'd.symbolItems.add(d.symbols.getByName(%s));')):
        pool = [i for i in items if i["category"] == cat and not i.get("extra", {}).get("in_every_library_file")]
        it = rnd.choice(pool)
        key = "preset:" + it["id"]
        if key in ck():
            continue
        f = it["invoke"]["file"]
        n_h = sum(1 for i in items if i["category"] == cat and i["invoke"].get("file") == f)
        r = js(LIB % {"file": f, "coll": coll, "apply": apply % json.dumps(it["name"])}, 180)
        save(key, {"name": it["name"], "library": f, "harvest_entries": n_h, "live": r,
                   "ok": r.split("|")[0] == str(n_h) and r.endswith("applied")})
    # Image Trace presets: loadFromPreset values vs harvest
    tr = [i for i in items if i["category"] == "Image Trace preset"]
    it = rnd.choice(tr)
    key = "preset:" + it["id"]
    if key not in ck():
        keys = [p["key"] for p in it["params"] if p["type"] in ("number", "int", "bool", "enum") and p["key"] != "preset"
                and "tracingColorType" not in p["key"]]
        plate = (PGD / "work/ai/presets_stage/pgd_ai_trace_plate.png")
        src = ('var lv=app.userInteractionLevel; app.userInteractionLevel=UserInteractionLevel.DONTDISPLAYALERTS;'
               'var d=app.documents.add(DocumentColorSpace.RGB, 600, 400); var pi=d.placedItems.add();'
               'pi.file=new File(File("%s").fsName); var t=pi.trace(); var o=t.tracing.tracingOptions; var r=[];'
               'try { o.loadFromPreset(%s); var ks=%s; for (var i=0;i<ks.length;i++) { try { r.push(ks[i]+"="+String(o[ks[i]])); }'
               ' catch(e) { r.push(ks[i]+"=ERR"); } } } catch(e) { r.push("ERR "+String(e)); }'
               'd.close(SaveOptions.DONOTSAVECHANGES); app.userInteractionLevel=lv; r.join("|");'
               % (plate.as_posix(), json.dumps(it["name"]), json.dumps(keys)))
        r = js(src, 240)
        live = dict(x.split("=", 1) for x in r.split("|") if "=" in x)
        hv = {p["key"]: p.get("default") for p in it["params"]}
        mism = {}
        for k2, lv in live.items():
            h = hv.get(k2)
            ok = str(h) == lv or (isinstance(h, bool) and str(h).lower() == lv) or \
                (isinstance(h, (int, float)) and re.match(r"^-?[\d.e+-]+$", lv) and same(float(h), float(lv)))
            if not ok:
                mism[k2] = {"harvest": h, "live": lv}
        save(key, {"name": it["name"], "checked": len(live), "mismatch": mism, "raw": r[:600]})
    # new document profile: getPresetSettings vs harvest
    nd = rnd.choice([i for i in items if i["category"] == "New document profile"])
    key = "preset:" + nd["id"]
    if key not in ck():
        keys = [p["key"] for p in nd.get("params") or [] if p["type"] in ("number", "int", "bool", "string", "enum")]
        r = js('var s=app.getPresetSettings(%s); var ks=%s; var r=[]; for (var i=0;i<ks.length;i++) r.push(ks[i]+"="+String(s[ks[i]])); r.join("|");'
               % (json.dumps(nd["name"]), json.dumps(keys)), 60)
        live = dict(x.split("=", 1) for x in r.split("|") if "=" in x)
        hv = {p["key"]: p.get("default") for p in nd["params"]}
        mism = {k2: {"harvest": hv.get(k2), "live": v2} for k2, v2 in live.items()
                if not (str(hv.get(k2)) == v2 or str(hv.get(k2)).lower() == v2.lower() or
                        (isinstance(hv.get(k2), (int, float)) and re.match(r"^-?[\d.]+$", v2) and same(float(hv[k2]), float(v2))))}
        save(key, {"name": nd["name"], "checked": len(live), "mismatch": mism})


def st_raster():
    key = "raster:resolution"
    if key in ck():
        return
    r = js('var d=app.documents.add(); var s=d.rasterEffectSettings; var out=["new="+s.resolution];'
           'var vs=[150, 72, 2400, 50, 71, 2401, 5000]; for (var i=0;i<vs.length;i++) {'
           ' try { s.resolution = vs[i]; d.rasterEffectSettings = s; out.push(vs[i]+"->"+d.rasterEffectSettings.resolution); }'
           ' catch(e) { out.push(vs[i]+"->ERR "+String(e)); } }'
           'd.close(SaveOptions.DONOTSAVECHANGES); out.join("|");', 60)
    save(key, {"probe": r})


STAGES = {"kys": lambda: (st_kys(), zoom_test()), "effects": st_effects, "apply": st_apply, "menus": st_menus,
          "blend": st_blend, "tools": st_tools, "presets": st_presets, "raster": st_raster}

if __name__ == "__main__":
    AUD.mkdir(parents=True, exist_ok=True)
    for s in sys.argv[1:] or list(STAGES):
        STAGES[s]()
    print("docs open:", js("app.documents.length", 30))
