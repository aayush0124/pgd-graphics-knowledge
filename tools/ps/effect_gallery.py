"""PGD effect gallery, Photoshop 2026: one 960x540 frame per visual card (ps_filter, ps_adjustment, ps_layer_style,
ps_blend_mode) with the card's demo_settings applied exactly, on a fixed 1920x1080 plate.

    python effect_gallery.py                       every kind (resumable: a key whose PNG + index entry exist is skipped)
    python effect_gallery.py --kind ps_filter      one kind
    python effect_gallery.py --ids ids.json        re-render just these card ids (JSON list / dict keys, or one per line)
    python effect_gallery.py --control             the dialog control (CONTROL below) -> work/ps/effgal/control/

Plates (PLATES; the index row's "plate" names the one used):
  photo  media/plate_photo.png (ps_filter, ps_adjustment).
  text   mid grey #808080 + "PGD" Arial Black 360 px #E1E1E1 centred: the ps_preset layer-style plate at 1920x1080
         (ps_layer_style; the effect is set on the text layer).
  blend  the photo plate + a known top layer at 100 % (ps_blend_mode; the mode is set on the top layer): rows 0-359 eight
         colour bars (white yellow cyan green magenta red blue black), rows 360-719 a grey ramp 0 -> 255 left to right,
         rows 720-1079 magenta #FF00C8 -> cyan #00E5FF with alpha 255 -> 0 left to right (shows Dissolve / opacity maths).
Every job: a fresh document from the plate file, colours reset to black / white, Move tool; apply; flatten; Photoshop
saves the full 1920x1080 frame; Python derives the 960x540 frame (Lanczos) and, for pixel-scale filters (wants_crop),
the 1:1 crop <key>_1to1.png of CROP_BOX (index row "crop"). ref.png per kind = the same set-up with no effect.
Demo values are typed from the harvest probe read-back of the same event (unit, enum type, object class), else from
the harvest param; object / list values (channel matrices, level lists, curve points, colour corrections) member by
member from a read-back of the same key or class, else from the class's declared members (harvest extra.members, from
Photoshop's terminology; see typed()). index.json "applied" = what Photoshop read back; "changed" = sent vs read back where they differ;
"dropped" = demo keys absent from a non-empty read-back (or that could not be typed).
Photoshop is started and restarted only through psdrv (its pid in work/ps/ps.pid); a Photoshop this pipeline did not
start is never sent a script. Restart at PGD_PS_MAX_GB (default 6) private memory, every RESTART_EVERY items, and when
commit headroom is low.
"""
import ctypes, hashlib, json, os, sys, threading, time, urllib.parse
from pathlib import Path

PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides
ROOT = PGD
HERE = Path(__file__).parent
WORK = ROOT / "work/ps"
SCR = WORK / "effgal"
GAL = ROOT / "gallery"
PLATE = (ROOT / "media/plate_photo.png").as_posix()
TOP = SCR / "blend_top.png"
KINDS = ["ps_filter", "ps_adjustment", "ps_layer_style", "ps_blend_mode"]
SETUP = {"ps_filter": "photo", "ps_adjustment": "photo", "ps_layer_style": "text", "ps_blend_mode": "blend"}
PLATES = {
    "photo": "media/plate_photo.png (1920x1080 RGB 8 bit, Background layer)",
    "text": "mid grey #808080 1920x1080 + 'PGD' text layer, Arial Black 360 px, #E1E1E1, centred "
            "(the ps_preset layer-style plate at 1920x1080)",
    "blend": "media/plate_photo.png + top pixel layer at Normal 100 %: rows 0-359 colour bars W Y C G M R B K, rows 360-719 "
             "grey ramp 0->255 left to right, rows 720-1079 magenta #FF00C8 -> cyan #00E5FF with alpha 255->0 left to right",
}
FRAME = (960, 540)
CROP_BOX = (1408, 568, 512, 512)  # x, y, w, h in plate px (top-left origin): bars, ramp, hairlines; same box as cdr_effect
DETAIL_PATHS = ("Filter/Blur/", "Filter/Sharpen/", "Filter/Noise/")
DETAIL_IDS = {"diffuse", "emboss", "findEdges", "glowingEdges", "traceContour", "highPass", "maximum", "minimum",
              "deInterlace", "filmGrain", "grain", "mezzotint", "adjustmentLayer:grainAdjustment"}
BATCH, RESTART_EVERY, MIN_HEADROOM_GB, WAIT_MAX_S = 8, 100, 4.0, 2700
MAX_PS_GB = float(os.environ.get("PGD_PS_MAX_GB") or 6.0)
SLOW = {"'Bokh'": 900}  # Lens Blur: moderate values only (huge ones hang Photoshop 20+ min)
UNITS = {"px": "pixelsUnit", "%": "percentUnit", "deg": "angleUnit"}
# the dialog control: one Filter Gallery filter, one plain filter with a dialog, one adjustment
CONTROL = [("ps_filter", "cutout"), ("ps_filter", "unsharpMask"), ("ps_adjustment", "brightnessEvent")]


def key(iid):
    return hashlib.sha1(iid.encode("utf-8")).hexdigest()[:12]


def log(msg):
    print(msg, flush=True)
    SCR.mkdir(parents=True, exist_ok=True)
    with open(SCR / "run.log", "a", encoding="utf-8") as f:
        f.write(time.strftime("%m-%d %X ") + msg + "\n")


def jload(p, d=None):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d


def wants_crop(item):
    """pixel-scale filters (blur, sharpen, noise, edge, high pass, minimum / maximum ...): also a 1:1 crop."""
    return (item.get("path") or "").startswith(DETAIL_PATHS) or item.get("id") in DETAIL_IDS


# ------------------------------------------------------------------ cards -> typed specs
def cards(kind):
    out = []
    for f in sorted((ROOT / "cards").glob(f"{kind}_*.json")):
        out += jload(f)["cards"]
    return out


def harvest(kind):
    return {i["id"]: i for i in jload(ROOT / f"harvest/ps/{kind}.json")["items"]}


_PROBES = {}


def probe(name):
    if name not in _PROBES:
        _PROBES[name] = jload(WORK / f"probe_{name}.json", {})
    return _PROBES[name]


