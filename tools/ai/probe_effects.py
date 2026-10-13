"""PGD / Illustrator: probe every Effect-menu item on a fresh test path -> work/ai/probe_ckpt.json (checkpointed per item)

    python probe_effects.py [--redo] [--only SUBSTR]

Per item, in a NEW document of its own (closed without saving afterwards):
  1. graphic styles / symbols removed (the new-doc profile ships styles that carry live effects), one 300x200 filled
     + stroked rectangle created and selected;
  2. the item invoked: app.executeMenuCommand(<ai_menu id>) when the harvest has one, else WM_COMMAND with the menu
     command number posted to the main window (menu_walk.py); every dialog that opens is recorded (title + PNG) and
     answered with Enter, so the dialog's own values apply;
  3. the document saved as an UNCOMPRESSED .ai (compressed=false; pdfCompatible=false makes Illustrator fail the
     save with "unknown error") and every live-effect block ('(<LiveEffect name>) 1 0 /Filter') that the clean
     baseline document does not have is parsed: LiveEffect name, plug-in file, title, dictionary (key, type, value).
"""
import json, re, sys, time
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aicom import js, js_watch, main_hwnd, dialogs, u32  # noqa: E402

WORK = (PGD / "work/ai")
HARVEST = (PGD / "harvest/ai/ai_effect.json")
CKPT = WORK / "probe_ckpt.json"
SHOTS = WORK / "dialogs"
TYPES = {"Real": "number", "Int": "int", "Bool": "bool", "String": "string", "UnicodeString": "string"}

NEW_DOC = r'''
var d = app.documents.add(DocumentColorSpace.RGB, 800, 600);
for (var i = d.graphicStyles.length - 1; i > 0; i--) { try { d.graphicStyles[i].remove(); } catch (e) {} }
for (var i = d.symbols.length - 1; i >= 0; i--) { try { d.symbols[i].remove(); } catch (e) {} }
var p = d.pathItems.rectangle(450, 250, 300, 200);
var c = new RGBColor(); c.red = 220; c.green = 60; c.blue = 40; p.fillColor = c;
var k = new RGBColor(); k.red = 20; k.green = 40; k.blue = 160; p.strokeColor = k; p.stroked = true; p.strokeWidth = 6;
p.name = "pgd_probe"; d.selection = null; p.selected = true;
d.name;'''

SAVE_CLOSE = r'''
var d = null; for (var i = 0; i < app.documents.length; i++) if (app.documents[i].name == "%(doc)s") d = app.documents[i];
var r = "nodoc";
if (d) {
  var o = new IllustratorSaveOptions(); o.compressed = false;
  try { d.saveAs(new File(File("%(path)s").fsName), o); r = "saved"; } catch (e) { r = "save failed: " + String(e); }
  d.close(SaveOptions.DONOTSAVECHANGES);
}
r;'''


def text(path):
    return Path(path).read_bytes().decode("latin-1").replace("\r\n", "\n").replace("\r", "\n")


def live_blocks(t):
    """[(start, block text)] for every live-effect BasicFilter in an uncompressed .ai."""
    out = []
    for m in re.finditer(r"/BasicFilter :\n\(([^()\n]*)\) 1 0 /Filter ,\n", t):
        end = t.find("\n; /Dict ;", m.end())
        out.append(t[m.start():end + 10])
    return out


def parse_block(b):
    """-> {live_effect, plugin_file, title, params:[{key,type,value,ai_type}]}"""
    d = {"live_effect": re.search(r"^\((.*?)\) 1 0 /Filter", b, re.M).group(1)}
    m = re.search(r"^\((.*?)\) /PluginFileName ,$", b, re.M)
    if m:
        d["plugin_file"] = m.group(1)
    m = re.search(r"^\((.*?)\) /Title ,$", b, re.M)
    if m:
        d["title"] = m.group(1)
    m = re.search(r"^(\d+) /FillOrStroke ,$", b, re.M)
    if m:
        d["fill_or_stroke"] = int(m.group(1))
    head = "/Dictionary : /NotRecorded ,\n"
    body = b[b.find(head) + len(head):]
    d["params"] = parse_dict(body.split("\n"))
    d["raw"] = b
    return d


KEYLINE = re.compile(r"^\s*;?\s*\(([^()]*)\) ,$")
SIMPLE = re.compile(r"^(.*?) /(Real|Int|Bool|String|UnicodeString) \(([^()]*)\) ,$")
ONELINE = re.compile(r"^/(\w+) : (.*) ; \(([^()]*)\) ,$")
OBJTYPE = {"FillStyle": "color", "StrokeStyle": "object", "Dictionary": "object", "Art": "object"}


