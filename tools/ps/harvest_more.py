"""PGD Photoshop: ps_adjustment, ps_layer_style, ps_blend_mode builders (called from harvest_effects.main).

Static names / ids come from the menu walk and Photoshop.exe's terminology; live data from probe.py checkpoints:
probe_adjust.json (Image > Adjustments events), probe_adjlayer.json (adjustment layers made + read back),
probe_style.json (layer effects set + read back), probe_blend.json (blend modes set + read back).
"""
import json, os, re
from pathlib import Path

import harvest_effects as he
from ps_terminology import zname

PS = he.PS

# Image > Adjustments item -> event; New Adjustment Layer item -> adjustment class. Each pair was matched by display
# name against Photoshop.exe's terminology (Events / Classes zstrings); the probes confirm them live.
EVENT_ALIAS = {"Shadows/Highlights": "adaptCorrect"}           # terminology zname is "Shadow/Highlight"
CLASS_ALIAS = {"Color and vibrance": "vibrance", "Clarity and dehaze": "clarity", "Grain": "grainAdjustment",
               "Gradient Map": "gradientMapClass", "Black & White": "blackAndWhite",
               "OpenColorIO Transform": None}


def declared_type(tstr, term):
    parts = [x.lstrip("/") for x in tstr.split()]
    if not parts:
        return "unknown", None
    t, is_list = parts[0], "list" in parts[1:]
    if is_list:
        return "object", None
    m = {"integer": "int", "floatType": "number", "double": "number", "percentUnit": "number", "angleUnit": "number",
         "pixelsUnit": "number", "distanceUnit": "number", "densityUnit": "number", "unitFloat": "number",
         "boolean": "bool", "char": "string", "color": "color", "FSS": "path", "alias": "path"}
    if t in m:
        return m[t], None
    if t in (term.get("Enums") or {}):
        return "enum", he.enum_from_term(term, t)
    return "object", None


def class_params(term, cls, seen=None):
    """declared keys of a terminology class incl. inherited ones: {key: (label, decl type string)}"""
    seen = seen or set()
    if cls in seen:
        return {}
    seen.add(cls)
    v = (term.get("Classes") or {}).get(cls)
    if not isinstance(v, list):
        return {}
    d = next((x for x in v if isinstance(x, dict) and "z" not in x), {})
    out = {}
    for k, val in d.items():
        if not (isinstance(val, list) and val and isinstance(val[0], dict)):
            continue
        tstr = " ".join(x for x in val[1:] if isinstance(x, str))
        if k == "inherits":
            par = tstr.lstrip("/").split()[0] if tstr else ""
            if par and par not in ("adjustment", "contentLayer", "layer", "mode"):
                out.update(class_params(term, par, seen))
            continue
        out[k] = (zname(val[0]), tstr)
    return out


def add_members(term, p):
    """an object param whose class is in the terminology (curvesAdjustment, colorCorrection, channelMatrix ...) gets
    extra.members {key: declared type}, so a demo value for it can be typed into an Action Manager object."""
    x = p.get("extra") or {}
    cls = x.get("class") or ((x.get("declared_type") or "").lstrip("/").split() or [""])[0]
    m = {k: t for k, (_, t) in class_params(term, cls).items()} if p.get("type") == "object" and cls else {}
    if m:
        p.setdefault("extra", {})["members"] = m
    return p


def merge_params(readback, declared, term, ranges=None):
    """read-back keys first (with defaults), then declared keys that were not in the read-back (no default)."""
    params, done = [], set()
    for k, rv in (readback or {}).items():
        if k in ("presetKind",) and not declared.get(k):
            pass
        lab = declared.get(k, (None, ""))[0]
        p = he.param_from_readback(k, rv, term, lab)
        if p["type"] == "enum" and len(p.get("enum") or []) <= 1 and declared.get(k):
            t, vals = declared_type(declared[k][1], term)
            if vals:
                p["enum"] = vals
        he.apply_ranges(p, (ranges or {}).get(k))
        params.append(add_members(term, p))
        done.add(k)
    for k, (lab, tstr) in declared.items():
        if k in done:
            continue
        t, vals = declared_type(tstr, term)
        p = {"name": lab or k, "key": k, "type": t, "extra": {"declared_type": tstr, "in_readback": False}}
        if vals:
            p["enum"] = vals
        he.apply_ranges(p, (ranges or {}).get(k))
        params.append(add_members(term, p))
    return params


