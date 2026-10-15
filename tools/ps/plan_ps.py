"""PGD plan runner, Photoshop backend (run_plan.py drives it; see its docstring for the plan format).

One working document per plan ("pgd_plan_w", closed unsaved), one ExtendScript call per step, so a hang or an error
names its step. Settings are typed exactly as the effect gallery types demo_settings (effect_gallery.spec_for /
job_for), so a plan step sends what a verified card frame sent. Routes per kind:
  ps_filter, ps_adjustment, ps_blend_mode   the effect gallery's job (event / adjustment layer / layer mode)
  ps_layer_style   ONE layerEffects set for all the step's effects (a set replaces the layer's whole style); an
                   effect given twice goes in its multi list (dropShadowMulti ...)
  ps_menu          the harvest's live-verified route: executeAction(invoke.ps_event, invoke_descriptor_js),
                   runMenuItem(invoke.ps_menu_cmd) or invoke.ps_dom; commands whose verified descriptor carries sample
                   values (Image Size 200 px ...) need a "script"; commands that act outside the document (print,
                   colour settings, package) are never run; View items are manual (view only: no export shows them)
  anything         "script": ExtendScript with d = the working document, L = the active (or target) layer, OUT =
                   the run's output folder (a path string; files a script writes go there) and say(msg) (a check's
                   finding, recorded in the step note)
Labels are layer IDs: photo -> the Background (after a step replaces the layer it acted on, such as Layer from
Background, Convert to Smart Object or a merge, labels that named it name the result); text / blank -> background; "text" on any plate adds a type layer
(label type; "at": [x, y] its centre, "size" px, "color", "font").
Photoshop is started and restarted only through psdrv (pid in work/ps/ps.pid); a Photoshop this pipeline did not
start is never sent a script.
"""
import importlib.util, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ps_effect_gallery", HERE / "effect_gallery.py")
eg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eg)
sys.path.insert(0, str(HERE.parents[1]))
import pgd  # noqa: E402

DOC = "pgd_plan_w"
STEP_TIMEOUT = 300
# verified descriptors that carry the probe's sample values, not values a plan chose: run only with a "script"
NEEDS_VALUES = {"1006": "bitmap conversion method / resolution", "1030": "the new width (probe: 200 px)",
                "1031": "the canvas width / height (probe: 500 x 400 px)", "1036": "the feather radius (probe: 5 px)",
                "1109": "the expand amount (probe: 10 px)", "1152": "the colour range (probe: Reds, fuzziness 40)",
                "1213": "the destination profile (probe: Adobe RGB (1998))", "2202": "the skew angles (probe: 20 deg)",
                "6300": "the fill colour (probe: orange #FF8000)",
                "1042": "the fill contents (probe: the foreground colour, so a '50 % Gray' fill came out black)"}
OUTSIDE_DOC = ("File/Print", "File/Package", "Edit/Color Settings", "Edit/Preferences", "Edit/Keyboard Shortcuts",
               "Edit/Menus", "File/Export", "File/Save", "File/Close", "File/Open")

