"""PGD/CDR: scratch test document (rectangle + imported test photo) and a pixel-diff check, for apply tests and
gallery renders. Every call goes through cdr_com.Corel.call (timeout + dialog dismissal).

    from testdoc import TestDoc
    td = TestDoc(cd)                     # new document we own: td.rect, td.photo (shapes), td.doc
    png = td.snapshot(shape, "name")     # export that shape alone (FAILS on this install: Document.ExportBitmap
                                         # and Document.Export return E_FAIL; prove changes with Bitmap.Image.Pixel)
    td.changed(png_a, png_b)             # mean absolute pixel difference (0 = identical)
    td.close()                           # close WITHOUT saving
"""
import time
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

WORK = Path(__file__).resolve().parents[2] / "work" / "cdr"
SNAP = WORK / "snap"
PHOTO = (PGD / "media/test_photo.png")
CDR_PNG, CDR_SELECTION = 802, 2


class TestDoc:
    def __init__(self, cd):
        self.cd = cd
        SNAP.mkdir(parents=True, exist_ok=True)

        def make(app):
            doc = app.CreateDocument()
            lay = doc.ActiveLayer
            rect = lay.CreateRectangle2(1, 1, 3, 2)
            rect.Fill.UniformColor.RGBAssign(200, 40, 40)
            n = lay.Shapes.Count
            lay.Import(str(PHOTO.resolve()), 0, None)   # returns void; Options must be None (VT_DISPATCH)
            photo = lay.Shapes.Item(1) if lay.Shapes.Count > n else None
            if photo is not None:
                # test_photo.png carries an aspect-only pHYs chunk (unit 0): Corel imports it ~1.6e-5 in wide, which
                # makes every export of it fail with E_FAIL. Give it a real size (16:9) next to the rectangle.
                photo.SetSize(3.2, 1.8)
                photo.SetPosition(4.5, 3.0)
            return doc, rect, photo, doc.Unit
        self.doc, self.rect, self.photo, self.unit = cd.call(make, timeout=180, note="testdoc")
        self.title = self.cd.call(lambda a: self.doc.Title, 30)

    def snapshot(self, shape, name, res=48):
        out = SNAP / f"{name}.png"
        out.unlink(missing_ok=True)

        def job(app):
            self.doc.ClearSelection()
            shape.CreateSelection()
            # every optional VT_DISPATCH arg must be passed as None (pywin32 cannot convert the typelib default 0)
            f = self.doc.ExportBitmap(str(out), CDR_PNG, CDR_SELECTION, 4, 0, 0, res, res, 1, False, False, True,
                                      False, 0, None, None)
            f.Finish()
            return out.exists()
        self.cd.call(job, timeout=120, note="snapshot " + name)
        return out

    @staticmethod
    def changed(a, b):
        from PIL import Image, ImageChops
        if not (Path(a).exists() and Path(b).exists()):
            return None
        ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
        if ia.size != ib.size:
            return 999.0  # geometry changed (e.g. contour / shadow grows the selection)
        d = ImageChops.difference(ia, ib)
        h = d.histogram()
        tot = sum(i % 256 * c for i, c in enumerate(h))
        return round(tot / (ia.size[0] * ia.size[1] * 3), 3)

    def close(self):
        def job(app):
            self.doc.Dirty = False
            self.doc.Close()
            return True
        try:
            return self.cd.call(job, timeout=60, note="close testdoc")
        except Exception as e:  # noqa: BLE001
            return str(e)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cdr_com import Corel
    cd = Corel()
    td = TestDoc(cd)
    try:  # a failure between create and close leaked a dirty Untitled document once: always close in finally
        print("unit", td.unit, "title", td.title, "photo type", cd.call(lambda app: td.photo.Type, 20),
              "size", cd.call(lambda app: (td.photo.SizeWidth, td.photo.SizeHeight), 20))
        a = td.snapshot(td.photo, "selftest_a")   # NB ExportBitmap / Export fail with E_FAIL on this install
        b = td.snapshot(td.photo, "selftest_b")
        assert td.changed(a, b) == 0, "two exports of an untouched shape must be identical"
    finally:
        print("closed", td.close())
