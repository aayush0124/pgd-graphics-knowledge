"""PGD/CDR: build harvest/cdr/cdr_preset.json from the files CorelDRAW 2024 ships (no app needed), then merge the live
read-back in work/cdr/presets_live.json (presets_live.py) when it exists.

    python harvest_presets.py            -> harvest/cdr/cdr_preset.json
    python harvest_presets.py --selftest

One item per preset a designer picks by name; one item per palette / library with the entry names in extra.entries.
id = <path relative to the install, or <UserContent>/... / <UserData>/...> + "#" + entry name.
Everything in an item is read from a file or from the running app; nothing is filled in from documentation.
"""
import html
import json, re, struct, sys, zipfile, zlib
import xml.etree.ElementTree as ET
from pathlib import Path
import os

HERE = Path(__file__).resolve().parent
PGD = HERE.parents[1]
OUT = PGD / "harvest" / "cdr" / "cdr_preset.json"
LIVE = PGD / "work" / "cdr" / "presets_live.json"
R = Path(r"C:/Program Files/Corel/CorelDRAW Graphics Suite/25")
USER_CONTENT = Path(os.environ.get("PGD_CDR_USER_CONTENT") or Path.home() / "OneDrive/Documents/Corel/Corel Content")
USER_DATA = Path(os.environ.get("PGD_CDR_USER_DATA") or Path.home() / "AppData/Roaming/Corel/CorelDRAW Graphics Suite 2024")
ROOTS = [(R, ""), (USER_CONTENT, "<UserContent>/"), (USER_DATA, "<UserData>/")]


def rel(p):
    p = Path(p)
    for root, tag in ROOTS:
        try:
            return tag + p.relative_to(root).as_posix()
        except ValueError:
            pass
    return p.as_posix()


def mk(name, f, category, path, entry=None, **kw):
    it = {"name": name, "id": rel(f) + "#" + (entry or name), "path": path, "category": category,
          "invoke": {"file": str(Path(f))}}
    it.update({k: v for k, v in kw.items() if v not in (None, [], {})})
    return it


def num(s):
    try:
        f = float(s)
        return int(f) if f.is_integer() and "." not in str(s) else f
    except (TypeError, ValueError):
        return None


def params_from_dict(d, prefix=""):
    """Flat {key: value} from a preset file -> typed params with the file's value as default (strings stay strings)."""
    out = []
    for k, v in d.items():
        key = prefix + k
        if isinstance(v, dict):
            out += params_from_dict(v, key + ".")
            continue
        if isinstance(v, bool):
            out.append({"name": key, "key": key, "type": "bool", "default": v})
        elif isinstance(v, (int, float)):
            out.append({"name": key, "key": key, "type": "number", "default": v})
        elif isinstance(v, str):
            n = num(v)
            if "Color" in k or k == "color":
                out.append({"name": key, "key": key, "type": "color", "default": v})
            elif n is not None:
                out.append({"name": key, "key": key, "type": "number", "default": n})
            else:
                out.append({"name": key, "key": key, "type": "string", "default": v})
    return out


# ---------------------------------------------------------------- zip packages (.fill .cdrt .cdss in Content)
def zcf_meta(z):
    try:
        m = zread(z, "META-INF/metadata.xml").decode("utf-8", "replace")
    except KeyError:
        return {}
    out = {}
    t = re.search(r"<dc:title>.*?<rdf:li[^>]*>(.*?)</rdf:li>", m, re.S)
    if t:
        out["title"] = html.unescape(t.group(1).strip())   # audit 2026-10-04: '&amp;' leaked into a template name
    kw = re.search(r"<dc:subject>(.*?)</dc:subject>", m, re.S)
    if kw:
        out["keywords"] = [html.unescape(x.strip()) for x in re.findall(r"<rdf:li[^>]*>(.*?)</rdf:li>", kw.group(1)) if x.strip()]
    d = re.search(r"<dc:description>.*?<rdf:li[^>]*>(.*?)</rdf:li>", m, re.S)
    if d and d.group(1).strip():
        out["description"] = html.unescape(d.group(1).strip())[:300]
    return out


def strip_ns(root):
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


MAX_XML = 4 << 20  # bytes: a fill / preset XML is a few KB; a bigger one is refused, not inflated whole


def zread(z, name, cap=MAX_XML):
    """a zip member, read at most cap bytes: z.read() inflates the whole member, whatever its header says (a missing
    member still raises KeyError)"""
    with z.open(name) as f:
        d = f.read(cap + 1)
    if len(d) > cap:
        raise ValueError(f"{name} is over {cap >> 20} MB")
    return d


