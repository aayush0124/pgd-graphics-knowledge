"""PGD plan runner, Illustrator 2026 backend (run_plan.py drives it; see its docstring for the plan format).

File-based, like the effect gallery: the working document is an .ai file; each step is one ExtendScript call that
opens the previous step's file, acts, exports the step frame (960x540) and saves the next file
(work/ai/effect_gallery/plans/<n>.ai), so a hang or an error names its step and no state lives in Illustrator
between calls. Labels are item names (they survive save and reopen): vector plate -> art (group PGD_TEST) and its
items by SVG id; photo -> photo (the embedded image); text / blank -> background (artboard-size rectangle); any
"text" -> type (a point text frame). A step acts on its "target", else on the active item (the input's main item
first: art, photo or type; after each step the single selected item, else the one it acted on).
Routes per kind:
  ai_effect      the effect gallery's plan (effect_gallery.plan_effect): applyEffect(<LiveEffect> XML) on the target;
                 when values cannot travel in the XML (Photoshop-effect descriptors, FillStyle colours) the saved file's
                 effect dictionary is replaced by the one Illustrator's own dialog stores (probe file) with the values
                 written in, and the file reopened and re-rendered (the gallery's patched route); Pathfinder is moved to
                 the head of the appearance chain
  ai_blend_mode  target.blendingMode = the harvested BlendModes value
  ai_menu        app.executeMenuCommand(id) with the target selected; commands that open a dialog (title ending in
                 '...'), panels (Window/), preferences and file commands are never run: they need a "script"
  anything       "script": ExtendScript with d = the document, T = the target / active item, g = group PGD_TEST (or
                 null), r = the result object (set r.active = an item name to make it active), OUT = the run's output
                 folder (files a script writes go there), say(msg) (a check's finding, recorded in the step note)
Illustrator is started by this backend (pid in work/ai/plan_run.pid) and stopped when the run ends; one another
client started is never sent a script.
"""
import importlib.util, json, subprocess, sys, time, types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import pgd  # noqa: E402


