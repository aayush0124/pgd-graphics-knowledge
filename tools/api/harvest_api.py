"""PGD: harvest the scripting surfaces of Photoshop / Illustrator / CorelDRAW from FILES (no app is started).

    python harvest_api.py            ps, ai and cdr
    python harvest_api.py ps cdr     just those
    python harvest_api.py --selftest

  ps  -> harvest/ps/ps_api.json    ExtendScript DOM (omv.xml) merged with the COM object library inside
                                   Required/Plug-Ins/Extensions/ScriptingSupport.8li, plus TypeLibrary.tlb (OLE Actions
                                   COM) and Terminology.jsx (Action Manager constants, item "am:terminology")
  ai  -> harvest/ai/ai_api.json    ExtendScript DOM (omv.xml, both installed copies compared) merged with the COM
                                   object library inside Plug-ins/Extensions/ScriptingSupport.aip
  cdr -> harvest/cdr/cdr_api.json  every CorelDRAW 2024 type library under Programs64/TypeLibs (VGCore first; types
                                   that several libraries share are listed once with extra.also_in)

Items: "class:<Name>" per class / interface / coclass / record / module / alias, "enum:<Name>" per enumeration;
members in extra.members, enumeration values in extra.values. Type libraries are read with pythoncom.LoadTypeLib,
which maps the file as data (no code from the app runs). Every value comes from a file; nothing is filled in.
"""
import datetime, hashlib, json, os, re, sys
import xml.etree.ElementTree as ET
from pathlib import Path

PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides
PS_DIR = Path(os.environ.get("PGD_PS_DIR") or r"C:\Program Files\Adobe\Adobe Photoshop 2026")
AI_DIR = Path(os.environ.get("PGD_AI_DIR") or r"C:\Program Files\Adobe\Adobe Illustrator 2026")
CDR_DIR = Path(os.environ.get("PGD_CDR_DIR") or r"C:\Program Files\Corel\CorelDRAW Graphics Suite\25\Programs64")
PS_OMV = Path(r"C:\Program Files (x86)\Common Files\Adobe\Scripting Dictionaries CC\photoshop\omv.xml")
AI_OMV = Path(r"C:\Program Files\Common Files\Adobe\Scripting Dictionaries CC\Illustrator 2026\omv.xml")
AI_OMV_OLD = Path(r"C:\Program Files (x86)\Common Files\Adobe\Scripting Dictionaries CC\Illustrator 2026\omv.xml")
PS_EXE, AI_EXE, CDR_EXE = PS_DIR / "Photoshop.exe", AI_DIR / r"Support Files\Contents\Windows\Illustrator.exe", CDR_DIR / "CorelDRW.exe"
PS_COM = PS_DIR / r"Required\Plug-Ins\Extensions\ScriptingSupport.8li"
AI_COM = AI_DIR / r"Plug-ins\Extensions\ScriptingSupport.aip"
PS_TLB = PS_DIR / "TypeLibrary.tlb"
PS_TERM = PS_DIR / r"Presets\Scripts\Stack Scripts Only\Terminology.jsx"
# Photo-Paint's own object model ships in the same folder; it is listed by name + counts only (not CorelDRAW's API).
CDR_SUMMARY_ONLY = {"PHOTOPAINT", "PhotoPaintCore"}
CDR_FIRST = ["VGCoreAuto.tlb", "CorelDRAW.tlb"]


# ----------------------------------------------------------------------------------------------- small helpers
def file_version(p):
    import win32api
    i = win32api.GetFileVersionInfo(str(p), "\\")
    ms, ls = i["FileVersionMS"], i["FileVersionLS"]
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


def file_info(p):
    p = Path(p)
    st = p.stat()
    return {"path": str(p), "bytes": st.st_size, "md5": hashlib.md5(p.read_bytes()).hexdigest(),
            "modified": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")}


def registered(guid):
    """Registered versions of a type library GUID (HKCR TypeLib key): [{version, name, win32, win64}]."""
    import winreg
    out = []
    try:
        k = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "TypeLib\\" + guid)
    except OSError:
        return out
    for j in range(256):
        try:
            v = winreg.EnumKey(k, j)
        except OSError:
            break
        r = {"version": v, "name": winreg.QueryValue(k, v)}
        for sub in ("win32", "win64"):
            try:
                r[sub] = winreg.QueryValue(k, v + "\\0\\" + sub)
            except OSError:
                pass
        out.append(r)
    return out