def fill_info(z):
    x = strip_ns(ET.fromstring(zread(z, "content/fill.xml")))
    ftype = x.get("type")
    params, extra = [], {"fill_type": ftype}
    fo = x.find("fountain")
    if fo is not None:
        extra["fountain_type"] = fo.get("type")
        for tag in ("angle", "blend", "anisotropic", "steps", "smoothness", "acceleration"):
            e = fo.find(tag)
            if e is not None and e.text:
                n = num(e.text)
                params.append({"name": tag, "key": "fountain." + tag,
                               "type": "number" if n is not None else ("bool" if e.text in ("true", "false") else "string"),
                               "default": n if n is not None else (e.text == "true" if e.text in ("true", "false") else e.text)})
        stops = [{"position": num(c.get("position")), "midpoint": num(c.get("midpoint")), "color": (c.text or "").split(";")[-1]}
                 for c in fo.iter("color")]
        extra["color_stops"] = [{k: v for k, v in s.items() if v is not None} for s in stops]
    ti = x.find("tilingInfo")
    if ti is not None:
        sz = ti.find("size")
        if sz is not None:
            extra["tile_size"] = {"width": num(sz.get("width")), "height": num(sz.get("height")), "units": ti.get("units")}
    return params, extra


def scan_content(root, items, seen_user):
    """Content (install) or Corel Content (user): fills, templates, adjustment presets, find-and-replace, painter brushes,
    image lists, photo frames, export presets, print styles."""
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        r = f.relative_to(root).as_posix()
        top = r.split("/")[0]
        ext = f.suffix.lower()
        user = root == USER_CONTENT
        if user and (R / "Content" / r).exists():
            seen_user[(R / "Content" / r)] = f       # same relative file in the user's content folder: a copy
            continue
        if user and top == "Export Presets" and (R / "Custom Data" / "Export" / f.name).exists():
            seen_user[(R / "Custom Data" / "Export" / f.name)] = f
            continue
        sub = "/".join(r.split("/")[:-1])
        if ext in (".fill", ".cdrt", ".cdss") and zipfile.is_zipfile(f):
            with zipfile.ZipFile(f) as z:
                meta = zcf_meta(z)
                name = meta.get("title") or f.stem
                extra = {"format": ext[1:], "name_source": "META-INF/metadata.xml dc:title" if meta.get("title") else "file name"}
                extra.update({k: v for k, v in meta.items() if k != "title"})
                params, req = [], None
                if ext == ".fill":
                    params, fx = fill_info(z)
                    extra.update(fx)
                    cat, req = "Fill", "vector object (fill)"
                    ev = "zip package parsed: content/fill.xml + META-INF/metadata.xml"
                elif ext == ".cdrt":
                    pages = [n for n in z.namelist() if re.match(r"previews/page\d+\.png$", n)]
                    extra["pages"] = len(pages)
                    try:
                        c = strip_ns(ET.fromstring(zread(z, "color/color.xml")))
                        cm = c.find(".//ColorModel")
                        if cm is not None:
                            extra["color_model"] = cm.text
                    except KeyError:
                        pass
                    cat = "Template"
                    ev = "zip package parsed: META-INF/metadata.xml, previews/page*.png count, color/color.xml"
                else:
                    try:
                        sty = json.loads(zread(z, "styles/document.cdss").decode("utf-8-sig"))
                        extra["styles"] = sty
                    except Exception as e:  # noqa: BLE001
                        extra["styles_error"] = str(e)[:120]
                    cat, req = "Adjustment Preset", "bitmap"
                    ev = "zip package parsed: styles/document.cdss + META-INF/metadata.xml"
                items.append(mk(name, f, cat, ("Corel Content/" if user else "Content/") + sub, params=params,
                                requires=req, evidence=ev, extra=extra))
        elif ext == ".fin":
            items.append(mk(f.stem, f, "Find and Replace Preset", "Content/" + sub, evidence="file name (Find and Replace preset file)",
                            extra={"format": "fin"}))
        elif top == "Painter" and "/Brushes/" in "/" + r and ext == ".xml":
            try:
                txt = f.read_text(encoding="utf-8", errors="replace")
                vn = re.search(r'variant-name="([^"]*)"', txt)
                name = vn.group(1) if vn else f.stem
                attrs = dict(re.findall(r'\b(dab-type|stroke-type|brush-source|pen-type|method|subcategory)="([^"]*)"', txt))
            except Exception:  # noqa: BLE001
                name, attrs = f.stem, {}
            cat_dir = r.split("/")[-2]
            items.append(mk(name, f, "Painterly Brush", "Content/" + sub, requires="open document",
                            evidence="Painter brush definition XML (variant-name, brush-type-parameters)",
                            extra={"format": "painter-brush-xml", "brush_category": cat_dir, "brush_type": attrs}))
        elif top in ("Image Lists", "Photo Frames") and ext == ".cpt":
            items.append(mk(f.stem, f, top[:-1], "Content/" + sub, evidence="file name",
                            extra={"format": "cpt"}))
        elif top == "Export Presets" and ext == ".xml":
            items.append(export_item(f, "Corel Content/Export Presets"))
        elif top == "Print Styles":
            items.append(mk(f.stem, f, "Print Style", "Corel Content/Print Styles", evidence="file name",
                            extra={"format": ext[1:]}))