def _load_gallery():
    """tools/ai/effect_gallery.py; without pywin32 (CI) the Illustrator COM module is stubbed: compile only"""
    try:
        import pythoncom  # noqa: F401
    except ImportError:
        nop = lambda *a, **k: None  # noqa: E731
        sys.modules.setdefault("aicom", types.SimpleNamespace(js=nop, js_watch=lambda *a, **k: (None, None, []),
                                                              ai_pid=nop, main_hwnd=nop, PANELS=(), dialogs=lambda: [],
                                                              u32=None, ai_windows=lambda *a: [], ctypes=None))
    sys.path.insert(0, str(HERE))
    spec = importlib.util.spec_from_file_location("ai_effect_gallery", HERE / "effect_gallery.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


eg = _load_gallery()
PIDFILE = eg.ROOT / "work" / "ai" / "plan_run.pid"
DIR = eg.WORK / "plans"  # under the gallery's work folder, so eg.cleanup() closes what a failed call left open
STEP_TIMEOUT = 300
NO_RUN = ("Window/", "Help/", "Edit/Preferences", "File/Package", "File/Print", "File/Document Setup",
          "File/Save", "File/Export", "File/Close", "File/Open", "File/Place", "File/Scripts")
MAIN = {"vector": "art", "photo": "photo", "text": "type", "blank": "background"}

LIB = r'''function byName(n){try{return d.pageItems.getByName(n);}catch(e){return null;}}
function nameOf(it){if(!it)return "";if(!it.name)it.name="pgd_item_"+d.pageItems.length+"_"+Math.floor(Math.random()*1e6);return it.name;}
function rgb(h){h=h.replace("#","");var c=new RGBColor();c.red=parseInt(h.substr(0,2),16);c.green=parseInt(h.substr(2,2),16);c.blue=parseInt(h.substr(4,2),16);return c;}
var AB=d.artboards[0].artboardRect;
'''
SELECT = r'''var T=%(target)s?byName(%(target)s):null;if(%(target)s&&!T)throw new Error("no item named "+%(target)s);
d.selection=null;if(T)T.selected=true;
'''
AFTER = r'''if(!r.active){var A=(d.selection&&d.selection.length==1)?d.selection[0]:T;r.active=nameOf(A);}
var L=[];for(var i=0;i<d.pageItems.length&&i<60;i++){var p=d.pageItems[i];if(p.parent.typename=="Layer"||p.parent.name=="PGD_TEST")L.push((p.name||"(unnamed)")+" ["+p.typename+(p.blendingMode!=BlendModes.NORMAL?" "+String(p.blendingMode).replace("BlendModes.","").toLowerCase():"")+(p.opacity<100?" "+Math.round(p.opacity)+"%":"")+"]");}
r.layers=L.join("|");d.selection=null;
'''
OPEN = r'''var I=%(inp)s;
if(I.plate=="photo"&&g&&g.pageItems.length)g.pageItems[0].name="photo";
if(I.plate=="text"||I.plate=="blank"||I.background){var bg=d.layers[0].pathItems.rectangle(AB[1],AB[0],AB[2]-AB[0],AB[1]-AB[3]);
 bg.stroked=false;bg.filled=true;bg.fillColor=rgb(I.background||(I.plate=="text"?"#808080":"#FFFFFF"));bg.name="background";bg.zOrder(ZOrderMethod.SENDTOBACK);}
if(I.plate=="text"||I.text){var tf=d.layers[0].textFrames.add();tf.contents=I.text||"PGD";var ca=tf.textRange.characterAttributes;
 try{ca.textFont=app.textFonts.getByName(I.font||"Arial-Black");}catch(e){}ca.size=I.size||(I.plate=="text"?360:150);
 ca.fillColor=rgb(I.color||(I.plate=="text"?"#E1E1E1":"#FFFFFF"));var at=I.at||[960,540],b=tf.geometricBounds;
 tf.translate(AB[0]+at[0]-(b[0]+b[2])/2,AB[1]-at[1]-(b[1]+b[3])/2);tf.name="type";}
r.active=%(main)s;
'''


DAMAGED_BASE = r'''(function(){var d=app.documents.add(DocumentColorSpace.RGB,1920,1080);
d.rasterEffectSettings.resolution=%d;var g=d.layers[0].groupItems.add();g.name="PGD_TEST";var pi=g.placedItems.add();
pi.file=new File(File(%s).fsName);pi.width=1920;pi.height=1080;var a2=d.artboards[0].artboardRect;
pi.position=[a2[0],a2[1]];pi.embed();var o=new IllustratorSaveOptions();o.compressed=false;
d.saveAs(new File(File(%s).fsName),o);d.close(SaveOptions.DONOTSAVECHANGES);return "ok";})();'''


def _label(st, it):
    return (it or {}).get("path") or (it or {}).get("name") or str(st.get("name") or st.get("id"))


_CTX = None


def ctx():
    """the gallery's Ctx (harvest + dialog probe file); without the probe file (a fresh clone, CI) values that need
    the patched route are reported as not sent"""
    global _CTX
    if _CTX is None:
        try:
            _CTX = eg.Ctx()
        except OSError:
            c = eg.Ctx.__new__(eg.Ctx)
            c.harvest = {k: {i["id"]: i for i in json.loads((eg.ROOT / "harvest" / "ai" / f"{k}.json")
                                                           .read_text("utf-8"))["items"]} for k in eg.KINDS}
            c.probe, c.by_le = {}, {}
            for it in c.harvest["ai_effect"].values():
                le = (it.get("invoke") or {}).get("ai_live_effect") or (it.get("extra") or {}).get("live_effect_name")
                if le:
                    c.by_le.setdefault(le, it)
            _CTX = c
    return _CTX


def effect_plan(it, settings):
    return eg.plan_effect(ctx(), {"demo_settings": dict(settings or {})}, it)


def _menu_op(it):
    path = it.get("path") or ""
    if path.startswith("View/"):
        return None, f"view only: {path} changes the window, not the document (an export cannot show it)"
    if path.startswith(NO_RUN):
        return None, f"not run: {path} opens a panel or dialog or acts outside the document; give the step a \"script\""
    if path.endswith("...") or "..." in path.split("/")[-1]:
        return None, f"needs values: {path} opens a dialog; give the step a \"script\" (its DOM equivalent)"
    cmd = (it.get("invoke") or {}).get("ai_menu")
    if not cmd:
        return None, "no executeMenuCommand id in the harvest; give the step a \"script\""
    return {"mode": "menu", "cmd": cmd}, None


def compile_steps(plan, inp):
    out = []
    for i, st in enumerate(plan.get("steps", []), 1):
        kind = st.get("kind", "")
        it = pgd._lookup("AI", kind, st)
        it = it if isinstance(it, dict) else None
        c = {"step": i, "kind": kind, "label": _label(st, it), "target": st.get("target"), "as": st.get("as"),
             "op": None, "manual": None, "untyped": []}
        try:
            if st.get("script"):
                c["op"] = {"mode": "script", "src": st["script"]}
            elif it is None and kind in ("ai_effect", "ai_blend_mode", "ai_menu"):
                raise ValueError(f"no single {kind} item for {st.get('name') or st.get('id')!r}")
            elif kind == "ai_effect":
                pl = effect_plan(it, st.get("settings"))
                c["op"] = {"mode": "effect", "id": it["id"], "settings": st.get("settings") or {}, "xml": pl.get("xml"),
                           "patch": bool(pl.get("patch")), "chain_first": bool(pl.get("chain_first")),
                           "dom": pl.get("dom")}
                c["untyped"] = list(pl.get("dropped") or [])
            elif kind == "ai_blend_mode":
                mode = ((it.get("invoke") or {}).get("ai_dom") or "").split("=")[-1].strip() or f"BlendModes.{it['id']}"
                c["op"] = {"mode": "blend", "blend": mode}
            elif kind == "ai_menu":
                c["op"], c["manual"] = _menu_op(it)
            else:
                c["manual"] = f"{kind} steps have no scripted route of their own; give the step a \"script\""
        except ValueError as e:
            c["manual"] = f"cannot compile: {e}"
        out.append(c)
    return out


def _find_pid():
    return eg.find_pid()


class Session:
    def __init__(self):
        pid, mine = _find_pid(), self._recorded()
        if pid and pid != mine:
            raise RuntimeError(f"an Illustrator this runner did not start is running (pid {pid}): not sending it scripts")
        if not pid:
            p = subprocess.Popen([eg.EXE], creationflags=0x00000008 | 0x00000200)  # DETACHED | NEW_PROCESS_GROUP
            PIDFILE.parent.mkdir(parents=True, exist_ok=True)
            PIDFILE.write_text(str(p.pid))
            time.sleep(15)
        self.version = eg.ready()
        DIR.mkdir(parents=True, exist_ok=True)
        self.n, self.cur, self.active = 0, None, None

    @staticmethod
    def _recorded():
        try:
            return int(PIDFILE.read_text().strip())
        except (OSError, ValueError):
            return None

    def _next(self):
        self.n += 1
        return DIR / f"{self.n:05d}.ai"

    def _call(self, open_path, body, png=None, save=None, timeout=STEP_TIMEOUT):
        res, err = eg.call(open_path, LIB + body, png=png, save=save, timeout=timeout)
        if err:
            raise RuntimeError(err)
        return res

    def open(self, inp):
        plate = inp["plate"]
        src = {"vector": "vector", "photo": "photo"}.get(plate)
        if plate == "photo" and inp.get("_photo"):  # a damaged photo plate: its own base, built like the gallery's
            base = DIR / (Path(inp["_photo"]).stem + "_base.ai")
            if not base.exists():
                r, e, _ = eg.run(DAMAGED_BASE % (eg.RES, eg.jsq(inp["_photo"]), eg.jsq(base)), 300)
                if r != "ok":
                    raise RuntimeError(f"damaged photo base: {r} {e}")
        elif src:
            eg.make_base(src)
            base = eg.PLATES[src][1]
        else:
            base = DIR / "blank_base.ai"
            if not base.exists():
                r, e, _ = eg.run(r'''(function(){var d=app.documents.add(DocumentColorSpace.RGB,1920,1080);
d.rasterEffectSettings.resolution=%d;var o=new IllustratorSaveOptions();o.compressed=false;
d.saveAs(new File(File(%s).fsName),o);d.close(SaveOptions.DONOTSAVECHANGES);return "ok";})();''' % (eg.RES, eg.jsq(base)), 120)
                if r != "ok":
                    raise RuntimeError(f"blank base: {r} {e}")
        out = self._next()
        inp = {k: v for k, v in inp.items() if k != "_photo"}
        main = MAIN[plate] if plate != "photo" or not inp.get("text") else "photo"
        res = self._call(base, OPEN % {"inp": json.dumps(inp), "main": json.dumps(main)}, save=out, timeout=180)
        self.cur, self.active = out, res.get("active") or main
        labels = {"background": "background"} if plate in ("text", "blank") or inp.get("background") else {}
        if plate == "vector":
            labels.update({k: k for k in pgd.INPUT_LABELS["vector"]})
            labels["art"] = "PGD_TEST"
            self.active = "PGD_TEST"
        if plate == "photo":
            labels["photo"] = "photo"
        if plate == "text" or inp.get("text"):
            labels["type"] = "type"
        return labels

    def step(self, cs, target, labels=None):
        op, tgt = cs["op"], target or self.active
        sel = SELECT % {"target": json.dumps(tgt)}
        note = ["settings not sent: " + ", ".join(map(str, cs["untyped"]))] if cs.get("untyped") else []
        png, out = DIR / f"{self.n + 1:05d}.png", self._next()
        try:
            if op["mode"] == "script":
                outdir = json.dumps(Path(getattr(self, "out", ".")).as_posix())
                res = self._call(self.cur, sel + f"var OUT={outdir};var SAY=[];function say(m){{SAY.push(String(m));}}"
                                 + "(function(){" + op["src"] + "\n})();r.say=SAY.join('; ');" + AFTER, png=png, save=out)
                info = "script ran" + (f"; script says: {res['say']}" if res.get("say") else "")
            elif op["mode"] == "blend":
                res = self._call(self.cur, sel + f"T.blendingMode={op['blend']};r.read=String(T.blendingMode);" + AFTER,
                                 png=png, save=out)
                info = f"blendingMode = {res.get('read')}"
            elif op["mode"] == "menu":
                res = self._call(self.cur, sel + f"app.executeMenuCommand({json.dumps(op['cmd'])});" + AFTER,
                                 png=png, save=out)
                info = f"executeMenuCommand({op['cmd']!r})"
            elif op["mode"] == "effect":
                res, info = self._effect(op, sel, png, out)
            else:
                raise RuntimeError(f"op mode {op['mode']}")
        except Exception as e:  # noqa: BLE001
            return "failed", "; ".join([f"{e}"] + note)[:500], None
        self.cur, self.png = out, png
        if res.get("active"):
            self.active = res["active"]
        self.layers = (res.get("layers") or "").split("|")
        dl = res.get("_dialogs")
        return "ok", "; ".join(note + [info] + ([f"dialogs answered (Enter): {dl}"] if dl else []))[:500], res.get("active")

    def _effect(self, op, sel, png, out):
        it = pgd._lookup("AI", "ai_effect", {"id": op["id"]})
        pl = effect_plan(it, op["settings"])
        if pl.get("dom") is not None:
            sets = "".join(f"s.{k}={v if isinstance(v, str) and '.' in v and not v[0].isdigit() else json.dumps(v)};"
                           for k, v in pl["dom"].items())
            return self._call(self.cur, sel + f"var s=d.rasterEffectSettings;{sets}" + AFTER, png=png, save=out), \
                f"rasterEffectSettings: {sets}"
        apply = f"T.applyEffect({json.dumps(pl['xml'])});"
        if not (pl["patch"] or pl["chain_first"]):
            return self._call(self.cur, sel + apply + AFTER, png=png, save=out), f"applyEffect('{pl['xml'][:160]}')"
        fa = DIR / f"{self.n:05d}_a.ai"
        res = self._call(self.cur, sel + apply + "r.tname=nameOf(T);T.hidden=true;" + AFTER, save=fa)
        ps = eg.read_ps(fa)
        bl = eg.blocks(ps, pl["le"])
        if not bl:
            raise RuntimeError(f"applyEffect stored no {pl['le']} block to replace")
        info = f"applyEffect('{pl['xml'][:120]}')"
        if pl["patch"]:
            pl["map_keys_simple"] = [p["key"] for _k, (kind, p, _v) in pl["map"].items() if kind == "simple"]
            nb = eg.patched_block(pl)
            # ponytail: every block of this LiveEffect in the file gets these values (an earlier step's same effect
            # too); per-item block matching if a plan ever applies one effect twice with different values
            for s, e in reversed(bl):
                ps = ps[:s] + nb + ps[e:]
            info += ", dictionary patched from the dialog's own (probe file)"
        if pl["chain_first"]:
            ps, moved = eg.chain_first(ps, pl["le"])
            if not moved:
                raise RuntimeError(f"no {pl['le']} in an appearance chain to move ahead of the fill/stroke stack")
            info += ", moved to the head of the appearance chain"
        fp = DIR / f"{self.n:05d}_p.ai"
        fp.write_bytes(ps.encode("latin-1"))
        res2 = self._call(fp, "var T=byName(%s);if(T){T.hidden=false;T.translate(1,0);T.translate(-1,0);}"
                          % json.dumps(res.get("tname")) + "d.selection=null;if(T)T.selected=true;" + AFTER,
                          png=png, save=out)
        for f in (fa, fp):
            f.unlink(missing_ok=True)
        return res2, info + ", reopened and re-rendered"

    def snap(self, path, w=480):
        """the step frame was exported by the step's own call (960x540); copied here"""
        import shutil
        src = getattr(self, "png", None)
        if src and Path(src).exists():
            shutil.copyfile(src, path)
        elif self.cur:
            try:
                self._call(self.cur, "", png=path, timeout=120)
            except Exception as e:  # noqa: BLE001
                print(f"    (no step frame: {e})"[:200], flush=True)
        self.png = None

    def export(self, full):
        res = self._call(self.cur, "var T=null;" + AFTER, png=full, timeout=180)
        return (res.get("layers") or "").split("|")

    def close(self):
        eg.cleanup()
        for f in DIR.glob("*.ai"):
            if f.name != "blank_base.ai":
                f.unlink(missing_ok=True)
        for f in DIR.glob("*.png"):
            f.unlink(missing_ok=True)
        self.cur = self.active = None

    def recover(self, err):
        eg.cleanup()

    def quit(self):
        self.close()
        pid = self._recorded()
        if pid and pid == _find_pid():
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            print(f"  stopped our Illustrator (pid {pid})", flush=True)
        PIDFILE.unlink(missing_ok=True)
