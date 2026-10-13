"""Parsers for Photoshop preset files (no Photoshop needed). Each parse_* returns a list of entry dicts
{"name", "zstring"?, ...}. Formats are read structurally; every parser is checked by selftest() against the
installed Photoshop 2026 files.

    import sys; sys.path.insert(0, r"<PGD_HOME>/tools/ps"); import presetfiles as pf
    pf.parse_file(r"C:/Program Files/Adobe/Adobe Photoshop 2026/Required/Default Gradients.grd")
"""
import re, struct
from pathlib import Path

INSTALL = Path(r"C:/Program Files/Adobe/Adobe Photoshop 2026")


def zlabel(s):
    """'$$$/Presets/Patterns/TreeTile4=Tree Tile 4' -> 'Tree Tile 4' (plain names pass through)."""
    s = (s or "").rstrip("\x00")
    return s.split("=", 1)[1] if s.startswith("$$$/") and "=" in s else s


class R:
    """Big-endian reader."""
    def __init__(self, b, p=0):
        self.b, self.p = b, p

    def take(self, n):
        v = self.b[self.p:self.p + n]
        if len(v) < n:
            raise EOFError(f"need {n} bytes at {self.p}")
        self.p += n
        return v

    def u8(self): return self.take(1)[0]
    def u16(self): return struct.unpack(">H", self.take(2))[0]
    def i16(self): return struct.unpack(">h", self.take(2))[0]
    def u32(self): return struct.unpack(">I", self.take(4))[0]
    def i32(self): return struct.unpack(">i", self.take(4))[0]
    def f64(self): return struct.unpack(">d", self.take(8))[0]
    def i64(self): return struct.unpack(">q", self.take(8))[0]
    def os(self): return self.take(4).decode("latin-1")

    def ustr(self):
        n = self.u32()
        return self.take(2 * n).decode("utf-16-be", "replace").rstrip("\x00")

    def pstr(self):
        return self.take(self.u8()).decode("latin-1")

    def key(self):
        n = self.u32()
        return self.take(n or 4).decode("latin-1")

    def align(self, k=4):
        self.p += (-self.p) % k

    # ---- Action Manager descriptors (version 16 body) ----
    def desc(self):
        o = {"_class": self.ustr(), "_classID": self.key()}
        for _ in range(self.u32()):
            k = self.key()
            o[k] = self.val(self.os())
        return o

    def val(self, t):
        if t in ("Objc", "GlbO"): return self.desc()
        if t == "VlLs": return [self.val(self.os()) for _ in range(self.u32())]
        if t == "doub": return self.f64()
        if t == "UntF": u = self.os(); return {"unit": u, "v": self.f64()}
        if t == "UnFl": u = self.os(); return {"unit": u, "v": [self.f64() for _ in range(self.u32())]}
        if t == "TEXT": return self.ustr()
        if t == "enum": tp = self.key(); return {"enum": tp, "v": self.key()}
        if t == "long": return self.i32()
        if t == "comp": return self.i64()
        if t == "bool": return bool(self.u8())
        if t in ("type", "GlbC"): self.ustr(); return {"class": self.key()}
        if t in ("alis", "tdta", "Pth "): return {"raw": t, "len": len(self.take(self.u32()))}
        if t == "obj ": return {"ref": [self.refitem() for _ in range(self.u32())]}
        if t == "ObAr":  # .atn: count, class, items; elsewhere a version word (16) comes first
            p0 = self.p
            for skip in (0, 4):
                self.p = p0 + skip
                try:
                    n = self.u32(); self.ustr(); self.key(); out = {}
                    for _ in range(self.u32()):
                        k = self.key(); tt = self.os()
                        if tt not in ("UnFl", "doub", "UntF", "long", "TEXT", "enum", "bool"):
                            raise ValueError(tt)
                        out[k] = self.val(tt)
                    return {"objarray": n, "v": out}
                except Exception:  # noqa: BLE001
                    continue
            raise ValueError(f"unparsed ObAr at {p0}")
        raise ValueError(f"unknown descriptor type {t!r} at {self.p}")

    def refitem(self):
        t = self.os()
        if t == "prop": self.ustr(); return ("prop", self.key(), self.key())
        if t == "Clss": self.ustr(); return ("class", self.key())
        if t == "Enmr": self.ustr(); return ("enum", self.key(), self.key(), self.key())
        if t == "rele": self.ustr(); return ("rel", self.key(), self.i32())
        if t in ("Idnt", "indx"): self.ustr(); return (t, self.key(), self.u32())
        if t == "name": self.ustr(); return ("name", self.key(), self.ustr())
        raise ValueError(f"unknown reference form {t!r}")


