"""PGD/CDR: read every bitmap effect's live data source (FrameWork.Application.DataContext.GetDataSource(ds))
-> work/cdr/ds_probe.json  {ds: {param_key: {default, min, max, enum, raw}}}

Run on a freshly started CorelDRAW before any effect is applied in the session: the data source's current value of
each param is then the value the effect dialog opens with (recorded as "default"). Range binds (rangeMin="*Bind(...;
Path=MinDepth)") are read the same way. Nothing is applied or changed.
"""
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cdr_com import Corel  # noqa: E402
from drawui import UI, params_from_controls, bind_of  # noqa: E402

OUT = HERE.parents[1] / "work" / "cdr" / "ds_probe.json"


def scalar(v):
    if isinstance(v, bool) or isinstance(v, (int, float, str)):
        return v
    return None


def main():
    ui = UI()
    hv = json.loads((HERE.parents[1] / "harvest" / "cdr" / "cdr_effect.json").read_text(encoding="utf-8"))
    dss = sorted({it["extra"]["data_source"] for it in hv["items"] if it.get("extra", {}).get("data_source")})
    plan = {}
    for ds in dss:
        ctrls = ui.ds_controls(ds)
        ps = []
        for p in params_from_controls(ctrls):
            items_bind = next((bind_of(c.get("items")) for c in ctrls if c["path"] == p["key"] and c.get("items")), None)
            ps.append({"key": p["key"], "minb": p.get("rangeMinBind"), "maxb": p.get("rangeMaxBind"),
                       "items": items_bind[1] if items_bind and items_bind[0] == ds else None})
        plan[ds] = ps
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    cd = Corel()
    for ds, ps in plan.items():
        if ds in res:
            continue

        def job(app, ds=ds, ps=ps):
            src = app.FrameWork.Application.DataContext.GetDataSource(ds)
            out = {}
            for p in ps:
                r = {}
                for tag, k in (("default", p["key"]), ("min", p["minb"]), ("max", p["maxb"]), ("enum", p["items"])):
                    if not k:
                        continue
                    try:
                        v = src.GetProperty(k)
                    except Exception as e:  # noqa: BLE001
                        r.setdefault("errors", {})[tag] = str(e)[:120]
                        continue
                    if tag == "enum":
                        try:
                            vals = [str(x) for x in v] if v is not None and not isinstance(v, str) else None
                        except TypeError:
                            vals = None
                        if vals:
                            r["enum"] = [{"value": x, "label": x} for x in vals]
                        r["raw_items"] = str(v)[:300]
                    else:
                        s = scalar(v)
                        if s is not None:
                            r[tag] = s
                        else:
                            r.setdefault("raw", {})[tag] = str(v)[:200]
                out[p["key"]] = r
            return out

        try:
            res[ds] = cd.call(job, timeout=60, note=ds)
        except Exception as e:  # noqa: BLE001
            res[ds] = {"_error": str(e)[:200]}
        OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")  # checkpoint per DS
    print(len(res), "data sources ->", OUT)


if __name__ == "__main__":
    main()