def parse_dict(lines):
    """top-level entries of a live-effect dictionary body (lines up to '; /Dict ;')."""
    params, i = [], 0
    while i < len(lines):
        ln = lines[i]
        m = SIMPLE.match(ln)
        if m:
            v, ty, key = m.groups()
            v = v.strip()
            if ty == "Real":
                val = float(v)
            elif ty == "Int":
                val = int(v)
            elif ty == "Bool":
                val = v == "1"
            else:
                val = v[1:-1] if v.startswith("(") and v.endswith(")") else v
            params.append({"key": key, "ai_type": ty, "type": TYPES[ty], "value": val})
        elif ONELINE.match(ln):  # one-line nested value: /GObjRef : (x) /SVGFilter ; (key) ,
            m = ONELINE.match(ln)
            params.append({"key": m.group(3), "ai_type": m.group(1), "type": "object", "value_raw": m.group(2)})
        elif re.match(r"^/(\w+) :", ln):
            kind, depth, j = re.match(r"^/(\w+) :", ln).group(1), 0, i
            while j < len(lines):
                if ONELINE.match(lines[j]):
                    j += 1
                    continue
                if re.match(r"^/\w+ :", lines[j]):
                    depth += 1
                km = KEYLINE.match(lines[j])
                if km:
                    depth -= 1
                    if depth == 0:
                        p = {"key": km.group(1), "ai_type": kind, "type": OBJTYPE.get(kind, "object"),
                             "value_raw": "\n".join(lines[i:j])[:600]}
                        if kind == "Dictionary":
                            p["entries"] = parse_dict(lines[i + 1:j])
                        params.append(p)
                        break
                j += 1
            i = j
        i += 1
    return params


def baseline():
    p = WORK / "probe_baseline.ai"
    name = js(NEW_DOC, 60)
    r = js(SAVE_CLOSE % {"doc": name, "path": p.as_posix()}, 120)
    assert r == "saved", r
    return set(live_blocks(text(p)))


def invoke_wm(cmd_id, timeout=90):
    """post WM_COMMAND(menu command number) to the main window, then answer dialogs until Illustrator is idle."""
    u32.PostMessageW(main_hwnd(), 0x0111, cmd_id, 0)
    time.sleep(0.5)
    return js_watch("app.documents.length", timeout, shot_dir=str(SHOTS))


def probe(it, base, timeout=120):
    rec = {"t": time.strftime("%H:%M:%S")}
    name = js(NEW_DOC, 60)
    try:
        if it["path"].startswith("Effect/SVG Filters/") and not (it.get("invoke") or {}).get("ai_menu"):
            # per-document filter list: no command string, WM_COMMAND numbers change per document -> applyEffect
            x = '<LiveEffect name="Adobe SVG Filter Effect"><Dict data="U SVGFilterUIDName %s"/></LiveEffect>' % it["name"]
            r, e, seen = js_watch("app.activeDocument.selection[0].applyEffect(%s); 'ok';" % json.dumps(x), timeout,
                                  shot_dir=str(SHOTS))
            rec["via"] = "applyEffect"
        elif (it.get("invoke") or {}).get("ai_menu"):
            r, e, seen = js_watch('app.executeMenuCommand("%s"); "ok";' % it["invoke"]["ai_menu"], timeout,
                                  shot_dir=str(SHOTS))
            rec["via"] = "executeMenuCommand"
        else:
            r, e, seen = invoke_wm(it["extra"]["menu_cmd_id"], timeout)
            rec["via"] = "WM_COMMAND"
        rec.update(result=r, error=e, dialogs=seen)
    finally:
        f = WORK / "probes" / (re.sub(r"[^A-Za-z0-9]+", "_", it["path"])[:80] + ".ai")
        f.parent.mkdir(exist_ok=True)
        for _ in range(3):
            if not dialogs():
                break
            js_watch("1", 10, key="escape")
        rec["save"] = js(SAVE_CLOSE % {"doc": name, "path": f.as_posix()}, 180)
    if rec["save"] == "saved":
        new = [b for b in live_blocks(text(f)) if b not in base]
        rec["effects"] = [parse_block(b) for b in new]
        rec["file"] = f.as_posix()
    return rec


def main(argv):
    SHOTS.mkdir(parents=True, exist_ok=True)
    items = json.loads(HARVEST.read_text(encoding="utf-8"))["items"]
    ck = json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else {}
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    base = baseline()
    for it in items:
        if only and only not in it["path"]:
            continue
        if it["path"] in ck and "--redo" not in argv:
            continue
        if it["name"] in ("Apply Last Effect", "Last Effect", "Import SVG Filter"):
            continue  # need a previous effect / a file dialog: not probed as effects
        print(it["path"], "...", end=" ", flush=True)
        try:
            rec = probe(it, base)
        except Exception as e:  # noqa: BLE001
            rec = {"crash": str(e)[:500]}
        ck[it["path"]] = rec
        CKPT.write_text(json.dumps(ck, indent=1, ensure_ascii=False), encoding="utf-8")
        print(rec.get("dialogs"), [x["live_effect"] for x in rec.get("effects", [])], rec.get("error") or "",
              rec.get("crash", ""), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
