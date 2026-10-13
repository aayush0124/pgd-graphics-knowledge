"""PGD / Illustrator: build harvest/ai/ai_effect.json from the live Effect menu + install files + probes.

    python ai_effects.py names      menu tree (work/ai/menu_Effect.json, from menu_walk.py with a doc + selected path
                                    open) + Keyboard Shortcuts .kys ids + Photoshop-filter PiPLs -> first harvest file
    python ai_effects.py merge      fold work/ai/probe_ckpt.json (probe_effects.py) into the harvest file

Item id = the executeMenuCommand string when one was found (kys) and confirmed by a probe, else the menu path.
"""
import json, re, sys
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).resolve().parent))
WORK = (PGD / "work/ai")
OUT = (PGD / "harvest/ai/ai_effect.json")
KYS = Path(r"C:/Program Files/Adobe/Adobe Illustrator 2026/Presets/en_US/Keyboard Shortcuts/Illustrator Defaults.kys")
SECTIONS = {"Illustrator Effects", "Photoshop Effects"}  # disabled header rows in the menu, not commands


# ids NOT in the .kys file (or whose .kys candidate failed with 'BKey'), each confirmed by find_menu_ids.py (the
# expected dialog opened) or confirm_ids.py (the stored live effect equals the WM_COMMAND probe of that menu item);
# results in work/ai/menu_id_tests.json. The kys candidates 'Live DropShadow2' / 'Live Round3' answer 'BKey'.
CONFIRMED = {"Stylize/Drop Shadow": "Live Adobe Drop Shadow", "Stylize/Round Corners": "Live Adobe Round Corners",
             "3D and Materials/Extrude & Bevel": "Live Adobe Geometry3D Extrude",
             "3D and Materials/Revolve": "Live Adobe Geometry3D Revolve",
             "3D and Materials/Inflate": "Live Adobe Geometry3D Inflate",
             "3D and Materials/Rotate": "Live Adobe Geometry3D Rotate",
             "3D and Materials/Materials": "Live Adobe Geometry3D Materials",
             "Crop Marks": "Live Trim Marks", "SVG Filters/Apply SVG Filter": "Live SVG Filters",
             "SVG Filters/Import SVG Filter": "SVG Filter Import"}


def kys_ids():
    t = KYS.read_text(encoding="latin-1")
    menus = t[:t.index("\n/Tools {")]
    # ids are written with '\ ' for a space: 'Live\ Pathfinder\ Add'
    return [re.sub(r"\\(.)", r"\1", m) for m in re.findall(r"^\t/(.+?) \{$", menus, re.M)]


def flatten(tree, trail=(), section=None):
    for n in tree:
        if "name" not in n:
            continue
        if n["name"] in SECTIONS and not n.get("children"):
            section = n["name"]
            continue
        nm = n["name"][:-3] if n["name"].endswith("...") else n["name"]
        if n.get("children"):
            yield from flatten(n["children"], trail + (nm,), section)
        else:
            yield n, nm, trail, section


def candidates(nm, trail, section, pipl):
    """executeMenuCommand strings that the kys file holds for this menu item (matched by name, verified later)."""
    top = trail[0] if trail else ""
    if section == "Photoshop Effects" or nm == "Effect Gallery":
        if nm == "Gaussian Blur":
            return ["Live Adobe PSL Gaussian Blur"]
        code = next((p["event_id"] for p in pipl if p["name"].rstrip(".").replace("Conte", "Cont\u00e9") ==
                     nm.replace("Effect Gallery", "Filter Gallery")), None)
        return [f"Live PSAdapter_plugin_{code}"] if code else []
    if "/".join(trail + (nm,)) in CONFIRMED:
        return [CONFIRMED["/".join(trail + (nm,))]]
    fixed = {"Apply Last Effect": "Adobe Apply Last Effect", "Last Effect": "Adobe Last Effect",
             "Document Raster Effects Settings": "Live Rasterize Effect Setting",
             "Extrude & Bevel (Classic)": "Live 3DExtrude", "Revolve (Classic)": "Live 3DRevolve",
             "Rotate (Classic)": "Live 3DRotate", "Tweak": "Live Scribble and Tweak", "Scribble": "Live Scribble Fill",
             "Rasterize": "Live Rasterize"}
    if nm in fixed and top != "Warp":
        return [fixed[nm]]
    if top == "Pathfinder":
        return [f"Live Pathfinder {nm}"]
    if top == "Warp":
        return [f"Live Deform {nm}"]
    if top == "3D and Materials":
        return []
    return [f"Live {nm}"]