def rb_types(kind, item, demo):
    """{AM key: dval entry} from the harvest's live read-back of this event / class, for typing the demo values."""
    ev = (item.get("invoke") or {}).get("ps_event")
    if kind == "ps_filter":
        rb = dict((probe("filter").get(ev) or {}).get("readback") or {})
        if ev == "'GEfc'" and demo.get("Effect"):  # Filter Gallery: the chosen effect's own read-back types its keys
            rb.update((probe("filter").get(demo["Effect"]) or {}).get("readback") or {})
        return rb
    if kind == "ps_adjustment":
        cls = (item.get("extra") or {}).get("adjustment_class")
        if cls:
            la = (probe("adjlayer").get(cls) or {}).get("layer_adjustment") or []
            return la[0]["v"] if la else {}
        return (probe("adjust").get(ev) or {}).get("readback") or {}
    if kind == "ps_layer_style":
        return (probe("style").get(item["id"]) or {}).get("readback") or {}
    return {}


def hex_rgb(v):
    if isinstance(v, str):
        h = v.lstrip("#")
        return [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    if isinstance(v, dict):
        return [v.get("red", 0), v.get("grain", v.get("green", 0)), v.get("blue", 0)]
    return list(v)[:3]


def enum_val(p, v):
    for e in p.get("enum") or []:
        if v == e.get("value"):
            return e["value"]
    for e in p.get("enum") or []:
        if str(v).lower() == str(e.get("label", "")).lower():
            return e["value"]
    return v


def enum_type(p):
    x = p.get("extra") or {}
    if x.get("enum_type"):
        return x["enum_type"]
    if x.get("declared_type"):
        return x["declared_type"].lstrip("/").split()[0]
    if x.get("declared_type_4cc"):
        return "'%s'" % x["declared_type_4cc"]
    return None


_CLASS_TMPL = {}


def class_template(cls):
    """{member: dval} of an object class from any harvested read-back of it (channelMatrix from the adjustment-layer
    probe), to type the same class where the harvest only has its declaration (the destructive Channel Mixer)."""
    if not _CLASS_TMPL:
        for kind in KINDS:
            for it in harvest(kind).values():
                for p in it.get("params") or []:
                    x = p.get("extra") or {}
                    if x.get("class") and isinstance(x.get("value"), dict):
                        _CLASS_TMPL.setdefault(x["class"], x["value"])
        _CLASS_TMPL.setdefault(None, {})
    return _CLASS_TMPL.get(cls) or {}


POINT_CLASSES = {"point", "paint", "curvePoint"}


def typed(v, decl="", r=None, members=None):
    """one JSON value (list / object values included) -> spec value [kind, ...] (no key) for the JS builder. Typed from
    the app's read-back of the same key (r, a harvest dval) when there is one, else from the declared terminology type
    (decl, e.g. "/integer /list", "/curvesAdjustment") and, inside an object, its class's declared members."""
    t, parts = (r or {}).get("t"), decl.replace("/", " ").split()
    base = parts[0] if parts else ""
    if t == "LISTTYPE" or "list" in parts[1:] or (isinstance(v, list) and v and isinstance(v[0], dict)):
        if not isinstance(v, list):  # an explicit list, or a JSON list of objects for a class-typed key (curves adjustment)
            raise ValueError(f"expects a list, got {v!r}")
        rl = (r or {}).get("v") if t == "LISTTYPE" else None
        return ["list", [typed(x, base, rl[min(i, len(rl) - 1)] if rl else None, members) for i, x in enumerate(v)]]
    if isinstance(v, dict):
        cls = (r or {}).get("cls") or base
        rv = (r or {}).get("v") if isinstance((r or {}).get("v"), dict) else class_template(cls)
        return ["obj", cls, [[mk] + typed(mv, (members or {}).get(mk, ""), rv.get(mk)) for mk, mv in v.items()]]
    if t == "UNITDOUBLE":
        return ["unit", r["unit"], float(v)]
    if t == "DOUBLETYPE":
        return ["dbl", float(v)]
    if t in ("INTEGERTYPE", "LARGEINTEGERTYPE"):
        return ["int", int(round(float(v)))]
    if t == "BOOLEANTYPE" or isinstance(v, bool):
        return ["bool", bool(v)]
    if t == "ENUMERATEDTYPE":
        return ["enum", r["etype"], v]
    if isinstance(v, list) and base in POINT_CLASSES and len(v) == 2:
        return ["point", "paint", float(v[0]), float(v[1])]
    if base == "channelReference" and isinstance(v, str):
        return ["chref", v]  # reference channel.<v> (composite, red, ...)
    if isinstance(v, (int, float)):
        if base == "integer":
            return ["int", int(round(float(v)))]
        return ["unit", base, float(v)] if base.endswith("Unit") else ["dbl", float(v)]
    if isinstance(v, str) and base and base not in ("text", "string", "char"):
        return ["enum", base, v]  # a declared enum type (colors.reds)
    if isinstance(v, str):
        return ["str", v]
    raise ValueError(f"no descriptor mapping for {v!r} (declared {decl or 'nothing'})")


def type_one(p, v, r):
    """one demo value -> spec entry [amkey, kind, ...] for the JS builder, or raise ValueError."""
    k, t = p.get("key") or p["name"], (r or {}).get("t")
    if p["type"] == "object":
        x = p.get("extra") or {}
        if t not in ("OBJECTTYPE", "LISTTYPE") and x.get("value"):  # the harvest's read-back of this key
            r = {"t": "OBJECTTYPE" if isinstance(x["value"], dict) else "LISTTYPE", "cls": x.get("class"), "v": x["value"]}
        elif t not in ("OBJECTTYPE", "LISTTYPE"):
            r = None
        return [k] + typed(v, x.get("declared_type") or ("/" + x["class"] if x.get("class") else ""), r, x.get("members"))
    if t == "UNITDOUBLE":
        return [k, "unit", r["unit"], float(v)]
    if t == "DOUBLETYPE":
        return [k, "dbl", float(v)]
    if t in ("INTEGERTYPE", "LARGEINTEGERTYPE"):
        return [k, "int", int(round(float(v)))]
    if t == "BOOLEANTYPE":
        return [k, "bool", bool(v)]
    if t == "ENUMERATEDTYPE":
        return [k, "enum", r["etype"], enum_val(p, v)]
    if t == "STRINGTYPE":
        return [k, "str", str(v)]
    if t == "OBJECTTYPE" and (p["type"] == "color" or isinstance(v, str)):
        return [k, "rgb"] + [float(c) for c in hex_rgb(v)]
    if t == "OBJECTTYPE" and p["type"] == "point":
        h, vv = (v["horizontal"], v["vertical"]) if isinstance(v, dict) else v
        return [k, "point", r.get("cls") or "paint", float(h), float(vv)]
    pt, x = p["type"], p.get("extra") or {}
    if pt == "int":
        return [k, "int", int(round(float(v)))]
    if pt == "number":
        u = UNITS.get(p.get("unit")) or (x.get("declared_type", "").lstrip("/") if x.get("declared_type", "").endswith("Unit") else None)
        return [k, "unit", u, float(v)] if u else [k, "dbl", float(v)]
    if pt == "bool":
        return [k, "bool", bool(v)]
    if pt == "enum":
        et = enum_type(p)
        if not et:
            raise ValueError(f"no enum type known for {k}")
        return [k, "enum", et, enum_val(p, v)]
    if pt == "color":
        return [k, "rgb"] + [float(c) for c in hex_rgb(v)]
    if pt == "point":
        h, vv = (v["horizontal"], v["vertical"]) if isinstance(v, dict) else v
        return [k, "point", x.get("class") or "paint", float(h), float(vv)]
    if pt == "string":
        return [k, "str", str(v)]
    raise ValueError(f"param type {pt} of {k} has no descriptor mapping")


def spec_for(kind, card, item):
    """-> (spec list, {demo key: spec entry}, [(demo key, why) untyped])"""
    demo = card.get("demo_settings") or {}
    params = {}
    for p in item.get("params") or []:
        params.setdefault(p["name"], p)
        if p.get("key"):
            params.setdefault(p["key"], p)
    rb = rb_types(kind, item, demo)
    spec, by, bad = [], {}, []
    for dk, v in demo.items():
        p = params.get(dk)
        if not p:
            bad.append((dk, "no harvested param of this name or key"))
            continue
        try:
            e = type_one(p, v, rb.get(p.get("key") or p["name"]))
        except (ValueError, TypeError, KeyError) as ex:
            bad.append((dk, str(ex)))
            continue
        spec.append(e)
        by[dk] = e
    return spec, by, bad


def fmt(e):
    k, t = e[0], e[1]
    if t == "unit":
        return f"{k}: {e[3]:g} {e[2]}"
    if t == "enum":
        return f"{k}: {e[2]}.{e[3]}"
    if t == "rgb":
        return f"{k}: RGBColor({e[2]:g},{e[3]:g},{e[4]:g})"
    if t == "point":
        return f"{k}: {e[2]}({e[3]:g},{e[4]:g})"
    return f"{k}: {json.dumps(sent_plain(e))}"


def plain(r):
    """harvest-style dval {t, v, ...} -> plain JSON value."""
    if not isinstance(r, dict) or "t" not in r:
        return r
    t, v = r["t"], r.get("v")
    if t == "OBJECTTYPE" and isinstance(v, dict):
        if r.get("cls") == "RGBColor" and {"red", "blue"} <= set(v):
            c = [plain(v["red"]), plain(v.get("grain", v.get("green"))), plain(v["blue"])]
            return "#%02X%02X%02X" % tuple(int(round(x)) for x in c)
        if {"horizontal", "vertical"} <= set(v):
            return [plain(v["horizontal"]), plain(v["vertical"])]
        return {k: plain(x) for k, x in v.items()}
    if t == "LISTTYPE" and isinstance(v, list):
        return [plain(x) for x in v]
    return v


def sent_plain(e):
    """spec entry [key, kind, ...] -> the plain JSON value it sends"""
    return _plain_v(e[1:])


def _plain_v(s):
    t = s[0]
    if t in ("unit", "enum"):
        return s[2]
    if t == "rgb":
        return "#%02X%02X%02X" % tuple(int(round(x)) for x in s[1:4])
    if t == "point":
        return [s[2], s[3]]
    if t == "list":
        return [_plain_v(x) for x in s[1]]
    if t == "obj":
        return {m[0]: _plain_v(m[1:]) for m in s[2]}
    return s[1]


def same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= 1e-3 * max(1.0, abs(a))
    return a == b


def reconcile(by, bad, rb):
    """-> applied {demo key: value read back}, dropped [demo keys], changed {demo key: [sent, got]}, readback flag"""
    applied, dropped, changed = {}, [k for k, _ in bad], {}
    if not rb:  # the event returned an empty descriptor: nothing to read back, report what was sent
        return {k: sent_plain(e) for k, e in by.items()}, dropped, changed, False
    for dk, e in by.items():
        r = rb.get(e[0])
        if r is None:
            dropped.append(dk)
            continue
        got = plain(r)
        applied[dk] = got
        s = sent_plain(e)
        if e[1] in ("int", "dbl", "unit", "bool", "enum", "str") and not same(s, got):
            changed[dk] = [s, got]
    return applied, dropped, changed, True


# ------------------------------------------------------------------ plates and frames (Python side)
BARS = [(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0), (255, 0, 255), (255, 0, 0), (0, 0, 255), (0, 0, 0)]


def blend_top(path=TOP):
    """the blend plate's top layer (see PLATES['blend']) as an RGBA PNG; deterministic, rebuilt when missing."""
    from PIL import Image
    path = Path(path)
    if path.exists():
        return path
    w, h, band = 1920, 1080, 360
    im = Image.new("RGBA", (w, h))
    px = im.load()
    for x in range(w):
        bar = BARS[x * len(BARS) // w]
        g = round(255 * x / (w - 1))
        mc = tuple(round(a + (b - a) * x / (w - 1)) for a, b in zip((255, 0, 200), (0, 229, 255)))
        for y in range(band):
            px[x, y] = bar + (255,)
            px[x, y + band] = (g, g, g, 255)
            px[x, y + 2 * band] = mc + (255 - g,)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


def derive(full, out, crop=None):
    """Photoshop's full-size frame -> the 960x540 gallery frame (and the 1:1 CROP_BOX crop when crop is a path)."""
    from PIL import Image
    im = Image.open(full).convert("RGB")
    if crop:
        x, y, w, h = CROP_BOX
        im.crop((x, y, x + w, y + h)).save(crop)
    im.resize(FRAME, Image.LANCZOS).save(out)


def diff_stats(a_png, b_png):
    """{mean, max, over2 (share of pixels with a channel off by more than 2)} or None when sizes differ / a file is missing."""
    import numpy as np
    from PIL import Image
    if not (Path(a_png).exists() and Path(b_png).exists()):
        return None
    a = np.asarray(Image.open(a_png).convert("RGB"), dtype=np.int16)
    b = np.asarray(Image.open(b_png).convert("RGB"), dtype=np.int16)
    if a.shape != b.shape:
        return None
    d = np.abs(a - b)
    return {"mean": round(float(d.mean()), 3), "max": int(d.max()), "over2": round(float((d.max(axis=2) > 2).mean()), 5)}


def respec(spec, by, changed):
    """the spec with each changed demo key's value replaced by what the event's result descriptor reported."""
    sub = {by[dk][0]: got for dk, (_, got) in changed.items()}
    out = []
    for e in spec:
        e = list(e)
        if e[0] in sub:
            e[3 if e[1] in ("unit", "enum") else 2] = sub[e[0]]
        out.append(e)
    return out


def diff(png, ref):
    s = diff_stats(png, ref)
    return s and s["mean"]


# ------------------------------------------------------------------ Photoshop side
PSJ = r'''
var PLATE = %(plate)s, TOP = %(top)s;
function rgbc(r, g, b) { var c = new SolidColor(); c.rgb.red = r; c.rgb.green = g; c.rgb.blue = b; return c; }
function savePng(doc, p) { var o = new PNGSaveOptions(); o.compression = 1; o.interlaced = false; doc.saveAs(new File(p), o, true, Extension.LOWERCASE); }
function closeIf(n) { for (var i = app.documents.length - 1; i >= 0; i--) if (app.documents[i].name == n) app.documents[i].close(SaveOptions.DONOTSAVECHANGES); }
function tk(s) { return s.charAt(0) == "'" ? C2T(s.substr(1, 4)) : S2T(s); }
function putE(d, s, L) {  // spec entry [key, kind, ...] into descriptor d, or (L) value [kind, ...] into ActionList d
  var o = L ? 0 : 1, k = L ? 0 : tk(s[0]), t = s[o], a = s[o + 1], b = s[o + 2], c = s[o + 3], x, i;
  if (t == "int") L ? d.putInteger(a) : d.putInteger(k, a); else if (t == "dbl") L ? d.putDouble(a) : d.putDouble(k, a);
  else if (t == "unit") L ? d.putUnitDouble(tk(a), b) : d.putUnitDouble(k, tk(a), b);
  else if (t == "bool") L ? d.putBoolean(a) : d.putBoolean(k, a); else if (t == "str") L ? d.putString(a) : d.putString(k, a);
  else if (t == "enum") L ? d.putEnumerated(tk(a), tk(b)) : d.putEnumerated(k, tk(a), tk(b));
  else if (t == "list") { x = new ActionList(); for (i = 0; i < a.length; i++) putE(x, a[i], true); L ? d.putList(x) : d.putList(k, x); }
  else if (t == "chref") { x = new ActionReference(); x.putEnumerated(S2T("channel"), S2T("channel"), tk(a)); L ? d.putReference(x) : d.putReference(k, x); }
  else { x = new ActionDescriptor(); var cls;  // object values: rgb, point, obj
    if (t == "rgb") { cls = "RGBColor"; x.putDouble(S2T("red"), a); x.putDouble(S2T("grain"), b); x.putDouble(S2T("blue"), c); }
    else if (t == "point") { cls = a; x.putDouble(S2T("horizontal"), b); x.putDouble(S2T("vertical"), c); }
    else if (t == "obj") { cls = a; for (i = 0; i < b.length; i++) putE(x, b[i], false); }
    else throw new Error("spec kind " + t);
    L ? d.putObject(tk(cls), x) : d.putObject(k, tk(cls), x); } }
function buildDesc(spec) { var d = new ActionDescriptor(); for (var i = 0; i < spec.length; i++) putE(d, spec[i], false); return d; }
function jobStart() { app.foregroundColor = rgbc(0, 0, 0); app.backgroundColor = rgbc(255, 255, 255); try { app.currentTool = "moveTool"; } catch (e) {} }
function photoDoc() { var s = app.open(new File(PLATE)); var d = s.duplicate("pgd_eg_w", true); s.close(SaveOptions.DONOTSAVECHANGES); app.activeDocument = d;
  if (d.mode != DocumentMode.RGB) d.changeMode(ChangeMode.RGB); if (d.bitsPerChannel != BitsPerChannelType.EIGHT) d.bitsPerChannel = BitsPerChannelType.EIGHT;
  d.resizeImage(undefined, undefined, 72, ResampleMethod.NONE); return d; }
function blendDoc() { var d = photoDoc(), t = app.open(new File(TOP)); t.layers[0].duplicate(d, ElementPlacement.PLACEATBEGINNING);
  t.close(SaveOptions.DONOTSAVECHANGES); app.activeDocument = d; d.activeLayer = d.layers[0]; d.activeLayer.name = "PGD top layer";
  if (d.layers.length != 2) throw new Error("blend plate has " + d.layers.length + " layers, expected 2"); return d; }
function textDoc() { var d = app.documents.add(UnitValue(1920, "px"), UnitValue(1080, "px"), 72, "pgd_eg_w", NewDocumentMode.RGB, DocumentFill.WHITE);
  d.selection.selectAll(); d.selection.fill(rgbc(128, 128, 128)); d.selection.deselect();
  var L = d.artLayers.add(); L.kind = LayerKind.TEXT; L.name = "PGD"; var t = L.textItem; t.contents = "PGD"; t.font = "Arial-Black";
  t.size = UnitValue(360, "px"); t.color = rgbc(225, 225, 225); t.justification = Justification.CENTER; t.position = [UnitValue(960, "px"), UnitValue(660, "px")];
  var b = L.bounds; L.translate(UnitValue(960 - (b[0].as("px") + b[2].as("px")) / 2, "px"), UnitValue(540 - (b[1].as("px") + b[3].as("px")) / 2, "px"));
  d.activeLayer = L; return d; }
function finish(d, out) { if (d.layers.length > 1 || !d.layers[0].isBackgroundLayer) d.flatten(); savePng(d, out); d.close(SaveOptions.DONOTSAVECHANGES); }
function fxRef() { var r = new ActionReference(); r.putProperty(C2T("Prpr"), S2T("layerEffects")); r.putEnumerated(C2T("Lyr "), C2T("Ordn"), C2T("Trgt")); return r; }
function setFx(key, cls, obj) { var d = new ActionDescriptor(); d.putReference(C2T("null"), fxRef());
  var fx = new ActionDescriptor(); fx.putUnitDouble(S2T("scale"), S2T("percentUnit"), 100); fx.putObject(S2T(key), S2T(cls), obj);
  d.putObject(C2T("T   "), S2T("layerEffects"), fx); executeAction(C2T("setd"), d, DialogModes.NO); }
function getFx(key) { var L = layerDesc(); if (!L.hasKey(S2T("layerEffects"))) return null; var fx = L.getObjectValue(S2T("layerEffects"));
  if (fx.hasKey(S2T(key))) return fx.getObjectValue(S2T(key));
  if (fx.hasKey(S2T(key + "Multi"))) return fx.getList(S2T(key + "Multi")).getObjectValue(0); return null; }
function setMode(v) { var d = new ActionDescriptor(), r = new ActionReference(); r.putEnumerated(C2T("Lyr "), C2T("Ordn"), C2T("Trgt")); d.putReference(C2T("null"), r);
  var l = new ActionDescriptor(); l.putEnumerated(S2T("mode"), S2T("blendMode"), S2T(v)); d.putObject(C2T("T   "), C2T("Lyr "), l); executeAction(C2T("setd"), d, DialogModes.NO); }
function adjLayer(cls, spec) { var u = new ActionDescriptor(); u.putObject(S2T("type"), S2T(cls), buildDesc(spec));
  var m = new ActionDescriptor(), r = new ActionReference(); r.putClass(S2T("adjustmentLayer")); m.putReference(C2T("null"), r);
  m.putObject(S2T("using"), S2T("adjustmentLayer"), u); executeAction(S2T("make"), m, DialogModes.NO); }
'''

ITEM = r'''
(function () {
  var J0 = %(job)s, R = {}, d = null;
  app.displayDialogs = DialogModes.NO;
  try {
    closeIf("pgd_eg_w");
    d = J0.setup == "text" ? textDoc() : (J0.setup == "blend" ? blendDoc() : photoDoc());
    jobStart();
    if (J0.mode == "event") { R.rb = d2o(executeAction(tk(J0.ev), buildDesc(J0.spec), J0.dialog ? DialogModes.ALL : DialogModes.NO)); }
    else if (J0.mode == "adjlayer") {
      adjLayer(J0.cls, J0.spec); var L = layerDesc();
      R.rb = L.hasKey(S2T("adjustment")) ? d2o(L.getList(S2T("adjustment")).getObjectValue(0)) : {}; R.layer = L.getString(S2T("name")); }
    else if (J0.mode == "style") {
      var e = buildDesc(J0.spec); e.putBoolean(S2T("enabled"), true); setFx(J0.key, J0.cls, e);
      var g = getFx(J0.key); if (!g) throw new Error("effect " + J0.key + " not on the layer after set"); R.rb = d2o(g); R.layer = d.activeLayer.name; }
    else if (J0.mode == "blend") {
      setMode(J0.ev); var L2 = layerDesc();
      R.rb = {mode: {t: "ENUMERATEDTYPE", v: tid2s(L2.getEnumerationValue(S2T("mode")))}, opacity: dval(L2, S2T("opacity"), 0)}; R.layer = d.activeLayer.name; }
    R.layers = d.layers.length;
    finish(d, J0.out); d = null; R.ok = 1;
  } catch (e) { R.err = String(e); }
  if (d) try { d.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {}
  return J(R);
})();
'''

CLOSE_ALL = 'closeIf("pgd_eg_w"); closeIf("pgd_eg_canary"); try { app.purge(PurgeTarget.ALLCACHES); } catch (e) {} "ok"'
CANARY = ('var d = app.documents.add(UnitValue(32, "px"), UnitValue(32, "px"), 72, "pgd_eg_canary", NewDocumentMode.RGB, DocumentFill.WHITE); '
          'executeAction(S2T("invert"), new ActionDescriptor(), DialogModes.NO); d.close(SaveOptions.DONOTSAVECHANGES); "ok"')


class Hang(Exception):
    pass


class NoHeadroom(Exception):
    pass


def ps():
    sys.path.insert(0, str(HERE))
    import psdrv
    return psdrv


STATE = {"since": 0, "base_gb": 0.0}


def restart(why):
    log(f"  restart Photoshop: {why}")
    ps().restart_ps()  # kills only the pid in work/ps/ps.pid, starts a new one and records its pid
    STATE["since"], STATE["base_gb"] = 0, ps_private_gb()
    log(f"  Photoshop up, pid {ps().owned_pid()} ({STATE['base_gb']:.1f} GB private)")


def ps_private_gb():
    import psutil
    pid = ps().owned_pid()
    try:
        return psutil.Process(pid).memory_info().private / 2 ** 30 if pid else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def headroom_gb():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/hostlock.py: vendored, same host mutex
    import hostlock
    _free, used, lim, top = hostlock.headroom()
    return (None, top) if used is None else (lim - used, top)


def guard():
    t0, first = time.time(), True
    while True:
        hr, top = headroom_gb()
        psgb = ps_private_gb()
        why = None
        if not ps().owned_pid():
            why = "Photoshop is not running"
        elif first and STATE["since"] >= RESTART_EVERY:
            why = f"{STATE['since']} items since the last restart"
        elif psgb > MAX_PS_GB:
            why = f"Photoshop holds {psgb:.1f} GB private (cap {MAX_PS_GB:g})"
        elif hr is not None and hr < MIN_HEADROOM_GB and psgb > STATE["base_gb"] + 0.5:
            why = f"commit headroom {hr:.1f} GB (largest: {top}); Photoshop {psgb:.1f} GB"
        first = False
        if why:
            restart(why)
            continue
        if hr is None or hr >= MIN_HEADROOM_GB:
            return
        if time.time() - t0 > WAIT_MAX_S:
            raise NoHeadroom(f"commit headroom below {MIN_HEADROOM_GB} GB for {WAIT_MAX_S // 60} min (now {hr:.1f}, largest {top})")
        log(f"  waiting for commit headroom: {hr:.1f} GB (largest: {top}; Photoshop {psgb:.1f} GB)")
        time.sleep(60)


# ------------------------------------------------------------------ dialogs (window handles only, no global input)
def _children(hwnd):
    import ctypes.wintypes as wt
    U, out = ctypes.windll.user32, []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        c, r = ctypes.create_unicode_buffer(64), wt.RECT()
        U.GetClassNameW(h, c, 64)
        U.GetWindowRect(h, ctypes.byref(r))
        if U.IsWindowVisible(h):
            out.append({"hwnd": h, "cls": c.value, "x": r.left, "y": r.top, "text": _text(h)})
        return True
    U.EnumChildWindows(hwnd, cb, 0)
    return out


def _text(h):
    """WM_GETTEXT with a timeout (works across processes for Edit / Static / Button controls)."""
    import ctypes.wintypes as wt
    buf, res = ctypes.create_unicode_buffer(256), wt.DWORD()
    ctypes.windll.user32.SendMessageTimeoutW(h, 0x000D, 256, buf, 0x0002, 2000, ctypes.byref(res))
    return buf.value


def pair_fields(ctrls):
    """dialog controls -> [{label, value}] for each Edit, top to bottom; label = the Static just left of it on its row."""
    stat = [c for c in ctrls if c["cls"] == "Static" and c["text"].strip()]
    out = []
    for e in sorted((c for c in ctrls if c["cls"] == "Edit"), key=lambda c: (c["y"], c["x"])):
        row = [s for s in stat if abs(s["y"] - e["y"]) <= 8 and s["x"] < e["x"]]
        lab = max(row, key=lambda s: s["x"])["text"].replace("&", "").rstrip(":") if row else ""
        out.append({"label": lab, "value": e["text"]})
    return out


def ok_dialog(hwnd, cls):
    """confirm a dialog by handle: BM_CLICK its win32 OK button; a Drover dialog (#32770 without Button children) takes
    Enter posted to its Edit field. -> how it was confirmed, or None (never Enter into any other window: the contextual
    task bar has a prompt field)."""
    U = ctypes.windll.user32
    kids = _children(hwnd)
    for c in kids:
        if c["cls"] == "Button" and c["text"].replace("&", "") == "OK":
            U.PostMessageW(c["hwnd"], 0x00F5, 0, 0)  # BM_CLICK
            return "BM_CLICK OK"
    eds = [c for c in kids if c["cls"] == "Edit"]
    if eds and cls == "#32770":
        for m, ch in ((0x0100, 0x0D), (0x0102, 0x0D), (0x0101, 0x0D)):  # WM_KEYDOWN / WM_CHAR / WM_KEYUP Enter
            U.PostMessageW(eds[0]["hwnd"], m, ch, 0)
        return "Enter posted to its Edit field"
    return None


def capture(hwnd, path):
    """PrintWindow of a dialog into a PNG (the visual record of the values it showed)."""
    import ctypes.wintypes as wt
    import win32gui, win32ui
    from PIL import Image
    r = wt.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
    hdc = win32gui.GetWindowDC(hwnd)
    mfc = win32ui.CreateDCFromHandle(hdc)
    sdc = mfc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc, r.right - r.left, r.bottom - r.top)
    sdc.SelectObject(bmp)
    ctypes.windll.user32.PrintWindow(hwnd, sdc.GetSafeHdc(), 2)  # PW_RENDERFULLCONTENT
    info = bmp.GetInfo()
    Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1).save(path)
    win32gui.DeleteObject(bmp.GetHandle())
    sdc.DeleteDC()
    mfc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hdc)


