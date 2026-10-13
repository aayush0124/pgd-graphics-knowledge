"""Find and CONFIRM a script route for every ps_menu command (PGD, Photoshop 2026).

    python menu_invoke.py run [id ...]   # test candidates; checkpoint work/ps/menuinv/results.json (resumable)
    python menu_invoke.py show [id ...]  # print the recorded observation per command

Each test: build a scratch document in the state the command needs (fixture), snapshot, run ONE candidate under
DialogModes.NO, snapshot again (doc list, size, mode, depth, layers, active layer, selection, history, view flags,
menuBarInfo check marks), record the AM events an 'All ' notifier saw and any dialog psdrv had to dismiss (by
window handle, no global input), then close every document this script created. Toggles run twice (flip + restore).
Only documents created here are closed (names captured before the first test are never touched).
"""
import ctypes, json, sys, time, urllib.parse
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).parent))
import psdrv  # noqa: E402

W = psdrv.WORK / "menuinv"
W.mkdir(exist_ok=True)
RES = W / "results.json"
NLOG = psdrv.WORK / "notify.log"
NOTIFIER = (PGD / "tools/ps/notifier.jsx").as_posix()
TEST_PHOTO = (PGD / "media/test_photo.png").as_posix()
DOC = "pgd_mt"

LIB = r"""
function tref(c) { var r = new ActionReference(); r.putEnumerated(C2T(c), C2T("Ordn"), C2T("Trgt")); return r; }
function selRef() { var r = new ActionReference(); r.putProperty(C2T("Chnl"), C2T("fsel")); return r; }
function addFx() {
  var d = new ActionDescriptor(), r = new ActionReference(); r.putProperty(C2T("Prpr"), S2T("layerEffects")); r.putEnumerated(C2T("Lyr "), C2T("Ordn"), C2T("Trgt"));
  d.putReference(C2T("null"), r); var fx = new ActionDescriptor(); fx.putUnitDouble(S2T("scale"), S2T("percentUnit"), 100);
  var e = new ActionDescriptor(); e.putBoolean(S2T("enabled"), true); e.putUnitDouble(S2T("distance"), C2T("#Pxl"), 10); fx.putObject(S2T("dropShadow"), S2T("dropShadow"), e);
  d.putObject(C2T("T   "), S2T("layerEffects"), fx); executeAction(C2T("setd"), d, DialogModes.NO);
}
function mkMaskDesc(how) {
  var d = new ActionDescriptor(); d.putClass(C2T("Nw  "), C2T("Chnl"));
  var at = new ActionReference(); at.putEnumerated(C2T("Chnl"), C2T("Chnl"), C2T("Msk ")); d.putReference(C2T("At  "), at);
  d.putEnumerated(C2T("Usng"), S2T("userMaskEnabled"), S2T(how)); return d;
}
function mkMask(how) { return executeAction(S2T("make"), mkMaskDesc(how), DialogModes.NO); }
function dprop(k) { var r = new ActionReference(); r.putProperty(C2T("Prpr"), S2T(k)); r.putEnumerated(C2T("Dcmn"), C2T("Ordn"), C2T("Trgt")); try { return _g(executeActionGet(r), k); } catch (e) { return null; } }
function _am(c) { var r = new ActionReference(); r.putEnumerated(C2T(c), C2T("Ordn"), C2T("Trgt")); return executeActionGet(r); }
function _g(d, k) { try { if (!d.hasKey(S2T(k))) return null; var v = dval(d, S2T(k), 7); return v.v; } catch (e) { return "ERR"; } }
function checked() {
  var r = new ActionReference(); r.putProperty(C2T("Prpr"), S2T("menuBarInfo")); r.putEnumerated(C2T("capp"), C2T("Ordn"), C2T("Trgt"));
  var ck = [];
  function walk(d) {
    if (d.hasKey(S2T("checked")) && d.getBoolean(S2T("checked")) && d.getInteger(S2T("command")) > 0) ck.push(d.getInteger(S2T("command")));
    if (d.hasKey(S2T("submenu"))) { var s = d.getList(S2T("submenu")); for (var j = 0; j < s.count; j++) walk(s.getObjectValue(j)); }
  }
  walk(executeActionGet(r).getObjectValue(S2T("menuBarInfo")));
  return ck;
}
function layerRow(i) {
  var r = new ActionReference(); r.putIndex(C2T("Lyr "), i); var L = executeActionGet(r);
  var s = [L.getString(S2T("name")), _g(L, "layerKind"), _g(L, "visible") ? "v" : "h", _g(L, "layerSection"),
           _g(L, "group") ? "clip" : "", _g(L, "hasUserMask") ? "um" + (_g(L, "userMaskEnabled") ? "" : "-off") + (_g(L, "userMaskLinked") ? "" : "-unl") : "",
           _g(L, "hasVectorMask") ? "vm" + (_g(L, "vectorMaskEnabled") ? "" : "-off") : "", _g(L, "linkedLayerIDs") ? "lnk" : ""];
  var b = _g(L, "bounds"); if (b) s.push([b.left.v, b.top.v, b.right.v, b.bottom.v].join(","));
  var lk = _g(L, "layerLocking"); if (lk) { var q = []; for (var k in lk) if (lk[k].v) q.push(k); s.push(q.join("+")); }
  if (L.hasKey(S2T("smartObject"))) { var so = L.getObjectValue(S2T("smartObject")); s.push("so:" + (so.hasKey(S2T("linked")) && so.getBoolean(S2T("linked")) ? "linked" : "emb") + (so.hasKey(S2T("filterFX")) ? ":fx" + so.getList(S2T("filterFX")).count : "")); }
  if (L.hasKey(S2T("smartObjectMore"))) { var sm = L.getObjectValue(S2T("smartObjectMore")); if (sm.hasKey(S2T("stackMode"))) s.push("stack:" + tid2s(sm.getEnumerationValue(S2T("stackMode")))); }
  if (L.hasKey(S2T("textKey"))) { var tk = L.getObjectValue(S2T("textKey")); s.push("aa:" + _g(tk, "antiAlias") + " or:" + _g(tk, "orientation") + " txt:" + _g(tk, "textKey"));
    try { var ws = tk.getObjectValue(S2T("warp")); s.push("warp:" + tid2s(ws.getEnumerationValue(S2T("warpStyle")))); } catch (e) {} }
  s.push("op" + _g(L, "opacity") + " " + _g(L, "mode") + (_g(L, "layerFXVisible") === false ? " fxoff" : "") + (L.hasKey(S2T("layerEffects")) ? " fx" : ""));
  return s.join("|");
}
function snap() {
  var o = {docs: app.documents.length, names: []};
  for (var i = 0; i < app.documents.length; i++) o.names.push(app.documents[i].name);
  o.ck = checked();
  try { o.tool = app.currentTool; } catch (e) {}
  try { var pr = new ActionReference(); pr.putProperty(C2T("Prpr"), S2T("panelList")); pr.putEnumerated(C2T("capp"), C2T("Ordn"), C2T("Trgt"));
        var pl = executeActionGet(pr).getList(S2T("panelList")), pv = [];
        for (var pi = 0; pi < pl.count; pi++) { var pd = pl.getObjectValue(pi); if (pd.getBoolean(S2T("visible"))) pv.push(pd.getString(S2T("name"))); }
        o.panels = pv.join(","); } catch (e) {}
  try { o.fg = app.foregroundColor.rgb.hexValue + "/" + app.backgroundColor.rgb.hexValue; } catch (e) {}
  if (!app.documents.length) return o;
  var d = app.activeDocument; o.doc = d.name;
  o.size = [d.width.as("px"), d.height.as("px"), d.resolution].join("x");
  o.mode = String(d.mode) + "/" + String(d.bitsPerChannel);
  try { o.prof = d.colorProfileName; } catch (e) { o.prof = null; }
  var ks = ["numberOfLayers", "numberOfChannels", "numberOfPaths", "zoom", "rulersVisibility", "guidesVisibility", "smartGuidesVisibility",
            "selectionEdgesVisible", "quickMask", "patternPreviewMode", "pixelScaleFactor", "hasBackgroundLayer", "measurementScale", "targetPathVisibility", "isDirty"];
  for (var q = 0; q < ks.length; q++) { var v = dprop(ks[q]); o[ks[q]] = (v && typeof v == "object") ? J(v).substr(0, 300) : v; }
  try { var tr = new ActionReference(); tr.putProperty(C2T("Prpr"), S2T("targetLayersIDs")); tr.putEnumerated(C2T("Dcmn"), C2T("Ordn"), C2T("Trgt")); o.targets = executeActionGet(tr).getList(S2T("targetLayersIDs")).count; } catch (e) { o.targets = 0; }
  o.hist = d.historyStates.length; o.hlast = d.historyStates[d.historyStates.length - 1].name; o.hcur = d.activeHistoryState.name;
  try { var sb = d.selection.bounds; o.sel = [sb[0].as("px"), sb[1].as("px"), sb[2].as("px"), sb[3].as("px")].join(","); } catch (e) { o.sel = null; }
  try { o.guides = d.guides.length; o.comps = d.layerComps.length; o.counts = d.countItems.length; o.samplers = d.colorSamplers.length; } catch (e) {}
  try { o.paths = []; for (var p = 0; p < d.pathItems.length; p++) o.paths.push(d.pathItems[p].name + ":" + String(d.pathItems[p].kind)); o.paths = o.paths.join(";"); } catch (e) {}
  o.L = []; var n = o.numberOfLayers, b0 = o.hasBackgroundLayer ? 0 : 1;
  for (var li = b0; li <= n; li++) try { o.L.push(layerRow(li)); } catch (e) { o.L.push("ERR " + String(e)); }
  try { o.act = layerRow(_g(_am("Lyr "), "itemIndex") - (o.hasBackgroundLayer ? 1 : 0)); } catch (e) { o.act = null; }
  try { o.chans = []; for (var c = 0; c < d.channels.length; c++) o.chans.push(d.channels[c].name + (d.channels[c].visible ? "" : "-h")); o.chans = o.chans.join(","); } catch (e) {}
  return o;
}
function _fill(d, x0, y0, x1, y1, r, g, b) {
  d.selection.select([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]); var c = new SolidColor(); c.rgb.red = r; c.rgb.green = g; c.rgb.blue = b;
  d.selection.fill(c); d.selection.deselect();
}
function selLayers(names) {  // select layers by name (multi)
  for (var i = 0; i < names.length; i++) {
    var r = new ActionReference(); r.putName(C2T("Lyr "), names[i]); var ds = new ActionDescriptor(); ds.putReference(C2T("null"), r);
    if (i) ds.putEnumerated(S2T("selectionModifier"), S2T("selectionModifierType"), S2T("addToSelection"));
    ds.putBoolean(C2T("MkVs"), false); executeAction(C2T("slct"), ds, DialogModes.NO);
  }
}
function fixture(state, name) {
  var d = newDoc(name, 400, 300);
  if (state == "doc") return d;
  var L = d.artLayers.add(); L.name = "px1"; _fill(d, 40, 40, 200, 200, 230, 30, 30);
  if (state == "filled") return d;
  if (state == "selection") { d.selection.select([[100, 80], [300, 80], [300, 220], [100, 220]]); return d; }
  if (state == "text") { var t = d.artLayers.add(); t.kind = LayerKind.TEXT; t.textItem.contents = "PGD Test"; t.textItem.size = UnitValue(40, "px"); t.textItem.position = [UnitValue(60, "px"), UnitValue(150, "px")]; return d; }
  if (state == "smart") { executeAction(S2T("newPlacedLayer"), undefined, DialogModes.NO); return d; }
  if (state == "group") { var g = d.layerSets.add(); g.name = "grp1"; L.move(g, ElementPlacement.INSIDE); d.activeLayer = g; return d; }
  if (state == "multi" || state == "multi3") {
    var L2 = d.artLayers.add(); L2.name = "px2"; _fill(d, 150, 120, 330, 260, 30, 30, 230);
    if (state == "multi3") { var L3 = d.artLayers.add(); L3.name = "px3"; _fill(d, 260, 20, 380, 120, 30, 200, 30); selLayers(["px1", "px2", "px3"]); }
    else selLayers(["px1", "px2"]);
    return d;
  }
  return d;
}
"""


