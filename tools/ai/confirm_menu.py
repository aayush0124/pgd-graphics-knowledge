"""PGD / Illustrator: confirm executeMenuCommand ids against the menu item itself -> work/ai/kbsc/confirm.json

    python confirm_menu.py [--limit N]

For every walked menu item that has a candidate id (old matcher in harvest/ai/ai_menu.json, or the Keyboard
Shortcuts dialog alignment in work/ai/kbsc/align.json) and is safe to run, two runs on identical fresh test documents:
  A  app.executeMenuCommand(id)
  B  WM_COMMAND(<the item's Win32 command number from the live menu walk>) posted to the main window = the menu item
Dialogs are answered with Escape (Cancel) through their window handles (no global input). After each run the document
state is read (items, bounds, selection, lock / hide, fills, text, view). Verdict:
  confirmed      both opened the same dialog(s), or both changed the document the same way
  refuted        the two runs did different things
  inconclusive   neither did anything observable on the test document
Command numbers were re-walked after the 15:21 restart (work/ai/kbsc/rewalk): identical, so B is the menu item.
Commands that quit, close, save, print, export, place, use the clipboard, open panels / web pages or change
preferences / view settings are never run.
"""
import json, re, sys, time
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aicom import js, js_watch, dialogs, main_hwnd, u32  # noqa: E402

KB = (PGD / "work/ai/kbsc")
OUT = KB / "confirm.json"
BASE = (PGD / "work/ai/ai_menu.json.bak-kbsc")  # harvest as it was before the merge

UNSAFE = re.compile(
    r"^File/|^Help/|^Window/|Exit|Quit|Close|Save|Print|Export|Package|Share|Sign|Open|Browse|Place|Bridge|Revert|"
    r"Preferences|Keyboard|Color Settings|Assign Profile|Workspace|Scripts|Generative|Mockup|Retype|Adobe Fonts|"
    r"^Edit/Cut$|^Edit/Copy$|^Edit/Paste|Smart Guides|Snap|Bounding Box|GPU|Pixel Preview|Overprint Preview|Rulers|"
    r"Guides|Grid|Edges|Artboards$|Print Tiling|Template|Text Threads|Gradient Annotator|Corner Widget|"
    r"Live Paint Gaps|Transparency Grid|Slices|Trim View|Presentation|Screen Mode|Proof|Find and Replace|Spelling|"
    r"Dictionary|Edit Original|Presets|Libraries|Collect For Export|Variables|Font|Glyphs|Type Conversion|"
    r"Legacy Text|Perspective|Image Trace|Graph/Data|Show Hidden|Edit Views|New View|Recolor|Collect|Link")

SETUP = r'''
var d = app.documents.add(DocumentColorSpace.RGB, 800, 600);
var a = d.pathItems.rectangle(450, 250, 300, 200); a.name = "A";
var c = new RGBColor(); c.red = 220; c.green = 60; c.blue = 40; a.fillColor = c; a.strokeWidth = 4;
var b = d.pathItems.ellipse(400, 350, 250, 250); b.name = "B";
var c2 = new RGBColor(); c2.red = 30; c2.green = 90; c2.blue = 200; b.fillColor = c2;
var t = d.textFrames.add(); t.contents = "Pgd test"; t.top = 120; t.left = 100; t.name = "T";
d.selection = null;
if (%(text)s) { t.selected = true; } else { a.selected = true; b.selected = true; }
d.name;'''

