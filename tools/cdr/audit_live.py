"""PGD/CDR independent audit (live part) -> work/cdr/audit_live.json, checkpointed per section, resumable.

    python audit_live.py [section ...]      sections: docs menubar menus toolbox effects vector tools menucmd presets

Different routes from the harvesters where possible:
  menubar  VGCore Application.CommandBars("Menu Bar").Controls (caption + ID), not the DrawUI.xml modeData list
  menus    recursion through live Automation.GetSubBar(item) instead of DrawUI.xml flyoutBarRef
  toolbox  CommandBars("Toolbox").Controls + GetSubBar for each flyout
  effects  re-applies harvested / templated ApplyBitmapEffect command strings with A/B values + out-of-range value,
           and re-reads data-source defaults and range binds
Everything runs in our own TestDoc (closed unsaved in finally).
"""
import json, random, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cdr_com import Corel  # noqa: E402
from testdoc import TestDoc  # noqa: E402

PGD = HERE.parents[1]
OUT = PGD / "work" / "cdr" / "audit_live.json"
H = {k: json.loads((PGD / "harvest" / "cdr" / f"{k}.json").read_text(encoding="utf-8"))
     for k in ("cdr_effect", "cdr_tool", "cdr_menu", "cdr_preset")}
RNG = random.Random(20261004)


def save(res):
    OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")


def clean(c):
    return (c or "").replace("&&", "\0").replace("&", "").replace("\0", "&").replace("...", "").strip()


# ---------------------------------------------------------------------------------------------------------------
def s_docs(cd, res, td):
    return cd.call(lambda a: [a.Documents.Item(i).Title for i in range(1, a.Documents.Count + 1)], 30)


def s_menubar(cd, res, td):
    def job(a):
        bar = a.CommandBars("Menu Bar")
        c = bar.Controls
        return [{"caption": c.Item(i).Caption, "id": c.Item(i).ID, "visible": c.Item(i).Visible}
                for i in range(1, c.Count + 1)]
    return cd.call(job, 60)


def live_walk(cd, top):
    """Recursive walk via Automation.GetSubBar (live), from a list of (guid, caption)."""
    def job(a):
        au = a.FrameWork.Automation
        rows = []

        def rec(item, path, depth):
            ok, sub = au.GetSubBar(item)
            if not ok or not sub or depth > 6:
                return False
            n = au.GetNumItemsOnBar(sub)
            for i in range(n):
                g, has = au.GetItem(sub, i)
                if not g or g == "00000000-0000-0000-0000-000000000000":
                    continue
                cap = au.GetCaptionText(g)
                p = path + "/" + clean(cap)
                row = {"path": p, "guid": g, "caption": cap, "has_sub": bool(has)}
                rows.append(row)
                if has:
                    row["walked"] = rec(g, p, depth + 1)
            return True
        for g, cap in top:
            rows.append({"path": clean(cap), "guid": g, "caption": cap, "top": True})
            rec(g, clean(cap), 1)
        return rows
    return cd.call(job, 600)


def s_menus(cd, res, td):
    top = [(m["id"], m["caption"]) for m in res["menubar"]]
    return live_walk(cd, top)


def s_toolbox(cd, res, td):
    def job(a):
        c = a.CommandBars("Toolbox").Controls
        return [(c.Item(i).ID, c.Item(i).Caption) for i in range(1, c.Count + 1)]
    top = cd.call(job, 60)
    return {"top": top, "walk": live_walk(cd, top)}


# ---------------------------------------------------------------------------------------------------------------
def photo(td):
    sh = td.doc.ActiveLayer.Shapes
    for i in range(1, sh.Count + 1):
        if sh.Item(i).Type == 5:
            return sh.Item(i)


def sample(td):
    im = photo(td).Bitmap.Image
    w, h = im.Width, im.Height
    px = []
    for yi in range(1, 7):
        for xi in range(1, 9):
            c = im.Pixel(int(w * xi / 9), int(h * yi / 7))
            px.append((c.RGBRed, c.RGBGreen, c.RGBBlue))
    return {"w": w, "h": h, "px": px}


def diff(a, b):
    if (a["w"], a["h"]) != (b["w"], b["h"]):
        return f"size {a['w']}x{a['h']} -> {b['w']}x{b['h']}"
    return round(sum(abs(x - y) for p, q in zip(a["px"], b["px"]) for x, y in zip(p, q)) / (len(a["px"]) * 3), 2)


def pick_numeric(it):
    for p in it.get("params") or []:
        if p.get("type") in ("number", "int") and isinstance(p.get("min"), (int, float)) and \
                isinstance(p.get("max"), (int, float)) and p["max"] > p["min"]:
            return p
    return None