def progid(name):
    """ProgID -> {progid, curver, clsid, server} from HKCR (which exe CreateObject / Dispatch(name) would start)."""
    import winreg
    r = {"progid": name}
    for key, sub in (("curver", "CurVer"), ("clsid", "CLSID")):
        try:
            r[key] = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, f"{name}\\{sub}")
        except OSError:
            pass
    cur = r.get("curver")
    if cur and "clsid" in r and cur != name:
        r["curver_clsid"] = progid(cur).get("clsid")
    try:
        r["server"] = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, f"CLSID\\{r['clsid']}\\LocalServer32")
    except (OSError, KeyError):
        pass
    return r


def jsonable(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return str(v)


def num(s):
    """'72' -> 72, '0.5' -> 0.5, 'true' -> True, anything else unchanged."""
    if not isinstance(s, str):
        return s
    t = s.strip()
    if t in ("true", "false"):
        return t == "true"
    try:
        return int(t, 16) if t.lower().startswith("0x") else int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        return s


def write_doc(app, kind, version, source, items, **top):
    out = PGD / "harvest" / app.lower() / f"{kind}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = {"app": app, "kind": kind, "app_version": version, "source": source, **top, "items": items}
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out)
    print(f"wrote {out}: {len(items)} items")
    return out


class Items:
    """Ordered items with unique ids: a name seen twice gets '<prefix>:<qualifier>.<Name>'."""

    def __init__(self):
        self.list, self.ids = [], {}

    def add(self, item, qualifier):
        if item["id"] in self.ids:
            pre, name = item["id"].split(":", 1)
            item["id"] = f"{pre}:{qualifier}.{name}"
        assert item["id"] not in self.ids, item["id"]
        self.ids[item["id"]] = item
        self.list.append(item)
        return item


# ----------------------------------------------------------------------------------------------- omv.xml (ExtendScript)
def _strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _txt(el):
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def _desc(el):
    parts = [_txt(el.find("shortdesc")), _txt(el.find("description"))]
    return " ".join(p for p in parts if p)


def _datatype(dt):
    """-> dict of type / array / default / min / max read from a <datatype> element."""
    if dt is None:
        return {}
    out = {"type": _txt(dt.find("type")) or None}
    if dt.find("array") is not None:
        out["array"] = True
    for tag, key in (("value", "default"), ("min", "min"), ("max", "max")):
        el = dt.find(tag)
        if el is not None and _txt(el) != "":
            out[key] = num(_txt(el))
    return out


def parse_omv(path):
    """-> (map title, map time, [class dicts]) from an Adobe omv.xml scripting dictionary."""
    root = _strip_ns(ET.parse(path).getroot())
    m = root.find("map")
    suite = {}
    for grp in m.findall("topicref"):
        for ref in grp.iter("topicref"):
            if ref is not grp and ref.get("href"):
                suite.setdefault(ref.get("href").split("/")[-1], grp.get("navtitle"))
    classes = []
    for cd in root.iter("classdef"):
        name = cd.get("name")
        c = {"name": name, "enumeration": cd.get("enumeration") == "true", "dynamic": cd.get("dynamic") == "true",
             "superclass": _txt(cd.find("superclass")) or None, "description": _desc(cd), "suite": suite.get(name),
             "members": [], "values": []}
        for els in cd.findall("elements"):
            scope = els.get("type")
            for el in els:
                if el.tag not in ("property", "method"):
                    continue
                dt = _datatype(el.find("datatype"))
                if c["enumeration"] and el.tag == "property":
                    c["values"].append({"name": el.get("name"), "value": dt.get("default"), "description": _desc(el)})
                    continue
                mem = {"name": el.get("name"), "kind": el.tag, "type": dt.get("type")}
                if el.tag == "property":
                    mem["readonly"] = el.get("rwaccess") == "readonly"
                else:
                    ps = []
                    for p in el.findall("parameters/parameter"):
                        pd = _datatype(p.find("datatype"))
                        q = {"name": p.get("name"), "type": pd.get("type"), "optional": p.get("optional") == "true"}
                        for k in ("default", "min", "max", "array"):
                            if k in pd:
                                q[k] = pd[k]
                        if _desc(p):
                            q["description"] = _desc(p)
                        ps.append(q)
                    mem["params"] = ps
                mem["description"] = _desc(el)
                for k in ("array", "default", "min", "max"):
                    if k in dt:
                        mem[k] = dt[k]
                mem["scope"] = scope
                c["members"].append(mem)
        classes.append(c)
    return m.get("title"), m.get("time"), classes