def names():
    tree = json.loads((WORK / "menu_Effect.json").read_text(encoding="utf-8"))
    ids = set(kys_ids())
    pipl = json.loads((WORK / "pipl_filters.json").read_text(encoding="utf-8"))
    items = []
    for n, nm, trail, section in flatten(tree):
        path = "/".join(("Effect",) + trail + (nm,))
        cands = [c for c in candidates(nm, trail, section, pipl) if c in ids or c in CONFIRMED.values()]
        it = {"name": nm, "id": path, "path": path,
              "category": "/".join(filter(None, (section, trail[0] if trail else None))) or "Effect"}
        if cands:
            it["id"] = cands[0]
            it["invoke"] = {"ai_menu": cands[0]}
        if n.get("shortcut"):
            it["shortcut"] = n["shortcut"]
        if trail[:1] == ("SVG Filters",) and nm not in ("Apply SVG Filter", "Import SVG Filter"):
            it["requires"] = "path or group selected; the filter must be defined in the document"
        conf = cands and cands[0] in CONFIRMED.values()
        it["evidence"] = ("menu walk (HMENU of the live Effect menu, doc open, path selected)" +
                          ("; ai_menu id confirmed by executing candidates taken from the effect's plug-in strings "
                           "(work/ai/menu_id_tests.json)" if conf else
                           "; ai_menu id from Illustrator Defaults.kys by name" if cands else
                           "; no executeMenuCommand id: per-document menu item, applied by applyEffect"))
        it["extra"] = {"menu_label": n["label"].split("\t")[0], "menu_cmd_id": n["cmd_id"], "section": section}
        items.append(it)
    doc = {"app": "AI", "kind": "ai_effect", "app_version": app_version(),
           "source": "Effect menu read live from Illustrator (menu_walk.py); ai_menu ids from Illustrator Defaults.kys, "
                     "Photoshop-filter PiPLs (pipl.py) and executed candidates (find_menu_ids.py / confirm_ids.py); "
                     "LiveEffect names + params from uncompressed .ai saves after each menu command (probe_effects.py); "
                     "applyEffect round trip (verify_live.py) and render check (render_check.py); "
                     "tools in tools/ai",
           "items": items}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    print(len(items), "items,", sum("invoke" in i for i in items), "with ai_menu ->", OUT)