def _d16(r):
    v = r.u32()
    if v != 16:
        raise ValueError(f"descriptor version {v} at {r.p - 4}")
    return r.desc()


def sections(b, p):
    """'8BIM' + key + u32 length sections (abr v6+, tpl)."""
    r, out = R(b, p), {}
    while r.p + 12 <= len(b):
        sig = r.os()
        if sig != "8BIM":
            break
        k, n = r.os(), r.u32()
        out[k] = (r.p, n)
        r.p += n
        if b[r.p:r.p + 4] != b"8BIM":
            r.align(4)
    return out


def _named(objs, extra_fn=None):
    out = []
    for o in objs:
        nm = o.get("Nm  ", "") if isinstance(o, dict) else ""
        e = {"name": zlabel(nm)}
        if nm.startswith("$$$/"):
            e["zstring"] = nm
        if extra_fn:
            e.update(extra_fn(o))
        out.append(e)
    return out


# ---------------------------------------------------------------- brushes / tool presets
def _brush_extra(o):
    b, x = o.get("Brsh") or {}, {}
    if isinstance(b, dict):
        x["brush_class"] = b.get("_classID")
        d = b.get("Dmtr")
        if isinstance(d, dict):
            x["diameter_px"] = d.get("v")
        for k, nm in (("Hrdn", "hardness_pct"), ("Spcn", "spacing_pct"), ("Angl", "angle_deg"), ("Rndn", "roundness_pct")):
            v = b.get(k)
            if isinstance(v, dict):
                x[nm] = v.get("v")
        if b.get("sampledData"):
            x["sampled_data_id"] = b["sampledData"]
    for k, nm in (("useTipDynamics", "tip_dynamics"), ("useScatter", "scatter"), ("useTexture", "texture"),
                  ("usePaintDynamics", "transfer"), ("useColorDynamics", "color_dynamics"), ("dualBrush", None)):
        if k in o and nm and o[k]:
            x[nm] = True
    return x


def parse_abr(b):
    r = R(b)
    ver, sub = r.u16(), r.u16()
    if ver < 6:
        raise ValueError(f"abr version {ver} (only v6+ parsed)")
    sec = sections(b, 4)
    p, n = sec["desc"]
    d = _d16(R(b, p))
    return _named(d.get("Brsh", []), _brush_extra), {"abr_version": f"{ver}.{sub}", "sections": sorted(sec)}


def _tool_extra(o):
    x = {}
    t = o.get("Type")
    if isinstance(t, dict):
        x["tool"] = t.get("class")
    return x


def parse_tpl(b):
    r = R(b)
    if r.os() != "8BTP":
        raise ValueError("not 8BTP")
    hdr = (r.u32(), r.u32())
    sec = sections(b, 12)
    p, n = sec["tptp"]
    r = R(b, p)
    out = []
    for _ in range(r.u32()):
        nm = r.ustr()
        d = _d16(r)
        e = {"name": zlabel(nm), "tool": d.get("_classID")}
        if nm.startswith("$$$/"):
            e["zstring"] = nm
        out.append(e)
    return out, {"tpl_header": list(hdr), "sections": sorted(sec)}


# ---------------------------------------------------------------- gradients
def _hex(c):
    if not isinstance(c, dict):
        return None
    if c.get("_classID") == "RGBC":
        rgb = [c.get("Rd  "), c.get("Grn ") if "Grn " in c else c.get("Grn"), c.get("Bl  ")]
        if all(isinstance(v, (int, float)) for v in rgb):
            return "#%02X%02X%02X" % tuple(max(0, min(255, round(v))) for v in rgb)
    keys = {k: v for k, v in c.items() if not k.startswith("_")}
    return {c.get("_classID"): {k: (round(v, 2) if isinstance(v, float) else v) for k, v in keys.items()}}


