"""PGD plan runner, CorelDRAW 2024 backend (run_plan.py drives it; see its docstring for the plan format).

The effect gallery's scene (tools/cdr/effect_gallery.py Scene) is reused: one document of our own, plates on a
hidden masters page, each plan built on the work layer of page 1 and cleared after. Steps act on their "target" (a
label) or on the active shape: at the start the input's main shape (photo, the type, blue_star of the vector plate),
after each step the shape the step left selected (Duplicate, Convert to Bitmap and Convert to Curves leave the new
shape selected), else the shape it acted on. Routes per kind:
  cdr_effect  bitmap effects: Bitmap.ApplyBitmapEffect with the command built as the effect gallery builds it
              (effect_gallery.bitmap_command), in the form its gallery render used (index.json "how": harvested
              defaults left out / enum keys as list index, enum defaults then sent as indexes too), or through the
              object-model twin when the gallery used it (Gamma: Shape.ApplyEffectGamma); vector effects and lenses: the harvest's cdr_com call
              (Shape.CreateContour, CreateDropShadow, CreateLens, Transparency.Apply* ...) with the step's values in
              harvested parameter order (effect_gallery.com_args); a bitmap effect on a vector shape fails (convert it
              first); CreateBlend / AddToPowerClip need a second shape, so they need a "script"
  cdr_menu    FrameWork.Automation.InvokeItem(guid) with the target selected; items the harvest saw open a dialog,
              dockers (Window/), File / Tools items never run (they need a "script"); View items are manual (view only)
  anything    "script": Python run with app, doc, layer (the work layer), s (the target / active shape), labels,
              rgb('#RRGGBB'), PW, PH (page in inches), PX (px per inch), out (the run's output folder: files a
              script writes go there); what it prints goes into the step note; set `result` to the shape that is
              active after
Traps (CorelDRAW 2024): Document.PublishToPDF exports every page, the scene's hidden masters page 2 included: a script
sets PDFSettings.PublishRange = 1 (current page). Shape.Duplicate does not copy a live drop shadow, and the shadow lives
in a separate group shape (type 16): convert that group, not the shape, to keep it in a bitmap. A script that deletes or
converts a labelled shape leaves the label pointing at a dead object: re-label the result.
CorelDRAW is started by this run (Corel(own=True)) and stopped when it ends; one another client started is never
driven. An interrupted run leaves its CorelDRAW behind: `python tools/cdr/plan_cdr.py stop` kills only the pids that
run recorded (work/cdr/plan_run.pids.json).
"""
import importlib.util, json, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("cdr_effect_gallery", HERE / "effect_gallery.py")
eg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eg)
sys.path.insert(0, str(HERE.parents[1]))
import pgd  # noqa: E402

STEP_TIMEOUT = 240
PIDS = HERE.parents[1] / "work" / "cdr" / "plan_run.pids.json"
NO_RUN = ("File/", "Tools/", "Window/", "Help/", "View/")
NEEDS_TWO = ("CreateBlend", "AddToPowerClip")
MAIN = {"photo": "photo", "text": "type", "vector": "blue_star", "blank": "background"}


def _gallery_forms():
    """card id -> the route its gallery render used: {use_base, enum_idx, skip_enums} for the bitmap command, or
    {"om": True} when the render went through the object-model twin (Shape.ApplyEffectGamma ...: the bitmap command
    ignored a key)"""
    out = {}
    idx = eg.OUT / "index.json"
    for row in json.loads(idx.read_text(encoding="utf-8")) if idx.exists() else []:
        how = row.get("how") or ""
        if how.startswith("Shape.ApplyEffect"):
            out[row["id"]] = {"om": True}
        elif "form: " in how:
            f = how.split("form: ", 1)[1]
            out[row["id"]] = {"use_base": "left out" not in f, "enum_idx": "list index" in f,
                              "skip_enums": "without the enum keys" in f}
    return out


def _om_op(eid, it, settings):
    """the Shape.ApplyEffect* twin (effect_gallery.OM_ROUTES) with the step's values, in its argument order"""
    meth, spec, _fixed = eg.OM_ROUTES[eid]
    params = it.get("params") or []
    have = {}
    for k, v in settings.items():
        p = eg.find_param(params, k)
        if p:
            have[p["key"]] = v
    args = [cast(have[h]) if h in have else d for h, d, cast in spec]
    unused = [k for k in settings if (eg.find_param(params, k) or {}).get("key") not in {h for h, _, _ in spec}]
    return {"mode": "om", "meth": meth, "args": args}, unused


_FORMS = None


def _label(st, it):
    return (it or {}).get("path") or (it or {}).get("name") or str(st.get("name") or st.get("id"))


