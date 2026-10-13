"""PGD / Illustrator: display names + shortcuts for harvest/ai/ai_tool.json from the Keyboard Shortcuts dialog.

    python ai_tool_names.py      work/ai/ai_tool.json.bak-kbsc + work/ai/kbsc/align.json -> harvest/ai/ai_tool.json

Edit > Keyboard Shortcuts > Export Text lists every tool (and tool-panel key command) with its shortcut in the dialog's
order; kbsc_align.py pairs each line with a /Tools id of Illustrator Defaults.kys (shortcut, words, order). Name rule:
  - a tool (id ends in 'Tool') whose tooltip ZString in the binaries reads '<dialog name> Tool' or '<dialog name>' takes
    that tooltip text (the toolbar shows it: 'Selection Tool (V)'); the dialog pairing is what ties tooltip and id
  - otherwise the dialog's own name ('Magic Wand', 'Swap Fill/Stroke', 'Opacity - 50%')
The id (what app.selectTool() takes) is unchanged. Shortcut = the one the dialog shows.
"""
import json, sys
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_tools import tooltips  # noqa: E402

WORK = (PGD / "work/ai")
BASE = WORK / "ai_tool.json.bak-kbsc"
OUT = (PGD / "harvest/ai/ai_tool.json")


def main():
    base = json.loads(BASE.read_text(encoding="utf-8"))
    al = json.loads((WORK / "kbsc" / "align.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in al["tools"] if r.get("id")}
    tips = {}
    for n, sc, key, b in tooltips():
        tips.setdefault(n, []).append((sc, key, b))
    named = 0
    out = []
    for it in base["items"]:
        it = json.loads(json.dumps(it))
        ex = it.setdefault("extra", {})
        r = by_id.get(it["id"])
        errs = [e for e in (it.get("error") or "").split("; ") if e and not e.startswith("display name")]
        if r:
            how = r["how"]
            strong = any(w in how for w in ("shortcut", "words", "table"))
            ex["kbsc_name"], ex["kbsc_position"] = r["name"], r["position"]
            ex["match"] = f"keyboard-shortcuts dialog alignment: {how} (kbsc_align.py)"
            ex["confirmed"] = strong
            tip = next((t for t in (r["name"] + " Tool", r["name"]) if t in tips), None) if it["id"].endswith("Tool") else None
            old = it["name"] if it["name"] != it["id"] else None
            if tip:
                name = tip
                src = (f"tooltip ZString $$$/{tips[tip][0][1]} in {tips[tip][0][2]} ('{tip}'), tied to this id by the "
                       f"Keyboard Shortcuts dialog entry '{r['name']}'")
            else:
                name = r["name"]
                src = f"Keyboard Shortcuts dialog entry '{r['name']}' (Export Text)"
            if old and old != name:
                ex["previous_name"] = old
            it["name"] = name
            if r.get("shortcut"):
                it["shortcut"] = r["shortcut"]
            elif "shortcut" in it and not r.get("shortcut"):
                ex["kys_shortcut"] = it.pop("shortcut")
            ev = [e for e in it.get("evidence", "").split("; ") if e and not e.startswith("display name")]
            ev.append(f"display name from {src}; dialog line paired with the id by {how}; shortcut as the dialog shows it")
            if not strong:
                ev.append("pairing inferred from dialog order only, not confirmed")
                errs.append("display name inferred from the Keyboard Shortcuts dialog order only (no shortcut or word evidence)")
            it["evidence"] = "; ".join(ev)
            named += 1
        else:
            ex["confirmed"] = False
            if it["name"] == it["id"]:
                errs.insert(0, "display name not found: the Keyboard Shortcuts dialog (Export Text) lists no entry for this id "
                               "and no tooltip ZString pairs with it")
        if errs:
            it["error"] = "; ".join(errs)
        else:
            it.pop("error", None)
        out.append(it)
    doc = dict(base, items=out)
    doc["source"] = base["source"] + " + display names / shortcuts from Edit > Keyboard Shortcuts > Export Text (kbsc_export.py, kbsc_align.py, ai_tool_names.py)"
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(out)} tools, {named} named from the dialog, {sum(1 for x in out if x['name'] == x['id'])} still id-named, "
          f"{sum(1 for x in out if x['extra'].get('confirmed'))} confirmed by shortcut/words")


if __name__ == "__main__":
    main()
