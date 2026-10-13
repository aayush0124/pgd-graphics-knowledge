"""Live Photoshop probes for the PGD effects harvest, checkpointed to work/ps/probe_<kind>.json (resumable).

    python probe.py ids        # 4-char codes from the plug-in PiPLs -> stringIDs (work/ps/ids_4cc.json) + app_version
    python probe.py filter     # every filter event: read-back of the values used + clamp probes
    python probe.py setup      # (re)open the test photo and make the 480x270 work document

Work happens in documents this script opens ("test_photo.png", "pgd_ps_work"); nothing else is touched.
"""
import json, sys, time
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).parent))
import psdrv  # noqa: E402

WORK = psdrv.WORK
TEST = (PGD / "media/test_photo.png").as_posix()
WORKDOC = "pgd_ps_work"


def ck_load(kind):
    p = WORK / f"probe_{kind}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def ck_save(kind, d):
    p = WORK / f"probe_{kind}.json"
    p.with_suffix(".tmp").write_text(json.dumps(d, indent=1), encoding="utf-8")
    p.with_suffix(".tmp").replace(p)


def setup():
    import urllib.parse
    js = '''
    if (!activate("test_photo.png")) openTest("%s");
    if (!activate("%s")) {
      activate("test_photo.png");
      var d = app.activeDocument.duplicate("%s", true);
      d.resizeImage(UnitValue(480, "px"), UnitValue(270, "px"), 72, ResampleMethod.BICUBIC);
    }
    activate("%s"); app.activeDocument.name + " " + app.activeDocument.width''' % (
        urllib.parse.quote(TEST, safe=""), WORKDOC, WORKDOC, WORKDOC)
    return psdrv.js(js, timeout=90, tag="setup")