def _effect_op(st, it):
    settings = st.get("settings") or {}
    eid = (it.get("extra") or {}).get("effect_id")
    if eid:
        if eid in eg.UNROUTED:
            return None, "no scripted form: " + eg.UNROUTED[eid][:200], []
        global _FORMS
        if _FORMS is None:
            _FORMS = _gallery_forms()
        form = _FORMS.get(it["id"], {"use_base": True, "enum_idx": False, "skip_enums": False})
        if form.get("om") and eid in eg.OM_ROUTES:
            op, unused = _om_op(eid, it, settings)
            return op, None, [f"{k}: Shape.{op['meth']} has no argument for it" for k in unused]
        if form["enum_idx"]:
            # the form sends enums as list indexes; an enum the step leaves out would go out by NAME from the harvested
            # defaults, which this form ignores (the whole command then changes no pixel): send its default as an index
            settings = dict({p["key"]: p["default"] for p in it.get("params") or []
                             if p.get("type") == "enum" and p.get("default") is not None
                             and p["key"] not in settings and p["name"] not in settings and p["key"] != "Preset"},
                            **settings)
        mapped, dropped, _base, enum_keys, _kv, cmd = eg.bitmap_command(it, settings)
        skip = tuple(enum_keys) if form["skip_enums"] else ()
        return ({"mode": "bitmap", "cmd": cmd(use_base=form["use_base"], enum_idx=form["enum_idx"], skip=skip)}, None,
                [f"{k}: no harvested param of this name or key" for k in dropped]
                + [f"{k}: left out (the gallery form drops enum keys)" for k in skip])
    api = (it.get("invoke") or {}).get("cdr_com") or ""
    meth = api.split("(")[0].split(".")[-1]
    if not meth:
        return None, "no scripted route in the harvest (no effect_id, no cdr_com); give the step a \"script\"", []
    if meth in NEEDS_TWO:
        return None, f"{meth} needs a second shape; give the step a \"script\"", []
    miss = pgd.missing_required(it, settings)
    if miss:
        raise ValueError(f"{meth} needs {', '.join(miss)} (no harvested default): set them in the step's settings")
    return {"mode": "com", "id": it["id"], "api": api, "meth": meth, "settings": settings,
            "lens_type": (it.get("extra") or {}).get("lens_type"),
            "pattern_type": (it.get("extra") or {}).get("pattern_type")}, None, []


def _menu_op(it):
    path, x = it.get("path") or "", it.get("extra") or {}
    if path.startswith("View/"):
        return None, f"view only: {path} changes the window, not the document (an export cannot show it)"
    if path.startswith(NO_RUN):
        return None, f"not run: {path.split('/')[0]} commands open dockers / dialogs or act outside the document; give the step a \"script\""
    if x.get("opens_dialog"):
        return None, f"not run: {path} opens a dialog (the menu route has no values); give the step a \"script\""
    g = (it.get("invoke") or {}).get("cdr_guid")
    if not g:
        return None, "no cdr_guid in the harvest; give the step a \"script\""
    return {"mode": "menu", "guid": g}, None


def compile_steps(plan, inp):
    out = []
    for i, st in enumerate(plan.get("steps", []), 1):
        kind = st.get("kind", "")
        it = pgd._lookup("CDR", kind, st)
        it = it if isinstance(it, dict) else None
        c = {"step": i, "kind": kind, "label": _label(st, it), "target": st.get("target"), "as": st.get("as"),
             "op": None, "manual": None, "untyped": []}
        if st.get("script"):
            c["op"] = {"mode": "script", "src": st["script"]}
        elif it is None and kind in ("cdr_effect", "cdr_menu"):
            c["manual"] = f"cannot compile: no single {kind} item for {st.get('name') or st.get('id')!r}"
        elif kind == "cdr_effect":
            try:
                c["op"], c["manual"], c["untyped"] = _effect_op(st, it)
            except ValueError as e:
                c["error"] = str(e)
        elif kind == "cdr_menu":
            c["op"], c["manual"] = _menu_op(it)
        else:
            c["manual"] = f"{kind} steps have no scripted route of their own; give the step a \"script\""
        out.append(c)
    return out