def load():
    return json.loads(RES.read_text(encoding="utf-8")) if RES.exists() else {}


def save(r):
    RES.with_suffix(".tmp").write_text(json.dumps(r, indent=1), encoding="utf-8")
    RES.with_suffix(".tmp").replace(RES)


FOREIGN = None


def cleanup():
    """close every document this script created (never one that was open before the first test)."""
    src = 'var F = %s, n = 0; app.displayDialogs = DialogModes.NO; for (var i = app.documents.length - 1; i >= 0; i--) { var nm = app.documents[i].name, keep = false; for (var k = 0; k < F.length; k++) if (F[k] == nm) keep = true; if (!keep) { app.documents[i].close(SaveOptions.DONOTSAVECHANGES); n++; } } app.displayDialogs = DialogModes.ERROR; n' % json.dumps(FOREIGN)
    for _ in range(3):
        try:
            return psdrv.js(src, timeout=60, tag="cleanup")
        except psdrv.PSError as e:
            last = e
    raise last


def notifier(on=True):
    if on:
        src = 'app.notifiersEnabled = true; var have = false; for (var i = 0; i < app.notifiers.length; i++) if (app.notifiers[i].event == "All ") have = true; if (!have) app.notifiers.add("All ", new File("%s")); app.notifiers.length' % NOTIFIER
    else:
        src = 'for (var i = app.notifiers.length - 1; i >= 0; i--) if (String(app.notifiers[i].eventFile.fsName).indexOf("notifier.jsx") >= 0) app.notifiers[i].remove(); app.notifiersEnabled = app.notifiers.length > 0; app.notifiers.length'
    return psdrv.js(src, timeout=30, tag="notifier")