def export_item(f, path):
    params = []
    try:
        x = ET.parse(f).getroot()
        flat = {}
        for el in x.iter():
            if len(el) == 0 and el.text and el.text.strip():
                flat[el.tag] = el.text.strip()
            for k, v in el.attrib.items():
                flat[f"{el.tag}.{k}"] = v
        params = params_from_dict(flat)
        ev = "export preset XML parsed (every leaf element / attribute)"
    except Exception as e:  # noqa: BLE001
        ev = f"export preset XML unreadable: {e}"
    return mk(f.stem, f, "Export Preset", path, params=params, evidence=ev, extra={"format": "xml"})


# ---------------------------------------------------------------- Draw/Presets/*.pst (property-bar preset lists)
MAX_THUMB = 4 << 20  # bytes a .pst thumbnail may inflate to
PST_KIND = {"Blend": "Blend", "Contour": "Contour", "Distortion": "Distortion", "Envelope": "Envelope",
            "Shadow": "Shadow", "VectorExtrude": "Extrude"}


def pst_info(f):
    b = f.read_bytes()
    n = struct.unpack_from("<H", b, 4)[0]
    cls = b[6:6 + n].decode("ascii", "replace")
    pos = 6 + n
    ver = struct.unpack_from("<I", b, pos)[0]
    sub = struct.unpack_from("<d", b, pos + 4)[0]
    clen = struct.unpack_from("<I", b, pos + 12)[0]
    i = b.find(b"\x78\x5e", pos)
    o = zlib.decompressobj()
    dib = o.decompress(b[i:], MAX_THUMB)  # the largest shipped thumbnail inflates to 66 KB
    if not o.eof:
        raise ValueError(f"thumbnail stream truncated or over {MAX_THUMB >> 20} MB")
    w, h, planes, bpp = struct.unpack_from("<iiHH", dib, 4)
    return {"class": cls, "class_version": ver, "subtype": sub, "thumbnail": f"{w}x{h} {bpp}-bit DIB (zlib, {clen} bytes)",
            "param_bytes": len(o.unused_data)}


def scan_pst(items):
    for f in sorted((R / "Draw" / "Presets").rglob("*.pst")):
        kind = PST_KIND.get(f.parent.name, f.parent.name)
        try:
            info = pst_info(f)
            err = None
        except Exception as e:  # noqa: BLE001
            info, err = {}, f"header unreadable: {e}"
        cat = kind
        if kind == "Shadow":
            cat = "Inner Shadow" if f.stem.startswith("InnerShadow") else "Drop Shadow"
        items.append(mk(f.stem, f, cat + " Preset", "Draw/Presets/" + f.parent.name, requires="vector object",
                        evidence="file header parsed (class name, subtype, zlib thumbnail); the parameter block after the "
                                 "thumbnail is an undocumented binary record, kept as a byte count only",
                        error=err, extra=dict(info, format="pst", name_source="file name")))
    # legacy envelope preset library (one file, many shapes)
    env = R / "Draw" / "Envelope Presets.env"
    if env.exists():
        items.append(mk("Envelope Presets", env, "Envelope Preset Library", "Draw", requires="vector object",
                        evidence="file listed; binary shape records not decoded",
                        error="entry count / names not decoded from the binary .env library",
                        extra={"format": "env", "bytes": env.stat().st_size}))


