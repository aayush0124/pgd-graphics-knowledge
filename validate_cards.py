"""PGD: check a card file against the harvested ground truth for its batch.

    python validate_cards.py work/batches/ps_filter_03.json cards/ps_filter_03.json
    python validate_cards.py              every cards/*.json that has a batch (work/batches, else the harvest) + summary
    python validate_cards.py --selftest

Exit 0 = clean, else one issue per line. Checks: one card per batch item (matched by id) and nothing else; required
fields per tier; status / confidence vocabularies; for visual kinds: params[].name and every demo_settings key are real
harvested params (name or key), values fit the harvested type, range and enum (an object param takes a JSON object or
list, checked against the app's read-back / declared class members, see check_object); equivalents name real items of
the other apps; verified verdicts use the vocabulary.
"""
import json, os, re, sys
from functools import lru_cache
from pathlib import Path

HERE = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parent)
STATUS = {"current", "obsolete", "hidden", "needs_input", "unusable"}
CONF = {"high", "medium", "low"}
VERDICT = {"pass", "weak", "wrong", "broken", "not_rendered"}
COMMON = ("name", "app", "kind", "id", "status", "summary", "use_for", "confidence")
TIER_FIELDS = {"visual": ("look", "scripting", "scriptable"), "tool": ("how", "scriptable"), "menu": ("scriptable",),
               "preset": ("applies_to",), "api": ("how", "key_members")}
SETTABLE = {"number", "int", "bool", "enum", "color", "point", "string"}


@lru_cache(None)
def names_of(app):
    """Lower-case names, ids and paths of every harvested item of one app (for equivalents)."""
    out = set()
    for f in (HERE / "harvest" / app.lower()).glob("*.json"):
        try:
            for it in json.loads(f.read_text(encoding="utf-8"))["items"]:
                out.update(str(it.get(k, "")).lower() for k in ("name", "id", "path"))
        except Exception:  # noqa: BLE001
            pass
    out.discard("")
    return out


def param_index(item):
    idx = {}
    for p in item.get("params") or []:
        for k in (p.get("name"), p.get("key")):
            if k:
                idx.setdefault(k, p)
    return idx


def check_value(n, p, v):
    t = p.get("type")
    num = isinstance(v, (int, float)) and not isinstance(v, bool)
    if t in ("number", "int"):
        if not num:
            return f"{n}: expects a number, got {v!r}"
        if t == "int" and v != int(v):
            return f"{n}: expects a whole number, got {v!r}"
    elif t == "bool" and not isinstance(v, bool):
        return f"{n}: expects true/false, got {v!r}"
    elif t == "enum":
        ok = {str(e.get("value")) for e in p.get("enum") or []} | {str(e.get("label")) for e in p.get("enum") or []}
        if ok - {"None"} and str(v) not in ok:
            return f"{n}: {v!r} is not one of {sorted(ok - {'None'})[:25]}"
    elif t == "color" and not (isinstance(v, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", v)):
        return f"{n}: expects \"#RRGGBB\", got {v!r}"
    elif t == "point" and not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)):
        return f"{n}: expects [x, y], got {v!r}"
    elif t == "object":
        return check_object(n, p, v)
    elif t not in SETTABLE:
        return f"{n}: a {t} param cannot be set from a spec"
    if num:
        lo, hi = p.get("min"), p.get("max")
        if isinstance(lo, (int, float)) and v < lo - 1e-9:
            return f"{n}: {v} below the harvested minimum {lo}"
        if isinstance(hi, (int, float)) and v > hi + 1e-9:
            return f"{n}: {v} above the harvested maximum {hi}"
    return None


def _leaf(n, r, v):
    """v against the app's read-back {t, v, ...} of the same member"""
    t = (r or {}).get("t") if isinstance(r, dict) else None
    num = isinstance(v, (int, float)) and not isinstance(v, bool)
    if t in ("INTEGERTYPE", "LARGEINTEGERTYPE") and not (num and v == int(v)):
        return f"{n}: expects a whole number, got {v!r}"
    if t in ("DOUBLETYPE", "UNITDOUBLE") and not num:
        return f"{n}: expects a number, got {v!r}"
    if t == "BOOLEANTYPE" and not isinstance(v, bool):
        return f"{n}: expects true/false, got {v!r}"
    if t in ("STRINGTYPE", "ENUMERATEDTYPE") and not isinstance(v, str):
        return f"{n}: expects a string, got {v!r}"
    if t in ("LISTTYPE", "OBJECTTYPE"):
        return _shape(n, v, r.get("v"), None)
    return None