NOISE = {"hostFocusChanged", "featureInfo", "owlAction", "homeScreenVisibilityChanged", "MRUFileListChanged", "notify",
         "toolModalStateChanged", "modalStateChanged", "invokeCommand", "historyStateChanged", "layersFiltered", "uiInfo",
         "closeViewlessDocument", "openViewlessDocument", "MRUFolderListChanged",
         "generatorDocActivated", "generatorTrackingEnable", "LoadedPluginsNames", "'Mn  '", "select"}


def events_since(pos):
    try:
        with open(NLOG, "rb") as f:
            f.seek(pos)
            lines = f.read().decode("utf-8", "replace").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for ln in lines:
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if e["event"] in NOISE and e["event"] != "select":
            continue
        d = json.dumps(e.get("desc"))[:400]
        out.append(e["event"] + " " + d)
    return out[:12]


def nlog_pos():
    return NLOG.stat().st_size if NLOG.exists() else 0


def diff(a, b):
    out = {}
    for k in sorted(set(a) | set(b)):
        if k in ("hcur",):
            continue
        if json.dumps(a.get(k)) != json.dumps(b.get(k)):
            if k == "ck" and "ck" in a and "ck" in b:
                out["ck"] = {"on": sorted(set(b["ck"]) - set(a["ck"])), "off": sorted(set(a["ck"]) - set(b["ck"]))}
            else:
                out[k] = [a.get(k), b.get(k)]
    return out


