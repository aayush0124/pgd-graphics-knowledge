"""PGD / Illustrator: render the ai_preset gallery -> gallery/ai_preset/<key>.png + index.json / failed.json /
not_renderable.json

    python preset_gallery.py                     # every category, biggest first, resumable
    python preset_gallery.py --cat Symbol --limit 20
    python preset_gallery.py --retry-failed      # drop failed.json entries first
    python preset_gallery.py --ids ids.json      # re-render just these item ids (json list or one per line)

key = sha1(item id)[:12]. Every harvested item ends in exactly one of the three json files. App renders run in
documents this script opens or creates (library .ai files opened with app.open, a scratch doc for tracing) and close
them DONOTSAVECHANGES. Each preset is built on its own top layer (every other layer hidden), the artboard is fitted to
the result, exported PNG24 with transparency to work/ai/gallery/raw/<key>.png, then cropped to the visible pixels and
fitted into 320x320 on a neutral background here. No global input: dialogs are answered by window handle (js_watch).
"""
import argparse, hashlib, json, math, re, struct, sys, time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import aicom  # noqa: E402
from aicom import js_watch  # noqa: E402

_PID = aicom.ai_pid()
aicom.ai_pid = lambda: _PID  # js_watch polls dialogs 4x/s; one tasklist spawn per poll ended in a MemoryError
# splash windows stay "visible" after start-up: not dialogs (js_watch answered and screenshotted them)
aicom.PANELS = aicom.PANELS + ("com.adobe.AdobeSplashKit.TextWindowClass", "com.adobe.AdobeSplashKit.GraphicWindowClass")

ROOT = HERE.parents[1]
HARVEST = ROOT / "harvest" / "ai" / "ai_preset.json"
OUT = ROOT / "gallery" / "ai_preset"
WORK = ROOT / "work" / "ai" / "gallery"
RAW = WORK / "raw"
TRACE_IMG = ROOT / "work" / "ai" / "presets_stage" / "pgd_ai_trace_plate.png"  # test photo at 480x270
SIZE = 320
GREY = (236, 236, 236)

NOT_VISUAL = {
    "Action": "Action: a recorded command sequence, not a look; its effect depends on the art it runs on",
    "Script": "Script: a .jsx program, nothing to draw",
    "Workspace": "Workspace: a panel layout of the application UI, not artwork",
    "Save for Web optimize preset": "Save for Web optimize preset: export compression settings, no artwork",
    "Save for Web color table": "Save for Web color table: an export indexing palette (listed as non-visual Save for Web settings)",
    "PDF preset": "PDF preset: PDF export settings, no artwork",
    "New document profile": "New document profile: document size / colour mode defaults, no artwork",
    "Transparency flattener preset": "Transparency flattener preset: output flattening settings, no artwork",
    "Print preset": "Print preset: print settings, no artwork",
    "Toolbar": "Toolbar: a tools panel layout, not artwork",
    "Keyboard shortcut set": "Keyboard shortcut set: key bindings, not artwork",
    "3D material (internal)": "internal material resource used by Illustrator's own icon renderer; not offered to the user, nothing to apply",
    "Bevel (3D Classic)": ("3D Classic stores the chosen bevel as path art inside the effect dictionary (bevelArt, seen in "
                           "Graphic Styles/3D Effects.ai saved uncompressed); applyEffect's LiveEffect XML takes only scalar "
                           "values (R/I/B/S), so a named bevel cannot be applied by script"),
}