def omv_item(c, category, evidence):
    is_enum = c["enumeration"]
    extra = {"description": c["description"]}
    if c["superclass"]:
        extra["superclass"] = c["superclass"]
    if c["dynamic"]:
        extra["dynamic"] = True
    if is_enum:
        extra["values"] = c["values"]
    else:
        extra["members"] = c["members"]
    item = {"name": c["name"], "id": f"{'enum' if is_enum else 'class'}:{c['name']}",
            "path": f"{c['suite'] or 'omv'}/{c['name']}", "category": category, "evidence": evidence, "extra": extra}
    return item


# ----------------------------------------------------------------------------------------------- COM type libraries
VT = {2: "short", 3: "long", 4: "single", 5: "double", 6: "currency", 7: "date", 8: "string", 9: "IDispatch",
      10: "scode", 11: "bool", 12: "variant", 13: "IUnknown", 14: "decimal", 16: "char", 17: "byte", 18: "ushort",
      19: "ulong", 20: "int64", 21: "uint64", 22: "int", 23: "uint", 24: "void", 25: "HRESULT", 30: "LPSTR",
      31: "LPWSTR"}
TKIND = {0: "enum", 1: "record", 2: "module", 3: "interface", 4: "dispinterface", 5: "coclass", 6: "alias", 7: "union"}
FIN, FOUT, FRETVAL, FOPT, FHASDEFAULT = 1, 2, 8, 16, 32
TYPEFLAGS = {0x1: "appobject", 0x2: "cancreate", 0x10: "hidden", 0x40: "dual", 0x200: "restricted",
             0x1000: "dispatchable"}


def tname(ti, td):
    """Type descriptor -> readable name. Pointers are dropped (ByRef is reported per param)."""
    if isinstance(td, int):
        return VT.get(td, f"VT_{td}")
    vt, inner = td[0], td[1]
    if vt == 26:
        return tname(ti, inner)
    if vt == 27:
        return f"SAFEARRAY({tname(ti, inner)})"
    if vt == 29:
        try:
            return ti.GetRefTypeInfo(inner).GetDocumentation(-1)[0]
        except Exception as e:  # noqa: BLE001
            return f"<unresolved {inner}: {e}>"
    return f"VT_{vt}({inner})"


def _param(ti, name, ed):
    td, flags, default = ed[0], ed[1], ed[2] if len(ed) > 2 else None
    p = {"name": name, "type": tname(ti, td), "optional": bool(flags & (FOPT | FHASDEFAULT))}
    if flags & FHASDEFAULT:
        p["default"] = jsonable(default)
    if flags & FOUT:
        p["byref"] = True
    return p