NOT_DIALOG = ("OWL.", "DroverLord - Window Class")  # shadows / frames and the contextual task bar, never dialogs


def call(src, timeout, tag, on_dialog=None):
    """psdrv.js plus: a window that opens during the call (a plug-in dialog that opens despite DialogModes.NO, such as
    Smart Blur, or the control's own dialog) goes to on_dialog(window) -> label or None; the crash reporter kills our
    Photoshop (recorded pid). Returns (result, [labels])."""
    pd = ps()
    inner = pd.LIB + "\n" + (PSJ % {"plate": json.dumps(PLATE), "top": json.dumps(TOP.as_posix())}) + "\n" + src
    wrapped = ('try { eval(decodeURIComponent("%s")) } catch (e) { "__ERR__" + String(e) + " @line " + e.line }'
               % urllib.parse.quote(inner, safe=""))
    before = {w["hwnd"] for w in pd.ps_windows()}
    box, handled = {}, []
    t = threading.Thread(target=pd._worker, args=(wrapped, box), daemon=True)
    t.start()
    t0 = time.time()
    while t.is_alive() and time.time() - t0 < timeout:
        t.join(1.0)
        if not t.is_alive():
            break
        for w in pd.ps_windows():
            if w["title"].startswith("Error Report for"):
                pd.kill_owned(exit_wait=0)
                log(f"  {tag}: crash reporter seen, Photoshop killed (recorded pid)")
            elif on_dialog and w["owner"] and w["hwnd"] not in before and not w["cls"].startswith(NOT_DIALOG):
                lab = on_dialog(w)
                if lab:
                    before.add(w["hwnd"])
                    handled.append(lab)
    if t.is_alive():
        seen = pd.dismiss_dialogs(tag)
        t.join(30)
        if t.is_alive():
            raise Hang(f"HANG {tag} after {timeout}s (dialogs dismissed: {seen})")
    if "e" in box:
        raise RuntimeError(f"COM {tag}: {box['e']}")
    r = box.get("r")
    if isinstance(r, str) and r.startswith("__ERR__"):
        raise RuntimeError(r[7:])
    return r, handled


