"""PGD/CDR stage "effects": every item under CorelDRAW 2024's Effects menu + the interactive vector effects
-> harvest/cdr/cdr_effect.json

    python harvest_effects.py            build (re-uses work/cdr/menu_live.json, captions.json, ds_probe.json,
                                         apply_tests.json when present: run menu_walk.py / probe_ds.py /
                                         apply_tests.py first to refresh them)

Sources, all read from this install: the live menu walk (menu_walk.py: Automation.GetItem + GetCaptionText),
DrawUI.xml dialog controls bound to each effect's data source (drawui.py), captions of those controls from the running
app (GetCaptionText, cached in captions.json), live data-source reads (probe_ds.py), the VGCore 25.1 typelib
(tlb_dump.py) and apply tests on a scratch document (apply_tests.py).
"""
import json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from drawui import UI, params_from_controls, bind_of  # noqa: E402

PGD = HERE.parents[1]
WORK = PGD / "work" / "cdr"
OUT = PGD / "harvest" / "cdr" / "cdr_effect.json"
CAPS = WORK / "captions.json"
TLB = WORK / "tlb" / "VGCoreAuto.json"

NAME_FIX = {"NNArtStyle": "ArtStyle"}   # menu OnNNArtStyle applies ArtStyleEffect (ApplyOrDeleteEffect:ArtStyleEffect)


def clean(c):
    return (c or "").replace("&&", "\0").replace("&", "").replace("\0", "&").replace("...", "").strip().rstrip(":")