def merge():
    """fold probe results (work/ai/probe_ckpt.json + the saved probe files) into the harvest file."""
    from probe_effects import live_blocks, parse_block, text
    doc = json.loads(OUT.read_text(encoding="utf-8"))
    ck = json.loads((WORK / "probe_ckpt.json").read_text(encoding="utf-8"))
    base = set(live_blocks(text(WORK / "probe_baseline.ai")))
    pipl = json.loads((WORK / "pipl_filters.json").read_text(encoding="utf-8"))
    vf = WORK / "verify_live.json"
    verify = json.loads(vf.read_text(encoding="utf-8")) if vf.exists() else {}
    rf = WORK / "render_check.json"
    render = json.loads(rf.read_text(encoding="utf-8")) if rf.exists() else {}
    for it in doc["items"]:
        for k in ("params", "error"):
            it.pop(k, None)
        rec = ck.get(it["path"])
        ev = [it["evidence"].split("; probe:")[0]]
        if it["name"] == "Document Raster Effects Settings":
            raster_settings(it)
            ev = [it["evidence"]]
        if rec is None:
            if it["name"] in ("Apply Last Effect", "Last Effect"):
                it["requires"] = "an effect applied earlier in the session"
                it["error"] = "not probed: repeats / reopens the last effect, has no parameters of its own"
            elif it["name"] == "Import SVG Filter":
                it["requires"] = "an SVG file holding <filter> definitions (the command opens 'Select an SVG file')"
            else:
                it["error"] = "not probed yet"
            continue
        if rec.get("crash"):
            it["error"] = "probe crashed: " + rec["crash"][:300]
            continue
        effects = []
        if rec.get("file") and Path(rec["file"]).exists():
            effects = [parse_block(b) for b in live_blocks(text(rec["file"])) if b not in base]
        dlg = [d for d in rec.get("dialogs") or [] if d != "Adobe Illustrator"]
        ev.append(f"probe: invoked via {rec.get('via')} on a selected 300x200 filled+stroked rectangle; dialogs "
                  f"{rec.get('dialogs') or []} answered with Enter (OK)")
        if rec.get("error"):
            it["error"] = "invoke error: " + str(rec["error"])[:300]
        if not effects and it["name"] == "Document Raster Effects Settings":
            it["evidence"] = "; ".join(ev)  # a document setting, not a live effect: params come from the DOM
            continue
        if not effects:
            it.setdefault("error", "no live effect stored on the probe art after the invoke")
            it["evidence"] = "; ".join(ev)
            continue
        e = effects[0]
        it["invoke"] = dict(it.get("invoke") or {}, ai_live_effect=e["live_effect"])
        it["params"] = [to_param(p) for p in e["params"]]
        x = it.setdefault("extra", {})
        ps = [p for p in e["params"] if p["ai_type"] == "Binary" and p["key"] == "data"]
        if ps:  # Photoshop effect: its parameters live in a binary descriptor, decoded into params of their own
            menu_names = {(x.get("invoke") or {}).get("ai_menu", "").replace("Live PSAdapter_plugin_", ""): x["name"]
                          for x in doc["items"] if "PSAdapter_plugin_" in (x.get("invoke") or {}).get("ai_menu", "")}
            it["params"] = [q for q in it["params"] if q["key"] != "data"] + ps_params(ps[0], it, pipl, menu_names)
            ev.append("Photoshop-effect parameters decoded from the stored binary descriptor (psdata.py); labels "
                      "and enum values from the filter's PiPL terminology resource")
        if it["path"].startswith("Effect/SVG Filters/") and it["name"] not in ("Apply SVG Filter", "Import SVG Filter"):
            stored = next((p.get("value") for p in e["params"] if p["key"] == "SVGFilterUIDName"), None)
            if stored != it["name"]:
                it["error"] = f"stored SVGFilterUIDName {stored!r} != menu item name"
            it["requires"] = "the SVG filter must be defined in the document (new-document profiles ship this set)"
        if it["name"] == "Effect Gallery":
            it["invoke"].pop("ai_live_effect")  # opens on the gallery filter used last: no fixed live effect
            it["params"] = [q for q in it["params"] if q["key"] == "GEfk"]  # the rest belong to that one filter
            x["note"] = (f"the dialog opened on '{e.get('title')}' (the gallery filter used last) and applied "
                         f"LiveEffect '{e['live_effect']}'; each gallery filter is its own item under Effect")
        if it["path"].startswith("Effect/Pathfinder/"):
            it["requires"] = ("group, layer or type object (on a single path Illustrator alerts: 'Pathfinder effects "
                              "should usually be applied to groups, layers or type objects.')")
        x.update(live_effect_title=e.get("title"), plugin_file=e.get("plugin_file"), dialog_titles=rec.get("dialogs"))
        if "fill_or_stroke" in e:
            x["fill_or_stroke"] = e["fill_or_stroke"]
        if len(effects) > 1:
            x["more_live_effects"] = [f["live_effect"] for f in effects[1:]]
        ev.append(f"saved uncompressed .ai, live-effect dictionary parsed: LiveEffect '{e['live_effect']}' "
                  f"(title '{e.get('title')}', plug-in {e.get('plugin_file')}); param defaults = the values the "
                  "menu command's dialog applied with Enter (Illustrator reopens a dialog with the values last used, "
                  "so these are the dialog values at harvest time)")
        vr = verify.get(it["path"])
        if vr and "ai_live_effect" in it["invoke"]:
            ok = vr.get("result") == "applied" and vr.get("stored_effect") == e["live_effect"] and not vr.get("mismatch")
            x["apply_effect_check"] = {k: vr.get(k) for k in ("result", "sent", "stored_effect", "mismatch")}
            if ok:
                ev.append(f"applyEffect round trip (verify_live.py): LiveEffect XML with {vr['sent']} simple params "
                          "applied on a new rectangle, saved, every sent value read back from the file" +
                          ("; the binary descriptor (data) cannot be sent in Dict data, so a scripted apply runs "
                           "without the Photoshop parameters: their rendering is unverified" if ps else ""))
            else:
                it["invoke"].pop("ai_live_effect")
                x["live_effect_name"] = e["live_effect"]
                ev.append(f"applyEffect round trip FAILED ({vr.get('result')}; mismatch {vr.get('mismatch')}): "
                          "ai_live_effect removed from invoke")
        rc = render.get(it["path"])
        if rc and "ai_live_effect" in it["invoke"]:
            x["render_check"] = {"mean_abs_diff_vs_plain": rc.get("mean_abs_diff"), "png": rc.get("png"),
                                 "result": rc.get("result")}
            d = rc.get("mean_abs_diff")
            md = rc.get("menu_route_diff")
            x["render_check"]["menu_route_mean_abs_diff_vs_plain"] = md
            ev.append(f"render check (render_check.py): scripted applyEffect on the probe rectangle exported as PNG, "
                      f"mean abs pixel difference vs the plain rectangle = {d}" +
                      (f"; the menu-command probe file renders {md} the same way" if md is not None else ""))
            if d == 0 and md:
                it["invoke"].pop("ai_live_effect")
                x["live_effect_name"] = it["extra"].get("live_effect_name") or (verify.get(it["path"]) or {}).get(
                    "stored_effect")
                ev.append("the scripted applyEffect stores the effect but draws nothing while the menu command draws: "
                          "ai_live_effect removed from invoke (use ai_menu)")
            elif d == 0:
                ev.append("both routes draw nothing on a single rectangle: the dialog values are a no-op here")
        it["evidence"] = "; ".join(ev)
    selector_enums(doc["items"])
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    print(len(doc["items"]), "items,", sum(bool(i.get("params")) for i in doc["items"]), "with params,",
          sum(bool(i.get("error")) for i in doc["items"]), "with error")


