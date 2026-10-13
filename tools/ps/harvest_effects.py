"""PGD Photoshop stage "effects": build harvest/ps/{ps_filter,ps_adjustment,ps_layer_style,ps_blend_mode}.json.

Sources (all read from the installed app):
  work/ps/menu_tree.json        dump_menus.py      menuBarInfo walk (names, command ids, shortcuts)
  work/ps/pipl_all.json         (this file, --pipl) JSON_PIPL resources of Required/Plug-ins/*/*.8bf
  work/ps/ps_terminology.json   ps_terminology.py   Photoshop.exe's built-in Action Manager dictionary
  work/ps/ids_4cc.json          probe.py ids        4-char code -> stringID, asked of Photoshop
  work/ps/probe_<kind>.json     probe.py <kind>     live read-backs and range probes (checkpoints)

    python harvest_effects.py --pipl     # re-extract plug-in PiPLs
    python harvest_effects.py            # (re)write all four harvest files from whatever is on disk
"""
import glob, json, re, sys, unicodedata
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).parent))
from ps_terminology import zname  # noqa: E402

PS = "C:/Program Files/Adobe/Adobe Photoshop 2026"
WORK = (PGD / "work/ps")
OUT = (PGD / "harvest/ps")
VERSION = "27.4.0"  # overwritten from work/ps/app_version.txt (read from app.version)


def load(name, default=None):
    p = WORK / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def clean(title):
    """menu title -> display name: drop & accelerators, && -> &, trailing ellipsis."""
    return re.sub(r"&(?!&)", "", title or "").replace("&&", "&").rstrip(".").strip()


def fold(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().rstrip(".").strip()


def extract_pipl():
    import pefile
    allp = []
    for f in glob.glob(PS + "/Required/Plug-ins/*/*.8bf"):
        pe = pefile.PE(f, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        for e in getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None).entries if hasattr(pe, "DIRECTORY_ENTRY_RESOURCE") else []:
            if str(e.name) != "JSON":
                continue
            for e2 in e.directory.entries:
                for e3 in e2.directory.entries:
                    d = e3.data.struct
                    j = json.loads(pe.get_data(d.OffsetToData, d.Size).decode("utf-8-sig"))
                    for p in j.get("PiPLs", []):
                        p["_file"] = Path(f).relative_to(PS).as_posix()
                        allp.append(p)
    (WORK / "pipl_all.json").write_text(json.dumps(allp, indent=1), encoding="utf-8")
    return allp


# ---------------------------------------------------------------- type mapping
RB_TYPE = {"UNITDOUBLE": "number", "DOUBLETYPE": "number", "INTEGERTYPE": "int", "LARGEINTEGERTYPE": "int",
           "BOOLEANTYPE": "bool", "ENUMERATEDTYPE": "enum", "STRINGTYPE": "string", "ALIASTYPE": "path",
           "OBJECTTYPE": "object", "LISTTYPE": "object", "CLASSTYPE": "string", "RAWTYPE": "object",
           "REFERENCETYPE": "object"}
COLOR_CLS = {"RGBColor", "CMYKColorClass", "grayscale", "HSBColorClass", "labColor", "bookColor", "'RGBC'"}
PIPL_TYPE = {"long": "int", "doub": "number", "bool": "bool", "TEXT": "string", "alis": "path", "Pth ": "path",
             "#Pxl": "number", "#Prc": "number", "#Ang": "number", "#Rlt": "number", "#Pnt": "number",
             "UntF": "number", "RGBC": "color", "Clr ": "color", "Objc": "object", "obj ": "object"}
UNIT_NAME = {"pixelsUnit": "px", "percentUnit": "%", "angleUnit": "deg", "distanceUnit": "pt", "densityUnit": "ppi",
             "pointsUnit": "pt", "millimetersUnit": "mm", "noneUnit": None}


def enum_from_term(term, etype):
    e = (term.get("Enums") or {}).get(etype)
    return [{"value": k, "label": zname(v)} for k, v in e.items()] if isinstance(e, dict) else None


def param_from_readback(key, rv, term, label=None, enums=None):
    t = rv.get("t")
    p = {"name": label or key, "key": key, "type": RB_TYPE.get(t, "unknown")}
    if t == "OBJECTTYPE" and rv.get("cls") in COLOR_CLS:
        p["type"] = "color"
    if t in ("UNITDOUBLE", "DOUBLETYPE", "INTEGERTYPE", "BOOLEANTYPE", "STRINGTYPE", "ENUMERATEDTYPE"):
        p["default"] = rv.get("v")
    elif t == "OBJECTTYPE" and p["type"] == "color":
        p["default"] = {k: v.get("v") for k, v in (rv.get("v") or {}).items() if isinstance(v, dict)}
        p["extra"] = {"class": rv.get("cls")}
    elif t == "OBJECTTYPE" and set(rv.get("v") or {}) == {"horizontal", "vertical"}:
        p["type"] = "point"
        p["default"] = {k: v.get("v") for k, v in rv["v"].items()}
        p["extra"] = {"class": rv.get("cls"), "units": {k: v.get("unit") for k, v in rv["v"].items() if v.get("unit")}}
    elif t in ("OBJECTTYPE", "LISTTYPE"):
        p["extra"] = {"class": rv.get("cls"), "value": rv.get("v")}
    if rv.get("unit") and rv["unit"] != "0":  # "0": Photoshop returned unit typeID 0 (no unit)
        p["unit"] = UNIT_NAME.get(rv["unit"], rv["unit"])
    if t == "ENUMERATEDTYPE":
        vals = (enums or {}).get(rv.get("etype")) or enum_from_term(term, rv.get("etype"))
        p["enum"] = vals or [{"value": rv.get("v"), "label": "(read-back value; full list not found)"}]
        p.setdefault("extra", {})["enum_type"] = rv.get("etype")
    return p


def apply_ranges(p, rng):
    """rng: {"1000000": v, "1000007": v, "-1000000": v, "-1000007": v} -> min/max when the app clamped both probes
    to the same value (a wrap or a pass-through is not a bound)."""
    if not rng or p["type"] not in ("number", "int"):
        return
    hi, hi2, lo, lo2 = (rng.get(k) for k in ("1000000", "1000007", "-1000000", "-1000007"))
    num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)  # noqa: E731
    if num(hi) and num(lo) and hi == lo:
        p.setdefault("extra", {})["range_note"] = "inconclusive: +1e6 and -1e6 read back the same value (set refused?)"
    else:
        if num(hi) and num(hi2) and hi == hi2 and hi != 1000000:
            p["max"] = hi
        if num(lo) and num(lo2) and lo == lo2 and lo != -1000000:
            p["min"] = lo
    if hi == 16960 and hi2 == 16967:  # 1000000 & 0xFFFF: kept as a 16-bit integer, no clamp
        p.setdefault("extra", {})["range_note"] = "no clamp on set: values are stored as 16-bit integers (1e6 read back as 16960)"
    elif hi == 1000000 and hi2 == 1000007:
        p.setdefault("extra", {})["range_note"] = "no clamp on set: 1e6 was stored as sent"
    errs = {k: v for k, v in rng.items() if isinstance(v, str)}
    p.setdefault("extra", {})["range_probe"] = rng if not errs else {k: (v[:160] if isinstance(v, str) else v)
                                                                      for k, v in rng.items()}


