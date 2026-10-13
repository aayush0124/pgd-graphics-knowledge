"""PGD/CDR: prove effect apply paths on a scratch document -> work/cdr/apply_tests.json

    python apply_tests.py

Bitmap effects: Bitmap.ApplyBitmapEffect(undo, cmd) on the imported test photo. That call returns OK for ANY string
(an unknown effect name too), so success is judged from the pixels: 48 grid samples of Bitmap.Image.Pixel before and
after (or a change of the bitmap's pixel size). Each command runs twice with two parameter values (Document.Undo in
between) so a parameter that the command string really feeds shows up as A != B.
Vector effects: the typelib Create* call on fresh shapes, judged by the IVGEffect it returns and Shape.Effects.
The document is ours and is closed without saving.
"""
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cdr_com import Corel  # noqa: E402
from testdoc import TestDoc  # noqa: E402

OUT = HERE.parents[1] / "work" / "cdr" / "apply_tests.json"

# effect_id -> (command with value A, command with value B). Keys are the effect data source's paths (DrawUI.xml).
# "<Prefix><Path>" keys (GaussianBlurRadius=...) were tried first: the effect ran but with identical pixels for both
# values, i.e. the keys were ignored.
BITMAP = {
    "PosterizeEffect": ("PosterizeEffect Level=2", "PosterizeEffect Level=16"),
    "GaussianBlurEffect": ("GaussianBlurEffect Radius=2", "GaussianBlurEffect Radius=40"),
    "SolarizeEffect": ("SolarizeEffect Level=64", "SolarizeEffect Level=230"),
    "PixelateEffect": ("PixelateEffect Mode=Square,Width=8,Height=8,Opacity=100",
                       "PixelateEffect Mode=Square,Width=60,Height=60,Opacity=100"),
    "EmbossEffect": ("EmbossEffect Depth=2,Level=100,Direction=45,ColorMode=Gray",
                     "EmbossEffect Depth=15,Level=400,Direction=200,ColorMode=Gray"),
    "MotionBlurEffect": ("MotionBlurEffect Distance=5,Direction=0", "MotionBlurEffect Distance=80,Direction=90"),
    "ThresholdEffect": ("ThresholdEffect Low=60,High=255", "ThresholdEffect Low=200,High=255"),
    "InvertEffect": ("InvertEffect", "InvertEffect"),
}


def photo(td):
    sh = td.doc.ActiveLayer.Shapes
    for i in range(1, sh.Count + 1):
        if sh.Item(i).Type == 5:
            return sh.Item(i)


def sample(td):
    im = photo(td).Bitmap.Image
    w, h = im.Width, im.Height
    px = []
    for yi in range(1, 7):
        for xi in range(1, 9):
            c = im.Pixel(int(w * xi / 9), int(h * yi / 7))
            px.append((c.RGBRed, c.RGBGreen, c.RGBBlue))
    return {"w": w, "h": h, "px": px}


def diff(a, b):
    if (a["w"], a["h"]) != (b["w"], b["h"]):
        return f"size {a['w']}x{a['h']} -> {b['w']}x{b['h']}"
    return round(sum(abs(x - y) for p, q in zip(a["px"], b["px"]) for x, y in zip(p, q)) / (len(a["px"]) * 3), 2)


def bitmap_tests(cd, td, res):
    for eid, (ca, cb) in BITMAP.items():
        if eid in res:
            continue

        def job(app, ca=ca, cb=cb):
            base = sample(td)
            photo(td).Bitmap.ApplyBitmapEffect("PGD " + eid, ca)
            a = sample(td)
            td.doc.Undo(1)
            back = sample(td)
            photo(td).Bitmap.ApplyBitmapEffect("PGD " + eid, cb)
            b = sample(td)
            td.doc.Undo(1)
            return {"base_vs_A": diff(base, a), "A_vs_B": diff(a, b), "undo_restores": diff(base, back) == 0}

        try:
            r = cd.call(job, timeout=180, note=eid)
        except Exception as e:  # noqa: BLE001
            r = {"error": "call failed: " + str(e)[:160]}
        applied = r.get("base_vs_A") not in (None, 0, 0.0)
        sens = r.get("A_vs_B") not in (None, 0, 0.0)
        r["cmd"] = ca if applied else None
        r["result"] = (f"Bitmap.ApplyBitmapEffect('{ca}') on the test photo: pixels base->A {r.get('base_vs_A')}, "
                       f"A('{ca.split(' ', 1)[-1]}') vs B('{cb.split(' ', 1)[-1]}') {r.get('A_vs_B')}: "
                       + ("APPLIED, parameter string read" if applied and sens else
                          "APPLIED, but the two parameter strings gave the same pixels" if applied else
                          "NO pixel change: command string not recognised"))
        if not applied:
            r["error"] = ("ApplyBitmapEffect returned OK but changed no pixels with '" + ca +
                          "': command-string keys for this effect not established")
        res[eid] = r
        OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(eid, r["result"], flush=True)