LIB = r'''
var PW = "pgd_plan_w";
function planDoc() { for (var i = 0; i < app.documents.length; i++) if (app.documents[i].name == PW) { app.activeDocument = app.documents[i]; return app.documents[i]; }
  throw new Error("the plan document is gone"); }
function actId() { try { return layerDesc().getInteger(S2T("layerID")); } catch (e) { return null; } }
function layerExists(id) { try { var r = new ActionReference(); r.putIdentifier(C2T("Lyr "), id); executeActionGet(r); return true; } catch (e) { return false; } }
function selById(id) { var r = new ActionReference(); r.putIdentifier(C2T("Lyr "), id); var d = new ActionDescriptor(); d.putReference(C2T("null"), r);
  d.putBoolean(C2T("MkVs"), false); executeAction(C2T("slct"), d, DialogModes.NO); }
// the same helpers the menu routes were verified with (tools/ps/menu_invoke.py LIB)
function tref(c) { var r = new ActionReference(); r.putEnumerated(C2T(c), C2T("Ordn"), C2T("Trgt")); return r; }
function selRef() { var r = new ActionReference(); r.putProperty(C2T("Chnl"), C2T("fsel")); return r; }
function mkMaskDesc(how) { var d = new ActionDescriptor(); d.putClass(C2T("Nw  "), C2T("Chnl"));
  var at = new ActionReference(); at.putEnumerated(C2T("Chnl"), C2T("Chnl"), C2T("Msk ")); d.putReference(C2T("At  "), at);
  d.putEnumerated(C2T("Usng"), S2T("userMaskEnabled"), S2T(how)); return d; }
function layerList(c, depth, out) {  // every DOM read guarded: some adjustment layers throw "Internal error" on .kind
  for (var i = 0; i < c.layers.length; i++) { var L = c.layers[i], k = "?", x = "", nm = "?";
    try { nm = L.name; } catch (e) {}
    try { k = L.typename == "LayerSet" ? "group" : String(L.kind).replace("LayerKind.", "").toLowerCase(); } catch (e) { k = "layer"; }
    try { if (L.typename != "LayerSet" && L.blendMode != BlendMode.NORMAL) x += " " + String(L.blendMode).replace("BlendMode.", "").toLowerCase(); } catch (e) {}
    try { if (L.opacity < 100) x += " " + Math.round(L.opacity) + "%"; } catch (e) {}
    try { if (!L.visible) x += " hidden"; } catch (e) {}
    out.push(new Array(depth + 1).join("  ") + nm + " [" + k + x + "]"); if (L.typename == "LayerSet") layerList(L, depth + 1, out); } return out; }
function hexc(h) { h = h.replace("#", ""); return rgbc(parseInt(h.substr(0, 2), 16), parseInt(h.substr(2, 2), 16), parseInt(h.substr(4, 2), 16)); }
function snapDoc(d, w) { var s = d.duplicate("pgd_plan_snap", true); app.activeDocument = s;
  if (s.mode == DocumentMode.BITMAP) s.changeMode(ChangeMode.GRAYSCALE);
  if (s.mode != DocumentMode.RGB && s.mode != DocumentMode.GRAYSCALE) s.changeMode(ChangeMode.RGB);
  if (s.layers.length > 1) s.flatten();  // a single transparent layer is kept: the PNG carries its alpha
  if (w) s.resizeImage(UnitValue(w, "px"), undefined, undefined, ResampleMethod.BICUBIC); return s; }
'''

OPEN = r'''
(function () { var I = %(inp)s, R = {labels: {}}; app.displayDialogs = DialogModes.NO; closeIf(PW); closeIf("pgd_plan_snap");
  var d;
  if (I.plate == "photo") { var s = app.open(new File(I._photo || PLATE)); d = s.duplicate(PW, true); s.close(SaveOptions.DONOTSAVECHANGES); app.activeDocument = d;
    if (d.mode != DocumentMode.RGB) d.changeMode(ChangeMode.RGB); if (d.bitsPerChannel != BitsPerChannelType.EIGHT) d.bitsPerChannel = BitsPerChannelType.EIGHT;
    d.resizeImage(undefined, undefined, 72, ResampleMethod.NONE); R.labels.photo = actId(); }
  else { d = app.documents.add(UnitValue(1920, "px"), UnitValue(1080, "px"), 72, PW, NewDocumentMode.RGB, DocumentFill.WHITE);
    if (I.plate == "text" || I.background) { d.selection.selectAll(); d.selection.fill(hexc(I.background || "#808080")); d.selection.deselect(); }
    R.labels.background = actId(); }
  if (I.plate == "text" || I.text) { var L = d.artLayers.add(); L.kind = LayerKind.TEXT; var t = L.textItem; t.contents = I.text || "PGD"; t.font = I.font || "Arial-Black";
    t.size = UnitValue(I.size || (I.plate == "text" ? 360 : 150), "px"); t.color = hexc(I.color || (I.plate == "text" ? "#E1E1E1" : "#FFFFFF"));
    t.justification = Justification.CENTER; t.position = [UnitValue(960, "px"), UnitValue(660, "px")]; var at = I.at || [960, 540];
    var b = L.bounds; L.translate(UnitValue(at[0] - (b[0].as("px") + b[2].as("px")) / 2, "px"), UnitValue(at[1] - (b[1].as("px") + b[3].as("px")) / 2, "px"));
    d.activeLayer = L; R.labels.type = actId(); }
  app.foregroundColor = rgbc(0, 0, 0); app.backgroundColor = rgbc(255, 255, 255); try { app.currentTool = "moveTool"; } catch (e) {}
  return J(R); })();
'''