def term_params(term, ev):
    """declared params of a built-in event: {key: (label, declared type)}"""
    e = (term.get("Events") or {}).get(ev)
    if not isinstance(e, list):
        return {}
    d = next((x for x in e if isinstance(x, dict) and "z" not in x), {})
    out = {}
    for k, v in d.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            out[k] = (zname(v[0]), " ".join(x for x in v[1:] if isinstance(x, str)))
    return out


# ---------------------------------------------------------------- ps_filter
SKIP_EXEC = {"displace": "not executed: run headless with no displacement-map file it wedged Photoshop (COM 'server threw an "
                          "exception' after 128 s, then every command reported 'not currently available' until a restart)",
             "neuralGalleryFilters": "not executed: Neural Filters opens its own workspace and downloads/cloud models",
             "generativeDenoise": "not executed: generative (cloud) service", "generativeSharpen": "not executed: generative (cloud) service"}


def filter_static(menu, pipl, term, ids):
    piplname = {}
    for p in pipl:
        if p.get("Kind") == "Filter":
            piplname.setdefault(fold(p["Name"]), p)
    evname = {}
    for k, v in (term.get("Events") or {}).items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            evname.setdefault(fold(zname(v[0])), []).append(k)
    items = []
    for n in menu:
        if not n["path"].startswith("Filter/") or n.get("kind") != "item":
            continue
        name = clean(n.get("title"))
        if name == "Last Filter" and not n.get("visible"):
            continue  # recent-filter slots: dynamic content
        parts = n["path"].split("/")
        it = {"name": name, "path": "/".join(parts[:-1] + [name]),
              "category": parts[1] if len(parts) > 2 else "Filter",
              "extra": {"menu_cmd": n.get("command"), "menu_title": n.get("title"), "menu_visible": n.get("visible")}}
        if n.get("shortcut"):
            it["shortcut"] = n["shortcut"]
        p = piplname.get(fold(name))
        if p:
            ht = p.get("HasTerminology") or {}
            ev4 = ht.get("EventID") if ht.get("ClassID") == "Fltr" else ht.get("EventID")
            it["extra"].update({"plugin": p["_file"], "event_4cc": ev4, "pipl_category": p.get("Category"),
                                "filter_gallery": bool(p.get("LegacyFilterGalleryMenuItem"))})
            if p.get("SupportedModes"):
                it["extra"]["supported_modes"] = sorted(k for k, v in p["SupportedModes"].items() if v)
            if p.get("EnableInfo"):
                it["extra"]["enable_info"] = p["EnableInfo"]
            sid = ids.get(ev4)
            it["_ev"] = {"cc": ev4, "sid": sid, "src": "pipl"}
        else:
            cands = evname.get(fold(name), [])
            if len(cands) == 1:
                it["_ev"] = {"sid": cands[0], "src": "exe-terminology"}
            elif cands:
                it["extra"]["candidate_events"] = cands
        items.append(it)
    return items