def _com_call(a, s, op):
    """one vector effect / lens / transparency call on shape s, as effect_gallery.vector_card makes it"""
    it = pgd._lookup("CDR", "cdr_effect", {"id": op["id"]})
    params = it.get("params") or []
    demo = dict(op["settings"])
    meth = op["meth"]
    if op["api"].startswith("Shape.CreateLens") or it["id"].startswith("lens:"):
        lead = [int(demo.pop("Type"))] if "Type" in demo else [int(op["lens_type"])]
        args, _ = eg.com_args(a, [p for p in params if p["key"] != "Type"], demo)
        return s.CreateLens(*(lead + args)), f"CreateLens{tuple(lead + args)}"
    if "Transparency." in op["api"]:
        args, _ = eg.com_args(a, params, demo)
        if op.get("pattern_type") is not None:
            args = [op["pattern_type"]] + (args if args and args[0] is not None else [""] + args[1:])
        getattr(s.Transparency, meth)(*args)
        return None, f"Transparency.{meth}{tuple(args)}"
    if meth in ("CreatePushPullDistortion", "CreateTwisterDistortion", "CreateZipperDistortion"):
        demo.setdefault("OriginX", s.CenterX)
        demo.setdefault("OriginY", s.CenterY)
    args, _ = eg.com_args(a, params, demo)
    return getattr(s, meth)(*args), f"{meth}{tuple(args)}"