STEP = r'''
(function () { var S = %(step)s, R = {}; app.displayDialogs = DialogModes.NO; var d = planDoc();
  try {
    if (S.target != null) selById(S.target);
    R.before = actId();
    var L = d.activeLayer, o = S.op;
    if (o.mode == "script") { var SAY = []; var say = function (m) { SAY.push(String(m)); };
      try { (function (d, L, OUT, say) { eval(o.src); })(d, L, S.out, say); } finally { if (SAY.length) R.say = SAY.join("; "); } }
    else if (o.mode == "js") { eval(o.src); }
    else if (o.mode == "event") { executeAction(tk(o.ev), buildDesc(o.spec), DialogModes.NO); }
    else if (o.mode == "adjlayer") { adjLayer(o.cls, o.spec); }
    else if (o.mode == "blend") { setMode(o.ev); }
    else if (o.mode == "style") {
      var fx = new ActionDescriptor(), multi = {}, keys = [], i; fx.putUnitDouble(S2T("scale"), S2T("percentUnit"), 100);
      for (i = 0; i < o.fx.length; i++) { var e = buildDesc(o.fx[i].spec); e.putBoolean(S2T("enabled"), true);
        if (o.fx[i].multi) { if (!multi[o.fx[i].multi]) { multi[o.fx[i].multi] = new ActionList(); keys.push(o.fx[i].multi); } multi[o.fx[i].multi].putObject(S2T(o.fx[i].cls), e); }
        else fx.putObject(S2T(o.fx[i].key), S2T(o.fx[i].cls), e); }
      for (i = 0; i < keys.length; i++) fx.putList(S2T(keys[i]), multi[keys[i]]);
      var sd = new ActionDescriptor(); sd.putReference(C2T("null"), fxRef()); sd.putObject(C2T("T   "), S2T("layerEffects"), fx);
      executeAction(C2T("setd"), sd, DialogModes.NO);
      var miss = []; for (i = 0; i < o.fx.length; i++) if (!getFx(o.fx[i].key)) miss.push(o.fx[i].key);
      if (miss.length) throw new Error("not on the layer after the set: " + miss.join(", ")); }
    else throw new Error("op mode " + o.mode);
  } catch (e) { R.err = String(e) + (e.line ? " @line " + e.line : ""); }
  try { d = planDoc(); R.active = actId(); R.active_name = d.activeLayer.name; R.history = d.historyStates[d.historyStates.length - 1].name; } catch (e2) {}
  if (R.before != null) R.before_gone = !layerExists(R.before);
  return J(R); })();
'''

SNAP = r'''(function () { var d = planDoc(), s = snapDoc(d, %(w)s); savePng(s, %(out)s); s.close(SaveOptions.DONOTSAVECHANGES); app.activeDocument = d; return "ok"; })();'''
EXPORT = r'''(function () { var d = planDoc(), out = layerList(d, 0, []); out.push("mode " + String(d.mode).replace("DocumentMode.", "").toLowerCase() + ", " + d.width.as("px") + "x" + d.height.as("px") + " px");
  var s = snapDoc(d, 0); savePng(s, %(out)s); s.close(SaveOptions.DONOTSAVECHANGES); return J(out); })();'''
CLOSE = 'closeIf("pgd_plan_w"); closeIf("pgd_plan_snap"); try { app.purge(PurgeTarget.ALLCACHES); } catch (e) {} "ok"'