SMART = {}


def build_filters(menu, pipl, term, ids, probes):
    SMART.update(load("probe_smart.json", {}))
    items = []
    for it in filter_static(menu, pipl, term, ids):
        ev = it.pop("_ev", None)
        name = it["name"]
        if name == "Last Filter":
            it["id"] = "lastFilter"
            it["error"] = "no event of its own: repeats the previous filter (menu command only)"
            items.append(it)
            continue
        if not ev:
            it["id"] = it["path"]
            it.setdefault("error", "no Action Manager event found for this menu item in the plug-in PiPLs or in "
                                   "Photoshop.exe's terminology; menu command ids are not accepted by app.runMenuItem")
            items.append(it)
            continue
        sid = ev.get("sid") or ("'%s'" % ev["cc"])
        it["id"] = sid
        pr = probes.get(sid) or (probes.get("'%s'" % ev["cc"]) if ev.get("cc") else None)
        enums = {}
        labels = {k: v[0] for k, v in term_params(term, sid).items()}
        if ev["src"] == "pipl":
            q4 = lambda cc: ids.get(cc) or "'%s'" % cc  # noqa: E731  (how tid2s prints a code with no stringID)
            p = next(x for x in pipl if (x.get("HasTerminology") or {}).get("EventID") == ev["cc"])
            for s in (p.get("Terminology") or {}).get("Suites", []):
                for e in s.get("Enumerations", []):
                    enums[q4(e["EnumID"])] = [{"value": q4(x["EnumKeyword"]), "label": zname({"z": x["EnumName"]})}
                                              for x in e.get("Enumerators", [])]
                for e in s.get("Events", []):
                    if e.get("EventType") == ev["cc"]:
                        for q in e.get("Parameters", []):
                            labels.setdefault(q4(q["ParamKeyword"]), zname({"z": q["ParamName"]}))
            it["extra"]["declared_params"] = len(labels)
        else:
            it["extra"]["declared_params"] = {k: v[1] for k, v in term_params(term, sid).items()}
        it["invoke"] = {"ps_event": sid}
        declared = []  # params as declared by the plug-in PiPL / exe terminology (no defaults): used when no read-back
        if ev["src"] == "pipl":
            q4 = lambda cc: ids.get(cc) or "'%s'" % cc  # noqa: E731
            p = next(x for x in pipl if (x.get("HasTerminology") or {}).get("EventID") == ev["cc"])
            pen = {}
            for s in (p.get("Terminology") or {}).get("Suites", []):
                for e in s.get("Enumerations", []):
                    pen[e["EnumID"]] = [{"value": q4(x["EnumKeyword"]), "label": zname({"z": x["EnumName"]})}
                                        for x in e.get("Enumerators", [])]
                for e in s.get("Events", []):
                    if e.get("EventType") != ev["cc"]:
                        continue
                    for q in e.get("Parameters", []):
                        t = q["ParamType"]
                        dp = {"name": zname({"z": q["ParamName"]}), "key": q4(q["ParamKeyword"]),
                              "type": "enum" if t in pen else PIPL_TYPE.get(t, "object" if t.startswith("#") or t[0].isupper() else "unknown"),
                              "extra": {"declared_type_4cc": t}}
                        if t in pen:
                            dp["enum"] = pen[t]
                        if not any(x["key"] == dp["key"] for x in declared):
                            declared.append(dp)
        else:
            import harvest_more as hm
            for k, (lab, t) in term_params(term, sid).items():
                ty, vals = hm.declared_type(t, term)
                dp = {"name": lab or k, "key": k, "type": ty, "extra": {"declared_type": t}}
                if vals:
                    dp["enum"] = vals
                declared.append(dp)
        if ev.get("cc"):
            it["extra"]["event_charid"] = ev["cc"]
            w = re.sub(r"[^a-z]", "", fold(name).split()[0])
            if sid.startswith("'"):
                it["extra"]["event_note"] = ("no stringID is registered for this charID: use charIDToTypeID('%s')" % ev["cc"])
            elif w[:4] not in sid.lower():
                it["extra"]["event_note"] = ("'%s' is the stringID Photoshop returns for charID '%s' (a shared code); "
                                             "stringIDToTypeID('%s') == charIDToTypeID('%s')" % (sid, ev["cc"], sid, ev["cc"]))
        dsrc = "plug-in PiPL terminology" if ev["src"] == "pipl" else "Photoshop.exe terminology"
        if sid in SKIP_EXEC:
            it["error"] = SKIP_EXEC[sid]
            it["evidence"] = "event from " + ev["src"] + "; params as declared in the " + dsrc + " (not run)"
            it["params"] = declared
            items.append(it)
            continue
        if not pr:
            it["error"] = "not probed yet"
            it["evidence"] = "event from " + ev["src"] + "; params as declared in the " + dsrc
            it["params"] = declared
        elif pr.get("err"):
            it["error"] = "executeAction(DialogModes.NO) failed on a plain 480x270 RGB pixel layer (no selection, no path): " + pr["err"][:300]
            if pr.get("fallback_err"):
                it["error"] += " | with one value per declared key: " + pr["fallback_err"][:200]
            it["evidence"] = "event from " + ev["src"] + "; live execute failed; params as declared in the " + dsrc
            it["params"] = declared
        else:
            params = []
            for k, rv in (pr.get("readback") or {}).items():
                if k in ("'GEfk'",):
                    it["extra"]["gallery_effect"] = rv.get("v")
                    continue
                prm = param_from_readback(k, rv, term, labels.get(k), enums)
                if k in (pr.get("base_sent") or {}):
                    prm.pop("default", None)  # we sent this value; it is not Photoshop's default
                    prm.setdefault("extra", {})["value_sent_for_probe"] = pr["base_sent"][k]
                apply_ranges(prm, (pr.get("ranges") or {}).get(k))
                params.append(prm)
            it["params"] = params
            it["requires"] = "pixel layer"
            it["evidence"] = ("event from " + ev["src"] + ", confirmed by executeAction(event, {}, DialogModes.NO) on a "
                              "480x270 RGB test layer; default = value Photoshop used with the key omitted (its last-used "
                              "value for this filter); min/max = value kept when 1e6 / 1e6+7 (and negatives) were sent "
                              "(clamp seen twice)")
            if pr.get("ms") is not None:
                it["extra"]["exec_ms"] = pr["ms"]
            sm = SMART.get(sid)
            if sm and not sm.get("err") and sm.get("n"):
                fx = sm.get("filterFX") or {}
                it["extra"]["smart_filter"] = True
                stored = (fx.get("filter") or {}).get("v") or {}
                it["extra"]["smart_filter_stored_keys"] = sorted(stored)
                it["evidence"] += "; smart-filter capable: applied to a smart object, filterFX entry read back"
            elif sm:
                it["extra"]["smart_filter"] = False
                it["extra"]["smart_filter_error"] = (sm.get("err") or "no filterFX entry after apply")[:200]
            if pr.get("note"):
                it["extra"]["probe_note"] = pr["note"]
            if pr.get("base_sent"):
                it["extra"]["empty_descriptor_error"] = (pr.get("empty_err") or "")[:300]
                it["evidence"] = it["evidence"].replace(
                    "default = value Photoshop used with the key omitted (its last-used value for this filter)",
                    "Photoshop refused an empty descriptor, so a probe value (1 / false / first enum) was sent for "
                    "each declared key: no defaults recorded for those keys")
        items.append(it)
    return items