def ids():
    pipl = json.loads((WORK / "pipl_all.json").read_text(encoding="utf-8"))
    codes = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("EventID", "EventType", "ParamKeyword", "ParamType", "EnumID", "EnumKeyword", "ClassID") \
                        and isinstance(v, str) and len(v) == 4:
                    codes.add(v)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(pipl)
    codes = sorted(codes)
    js = 'var c = %s, o = {}; for (var i = 0; i < c.length; i++) { var s = ""; try { s = typeIDToStringID(C2T(c[i])); } catch (e) {} if (s) o[c[i]] = s; } J(o)' % json.dumps(codes)
    m = psdrv.jsj(js, timeout=60, tag="ids")
    (WORK / "ids_4cc.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    (WORK / "app_version.txt").write_text(psdrv.js("app.version"), encoding="utf-8")
    print(len(codes), "codes,", len(m), "with stringIDs")


PROBE_JS = r'''
(function () {
  var ev = %(ev)s, PROBE = %(probe)s, FB = %(fallback)s;
  activate("%(doc)s"); var doc = app.activeDocument; var h = doc.activeHistoryState;
  var out = {}, t0 = new Date().getTime(), base;
  try { base = executeAction(ev, new ActionDescriptor(), DialogModes.NO); out.readback = d2o(base); }
  catch (e) {
    out.err = String(e); try { doc.activeHistoryState = h; } catch (e0) {}
    if (!FB) return J(out);
    // the empty descriptor was refused: send one simple value per declared key, read back what was used
    var fd = new ActionDescriptor(), sent = {};
    for (var q = 0; q < FB.length; q++) {
      var f = FB[q], kk = f[0].charAt(0) == "'" ? C2T(f[0].substr(1, 4)) : S2T(f[0]);
      if (f[1] == "int") fd.putInteger(kk, 1);
      else if (f[1] == "unit") fd.putUnitDouble(kk, S2T(f[2]), 1);
      else if (f[1] == "double") fd.putDouble(kk, 1);
      else if (f[1] == "bool") fd.putBoolean(kk, false);
      else if (f[1] == "enum") fd.putEnumerated(kk, S2T(f[2]), S2T(f[3]));
      else continue;
      sent[f[0]] = f.slice(1);
    }
    try { base = executeAction(ev, fd, DialogModes.NO); out.readback = d2o(base); out.empty_err = out.err; delete out.err; out.base_sent = sent; }
    catch (e9) { out.fallback_err = String(e9); try { doc.activeHistoryState = h; } catch (e8) {} return J(out); }
  }
  doc.activeHistoryState = h;
  out.ms = new Date().getTime() - t0;
  out.ranges = {};
  if (PROBE && out.ms < 15000) {
    var vals = [1000000, 1000007, -1000000, -1000007];
    for (var i = 0; i < base.count; i++) {
      var k = base.getKey(i), ty = DVT[String(base.getType(k))];
      if (ty != "UNITDOUBLE" && ty != "DOUBLETYPE" && ty != "INTEGERTYPE") continue;
      var rr = {};
      if (out.slow) break;
      for (var j = 0; j < vals.length; j++) {
        var tj = new Date().getTime();
        var d = new ActionDescriptor(); d.fromStream(base.toStream());
        if (ty == "UNITDOUBLE") d.putUnitDouble(k, base.getUnitDoubleType(k), vals[j]);
        else if (ty == "DOUBLETYPE") d.putDouble(k, vals[j]); else d.putInteger(k, vals[j]);
        try { var r = executeAction(ev, d, DialogModes.NO); rr[String(vals[j])] = r.hasKey(k) ? dval(r, k, 0).v : "ERR:key missing in result"; }
        catch (e2) { rr[String(vals[j])] = "ERR:" + String(e2); }
        try { doc.activeHistoryState = h; } catch (e4) {}
        if (new Date().getTime() - tj > 20000) { out.slow = tid2s(k) + "=" + vals[j]; break; }
      }
      out.ranges[tid2s(k)] = rr;
    }
    try { executeAction(ev, base, DialogModes.NO); } catch (e3) {}  // leave the user's last-used values as found
    doc.activeHistoryState = h;
  }
  return J(out);
})();
'''


def ev_expr(sid):
    return 'C2T("%s")' % sid[1:-1] if sid.startswith("'") else 'S2T("%s")' % sid


FALLBACK = {}  # sid -> [[key, int|unit|double|bool|enum, unit or enum type, enum value]] (filled by fallback_specs)


def fallback_specs(term, sids):
    """for events whose empty descriptor was refused: one simple value per declared key (terminology types)"""
    import harvest_effects as he
    enums = term.get("Enums") or {}
    for sid in sids:
        spec = []
        for k, (lab, t) in he.term_params(term, sid).items():
            t0 = t.split()[0].lstrip("/") if t else ""
            if "/list" in t:
                continue
            if t0 == "integer":
                spec.append([k, "int"])
            elif t0 in ("percentUnit", "angleUnit", "pixelsUnit", "distanceUnit"):
                spec.append([k, "unit", t0])
            elif t0 == "floatType":
                spec.append([k, "unit", "pixelsUnit"])
            elif t0 == "boolean":
                spec.append([k, "bool"])
            elif t0 in enums and enums[t0]:
                spec.append([k, "enum", t0, next(iter(enums[t0]))])
        if spec:
            FALLBACK[sid] = spec


NO_RANGES = {"'Bokh'": "range probe skipped: sending 1e6 values to Lens Blur kept Photoshop busy > 9 min (2026-10-04)",
             "shear": "range probe skipped: probing Shear with 1e6 values wedged Photoshop (COM exception after 236 s)"}


def wait_responsive(max_s=1800):
    """after a hang: block until Photoshop answers a trivial script again (the hung call finishes first)."""
    t0 = time.time()
    while time.time() - t0 < max_s:
        try:
            psdrv.js("1", timeout=60, tag="ping")
            return True
        except psdrv.PSError:
            pass
    return False


CANARY = 'activate("%s"); var doc = app.activeDocument, h = doc.activeHistoryState; executeAction(S2T("invert"), new ActionDescriptor(), DialogModes.NO); doc.activeHistoryState = h; "ok"'


def canary():
    try:
        return psdrv.js(CANARY % WORKDOC, timeout=60, tag="canary") == "ok"
    except psdrv.PSError as e:
        return "not currently available" not in str(e) and "COM" not in str(e)


def probe_events(kind, events, probe_ranges=True, timeout=180):
    ck = ck_load(kind)
    for sid in events:
        if sid in ck and not ck[sid].get("retry") and not (ck[sid].get("wedged") and sid in NO_RANGES and "readback" not in ck[sid] and not ck[sid].get("retried")):
            continue
        if sid in ck and ck[sid].get("wedged"):
            retried = True
        else:
            retried = False
        t0 = time.time()
        try:
            rng = probe_ranges and sid not in NO_RANGES
            r = psdrv.jsj(PROBE_JS % {"ev": ev_expr(sid), "probe": "true" if rng else "false", "doc": WORKDOC,
                                      "fallback": json.dumps(FALLBACK.get(sid)) if FALLBACK.get(sid) else "null"},
                          timeout=timeout, tag=f"{kind}:{sid}")
            if sid in NO_RANGES:
                r["note"] = NO_RANGES[sid]
            if retried:
                r["retried"] = True
        except psdrv.PSError as e:
            r = {"err": str(e)[:600]}
            if "HANG" in str(e):
                r["note"] = "call hung"
                wait_responsive()
            try:
                setup()
            except psdrv.PSError:
                pass
        r["wall_s"] = round(time.time() - t0, 1)
        if not canary():  # the probe left Photoshop unable to run commands: restart, then retry once with no ranges
            r["wedged"] = True
            r.setdefault("note", "")
            r["note"] += " | after this probe every command reported 'not currently available'; Photoshop restarted"
            psdrv.restart_ps()
            setup()
            if probe_ranges and "readback" not in r:
                NO_RANGES[sid] = "range probe skipped: probing it wedged Photoshop (2026-10-04)"
                ck[sid] = r
                ck_save(kind, ck)
                return probe_events(kind, [sid] + events[events.index(sid) + 1:], probe_ranges, timeout)                     if not r.get("retried") else ck
        ck[sid] = r
        ck_save(kind, ck)
        print(f"{sid:28s} {r.get('wall_s')}s {'ERR ' + r['err'][:120] if r.get('err') else len(r.get('readback') or {})}",
              flush=True)
    return ck


def filter_events():
    sys.argv = [sys.argv[0]]
    import harvest_effects as he
    menu, pipl, term = he.load("menu_tree.json"), he.load("pipl_all.json"), he.load("ps_terminology.json")
    idm = he.load("ids_4cc.json", {})
    evs = []
    for it in he.filter_static(menu, pipl, term, idm):
        ev = it.get("_ev")
        if ev:
            sid = ev.get("sid") or "'%s'" % ev["cc"]
            if sid not in he.SKIP_EXEC and sid not in evs:
                evs.append(sid)
    return evs


ADJLAYER_JS = r"""
(function () {
  activate("%(doc)s"); var doc = app.activeDocument, h = doc.activeHistoryState, out = {};
  try {
    var d = new ActionDescriptor(), r = new ActionReference(); r.putClass(S2T("adjustmentLayer")); d.putReference(C2T("null"), r);
    var u = new ActionDescriptor(); u.putObject(S2T("type"), S2T("%(cls)s"), new ActionDescriptor());
    d.putObject(S2T("using"), S2T("adjustmentLayer"), u);
    var res = executeAction(S2T("make"), d, DialogModes.NO);
    out.make_result = d2o(res);
    var L = layerDesc();
    out.layer_adjustment = L.hasKey(S2T("adjustment")) ? l2o(L.getList(S2T("adjustment")), 0) : null;
    out.name = L.getString(S2T("name"));
    // clamp probes: set each numeric key on the adjustment layer and read back what was kept
    var NUM = %(num)s, vals = [1000000, 1000007, -1000000, -1000007]; out.ranges = {};
    for (var i = 0; i < NUM.length; i++) {
      var k = S2T(NUM[i][0]), rr = {};
      for (var j = 0; j < vals.length; j++) {
        try {
          var sd = new ActionDescriptor(), sr = new ActionReference(); sr.putEnumerated(S2T("adjustmentLayer"), C2T("Ordn"), C2T("Trgt"));
          sd.putReference(C2T("null"), sr);
          var o = new ActionDescriptor();
          if (NUM[i][1] == "int") o.putInteger(k, vals[j]); else o.putDouble(k, vals[j]);
          sd.putObject(C2T("T   "), S2T("%(cls)s"), o);
          executeAction(C2T("setd"), sd, DialogModes.NO);
          var a = layerDesc().getList(S2T("adjustment")).getObjectValue(0);
          rr[String(vals[j])] = a.hasKey(k) ? dval(a, k, 0).v : "ERR:key missing";
        } catch (e5) { rr[String(vals[j])] = "ERR:" + String(e5); }
      }
      out.ranges[NUM[i][0]] = rr;
    }
  } catch (e) { out.err = String(e); }
  try { doc.activeHistoryState = h; } catch (e2) {}
  return J(out);
})();
"""

STYLE_JS = r"""
(function () {
  var KEY = "%(key)s", CLS = "%(cls)s";
  activate("%(doc)s"); var doc = app.activeDocument, h = doc.activeHistoryState, out = {};
  function setFx(obj) {
    var d = new ActionDescriptor(), r = new ActionReference();
    r.putProperty(C2T("Prpr"), S2T("layerEffects")); r.putEnumerated(C2T("Lyr "), C2T("Ordn"), C2T("Trgt"));
    d.putReference(C2T("null"), r);
    var fx = new ActionDescriptor(); fx.putUnitDouble(S2T("scale"), S2T("percentUnit"), 100);
    fx.putObject(S2T(KEY), S2T(CLS), obj);
    d.putObject(C2T("T   "), S2T("layerEffects"), fx);
    executeAction(C2T("setd"), d, DialogModes.NO);
  }
  function getFx() {
    var L = layerDesc(); if (!L.hasKey(S2T("layerEffects"))) return null;
    var fx = L.getObjectValue(S2T("layerEffects"));
    if (fx.hasKey(S2T(KEY))) return fx.getObjectValue(S2T(KEY));
    if (fx.hasKey(S2T(KEY + "Multi"))) { out.via_multi = true; return fx.getList(S2T(KEY + "Multi")).getObjectValue(0); }
    return null;
  }
  try {
    doc.activeLayer = doc.layers[doc.layers.length - 1];
    doc.activeLayer.duplicate(); doc.activeLayer = doc.layers[0];
    var e = new ActionDescriptor(), EX = %(extra)s; e.putBoolean(S2T("enabled"), true);
    if (EX.flags) for (var f = 0; f < EX.flags.length; f++) e.putBoolean(S2T(EX.flags[f]), true);
    if (EX.pattern) {  // first pattern preset loaded in this Photoshop (presetManager), by name
      var pr = new ActionReference(); pr.putProperty(C2T("Prpr"), S2T("presetManager")); pr.putEnumerated(C2T("capp"), C2T("Ordn"), C2T("Trgt"));
      var pm = executeActionGet(pr).getList(S2T("presetManager")), pname = null;
      for (var m = 0; m < pm.count; m++) if (tid2s(pm.getObjectType(m)) == "pattern") { var nl = pm.getObjectValue(m).getList(S2T("name")); if (nl.count) pname = nl.getString(0); }
      out.pattern_used = pname;
      var pd = new ActionDescriptor(); pd.putString(S2T("name"), pname); e.putObject(S2T("pattern"), S2T("pattern"), pd);
    }
    setFx(e);
    var base = getFx();
    if (!base) throw new Error("effect not found in layerEffects after set");
    out.readback = d2o(base);
    out.ranges = {};
    var vals = [1000000, 1000007, -1000000, -1000007];
    for (var i = 0; i < base.count; i++) {
      var k = base.getKey(i), ty = DVT[String(base.getType(k))];
      if (ty != "UNITDOUBLE" && ty != "DOUBLETYPE" && ty != "INTEGERTYPE") continue;
      var rr = {};
      for (var j = 0; j < vals.length; j++) {
        try { var b0 = new ActionDescriptor(); b0.fromStream(base.toStream()); setFx(b0); } catch (e7) {}  // reset first
        var o = new ActionDescriptor(); o.fromStream(base.toStream());
        if (ty == "UNITDOUBLE") o.putUnitDouble(k, base.getUnitDoubleType(k), vals[j]);
        else if (ty == "DOUBLETYPE") o.putDouble(k, vals[j]); else o.putInteger(k, vals[j]);
        try { setFx(o); var g = getFx(); rr[String(vals[j])] = (g && g.hasKey(k)) ? dval(g, k, 0).v : "ERR:key missing"; }
        catch (e2) { rr[String(vals[j])] = "ERR:" + String(e2); }
      }
      out.ranges[tid2s(k)] = rr;
    }
  } catch (e) { out.err = String(e); }
  try { doc.activeHistoryState = h; } catch (e3) {}
  return J(out);
})();
"""

BLEND_JS = r"""
(function () {
  var MODES = %(modes)s;
  activate("%(doc)s"); var doc = app.activeDocument, h = doc.activeHistoryState, out = {am: {}, dom: {}};
  var dd = app.displayDialogs; app.displayDialogs = DialogModes.NO;  // DOM errors throw instead of opening alerts
  function setMode(v) {
    var d = new ActionDescriptor(), r = new ActionReference(); r.putEnumerated(C2T("Lyr "), C2T("Ordn"), C2T("Trgt"));
    d.putReference(C2T("null"), r);
    var l = new ActionDescriptor(); l.putEnumerated(S2T("mode"), S2T("blendMode"), S2T(v));
    d.putObject(C2T("T   "), C2T("Lyr "), l);
    executeAction(C2T("setd"), d, DialogModes.NO);
  }
  function getMode() { return tid2s(layerDesc().getEnumerationValue(S2T("mode"))); }
  try {
    doc.activeLayer = doc.layers[doc.layers.length - 1];
    doc.activeLayer.duplicate(); var px = doc.layers[0];
    var grp = doc.layerSets.add();
    for (var i = 0; i < MODES.length; i++) {
      var m = MODES[i], rec = {};
      doc.activeLayer = px;
      try { setMode("normal"); setMode(m); var g = getMode(); rec.layer = g == m ? "ok" : "kept " + g; } catch (e) { rec.layer = "ERR:" + String(e); }
      doc.activeLayer = grp;
      try { setMode("passThrough"); setMode(m); var g2 = getMode(); rec.group = g2 == m ? "ok" : "kept " + g2; } catch (e1) { rec.group = "ERR:" + String(e1); }
      out.am[m] = rec;
    }
    var names = BlendMode.reflect.properties;
    for (var j = 0; j < names.length; j++) {
      var n = names[j].name; if (n == "__proto__" || n == "reflect" || n == "prototype") continue;
      var tgt = (n == "PASSTHROUGH") ? grp : px;
      try { doc.activeLayer = tgt; tgt.blendMode = BlendMode[n]; out.dom[n] = getMode(); }
      catch (e2) { out.dom[n] = "ERR:" + String(e2); }
    }
  } catch (e) { out.err = String(e); }
  app.displayDialogs = dd;
  try { doc.activeHistoryState = h; } catch (e3) {}
  return J(out);
})();
"""


SMART_JS = r"""
(function () {
  var ev = %(ev)s;
  activate("%(doc)s"); var doc = app.activeDocument, h = doc.activeHistoryState, out = {};
  try {
    doc.activeLayer = doc.layers[doc.layers.length - 1]; doc.activeLayer.duplicate(); doc.activeLayer = doc.layers[0];
    executeAction(S2T("newPlacedLayer"), new ActionDescriptor(), DialogModes.NO);
    executeAction(ev, new ActionDescriptor(), DialogModes.NO);
    var L = layerDesc();
    if (!L.hasKey(S2T("smartObject"))) throw new Error("layer has no smartObject key");
    var so = L.getObjectValue(S2T("smartObject"));
    if (so.hasKey(S2T("filterFX"))) {
      var fx = so.getList(S2T("filterFX")); out.n = fx.count; out.filterFX = d2o(fx.getObjectValue(fx.count - 1));
    } else { out.n = 0; out.keys = []; for (var i = 0; i < so.count; i++) out.keys.push(tid2s(so.getKey(i))); }
  } catch (e) { out.err = String(e); }
  try { doc.activeHistoryState = h; } catch (e2) {}
  return J(out);
})();
"""


STYLE_EXTRA = {"patternFill": {"pattern": True}}


def run_simple(kind, key, js, timeout=120):
    ck = ck_load(kind)
    if key in ck:
        return ck[key]
    try:
        r = psdrv.jsj(js, timeout=timeout, tag=f"{kind}:{key}")
    except psdrv.PSError as e:
        r = {"err": str(e)[:600]}
        if "HANG" in str(e):
            wait_responsive()
        try:
            setup()
        except psdrv.PSError:
            pass
    if not canary():
        r["wedged"] = True
        psdrv.restart_ps()
        setup()
    ck[key] = r
    ck_save(kind, ck)
    print(kind, key, ("ERR " + r["err"][:150]) if r.get("err") else "ok", flush=True)
    return r


def harvest_items(kind):
    p = (PGD / "harvest/ps") / f"{kind}.json"
    return json.loads(p.read_text(encoding="utf-8"))["items"]


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "filter"
    if what == "ids":
        ids()
    elif what == "setup":
        print(setup())
    elif what == "filter":
        print(setup())
        evs = filter_events()
        print(len(evs), "filter events")
        probe_events("filter", evs)
    elif what == "refused":  # second pass: events whose empty descriptor was refused
        import harvest_effects as he
        kind = sys.argv[2] if len(sys.argv) > 2 else "filter"
        ck = ck_load(kind)
        bad = [k for k, v in ck.items() if v.get("err") and "HANG" not in v["err"] and "COM " not in v["err"]
               and "fallback_err" not in v and k not in he.SKIP_EXEC and "User cancelled" not in v["err"]]
        fallback_specs(he.load("ps_terminology.json"), bad)
        for k in bad:
            if k in FALLBACK:
                ck[k]["retry"] = True
        ck_save(kind, ck)
        print(setup())
        probe_events(kind, [k for k in bad if k in FALLBACK])
    elif what == "adjust":
        print(setup())
        items = harvest_items("ps_adjustment")
        evs = [i["invoke"]["ps_event"] for i in items if i.get("extra", {}).get("destructive") and i.get("invoke")]
        probe_events("adjust", evs)
        for i in items:
            c = i.get("extra", {}).get("adjustment_class")
            if c:
                num = [[p["key"], "int" if p["type"] == "int" else "num"] for p in i.get("params", [])
                       if p["type"] in ("int", "number") and p.get("key")]
                run_simple("adjlayer", c, ADJLAYER_JS % {"doc": WORKDOC, "cls": c, "num": json.dumps(num)})
    elif what == "smart":
        print(setup())
        ok = [k for k, v in ck_load("filter").items() if not v.get("err")]
        for sid in ok:
            run_simple("smart", sid, SMART_JS % {"doc": WORKDOC, "ev": ev_expr(sid)}, timeout=180)
    elif what == "style":
        print(setup())
        for i in harvest_items("ps_layer_style"):
            run_simple("style", i["id"], STYLE_JS % {"doc": WORKDOC, "key": i["id"], "cls": i["extra"]["descriptor_class"],
                                                     "extra": json.dumps(STYLE_EXTRA.get(i["id"], {}))}, timeout=240)
        # Bevel & Emboss sub-panels: Contour (useShape) and Texture (useTexture + a pattern)
        run_simple("style", "bevelEmboss+contour+texture", STYLE_JS % {
            "doc": WORKDOC, "key": "bevelEmboss", "cls": "bevelEmboss",
            "extra": json.dumps({"flags": ["useShape", "useTexture"], "pattern": True})}, timeout=240)
    elif what == "blend":
        print(setup())
        import harvest_effects as he
        modes = list((he.load("ps_terminology.json")["Enums"]["blendMode"]).keys())
        r = run_simple("blend_all", "all", BLEND_JS % {"doc": WORKDOC, "modes": json.dumps(modes)}, timeout=240)
        ck_save("blend", r)
