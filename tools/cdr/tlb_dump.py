"""PGD/CDR: dump CorelDRAW 2024 type libraries to JSON (interfaces, members, args, types, defaults, enums).

    python tlb_dump.py            -> work/cdr/tlb/<lib>.json for every Programs64/TypeLibs/*.tlb
    python tlb_dump.py --selftest

Read straight from the .tlb files with pythoncom (no running app needed), so every member, argument name, VT type,
optional flag and default value comes from the installed typelib.
"""
import json, sys
from pathlib import Path
import pythoncom

TLB = Path(r"C:/Program Files/Corel/CorelDRAW Graphics Suite/25/Programs64/TypeLibs")
OUT = Path(__file__).resolve().parents[2] / "work" / "cdr" / "tlb"

VT = {2: "short", 3: "long", 4: "single", 5: "double", 6: "currency", 7: "date", 8: "string", 9: "dispatch",
      10: "scode", 11: "bool", 12: "variant", 13: "unknown", 16: "char", 17: "byte", 18: "ushort", 19: "ulong",
      20: "int64", 21: "uint64", 22: "int", 23: "uint", 24: "void", 25: "hresult", 26: "ptr", 27: "safearray",
      28: "carray", 29: "userdefined", 30: "lpstr", 31: "lpwstr"}
INVK = {1: "func", 2: "get", 4: "put", 8: "putref"}
TKIND = {0: "enum", 1: "record", 2: "module", 3: "interface", 4: "dispatch", 5: "coclass", 6: "alias", 7: "union"}


def tname(ti, td):
    """Readable type of a TYPEDESC tuple/int from pythoncom."""
    if isinstance(td, int):
        return VT.get(td & 0xFFF, str(td)) + ("[]" if td & 0x2000 else "")
    vt, sub = td[0], td[1]
    if vt == 26:  # VT_PTR
        return tname(ti, sub) + "*"
    if vt == 27:
        return tname(ti, sub) + "[]"
    if vt == 29:  # user defined: sub is an HREFTYPE
        try:
            return ti.GetRefTypeInfo(sub).GetDocumentation(-1)[0]
        except pythoncom.com_error:
            return "userdefined"
    return VT.get(vt, str(vt))


def dump_lib(path):
    tl = pythoncom.LoadTypeLib(str(path))
    lib = {"lib": tl.GetDocumentation(-1)[0], "file": path.name, "version": "%d.%d" % tl.GetLibAttr()[3:5],
           "types": []}
    for i in range(tl.GetTypeInfoCount()):
        ti = tl.GetTypeInfo(i)
        ta = ti.GetTypeAttr()
        name, doc = ti.GetDocumentation(-1)[:2]
        t = {"name": name, "kind": TKIND.get(ta.typekind, ta.typekind), "guid": str(ta.iid)}
        if doc:
            t["doc"] = doc
        if ta.typekind == 0:
            t["values"] = []
            for v in range(ta.cVars):
                vd = ti.GetVarDesc(v)
                t["values"].append({"name": ti.GetNames(vd.memid)[0], "value": vd.value})
        elif ta.typekind in (3, 4):
            ms = []
            for f in range(ta.cFuncs):
                fd = ti.GetFuncDesc(f)
                names = ti.GetNames(fd.memid)
                m = {"name": names[0], "invkind": INVK.get(fd.invkind, fd.invkind), "dispid": fd.memid,
                     "returns": tname(ti, fd.rettype[0]), "args": []}
                if fd.wFuncFlags & 0x40:  # FUNCFLAG_FHIDDEN
                    m["hidden"] = True
                for k, a in enumerate(fd.args):
                    td, flags, dflt = a
                    an = names[k + 1] if k + 1 < len(names) else f"arg{k}"
                    if fd.invkind in (4, 8) and k == len(fd.args) - 1 and k + 1 >= len(names):
                        an = "value"
                    arg = {"name": an, "type": tname(ti, td)}
                    if flags & 0x10:  # PARAMFLAG_FOPT
                        arg["optional"] = True
                    if flags & 0x20 and dflt is not None:  # PARAMFLAG_FHASDEFAULT
                        arg["default"] = dflt if isinstance(dflt, (int, float, str, bool)) else str(dflt)
                    if flags & 0x2 and not flags & 0x1:
                        arg["out"] = True
                    m["args"].append(arg)
                ms.append(m)
            t["members"] = ms
            if ta.typekind == 3 or ta.cImplTypes:
                try:
                    t["inherits"] = [ti.GetRefTypeInfo(ti.GetRefTypeOfImplType(k)).GetDocumentation(-1)[0]
                                     for k in range(ta.cImplTypes)]
                except pythoncom.com_error:
                    pass
        elif ta.typekind == 5:
            t["interfaces"] = [ti.GetRefTypeInfo(ti.GetRefTypeOfImplType(k)).GetDocumentation(-1)[0]
                               for k in range(ta.cImplTypes)]
        lib["types"].append(t)
    return lib


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for p in sorted(TLB.glob("*.tlb")):
        try:
            lib = dump_lib(p)
        except Exception as e:  # noqa: BLE001
            print("FAIL", p.name, e)
            continue
        (OUT / (p.stem + ".json")).write_text(json.dumps(lib, indent=1), encoding="utf-8")
        print(p.name, len(lib["types"]), "types")


def selftest():
    lib = dump_lib(TLB / "VGCoreAuto.tlb")
    shape = next(t for t in lib["types"] if t["name"] == "IVGShape")
    cc = next(m for m in shape["members"] if m["name"] == "CreateContour")
    assert cc["args"] and all("name" in a and "type" in a for a in cc["args"]), cc
    assert any(t["kind"] == "enum" and t["name"] == "cdrContourDirection" for t in lib["types"])
    print("selftest ok:", "CreateContour(" + ", ".join(a["name"] for a in cc["args"]) + ")")


if __name__ == "__main__":
    selftest() if sys.argv[1:] == ["--selftest"] else main()
