"""PGD/CDR: which commands / tools are enabled in which state, read live with FrameWork.Automation.IsEnabled(guid).

    python enabled_probe.py          -> work/cdr/enabled_probe.json  {guid: {no_doc, doc, rect, bitmap}}

States: no document open (only when CorelDRAW has 0 documents: we never touch other people's documents), our scratch
TestDoc with nothing selected, with the rectangle selected, with the imported bitmap selected. A command enabled only
with a selection "requires" one. Also reads the simple *Bind visibility conditions of menu items (DataSource.GetProperty).
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdr_com import Corel  # noqa: E402
from drawui import UI, bind_of  # noqa: E402
from testdoc import TestDoc  # noqa: E402

WORK = Path(__file__).resolve().parents[2] / "work" / "cdr"
OUT = WORK / "enabled_probe.json"


def guids():
    rows = json.loads((WORK / "menu_live.json").read_text(encoding="utf-8"))
    tl = json.loads((WORK / "tools_live.json").read_text(encoding="utf-8"))
    g = [r["guid"] for r in rows if r.get("guid")]
    g += [r["guid"] for r in tl["toolbox"]] + [t["guid"] for t in tl["all_tools"]]
    return list(dict.fromkeys(g))


def main():
    ui = UI()
    gs = guids()
    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    en = data.setdefault("enabled", {})
    cd = Corel()

    def read(state):
        def job(app):
            au = app.FrameWork.Automation
            out = {}
            for g in gs:
                try:
                    out[g] = bool(au.IsEnabled(g))
                except Exception as e:  # noqa: BLE001
                    out[g] = "error: " + str(e)[:80]
            return out
        for g, v in cd.call(job, timeout=300, note="IsEnabled " + state).items():
            en.setdefault(g, {})[state] = v
        OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")

    if cd.call(lambda a: a.Documents.Count, 30) == 0:
        read("no_doc")
    else:
        data["no_doc_note"] = "skipped: other documents were open"
    td = TestDoc(cd)
    try:
        cd.call(lambda a: td.doc.ClearSelection(), 30)
        read("doc")
        cd.call(lambda a: (td.doc.ClearSelection(), td.rect.CreateSelection()), 30)
        read("rect")
        if td.photo is not None:
            cd.call(lambda a: (td.doc.ClearSelection(), td.photo.CreateSelection()), 30)
            read("bitmap")
        cd.call(lambda a: td.doc.ClearSelection(), 30)
    finally:
        td.close()

    # simple visibility binds of menu items: *Bind(DataSource=X;Path=Y) -> live value
    vis = data.setdefault("visible_bind", {})
    want = {}
    for g in gs:
        e = ui.items.get(g)
        v = e.get("visible") if e is not None else None
        b = bind_of(v) if v and v.startswith("*Bind(") else None
        if b:
            want[g] = b

    def job(app):
        out = {}
        for g, (ds, path) in want.items():
            try:
                src = app.FrameWork.Application.DataContext.GetDataSource(ds)
                out[g] = {"bind": f"{ds}.{path}", "value": None if src is None else str(src.GetProperty(path))}
            except Exception as e:  # noqa: BLE001
                out[g] = {"bind": f"{ds}.{path}", "error": str(e)[:120]}
        return out
    vis.update(cd.call(job, timeout=120, note="visible binds"))
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(len(en), "guids,", len(vis), "visible binds ->", OUT)


if __name__ == "__main__":
    main()