def key(iid):
    return hashlib.sha1(iid.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- state
class State:
    def __init__(self, retry_failed=False):
        OUT.mkdir(parents=True, exist_ok=True)
        RAW.mkdir(parents=True, exist_ok=True)
        rd = lambda n, d: json.loads((OUT / n).read_text(encoding="utf-8")) if (OUT / n).exists() else d
        self.index = {r["id"]: r for r in rd("index.json", [])}
        self.failed = {} if retry_failed else rd("failed.json", {})
        self.nr = rd("not_renderable.json", {})
        for iid in [i for i, r in self.index.items() if not (OUT / f"{r['key']}.png").exists()]:
            del self.index[iid]  # an index row whose PNG vanished is redone

    def done(self, it):
        return it["id"] in self.index or it["id"] in self.failed or it["id"] in self.nr \
            or (OUT / f"{key(it['id'])}.png").exists() and it["id"] in self.index

    def put(self, it, img, how):
        k = key(it["id"])
        img.save(OUT / f"{k}.png")
        self.failed.pop(it["id"], None)
        self.index[it["id"]] = {"key": k, "id": it["id"], "name": it["name"], "category": it["category"], "how": how}

    def fail(self, it, err):
        self.index.pop(it["id"], None)
        self.failed[it["id"]] = str(err)[:400]

    def not_renderable(self, it, reason):
        self.nr[it["id"]] = reason

    def save(self):
        for n, v in (("index.json", list(self.index.values())), ("failed.json", self.failed),
                     ("not_renderable.json", self.nr)):
            tmp = OUT / (n + ".tmp")
            tmp.write_text(json.dumps(v, indent=1, ensure_ascii=False), "utf-8")
            tmp.replace(OUT / n)


# ---------------------------------------------------------------- image helpers
def lum(px):
    return 0.299 * px[0] + 0.587 * px[1] + 0.114 * px[2]


CHECK = ((102, 102, 102), (138, 138, 138), 10)  # mid-grey checker: white paint reads white, holes read as checker
WHITE_MIN = 0.005  # share of visible pixels that are near-white paint above which white / pale art gets the checker


def checker():
    a, b, c = CHECK
    im = Image.new("RGBA", (SIZE, SIZE), a + (255,))
    d = ImageDraw.Draw(im)
    for y in range(0, SIZE, c):
        for x in range((y // c) % 2 * c, SIZE, 2 * c):
            d.rectangle([x, y, x + c - 1, y + c - 1], fill=b + (255,))
    return im


def fit(im, bg, pad=14):
    """RGBA content -> SIZE x SIZE on bg (an RGB tuple or a SIZE x SIZE RGBA image), scaled (premultiplied, no dark
    fringes) to fill the box minus pad."""
    s = (SIZE - 2 * pad) / max(im.size)
    w, h = max(1, round(im.width * s)), max(1, round(im.height * s))
    im = im.convert("RGBa").resize((w, h), Image.LANCZOS).convert("RGBA")
    canvas = bg.copy() if isinstance(bg, Image.Image) else Image.new("RGBA", (SIZE, SIZE), bg + (255,))
    canvas.alpha_composite(im, ((SIZE - w) // 2, (SIZE - h) // 2))
    return canvas.convert("RGB")


def white_share(im):
    """near-white paint (every channel >= 230, alpha >= 64: thin antialiased white lines count) / visible pixels"""
    r, g, b, a = im.split()
    vis = a.point(lambda v: 255 if v >= 64 else 0)
    light = ImageChops.darker(ImageChops.darker(r, g), b).point(lambda v: 255 if v >= 230 else 0)
    n = vis.histogram()[255]
    return ImageChops.multiply(light, vis).histogram()[255] / n if n else 0.0


def finish(raw, white=False):
    """raw transparent export -> (thumbnail, note, backing). Raises on a blank render.
    Backing, decided from the raw alpha export: art with near-white paint (white_share >= WHITE_MIN) or a pale average
    goes on a mid-grey checker, so white paint and holes stay distinct (on a white plate both vanished); other art on
    white (white=True: symbols) or light grey."""
    im = Image.open(raw).convert("RGBA")
    a = im.getchannel("A").point(lambda v: 255 if v > 10 else 0)
    bb = a.getbbox()
    if not bb:
        raise ValueError("rendered blank: nothing visible in the export")
    note = "clipped" if (bb[0] == 0 or bb[1] == 0 or bb[2] == im.width or bb[3] == im.height) else ""
    im = im.crop(bb)
    small = im.copy()
    small.thumbnail((96, 96))
    px = [p for p in small.get_flattened_data() if p[3] > 128] if hasattr(small, "get_flattened_data") \
        else [p for p in small.getdata() if p[3] > 128]
    m = sum(lum(p) for p in px) / len(px) if px else 0
    if white_share(im) >= WHITE_MIN or m >= (225 if white else 205):
        return fit(im, checker()), note, "mid-grey checker (white paint shows white, holes show the checker)"
    return (fit(im, (255, 255, 255)), note, "white") if white else (fit(im, GREY), note, "light grey")


# ---------------------------------------------------------------- swatch files (no app)
def lab2rgb(L, a, b):
    y = (L + 16) / 116
    x, z = a / 500 + y, y - b / 200
    f = lambda t: t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787
    X, Y, Z = 0.95047 * f(x), f(y), 1.08883 * f(z)
    r = 3.2406 * X - 1.5372 * Y - 0.4986 * Z
    g = -0.9689 * X + 1.8758 * Y + 0.0415 * Z
    bl = 0.0557 * X - 0.2040 * Y + 1.0570 * Z
    gam = lambda c: 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return tuple(max(0, min(255, round(255 * gam(c)))) for c in (r, g, bl))


def cmyk2rgb(c, m, y, k):
    return tuple(round(255 * (1 - v) * (1 - k)) for v in (c, m, y))


def swatch_colors(path):
    """-> [(r,g,b)] in file order, from .ase / .acb / .acbl"""
    p = Path(path)
    b = p.read_bytes()
    out = []
    if p.suffix == ".ase":
        from ai_presets import parse_ase
        for s in parse_ase(b):
            v = s["values"]
            out.append({"RGB": lambda: tuple(round(255 * x) for x in v),
                        "CMYK": lambda: cmyk2rgb(*v),
                        "LAB": lambda: lab2rgb(v[0] * 100, v[1], v[2]),
                        "Gray": lambda: (round(255 * v[0]),) * 3}[s["model"]]())
    elif p.suffix == ".acb":
        from ai_presets import parse_acb
        r = parse_acb(b)
        for c in r["colors"]:
            v = c["values"]
            if r["model"] == "RGB":
                out.append(tuple(v))
            elif r["model"] == "CMYK":  # stored inverted: 255 = 0 % ink
                out.append(cmyk2rgb(*[(255 - x) / 255 for x in v]))
            else:
                out.append(lab2rgb(v[0] * 100 / 255, v[1] - 128, v[2] - 128))
    else:  # .acbl: <Format ColorSpace=... Encoding=...> + <Sp N=..><C>v v v</C></Sp>
        t = b.decode("utf-8", "replace")
        cs = re.search(r'ColorSpace="([^"]+)"', t).group(1)
        enc = (re.search(r'<Format [^>]*Encoding="([^"]+)"', t) or [None, "Float"])[1]
        div = {"Float": 1.0, "Int8": 255.0}.get(enc)  # legacy HKS books: Int8 = 0-255 per channel
        if div is None or (cs == "Lab" and div != 1.0):
            raise ValueError(f"unsupported .acbl encoding {enc} for {cs}")
        for vals in re.findall(r"<Sp [^>]*>.*?<C>([^<]*)</C>", t, re.S):
            v = [float(x) / div for x in vals.split()]
            out.append({"CMYK": lambda: cmyk2rgb(*v), "RGB": lambda: tuple(round(255 * x) for x in v),
                        "Lab": lambda: lab2rgb(*v)}[cs]())
    return out


def strip(colors, cap=400):
    """swatch strip: one row for a short library, a near-square grid for long ones (evenly sampled above cap)."""
    if not colors:
        raise ValueError("no colours parsed from the library file")
    if len(colors) > cap:
        colors = [colors[int(i * len(colors) / cap)] for i in range(cap)]
    n = len(colors)
    cols = n if n <= 8 else math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    pad, gap = 14, 2 if n <= 100 else 1
    cell = (SIZE - 2 * pad - gap * (max(cols, rows) - 1)) / max(cols, rows)
    im = Image.new("RGB", (SIZE, SIZE), GREY)
    d = ImageDraw.Draw(im)
    w, h = cols * cell + (cols - 1) * gap, rows * cell + (rows - 1) * gap
    x0, y0 = (SIZE - w) / 2, (SIZE - h) / 2
    for i, c in enumerate(colors):
        x, y = x0 + (i % cols) * (cell + gap), y0 + (i // cols) * (cell + gap)
        d.rectangle([round(x), round(y), round(x + cell) - 1, round(y + cell) - 1], fill=c)
    return im


# ---------------------------------------------------------------- width profiles (no app)
def width_profile(it):
    """outline of a 400 pt stroke, 60 pt at full width, with the profile's width points (monotone cubic between them)"""
    P = {p["key"]: p["default"] for p in it.get("params") or []}
    xs = P["VariableWidth_Distances"]
    if "VariableWidth_Widths" in P:  # symmetric profile: total width, half on each side
        lw = rw = [v / 2 for v in P["VariableWidth_Widths"]]
    else:  # asymmetric profile: one width per side
        lw, rw = P["VariableWidth_LeftWidths"], P["VariableWidth_RightWidths"]
    n = len(xs)

    def interp(ws):
        sl = [(ws[i + 1] - ws[i]) / ((xs[i + 1] - xs[i]) or 1e-9) for i in range(n - 1)]
        m = [sl[0]] + [0 if sl[i - 1] * sl[i] <= 0 else (sl[i - 1] + sl[i]) / 2 for i in range(1, n - 1)] + [sl[-1]]

        def w(t):
            for i in range(n - 1):
                if xs[i] <= t <= xs[i + 1]:
                    hh = xs[i + 1] - xs[i] or 1e-9
                    u = (t - xs[i]) / hh
                    h00, h10, h01, h11 = 2*u**3 - 3*u**2 + 1, u**3 - 2*u**2 + u, -2*u**3 + 3*u**2, u**3 - u**2
                    return max(0, h00 * ws[i] + h10 * hh * m[i] + h01 * ws[i + 1] + h11 * hh * m[i + 1])
            return 0
        return w
    wl, wr = interp(lw), interp(rw)
    S = 4  # supersample
    L, H = 280 * S, 42 * S
    im = Image.new("RGB", (SIZE * S, SIZE * S), GREY)
    d = ImageDraw.Draw(im)
    x0, cy = (SIZE * S - L) / 2, SIZE * S / 2
    ts = [i / 400 for i in range(401)]
    top = [(x0 + t * L, cy - wl(t) * H) for t in ts]
    bot = [(x0 + t * L, cy + wr(t) * H) for t in reversed(ts)]
    d.polygon(top + bot, fill=(30, 30, 30))
    d.line([(x0, cy), (x0 + L, cy)], fill=(0, 160, 255), width=S)  # the path the profile sits on
    return im.resize((SIZE, SIZE), Image.LANCZOS)


# ---------------------------------------------------------------- app renders
JS_LIB = r'''
(function(){
var A=%(args)s, out={}, uil=app.userInteractionLevel;
app.userInteractionLevel=UserInteractionLevel.DONTDISPLAYALERTS;
function K(c,r,g,b){var x=new RGBColor();x.red=r;x.green=g;x.blue=b;return x;}
function UB(a){var b=null;for(var i=0;i<a.length;i++){var v=a[i].visibleBounds;
  if(!b)b=[v[0],v[1],v[2],v[3]];else{b[0]=Math.min(b[0],v[0]);b[1]=Math.max(b[1],v[1]);b[2]=Math.max(b[2],v[2]);b[3]=Math.min(b[3],v[3]);}}return b;}
function sp(p,a,l,r){var q=p.pathPoints.add();q.anchor=a;q.leftDirection=l;q.rightDirection=r;q.pointType=PointType.SMOOTH;}
function scurve(L,cx,cy,k){var p=L.pathItems.add();
  sp(p,[cx-150*k,cy],[cx-150*k,cy],[cx-100*k,cy+95*k]);
  sp(p,[cx,cy],[cx-50*k,cy+95*k],[cx+50*k,cy-95*k]);
  sp(p,[cx+150*k,cy],[cx+100*k,cy-95*k],[cx+150*k,cy]);
  p.closed=false;p.filled=false;p.stroked=true;p.strokeWidth=1;p.strokeColor=K(0,0,0,0);return p;}
var BUILD={
 Symbol:function(d,L,n,cx,cy){var si=L.symbolItems.add(d.symbols.getByName(n));
   var f=300/Math.max(si.width,si.height,0.01);si.resize(f*100,f*100);
   si.position=[cx-si.width/2,cy+si.height/2];return [si];},
 Brush:function(d,L,n,cx,cy){var p=scurve(L,cx,cy,1);d.brushes.getByName(n).applyTo(p);return [p];},
 "Graphic Style":function(d,L,n,cx,cy){var gs=d.graphicStyles.getByName(n);
   var st=L.pathItems.star(cx,cy+70,95,42,5);st.filled=true;st.fillColor=K(0,70,140,210);st.stroked=false;
   var t=L.textFrames.add();t.contents="PGD";var ca=t.textRange.characterAttributes;ca.size=120;  // default font: a textFonts lookup cost ~20 s per call
   t.position=[cx-t.width/2,cy-40];
   var g=t.createOutline(),parts=[st];   // a style on a live text frame lost to the character fill, or vanished (3D)
   for(var i=0;i<g.pageItems.length;i++){var q=g.pageItems[i];parts.push(q);
     if(A.additive){try{(q.typename=='CompoundPathItem'?q.pathItems[0]:q).fillColor=K(0,70,140,210);}catch(e){}}}
   for(var i=0;i<parts.length;i++){if(A.additive)gs.mergeTo(parts[i]);else gs.applyTo(parts[i]);}
   return [st,g];},
 Arrowhead:function(d,L,n,cx,cy){
   var sym=d.symbols.getByName(n),e=L.symbolItems.add(sym),s=L.symbolItems.add(sym);
   var f=120/Math.max(e.width,0.01)*100;e.resize(f,f);s.resize(f,f);s.rotate(180);var H=e.width*1.6;
   e.position=[cx+H-e.width,cy+e.height/2];s.position=[cx-H,cy+s.height/2];
   var p=L.pathItems.add();p.setEntirePath([[cx-H,cy],[cx+H,cy]]);p.filled=false;p.stroked=true;
   p.strokeWidth=6;p.strokeColor=K(0,0,0,0);p.move(L,ElementPlacement.PLACEATEND);
   return [p,e,s];},
 Swatches:function(d,L,n,cx,cy){var a=[],sw=d.swatches;
   for(var i=0;i<sw.length;i++){var c=sw[i].color.typename;if(c=='NoColor'||(c=='SpotColor'&&sw[i].color.spot.colorType==ColorModel.REGISTRATION))continue;a.push(sw[i]);}
   if(!a.length)throw new Error("no drawable swatches");
   var N=a.length,cols=N<=8?N:Math.ceil(Math.sqrt(N)),c=24,g=3,res=[];
   for(var i=0;i<N;i++){var x=cx+(i%%cols)*(c+g),y=cy-Math.floor(i/cols)*(c+g);
     var r=L.pathItems.rectangle(y,x,c,c);r.stroked=false;r.filled=true;r.fillColor=a[i].color;res.push(r);}
   return res;}
};
try{
 var f=File(A.lib),d=null;
 for(var i=0;i<app.documents.length;i++){if(app.documents[i].fullName.fsName==f.fsName)d=app.documents[i];}
 if(d&&!A.ours)throw new Error("library already open in a document this script did not open");
 if(!d){d=app.open(f);out._opened=1;}
 if(A.close_only){d.close(SaveOptions.DONOTSAVECHANGES);app.userInteractionLevel=uil;return '{"closed":1}';}
 app.activeDocument=d;
 var L=null;for(var i=0;i<d.layers.length;i++)if(d.layers[i].name=='pgd_gallery')L=d.layers[i];
 if(!L){L=d.layers.add();L.name='pgd_gallery';}
 for(var i=0;i<d.layers.length;i++)if(d.layers[i].name!='pgd_gallery'){try{d.layers[i].visible=false;}catch(e){}}
 L.visible=true;L.locked=false;
 d.artboards.setActiveArtboardIndex(0);var ab=d.artboards[0],R0=ab.artboardRect;
 var cx=(R0[0]+R0[2])/2,cy=(R0[1]+R0[3])/2;
 for(var j=0;j<A.names.length;j++){var k=A.keys[j];
  try{
   $.hiresTimer;while(L.pageItems.length)L.pageItems[0].remove();
   var it=BUILD[A.kind](d,L,A.names[j],cx,cy);
   var b=UB(it),w=b[2]-b[0],h=b[1]-b[3],mx=Math.max(w,h,1),m=mx*A.margin+12;
   ab.artboardRect=[b[0]-m,b[1]+m,b[2]+m,b[3]-m];
   var s=Math.min(776,Math.max(5,A.px/(mx+2*m)*100));
   var o=new ExportOptionsPNG24();o.artBoardClipping=true;o.antiAliasing=true;o.transparency=true;o.horizontalScale=s;o.verticalScale=s;
   var t0=$.hiresTimer, fo=new File(File(A.raw+'/'+k+'.png').fsName), tb=0;
   if(fo.exists)fo.remove();fo=new File(fo.fsName);   // a stale raw from an earlier build must not pass the check below
   for(var tries=0;tries<3&&!fo.exists;tries++){d.exportFile(fo,ExportType.PNG24,o);fo=new File(fo.fsName);}
   out[k]=(fo.exists?'ok ':'ERR export wrote no file ')+Math.round(w)+'x'+Math.round(h)+' t'+Math.round($.hiresTimer/1000)+'ms';
  }catch(e){out[k]='ERR '+String(e);}
 }
 try{while(L.pageItems.length)L.pageItems[0].remove();ab.artboardRect=R0;}catch(e){}
}catch(e){out._err=String(e);}
app.userInteractionLevel=uil;
var s=[];for(var q in out)s.push('"'+q+'":"'+String(out[q]).replace(/\\/g,'/').replace(/"/g,"'").replace(/[\r\n]/g,' ')+'"');
return '{'+s.join(',')+'}';
})();
'''

JS_TRACE = r'''
(function(){
var A=%(args)s, out={}, uil=app.userInteractionLevel, d=null;
app.userInteractionLevel=UserInteractionLevel.DONTDISPLAYALERTS;
try{
 d=app.documents.add(DocumentColorSpace.RGB,480,270);
 var ab=d.artboards[0],R=ab.artboardRect;
 for(var j=0;j<A.names.length;j++){var k=A.keys[j];
  try{
   var pl=d.placedItems.add();pl.file=File(A.img);pl.position=[R[0],R[1]];
   var t=pl.trace();t.tracing.tracingOptions.loadFromPreset(A.names[j]);app.redraw();
   var o=new ExportOptionsPNG24();o.artBoardClipping=true;o.antiAliasing=true;o.transparency=true;o.horizontalScale=150;o.verticalScale=150;
   d.exportFile(new File(File(A.raw+'/'+k+'.png').fsName),ExportType.PNG24,o);
   out[k]='ok';try{t.remove();}catch(e){}
  }catch(e){out[k]='ERR '+String(e);}
 }
}catch(e){out._err=String(e);}
try{if(d)d.close(SaveOptions.DONOTSAVECHANGES);}catch(e){out._close=String(e);}
app.userInteractionLevel=uil;
var s=[];for(var q in out)s.push('"'+q+'":"'+String(out[q]).replace(/"/g,"'")+'"');
return '{'+s.join(',')+'}';
})();
'''

HOW = {
    "Symbol": "applied: one instance of the symbol placed from its library and fitted to 300 pt",
    "Brush": "applied: brush applied to a 300 pt S-curve path (1 pt stroke) in its library document",
    "Graphic Style": "applied: graphic style applied (applyTo) to a 5-point star and to each letter of 'PGD' type converted to outlines",
    "Graphic Style additive": ("applied: additive style merged (mergeTo) onto a blue 5-point star and onto each letter of "
                               "'PGD' type converted to outlines, as Alt-click adds it in the Graphic Styles panel"),
    "Arrowhead": ("applied: arrowhead art (the entry's symbol in Arrowheads.ai, scaled to 120 pt wide) placed over both ends of a "
                  "6 pt stroked line, start end mirrored; stroke arrowheads themselves are not exposed to scripting"),
    "Swatches": "swatch strip",
    "Image Trace preset": "applied: test photo (480x270) placed, traced, preset loaded with tracingOptions.loadFromPreset",
}


def run_js(src, timeout):
    r, e, seen = js_watch(src, timeout, key="escape", shot_dir=(WORK / "dialogs").as_posix())
    res = {}
    if r:
        try:
            res = json.loads(r)
        except Exception as ex:  # noqa: BLE001
            e = f"bad result {r[:200]}: {ex}"
    if seen:
        res["_dialogs"] = seen
    return res, e


def lib_kind(it):
    return "Swatches" if it["category"] == "Swatch library" else it["category"]


OPENED = WORK / "opened_libs.json"  # libraries this script opened and has not closed yet (crash recovery)


def mark_open(lib, is_open):
    s = set(json.loads(OPENED.read_text(encoding="utf-8"))) if OPENED.exists() else set()
    (s.add if is_open else s.discard)(lib)
    OPENED.write_text(json.dumps(sorted(s)), encoding="utf-8")


def close_lib(lib):
    res, err = run_js(JS_LIB % {"args": json.dumps({"lib": lib, "ours": True, "close_only": True, "kind": "Symbol",
                                                    "names": [], "keys": [], "raw": "", "margin": 0, "px": 0})}, 60)
    if res.get("closed"):
        mark_open(lib, False)
    else:
        print("  CLOSE FAILED", lib, res, err)


def render_lib(st, lib, items, chunk, margin, white, limit_log=print):
    """all entries of one library .ai file, in chunks, in one opened library document (closed at the end)."""
    kind = lib_kind(items[0])
    opened = False
    try:
        for c0 in range(0, len(items), chunk):
            part = items[c0:c0 + chunk]
            args = {"lib": lib, "kind": kind, "names": [it["name"] for it in part], "keys": [key(it["id"]) for it in part],
                    "raw": RAW.as_posix(), "ours": opened, "margin": margin, "px": 700,
                    "additive": "Additive" in Path(lib).name}
            t1 = time.time()
            res, err = run_js(JS_LIB % {"args": json.dumps(args)}, 60 + 8 * len(part))
            took = time.time() - t1
            if res.get("_opened"):
                opened = True
                mark_open(lib, True)
            if res.get("_err"):
                err = (err or "") + " " + res["_err"]
            for it in part:
                k = key(it["id"])
                raw = RAW / f"{k}.png"
                r = res.get(k)
                if r and r.startswith("ok") and raw.exists():
                    try:
                        img, note, bg = finish(raw, white)
                        st.put(it, img, HOW[kind + (" additive" if args["additive"] and kind == "Graphic Style" else "")]
                               + f", on a {bg} backing" + (" (art reaches the export edge)" if note else ""))
                    except Exception as ex:  # noqa: BLE001
                        st.fail(it, ex)
                else:
                    st.fail(it, (r or "") + (" | " if r and err else "") + (err or "" if not r else ""))
            st.save()
            limit_log(f"  {Path(lib).name} {c0 + len(part)}/{len(items)} {took:.0f}s err={err or ''}"[:300], flush=True)
    finally:
        if opened:
            close_lib(lib)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", action="append")
    ap.add_argument("--limit", type=int, default=0, help="max items per category (sampling)")
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--chunk", type=int, default=12)
    ap.add_argument("--ids", help="file: json list or one item id per line; those items are re-rendered "
                                  "(their old PNG is removed first, so a failed re-render leaves no stale frame)")
    a = ap.parse_args(argv)
    st = State(a.retry_failed)
    if a.ids:
        t = Path(a.ids).read_text("utf-8").strip()
        for iid in (json.loads(t) if t.startswith("[") else [ln.strip() for ln in t.splitlines() if ln.strip()]):
            st.index.pop(iid, None), st.failed.pop(iid, None), st.nr.pop(iid, None)
            (OUT / f"{key(iid)}.png").unlink(missing_ok=True)
    items = json.loads(HARVEST.read_text(encoding="utf-8"))["items"]
    todo = [it for it in items if not st.done(it) and (not a.cat or it["category"] in a.cat)]
    t0 = time.time()
    for lib in (json.loads(OPENED.read_text(encoding="utf-8")) if OPENED.exists() else []):
        print("closing library left open by an earlier run:", lib)
        close_lib(lib)

    # no-app categories first (seconds)
    for it in [i for i in todo if i["category"] in NOT_VISUAL]:
        st.not_renderable(it, NOT_VISUAL[it["category"]])
    for it in [i for i in todo if i["category"].startswith("Swatch library") and not i["id"].endswith(".ai")]:
        try:
            st.put(it, strip(swatch_colors(it["invoke"]["file"])), "swatch strip")
        except Exception as ex:  # noqa: BLE001
            st.fail(it, ex)
    for it in [i for i in todo if i["category"] == "Width profile"]:
        try:
            st.put(it, width_profile(it), "applied: width profile drawn as the outline of a 280 pt stroke from the "
                   "profile's Distances/Widths (variable width is not exposed to scripting); blue line = the path")
        except Exception as ex:  # noqa: BLE001
            st.fail(it, ex)
    for it in [i for i in todo if i["category"] == "3D material (Substance)"]:
        th = (it.get("extra") or {}).get("thumbnail")
        if th and Path(th).exists():
            st.put(it, fit(Image.open(th).convert("RGBA"), GREY, pad=8), "file image")
        else:
            st.fail(it, "no shipped thumbnail")
    st.save()

    # app categories, biggest first; library-based ones grouped by library file
    libcats = ("Symbol", "Brush", "Graphic Style", "Arrowhead", "Swatch library")
    by_cat = {}
    for it in todo:
        if it["category"] in libcats and (it["category"] != "Swatch library" or it["id"].endswith(".ai")):
            by_cat.setdefault(it["category"], {}).setdefault(it["invoke"]["file"], []).append(it)
    for cat in sorted(by_cat, key=lambda c: -sum(len(v) for v in by_cat[c].values())):
        n_left = a.limit or 10 ** 9
        for lib, its in by_cat[cat].items():
            its = [i for i in its if not st.done(i)][:n_left]
            if not its:
                continue
            n_left -= len(its)
            print(f"{cat}: {Path(lib).name} ({len(its)})", flush=True)
            render_lib(st, lib, its, 1 if cat == "Swatch library" else a.chunk,
                       margin={"Brush": 0.5, "Symbol": 0.15}.get(cat, 0.3), white=cat == "Symbol")
            if n_left <= 0:
                break
    tr = [i for i in todo if i["category"] == "Image Trace preset" and not st.done(i)][:a.limit or None]
    if tr:
        res, err = run_js(JS_TRACE % {"args": json.dumps({"names": [i["name"] for i in tr], "keys": [key(i["id"]) for i in tr],
                                                          "img": TRACE_IMG.as_posix(), "raw": RAW.as_posix()})}, 60 + 20 * len(tr))
        for it in tr:
            k = key(it["id"])
            r = res.get(k)
            if r == "ok" and (RAW / f"{k}.png").exists():
                try:
                    img, _, bg = finish(RAW / f"{k}.png")
                    st.put(it, img, HOW["Image Trace preset"] + f", on a {bg} backing")
                except Exception as ex:  # noqa: BLE001
                    st.fail(it, ex)
            else:
                st.fail(it, r or err or res.get("_err") or "no result")
        st.save()
    st.save()
    total = len(items)
    print(f"done in {time.time() - t0:.0f}s: index {len(st.index)} failed {len(st.failed)} "
          f"not_renderable {len(st.nr)} / {total}")


def selftest():
    assert key("a") == hashlib.sha1(b"a").hexdigest()[:12]
    assert lab2rgb(100, 0, 0) == (255, 255, 255) and lab2rgb(0, 0, 0) == (0, 0, 0)
    assert cmyk2rgb(1, 0, 0, 0) == (0, 255, 255)
    im = Image.new("RGBA", (50, 20), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle([10, 5, 30, 12], fill=(200, 0, 0, 255))
    p = WORK / "_selftest.png"
    WORK.mkdir(parents=True, exist_ok=True)
    im.save(p)
    out, note, _ = finish(p)
    assert out.size == (SIZE, SIZE) and note == "" and out.getpixel((160, 160))[0] > 150
    print("selftest ok")


if __name__ == "__main__":
    selftest() if sys.argv[1:] == ["selftest"] else main()