# ---------------------------------------------------------------- colour palettes
def scan_palettes(items):
    for f in sorted((R / "Color" / "Palettes").rglob("*.xml")):
        try:
            x = ET.parse(f).getroot()
        except Exception as e:  # noqa: BLE001
            items.append(mk(f.stem, f, "Color Palette", "Color/Palettes", error=f"unparseable XML: {e}"))
            continue
        cols = x.find("colors")
        entries, models = [], {}
        for c in (cols.iter("color") if cols is not None else []):
            entries.append(c.get("name") or "")
            models[c.get("cs")] = models.get(c.get("cs"), 0) + 1
        cs = x.find("colorspaces")
        spot = cs is not None and len(cs) > 0
        sub = f.parent.relative_to(R / "Color" / "Palettes").as_posix()
        name = x.get("name")
        extra = {"format": "corel-palette-xml", "guid": x.get("guid"), "resid": x.get("resid"),
                 "color_count": len(entries), "entries": [e for e in entries if e],
                 "unnamed_entries": sum(1 for e in entries if not e), "locked": x.get("locked") == "true",
                 "prefix": x.get("prefix"), "color_models": {k: v for k, v in models.items() if k} if not spot else None,
                 "library": "Spot" if sub.startswith("Spot") else "Process" if sub.startswith("Process") else "My Palettes / default",
                 "name_source": "palette@name" if name else "resid (resolved live, see presets_live.json)"}
        items.append(mk(name or f.stem, f, "Color Palette", "Color/Palettes/" + sub if sub != "." else "Color/Palettes",
                        entry=None, evidence="palette XML parsed (palette@name / colors/page/color@name, cs, tints)",
                        extra={k: v for k, v in extra.items() if v not in (None, "", [])}))


