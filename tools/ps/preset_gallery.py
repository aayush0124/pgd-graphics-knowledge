"""PGD preset gallery: one 320x320 thumbnail per visual Photoshop 2026 preset (harvest/ps/ps_preset.json).

    python preset_gallery.py                 every category, biggest first (resumable)
    python preset_gallery.py Brush Pattern   only these categories
    python preset_gallery.py --selftest      offline checks (no Photoshop)
    python preset_gallery.py --ids FILE      render these ids again (JSON list, rerender_all.json, or one per line);
                                             old frames move to work/ps/gallery/pre_fix/; resumable

Output gallery/ps_preset/<key>.png (key = sha1(item id)[:12]) + index.json / failed.json / not_renderable.json,
checkpointed after every batch; a key whose PNG exists is skipped. Raw renders go to work/ps/gal/raw/.

How each category is rendered (Photoshop does the drawing unless noted):
  Custom shape   shape layer by name + ID, fit to its own aspect, near-black on white
  Brush          brush library loaded into the Brushes panel (replace), preset selected by panel index, S-path
                 stroked with the brush (simulated pressure) on white; panel index verified via sampled-tip ID.
                 Every job starts clean (jobStart): the preset's own tool (from its stored tool options) reset to its
                 defaults, black / white colours, the preset, then its stored diameter (read back). A light saved colour
                 is stroked on black. An image-editing tool (Mixer Brush, Smudge, Sponge, History / Art History,
                 Pattern Stamp ...) strokes the test photo via the Stroke Path event (history tools: photo filled
                 white first so the stroke paints it back); thumbnail = stroke on top, original below
  HDR Toning     .hdt parsed (parse_hdt) -> explicit Local Adaptation hdrOptions descriptor on 32 -> 8 bit conversion
  Layer style    style library loaded (replace), applied by panel index to a bold "PGD" text layer on mid grey;
                 index verified via the enabled-effects set
  Gradient       gradient object read from the .grd with ActionDescriptor.fromStream -> gradient fill layer, one fresh
                 transparent document per gradient (saved over white and over black -> checkerboard composite)
  Pattern        pattern library appended to the Patterns panel, pattern fill layer by name + ID on a 300 px square
                 shown 1:1 (a crop for larger tiles, never shrunk)
  Duotone        test photo -> Grayscale -> Duotone mode with using=<.ado> -> RGB
  Curves/Levels/Hue-Sat/B&W/Channel Mixer/Exposure: adjustment event with using=<file> on the test photo
  Contour        curve parsed from the .shc and plotted (PIL)
  Sky            the sky image file the .sky preset points to (file image)
  Swatch library / Color book: swatch strip (PIL) from the parsed colors
Non-visual categories go to not_renderable.json with the reason (Actions also carry their step list).
"""
import hashlib, json, math, struct, sys, time, urllib.parse
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import presetfiles as pf  # noqa: E402

ROOT = PGD
HARVEST = ROOT / "harvest/ps/ps_preset.json"
OUT = ROOT / "gallery/ps_preset"
RAW = ROOT / "work/ps/gal/raw"
PHOTO = ROOT / "media/test_photo.png"
INSTALL = pf.INSTALL
SIZE, BG = 320, (128, 128, 128)
for p in (OUT, RAW):
    p.mkdir(parents=True, exist_ok=True)

NOT_VISUAL = {
    "Action": "an action is a recorded command sequence, not a look; its steps are listed instead",
    "Tool preset": "a tool preset stores tool options (tool + settings), not an image",
    "Document preset": "a New Document size preset (dimensions / resolution / profile), not a look",
    "Video render preset": "an Adobe Media Encoder export setting, not a look",
    "Image Size preset": "an Image Size dialog setting (dimensions / resolution), not a look",
    "Save for Web optimize settings": "an export compression setting, not a look",
    "Optimized output settings": "an export HTML/file-naming setting, not a look",
    "Optimized color table": "an export color table (Save for Web), not applied as a look",
    "Script": "a script (automation), not a look",
    "Deco script": "a Deco fill script (procedural fill generator), not a preset image",
    "Guide layout": "a guide layout (guide positions), not a look",
    "3D widget": "a 3D axis/light widget model for the retired 3D feature, not a look",
}
ORDER = ["Custom shape", "Brush", "Layer style", "Gradient", "Pattern", "Duotone preset", "Contour", "3D LUT",
         "Sky (Sky Replacement)", "Swatch library", "HDR Toning preset", "Color book", "Black & White preset",
         "Curves preset", "Hue/Saturation preset", "Levels preset", "Channel Mixer preset", "Exposure preset",
         "Photo Filter colors"]