def press_ok(w):
    how = ok_dialog(w["hwnd"], w["cls"])
    return how and f"{w['title'] or w['cls']} ({how})"


def canary():
    try:
        return call(CANARY, 60, "canary")[0] == "ok"
    except Exception:  # noqa: BLE001
        return False


def wait_responsive(max_s=1500):
    t0 = time.time()
    while time.time() - t0 < max_s:
        try:
            if call('"1"', 60, "ping")[0] == "1":
                return True
        except Exception:  # noqa: BLE001
            time.sleep(10)
    return False


# ------------------------------------------------------------------ jobs
def job_for(kind, card, item, out):
    spec, by, bad = spec_for(kind, card, item)
    inv = item.get("invoke") or {}
    plate = SETUP[kind]
    j = {"setup": plate, "spec": spec, "out": Path(out).as_posix()}
    args = "{" + ", ".join(fmt(e) for e in spec) + "}"
    if kind == "ps_blend_mode":
        j.update(mode="blend", ev=(item.get("extra") or {}).get("am_enum") or item["id"])
        how = f"set layer mode blendMode.{j['ev']} on the blend plate's top layer (bars / grey ramp / fading magenta-cyan, 100% opacity) over the photo"
    elif kind == "ps_layer_style":
        x = item.get("extra") or {}
        j.update(mode="style", key=x.get("layerEffects_key") or item["id"], cls=x.get("descriptor_class") or item["id"])
        how = f"set layerEffects.{j['key']} = {j['cls']}{{enabled: true, {args[1:]} on the 'PGD' text layer of the text plate"
    elif kind == "ps_adjustment" and (item.get("extra") or {}).get("adjustment_class"):
        j.update(mode="adjlayer", cls=item["extra"]["adjustment_class"])
        how = f"make adjustmentLayer using {{type: {j['cls']}{args}}} above the photo plate"
    else:
        if not inv.get("ps_event"):
            raise ValueError("the harvest has no Action Manager event for this item (invoke is null)")
        j.update(mode="event", ev=inv["ps_event"])
        how = f"executeAction({j['ev']}, {args}, DialogModes.NO) on the photo plate's Background layer"
    return j, by, bad, how