def build_adjustments(menu, term, write):
    evname, clsname = {}, {}
    for sec, dst in (("Events", evname), ("Classes", clsname)):
        for k, v in (term.get(sec) or {}).items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                dst.setdefault(he.fold(zname(v[0])), []).append(k)
    pa, pl = he.load("probe_adjust.json", {}), he.load("probe_adjlayer.json", {})
    luts = sorted(os.listdir(PS + "/Presets/3DLUTs")) if os.path.isdir(PS + "/Presets/3DLUTs") else []
    items = []
    for n in menu:
        img = n["path"].startswith("Image/Adjustments/")
        lay = n["path"].startswith("Layer/New Adjustment Layer/")
        if not (img or lay) or n.get("kind") != "item":
            continue
        name = he.clean(n.get("title"))
        it = {"name": name, "path": "/".join(n["path"].split("/")[:-1] + [name]),
              "category": "Image > Adjustments" if img else "Adjustment layer",
              "extra": {"menu_cmd": n.get("command"), "menu_title": n.get("title"), "menu_visible": n.get("visible"),
                        "destructive": img}}
        if n.get("shortcut"):
            it["shortcut"] = n["shortcut"]
        if img:
            ev = EVENT_ALIAS.get(name) or (evname.get(he.fold(name)) or [None])[0]
            if not ev:
                it["id"] = it["path"]
                it["error"] = ("no Action Manager event with this display name in Photoshop.exe's terminology"
                               + ("; HDR Toning is implemented by Required/HDRToning.jsx" if name == "HDR Toning" else ""))
                items.append(it)
                continue
            it["id"] = ev
            it["invoke"] = {"ps_event": ev}
            it["requires"] = "pixel layer"
            pr = pa.get(ev)
            declared = {k: v for k, v in he.term_params(term, ev).items()}
            if not pr:
                it["params"] = merge_params({}, declared, term)
                it["error"] = "not probed yet"
                it["evidence"] = "event matched by name in Photoshop.exe terminology; params declared there"
            elif pr.get("err"):
                it["params"] = merge_params({}, declared, term)
                it["error"] = "executeAction(DialogModes.NO) failed: " + pr["err"][:300]
                it["evidence"] = "event matched by name in Photoshop.exe terminology; declared params only"
            else:
                it["params"] = merge_params(pr.get("readback"), declared, term, pr.get("ranges"))
                it["evidence"] = ("executeAction(event, {}, DialogModes.NO) on a 480x270 RGB layer: keys/defaults are "
                                  "what Photoshop used with nothing specified; keys not in the read-back are declared "
                                  "in Photoshop.exe's terminology (no default); min/max from clamp probes")
        else:
            cls = CLASS_ALIAS[name] if name in CLASS_ALIAS else (clsname.get(he.fold(name)) or [None])[0]
            if not cls:
                it["id"] = "adjustmentLayer:" + name
                it["error"] = "no adjustment class with this name in Photoshop.exe's terminology (item hidden unless an OCIO document is open)" \
                    if name == "OpenColorIO Transform" else "no adjustment class found"
                if name == "OpenColorIO Transform":
                    it["extra"]["candidate_event"] = "adjustmentLayerOCIOAdjustment"
                items.append(it)
                continue
            it["id"] = "adjustmentLayer:" + cls
            it["invoke"] = {"ps_event": "make", "ps_dom": "make adjustmentLayer using {type: %s}" % cls}
            it["extra"]["adjustment_class"] = cls
            pr = pl.get(cls)
            declared = class_params(term, cls)
            rb = None
            if pr and not pr.get("err"):
                adj = pr.get("layer_adjustment") or []
                rb = (adj[0].get("v") if adj and isinstance(adj[0], dict) else None) or {}
                it["extra"]["layer_name"] = pr.get("name")
                if adj and adj[0].get("cls") and adj[0]["cls"] != cls:
                    it["extra"]["readback_class"] = adj[0]["cls"]
            it["params"] = merge_params(rb, declared, term, (pr or {}).get("ranges"))
            if not pr:
                it["error"] = "not probed yet"
                it["evidence"] = "class matched by name in Photoshop.exe terminology; keys declared there"
            elif pr.get("err"):
                it["error"] = "make adjustmentLayer failed: " + pr["err"][:300]
                it["evidence"] = "class matched by name in Photoshop.exe terminology; declared keys only"
            else:
                it["evidence"] = ("adjustment layer made with an empty settings descriptor, then the layer's "
                                  "'adjustment' descriptor read back (keys with defaults); other keys declared in "
                                  "Photoshop.exe's terminology class (no default)")
        if cls_is(it, "colorLookup") or name == "Color Lookup":
            it["extra"]["lut_files"] = luts
            it["extra"]["lut_files_source"] = "Presets/3DLUTs folder listing (the dialog's 3DLUT File menu)"
        items.append(it)
    write("ps_adjustment", items, "Image > Adjustments + Layer > New Adjustment Layer menu walk; events/classes from "
          "Photoshop.exe terminology; live read-backs (tools/ps/harvest_more.py, probe.py)")


