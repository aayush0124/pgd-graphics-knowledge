"""PGD/CDR effect gallery: every cdr_effect card's demo_settings rendered in CorelDRAW 2024 -> gallery/cdr_effect/

    python effect_gallery.py                  # all cards, resumable (skips cards whose PNG exists / not_rendered)
    python effect_gallery.py --ids ids.txt    # re-render just these card ids (one per line, or a JSON list / dict)
    python effect_gallery.py --rerender       # ignore existing PNGs
    python effect_gallery.py --refs           # reference frames only (ref_photo / ref_vector / ref_lens)
    python effect_gallery.py --no-probe       # skip the per-key perturbation test (no `dropped` detection)
    python stop_effect_gallery.py             # stop a run: kills ONLY the pid in work/cdr/effect_gallery/run.pid.json
                                              # (all three apps' renderers are named effect_gallery.py: never kill
                                              # by command-line match)

Output: <key>.png (960x540, key = sha1(card id)[:12]), index.json, failed.json, not_rendered.json, ref_*.png.
Every card ends in exactly one of the three json files.
1:1 detail crop: the 960x540 frame is a 2x downsample of the 1920x1080 plate, which averages away pixel-scale effects
(sharpen, smooth, noise, blur, edge). Bitmap cards whose harvest path is under Blur / Sharpen / Noise / Contour /
Correction (plus Diffuse and DeInterlace) also get <key>_1to1.png: the page region CROP_BOX (x, y, w, h px of the
1920x1080 page, top-left origin) exported at 100 % from the same render as the main frame (bottom-right of the plate:
hairline stripes, colour-bar edges, grey ramp, small bright highlights, a thin dark diagonal). The index row records
it as "crop": {"file", "box", "scale"}. On the plain plate the crop equals the PIL crop of plate_photo.png exactly.

One scratch document we own (closed unsaved): page 20 x 11.25 in (= 1920x1080 px at 96 px/in, bottom-left origin,
document unit inch, which is what the cards' vector offsets assume). A hidden, non-printing "PGD masters" layer holds
the plates; each render duplicates what it needs onto the work layer, applies, exports the page, deletes.
  photo   plate_photo.png as a 1920x1080 bitmap filling the page              -> bitmap / camera / colour / texture
  vector  plate_vector.svg shapes (star = the effect target; Blend: orange box into the star) on the white page
  lens    photo in the left half + the vector plate at 50 % in the right half, lens circle r 300 px at (960, 540)

Bitmap effects: Bitmap.ApplyBitmapEffect('PGD gallery', '<effect_id> k=v,...') with the card values (bools as 1/0,
enum value or label -> the harvested enum value, numbers as given even beyond the dialog range); harvested defaults
are sent for every other scalar param, because an omitted or unknown key silently keeps the effect's LAST-USED value
(probe 2026-10-04: 'Vignette=false' gave the pixels of the previous 'Vignette=1'). `dropped` = demo keys whose
perturbed value gives the same pixels as the demo value (the app ignored them), above the repeat-render noise floor.
Vector effects / lenses: the typelib Create* call with the card values in harvested parameter order (harvested
defaults elsewhere, colours via CreateRGBColor, VT_DISPATCH defaults as None); `applied` is read back from the
effect object where it has a property of that name, `dropped` = keys whose read-back differs from what was sent.
"""
import argparse, glob, hashlib, json, os, sys, time
from pathlib import Path

from PIL import Image, ImageChops

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("PGD_HOME") or HERE.parents[1])  # repo root; PGD_HOME overrides
sys.path.insert(0, str(HERE))
OUT = ROOT / "gallery" / "cdr_effect"
TMP = ROOT / "work" / "cdr" / "effect_gallery"
PHOTO = ROOT / "media" / "plate_photo.png"
SVG = ROOT / "media" / "plate_vector.svg"
PIDFILE = TMP / "run.pid.json"  # {"pid", "script", "started"} of the running renderer (see stop_effect_gallery.py)
PX = 96.0                      # px per inch on the 20 x 11.25 in page
PW, PH = 20.0, 11.25
BL = 5                         # cdrBottomLeft
LENS_C, LENS_R = (10.0, 5.625), 300 / PX
SCALAR = ("number", "int", "bool", "enum")
CROP_BOX = (1408, 568, 512, 512)   # x, y, w, h in px of the 1920x1080 page, top-left origin
CROP_SUFFIX = "_1to1"
DETAIL_PATHS = ("Effects/Blur/", "Effects/Sharpen/", "Effects/Noise/", "Effects/Contour/", "Effects/Correction/")
DETAIL_NAMES = {"Diffuse", "DeInterlace"}   # pixel-scale effects filed under Camera / Transform


def key(iid):
    return hashlib.sha1(iid.encode("utf-8")).hexdigest()[:12]


def wants_crop(it):
    """harvest item of a pixel-scale effect (its look lives at the pixel level) -> True"""
    return (it.get("path") or "").startswith(DETAIL_PATHS) or it.get("name") in DETAIL_NAMES


def crop_path(png):
    """the 1:1 crop that goes with a frame: r00012.png -> r00012_1to1.png, <key>.png -> <key>_1to1.png"""
    png = Path(png)
    return png.with_name(png.stem + CROP_SUFFIX + png.suffix)


def crop_rect(box=CROP_BOX):
    """CROP_BOX (px, top-left origin) -> CreateRect(x, y, w, h) in page inches; Rect y is the BOTTOM edge (the page has
    a bottom-left origin; a top-edge y exported the wrong strip, diff 77 vs the plate crop, probe 2026-10-13)"""
    x, y, w, h = box
    return x / PX, PH - (y + h) / PX, w / PX, h / PX


def diff(a, b):
    """mean absolute RGB difference of two PNG files (0 = identical, 999 = different size)."""
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    if ia.size != ib.size:
        return 999.0
    h = ImageChops.difference(ia, ib).histogram()
    return round(sum(i % 256 * c for i, c in enumerate(h)) / (ia.size[0] * ia.size[1] * 3), 4)


def flat(path, sd=1.5):
    """True when the frame is (almost) a single colour"""
    from PIL import ImageStat
    return max(ImageStat.Stat(Image.open(path).convert("RGB")).stddev) < sd


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/hostlock.py: vendored, same host mutex
from hostlock import headroom  # noqa: E402

MIN_ROOM_GB = 4.0              # commit headroom wanted before every batch (the box runs near its commit limit)


def room_gb():
    """free commit in GB (limit - used), or None when it cannot be read."""
    _, used, lim, _ = headroom()
    return None if used is None else round(lim - used, 2)


def wait_room(need=MIN_ROOM_GB, max_wait=1800):
    # ponytail: polls the host commit charge; other pipelines (Photoshop, ffmpeg) swing it by 10 GB in a minute
    t0 = time.time()
    while True:
        r = room_gb()
        if r is None or r >= need:
            return r
        if time.time() - t0 > max_wait:
            print(f"  commit headroom still {r} GB after {max_wait}s; going on", flush=True)
            return r
        print(f"  commit headroom {r} GB < {need} GB: waiting", flush=True)
        time.sleep(30)


