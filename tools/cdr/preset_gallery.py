"""PGD/CDR: render the cdr_preset gallery -> gallery/cdr_preset/<key>.png + index.json / failed.json / not_renderable.json

    python preset_gallery.py                 # every phase, resumable (skips ids already in one of the three json files)
    python preset_gallery.py --phase file    # no app: palettes, image files, embedded thumbnails, not-renderable
    python preset_gallery.py --phase app     # CorelDRAW 2024 (one scratch document we own, closed unsaved)
    python preset_gallery.py --retry-failed  # drop failed.json entries first

key = sha1(item id)[:12]. Every harvested item ends in exactly one of index.json / failed.json / not_renderable.json.
App renders: shapes are built in our own scratch document, the preset is applied through the object model, the
selection is exported with Document.ExportBitmap (PNG, transparent) and composited on a neutral grey (transparency
presets on a checker). Images Corel ships as CPT (Photo-Paint) are converted by importing them into the scratch doc.
"""
import argparse, hashlib, io, json, math, os, re, struct, sys, time, zipfile, zlib
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HARVEST = ROOT / "harvest" / "cdr" / "cdr_preset.json"
OUT = ROOT / "gallery" / "cdr_preset"
SCR = ROOT / "work" / "cdr" / "gallery"
CD = Path(r"C:/Program Files/Corel/CorelDRAW Graphics Suite/25")
PHOTO = ROOT / "media" / "plate_photo.png"
BG = (222, 222, 222)
SIZE = 320


def _file(it):
    """invoke.file; the harvest writes per-user folders as %USERPROFILE% (no machine path in the public repo)."""
    f = (it.get("invoke") or {}).get("file")
    return f.replace("%USERPROFILE%", str(Path.home())) if f else f


