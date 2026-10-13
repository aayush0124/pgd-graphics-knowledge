"""PGD/CDR: walk CorelDRAW 2024's LIVE toolbox and prove which COM ActiveTool value each tool is.

    python tools_walk.py            -> work/cdr/tools_live.json   (resumes: probe rows already on disk are kept)

1. Live toolbox: Automation.GetNumItemsOnBar / GetItem / GetCaptionText from the Toolbox bar down every flyout.
2. Every other tool: itemData whose currentActiveOfGroup binds AppOrViewDataSource.ActiveTool (DrawUI.xml + the
   active workspace), captioned live.
3. Probe (in a scratch TestDoc, closed unsaved): per tool GUID, reset to Pick, Automation.InvokeItem(guid) (fallback:
   Application.ActiveToolStateGuid = guid), read back Application.ActiveTool + ActiveToolStateGuid. Then per cdrTools
   enum value: Application.ActiveTool = v, read ActiveToolStateGuid. Checkpoint after every row.
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdr_com import Corel  # noqa: E402
from drawui import UI, workspace_root  # noqa: E402
from testdoc import TestDoc  # noqa: E402

WORK = Path(__file__).resolve().parents[2] / "work" / "cdr"
OUT = WORK / "tools_live.json"
TOOLBOX = "7c905e2a-cb64-4ba1-aff0-c306f392680c"   # commandBarData nonLocalizableName="Toolbox"
SEP = "266435b4-6e53-460f-9fa7-f45be187d400"
PICK_ITEM = "f1aee54d-c9aa-4e6f-9193-82f496b0b72b"


def ds_tool(app):
    ds = app.FrameWork.Application.DataContext.GetDataSource("AppOrViewDataSource")
    return None if ds is None else str(ds.GetProperty("ActiveTool"))


def tool_guids(*roots):
    out = []
    for r in roots:
        if r is None:
            continue
        for e in r.iter("itemData"):
            if e.get("type") == "groupedRadioButton" and "Path=ActiveTool" in (e.get("currentActiveOfGroup") or ""):
                if e.get("guid") not in out:
                    out.append(e.get("guid"))
    return out


def bar_names(*roots):
    """item guid -> [nonLocalizableName of every command bar that lists it]"""
    par = {}
    for r in roots:
        if r is None:
            continue
        for b in r.iter("commandBarData"):
            nm = b.get("nonLocalizableName") or b.get("guid")
            for i in b.iter("item"):
                lst = par.setdefault(i.get("guidRef"), [])
                if nm not in lst:
                    lst.append(nm)
    return par


def walk_toolbox(cd, ui):
    def job(app):
        au = app.FrameWork.Automation
        rows = []

        def rec(bar, parent, depth):
            for i in range(au.GetNumItemsOnBar(bar)):
                g, sub = au.GetItem(bar, i)
                if not g or g == SEP:
                    continue
                x = ui.items.get(g)
                a = dict(x.attrib) if x is not None else {}
                fb = a.get("flyoutBarRef")
                rows.append({"guid": g, "caption": au.GetCaptionText(g), "type": a.get("type"), "bar": bar,
                             "parent": parent, "depth": depth, "order": len(rows), "has_sub": bool(sub),
                             "flyoutBarRef": fb, "enabled_no_doc": bool(au.IsEnabled(g))})
                if sub and fb and depth < 4:
                    rec(fb, g, depth + 1)
        rec(TOOLBOX, None, 0)
        return rows
    return cd.call(job, timeout=180, note="toolbox walk")


def main():
    ui = UI()
    ws = workspace_root()
    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    cd = Corel()
    data["app_version"] = cd.call(lambda a: a.Version, 30)
    data["workspace"] = cd.call(lambda a: a.ActiveWorkspace.Name, 30)
    if "toolbox" not in data:
        data["toolbox"] = walk_toolbox(cd, ui)
    allg = tool_guids(ui.root, ws)
    par = bar_names(ui.root, ws)
    caps = data.setdefault("captions", {})
    missing = [g for g in allg if g not in caps]
    if missing:
        caps.update(cd.call(lambda a: {g: a.FrameWork.Automation.GetCaptionText(g) for g in missing}, 120))
    data["all_tools"] = [{"guid": g, "bars": par.get(g, [])} for g in allg]
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")

    probe = data.setdefault("probe", {})
    enum_probe = data.setdefault("enum_probe", {})
    tb_tools = [r["guid"] for r in data["toolbox"] if r["type"] == "groupedRadioButton"]
    todo = [g for g in dict.fromkeys(tb_tools + allg) if g not in probe]
    enums = [m for t in json.loads((WORK / "tlb" / "VGCoreAuto.json").read_text(encoding="utf-8"))["types"]
             if t["name"] == "cdrTools" for m in t["values"]]
    # ActiveTool read-backs that are NOT cdrTools members (Eraser 28, Envelope 29, Mesh Fill 118 ...): does the
    # setter accept them too?
    known = {m["value"] for m in enums}
    rb_probe = data.setdefault("readback_probe", {})
    extra_vals = sorted({r["active_tool"] for r in probe.values() if isinstance(r.get("active_tool"), int)
                         and r["active_tool"] > 0 and r["active_tool"] not in known} - {int(k) for k in rb_probe})
    if not todo and len(enum_probe) == len(enums) and not extra_vals:
        print("nothing to probe")
        return
    td = TestDoc(cd)
    try:
        cd.call(lambda a: a.ActiveDocument.ClearSelection(), 30)
        for g in todo:
            def one(app, g=g):
                au = app.FrameWork.Automation
                app.ActiveTool = 1
                r = {"enabled_with_doc": bool(au.IsEnabled(g))}
                try:
                    au.InvokeItem(g)
                    r["method"] = "Automation.InvokeItem"
                except Exception as e:  # noqa: BLE001
                    r["invoke_error"] = str(e)[:160]
                if (ds_tool(app) or "").lower() != g.lower():
                    try:
                        app.ActiveToolStateGuid = g
                        r["method"] = "Application.ActiveToolStateGuid"
                    except Exception as e:  # noqa: BLE001
                        r["state_error"] = str(e)[:160]
                r["active_tool"] = int(app.ActiveTool)
                r["state_guid"] = app.ActiveToolStateGuid
                # AppOrViewDataSource.ActiveTool holds the toolbox ITEM guid; the state guid can be shared (Pick and
                # Freehand Pick both report 5f85cce2-...), so the data source is the proof the tool is active.
                r["ds_active_tool"] = ds_tool(app)
                r["activated"] = (r["ds_active_tool"] or "").lower() == g.lower()
                return r
            try:
                probe[g] = cd.call(one, timeout=40, note="tool " + g)
            except Exception as e:  # noqa: BLE001
                probe[g] = {"error": str(e)[:200]}
            OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
        for m in enums:
            if m["name"] in enum_probe:
                continue

            def en(app, v=m["value"]):
                app.ActiveTool = 1
                app.ActiveTool = v
                return {"value": v, "active_tool": int(app.ActiveTool), "state_guid": app.ActiveToolStateGuid,
                        "ds_active_tool": ds_tool(app)}
            try:
                enum_probe[m["name"]] = cd.call(en, timeout=40, note="enum " + m["name"])
            except Exception as e:  # noqa: BLE001
                enum_probe[m["name"]] = {"value": m["value"], "error": str(e)[:200]}
            OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
        for v in extra_vals:
            def rb(app, v=v):
                app.ActiveTool = 1
                app.ActiveTool = v
                return {"value": v, "active_tool": int(app.ActiveTool), "state_guid": app.ActiveToolStateGuid,
                        "ds_active_tool": ds_tool(app)}
            try:
                rb_probe[str(v)] = cd.call(rb, timeout=40, note=f"readback {v}")
            except Exception as e:  # noqa: BLE001
                rb_probe[str(v)] = {"value": v, "error": str(e)[:200]}
            OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
        cd.call(lambda a: setattr(a, "ActiveTool", 1), 30)
    finally:
        td.close()
    print(len(probe), "tools probed,", len(enum_probe), "enum values ->", OUT)


if __name__ == "__main__":
    main()