PS_TYPES = {"long": "int", "doub": "number", "bool": "bool", "enum": "enum", "object": "object"}


def ps_params(binp, it, pipl, menu_names=None):
    from psdata import a85, decode
    code = (it.get("invoke") or {}).get("ai_menu", "").replace("Live PSAdapter_plugin_", "")
    term = {t["key"]: t for f in pipl if f["event_id"] == code for t in f["terminology"]}
    if not term:  # gallery filters share one terminology list (the Filter Gallery event)
        term = {t["key"]: t for f in pipl if f["event_id"] == "GEfc" for t in f["terminology"]}
    vals, rest = decode(a85(binp["value_raw"]))
    out = []
    for v in vals:
        t = term.get(v["key"], {})
        q = {"key": v["key"], "type": PS_TYPES[v["ps_type"]]}
        if t.get("label"):
            q["name"] = t["label"].replace("&", "")
        if "value" in v:
            q["default"] = v["value"]
        if t.get("enum"):
            # PiPL label kept as is: 'Cont^e Crayon' is also how the gallery dialog titles it ('Cont^e Crayon
            # (100%)'), while the Effect menu shows 'Conté Crayon' (audit 2026-10-04)
            q["enum"] = t["enum"]
        elif v["ps_type"] == "enum":
            q["type"] = "string"  # enumerator code known, its value list is not in the PiPL terminology
        q["extra"] = {"ps_type": v["ps_type"], "in": "binary descriptor (data)"}
        if v.get("class"):
            q["extra"]["class"] = v["class"]
            q["type"] = "color" if v["class"] == "RGBC" else "point" if v["class"] == "Pnt " else "object"
        if v["key"] == "FlRs":
            q["extra"]["note"] = "random seed: differs on every application"
        out.append(q)
    if rest:
        out.append({"key": "data_rest", "type": "object", "extra": {"hex": rest[:400],
                    "note": "remainder of the binary descriptor from the first nested descriptor on; not decoded"}})
    return out


