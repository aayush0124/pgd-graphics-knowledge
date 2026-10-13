"""PGD / Illustrator: check that each harvested LiveEffect name + dictionary can be applied by script
(pageItem.applyEffect(xml)) and round-trips -> work/ai/verify_live.json

    python verify_live.py fmt          try the Dict data syntax on one effect (Adobe Twirl) and print what is stored
    python verify_live.py              every ai_effect item with ai_live_effect + simple params

Per item: one rectangle in a fresh document, applyEffect('<LiveEffect name="N"><Dict data="..."/></LiveEffect>')
with every simple param (Real/Int/Bool/String) set to its harvested default, then the document is saved uncompressed
and the stored dictionary compared with what was sent. Documents are closed without saving.
"""
import json, sys
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aicom import js_watch  # noqa: E402
from probe_effects import live_blocks, parse_block, text  # noqa: E402

WORK = (PGD / "work/ai")
HARVEST = (PGD / "harvest/ai/ai_effect.json")
OUT = WORK / "verify_live.json"
LETTER = {"Real": "R", "Int": "I", "Bool": "B", "String": "S", "UnicodeString": "U"}

APPLY = r'''
var d = app.documents.add(DocumentColorSpace.RGB, 800, 600);
for (var i = d.graphicStyles.length - 1; i > 0; i--) { try { d.graphicStyles[i].remove(); } catch (e) {} }
for (var i = d.symbols.length - 1; i >= 0; i--) { try { d.symbols[i].remove(); } catch (e) {} }
var p = d.pathItems.rectangle(450, 250, 300, 200);
var c = new RGBColor(); c.red = 220; c.green = 60; c.blue = 40; p.fillColor = c;
var k = new RGBColor(); k.red = 20; k.green = 40; k.blue = 160; p.strokeColor = k; p.stroked = true; p.strokeWidth = 6;
var r = "applied";
try { p.applyEffect(%(xml)s); } catch (e) { r = "applyEffect failed: " + String(e); }
var o = new IllustratorSaveOptions(); o.compressed = false;
try { d.saveAs(new File(File("%(path)s").fsName), o); } catch (e) { r += " | save failed: " + String(e); }
d.close(SaveOptions.DONOTSAVECHANGES);
r;'''


_BASE = []


def _baseline():
    """baseline blocks from a probe document made in THIS Illustrator session: a probe_baseline.ai left by an earlier
    session no longer subtracts the [Default] style's 'Adobe Stroke Offset' block (audit 2026-10-04), so got[0]
    would be that block instead of the effect under test."""
    if not _BASE:
        from probe_effects import baseline
        _BASE.append(baseline())
    return _BASE[0]


def xml(name, data):
    return '<LiveEffect name="%s"><Dict data="%s"/></LiveEffect>' % (name, data)


def apply(name, data, tag):
    f = WORK / "verify" / f"{tag}.ai"
    f.parent.mkdir(exist_ok=True)
    r, e, seen = js_watch(APPLY % {"xml": json.dumps(xml(name, data)), "path": f.as_posix()}, 120)
    base = _baseline()
    got = [parse_block(b) for b in live_blocks(text(f)) if b not in base] if f.exists() else []
    return r, e, seen, got


def fmt():
    for data in ("R angle 45", "R angle 45 B dummyB 1 I dummyI 3 S dummyS 5 hello"):
        r, e, seen, got = apply("Adobe Twirl", data, "fmt")
        print(repr(data), r, e, seen, [(p["key"], p["ai_type"], p.get("value")) for g in got for p in g["params"]])


def value(p):
    v = p["default"]
    t = p["extra"]["ai_type"]
    if t == "Bool":
        return "1" if v else "0"
    if t in ("String", "UnicodeString"):
        # fmt() confirmed 'S key value' / 'U key value' for one token; values with spaces are left out
        return None if (not isinstance(v, str) or not v or " " in v or '"' in v) else v
    return repr(v) if t == "Real" else str(v)


def same(t, v, got):
    if got is None:
        return False
    if t == "Real":
        return abs(float(v) - float(got)) < 1e-6 * max(1, abs(float(v)))
    if t == "Bool":
        return (v == "1") == bool(got)
    return str(v) == str(got)


def main():
    items = json.loads(HARVEST.read_text(encoding="utf-8"))["items"]
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    for it in items:
        name = (it.get("invoke") or {}).get("ai_live_effect")
        if not name or it["path"] in res:
            continue
        sent = {p["key"]: (p["extra"]["ai_type"], value(p)) for p in it.get("params") or []
                if p.get("extra", {}).get("ai_type") in LETTER and "default" in p and value(p) is not None
                and " " not in p["key"]}
        data = " ".join(f"{LETTER[t]} {k} {v}" for k, (t, v) in sent.items())
        tag = "".join(ch if ch.isalnum() else "_" for ch in it["path"])[:80]
        r, e, seen, got = apply(name, data, tag)
        stored = {p["key"]: p.get("value") for g in got[:1] for p in g["params"]}
        bad = {k: (v, stored.get(k)) for k, (t, v) in sent.items() if not same(t, v, stored.get(k))}
        res[it["path"]] = {"live_effect": name, "result": r, "error": e, "dialogs": seen, "sent": len(sent),
                           "stored_effect": got[0]["live_effect"] if got else None, "mismatch": bad}
        OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
        print(it["path"], r, e or "", "stored:", res[it["path"]]["stored_effect"], "mismatch:", bad, flush=True)


if __name__ == "__main__":
    fmt() if sys.argv[1:] == ["fmt"] else main()