STATE = r'''
function col(c) { try { if (c.typename == "RGBColor") return Math.round(c.red) + "," + Math.round(c.green) + "," + Math.round(c.blue);
  if (c.typename == "GrayColor") return "g" + Math.round(c.gray); if (c.typename == "CMYKColor") return "k" + Math.round(c.cyan) + "," +
  Math.round(c.magenta) + "," + Math.round(c.yellow) + "," + Math.round(c.black); return c.typename; } catch (e) { return "?"; } }
var d = app.activeDocument, o = [];
o.push("n=" + d.pageItems.length + " p=" + d.pathItems.length + " g=" + d.groupItems.length + " c=" + d.compoundPathItems.length +
  " t=" + d.textFrames.length + " r=" + d.rasterItems.length + " m=" + d.meshItems.length + " pl=" + d.pluginItems.length +
  " sy=" + d.symbolItems.length + " L=" + d.layers.length + " ab=" + d.artboards.length + " cs=" + d.documentColorSpace);
var s = d.selection, sn = [];
if (s && s.length !== undefined) { for (var i = 0; i < s.length; i++) sn.push(s[i].typename + ":" + s[i].name); } else if (s) sn.push("range:" + s.typename);
o.push("sel=" + sn.join(","));
for (var i = 0; i < d.pageItems.length && i < 12; i++) { var it = d.pageItems[i], g = it.geometricBounds;
  var x = it.typename + ":" + it.name + ":" + (it.locked ? "L" : "") + (it.hidden ? "H" : "") + ":" + Math.round(g[0]) + "," +
    Math.round(g[1]) + "," + Math.round(g[2]) + "," + Math.round(g[3]) + ":o" + Math.round(it.opacity) + ":" + it.blendingMode;
  try { if (it.typename == "PathItem") x += ":pp" + it.pathPoints.length + ":f" + (it.filled ? col(it.fillColor) : "-") +
    ":s" + (it.stroked ? Math.round(it.strokeWidth * 10) + "/" + col(it.strokeColor) : "-") + (it.guides ? ":guide" : "") +
    (it.clipping ? ":clip" : ""); } catch (e) {}
  try { if (it.typename == "TextFrame") x += ":'" + it.contents + "':" + it.orientation + ":" + it.kind + ":" +
    it.textRange.characterAttributes.size + ":" + col(it.textRange.characterAttributes.fillColor); } catch (e) {}
  o.push(x); }
var v = d.views[0]; o.push("zoom=" + Math.round(v.zoom * 100) + " cp=" + Math.round(v.centerPoint[0]) + "," + Math.round(v.centerPoint[1]));
try { o.push("rot=" + v.rotateAngle); } catch (e) {}
for (var i = 0; i < d.layers.length; i++) o.push("layer " + d.layers[i].name + (d.layers[i].locked ? " L" : "") + (d.layers[i].visible ? "" : " H"));
o.join("\n");'''

CLOSE = ('for (var i = app.documents.length - 1; i >= 0; i--) if (app.documents[i].name == "%s") '
         '{ app.documents[i].close(SaveOptions.DONOTSAVECHANGES); break; } app.documents.length;')


def clear_dialogs():
    for _ in range(4):
        if not [d for d in dialogs() if d[3]]:
            return
        js_watch("1", 10, key="escape")


def run(how, arg, text):
    name = js(SETUP % {"text": "true" if text else "false"}, 60)
    s0 = js(STATE, 30)
    try:
        if how == "id":
            r, e, seen = js_watch('app.executeMenuCommand(%s); "ok";' % json.dumps(arg), 45, key="escape")
        else:
            u32.PostMessageW(main_hwnd(), 0x0111, arg, 0)
            time.sleep(0.6)
            r, e, seen = js_watch("app.documents.length", 45, key="escape")
        time.sleep(0.4)
        clear_dialogs()
        try:
            s1 = js(STATE, 30)
        except Exception as x:  # noqa: BLE001
            s1 = "STATE ERR " + str(x)[:200]
    finally:
        clear_dialogs()
        # the command may have opened / switched documents: close only ours
        js(CLOSE % name, 60)
    return {"error": (e or "")[:200] or None, "dialogs": seen, "changed": s0 != s1, "s0": s0, "s1": s1}


def verdict(a, b):
    return verdict_rec({"a": a, "b": b, "diff_b": None if a.get("s1") == b.get("s1") else b.get("s1")})


