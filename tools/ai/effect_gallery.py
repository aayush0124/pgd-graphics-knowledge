"""PGD / Illustrator: render the EFFECT GALLERY (ai_effect + ai_blend_mode cards) on the vector test plate
-> gallery/<kind>/<key>.png (960x540) + index.json / failed.json / not_rendered.json + ref.png

    python effect_gallery.py                       # both kinds, resumable (skips keys whose PNG exists)
    python effect_gallery.py --kind ai_effect --limit 5
    python effect_gallery.py --ids ids.txt         # re-render just these card ids (json list or one per line)
    python effect_gallery.py selftest

Plates (1920x1080 RGB, white artboard, group PGD_TEST, raster effects 150 ppi; each saved once in work/ai/effect_gallery,
each with its own reference frame in gallery/ai_effect), chosen per LiveEffect by plate_of():
  vector   media/plate_vector.svg   -> plate_base.ai          ref.png           everything else
  overlap  media/plate_overlap.svg  -> plate_overlap_base.ai  ref_overlap.png   Pathfinder (shapes must overlap)
  photo    media/plate_photo.png    -> plate_photo_base.ai    ref_photo.png     Photoshop Effects (PSAdapter): their
           strokes and textures come from image detail; on flat fills they only remap brightness (the Effect menu's
           own dialog gives byte-identical frames there, so that is the filters' behaviour, not this route's)
key = sha1(card id)[:12].

ai_effect, two routes:
  direct  g.applyEffect('<LiveEffect name=..><Dict data="R k v I k v B k 0|1 S k word U k word"/></LiveEffect>') with
          the harvested simple defaults overridden by demo_settings; PNG exported; saved uncompressed and the stored
          dictionary read back.
  patched used when a demo value cannot travel in Dict data (Photoshop-effect binary descriptor, FillStyle colours,
          keys or strings with spaces) or when applyEffect alone draws nothing (no ai_live_effect in the harvest,
          every PSAdapter effect): applyEffect places the effect, the doc is saved uncompressed, its private
          PostScript data (AIPrivateData streams) gets the effect's dictionary replaced by the one Illustrator's own
          dialog stored in the probe file (work/ai/probes, probe_effects.py) with the demo values written in
          (binary descriptor patched in place, PrevDres = document resolution so pixel values are not rescaled), that
          PostScript is written as a plain .ai, reopened, re-rendered (nudge + resolution toggle), exported, saved and
          read back.
  chain    Pathfinder on a group: applyEffect appends the effect after the group's fill/stroke stack, where it acts
          on the group's own (empty) paint (blank or unchanged frames); the Effect menu puts it at the head of the
          chain, on the group's contents. So the saved file gets the effect moved there (chain_first), reopened,
          re-rendered, as in the patched route.
ai_blend_mode: magenta (#FF00C8) -> cyan (#00E5FF) linear gradient rectangle over the group's bounds, set to the mode.

No global input: dialogs are answered by window handle (Enter); Illustrator's 'Progress' window is left alone (answering
it cancels the render). Documents this script opens are closed DONOTSAVECHANGES.
"""
import argparse, base64, hashlib, json, re, struct, subprocess, sys, threading, time
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

from PIL import Image, ImageChops, ImageStat

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/hostlock.py: vendored, same host mutex
import aicom  # noqa: E402
from probe_effects import parse_block  # noqa: E402

ROOT = HERE.parents[1]
WORK = ROOT / "work" / "ai" / "effect_gallery"
GAL = ROOT / "gallery"
PLATE_SVG = ROOT / "media" / "plate_vector.svg"
BASE = WORK / "plate_base.ai"
PLATES = {"vector": (PLATE_SVG, BASE, "ref.png"),  # plate -> (source, base .ai, reference frame name)
          "overlap": (ROOT / "media" / "plate_overlap.svg", WORK / "plate_overlap_base.ai", "ref_overlap.png"),
          "photo": (ROOT / "media" / "plate_photo.png", WORK / "plate_photo_base.ai", "ref_photo.png")}
PROBE_CKPT = ROOT / "work" / "ai" / "probe_ckpt.json"
EXE = os.environ.get("PGD_AI_EXE") or r"C:\Program Files\Adobe\Adobe Illustrator 2026\Support Files\Contents\Windows\Illustrator.exe"
RES = 150
LETTER = {"Real": "R", "Int": "I", "Bool": "B", "String": "S", "UnicodeString": "U"}
KINDS = ("ai_effect", "ai_blend_mode")
CRASH = "Illustrator crashed while rendering this card"

aicom.PANELS = aicom.PANELS + ("com.adobe.AdobeSplashKit.TextWindowClass", "com.adobe.AdobeSplashKit.GraphicWindowClass")
_PID = [None]
aicom.ai_pid = lambda: _PID[0]  # one tasklist per poll ended in a MemoryError (preset_gallery.py)


