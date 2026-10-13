"""PGD / Illustrator: read the JSON PiPL resources of the Photoshop filters Illustrator ships -> work/ai/pipl_filters.json

    python pipl.py

Each filter: name, category, class_id, event_id (the 4-char code in Illustrator's 'Live PSAdapter_plugin_<code>' menu
command) and the scripting terminology (param name, keyword, type, enum values) from the same resource.
"""
import glob, json, os, re
from pathlib import Path
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

import win32api, win32con

DIR = r"C:\Program Files\Adobe\Adobe Illustrator 2026\Plug-ins\Photoshop Filters"
OUT = (PGD / "work/ai/pipl_filters.json").as_posix()


def zlabel(s):
    """'$$$/AdobePlugin/X/Radius=Radius:' -> 'Radius:'"""
    return s.split("=", 1)[1] if isinstance(s, str) and s.startswith("$$$") and "=" in s else s


def read(f):
    h = win32api.LoadLibraryEx(f, 0, win32con.LOAD_LIBRARY_AS_DATAFILE)
    out = []
    try:
        if "JSON" not in win32api.EnumResourceTypes(h):
            return out
        for n in win32api.EnumResourceNames(h, "JSON"):
            doc = json.loads(win32api.LoadResource(h, "JSON", n).decode("utf-8"))
            for p in doc.get("PiPLs", []):
                if p.get("Kind") != "Filter":
                    continue
                ht = p.get("HasTerminology") or {}
                enums, params = {}, []
                for suit in (p.get("Terminology") or {}).get("Suits", []):
                    for en in suit.get("Enumerations", []):
                        enums[en["EnumID"]] = [{"value": e["EnumKeyword"], "label": zlabel(e.get("EnumName"))}
                                               for e in en.get("Enumerators", [])]
                    for ev in suit.get("Events", []):
                        if ev.get("ClassID") not in (ht.get("ClassID"), None) and ev.get("EventType") != ht.get("EventID"):
                            continue
                        for prm in ev.get("Parameters", []):
                            params.append({"label": zlabel(prm.get("ParamName")), "key": prm.get("ParamKeyword"),
                                           "ps_type": prm.get("ParamType")})
                for prm in params:
                    if prm["ps_type"] in enums:
                        prm["enum"] = enums[prm["ps_type"]]
                out.append({"file": os.path.basename(f), "name": p.get("Name"), "category": p.get("Category"),
                            "class_id": ht.get("ClassID"), "event_id": ht.get("EventID"), "terminology": params})
    finally:
        win32api.FreeLibrary(h)
    return out


def main():
    res = []
    for f in sorted(glob.glob(os.path.join(DIR, "*.8[bB][fF]"))):
        res.extend(read(f))
    json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(len(res), "filters ->", OUT)
    assert any(r["event_id"] == "GEfc" for r in res)


if __name__ == "__main__":
    main()