class State:
    def __init__(self, kind):
        self.kind, self.dir = kind, GAL / kind
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index = {e["id"]: e for e in jload(self.dir / "index.json", [])}
        self.failed = jload(self.dir / "failed.json", {})
        self.notr = jload(self.dir / "not_rendered.json", {})

    def done(self, cid):
        return cid in self.index and (self.dir / f"{key(cid)}.png").exists()

    def put(self, cid, where, val):
        """record cid in exactly one of index / failed / not_rendered; frames of an id that is no longer in the
        index (and a crop its row no longer names) are deleted, so the PNGs always match index.json."""
        for d in (self.index, self.failed, self.notr):
            d.pop(cid, None)
        where[cid] = val
        k = key(cid)
        if where is not self.index:
            (self.dir / f"{k}.png").unlink(missing_ok=True)
        if where is not self.index or "crop" not in val:
            (self.dir / f"{k}_1to1.png").unlink(missing_ok=True)

    def save(self):
        for n, v in (("index.json", sorted(self.index.values(), key=lambda e: e["id"])),
                     ("failed.json", self.failed), ("not_rendered.json", self.notr)):
            t = self.dir / (n + ".tmp")
            t.write_text(json.dumps(v, indent=1, ensure_ascii=False), encoding="utf-8")
            t.replace(self.dir / n)