def cls_is(it, c):
    return it.get("extra", {}).get("adjustment_class") == c or it.get("id") == c


STYLE = [("Drop Shadow", "dropShadow", "dropShadow"), ("Inner Shadow", "innerShadow", "innerShadow"),
         ("Outer Glow", "outerGlow", "outerGlow"), ("Inner Glow", "innerGlow", "innerGlow"),
         ("Bevel & Emboss", "bevelEmboss", "bevelEmboss"), ("Satin", "chromeFX", "chromeFX"),
         ("Color Overlay", "solidFill", "solidFill"), ("Gradient Overlay", "gradientFill", "gradientFill"),
         ("Pattern Overlay", "patternFill", "patternFill"), ("Stroke", "frameFX", "frameFX")]


def build_styles(menu, term, write):
    le = class_params(term, "layerEffects")
    probes = he.load("probe_style.json", {})
    run1 = he.load("probe_style_run1.json", {})  # first pass (no reset between clamp probes); used where pass 2 failed
    for k, v in run1.items():
        if (k not in probes or probes[k].get("err")) and not v.get("err"):
            probes[k] = dict(v, note="from probe pass 1 (pass 2 failed: %s)" % (probes.get(k, {}).get("err") or "missing")[:120])
    cmd = {he.clean(n.get("title")): n for n in menu if n["path"].startswith("Layer/Layer Style/")}
    items = []
    for name, key, cls in STYLE:
        if key not in le:
            raise SystemExit(f"{key} is not a layerEffects key in this Photoshop's terminology")
        n = cmd.get(name, {})
        it = {"name": name, "id": key, "path": "Layer/Layer Style/" + name, "category": "Layer Style",
              "invoke": {"ps_event": "set", "ps_dom": "set layer property layerEffects.%s (object class %s)" % (key, cls)},
              "requires": "layer that is not the locked Background",
              "extra": {"layerEffects_key": key, "descriptor_class": cls, "menu_cmd": n.get("command"),
                        "terminology_label": le[key][0]}}
        multi = key + "Multi"
        if multi in le:
            it["extra"]["multi_key"] = multi
        declared = class_params(term, cls)
        pr = probes.get(key)
        rb = dict((pr or {}).get("readback") or {})
        rng = dict((pr or {}).get("ranges") or {})
        sub = probes.get(key + "+contour+texture")
        only = set()
        if sub and not sub.get("err"):
            for k, v in (sub.get("readback") or {}).items():
                if k not in rb:
                    rb[k] = v
                    only.add(k)
            for k, v in (sub.get("ranges") or {}).items():
                rng.setdefault(k, v)
            it["extra"]["contour_texture_probe"] = {"flags_set": ["useShape", "useTexture"],
                                                    "pattern_used": sub.get("pattern_used")}
        if pr and pr.get("note"):
            it["extra"]["probe_note"] = pr["note"]
        if pr and pr.get("pattern_used"):
            it["extra"]["pattern_used_for_probe"] = pr["pattern_used"]
        it["params"] = merge_params(rb or None, declared, term, rng)
        for p in it["params"]:
            if p.get("key") in only:
                p.setdefault("extra", {})["appears_when"] = "useShape / useTexture is on (Contour / Texture panels)"
        keys = {p.get("key") for p in it["params"]}
        if keys & {"transferSpec", "mappingShape"}:
            it["extra"]["contour_preset_files"] = [f for f in ("Required/Default Contours.shc", "Presets/Contours/Contours.shc")
                                                   if os.path.exists(PS + "/" + f)]
        if "pattern" in keys:
            it["extra"]["pattern_preset_files"] = ["Required/Default Patterns.pat"] + sorted(
                "Presets/Patterns/" + f for f in os.listdir(PS + "/Presets/Patterns"))
        if not pr:
            it["error"] = "not probed yet"
            it["evidence"] = "keys declared in Photoshop.exe terminology class " + cls
        elif pr.get("err"):
            it["error"] = "set layerEffects failed: " + pr["err"][:300]
            it["evidence"] = "keys declared in Photoshop.exe terminology class " + cls
        else:
            it["evidence"] = ("effect set on a pixel layer with only {enabled: true}; the layer's layerEffects read back "
                              "gives every key Photoshop filled in (defaults); min/max = value kept after setting "
                              "1e6 / 1e6+7 and negatives (clamp seen twice); other keys declared in the terminology class")
            if pr.get("sub"):
                it["extra"]["sub_objects"] = pr["sub"]
        items.append(it)
    write("ps_layer_style", items, "layerEffects class of Photoshop.exe terminology + live set/read-back of each effect "
          "(tools/ps/harvest_more.py, probe.py)")