def tlb_type(tl, i):
    """-> dict describing type i of a loaded type library (members / values / implements ...)."""
    import pythoncom
    ti = tl.GetTypeInfo(i)
    ta = ti.GetTypeAttr()
    name, doc = tl.GetDocumentation(i)[:2]
    kind = TKIND.get(ta.typekind, str(ta.typekind))
    t = {"name": name, "typekind": kind, "description": doc or "", "guid": str(ta.iid),
         "flags": [v for k, v in TYPEFLAGS.items() if ta.wTypeFlags & k]}
    if str(ta.iid) == str(pythoncom.IID_NULL):
        t.pop("guid")
    if kind == "alias":
        t["alias_of"] = tname(ti, ta.tdescAlias)
    if kind == "coclass":
        t["implements"] = []
        for j in range(ta.cImplTypes):
            r = ti.GetRefTypeInfo(ti.GetRefTypeOfImplType(j))
            f = ti.GetImplTypeFlags(j)
            t["implements"].append({"name": r.GetDocumentation(-1)[0], "default": bool(f & 1), "source": bool(f & 2)})
        return t
    if kind in ("dispinterface", "interface") and ta.cImplTypes:
        try:  # dual: the vtable view names the real parent; plain dispinterface: impl type 0
            base = ti
            if ta.wTypeFlags & 0x40:
                base = ti.GetRefTypeInfo(ti.GetRefTypeOfImplType(-1))
            if base.GetTypeAttr().cImplTypes:
                t["inherits"] = base.GetRefTypeInfo(base.GetRefTypeOfImplType(0)).GetDocumentation(-1)[0]
        except Exception as e:  # noqa: BLE001
            t["inherits_error"] = str(e)
    values, members, byid = [], [], {}
    for j in range(ta.cVars):
        vd = ti.GetVarDesc(j)
        vname, vdoc = ti.GetDocumentation(vd.memid)[:2]
        if kind == "enum" or vd.varkind == 2:  # VAR_CONST
            (values if kind == "enum" else members).append(
                {"name": vname, "value": jsonable(vd.value), "description": vdoc or ""} if kind == "enum" else
                {"name": vname, "kind": "constant", "type": tname(ti, vd.elemdescVar[0]), "value": jsonable(vd.value),
                 "description": vdoc or ""})
        else:
            members.append({"name": vname, "kind": "property", "type": tname(ti, vd.elemdescVar[0]),
                            "readonly": bool(vd.wVarFlags & 1), "params": [], "description": vdoc or ""})
    for j in range(ta.cFuncs):
        fd = ti.GetFuncDesc(j)
        if fd.wFuncFlags & 1:  # restricted: IUnknown / IDispatch plumbing
            continue
        names = ti.GetNames(fd.memid)
        fname, fdoc = ti.GetDocumentation(fd.memid)[:2]
        args = list(fd.args)
        ret = tname(ti, fd.rettype[0])
        if args and args[-1][1] & FRETVAL:  # vtable interface: [out, retval] is the result
            ret = tname(ti, args[-1][0])
            args = args[:-1]
        argnames = list(names[1:]) + [f"arg{k}" for k in range(len(names) - 1, len(args))]
        params = [_param(ti, argnames[k], a) for k, a in enumerate(args)]
        inv = fd.invkind
        if inv == 1:  # method
            m = {"name": fname, "kind": "method", "type": ret, "params": params, "description": fdoc or ""}
            if fd.wFuncFlags & 0x40:
                m["hidden"] = True
            m["dispid"] = fd.memid
            members.append(m)
            continue
        m = byid.get(fd.memid)
        if m is None:
            m = {"name": fname, "kind": "property", "type": None, "readonly": True, "params": [],
                 "description": fdoc or "", "dispid": fd.memid}
            if fd.wFuncFlags & 0x40:
                m["hidden"] = True
            byid[fd.memid] = m
            members.append(m)
        if inv == 2:  # get
            m["type"], m["params"] = ret, params
        else:  # put (4) / putref (8)
            m["readonly"] = False
            if inv == 8:
                m["putref"] = True
            if m["type"] is None and params:
                m["type"], m["params"] = params[-1]["type"], params[:-1]
    if kind == "enum":
        t["values"] = values
    else:
        t["members"] = members
    return t


def load_tlb(path):
    import pythoncom
    tl = pythoncom.LoadTypeLib(str(path))
    la = tl.GetLibAttr()
    name, doc = tl.GetDocumentation(-1)[:2]
    return tl, {"library": name, "description": doc or "", "guid": str(la[0]), "version": f"{la[3]}.{la[4]}",
                "file": file_info(path)}


def tlb_item(t, lib, category, evidence):
    is_enum = t["typekind"] == "enum"
    extra = {k: v for k, v in t.items() if k != "name" and v not in (None, [], "")}
    if t["typekind"] == "coclass":  # members live on the interface it implements
        extra["members_on"] = next((x["name"] for x in t.get("implements", []) if x["default"] and not x["source"]),
                                   None)
    elif not is_enum:
        extra.setdefault("members", [])
    return {"name": t["name"], "id": f"{'enum' if is_enum else 'class'}:{t['name']}", "path": f"{lib}/{t['name']}",
            "category": category, "evidence": evidence, "extra": extra}


def fingerprint(t):
    """Same GUID = same type. A coclass is the same when its name and interface list match (CorelDRAW.tlb re-declares
    VGCore's coclasses under its own CLSIDs); enums / records without a GUID compare by name, member names and values."""
    if t["typekind"] == "coclass":
        return ("coclass", t["name"], json.dumps(t.get("implements")))
    if t.get("guid"):
        return ("guid", t["guid"], t["typekind"])
    body = t.get("values") or t.get("members") or []
    return (t["typekind"], t["name"], json.dumps([[x.get("name"), x.get("value"), x.get("type")] for x in body]))


# ----------------------------------------------------------------------------------------------- omv <-> COM merge
def com_key(name, prefix):
    """COM type name -> the omv class it describes: '_Application' -> 'Application', 'PsBlendMode' -> 'BlendMode'."""
    n = name.lstrip("_")
    if prefix and n.startswith(prefix) and len(n) > len(prefix) and n[len(prefix)].isupper():
        n = n[len(prefix):]
    return n