def full_path(name):
    p = SCR / "full" / f"{name}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def render_ref(st):
    out = st.dir / "ref.png"
    if out.exists():
        return
    full = full_path("ref_" + st.kind)
    r, _ = call(ITEM % {"job": json.dumps({"setup": SETUP[st.kind], "mode": "ref", "spec": [], "out": full.as_posix()})}, 180, f"{st.kind}:ref")
    res = json.loads(r)
    if res.get("err"):
        raise RuntimeError(f"reference frame for {st.kind}: {res['err']}")
    derive(full, out, st.dir / "ref_1to1.png" if st.kind in ("ps_filter", "ps_adjustment") else None)
    full.unlink()
    log(f"  {st.kind}: ref.png written")


def render_one(st, card, item):
    cid, k = card["id"], key(card["id"])
    out, full = st.dir / f"{k}.png", full_path(k)
    try:
        j, by, bad, how = job_for(st.kind, card, item, full)
    except ValueError as e:
        st.put(cid, st.failed, str(e))
        return "failed"
    tmo = SLOW.get(j.get("ev"), 240)
    t0 = time.time()
    full.unlink(missing_ok=True)
    try:
        r, oked = call(ITEM % {"job": json.dumps(j)}, tmo, f"{st.kind}:{cid}",
                       on_dialog=press_ok if st.kind in ("ps_filter", "ps_adjustment") else None)
        res = json.loads(r)
    except Hang as e:
        st.put(cid, st.failed, str(e)[:500])
        if not wait_responsive(600):
            restart(f"hung on {cid}")
        return "failed"
    except Exception as e:  # noqa: BLE001
        res, oked = {"err": str(e)}, []
    STATE["since"] += 1
    if res.get("err") or not full.exists():
        st.put(cid, st.failed, (res.get("err") or "no PNG written")[:500])
        return "failed"
    applied, dropped, changed, had_rb = reconcile(by, bad, res.get("rb") or {})
    stale = rep = None
    if j["mode"] == "event" and changed:  # some built-in filters (Unsharp Mask) report their dialog's last-used values
        stale = readback_check(j, respec(j["spec"], by, changed), full, f"{st.kind}:{cid}:readback")
        if stale and stale["differs"]:  # the same values again: is the filter deterministic, so the test means something?
            rep = readback_check(j, j["spec"], full, f"{st.kind}:{cid}:repeat")
    crop = st.dir / f"{k}_1to1.png" if wants_crop(item) else None
    derive(full, out, crop)
    full.unlink()
    if st.kind == "ps_blend_mode":
        applied = {"mode": plain(res["rb"]["mode"]), "opacity": plain(res["rb"]["opacity"])}
        if applied["mode"] != j["ev"]:
            changed["mode"] = [j["ev"], applied["mode"]]
    e = {"key": k, "id": cid, "name": card["name"], "plate": j["setup"], "applied": applied, "dropped": dropped,
         "how": how + (f" [a dialog opened despite DialogModes.NO and was confirmed by handle: {oked}]" if oked else ""),
         "diff_vs_ref": diff(out, st.dir / "ref.png"), "secs": round(time.time() - t0, 1)}
    if crop:
        e["crop"] = {"file": crop.name, "box": list(CROP_BOX), "scale": "1:1"}
    if stale and stale["differs"] and rep and not rep["differs"]:
        e["readback_stale"] = {dk: got for dk, (_, got) in changed.items()}
        e["readback_note"] = ("the event's result descriptor reported these values, but the same event with them gives "
                              f"different pixels (mean diff {stale['diff']['mean']}) while the values sent reproduce the "
                              "frame exactly, so the descriptor does not describe this frame; applied lists the values sent")
        applied.update({dk: sent for dk, (sent, _) in changed.items()})
    elif changed:
        e["changed"] = changed
        e["changed_check"] = ("re-check failed" if not stale else
                              "re-applied with the read-back values: pixel-identical, so the app used them" if not stale["differs"] else
                              "inconclusive: the read-back values give different pixels, but so does the same event with the "
                              f"values sent (mean diff {rep['diff']['mean']}): the filter is not deterministic" if rep else
                              "the read-back values give different pixels; the repeat with the values sent failed")
    if bad:
        e["untyped"] = dict(bad)
    if not had_rb and by:
        e["readback"] = "none: the event returned an empty descriptor, so applied lists the values sent"
    st.put(cid, st.index, e)
    return "ok"