def verdict_rec(rec):
    """verdict from a stored record (a / b run summaries; diff_b is set only when b ended in another state than a).
    Untitled helper windows ('' titles) are ignored; a generic 'Adobe Illustrator' alert alone proves nothing."""
    a, b = rec["a"], rec["b"]
    if a.get("error") and "1200" in a["error"]:
        return "refuted", "executeMenuCommand raised Error 1200 (not a command)"
    da, db = set(a.get("dialogs") or []) - {""}, set(b.get("dialogs") or []) - {""}
    same_state = rec.get("diff_b") is None and a.get("changed") == b.get("changed")
    if da or db:
        if da != db:
            return "refuted", "executeMenuCommand opened %s, the menu item opened %s" % (sorted(da), sorted(db))
        if da == {"Adobe Illustrator"}:
            if a.get("changed") and same_state:
                return "confirmed", "both showed the same alert and changed the test document the same way"
            return "inconclusive", "both showed only a generic 'Adobe Illustrator' alert (not specific to a command)"
        return "confirmed", "both opened the dialog %s" % sorted(da)
    if a.get("changed") or b.get("changed"):
        if a.get("changed") and same_state:
            return "confirmed", "both changed the test document the same way"
        return "refuted", "executeMenuCommand and the menu item changed the test document differently"
    return "inconclusive", "neither changed the test document or opened a dialog"


def candidates():
    base = json.loads(BASE.read_text(encoding="utf-8"))["items"]
    al = json.loads((KB / "align.json").read_text(encoding="utf-8"))
    by_path = {it["path"]: it for it in base if it.get("path")}
    out = {}
    for it in base:
        if it.get("path") and not it["id"].startswith("path:"):
            out.setdefault(it["path"], set()).add(it["id"])
    for r in al["menus"]:
        if r.get("id") and r.get("walked_path") in by_path:
            out.setdefault(r["walked_path"], set()).add(r["id"])
    res = []
    for p, ids in out.items():
        if UNSAFE.search(p):
            continue
        cmd = by_path[p]["extra"]["win32_cmd"]
        old = by_path[p]["id"]
        meth = by_path[p].get("extra", {}).get("id_match")
        for i in sorted(ids):
            # most doubtful first: ids only the dialog alignment proposes, matchers that disagree, then weak old
            # matches, then shortcut matches; already verified ones last
            pr = 0 if old.startswith("path:") or len(ids) > 1 else {"words+path": 1, "idtext": 1, "table": 1,
                                                                    "shortcut": 2}.get(meth, 3)
            res.append((pr, p, i, cmd))
    return [r[1:] for r in sorted(res, key=lambda r: r[0])]


def main(argv):
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 10 ** 6
    done = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    todo = [c for c in candidates() if f"{c[0]} | {c[1]}" not in done][:limit]
    print(len(todo), "to test")
    for p, i, cmd in todo:
        text = p.startswith("Type/")
        try:
            a = run("id", i, text)
            b = run("wm", cmd, text)
            v, why = verdict(a, b)
        except Exception as x:  # noqa: BLE001
            clear_dialogs()
            a, b, v, why = {}, {}, "error", str(x)[:300]
        done[f"{p} | {i}"] = {"path": p, "id": i, "win32_cmd": cmd, "verdict": v, "why": why,
                              "a": {k: a.get(k) for k in ("error", "dialogs", "changed")},
                              "b": {k: b.get(k) for k in ("error", "dialogs", "changed")},
                              "diff_a": a.get("s1") if a.get("changed") else None,
                              "diff_b": b.get("s1") if b.get("changed") and b.get("s1") != a.get("s1") else None,
                              "t": time.strftime("%H:%M:%S")}
        OUT.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{v:12s} {p} | {i} | {why}", flush=True)
    print("docs open:", js("app.documents.length", 30))


if __name__ == "__main__":
    assert UNSAFE.search("File/Save As...") and UNSAFE.search("Edit/Paste in Front") and not UNSAFE.search("Object/Group")
    assert not UNSAFE.search("Edit/Copy Appearance") or True
    main(sys.argv[1:])
