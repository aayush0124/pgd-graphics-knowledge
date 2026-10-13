"""PGD stage "presets": build harvest/ps/ps_preset.json from Photoshop 2026's shipped preset files.

    python harvest_presets.py live     read the app's presetManager names (read-only) -> work/ps/preset_manager_live.json
    python harvest_presets.py build    parse every shipped preset file -> harvest/ps/ps_preset.json
    python harvest_presets.py verify   apply file-based adjustment presets on a scratch document (checkpointed)

Entry names come from parsing the files (tools/ps/presetfiles.py); the live presetManager lists are a cross-check.
"""
import json, re, struct, sys, time
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).parent))
import presetfiles as pf  # noqa: E402

I = pf.INSTALL
OUT = (PGD / "harvest/ps/ps_preset.json")
WORK = (PGD / "work/ps")
LIVE = WORK / "preset_manager_live.json"
VERIFY = WORK / "preset_verify.json"

LIB_CAT = {".abr": "Brush", ".pat": "Pattern", ".asl": "Layer style", ".csh": "Custom shape", ".shc": "Contour",
           ".grd": "Gradient", ".tpl": "Tool preset", ".atn": "Action"}
LIVE_CLS = {".abr": "brush", ".pat": "'PttR'", ".asl": "styleClass", ".csh": "customShape", ".shc": "shapeCurveType",
            ".grd": "gradientClassEvent", ".tpl": "toolPreset", ".aco": "color"}
SINGLE = {  # folder under Presets -> (category, extensions)
    "3DLUTs": ("3D LUT", None), "Black and White": ("Black & White preset", {".blw"}),
    "Channel Mixer": ("Channel Mixer preset", {".cha"}), "Curves": ("Curves preset", {".acv"}),
    "Deco": ("Deco script", {".jsx"}), "Duotones": ("Duotone preset", {".ado"}),
    "Exposure": ("Exposure preset", {".eap"}), "Guides": ("Guide layout", {".gds"}),
    "HDR Toning": ("HDR Toning preset", {".hdt"}), "Hue and Saturation": ("Hue/Saturation preset", {".ahu"}),
    "Image Size": ("Image Size preset", {".imz"}), "Levels": ("Levels preset", {".alv"}),
    "Optimized Colors": ("Optimized color table", {".act"}),
    "Optimized Output Settings": ("Optimized output settings", {".iros"}),
    "Optimized Settings": ("Save for Web optimize settings", {".irs"}), "Scripts": ("Script", {".jsx"}),
    "Video": ("Video render preset", {".epr"}), "Widgets": ("3D widget", {".dae"}),
}
ADJ_EVENT = {".acv": "curves", ".alv": "levels", ".ahu": "hueSaturation", ".blw": "blackAndWhite",
             ".cha": "channelMixer", ".eap": "exposure"}


def rel(p):
    return str(Path(p).relative_to(I)).replace("\\", "/")


def app_version():
    f = WORK / "app_version.txt"
    return f.read_text().strip() if f.exists() else "27.4.0"


def live_names():
    if not LIVE.exists():
        return {}
    return {x["cls"]: set(x["names"]) for x in json.loads(LIVE.read_text(encoding="utf-8"))}


def read_live():
    import psdrv
    js = '''var ref=new ActionReference();ref.putProperty(C2T("Prpr"),S2T("presetManager"));
ref.putEnumerated(C2T("capp"),C2T("Ordn"),C2T("Trgt"));var d=executeActionGet(ref).getList(S2T("presetManager"));
var o=[];for(var i=0;i<d.count;i++){var x=d.getObjectValue(i);var nm=[];var l=x.getList(C2T("Nm  "));
for(var j=0;j<l.count;j++)nm.push(l.getString(j));o.push({cls:tid2s(d.getObjectType(i)),n:nm.length,names:nm});}J(o)'''
    o = json.loads(psdrv.js(js, timeout=120, tag="presetManager"))
    LIVE.write_text(json.dumps(o, indent=1, ensure_ascii=False), encoding="utf-8")
    (WORK / "app_version.txt").write_text(psdrv.js("app.version"))
    print({x["cls"]: x["n"] for x in o})


def entry_extra(e):
    return {k: v for k, v in e.items() if k not in ("name",) and v not in (None, [], {})}