def dedupe(params):
    """a repeated display name is not an address: suffix the key to every repeat"""
    from collections import Counter
    c = Counter(p["name"] for p in params)
    for p in params:
        if c[p["name"]] > 1 and p.get("key"):
            p["name"] = "%s (%s)" % (p["name"], p["key"])
    return params


def write(kind, items, source):
    OUT.mkdir(parents=True, exist_ok=True)
    for it in items:
        if it.get("params"):
            dedupe(it["params"])
    doc = {"app": "PS", "kind": kind, "app_version": VERSION, "source": source, "items": items}
    (OUT / f"{kind}.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    print(kind, len(items), "items")


def main():
    global VERSION
    if "--pipl" in sys.argv:
        extract_pipl()
    v = WORK / "app_version.txt"
    if v.exists():
        VERSION = v.read_text().strip()
    menu, pipl, term = load("menu_tree.json"), load("pipl_all.json"), load("ps_terminology.json")
    ids = load("ids_4cc.json", {})
    write("ps_filter", build_filters(menu, pipl, term, ids, load("probe_filter.json", {})),
          "Filter menu walk (menuBarInfo) + plug-in JSON PiPLs + Photoshop.exe terminology; params from live "
          "executeAction read-backs and clamp probes (tools/ps/harvest_effects.py, probe.py)")
    import harvest_more  # adjustments, layer styles, blend modes
    harvest_more.main(menu, term, ids, write)


if __name__ == "__main__":
    main()
