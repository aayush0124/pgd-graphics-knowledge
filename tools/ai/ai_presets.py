"""PGD / Illustrator: harvest kind ai_preset -> harvest/ai/ai_preset.json

    python ai_presets.py libs     open every .ai library under Presets/en_US (+ Arrowheads.ai, Bevels.ai) as a document
                                  of our own, read brushes / graphic styles / symbols / swatches, test-apply each entry in
                                  that document, close it unsaved. Checkpoint per library: work/ai/presets_stage/libs.json
    python ai_presets.py app      app-level preset lists (tracing, PDF, print, flattener, new-document profiles) and
                                  their readable settings -> work/ai/presets_stage/app.json
    python ai_presets.py unc      save each brush / graphic-style library as an uncompressed .ai copy into
                                  work/ai/presets_stage/unc (brush tool ids, graphic-style filter stacks come from these)
    python ai_presets.py actions  run each Default Action on two selected rectangles in a scratch document (skips Save For
                                  Web and Revert) -> work/ai/presets_stage/actions_run.json
    python ai_presets.py build    parse the non-.ai preset files (.ase .acb .acbl .aia .irs .act .joboptions workspaces,
                                  width profiles, toolbars, .sbsar 3D materials) and write the harvest file (no app needed)
    python ai_presets.py selftest parsers against a synthetic .ase / .aia snippet

Only documents this script opened are ever closed (by the reference app.open returned), always DONOTSAVECHANGES.
"""
import json, lzma, re, struct, sys, time
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path("C:/Program Files/Adobe/Adobe Illustrator 2026")
PRESETS = ROOT / "Presets/en_US"
RES = ROOT / "Support Files/Required/Resources/en_US"
MATS = ROOT / "Support Files/Contents/Windows/Material-Resources"
WORK = (PGD / "work/ai/presets_stage")
OUT = (PGD / "harvest/ai/ai_preset.json")
LIBS_CKPT = WORK / "libs.json"
APP_CKPT = WORK / "app.json"

# ExtendScript has no JSON object: tiny serializer shipped with every payload
JSER = r'''
function J(v){if(v===null||v===undefined)return 'null';var t=typeof v;
 if(t=='number')return isFinite(v)?String(v):'null'; if(t=='boolean')return String(v);
 if(t=='string'){var s='';for(var i=0;i<v.length;i++){var c=v.charCodeAt(i);
   if(c==34)s+='\\"';else if(c==92)s+='\\\\';else if(c<32||c>126){var h=c.toString(16);while(h.length<4)h='0'+h;s+='\\u'+h;}
   else s+=v.charAt(i);}return '"'+s+'"';}
 if(v instanceof Array){var a=[];for(var i=0;i<v.length;i++)a.push(J(v[i]));return '['+a.join(',')+']';}
 var a=[];for(var k in v)a.push(J(k)+':'+J(v[k]));return '{'+a.join(',')+'}';}
'''

READ_LIB = JSER + r'''
function C(c){var t=c.typename,o={t:t};
 try{
 if(t=='RGBColor')o.v=[c.red,c.green,c.blue];
 else if(t=='CMYKColor')o.v=[c.cyan,c.magenta,c.yellow,c.black];
 else if(t=='GrayColor')o.v=[c.gray];
 else if(t=='LabColor')o.v=[c.l,c.a,c.b];
 else if(t=='SpotColor'){o.spot=c.spot.name;o.tint=c.tint;o.kind=String(c.spot.colorType);o.base=C(c.spot.color);}
 else if(t=='GradientColor'){o.gradient=c.gradient.name;o.gtype=String(c.gradient.type);o.stops=c.gradient.gradientStops.length;}
 else if(t=='PatternColor')o.pattern=c.pattern.name;
 }catch(e){o.err=String(e);}
 return o;}
(function(){
var p=%(path)s, verify=%(verify)s, r={};
var uil=app.userInteractionLevel; var d=null;
try{
 app.userInteractionLevel=UserInteractionLevel.DONTDISPLAYALERTS;
 r.n0=app.documents.length;
 d=app.open(File(File(p).fsName));
 r.doc=d.name; r.mode=String(d.documentColorSpace);
 r.brushes=[];for(var i=0;i<d.brushes.length;i++)r.brushes.push({n:d.brushes[i].name});
 r.styles=[];for(var i=0;i<d.graphicStyles.length;i++)r.styles.push({n:d.graphicStyles[i].name});
 r.symbols=[];for(var i=0;i<d.symbols.length;i++)r.symbols.push({n:d.symbols[i].name});
 r.swatches=[];for(var i=0;i<d.swatches.length;i++){var s=d.swatches[i];r.swatches.push({n:s.name,c:C(s.color)});}
 r.groups=[];for(var i=0;i<d.swatchGroups.length;i++){var g=d.swatchGroups[i],m=[];
   try{var a=g.getAllSwatches();for(var j=0;j<a.length;j++)m.push(a[j].name);}catch(e){m.push('ERR '+String(e));}
   r.groups.push({n:g.name,m:m});}
 if(verify){
  var L=d.layers.add(); L.name='pgd_probe';
  for(var i=0;i<d.brushes.length;i++){var pi=L.pathItems.add();pi.setEntirePath([[0,0],[120,60],[240,0]]);pi.stroked=true;
    try{d.brushes[i].applyTo(pi);r.brushes[i].ok=1;}catch(e){r.brushes[i].err=String(e);} try{pi.remove();}catch(e){}}
  for(var i=0;i<d.graphicStyles.length;i++){var rc=L.pathItems.rectangle(100,0,100,60);
    try{d.graphicStyles[i].applyTo(rc);r.styles[i].ok=1;}catch(e){r.styles[i].err=String(e);} try{rc.remove();}catch(e){}}
  for(var i=0;i<d.symbols.length;i++){
    try{var si=L.symbolItems.add(d.symbols[i]);r.symbols[i].ok=1;r.symbols[i].w=si.width;r.symbols[i].h=si.height;si.remove();}
    catch(e){r.symbols[i].err=String(e);}}
 }
}catch(e){r.err=String(e);}
try{if(d)d.close(SaveOptions.DONOTSAVECHANGES);}catch(e){r.close_err=String(e);}
r.n1=app.documents.length;
app.userInteractionLevel=uil;
return J(r);
})();
'''


def lib_files():
    fs = []
    for sub in ("Brushes", "Graphic Styles", "Symbols", "Swatches"):
        fs += sorted((PRESETS / sub).rglob("*.ai"))
    return fs + [RES / "Arrowheads.ai", RES / "Bevels.ai"]


def rel(p):
    p = Path(p)
    try:
        return p.relative_to(PRESETS).as_posix()
    except ValueError:
        return p.relative_to(ROOT).as_posix()