def build_blend(term, write):
    enum = (term.get("Enums") or {}).get("blendMode") or {}
    probes = he.load("probe_blend.json", {})
    am = probes.get("am", {})
    dom = probes.get("dom", {})          # DOM name -> AM enum read back
    rev = {}
    for d, a in dom.items():
        if isinstance(a, str) and not a.startswith("ERR"):
            rev.setdefault(a, []).append(d)
    items = []
    for k, z in enum.items():
        it = {"name": zname(z), "id": k, "category": "blend mode",
              "invoke": {"ps_event": "set", "ps_dom": ("layer.blendMode = BlendMode.%s" % rev[k][0]) if rev.get(k) else None},
              "extra": {"am_enum": k, "am_enum_type": "blendMode", "dom": rev.get(k)}}
        if it["invoke"]["ps_dom"] is None:
            del it["invoke"]["ps_dom"]
        r = am.get(k)
        if r:
            it["extra"]["on_pixel_layer"] = r.get("layer")
            it["extra"]["on_group"] = r.get("group")
            ok = [w for w in ("layer", "group") if r.get(w) == "ok"]
            it["requires"] = "group" if ok == ["group"] else ("layer or group" if ok else "tool/fill/effect only (rejected on a layer)")
            it["evidence"] = ("AM enum from Photoshop.exe terminology (blendMode); set on a pixel layer and a group with "
                              "AM 'set' mode, read back; DOM name found by setting each BlendMode on a layer and reading "
                              "the AM enum back")
        else:
            it["error"] = ("not verified live: the set/read-back probe (probe.py blend) raised 'The command \"Select\" is "
                           "not currently available' alerts on the group and Photoshop crashed once during it; validity "
                           "on layers vs tools and the DOM BlendMode name are not recorded")
            it["evidence"] = "AM enum value and English label from Photoshop.exe terminology (Enums.blendMode)"
        items.append(it)
    for d, a in dom.items():
        if isinstance(a, str) and a.startswith("ERR"):
            items.append({"name": d, "id": "dom:" + d, "category": "blend mode", "error": a[:300],
                          "evidence": "BlendMode enumeration member that a layer refused"})
    write("ps_blend_mode", items, "blendMode enum of Photoshop.exe terminology + DOM BlendMode enumeration, each set on a "
          "layer / group and read back (tools/ps/harvest_more.py, probe.py)")


def main(menu, term, ids, write):
    build_adjustments(menu, term, write)
    build_styles(menu, term, write)
    build_blend(term, write)