def readback_check(j, spec, full, tag):
    """apply the job again with the read-back values; {differs, diff} against the frame just made, or None on error."""
    alt = full.with_name(full.stem + "_rb.png")
    try:
        r, _ = call(ITEM % {"job": json.dumps(dict(j, spec=spec, out=alt.as_posix()))}, SLOW.get(j.get("ev"), 240), tag,
                    on_dialog=press_ok)
        if json.loads(r).get("err") or not alt.exists():
            return None
        d = diff_stats(full, alt)
        return d and {"differs": d["max"] > 0, "diff": d}
    except Exception:  # noqa: BLE001
        return None
    finally:
        alt.unlink(missing_ok=True)


def not_rendered_reason(card):
    if card.get("status") != "current":
        return f"status is '{card.get('status')}', not current"
    if card.get("scriptable") == "no":
        return "scriptable is 'no': " + (card.get("scripting") or card.get("script_api") or "")[:200]
    return None


def run_kind(kind, only=None):
    st = State(kind)
    items = harvest(kind)
    todo = []
    for c in cards(kind):
        if only is not None and c["id"] not in only:
            continue
        why = not_rendered_reason(c)
        if why:
            st.put(c["id"], st.notr, why)
            continue
        if only is None and st.done(c["id"]):
            continue
        todo.append(c)
    st.save()
    log(f"{kind}: {len(todo)} to render ({len(st.index)} done, {len(st.notr)} not rendered)")
    for i in range(0, len(todo), BATCH):
        guard()
        render_ref(st)
        for c in todo[i:i + BATCH]:
            t0 = time.time()
            res = render_one(st, c, items[c["id"]])
            ok_canary = canary()
            log(f"  {kind} {c['id']:40s} {res:6s} {time.time() - t0:5.1f}s"
                + (f"  diff {st.index[c['id']]['diff_vs_ref']}" if res == "ok" else f"  {st.failed.get(c['id'], '')[:140]}"))
            st.save()
            if not ok_canary:
                restart(f"canary failed after {c['id']}")
        try:
            call(CLOSE_ALL, 120, "close")
        except Exception as e:  # noqa: BLE001
            log(f"  closing documents failed: {e}")
    return st