def load(p, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def libs(only=None, verify=True):
    from aicom import js_watch, js
    ck = load(LIBS_CKPT, {})
    n0 = int(js("app.documents.length", 30))
    for f in lib_files():
        k = rel(f)
        if only and only not in k:
            continue
        if k in ck and "err" not in ck[k] and not only:
            continue
        t0 = time.time()
        src = READ_LIB % {"path": json.dumps(f.as_posix()), "verify": "true" if verify else "false"}
        res, err, seen = js_watch(src, timeout=240, key="enter", shot_dir=str(WORK))
        rec = json.loads(res, strict=False) if res else {"err": err}
        if seen:
            rec["dialogs"] = seen
        rec["secs"] = round(time.time() - t0, 1)
        ck[k] = rec
        save(LIBS_CKPT, ck)
        print(f"{k}: {len(rec.get('brushes', []))}b {len(rec.get('styles', []))}g {len(rec.get('symbols', []))}s "
              f"{len(rec.get('swatches', []))}w {rec['secs']}s {rec.get('err', '')} {seen or ''}", flush=True)
        n = int(js("app.documents.length", 60))
        if n != n0:
            print(f"STOP: document count {n} != {n0} after {k}")
            return 1
    return 0


UNC = WORK / "unc"
SAVE_UNC = r'''(function(){var uil=app.userInteractionLevel,d=null,r='';
try{app.userInteractionLevel=UserInteractionLevel.DONTDISPLAYALERTS;
 d=app.open(File(File(%(src)s).fsName));var o=new IllustratorSaveOptions();o.compressed=false;
 d.saveAs(File(File(%(dst)s).fsName),o);r='ok';}catch(e){r=String(e);}
try{if(d)d.close(SaveOptions.DONOTSAVECHANGES);}catch(e){r+=' close: '+String(e);}
app.userInteractionLevel=uil;return r+' docs='+app.documents.length;})();'''


def unc_path(k):
    return UNC / ("pgd_unc_" + re.sub(r"[^\w.-]+", "_", k))


def save_unc():
    """brush + graphic style libraries -> uncompressed .ai copies in work/ai/presets_stage/unc (text plug-in records)"""
    from aicom import js_watch
    UNC.mkdir(parents=True, exist_ok=True)
    for f in lib_files():
        k = rel(f)
        if not k.startswith(("Brushes/", "Graphic Styles/")) or unc_path(k).exists():
            continue
        res, err, seen = js_watch(SAVE_UNC % {"src": json.dumps(f.as_posix()), "dst": json.dumps(unc_path(k).as_posix())},
                                  timeout=240, key="enter")
        print(k, res, err or "", seen or "", flush=True)
        if not (res or "").endswith("docs=0"):
            return 1
    return 0


def brush_types(t):
    """uncompressed .ai text -> {brush name: (tool id, plug-in display name)} from %AI8_BeginPluginObject records"""
    plug = dict(re.findall(r"^\((Adobe [^)]*Brush Tool)\) \(([^)]*)\) \([^)]*\.aip\)", t, flags=re.M))
    res = {}
    for tool, name in re.findall(r"%AI8_BeginPluginObject\s*\n\(([^)\n]*Brush[^)\n]*)\)\s*\n\(((?:[^()\\\n]|\\.)*)\)", t):
        res[re.sub(r"\\(.)", r"\1", name)] = (tool, plug.get(tool))
    return res


STRUCT_FILTERS = {"Chain Style Filter", "Stack Style Filter", "Conduit Filter", "Blend Style Filter"}


def style_filters(t):
    """uncompressed .ai text -> {graphic style name: [filter names in stored order]} from %AI9_BeginArtStyles"""
    sec = t[t.find("%AI9_BeginArtStyles"):t.find("%AI9_EndArtStyles")]
    res = {}
    for blk in sec.split("/KnownStyle :")[1:]:
        m = re.search(r"\(((?:[^()\\]|\\.)*)\) /Name ,", blk)
        if m:
            res[re.sub(r"\\(.)", r"\1", m.group(1))] = re.findall(r"\(([^()\n]*)\) \d+ \d+ /Filter ,", blk)
    return res


RUN_ACTION = JSER + r'''
(function(){var uil=app.userInteractionLevel,d=null,r={};
function S(){var o={n:d.pageItems.length,sw:d.swatches.length,sy:d.symbols.length,br:d.brushes.length,gs:d.graphicStyles.length,it:[]};
 for(var i=0;i<d.pageItems.length;i++){var p=d.pageItems[i];var q={t:p.typename,b:p.geometricBounds,op:p.opacity};
   try{q.bm=String(p.blendingMode);}catch(e){} o.it.push(q);} return o;}
try{app.userInteractionLevel=UserInteractionLevel.DONTDISPLAYALERTS;
 d=app.documents.add(DocumentColorSpace.RGB,400,300);
 var a=d.pathItems.rectangle(250,50,150,120),b=d.pathItems.rectangle(200,120,150,120);
 a.fillColor=new RGBColor();b.fillColor=new RGBColor();a.selected=true;b.selected=true;
 r.before=S(); app.doScript(%(name)s,%(set)s); r.after=S();
}catch(e){r.err=String(e);}
try{if(d)d.close(SaveOptions.DONOTSAVECHANGES);}catch(e){r.close_err=String(e);}
r.docs=app.documents.length;app.userInteractionLevel=uil;return J(r);})();'''
ACTION_SKIP = {"Revert": "reverts the document to its saved state (a scratch document has none)",
               "Save For Web": "writes an export file and shows the Save for Web dialog"}


def run_actions():
    """run each default action on two selected test rectangles in a scratch document -> work/ai/presets_stage/actions_run.json"""
    from aicom import js_watch
    out = load(WORK / "actions_run.json", {})
    for f in sorted((PRESETS / "Actions").glob("*.aia")):
        setname, acts = parse_aia(f.read_text(encoding="latin-1"))
        for a in acts:
            n = a["name"]
            if n in out:
                continue
            skip = next((v for k, v in ACTION_SKIP.items() if n.startswith(k)), None)
            if skip:
                out[n] = {"skip": skip}
                continue
            res, err, seen = js_watch(RUN_ACTION % {"name": json.dumps(n), "set": json.dumps(setname)}, timeout=90, key="enter")
            r = json.loads(res, strict=False) if res else {"err": err}
            if seen:
                r["dialogs"] = seen
            if "after" in r:
                b, c = r["before"], r["after"]
                diff = [f"{k} {b[k]}->{c[k]}" for k in ("n", "sw", "sy", "br", "gs") if b[k] != c[k]]
                for i, (x, y) in enumerate(zip(b["it"], c["it"])):
                    diff += [f"item{i} {k} {x.get(k)}->{y.get(k)}" for k in ("t", "op", "bm") if x.get(k) != y.get(k)]
                    if [round(v, 1) for v in x["b"]] != [round(v, 1) for v in y["b"]]:
                        diff.append(f"item{i} bounds {[round(v, 1) for v in x['b']]}->{[round(v, 1) for v in y['b']]}")
                r["note"] = ("; ".join(diff) if diff else "no change in item count, opacity, blend mode, bounds or panel counts") + \
                            (f" (dialogs answered with Enter: {seen})" if seen else "")
            out[n] = r
            save(WORK / "actions_run.json", out)
            print(n, r.get("note") or r.get("err"), flush=True)
            if r.get("docs", 0) != 0:
                print("STOP: document left open")
                return 1
    save(WORK / "actions_run.json", out)
    return 0


# ---------------------------------------------------------------- app-level preset lists
LISTS = {"tracing": "tracingPresetsList", "pdf": "PDFPresetsList", "print": "printPresetsList",
         "flattener": "flattenerPresetsList", "startup": "startupPresetsList"}

READ_APP = JSER + r'''
function P(o){var a={},ps=o.reflect.properties;for(var i=0;i<ps.length;i++){var k=ps[i].name;
  if(k=='typename'||k=='parent'||k=='__proto__')continue;
  try{var v=o[k];if(v!==null&&typeof v=='object'&&!(v instanceof Array))v=String(v);a[k]=v;}catch(e){a[k]={err:String(e)};}}
 return a;}
function N(o){var a=[],ps=o.reflect.properties;for(var i=0;i<ps.length;i++)a.push(ps[i].name);return a;}
(function(){
var img=%(img)s, r={lists:{}}, uil=app.userInteractionLevel, d=null;
try{
 app.userInteractionLevel=UserInteractionLevel.DONTDISPLAYALERTS;
 r.n0=app.documents.length;
 var L=%(lists)s;
 for(var k in L){var a=[],s=app[L[k]];for(var i=0;i<s.length;i++)a.push(s[i]);r.lists[k]=a;}
 r.docpreset={};for(var i=0;i<r.lists.startup.length;i++){var n=r.lists.startup[i];
   try{r.docpreset[n]=P(app.getPresetSettings(n));}catch(e){r.docpreset[n]={err:String(e)};}}
 r.optprops={pdf:N(new PDFSaveOptions()),print:N(new PrintOptions()),flat:N(new PrintFlattenerOptions())};
 d=app.documents.add(DocumentColorSpace.RGB,600,400);
 var pl=d.placedItems.add();pl.file=File(File(img).fsName);
 var tr=pl.trace(),to=tr.tracing.tracingOptions;r.trace={};
 for(var i=0;i<r.lists.tracing.length;i++){var n=r.lists.tracing[i];
   try{to.loadFromPreset(n);r.trace[n]=P(to);}catch(e){r.trace[n]={err:String(e)};}}
}catch(e){r.err=String(e);}
try{if(d)d.close(SaveOptions.DONOTSAVECHANGES);}catch(e){r.close_err=String(e);}
r.n1=app.documents.length;app.userInteractionLevel=uil;
return J(r);})();
'''


def app_stage():
    from aicom import js_watch
    from PIL import Image
    img = WORK / "pgd_ai_trace_plate.png"  # the test photo at 1/4 size: tracing every preset stays quick
    if not img.exists():
        Image.open((PGD / "media/test_photo.png").as_posix()).convert("RGB").resize((480, 270)).save(img)
    src = READ_APP % {"img": json.dumps(img.as_posix()), "lists": json.dumps(LISTS)}
    res, err, seen = js_watch(src, timeout=600, key="enter", shot_dir=str(WORK))
    rec = json.loads(res, strict=False) if res else {"err": err}
    rec["dialogs"] = seen
    save(APP_CKPT, rec)
    print({k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in rec.items()})
    return 0 if res else 1


# ---------------------------------------------------------------- file parsers (no app needed)
def parse_ase(b):
    """Adobe Swatch Exchange -> [{name, model, values, type, group}]"""
    assert b[:4] == b"ASEF", "not an ASE file"
    n = struct.unpack(">I", b[8:12])[0]
    pos, out, group = 12, [], ""
    for _ in range(n):
        typ, ln = struct.unpack(">HI", b[pos:pos + 6])
        body = b[pos + 6:pos + 6 + ln]
        pos += 6 + ln
        if typ == 0xC002:
            group = ""
            continue
        nl = struct.unpack(">H", body[:2])[0]
        name = body[2:2 + 2 * nl].decode("utf-16-be").rstrip("\0")
        if typ == 0xC001:
            group = name
            continue
        q = 2 + 2 * nl
        model = body[q:q + 4].decode("ascii").strip()
        k = {"CMYK": 4, "RGB": 3, "LAB": 3, "Gray": 1}[model]
        vals = struct.unpack(">" + "f" * k, body[q + 4:q + 4 + 4 * k])
        ctype = struct.unpack(">H", body[q + 4 + 4 * k:q + 6 + 4 * k])[0]
        out.append({"name": name, "model": model, "values": [round(v, 4) for v in vals],
                    "type": {0: "global", 1: "spot", 2: "normal"}.get(ctype, ctype), "group": group})
    return out


def _ustr(b, pos):
    n = struct.unpack(">I", b[pos:pos + 4])[0]
    return b[pos + 4:pos + 4 + 2 * n].decode("utf-16-be").rstrip("\0"), pos + 4 + 2 * n


def zs(s):
    """'$$$/colorbook/ANPA/title=ANPA Color' -> 'ANPA Color'"""
    return s.split("=", 1)[1] if s.startswith("$$$/") and "=" in s else s


def parse_acb(b):
    """Adobe Color Book -> {title, prefix, postfix, description, model, colors:[{name, code, values}]}"""
    assert b[:4] == b"8BCB", "not an ACB file"
    book_id = struct.unpack(">H", b[6:8])[0]
    pos = 8
    title, pos = _ustr(b, pos)
    prefix, pos = _ustr(b, pos)
    postfix, pos = _ustr(b, pos)
    desc, pos = _ustr(b, pos)
    count, page, sel, space = struct.unpack(">HHHH", b[pos:pos + 8])
    pos += 8
    model, k = {0: ("RGB", 3), 2: ("CMYK", 4), 7: ("Lab", 3)}[space]
    colors = []
    for _ in range(count):
        name, pos = _ustr(b, pos)
        code = b[pos:pos + 6].decode("ascii", "replace").strip()
        vals = list(b[pos + 6:pos + 6 + k])
        pos += 6 + k
        colors.append({"name": zs(name), "code": code, "values": vals})
    tail = b[pos:pos + 8].decode("ascii", "replace")
    return {"title": zs(title), "book_id": book_id, "prefix": zs(prefix), "postfix": zs(postfix),
            "description": zs(desc), "model": model, "page_size": page, "colors": colors,
            "spot_or_process": tail if tail in ("spflspot", "spflproc") else None}


def _n7z(b, i):
    """7z variable-length number at b[i] -> (value, next index)"""
    first, mask, val = b[i], 0x80, 0
    for k in range(8):
        if not first & mask:
            return val | ((first & (mask - 1)) << (8 * k)), i + 1 + k
        val |= b[i + 1 + k] << (8 * k)
        mask >>= 1
    return val, i + 9


def _lzma(data, props, size):
    lc, rem = props[0] % 9, props[0] // 9
    d = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA1, "lc": lc, "lp": rem % 5, "pb": rem // 5,
                                                                "dict_size": struct.unpack("<I", props[1:5])[0]}])
    return d.decompress(data, max_length=size)