def key(iid):
    return hashlib.sha1(iid.encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------------------ state (index / failed / not_renderable)
ONLY = None  # --ids: the ids this run renders again (None: every item without a current render)
PRE_FIX = ROOT / "work/ps/gallery/pre_fix"
FRESH = PRE_FIX.parent / "rerendered.json"  # ids an --ids run has already rendered again (resume skips them)


def read_ids(path):
    """item ids from a JSON list, a JSON object's "ps_preset" (work/rerender_all.json) or "ids" list, or one id per line."""
    t = Path(path).read_text(encoding="utf-8").strip()
    try:
        v = json.loads(t)
    except ValueError:
        return [ln.strip() for ln in t.splitlines() if ln.strip()]
    return [str(x) for x in ((v.get("ps_preset") or v["ids"]) if isinstance(v, dict) else v)]


def keep_old(st, ids, pre=None):
    """forget these ids so they render again: index / failed entries dropped, raw renders deleted (a stale raw must
    never become a new thumbnail), the old frame moved to work/ps/gallery/pre_fix/ (the first one kept is never
    overwritten)."""
    pre = Path(pre or PRE_FIX)
    pre.mkdir(parents=True, exist_ok=True)
    for iid in ids:
        k = key(iid)
        st.index.pop(k, None)
        st.failed.pop(iid, None)
        for r in (RAW / f"{k}.png", RAW / f"{k}_b.png"):
            r.unlink(missing_ok=True)
        png = OUT / f"{k}.png"
        if png.exists():
            if (pre / png.name).exists():
                png.unlink()
            else:
                os.replace(png, pre / png.name)


class State:
    def __init__(self):
        self.index = {e["key"]: e for e in self._load("index.json", [])}
        self.failed = self._load("failed.json", {})
        self.notr = self._load("not_renderable.json", {})
        self.fresh = set(json.loads(FRESH.read_text(encoding="utf-8"))) if FRESH.exists() else set()

    @staticmethod
    def _load(n, d):
        p = OUT / n
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d

    def done(self, it, how_has=None):
        """PNG exists (and, when how_has is given, it was made by the current method: older renders are redone).
        With --ids every item outside the list counts as done, so the handlers render the listed ids only."""
        if ONLY is not None and it["id"] not in ONLY:
            return True
        k = key(it["id"])
        return k in self.index and (OUT / f"{k}.png").exists() and (how_has is None or how_has in self.index[k]["how"])

    def ok(self, it, how):
        k = key(it["id"])
        self.index[k] = {"key": k, "id": it["id"], "name": it["name"], "category": it["category"], "how": how}
        self.failed.pop(it["id"], None)
        if ONLY is not None:
            self.fresh.add(it["id"])

    def fail(self, it, err):
        self.failed[it["id"]] = str(err)[:500]

    def save(self):
        for n, v in (("index.json", sorted(self.index.values(), key=lambda e: (e["category"], e["id"]))),
                     ("failed.json", self.failed), ("not_renderable.json", self.notr)):
            t = OUT / (n + ".tmp")
            t.write_text(json.dumps(v, indent=1, ensure_ascii=False), encoding="utf-8")
            t.replace(OUT / n)
        if ONLY is not None:
            FRESH.parent.mkdir(parents=True, exist_ok=True)
            FRESH.write_text(json.dumps(sorted(self.fresh), indent=1, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------ thumbnails
def checker(w, h, s=10):
    im = Image.new("RGB", (w, h), (204, 204, 204))
    d = ImageDraw.Draw(im)
    for y in range(0, h, s):
        for x in range((y // s % 2) * s, w, 2 * s):
            d.rectangle([x, y, x + s - 1, y + s - 1], fill=(255, 255, 255))
    return im


def thumb_wb(white, black, dst, box=300):
    """render saved over white and over black -> composite over a checkerboard: out = B + K * (W - B) / 255."""
    import numpy as np
    w = np.asarray(Image.open(white).convert("RGB"), dtype=float)
    b = np.asarray(Image.open(black).convert("RGB"), dtype=float)
    k = np.asarray(checker(w.shape[1], w.shape[0], max(8, w.shape[1] // 30)), dtype=float)
    im = Image.fromarray(np.clip(b + k * (w - b) / 255.0, 0, 255).astype("uint8"))
    im.thumbnail((box, box), Image.LANCZOS)
    out = Image.new("RGB", (SIZE, SIZE), BG)
    out.paste(im, ((SIZE - im.width) // 2, (SIZE - im.height) // 2))
    out.save(dst)


def thumb(src, dst, bg=BG, box=SIZE, alpha_checker=False):
    """fit src into a SIZE x SIZE square (inner box `box`) on a neutral background."""
    im = Image.open(src)
    im.load()
    im = im.convert("RGBA")
    im.thumbnail((box, box), Image.LANCZOS)
    if alpha_checker:
        base = checker(*im.size)
        base.paste(im, (0, 0), im)
        im = base.convert("RGBA")
    out = Image.new("RGB", (SIZE, SIZE), bg)
    out.paste(im, ((SIZE - im.width) // 2, (SIZE - im.height) // 2), im)
    out.save(dst)


def thumb_ba(after, before, dst, top="PRESET APPLIED", bottom="ORIGINAL"):
    """photo presets: the result on top, the untouched test photo below it for comparison, both labelled."""
    a, b = Image.open(after).convert("RGB"), Image.open(before).convert("RGB")
    h = (SIZE - 4) // 2
    w = min(SIZE, round(h * a.width / a.height))
    out = Image.new("RGB", (SIZE, SIZE), BG)
    d = ImageDraw.Draw(out)
    for im, y, lab in ((a, 0, top), (b, h + 4, bottom)):
        out.paste(im.resize((w, h), Image.LANCZOS), ((SIZE - w) // 2, y))
        tw = int(d.textlength(lab)) + 8
        d.rectangle([(SIZE - w) // 2, y, (SIZE - w) // 2 + tw, y + 13], fill=(0, 0, 0))
        d.text(((SIZE - w) // 2 + 4, y + 1), lab, fill=(255, 255, 255))
    out.save(dst)


def stripes():
    """640x360 chart of saturated hue bands (hard vertical edges) for the sponge / smudge / blur brush presets."""
    p = RAW.parent / "stripes.png"
    if not p.exists():
        import colorsys
        im = Image.new("RGB", (640, 360))
        d = ImageDraw.Draw(im)
        for i in range(16):
            d.rectangle([i * 40, 0, i * 40 + 39, 359], fill=tuple(round(255 * c) for c in colorsys.hsv_to_rgb(i / 16, 1, 1 if i % 2 else .8)))
        im.save(p)
    return p


def photo_base():
    """the 640x360 test photo exactly as Photoshop downsizes it for the photo categories (the 'before' image)."""
    base = RAW.parent / "photo_base.png"
    if not base.exists():
        run('var d = work(); savePng(d, %s); d.close(SaveOptions.DONOTSAVECHANGES); RES.ok = 1;' % jstr(base.as_posix()), 120, "base")
    return base


# ------------------------------------------------------------------ preset file helpers
def lib_items(items):
    """{file: [items in file order]} (harvest order == file order, checked in selftest)."""
    out = {}
    for it in items:
        out.setdefault(it["invoke"]["file"], []).append(it)
    return out


def seq_positions(path, n):
    """1-based Brushes/Styles panel position of each preset of a library file, counting its own group rows."""
    b = Path(path).read_bytes()
    i = b.rfind(b"8BIMphry")
    if i < 0:
        return list(range(1, n + 1))
    d = pf._d16(pf.R(b, i + 12))
    pos, k = [], 0
    for h in d.get("hierarchy", []):
        c = h.get("_classID") if isinstance(h, dict) else None
        if c in ("Grup", "preset"):
            k += 1
            if c == "preset":
                pos.append(k)
    if len(pos) != n:
        raise ValueError(f"hierarchy has {len(pos)} presets, file has {n}")
    return pos


# tool-options class stored in a brush preset -> the tool it loads into (the 2026-10-07 renders saw every preset of
# each class switch Photoshop to exactly this tool when selected: 41 / 3 / 4 / 79 / 11 / 1 / 4 / 1 presets)
TOOL_OF = {"PbTl": "paintbrushTool", "ErTl": "eraserTool", "SmTl": "smudgeTool", "MixB": "wetBrushTool",
           "ABTl": "artBrushTool", "HBTl": "historyBrushTool", "PaTl": "patternStampTool", "SrTl": "saturationTool"}


def saved_rgb(c):
    """a colour as presetfiles._hex gives it ('#RRGGBB', or {class: {keys}} for HSBC / CMYC / Grsc / LbCl) -> (r, g, b)."""
    if isinstance(c, str):
        return to_rgb(c)
    (cls, v), = c.items()
    num = lambda x: x["v"] if isinstance(x, dict) else x  # noqa: E731  (unit values: {"unit", "v"})
    if cls == "HSBC":
        return to_rgb({"HSB": [num(v["H   "]), num(v["Strt"]), num(v["Brgh"])]})
    if cls == "CMYC":
        return to_rgb({"CMYK": [num(v[k]) for k in ("Cyn ", "Mgnt", "Ylw ", "Blck")]})
    if cls == "Grsc":
        return to_rgb({"Gray": num(v["Gry "])})
    if cls == "LbCl":
        return lab2rgb(num(v["Lmnc"]), num(v["A   "]), num(v["B   "]))
    raise ValueError(f"colour class {cls}")


def preset_meta(o):
    """one parsed brush preset -> {"tool": the tool its stored tool options belong to (paintbrushTool when it stores
    none), "fg": the foreground colour it saves as (r, g, b), or None, "use_brush_size": it keeps the current brush
    size instead of its own when selected, "opts": it stores tool options (opacity, flow, mode ...)}."""
    t = o.get("toolOptions") or {}
    cls = t.get("_classID")
    if cls is not None and cls not in TOOL_OF:
        raise ValueError(f"unmapped tool-options class {cls!r}")
    return {"tool": TOOL_OF.get(cls, "paintbrushTool"), "fg": saved_rgb(pf._hex(t["FrgC"])) if t.get("FrgC") else None,
            "use_brush_size": bool(o.get("useBrushSize")), "opts": cls is not None}


def brush_meta(path):
    """preset_meta of every preset of an .abr, in file order."""
    b = Path(path).read_bytes()
    p, _ = pf.sections(b, 4)["desc"]
    return [preset_meta(o) for o in pf._d16(pf.R(b, p)).get("Brsh", [])]


def light(rgb):
    """a saved colour too light to see on the white canvas (DP Cloud saves white): stroke it on black instead."""
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2] >= 200


def brush_job(it, pos, meta, sig):
    """the render job of one brush preset: every value a job needs to start from a clean state is in the job itself."""
    k = key(it["id"])
    d = it["extra"].get("diameter_px") or 60
    return {"k": k, "out": raw(k), "pos": pos, "s": int(min(2500, max(360, d * 5))), "d": d, "tool": meta["tool"], "opts": meta["opts"],
            "fg": "#%02X%02X%02X" % meta["fg"] if meta["fg"] else None, "dark": bool(meta["fg"]) and light(meta["fg"]),
            "stripes": stripes().as_posix(), "sig": sig}


def csh_bounds(path):
    """[(shape_id without $, top, left, bottom, right, record bytes)] in file order."""
    b = Path(path).read_bytes()
    r = pf.R(b)
    assert r.os() == "cush"
    r.u32()
    out = []
    for _ in range(r.u32()):
        r.ustr()
        r.align(4)
        r.u32()
        ln = r.u32()
        body = b[r.p:r.p + ln]
        # "$" + 36-char uuid (no terminator), then top/left/bottom/right as signed int32; splitting at the first NUL
        # (2026-10-04 code) misread every shape whose top bound is negative (Arrow 5, Arrow 7 rendered blank)
        assert body[:1] == b"$" and body[9:10] == b"-", body[:40]
        t, l, bt, rt = struct.unpack(">4i", body[37:53])
        out.append((body[1:37].decode("ascii"), t, l, bt, rt, ln))
        r.p += ln
        r.align(4)
    return out


def shc_curves(path):
    """[(name, [(input, output, corner)])] in file order, read after each record's UTF-16 name."""
    b = Path(path).read_bytes()
    out, pat = [], "$$$/".encode("utf-16-be")
    i = b.find(pat)
    while i >= 0:
        j = i
        while j + 1 < len(b) and b[j:j + 2] != b"\x00\x00":
            j += 2
        if j + 1 >= len(b):
            raise ValueError(f"{Path(path).name}: unterminated name at byte {i}")
        name = b[i:j].decode("utf-16-be")
        p = j + 2
        _, n = struct.unpack(">HH", b[p:p + 4])
        p += 4
        pts = [struct.unpack(">HH", b[p + 4 * k:p + 4 * k + 4]) for k in range(n)]
        flags = b[p + 4 * n:p + 5 * n]
        out.append((pf.zlabel(name), [(x, y, flags[k]) for k, (y, x) in enumerate(pts)]))
        i = b.find(pat, p + 5 * n)
    return out


def _spline(xs, ys):
    """natural cubic spline through the points (what Photoshop's curve editors draw); returns f(x)."""
    n = len(xs)
    if n < 3:
        return lambda x: ys[0] + (ys[-1] - ys[0]) * (x - xs[0]) / ((xs[-1] - xs[0]) or 1)
    h = [xs[i + 1] - xs[i] or 1e-6 for i in range(n - 1)]
    a, b, c, r = [0.0] * n, [1.0] * n, [0.0] * n, [0.0] * n
    for i in range(1, n - 1):
        a[i], b[i], c[i] = h[i - 1], 2 * (h[i - 1] + h[i]), h[i]
        r[i] = 6 * ((ys[i + 1] - ys[i]) / h[i] - (ys[i] - ys[i - 1]) / h[i - 1])
    for i in range(1, n):  # Thomas algorithm
        m = a[i] / b[i - 1]
        b[i] -= m * c[i - 1]
        r[i] -= m * r[i - 1]
    M = [0.0] * n
    for i in range(n - 1, -1, -1):
        M[i] = (r[i] - c[i] * (M[i + 1] if i + 1 < n else 0)) / b[i]

    def f(x):
        k = max(0, min(n - 2, max(i for i in range(n - 1) if xs[i] <= x) if x >= xs[0] else 0))
        t0, t1, hk = xs[k + 1] - x, x - xs[k], h[k]
        return (M[k] * t0 ** 3 + M[k + 1] * t1 ** 3) / (6 * hk) + (ys[k] / hk - M[k] * hk / 6) * t0 + (ys[k + 1] / hk - M[k + 1] * hk / 6) * t1
    return f


def contour_ys(pts, n=256):
    """y(x) for x in 0..255. A point's flag is the file's continuity bit (1 = smooth, 0 = corner, as Cnty in style
    contours): the curve is a natural cubic spline through each run of points, broken at corner points."""
    pts = sorted(pts)
    runs, cur = [], [pts[0]]
    for p in pts[1:]:
        cur.append(p)
        if p[2] == 0 and p is not pts[-1]:
            runs.append(cur)
            cur = [p]
    runs.append(cur)
    out = []
    for x in range(n):
        run = next((r for r in runs if r[0][0] <= x <= r[-1][0]), runs[0] if x < pts[0][0] else runs[-1])
        f = _spline([q[0] for q in run], [q[1] for q in run])
        xx = min(max(x, run[0][0]), run[-1][0])
        out.append(max(0, min(255, f(xx))))
    return out


def draw_contour(pts, dst):
    im = Image.new("RGB", (SIZE, SIZE), (245, 245, 245))
    d = ImageDraw.Draw(im)
    m, s = 24, SIZE - 48
    d.rectangle([m, m, m + s, m + s], outline=(170, 170, 170))
    for q in (0.25, 0.5, 0.75):
        d.line([m + s * q, m, m + s * q, m + s], fill=(222, 222, 222))
        d.line([m, m + s * q, m + s, m + s * q], fill=(222, 222, 222))
    ys = contour_ys(pts)
    poly = [(m + s * x / 255, m + s - s * y / 255) for x, y in enumerate(ys)]
    d.polygon(poly + [(m + s, m + s), (m, m + s)], fill=(200, 210, 230))
    d.line(poly, fill=(20, 20, 20), width=3)
    for x, y, c in pts:
        cx, cy = m + s * x / 255, m + s - s * y / 255
        (d.ellipse if c else d.rectangle)([cx - 4, cy - 4, cx + 4, cy + 4], fill=(200, 40, 40))
    im.save(dst)


def lab2rgb(L, a, b):
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200

    def f(t):
        return t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787
    X, Y, Z = 0.9642 * f(fx), 1.0 * f(fy), 0.8249 * f(fz)  # D50 white (Photoshop Lab)
    r = 3.1338561 * X - 1.6168667 * Y - 0.4906146 * Z      # Bradford-adapted D50 -> sRGB
    g = -0.9787684 * X + 1.9161415 * Y + 0.0334540 * Z
    bb = 0.0719453 * X - 0.2289914 * Y + 1.4052427 * Z

    def gam(v):
        v = max(0.0, min(1.0, v))
        return 255 * (12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055)
    return tuple(round(gam(v)) for v in (r, g, bb))


def to_rgb(c):
    """a color as presetfiles reports it -> (r, g, b) for display."""
    if isinstance(c, str) and c.startswith("#"):
        return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
    (sp, v), = c.items()
    if sp == "CMYK":
        cc, m, y, k = [x / 100 for x in v]
        return tuple(round(255 * (1 - q) * (1 - k)) for q in (cc, m, y))
    if sp == "Lab":
        return lab2rgb(*v)
    if sp == "Gray":
        g = round(255 * (1 - v / 100))
        return (g, g, g)
    if sp == "HSB":
        import colorsys
        return tuple(round(255 * q) for q in colorsys.hsv_to_rgb(v[0] / 360, v[1] / 100, v[2] / 100))
    raise ValueError(f"color space {sp}")


def acb_rgb(path):
    ents, meta = pf.parse_acb(Path(path).read_bytes())
    sp = meta["color_space"]
    out = []
    for e in ents:
        c = e["comp"]
        if sp == "RGB":
            out.append(tuple(c))
        elif sp == "CMYK":
            out.append(to_rgb({"CMYK": [(255 - x) / 2.55 for x in c]}))
        elif sp == "Lab":
            out.append(lab2rgb(c[0] / 2.55, c[1] - 128, c[2] - 128))
        else:
            raise ValueError(f"acb color space {sp}")
    return out


def swatch_strip(cols, dst):
    im = Image.new("RGB", (SIZE, SIZE), (235, 235, 235))
    d = ImageDraw.Draw(im)
    n = len(cols)
    c = max(1, math.ceil(math.sqrt(n)))
    rows = math.ceil(n / c)
    cw, ch = (SIZE - 8) / c, (SIZE - 8) / max(rows, 1)
    g = 1 if cw >= 8 else 0
    for i, col in enumerate(cols):
        x, y = 4 + (i % c) * cw, 4 + (i // c) * ch
        d.rectangle([round(x), round(y), round(x + cw) - 1 - g, round(y + ch) - 1 - g], fill=col)
    im.save(dst)


# ------------------------------------------------------------------ Photoshop side
PSJ = r'''
function savePng(doc, p) { var o = new PNGSaveOptions(); o.compression = 1; o.interlaced = false; doc.saveAs(new File(p), o, true, Extension.LOWERCASE); }
function readBin(p) { var f = new File(p); f.encoding = "BINARY"; f.open("r"); var s = f.read(); f.close(); return s; }
function loadPreset(prop, path, append) { var r = new ActionReference(); r.putProperty(C2T("Prpr"), prop); r.putEnumerated(C2T("capp"), C2T("Ordn"), C2T("Trgt"));
  var d = new ActionDescriptor(); d.putReference(C2T("null"), r); d.putPath(C2T("T   "), new File(path)); d.putBoolean(C2T("Appe"), append);
  executeAction(C2T("setd"), d, DialogModes.NO); }
function toolOpts() { var r = new ActionReference(); r.putProperty(C2T("Prpr"), S2T("currentToolOptions")); r.putEnumerated(C2T("capp"), C2T("Ordn"), C2T("Trgt"));
  return executeActionGet(r).getObjectValue(S2T("currentToolOptions")); }
function selBrush(i) { var r = new ActionReference(); r.putIndex(C2T("Brsh"), i); var d = new ActionDescriptor(); d.putReference(C2T("null"), r); executeAction(C2T("slct"), d, DialogModes.NO); }
function brushSig() { var b = toolOpts().getObjectValue(C2T("Brsh")); return b.hasKey(S2T("sampledData")) ? b.getString(S2T("sampledData")) : ""; }
function tgt() { var r = new ActionReference(); r.putEnumerated(C2T("Lyr "), C2T("Ordn"), C2T("Trgt")); return r; }
function applyStyleIdx(i) { var r = new ActionReference(); r.putIndex(C2T("Styl"), i); var d = new ActionDescriptor(); d.putReference(C2T("null"), r); d.putReference(C2T("T   "), tgt()); executeAction(C2T("ASty"), d, DialogModes.NO); }
var FXN = {dropShadow: "Drop Shadow", innerShadow: "Inner Shadow", outerGlow: "Outer Glow", innerGlow: "Inner Glow", bevelEmboss: "Bevel & Emboss",
  chromeFX: "Satin", solidFill: "Color Overlay", gradientFill: "Gradient Overlay", patternFill: "Pattern Overlay", frameFX: "Stroke"};
function styleSig() { var d = layerDesc(); if (!d.hasKey(C2T("Lefx"))) return ""; var l = d.getObjectValue(C2T("Lefx")), on = {};
  for (var i = 0; i < l.count; i++) { var k = l.getKey(i), s = tid2s(k), base = s.replace(/Multi$/, ""); if (!FXN[base]) continue;
    var objs = []; if (l.getType(k) == DescValueType.LISTTYPE) { var ll = l.getList(k); for (var j = 0; j < ll.count; j++) objs.push(ll.getObjectValue(j)); } else objs.push(l.getObjectValue(k));
    for (var j = 0; j < objs.length; j++) if (!objs[j].hasKey(C2T("enab")) || objs[j].getBoolean(C2T("enab"))) on[FXN[base]] = 1; }
  var a = []; for (var n in on) a.push(n); a.sort(); return a.join(","); }
function rgbc(r, g, b) { var c = new SolidColor(); c.rgb.red = r; c.rgb.green = g; c.rgb.blue = b; return c; }
function bw() { app.foregroundColor = rgbc(0, 0, 0); app.backgroundColor = rgbc(255, 255, 255); }
function closeIf(n) { for (var i = app.documents.length - 1; i >= 0; i--) if (app.documents[i].name == n) app.documents[i].close(SaveOptions.DONOTSAVECHANGES); }
function photoBase() { if (!activate("pgd_gal_photo")) { var s = app.open(new File(PHOTO)); var d = s.duplicate("pgd_gal_photo", true); s.close(SaveOptions.DONOTSAVECHANGES);
  app.activeDocument = d; d.resizeImage(UnitValue(640, "px"), UnitValue(360, "px"), 72, ResampleMethod.BICUBIC); } return app.activeDocument; }
function work() { var b = photoBase(); var d = b.duplicate("pgd_gal_w", true); app.activeDocument = d; return d; }
function saveWB(doc, out, out2) { var bg = doc.layers[doc.layers.length - 1], keep = doc.activeLayer; doc.activeLayer = bg;
  doc.selection.selectAll(); doc.selection.fill(rgbc(255, 255, 255)); savePng(doc, out); doc.selection.fill(rgbc(0, 0, 0)); savePng(doc, out2);
  doc.selection.deselect(); doc.activeLayer = keep; }
var RES = {};
'''

_SESSION = {"loaded": set(), "offset": {}, "since": 0}

# Memory guard (2026-10-05): the 2026-10-04 run let Photoshop grow to 32.6 GB private and took the box within 2.5 GB of
# its commit limit. Before every batch: restart Photoshop every RESTART_EVERY items, when it holds more than MAX_PS_GB
# (PGD_PS_MAX_GB, default 6: the host keeps only ~6 GB free for it), or when commit headroom is below MIN_HEADROOM_GB
# (then also wait for the headroom to come back).
RESTART_EVERY, MIN_HEADROOM_GB, WAIT_MAX_S = 150, 4.0, 2700
MAX_PS_GB = float(os.environ.get("PGD_PS_MAX_GB") or 6.0)
LOG = RAW.parent / "resume" / "run.log"


class NoHeadroom(Exception):
    """commit headroom stayed low for WAIT_MAX_S: stop the whole run (never recorded as an item failure)."""


def log(msg):
    print(msg, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%m-%d %X ") + msg + "\n")


def ps_private_gb():
    import psutil
    tot = 0
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower() == "photoshop.exe":
            try:
                tot += p.memory_info().private
            except Exception:  # noqa: BLE001
                pass
    return tot / 2 ** 30


def headroom_gb():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/hostlock.py: vendored, same host mutex
    import hostlock
    free_mb, used, lim, top = hostlock.headroom()
    return (None, top) if used is None else (lim - used, top)


def guard(tag):
    t0, first = time.time(), True
    while True:
        hr, top = headroom_gb()
        psgb = ps_private_gb()
        why = None
        if first and _SESSION["since"] >= RESTART_EVERY:
            why = f"{_SESSION['since']} items since the last restart"
        elif psgb > MAX_PS_GB:
            why = f"Photoshop holds {psgb:.1f} GB private"
        elif hr is not None and hr < MIN_HEADROOM_GB and psgb > _SESSION.get("base_gb", 0) + 0.5:
            # restarting a Photoshop that has not grown since its last start frees nothing: then only wait
            why = f"commit headroom {hr:.1f} GB (largest: {top}); Photoshop holds {psgb:.1f} GB"
        first = False
        if why:
            log(f"  restart Photoshop before {tag}: {why}")
            restart()
            continue
        if hr is None or hr >= MIN_HEADROOM_GB:
            return
        if time.time() - t0 > WAIT_MAX_S:
            raise NoHeadroom(f"commit headroom stayed below {MIN_HEADROOM_GB} GB for {WAIT_MAX_S // 60} min "
                             f"(now {hr:.1f} GB, largest {top}, Photoshop {ps_private_gb():.1f} GB)")
        log(f"  waiting for commit headroom: {hr:.1f} GB free of commit (largest: {top}; Photoshop {ps_private_gb():.1f} GB)")
        time.sleep(60)


def ps():
    import psdrv
    return psdrv


def _crash_watch(stop):
    """Photoshop's crash reporter ('Error Report for "Adobe Photoshop"') is not an owned dialog, so psdrv would wait
    out two full timeouts; kill the crashed process as soon as the reporter shows so the pending call fails fast."""
    while not stop.wait(5):
        for w in ps().ps_windows():
            if w["title"].startswith("Error Report for"):
                ps().kill_owned(exit_wait=0)  # the Photoshop this pipeline started (recorded pid), never by name
                with open(RAW.parent / "crashes.log", "a", encoding="utf-8") as f:
                    f.write(time.strftime("%X") + " Photoshop crash reporter seen; killed Photoshop\n")
                return


def run(src, timeout, tag):
    """run a batch script in Photoshop; returns its JSON result."""
    import threading
    # every batch ends with no document of ours left open (the test-photo base included) and Photoshop's caches purged
    js = (PSJ.replace("PHOTO)", '"%s")' % PHOTO.as_posix()) + src
          + '\ntry { closeIf("pgd_gal_photo"); app.purge(PurgeTarget.ALLCACHES); } catch (eP) {}\nJ(RES)')
    stop = threading.Event()
    threading.Thread(target=_crash_watch, args=(stop,), daemon=True).start()
    try:
        return ps().jsj(js, timeout=timeout, tag=tag)
    finally:
        stop.set()


def canary():
    try:
        return ps().js('var d = newDoc("pgd_gal_canary", 32, 32); executeAction(S2T("invert"), new ActionDescriptor(), DialogModes.NO); '
                       'd.close(SaveOptions.DONOTSAVECHANGES); "ok"', timeout=60, tag="canary") == "ok"
    except Exception:  # noqa: BLE001
        return False


def restart():
    ps().restart_ps()
    _SESSION["loaded"].clear()
    _SESSION["offset"].clear()
    _SESSION["since"] = 0
    _SESSION["base_gb"] = ps_private_gb()
    log(f"  Photoshop restarted ({_SESSION['base_gb']:.1f} GB private)")


def jstr(s):
    return json.dumps(s)


def raw(k):
    return (RAW / f"{k}.png").as_posix()


# ---- per-category batch scripts (jobs -> RES[key] = "ok" | "ERR ...")
def js_shapes(jobs):
    return '''bw(); closeIf("pgd_gal_shape"); var doc = newDoc("pgd_gal_shape", 400, 400);
function shape(nm, id, t, l, b, r) { var d = new ActionDescriptor(); var rf = new ActionReference(); rf.putClass(S2T("contentLayer")); d.putReference(C2T("null"), rf);
  var cl = new ActionDescriptor(); var sc = new ActionDescriptor(); sc.putObject(C2T("Clr "), C2T("RGBC"), (function () { var c = new ActionDescriptor();
  c.putDouble(C2T("Rd  "), 20); c.putDouble(C2T("Grn "), 20); c.putDouble(C2T("Bl  "), 20); return c; })());
  cl.putObject(C2T("Type"), S2T("solidColorLayer"), sc); var sh = new ActionDescriptor(); sh.putString(C2T("Nm  "), nm); sh.putString(S2T("ID"), id);
  sh.putUnitDouble(C2T("Top "), C2T("#Pxl"), t); sh.putUnitDouble(C2T("Left"), C2T("#Pxl"), l); sh.putUnitDouble(C2T("Btom"), C2T("#Pxl"), b); sh.putUnitDouble(C2T("Rght"), C2T("#Pxl"), r);
  cl.putObject(C2T("Shp "), S2T("customShape"), sh); d.putObject(C2T("Usng"), S2T("contentLayer"), cl); executeAction(C2T("Mk  "), d, DialogModes.NO); }
var JOBS = %s;
for (var i = 0; i < JOBS.length; i++) { var j = JOBS[i];
  try { shape(j.name, j.id, j.t, j.l, j.b, j.r); savePng(doc, j.out); RES[j.k] = "ok"; } catch (e) { RES[j.k] = "ERR " + String(e); }
  while (doc.layers.length > 1) doc.layers[0].remove(); }
doc.close(SaveOptions.DONOTSAVECHANGES);''' % json.dumps(jobs)


JS_JOB_START = r'''
function setDiam(px) { var d = new ActionDescriptor(), r = new ActionReference(); r.putEnumerated(C2T("Brsh"), C2T("Ordn"), C2T("Trgt")); d.putReference(C2T("null"), r);
  var b = new ActionDescriptor(); b.putUnitDouble(S2T("masterDiameter"), C2T("#Pxl"), px); d.putObject(C2T("T   "), C2T("Brsh"), b); executeAction(C2T("setd"), d, DialogModes.NO); }
function brushDiam() { var b = toolOpts().getObjectValue(C2T("Brsh")); return b.hasKey(C2T("Dmtr")) ? b.getUnitDoubleValue(C2T("Dmtr")) : -1; }
function resetTool() { var d = new ActionDescriptor(), r = new ActionReference(); r.putProperty(C2T("Prpr"), S2T("currentToolOptions"));
  r.putEnumerated(C2T("capp"), C2T("Ordn"), C2T("Trgt")); d.putReference(C2T("null"), r); executeAction(C2T("Rset"), d, DialogModes.NO); }
function optInt(k) { var o = toolOpts(); return o.hasKey(S2T(k)) ? o.getInteger(S2T(k)) : 100; }
// Every job starts from the same state, whatever the job before it left (2026-10-13 fixes): (c) the preset's own tool
// first (Smudge / Mixer / Eraser presets were stroked with the Brush tool still holding the previous preset); (g) that
// tool reset to its defaults (Reset Tool: a preset that stores no tool options inherited the last one's, e.g. 18% flow);
// (a) black / white colours, set with that tool active (once per batch let a preset's saved colour, DP Cloud's white or
// Aurora's teal, and the Mixer Brush load carry into the presets after it); then the preset (which may set its own
// tool options and colours); then (b) its stored diameter (a useBrushSize preset keeps the size of the one before it).
function jobStart(j) { app.currentTool = j.tool; resetTool(); bw(); selBrush(j.idx);
  if (app.currentTool != j.tool) throw new Error("selecting the preset left " + app.currentTool + " active, not its own " + j.tool);
  if (!j.opts && j.tool == "paintbrushTool" && (optInt("opacity") != 100 || optInt("flow") != 100))
    throw new Error("tool options not at their defaults: opacity " + optInt("opacity") + ", flow " + optInt("flow"));
  setDiam(j.d); var dm = brushDiam(); if (Math.abs(dm - j.d) > 0.5) throw new Error("brush diameter " + dm + " px after setting " + j.d); }
'''


def js_brushes(jobs):
    return JS_JOB_START + '''var JOBS = %s;
var TT = {paintbrushTool: ToolType.BRUSH, pencilTool: ToolType.PENCIL, eraserTool: ToolType.ERASER, backgroundEraserTool: ToolType.BACKGROUNDERASER};
function pp(x, y, lx, ly, rx, ry) { var p = new PathPointInfo(); p.kind = PointKind.SMOOTHPOINT; p.anchor = [x, y]; p.leftDirection = [lx, ly]; p.rightDirection = [rx, ry]; return p; }
// tools that act on image content, stroked through the Action Manager Stroke Path event (DOM ToolType has no Mixer Brush).
// Canvas: 1 test photo | 2 test photo filled white (history tools paint the photo back) | 3 mid grey (pattern stamp: the
// texture presets use blend modes that vanish on white or on a busy photo) | 4 colour-stripe chart (sponge / smudge: a
// desaturated or smeared path is only legible across saturated hard edges)
var PHOTO_TOOLS = {wetBrushTool: 1, artBrushTool: 2, historyBrushTool: 2, patternStampTool: 3, saturationTool: 4, smudgeTool: 4,
  blurTool: 4, sharpenTool: 1, dodgeTool: 1, burnTool: 1};
for (var i = 0; i < JOBS.length; i++) { var j = JOBS[i], doc = null;
  try { jobStart(j); var sig = brushSig(); if (j.sig && sig != j.sig) throw new Error("panel index mismatch: tip " + sig + " expected " + j.sig);
    var tool = app.currentTool, tt = TT[tool];
    var MODE = PHOTO_TOOLS[tool];
    if (MODE) { var d0; if (MODE == 4) { var s0 = app.open(new File(j.stripes)); d0 = s0.duplicate("pgd_gal_w", true); s0.close(SaveOptions.DONOTSAVECHANGES); app.activeDocument = d0; }
      else d0 = work();
      var W = Math.round(Math.min(640, Math.max(200, 16 * j.d))), H = Math.round(W * 9 / 16);
      d0.resizeImage(UnitValue(W, "px"), UnitValue(H, "px"), 72, ResampleMethod.BICUBIC);
      // duplicate after the resize: the history snapshot (history tools' source) must have the canvas size being painted
      doc = d0.duplicate("pgd_gal_w2", true); d0.close(SaveOptions.DONOTSAVECHANGES); app.activeDocument = doc;
      var SUF = "";  // a history preset in a lightening blend mode (Champagne: lighten) paints nothing on white: use black
      if (MODE == 2) { try { if (/lighten|screen|dodge|lighterColor/i.test(tid2s(toolOpts().getEnumerationValue(S2T("mode"))))) SUF = "k"; } catch (eM) {} }
      // no chained ternary here: ExtendScript evaluated (3 == 3 ? 128 : "" ? 0 : 255) to 0 (2026-10-07)
      if (MODE == 2 || MODE == 3) { var g = 255; if (MODE == 3) g = 128; else if (SUF) g = 0; doc.selection.selectAll(); doc.selection.fill(rgbc(g, g, g)); doc.selection.deselect(); }
      var sp = new SubPathInfo(); sp.closed = false; sp.operation = ShapeOperation.SHAPEXOR;
      sp.entireSubPath = [pp(.08*W, .5*H, .08*W, .5*H, .22*W, .06*H), pp(.5*W, .5*H, .36*W, .06*H, .64*W, .94*H), pp(.92*W, .5*H, .78*W, .94*H, .92*W, .5*H)];
      var pth = doc.pathItems.add("pgd_s", [sp]); pth.select();
      var sd = new ActionDescriptor(), sr = new ActionReference(); sr.putEnumerated(C2T("Path"), C2T("Ordn"), C2T("Trgt")); sd.putReference(C2T("null"), sr);
      sd.putClass(C2T("Usng"), S2T(tool)); sd.putBoolean(C2T("Prs "), true); executeAction(C2T("Strk"), sd, DialogModes.NO); pth.remove();
      savePng(doc, j.out); RES[j.k] = "ok|" + tool + "|photo" + MODE + SUF; doc.close(SaveOptions.DONOTSAVECHANGES); doc = null; continue; }
    if (!tt) throw new Error("preset switches to " + tool + ", which DOM strokePath cannot drive (no ToolType for it)");
    closeIf("pgd_gal_brush"); doc = newDoc("pgd_gal_brush", j.s, j.s); var S = j.s;
    // black canvas: erasers paint the white background colour; a preset that saves a light colour (j.dark) is invisible on white
    if (tt == ToolType.ERASER || tt == ToolType.BACKGROUNDERASER || j.dark) { doc.selection.selectAll(); doc.selection.fill(rgbc(0, 0, 0)); doc.selection.deselect(); }
    var sp = new SubPathInfo(); sp.closed = false; sp.operation = ShapeOperation.SHAPEXOR;
    sp.entireSubPath = [pp(.08*S, .5*S, .08*S, .5*S, .22*S, .06*S), pp(.5*S, .5*S, .36*S, .06*S, .64*S, .94*S), pp(.92*S, .5*S, .78*S, .94*S, .92*S, .5*S)];
    var pth = doc.pathItems.add("pgd_s", [sp]); pth.strokePath(tt, true); pth.remove();  // "path" is a host global
    savePng(doc, j.out); RES[j.k] = "ok|" + tool + (j.dark ? "|dark" : ""); } catch (e) { RES[j.k] = "ERR " + String(e); }
  if (doc) try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {}
  try { closeIf("pgd_gal_w"); closeIf("pgd_gal_w2"); } catch (e3) {} }''' % json.dumps(jobs)


def js_styles(jobs):
    return '''bw(); closeIf("pgd_gal_style"); var doc = newDoc("pgd_gal_style", 420, 420);
doc.selection.selectAll(); doc.selection.fill(rgbc(128, 128, 128)); doc.selection.deselect();
var tl = doc.artLayers.add(); tl.kind = LayerKind.TEXT; var ti = tl.textItem; ti.contents = "PGD"; ti.font = "Arial-Black"; ti.size = UnitValue(140, "px");
ti.color = rgbc(225, 225, 225); ti.justification = Justification.CENTER; ti.position = [210, 262]; tl.visible = false;
var JOBS = %s;
for (var i = 0; i < JOBS.length; i++) { var j = JOBS[i], L = null;
  try { L = tl.duplicate(); L.visible = true; doc.activeLayer = L; applyStyleIdx(j.idx); var sig = styleSig();
    if (j.sig !== null && sig != j.sig) throw new Error("panel index mismatch: effects [" + sig + "] expected [" + j.sig + "]");
    savePng(doc, j.out); RES[j.k] = "ok"; } catch (e) { RES[j.k] = "ERR " + String(e); }
  if (L) try { L.remove(); } catch (e2) {} }
doc.close(SaveOptions.DONOTSAVECHANGES);''' % json.dumps(jobs)


def js_sig(kind, idxs):
    """read the panel signature at each index (brush tip ID / enabled effects) for offset detection."""
    if kind == "brush":
        return '''app.currentTool = "paintbrushTool"; var I = %s; var a = [];
for (var i = 0; i < I.length; i++) { try { selBrush(I[i]); a.push(brushSig()); } catch (e) { a.push("ERR"); } } RES.sig = a;''' % json.dumps(idxs)
    return '''closeIf("pgd_gal_sig"); var doc = newDoc("pgd_gal_sig", 64, 64); var L = doc.artLayers.add(); doc.selection.selectAll(); doc.selection.fill(rgbc(9, 9, 9));
var I = %s; var a = [];
for (var i = 0; i < I.length; i++) { try { applyStyleIdx(I[i]); a.push(styleSig()); } catch (e) { a.push("ERR"); } }
doc.close(SaveOptions.DONOTSAVECHANGES); RES.sig = a;''' % json.dumps(idxs)


def js_gradients(file, jobs):
    # (d) a fresh document per job, with a white Background layer under the fill layer. Photoshop makes a fill layer
    # REPLACE a document's only, empty, transparent layer (seen 2026-10-13: 1 layer after the make), so in the
    # 2026-10-04 shared document the first gradient became the bottom layer, the "remove all but the bottom layer"
    # cleanup kept it, and it sat under the next 24 jobs (transparent gradients showed it, Neutral Density stacked)
    return '''var gd = new ActionDescriptor(); gd.fromStream(readBin(%s).substr(6)); var GL = gd.getList(C2T("GrdL"));
var JOBS = %s;
for (var i = 0; i < JOBS.length; i++) { var j = JOBS[i], doc = null;
  try { bw(); closeIf("pgd_gal_grad");
    doc = app.documents.add(UnitValue(480, "px"), UnitValue(300, "px"), 72, "pgd_gal_grad", NewDocumentMode.RGB, DocumentFill.WHITE);
    var g = GL.getObjectValue(j.i).getObjectValue(C2T("Grad")); var nm = g.getString(C2T("Nm  ")); if (nm != j.zname) throw new Error("gradient name " + nm + " != " + j.zname);
    var d = new ActionDescriptor(); var r = new ActionReference(); r.putClass(S2T("contentLayer")); d.putReference(C2T("null"), r);
    var cl = new ActionDescriptor(); var gL = new ActionDescriptor(); gL.putUnitDouble(C2T("Angl"), C2T("#Ang"), 0); gL.putEnumerated(C2T("Type"), C2T("GrdT"), C2T("Lnr "));
    gL.putObject(C2T("Grad"), C2T("Grdn"), g); cl.putObject(C2T("Type"), S2T("gradientLayer"), gL); d.putObject(C2T("Usng"), S2T("contentLayer"), cl);
    executeAction(C2T("Mk  "), d, DialogModes.NO);
    if (doc.layers.length != 2) throw new Error(doc.layers.length + " layers in the render document, expected the gradient over the Background");
    saveWB(doc, j.out, j.out2); RES[j.k] = "ok"; } catch (e) { RES[j.k] = "ERR " + String(e); }
  if (doc) try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {} }''' % (jstr(file), json.dumps(jobs))


def js_patterns(jobs):
    return '''var JOBS = %s;
for (var i = 0; i < JOBS.length; i++) { var j = JOBS[i], doc = null;
  // a white Background under the fill layer: in a transparent document the fill layer replaces the only, empty layer
  // and saveWB has no pixel layer to fill white / black (Photoshop answers with an alert)
  try { closeIf("pgd_gal_pat"); doc = app.documents.add(UnitValue(j.s, "px"), UnitValue(j.s, "px"), 72, "pgd_gal_pat", NewDocumentMode.RGB, DocumentFill.WHITE);
    var d = new ActionDescriptor(); var r = new ActionReference(); r.putClass(S2T("contentLayer")); d.putReference(C2T("null"), r);
    var cl = new ActionDescriptor(); var pL = new ActionDescriptor(); var p = new ActionDescriptor(); p.putString(C2T("Nm  "), j.name); p.putString(C2T("Idnt"), j.pid);
    pL.putObject(C2T("Ptrn"), C2T("Ptrn"), p); cl.putObject(C2T("Type"), S2T("patternLayer"), pL); d.putObject(C2T("Usng"), S2T("contentLayer"), cl);
    executeAction(C2T("Mk  "), d, DialogModes.NO);
    if (doc.layers.length != 2) throw new Error(doc.layers.length + " layers in the render document, expected the pattern over the Background");
    saveWB(doc, j.out, j.out2); RES[j.k] = "ok"; } catch (e) { RES[j.k] = "ERR " + String(e); }
  if (doc) try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {} }''' % json.dumps(jobs)


def js_photo(jobs):
    """jobs: {k, out, mode: 'using'|'duotone', ev, file}"""
    return '''var JOBS = %s;
for (var i = 0; i < JOBS.length; i++) { var j = JOBS[i], doc = null;
  try { doc = work();
    if (j.mode == "duotone") { doc.changeMode(ChangeMode.GRAYSCALE); var a = new ActionDescriptor(); var m = new ActionDescriptor(); m.putPath(S2T("using"), new File(j.file));
      a.putObject(C2T("T   "), C2T("DtnM"), m); executeAction(C2T("CnvM"), a, DialogModes.NO); if (doc.mode != DocumentMode.DUOTONE) throw new Error("not duotone: " + doc.mode); doc.changeMode(ChangeMode.RGB); }
    else if (j.mode == "hdr") { var a = new ActionDescriptor(); a.putInteger(C2T("Dpth"), 32); a.putBoolean(C2T("Mrge"), true); a.putBoolean(C2T("Rstr"), false); executeAction(C2T("CnvM"), a, DialogModes.NO);
      // the descriptor StackSupport.jsx convertFromHDRNoDialog builds for Local Adaptation, filled from the parsed .hdt
      var P = j.p, t = new ActionDescriptor(); t.putInteger(S2T("version"), 4); t.putEnumerated(C2T("Mthd"), S2T("hdrToningMethodType"), S2T("hdrtype4"));
      for (var nk in P.num) t.putDouble(S2T(nk), P.num[nk]);
      t.putBoolean(S2T("smooth"), P.smooth); var cd = new ActionDescriptor(); cd.putString(C2T("Nm  "), "Default"); var cl = new ActionList();
      for (var q = 0; q < P.curve.length; q++) { var pd = new ActionDescriptor(); pd.putDouble(C2T("Hrzn"), P.curve[q][0]); pd.putDouble(C2T("Vrtc"), P.curve[q][1]); pd.putBoolean(C2T("Cnty"), P.curve[q][2] == 1); cl.putObject(C2T("CrPt"), pd); }
      cd.putList(C2T("Crv "), cl); t.putObject(S2T("classFXShapeCurve"), C2T("ShpC"), cd);
      var b = new ActionDescriptor(); b.putInteger(C2T("Dpth"), 8); b.putObject(C2T("With"), S2T("hdrOptions"), t); executeAction(C2T("CnvM"), b, DialogModes.NO); }
    else if (j.mode == "pfilter") { var a = new ActionDescriptor(); var c = new ActionDescriptor(); c.putDouble(C2T("Rd  "), j.rgb[0]); c.putDouble(C2T("Grn "), j.rgb[1]); c.putDouble(C2T("Bl  "), j.rgb[2]);
      a.putObject(C2T("Clr "), C2T("RGBC"), c); a.putInteger(C2T("Dnst"), 50); a.putBoolean(C2T("PrsL"), true); executeAction(S2T("photoFilter"), a, DialogModes.NO); }
    else { var a = new ActionDescriptor(); a.putPath(S2T("using"), new File(j.file)); executeAction(S2T(j.ev), a, DialogModes.NO); }
    savePng(doc, j.out); RES[j.k] = "ok"; } catch (e) { RES[j.k] = "ERR " + String(e); }
  if (doc) try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {} }''' % json.dumps(jobs)


def ensure_loaded(prop, file, append):
    """load a preset library into its panel once per Photoshop session (replace mode: only one file at a time)."""
    tag = (prop, file, append)
    if tag in _SESSION["loaded"]:
        return
    run('loadPreset(%s, %s, %s); RES.ok = 1;' % (prop, jstr(file), "true" if append else "false"), 120, "load")
    if not append:
        _SESSION["loaded"] = {t for t in _SESSION["loaded"] if t[0] != prop}
        _SESSION["offset"] = {k: v for k, v in _SESSION["offset"].items() if k[0] != prop}
    _SESSION["loaded"].add(tag)


def detect_offset(kind, file, its, pos, sigf):
    """panel index of preset p = offset + pos[p]; offset found by matching signatures (tip ID / effects set)."""
    ck = (kind, file)
    if ck in _SESSION["offset"]:
        return _SESSION["offset"][ck]
    samp = [(p, sigf(it)) for p, it in enumerate(its) if sigf(it)]
    samp = samp[:: max(1, len(samp) // 10)][:10] or [(p, sigf(it)) for p, it in enumerate(its)][:6]
    best = (-1, None)
    for w in range(0, 4):
        got = run(js_sig(kind, [w + pos[p] for p, _ in samp]), 120, f"sig:{kind}")["sig"]
        hits = sum(g == s for g, (_, s) in zip(got, samp))
        if hits > best[0]:
            best = (hits, w)
        if hits == len(samp):
            break
    if best[0] < max(1, 0.8 * len(samp)):
        raise RuntimeError(f"{kind} panel offset not found for {file}: best {best} of {len(samp)}")
    _SESSION["offset"][ck] = best[1]
    return best[1]


# ------------------------------------------------------------------ driver
def items_of(cat):
    return [it for it in json.loads(HARVEST.read_text(encoding="utf-8"))["items"] if it["category"] == cat]


def finish(st, it, src, how, **kw):
    k = key(it["id"])
    thumb(src, OUT / f"{k}.png", **kw)
    st.ok(it, how)


def finish_wb(st, it, j, how):
    thumb_wb(j["out"], j["out2"], OUT / f"{key(it['id'])}.png")
    st.ok(it, how)


def batches(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def ps_batch(st, todo, make_js, post, n, per_item_s, tag, setup=None):
    """render `todo` (list of (item, job)) in Photoshop batches; post(item, job) writes the thumbnail.
    setup() runs before every batch (loads libraries; a no-op until a restart drops them)."""
    for chunk in batches(todo, n):
        t0 = time.time()
        jobs = [j for _, j in chunk]
        try:
            guard(tag)
            if setup:
                setup()
            res = run(make_js(jobs), 60 + per_item_s * len(jobs), tag)
        except NoHeadroom:
            st.save()
            raise
        except Exception as e:  # noqa: BLE001
            res = {"__batch__": str(e)}
        _SESSION["since"] += len(jobs)
        if "__batch__" in res or any("not currently available" in str(v) for v in res.values()):
            if not canary():
                log("  canary failed: restarting Photoshop")
                restart()
                if len(chunk) > 1:
                    for one in chunk:  # retry one by one to isolate the item that wedged it
                        ps_batch(st, [one], make_js, post, 1, per_item_s, tag, setup)
                    st.save()
                    continue
            elif "__batch__" in res and len(chunk) > 1:
                for one in chunk:
                    ps_batch(st, [one], make_js, post, 1, per_item_s, tag, setup)
                st.save()
                continue
        for it, j in chunk:
            r = res.get(j["k"], res.get("__batch__", "no result"))
            j["res"] = r
            if str(r).split("|")[0] == "ok" and Path(j["out"]).exists():
                try:
                    post(it, j)
                except Exception as e:  # noqa: BLE001
                    st.fail(it, f"thumbnail: {e}")
            else:
                st.fail(it, r)
        st.save()
        log(f"  {tag}: {len(chunk)} in {time.time() - t0:.1f}s  (ok {len(st.index)} / failed {len(st.failed)}; "
            f"Photoshop {ps_private_gb():.1f} GB)")


def do_shapes(st, items):
    """small shapes in batches of 10; shapes with > 100 KB of path data one per call with a long timeout (a slow shape
    must not reach psdrv's dialog rescue, which would Cancel Photoshop's Progress window and fail the item)."""
    small, big, files = [], [], []
    for file, its in lib_items(items).items():
        bounds = csh_bounds(file)
        assert len(bounds) == len(its)
        pend = [(it, b) for it, b in zip(its, bounds) if not st.done(it)]
        if not pend:
            continue
        files.append(file)
        for it, (sid, t, l, b, r, ln) in pend:
            w, h = max(1, r - l), max(1, b - t)
            sc = 360 / max(w, h)
            W, H = w * sc, h * sc
            k = key(it["id"])
            (big if ln > 100000 else small).append(
                (it, {"k": k, "out": raw(k), "name": it["name"], "id": sid, "t": 200 - H / 2, "l": 200 - W / 2,
                      "b": 200 + H / 2, "r": 200 + W / 2}))
    post = lambda it, j: finish(st, it, j["out"], "applied: custom shape layer (by name + ID), filled near-black on white", bg=(255, 255, 255))  # noqa: E731
    setup = lambda: [ensure_loaded('S2T("customShape")', f, True) for f in files]  # noqa: E731
    ps_batch(st, small, js_shapes, post, 10, 15, "shape", setup)
    ps_batch(st, big, js_shapes, post, 1, 300, "shape-big", setup)


PHOTO_ON = {"1": "on the test photo",
            "2": "on the test photo filled white first, so the stroke paints the photo back from the history snapshot",
            "2k": "on the test photo filled black first (the preset paints in a lightening blend mode, invisible on white), "
                  "so the stroke paints the photo back from the history snapshot",
            "3": "on a mid-grey canvas, with Required/Legacy Patterns and More.pat appended to the Patterns panel first so "
                 "the preset stamps its own pattern",
            "4": "on a chart of saturated colour bands"}


def brush_how(j, res):
    """(index 'how', photo canvas mode or None) of a brush render from its job and the script's 'ok|<tool>|...' result."""
    parts = res.split("|")
    tool = parts[1] if len(parts) > 1 else j["tool"]
    head = (f"applied: brush preset selected in the Brushes panel with its own tool ({tool}) selected first and reset to "
            f"its default options (tool checked after selection), colours reset to black / white before it, diameter set to "
            f"its stored {j['d']:g} px, ")
    if parts[-1].startswith("photo"):
        mode = parts[-1][5:] or "1"
        return (head + f"S-path stroked with that tool via the Stroke Path event (simulated pressure) {PHOTO_ON[mode]}"
                + (f" (the preset loads its saved foreground colour {j['fg']})" if j.get("fg") else "")
                + ("" if mode == "3" else "; thumbnail: result on top, the untouched canvas below")), mode
    if "raser" in tool:
        paint = "on a black canvas: the eraser paints the white background colour"
    elif j.get("fg"):
        paint = f"in the foreground colour the preset saves ({j['fg']}) " + (
            "on a black canvas (too light to see on white)" if j.get("dark") else "on white")
    else:
        paint = "black on white"
    return head + "stroked along an S-path with simulated pressure, " + paint, None


def with_idx(jobs, kind, file):
    w = _SESSION["offset"][(kind, file)]
    return [dict(j, idx=w + j["pos"]) for j in jobs]


def do_panel(st, items, kind):
    """brushes / styles: one library at a time in replace mode, preset addressed by panel index."""
    prop = 'C2T("Brsh")' if kind == "brush" else 'S2T("style")'
    for file, its in lib_items(items).items():
        need = "tool checked" if kind == "brush" and "Converted Legacy Tool Presets" in file else None
        pend = [p for p, it in enumerate(its) if not st.done(it, need) and not st.done(it, "switched Photoshop")]
        if not pend:
            continue
        print(f" {kind} library {file} ({len(pend)} to do)", flush=True)
        pos = seq_positions(file, len(its))
        if kind == "brush":
            def sigf(it):
                return it["extra"].get("sampled_data_id") or ""
        else:
            def sigf(it):
                return ",".join(sorted(it["extra"].get("effects", [])))
        def setup(file=file, its=its, pos=pos, sigf=sigf):
            if kind == "brush" and "Converted Legacy Tool Presets" in file:
                # its Pattern Stamp presets reference Canvas / Clouds / Tie Dye / Gouache Light on Watercolor by name + ID;
                # when that pattern is not in the Patterns panel Photoshop silently stamps the current pattern instead
                ensure_loaded('S2T("pattern")', (INSTALL / "Required/Legacy Patterns and More.pat").as_posix(), True)
            ensure_loaded(prop, file, False)
            return detect_offset(kind, file, its, pos, sigf)
        for attempt in range(2):
            try:
                w = setup()
                break
            except Exception as e:  # noqa: BLE001
                print("  setup failed:", str(e)[:300], flush=True)
                if attempt or canary():
                    for p in pend:
                        st.fail(its[p], f"library setup: {e}")
                    st.save()
                    w = None
                    break
                restart()
        if w is None:
            continue
        meta = brush_meta(file) if kind == "brush" else None
        if meta is not None and len(meta) != len(its):
            raise ValueError(f"{file}: {len(meta)} presets parsed, {len(its)} harvested")
        todo = []
        for p in pend:
            it = its[p]
            if kind == "brush":
                j = brush_job(it, pos[p], meta[p], sigf(it))
            else:
                k = key(it["id"])
                j = {"k": k, "out": raw(k), "pos": pos[p], "sig": sigf(it) if it["extra"].get("effects") is not None else None}
            todo.append((it, j))
        if kind == "brush":
            def post(it, j):
                how, mode = brush_how(j, j.get("res") or "ok|" + j["tool"])
                dst = OUT / f"{key(it['id'])}.png"
                if mode is None:
                    thumb(j["out"], dst, bg=(255, 255, 255))
                elif mode == "3":
                    thumb(j["out"], dst)
                else:
                    thumb_ba(j["out"], stripes() if mode == "4" else photo_base(), dst, top="STROKE WITH PRESET")
                st.ok(it, how)
            ps_batch(st, todo, lambda jobs: js_brushes(with_idx(jobs, kind, file)), post, 10, 25, "brush", setup)
        else:
            post = lambda it, j: finish(st, it, j["out"], "applied: layer style preset on a bold 'PGD' text layer (Arial Black, light grey) over mid-grey")  # noqa: E731
            ps_batch(st, todo, lambda jobs: js_styles(with_idx(jobs, kind, file)), post, 20, 6, "style", setup)
        # a restart inside ps_batch drops the loaded library; the next file reloads it (ensure_loaded)


def do_gradients(st, items):
    for file, its in lib_items(items).items():
        b = Path(file).read_bytes()
        r = pf.R(b)
        r.os(), r.u16()
        d = pf._d16(r)
        znames = [(o.get("Grad") or {}).get("Nm  ", "") for o in d.get("GrdL", [])]
        assert len(znames) == len(its), (file, len(znames), len(its))
        todo = []
        for i, it in enumerate(its):
            if st.done(it, "(foreground black"):
                continue
            k = key(it["id"])
            todo.append((it, {"k": k, "out": raw(k), "out2": raw(k + "_b"), "i": i, "zname": znames[i]}))
        ps_batch(st, todo, lambda jobs, f=file: js_gradients(f, jobs),
                 lambda it, j: finish_wb(st, it, j, "applied: gradient fill layer (linear, 0 deg) with the preset's gradient read from the .grd file (foreground black, background white), alone in a fresh document per gradient, saved over a white and a black Background; transparency shown over a checkerboard"),
                 8, 4, "gradient")  # 8 per batch: 25 fresh documents grew Photoshop by ~2 GB between two memory checks


def do_patterns(st, items):
    todo, files = [], []
    for file, its in lib_items(items).items():
        pend = [it for it in its if not st.done(it, "transparent pattern pixels")]
        if not pend:
            continue
        files.append(file)
        for it in pend:
            todo.append((it, pattern_job(it)))
    ps_batch(st, todo, js_patterns, lambda it, j: finish_wb(st, it, j, pattern_how(j)),
             8, 8, "pattern", lambda: [ensure_loaded('S2T("pattern")', f, True) for f in files])


# (e) the fill is rendered on a square exactly as big as the thumbnail's inner box and shown 1:1: the 2026-10-04 run
# rendered up to 1200 px and shrank it to 25-29%, which averaged fine grain to flat grey. A tile larger than the box
# shows a crop (its top-left PAT_S x PAT_S px) instead of being shrunk.
PAT_S = 300


def pattern_job(it):
    x, k = it["extra"], key(it["id"])
    return {"k": k, "out": raw(k), "out2": raw(k + "_b"), "name": it["name"], "pid": x["pattern_id"], "s": PAT_S,
            "tile": [x.get("width"), x.get("height")]}


def pattern_how(j):
    w, h = j["tile"]
    crop = (f"; the {w} x {h} px tile is larger than the square, so this is a 1:1 crop of its top-left {j['s']} px, "
            "never shrunk") if max(w or 0, h or 0) > j["s"] else f" ({w} x {h} px tile, repeats visible)"
    return (f"applied: pattern fill layer (100% scale) on a {j['s']} px square shown 1:1 in the thumbnail{crop}; "
            "transparent pattern pixels shown over a checkerboard")


ADJ = {"Curves preset": "curves", "Levels preset": "levels", "Hue/Saturation preset": "hueSaturation",
       "Black & White preset": "blackAndWhite", "Channel Mixer preset": "channelMixer", "Exposure preset": "exposure"}


def do_photo(st, items, cat):
    todo = []
    for it in items:
        if st.done(it):
            continue
        k = key(it["id"])
        f = it["invoke"]["file"]
        if cat == "Duotone preset":
            j = {"mode": "duotone", "file": f}
            how = "applied: test photo converted to Grayscale, then Duotone mode with the preset file, then RGB for display"
        elif cat == "HDR Toning preset":
            j = {"mode": "hdr", "p": parse_hdt(f)}
            how = ("applied: test photo converted to 32 bit, then back to 8 bit with HDR Toning (Local Adaptation) given the "
                   "preset's values parsed from the .hdt (radius, strength, exposure, gamma, detail, shadow, highlight, vibrance, "
                   "saturation, smooth edges, toning curve) as an explicit hdrOptions descriptor; the field order of the "
                   ".hdt was inferred from the 16 shipped files (the Monochromatic presets render grey, More Saturated "
                   "saturated), so treat the exact gamma/exposure scale as unverified")
        else:
            j = {"mode": "using", "ev": ADJ[cat], "file": f}
            how = f"applied: {ADJ[cat]} adjustment with using=<preset file> on the test photo"
        j.update({"k": k, "out": raw(k), "how": how})
        todo.append((it, j))
    if not todo:
        return
    before = photo_base()

    def post(it, j):
        thumb_ba(j["out"], before, OUT / f"{key(it['id'])}.png")
        st.ok(it, j["how"] + "; thumbnail: result on top, the untouched test photo below for comparison")
    ps_batch(st, todo, js_photo, post, 8, 15, cat)


def do_pfilter(st, items):
    """Default Filter Colors: the test photo through each of the library's Photo Filter colors, as a grid."""
    for it in items:
        if st.done(it):
            continue
        k = key(it["id"])
        cols = it["extra"]["entry_colors"]
        jobs = [{"k": f"{k}_{i}", "out": raw(f"{k}_{i}"), "mode": "pfilter", "rgb": list(to_rgb(c))} for i, c in enumerate(cols)]
        try:
            res = run(js_photo(jobs), 60 + 10 * len(jobs), "pfilter")
            bad = {j["k"]: v for j in jobs if (v := res.get(j["k"])) != "ok"}
            if bad:
                raise RuntimeError(f"tiles failed: {bad}")
            grid = Image.new("RGB", (SIZE, SIZE), BG)
            c, tw = 4, SIZE // 4
            th = tw * 9 // 16
            for i, j in enumerate(jobs):
                t = Image.open(j["out"]).convert("RGB").resize((tw - 2, th - 2), Image.LANCZOS)
                grid.paste(t, ((i % c) * tw + 1, (SIZE - th * 5) // 2 + (i // c) * th + 1))
            grid.save(OUT / f"{k}.png")
            st.ok(it, f"applied: photoFilter (density 50%, preserve luminosity) with each of the {len(jobs)} library colors on the test photo, tiles in file order (4 per row)")
        except Exception as e:  # noqa: BLE001
            st.fail(it, f"photo filter grid: {e}")
    st.save()


def read_lut(path):
    """3D LUT table -> numpy array [r][g][b] -> (r, g, b) in 0..1. .cube: red fastest; .3dl: blue fastest."""
    import numpy as np
    import re
    if path.lower().endswith(".look"):
        # SpeedGrade .look: XML shader parameters plus the look baked into <LUT><size>N</size><data>hex</data>: N^3 RGB
        # little-endian float32 triplets, red index fastest (checked: entry N-1 of 2Strip.look is pure red)
        m = re.search(r'<LUT>\s*<size>"?(\d+)"?</size>\s*<data>"?([0-9A-Fa-f\s]+)"?\s*</data>', Path(path).read_text(encoding="latin-1"))
        if not m:
            raise ValueError("no baked <LUT> in the .look")
        n = int(m.group(1))
        v = np.frombuffer(bytes.fromhex(re.sub(r"\s", "", m.group(2))), dtype="<f4").astype(float)
        return np.transpose(v.reshape(n, n, n, 3), (2, 1, 0, 3)), [0.0] * 3, [1.0] * 3
    txt = Path(path).read_text(encoding="latin-1").splitlines()
    if path.lower().endswith(".cube"):
        n, lo, hi, vals = 0, [0.0] * 3, [1.0] * 3, []
        for ln in txt:
            t = ln.split()
            if not t or t[0].startswith("#") or t[0] == "TITLE":
                continue
            if t[0] == "LUT_3D_SIZE":
                n = int(t[1])
            elif t[0] == "DOMAIN_MIN":
                lo = [float(x) for x in t[1:4]]
            elif t[0] == "DOMAIN_MAX":
                hi = [float(x) for x in t[1:4]]
            elif t[0][0] in "-.0123456789":
                vals.append([float(x) for x in t[:3]])
        a = np.array(vals).reshape(n, n, n, 3)  # [b][g][r]
        return np.transpose(a, (2, 1, 0, 3)), lo, hi
    rows = [[int(x) for x in ln.split()] for ln in txt if ln.strip() and ln.split()[0].isdigit()]
    mesh = rows[0]
    n = len(mesh)
    vals = np.array([r for r in rows[1:] if len(r) == 3][: n ** 3], dtype=float)
    vals /= 4095.0 if vals.max() > 1023 else 1023.0
    return vals.reshape(n, n, n, 3), [0.0] * 3, [1.0] * 3  # [r][g][b]


def apply_lut(img, lut, lo, hi):
    import numpy as np
    a = np.asarray(img.convert("RGB"), dtype=float) / 255.0
    n = lut.shape[0]
    x = np.clip((a - lo) / (np.array(hi) - lo), 0, 1) * (n - 1)
    i0 = np.floor(x).astype(int).clip(0, n - 2)
    f = x - i0
    out = 0
    for dr in (0, 1):
        for dg in (0, 1):
            for db in (0, 1):
                w = (f[..., 0] if dr else 1 - f[..., 0]) * (f[..., 1] if dg else 1 - f[..., 1]) * (f[..., 2] if db else 1 - f[..., 2])
                out = out + w[..., None] * lut[i0[..., 0] + dr, i0[..., 1] + dg, i0[..., 2] + db]
    return Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype("uint8"))


def do_lut(st, items):
    todo = [it for it in items if not st.done(it)]
    if not todo:
        return
    base = photo_base()
    src = Image.open(base)
    for it in todo:
        f = it["invoke"]["file"]
        try:
            lut, lo, hi = read_lut(f)
            k = key(it["id"])
            apply_lut(src, lut, lo, hi).save(RAW / f"{k}.png")
            thumb_ba(RAW / f"{k}.png", base, OUT / f"{k}.png")
            what = ("the look's baked LUT (the <LUT> table inside the SpeedGrade .look, %d^3)" % lut.shape[0]) if f.lower().endswith(".look")                 else "the LUT table (%d^3)" % lut.shape[0]
            st.ok(it, f"applied (outside Photoshop): {what} trilinear-interpolated in Python on the 640x360 test photo, because "
                      "Photoshop's Color Lookup ignores LUT data passed by script (it renders only from the ICC profile its dialog "
                      "builds; tested 2026-10-04); thumbnail: result on top, the untouched test photo below for comparison")
        except Exception as e:  # noqa: BLE001
            st.fail(it, f"lut: {e}")
    st.save()


def parse_hdt(path):
    """.hdt (HDR Toning preset, 'hdrt' v3) -> the Local Adaptation values under the Action Manager keys that
    StackSupport.jsx convertFromHDRNoDialog uses. convertMode with using=<.hdt> ignores the file (2026-10-04), so the
    preset is passed as an explicit hdrOptions descriptor. Layout read from the 16 shipped presets (2026-10-07):
    'hdrt' u32 version | f32 threshold (Strength) | u32 | u32 n + UTF-16 curve name | u16, u16 npts, npts x (u16 out,
    u16 in), npts continuity bytes | u32 0, u32 0 | f32 radius | u32 method (3 = Local Adaptation) | f32, f32 (Exposure and
    Gamma method, unused) | 'hdra' u32 6 | f32 exposure, saturation, detail, shadow, highlight, gamma, vibrance | smooth."""
    b = Path(path).read_bytes()
    assert b[:4] == b"hdrt", b[:4]
    thr, = struct.unpack(">f", b[8:12])
    n, = struct.unpack(">I", b[16:20])
    p = 20 + 2 * n
    _, npts = struct.unpack(">HH", b[p:p + 4])
    p += 4
    pts = [struct.unpack(">HH", b[p + 4 * k:p + 4 * k + 4]) for k in range(npts)]
    flags = b[p + 4 * npts:p + 5 * npts]
    p += 5 * npts + 8
    radius, method = struct.unpack(">fI", b[p:p + 8])
    a = b.index(b"hdra", p)
    v = struct.unpack(">7f", b[a + 8:a + 36])
    if method != 3:
        raise ValueError(f"method {method} (only Local Adaptation presets are mapped)")
    num = dict(zip(("brightness", "saturation", "detail", "shallow", "highlights", "contrast", "vibrance"), v))
    num.update(radius=radius, threshold=thr)
    return {"num": {k: round(x, 4) for k, x in num.items()}, "smooth": any(b[a + 36:a + 40]),
            "curve": [[x, y, flags[k]] for k, (y, x) in enumerate(pts)]}


def do_contours(st, items):
    for file, its in lib_items(items).items():
        curves = shc_curves(file)
        for it, (nm, pts) in zip(its, curves):
            if st.done(it):
                continue
            if nm != it["name"] or len(pts) < 2:
                st.fail(it, f"contour parse: name {nm!r} / {len(pts)} points")
                continue
            draw_contour([(x, y, c) for x, y, c in pts], OUT / f"{key(it['id'])}.png")
            st.ok(it, "applied: contour curve parsed from the .shc file and plotted (x = input 0-255, y = output; natural cubic spline, broken at corner points; red dots = smooth points, red squares = corner points)")
    st.save()


def do_sky(st, items):
    b = Path(items[0]["invoke"]["file"]).read_bytes()
    r = pf.R(b, 6)
    n = pf._d16(r).get("spCt", 0)
    ids = {}
    for _ in range(n):
        ln = r.u32()
        st0 = r.p
        d = pf._d16(r)
        ids[pf.zlabel(d.get("skpN", ""))] = d.get("Szid")
        r.p = st0 + ln
        r.align(4)
    folder = Path(items[0]["invoke"]["file"]).parent
    for it in items:
        if st.done(it):
            continue
        sid = ids.get(it["name"])
        src = folder / f"{sid}.jpg"
        if not sid or not src.exists():
            st.fail(it, f"sky image not found (Szid {sid})")
            continue
        finish(st, it, src, f"file image: the sky photo the preset points to (Sky_Presets/{sid}.jpg)")
    st.save()


def do_swatches(st, items):
    for it in items:
        if st.done(it):
            continue
        try:
            f = it["invoke"]["file"]
            cols = acb_rgb(f) if f.lower().endswith(".acb") else [to_rgb(c) for c in it["extra"]["entry_colors"]]
            swatch_strip(cols, OUT / f"{key(it['id'])}.png")
            st.ok(it, f"swatch strip: all {len(cols)} colors in file order, converted to sRGB for display (Lab D50 / naive CMYK)")
        except Exception as e:  # noqa: BLE001
            st.fail(it, f"swatch strip: {e}")
    st.save()


def mark_not_renderable(st, items):
    for it in items:
        why = NOT_VISUAL[it["category"]]
        if it["category"] == "Action":
            steps = it.get("extra", {}).get("steps")
            why = {"reason": why, "set": it.get("extra", {}).get("set"), "steps": steps} if steps else \
                {"reason": why, "steps_error": it.get("error", "steps not readable from the .atn")}
        st.notr[it["id"]] = why
    st.save()


HANDLERS = {"Custom shape": do_shapes, "Brush": lambda st, it: do_panel(st, it, "brush"),
            "Layer style": lambda st, it: do_panel(st, it, "style"), "Gradient": do_gradients, "Pattern": do_patterns,
            "Contour": do_contours, "Sky (Sky Replacement)": do_sky, "Swatch library": do_swatches,
            "Color book": do_swatches, "Photo Filter colors": do_pfilter, "3D LUT": do_lut}
for _c in ["Duotone preset", "HDR Toning preset"] + list(ADJ):
    HANDLERS[_c] = (lambda c: (lambda st, it: do_photo(st, it, c)))(_c)


def main(cats, ids_file=None):
    global ONLY
    (RAW.parent / "renderer.pid").write_text(str(os.getpid()))  # stop THIS renderer by pid, never by name
    st = State()
    allit = json.loads(HARVEST.read_text(encoding="utf-8"))["items"]
    mark_not_renderable(st, [i for i in allit if i["category"] in NOT_VISUAL])
    if ids_file:
        want = set(read_ids(ids_file))
        cat_of = {i["id"]: i["category"] for i in allit}
        unknown = sorted(want - set(cat_of))
        if unknown:
            sys.exit(f"ids not in the harvest: {unknown[:5]}")
        ONLY = want - st.fresh  # resume: ids already rendered again by an earlier --ids run are kept
        keep_old(st, ONLY)
        st.save()
        cats = [c for c in ORDER if c in {cat_of[i] for i in ONLY}]
        log(f"== --ids {ids_file}: {len(want)} ids, {len(ONLY)} to render again ({len(want) - len(ONLY)} done before)")
    if ps()._ps_pids() and not ps().owned_pid():
        sys.exit("a Photoshop this pipeline did not start (work/ps/ps.pid) is running: not sending it scripts")
    try:
        if not ps()._ps_pids():  # start Photoshop ourselves (a COM Dispatch would launch it outside the guard)
            guard("start")
            log("  starting Photoshop")
            restart()
        for cat in cats:
            its = [i for i in allit if i["category"] == cat]
            if cat not in HANDLERS:
                print("no handler:", cat)
                continue
            log(f"== {cat}: {len(its)} ({sum(not st.done(i) for i in its)} to do)")
            HANDLERS[cat](st, its)
    except NoHeadroom as e:
        log(f"STOPPED (resume later): {e}")
    st.save()
    missing = [i["id"] for i in allit if key(i["id"]) not in st.index and i["id"] not in st.failed and i["id"] not in st.notr]
    print(f"index {len(st.index)}  failed {len(st.failed)}  not_renderable {len(st.notr)}  missing {len(missing)}")


def selftest():
    allit = json.loads(HARVEST.read_text(encoding="utf-8"))["items"]
    for file, its in lib_items([i for i in allit if i["category"] in ("Custom shape", "Brush", "Layer style", "Gradient", "Pattern")]).items():
        ents, _ = pf.parse_file(file)
        assert [e["name"] for e in ents] == [i["name"] for i in its], file
    assert len(csh_bounds(INSTALL / "Required/Default Custom Shapes.csh")) == 54
    c = shc_curves(INSTALL / "Required/Default Contours.shc")
    assert c[0] == ("Linear", [(0, 0, 1), (255, 255, 1)]) and c[1][1][1] == (129, 255, 1), c[:2]
    assert contour_ys([(0, 0, 1), (255, 255, 1)])[128] == 128
    assert lab2rgb(100, 0, 0) == (255, 255, 255) and lab2rgb(0, 0, 0) == (0, 0, 0)
    assert seq_positions(INSTALL / "Required/Default Brushes.abr", 28)[:2] == [2, 3]
    assert key("x") == hashlib.sha1(b"x").hexdigest()[:12]
    h = parse_hdt(INSTALL / "Presets/HDR Toning/City Twilight.hdt")
    assert h["num"]["radius"] == 183 and h["num"]["threshold"] == 1.15 and h["num"]["detail"] == 98, h
    assert h["curve"][1] == [53, 48, 1] and len(h["curve"]) == 5, h["curve"]
    assert parse_hdt(INSTALL / "Presets/HDR Toning/Monochromatic.hdt")["num"]["saturation"] == -100
    print("preset_gallery selftest ok")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a == ["--selftest"]:
        selftest()
    elif a[:1] == ["--ids"]:
        main(ORDER, a[1])
    else:
        main(a or ORDER)