def fmt(v):
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def s_effects(cd, res, td):
    """Bitmap effects: A/B in-range values on the param with a range, then max and max*4+10 (out of range)."""
    bmp = [it for it in H["cdr_effect"]["items"] if (it.get("extra") or {}).get("effect_id") and pick_numeric(it)]
    proven = [it for it in bmp if "cdr_effect_cmd" in it["invoke"]]
    untested = [it for it in bmp if "cdr_effect_cmd" not in it["invoke"]]
    plan = RNG.sample(untested, 12) + RNG.sample(proven, 2)
    out = res.get("effects") or {}
    for it in plan:
        if it["name"] in out:
            continue
        eid, p = it["extra"]["effect_id"], pick_numeric(it)
        lo, hi = p["min"], p["max"]
        a_v = lo + (hi - lo) * 0.15
        b_v = lo + (hi - lo) * 0.85
        if p["type"] == "int":
            a_v, b_v = round(a_v), round(b_v)
        over = hi * 4 + 10 if hi > 0 else hi + 100
        cmds = {"A": f"{eid} {p['key']}={fmt(a_v)}", "B": f"{eid} {p['key']}={fmt(b_v)}", "B2": f"{eid} {p['key']}={fmt(b_v)}",
                "MAX": f"{eid} {p['key']}={fmt(hi)}", "OVER": f"{eid} {p['key']}={fmt(over)}",
                "BADKEY": f"{eid} NoSuchKey{p['key']}={fmt(b_v)}"}

        def job(app, cmds=cmds, eid=eid, ds=it["extra"].get("data_source"), key=p["key"]):
            r = {"param": key, "cmds": cmds}
            try:
                src = app.FrameWork.Application.DataContext.GetDataSource(ds)
                r["ds_value_now"] = None if src is None else src.GetProperty(key)
            except Exception as e:  # noqa: BLE001
                r["ds_value_now"] = "ERR " + str(e)[:80]
            base = sample(td)
            got = {}
            for tag, c in cmds.items():
                try:
                    photo(td).Bitmap.ApplyBitmapEffect("PGD audit", c)
                    got[tag] = sample(td)
                    td.doc.Undo(1)
                except Exception as e:  # noqa: BLE001
                    got[tag] = None
                    r["err_" + tag] = str(e)[:120]
            back = sample(td)
            r["undo_ok"] = diff(base, back) == 0
            got["base"] = base

            def d(x, y):
                return None if got.get(x) is None or got.get(y) is None else diff(got[x], got[y])
            for x, y in (("base", "A"), ("A", "B"), ("B", "B2"), ("base", "MAX"), ("MAX", "OVER"), ("base", "OVER"),
                         ("B", "BADKEY"), ("base", "BADKEY")):
                r[x + "_" + y] = d(x, y)
            return r
        try:
            out[it["name"]] = cd.call(job, timeout=400, note="audit " + eid)
        except Exception as e:  # noqa: BLE001
            out[it["name"]] = {"error": str(e)[:200]}
        out[it["name"]]["id"] = it["id"]
        res["effects"] = out
        save(res)
        print(it["name"], {k: v for k, v in out[it["name"]].items() if k not in ("cmds",)}, flush=True)
    return out