# ------------------------------------------------------------------ the dialog control
def control():
    """for each CONTROL card: the scripted route (DialogModes.NO) and the app's own dialog (the same descriptor with
    DialogModes.ALL: the dialog opens holding the values, its fields are read back and captured, OK by handle), both at
    full size from fresh plate documents; diff full size and at 960x540; the scripted frame is also diffed against the
    gallery frame. Extra: the adjustment-layer route with the dialog's values against the dialog frame."""
    d = SCR / "control"
    d.mkdir(parents=True, exist_ok=True)
    rows = []

    def run(name, j, dialog):
        full = d / f"{name}_{'dialog' if dialog else 'script'}_full.png"
        full.unlink(missing_ok=True)
        jj = dict(j, out=full.as_posix(), dialog=dialog)
        seen = {}

        def on_dialog(w):
            time.sleep(3)  # let the preview draw before the capture
            cap = d / f"{name}_dialog_window.png"
            try:
                capture(w["hwnd"], cap)
            except Exception as e:  # noqa: BLE001
                seen["capture_err"] = str(e)
            seen.update(title=w["title"], window_class=w["cls"], fields=pair_fields(_children(w["hwnd"])), capture=cap.name)
            seen["confirmed"] = ok_dialog(w["hwnd"], w["cls"])
            return seen["confirmed"] and w["title"]
        r, handled = call(ITEM % {"job": json.dumps(jj)}, 300, f"control:{name}", on_dialog=on_dialog if dialog else None)
        res = json.loads(r)
        if res.get("err"):
            raise RuntimeError(res["err"])
        if dialog and not handled:
            raise RuntimeError("the dialog never opened")
        small = d / f"{name}_{'dialog' if dialog else 'script'}.png"
        derive(full, small)
        return full, small, res, seen

    for kind, cid in CONTROL:
        card = next(c for c in cards(kind) if c["id"] == cid)
        item = harvest(kind)[cid]
        j, by, bad, how = job_for(kind, card, item, "x")
        row = {"kind": kind, "id": cid, "name": card["name"], "demo_settings": card.get("demo_settings"),
               "sent": {dk: sent_plain(e) for dk, e in by.items()}, "untyped": dict(bad), "scripted_how": how,
               "dialog_how": how.replace("DialogModes.NO", "DialogModes.ALL") + "; the dialog opened holding these values, its "
                             "fields were read back (WM_GETTEXT) and captured (PrintWindow), then OK by window handle"}
        try:
            sf, ss, sres, _ = run(cid, j, False)
            df, ds, dres, seen = run(cid, j, True)
            row.update(dialog=seen, script_readback={k: plain(v) for k, v in (sres.get("rb") or {}).items()},
                       dialog_readback={k: plain(v) for k, v in (dres.get("rb") or {}).items()},
                       diff_full=diff_stats(sf, df), diff_960=diff_stats(ss, ds),
                       script_vs_gallery_frame=diff_stats(ss, GAL / kind / f"{key(cid)}.png"))
            row["identical"] = row["diff_full"] is not None and row["diff_full"]["max"] == 0
            if cid == "brightnessEvent":  # does the adjustment-layer route give the dialog's pixels at the same values?
                lj = dict(j, mode="adjlayer", cls="brightnessEvent")
                lf, ls, lres, _ = run("adjlayer_brightnessEvent", lj, False)
                row["adjustment_layer_same_values"] = {"how": f"make adjustmentLayer using {{type: brightnessEvent{{"
                                                       + ", ".join(fmt(e) for e in j["spec"]) + "}} above the photo plate",
                                                       "vs_dialog_full": diff_stats(lf, df), "vs_dialog_960": diff_stats(ls, ds)}
        except Exception as e:  # noqa: BLE001
            row["error"] = str(e)[:500]
        rows.append(row)
        log(f"  control {cid}: " + json.dumps({k: row.get(k) for k in ("identical", "diff_full", "error")}))
        call(CLOSE_ALL, 120, "close")
    (d / "control.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    return rows


def main(argv):
    kinds, only = KINDS, None
    if "--kind" in argv:
        kinds = [argv[argv.index("--kind") + 1]]
    if "--ids" in argv:
        txt = Path(argv[argv.index("--ids") + 1]).read_text(encoding="utf-8")
        try:
            v = json.loads(txt)
            only = set(v if isinstance(v, list) else v.get("ids") or v.keys())
        except json.JSONDecodeError:
            only = {ln.strip() for ln in txt.splitlines() if ln.strip()}
    if ps()._ps_pids() and not ps().owned_pid():
        sys.exit("a Photoshop this pipeline did not start (work/ps/ps.pid) is running: not sending it scripts")
    blend_top()
    try:
        guard()  # starts Photoshop (psdrv, pid recorded) when it is not running
        if "--control" in argv:
            control()
            return 0
        for k in kinds:
            sel = None if only is None else only & {c["id"] for c in cards(k)}
            if sel is not None and not sel:
                continue
            st = run_kind(k, sel)
            log(f"{k}: index {len(st.index)}  failed {len(st.failed)}  not_rendered {len(st.notr)}")
    except NoHeadroom as e:
        log(f"STOPPED: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