def clip_text():
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            return str(win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT))[:300]
        finally:
            win32clipboard.CloseClipboard()
    except Exception as e:  # noqa: BLE001
        return "no text (" + str(e)[:60] + ")"


def run_one(state, pre, run, timeout=10, toggle=False, post_run=None, check=None):
    """-> observation dict for one candidate."""
    cleanup()
    obs = {"state": state}
    before = psdrv.jsj(LIB + 'app.displayDialogs = DialogModes.NO; var _d = fixture("%s", "%s"); %s; app.displayDialogs = DialogModes.ERROR; J(snap())'
                       % (state, DOC, pre or ""), timeout=90, tag="fixture")
    pos = nlog_pos()
    clip0 = ctypes.windll.user32.GetClipboardSequenceNumber()
    t0 = time.time()
    wrapped = LIB + 'app.displayDialogs = DialogModes.NO; var _r = "ok"; try { %s } catch (e) { _r = "ERR " + String(e); } app.displayDialogs = DialogModes.ERROR; _r' % run
    try:
        obs["ret"] = psdrv.js(wrapped, timeout=timeout, tag="run")
    except psdrv.PSError as e:
        obs["ret"] = "PSERR " + str(e)[:400]
    obs["s"] = round(time.time() - t0, 1)
    time.sleep(0.3)
    try:
        after = psdrv.jsj(LIB + "J(snap())", timeout=60, tag="snap")
    except psdrv.PSError as e:
        after = {"err": str(e)[:200]}
    obs["events"] = events_since(pos)
    obs["diff"] = diff(before, after)
    if ctypes.windll.user32.GetClipboardSequenceNumber() != clip0:
        obs["diff"]["clipboard"] = "written"
        obs["clip_text"] = clip_text()
    if check:
        try:
            obs["check"] = psdrv.js(LIB + 'app.displayDialogs = DialogModes.NO; var _c = ""; try { _c = eval(decodeURIComponent("%s")); } catch (e) { _c = "ERR " + String(e); } app.displayDialogs = DialogModes.ERROR; _c' % urllib.parse.quote(check, safe=""), timeout=30, tag="check")
        except psdrv.PSError as e:
            obs["check"] = "PSERR " + str(e)[:200]
    if toggle or post_run:
        try:
            psdrv.js(LIB + 'app.displayDialogs = DialogModes.NO; try { %s } catch (e) {} app.displayDialogs = DialogModes.ERROR; "ok"' % (post_run or run), timeout=timeout, tag="restore")
        except psdrv.PSError as e:
            obs["restore_err"] = str(e)[:200]
        try:
            again = psdrv.jsj(LIB + "J(snap())", timeout=60, tag="snap2")
            obs["restore_diff"] = diff(before, again)
        except psdrv.PSError as e:
            obs["restore_diff"] = {"err": str(e)[:200]}
    cleanup()
    return obs