def _streams(b, h):
    """(packPos, [pack sizes], [(lzma props, unpack size)]) from a 7z header that starts at kPackInfo; only the layout
    the shipped .sbsar files use (one LZMA coder per folder) is handled, anything else raises"""
    assert h[0] == 0x06, "no PackInfo"
    pos, i = _n7z(h, 1)
    n, i = _n7z(h, i)
    assert h[i] == 0x09
    i += 1
    sizes = []
    for _ in range(n):
        s, i = _n7z(h, i)
        sizes.append(s)
    while h[i] != 0x00:  # optional CRCs
        i += 1 + 1 + 4 * n if h[i] == 0x0A else 1
    i += 1
    assert h[i:i + 2] == b"\x07\x0b", "no UnpackInfo/Folder"
    nf, i = _n7z(h, i + 2)
    assert h[i] == 0, "external folders"
    i += 1
    props = []
    for _ in range(nf):
        assert h[i] == 0x01, "folder with several coders"
        fl = h[i + 1]
        cid = h[i + 2:i + 2 + (fl & 0x0F)]
        assert not fl & 0x10, "complex coder"
        if cid in (b"", b"\x00"):  # Copy (stored stream, e.g. the .png icon); the .sbsar writer uses a 0-byte id
            props.append(None)
            i += 2 + len(cid)
            continue
        assert cid == b"\x03\x01\x01" and fl & 0x20, f"coder {cid.hex()} is neither LZMA nor Copy"
        ps, j = _n7z(h, i + 2 + (fl & 0x0F))
        props.append(h[j:j + ps])
        i = j + ps
    assert h[i] == 0x0C
    i += 1
    out = []
    for p in props:
        s, i = _n7z(h, i)
        out.append((p, s))
    return pos, sizes, out


