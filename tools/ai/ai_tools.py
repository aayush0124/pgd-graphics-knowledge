"""PGD / Illustrator: build harvest/ai/ai_tool.json.

    python ai_tools.py probe    selectTool(id) + getSelectedToolName() for every id, in a test document -> tool_probe.json
    python ai_tools.py build    -> harvest/ai/ai_tool.json

Sources (all from the installed app):
  Presets/en_US/Tools/Tools Panel Presets   the built-in toolbars (Getting Started / Basic / Advanced): tool ids, the
                                            toolbar group (SELECT, SHAPES ...) and the flyout sets (hidden members)
  Illustrator Defaults.kys  /Tools { }      tool ids + default shortcuts (also keyboard-only commands: Swap Fill/Stroke ...)
  tooltips                                  "$$$/...=<Name> Tool (K)" ZStrings in Illustrator.exe and the .aip that
                                            registers the tool; paired to an id only when the words or (shortcut + a word)
                                            agree, otherwise the item keeps its id as name with an error
  tool_probe.json                           live: getSelectedToolName() == id after app.selectTool(id)
"""
import json, re, sys
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_menus import ROOT, STAGE, WORK, read_kys, kys_shortcut  # noqa: E402

PRESETS = ROOT / "Presets/en_US/Tools/Tools Panel Presets"
OUT = (PGD / "harvest/ai/ai_tool.json")
# 2026-10-04 14:53: the probe call app.selectTool("Adobe Quick Pen Tool") never returned and Illustrator 30.2.1 crashed
# (WerFault -u -p <pid>, "Illustrator has encountered a problem and needs to close"). Never select it from a script.
# 15:21: the resumed probe hung on "Adobe Color Picker Tool" (no return in 20 s) and the Illustrator process then
# exited (next call: RPC_E 'The remote procedure call failed'). Measure / Symbol tools after it were not re-probed.
CRASHED = {"Adobe Quick Pen Tool": "app.selectTool() on this id crashed Illustrator 30.2.1 (2026-10-04 14:53, WerFault); do not script it",
           "Adobe Color Picker Tool": "app.selectTool() on this id hung Illustrator 30.2.1 and the process exited (2026-10-04 15:21); do not script it"}


def toolbars():
    """-> {toolbar name: [(group label, [flyout member ids])]} in panel order."""
    t = PRESETS.read_text(encoding="latin-1")
    res = {}
    for blk in re.split(r"^/collection\d+ \{", t, flags=re.M)[1:]:
        hexname = re.search(r"/collectionName \[ \d+\s+([0-9a-f]+)", blk)
        name = bytes.fromhex(hexname.group(1)).decode("latin-1") if hexname else "?"
        attrs = dict(re.findall(r"^\t\t/(\S+) \((.*)\)$", blk, flags=re.M))
        items = sorted(((int(re.search(r"\d+$", k).group()), v) for k, v in attrs.items()
                        if re.fullmatch(r"(ToolGroup|CustomToolboxItem)\d+", k)))
        groups, label = [], ""
        for n, v in items:
            if v.isupper() and " " not in v:
                label = v
                continue
            m = re.fullmatch(r"CustomToolboxItemSet(\d+)_Count_(\d+)", v)
            members = [attrs[f"CustomToolboxItemSet{m.group(1)}_{i}"] for i in range(int(m.group(2)))] if m else [v]
            groups.append((label, members))
        res[name] = groups
    return res


def tooltips():
    """[(display name, shortcut letter or '', zstring key, binary)] from every binary."""
    out = []
    bins = [ROOT / "Support Files/Contents/Windows/Illustrator.exe"] + sorted(ROOT.rglob("*.aip"))
    rx = re.compile(rb"\$\$\$/([A-Za-z0-9_/.\-]+)=([A-Za-z0-9 &'\-]{2,60} Tool)(?: \((.{1,6}?)\))?\x00")
    for b in bins:
        for m in rx.finditer(b.read_bytes()):
            out.append((m.group(2).decode("latin-1").replace("&", ""), (m.group(3) or b"").decode("latin-1"),
                        m.group(1).decode("latin-1"), b.name))
    return out


def words(s):
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    w = set(re.findall(r"[a-z0-9]+", s.lower())) - {"adobe", "tool", "shape", "construction", "new"}
    return w


def probe():
    from aicom import js
    tb = toolbars()
    on_bar = {m for g in tb.values() for _, mem in g for m in mem}
    ids = [i for i in all_ids() if i in on_bar]  # keyboard-only commands and off-toolbar tools are not scripted
    f = STAGE / "tool_probe.json"
    res = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    js("app.documents.add(DocumentColorSpace.RGB, 800, 600); 'ok'", 60)
    try:
        for i in ids:
            if i in CRASHED or (i in res and "did not return" not in res[i]):
                continue  # checkpoint: done, or known to crash Illustrator
            src = ('var r; try { app.selectTool(%s); r = app.getSelectedToolName(); } catch (e) { r = "ERR " + String(e); } r'
                   % json.dumps(i))
            try:
                res[i] = js(src, 20)
            except Exception as e:  # noqa: BLE001
                res[i] = f"ERR {e}"
                f.write_text(json.dumps(res, indent=1), encoding="utf-8")
                raise SystemExit(f"{i}: no return; stopping (dialog or crash): {e}")
            f.write_text(json.dumps(res, indent=1), encoding="utf-8")
        js("app.selectTool('Adobe Select Tool'); 'ok'", 20)
    finally:
        js("app.activeDocument.close(SaveOptions.DONOTSAVECHANGES); 'closed'", 60)
    ok = sum(1 for i in ids if res.get(i) == i)
    print(f"{ok}/{len(ids)} ids selected and read back")