def omv_member_names(name, cls):
    """lower-case -> name of every member of an omv class and its superclass chain (COM flattens inheritance)."""
    out, seen = {}, set()
    while name in cls and name not in seen:
        seen.add(name)
        for m in cls[name]["members"]:
            out.setdefault(m["name"].lower(), m["name"])
        name = cls[name]["superclass"]
    return out


def enum_norm(n):
    """'aiPatternDither' / 'PATTERNDITHER' / 'PATTERN_DITHER' -> 'PATTERNDITHER'."""
    return re.sub(r"^(ai|ps)(?=[A-Z0-9])", "", n).replace("_", "").upper()


def _names(target, t, omv_names):
    """-> (omv names, COM names) as {normalised: shown} for an omv item and a COM type of the same kind."""
    if t["typekind"] == "enum":
        return ({enum_norm(a["name"]): a["name"] for a in target["extra"].get("values", [])},
                {enum_norm(b["name"]): b["name"] for b in t["values"]})
    return omv_member_names(target["name"], omv_names), {m["name"].lower(): m["name"] for m in t["members"]}


def _attach(target, t, lib, omv_names, matched_by):
    """Put COM type t on omv item target: extra.com.types + a name diff (enums: by value name, then by value)."""
    com = target["extra"].get("com") or {"library": lib, "types": []}
    target["extra"]["com"] = com
    com["types"].append(dict(t, matched_by=matched_by))
    if t["typekind"] == "coclass":
        return False
    om, cm = _names(target, t, omv_names)
    ol, cl = [k for k in om if k not in cm], [k for k in cm if k not in om]
    if t["typekind"] == "enum":  # names that differ but carry the same value are the same entry
        ov = {enum_norm(a["name"]): a["value"] for a in target["extra"].get("values", [])}
        cv = {enum_norm(b["name"]): b["value"] for b in t["values"]}
        ol, cl = [k for k in ol if ov[k] not in {cv[x] for x in cl}], [k for k in cl if cv[k] not in {ov[x] for x in ol}]
        mism = [[om[k], ov[k], cv[k]] for k in ov if k in cv and ov[k] != cv[k]]
        if mism:
            com["value_mismatch"] = mism
    d = com.setdefault("diff", {"omv_only": [], "com_only": []})
    d["omv_only"] += [om[k] for k in ol if om[k] not in d["omv_only"]]
    d["com_only"] += [cm[k] for k in cl if cm[k] not in d["com_only"]]
    return bool(ol or cl)


def merge_com(items, omv_names, tl, info, prefix, category, evidence, min_overlap=0.5):
    """Attach each COM type to the omv item it describes (extra.com + diff). Match by name ('_X' / 'PsX' -> 'X'),
    then, for what is left, by member / value-name overlap (Jaccard >= min_overlap, the score is recorded).
    COM types still unmatched become items of their own. Returns counts."""
    lib = info["library"]
    by_omv = {it["name"]: it for it in items.list if it["name"] in omv_names}
    stats = {"com_types": tl.GetTypeInfoCount(), "matched_by_name": 0, "matched_by_overlap": [], "com_only_types": [],
             "classes_with_member_diffs": 0}
    types = [tlb_type(tl, i) for i in range(tl.GetTypeInfoCount())]
    hit, left = {}, []
    for t in types:
        target = by_omv.get(com_key(t["name"], prefix)) or (by_omv.get(t["name"]) if t["typekind"] == "coclass" else None)
        if target is not None and target["id"].startswith("enum:") == (t["typekind"] == "enum"):
            stats["classes_with_member_diffs"] += _attach(target, t, lib, omv_names, "name")
            stats["matched_by_name"] += 1
            hit[t["name"]] = target
        else:
            left.append(t)
    for t in sorted(left, key=lambda x: x["typekind"] == "coclass"):  # interfaces first, coclasses follow them
        target, why = None, None
        if t["typekind"] == "coclass":
            dflt = next((x["name"] for x in t.get("implements", []) if x["default"] and not x["source"]), None)
            target, why = hit.get(dflt), f"default interface {dflt}"
        else:
            best = 0.0
            for it in by_omv.values():
                if "com" in it["extra"] or it["id"].startswith("enum:") != (t["typekind"] == "enum"):
                    continue
                om, cm = _names(it, t, omv_names)
                score = len(om.keys() & cm.keys()) / max(1, len(om.keys() | cm.keys()))
                if score > best:
                    best, target = score, it
            why = f"member overlap {best:.2f}"
            if best < min_overlap:
                target = None
        if target is None:
            items.add(tlb_item(t, lib, category, evidence), "com")
            stats["com_only_types"].append(t["name"])
            continue
        stats["classes_with_member_diffs"] += _attach(target, t, lib, omv_names, why)
        stats["matched_by_overlap"].append([t["name"], target["name"], why])
        hit[t["name"]] = target
    for it in by_omv.values():  # an omv class with no COM counterpart
        it["extra"].setdefault("com", None)
    return stats