def load(p, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def keep_cmd_forms(items, old):
    """extra.cmd_form is not harvested: it is the bitmap-command form a gallery render proved (recorded from
    gallery/cdr_effect/index.json; plan_cdr._gallery_forms reads it, so a clone without gallery/ sends the proven form).
    A re-harvest carries it over by id from the file it replaces."""
    forms = {it.get("id"): it["extra"]["cmd_form"] for it in (old or {}).get("items") or []
             if isinstance(it.get("extra"), dict) and it["extra"].get("cmd_form")}
    for it in items:
        if it["id"] in forms:
            it.setdefault("extra", {})["cmd_form"] = forms[it["id"]]
    return items


def caption_guids(ui, ctrls):
    gs = set()
    for c in ctrls:
        gs.add(c["guid"])
        gs.update(ui.label_for(c["guid"]))
        if c.get("captionRef"):
            gs.add(c["captionRef"])
    return gs


def fetch_captions(guids):
    """GetCaptionText for every guid not yet cached (one COM job), cache to captions.json."""
    caps = load(CAPS, {})
    todo = sorted(g for g in guids if g and g not in caps)
    if todo:
        from cdr_com import Corel
        cd = Corel()

        def job(app):
            au, out = app.FrameWork.Automation, {}
            for g in todo:
                try:
                    out[g] = au.GetCaptionText(g)
                except Exception as e:  # noqa: BLE001
                    out[g] = "!ERR " + str(e)[:80]
            return out

        caps.update(cd.call(job, timeout=600))
        CAPS.write_text(json.dumps(caps, indent=0, ensure_ascii=False), encoding="utf-8")
    return caps


def cap_of(ui, caps, c):
    """Display label of a dialog control: its own caption, its label statusText, or its captionRef."""
    for g in [c["guid"]] + ui.label_for(c["guid"]) + ([c["captionRef"]] if c.get("captionRef") else []):
        t = clean(caps.get(g, ""))
        if t and not t.startswith("!ERR"):
            return t
    return None


ITEM = re.compile(r'<itemData\s([^>]*)/>')
ATTR = re.compile(r'(\w+)="([^"]*)"')


def xml_items(v):
    """The data sources hand combo items back as '<container><itemData text=".." value=".."/>..' strings."""
    if not isinstance(v, str) or "<itemData" not in v:
        return None
    out = []
    for m in ITEM.finditer(v):
        a = dict(ATTR.findall(m.group(1)))
        out.append(a)
    return out


def live_param(raw):
    """ds_probe.json entry -> {default, min, max, enum} with combo itemData strings decoded."""
    if not raw:
        return {}
    q = {k: raw[k] for k in ("min", "max") if isinstance(raw.get(k), (int, float)) and not isinstance(raw.get(k), bool)}
    items = xml_items(raw.get("raw_items"))
    if items:
        vals = [{"value": a.get("value", a.get("guid")), "label": a.get("text") or a.get("guid")}
                for a in items if a.get("text") or a.get("value")]
        if vals:
            q["enum"] = vals
    d = raw.get("default")
    di = xml_items(d)
    if di:
        a = di[0]
        if a.get("text") or a.get("value"):
            q["default"] = a.get("value", a.get("text"))
    elif d is not None and d != "":
        q["default"] = d
    return q


def ptype(p):
    ctl = set(p["controls"])
    if "groupedRadioButton" in ctl:
        return "enum"
    if "checkButton" in ctl:
        return "bool"
    if ctl & {"slider", "spinner", "compassWheel", "imageSlider"}:
        return "int" if p.get("numDecimalPlaces") == "0" else "number"
    if ctl & {"comboBoxEx", "comboBox", "cellCombo", "listBox"}:
        return "color" if re.search(r"colou?r(item)?$", p["key"], re.I) else "enum"
    if ctl & {"editBox", "statusText"}:
        return "string"
    return "unknown"


def bitmap_params(ui, caps, ds, probe):
    ctrls = ui.ds_controls(ds)
    out = []
    for p in params_from_controls(ctrls):
        cs = [c for c in ctrls if c["path"] == p["key"]]
        # a radio group has no caption of its own (each button carries its option's caption): name it by its key
        name = None if p.get("enum") else next((n for n in (cap_of(ui, caps, c) for c in cs) if n), None)
        q = {"name": name or p["key"], "key": p["key"], "type": ptype(p)}
        live = live_param((probe or {}).get(p["key"]))
        for k in ("min", "max"):
            src = p.get("range" + k.capitalize())
            if isinstance(src, (int, float)):
                q[k] = src
            elif isinstance(live.get(k), (int, float)) and not isinstance(live.get(k), bool):
                q[k] = live[k]
        if "default" in live:
            q["default"] = live["default"]
        if "degrees" in str(p.get("increment", "")):
            q["unit"] = "deg"
        if p.get("enum"):
            q["enum"] = [{"value": e["value"],
                          "label": clean(caps.get(e["guid"], "")) or clean(caps.get(e.get("captionRef") or "", ""))
                          or e["value"]} for e in p["enum"]]
        elif live.get("enum"):
            q["enum"] = live["enum"]
        x = {k: p[k] for k in ("increment", "numDecimalPlaces", "transform", "rangeMinBind", "rangeMaxBind") if k in p}
        x["controls"] = sorted(set(p["controls"]))
        if name is None:
            x["caption"] = ("radio group: options carry the captions, name is the data-source path" if p.get("enum")
                            else "no caption on the control: name is the data-source path")
        q["extra"] = x
        out.append(q)
    seen = {}
    for q in out:
        seen[q["name"]] = seen.get(q["name"], 0) + 1
    for q in out:  # one caption on several controls (Color Balance: "Cyan -- Red" x3): keep it addressable
        if seen[q["name"]] > 1:
            q["name"] = f"{q['name']} ({q['key']})"
    return out


def main():
    ui = UI()
    rows = [r for r in load(WORK / "menu_live.json", []) if r.get("guid") and r["path"].startswith("Effects/")]
    live_guids = {r["guid"] for r in rows}
    # XML entries of the Effects bars that the live menu does not show (hidden in this build)
    hidden = []
    for fl in ui.menu_tree("21cd018a-87c1-476c-9a98-a8e36b9c479e"):
        for ch in fl.get("children", []):
            if ch["guid"] not in live_guids and ch.get("type") != "separator":
                parent = next(r for r in rows if r["guid"] == fl["guid"])
                hidden.append({"guid": ch["guid"], "parent": parent["path"], "onInvoke": ch.get("onInvoke")})

    probe = load(WORK / "ds_probe.json", {})
    tests = load(WORK / "apply_tests.json", {})
    items, need = [], set(h["guid"] for h in hidden)
    plan = []
    for r in rows:
        b = bind_of(r.get("onInvoke"))
        plan.append((r, b))
    for h in hidden:
        plan.append(({"path": None, "guid": h["guid"], "parent": h["parent"], "onInvoke": h["onInvoke"],
                      "type": "button", "hidden": True}, bind_of(h["onInvoke"])))
    for r, b in plan:
        if b and b[0] == "EffectsDialogFactoryDS":
            key = b[1][2:]
            ds = NAME_FIX.get(key, key) + "EffectDS"
            need |= caption_guids(ui, ui.ds_controls(ds))
    caps = fetch_captions(need)

    for r, b in plan:
        if r.get("type") == "flyout":
            continue
        # names may contain "/" (Pinch/Punch, Hue/Saturation/Lightness): take them from captions, never split paths
        name = clean(r.get("caption") if r.get("caption") is not None else caps.get(r["guid"], ""))
        par = next((x for x in rows if x.get("flyoutBarRef") == r.get("bar")), None) if r["path"] else             next(x for x in rows if x["path"] == r["parent"])
        path = r["path"] or (r["parent"] + "/" + name)
        it = {"name": name, "id": r["guid"], "path": path, "invoke": {"cdr_guid": r["guid"]}}
        if par and par["path"] != "Effects":
            it["category"] = clean(par["caption"])
        if b and b[0] == "EffectsDialogFactoryDS":
            key = NAME_FIX.get(b[1][2:], b[1][2:])
            eid = key + "Effect"
            ds = eid + "DS"
            it["requires"] = ("bitmap shape for the scripted path (Shape.Bitmap); from the menu any bitmap or vector "
                              "object (non-destructive in CorelDRAW 2024)")
            it["params"] = bitmap_params(ui, caps, ds, probe.get(ds))
            t = tests.get(eid)
            it["extra"] = {"effect_id": eid, "data_source": ds, "menu_binding": b[1],
                           "properties_docker_toggle": f"EffectsPropertiesDS;Path=ApplyOrDeleteEffect:{eid}"}
            it["invoke"]["cdr_com"] = ("Shape.Bitmap.ApplyBitmapEffect(UndoString: string, Command: string) -> void; "
                                       "Command = '<effect_id> <param key>=<value>,...'")
            it["extra"]["cmd_template"] = eid + (" " + ",".join(f"{q['key']}=<{q['type']}>" for q in it["params"]
                                                                 if q["type"] in ("number", "int", "bool", "enum"))
                                                 if it["params"] else "")
            if t and t.get("cmd"):
                it["invoke"]["cdr_effect_cmd"] = t["cmd"]
            elif not t:
                it["extra"]["cmd_status"] = ("command format proven on 6 other effects (apply_tests.py); this effect's "
                                             "command string not applied in a test")
            ev = ["menu: live Automation.GetItem walk + GetCaptionText",
                  f"params: DrawUI.xml controls bound to DataSource={ds} (keys = data-source paths, literal rangeMin/rangeMax)",
                  "param names: GetCaptionText on the control / its label"]
            if probe.get(ds):
                ev.append("min/max/default/enum from live data-source read (probe_ds.py)")
            if t:
                ev.append("apply test: " + t.get("result", ""))
            it["evidence"] = "; ".join(ev)
            if not it["params"]:
                it["extra"]["no_dialog_params"] = True
            pr = probe.get(ds) or {}
            if any("NoneType" in str((v or {}).get("errors", "")) for v in pr.values() if isinstance(v, dict)):
                it["error"] = ("data source " + ds + " is not instantiated until its dialog opens: live defaults and "
                               "bound ranges (rangeMinBind/rangeMaxBind) not read")
            if t and t.get("error"):
                it["error"] = t["error"]
        elif (r.get("check") or "").startswith("*Docker("):
            it["invoke"]["cdr_guid"] = r["guid"]
            it["extra"] = {"opens_docker": r["check"][9:-2]}
            it["category"] = "Docker"
            it["evidence"] = "menu: live Automation walk; item toggles a docker (DrawUI.xml check=*Docker(...))"
        else:
            it["extra"] = {"binding": r.get("onInvoke") or r.get("check")}
            it["evidence"] = "menu: live Automation walk"
            if b and b[1] == "OnFinalizeEffects":
                from vector_effects import sig
                it["invoke"]["cdr_com"] = sig("IVGShape", "FlattenEffects") + " (also on ShapeRange)"
                it["evidence"] += "; object-model equivalent from typelib VGCoreAuto.tlb 25.1"
        if r.get("hidden"):
            it.setdefault("extra", {})["in_live_menu"] = False
            it["evidence"] += "; listed in DrawUI.xml Effects bar but NOT shown by the live menu (Automation.GetItem)"
        items.append(it)

    # vector effects (vector.py adds them; kept separate so this file stays about the menu)
    from vector_effects import vector_items, enrich
    enrich(items, tests)
    items += vector_items(caps, tests)
    keep_cmd_forms(items, load(OUT, {}))

    version = load(WORK / "app_version.json", {}).get("version", "25.1.0.269")
    doc = {"app": "CDR", "kind": "cdr_effect", "app_version": version,
           "source": "live FrameWork.Automation menu walk + DrawUI.xml dialog controls + VGCore 25.1 typelib "
                     "+ live data-source probe + apply tests (PGD/tools/cdr/harvest_effects.py)",
           "items": items}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    print(len(items), "items ->", OUT)
    if (WORK / "audit_live.json").exists():   # re-apply the independent audit's live verdicts (apply_audit.py)
        import apply_audit
        apply_audit.main()


if __name__ == "__main__":
    main()