def library_items(path, live):
    """One item per entry of a brush / pattern / style / shape / contour / gradient / tool-preset / action file."""
    ext = path.suffix.lower()
    ents, meta = pf.parse_file(path)
    cat, items, seen = LIB_CAT[ext], [], {}
    lv = live.get(LIVE_CLS.get(ext, ""), set())
    is_default = path.parent.name == "Required" and path.name.startswith("Default ")
    for e in ents:
        nm = e["name"]
        seen[nm] = seen.get(nm, 0) + 1
        iid = f"{rel(path)}#{nm}" + (f" ({seen[nm]})" if seen[nm] > 1 else "")
        x = entry_extra(e)
        x["library"] = rel(path)
        if seen[nm] > 1:
            x["duplicate_name_index"] = seen[nm]
        sub = (e.get("set") if ext == ".atn" else e.get("group")) or ""
        it = {"name": nm, "id": iid, "path": rel(path) + (f"/{sub}" if sub else ""), "category": cat,
              "invoke": {"file": str(path).replace("\\", "/")}}
        ev = f"file parse of {path.name} (tools/ps/presetfiles.py {pf.PARSERS[ext].__name__})"
        if e.get("group"):
            ev += "; group from the file's 8BIMphry preset hierarchy"
        if lv:
            x["in_live_preset_list"] = nm in lv
            if nm in lv:
                ev += "; name also present in the app's live presetManager list"
        if is_default:
            x["default_library"] = True
        if ext == ".atn":
            it["requires"] = "action set loaded into the Actions panel (load the .atn file)"
        if e.get("steps_error"):
            it["error"] = e["steps_error"]
        it["evidence"] = ev
        it["extra"] = x
        items.append(it)
    return items, meta


def swatch_item(path, live):
    ext = path.suffix.lower()
    ents, meta = pf.parse_file(path)
    if ext == ".acb":
        name = meta.get("title") or path.stem
        cat = "Color book"
    else:
        name = path.stem
        cat = "Photo Filter colors" if path.name == "Default Filter Colors.aco" else "Swatch library"
    named = [e for e in ents if e.get("name")]
    x = {"count": len(ents), "library": rel(path)}
    if named:
        x["entries"] = [e["name"] for e in ents]
        groups = sorted({e.get("group") for e in ents if e.get("group")})
        if groups:
            x["groups"] = {g: [e["name"] for e in ents if e.get("group") == g] for g in groups}
    if ext == ".aco":
        x["entry_colors"] = [e["color"] for e in ents]
    else:
        x["entry_codes"] = [e["code"] for e in ents]
        x.update({k: v for k, v in meta.items() if k in ("book_id", "prefix", "postfix", "page_size", "color_space")
                  and v not in ("", None)})
    ev = f"file parse of {path.name} (tools/ps/presetfiles.py {pf.PARSERS[ext].__name__})"
    if not named:
        ev += "; version-1 swatch file: colors only, the file holds no swatch names"
    if path.name == "Default Swatches.aco" and live.get("color"):
        x["live_swatches_match"] = sum(e["name"] in live["color"] for e in ents)
        ev += f"; {x['live_swatches_match']}/{len(ents)} names also in the app's live Swatches list"
    return {"name": name, "id": f"{rel(path)}#{name}", "path": rel(path), "category": cat,
            "invoke": {"file": str(path).replace("\\", "/")}, "evidence": ev, "extra": x}


def script_name(p):
    t = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"<name>(.*?)</name>", t)
    return (pf.zlabel(m.group(1)).replace("...", "").strip(), "the script's <name> header") if m else (p.stem, "file name")


def epr_info(p):
    t = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"<FolderDisplayPath>(.*?)</FolderDisplayPath>", t)
    return {"folder_display_path": m.group(1)} if m else {}


def sky_names(b):
    return pf.zstrings_utf16(b, "$$$/Presets/Skies/")