def _grad_extra(o):
    g = o.get("Grad") or {}
    x = {"gradient_form": (g.get("GrdF") or {}).get("v")}
    stops = []
    for s in g.get("Clrs") or []:
        if isinstance(s, dict):
            c = s.get("Clr ")
            st = {"location": s.get("Lctn"), "midpoint": s.get("Mdpn")}
            st["color"] = _hex(c) if c else (s.get("Type") or {}).get("v")
            stops.append(st)
    if stops:
        x["color_stops"] = stops
    tr = [{"location": t.get("Lctn"), "opacity_pct": (t.get("Opct") or {}).get("v")} for t in g.get("Trns") or []
          if isinstance(t, dict)]
    if tr:
        x["opacity_stops"] = tr
    if isinstance(g.get("Intr"), float):
        x["smoothness"] = g["Intr"]
    return x


def parse_grd(b):
    r = R(b)
    if r.os() != "8BGR":
        raise ValueError("not 8BGR")
    v = r.u16()
    if v != 5:
        raise ValueError(f"grd version {v}")
    d = _d16(r)
    out = []
    for o in d.get("GrdL", []):
        e = {"name": zlabel((o.get("Grad") or {}).get("Nm  ", ""))}
        z = (o.get("Grad") or {}).get("Nm  ", "")
        if z.startswith("$$$/"):
            e["zstring"] = z
        e.update(_grad_extra(o))
        out.append(e)
    return out, {"grd_version": v}


# ---------------------------------------------------------------- patterns
def _patterns(r, count, end=None):
    out = []
    for _ in range(count):
        start = r.p
        ver, mode, h, w = r.u32(), r.u32(), r.u16(), r.u16()
        nm, pid = r.ustr(), r.pstr()
        if mode == 2:
            r.take(768 + 4)
        vver, vlen = r.u32(), r.u32()
        if vver != 3:
            raise ValueError(f"pattern VMAL version {vver} at {r.p - 8}")
        r.p += vlen
        e = {"name": zlabel(nm), "width": w, "height": h, "image_mode_code": mode, "pattern_id": pid}
        if nm.startswith("$$$/"):
            e["zstring"] = nm
        out.append(e)
        if end is not None and r.p >= end:
            break
    return out


def parse_pat(b):
    r = R(b)
    if r.os() != "8BPT":
        raise ValueError("not 8BPT")
    v, n = r.u16(), r.u32()
    return _patterns(r, n), {"pat_version": v, "declared_count": n}


# ---------------------------------------------------------------- layer styles
FX = {"DrSh": "Drop Shadow", "IrSh": "Inner Shadow", "OrGl": "Outer Glow", "IrGl": "Inner Glow",
      "ebbl": "Bevel & Emboss", "ChFX": "Satin", "SoFi": "Color Overlay", "GrFl": "Gradient Overlay",
      "patternFill": "Pattern Overlay", "FrFX": "Stroke", "dropShadowMulti": "Drop Shadow",
      "innerShadowMulti": "Inner Shadow", "solidFillMulti": "Color Overlay", "gradientFillMulti": "Gradient Overlay",
      "frameFXMulti": "Stroke"}


def _fx_list(styl):
    lefx = styl.get("Lefx") or {}
    on = []
    for k, v in lefx.items():
        if k.startswith("_"):
            continue
        for one in (v if isinstance(v, list) else [v]):
            if isinstance(one, dict) and one.get("enab", True) and k in FX and FX[k] not in on:
                on.append(FX[k])
    return on


def parse_asl(b):
    r = R(b)
    v1, sig, v2 = r.u16(), r.os(), r.u16()
    if sig != "8BSL":
        raise ValueError("not 8BSL")
    plen = r.u32()
    pstart = r.p
    r.p = pstart + plen
    n = r.u32()
    out = []
    for _ in range(n):
        ln = r.u32()
        start = r.p
        meta = _d16(r)
        styl = _d16(r)
        nm = meta.get("Nm  ", "")
        e = {"name": zlabel(nm), "style_id": meta.get("Idnt"), "effects": _fx_list(styl)}
        bo = styl.get("blendOptions")
        if isinstance(bo, dict) and isinstance(bo.get("fillOpacity"), dict):
            e["fill_opacity_pct"] = bo["fillOpacity"].get("v")
        if nm.startswith("$$$/"):
            e["zstring"] = nm
        out.append(e)
        r.p = start + ln
        r.align(4)
    return out, {"asl_version": [v1, v2], "embedded_patterns_bytes": plen}