class Session:
    """our own CorelDRAW 2024 and one scene document (effect_gallery.Scene)"""

    def __init__(self):
        eg.TMP.mkdir(parents=True, exist_ok=True)
        self._start()
        self.version = self.sc.call(lambda a: a.Version, 30, "version")
        self.labels, self.active = {}, None

    def _start(self):
        self.sc = eg.Scene()
        PIDS.write_text(json.dumps(sorted(self.sc.cd.pids)), encoding="utf-8")  # what `plan_cdr.py stop` may kill

    def _layers(self, a):
        w = self.sc.s["work"]
        out = []
        for i in range(1, w.Shapes.Count + 1):
            sh = w.Shapes.Item(i)
            try:
                fx = sh.Effects.Count
            except Exception:  # noqa: BLE001
                fx = 0
            out.append(f"{sh.Name or '(unnamed)'} [type {sh.Type}{f', {fx} effects' if fx else ''}]")
        return out

    def open(self, inp):
        sc = self.sc

        def job(a):
            sc.clear()
            doc = sc.s["doc"]
            doc.Unit = 1
            doc.Pages.Item(1).SetSize(eg.PW, eg.PH)
            sc.s["page1"].Activate()
            sc.s["work"].Activate()
            lab, plate = {}, inp["plate"]
            if plate == "photo" and inp.get("_photo"):  # a damaged photo plate (run_plan.damaged_photo)
                ph = sc._import(Path(inp["_photo"]))[0]
                ph.SetBoundingBox(0.0, 0.0, eg.PW, eg.PH, False, eg.BL)
                lab["photo"] = ph
            elif plate == "photo":
                lab.update(sc.plate("photo"))
            elif plate == "vector":
                lab.update(sc.plate("vector"))
            if plate in ("text", "blank") or inp.get("background"):
                bg = sc.s["work"].CreateRectangle2(0.0, 0.0, eg.PW, eg.PH, 0, 0, 0, 0)
                bg.Fill.ApplyUniformFill(eg.rgb(a, inp.get("background") or ("#808080" if plate == "text" else "#FFFFFF")))
                bg.Outline.SetNoOutline()
                bg.Name = "background"
                bg.OrderToBack()
                lab["background"] = bg
            if plate == "text" or inp.get("text"):
                px = float(inp.get("size") or (360 if plate == "text" else 150))
                t = sc.s["work"].CreateArtisticText(0.0, 0.0, inp.get("text") or "PGD", 0, -1,
                                                    inp.get("font") or "Arial Black", px * 72 / eg.PX)
                t.Fill.ApplyUniformFill(eg.rgb(a, inp.get("color") or ("#E1E1E1" if plate == "text" else "#FFFFFF")))
                t.Outline.SetNoOutline()
                cx, cy = inp.get("at") or (960, 540)
                t.SetPosition(cx / eg.PX - t.SizeWidth / 2, eg.PH - cy / eg.PX + t.SizeHeight / 2)
                t.Name = "type"
                lab["type"] = t
            main = lab.get(MAIN[plate]) or next(iter(lab.values()), None)
            if main is not None:
                main.CreateSelection()
            return lab, main
        self.labels, self.active = sc.call(job, 300, "plan:open")
        return dict(self.labels)

    def step(self, cs, target, labels=None):
        sc, op = self.sc, cs["op"]
        s = target if target is not None else self.active
        note = ["settings not sent: " + ", ".join(cs["untyped"])] if cs.get("untyped") else []

        def job(a):
            info = ""
            if op["mode"] == "script":
                ns = {"app": a, "doc": sc.s["doc"], "layer": sc.s["work"], "s": s,
                      "labels": labels if labels is not None else self.labels,
                      "rgb": lambda h: eg.rgb(a, h), "PW": eg.PW, "PH": eg.PH, "PX": eg.PX, "result": None,
                      "out": str(getattr(self, "out", "."))}
                import contextlib, io
                said = io.StringIO()
                with contextlib.redirect_stdout(said):
                    exec(op["src"], ns)  # noqa: S102 (the plan's own script: run only plans you trust)
                said = " ".join(said.getvalue().split())
                return ns.get("result"), "script ran" + (f"; script says: {said}" if said else ""), False
            if s is None:
                raise RuntimeError("no target shape (the input has none and no step selected one)")
            if op["mode"] == "om":
                if s.Type != 5:
                    raise RuntimeError(f"the target is not a bitmap (shape type {s.Type}): convert it first")
                getattr(s, op["meth"])(*op["args"])
                info = f"Shape.{op['meth']}{tuple(op['args'])} (the gallery's object-model route for this effect)"
            elif op["mode"] == "bitmap":
                if s.Type != 5:  # cdrBitmapShape
                    raise RuntimeError(f"the target is not a bitmap (shape type {s.Type}): convert it first "
                                       "(Object > Convert to Bitmap)")
                s.Bitmap.ApplyBitmapEffect("PGD plan", op["cmd"])
                info = f"ApplyBitmapEffect('{op['cmd'][:160]}')"
            elif op["mode"] == "com":
                _e, info = _com_call(a, s, op)
            elif op["mode"] == "menu":
                s.CreateSelection()
                a.FrameWork.Automation.InvokeItem(op["guid"])
                info = f"InvokeItem({op['guid']})"
            sel = a.ActiveSelectionRange
            after = sel.Item(1) if sel is not None and sel.Count == 1 else s
            gone = False
            if s is not None:
                try:
                    s.Type  # a shape the step replaced (Convert to Bitmap / Curves) no longer answers
                except Exception:  # noqa: BLE001
                    gone = True
            return after, info, gone
        try:
            after, info, gone = sc.call(job, STEP_TIMEOUT, f"plan step {cs['step']}")
        except Exception as e:  # noqa: BLE001
            if "CallTimeout" in type(e).__name__:
                self.recover(e)
            return "failed", "; ".join([f"{type(e).__name__}: {e}"] + note)[:500], None
        if gone and after is not None and labels:
            moved = [k for k, v in labels.items() if v is s]
            for k in moved:
                labels[k] = after
            if moved:
                note.append(f"label {', '.join(moved)} now names the result (the step replaced the shape)")
            self.labels = labels
        if after is not None:
            self.active = after
        return "ok", "; ".join(note + [info])[:500], after

    def snap(self, path, w=480):
        try:
            self.sc.call(lambda a: self.sc.export(path), 120, "plan:snap")
        except Exception as e:  # noqa: BLE001
            print(f"    (no step frame: {e})"[:200], flush=True)

    def detail(self, path):
        """the 1:1 detail crop (run_plan.DETAIL = the gallery's CROP_BOX): that page region exported at 100 %"""
        try:
            self.sc.call(lambda a: self.sc.export_crop(path), 120, "plan:detail")
        except Exception as e:  # noqa: BLE001 (the frame and the strip still exist; the crop is a bonus)
            print(f"    (no detail crop: {e})"[:200], flush=True)

    def export(self, full):
        self.sc.call(lambda a: self.sc.export(full), 180, "plan:export")
        return self.sc.call(self._layers, 60, "plan:layers")

    def close(self):
        try:
            self.sc.call(lambda a: self.sc.clear(), 120, "plan:clear")
        except Exception:  # noqa: BLE001
            pass
        self.labels, self.active = {}, None

    def recover(self, err):
        """a hung call leaves the COM thread stuck: kill the CorelDRAW we started and build a new scene"""
        print(f"    CorelDRAW recovery after: {err}"[:200], flush=True)
        try:
            self.sc.cd.kill()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(10)
        self._start()

    def quit(self):
        """close our document and stop the CorelDRAW this session started (Corel.kill: its own pids only), so the next
        run can start its own"""
        self.close()
        try:
            self.sc.close()
        except Exception:  # noqa: BLE001
            pass
        print(f"  stopped our CorelDRAW: pids {self.sc.cd.kill()}", flush=True)
        PIDS.unlink(missing_ok=True)


def stop():
    """kill the CorelDRAW a plan run started and left behind (an interrupted run): only the pids it recorded"""
    import psutil
    try:
        pids = json.loads(PIDS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return print("no CorelDRAW recorded by a plan run (work/cdr/plan_run.pids.json)")
    for pid in pids:
        try:
            p = psutil.Process(pid)
            for q in p.children(recursive=True) + [p]:
                q.kill()
            print("killed", pid)
        except psutil.NoSuchProcess:
            print("gone", pid)
    PIDS.unlink(missing_ok=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["stop"]:
        stop()
    else:
        print(__doc__)