def sbsar_xml(path):
    """the sbsdescription XML inside a Substance .sbsar (7z, LZMA) -> str"""
    b = Path(path).read_bytes()
    assert b[:6] == b"7z\xbc\xaf\x27\x1c", "not 7z"
    off, size = struct.unpack("<QQ", b[12:28])
    h = b[32 + off:32 + off + size]
    if h[0] == 0x17:  # encoded header: one LZMA stream holding the real header
        pos, sizes, co = _streams(b, h[1:])
        raw = b[32 + pos:32 + pos + sizes[0]]
        h = raw if co[0][0] is None else _lzma(raw, *co[0])
    assert h[:2] == b"\x01\x04", "no MainStreamsInfo"
    pos, sizes, co = _streams(b, h[2:])
    p = 32 + pos
    for s, (props, usize) in zip(sizes, co):
        data = b"" if props is None or usize > 20_000_000 else _lzma(b[p:p + s], props, usize)
        if data.startswith(b"<?xml") and b"<sbsdescription" in data[:400]:
            return data.decode("utf-8")
        p += s
    raise ValueError("no sbsdescription XML stream")


def parse_sbsar(x):
    """sbsdescription XML -> {label, category, keywords, presets, params}"""
    g = re.search(r"<graph ([^>]*)>", x)
    ga = dict(re.findall(r'(\w+)="([^"]*)"', g.group(1))) if g else {}
    params = []
    for m in re.finditer(r'<input ([^>]*?)(/?)>(.*?)(?=<input |</inputs>)', x, flags=re.S):
        a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        gui = re.search(r'<inputgui ([^>]*)>', m.group(3))
        ga2 = dict(re.findall(r'(\w+)="([^"]*)"', gui.group(1))) if gui else {}
        sl = re.search(r'<guislider ([^>]*)/>', m.group(3))
        sa = dict(re.findall(r'(\w+)="([^"]*)"', sl.group(1))) if sl else {}
        try:
            dv = [float(v) for v in a.get("default", "").split(",") if v.strip()]
        except ValueError:  # a string input
            dv = None
        w = ga2.get("widget")
        if dv is None:
            typ = "string"
        else:
            typ = {"color": "color", "togglebutton": "bool", "combobox": "enum"}.get(w) or \
                ("number" if a.get("type") == "0" else "int" if a.get("type") == "4" else "object" if len(dv) > 1 else "unknown")
        p = {"name": (ga2.get("label") or a["identifier"]).strip(), "key": a["identifier"], "type": typ,
             "default": a.get("default") if dv is None else dv[0] if len(dv) == 1 else dv, "sbs_type": a.get("type")}
        if typ in ("int", "bool", "enum") and isinstance(p["default"], float):
            p["default"] = bool(p["default"]) if typ == "bool" else int(p["default"])
        for k in ("min", "max"):
            if k in sa and len(sa[k].split(",")) == 1:
                p[k] = float(sa[k])
        if "step" in sa:
            p["step"] = sa["step"]
        items = re.findall(r'<guicomboboxitem value="([^"]*)" text="([^"]*)"', m.group(3))
        if items:
            p["enum"] = [{"value": int(v), "label": t} for v, t in items]
        if ga2.get("group"):
            p["group"] = ga2["group"]
        params.append(p)
    count = {}
    for p in params:
        count[p["name"]] = count.get(p["name"], 0) + 1
    for p in params:  # two inputs sharing a GUI label (e.g. 'Roughness' in two groups): keep the label, add the key
        if count[p["name"]] > 1:
            p["label"], p["name"] = p["name"], f"{p['name']} ({p['key']})"
    return {"label": ga.get("label"), "category": ga.get("category"), "keywords": ga.get("keywords"),
            "physical_size": ga.get("physicalSize"), "presets": re.findall(r'<sbspreset label="([^"]*)"', x), "params": params}


def parse_acbl(t):
    """legacy XML color book -> {prefix, postfix, model, names}"""
    pp = re.search(r'Prefix="([^"]*)" Postfix="([^"]*)"', t)
    fmt = re.search(r'ColorSpace="([^"]+)"', t)
    return {"prefix": pp.group(1) if pp else "", "postfix": pp.group(2) if pp else "",
            "model": fmt.group(1) if fmt else None, "book_id": (re.search(r'BookID="(\d+)"', t) or [None, None])[1],
            "names": re.findall(r'<Sp N="([^"]*)"', t)}


def _hexname(s):
    m = re.search(r"/name \[ \d+\s+([0-9a-f\s]+?)\]", s)
    return bytes.fromhex(re.sub(r"\s", "", m.group(1))).decode("utf-8", "replace") if m else None


def parse_aia(t):
    """Illustrator action set (.aia) -> (set name, [{name, events:[{internal, localized, dialog}]}])"""
    head, *acts = re.split(r"/action-\d+ \{", t)
    out = []
    for a in acts:
        evs = []
        for e in re.split(r"/event-\d+ \{", a)[1:]:
            loc = re.search(r"/localizedName \[ \d+\s+([0-9a-f\s]+?)\]", e)
            ehead, *prms = re.split(r"/parameter-\d+ \{", e)
            ps = []
            for p in prms:
                key = int(re.search(r"/key (\d+)", p).group(1))
                k4 = key.to_bytes(4, "big").decode("latin-1")
                typ = (re.search(r"/type \((.*?)\)", p) or [None, None])[1]
                val = (re.search(r"/value (\S+)", p) or [None, None])[1]
                unit = re.search(r"/unit (\d+)", p)
                ps.append({"key": k4, "type": typ, "value": val, "label": _hexname(p),
                           "unit": int(unit.group(1)).to_bytes(4, "big").decode("latin-1") if unit else None})
            evs.append({"internal": (re.search(r"/internalName \((.*?)\)", ehead) or [None, None])[1],
                        "localized": bytes.fromhex(re.sub(r"\s", "", loc.group(1))).decode("utf-8", "replace") if loc else None,
                        "has_dialog": (re.search(r"/hasDialog (\d)", ehead) or [None, None])[1] == "1",
                        "show_dialog": (re.search(r"/showDialog (\d)", ehead) or [None, None])[1] == "1",
                        "is_on": (re.search(r"/isOn (\d)", ehead) or [None, None])[1] == "1", "params": ps})
        out.append({"name": _hexname(a), "events": evs})
    return _hexname(head), out