def key(iid):
    return hashlib.sha1(iid.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- app plumbing
def find_pid():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Illustrator.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower() == "illustrator.exe":
            return int(parts[1])
    return None


def run(src, timeout=240):
    """js with dialogs answered (Enter) by handle while it runs; 'Progress' windows are left alone.
    -> (result, error, [dialog titles])"""
    box, seen, done = {}, [], set()

    def work():
        try:
            box["r"] = aicom.js(src, timeout)
        except Exception as e:  # noqa: BLE001
            box["e"] = str(e)

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t0 = time.time()
    while t.is_alive() and time.time() - t0 < timeout:
        time.sleep(0.3)
        for h, c, title, en in aicom.dialogs():
            if h in done or not en or title.startswith("Progress"):
                continue
            time.sleep(0.5)
            seen.append(title)
            for msg in (0x100, 0x101):
                aicom.u32.PostMessageW(h, msg, 0x0D, 0)
            done.add(h)
    t.join(2)
    if t.is_alive():
        return None, f"no return in {timeout}s; dialogs {seen}", seen
    return box.get("r"), box.get("e"), seen


def press_launch():
    """after a crash Illustrator starts behind 'Adobe Illustrator quit unexpectedly during launch' (Launch Illustrator /
    Run Diagnostics) and every script waits on it: press Launch Illustrator by handle (BM_CLICK, no global input)."""
    import ctypes.wintypes as W
    hits = []

    @aicom.ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def cb(h, _):
        t = aicom.ctypes.create_unicode_buffer(128)
        aicom.u32.GetWindowTextW(h, t, 128)
        if t.value.replace("&", "") == "Launch Illustrator":
            hits.append(h)
        return True
    for h, c, title, en in aicom.ai_windows(_PID[0]):
        if c == "#32770":
            aicom.u32.EnumChildWindows(h, cb, 0)
    for b in hits:
        aicom.u32.PostMessageW(b, 0x00F5, 0, 0)  # BM_CLICK
    return hits


def ready(wait=1200):  # a start under memory pressure (paging) sat on the splash for over 5 minutes
    t0 = time.time()
    while time.time() - t0 < wait:
        _PID[0] = find_pid()
        if _PID[0]:
            try:
                return aicom.js("app.version", 10)
            except Exception:  # noqa: BLE001
                if press_launch():
                    print("  answered the crash-recovery dialog: Launch Illustrator", flush=True)
        time.sleep(5)
    raise RuntimeError("Illustrator did not come up")


def start_app():
    if not find_pid():
        p = subprocess.Popen([EXE], creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | NEW_PROCESS_GROUP
        (WORK / "illustrator.pid").write_text(str(p.pid))  # the only PID this renderer may ever stop
        time.sleep(15)
    print("Illustrator", ready(), flush=True)


def headroom_gb():
    from hostlock import headroom
    _, used, lim, _ = headroom()
    return None if used is None else lim - used


def ai_private_gb():
    try:
        import psutil
        return psutil.Process(_PID[0]).memory_info().private / 2 ** 30
    except Exception:  # noqa: BLE001
        return None


def ensure_room(min_gb=4.0, max_ai_gb=float(os.environ.get("PGD_AI_MAX_GB") or 6)):
    """below min_gb commit headroom, or Illustrator's private memory above max_ai_gb (it grows per card and the
    machine runs short of physical RAM long before commit): restart Illustrator (only when no foreign document is
    open), wait for room."""
    h, mine = headroom_gb(), ai_private_gb()
    if (h is None or h >= min_gb) and (mine is None or mine < max_ai_gb):
        return h
    print(f"commit headroom {h if h is None else round(h, 1)} GB, Illustrator private {mine if mine is None else round(mine, 1)}"
          f" GB: restarting Illustrator", flush=True)
    cleanup()
    try:
        n = aicom.js("app.documents.length", 30)
    except Exception:  # noqa: BLE001  (still starting: nothing of ours to free)
        n = None
    if str(n) == "0":
        try:
            aicom.js("app.quit()", 60)
        except Exception:  # noqa: BLE001
            pass
        for _ in range(60):
            if not find_pid():
                break
            time.sleep(2)
    for i in range(180):  # up to 30 min
        h = headroom_gb()
        if h is None or h >= min_gb:
            break
        if i % 6 == 0:
            print(f"  waiting for room: commit headroom {h:.1f} GB", flush=True)
        time.sleep(10)
    start_app()
    return headroom_gb()


CLEANUP = r'''
(function(){var n=0;for(var i=app.documents.length-1;i>=0;i--){var d=app.documents[i],p="";
try{p=d.fullName.fsName.toLowerCase();}catch(e){}
if(p.indexOf(%s)==0){d.close(SaveOptions.DONOTSAVECHANGES);n++;}}return n;})();'''


def cleanup():
    """close every document opened from this script's work folder (left open by a failed call)."""
    try:
        return aicom.js(CLEANUP % json.dumps(str(WORK).lower()), 60)
    except Exception as e:  # noqa: BLE001
        return str(e)


# ---------------------------------------------------------------- .ai private data (PostScript) + PS descriptors
def private_data(raw):
    """concatenated AIPrivateData streams of a PDF-wrapped .ai (latin-1 str): the plain PostScript .ai inside."""
    i = raw.find("/AIMetaData ")  # str.find: the regex '.*?' version took seconds to minutes on some files
    j = raw.find("/ContainerVersion", i) if i >= 0 else -1
    if j < 0:
        return raw if raw.startswith("%!PS-Adobe") else None
    head = raw[i:j]
    # one pass over the file: a search per stream (432 of them in a 28 MB file) took minutes per card
    objs = {mm.group(1): mm for mm in re.finditer(r"(?<![0-9])(\d+) 0 obj\s*<</Length (\d+)>>stream\r?\n", raw)}
    parts = []
    for oid in re.findall(r"/AIPrivateData\d+ (\d+) 0 R", head):
        mm = objs[oid]
        parts.append(raw[mm.end():mm.end() + int(mm.group(2))])
    return "".join(parts)


def read_ps(path):
    return private_data(Path(path).read_bytes().decode("latin-1"))


def blocks(ps, name=None):
    """[(start, end)] of live-effect BasicFilter blocks (CRLF text)."""
    out = []
    for m in re.finditer(r"/BasicFilter :\r\n\(([^()\r\n]*)\) 1 0 /Filter ,\r\n", ps):
        if name is None or m.group(1) == name:
            e = ps.find("\r\n; /Dict ;", m.end())
            out.append((m.start(), e + len("\r\n; /Dict ;")))
    return out


CHAIN_HEAD = "(Chain Style Filter) 0 0 /Filter ,\r\n1 /Visible ,\r\n"
PART = "\r\n /Part ,\r\n"


def chain_first(ps, le):
    """move each `le` live effect to the head of its art style's chain, ahead of the fill/stroke stack (where the
    Effect menu puts a Pathfinder effect on a group: it then works on the group's contents). -> (ps, number moved)"""
    n = 0
    # ponytail: one `le` per art style (one applyEffect); two in one chain would need blocks() re-read per move
    for s, e in reversed(blocks(ps, le)):
        h = ps.rfind(CHAIN_HEAD, 0, s)
        if h < 0 or not ps.startswith(PART, e) or "/KnownStyle :" in ps[h:s]:
            continue  # not a part of an art style's chain
        h += len(CHAIN_HEAD)
        if h == s:
            continue  # already first
        ps = ps[:h] + ps[s:e + len(PART)] + ps[h:s] + ps[e + len(PART):]
        n += 1
    return ps, n


A85 = re.compile(r"/Binary : /ASCII85Decode ,\r\n(.*?~>)\r\n; \(data\) ,", re.S)


def get_data(block):
    m = A85.search(block)
    if not m:
        return None
    body = "".join(l[1:] if l.startswith("%") else l for l in m.group(1).split("\r\n"))
    return base64.a85decode(body.split("~>")[0])


def put_data(block, b):
    m = A85.search(block)
    s = base64.a85encode(b).decode("latin-1")
    lines = [s[i:i + 80] for i in range(0, len(s), 80)] or [""]
    lines[-1] += "~>"  # never split the end marker over a line break: Illustrator then reads the file as damaged (Smart Blur)
    return block[:m.start(1)] + "\r\n".join("%" + ln for ln in lines) + block[m.end(1):]


def walk(b, base=0, end=None):
    """Photoshop descriptor entries -> [(key, kind, value offset, length, children)] (layout as psdata.py)."""
    out, i, end = [], base + 4, len(b) if end is None else end
    while i + 12 <= end:
        k, flags, ty = b[i:i + 4].decode("latin-1"), struct.unpack(">I", b[i + 4:i + 8])[0], b[i + 8:i + 12].decode("latin-1")
        i += 12
        if flags & 0x2000:
            out.append((k, "enum", i, 4, None)); i += 4
        elif ty in ("long", "doub", "bool"):
            n = {"long": 4, "doub": 8, "bool": 1}[ty]
            out.append((k, ty, i, n, None)); i += n
        elif flags & 0x80000000:  # nested descriptor: size, then a block that starts with uint32 1
            size = struct.unpack(">I", b[i:i + 4])[0]
            out.append((k, "obj", i + 4, size, walk(b, i + 4, i + 4 + size))); i += 4 + size
        else:
            break
    return out


def desc_get(b, ents=None):
    res = {}
    for k, kind, off, n, ch in (walk(b) if ents is None else ents):
        res[k] = {"enum": lambda: b[off:off + 4].decode("latin-1"), "long": lambda: struct.unpack(">i", b[off:off + 4])[0],
                  "doub": lambda: struct.unpack(">d", b[off:off + 8])[0], "bool": lambda: bool(b[off]),
                  "obj": lambda: desc_get(b, ch)}[kind]()
    return res


def desc_patch(b, values, ents=None):
    """-> (patched bytes, keys written). Values: enum code, int, float, bool, or {sub key: value} for a nested one."""
    b, hit = bytearray(b), set()
    for k, kind, off, n, ch in (walk(bytes(b)) if ents is None else ents):
        if k not in values:
            continue
        v = values[k]
        if kind == "enum":
            b[off:off + 4] = str(v).encode("latin-1")[:4].ljust(4)
        elif kind == "long":
            b[off:off + 4] = struct.pack(">i", int(round(float(v))))
        elif kind == "doub":
            b[off:off + 8] = struct.pack(">d", float(v))
        elif kind == "bool":
            b[off] = 1 if v else 0
        elif kind == "obj" and isinstance(v, dict):
            b = bytearray(desc_patch(bytes(b), v, ch)[0])
        else:
            continue
        hit.add(k)
    return bytes(b), hit


def set_simple(block, k, ty, v):
    """write '<v> /<ty> (<k>) ,' into the dictionary: replace the line(s), or add one before '; /Dict ;'."""
    sv = f"({v})" if ty in ("String", "UnicodeString") else str(v)
    pat = re.compile(r"(?m)^[^\r\n]*? /%s \(%s\) ,(?=\r?$)" % (ty, re.escape(k)))  # CRLF: '$' stops before \n only
    # ponytail: replaces every line with this key, nested dictionaries included; no demo key repeats in one today
    if pat.search(block):
        return pat.sub(lambda m: f"{sv} /{ty} ({k}) ,", block)
    i = block.rfind("\r\n; /Dict ;")
    return block[:i] + f"\r\n{sv} /{ty} ({k}) ," + block[i:]


def fill_rgb(block, k):
    m = re.search(r"/FillStyle : 0 O\r\n([^\r\n]*) Xa\r\n(?:(?!/FillStyle)[\s\S])*?\(%s\) ," % re.escape(k), block)
    if not m:
        return None
    v = [float(x) for x in m.group(1).split()]
    return "#%02X%02X%02X" % tuple(round(255 * x) for x in v[4:7]) if len(v) >= 7 else None


def set_fill(block, k, hexrgb):
    r, g, b = (int(hexrgb.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    kk = 1 - max(r, g, b)
    c, m, y = ((1 - x - kk) / (1 - kk) if kk < 1 else 0 for x in (r, g, b))
    xa = " ".join(f"{x:.6g}" for x in (c, m, y, kk, r, g, b))
    pat = re.compile(r"(/FillStyle : 0 O\r\n)[^\r\n]* Xa(\r\n(?:(?!/FillStyle)[\s\S])*?\(%s\) ,)" % re.escape(k))
    return pat.sub(lambda mm: mm.group(1) + xa + " Xa" + mm.group(2), block, count=1) if pat.search(block) else None


# ---------------------------------------------------------------- JS
EXPORT = r'''var e=new ExportOptionsPNG24();e.artBoardClipping=true;e.antiAliasing=true;e.transparency=false;
e.horizontalScale=50;e.verticalScale=50;d.exportFile(new File(File(%(png)s).fsName),ExportType.PNG24,e);r.png=1;'''
SAVE = r'''var o=new IllustratorSaveOptions();o.compressed=false;o.pdfCompatible=false;o.embedICCProfile=false;d.saveAs(new File(File(%(save)s).fsName),o);r.saved=1;'''
WRAP = r'''(function(){
var r={},d=null,uil=app.userInteractionLevel;app.userInteractionLevel=UserInteractionLevel.DONTDISPLAYALERTS;
try{
 d=app.open(new File(File(%(open)s).fsName));
 var g=null;try{g=d.groupItems.getByName("PGD_TEST");}catch(e){}
 %(body)s
}catch(e){r.err=String(e);}
try{if(d)d.close(SaveOptions.DONOTSAVECHANGES);}catch(e){r.close=String(e);}
app.userInteractionLevel=uil;
var s=[];for(var q in r)s.push('"'+q+'":"'+String(r[q]).replace(/\\/g,'/').replace(/"/g,"'").replace(/[\r\n]+/g,' ')+'"');
return '{'+s.join(',')+'}';
})();'''
RERENDER = r'''if(g){g.hidden=false;g.translate(1,0);g.translate(-1,0);}'''  # hidden at save: no render of the placeholder
BLEND = r'''var b=g.geometricBounds,L=g.layer;
var rc=L.pathItems.rectangle(b[1],b[0],b[2]-b[0],b[1]-b[3]);
function C(x,y,z){var c=new RGBColor();c.red=x;c.green=y;c.blue=z;return c;}
var gr=d.gradients.add();gr.type=GradientType.LINEAR;
gr.gradientStops[0].color=C(255,0,200);gr.gradientStops[1].color=C(0,229,255);
var gc=new GradientColor();gc.gradient=gr;rc.stroked=false;rc.filled=true;rc.fillColor=gc;
rc.blendingMode=%(mode)s;r.read=String(rc.blendingMode);'''


def jsq(p):
    return json.dumps(Path(p).as_posix())


def call(open_path, body, png=None, save=None, timeout=300):
    code = body + (EXPORT % {"png": jsq(png)} if png else "") + (SAVE % {"save": jsq(save)} if save else "")
    r, e, seen = run(WRAP % {"open": jsq(open_path), "body": code}, timeout)
    res = {}
    if r:
        try:
            res = json.loads(r)
        except Exception as ex:  # noqa: BLE001
            e = f"bad result {r[:200]}: {ex}"
    if seen:
        res["_dialogs"] = seen
    err = e or res.get("err") or res.get("close")
    if err:
        cleanup()
    return res, err


def plate_of(le):
    """LiveEffect name -> plate name (PLATES)."""
    if le == "Adobe Pathfinder":
        return "overlap"
    if str(le).startswith("PSAdapter_plugin_"):
        return "photo"
    return "vector"


def make_base(plate="vector"):
    src_file, base, _ = PLATES[plate]
    WORK.mkdir(parents=True, exist_ok=True)
    if base.exists():
        return
    # a NEW RGB document (its profile ships the SVG filter definitions the SVG Filters effects need); its graphic
    # styles and symbols removed so the only live-effect blocks in a saved file are the ones applied here
    if plate == "photo":  # the photo embedded as one 1920x1080 pt image filling the artboard, inside PGD_TEST
        art = r'''var g=d.layers[0].groupItems.add();g.name="PGD_TEST";var pi=g.placedItems.add();
pi.file=new File(File(%s).fsName);pi.width=1920;pi.height=1080;var a2=d.artboards[0].artboardRect;
pi.position=[a2[0],a2[1]];pi.embed();''' % jsq(src_file)
    else:
        art = r'''var s=app.open(new File(File(%s).fsName));var sg=s.layers[0].groupItems[0];
var g=sg.duplicate(d.layers[0],ElementPlacement.PLACEATBEGINNING);
var a1=s.artboards[0].artboardRect,a2=d.artboards[0].artboardRect;g.translate(a2[0]-a1[0],a2[1]-a1[1]);g.name="PGD_TEST";
s.close(SaveOptions.DONOTSAVECHANGES);''' % jsq(src_file)
    src = r'''(function(){var d=app.documents.add(DocumentColorSpace.RGB,1920,1080);
for(var i=d.graphicStyles.length-1;i>0;i--){try{d.graphicStyles[i].remove();}catch(e){}}
for(var i=d.symbols.length-1;i>=0;i--){try{d.symbols[i].remove();}catch(e){}}
d.rasterEffectSettings.resolution=%d;
%s
var o=new IllustratorSaveOptions();o.compressed=false;d.saveAs(new File(File(%s).fsName),o);
d.close(SaveOptions.DONOTSAVECHANGES);return "ok";})();''' % (RES, art, jsq(base))
    r, e, _ = run(src, 300)
    if r != "ok":
        raise RuntimeError(f"plate base {plate}: {r} {e}")


# ---------------------------------------------------------------- plan: demo_settings -> what the app gets
def find_param(it, k):
    ps = it.get("params") or []
    for p in ps:
        if p["key"] == k or p.get("name") == k:
            return p
    kk = str(k).strip().casefold()
    for p in ps:
        if p["key"].strip().casefold() == kk or (p.get("name") or "").strip().casefold() == kk:
            return p
    return None


def enum_code(p, v):
    for e in p.get("enum") or []:
        if str(v).strip().casefold() in (str(e["label"]).strip().casefold(), str(e["value"]).strip().casefold()):
            return e["value"]
    if (p.get("extra") or {}).get("ps_type") == "enum" and isinstance(v, str) and 1 <= len(v.strip()) <= 4:
        return v  # 4-char enumerator given directly (Texture Type 'TxCa')
    raise ValueError(f"{v!r} is not one of the harvested values")


def label_of(p, code, demo):
    for e in p.get("enum") or []:
        if str(e["value"]).strip() == str(code).strip():
            return e["label"] if str(demo).strip().casefold() == str(e["label"]).strip().casefold() else e["value"]
    return code


def hexcol(v):
    s = str(v).strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", s):
        raise ValueError(f"colour {v!r} is not #RRGGBB")
    return "#" + s.upper()


def simple_val(ty, v):
    if ty == "Bool":
        return "1" if (v is True or str(v).lower() in ("1", "true")) else "0"
    if ty == "Int":
        return str(int(round(float(v))))
    if ty == "Real":
        return repr(float(v))
    return str(v)


def default_simple(p):
    t, v = (p.get("extra") or {}).get("ai_type"), p.get("default")
    if t not in LETTER or v is None or " " in p["key"]:
        return None
    if t in ("String", "UnicodeString") and (not isinstance(v, str) or not v or " " in v or '"' in v):
        return None
    return simple_val(t, v)


class Ctx:
    def __init__(self):
        self.harvest = {k: {i["id"]: i for i in json.loads((ROOT / "harvest" / "ai" / f"{k}.json").read_text("utf-8"))["items"]}
                        for k in KINDS}
        self.probe = json.loads(PROBE_CKPT.read_text("utf-8"))
        self.by_le = {}
        for it in self.harvest["ai_effect"].values():
            le = (it.get("invoke") or {}).get("ai_live_effect") or (it.get("extra") or {}).get("live_effect_name")
            if le:
                self.by_le.setdefault(le, it)

    def template(self, path, le):
        """the dictionary block Illustrator's own dialog stored for this effect (probe file), or None."""
        f = (self.probe.get(path) or {}).get("file")
        if not f or not Path(f).exists():
            return None
        ps = read_ps(f)
        bl = blocks(ps, le) if ps else []
        return ps[bl[0][0]:bl[0][1]] if bl else None


def plan_effect(ctx, card, it):
    """-> dict(le, xml, demo map, route, ...) or raises ValueError(reason)."""
    demo = dict(card.get("demo_settings") or {})
    inv = it.get("invoke") or {}
    pl = {"le": inv.get("ai_live_effect"), "path": it["path"], "item": it, "simple": {}, "text": {}, "bin": {},
          "fill": {}, "dropped": [], "notes": [], "map": {}, "dom": None}
    if it["id"] == "Live PSAdapter_plugin_GEfc":  # Effect Gallery: the chosen gallery filter is what gets stored
        code = enum_code(find_param(it, "Effect"), demo.pop("Effect", "Glowing Edges"))
        pl["le"] = "PSAdapter_plugin_" + code.strip()
        tgt = ctx.by_le.get(pl["le"])
        pl["path"], it = tgt["path"], tgt
        pl["map"]["Effect"] = ("gallery", None, code)
        pl["notes"].append(f"Effect Gallery filter {code.strip()} = LiveEffect {pl['le']} (what the gallery dialog stores)")
    if it["id"] == "Live Rasterize Effect Setting":
        pl["dom"] = {}
        for k, v in demo.items():
            p = find_param(it, k)
            if not p:
                pl["dropped"].append(k)
                continue
            pl["dom"][p["key"]] = enum_code(p, v) if p.get("enum") else v
            pl["map"][k] = ("dom", p, v)
        return pl
    if not pl["le"]:
        pl["le"] = (it.get("extra") or {}).get("live_effect_name") or next(
            (e["live_effect"] for e in (ctx.probe.get(it["path"]) or {}).get("effects") or []), None)
    if not pl["le"]:
        raise ValueError("no LiveEffect name in the harvest or the probe file")
    for p in it.get("params") or []:
        dv = default_simple(p)
        if dv is not None:
            pl["simple"][p["key"]] = (p["extra"]["ai_type"], dv)
    for k, v in demo.items():
        p = find_param(it, k)
        if not p:
            pl["dropped"].append(k)
            pl["notes"].append(f"{k}: no harvested param of that name or key")
            continue
        x = p.get("extra") or {}
        try:
            if str(x.get("in", "")).startswith("binary"):
                if p["type"] == "color":
                    c = hexcol(v)
                    val = {"Rd  ": int(c[1:3], 16), "Grn ": int(c[3:5], 16), "Bl  ": int(c[5:7], 16)}
                elif p.get("enum") or x.get("ps_type") == "enum":
                    val = enum_code(p, v)
                elif x.get("ps_type") == "bool":
                    val = bool(v)
                else:
                    val = float(v) if x.get("ps_type") == "doub" else int(round(float(v)))
                pl["bin"][p["key"]] = val
                pl["map"][k] = ("bin", p, v)
            elif x.get("ai_type") == "FillStyle":
                pl["fill"][p["key"]] = hexcol(v)
                pl["map"][k] = ("fill", p, v)
            elif x.get("ai_type") in LETTER:
                ty = x["ai_type"]
                sv = simple_val(ty, enum_code(p, v) if p.get("enum") else v)
                if " " in p["key"] or (ty in ("String", "UnicodeString") and (" " in sv or '"' in sv or not sv)):
                    pl["text"][p["key"]] = (ty, sv)
                    pl["simple"].pop(p["key"], None)
                else:
                    pl["simple"][p["key"]] = (ty, sv)
                pl["map"][k] = ("simple", p, v)
            else:
                pl["dropped"].append(k)
                pl["notes"].append(f"{k}: type {x.get('ai_type') or p['type']} has no scripted route")
        except ValueError as ex:
            pl["dropped"].append(k)
            pl["notes"].append(f"{k}: {ex}")
    data = " ".join(f"{LETTER[t]} {k} {v}" for k, (t, v) in pl["simple"].items())
    pl["xml"] = '<LiveEffect name="%s"><Dict data="%s"/></LiveEffect>' % (pl["le"], data)
    pl["patch"] = bool(pl["bin"] or pl["fill"] or pl["text"] or not inv.get("ai_live_effect")
                       or pl["le"].startswith("PSAdapter_plugin_") or pl["le"] != inv.get("ai_live_effect"))
    if pl["patch"]:
        pl["template"] = ctx.template(pl["path"], pl["le"])
        if pl["template"] is None:
            pl["notes"].append("no dialog-made dictionary to start from (probe file): applyEffect values only")
            for k, (kind, p, v) in list(pl["map"].items()):
                if kind in ("bin", "fill") or (kind == "simple" and p["key"] in pl["text"]):
                    pl["dropped"].append(k)
                    del pl["map"][k]
            pl["bin"], pl["fill"], pl["text"], pl["patch"] = {}, {}, {}, False
    pl["chain_first"] = pl["le"] == "Adobe Pathfinder"
    pl["plate"] = plate_of(pl["le"])
    return pl


def patched_block(pl):
    blk = pl["template"]
    for k, (ty, v) in pl["simple"].items():
        if any(k == kk for kk in pl["map_keys_simple"]):
            blk = set_simple(blk, k, ty, v)
    for k, (ty, v) in pl["text"].items():
        blk = set_simple(blk, k, ty, v)
    if re.search(r"(?m)^\d+ /Int \(PrevDres\) ,\r?$", blk):
        blk = set_simple(blk, "PrevDres", "Int", RES)
    for k, c in pl["fill"].items():
        nb = set_fill(blk, k, c)
        if nb is None:
            raise ValueError(f"FillStyle {k} not in the dialog dictionary")
        blk = nb
    if pl["bin"]:
        b = get_data(blk)
        if b is None:
            raise ValueError("no binary descriptor (data) in the dialog dictionary")
        b2, hit = desc_patch(b, pl["bin"])
        miss = set(pl["bin"]) - hit
        if miss:
            raise ValueError(f"descriptor has no {sorted(miss)}")
        blk = put_data(blk, b2)
    return blk


def read_back(pl, ps):
    """values of the mapped demo keys in the saved file -> (applied, dropped, block found)"""
    bl = blocks(ps, pl["le"]) if ps else []
    if not bl:
        return {}, list(pl["map"]), False
    blk = ps[bl[0][0]:bl[0][1]]
    simple = {p["key"]: p.get("value") for p in parse_block(blk.replace("\r\n", "\n"))["params"]}
    data = get_data(blk)
    desc = desc_get(data) if data else {}
    applied, dropped = {}, []
    for k, (kind, p, v) in pl["map"].items():
        if kind == "gallery":
            got = desc.get("GEfk")
            applied[k] = label_of(find_param(pl["item"], "Effect") or {}, got, v) if got else pl["le"]
            continue
        got = None
        if kind == "simple":
            got = simple.get(p["key"])
            if got is not None and p.get("enum"):
                got = label_of(p, got, v)
        elif kind == "fill":
            got = fill_rgb(blk, p["key"])
        elif kind == "bin":
            got = desc.get(p["key"])
            if isinstance(got, dict):
                got = "#%02X%02X%02X" % tuple(int(round(got.get(c, 0))) for c in ("Rd  ", "Grn ", "Bl  "))
            elif isinstance(got, str):
                got = label_of(p, got, v).strip() if p.get("enum") else got.strip()
        if got is None:
            dropped.append(k)
        else:
            applied[k] = got
    return applied, dropped, True


def same(got, v):
    if isinstance(v, bool) or isinstance(got, bool):
        return bool(got) == (v is True or str(v).lower() in ("1", "true"))
    try:
        return abs(float(got) - float(v)) <= 1e-3 * max(1, abs(float(v)))
    except (TypeError, ValueError):
        return str(got).strip().casefold() == str(v).strip().casefold()


def mismatches(pl, applied):
    return [f"{k}: sent {pl['map'][k][2]!r}, stored {got!r}" for k, got in applied.items()
            if pl["map"][k][0] not in ("gallery", "dom") and not same(got, pl["map"][k][2])]


# ---------------------------------------------------------------- render one card
def frame_diff(png, ref):
    try:
        A, B = Image.open(png).convert("RGB"), Image.open(ref).convert("RGB")
        return round(sum(ImageStat.Stat(ImageChops.difference(A, B)).mean) / 3, 3) if A.size == B.size else None
    except Exception:  # noqa: BLE001
        return None


def blank(png):
    """near-uniform frame: the effect left nothing visible on the white artboard (Convert to Shape / Pathfinder on the
    group draw with the group's own paint, which is none). Its diff vs the plate is large, so diff alone passes it."""
    with Image.open(png) as im:
        return max(ImageStat.Stat(im.convert("RGB")).stddev) < 2


APPLY = {"group": "g.applyEffect(%s);",
         # some effects draw nothing on a group (3D Classic: not even through its own dialog) but do on single paths
         "each": "for(var i=0;i<g.pageItems.length;i++)g.pageItems[i].applyEffect(%s);"}


def render_effect(ctx, card, png):
    """-> (applied, dropped, how, notes, dialogs, reference frame of the plate it was rendered on)"""
    applied, dropped, how, notes, dlg, ref = render_effect_on(ctx, card, png, "group")
    if "rasterEffectSettings" not in how:
        why = "identical to the plate" if frame_diff(png, ref) == 0.0 else "blank" if blank(png) else None
        if why:
            applied, dropped, how, notes, dlg, ref = render_effect_on(ctx, card, png, "each")
            notes = notes + [f"frame {why} when applied to the group: applied to each plate shape instead"]
    return applied, dropped, how, notes, dlg, ref


def render_effect_on(ctx, card, png, target):
    it = ctx.harvest["ai_effect"][card["id"]]
    pl = plan_effect(ctx, card, it)
    plate = pl.get("plate", "vector")
    src_file, base, ref_name = PLATES[plate]
    ref = GAL / "ai_effect" / ref_name
    k = key(card["id"])
    fa, fp, fr = WORK / f"{k}_a.ai", WORK / f"{k}_p.ai", WORK / f"{k}_r.ai"
    if pl["dom"] is not None:  # Document Raster Effects Settings + a Gaussian Blur so the settings have something to draw
        sets = "".join(f"s.{kk}={vv if isinstance(vv, str) and '.' in vv and not vv[0].isdigit() else json.dumps(vv)};"
                       for kk, vv in pl["dom"].items())
        blur = '<LiveEffect name="Adobe PSL Gaussian Blur"><Dict data="R blur 6"/></LiveEffect>'
        body = (f"var s=d.rasterEffectSettings;{sets}g.applyEffect({json.dumps(blur)});"
                "r.read=[s.resolution,s.colorModel,s.antiAliasing,s.transparency,s.clippingMask,s.padding].join('|');")
        res, err = call(BASE, body, png=png)
        if err:
            raise RuntimeError(err)
        got = dict(zip(["resolution", "colorModel", "antiAliasing", "transparency", "clippingMask", "padding"],
                       res.get("read", "").split("|")))
        conv = lambda v: v == "true" if v in ("true", "false") else (float(v) if re.fullmatch(r"-?[\d.]+", v or "x") else v)
        applied = {kk: conv(got.get(p["key"])) for kk, (_, p, _) in pl["map"].items()}
        how = (f"doc.rasterEffectSettings: {sets} then g.applyEffect('{blur}') on group PGD_TEST so a raster effect "
               "shows the settings (the settings draw nothing on their own)")
        return applied, pl["dropped"], how, pl["notes"], res.get("_dialogs"), ref
    ap = APPLY[target] % json.dumps(pl["xml"])
    on = ("group PGD_TEST" if target == "group" else "each item of group PGD_TEST") + \
        ("" if plate == "vector" else f" on the {plate} plate ({src_file.name})")
    if not (pl["patch"] or pl["chain_first"]):
        res, err = call(base, ap, png=png, save=fa)
        if err:
            raise RuntimeError(err)
        ps = read_ps(fa)
        how = f"applyEffect('{pl['xml']}') on {on}"
    else:
        res, err = call(base, ap + "g.hidden=true;", save=fa)
        if err:
            raise RuntimeError(err)
        ps = read_ps(fa)
        bl = blocks(ps, pl["le"])
        if not bl:
            raise RuntimeError(f"applyEffect stored no {pl['le']} block to replace")
        how = f"applyEffect('{pl['xml']}') on {on}; saved"
        if pl["patch"]:
            pl["map_keys_simple"] = [p["key"] for kk, (kind, p, v) in pl["map"].items() if kind == "simple"]
            nb = patched_block(pl)
            for s, e in reversed(bl):
                ps = ps[:s] + nb + ps[e:]
            written = sorted(set(pl["bin"]) | set(pl["fill"]) | set(pl["text"]) | set(pl["map_keys_simple"]))
            how += (f", the effect's dictionary replaced by the one Illustrator's {it['name']} dialog stores (probe file) "
                    f"with {', '.join(repr(x) for x in written) or 'no demo key'}"
                    f"{' + PrevDres ' + str(RES) if 'PrevDres' in nb else ''} written in")
        if pl["chain_first"] and target == "group":
            ps, moved = chain_first(ps, pl["le"])
            if not moved:
                raise RuntimeError(f"no {pl['le']} in an art-style chain to move ahead of the fill/stroke stack")
            how += (", the effect moved to the head of the group's appearance chain (ahead of its fill/stroke stack, "
                    "where the Effect menu puts it)")
        fp.write_bytes(ps.encode("latin-1"))
        res2, err = call(fp, RERENDER, png=png, save=fr)
        if err:
            raise RuntimeError(err)
        res.setdefault("_dialogs", []).extend(res2.get("_dialogs", []))
        ps = read_ps(fr)
        how += ", reopened as plain PostScript .ai, re-rendered"
    applied, dropped, found = read_back(pl, ps)
    notes = list(pl["notes"])
    if not found:
        notes.append(f"no {pl['le']} block in the saved file")
    notes += mismatches(pl, applied)
    for f in (fa, fp, fr):
        f.unlink(missing_ok=True)
    return applied, sorted(set(pl["dropped"]) | set(dropped)), how, notes, res.get("_dialogs"), ref


def render_blend(ctx, card, png):
    it = ctx.harvest["ai_blend_mode"][card["id"]]
    mode = (it.get("invoke") or {}).get("ai_dom", "").split("=")[-1].strip() or f"BlendModes.{card['id']}"
    res, err = call(BASE, BLEND % {"mode": mode}, png=png)
    if err:
        raise RuntimeError(err)
    dropped = sorted((card.get("demo_settings") or {}).keys())
    return ({"blendingMode": res.get("read")}, dropped,
            f"rect.blendingMode = {mode} on a #FF00C8 -> #00E5FF linear gradient rectangle over group PGD_TEST's bounds",
            [] if res.get("read") == mode else [f"read back {res.get('read')}"], res.get("_dialogs"),
            GAL / "ai_blend_mode" / "ref.png")


# ---------------------------------------------------------------- state / main
class State:
    def __init__(self, kind):
        self.dir = GAL / kind
        self.dir.mkdir(parents=True, exist_ok=True)
        rd = lambda n, d: json.loads((self.dir / n).read_text("utf-8")) if (self.dir / n).exists() else d
        self.index = {r["id"]: r for r in rd("index.json", [])}
        self.failed = rd("failed.json", {})
        self.nr = rd("not_rendered.json", {})

    def forget(self, iid):
        self.index.pop(iid, None), self.failed.pop(iid, None), self.nr.pop(iid, None)

    def save(self):
        for n, v in (("index.json", list(self.index.values())), ("failed.json", self.failed),
                     ("not_rendered.json", self.nr)):
            tmp = self.dir / (n + ".tmp")
            tmp.write_text(json.dumps(v, indent=1, ensure_ascii=False), "utf-8")
            tmp.replace(self.dir / n)


def cards_of(kind):
    out = []
    for f in sorted((ROOT / "cards").glob(f"{kind}_*.json")):
        out += json.loads(f.read_text("utf-8"))["cards"]
    return out


def refs():
    r2 = GAL / "ai_blend_mode" / "ref.png"
    for plate, (_, base, name) in PLATES.items():
        r1 = GAL / "ai_effect" / name
        r1.parent.mkdir(parents=True, exist_ok=True)
        if not r1.exists():
            _, err = call(base, "", png=r1)
            print("ref ai_effect", plate, err or "ok", flush=True)
    r2.parent.mkdir(parents=True, exist_ok=True)
    if not r2.exists():
        _, err = call(BASE, BLEND % {"mode": "BlendModes.NORMAL"}, png=r2)
        print("ref ai_blend_mode", err or "ok", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=KINDS, action="append")
    ap.add_argument("--ids", help="file: json list or one card id per line; those cards are re-rendered")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--rerender", action="store_true", help="redo every card, existing PNGs included")
    ap.add_argument("--batch", type=int, default=8, help="cards between commit-headroom checks")
    a = ap.parse_args(argv)
    ids = None
    if a.ids:
        t = Path(a.ids).read_text("utf-8").strip()
        ids = set(json.loads(t) if t.startswith("[") else [l.strip() for l in t.splitlines() if l.strip()])
    (WORK / "renderer.pid").write_text(str(__import__("os").getpid()))  # other agents: stop this run by PID only
    start_app()
    cleanup()
    for plate in PLATES:
        make_base(plate)
    refs()
    ctx = Ctx()
    n_done, t0 = 0, time.time()
    for kind in a.kind or KINDS:
        st = State(kind)
        todo = []
        for c in cards_of(kind):
            if ids is not None and c["id"] not in ids:
                continue
            png = st.dir / f"{key(c['id'])}.png"
            if ids is None and not a.rerender and (c["id"] in st.nr or (png.exists() and c["id"] in st.index)
                                                   or st.failed.get(c["id"], "").startswith(CRASH)):
                continue  # a card that crashed the app is retried only through --ids
            todo.append(c)
        if a.limit:
            todo = todo[:a.limit]
        print(f"{kind}: {len(todo)} to render", flush=True)
        for i, c in enumerate(todo):
            if i % a.batch == 0:
                h = ensure_room()
                print(f"  commit headroom {h if h is None else round(h, 1)} GB", flush=True)
            st.forget(c["id"])
            if c.get("status") != "current" or c.get("scriptable") == "no":
                st.nr[c["id"]] = (f"status {c.get('status')}" if c.get("status") != "current" else "scriptable: no") + \
                    (": " + (ctx.harvest[kind].get(c["id"], {}).get("error") or "")).rstrip(": ")
                st.save()
                continue
            if not find_pid():  # a crash (Plastic Wrap, 10-07) turned every later card into 'Operation unavailable'
                print("  Illustrator is not running: starting it", flush=True)
                start_app()
            k = key(c["id"])
            png = st.dir / f"{k}.png"
            png.unlink(missing_ok=True)
            t1 = time.time()
            try:
                applied, dropped, how, notes, dlg, ref = (render_effect if kind == "ai_effect" else render_blend)(ctx, c, png)
                if not png.exists():
                    raise RuntimeError("export wrote no PNG")
                with Image.open(png) as im:
                    if im.size != (960, 540):
                        raise RuntimeError(f"PNG is {im.size}, not 960x540")
                if blank(png):
                    raise RuntimeError("blank frame (pixel stddev < 2): the effect left nothing visible")
                row = {"key": k, "id": c["id"], "name": c["name"], "applied": applied, "dropped": dropped, "how": how,
                       "diff_vs_ref": frame_diff(png, ref)}
                if kind == "ai_effect" and row["diff_vs_ref"] == 0.0:
                    raise RuntimeError(f"frame identical to the plate: the scripted apply drew nothing ({how[:300]})")
                if notes:
                    row["note"] = "; ".join(notes)
                if dlg:
                    row["dialogs"] = dlg
                st.index[c["id"]] = row
                print(f"  {c['name'][:34]:34} {k} {time.time() - t1:5.1f}s diff {row['diff_vs_ref']} "
                      f"dropped {dropped} {('| ' + row.get('note', ''))[:160]}", flush=True)
            except Exception as ex:  # noqa: BLE001
                st.failed[c["id"]] = ((CRASH + ": ") if not find_pid() else "") + str(ex)[:500]
                png.unlink(missing_ok=True)  # gallery frames = index rows only
                print(f"  FAIL {c['name']} {k}: {str(ex)[:300]}", flush=True)
            n_done += 1
            if n_done % 3 == 0:
                st.save()
        st.save()
        print(f"{kind}: index {len(st.index)} failed {len(st.failed)} not_rendered {len(st.nr)} / {len(cards_of(kind))}",
              flush=True)
    print(f"done in {time.time() - t0:.0f}s", flush=True)


def selftest():
    bb = bytes.fromhex("000000014745666b000020004745667453746d704c674472000000006c6f6e6700000019536d7468000000006c6f6e6700000005")
    assert desc_get(bb) == {"GEfk": "Stmp", "LgDr": 25, "Smth": 5}
    p, hit = desc_patch(bb, {"LgDr": 7, "GEfk": "Ct"})
    assert desc_get(p) == {"GEfk": "Ct  ", "LgDr": 7, "Smth": 5} and hit == {"LgDr", "GEfk"}
    nested = bytes.fromhex("00000001436c7220800000005247424300000040000000015264202000000000646f75620000000000000000"
                           "47726e2000000000646f75620000000000000000426c202000000000646f7562406fe00000000000")
    assert desc_get(nested) == {"Clr ": {"Rd  ": 0.0, "Grn ": 0.0, "Bl  ": 255.0}}
    assert desc_get(desc_patch(nested, {"Clr ": {"Grn ": 229}})[0])["Clr "]["Grn "] == 229
    blk = ("/BasicFilter :\r\n(X) 1 0 /Filter ,\r\n/Dictionary : /NotRecorded ,\r\n300 /Int (PrevDres) ,\r\n"
           "/FillStyle : 0 O\r\n0 0 0 0 1 1 1 Xa\r\n0 1 0 0 0 Xy\r\n/Def ; \r\n (gclr) ,\r\n"
           "/Binary : /ASCII85Decode ,\r\n%" + base64.a85encode(bb).decode() + "~>\r\n; (data) ,\r\n; /Dict ;")
    assert blocks(blk, "X") == [(0, len(blk))]
    assert desc_get(get_data(put_data(blk, p)))["LgDr"] == 7
    b79 = bytes(range(1, 64))  # encodes to 79 chars: '~>' would straddle the 80-char line break
    assert len(base64.a85encode(b79)) == 79 and get_data(put_data(blk, b79)) == b79
    sb = set_simple(blk, "PrevDres", "Int", 150)
    assert "150 /Int (PrevDres) ," in sb and "300 /Int (PrevDres)" not in sb and sb.count("PrevDres") == 1
    assert "2 /Int (new) ," in set_simple(blk, "new", "Int", 2)
    assert fill_rgb(set_fill(blk, "gclr", "#00E5FF"), "gclr") == "#00E5FF"
    assert key("a") == hashlib.sha1(b"a").hexdigest()[:12]
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        Image.new("RGB", (960, 540), "white").save(f"{t}/w.png")
        im = Image.new("RGB", (960, 540), "white"); im.paste((30, 90, 255), (300, 100, 600, 400)); im.save(f"{t}/s.png")
        assert blank(f"{t}/w.png") and not blank(f"{t}/s.png")
    print("selftest ok")


if __name__ == "__main__":
    selftest() if sys.argv[1:] == ["selftest"] else main()