# ---------------------------------------------------------------- Custom Data
def scan_custom_data(items):
    cd = R / "Custom Data"
    # JSON style libraries: one item per named style
    for fn, key, cat, req in (("CalloutPresets.cdss", "style", "Callout Preset", "callout"),
                              ("DimensionPresets.cdss", "style", "Dimension Preset", "dimension line"),
                              ("FountainFills.cdss", "fill", "Fountain Fill Preset", "vector object (fill)"),
                              ("Transparency.cdss", "transparency", "Transparency Preset", "vector object or bitmap")):
        f = cd / fn
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception as e:  # noqa: BLE001
            items.append(mk(fn, f, cat, "Custom Data", error=f"unreadable JSON: {e}"))
            continue
        for sname, sval in (d.get(key) or {}).items():
            items.append(mk(sname, f, cat, "Custom Data/" + fn, entry=sname, requires=req,
                            params=params_from_dict(sval) if isinstance(sval, dict) else [],
                            evidence=f"JSON style sheet parsed: {key}.{sname} (values are the preset's own settings)",
                            extra={"format": "cdss-json", "name_source": "style key in the file"}))
    # export presets
    for f in sorted((cd / "Export").glob("*.xml")):
        items.append(export_item(f, "Custom Data/Export"))
    # print layouts, duotone, tone curves, effect source images
    simple = {"Layouts": ("Imposition Layout", None), "Duotone": ("Duotone Preset", "bitmap"),
              "Tonecrve": ("Tone Curve Preset", "bitmap"), "Bumpmap": ("Bump Map Image", "bitmap"),
              "Canvas": ("Canvas Image", "bitmap"), "Displace": ("Displace Map", "bitmap"),
              "Frame": ("Frame Effect Image", "bitmap"), "Shearmap": ("Shear Map", "bitmap"),
              "Textures": ("Texture Image", "bitmap"), "Brushtxr": ("Brush Texture", "bitmap"),
              "Brushes": ("Brush Image", "bitmap"), "Photo Frames": ("Photo Frame", "bitmap"),
              "Preflight Styles": ("Preflight Style", None)}
    for folder, (cat, req) in simple.items():
        for f in sorted((cd / folder).glob("*")):
            if f.is_file():
                items.append(mk(f.stem, f, cat, "Custom Data/" + folder, requires=req, evidence="file name",
                                extra={"format": f.suffix[1:].lower(), "folder": folder}))
    # libraries with many entries: texture fills, arrowheads
    for fn in ("library.txr", "texture.txr"):
        f = cd / fn
        if not f.exists():
            continue
        secs, cur = {}, None
        for line in f.read_text(encoding="utf-16", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                cur = secs.setdefault(line[1:-1], {})
            elif cur is not None and "=" in line and not line.startswith(";"):
                k, v = line.split("=", 1)
                cur[k.strip()] = v.strip().strip('"')
        libs = {k: [v for kk, v in sec.items() if re.fullmatch(r"T\d+", kk)] for k, sec in secs.items()}
        libs = {k: v for k, v in libs.items() if v}
        items.append(mk(f.stem, f, "Texture Fill Library", "Custom Data", requires="vector object (fill)",
                        evidence="UTF-16 INI parsed: [library] sections with T<n>= texture ids",
                        error="library and texture names are CorelDefaultID_<n> resource ids that only the app resolves; "
                              "no COM member lists them (Fill.ApplyTextureFill takes the resolved names)",
                        invoke={"file": str(f)},
                        extra={"format": "txr-ini", "libraries": libs, "texture_count": sum(map(len, libs.values()))}))
    for fn, cat in (("arrows.end", "Arrowhead Library"),):
        f = cd / fn
        if f.exists():
            items.append(mk(f.stem, f, cat, "Custom Data", requires="vector object" if "txr" in fn else "open path",
                            evidence="file listed; entries come from the live app (presets_live.py)",
                            extra={"format": f.suffix[1:], "bytes": f.stat().st_size}))


# ---------------------------------------------------------------- artistic media strokes
def scan_strokes(items):
    base = R / "Draw" / "CustomMediaStrokes"
    for f in sorted(base.rglob("*")):
        if not f.is_file() or f.suffix.lower() == ".ico":
            continue
        ext = f.suffix.lower()
        folder = f.parent.relative_to(base).as_posix()
        if ext == ".npm":
            mode = "Preset"
        elif ext == ".cmx":
            mode = "Brush"
        else:
            mode = "Sprayer"
        items.append(mk(f.stem, f, f"Artistic Media {mode}", "Draw/CustomMediaStrokes" + ("" if folder == "." else "/" + folder),
                        requires="open path or curve",
                        evidence="file name; mode from the file type (.npm preset stroke, .cmx brush stroke, .cdr sprayer list) "
                                 "and the folder the Artistic Media category list shows",
                        extra={"format": ext[1:], "stroke_category": None if folder == "." else folder, "mode": mode}))


# ---------------------------------------------------------------- Draw folder libraries, colour settings, profiles, workspaces
def scan_misc(items):
    ls = R / "Draw" / "linestyles.dot"
    items.append(mk("Line Styles", ls, "Line Style Library", "Draw", requires="outline",
                    evidence="file listed; dash patterns come from the live app (Application.OutlineStyles)",
                    extra={"format": "dot", "bytes": ls.stat().st_size}))
    ow = R / "Draw" / "outlineWidths.xml"
    txt = ow.read_text(encoding="utf-8", errors="replace")
    body = re.sub(r"<!--.*?-->", "", txt, flags=re.S)
    try:
        x = ET.fromstring(body)
        ents = [{k: v for k, v in el.attrib.items()} | ({"text": el.text.strip()} if el.text and el.text.strip() else {})
                for el in x.iter() if el is not x and (el.attrib or (el.text and el.text.strip()))]
        err = None
    except Exception as e:  # noqa: BLE001
        ents, err = [], f"unparseable: {e}"
    items.append(mk("Outline Widths", ow, "Outline Width Library", "Draw", requires="outline", error=err,
                    evidence="outlineWidths.xml parsed (every element with attributes or text)",
                    extra={"format": "xml", "entries": ents}))
    cs = R / "Color" / "Settings" / "ColorSettings.xml"
    if cs.exists():
        x = ET.parse(cs).getroot()
        for s in x.iter("ColorSettings"):
            nm = (s.findtext("Name") or s.get("id") or "").strip()
            flat = {}
            for el in s.iter():
                if el is s or len(el):
                    continue
                if el.text and el.text.strip():
                    flat[(el.tag + "." + el.get("id")) if el.get("id") else el.tag] = el.text.strip()
            items.append(mk(nm, cs, "Color Management Preset", "Color/Settings/ColorSettings.xml", entry=nm,
                            params=params_from_dict({k: v for k, v in flat.items() if k != "Name"}),
                            evidence="ColorSettings.xml parsed (ColorSettings element)", extra={"format": "xml"}))
    for f in sorted((R / "Color").glob("*.ic[cm]")):
        b = f.read_bytes()
        desc = icc_desc(b)
        items.append(mk(desc or f.stem, f, "Color Profile", "Color",
                        evidence="ICC header + desc tag read from the file",
                        extra={"format": "icc", "color_space": b[16:20].decode("ascii", "replace").strip(),
                               "device_class": b[12:16].decode("ascii", "replace").strip(),
                               "name_source": "ICC desc tag" if desc else "file name"}))
    for f in sorted((R / "Draw" / "Workspace").glob("*.cdws")):
        items.append(mk(f.stem, f, "Workspace", "Draw/Workspace", evidence="file name",
                        extra={"format": "cdws"}))
    up = USER_DATA / "Draw" / "Workspace"
    for f in sorted(up.glob("*.cdws")) if up.exists() else []:
        if not (R / "Draw" / "Workspace" / f.name).exists():
            items.append(mk(f.stem, f, "Workspace", "<UserData>/Draw/Workspace", evidence="file name (user workspace folder)",
                            extra={"format": "cdws", "user": True}))
    tp = R / "Data"
    for f in sorted(tp.glob("*.[tT][pP][lL]")):
        strs = [x.decode("latin-1") for x in re.findall(rb"[ -~]{4,}", f.read_bytes())]
        ok = bool(strs) and strs[0].startswith("Labeler")
        items.append(mk(strs[1] if ok and len(strs) > 1 else f.stem, f, "Label Template Library", "Data",
                        requires="open document",
                        evidence="ASCII records after the 'Labeler V2.0 TPL' header: library title, then one label stock per record"
                        if ok else "file listed", error=None if ok else "unknown .tpl header",
                        extra={"format": "tpl", "header": strs[0] if strs else None, "file_stem": f.stem,
                               "entries": strs[2:] if ok else [], "entry_count": len(strs[2:]) if ok else 0}))
    for d in (USER_DATA / "Custom Data" / "Presets",):
        for f in sorted(d.rglob("*")) if d.exists() else []:
            if f.is_file():
                items.append(mk(f.stem, f, f.parent.name + " Preset (user)", rel(f.parent), evidence="file name (user preset folder)",
                                extra={"format": f.suffix[1:].lower(), "user": True}))


def icc_desc(b):
    try:
        n = struct.unpack_from(">I", b, 128)[0]
        for i in range(n):
            sig, off, ln = struct.unpack_from(">4sII", b, 132 + 12 * i)
            if sig == b"desc":
                t = b[off:off + 4]
                if t == b"desc":
                    k = struct.unpack_from(">I", b, off + 8)[0]
                    return b[off + 12:off + 12 + k].split(b"\0")[0].decode("latin-1").strip()
                if t == b"mluc":
                    cnt, sz = struct.unpack_from(">II", b, off + 8)
                    l, o = struct.unpack_from(">II", b, off + 16 + 4)
                    return b[off + o:off + o + l].decode("utf-16-be").strip("\0 ")
    except Exception:  # noqa: BLE001
        return None
    return None


# ---------------------------------------------------------------- live merge
def merge_live(items, live):
    """Apply what presets_live.py read from the running app."""
    pals = {Path(p["file"]).resolve().as_posix().lower(): p for p in live.get("palettes", []) if p.get("file")}
    for it in items:
        if it["category"] == "Color Palette":
            p = pals.get(Path(it["invoke"]["file"]).resolve().as_posix().lower())
            if not p:
                continue
            ex = it["extra"]
            if p.get("name") and p["name"] != it["name"]:
                ex["file_stem"] = it["name"]
                it["name"] = p["name"]
                ex["name_source"] = "live PaletteManager.GetPalette(i).Name"
            ex["live"] = {k: p[k] for k in ("identifier", "color_count", "type", "locked", "index") if k in p}
            if p.get("entries") and (ex.get("unnamed_entries") or not ex.get("entries")):
                ex["entries"] = p["entries"]
                ex.pop("unnamed_entries", None)
                ex["entries_source"] = "live Palette.Color(i).Name"
            it["invoke"]["cdr_com"] = f'Application.PaletteManager.GetPalette("{p.get("identifier") or p.get("name")}")'
            it["evidence"] += "; name, colour count and entries confirmed live (Application.PaletteManager)"
    for lib, key in (("arrows.end", "arrowheads"), ("linestyles.dot", "outline_styles")):
        rows = live.get(key)
        if rows is None:
            continue
        for it in items:
            if it["invoke"]["file"].endswith(lib):
                it["extra"]["entries"] = rows
                it["extra"]["entry_count"] = len(rows)
                it.pop("error", None)
                it["evidence"] = f"entries read live (Application.{'ArrowHeads' if key == 'arrowheads' else 'OutlineStyles'})"
                it["invoke"]["cdr_com"] = "Application.ArrowHeads.Item(i)" if key == "arrowheads" else "Application.OutlineStyles.Item(i)"
    ws = live.get("workspaces")
    if ws:
        names = {w.get("name") for w in ws}
        for it in items:
            if it["category"] == "Workspace":
                it["extra"]["listed_live"] = it["name"] in names
        it_names = {it["name"] for it in items if it["category"] == "Workspace"}
        for w in ws:
            if w.get("name") and w["name"] not in it_names:
                items.append({"name": w["name"], "id": "<Workspaces>#" + w["name"], "path": "Window/Workspace",
                              "category": "Workspace", "invoke": {"cdr_com": f'Application.Workspaces.Item("{w["name"]}").Activate'},
                              "evidence": "live Application.Workspaces", "extra": {k: v for k, v in w.items() if k != "name"}})
    # live preset lists: add each entry as an item, unless a file item already IS that preset (then confirm it)
    papers = {}
    try:
        for el in ET.parse(R / "Config" / "PaperTypes.xml").getroot().iter("size"):
            if el.get("width"):
                papers[el.get("name")] = el
    except Exception:  # noqa: BLE001
        pass
    by_cat = {}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)
    confirm = {"Color Management Preset (dialog)": ("Color Management Preset", lambda it: it["name"].lower()),
               "Find and Replace Preset (docker)": ("Find and Replace Preset",
                                                    lambda it: it["name"].lower().removeprefix("find ").strip())}
    for row in live.get("ds_lists", []):
        if not row.get("entries") or "Category" in row["category"]:
            continue
        cat = row["category"]
        src = f'live data source list {row["ds"]}.{row["path"]}' + (f' ({row["context"]})' if row.get("context") else "")
        targets = {}
        if cat in confirm:
            fcat, key = confirm[cat]
            targets = {key(it): it for it in by_cat.get(fcat, [])}
        for e in row["entries"]:
            if e["text"] == "Custom":      # the list's own 'custom settings' slot, not a preset
                continue
            t = targets.get(e["text"].lower())
            if t is not None:
                if t["name"] != e["text"]:
                    t.setdefault("extra", {})["file_stem"] = t["name"]
                    t["name"] = e["text"]
                    t["extra"]["name_source"] = "live list " + row["ds"] + "." + row["path"]
                t["evidence"] += "; listed live by " + row["ds"] + "." + row["path"]
                continue
            it = {"name": e["text"], "id": f'<{row["ds"]}.{row["path"]}>#{e["text"]}' + (f'#{e["guid"]}' if e.get("dup") else ""),
                  "path": effect_path(row), "category": cat, "requires": row.get("requires"), "evidence": src,
                  "extra": {k: v for k, v in e.items() if k not in ("text", "dup")} | {"data_source": row["ds"], "list_path": row["path"]}}
            if it["path"] == row["ui_path"] and row["ui_path"].startswith("Effects/") and row["ds"].endswith("EffectDS")                     and row["ds"] not in ("NNArtStyleEffectDS", "BevelFactoryEffectDS"):
                it["extra"]["path_note"] = ("no Effects-menu item uses " + row["ds"] + " in the live menu walk: "
                                            "a Properties/Effects-docker effect; the path is a label, not a menu path")
            pt = papers.get(e["text"])
            if pt is not None:
                it["params"] = [{"name": k, "key": k, "type": "number", "default": num(pt.get(k)), "unit": pt.get("units")}
                                for k in ("width", "height")]
                it["evidence"] += "; size from Config/PaperTypes.xml"
            if not it["requires"]:
                it.pop("requires")
            items.append(it)