# ---------------------------------------------------------------------------------------------------------------
def s_vector(cd, res, td):
    """Vector effects / lenses: call with the HARVESTED defaults only (all optional args omitted except required)."""
    out = {}

    def fresh(app, x=1.0, ell=False):
        lay = td.doc.ActiveLayer
        s = lay.CreateEllipse2(x + 0.6, 5.0, 0.5) if ell else lay.CreateRectangle2(x, 4.5, 1.2, 0.9)
        s.Fill.UniformColor.RGBAssign(30, 90, 200)
        return s

    hv = {it["name"]: it for it in H["cdr_effect"]["items"]}

    def dflt(name, *lead):
        """positional args = lead + every harvested param default in order (None where the harvest has none:
        VT_DISPATCH colours must be None from Python, the typelib's 0 cannot be converted)."""
        import re
        if name in ("Fish Eye", "Tinted Grayscale", "Wireframe"):   # lens type is the call's first argument
            lead = (int(re.search(r"Type=(\d+)", hv[name]["invoke"]["cdr_com"]).group(1)),)
        return list(lead) + [p.get("default") for p in (hv[name].get("params") or [])]

    tests = {  # harvested name -> call built ONLY from the harvested defaults
        "Contour": lambda app: fresh(app).CreateContour(*dflt("Contour")),
        "Drop Shadow": lambda app: fresh(app).CreateDropShadow(*dflt("Drop Shadow")),
        "Fish Eye": lambda app: fresh(app).CreateLens(*dflt("Fish Eye")),
        "Tinted Grayscale": lambda app: fresh(app).CreateLens(*dflt("Tinted Grayscale")),
        "Wireframe": lambda app: fresh(app).CreateLens(*dflt("Wireframe")),
        "Inner Shadow": lambda app: fresh(app).CreateInnerShadow(*dflt("Inner Shadow")),
    }
    for name, fn in tests.items():
        def job(app, fn=fn):
            e = fn(app)
            r = {"returned": e._oleobj_.GetTypeInfo().GetDocumentation(-1)[0]}
            try:
                r["effect_type"] = e.Type
                if e.Type == 6:      # contour: read back the defaults it was created with
                    c = e.Contour
                    r["readback"] = {"Direction": c.Direction, "Offset": c.Offset, "Steps": c.Steps,
                                     "EndCapType": c.EndCapType, "CornerType": c.CornerType,
                                     "MiterLimit": c.MiterLimit}
                if e.Type == 4:      # drop shadow
                    s = e.DropShadow
                    r["readback"] = {"Opacity": s.Opacity, "Feather": s.Feather, "OffsetX": s.OffsetX,
                                     "OffsetY": s.OffsetY, "FeatherType": s.FeatherType, "Type": s.Type}
                if e.Type == 9:      # lens
                    r["readback"] = {"LensType": e.Lens.Type}
            except Exception as ex:  # noqa: BLE001
                r["readback_err"] = str(ex)[:120]
            return r
        try:
            out[name] = cd.call(job, 120, note="vector " + name)
        except Exception as e:  # noqa: BLE001
            out[name] = {"error": str(e)[:200]}
        it = hv.get(name)
        out[name]["id"] = it["id"] if it else None
        out[name]["harvest_defaults"] = {p["key"]: p.get("default") for p in (it or {}).get("params") or []}
        out[name]["args"] = repr(dflt(name))
        print(name, out[name], flush=True)
    return out


# ---------------------------------------------------------------------------------------------------------------
def s_tools(cd, res, td):
    items = H["cdr_tool"]["items"]
    com = [it for it in items if "cdr_com" in it["invoke"]]
    guid_only = [it for it in items if "cdr_com" not in it["invoke"] and not it.get("error")]
    plan = RNG.sample(com, 4) + RNG.sample(guid_only, 2)
    out = {}
    for it in plan:
        def job(app, it=it):
            r = {}
            ds = app.FrameWork.Application.DataContext.GetDataSource("AppOrViewDataSource")
            app.FrameWork.Automation.InvokeItem("f1aee54d-c9aa-4e6f-9193-82f496b0b72b")   # Pick first
            time.sleep(0.3)
            if "cdr_com" in it["invoke"]:
                v = int(it["invoke"]["cdr_com"].split("=")[1].split()[0])
                app.ActiveTool = v
                r["set"] = v
            else:
                app.FrameWork.Automation.InvokeItem(it["invoke"]["cdr_guid"])
                r["set"] = "InvokeItem"
            time.sleep(0.5)
            r["readback"] = app.ActiveTool
            r["state"] = app.ActiveToolStateGuid
            r["ds_active"] = ds.GetProperty("ActiveTool")
            r["caption"] = app.FrameWork.Automation.GetCaptionText(it["id"])
            app.FrameWork.Automation.InvokeItem("f1aee54d-c9aa-4e6f-9193-82f496b0b72b")
            return r
        try:
            r = cd.call(job, 60, note="tool " + it["name"])
        except Exception as e:  # noqa: BLE001
            r = {"error": str(e)[:200]}
        ap = (it.get("extra") or {}).get("activation_probe") or {}
        r.update(id=it["id"], name=it["name"], harvest_state=ap.get("state_guid"),
                 state_match=r.get("state") == ap.get("state_guid"),
                 caption_match=clean(r.get("caption")) == it["name"])
        out[it["name"]] = r
        print(it["name"], r, flush=True)
    return out


# ---------------------------------------------------------------------------------------------------------------
SAFE_MENU = ["Object/Order/To Back of Page", "Object/Group/Group", "Edit/Duplicate", "Object/Convert to Curves",
             "Object/Order/To Front of Page", "Object/Lock/Lock", "Object/Align and Distribute/Align Left",
             "Object/Transform/Clear Transformations", "Object/Shaping/Combine", "Edit/Select All/Objects",
             "Edit/Delete", "Object/Combine"]