def parse_width_profiles(t):
    """VariableWidthProfiles -> [{collectionName, VariableWidth_Distances, ..., canEdit}] (hex values decoded)"""
    out = []
    for blk in re.findall(r"/collection\d+ \{(.*?)\n\}", t, flags=re.S):
        d = {k: bytes.fromhex(re.sub(r"\s", "", v)).decode("latin-1").strip()
             for k, v in re.findall(r"/(\w+) \[ \d+\s+([0-9a-f\s]+?)\]", blk)}
        d.update(re.findall(r"/(\w+) (-?\d+)\s*$", blk, flags=re.M))
        out.append(d)
    return out


PDFSET = ROOT / "Support Files/Required/pdfsettings/settings/mul/settings"


def parse_joboptions(t):
    """Adobe PDF settings (.joboptions) -> [param] for the top-level scalar keys (nested dicts / arrays are skipped)"""
    ps = []
    for k, v in re.findall(r"^  /(\w+) (.+?)\s*$", t, flags=re.M):
        if v.startswith(("<<", "[")):
            continue
        if v in ("true", "false"):
            ps.append({"name": k, "key": k, "type": "bool", "default": v == "true"})
        elif re.fullmatch(r"-?\d+", v):
            ps.append({"name": k, "key": k, "type": "int", "default": int(v)})
        elif re.fullmatch(r"-?\d*\.\d+", v):
            ps.append({"name": k, "key": k, "type": "number", "default": float(v)})
        elif v.startswith("/"):
            ps.append({"name": k, "key": k, "type": "enum", "default": v[1:], "enum": [{"value": v[1:], "label": v[1:]}]})
        elif v.startswith("("):
            ps.append({"name": k, "key": k, "type": "string",
                       "default": re.sub(r"\\(\d{3})", lambda m: chr(int(m.group(1), 8)), v[1:-1])})
    return ps