def vector_tests(cd, td, res):
    def fresh(app, kind="rect", x=1.0):
        lay = td.doc.ActiveLayer
        if kind == "ellipse":
            s = lay.CreateEllipse2(x + 0.6, 5.0, 0.5)
        else:
            s = lay.CreateRectangle2(x, 4.5, 1.2, 0.9)
        s.Fill.UniformColor.RGBAssign(30, 90, 200)
        return s

    def red(app):
        return app.CreateRGBColor(220, 30, 30)

    T = {
        "vector:Contour": lambda app: fresh(app).CreateContour(1, 0.05, 3, 0, None, red(app), None, 0, 0, 2, 4, 0.0),
        "vector:Blend": lambda app: fresh(app).CreateBlend(fresh(app, "ellipse", 4.0), 8, 0, 0, 0.0, 0.0, False,
                                                           None, False, 0, 0, False),
        "vector:Extrude": lambda app: fresh(app).CreateExtrude(0, 0, 3.0, 3.0, 20.0, 0, None, None, 0.0, 45.0, None,
                                                               False),
        "vector:Envelope": lambda app: fresh(app).CreateEnvelope(1, 2, False),
        "vector:DropShadow": lambda app: fresh(app).CreateDropShadow(0, 60, 10, 0.08, -0.08, None, 4, 0, -45.0,
                                                                     1.0, 1, 0),
        "vector:InnerShadow": lambda app: fresh(app).CreateInnerShadow(60, 10, 0.05, -0.05, None, 4, 0, 0, -1.0),
        "vector:Perspective": lambda app: fresh(app).CreatePerspective(8.0, 5.0),
        "vector:Distort:PushPull": lambda app: (lambda s: s.CreatePushPullDistortion(s.CenterX, s.CenterY, 40))(
            fresh(app)),
        "vector:Distort:Zipper": lambda app: (lambda s: s.CreateZipperDistortion(s.CenterX, s.CenterY, 30, 10,
                                                                                 False, False, False))(fresh(app)),
        "vector:Distort:Twister": lambda app: (lambda s: s.CreateTwisterDistortion(s.CenterX, s.CenterY, 180.0))(
            fresh(app)),
        "lens:cdrLensMagnify": lambda app: fresh(app).CreateLens(0, 2.0, None, None, 0),
        "lens:cdrLensFishEye": lambda app: fresh(app).CreateLens(1, 100.0, None, None, 0),
        "lens:cdrLensInvert": lambda app: fresh(app).CreateLens(5, 50.0, None, None, 0),
        "lens:cdrLensHeatMap": lambda app: fresh(app).CreateLens(8, 50.0, None, None, 0),
        "vector:Transparency:Uniform": lambda app: (lambda s: (s.Transparency.ApplyUniformTransparency(50), s)[1])(
            fresh(app)),
        "vector:Transparency:Fountain": lambda app: (lambda s: (s.Transparency.ApplyFountainTransparency(
            0, 100, 1, 0.0, 0, 0, 50, 0.0, 0.0), s)[1])(fresh(app)),
        "vector:PowerClip": lambda app: (lambda c, s: (s.AddToPowerClip(c, -2), c)[1])(fresh(app, "rect", 7.0),
                                                                                       fresh(app, "ellipse", 7.0)),
    }
    for iid, fn in T.items():
        if iid in res:
            continue

        def job(app, fn=fn):
            r = fn(app)
            out = {"returned": r._oleobj_.GetTypeInfo().GetDocumentation(-1)[0]}
            if out["returned"] in ("IVGEffect", "Effect"):
                out["effect_type"] = r.Type
                out["shape_effects"] = r.Parent.Parent.Effects.Count
            else:
                try:  # a shape (transparency / powerclip container)
                    out["shape_type"] = r.Type
                    try:
                        out["transparency_type"] = r.Transparency.Type
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        out["powerclip_contents"] = r.PowerClip.Shapes.Count
                    except Exception:  # noqa: BLE001
                        pass
                except Exception as e:  # noqa: BLE001
                    out["readback_error"] = str(e)[:120]
            return out

        try:
            r = cd.call(job, timeout=120, note=iid)
            r["result"] = "APPLIED: " + ", ".join(f"{k}={v}" for k, v in r.items())
        except Exception as e:  # noqa: BLE001
            r = {"error": "apply call failed: " + str(e)[:200], "result": "FAILED"}
        res[iid] = r
        OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(iid, r["result"], flush=True)


def main():
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    cd = Corel()
    td = TestDoc(cd)
    try:
        bitmap_tests(cd, td, res)
        vector_tests(cd, td, res)
    finally:
        print("closed:", td.close())


if __name__ == "__main__":
    main()