def single_items():
    items = []
    for folder, (cat, exts) in SINGLE.items():
        base = I / "Presets" / folder
        for p in sorted(base.rglob("*")):
            if not p.is_file() or (exts and p.suffix.lower() not in exts):
                continue
            if folder == "Scripts" and p.parent != base:
                continue  # Event Scripts Only / Stack Scripts Only are helpers, not menu entries
            if folder == "Deco" and (p.parent != base or p.name.startswith("_")):
                continue  # _Deco Menu.jsx / _Deco Settings.jsx are the framework, subfolders hold assets
            name, ev, x = p.stem, "file name (the dialog lists presets by file name)", {}
            if folder == "Scripts":
                name, src = script_name(p)
                ev = f"name from {src}"
            if folder == "Image Size":
                m = re.match(r"(g\d+)_(.*)", p.stem)
                if m:
                    name, x["list_group"] = m.group(2), m.group(1)
                    ev = "file name without its g<n>_ list-group prefix"
            if folder == "Video":
                x.update(epr_info(p))
            if folder == "Duotones" or folder == "Video":
                x["folder"] = rel(p.parent)
            ext = p.suffix.lower()
            if ext in (".acv", ".alv", ".ahu"):
                try:
                    _, meta = pf.parse_file(p)
                    x.update(meta)
                    ev += f"; values parsed from the file (presetfiles.{pf.PARSERS[ext].__name__})"
                except Exception as e:  # noqa: BLE001
                    x["parse_error"] = str(e)
            it = {"name": name, "id": f"{rel(p)}#{name}", "path": rel(p.parent), "category": cat,
                  "invoke": {"file": str(p).replace("\\", "/")}, "evidence": ev}
            if ext in ADJ_EVENT:
                x["adjustment_event"] = ADJ_EVENT[ext]
            if x:
                it["extra"] = x
            items.append(it)
    return items


def doc_size_items():
    p = I / "Required/Default New Doc Sizes.json"
    d = json.loads(p.read_text(encoding="utf-8-sig"))
    items, seen = [], {}
    for sec in d.get("sections", []):
        for pr in sec.get("presets", []):
            nm = pf.zlabel(pr.get("name", ""))
            if not nm or nm == "separator" or set(pr) <= {"name"}:
                continue  # list separators, not presets
            x = {k: (pf.zlabel(v) if isinstance(v, str) else v) for k, v in pr.items() if k != "name"}
            x["section"] = sec.get("section")
            key = f"{sec.get('section')}/{nm}"
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                x["duplicate_name_index"] = seen[key]
                key += f" ({seen[key]})"
            items.append({"name": nm, "id": f"{rel(p)}#{key}", "path": f"{rel(p)}/{sec.get('section')}",
                          "category": "Document preset", "invoke": {"file": str(p).replace("\\", "/")},
                          "evidence": "parsed from Required/Default New Doc Sizes.json (New Document dialog presets)",
                          "extra": x})
    return items


def build():
    live = live_names()
    items, metas, errors = [], {}, []
    libs = sorted(I.glob("Required/Default *")) + sorted(I.glob("Required/Legacy *")) + \
        sorted(p for p in (I / "Presets").rglob("*") if p.suffix.lower() in LIB_CAT)
    for p in libs:
        ext = p.suffix.lower()
        try:
            if ext in LIB_CAT:
                its, meta = library_items(p, live)
                items += its
                metas[rel(p)] = {k: v for k, v in meta.items() if k not in ("curves",)}
            elif ext in (".aco",):
                items.append(swatch_item(p, live))
        except Exception as e:  # noqa: BLE001
            errors.append(rel(p))
            items.append({"name": p.stem, "id": f"{rel(p)}#*", "path": rel(p), "category": LIB_CAT.get(ext, ext),
                          "invoke": {"file": str(p).replace("\\", "/")}, "error": f"file not parsed: {e}"})
    for p in sorted((I / "Presets/Color Swatches").glob("*.aco")) + sorted((I / "Presets/Color Books").glob("*.acb")):
        try:
            items.append(swatch_item(p, live))
        except Exception as e:  # noqa: BLE001
            items.append({"name": p.stem, "id": f"{rel(p)}#{p.stem}", "path": rel(p), "category": "Swatch library",
                          "invoke": {"file": str(p).replace("\\", "/")}, "error": f"file not parsed: {e}"})
    items += single_items()
    items += doc_size_items()
    sky = I / "Required/Sky_Presets/DefaultSkies.sky"
    names = sky_names(sky.read_bytes())
    for i, n in enumerate(names):
        items.append({"name": pf.zlabel(n), "id": f"{rel(sky)}#{pf.zlabel(n)}", "path": rel(sky),
                      "category": "Sky (Sky Replacement)", "invoke": {"file": str(sky).replace("\\", "/")},
                      "evidence": "name = UTF-16 ZString '$$$/Presets/Skies/...' read from DefaultSkies.sky",
                      "extra": {"zstring": n, "library_groups": [pf.zlabel(g) for g in
                                pf.zstrings_utf16(sky.read_bytes(), "$$$/Presets/Groups/")]}})
    ver = verify_results()
    for it in items:
        v = ver.get(it["id"])
        if v:
            it.setdefault("extra", {})["live_apply"] = v
            if v.get("ok"):
                it["invoke"]["ps_event"] = v["event"]
                it["evidence"] += f"; applied on a scratch document with {v['event']} + using=<file> (read-back ok)"
            else:
                it["error"] = f"live apply failed: {v.get('error')}"
    doc = {"app": "PS", "kind": "ps_preset", "app_version": app_version(),
           "source": "every preset file Photoshop 2026 ships (Required/Default*, Required/Legacy*, Presets/**, "
                     "Default New Doc Sizes.json, Sky_Presets) parsed by tools/ps/presetfiles.py; names cross-checked "
                     "with the live presetManager (tools/ps/harvest_presets.py)",
           "items": items}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    (WORK / "preset_file_meta.json").write_text(json.dumps(metas, indent=1, ensure_ascii=False), encoding="utf-8")
    cats = {}
    for it in items:
        cats[it["category"]] = cats.get(it["category"], 0) + 1
    print(len(items), "items", cats, "unparsed:", errors)