def _label(st, it):
    if st.get("effects"):
        return "Layer Style: " + " + ".join(str(e.get("name") or e.get("id")) for e in st["effects"])
    return (it or {}).get("path") or (it or {}).get("name") or str(st.get("name") or st.get("id"))


def _menu_op(it):
    """-> (op, None) or (None, why it is manual)"""
    path, x, inv = it.get("path") or "", it.get("extra") or {}, it.get("invoke") or {}
    if path.startswith("View/"):
        return None, f"view only: {path} changes the window, not the document (an export cannot show it)"
    if path.startswith(OUTSIDE_DOC):
        return None, f"not run: {path} acts outside the document (prints, writes files or changes app settings)"
    if it["id"] in NEEDS_VALUES:
        return None, (f"needs values: the harvest's verified route carries the probe's {NEEDS_VALUES[it['id']]}; give "
                      "the step a \"script\" with the plan's own values")
    if inv.get("ps_event") and x.get("invoke_verified") and "invoke_descriptor_js" in x:
        desc = x["invoke_descriptor_js"] or "new ActionDescriptor()"
        return {"mode": "js", "src": f"executeAction(tk({json.dumps(inv['ps_event'])}), {desc}, DialogModes.NO);"}, None
    if inv.get("ps_menu_cmd"):
        return {"mode": "js", "src": f"app.runMenuItem(S2T({json.dumps(inv['ps_menu_cmd'])}));"}, None
    if inv.get("ps_dom"):
        return {"mode": "js", "src": inv["ps_dom"]}, None
    if inv.get("ps_event"):
        return {"mode": "js", "src": f"executeAction(tk({json.dumps(inv['ps_event'])}), new ActionDescriptor(), DialogModes.NO);"}, None
    return None, "no scripted route in the harvest (invoke is empty); give the step a \"script\""


def _style_op(st):
    fx, notes = [], []
    for e in st.get("effects") or [st]:
        it = pgd._lookup("PS", "ps_layer_style", e)
        if not isinstance(it, dict):
            raise ValueError(f"no single ps_layer_style item for {e.get('name') or e.get('id')!r}")
        spec, _by, bad = eg.spec_for("ps_layer_style", {"demo_settings": e.get("settings") or {}}, it)
        x = it.get("extra") or {}
        fx.append({"key": x.get("layerEffects_key") or it["id"], "cls": x.get("descriptor_class") or it["id"],
                   "spec": spec, "multi": None})
        notes += [f"{it['name']}.{k}: {why}" for k, why in bad]
    seen = {}
    for f, e in zip(fx, st.get("effects") or [st]):
        seen.setdefault(f["key"], []).append(f)
    for key, fs in seen.items():
        if len(fs) > 1:
            it = pgd._lookup("PS", "ps_layer_style", {"id": key}) or {}
            mk = (it.get("extra") or {}).get("multi_key")
            if not mk:
                raise ValueError(f"{key} given {len(fs)} times but it has no multi list")
            for f in fs:
                f["multi"] = mk
    return {"mode": "style", "fx": fx}, notes


def compile_steps(plan, inp):
    if inp.get("plate") == "vector":
        raise ValueError("the vector plate is for Illustrator / CorelDRAW; a Photoshop plan starts from photo, text or blank")
    out = []
    for i, st in enumerate(plan.get("steps", []), 1):
        kind = st.get("kind", "")
        it = None if st.get("effects") else pgd._lookup("PS", kind, st)
        it = it if isinstance(it, dict) else None
        c = {"step": i, "kind": kind, "label": _label(st, it), "target": st.get("target"), "as": st.get("as"),
             "op": None, "manual": None, "untyped": []}
        try:
            if st.get("script"):
                c["op"] = {"mode": "script", "src": st["script"]}
            elif kind == "ps_layer_style":
                c["op"], c["untyped"] = _style_op(st)
            elif kind in ("ps_filter", "ps_adjustment", "ps_blend_mode"):
                if it is None:
                    raise ValueError(f"no single {kind} item for {st.get('name') or st.get('id')!r}")
                j, _by, bad, _how = eg.job_for(kind, {"demo_settings": st.get("settings") or {}}, it, "x.png")
                c["op"] = {k: j[k] for k in ("mode", "ev", "cls", "spec") if k in j}
                c["untyped"] = [f"{k}: {why}" for k, why in bad]
            elif kind == "ps_menu":
                if it is None:
                    raise ValueError(f"no single ps_menu item for {st.get('name') or st.get('id')!r}")
                c["op"], c["manual"] = _menu_op(it)
            else:
                c["manual"] = f"{kind} steps have no scripted route of their own; give the step a \"script\""
        except ValueError as e:
            c["manual"] = f"cannot compile: {e}"
        out.append(c)
    return out