def alnum(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def menu_paths():
    """leaf paths of the earlier live menu walks (work/ai/menu_<Top>.json) -> set('Window/Brush Libraries/...')"""
    res = set()

    def walk(nodes, p):
        for c in nodes:
            if c.get("separator"):
                continue
            q = p + "/" + c["name"]
            res.add(q)
            walk(c.get("children", []), q)
    for top in ("File", "Window"):
        f = (PGD / f"work/ai/menu_{top}.json")
        if f.exists():
            walk(json.loads(f.read_text(encoding="utf-8")), top)
    return res


# ---------------------------------------------------------------- build
def vstr(c):
    t = c.get("t", "")
    if t == "SpotColor":
        return f"Spot {c.get('kind', '').replace('ColorModel.', '')} tint {c.get('tint')} of " + vstr(c.get("base") or {})
    if t == "GradientColor":
        return f"Gradient {c.get('gtype', '').replace('GradientType.', '')} {c.get('stops')} stops"
    if t == "PatternColor":
        return "Pattern"
    if "v" in c:
        return t.replace("Color", "") + " " + " ".join(f"{x:g}" for x in c["v"])
    return t.replace("Color", "") or "?"


def ptype(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "number"
    if isinstance(v, list):
        return "object"
    if isinstance(v, str) and re.fullmatch(r"[A-Z][A-Za-z]+\.[A-Z0-9_]+", v):
        return "enum"
    return "string" if isinstance(v, str) else "unknown"


def settings_params(d):
    ps = []
    for k, v in d.items():
        if isinstance(v, dict):  # {err}: the getter raised
            ps.append({"key": k, "name": k, "type": "unknown", "error": v.get("err")})
            continue
        p = {"key": k, "name": k, "type": ptype(v), "default": v}
        if p["type"] == "enum":
            p["enum"] = [{"value": v, "label": v.split(".", 1)[1]}]  # only the value this preset holds
        ps.append(p)
    return ps


# verified 2026-10-04 (Artistic_Ink / Neon Effects / Arrows): an item using a library entry, duplicated from the opened
# library document into another document, brings the brush / graphic style / symbol into that document's panel
XFER = ("; to use it elsewhere: app.open(<library>), apply it to an item there, item.duplicate(target.layers[0], "
        "ElementPlacement.PLACEATEND) (the entry arrives in the target document), close the library DONOTSAVECHANGES")
LIB_KINDS = {  # folder -> (record key, category, menu root, DOM call, requires)
    "Brushes": ("brushes", "Brush", "Window/Brush Libraries/", "doc.brushes.getByName({n}).applyTo(pathItem)",
                "path item in a document that holds the brush" + XFER),
    "Graphic Styles": ("styles", "Graphic Style", "Window/Graphic Style Libraries/",
                       "doc.graphicStyles.getByName({n}).applyTo(pageItem)", "page item in a document that holds the style" + XFER),
    "Symbols": ("symbols", "Symbol", "Window/Symbol Libraries/", "doc.symbolItems.add(doc.symbols.getByName({n}))",
                "a document that holds the symbol" + XFER)}
DOM_KEY = {"brushes": "brushes", "styles": "graphicStyles", "symbols": "symbols"}


def build():
    libs_ck = load(LIBS_CKPT, {})
    app_ck = load(APP_CKPT, {})
    mp = menu_paths()
    vf = (PGD / "work/ai/app_version.txt")
    ver = app_ck.get("version") or (vf.read_text().strip() if vf.exists() else None)
    items, ids = [], {}
    fxname = {}  # LiveEffect name -> [Effect-menu display names sharing it] (earlier effects stage)
    fxf = (PGD / "harvest/ai/ai_effect.json")
    if fxf.exists():
        for x in json.loads(fxf.read_text(encoding="utf-8"))["items"]:
            le = (x.get("invoke") or {}).get("ai_live_effect") or (x.get("extra") or {}).get("live_effect_name")
            if le and x["name"] not in fxname.get(le, []):
                fxname.setdefault(le, []).append(x["name"])

    def add(it):
        base = it["id"]
        ids[base] = ids.get(base, 0) + 1
        if ids[base] > 1:  # a library holding two entries of one name: keep both, number the later one
            it["id"] = f"{base}#{ids[base]}"
            it.setdefault("extra", {})["duplicate_name_index"] = ids[base]
        items.append(it)

    def menu_ev(mpath, what="library"):
        return (f"{what} listed in the live menu walk at {mpath}" if mpath in mp
                else f"{what} not found in the live menu walk (looked for {mpath})")

    # ---- .ai libraries opened in Illustrator: one item per brush / graphic style / symbol
    nlibs, seen_in = {}, {}  # entries every library file of a folder carries (document defaults, e.g. [Default] style)
    for k, rec in libs_ck.items():
        top = k.split("/", 1)[0]
        if top in LIB_KINDS:
            nlibs[top] = nlibs.get(top, 0) + 1
            for e in {e["n"] for e in rec.get(LIB_KINDS[top][0], [])}:
                seen_in[(top, e)] = seen_in.get((top, e), 0) + 1
    for k, rec in sorted(libs_ck.items()):
        top = k.split("/", 1)[0]
        if top == "Swatches":
            continue
        f = (PRESETS / k) if (PRESETS / k).exists() else (ROOT / k)
        stem = Path(k).stem
        if stem in ("Arrowheads", "Bevels"):
            cat = "Arrowhead" if stem == "Arrowheads" else "Bevel (3D Classic)"
            for s in rec.get("symbols", []):
                it = {"name": s["n"], "id": f"{k}#{s['n']}", "path": k, "category": cat, "invoke": {"file": f.as_posix()},
                      "requires": "stroked open path" if cat == "Arrowhead" else "Effect > 3D and Materials > 3D (Classic) > Extrude & Bevel (Classic)",
                      "evidence": f"entry name read from document.symbols of {f.name} opened with app.open"
                                  + ("; symbolItems.add(symbol) ran in that document" if s.get("ok") else ""),
                      "extra": {"library_file": k, "symbol_size_pt": [s.get("w"), s.get("h")]}}
                if s.get("err"):
                    it["error"] = "symbolItems.add failed: " + s["err"]
                add(it)
            if rec.get("err") or not rec.get("symbols"):
                add({"name": stem, "id": k, "path": k, "category": cat + " library", "invoke": {"file": f.as_posix()},
                     "error": "library could not be read: " + str(rec.get("err") or "no symbols in the document")})
            continue
        key, cat, mroot, dom, req = LIB_KINDS[top]
        mpath = mroot + Path(k).relative_to(top).with_suffix("").as_posix()
        unc = unc_path(k)
        utext = unc.read_text(encoding="latin-1") if unc.exists() else None
        btypes = brush_types(utext) if utext and key == "brushes" else {}
        sfilt = style_filters(utext) if utext and key == "styles" else {}
        if rec.get("err") or not rec.get(key):
            add({"name": stem, "id": k, "path": mpath, "category": cat + " library", "invoke": {"file": f.as_posix()},
                 "error": "library could not be read: " + str(rec.get("err") or f"no {DOM_KEY[key]} in the document"),
                 "evidence": menu_ev(mpath)})
            continue
        for e in rec[key]:
            it = {"name": e["n"], "id": f"{k}#{e['n']}", "path": mpath, "category": cat,
                  "invoke": {"file": f.as_posix(), "ai_dom": dom.format(n=json.dumps(e["n"]))}, "requires": req,
                  "evidence": f"name read from document.{DOM_KEY[key]} of {f.name} opened with app.open; "
                              + ("the invoke call ran without error in that document; " if e.get("ok") else "") + menu_ev(mpath),
                  "extra": {"library": stem, "library_file": k}}
            if "w" in e:
                it["extra"]["symbol_size_pt"] = [e["w"], e["h"]]
            if nlibs[top] > 2 and seen_in[(top, e["n"])] == nlibs[top]:
                it["extra"]["in_every_library_file"] = f"all {nlibs[top]} {top} library files contain an entry of this name"
            if e["n"] in btypes:
                tool, plug = btypes[e["n"]]
                it["extra"]["brush_tool"] = tool
                if plug:
                    it["extra"]["brush_plugin"] = plug
                it["evidence"] += "; brush tool id from the library saved uncompressed (%AI8_BeginPluginObject record)"
            elif key == "brushes" and utext:
                it["extra"]["brush_tool"] = None
            if e["n"] in sfilt:
                fl = sfilt[e["n"]]
                fx = [x for x in fl if x not in STRUCT_FILTERS | {"Fill Style Filter", "Stroke Style Filter"}
                      and not x.endswith("Brush Tool")]
                it["extra"].update(fills=fl.count("Fill Style Filter"), strokes=fl.count("Stroke Style Filter"),
                                   brushed_strokes=[x for x in fl if x.endswith("Brush Tool")], live_effects=fx,
                                   effect_names=[fxname[x][0] if len(fxname.get(x, [])) == 1 else x for x in fx])
                amb = {x: fxname[x] for x in fx if len(fxname.get(x, [])) > 1}
                if amb:  # one LiveEffect behind several Effect-menu items (Warp styles, 3D, Pathfinder ...)
                    it["extra"]["effect_candidates"] = amb
                it["evidence"] += "; appearance read from the library saved uncompressed (%AI9_BeginArtStyles filters)"
            if e.get("err"):
                it["error"] = "invoke call failed in the library document: " + e["err"]
            add(it)

    # ---- swatch libraries: one item per library, entries in extra
    for f in sorted((PRESETS / "Swatches").rglob("*")):
        if not f.is_file():
            continue
        k, ext = rel(f), f.suffix.lower()
        mpath = "Window/Swatch Libraries/" + Path(k).relative_to("Swatches").with_suffix("").as_posix()
        it = {"name": f.stem, "id": k, "path": mpath, "category": "Swatch library", "invoke": {"file": f.as_posix()},
              "requires": "open document", "extra": {"format": ext.lstrip(".")}}
        try:
            if ext == ".ai":
                rec = libs_ck.get(k) or {"err": "library not opened yet"}
                if rec.get("err"):
                    it["error"] = "not read: " + rec["err"]
                else:
                    sw = rec["swatches"]
                    it["extra"].update(entries=[s["n"] for s in sw], entry_values=[vstr(s["c"]) for s in sw],
                                       groups={g["n"] or "(ungrouped)": g["m"] for g in rec["groups"]},
                                       document_color_mode=rec.get("mode"))
                    it["evidence"] = f"entries read from document.swatches / swatchGroups of {f.name} opened with app.open; " + menu_ev(mpath)
            elif ext == ".ase":
                sw = parse_ase(f.read_bytes())
                it["extra"].update(entries=[s["name"] for s in sw],
                                   entry_values=[f"{s['model']} {' '.join(f'{v:g}' for v in s['values'])} ({s['type']})" for s in sw],
                                   groups=sorted({s["group"] for s in sw if s["group"]}))
                it["evidence"] = "entries parsed from the .ase file (ASEF blocks); " + menu_ev(mpath)
            elif ext == ".acb":
                bk = parse_acb(f.read_bytes())
                it["extra"].update(entries=[c["name"] for c in bk["colors"]],
                                   entry_values=[f"{bk['model']} {' '.join(map(str, c['values']))}" for c in bk["colors"]],
                                   book_title=bk["title"], book_id=bk["book_id"], prefix=bk["prefix"], postfix=bk["postfix"],
                                   description=bk["description"], color_model=bk["model"], page_size=bk["page_size"],
                                   spot_or_process=bk["spot_or_process"])
                it["category"] = "Swatch library (color book)"
                it["evidence"] = "entries parsed from the .acb color book (8BCB records; values are the raw channel bytes; prefix / postfix kept separately); " + menu_ev(mpath)
            elif ext == ".acbl":
                bk = parse_acbl(f.read_text(encoding="utf-8"))
                it["extra"].update(entries=bk["names"], prefix=bk["prefix"], postfix=bk["postfix"], color_model=bk["model"],
                                   book_id=bk["book_id"])
                it["category"] = "Swatch library (legacy color book)"
                it["evidence"] = "entries parsed from the legacy XML color book; " + menu_ev(mpath)
            else:
                it["error"] = f"unknown swatch file type {ext}"
        except Exception as e:  # noqa: BLE001
            it["error"] = f"parse failed: {e}"
        if "entries" in it["extra"]:
            it["extra"]["entry_count"] = len(it["extra"]["entries"])
        add(it)

    # ---- actions
    for f in sorted((PRESETS / "Actions").glob("*.aia")):
        setname, acts = parse_aia(f.read_text(encoding="latin-1"))
        runs = load(WORK / "actions_run.json", {})
        for a in acts:
            prm = []
            for i, e in enumerate(a["events"]):
                for p in e["params"]:
                    t = {"unit real": "number", "real": "number", "boolean": "bool", "integer": "int",
                         "enumerated": "enum", "ustring": "string", "string": "string"}.get(p["type"], "unknown")
                    v = p["value"]
                    try:
                        v = {"number": float, "int": int, "enum": int, "bool": lambda x: x == "1"}.get(t, str)(v) if v is not None else None
                    except ValueError:
                        t = "unknown"
                    q = {"name": f"step{i + 1}.{p['key']}", "key": p["key"], "type": t, "default": v}
                    if p["unit"]:
                        q["unit"] = p["unit"]
                    if t == "enum":
                        q["enum"] = [{"value": v, "label": p["label"]}]  # only the value the action records
                    if p["type"] not in ("unit real", "real", "boolean", "integer", "enumerated", "ustring", "string"):
                        q["raw_type"] = p["type"]
                    prm.append(q)
            it = {"name": a["name"], "id": f"{rel(f)}#{a['name']}", "path": f"Actions panel/{setname}", "category": "Action",
                  "invoke": {"file": f.as_posix(), "ai_dom": f"app.doScript({json.dumps(a['name'])}, {json.dumps(setname)})"},
                  "requires": "the action set loaded in the Actions panel; '(selection)' actions need a selection",
                  "evidence": f"action, steps and recorded parameters parsed from {f.name} (hex /name fields, 4-char /key codes)",
                  "extra": {"action_set": setname, "steps": [e["localized"] for e in a["events"]],
                            "step_ids": [e["internal"] for e in a["events"]],
                            "steps_showing_dialog": sum(e["show_dialog"] for e in a["events"])}}
            if prm:
                it["params"] = prm
            r = runs.get(a["name"])
            if r is None:
                it["evidence"] += "; not run"
            elif r.get("skip"):
                it["evidence"] += "; not run: " + r["skip"]
            elif r.get("err"):
                it["error"] = "app.doScript on a test document failed: " + r["err"]
            else:
                it["evidence"] += f"; ran with app.doScript on two selected test rectangles: {r['note']}"
            add(it)

    # ---- scripts, keyboard shortcut sets, Save for Web settings, workspaces
    for f in sorted((PRESETS / "Scripts").glob("*.jsx")):
        mpath = f"File/Scripts/{f.stem}"
        add({"name": f.stem, "id": rel(f), "path": mpath, "category": "Script", "invoke": {"file": f.as_posix()},
             "evidence": "file in Presets/en_US/Scripts; " + menu_ev(mpath, "script")})
    for f in sorted((PRESETS / "Keyboard Shortcuts").glob("*.kys")):
        add({"name": f.stem, "id": rel(f), "path": "Edit/Keyboard Shortcuts...", "category": "Keyboard shortcut set",
             "invoke": {"file": f.as_posix()}, "evidence": "file in Presets/en_US/Keyboard Shortcuts (set name = file name)"})
    for f in sorted((PRESETS / "Save for Web Settings").rglob("*")):
        if f.is_file():
            cat = {"Optimize": "Save for Web optimize preset", "Color Tables": "Save for Web color table"}[f.parent.name]
            ex = {"bytes": f.stat().st_size}
            if f.suffix == ".act" and f.stat().st_size >= 770:
                ex["color_count"] = struct.unpack(">H", f.read_bytes()[768:770])[0]
            add({"name": f.stem, "id": rel(f), "path": "File/Export/Save for Web (Legacy)...", "category": cat,
                 "invoke": {"file": f.as_posix()}, "evidence": f"file in Presets/en_US/Save for Web Settings/{f.parent.name}",
                 "extra": ex})
    for f in sorted((PRESETS / "Workspaces").iterdir()):
        cn = re.search(r"/collectionName \[ \d+\s+([0-9a-f]+)", f.read_text(encoding="latin-1"))
        mpath = f"Window/Workspace/{f.name}"
        add({"name": f.name, "id": rel(f), "path": mpath, "category": "Workspace", "invoke": {"file": f.as_posix()},
             "evidence": "file in Presets/en_US/Workspaces; " + menu_ev(mpath, "workspace"),
             "extra": {"collection_name": bytes.fromhex(cn.group(1)).decode("latin-1") if cn else None}})

    # ---- toolbars
    from ai_tools import toolbars
    tp = PRESETS / "Tools/Tools Panel Presets"
    tbs = toolbars()
    walked = {p.rsplit("/", 1)[1] for p in mp if p.startswith("Window/Toolbars/") and not p.endswith("...")}
    left_file, left_menu = [n for n in tbs if n not in walked], sorted(walked - set(tbs))
    for name, groups in tbs.items():
        ex = {"groups": [{"label": g, "tools": m} for g, m in groups], "tool_count": sum(len(m) for _, m in groups)}
        ev = "parsed from Presets/en_US/Tools/Tools Panel Presets (ai_tools.toolbars); "
        shown = name
        if name in walked:
            ev += f"toolbar listed in the live menu walk at Window/Toolbars/{name}"
        elif len(left_file) == 1 and len(left_menu) == 1:  # the one unmatched preset vs the one unmatched menu label
            shown, ex["preset_collection_name"] = left_menu[0], name
            ev += (f"menu label matched by elimination: the preset file calls it {name!r}, the live Window > Toolbars walk "
                   f"lists {left_menu[0]!r} as the only label with no preset of that name")
        else:
            ev += "not found in the live Window > Toolbars walk"
        add({"name": shown, "id": f"{rel(tp)}#{name}", "path": f"Window/Toolbars/{shown}", "category": "Toolbar",
             "invoke": {"file": tp.as_posix()}, "evidence": ev, "extra": ex})

    # ---- width profiles
    wp = RES / "VariableWidthProfiles"
    for d in reversed(parse_width_profiles(wp.read_text(encoding="latin-1"))):
        nm = d.get("collectionName")
        prm = [{"name": key.split("_", 1)[1], "key": key, "type": "object", "default": [float(x) for x in d[key].split()]}
               for key in ("VariableWidth_Distances", "VariableWidth_Widths", "VariableWidth_LeftWidths",
                           "VariableWidth_RightWidths") if key in d]
        add({"name": nm, "id": f"{rel(wp)}#{nm}", "path": "Stroke panel/Profile", "category": "Width profile",
             "params": prm, "invoke": {"file": wp.as_posix()}, "requires": "stroked path",
             "evidence": "parsed from Support Files/Required/Resources/en_US/VariableWidthProfiles",
             "extra": {"profile_type": int(d.get("VariableWidth_ProfileType", -1)), "can_edit": d.get("canEdit"),
                       "can_delete": d.get("canDelete")}})

    # ---- 3D materials
    for f in sorted(MATS.rglob("*.sbsar")):
        default = f.parent.name == "Default_Substance_Materials"
        png = f.with_suffix(".png")
        it = {"name": f.stem, "id": rel(f), "path": "Effect/3D and Materials/Materials" if default else "(internal resource)",
              "category": "3D material (Substance)" if default else "3D material (internal)",
              "invoke": {"file": f.as_posix()}, "requires": "object with a 3D and Materials effect",
              "extra": {"file_stem": f.stem, "thumbnail": png.as_posix() if png.exists() else None}}
        try:
            sb = parse_sbsar(sbsar_xml(f))
            if sb["label"]:
                it["name"] = sb["label"].strip()
            it["params"] = sb["params"]
            it["extra"].update(sbs_category=sb["category"], keywords=sb["keywords"], physical_size=sb["physical_size"],
                               sbs_presets=sb["presets"])
            it["evidence"] = ("name, category, presets and inputs (label, default, slider min / max) read from the sbsdescription "
                              "XML inside the .sbsar (7z/LZMA, decoded by ai_presets.sbsar_xml); not checked against the 3D panel")
        except Exception as e:  # noqa: BLE001
            it["error"] = f"sbsar not decoded ({e}); name is the file stem"
        add(it)

    # ---- app-level lists
    meta = {"tracing": ("Image Trace preset", "Window/Image Trace/Preset",
                        "placedItem.trace().tracing.tracingOptions.loadFromPreset({n})", "placed or embedded raster image"),
            "pdf": ("PDF preset", "Edit/Adobe PDF Presets...", "var o = new PDFSaveOptions(); o.pDFPreset = {n}; doc.saveAs(file, o)", "open document"),
            "print": ("Print preset", "Edit/Print Presets...", "var o = new PrintOptions(); o.printPreset = {n}; doc.print(o)", "open document"),
            "flattener": ("Transparency flattener preset", "Edit/Transparency Flattener Presets...",
                          "var o = new PrintOptions(); o.flattenerPreset = {n}", "open document with transparency"),
            "startup": ("New document profile", "File/New...", "app.documents.addDocument({n}, app.getPresetSettings({n}))", None)}
    optprops = app_ck.get("optprops", {})
    for k, names in app_ck.get("lists", {}).items():
        cat, path, dom, req = meta[k]
        for n in names:
            it = {"name": n, "id": f"app.{LISTS[k]}#{n}", "path": path, "category": cat,
                  "invoke": {"ai_dom": dom.format(n=json.dumps(n))}, "evidence": f"name read live from app.{LISTS[k]}"}
            if req:
                it["requires"] = req
            prop = {"pdf": ("pdf", "pDFPreset"), "print": ("print", "printPreset"), "flattener": ("print", "flattenerPreset")}.get(k)
            if prop:
                it["evidence"] += (f"; {prop[1]} is a property of the options object (reflection)" if prop[1] in optprops.get(prop[0], [])
                                   else f"; {prop[1]} NOT found by reflection on the options object")
                jo = {alnum(p.stem): p for p in PDFSET.glob("*.joboptions")} if k == "pdf" else {}
                if alnum(n) in jo:
                    jf = jo[alnum(n)]
                    it["params"] = parse_joboptions(jf.read_text(encoding="latin-1"))
                    it["invoke"]["file"] = jf.as_posix()
                    it["evidence"] += (f"; settings parsed from Support Files/Required/pdfsettings/settings/mul/settings/{jf.name} "
                                       "(the one .joboptions whose name equals the preset name with punctuation removed; "
                                       "top-level scalar keys only); not applied")
                else:
                    it["error"] = ("preset settings are not readable from the scripting DOM (only the name)"
                                   + ("; no .joboptions file in the install matches this name" if k == "pdf" else "")
                                   + "; not applied")
            src_key = {"tracing": "trace", "startup": "docpreset"}.get(k)
            if src_key:
                s = app_ck.get(src_key, {}).get(n)
                if s and "err" not in s:
                    it["params"] = settings_params(s)
                    it["evidence"] += ("; settings read back from TracingOptions after loadFromPreset on a traced copy of the test photo"
                                       if k == "tracing" else "; settings read from app.getPresetSettings(name)")
                else:
                    it["error"] = "settings not read: " + (s or {}).get("err", "app stage has not run")
            add(it)

    src = ("Presets/en_US .ai libraries opened as documents in Illustrator (document.brushes / graphicStyles / symbols / swatches; "
           "each entry test-applied inside its own library document) + .ase/.acb/.acbl/.aia/.act/workspace/toolbar files parsed "
           "from disk + Arrowheads.ai, Bevels.ai, VariableWidthProfiles, Material-Resources from Support Files + app.*PresetsList, "
           "TracingOptions.loadFromPreset and app.getPresetSettings read live (tools/ai/ai_presets.py)")
    save(OUT, {"app": "AI", "kind": "ai_preset", "app_version": ver, "source": src, "items": items})
    print(f"{OUT}: {len(items)} items, {sum('error' in i for i in items)} with error")
    return 0


def selftest():
    name = "Red".encode("utf-16-be") + b"\0\0"
    body = struct.pack(">H", 4) + name + b"RGB " + struct.pack(">fff", 1, 0, 0) + struct.pack(">H", 2)
    ase = b"ASEF" + struct.pack(">HHI", 1, 0, 1) + struct.pack(">HI", 1, len(body)) + body
    assert parse_ase(ase) == [{"name": "Red", "model": "RGB", "values": [1.0, 0.0, 0.0], "type": "normal", "group": ""}]
    aia = ("/version 3/name [ 3\t616263]/action-1 {\t/name [ 2\t6869\t]\t/event-1 {\t/internalName (x)\t/localizedName [ 1\t41\t]"
           "\t/isOn 1\t/hasDialog 1\t/showDialog 0\t/parameterCount 1\t/parameter-1 {\t/key 1634625388\t/type (unit real)"
           "\t/value 90.0\t/unit 591490663\t}\t}}")
    assert parse_aia(aia) == ("abc", [{"name": "hi", "events": [
        {"internal": "x", "localized": "A", "has_dialog": True, "show_dialog": False, "is_on": True,
         "params": [{"key": "angl", "type": "unit real", "value": "90.0", "label": None, "unit": "#Ang"}]}]}]), parse_aia(aia)
    assert zs("$$$/colorbook/ANPA/title=ANPA Color") == "ANPA Color"
    wp = "/collection1 {\n\t/attributes {\n\t\t/VariableWidth_Widths [ 3\n\t\t\t302031\n\t\t]\n\t\t/collectionName [ 1\n\t\t\t41\n\t\t]\n\t}\n\t/canEdit 0\n}"
    assert parse_width_profiles(wp) == [{"VariableWidth_Widths": "0 1", "collectionName": "A", "canEdit": "0"}], parse_width_profiles(wp)
    print("selftest ok")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "libs":
        sys.exit(libs(sys.argv[2] if len(sys.argv) > 2 else None))
    sys.exit({"app": app_stage, "unc": save_unc, "actions": run_actions, "build": build, "selftest": selftest}[cmd]())