def s_menucmd(cd, res, td):
    items = {it["path"]: it for it in H["cdr_menu"]["items"]}
    cand = [p for p in SAFE_MENU if p in items]
    rest = [it for it in H["cdr_menu"]["items"] if it["path"].split("/")[0] in ("Object", "Edit")
            and not (it.get("extra") or {}).get("opens_dialog") and "..." not in it.get("extra", {}).get("caption", "")]
    plan = [items[p] for p in cand[:4]] + RNG.sample(rest, 2)
    out = {}
    for it in plan:
        def job(app, it=it):
            d = td.doc
            lay = d.ActiveLayer
            a1 = lay.CreateRectangle2(6.0, 0.5, 0.8, 0.6)
            a2 = lay.CreateEllipse2(7.5, 0.8, 0.3)
            d.ClearSelection()
            a1.AddToSelection()
            a2.AddToSelection()

            def state():
                return {"shapes": lay.Shapes.Count, "sel": d.SelectionRange.Count,
                        "types": [lay.Shapes.Item(i).Type for i in range(1, lay.Shapes.Count + 1)],
                        "order1": [lay.Shapes.Item(i).StaticID for i in range(1, lay.Shapes.Count + 1)],
                        "locked": [lay.Shapes.Item(i).Locked for i in range(1, lay.Shapes.Count + 1)],
                        "x": [round(lay.Shapes.Item(i).PositionX, 3) for i in range(1, lay.Shapes.Count + 1)]}
            r = {"enabled": app.FrameWork.Automation.IsEnabled(it["id"]), "caption":
                 app.FrameWork.Automation.GetCaptionText(it["id"])}
            before = state()
            app.FrameWork.Automation.InvokeItem(it["id"])
            time.sleep(0.5)
            after = state()
            r["changed"] = {k: [before[k], after[k]] for k in before if before[k] != after[k]}
            return r
        try:
            r = cd.call(job, 60, note="menu " + it["path"])
        except Exception as e:  # noqa: BLE001
            r = {"error": str(e)[:200]}
        r.update(id=it["id"], path=it["path"], name=it["name"])
        r["caption_match"] = clean(r.get("caption")) == it["name"]
        out[it["path"]] = r
        print(it["path"], r, flush=True)
    return out


# ---------------------------------------------------------------------------------------------------------------
def s_presets(cd, res, td):
    items = H["cdr_preset"]["items"]
    pal = RNG.sample([it for it in items if it["category"] == "Color Palette"], 3)
    out = {}
    for it in pal:
        def job(app, it=it):
            p = app.PaletteManager.LoadPalette(it["invoke"]["file"])
            r = {"name": p.Name, "identifier": p.Identifier, "count": p.ColorCount}
            g = it["invoke"].get("cdr_com", "")
            if "GetPalette(" in g:
                gid = g.split('"')[1]
                q = app.PaletteManager.GetPalette(gid)
                r["getpalette_name"] = None if q is None else q.Name
            return r
        try:
            r = cd.call(job, 60, note="palette")
        except Exception as e:  # noqa: BLE001
            r = {"error": str(e)[:200]}
        r.update(id=it["id"], harvest_name=it["name"], name_match=r.get("name") == it["name"],
                 harvest_count=(it.get("extra") or {}).get("color_count"))
        out[it["id"]] = r
        print(it["id"], r, flush=True)

    def job2(app):
        ah = app.ArrowHeads
        ls = app.OutlineStyles
        return {"arrowheads": ah.Count, "first": [ah.Item(i).Name for i in range(1, 4)],
                "outline_styles": ls.Count}
    out["libs"] = cd.call(job2, 60)
    # one .pst preset: does the shadow preset file apply anything? (no documented call; just record the file exists)
    return out


SECTIONS = ["docs", "menubar", "menus", "toolbox", "effects", "vector", "tools", "menucmd", "presets"]
NEEDS_DOC = {"menubar", "menus", "effects", "vector", "tools", "menucmd"}


def main(argv):
    want = argv or SECTIONS
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    cd = Corel()
    if "docs_at_start" not in res:
        res["docs_at_start"] = s_docs(cd, res, None)
        save(res)
    td = None
    try:
        for s in want:
            if s in res and s != "effects":
                continue
            if s in NEEDS_DOC and td is None:
                td = TestDoc(cd)
            res[s] = globals()["s_" + s](cd, res, td)
            save(res)
            print("==", s, "done", flush=True)
    finally:
        if td is not None:
            print("close", td.close())
        res["docs_at_end"] = s_docs(cd, res, None)
        save(res)


if __name__ == "__main__":
    main(sys.argv[1:])