def init():
    global FOREIGN
    FOREIGN = psdrv.jsj('var a = []; for (var i = 0; i < app.documents.length; i++) a.push(app.documents[i].name); J(a)', timeout=30)
    FOREIGN = [n for n in FOREIGN if not n.startswith(DOC)]
    notifier(True)


def success(t):
    ch = {k: v for k, v in (t.get("diff") or {}).items() if k not in ("isDirty", "ck")}
    return bool(ch) and not str(t.get("ret", "")).startswith(("ERR", "PSERR"))


def probe_ok():
    try:
        return psdrv.js("1", timeout=30, tag="ping") == "1"
    except psdrv.PSError:
        return False


if __name__ == "__main__":
    from menu_plan import PLAN  # noqa: E402
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    ids = sys.argv[2:]
    res = load()
    if cmd == "show":
        for k in ids or res:
            print(k, json.dumps(res.get(k), indent=1)[:3000])
        sys.exit()
    init()
    force = "--force" in ids
    ids = [i for i in ids if i != "--force"]
    for cid, spec in PLAN.items():
        if ids and cid not in ids:
            continue
        if spec.get("skip"):
            continue
        rec = res.get(cid, {"tries": []})
        done = {t["how"] for t in rec["tries"]}
        if not force and any(success(t) for t in rec["tries"]):
            continue
        for cand in spec["cands"]:
            how = cand["how"]
            (W / "current.txt").write_text(cid + " " + how, encoding="utf-8")
            if how in done and not force:
                continue
            try:
                obs = run_one(cand.get("state", spec["state"]), cand.get("pre", spec.get("pre", "")), cand["run"],
                              timeout=cand.get("timeout", spec.get("timeout", 4)), toggle=cand.get("toggle", spec.get("toggle", False)),
                              post_run=cand.get("post_run"), check=cand.get("check"))
            except psdrv.PSError as e:
                obs = {"fatal": str(e)[:300]}
                if not probe_ok():
                    psdrv.restart_ps()
                    init()
            obs["how"] = how
            rec["tries"] = [t for t in rec["tries"] if t["how"] != how] + [obs]
            res[cid] = rec
            save(res)
            ch = {k: v for k, v in obs.get("diff", {}).items() if k not in ("isDirty",)}
            print(f"{cid:>8} {spec['path'][:45]:45s} {how[:50]:50s} {str(obs.get('ret'))[:60]:60s} {list(ch)[:8]}", flush=True)
            if ch and not str(obs.get("ret", "")).startswith(("ERR", "PSERR")) and not cand.get("try_all"):
                break
    notifier(False)