# ---------------------------------------------------------------- cards / values
def load_cards():
    cards = [c for f in sorted(glob.glob(str(ROOT / "cards" / "cdr_effect_*.json")))
             for c in json.loads(Path(f).read_text(encoding="utf-8"))["cards"]]
    items = {i["id"]: i for i in json.loads((ROOT / "harvest" / "cdr" / "cdr_effect.json")
                                            .read_text(encoding="utf-8"))["items"]}
    return cards, items


def find_param(params, k):
    return next((p for p in params if p.get("key") == k), None) or next((p for p in params if p.get("name") == k),
                                                                        None)


def truthy(v):
    return v not in (False, 0, "0", "false", "False", None, "")


def fmt(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(int(v)) if float(v).is_integer() else f"{v:g}"
    return str(v)


def enum_value(p, v):
    """card value (enum value or label) -> the harvested enum value; None if it matches neither."""
    for e in p.get("enum") or []:
        if str(e["value"]) == str(v):
            return e["value"]
    for e in p.get("enum") or []:
        if str(e.get("label", "")).lower() == str(v).lower():
            return e["value"]
    return None


def enum_index(p, v):
    """card enum value / label -> its position in the harvested enum list (duplicates collapsed), as text"""
    vals = list(dict.fromkeys(str(e["value"]) for e in p.get("enum") or []))
    ev = enum_value(p, v)
    return str(vals.index(str(ev))) if ev is not None and str(ev) in vals else to_cmd_value(p, v)


def to_cmd_value(p, v):
    t = p.get("type")
    if t == "bool":
        return "1" if truthy(v) else "0"
    if t == "enum":
        ev = enum_value(p, v)
        return fmt(ev if ev is not None else v)
    return fmt(v)


def perturb(p, v):
    """a different, valid value for p (to see whether the app reads the key), or None."""
    t = p.get("type")
    if t == "bool":
        return not truthy(v)
    if t == "enum":
        vals = list(dict.fromkeys(e["value"] for e in p.get("enum") or []))
        cur = enum_value(p, v)
        d = p.get("default")
        if d in vals and str(d) != str(cur):
            return d
        return next((x for x in vals if str(x) != str(cur)), None)
    if t == "color":
        return "#00FF00" if str(v).upper() != "#00FF00" else "#FF00FF"
    if t in ("number", "int") and isinstance(v, (int, float)) and not isinstance(v, bool):
        lo, hi, d = p.get("min"), p.get("max"), p.get("default")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and hi > lo:
            if isinstance(d, (int, float)) and lo <= d <= hi and abs(d - v) >= 0.25 * (hi - lo):
                alt = d
            else:
                far = lo if abs(v - lo) >= abs(v - hi) else hi
                alt = v + 0.6 * (far - v)
        else:
            alt = d if isinstance(d, (int, float)) and d != v else (v * 2 if v else 10)
        if t == "int":
            alt = round(alt)
        return None if alt == v else alt
    return None


# ---------------------------------------------------------------- state
class State:
    def __init__(self):
        OUT.mkdir(parents=True, exist_ok=True)
        TMP.mkdir(parents=True, exist_ok=True)
        rd = lambda n, d: json.loads((OUT / n).read_text(encoding="utf-8")) if (OUT / n).exists() else d
        self.index = {r["id"]: r for r in rd("index.json", [])}
        self.failed = rd("failed.json", {})
        self.nr = rd("not_rendered.json", {})

    def forget(self, iid):
        self.index.pop(iid, None)
        self.failed.pop(iid, None)
        self.nr.pop(iid, None)

    def put(self, card, tmp_png, applied, dropped, how, note=None):
        k = key(card["id"])
        os.replace(tmp_png, OUT / f"{k}.png")
        self.forget(card["id"])
        row = {"key": k, "id": card["id"], "name": card["name"], "applied": applied, "dropped": dropped, "how": how}
        if note:
            row["note"] = note
        crop = crop_path(OUT / f"{k}.png")
        if crop_path(tmp_png).exists():          # exported by the same render as the frame
            os.replace(crop_path(tmp_png), crop)
            row["crop"] = {"file": crop.name, "box": list(CROP_BOX), "scale": "1:1"}
        else:
            crop.unlink(missing_ok=True)         # never leave a crop from an older render next to a new frame
        self.index[card["id"]] = row

    def drop_frames(self, card):
        png = OUT / f"{key(card['id'])}.png"
        png.unlink(missing_ok=True)
        crop_path(png).unlink(missing_ok=True)

    def fail(self, card, err):
        self.forget(card["id"])
        self.drop_frames(card)
        self.failed[card["id"]] = str(err)[:600]

    def not_rendered(self, card, reason):
        self.forget(card["id"])
        self.drop_frames(card)   # a card that turned not-current keeps no frame
        self.nr[card["id"]] = reason

    def save(self):
        w = lambda n, o: (OUT / n).write_text(json.dumps(o, indent=1, ensure_ascii=False), encoding="utf-8")
        w("index.json", list(self.index.values()))
        w("failed.json", self.failed)
        w("not_rendered.json", self.nr)


# ---------------------------------------------------------------- the CorelDRAW scene
class Scene:
    def __init__(self):
        from cdr_com import Corel, NotOurCorel
        wait_room()
        # own=True: this run starts its own CorelDRAW 2024 and never drives one another client started (two runs on
        # one CorelDRAW clobbered each other's documents and json, 2026-10-06)
        try:
            self.cd = Corel(own=True)
        except NotOurCorel:
            raise
        except Exception:  # noqa: BLE001 - right after a kill, CoCreateInstance can hit the dying server (RPC failed)
            time.sleep(15)
            self.cd = Corel(own=True)
        try:
            rec = json.loads(PIDFILE.read_text(encoding="utf-8"))
            if rec.get("pid") == os.getpid():
                rec["corel"] = sorted(self.cd.pids)
                PIDFILE.write_text(json.dumps(rec), encoding="utf-8")
        except (OSError, ValueError):
            pass
        self.s = {}
        self.n = 0
        # one call per step, so a hang names its step; imports can take minutes
        try:
            for step, t in ((self._doc, 120), (self._photo, 900), (self._svg, 300), (self._finish, 300)):
                print("  scene:", step.__name__, self.call(step, t, "scene " + step.__name__), flush=True)
        except Exception:
            if "doc" in self.s:
                print("  scene build failed, closing our document:", self.close(), flush=True)
            raise

    def call(self, fn, timeout=150, note=""):
        return self.cd.call(fn, timeout=timeout, grace=20, note=note)

    def _doc(self, a):
        s = self.s
        s["app"] = a
        doc = a.CreateDocument()
        s["doc"] = doc
        doc.Unit = 1                                  # cdrInch
        pg = doc.ActivePage
        pg.SetSize(PW, PH)
        s["work"] = doc.ActiveLayer
        # masters live on page 2: a hidden layer on page 1 is still exported, a non-printing one makes ExportBitmap
        # fail with E_FAIL (2026-10-04); ExportBitmap(Range=cdrCurrentPage) only sees page 1
        p2 = doc.AddPagesEx(1, PW, PH)
        s["masters"] = p2.CreateLayer("PGD masters")
        pg.Activate()
        s["work"].Activate()
        return doc.Title

    def _import(self, path):
        """import into the active (work) layer, the route proven in testdoc / the probe -> new top-level shapes"""
        w = self.s["work"]
        n0 = w.Shapes.Count
        w.Import(str(path), 0, None)                  # returns void; Options (VT_DISPATCH) must be None
        return [w.Shapes.Item(i) for i in range(1, w.Shapes.Count - n0 + 1)]

    def _photo(self, a):
        ph = self._import(PHOTO)[0]                   # 1920 px over 20 in = 96 px/in
        ph.SetBoundingBox(0.0, 0.0, PW, PH, False, BL)
        self.s["photo"] = ph
        return ph.Type, ph.Bitmap.SizeWidth, ph.Bitmap.SizeHeight

    def _svg(self, a):
        """the plate_vector.svg shapes, drawn with the object model from the SVG's own geometry.
        Layer.Import of the SVG hung CorelDRAW 2024 here (2026-10-04: > 10 min, CPU and read bytes flat, no
        visible dialog), so the five elements are rebuilt natively: same ids, coordinates, fills and strokes."""
        import xml.etree.ElementTree as ET
        ns = "{http://www.w3.org/2000/svg}"
        el = {e.get("id"): e for e in ET.parse(SVG).getroot().iter() if e.get("id")}
        w, doc = self.s["work"], self.s["doc"]
        X = lambda v: float(v) / PX
        Y = lambda v: PH - float(v) / PX

        def col(h):
            return rgb(a, h)

        def stroke(sh, e):
            if e.get("stroke") and e.get("stroke") != "none":
                sh.Outline.Width = X(e.get("stroke-width", "1"))
                sh.Outline.Color.CopyAssign(col(e.get("stroke")))
            else:
                sh.Outline.SetNoOutline()

        def poly(e, closed):
            pts = [tuple(map(float, p.split(","))) for p in e.get("points").split()]
            crv = a.CreateCurve(doc)
            sp = crv.CreateSubPath(X(pts[0][0]), Y(pts[0][1]))
            for x, y in pts[1:]:
                sp.AppendLineSegment(X(x), Y(y))
            sp.Closed = closed
            return w.CreateCurve(crv)

        out = {}
        r = el["orange_box"]
        rx = X(r.get("rx", "0"))
        sh = w.CreateRectangle2(X(r.get("x")), Y(float(r.get("y")) + float(r.get("height"))), X(r.get("width")),
                                X(r.get("height")), rx, rx, rx, rx)
        sh.Fill.ApplyUniformFill(col(r.get("fill")))
        stroke(sh, r)
        out["orange_box"] = sh
        s = el["blue_star"]
        sh = poly(s, True)
        sh.Fill.ApplyUniformFill(col(s.get("fill")))
        stroke(sh, s)
        out["blue_star"] = sh
        c = el["grad_circle"]
        sh = w.CreateEllipse2(X(c.get("cx")), Y(c.get("cy")), X(c.get("r")))
        stops = [st.get("stop-color") for st in el["g"].iter(ns + "stop")]
        sh.Fill.ApplyFountainFill(col(stops[0]), col(stops[-1]), 1, -45.0)   # x1,y1 0,0 -> x2,y2 1,1: TL -> BR
        sh.Outline.SetNoOutline()
        out["grad_circle"] = sh
        t = el["pgd_type"]
        sh = w.CreateArtisticText(0.0, 0.0, t.text, 0, -1, "Arial Black", float(t.get("font-size")) * 72 / PX)
        sh.Fill.ApplyUniformFill(col(t.get("fill")))
        sh.Outline.SetNoOutline()
        sh.SetPosition(X(t.get("x")) - sh.SizeWidth / 2, Y(t.get("y")) + sh.SizeHeight)  # bottom ~ baseline
        out["pgd_type"] = sh
        z = el["zigzag"]
        sh = poly(z, False)
        sh.Fill.ApplyNoFill()
        stroke(sh, z)
        out["zigzag"] = sh
        for k, v in out.items():
            v.Name = k
        self.s["vec"] = out
        return {k: (v.Type, round(v.LeftX, 2), round(v.BottomY, 2), round(v.SizeWidth, 2)) for k, v in out.items()}

    def _finish(self, a):
        s = self.s
        m, doc, ph = s["masters"], s["doc"], s["photo"]
        # lens plate: photo left half, vector plate at 50 % right half
        lp = ph.Duplicate(0, 0)
        lp.SetBoundingBox(0.0, (PH - PH / 2) / 2, PW / 2, PH / 2, False, BL)
        sr = a.CreateShapeRange()
        for v in s["vec"].values():
            sr.Add(v.Duplicate(0, 0))
        g = sr.Group()
        g.SetBoundingBox(PW / 2 + g.LeftX * 0.5, (PH - PH / 2) / 2 + g.BottomY * 0.5, g.SizeWidth * 0.5,
                         g.SizeHeight * 0.5, False, BL)
        s["lens_parts"] = [lp, g]
        for sh in [ph, lp, g] + list(s["vec"].values()):
            sh.MoveToLayer(m)
        s["page1"] = doc.Pages.Item(1)
        s["page1"].Activate()
        s["work"].Activate()
        return doc.Title, {k: (v.Type, round(v.LeftX, 3), round(v.BottomY, 3), round(v.SizeWidth, 3),
                               round(v.SizeHeight, 3)) for k, v in s["vec"].items()}

    # -- per render
    def clear(self):
        # re-read Count every pass: deleting an effect's control shape also deletes its linked shapes (Inner Shadow:
        # "Parameter Index is out of range. Its value must be between 1 and 3", 2026-10-06)
        w = self.s["work"]
        for _ in range(500):
            n = w.Shapes.Count
            if not n:
                return
            w.Shapes.Item(n).Delete()

    def dup(self, shape):
        d = shape.Duplicate(0, 0)
        d.MoveToLayer(self.s["work"])
        return d

    def plate(self, kind):
        """duplicate a plate onto the work layer -> dict of shapes"""
        if kind == "photo":
            return {"photo": self.dup(self.s["photo"])}
        if kind == "vector":
            return {k: self.dup(v) for k, v in self.s["vec"].items()}
        if kind == "lens":
            for p in self.s["lens_parts"]:
                self.dup(p)
            c = self.s["work"].CreateEllipse2(LENS_C[0], LENS_C[1], LENS_R)
            c.Fill.ApplyNoFill()
            c.Outline.Width = 1.0 / PX                 # 1 px hairline: shows where the lens sits
            c.Outline.Color.RGBAssign(0, 0, 0)
            return {"lens": c}
        raise ValueError(kind)

    def export(self, path):
        path = Path(path)
        path.unlink(missing_ok=True)
        self.s["page1"].Activate()
        # ExportArea = the page: without it cdrCurrentPage exports the objects' bounding box stretched to 960x540
        area = self.s["app"].CreateRect(0.0, 0.0, PW, PH)
        f = self.s["doc"].ExportBitmap(str(path), 802, 1, 4, 960, 540, 48, 48, 1, False, False, True, False, 0,
                                       None, area)
        f.Finish()
        if not path.exists():
            raise RuntimeError("ExportBitmap wrote no file")
        return path

    def export_crop(self, path, box=CROP_BOX):
        """the page region box at 100 % (96 px/in, w x h px)"""
        path = Path(path)
        path.unlink(missing_ok=True)
        area = self.s["app"].CreateRect(*crop_rect(box))
        f = self.s["doc"].ExportBitmap(str(path), 802, 1, 4, box[2], box[3], 96, 96, 1, False, False, True, False, 0,
                                       None, area)
        f.Finish()
        if not path.exists():
            raise RuntimeError("ExportBitmap wrote no crop file")
        return path

    def render(self, build, path, timeout=150, note="", crop=False):
        """build(app, plate shapes) -> anything; exports the page to path (and with crop=True the 1:1 CROP_BOX to
        crop_path(path) from the same render). Returns build's result."""
        def job(a):
            self.clear()
            r = build(a)
            self.export(path)
            if crop:
                self.export_crop(crop_path(path))
            self.clear()
            return r
        try:
            return self.call(job, timeout, note)
        except Exception as e:  # noqa: BLE001
            if "CallTimeout" not in type(e).__name__:
                try:
                    self.call(lambda a: self.clear(), 60, "clear")
                except Exception:  # noqa: BLE001
                    pass
            raise

    def tmp(self):
        # a fresh name per render: the old 6-slot ring (r{n % 6}) let the 6th probe render after the main frame
        # overwrite it, so cards with >= 5 probed keys saved a perturbed frame and reported its key as dropped
        # (Light 'Shadows', Conte Crayon 'Sepia', Halftone 'Max dot radius'; found 2026-10-06)
        self.n += 1
        return TMP / f"r{self.n:05d}.png"

    @staticmethod
    def sweep():
        for f in TMP.glob("r*.png"):
            f.unlink(missing_ok=True)

    def close(self):
        def job(a):
            self.s["doc"].Dirty = False
            self.s["doc"].Close()
            return True
        try:
            return self.call(job, 60, "close effect gallery doc")
        except Exception as e:  # noqa: BLE001
            return str(e)


def refs(sc):
    out = {}
    for kind in ("photo", "vector", "lens"):
        p = OUT / f"ref_{kind}.png"
        sc.render(lambda a, kind=kind: sc.plate(kind), p, note="ref " + kind)
        out[kind] = p
    return out


# ---------------------------------------------------------------- routes
def bitmap_card(sc, card, it, ref, probe=True):
    eid = it["extra"]["effect_id"]
    params = it.get("params") or []
    demo = card.get("demo_settings") or {}
    mapped, dropped = {}, []
    for k, v in demo.items():
        p = find_param(params, k)
        if p is None:
            dropped.append(k)
            continue
        mapped[k] = (p, v)
    keys_set = {p["key"] for p, _ in mapped.values()}
    base = {p["key"]: to_cmd_value(p, p["default"]) for p in params
            if p.get("type") in SCALAR and p.get("default") is not None and p["key"] not in keys_set
            and p["key"] != "Preset"}

    enum_keys = [k for k, (p, _) in mapped.items() if p.get("type") == "enum"]
    alias = KEY_ALIAS.get(eid, {})

    def kv(p, v, idx=False):
        """-> (command key, command value) for one card param"""
        if p["key"] in alias:
            ak, m = alias[p["key"]]
            ev = enum_value(p, v)
            return ak, fmt(m.get(str(ev if ev is not None else v), v))
        return p["key"], (enum_index(p, v) if idx else to_cmd_value(p, v))

    def cmd(use_base=True, enum_idx=False, skip=(), over=None):
        # NO strip(): a key-less command needs its trailing space ('DesaturateEffect ' applies, 'DesaturateEffect'
        # changes nothing; probe 2026-10-05)
        vals = dict(base) if use_base else {}
        for k, (p, v) in mapped.items():
            if k in skip:
                continue
            v = v if over is None or over[0] != k else over[1]
            ck, cv = kv(p, v, enum_idx and k in enum_keys)
            vals[ck] = cv
        return eid + " " + ",".join(f"{k}={v}" for k, v in vals.items())

    def build(c):
        return lambda a: sc.plate("photo")["photo"].Bitmap.ApplyBitmapEffect("PGD gallery", c)

    want_crop = wants_crop(it)   # main-frame candidates only; probe renders never need one

    # One invalid value (an enum caption the effect does not know, e.g. 'CylinderEffect ...,Mode=Horizontal') makes
    # the app ignore the WHOLE command: the call still returns OK and the plate comes back unchanged. So step down
    # until the pixels move, and say which step it took.
    ladder = [("card values + harvested defaults for the other keys", {}),
              ("card values only (harvested defaults for the other keys left out)", {"use_base": False})]
    if enum_keys:
        ladder += [("card values, enum keys sent as their list index", {"use_base": False, "enum_idx": True}),
                   ("card values without the enum keys (their values made the app ignore the command)",
                    {"use_base": False, "skip": tuple(enum_keys)})]
    tried = []
    t0 = time.time()
    try:
        for step, cfg in ladder:
            main_cmd = cmd(**cfg)
            if main_cmd in tried or f"{main_cmd} (server fault)" in tried:   # same string as the step before
                continue
            main = sc.tmp()
            try:
                sc.render(build(main_cmd), main, note=card["name"], crop=want_crop)
            except Exception as e:  # noqa: BLE001 - RPC_E_SERVERFAULT on one form: try the next (Levels / Equalize)
                if "-2147417851" not in str(e):
                    raise
                tried.append(f"{main_cmd} (server fault)")
                continue
            d_ref = diff(main, ref)
            if d_ref and flat(main) and not flat(ref):
                # the plate became one flat colour (Zig Zag 2026-10-04: near-black for every value): not the effect
                tried.append(f"{main_cmd} (flat frame)")
                continue
            if d_ref:
                break
            tried.append(main_cmd)
        else:
            raise RuntimeError("ApplyBitmapEffect changed no pixel of the plate (or raised RPC_E_SERVERFAULT) for "
                               "every form tried: " + " | ".join(repr(c) for c in tried))
    except RuntimeError as e:
        if eid not in OM_ROUTES:
            raise
        r = om_card(sc, card, eid, mapped, dropped, ref, probe, why=f"bitmap route: {e}")
        if r is None:
            raise
        return r
    secs = time.time() - t0
    if cfg.get("skip"):
        dropped += [k for k in cfg["skip"] if k not in dropped]

    def probe_keys(cfg, main, keys):
        """perturb each key in turn -> (keys whose new value gives the same pixels, notes)"""
        rep = sc.tmp()
        sc.render(build(cmd(**cfg)), rep, note=card["name"] + " repeat")
        floor = diff(main, rep)
        drop, notes = [], [f"repeat-render noise {floor}"]
        for k in keys:
            p, v = mapped[k]
            alt = perturb(p, v)
            if alt is None:
                notes.append(f"{k}: no alternative value to test")
                continue
            pp = sc.tmp()
            try:
                sc.render(build(cmd(**cfg, over=(k, alt))), pp, note=f"{card['name']} {k}={alt}")
            except Exception as e:  # noqa: BLE001 - the app faulted on this value: the key IS read (Equalize Model)
                if "-2147417851" not in str(e):
                    raise
                notes.append(f"{k}={fmt(alt)} -> RPC_E_SERVERFAULT (value rejected, key parsed)")
                continue
            d = diff(main, pp)
            if diff(pp, ref) == 0:          # the alternative value voided the command: the key IS parsed
                notes.append(f"{k}={fmt(alt)} -> plate unchanged (value rejected, key parsed)")
                continue
            notes.append(f"{k}={fmt(alt)} -> {d}")
            if d <= floor * 1.5 + 0.005:
                drop.append(k)
        return drop, notes

    probe_note = []
    if probe and mapped:
        drop, probe_note = probe_keys(cfg, main, [k for k in mapped if k not in cfg.get("skip", ())])
        # Keys the app ignored in this form: try the other forms and keep the one that honours the most card keys.
        #  - enum captions parsed but ignored (Emboss ColorMode, Page Curl CornerType ...): radio-group enums take their
        #    list index ('CylinderEffect Mode=1' = Vertical; probe 2026-10-05)
        #  - a harvested default sent for a key the card does not set can override a card key (Gamma: with
        #    'LevelCompact=0' the card's Level was ignored and the plate went near-black; 2026-10-06)
        alts = []
        if drop and any(k in enum_keys for k in drop) and not cfg.get("enum_idx") and not cfg.get("skip"):
            alts.append(("enum keys sent as their list index (the captions were ignored)", dict(cfg, enum_idx=True)))
        if drop and cfg.get("use_base", True) and base:
            alts.append(("harvested defaults for the other keys left out (with them card keys were ignored)",
                         dict(cfg, use_base=False)))
            if enum_keys and not cfg.get("enum_idx") and not cfg.get("skip"):
                alts.append(("harvested defaults left out and enum keys sent as their list index",
                             dict(cfg, use_base=False, enum_idx=True)))
        seen = {main_cmd}
        for label, c2 in alts:
            if not drop:
                break
            c2cmd = cmd(**c2)
            if c2cmd in seen:
                continue
            seen.add(c2cmd)
            m2 = sc.tmp()
            try:
                sc.render(build(c2cmd), m2, note=card["name"] + " other form", crop=want_crop)
            except Exception as e:  # noqa: BLE001
                if "-2147417851" not in str(e):
                    raise
                probe_note.append(f"other form '{c2cmd}': RPC_E_SERVERFAULT")
                continue
            d2 = diff(m2, ref)
            if not d2:
                probe_note.append(f"other form '{c2cmd}': plate unchanged")
                continue
            drop2, notes2 = probe_keys(c2, m2, [k for k in mapped if k not in c2.get("skip", ())])
            probe_note += [f"ignored {drop}; other form '{c2cmd}' ignores {drop2}:"] + notes2
            if len(drop2) < len(drop):
                cfg, main, d_ref, main_cmd, drop = c2, m2, d2, c2cmd, drop2
                step += "; " + label
        dropped += [k for k in drop if k not in dropped]
    if eid in OM_ROUTES and probe:
        # the object-model twin of this adjustment (Shape.ApplyEffectHSL / Gamma / ColorBalance ...): used when it
        # honours more card keys than ApplyBitmapEffect did
        covered = {h for h, _, _ in OM_ROUTES[eid][1] if h}
        if any(mapped[k][0]["key"] in covered for k in dropped if k in mapped):
            r = om_card(sc, card, eid, mapped, [k for k in dropped if k not in mapped], ref, probe,
                        why=f"bitmap route '{main_cmd}' ignored {dropped}")
            if r is not None and len(r[2]) < len(dropped):
                return r
            probe_note.append("object-model route " + ("not applicable" if r is None else
                                                        f"ignored {r[2]} (not better): {r[3][:200]}"))
    applied = {k: ("=".join(kv(p, v)) if p["key"] in alias else kv(p, v, cfg.get("enum_idx") and k in enum_keys)[1])
               for k, (p, v) in mapped.items() if k not in dropped}
    how = (f"Bitmap.ApplyBitmapEffect('PGD gallery', '{main_cmd}') on plate_photo.png imported as a 1920x1080 px "
           f"bitmap filling the 20x11.25 in page; page exported at 960x540 ({secs:.1f}s); form: {step}"
           + (f"; 1:1 crop {key(card['id'])}{CROP_SUFFIX}.png = page px {CROP_BOX[:2]} {CROP_BOX[2]}x{CROP_BOX[3]} "
              "at 100 % from the same render" if want_crop else ""))
    note = (f"diff vs ref_photo {d_ref}" + (f"; forms that changed no pixel first: {tried}" if tried else "")
            + ("; key probe: " + "; ".join(probe_note) if probe_note else ""))
    return main, applied, dropped, how, note


# effect_id -> {harvested key: (serialized key, {harvested enum value: serialized value})}.
# The harvest keys are the DIALOG's data-source paths (DrawUI.xml); the command parser reads the EFFECT's own
# serialized keys, which sit next to the effect name in the UTF-16 string pool of Programs64\CrlFX.dll
# (PageCurlEffect: Corner, Opaque, Back, Paint; ReplaceColorsV2Effect: InputColor, OutputColor, Range ...;
# HueSaturationLightnessEffect: Channel, IncludeBlack, Hue, Saturation, Lightness, PerceivedGrayscaleHue).
# Values below were read off probe frames (work/cdr/eg_probe_run10*.py, 2026-10-07):
#   Page Curl Corner 0 = top-right, 1 = top-left, 2 = bottom-right, 3 = bottom-left; Opaque 1 = solid curl,
#   0 = see-through curl; Direction 0 = cone runs down the side edge (Vertical), 1 = along the top edge (Horizontal).
# Unsolved (same probes): Replace Colors InputColor / OutputColor accept '#RRGGBB' without effect, and a
#   Color.ToString() value ('RGB255,USER,...') or a COLORREF integer hangs the call for good (kill + restart);
#   HueSaturationLightnessEffect ignores Hue / Saturation / Lightness in every form tried, and Shape.ApplyEffectHSL
#   changes no pixel of a bitmap (floats, ints, negatives).
KEY_ALIAS = {
    "PageCurlEffect": {"CornerType": ("Corner", {"CornerNE": 0, "CornerNW": 1, "CornerSE": 2, "CornerSW": 3}),
                       "DirectionType": ("Direction", {"Vertical": 0, "Horizontal": 1}),
                       "PaperType": ("Opaque", {"Opaque": 1, "Transparent": 0})},
    # the pool has 'Smear Length' (with a space); 'SmearLength' is ignored (same pixels with it left out, probe
    # work/cdr/owner_probe14 2026-10-13). Whirlpool's pattern changes with every key it reads, so the key probe's
    # 'dropped' cannot be trusted for it.
    "WhirlpoolEffect": {"SmearLength": ("Smear Length", {})},
}


# effect_id -> (Shape method, [(harvested key or None, default, cast)], {harvested key: values the call is fixed to})
# typelib VGCoreAuto 25.1 IVGShape: ApplyEffectHSL(Hue, Saturation, Lightness), ApplyEffectGamma(Gamma),
# ApplyEffectColorBalance(CyanRed, MagentaGreen, YellowBlue, ApplyToShadows, ApplyToMidtones, ApplyToHighlights,
# PreserveLuminance), ApplyEffectPosterize(Level), ApplyEffectInvert(), ApplyEffectBCI(Brighness, Contrast, Intensity)
def _num(v):
    f = float(v)
    return int(f) if f.is_integer() else f


OM_ROUTES = {
    "HueSaturationLightnessEffect": ("ApplyEffectHSL", [("Hue", 0, _num), ("Saturation", 0, _num),
                                                        ("Lightness", 0, _num)], {"Channel": ("Master",)}),
    "GammaEffect": ("ApplyEffectGamma", [("Level", 1.0, float)], {}),
    "ColorBalanceEffect": ("ApplyEffectColorBalance", [("CR_Master", 0, int), ("MG_Master", 0, int),
                                                       ("YB_Master", 0, int), (None, True, bool), (None, True, bool),
                                                       (None, True, bool), ("Luminance", True, truthy)], {}),
    "PosterizeEffect": ("ApplyEffectPosterize", [("Level", 4, int)], {}),
    "InvertEffect": ("ApplyEffectInvert", [], {}),
    "BCIEffect": ("ApplyEffectBCI", [("Brightness", 0, int), ("Contrast", 0, int), ("Intensity", 0, int)], {}),
}


def om_card(sc, card, eid, mapped, unmapped, ref, probe=True, why=""):
    """the Shape.ApplyEffect* twin of a bitmap adjustment -> (png, applied, dropped, how, note) or None"""
    meth, spec, fixed = OM_ROUTES[eid]
    bykey = {p["key"]: (k, p, v) for k, (p, v) in mapped.items()}
    for fk, ok in fixed.items():
        if fk in bykey:
            _, p, v = bykey[fk]
            ev = enum_value(p, v)
            if str(ev if ev is not None else v) not in ok:
                return None
    covered = [h for h, _, _ in spec if h and h in bykey]

    def args_for(over=None):
        out = []
        for h, d, cast in spec:
            v = bykey[h][2] if h in bykey else d
            if over and h == over[0]:
                v = over[1]
            out.append(cast(v))
        return out

    def build(args):
        return lambda a: getattr(sc.plate("photo")["photo"], meth)(*args)

    args = args_for()
    t0 = time.time()
    main = sc.tmp()
    sc.render(build(args), main, note=f"{card['name']} {meth}")
    d_ref = diff(main, ref)
    if not d_ref:
        raise RuntimeError(f"{why}; Shape.{meth}{tuple(args)} also changed no pixel of the plate")
    secs = time.time() - t0
    drop, notes = [], []
    if probe and covered:
        rep = sc.tmp()
        sc.render(build(args), rep, note=card["name"] + " repeat")
        floor = diff(main, rep)
        notes.append(f"repeat-render noise {floor}")
        for h in covered:
            k, p, v = bykey[h]
            alt = perturb(p, v)
            if alt is None and p.get("type") in ("number", "int") and isinstance(v, (int, float)):
                alt = v + 50
            if alt is None:
                notes.append(f"{k}: no alternative value to test")
                continue
            pp = sc.tmp()
            sc.render(build(args_for((h, alt))), pp, note=f"{card['name']} {meth} {k}={alt}")
            d = diff(main, pp)
            notes.append(f"{k}={fmt(alt)} -> {d}")
            if d <= floor * 1.5 + 0.005:
                drop.append(k)
    extra = [k for h, (k, p, v) in bykey.items() if h not in covered and h not in fixed]
    dropped = list(unmapped) + drop + [k for k in extra if k not in drop]
    applied = {k: v for h, (k, p, v) in bykey.items() if k not in dropped}
    how = (f"Shape.{meth}({', '.join(map(repr, args))}) on plate_photo.png imported as a 1920x1080 px bitmap filling "
           f"the 20x11.25 in page; page exported at 960x540 ({secs:.1f}s); object-model twin of {eid}, used because "
           f"{why}")
    note = (f"diff vs ref_photo {d_ref}" + (f"; keys with no argument in Shape.{meth}: {extra}" if extra else "")
            + (f"; fixed by the call: {list(fixed)}" if fixed else "")
            + ("; key probe: " + "; ".join(notes) if notes else ""))
    return main, applied, dropped, how, note


def rgb(a, hexv):
    h = str(hexv).lstrip("#")
    return a.CreateRGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


FILE_KEYS = ("FileName", "File")


def pgd_path(v):
    """a card's file value: a relative path (media/plate_photo.png) is resolved against the PGD root; an absolute
    one is passed on unchanged."""
    return v if not v or Path(v).is_absolute() else str(ROOT / v)


def com_args(a, params, demo, skip=()):
    """positional args in harvested order: demo value, else harvested default, colours / objects None;
    file-name strings go through pgd_path."""
    args, sent = [], {}
    for p in params:
        if p["key"] in skip:
            continue
        k = p["key"] if p["key"] in demo else (p["name"] if p["name"] in demo else None)
        t = p.get("type")
        if k is not None:
            v = demo[k]
            sent[k] = v
            if t == "color":
                v = rgb(a, v)
            elif t == "bool":
                v = truthy(v)
            elif t == "int" or (t == "enum" and isinstance(v, (int, float))):
                v = int(v)
            elif t == "number":
                v = float(v)
            elif t == "string" and p["key"] in FILE_KEYS and isinstance(v, str):
                v = pgd_path(v)
        else:
            v = None if t in ("color", "object") else p.get("default")
        args.append(v)
    while args and args[-1] is None:       # trailing optional VT_DISPATCH args can be left out
        args.pop()
    return args, sent


def readback(e, sent):
    """effect object properties named like the demo keys -> {key: value}, {key: why dropped}"""
    subs = []
    names = {0: "Blend", 1: "Extrude", 2: "Envelope", 5: "DropShadow", 6: "Contour", 7: "Distortion",
             8: "Perspective", 9: "Lens", 11: "InnerShadow"}
    try:
        sub = getattr(e, names.get(e.Type, ""), None)
        if sub is not None:
            subs.append(sub)
            if e.Type == 7:
                for n in ("PushPull", "Twister", "Zipper"):
                    try:
                        subs.append(getattr(sub, n))
                    except Exception:  # noqa: BLE001
                        pass
    except Exception:  # noqa: BLE001
        pass
    got, bad = {}, {}
    for k, v in sent.items():
        val = None
        for sub in subs:
            try:
                val = getattr(sub, k)
                break
            except Exception:  # noqa: BLE001
                continue
        if val is None or callable(val):
            got[k] = v
            continue
        if hasattr(val, "HexValue"):
            val = "#" + val.HexValue.lstrip("#").upper()[-6:]
            ok = val.upper() == str(v).upper()
        elif isinstance(val, (int, float)) and isinstance(v, (int, float)):
            ok = abs(val - v) <= 1e-3 * max(1, abs(v))
        else:
            ok = str(val) == str(v)
        got[k] = val
        if not ok:
            bad[k] = f"sent {v}, read back {val}"
    return got, bad


VEC_TARGET = "blue_star"


def vector_card(sc, card, it, ref_vec, ref_lens):
    cid, name = card["id"], card["name"]
    demo = dict(card.get("demo_settings") or {})
    params = it.get("params") or []
    api = (it.get("invoke") or {}).get("cdr_com", "")
    lens = cid.startswith("lens:") or api.startswith("Shape.CreateLens")
    info = {}

    def build(a):
        nonlocal demo
        if lens:
            sh = sc.plate("lens")
            lt = (it.get("extra") or {}).get("lens_type")
            ps = [p for p in params if p["key"] != "Type"]
            lead = [int(demo.pop("Type"))] if "Type" in demo else [int(lt)]
            args, sent = com_args(a, ps, demo)
            info["call"] = f"lens_circle.CreateLens({', '.join(map(repr, lead + args))})"
            e = sh["lens"].CreateLens(*(lead + args))
            info["target"] = "a circle r 300 px at (960, 540) over the lens plate (photo left, vector right)"
            if lead and "Type" in (card.get("demo_settings") or {}):
                sent = {"Type": lead[0], **sent}
            return e, sent
        sh = sc.plate("vector")
        t = sh[VEC_TARGET]
        info["target"] = "blue_star of the vector plate"
        meth = api.split("(")[0].split(".")[-1]
        if cid.startswith("vector:Transparency:"):
            pat = (it.get("extra") or {}).get("pattern_type")
            args, sent = com_args(a, params, demo)
            if pat is not None:
                if not args:
                    args = [""]
                elif args[0] is None:
                    args[0] = ""
                args = [pat] + args
            info["call"] = f"star.Transparency.{meth}({', '.join(map(repr, args))})"
            getattr(t.Transparency, meth)(*args)
            return None, sent
        if meth in ("CreatePushPullDistortion", "CreateTwisterDistortion", "CreateZipperDistortion"):
            demo.setdefault("OriginX", t.CenterX)
            demo.setdefault("OriginY", t.CenterY)
        if meth == "CreatePerspective":
            if not demo:
                demo = {"HorizVanishPointX": t.CenterX + 12.0, "HorizVanishPointY": t.CenterY}
                info["computed"] = "no demo_settings: one-point perspective, vanishing point 12 in right of the " \
                                   "star centre at its height (the card's own advice)"
            args = [demo[k] for k in ("HorizVanishPointX", "HorizVanishPointY", "VertVanishPointX",
                                      "VertVanishPointY") if k in demo]
            sent = dict(demo)
        else:
            args, sent = com_args(a, params, demo)
        if meth == "CreateBlend":
            args[0] = sh["blue_star"]
            t = sh["orange_box"]
            info["target"] = "orange_box blended into blue_star"
        info["call"] = f"{'orange_box' if meth == 'CreateBlend' else 'star'}.{meth}({', '.join(map(repr, args))})"
        e = getattr(t, meth)(*args)
        return e, sent

    def job(a):
        e, sent = build(a)
        got, bad = readback(e, sent) if e is not None else (dict(sent), {})
        etype = e.Type if e is not None else None
        return got, bad, etype

    out = sc.tmp()
    got, bad, etype = sc.render(job, out, note=name)
    ref = ref_lens if lens else ref_vec
    d_ref = diff(out, ref)
    if d_ref < 0.05:
        # 0.05 mean |dRGB| on 960x540 is a few hundred pixels: no visible effect (Envelope PresetIndex=1 gave 0.0051,
        # the star unchanged to the eye; 2026-10-06)
        raise RuntimeError(f"{info.get('call')} returned (effect type {etype}) but the page differs from the "
                           f"reference plate by only {d_ref} mean px: the card's values give no visible effect")
    how = (f"{info.get('call')} on {info['target']}" + (f" ({info['computed']})" if "computed" in info else "")
           + "; doc unit inch, page 20x11.25 in, bottom-left origin; page exported at 960x540")
    note = f"diff vs ref_{'lens' if lens else 'vector'} {d_ref}" + (f"; effect type {etype}" if etype is not None
                                                                     else "")
    if bad:
        note += "; read-back mismatch: " + "; ".join(f"{k}: {v}" for k, v in bad.items())
    applied = {k: (str(v) if not isinstance(v, (int, float, bool, str)) else v) for k, v in got.items()
               if k not in bad}
    return out, applied, sorted(bad), how, note


# card id -> (EffectID, [(argument, value)]) for Shape.CreateCustomEffect(EffectID, *values). Probe 2026-10-13
# (work/cdr/rr2/probe_fx.json): 'Bevel' is the id the call knows (the docker / component / coclass guids give
# 'Requested component is not installed'); the values go as separate arguments in BevelToolOM IEffectBevel order (one
# array argument -> DISP_E_BADPARAMCOUNT, a number where a colour belongs -> DISP_E_TYPEMISMATCH); with only the first
# three the lights default to nothing and the star turns black. Reading the light values back gives garbage
# (LightIntensity 8.7e-309 whatever was sent), so only EffectID / Type / Mode / Offset are checked.
# Bevel demo: Type 0 = cdrBevelSoftEdge, Mode 1 = cdrBevelOffset (a distance, not to the centre), 0.3 in.
CUSTOM = {"91062f47-0342-43a3-827b-ed78815cfce5": (
    "Bevel", [("Type", 0), ("Mode", 1), ("Offset", 0.3), ("LightColor", "#FFFFFF"), ("LightIntensity", 100),
              ("LightDirection", 135.0), ("LightAltitude", 45.0), ("ShadowColor", "#000000"),
              ("AmbientIntensity", 50)])}
CUSTOM_READ = ("Type", "Mode", "Offset")

# effect_id -> why no render is attempted (every form probed changed nothing or faulted)
UNROUTED = dict.fromkeys(
    ("TuneBlurEffect", "TuneSharpnessEffect", "TuneNoiseEffect"),
    "no scripted form found: CrlFX.dll serializes a Tune effect as ListSize plus per-step keys (Effect_%d with Step_%d; "
    "Percentage_%d, Background_%d, MaskType_%d; Level_%d, Density_%d); 2026-10-13 probe (work/cdr/rr2/probe_fx.json): "
    "Effect_n = 0..5, the sub-effect's command name (SharpenEffect, MedianEffect ...), the dialog thumbnail's item guid "
    "(a new guid every session), ListSize 1-2, the plain Step / Percentage / Level keys, and the data-source route "
    "(Step set, thumbnail OnItemActivate_<node> invoked, then a key-less command): TuneBlurEffect raises "
    "RPC_E_SERVERFAULT on every form, TuneSharpnessEffect and TuneNoiseEffect accept every form and change no pixel; "
    "the dialog (menu GUID) is the only route")


def custom_card(sc, card, ref_vec):
    eid, spec = CUSTOM[card["id"]]

    def job(a):
        import win32com.client
        t = sc.plate("vector")[VEC_TARGET]
        args = [rgb(a, v) if isinstance(v, str) and v.startswith("#") else v for _, v in spec]
        e = t.CreateCustomEffect(eid, *args)
        cu = win32com.client.dynamic.Dispatch(e.Custom._oleobj_)
        return {"EffectID": cu.EffectID, **{k: getattr(cu, k) for k in CUSTOM_READ}}, e.Type

    out = sc.tmp()
    got, etype = sc.render(job, out, note=card["name"])
    d_ref = diff(out, ref_vec)
    if d_ref < 0.05:
        raise RuntimeError(f"star.CreateCustomEffect({eid!r}, ...) returned but the page differs from the reference "
                           f"plate by only {d_ref} mean px")
    sent = dict(spec)
    bad = sorted(k for k in CUSTOM_READ if abs(float(got[k]) - float(sent[k])) > 1e-6)
    call = f"star.CreateCustomEffect({eid!r}, " + ", ".join(
        f"{k}={'CreateRGBColor(' + v + ')' if isinstance(v, str) else v}" for k, v in spec) + ")"
    how = (f"{call} on blue_star of the vector plate (BevelToolOM IEffectBevel argument order); doc unit inch, page "
           "20x11.25 in, bottom-left origin; page exported at 960x540")
    note = (f"diff vs ref_vector {d_ref}; effect type {etype} (custom), EffectID {got['EffectID']!r}; read back "
            + ", ".join(f"{k}={got[k]}" for k in CUSTOM_READ) + "; light values not read back (the property read "
            "returns garbage)")
    return out, {k: v for k, v in spec if k not in bad}, bad, how, note


# ---------------------------------------------------------------- main
def route(card, it):
    if card.get("status") != "current":
        return "skip", f"status '{card.get('status')}' (only current cards are rendered)"
    if card.get("scriptable") == "no":
        return "skip", "scriptable 'no': " + (card.get("scripting") or "")[:300]
    if card["id"] in CUSTOM:
        return "custom", None
    eid = (it.get("extra") or {}).get("effect_id")
    if eid in UNROUTED:
        return "fail", UNROUTED[eid]
    if eid:
        return "bitmap", None
    inv = it.get("invoke") or {}
    if "cdr_com" in inv and (card["id"].startswith(("vector:", "lens:")) or inv["cdr_com"].startswith("Shape.Create")):
        return "vector", None
    return "fail", ("no scripted apply path: the harvest has no cdr_com / effect_id for this item, only "
                    f"{sorted(inv)} (the Effects menu entry toggles a docker); " + (it.get("error") or ""))[:500]


def read_ids(path):
    t = Path(path).read_text(encoding="utf-8").strip()
    try:
        j = json.loads(t)
        return list(j) if isinstance(j, (list, dict)) else [str(j)]
    except ValueError:
        return [ln.strip() for ln in t.splitlines() if ln.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids")
    ap.add_argument("--rerender", action="store_true")
    ap.add_argument("--refs", action="store_true")
    ap.add_argument("--no-probe", action="store_true")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    cards, items = load_cards()
    st = State()
    # The PS / AI / CDR renderers are ALL called effect_gallery.py: a command-line match kills other agents' runs
    # (preset_gallery.py 2026-10-04, effect_gallery.py 2026-10-06). Stop this run with stop_effect_gallery.py, which
    # kills only the pid recorded here, after checking that the pid still runs THIS file.
    # ...and the pid file is also a single-run lock: two copies of this renderer (2026-10-06) shared the json and the
    # scratch folder and each one's saves erased the other's results
    if PIDFILE.exists():
        try:
            import psutil
            other = json.loads(PIDFILE.read_text(encoding="utf-8")).get("pid")
            if other and other != os.getpid() and psutil.pid_exists(int(other)) and \
                    "effect_gallery.py" in " ".join(psutil.Process(int(other)).cmdline()) and \
                    Path(psutil.Process(int(other)).cwd()).resolve() == HERE:
                sys.exit(f"another CDR effect-gallery run is live (pid {other}, {PIDFILE}); not starting a second one")
        except (OSError, ValueError, psutil.Error):
            pass
    (TMP / "run.pid").unlink(missing_ok=True)             # the old plain-text pid file of a 2026-10-06 build
    PIDFILE.write_text(json.dumps({"pid": os.getpid(), "script": str(Path(__file__).resolve()),
                                   "started": time.strftime("%Y-%m-%d %H:%M:%S")}), encoding="utf-8")
    want = set(read_ids(args.ids)) if args.ids else None
    todo = []
    for c in cards:
        if want is not None and c["id"] not in want:
            continue
        it = items.get(c["id"], {})
        kind, why = route(c, it)
        if kind == "skip":
            st.not_rendered(c, why)
            continue
        if kind == "fail":
            st.fail(c, why)
            continue
        png = OUT / f"{key(c['id'])}.png"
        if want is None and not args.rerender and c["id"] in st.index and png.exists():
            continue
        todo.append((c, it, kind))
    st.save()
    if args.limit:
        todo = todo[:args.limit]
    print(f"cards {len(cards)} todo {len(todo)} index {len(st.index)} failed {len(st.failed)} "
          f"not_rendered {len(st.nr)}", flush=True)
    if not todo and not args.refs:
        PIDFILE.unlink(missing_ok=True)
        return
    sc = Scene()
    print("scene", sc.call(lambda a: sc.s["doc"].Title, 30), flush=True)
    t0 = time.time()
    try:
        ref = refs(sc)
        if args.refs:
            return
        for n, (c, it, kind) in enumerate(todo, 1):
            if n % 5 == 1 and n > 1:
                r = room_gb()
                if r is not None and r < MIN_ROOM_GB:
                    st.save()
                    print(f"  commit headroom {r} GB < {MIN_ROOM_GB}: closing our doc, restarting CorelDRAW",
                          flush=True)
                    sc.close()
                    sc.cd.kill()
                    time.sleep(8)
                    wait_room()
                    sc = Scene()
                    ref = refs(sc)
            try:
                if kind == "bitmap":
                    r = bitmap_card(sc, c, it, ref["photo"], probe=not args.no_probe)
                elif kind == "custom":
                    r = custom_card(sc, c, ref["vector"])
                else:
                    r = vector_card(sc, c, it, ref["vector"], ref["lens"])
                st.put(c, *r)
                print(f"[{n}/{len(todo)}] OK {c['name']}: dropped {r[2]} | {r[4][:160]}", flush=True)
            except Exception as e:  # noqa: BLE001
                st.fail(c, f"{type(e).__name__}: {e}")
                print(f"[{n}/{len(todo)}] FAIL {c['name']}: {type(e).__name__}: {str(e)[:200]}", flush=True)
                msg = f"{type(e).__name__} {e}"
                # only a hang or a dead server: our own "no pixel changed (or RPC_E_SERVERFAULT)" message is neither
                if "CallTimeout" in msg or "RPC server" in msg or "-2147023174" in msg or "-2147417848" in msg:
                    st.save()
                    print("app wedged or gone: killing our CorelDRAW and rebuilding the scene", flush=True)
                    sc.cd.kill()
                    time.sleep(8)
                    sc = Scene()
                    ref = refs(sc)
            Scene.sweep()
            if n % 5 == 0:
                st.save()
                print(f"  checkpoint {n}/{len(todo)} {time.time() - t0:.0f}s ok={len(st.index)} "
                      f"failed={len(st.failed)}", flush=True)
    finally:
        st.save()
        print("closed", sc.close(), flush=True)
        # quit the CorelDRAW this run started: the next run starts its own (own=True) and refuses to attach to a
        # leftover one (run9 2026-10-06 died with NotOurCorel on run8's instance)
        try:
            sc.cd.kill()
            print("killed our CorelDRAW", sorted(sc.cd.pids), flush=True)
        except Exception as e:  # noqa: BLE001
            print("could not kill our CorelDRAW:", e, flush=True)
        try:
            if json.loads(PIDFILE.read_text(encoding="utf-8")).get("pid") == os.getpid():
                PIDFILE.unlink()
        except (OSError, ValueError):
            pass
        allids = {c["id"] for c in cards}
        placed = [set(st.index), set(st.failed), set(st.nr)]
        overlap = (placed[0] & placed[1]) | (placed[0] & placed[2]) | (placed[1] & placed[2])
        print(f"index {len(st.index)} failed {len(st.failed)} not_rendered {len(st.nr)} "
              f"missing {len(allids - set().union(*placed))} overlap {len(overlap)}", flush=True)


if __name__ == "__main__":
    main()