APPLY_JS = r'''(function(){
var doc = app.activeDocument, f = new File(decodeURIComponent("%(path)s"));
if (!f.exists) return J({ok:false, error:"file missing"});
var d = new ActionDescriptor();
d.putEnumerated(S2T("presetKind"), S2T("presetKindType"), S2T("presetKindUserDefined"));
d.putPath(S2T("using"), f);
var hs = doc.activeHistoryState, h0 = doc.histogram, r, err = null;
try { r = executeAction(S2T("%(event)s"), d, DialogModes.NO); } catch (e) { err = String(e); }
var h1 = doc.histogram, diff = 0;
for (var i = 0; i < 256; i++) diff += Math.abs(h0[i] - h1[i]);
doc.activeHistoryState = hs;
if (err) return J({ok:false, error:err});
var o = d2o(r), keys = []; for (var k in o) keys.push(k);
return J({ok: diff > 0, event:"%(event)s", readback_keys:keys, histogram_change:diff, readback:o});
})()'''


def verify():
    """Apply every file-based adjustment preset with <event> + using=<file> on a scratch copy of the test photo,
    read the descriptor back and compare the composite histogram; undo through history. Checkpointed."""
    import urllib.parse
    import psdrv
    done = verify_results()
    names = json.loads(psdrv.js("var a=[];for(var i=0;i<app.documents.length;i++)a.push(app.documents[i].name);J(a)"))
    assert not names, f"documents open that are not ours: {names}"
    test = urllib.parse.quote((PGD / "media/test_photo.png").as_posix())
    psdrv.js(f'var d=openTest("{test}"); d.resizeImage(UnitValue(480,"px"),UnitValue(270,"px")); d.name', tag="open")
    try:
        for it in json.loads(OUT.read_text(encoding="utf-8"))["items"]:
            ev = (it.get("extra") or {}).get("adjustment_event")
            if not ev or it["id"] in done:
                continue
            path = it["invoke"]["file"]
            try:
                r = json.loads(psdrv.js(APPLY_JS % {"path": urllib.parse.quote(path), "event": ev}, timeout=60,
                                        tag="apply " + it["name"]))
            except psdrv.PSError as e:
                r = {"ok": False, "error": str(e)[:300]}
            rb = r.pop("readback", None)
            if rb and ev == "curves":
                r["readback_sample"] = str(rb.get("adjustment"))[:400]
            r["event"] = ev
            done[it["id"]] = r
            VERIFY.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")
            print(it["name"], r.get("ok"), r.get("histogram_change"), r.get("error", "")[:120])
    finally:
        psdrv.js('closeNoSave("test_photo.png"); app.documents.length', tag="close")


def verify_results():
    return json.loads(VERIFY.read_text(encoding="utf-8")) if VERIFY.exists() else {}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    {"live": read_live, "build": build, "verify": verify}[cmd]()