def key(iid):
    return hashlib.sha1(iid.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- state
class State:
    def __init__(self, retry_failed=False):
        OUT.mkdir(parents=True, exist_ok=True)
        SCR.mkdir(parents=True, exist_ok=True)
        rd = lambda n, d: json.loads((OUT / n).read_text(encoding="utf-8")) if (OUT / n).exists() else d
        self.index = {r["id"]: r for r in rd("index.json", [])}
        self.failed = rd("failed.json", {})
        self.nr = rd("not_renderable.json", {})
        if retry_failed:
            self.failed = {}
        # an index row whose PNG vanished is redone
        for iid in [i for i, r in self.index.items() if not (OUT / f"{r['key']}.png").exists()]:
            del self.index[iid]

    def done(self, iid):
        return iid in self.index or iid in self.failed or iid in self.nr

    def put(self, it, img, how):
        k = key(it["id"])
        fit(img).save(OUT / f"{k}.png")
        self.failed.pop(it["id"], None)
        self.index[it["id"]] = {"key": k, "id": it["id"], "name": it["name"], "category": it["category"], "how": how}

    def fail(self, it, err):
        self.failed[it["id"]] = str(err)[:400]

    def not_renderable(self, it, reason):
        self.nr[it["id"]] = reason

    def save(self):
        (OUT / "index.json").write_text(json.dumps(list(self.index.values()), indent=1, ensure_ascii=False), "utf-8")
        (OUT / "failed.json").write_text(json.dumps(self.failed, indent=1, ensure_ascii=False), "utf-8")
        (OUT / "not_renderable.json").write_text(json.dumps(self.nr, indent=1, ensure_ascii=False), "utf-8")


# ---------------------------------------------------------------- image helpers
def checker(w, h, s=16):
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    for y in range(0, h, s):
        for x in range(0, w, s):
            if (x // s + y // s) % 2:
                d.rectangle([x, y, x + s - 1, y + s - 1], fill=(200, 200, 200))
    return im


def fit(img, margin=12, bg=BG):
    """Fit into 320x320 on a neutral background; small sources are enlarged (nearest for pixel-art sizes)."""
    if img.mode in ("P", "1", "L", "LA", "I", "I;16", "CMYK"):
        img = img.convert("RGBA")
    box = SIZE - 2 * margin
    w, h = img.size
    s = box / max(w, h)
    if abs(s - 1) > 1e-3:
        rs = Image.NEAREST if (s > 2 and max(w, h) <= 64) else Image.LANCZOS
        img = img.resize((max(1, round(w * s)), max(1, round(h * s))), rs)
    can = bg.copy() if isinstance(bg, Image.Image) else Image.new("RGB", (SIZE, SIZE), bg)
    x, y = (SIZE - img.size[0]) // 2, (SIZE - img.size[1]) // 2
    if img.mode == "RGBA":
        can.paste(img, (x, y), img)
    else:
        can.paste(img.convert("RGB"), (x, y))
    return can


def dib_to_image(dib):
    """BITMAPINFOHEADER + pixels (24/32-bit, bottom-up unless height < 0) -> PIL image."""
    hs, w, h, planes, bpp, comp = struct.unpack_from("<IiiHHI", dib, 0)
    clr = struct.unpack_from("<I", dib, 32)[0]
    off = hs + (clr * 4 if bpp <= 8 else 0)
    if bpp <= 8:
        n = clr or (1 << bpp)
        pal = [tuple(dib[hs + 4 * i + 2 - c] for c in range(3)) for i in range(n)]
        off = hs + 4 * n
    stride = ((w * bpp + 31) // 32) * 4
    ah = abs(h)
    raw = dib[off:off + stride * ah]
    if bpp == 24:
        im = Image.frombuffer("RGB", (w, ah), raw, "raw", "BGR", stride, -1 if h > 0 else 1)
    elif bpp == 32:
        im = Image.frombuffer("RGBA", (w, ah), raw, "raw", "BGRA", stride, -1 if h > 0 else 1).convert("RGB")
    elif bpp == 8:
        im = Image.frombuffer("P", (w, ah), raw, "raw", "P", stride, -1 if h > 0 else 1)
        im.putpalette([v for p in pal for v in p])
    else:
        raise ValueError(f"unsupported DIB bpp {bpp}")
    return im.copy()


def pst_thumb(path):
    b = Path(path).read_bytes()
    n = struct.unpack_from("<H", b, 4)[0]
    i = b.find(b"\x78\x5e", 6 + n)
    if i < 0:
        i = b.find(b"\x78\x9c", 6 + n)
    if i < 0:
        raise ValueError("no zlib thumbnail in the .pst")
    return dib_to_image(zlib.decompressobj().decompress(b[i:]))


def npm_thumb(path):
    b = Path(path).read_bytes()
    i = b.find(b"CCustomNaturalMediaStrokeImage")
    if i < 0:
        raise ValueError("no CCustomNaturalMediaStrokeImage record")
    j = b.find(b"\x28\x00\x00\x00", i)   # BITMAPINFOHEADER.biSize = 40
    return dib_to_image(b[j:])


# ---------------------------------------------------------------- colours
def lab2rgb(L, a, b):
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    f = lambda t: t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787
    X, Y, Z = 0.95047 * f(fx), 1.0 * f(fy), 1.08883 * f(fz)
    r = 3.2406 * X - 1.5372 * Y - 0.4986 * Z
    g = -0.9689 * X + 1.8758 * Y + 0.0415 * Z
    bb = 0.0557 * X - 0.2040 * Y + 1.0570 * Z
    gam = lambda c: 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return tuple(max(0, min(255, round(gam(c) * 255))) for c in (r, g, bb))


def cmyk2rgb(c, m, y, k):
    return tuple(round(255 * (1 - v) * (1 - k)) for v in (c, m, y))


def to_rgb(cs, tints):
    t = [float(x) for x in tints.split(",") if x.strip() != ""]
    cs = (cs or "").upper()
    if cs in ("RGB", "SRGB", "ADOBERGB", "HKSRGB", "RGB255") and len(t) >= 3:
        return tuple(round(max(0, min(1, v)) * 255) for v in t[:3])
    if cs in ("CMYK", "CMYK255") and len(t) >= 4:
        return cmyk2rgb(*[max(0, min(1, v)) for v in t[:4]])
    if cs == "GRAY" and t:
        g = round(max(0, min(1, t[0])) * 255)
        return (g, g, g)
    if cs == "LAB" and len(t) >= 3:
        return lab2rgb(t[0] * 100, t[1] * 255 - 128, t[2] * 255 - 128)
    if cs == "HEXACHROME" and len(t) >= 6:   # C M Y K Orange Green, folded into CMY
        c, m, y, k, o, g = t[:6]
        return cmyk2rgb(min(1, c + g * 0.8), min(1, m + o * 0.5), min(1, y + o * 0.9 + g * 0.9), k)
    return None


PREF = ("SRGB", "RGB", "ADOBERGB", "HKSRGB", "LAB", "CMYK", "HEXACHROME", "GRAY")


def palette_colors(path):
    x = ET.parse(path).getroot()
    spaces = {}
    cs_el = x.find("colorspaces")
    if cs_el is not None:
        for s in cs_el.findall("cs"):
            alts = {(c.get("cs") or "").upper(): c.get("tints") for c in s.iter("color")}
            spaces[s.get("name")] = alts
    out = []
    cols = x.find("colors")
    for c in (cols.iter("color") if cols is not None else []):
        cs, tints = c.get("cs"), c.get("tints") or ""
        rgb = to_rgb(cs, tints)
        if rgb is None and cs in spaces:
            for p in PREF:
                if p in spaces[cs]:
                    rgb = to_rgb(p, spaces[cs][p])
                    if rgb is not None:
                        tint = float((tints or "1").split(",")[0] or 1)
                        rgb = tuple(round(255 - (255 - v) * tint) for v in rgb)  # spot tint toward white
                        break
        if rgb is not None:
            out.append(rgb)
    return out


def swatch_strip(cols):
    n = len(cols)
    if n > 256:  # sample evenly, keep order
        cols = [cols[round(i * (n - 1) / 255)] for i in range(256)]
        n = 256
    k = max(1, math.ceil(math.sqrt(n)))
    rows = math.ceil(n / k)
    cell = (SIZE - 24) // k
    im = Image.new("RGB", (cell * k, cell * rows), BG)
    d = ImageDraw.Draw(im)
    for i, c in enumerate(cols):
        x, y = (i % k) * cell, (i // k) * cell
        d.rectangle([x + 1, y + 1, x + cell - 2, y + cell - 2], fill=c)
    return im


# ---------------------------------------------------------------- not renderable
NOT_VISUAL = {
    "New Document Preset": "new-document page-size / colour preset: settings, no look of its own",
    "Template": None,  # rendered from the template's stored first-page preview
    "Label Template Library": "label stock geometry library (page layout data), no look of its own",
    "Color Profile": "ICC colour profile: colour-management data, no look of its own",
    "Color Management Preset": "colour-management settings preset, no look of its own",
    "Color Management Preset (dialog)": "colour-management settings preset, no look of its own",
    "Export Preset": "export file-format settings, no look of its own",
    "Imposition Layout": "print imposition layout, no look of its own",
    "Print Style": "print settings style, no look of its own",
    "Preflight Style": "preflight rule set, no look of its own",
    "Workspace": "UI workspace layout, not a design preset",
    "Find and Replace Preset": "Find and Replace query, not a visual preset",
    "Find and Replace Preset (docker)": "Find and Replace query, not a visual preset",
    "Dimension Preset": "dimension-line tool setting (annotation), listed as not visual",
    "Callout Preset": "callout tool setting (annotation), listed as not visual",
}
NOT_DECODED = {
    "Painterly Paper Library": "binary Painter paper library (.paper): no decoder, no COM call renders it",
    "Painterly Gradient Library": "binary Painter gradient library (.gradient): no decoder, no COM call renders it",
    "Painterly Flow Map Library": "binary Painter flow-map library (.flowmap): no decoder, no COM call renders it",
    "Painterly Color Set": "binary Painter colour set (.colors): no decoder, no COM call renders it",
    "Shear Map": "binary .shr shear curve: format not decoded and the Shear effect's command keys are not established",
}

PIL_IMAGE_CATS = {"Brush Image", "Texture Image", "Bump Map Image", "Canvas Image", "Displace Map",
                  "Frame Effect Image", "Photo Frame", "Brush Texture", "Image List"}
PST_CATS = {"Blend Preset", "Contour Preset", "Distortion Preset", "Envelope Preset", "Drop Shadow Preset",
            "Inner Shadow Preset", "Extrude Preset", "Brush Preset (user)"}


def file_phase(st, items):
    for it in items:
        if st.done(it["id"]):
            continue
        c = it["category"]
        f = _file(it)
        try:
            if c in NOT_VISUAL and NOT_VISUAL[c]:
                st.not_renderable(it, NOT_VISUAL[c])
            elif c in NOT_DECODED:
                st.fail(it, NOT_DECODED[c])
            elif c == "Color Palette":
                cols = palette_colors(f)
                if not cols:
                    st.not_renderable(it, "dynamic palette: the file stores no colours (filled from the open "
                                          "document at run time)")
                else:
                    st.put(it, swatch_strip(cols), "swatch strip")
            elif c == "Template":
                with zipfile.ZipFile(f) as z:
                    nm = "previews/page1.png" if "previews/page1.png" in z.namelist() else "previews/thumbnail.png"
                    st.put(it, Image.open(io.BytesIO(z.read(nm))).convert("RGBA"), "file image")
            elif c in PIL_IMAGE_CATS and Path(f).suffix.lower() != ".cpt":
                try:
                    im = Image.open(f)
                    im.load()
                except Exception:  # noqa: BLE001
                    continue   # PIL cannot read it: left for the app phase (CorelDRAW import, like CPT)
                st.put(it, im, "file image")
            elif c in PST_CATS:
                st.put(it, pst_thumb(f), "embedded thumbnail")
            elif c == "Artistic Media Sprayer":
                # Layer.Import of a sprayer .cdr deadlocked CorelDRAW 2024 twice on 2026-10-04 (UI thread not
                # responding, CPU and read bytes flat): the package's own page thumbnail is used instead
                with zipfile.ZipFile(f) as z:
                    im = Image.open(io.BytesIO(z.read("metadata/thumbnails/page1.bmp"))).convert("RGB")
                from PIL import ImageChops
                bb = ImageChops.difference(im, Image.new("RGB", im.size, (255, 255, 255))).convert("L").point(
                    lambda v: 255 if v > 12 else 0).getbbox()   # the objects sit small on a white page: crop
                if bb:
                    im = im.crop((max(0, bb[0] - 4), max(0, bb[1] - 4), min(im.width, bb[2] + 4),
                                  min(im.height, bb[3] + 4)))
                st.put(it, im, "embedded thumbnail")
            elif c == "Artistic Media Preset":
                st.put(it, npm_thumb(f), "embedded thumbnail")
            elif c == "Painterly Brush":
                png = Path(f).with_suffix(".png")
                if not png.exists():
                    raise FileNotFoundError(f"no stroke preview {png.name} next to the brush XML")
                st.put(it, Image.open(png).convert("RGBA"), "embedded thumbnail")
            elif c == "Fill":
                with zipfile.ZipFile(f) as z:
                    nm = next(n for n in z.namelist() if n.startswith("previews/"))
                    st.put(it, Image.open(io.BytesIO(z.read(nm))).convert("RGB"), "embedded thumbnail")
            elif c == "Tone Curve Preset":
                # .crv = COREL PhotoPaint 8 tone curve: five 266-byte records (10-byte header + 256-entry LUT) end
                # the file; the first is the master curve (the R/G/B ones are identity in every shipped file).
                # No object-model call loads a .crv, so the LUT itself is applied to the test photo.
                b = Path(f).read_bytes()
                lut = list(b[len(b) - 1320:len(b) - 1064])
                ph = Image.open(PHOTO).convert("RGB").resize((640, 360), Image.LANCZOS)
                st.put(it, ph.point(lut * 3), "applied: the .crv master tone-curve LUT (256 entries read from "
                                              "the file) applied to the test photo with PIL")
            elif c == "Line Style Library":
                st.put(it, line_styles(it), "swatch strip")
            elif c == "Outline Width Library":
                st.put(it, outline_widths(it), "swatch strip")
        except Exception as e:  # noqa: BLE001
            st.fail(it, f"{type(e).__name__}: {e}")
    st.save()


def line_styles(it):
    ents = (it.get("extra") or {}).get("entries") or []
    im = Image.new("RGB", (600, 26 * len(ents) + 10), BG)
    d = ImageDraw.Draw(im)
    for r, e in enumerate(ents):
        y, x, u = 14 + r * 26, 10, 5
        while x < 590:
            for dl, gl in zip(e["dashes"], e["gaps"]):
                d.line([x, y, min(590, x + dl * u), y], fill=(20, 20, 20), width=5)
                x += (dl + gl) * u
    return im


def outline_widths(it):
    ents = [e for e in (it.get("extra") or {}).get("entries") or [] if "value" in e]
    ents = ents[:12]  # first unit block (inches): 0.007 .. 0.5 in
    im = Image.new("RGB", (600, 600), BG)
    d = ImageDraw.Draw(im)
    for r, e in enumerate(ents):
        w = max(1, round(float(e["value"]) * 96))
        y = 25 + r * 48
        d.line([20, y, 580, y], fill=(20, 20, 20), width=w)
    return im


# ---------------------------------------------------------------- app phase
class Scene:
    """Our own scratch document; every render builds shapes, exports the selection and deletes them again."""

    def __init__(self):
        sys.path.insert(0, str(HERE))
        from cdr_com import Corel
        self.cd = Corel()
        self.small_photo = SCR / "plate_photo_640.png"
        if not self.small_photo.exists():
            im = Image.open(PHOTO).convert("RGB").resize((640, 360), Image.LANCZOS)
            im.save(self.small_photo, dpi=(96, 96))
        self.st = {}

        def mk(a):
            doc = a.CreateDocument()
            doc.Unit = 1  # cdrInch
            self.st["doc"] = doc
            self.st["app"] = a
            return doc.Title
        self.title = self.cd.call(mk, 120, note="gallery doc")
        self.n = 0

    def call(self, fn, timeout=120, note=""):
        return self.cd.call(fn, timeout=timeout, note=note)

    @property
    def doc(self):
        return self.st["doc"]

    def clear(self, a):
        lay = self.doc.ActiveLayer
        for i in range(lay.Shapes.Count, 0, -1):
            lay.Shapes.Item(i).Delete()

    def export(self, a, shapes, px=640, name="x"):
        doc = self.doc
        doc.ClearSelection()
        for s in shapes:
            s.AddToSelection()
        sr = doc.SelectionRange
        w, h = sr.SizeWidth, sr.SizeHeight
        res = max(10, min(1200, int(px / max(w, h, 1e-3))))
        self.n += 1
        p = SCR / f"tmp_{self.n % 4}.png"
        p.unlink(missing_ok=True)
        f = doc.ExportBitmap(str(p), 802, 2, 4, 0, 0, res, res, 1, False, True, True, False, 0, None, None)
        f.Finish()
        return str(p)

    def render(self, build, px=640, timeout=180, note=""):
        """build(a) -> list of shapes to export. Returns RGBA PIL image."""
        def job(a):
            self.clear(a)
            shapes = build(a)
            p = self.export(a, shapes, px)
            return p
        try:
            p = self.call(job, timeout, note)
        except Exception as e:  # noqa: BLE001
            if "CallTimeout" not in type(e).__name__:   # a wedged app would only time out again
                try:
                    self.call(lambda a: self.clear(a), 60, "clear")
                except Exception:  # noqa: BLE001
                    pass
            raise
        self.call(lambda a: self.clear(a), 60, "clear")
        im = Image.open(p)
        im.load()
        return im.convert("RGBA")

    def close(self):
        def job(a):
            self.doc.Dirty = False
            self.doc.Close()
            return True
        try:
            return self.call(job, 60, "close gallery doc")
        except Exception as e:  # noqa: BLE001
            return str(e)


def color_from(a, s):
    """Corel colour string 'RGB255,USER,r,g,b,100,guid' / 'CMYK,USER,c,m,y,k,100,guid' -> IVGColor."""
    p = s.split(",")
    m = p[0].upper()
    v = []
    for x in p[2:]:   # numbers up to the trailing palette guid
        try:
            v.append(float(x))
        except ValueError:
            break
    if m == "RGB255":
        return a.CreateRGBColor(int(v[0]), int(v[1]), int(v[2]))
    if m in ("CMYK", "CMYK255"):
        k = 1 if m == "CMYK" else 100 / 255
        return a.CreateCMYKColor(*[int(round(x * k)) for x in v[:4]])
    if m == "GRAY" or m == "GRAYSCALE":
        return a.CreateGrayColor(int(v[0]))
    c = a.CreateColor()
    c.StringAssign(s)
    return c


def s_curve(a, doc, x0=1.0, y0=3.0, x1=7.0):
    crv = a.CreateCurve(doc)
    sp = crv.CreateSubPath(x0, y0)
    sp.AppendCurveSegment2(x1, y0, x0 + 2.0, y0 + 2.5, x0 + 4.0, y0 - 2.5)
    return doc.ActiveLayer.CreateCurve(crv)


def app_phase(st, items, cats=None, limit=None, all_items=None):
    todo = [it for it in items if not st.done(it["id"]) and (cats is None or it["category"] in cats)]
    if not todo:
        return
    sc = Scene()
    print("scene", sc.title, "todo", len(todo), flush=True)
    t0 = time.time()
    fountain = json.loads((CD / "Custom Data" / "FountainFills.cdss").read_text(encoding="utf-8-sig"))["fill"]
    transp = json.loads((CD / "Custom Data" / "Transparency.cdss").read_text(encoding="utf-8-sig"))["transparency"]
    try:
        for n, it in enumerate(todo[:limit] if limit else todo, 1):
            c = it["category"]
            f = _file(it)
            fn = HANDLERS.get(c)
            if fn is None:
                continue
            try:
                img, how = fn(sc, it, f, dict(fountain=fountain, transp=transp, items=all_items or items))
                st.put(it, img, how)
            except Exception as e:  # noqa: BLE001
                st.fail(it, f"{type(e).__name__}: {e}")
                if "CallTimeout" in type(e).__name__:
                    # the app is wedged (a modal or a deadlock): it is ours, so kill it and start a fresh scene
                    st.save()
                    print("CallTimeout on", it["id"], "-> restarting CorelDRAW", flush=True)
                    sc.cd.kill()
                    time.sleep(5)
                    _cache.clear()
                    sc = Scene()
            if n % 10 == 0:
                st.save()
                print(f"{n}/{len(todo)} {time.time() - t0:.0f}s ok={len(st.index)} failed={len(st.failed)}",
                      flush=True)
    finally:
        st.save()
        print("closed", sc.close(), flush=True)
        if sc.cd.pids:   # quit the CorelDRAW this run started (by its pid); an attached one is left running
            print("killed our CorelDRAW", sc.cd.kill(), flush=True)


# --- handlers: (scene, item, file, ctx) -> (PIL image, how)
def _import(sc, f):
    lay = sc.doc.ActiveLayer
    lay.Import(str(Path(f).resolve()), 0, None)
    s = lay.Shapes.Item(1)
    if s.SizeWidth < 0.01 or s.SizeHeight < 0.01:  # aspect-only pHYs imports ~1e-5 in wide: give it a real size
        s.SetSize(4.0, 4.0 * s.SizeHeight / max(s.SizeWidth, 1e-9))
    return s


def _photo(sc):
    s = _import(sc, sc.small_photo)
    s.SetSize(4.0, 2.25)
    return s


def h_cpt(sc, it, f, ctx):
    return sc.render(lambda a: [_import(sc, f)], note="cpt " + it["name"]), "file image"


def cmx_disp(path):
    """the DISP preview chunk of a .cmx (RIFF) brush file -> PIL image (a BITMAPINFOHEADER DIB within its first bytes)"""
    d = Path(path).read_bytes()
    pos = 12
    while pos + 8 <= len(d):
        cid, sz = d[pos:pos + 4], struct.unpack_from("<I", d, pos + 4)[0]
        if cid == b"DISP":
            c = d[pos + 8:pos + 8 + sz]
            off = next((o for o in range(12) if len(c) >= o + 40 and struct.unpack_from("<I", c, o)[0] == 40), None)
            if off is None:
                raise ValueError("DISP chunk without a BITMAPINFOHEADER")
            return dib_to_image(c[off:])
        pos += 8 + sz + (sz & 1)
    raise ValueError("no DISP chunk in the .cmx")


def blank(im):
    """True when an exported RGBA render shows nothing (every pixel transparent)"""
    return im.mode == "RGBA" and im.getchannel("A").getbbox() is None


def h_brush(sc, it, f, ctx):
    # 2026-10-13: multi-part brushes were combined into ONE curve with the first filled part's fill, so overlapping parts
    # punched holes (even-odd), white highlight parts painted the whole stroke white (splatter11) and one came out empty
    # (splatter10). Now every part is mapped on its own, in the whole brush's frame, and keeps its own fill and outline.
    def build(a):
        b = _import(sc, f)
        path = s_curve(a, sc.doc)
        sp = path.Curve.SubPaths.Item(1)
        L = sp.Length
        h = min(1.2, max(0.25, L * b.SizeHeight / max(b.SizeWidth, 1e-6)))
        b.SetSize(L, h)
        frame = (b.LeftX, b.BottomY, b.SizeWidth, b.SizeHeight)
        if b.Type == 7:
            ps = b.UngroupAllEx()
            parts = [ps.Item(i) for i in range(1, ps.Count + 1)]
        else:
            parts = [b]
        out = []
        for p in parts:
            if p.Type != 3:
                p.ConvertToCurves()
            p.Curve.CopyAssign(framed_map(p.Curve, frame, sp))
            out.append(p)
        path.Delete()
        return out
    im = None
    try:
        im = sc.render(build, note="brush " + it["name"])
    except Exception as e:  # noqa: BLE001
        if "CallTimeout" in type(e).__name__:
            raise
        why = f"{type(e).__name__}: {e}"[:160]
    else:
        why = "the mapped artwork exported empty"
    if im is not None and not blank(im):
        return im, ("applied: the brush stroke artwork (.cmx) mapped along an S-curve with "
                    "Curve.CreateCurveMappedToStroke (what Artistic Media Brush does); each part of a multi-part brush "
                    "mapped in the whole brush's frame with its own fill and outline")
    return cmx_disp(f), f"embedded thumbnail (the .cmx DISP preview; the S-curve render failed: {why})"


def framed_map(curve, frame, sp, eps=1e-4):
    """Curve.CreateCurveMappedToStroke maps a curve's OWN bounding box onto the stroke, so one part of a multi-part
    brush mapped alone is stretched to the whole stroke. Two marker squares (eps wide) at the corners of the whole
    brush's frame (x, y, w, h) give every part that bounding box; after mapping, the subpaths that small are deleted.
    Tried and dropped on 2026-10-13: the frame as ONE rectangle subpath deleted by index (the mapping reorders
    subpaths: the wrong one went and the frame band showed, splatter11 / 13), and
    CreateCurveMappedToStrokeAndReferenceLine (bent every part into a bowl smear, not along the S-curve)."""
    c = curve.GetCopy()
    x, y, w, h = frame
    for px, py in ((x, y), (x + w, y + h)):
        c.AppendSubpathRectangle(px, py + eps, px + eps, py)   # left, top, right, bottom
    m = c.CreateCurveMappedToStroke(sp, 1.0, False)
    tiny = [i for i in range(1, m.SubPaths.Count + 1)
            if max(m.SubPaths.Item(i).SizeWidth, m.SubPaths.Item(i).SizeHeight) < 50 * eps]
    for i in reversed(tiny):
        m.SubPaths.Item(i).Delete()
    return m


def h_fountain(sc, it, f, ctx):
    name = it["id"].split("#", 1)[1]
    p = ctx["fountain"][name]

    def build(a):
        r = sc.doc.ActiveLayer.CreateRectangle2(1.0, 1.0, 4.0, 2.5)
        r.Outline.SetNoOutline()
        ff = r.Fill.ApplyFountainFill(color_from(a, p["primaryColor"]), color_from(a, p["secondaryColor"]),
                                      int(p.get("fountainType", 1)), float(p.get("angle", 0)),
                                      int(p.get("numSteps", 0)), int(p.get("padding", 0)),
                                      int(p.get("rateValue", 50)), int(p.get("mode", 0)),
                                      float(p.get("xCenterOffset", 0)), float(p.get("yCenterOffset", 0)))
        for ic in p.get("intermediateColors") or []:
            pos, col = ic.split(":", 1)
            ff.Colors.Add(color_from(a, col), int(pos))
        return [r]
    return (sc.render(build, note="fountain " + name),
            "applied: Fill.ApplyFountainFill on a 4x2.5 in rectangle with the preset colours, type, angle, "
            "midpoint, centre offset and intermediate colour stops (FountainFills.cdss)")


def h_transparency(sc, it, f, ctx):
    name = it["id"].split("#", 1)[1]
    p = ctx["transp"][name]

    def build(a):
        r = sc.doc.ActiveLayer.CreateRectangle2(1.0, 1.0, 4.0, 2.5)
        r.Fill.UniformColor.RGBAssign(255, 122, 26)
        r.Outline.SetNoOutline()
        t = r.Transparency
        fl = p.get("fill", {})
        if "uniformTransparency" in p:
            t.ApplyUniformTransparency(int(round(float(p["uniformTransparency"]) * 100)))
        else:
            s = int(round(100 - int(fl.get("primaryAlpha", 255)) / 2.55))
            e = int(round(100 - int(fl.get("secondaryAlpha", 0)) / 2.55))
            t.ApplyFountainTransparency(s, e, int(fl.get("fountainType", 1)), 0.0, int(fl.get("numSteps", 256)),
                                        0, 50, 0.0, 0.0)
        return [r]
    im = sc.render(build, note="transparency " + name)
    return fit(im, bg=checker(SIZE, SIZE)), (
        "applied: Shape.Transparency (" + ("uniform" if "uniformTransparency" in p else "fountain") +
        ") from Transparency.cdss on an orange rectangle, shown over a checker")


def h_duotone(sc, it, f, ctx):
    def build(a):
        ph = _photo(sc)
        d = a.CreateDuotone()
        if not d.Load(str(Path(f).resolve())):
            raise RuntimeError("Duotone.Load returned False")
        try:
            ph.Bitmap.ConvertToDuotone(d)
        except Exception:  # noqa: BLE001
            ph.Bitmap.ConvertTo(2)  # grayscale first
            ph.Bitmap.ConvertToDuotone(d)
        return [ph]
    return (sc.render(build, note="duotone " + it["name"]),
            "applied: Duotone.Load(<.cpd>) then Bitmap.ConvertToDuotone on the test photo")


EFFECT_KEY = {"NNArtStyleEffectDS": "CurrentStylePreset"}
EFFECT_CMD = {"NNArtStyleEffectDS": "ArtStyleEffect"}   # DrawUI.xml EffectsPropertiesDS ApplyOrDeleteEffect:<name>
_cache = {}
_sent = {}   # item id -> (command, {key: why not sent}) of this run's bitmap-effect preset renders (read by audit)

# Why 'Preset=<guid>' rendered every preset of an effect pixel-identical (2026-10-04 run): the command parser only reads
# the effect's own serialized keys (UTF-16 string pool of Programs64\CrlFX.dll next to the effect name) and
# LensFlareEffect / GlassEffect / TheBossEffect / UserDefinedEffect / WhirlpoolEffect have no Preset key, so the key was
# dropped and every preset got the defaults. The preset's values live in the effect's data source: SetProperty('Preset',
# <its itemData row>) loads them (it raises RPC_E_SERVERFAULT although the values DO load: read Preset back to check),
# GetProperty(<path>) reads each one, and they are sent as explicit keys (probes work/cdr/owner_probe1..14, 2026-10-13).
# Colours cannot be sent: the colour keys (FlareColor, ...) parse, but '#RRGGBB' and integers are not read as a colour,
# and any token without '=' (every 'RGB255,USER,r,g,b,100,<guid>' colour string has six, quoted or length-prefixed alike)
# hangs CorelDRAW 2024 in ApplyBitmapEffect for good. Enum items go as their list index ('Dropoff=Flat' faults the call,
# 'Dropoff=1' applies).
SKIP_PATH = ("Preset", "PresetItems", "CurrentPreviewImage")
SKIP_SUFFIX = ("PageSelected", "TabSelected", "Properties", "Context", "ImageList")


def _item_attrs(x):
    """'<itemData ... text="Flat" icon="..."/>' -> {attr: value}; {} for anything else"""
    return dict(re.findall(r'(\w+)="([^"]*)"', x)) if isinstance(x, str) and x.lstrip().startswith("<itemData") else {}


def _num(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return f"{v:g}" if isinstance(v, float) else str(v)


def preset_command(eff, vals, lists, alias=None):
    """data-source values of one preset -> ('<eff> k=v,...', {key: why it was not sent}).
    vals: {path: value as GetProperty returned it}; lists: {path: '<container><itemData text=.../>...'} for enum paths;
    alias: {path: serialized key} where the effect's key differs from the dialog's path."""
    alias = alias or {}
    kv, unsent = [], {}
    for k, v in vals.items():
        if k in SKIP_PATH or k.endswith(SKIP_SUFFIX):
            continue
        a = _item_attrs(v)
        if a:
            if "icon" in a and "text" not in a:
                unsent[k] = "colour: no ApplyBitmapEffect value form takes a colour (note above SKIP_PATH)"
                continue
            names = [_item_attrs(r).get("text") for r in re.findall(r"<itemData [^>]*/>", lists.get(k) or "")]
            if a.get("text") not in names:
                unsent[k] = f"enum item {a.get('text')!r} not in its list"
                continue
            v = names.index(a["text"])
        elif not isinstance(v, (int, float)):
            unsent[k] = f"not a scalar ({str(v)[:40]})"
            continue
        kv.append(f"{alias.get(k, k)}={_num(v)}")
    return f"{eff} " + ",".join(kv), unsent   # keep the space: 'GlassEffect ' applies, 'GlassEffect' does nothing


def _ds_paths(ds):
    """value paths of a data source from DrawUI.xml -> ([path, ...], {path: list path of its items})"""
    if ("paths", ds) not in _cache:
        from drawui import UI, params_from_controls, bind_of
        ui = _cache.get("ui") or _cache.setdefault("ui", UI())
        ctrls = ui.ds_controls(ds)
        paths = [p["key"] for p in params_from_controls(ctrls)]
        lists = {}
        for c in ctrls:
            b = bind_of(c.get("items") or "")
            if b and b[0] == ds:
                lists[c["path"]] = b[1]
        _cache[("paths", ds)] = (paths, lists)
    return _cache[("paths", ds)]


def ds_preset_values(a, ds, guid, paths, list_paths):
    """select the preset (by guid) in the data source and read every value path -> (vals, lists)"""
    s = a.FrameWork.Application.DataContext.GetDataSource(ds)
    row = next((r for r in re.findall(r"<itemData [^>]*/>", s.GetProperty("PresetItems")) if f'guid="{guid}"' in r),
               None)
    if row is None:
        raise RuntimeError(f"{ds}.PresetItems has no item with guid {guid}")
    try:
        s.SetProperty("Preset", row)
    except Exception as e:  # noqa: BLE001 - RPC_E_SERVERFAULT although the preset loads
        if "-2147417851" not in str(e):
            raise
    if f'guid="{guid}"' not in str(s.GetProperty("Preset")):
        raise RuntimeError(f"{ds}.Preset did not take the preset item {row}")
    vals = {}
    for p in paths:
        if p in SKIP_PATH or p.endswith(SKIP_SUFFIX):
            continue
        try:
            v = s.GetProperty(p)
        except Exception as e:  # noqa: BLE001
            v = f"error {e}"[:80]
        vals[p] = v if isinstance(v, (int, float, str)) or v is None else str(v)
    lists = {p: str(s.GetProperty(lp)) for p, lp in list_paths.items() if p in vals}
    return vals, lists


def _alpha_star(sc, a):
    """An orange star converted to an RGB bitmap with a transparent background: edge effects (Bevel, The Boss,
    Glass) change nothing on an opaque photo, they work on the alpha edge."""
    lay = sc.doc.ActiveLayer
    st = lay.CreatePolygon2(3.0, 3.0, 1.6, 5, 90.0, 0.7, True, 0)   # 5-point star, inner radius 0.7 in
    st.Fill.UniformColor.RGBAssign(255, 122, 26)
    st.Outline.SetNoOutline()
    return st.ConvertToBitmapEx(4, False, True, 150, 1, True, False, 95)


def _effect_png(sc, cmd, note, target="photo"):
    def build(a):
        sh = _photo(sc) if target == "photo" else _alpha_star(sc, a)
        if cmd:
            sh.Bitmap.ApplyBitmapEffect("PGD gallery", cmd)
        return [sh]
    return sc.render(build, note=note, timeout=300)


def _diff(a, b):
    from PIL import ImageChops
    if a.size != b.size:
        return 999.0
    h = ImageChops.difference(a, b).histogram()   # RGBA: alpha changes count too
    return sum(i % 256 * c for i, c in enumerate(h)) / (a.size[0] * a.size[1] * 4)


def h_effect_preset(sc, it, f, ctx):
    ds = it["extra"]["data_source"]
    eff = EFFECT_CMD.get(ds, ds[:-2])  # LensFlareEffectDS -> LensFlareEffect
    guid = it["extra"]["guid"]
    if ds in EFFECT_KEY:   # Art Style: the preset list has its own key; not re-probed (2026-10-13)
        cmd, unsent, src = f"{eff} {EFFECT_KEY[ds]}={guid}", {}, f"'{eff} {EFFECT_KEY[ds]}=<preset guid>'"
    else:
        paths, list_paths = _ds_paths(ds)
        vals, lists = sc.call(lambda a: ds_preset_values(a, ds, guid, paths, list_paths), 60,
                              f"{ds} preset {it['name']}")
        from effect_gallery import KEY_ALIAS   # the effect's own key where it differs from the dialog's path
        cmd, unsent = preset_command(eff, vals, lists, {k: v[0] for k, v in KEY_ALIAS.get(eff, {}).items()})
        src = (f"'{cmd}' (the preset's values, read from {ds} after selecting the preset there; the effect has no "
               "preset key)")
    _sent[it["id"]] = (cmd, unsent)
    left = (f"; not sent: {', '.join(sorted(unsent))} (colours cannot cross ApplyBitmapEffect: the effect's default "
            "colours show)") if unsent else ""
    errs, identity = [], None
    for target in ("photo", "alpha star"):
        if ("base", target) not in _cache:
            _cache[("base", target)] = _effect_png(sc, None, "base " + target, target)
        try:
            im = _effect_png(sc, cmd, f"{eff} {it['name']}", target)
        except Exception as e:  # noqa: BLE001 - RPC_E_SERVERFAULT on this target: try the other one
            if "-2147417851" not in str(e):
                raise
            errs.append(f"{target}: RPC_E_SERVERFAULT")
            continue
        if _diff(im, _cache[("base", target)]) < 0.05:
            errs.append(f"{target}: ApplyBitmapEffect('{cmd}') changed no pixels")
            if target == "photo" and it["name"] == "Default":
                identity = im
            continue
        what = "the test photo" if target == "photo" else "an orange star bitmap with a transparent background"
        return im, f"applied: Bitmap.ApplyBitmapEffect({src}) on {what}{left}"
    if identity is not None:
        return identity, (f"applied: Bitmap.ApplyBitmapEffect({src}) on the test photo; the Default preset is an "
                          "identity setting, so the photo is unchanged")
    raise RuntimeError("; ".join(errs))


def h_adjustment(sc, it, f, ctx):
    # 2026-10-04: the first preset (Bright Midtones: ToneCurveEffect with Map0..Map4 lookup strings) hung
    # CorelDRAW 2024 for 390 s and the app had to be killed; every Adjustment Preset is the same shape, so none is
    # sent again (each would cost a 390 s hang + restart)
    raise RuntimeError("Bitmap.ApplyBitmapEffect with this preset's StackedBitmapEffects parameter string hung "
                       "CorelDRAW 2024 (390 s, app killed) on 'Bright Midtones'; not sent for the other presets")
    sty = (it.get("extra") or {}).get("styles", {}).get("style", {})
    eff = next(iter(sty.values())).get("StackedBitmapEffects", {})
    cmds = [f"{e} " + ",".join(f"{k}={v}" for k, v in prm.items() if not isinstance(v, (dict, list)))
            for e, prm in eff.items() if isinstance(prm, dict)]
    if not cmds:
        raise RuntimeError("no StackedBitmapEffects in the .cdss")

    def build(a):
        ph = _photo(sc)
        for c in cmds:
            ph.Bitmap.ApplyBitmapEffect("PGD gallery", c)
        return [ph]
    if ("base", "photo") not in _cache:
        _cache[("base", "photo")] = _effect_png(sc, None, "base photo")
    im = sc.render(build, note="adjustment " + it["name"], timeout=300)
    if _diff(im, _cache[("base", "photo")]) < 0.05:
        raise RuntimeError("the preset effect commands changed no pixels: " + "; ".join(cmds)[:200])
    return im, "applied: the preset StackedBitmapEffects as Bitmap.ApplyBitmapEffect commands on the test photo"


def _grid_shapes(a, doc, x0=1.0, y0=1.0, n=5, cell=0.6):
    lay = doc.ActiveLayer
    sr = a.CreateShapeRange()
    cols = [(255, 122, 26), (30, 91, 255)]
    for r in range(n):
        for c in range(n):
            s = lay.CreateRectangle2(x0 + c * cell, y0 + r * cell, cell, cell)
            s.Fill.UniformColor.RGBAssign(*cols[(r + c) % 2])
            s.Outline.SetNoOutline()
            sr.Add(s)
    return sr.Group()


def h_envelope_pb(sc, it, f, ctx):
    names = [x["name"] for x in ctx["items"] if x["category"] == "Envelope Preset (property bar)"]
    idx = names.index(it["name"]) + 1

    def build(a):
        g = _grid_shapes(a, sc.doc)
        g.CreateEnvelope(idx, 2, False)
        return [g]
    return (sc.render(build, note="envelope " + it["name"]),
            f"applied: Shape.CreateEnvelope(PresetIndex={idx}) on a checker group of squares")


def h_envelope_lib(sc, it, f, ctx):
    def build(a):
        out = []
        for i in range(6):
            g = _grid_shapes(a, sc.doc, x0=1.0 + (i % 3) * 3.6, y0=1.0 + (i // 3) * 3.6, n=4, cell=0.7)
            g.CreateEnvelope(i + 1, 2, False)
            out.append(g)
        return out
    return (sc.render(build, note="envelope library"),
            "applied: Shape.CreateEnvelope(PresetIndex=1..6) on six checker groups (the library presets)")


def h_perspective(sc, it, f, ctx):
    n = it["name"]
    if n.startswith("Three-point"):
        raise RuntimeError("Shape.CreatePerspective takes at most two vanishing points; a three-point preset "
                           "has no object-model equivalent")

    def build(a):
        g = _grid_shapes(a, sc.doc, n=6, cell=0.5)
        if n == "One-point":
            g.CreatePerspective(9.0, 2.5)
        else:
            g.CreatePerspective(9.0, 2.5, 2.5, 9.0)
        return [g]
    return (sc.render(build, note="perspective " + n),
            "applied: Shape.CreatePerspective with " + ("one" if n == "One-point" else "two") +
            " vanishing point(s) on a checker group")


def h_arrowheads(sc, it, f, ctx):
    def build(a):
        lay = sc.doc.ActiveLayer
        out = []
        ah = a.ArrowHeads
        for i in range(min(16, ah.Count)):
            y = 6.0 - i * 0.35
            s = lay.CreateLineSegment(1.0, y, 4.0, y)
            s.Outline.Width = 0.03
            s.Outline.EndArrow = ah.Item(i + 1)
            out.append(s)
        return out
    return sc.render(build, note="arrowheads"), "applied: Outline.EndArrow = Application.ArrowHeads(1..16) on lines"


def h_texture_lib(sc, it, f, ctx):
    libs = (it.get("extra") or {}).get("libraries") or {}
    lib, tex = next(iter(libs.items()))

    def build(a):
        out = []
        for i, t in enumerate(tex[:6]):
            r = sc.doc.ActiveLayer.CreateRectangle2(1.0 + (i % 3) * 1.6, 1.0 + (i // 3) * 1.6, 1.5, 1.5)
            r.Fill.ApplyTextureFill(t, lib)
            out.append(r)
        return out
    return (sc.render(build, note="texture lib"),
            "applied: Fill.ApplyTextureFill(<first six textures>, <first library>) on squares")


def h_two_color(sc, it, f, ctx):
    def build(a):
        out = []
        for i in range(12):
            r = sc.doc.ActiveLayer.CreateRectangle2(1.0 + (i % 4) * 1.1, 1.0 + (i // 4) * 1.1, 1.0, 1.0)
            r.Fill.ApplyPatternFill(0, "", i + 1, a.CreateRGBColor(20, 20, 20), a.CreateRGBColor(255, 255, 255),
                                    False)
            out.append(r)
        return out
    return sc.render(build, note="two-color"), "applied: Fill.ApplyPatternFill(two-color, canvas 1..12) on squares"


HANDLERS = {
    "Artistic Media Brush": h_brush,
    "Fountain Fill Preset": h_fountain, "Transparency Preset": h_transparency, "Duotone Preset": h_duotone,
    "Lens Flare Effect Preset": h_effect_preset, "Art Style Preset": h_effect_preset,
    "Bevel Effect Preset": h_effect_preset, "Glass Effect Preset": h_effect_preset,
    "The Boss Effect Preset": h_effect_preset, "User Defined Effect Preset": h_effect_preset,
    "Whirlpool Effect Preset": h_effect_preset, "Channel Mixer Effect Preset": h_effect_preset,
    "Shear Effect Preset": h_effect_preset, "Tone Curve Effect Preset": h_effect_preset,
    "Adjustment Preset": h_adjustment,
    "Envelope Preset (property bar)": h_envelope_pb, "Envelope Preset Library": h_envelope_lib,
    "Perspective Preset": h_perspective, "Arrowhead Library": h_arrowheads,
    "Texture Fill Library": h_texture_lib, "Two-Color Pattern Library": h_two_color,
}
for _c in PIL_IMAGE_CATS:
    HANDLERS[_c] = h_cpt   # only CPT files reach the app phase (PIL-readable ones were done by file_phase)


def same_render_reason(cat, n, sent):
    """pixel-identical bitmap-effect preset renders -> None (keep them: the presets hold the same values) or why they
    are dropped. sent: this run's (command, unsent keys) per row of the group; None for a row from an earlier run."""
    cmds = [s[0] if s else None for s in sent]
    if cmds and None not in cmds and len(set(cmds)) == 1:
        unsent = sorted({k for s in sent for k in s[1]})
        if not unsent:
            return None   # every readable value is the same (The Boss Default = Rounded Dropoff): one look, two names
        return (f"render pixel-identical to {n} other {cat} item(s): the same command '{cmds[0]}' for each; what tells "
                f"these presets apart is not in it: {', '.join(unsent)} cannot be sent (no ApplyBitmapEffect value form "
                "takes a colour: a colour string has commas, and a token without '=' hangs CorelDRAW 2024), and a "
                "flare's position is not a data-source value at all")
    return (f"render pixel-identical to {n} other {cat} item(s): the effect ignored the keys that tell them apart"
            + (f" (commands: {' | '.join(sorted(set(c for c in cmds if c)))[:300]})" if any(cmds) else ""))


def audit(st, items):
    """Drop renders that cannot be told apart from their siblings: when two presets of one bitmap effect render
    pixel-identical, the render does not show what tells them apart (2026-10-04: every preset sent as 'Preset=<guid>',
    a key the effects do not have; 2026-10-13: presets that differ only in colour). Whirlpool is random but repeatable:
    the same command gives the same pixels (probe 12), so identity catches it like the others.
    Envelope property-bar presets: CreateEnvelope(PresetIndex) does not follow the property-bar order."""
    import hashlib
    from collections import defaultdict
    cat = {it["id"]: it for it in items}
    groups = defaultdict(list)
    for r in list(st.index.values()):
        it = cat[r["id"]]
        if HANDLERS.get(it["category"]) is h_effect_preset:
            px = Image.open(OUT / f"{r['key']}.png").convert("RGB").tobytes()
            groups[(it["category"], hashlib.md5(px).hexdigest())].append(r)
        elif it["category"] == "Envelope Preset (property bar)":
            st.index.pop(r["id"])
            (OUT / f"{r['key']}.png").unlink(missing_ok=True)
            st.fail(it, "Shape.CreateEnvelope(PresetIndex=n) does not follow the property-bar list order (indexes "
                        "1-2 changed nothing, 3 gave a circle on 2026-10-04): which index is this preset is not "
                        "established; the library item shows indexes 1-6 unnamed")
    for (c, _), rs in groups.items():
        if len(rs) > 1:
            why = same_render_reason(c, len(rs) - 1, [_sent.get(r["id"]) for r in rs])
            if why is None:
                for r in rs:
                    r["how"] += "; same values (so the same render) as " + ", ".join(
                        x["name"] for x in rs if x is not r)
                continue
            for r in rs:
                st.index.pop(r["id"])
                (OUT / f"{r['key']}.png").unlink(missing_ok=True)
                st.fail(cat[r["id"]], why)


def check(items):
    """Every harvested id in exactly one of the three json files; every index row has its 320x320 PNG."""
    st = State()
    ids = [it["id"] for it in items]
    assert len(ids) == len(set(ids)), "duplicate ids in the harvest"
    for iid in ids:
        n = (iid in st.index) + (iid in st.failed) + (iid in st.nr)
        assert n == 1, f"{iid} is in {n} of index/failed/not_renderable"
    extra = (set(st.index) | set(st.failed) | set(st.nr)) - set(ids)
    assert not extra, f"ids not in the harvest: {sorted(extra)[:5]}"
    for r in st.index.values():
        assert r["key"] == key(r["id"]) and Image.open(OUT / f"{r['key']}.png").size == (SIZE, SIZE), r
    return len(st.index), len(st.failed), len(st.nr)


def read_ids(path):
    t = Path(path).read_text(encoding="utf-8").strip()
    try:
        return [str(x) for x in json.loads(t)]
    except ValueError:
        return [ln.strip() for ln in t.splitlines() if ln.strip()]


def keep_old(st, ids, pre=SCR / "pre_fix"):
    """forget these ids so they render again; an existing frame moves to pre_fix/ (kept, never overwritten)"""
    pre.mkdir(parents=True, exist_ok=True)
    for iid in ids:
        st.index.pop(iid, None)
        st.failed.pop(iid, None)
        png = OUT / f"{key(iid)}.png"
        if png.exists():
            dst = pre / png.name
            if dst.exists():
                png.unlink()
            else:
                os.replace(png, dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["file", "app", "all"], default="all")
    ap.add_argument("--cats", help="comma list of categories (app phase)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--redo", help="comma list of categories to drop from index/failed and render again")
    ap.add_argument("--check", action="store_true", help="only verify the three json files against the harvest")
    ap.add_argument("--ids", help="file of item ids (JSON list or one per line) to render again; their old PNGs move "
                                  "to work/cdr/gallery/pre_fix/")
    args = ap.parse_args()
    items = json.loads(HARVEST.read_text(encoding="utf-8"))["items"]
    if args.check:
        print("check ok: index %d failed %d not_renderable %d" % check(items))
        return
    st = State(args.retry_failed)
    if args.redo:
        rc = set(args.redo.split(","))
        for it in items:
            if it["category"] in rc:
                st.index.pop(it["id"], None)
                st.failed.pop(it["id"], None)
    if args.ids:
        want = set(read_ids(args.ids))
        unknown = want - {it["id"] for it in items}
        if unknown:
            sys.exit(f"ids not in the harvest: {sorted(unknown)[:5]}")
        keep_old(st, want)
    todo = [it for it in items if it["id"] in want] if args.ids else items
    if args.phase in ("file", "all"):
        file_phase(st, todo)
        print("file phase: index", len(st.index), "failed", len(st.failed), "nr", len(st.nr), flush=True)
    if args.phase in ("app", "all"):
        cats = set(args.cats.split(",")) if args.cats else None
        from collections import Counter
        cnt = Counter(it["category"] for it in todo)
        order = sorted(todo, key=lambda it: -cnt[it["category"]])  # categories with the most items first
        app_phase(st, order, cats, args.limit, items)
    audit(st, items)
    if args.phase == "all" and not args.limit:
        for it in todo:
            if not st.done(it["id"]):
                st.failed[it["id"]] = "no renderer for this category"
    st.save()
    print(f"index {len(st.index)} failed {len(st.failed)} not_renderable {len(st.nr)} total {len(items)}")


if __name__ == "__main__":
    main()
