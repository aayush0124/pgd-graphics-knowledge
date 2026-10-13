"""PGD: check harvest files against CONTRACT.md.

    python check_harvest.py              every harvest/<app>/<kind>.json
    python check_harvest.py FILE ...     just those
    python check_harvest.py --selftest

Exit 0 = no errors (warnings are printed but do not fail).
"""
import json, os, sys
from pathlib import Path

HERE = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parent)
KINDS = {"PS": {"ps_filter", "ps_adjustment", "ps_layer_style", "ps_blend_mode", "ps_tool", "ps_menu", "ps_preset", "ps_api"},
         "AI": {"ai_effect", "ai_blend_mode", "ai_tool", "ai_menu", "ai_preset", "ai_api"},
         "CDR": {"cdr_effect", "cdr_tool", "cdr_menu", "cdr_preset", "cdr_api"}}
PTYPES = {"number", "int", "bool", "enum", "color", "point", "string", "path", "object", "unknown"}
INVOKE = {"ps_event", "ps_menu_cmd", "ps_dom", "ai_menu", "ai_live_effect", "ai_dom", "cdr_guid", "cdr_com",
          "cdr_effect_cmd", "file"}


def check_doc(doc, fname=""):
    """-> (errors, warnings) for one harvest document."""
    err, warn = [], []
    app, kind = doc.get("app"), doc.get("kind")
    if app not in KINDS:
        return [f"app {app!r} not in {sorted(KINDS)}"], warn
    if kind not in KINDS[app]:
        err.append(f"kind {kind!r} not a {app} kind {sorted(KINDS[app])}")
    if fname and Path(fname).stem != kind:
        err.append(f"file is named {Path(fname).stem!r} but holds kind {kind!r}")
    if not doc.get("app_version"):
        warn.append("no app_version")
    items = doc.get("items")
    if not isinstance(items, list) or not items:
        return err + ["no items"], warn
    seen = {}
    for i, it in enumerate(items):
        where = f"item {i} {it.get('name')!r}"
        for f in ("name", "id"):
            if not isinstance(it.get(f), str) or not it[f].strip():
                err.append(f"{where}: missing {f}")
        if isinstance(it.get("id"), str):
            if it["id"] in seen:
                err.append(f"{where}: id {it['id']!r} repeats item {seen[it['id']]}")
            seen.setdefault(it["id"], i)
        for k in it.get("invoke") or {}:
            if k not in INVOKE:
                err.append(f"{where}: invoke key {k!r} not in {sorted(INVOKE)}")
        names = {}
        for p in it.get("params") or []:
            pn = p.get("name") or p.get("key")
            if not pn:
                err.append(f"{where}: a param has neither name nor key")
                continue
            names[pn] = names.get(pn, 0) + 1
            if p.get("type") not in PTYPES:
                err.append(f"{where}: param {pn!r} type {p.get('type')!r} not in {sorted(PTYPES)}")
            lo, hi, d = p.get("min"), p.get("max"), p.get("default")
            nums = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (lo, hi))
            if lo is not None and hi is not None and nums and lo > hi:
                err.append(f"{where}: param {pn!r} min {lo} > max {hi}")
            if nums and isinstance(d, (int, float)) and not isinstance(d, bool) and not lo - 1e-9 <= d <= hi + 1e-9:
                warn.append(f"{where}: param {pn!r} default {d} outside {lo}..{hi}")
            if p.get("type") == "enum" and not p.get("enum"):
                warn.append(f"{where}: enum param {pn!r} lists no values")
            for e in p.get("enum") or []:
                if not isinstance(e, dict) or "value" not in e:
                    err.append(f"{where}: param {pn!r} enum entries must be {{value, label}}")
                    break
        dup = [n for n, c in names.items() if c > 1]
        if dup:  # obs 545: a repeated display name is not an address
            warn.append(f"{where}: repeated param names {dup}: give each a distinct key")
    return err, warn


def main(argv):
    if argv == ["--selftest"]:
        return selftest()
    files = [Path(a) for a in argv] or sorted((HERE / "harvest").glob("*/*.json"))
    bad = 0
    for f in files:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {f}: unreadable: {e}")
            bad += 1
            continue
        err, warn = check_doc(doc, f.name)
        if f.parent.name.upper() != doc.get("app"):
            err.append(f"lives in harvest/{f.parent.name} but app is {doc.get('app')!r}")
        print(f"{f.parent.name}/{f.name}: {len(doc.get('items') or [])} items, {len(err)} errors, {len(warn)} warnings")
        for m in err[:40]:
            print("  ERROR", m)
        for m in warn[:15]:
            print("  warn ", m)
        bad += bool(err)
    return 1 if bad else 0


def selftest():
    good = {"app": "PS", "kind": "ps_filter", "app_version": "27.4.0", "items": [
        {"name": "Gaussian Blur", "id": "gaussianBlur", "invoke": {"ps_event": "gaussianBlur"},
         "params": [{"name": "Radius", "key": "radius", "type": "number", "default": 1, "min": 0.1, "max": 1000}]}]}
    assert check_doc(good, "ps_filter.json") == ([], [])
    bad = json.loads(json.dumps(good))
    bad["items"].append(dict(bad["items"][0]))                      # repeated id
    bad["items"][0]["params"][0].update(type="float", min=5, max=1)  # bad type, min > max
    bad["items"][0]["invoke"] = {"menu": 1}
    e, _ = check_doc(bad, "ps_filter.json")
    assert any("repeats" in x for x in e) and any("float" in x for x in e) and any("min 5 > max 1" in x for x in e) \
        and any("invoke key" in x for x in e), e
    assert check_doc(dict(good, kind="ai_effect"), "ai_effect.json")[0]
    print("selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