def raster_settings(it):
    """Effect > Document Raster Effects Settings is the DOM's document.rasterEffectSettings (RasterEffectOptions)."""
    x = Path(r"C:/Program Files/Common Files/Adobe/Scripting Dictionaries CC/Illustrator 2026/omv.xml").read_text(
        encoding="utf-8")
    blk = x[x.index('<classdef name="RasterEffectOptions"'):]
    blk = blk[:blk.index("</classdef>")]
    cm = x[x.index('<classdef name="RasterizationColorModel"'):]
    cm = cm[:cm.index("</classdef>")]
    cms = [{"value": f"RasterizationColorModel.{n}", "label": n} for n, v in re.findall(
        r'<property name="(\w+)"[^>]*>\s*(?:<shortdesc>.*?</shortdesc>\s*)?<datatype>\s*<type>int</type>\s*'
        r'<value>(\d+)</value>', cm, re.S)]
    live = json.loads((WORK / "raster_settings_new_doc.json").read_text(encoding="utf-8"))
    params = []
    for m in re.finditer(r'<property name="(\w+)"[^>]*>\s*<shortdesc>(.*?)</shortdesc>\s*<datatype>(.*?)</datatype>',
                         blk, re.S):
        key, desc, dt = m.groups()
        ty = re.search(r"<type[^>]*>(\w+)</type>", dt).group(1)
        p = {"key": key, "type": "enum" if key == "colorModel" else {"number": "number", "bool": "bool"}.get(ty, "unknown"),
             "extra": {"description": " ".join(desc.split())}}
        if key in live:
            p["default"] = live[key]
        for b in ("min", "max"):
            mm = re.search(f"<{b}>([^<]+)</{b}>", dt)
            if mm:
                p[b] = float(mm.group(1))
        if key == "colorModel":
            p["enum"] = cms
        params.append(p)
    it["params"] = params
    it["invoke"] = dict(it.get("invoke") or {}, ai_dom="app.activeDocument.rasterEffectSettings.<key> = value")
    base = it["evidence"].split("; params = RasterEffectOptions")[0].split("; probe:")[0]  # merge must be idempotent
    it["evidence"] = (base + "; params = RasterEffectOptions properties from omv.xml "
                      "(types, min/max where the dictionary gives them); defaults read live from rasterEffectSettings "
                      "of a new RGB document (work/ai/raster_settings_new_doc.json)")
    af = WORK / "audit" / "audit_live.json"  # range probe by the audit: does an out-of-range value fail or clamp?
    probe = json.loads(af.read_text(encoding="utf-8")).get("raster:resolution", {}).get("probe") if af.exists() else None
    if probe:
        for p in params:
            if p["key"] == "resolution":
                p["extra"]["range_probe"] = probe
                p["extra"]["out_of_range"] = "raises an error (not clamped)"
        it["evidence"] += ("; resolution range probed live (audit_live.py 2026-10-04): 72 and 2400 accepted, 71 / 50 "
                           "and 2401 / 5000 raise 'Specified value less / greater than minimum / maximum allowed value'")


def selector_enums(items):
    """an Int key whose value differs between the menu items sharing one LiveEffect (Warp's DeformStyle, Pathfinder's
    Command ...) selects the variant: list the values those items stored, labelled with the items' names."""
    from collections import defaultdict
    groups = defaultdict(list)
    for it in items:
        le = (it.get("invoke") or {}).get("ai_live_effect") or (it.get("extra") or {}).get("live_effect_name")
        if le and it.get("params"):
            groups[le].append(it)
    for le, its in groups.items():
        if len(its) < 2:
            continue
        keys = {p["key"] for p in its[0]["params"] if p.get("extra", {}).get("ai_type") == "Int"}
        for k in keys:
            vals = defaultdict(list)
            for it in its:
                for p in it["params"]:
                    if p["key"] == k and "default" in p:
                        vals[p["default"]].append(it["name"])
            # a selector gives (almost) every item its own value; a key that merely differs (a dialog value) does not
            if not (len(vals) == len(its) or (len(its) >= 4 and len(vals) >= len(its) - 1)):
                continue
            enum = [{"value": v, "label": " / ".join(n)} for v, n in sorted(vals.items())]
            for it in its:
                for p in it["params"]:
                    if p["key"] == k:
                        p["type"], p["enum"] = "enum", enum
                        p["extra"]["enum_from"] = (f"values stored by the {len(its)} Effect-menu items that apply "
                                                   f"LiveEffect '{le}' (other values may exist)")


def to_param(p):
    q = {"key": p["key"], "type": p["type"]}
    if "value" in p:
        q["default"] = p["value"]
    x = {"ai_type": p["ai_type"]}
    if "value_raw" in p:
        x["value_raw"] = p["value_raw"]
    if p.get("entries"):
        x["entries"] = [to_param(e) for e in p["entries"]]
    q["extra"] = x
    return q


def app_version():
    p = WORK / "app_version.txt"
    if not p.exists():
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from aicom import js
        p.write_text(js("app.version", 30))
    return p.read_text().strip()


if __name__ == "__main__":
    {"names": names, "merge": merge}[sys.argv[1] if len(sys.argv) > 1 else "names"]()