_EFFECT_PATHS = None


def effect_path(row):
    """UI path of a live list. The generated 'Effects/<label>/Preset' paths were guesses (audit 2026-10-04: Channel
    Mixer lives under Effects/Adjust, Shear under Effects/Distort ...): use the real menu path of the effect whose
    data source owns the list, read from cdr_effect.json; a data source with no Effects-menu entry keeps its label path
    and says so in extra.path_note."""
    global _EFFECT_PATHS
    if _EFFECT_PATHS is None:
        try:
            ef = json.loads((PGD / "harvest" / "cdr" / "cdr_effect.json").read_text(encoding="utf-8"))["items"]
            _EFFECT_PATHS = {(it.get("extra") or {}).get("data_source"): it["path"] for it in ef
                             if (it.get("extra") or {}).get("data_source")}
        except Exception:  # noqa: BLE001
            _EFFECT_PATHS = {}
    p = _EFFECT_PATHS.get(row["ds"])
    return p + "/Preset" if p and row["ui_path"].startswith("Effects/") else row["ui_path"]


# Preset libraries the first build missed (independent file audit 2026-10-04, tools/cdr/audit_files.py): listed by file,
# contents not decoded, so no params and no invented entry names.
AUDIT_EXTRAS = [
    ("Custom Data/patterns.bpt", "Two-Color Pattern Library", "vector object (fill)",
     "two-color bitmap pattern library (binary, entries not decoded)"),
    ("Content/Painter/Resources/24.0/Papers/Default Papers/Default.paper", "Painterly Paper Library", "open document",
     "Painterly Brush paper texture library (Painter resource, entries not decoded)"),
    ("Content/Painter/Resources/24.0/Gradients/Default Gradients/Default.gradient", "Painterly Gradient Library",
     "open document", "Painterly Brush gradient library (Painter resource, entries not decoded)"),
    ("Content/Painter/Resources/24.0/Flow Maps/Default Flow Maps/Default.flowmap", "Painterly Flow Map Library",
     "open document", "Painterly Brush flow map library (Painter resource, entries not decoded)"),
    ("Content/Painter/Resources/24.0/Color Sets/Default.colors", "Painterly Color Set", "open document",
     "Painterly Brush color set (Painter resource, entries not decoded)"),
]