class Session:
    """the Photoshop this pipeline started (started here when none runs)"""
    exports_doc_pixels = True  # export() writes the document at its own size (run_plan crops the 1:1 detail from it)

    def __init__(self):
        pd = eg.ps()
        if pd._ps_pids() and not pd.owned_pid():
            raise RuntimeError("a Photoshop this pipeline did not start (work/ps/ps.pid) is running: not sending it scripts")
        eg.guard()
        self.version = self._call('app.version', 60, "version")

    def _call(self, src, timeout, tag):
        r, oked = eg.call(LIB + "\n" + src, timeout, tag, on_dialog=eg.press_ok)
        self.oked = oked
        return r

    def open(self, inp):
        eg.guard()
        r = json.loads(self._call(OPEN % {"inp": json.dumps(inp)}, 240, "plan:open"))
        return {k: v for k, v in r["labels"].items() if v is not None}

    def step(self, cs, target, labels=None):
        note = "; ".join(["settings not sent: " + ", ".join(cs["untyped"])] if cs.get("untyped") else [])
        try:
            r = json.loads(self._call(STEP % {"step": json.dumps({"op": cs["op"], "target": target,
                                                                  "out": Path(getattr(self, "out", ".")).as_posix()})},
                                      STEP_TIMEOUT,
                                      f"plan:step{cs['step']}"))
        except eg.Hang as e:
            if not eg.wait_responsive(600):
                eg.restart(f"hung on plan step {cs['step']}")
            return "failed", f"{e}"[:400], None
        except Exception as e:  # noqa: BLE001
            return "failed", f"{e}"[:400], None
        eg.STATE["since"] += 1
        bits = [note] if note else []
        if r.get("before_gone") and r.get("active") is not None and labels:
            # the layer the step acted on is gone (Layer from Background, Convert to Smart Object, Merge give the
            # result a new layer ID): labels that named it now name the layer the step left active
            moved = [k for k, v in labels.items() if v == r["before"]]
            for k in moved:
                labels[k] = r["active"]
            if moved:
                bits.append(f"label {', '.join(moved)} now names the result (new layer ID)")
        if self.oked:
            bits.append(f"a dialog opened and was confirmed by handle: {self.oked}")
        if r.get("err"):
            return "failed", "; ".join([r["err"]] + bits)[:500], r.get("active")
        if r.get("say"):
            bits.append(f"script says: {r['say']}")
        bits.append(f"history: {r.get('history')}; active layer: {r.get('active_name')}")
        return "ok", "; ".join(bits)[:500], r.get("active")

    def snap(self, path, w=480):
        try:
            self._call(SNAP % {"w": w, "out": json.dumps(Path(path).as_posix())}, 180, "plan:snap")
        except Exception as e:  # noqa: BLE001 (a missing step frame is shown as such in the strip)
            print(f"    (no step frame: {e})"[:200], flush=True)

    def export(self, full):
        """the document at full size -> full (PNG, alpha kept); returns its layer list"""
        return json.loads(self._call(EXPORT % {"out": json.dumps(Path(full).as_posix())}, 300, "plan:export"))

    def close(self):
        try:
            self._call(CLOSE, 120, "plan:close")
        except Exception:  # noqa: BLE001
            pass

    def recover(self, err):
        if not eg.wait_responsive(300):
            eg.restart(f"plan run error: {err}"[:120])
        self.close()

    def quit(self):
        self.close()