# ---------------------------------------------------------------- custom shapes
def parse_csh(b):
    r = R(b)
    if r.os() != "cush":
        raise ValueError("not cush")
    v, n = r.u32(), r.u32()
    out = []
    for _ in range(n):
        nm = r.ustr()
        r.align(4)
        r.u32()                      # record version (1)
        ln = r.u32()
        e = {"name": zlabel(nm)}
        # record body: "$" + 36-char uuid with no terminator, then top/left/bottom/right as int32 and the path data.
        # Cutting at the first NUL (the 2026-10-04 code) appended the bound bytes to the id of every shape whose top
        # bound does not start with a zero byte (90 shapes: Arrow 5, Light Bulb 2 ...); csh_bounds in preset_gallery.py
        # reads the same 37 bytes
        sid = b[r.p:r.p + 37]
        if sid[:1] == b"$" and sid[9:10] == b"-":
            e["shape_id"] = sid.decode("ascii")
        if nm.startswith("$$$/"):
            e["zstring"] = nm
        out.append(e)
        r.p += ln
        r.align(4)
    return out, {"csh_version": v, "declared_count": n}


# ---------------------------------------------------------------- contours (record layout varies: ZString scan)
ZS = re.compile(rb"((?:\x00[\x20-\x7e]){4,}|(?:[\x01-\xff][\x00-\xff](?=\x00\x00)))")


def zstrings_utf16(b, prefix):
    """Every UTF-16BE string in the file that starts with prefix (e.g. '$$$/Contours/'), in file order."""
    pat = prefix.encode("utf-16-be")
    out, i = [], b.find(pat)
    while i >= 0:
        j = i
        while j + 1 < len(b) and b[j:j + 2] != b"\x00\x00":
            j += 2
        out.append(b[i:j].decode("utf-16-be", "replace"))
        i = b.find(pat, j)
    return out


def parse_shc(b):
    if b[:4] != b"8BFS":
        raise ValueError("not 8BFS")
    n = struct.unpack(">I", b[6:10])[0]
    zs = zstrings_utf16(b, "$$$/")
    return [{"name": zlabel(z), "zstring": z} for z in zs], {"declared_count": n,
                                                            "method": "UTF-16 ZString scan (record layout varies)"}


