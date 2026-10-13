"""PGD / Illustrator: does the scripted invoke (applyEffect with the harvested simple params) change the rendering?
-> work/ai/render_check.json + work/ai/render/<item>.png

    python render_check.py [--only SUBSTR]

Per item: new document, the probe rectangle, applyEffect(LiveEffect XML built like verify_live.py), PNG24 export of
the artboard; compared with the same export of the plain rectangle (mean absolute pixel difference). A difference of 0
means the effect was stored but drew nothing different. Documents are closed without saving.
"""
import json, sys
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

from PIL import Image, ImageChops, ImageStat

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aicom import js_watch  # noqa: E402
from verify_live import LETTER, value  # noqa: E402

WORK = (PGD / "work/ai")
HARVEST = (PGD / "harvest/ai/ai_effect.json")
OUT = WORK / "render_check.json"
PNG = WORK / "render"

RENDER = r'''
var d = app.documents.add(DocumentColorSpace.RGB, 800, 600);
for (var i = d.graphicStyles.length - 1; i > 0; i--) { try { d.graphicStyles[i].remove(); } catch (e) {} }
var p = d.pathItems.rectangle(450, 250, 300, 200);
var c = new RGBColor(); c.red = 220; c.green = 60; c.blue = 40; p.fillColor = c;
var k = new RGBColor(); k.red = 20; k.green = 40; k.blue = 160; p.strokeColor = k; p.stroked = true; p.strokeWidth = 6;
var r = "rendered";
if (%(xml)s) { try { p.applyEffect(%(xml)s); } catch (e) { r = "applyEffect failed: " + String(e); } }
var o = new ExportOptionsPNG24(); o.artBoardClipping = true; o.antiAliasing = true; o.transparency = false;
try { d.exportFile(new File(File("%(png)s").fsName), ExportType.PNG24, o); } catch (e) { r += " | export failed: " + String(e); }
d.close(SaveOptions.DONOTSAVECHANGES);
r;'''


def render(xml, png):
    return js_watch(RENDER % {"xml": json.dumps(xml), "png": png.as_posix()}, 180)


def diff(a, b):
    A, B = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    if A.size != B.size:
        return None
    return round(sum(ImageStat.Stat(ImageChops.difference(A, B)).mean) / 3, 3)


def main(argv):
    PNG.mkdir(parents=True, exist_ok=True)
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    plain = PNG / "_plain.png"
    if not plain.exists():
        print("plain:", render("", plain))
    for it in json.loads(HARVEST.read_text(encoding="utf-8"))["items"]:
        name = (it.get("invoke") or {}).get("ai_live_effect")
        if not name or it["path"] in res or (only and only not in it["path"]):
            continue
        data = " ".join(f"{LETTER[p['extra']['ai_type']]} {p['key']} {value(p)}" for p in it.get("params") or []
                        if p.get("extra", {}).get("ai_type") in LETTER and "default" in p and value(p) is not None
                        and " " not in p["key"])
        xml = '<LiveEffect name="%s"><Dict data="%s"/></LiveEffect>' % (name, data)
        png = PNG / ("".join(ch if ch.isalnum() else "_" for ch in it["path"])[:80] + ".png")
        r, e, seen = render(xml, png)
        d = diff(png, plain) if png.exists() else None
        res[it["path"]] = {"result": r, "error": e, "dialogs": seen, "png": png.as_posix(), "mean_abs_diff": d}
        OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
        print(it["path"], r, e or "", "diff", d, flush=True)




OPEN_EXPORT = r'''
var d = app.open(new File(File("%(ai)s").fsName));
var o = new ExportOptionsPNG24(); o.artBoardClipping = true; o.antiAliasing = true; o.transparency = false;
var r = "rendered";
try { d.exportFile(new File(File("%(png)s").fsName), ExportType.PNG24, o); } catch (e) { r = "export failed: " + String(e); }
d.close(SaveOptions.DONOTSAVECHANGES);
r;'''


def menu_route(only_zero=True):
    """render the file the menu-command probe saved (probe_effects.py) the same way, for items whose scripted
    apply drew nothing: tells a no-op parameter set from a scripted invoke that does not work."""
    res = json.loads(OUT.read_text(encoding="utf-8"))
    ck = json.loads((WORK / "probe_ckpt.json").read_text(encoding="utf-8"))
    plain = PNG / "_plain.png"
    for path, r in res.items():
        if (only_zero and r.get("mean_abs_diff") != 0) or "menu_route_diff" in r or not ck.get(path, {}).get("file"):
            continue
        png = Path(r["png"]).with_name(Path(r["png"]).stem + "__menu.png")
        rr, e, seen = js_watch(OPEN_EXPORT % {"ai": ck[path]["file"], "png": png.as_posix()}, 180)
        r["menu_route_png"], r["menu_route_diff"] = png.as_posix(), diff(png, plain) if png.exists() else None
        r["menu_route_result"] = rr or e
        OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
        print(path, "menu route diff", r["menu_route_diff"], e or "", seen, flush=True)


if __name__ == "__main__":
    menu_route() if sys.argv[1:] == ["menu"] else main(sys.argv[1:])
