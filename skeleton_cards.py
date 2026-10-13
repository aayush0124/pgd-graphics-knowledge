"""PGD: write the cards that are pure lookup data, straight from the harvest (no agent): scripting enumerations, type
library entries and the Action Manager terminology item -> cards/<kind>_x<nn>.json for every work/batches/*_x*.json.

    python skeleton_cards.py

An enum card lists every value and the members that take or return the enum ("used by"), computed from the class
members in the same API harvest, so a script author can go from a method to the constants it accepts.
"""
import json, os, re
from collections import defaultdict
from pathlib import Path

HERE = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parent)
HOW = {"PS": "ExtendScript: {n}.<VALUE> (e.g. {n}.{v}). COM / VBScript: the numeric value.",
       "AI": "ExtendScript: {n}.<VALUE> (e.g. {n}.{v}). COM: the Ai-prefixed enum of the type library, same values.",
       "CDR": "COM / VBA: the named constant (e.g. {v} = {val}); Python win32com after gencache.EnsureDispatch: "
              "win32com.client.constants.{v}."}


def used_by(api_items):
    """enum name -> ['Class.member', ...] from member types and parameter types."""
    out = defaultdict(set)
    for it in api_items:
        if not it["id"].startswith("class:"):
            continue
        for m in (it.get("extra") or {}).get("members") or []:
            types = [m.get("type") or ""] + [p.get("type") or "" for p in m.get("params") or []]
            for t in types:
                for w in re.findall(r"\w+", t):
                    out[w].add(f"{it['name']}.{m['name']}")
    return out


def clip(s, n):
    """vendor text over 25 words (the public quote limit) -> its first n words + ' [...]', so the card string that
    quotes it, our own words included, stays within 25 words; shorter text is kept whole."""
    w = s.split()
    return s if len(w) <= 25 else " ".join(w[:n]) + " [...]"


def enum_card(it, app, kind, users):
    vals = (it.get("extra") or {}).get("values") or []
    desc = clip((it.get("extra") or {}).get("description") or "", 9)  # + up to 15 words of our own around it
    u = sorted(users.get(it["name"], ()))
    v0 = vals[0] if vals else {"name": "?", "value": "?"}
    return {"name": it["name"], "id": it["id"], "app": app, "kind": kind, "path": it.get("path"), "status": "current",
            "summary": f"Enumeration {it['name']} ({len(vals)} values){': ' + desc if desc else ''}."
                       + (f" Taken or returned by {len(u)} members, e.g. {', '.join(u[:4])}." if u else ""),
            "use_for": [f"values for {x}" for x in u[:8]] or [f"named constants of type {it['name']}"],
            "confidence": "high",
            "how": HOW[app].format(n=it["name"], v=v0["name"], val=v0["value"]),
            "key_members": [{"name": v["name"], "use": f"= {v['value']}" +
                             (f". {clip(v['description'], 22)}" if v.get("description") else "")} for v in vals],
            "used_by": u, "source": "skeleton_cards.py (harvest only)"}


def lib_card(it, app, kind, api_items):
    lib = (it.get("extra") or {}).get("library") or it["name"]
    members = [x["name"] for x in api_items if x.get("category") == lib and x["id"].startswith("class:")]
    enums = [x["name"] for x in api_items if x.get("category") == lib and x["id"].startswith("enum:")]
    ex = it.get("extra") or {}
    desc = ex.get("description") or ""
    km = [{"name": n, "use": "interface"} for n in members[:60]] + [{"name": n, "use": "enum"} for n in enums[:30]]
    if not km:  # its types repeat an earlier library's (CorelDRAW.tlb re-exports VGCore) or it was listed by name only
        km = [{"name": k, "use": f"{v} types"} for k, v in (ex.get("type_counts") or {}).items()] or \
             [{"name": lib, "use": "listed by name only, members not harvested"}]
        if ex.get("types_shared_with_earlier_libs"):
            km.append({"name": "shared types", "use": f"{ex['types_shared_with_earlier_libs']} types are the same as an "
                                                      f"earlier library's (cards under that library)"})
    return {"name": it["name"], "id": it["id"], "app": app, "kind": kind, "path": it.get("path"), "status": "current",
            "summary": f"COM type library {lib}{' (' + desc + ')' if desc else ''}: {len(members)} interfaces, "
                       f"{len(enums)} enumerations.",
            "use_for": [f"scripting through {lib}"], "confidence": "high",
            "how": f"pythoncom.LoadTypeLib(r\"{it.get('path')}\") reads it without the app; its interfaces are reached "
                   f"from CorelDRAW.Application.25 objects at run time.",
            "key_members": km, "source": "skeleton_cards.py (harvest only)"}


def am_card(it, app, kind):
    ex = it.get("extra") or {}
    return {"name": it["name"], "id": it["id"], "app": app, "kind": kind, "path": it.get("path"), "status": "current",
            "summary": clip(ex.get("description") or "Action Manager constants.", 24), "confidence": "high",
            "use_for": ["building ActionDescriptors for executeAction / executeActionGet",
                        "decoding ScriptListener output"],
            "how": "charIDToTypeID('Xxxx') for 4-character ids, stringIDToTypeID('name') for string ids; this file maps "
                   "Adobe's PITerminology names to them. The full built-in dictionary (every event, class and enum with "
                   "English labels) was extracted from Photoshop.exe: see harvest/ps/ps_filter.json evidence and "
                   "work/ps/ps_terminology.json.",
            "key_members": [{"name": c.get("name"), "use": f"{c.get('group', '')} {c.get('id', '')}".strip()}
                            for c in ex.get("constants") or []],
            "source": "skeleton_cards.py (harvest only)"}


def main():
    n = 0
    for b in sorted((HERE / "work" / "batches").glob("*_x*.json")):
        batch = json.loads(b.read_text(encoding="utf-8"))
        app, kind = batch["app"], batch["kind"]
        api = json.loads((HERE / "harvest" / app.lower() / f"{kind}.json").read_text(encoding="utf-8"))["items"]
        users = used_by(api)
        cards = []
        for it in batch["items"]:
            pre = it["id"].split(":")[0]
            cards.append(enum_card(it, app, kind, users) if pre == "enum" else
                         lib_card(it, app, kind, api) if pre == "lib" else am_card(it, app, kind))
        (HERE / "cards" / b.name).write_text(json.dumps({"cards": cards}, indent=1, ensure_ascii=False), encoding="utf-8")
        n += len(cards)
    print(f"{n} skeleton cards")


if __name__ == "__main__":
    main()