def _shape(n, v, rb, members):
    """an object / list value against the harvested read-back (rb: [{t, v}] or {member: {t, v}}) and the declared
    members of its class ({member: type}; a list of objects is checked object by object)."""
    if isinstance(rb, list) and rb:
        if not isinstance(v, list) or len(v) != len(rb):
            return f"{n}: expects a list of {len(rb)} like the app's read-back, got {v!r}"
        return next((e for i, x in enumerate(v) if (e := _leaf(f"{n}[{i}]", rb[i], x))), None)
    for i, o in enumerate(v if isinstance(v, list) else [v]):
        if not isinstance(o, dict) or not (isinstance(rb, dict) or members):
            continue
        ok = set(rb if isinstance(rb, dict) else ()) | set(members or ())
        ok |= {"grain"} if "green" in ok else set()  # one typeID ('Grn '): declared "green", read back "grain"
        bad = [k for k in o if k not in ok]
        if bad:
            return f"{n}: {bad} not members of this object (have {sorted(ok)})"
        e = next((e for k, x in o.items() if isinstance(rb, dict) and (e := _leaf(f"{n}.{k}", rb.get(k), x))), None)
        if e:
            return e
    return None


def _numbers(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        yield v
    elif isinstance(v, (list, dict)):
        for x in v.values() if isinstance(v, dict) else v:
            yield from _numbers(x)


def check_object(n, p, v):
    """an object / list param (channel matrix, level lists, curve points ...): a JSON object or list, checked against
    the app's read-back of the same key when the harvest has one (members, types, list length), the declared type
    ("/integer /list": a list of whole numbers), the class's declared members, and the param's min / max on every
    number in it."""
    x = p.get("extra") or {}
    decl = x.get("declared_type") or ""
    if not isinstance(v, (dict, list)):
        return f"{n}: expects an object {{member: value}} or a list, got {v!r}"
    if "/list" in decl and not isinstance(v, list):
        return f"{n}: expects a list (declared {decl}), got {v!r}"
    if decl.startswith("/integer") and any(y != int(y) for y in _numbers(v)):
        return f"{n}: expects whole numbers (declared {decl}), got {v!r}"
    e = _shape(n, v, x.get("value"), x.get("members"))
    if e:
        return e
    lo, hi = p.get("min"), p.get("max")
    for y in _numbers(v):
        if isinstance(lo, (int, float)) and y < lo - 1e-9:
            return f"{n}: {y} below the harvested minimum {lo}"
        if isinstance(hi, (int, float)) and y > hi + 1e-9:
            return f"{n}: {y} above the harvested maximum {hi}"
    return None


def check(batch, cards):
    tier, kind = batch.get("tier"), batch["kind"]
    issues, by_id = [], {}
    for c in cards:
        by_id.setdefault(c.get("id"), []).append(c)
    for it in batch["items"]:
        got = by_id.get(it["id"])
        if not got:
            issues.append(f"missing card for id {it['id']!r} ({it['name']})")
            continue
        if len(got) > 1:
            issues.append(f"{len(got)} cards for id {it['id']!r}")
        c, w = got[0], it["name"]
        miss = [f for f in COMMON + TIER_FIELDS.get(tier, ()) if c.get(f) in (None, "", [], {})]
        if miss:
            issues.append(f"{w}: missing {miss}")
        if c.get("name") != it["name"]:
            issues.append(f"{w}: card name {c.get('name')!r} must be the harvested name exactly")
        if c.get("kind") != kind or c.get("app") != batch["app"]:
            issues.append(f"{w}: kind/app {c.get('kind')}/{c.get('app')} should be {kind}/{batch['app']}")
        if c.get("status") and c["status"] not in STATUS:
            issues.append(f"{w}: status {c['status']!r} not in {sorted(STATUS)}")
        if c.get("confidence") and c["confidence"] not in CONF:
            issues.append(f"{w}: confidence {c['confidence']!r} not in {sorted(CONF)}")
        if tier in ("tool", "menu", "visual") and c.get("scriptable") not in (None, "yes", "partial", "no"):
            issues.append(f"{w}: scriptable must be yes / partial / no")
        if tier == "api":  # a member named on the card must exist in the harvested class / enum
            ex = it.get("extra") or {}
            real = {m.get("name") for m in (ex.get("members") or []) + (ex.get("values") or [])}
            if real:
                fake = [k.get("name") for k in c.get("key_members") or [] if k.get("name") not in real]
                if fake:
                    issues.append(f"{w}: key_members {fake[:8]} are not harvested members of {it['name']}")
        v = (c.get("verified") or {}).get("verdict")
        if v and v not in VERDICT:
            issues.append(f"{w}: verified.verdict {v!r} not in {sorted(VERDICT)}")
        for app, eq in (c.get("equivalents") or {}).items():
            if app not in ("PS", "AI", "CDR") or app == batch["app"]:
                issues.append(f"{w}: equivalents key {app!r} must be another app code (PS / AI / CDR)")
            elif eq and str(eq).lower() not in names_of(app):
                issues.append(f"{w}: equivalents.{app} {eq!r} is not a harvested {app} name, id or path "
                              f"(look it up: python pgd.py items {app} \"<words>\")")
        if tier == "visual":
            idx = param_index(it)
            for p in c.get("params") or []:
                if p.get("name") not in idx:
                    issues.append(f"{w}: params lists {p.get('name')!r}, not a harvested param (have {list(idx)[:40]})")
            for n, val in (c.get("demo_settings") or {}).items():
                if n not in idx:
                    issues.append(f"{w}: demo_settings {n!r} is not a harvested param")
                    continue
                e = check_value(n, idx[n], val)
                if e:
                    issues.append(f"{w}: {e}")
            settable = [p for p in it.get("params") or [] if p.get("type") in SETTABLE]
            if c.get("status") == "current" and settable and not c.get("demo_settings"):
                issues.append(f"{w}: a current item with settable params needs demo_settings that make it clearly visible")
    ids = {it["id"] for it in batch["items"]}
    issues += [f"card {c.get('name')!r} (id {c.get('id')!r}) is not in the batch" for c in cards if c.get("id") not in ids]
    return issues


def validate_all(show=8):
    """Every cards/<batch>.json against its batch (work/batches/<batch>.json, else built in memory from the harvest)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from prepare_batches import all_batches
    mem, files, cards_n, bad, skipped, src = None, 0, 0, [], [], {"work/batches": 0, "harvest (in memory)": 0}
    for cf in sorted((HERE / "cards").glob("*.json")):
        disk = HERE / "work" / "batches" / cf.name
        if disk.exists():
            batch, s = json.loads(disk.read_text(encoding="utf-8")), "work/batches"
        else:
            mem = all_batches(HERE) if mem is None else mem
            batch, s = mem.get(cf.stem), "harvest (in memory)"
        if batch is None:
            skipped.append(cf.name)  # recipe_* / zz_critic: not one card per harvested item
            continue
        files += 1
        src[s] += 1
        try:
            cards = json.loads(cf.read_text(encoding="utf-8"))["cards"]
        except Exception as e:  # noqa: BLE001
            bad.append((cf.name, [f"card file unreadable: {e}"]))
            continue
        cards_n += len(cards)
        issues = check(batch, cards)
        if issues:
            bad.append((cf.name, issues))
    for name, issues in bad:
        print(f"{name}: {len(issues)} issues")
        for m in issues[:show]:
            print("  ", m)
    print(f"{files} card files ({', '.join(f'{n} from {k}' for k, n in src.items() if n)}), {cards_n} cards: "
          f"{files - len(bad)} clean, {len(bad)} with issues ({sum(len(i) for _, i in bad)} issues)"
          + (f"; skipped {len(skipped)} without a batch: {', '.join(skipped)}" if skipped else ""))
    return 1 if bad else 0


def main(argv):
    if argv == ["--selftest"]:
        return selftest()
    if not argv:
        return validate_all()
    if len(argv) < 2:
        print(__doc__)
        return 2
    batch = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    try:
        cards = json.loads(Path(argv[1]).read_text(encoding="utf-8"))["cards"]
    except Exception as e:  # noqa: BLE001
        print(f"card file unreadable: {e}")
        return 1
    issues = check(batch, cards)
    print("\n".join(issues))
    print(f"{len(cards)} cards, {len(issues)} issues")
    return 1 if issues else 0


def selftest():
    b = {"kind": "ps_filter", "app": "PS", "tier": "visual", "items": [{"name": "Gaussian Blur", "id": "gaussianBlur",
         "params": [{"name": "Radius", "key": "radius", "type": "number", "min": 0.1, "max": 1000},
                    {"name": "Mode", "key": "mode", "type": "enum", "enum": [{"value": "a", "label": "A"}]}]}]}
    good = {"name": "Gaussian Blur", "app": "PS", "kind": "ps_filter", "id": "gaussianBlur", "status": "current",
            "summary": "s", "use_for": ["x"], "confidence": "high", "look": ["soft"], "scripting": "executeAction", "scriptable": "yes",
            "params": [{"name": "Radius", "does": "d"}], "demo_settings": {"Radius": 12, "mode": "A"}}
    assert check(b, [good]) == [], check(b, [good])
    bad = dict(good, demo_settings={"Radius": 5000, "Amount": 1, "mode": "z"}, status="live", equivalents={"PS": "x"})
    e = " | ".join(check(b, [bad, dict(good, id="other")]))
    for want in ("above the harvested maximum", "'Amount' is not a harvested", "not one of", "status 'live'",
                 "equivalents key", "not in the batch"):
        assert want in e, (want, e)
    assert "needs demo_settings" in " ".join(check(b, [dict(good, demo_settings={})]))
    # object / list params: shape and members from the app's read-back or the declared class
    lv = {"name": "Shadow Levels", "type": "object", "extra": {"value": [{"t": "INTEGERTYPE", "v": 0}] * 3}}
    mx = {"name": "Gray", "type": "object", "extra": {"declared_type": "/channelMatrix", "members": {"red": "/integer", "green": "/integer"}}}
    il = {"name": "Matrix", "type": "object", "min": -999, "max": 999, "extra": {"declared_type": "/integer /list"}}
    assert check_value("s", lv, [-40, 0, 40]) is None and check_value("g", mx, {"red": 40, "grain": 60}) is None
    for p, v, want in ((lv, [1, 2], "list of 3"), (lv, [1, 2.5, 3], "whole number"), (mx, {"blu": 1}, "not members"),
                       (il, [1, 2000], "above the harvested maximum"), (il, {"a": 1}, "expects a list"), (lv, 5, "expects an object")):
        assert want in (check_value("n", p, v) or ""), (p, v, check_value("n", p, v))
    print("selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