# ---------------------------------------------------------------- swatches / color books
def _aco_color(sp, w):
    if sp == 0:
        return "#%02X%02X%02X" % tuple(x // 257 for x in w[:3])
    if sp == 1:
        return {"HSB": [round(w[0] / 182.04), round(w[1] / 655.35), round(w[2] / 655.35)]}
    if sp == 2:
        return {"CMYK": [round((65535 - x) / 655.35) for x in w]}
    if sp == 7:
        return {"Lab": [round(w[0] / 100), struct.unpack(">h", struct.pack(">H", w[1]))[0] / 100,
                        struct.unpack(">h", struct.pack(">H", w[2]))[0] / 100]}
    if sp == 8:
        return {"Gray": round(w[0] / 100)}
    return {"space": sp, "raw": list(w)}


def parse_aco(b):
    r = R(b)
    v, n = r.u16(), r.u16()
    if v == 1:
        cols = []
        for _ in range(n):
            sp = r.u16()
            cols.append(_aco_color(sp, [r.u16() for _ in range(4)]))
        if r.p >= len(b):
            return [{"name": "", "color": c} for c in cols], {"aco_version": 1, "count": n,
                                                             "note": "version-1 file: colors only, no names"}
        v2, n2 = r.u16(), r.u16()
    else:
        v2, n2 = v, n
    out = []
    for _ in range(n2):
        sp = r.u16()
        w = [r.u16() for _ in range(4)]
        nm = r.ustr()
        out.append({"name": zlabel(nm), "color": _aco_color(sp, w)})
    return out, {"aco_version": v2, "count": n2}


def parse_acb(b):
    r = R(b)
    if r.os() != "8BCB":
        raise ValueError("not 8BCB")
    ver, bid = r.u16(), r.u16()
    title, pre, post, desc = r.ustr(), r.ustr(), r.ustr(), r.ustr()
    n, page, pkey, sp = r.u16(), r.u16(), r.u16(), r.u16()
    w = 4 if sp == 2 else 3
    cols = []
    for _ in range(n):
        nm = r.ustr()
        code = r.take(6).decode("latin-1").strip()
        comp = list(r.take(w))
        cols.append({"name": zlabel(pre) + zlabel(nm) + zlabel(post) if nm else "", "code": code, "comp": comp})
    meta = {"book_id": bid, "title": zlabel(title), "prefix": zlabel(pre), "postfix": zlabel(post),
            "description": zlabel(desc), "page_size": page, "color_space": {0: "RGB", 2: "CMYK", 7: "Lab"}.get(sp, sp),
            "count": n}
    return cols, meta


# ---------------------------------------------------------------- actions
def parse_atn(b):
    r = R(b)
    v = r.u32()
    if v != 16:
        raise ValueError(f"atn version {v}")
    set_name = r.ustr()
    r.u8()
    out, n = [], r.u32()
    try:
        _atn_actions(r, n, set_name, out)
        return out, {"set": zlabel(set_name), "set_zstring": set_name if set_name.startswith("$$$/") else None}
    except Exception as e:  # noqa: BLE001  structural parse stopped: recover the remaining names by ZString scan
        err = f"structural parse stopped after {len(out)} of {n} actions: {e}"
    prefix = set_name.split("=", 1)[0].rsplit("/", 1)[0] + "/" if set_name.startswith("$$$/") else None
    if prefix:
        seen = {x.get("zstring") for x in out}
        for z in zstrings_utf16(b, prefix):
            if z != set_name and z not in seen and "=" in z and len(out) < n:
                out.append({"name": zlabel(z), "set": zlabel(set_name), "zstring": z, "steps_error": err})
                seen.add(z)
    return out, {"set": zlabel(set_name), "declared_actions": n, "parse_error": err}


def _atn_actions(r, n, set_name, out):
    for _ in range(n):
        fkey, shift, cmd, color = r.u16(), r.u8(), r.u8(), r.u16()
        nm = r.ustr()
        r.u8()
        steps = []
        for _ in range(r.u32()):
            r.u8(); enabled = r.u8(); dlg = r.u8(); r.u8()
            t = r.os()
            ev = r.take(r.u32()).decode("latin-1") if t == "TEXT" else r.take(4).decode("latin-1")
            disp = r.take(r.u32()).decode("latin-1")
            if r.i32() == -1:
                r.desc()  # no version word inside .atn
            steps.append(disp or ev)
        e = {"name": zlabel(nm), "set": zlabel(set_name), "steps": steps}
        if nm.startswith("$$$/"):
            e["zstring"] = nm
        if fkey:
            e["function_key"] = f"F{fkey}" + (" +Shift" if shift else "") + (" +Ctrl" if cmd else "")
        out.append(e)


# ---------------------------------------------------------------- adjustment presets with simple layouts
def parse_acv(b):
    r = R(b)
    v, n = r.u16(), r.u16()
    curves = []
    for _ in range(n):
        pts = r.u16()
        curves.append([[r.u16(), r.u16()][::-1] for _ in range(pts)])  # stored (output, input) -> [input, output]
    names = ["composite", "red", "green", "blue"]
    return [], {"acv_version": v, "curves": {names[i] if i < 4 else f"curve{i}": c for i, c in enumerate(curves)
                                             if not (len(c) == 2 and c == [[0, 0], [255, 255]])}}


def parse_alv(b):
    r = R(b)
    v = r.u16()
    recs = []
    for i in range(4):
        a = [r.u16() for _ in range(5)]
        recs.append({"input": [a[0], a[1]], "output": [a[2], a[3]], "gamma": a[4] / 100})
    ident = {"input": [0, 255], "output": [0, 255], "gamma": 1.0}
    return [], {"alv_version": v, "levels": {n: x for n, x in zip(["composite", "red", "green", "blue"], recs)
                                             if x != ident}}


def parse_ahu(b):
    r = R(b)
    v, colorize = r.u16(), r.u8()
    r.u8()
    cz = [r.i16() for _ in range(3)]
    master = [r.i16() for _ in range(3)]
    x = {"ahu_version": v, "colorize": bool(colorize), "master_hue_sat_light": master}
    if colorize:
        x["colorize_hue_sat_light"] = cz
    ranges = {}
    for nm in ("reds", "yellows", "greens", "cyans", "blues", "magentas"):
        rng = [r.i16() for _ in range(4)]
        hsl = [r.i16() for _ in range(3)]
        if any(hsl):
            ranges[nm] = {"range": rng, "hue_sat_light": hsl}
    if ranges:
        x["ranges"] = ranges
    return [], x


ADO_SPACE = {0: "RGB", 1: "HSB", 2: "CMYK", 3: "Pantone", 4: "Focoltone", 5: "Trumatch", 6: "Toyo", 7: "Lab",
             8: "Gray", 10: "HKS", 11: "DIC"}
ADO_TONES = (0, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100)


def parse_ado(b):
    """.ado (Duotone / Tritone / Quadtone options, 524 bytes): u16 version, u16 ink count, 4 x ink colour (u16 colour
    space + 8 bytes: CMYK / RGB as u16 words, a colour-book ink as its ASCII code), 4 x Pascal ink name in 64 bytes
    from 0x2c, 4 x transfer curve from 0x12c (13 x u16 tenths of a percent at 0, 5, 10, 20 ... 90, 95, 100 % tone,
    0xFFFF = no point, + a u16 flag). Checked on the 114 shipped files (2026-10-13: every ink is CMYK or Pantone; the
    Lab / Gray / HSB branches decode as in .aco and are untested on an .ado). Returns ([], meta) like the other single-
    preset formats; meta["inks"][i] = {"name", "space", "value"}, meta["curves"][i] = {tone %: ink %}."""
    if len(b) < 0x12c + 4 * 28:
        raise ValueError(f"ado too short ({len(b)} bytes)")
    ver, n = struct.unpack_from(">HH", b, 0)
    if not 1 <= n <= 4:
        raise ValueError(f"ado ink count {n}")
    inks, curves = [], []
    for i in range(n):
        sp, *w = struct.unpack_from(">H4H", b, 4 + 10 * i)
        if sp == 2:
            val = [round((65535 - x) / 655.35, 1) for x in w]
        elif sp == 0:
            val = [round(x / 257) for x in w[:3]]
        elif sp in (1, 7, 8):
            (_, val), = _aco_color(sp, w).items()
        else:
            val = b[6 + 10 * i:14 + 10 * i].decode("latin-1").strip("\x00 ")
        o = 0x2c + 64 * i
        inks.append({"name": b[o + 1:o + 1 + b[o]].decode("latin-1"), "space": ADO_SPACE.get(sp, sp), "value": val})
        v = struct.unpack_from(">13H", b, 0x12c + 28 * i)
        curves.append({t: x / 10 for t, x in zip(ADO_TONES, v) if x != 0xFFFF})
    return [], {"ado_version": ver, "inks": inks, "curves": curves}


PARSERS = {".abr": parse_abr, ".tpl": parse_tpl, ".grd": parse_grd, ".pat": parse_pat, ".asl": parse_asl,
           ".csh": parse_csh, ".shc": parse_shc, ".aco": parse_aco, ".acb": parse_acb, ".atn": parse_atn,
           ".acv": parse_acv, ".alv": parse_alv, ".ahu": parse_ahu, ".ado": parse_ado}


def hierarchy(b):
    """The preset-group tree stored in a trailing '8BIMphry' section: list of group paths, one per preset, in order.
    None when the file has no hierarchy section."""
    i = b.rfind(b"8BIMphry")
    if i < 0:
        return None
    d = _d16(R(b, i + 12))
    stack, out = [], []
    for h in d.get("hierarchy", []):
        c = h.get("_classID") if isinstance(h, dict) else None
        if c == "Grup":
            stack.append(zlabel(h.get("Nm  ", "")))
        elif c == "groupEnd":
            stack and stack.pop()
        elif c == "preset":
            out.append("/".join(stack))
    return out


def parse_file(p):
    p = Path(p)
    b = p.read_bytes()
    ents, meta = PARSERS[p.suffix.lower()](b)
    try:
        groups = hierarchy(b) if ents else None
    except Exception as e:  # noqa: BLE001
        groups, meta["hierarchy_error"] = None, str(e)
    if groups is not None:
        meta["hierarchy_presets"] = len(groups)
        if len(groups) == len(ents):
            for e, g in zip(ents, groups):
                if g:
                    e["group"] = g
        else:
            meta["hierarchy_error"] = f"{len(groups)} presets in hierarchy vs {len(ents)} parsed: groups not applied"
    return ents, meta


def selftest():
    req = INSTALL / "Required"
    checks = {"Default Gradients.grd": "Foreground to Background", "Default Contours.shc": "Linear",
              "Default Patterns.pat": "Tree Tile 4", "Default Custom Shapes.csh": "Tiger"}
    for f, first in checks.items():
        e, _ = parse_file(req / f)
        assert e and e[0]["name"] == first, (f, e[:2])
    assert zlabel("$$$/a/b=C d") == "C d" and zlabel("plain") == "plain"
    print("presetfiles selftest ok")


if __name__ == "__main__":
    selftest()