# ----------------------------------------------------------------------------------------------- Terminology.jsx
TERM_RE = re.compile(r"const\s+(\w+)\s*=\s*app\.(charIDToTypeID|stringIDToTypeID)\(\s*(['\"])(.*?)\3\s*\)")


def parse_terminology(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    out = []
    for m in TERM_RE.finditer(text):
        var, fn, code = m.group(1), m.group(2), m.group(4)
        grp = re.match(r"(class|enum|event|key|type|unit|k)(?=[A-Za-z])", var)
        out.append({"name": var, "group": grp.group(1) if grp else None,
                    "id_kind": "charID" if fn.startswith("char") else "stringID", "id": code})
    return out


# ----------------------------------------------------------------------------------------------- per app
def omv_items(path, category):
    title, time, classes = parse_omv(path)
    items = Items()
    for c in classes:
        items.add(omv_item(c, category, f"parsed from {path}"), "omv")
    return title, time, classes, items


def harvest_ps():
    ver = file_version(PS_EXE)
    title, time, classes, items = omv_items(PS_OMV, "omv: " + "Photoshop ExtendScript DOM")
    omv_names = {c["name"]: c for c in classes}
    tl, info = load_tlb(PS_COM)
    stats = merge_com(items, omv_names, tl, info, "Ps", f"COM: {info['description']}",
                      f"pythoncom.LoadTypeLib({PS_COM})")
    # TypeLibrary.tlb: the OLE Actions (Action Manager) COM interfaces
    tl2, info2 = load_tlb(PS_TLB)
    am_pairs = {"IActionDescriptor": "ActionDescriptor", "IActionList": "ActionList",
                "IActionReference": "ActionReference", "IPhotoshopApplication": "Application"}
    by_name = {it["name"]: it for it in items.list}
    for i in range(tl2.GetTypeInfoCount()):
        t = tlb_type(tl2, i)
        it = items.add(tlb_item(t, info2["library"], f"COM: {info2['description']} (TypeLibrary.tlb)",
                                f"pythoncom.LoadTypeLib({PS_TLB})"), "oleactions")
        omv_c = am_pairs.get(t["name"])
        if omv_c and omv_c in by_name and t.get("members") is not None:
            om = omv_member_names(omv_c, omv_names)
            cm = {m["name"].lower(): m["name"] for m in t["members"]}
            it["extra"]["compare_omv"] = {"omv_class": omv_c, "omv_only": [om[k] for k in om if k not in cm],
                                          "tlb_only": [cm[k] for k in cm if k not in om]}
    consts = parse_terminology(PS_TERM)
    items.add({"name": "Action Manager terminology (Terminology.jsx)", "id": "am:terminology",
               "path": str(PS_TERM), "category": "Terminology.jsx",
               "evidence": f"regex parse of the const declarations in {PS_TERM}",
               "extra": {"description": "TypeID constants used by Adobe's Stack scripts (an abridged translation of "
                                        "PITerminology.h, per the file's own header comment). 'id' is the 4-char "
                                        "charID or the stringID passed to app.charIDToTypeID / app.stringIDToTypeID.",
                         "count": len(consts), "constants": consts}}, "am")
    omv_com_diff = {"omv_title": title, "omv_generated": time, "com_library": info,
                    "oleactions_library": info2, **{k: v for k, v in stats.items() if k != "com_only_types"},
                    "com_only_types": stats["com_only_types"],
                    "omv_classes_without_com": sorted(it["name"] for it in items.list
                                                      if it["extra"].get("com", 0) is None)}
    empty = [[it["name"], len(it["extra"]["members"]), max(len(t.get("members", [])) for t in it["extra"]["com"]["types"])]
             for it in items.list if it["id"].startswith("class:") and len(it["extra"].get("members", [0, 0])) <= 1
             and it["extra"].get("com") and max(len(t.get("members", [])) for t in it["extra"]["com"]["types"]) >= 5]
    notes = [f"omv.xml is the '{title}' dictionary generated {time}; it was not regenerated for Photoshop {ver}. The COM "
             f"object library '{info['description']}' in {PS_COM} is the current one: diff per class in extra.com.diff.",
             f"TypeLibrary.tlb ('{info2['description']}', library {info2['library']}) declares only "
             f"{[tl2.GetDocumentation(i)[0] for i in range(tl2.GetTypeInfoCount())]}: the OLE Actions / Action Manager "
             f"COM interfaces, not the DOM.",
             f"omv classes listing at most one member while the COM side lists 5+ ([class, omv members, COM members]; use extra.com): {empty}",
             f"registered type libraries: DOM {registered(info['guid'])}; OLE Actions {registered(info2['guid'])}"]
    write_doc("PS", "ps_api", ver,
              f"omv.xml ({title}, generated {time}) + COM object library in ScriptingSupport.8li + TypeLibrary.tlb "
              f"(OLE Actions) + Terminology.jsx, all parsed from files by tools/api/harvest_api.py",
              items.list, sources=[file_info(PS_OMV), file_info(PS_COM), file_info(PS_TLB), file_info(PS_TERM),
                                   {"path": str(PS_EXE), "file_version": ver}], notes=notes, comparison=omv_com_diff)
    return items.list, omv_com_diff


def harvest_ai():
    ver = file_version(AI_EXE)
    title, time, classes, items = omv_items(AI_OMV, "omv: Illustrator ExtendScript DOM")
    a, b = file_info(AI_OMV), file_info(AI_OMV_OLD)
    if a["md5"] == b["md5"]:
        copies = (f"the two installed omv.xml copies are byte-identical (md5 {a['md5']}, {a['bytes']} bytes): "
                  f"{AI_OMV} written {a['modified']}, {AI_OMV_OLD} written {b['modified']}; both carry map title "
                  f"'{title}' generated '{time}'")
    else:
        _, t2, cls2 = parse_omv(AI_OMV_OLD)
        n1, n2 = {c["name"] for c in classes}, {c["name"] for c in cls2}
        copies = f"copies differ: only in new {sorted(n1 - n2)}, only in old {sorted(n2 - n1)}; old generated {t2}"
    omv_names = {c["name"]: c for c in classes}
    tl, info = load_tlb(AI_COM)
    stats = merge_com(items, omv_names, tl, info, "Ai", f"COM: {info['description']}",
                      f"pythoncom.LoadTypeLib({AI_COM})")
    cmp_ = {"omv_title": title, "omv_generated": time, "omv_copies": copies, "com_library": info,
            **{k: v for k, v in stats.items()},
            "omv_classes_without_com": sorted(it["name"] for it in items.list if it["extra"].get("com", 0) is None)}
    exe = file_info(AI_EXE)
    notes = [copies + f". {AI_EXE.name} {ver} was written {exe['modified']}, the same install pass as the Program Files "
             f"copy, so that copy is the one laid down by {ver}; its content is unchanged from the Feb copy.",
             f"COM library '{info['description']}' ({AI_COM}): {stats['matched_by_name']} of {stats['com_types']} "
             f"types match an omv class by name, {len(stats['matched_by_overlap'])} by member overlap, "
             f"{len(stats['com_only_types'])} are COM-only; per-class differences in extra.com.diff.",
             f"registered type library: {registered(info['guid'])}"]
    write_doc("AI", "ai_api", ver,
              f"omv.xml ({title}, generated {time}) merged with the COM type library in ScriptingSupport.aip, parsed "
              f"from files by tools/api/harvest_api.py",
              items.list, sources=[a, b, file_info(AI_COM), {"path": str(AI_EXE), "file_version": ver}],
              notes=notes, comparison=cmp_)
    return items.list, cmp_


def harvest_cdr():
    ver = file_version(CDR_EXE)
    tdir = CDR_DIR / "TypeLibs"
    files = sorted(tdir.glob("*.tlb"), key=lambda p: (p.name not in CDR_FIRST,
                                                       CDR_FIRST.index(p.name) if p.name in CDR_FIRST else 0, p.name))
    items, seen, libs = Items(), {}, []
    for f in files:
        try:
            tl, info = load_tlb(f)
        except Exception as e:  # noqa: BLE001
            libs.append({"file": str(f), "error": str(e)})
            items.add({"name": f.stem, "id": f"lib:{f.stem}", "path": str(f), "category": f.stem,
                       "error": f"LoadTypeLib failed: {e}"}, "lib")
            continue
        lib = info["library"]
        counts = {}
        for i in range(tl.GetTypeInfoCount()):
            k = TKIND.get(tl.GetTypeInfoType(i), "?")
            counts[k] = counts.get(k, 0) + 1
        info["type_counts"] = counts
        info["interfaces"] = counts.get("dispinterface", 0) + counts.get("interface", 0)
        full = lib not in CDR_SUMMARY_ONLY
        info["harvested"] = "full" if full else "summary"
        libs.append(info)
        lib_item = {"name": f"{lib} type library ({f.name})", "id": f"lib:{lib}", "path": str(f), "category": lib,
                    "evidence": f"pythoncom.LoadTypeLib({f})", "extra": dict(info)}
        if not full:
            lib_item["extra"]["type_names"] = [tl.GetDocumentation(i)[0] for i in range(tl.GetTypeInfoCount())]
            lib_item["extra"]["note"] = ("Corel PHOTO-PAINT object model (separate app of the suite): listed by name "
                                         "and counts only, not expanded into class items")
        items.add(lib_item, "lib")
        if not full:
            continue
        added = shared = 0
        for i in range(tl.GetTypeInfoCount()):
            t = tlb_type(tl, i)
            fp = fingerprint(t)
            if fp in seen:  # the same type re-declared by another library
                ex = seen[fp]["extra"]
                ex.setdefault("also_in", []).append(lib)
                if t.get("guid") and t["guid"] != ex.get("guid"):
                    ex.setdefault("guid_in", {})[lib] = t["guid"]
                shared += 1
                continue
            it = items.add(tlb_item(t, lib, lib, f"pythoncom.LoadTypeLib({f})"), lib)
            seen[fp] = it
            added += 1
        lib_item["extra"]["types_added"], lib_item["extra"]["types_shared_with_earlier_libs"] = added, shared
    by_id = items.ids
    reg = {x["library"]: registered(x["guid"]) for x in libs if x.get("guid") and x.get("version", "").startswith("25")}
    notes = ["VGCore (VGCoreAuto.tlb) holds every interface of the CorelDRAW object model; CorelDRAW.tlb re-declares "
             "VGCore's enums and coclasses (its coclasses under their own CLSIDs, kept in extra.guid_in).",
             "A type several libraries declare is listed once, under the first library that declares it, with "
             "extra.also_in; a different type under a name already used gets id class:<Library>.<Name>.",
             f"registered versions of the main libraries (HKCR TypeLib key): {reg}",
             f"COM ProgIDs (HKCR): {[progid(p) for p in ('CorelDRAW.Application', 'CorelDRAW.Application.25')]}. "
             f"The coclass Application of CorelDRAW.tlb 25.1 has CLSID "
             f"{(by_id.get('class:Application') or {}).get('extra', {}).get('guid_in', {}).get('CorelDRAW')}."]
    write_doc("CDR", "cdr_api", ver,
              f"all {len(files)} type libraries in {tdir} read with pythoncom.LoadTypeLib (VGCore + CorelDRAW in "
              f"full, tool / filter / framework libraries in full, PHOTO-PAINT libraries as summary items) by "
              f"tools/api/harvest_api.py", items.list, libraries=libs,
              notes=notes, sources=[{"path": str(CDR_EXE), "file_version": ver}])
    return items.list, libs


def selftest():
    assert num("72") == 72 and num("0.5") == 0.5 and num("true") is True and num("NewDocumentMode.RGB") == "NewDocumentMode.RGB"
    assert com_key("_Application", "Ps") == "Application" and com_key("PsBlendMode", "Ps") == "BlendMode"
    assert com_key("Pstring", "Ps") == "Pstring"
    assert num("0x536C7476") == 1399616630 and enum_norm("aiPatternDither") == enum_norm("PATTERN_DITHER")
    t = parse_terminology(PS_TERM)
    assert {"name": "classBitmapMode", "group": "class", "id_kind": "charID", "id": "BtmM"} in t, t[:2]
    assert any(c["name"] == "enumMask" and c["id"] == "Msk " for c in t)  # tab before ')' in the file
    it = Items()
    it.add({"id": "class:A", "name": "A"}, "x")
    assert it.add({"id": "class:A", "name": "A"}, "x")["id"] == "class:x.A"
    print("selftest ok")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--selftest"]:
        selftest()
        sys.exit(0)
    for app in args or ["ps", "ai", "cdr"]:
        {"ps": harvest_ps, "ai": harvest_ai, "cdr": harvest_cdr}[app]()