def all_ids():
    ids = []
    for groups in toolbars().values():
        for _, mem in groups:
            ids += [m for m in mem if m not in ids]
    ids += [k["id"] for k in read_kys("Tools") if k["id"] not in ids]
    return ids


def build():
    tb = toolbars()
    kys = {k["id"]: k for k in read_kys("Tools")}
    pr = json.loads((STAGE / "tool_probe.json").read_text(encoding="utf-8")) if (STAGE / "tool_probe.json").exists() else {}
    pool = json.loads((STAGE / "pool.json").read_text(encoding="utf-8"))
    tips = tooltips()
    adv = max(tb, key=lambda n: sum(len(m) for _, m in tb[n]))  # the fullest built-in toolbar (Advanced)
    where = {}
    for name, groups in tb.items():
        for gi, (label, mem) in enumerate(groups):
            for pos, m in enumerate(mem):
                where.setdefault(m, {})[name] = {"group": label, "flyout": mem, "position": pos}
    out, used_tips = [], set()
    for i in all_ids():
        k = kys.get(i)
        sc = k["shortcut"] if k and k["key"] else ""
        bins = {o["bin"] for o in pool.get(i, [])} | {"Illustrator.exe"}
        # display name: tooltip whose words equal the id's words; else same shortcut letter + a shared word
        iw = words(i)
        cands = [t for t in tips if t[3] in bins and words(t[0]) == iw]
        how = "words"
        if not cands and sc and "+" not in sc:
            cands = [t for t in tips if t[3] in bins and t[1] == sc and words(t[0]) & iw]
            how = "shortcut letter + shared word"
        names = sorted({t[0] for t in cands})
        it = {"name": names[0] if len(names) == 1 else i, "id": i}
        w = where.get(i, {})
        if w:
            a = w.get(adv) or next(iter(w.values()))
            grp = a["group"] or f"flyout of {a['flyout'][0]}"  # the Default toolbar has no group labels
            it["category"] = grp
            it["path"] = f"Toolbar ({adv if adv in w else next(iter(w))})/{grp}"
        else:
            it["category"] = "keyboard command" if not i.endswith("Tool") else "tool (not on a built-in toolbar)"
        if sc:
            it["shortcut"] = sc
        ev = ["id from " + " + ".join(x for x, c in (("Tools Panel Presets", bool(w)), ("Illustrator Defaults.kys /Tools", bool(k))) if c)]
        if len(names) == 1:
            t = cands[0]
            ev.append(f"display name from tooltip ZString $$$/{t[2]} in {t[3]} (matched by {how})")
        p = pr.get(i)
        if p == i:
            it["invoke"] = {"ai_dom": f"app.selectTool({json.dumps(i)})"}
            ev.append("live: app.selectTool(id) then app.getSelectedToolName() returned the id")
        elif p is not None and not p.startswith("ERR"):
            ev.append(f"live: app.selectTool(id) left getSelectedToolName() = {p!r}")
        errs = []
        if len(names) != 1:
            errs.append("display name not found: no tooltip ZString paired with this id" if not names
                        else f"display name ambiguous: {names}")
        if i in CRASHED:
            errs.append(CRASHED[i])
        elif p is None or "did not return" in p:
            errs.append("not verified live: the selectTool probe did not reach this id (Illustrator crashed on an earlier id)")
        elif p.startswith("ERR"):
            errs.append(f"not verified live: app.getSelectedToolName() after app.selectTool(id) raised {p[4:]}")
        elif p != i:
            errs.append(f"app.selectTool(id) did not select it (getSelectedToolName returned {p!r})")
        if errs:
            it["error"] = "; ".join(errs)
        it["evidence"] = "; ".join(ev)
        ex = {}
        if w:
            ex["toolbars"] = {n: {"group": v["group"], "flyout": v["flyout"], "position": v["position"]} for n, v in w.items()}
        if k:
            ex["kys_context"] = k["context"]
        if ex:
            it["extra"] = ex
        out.append(it)
    ver = (WORK / "app_version.txt").read_text().strip()
    doc = {"app": "AI", "kind": "ai_tool", "app_version": ver,
           "source": "Presets/en_US/Tools/Tools Panel Presets + Illustrator Defaults.kys /Tools + tooltip ZStrings in "
                     "Illustrator.exe and Plug-ins/*.aip + live selectTool/getSelectedToolName probe (tools/ai/ai_tools.py)",
           "items": out}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(out)} items, named {sum(1 for x in out if x['name'] != x['id'])}, "
          f"selectable {sum(1 for x in out if 'invoke' in x)}, toolbar {sum(1 for x in out if 'path' in x)}")


if __name__ == "__main__":
    assert words("Adobe Shape Construction Star Tool") == {"star"} and words("Star Tool") == {"star"}
    {"probe": probe, "build": build}[sys.argv[1]]()