def scan_audit_extras(items):
    have = {it.get("invoke", {}).get("file", "").lower() for it in items}
    for rel, cat, req, what in AUDIT_EXTRAS:
        f = R / rel
        if not f.exists() or str(f).lower() in have:
            continue
        items.append({"name": f.stem, "id": f"{rel}#{f.stem}", "path": str(Path(rel).parent.as_posix()),
                      "category": cat, "invoke": {"file": str(f)}, "requires": req,
                      "evidence": "file listed (independent audit of the install folders); " + what,
                      "extra": {"bytes": f.stat().st_size, "decoded": False}})

def build():
    items, seen_user = [], {}
    scan_pst(items)
    scan_palettes(items)
    scan_content(R / "Content", items, seen_user)
    if USER_CONTENT.exists():
        scan_content(USER_CONTENT, items, seen_user)
    scan_custom_data(items)
    scan_strokes(items)
    scan_misc(items)
    scan_audit_extras(items)
    for it in items:   # user-folder copies of install content
        f = Path(it.get("invoke", {}).get("file", ""))
        if f in seen_user:
            it.setdefault("extra", {})["user_copy"] = str(seen_user[f])
    ver = "25.1.0.269"
    av = PGD / "work" / "cdr" / "app_version.json"
    if av.exists():
        try:
            ver = json.loads(av.read_text(encoding="utf-8")).get("version") or ver
        except Exception:  # noqa: BLE001
            pass
    live = json.loads(LIVE.read_text(encoding="utf-8")) if LIVE.exists() else {}
    if live:
        merge_live(items, live)
        ver = live.get("version") or ver
    # audit 2026-10-04: FountainFills.cdss keys are resource ids (CorelDefaultID_<n>); the app shows resolved names that
    # no file, language DLL string table (LoadString on Languages/EN/Programs/*.dll returned nothing) or COM call gave us
    for it in items:
        if it["name"].startswith("CorelDefaultID_") and not it.get("error"):
            it["error"] = ("name is the file's resource id, not the display name the app shows: the id did not resolve "
                           "through the language DLL string tables and no COM call lists fountain fill presets")
    # ids must be unique: a repeated name inside one file gets its ordinal
    seen = {}
    for it in items:
        if it["id"] in seen:
            seen[it["id"]] += 1
            it["id"] += f"~{seen[it['id']]}"
        else:
            seen[it["id"]] = 1
    src = ("CorelDRAW 2024 install + user content folders parsed by tools/cdr/harvest_presets.py"
           + ("; names / entries / lists confirmed live by tools/cdr/presets_live.py" if live else ""))
    return {"app": "CDR", "kind": "cdr_preset", "app_version": ver, "source": src, "items": items}


def selftest():
    assert rel(R / "Draw" / "Presets" / "Blend" / "Blend1.pst") == "Draw/Presets/Blend/Blend1.pst"
    assert rel(USER_CONTENT / "x" / "y.fill") == "<UserContent>/x/y.fill"
    p = params_from_dict({"uniformTransparency": "0.05", "fill": {"type": "1"}, "primaryColor": "RGB255,USER,1,2,3"})
    assert p[0]["default"] == 0.05 and p[1]["key"] == "fill.type" and p[2]["type"] == "color", p
    info = pst_info(R / "Draw" / "Presets" / "Shadow" / "DropShadow1.pst")
    assert info["class"] == "CDropShadowPresetInfo" and info["thumbnail"].startswith("147x149"), info
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
        sys.exit(0)
    doc = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    from collections import Counter
    print(len(doc["items"]), "items ->", OUT)
    for k, v in sorted(Counter(i["category"] for i in doc["items"]).items()):
        print(f"  {v:5d} {k}")
