"""PGD Photoshop harvest audit (independent auditor, 2026-10-04).

    python audit_ps.py menus      compare a fresh menuBarInfo walk with every harvest kind -> work/ps/audit/menu_diff.json
"""
import json, sys
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
H = (PGD / "harvest/ps")
A = (PGD / "work/ps/audit")
A.mkdir(parents=True, exist_ok=True)
KINDS = ["ps_filter", "ps_adjustment", "ps_layer_style", "ps_blend_mode", "ps_tool", "ps_menu", "ps_preset"]


def load(k):
    return json.loads((H / f"{k}.json").read_text(encoding="utf-8"))


def save(k, doc):
    (H / f"{k}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


def menus():
    tree = tree_paths()
    by_cmd, by_path = {}, {}
    for k in ["ps_filter", "ps_adjustment", "ps_layer_style", "ps_menu"]:
        for it in load(k)["items"]:
            c = (it.get("extra") or {}).get("menu_cmd")
            if c is not None:
                by_cmd.setdefault(c, []).append((k, it["id"]))
            if it.get("path"):
                by_path.setdefault(it["path"], []).append((k, it["id"]))
    missing, leaves = [], 0
    for n in tree:
        if n.get("n_sub") or not n["disp"] or "/" not in n["dpath"]:
            continue
        leaves += 1
        hit = by_path.get(n["dpath"]) or (by_cmd.get(n.get("command")) if n.get("command", 0) > 0 else None)
        if not hit:
            missing.append({"path": n["dpath"], "command": n.get("command"), "title": n.get("title"), "visible": n.get("visible")})
    out = {"leaves": leaves, "missing": missing}
    (A / "menu_diff.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(leaves, "leaf commands;", len(missing), "not in any harvest kind")
    for m in missing:
        print(" ", m)



def disp(title):
    """menu title -> name as the app shows it: '&&' is a literal '&', a single '&' marks the mnemonic, '...' dropped."""
    t = (title or "").replace("&&", "\0").replace("&", "").replace("\0", "&")
    return t[:-3].rstrip() if t.endswith("...") else t.strip()


def tree_paths():
    """fresh menu tree -> list of nodes with 'dpath' (display path built from titles, so '/' inside a name is kept)."""
    tree = json.loads((A / "menu_tree_audit.json").read_text(encoding="utf-8"))
    out, stack = [], []  # stack of [dpath, children left]; the walk is depth-first with n_sub counts
    for n in tree:
        while stack and stack[-1][1] == 0:
            stack.pop()
        parent = stack[-1][0] if stack else None
        if stack:
            stack[-1][1] -= 1
        d = disp(n.get("title") or n["name"])
        n["disp"] = d
        n["dpath"] = (parent + "/" + d).lstrip("/") if parent is not None else ""
        out.append(n)
        if n.get("n_sub"):
            stack.append([n["dpath"], n["n_sub"]])
    return out


def names():
    """harvest name/path vs the display path of the same menu node (matched by positive unique command id)."""
    nodes = tree_paths()
    cmd = {}
    for n in nodes:
        if n.get("command", 0) > 0:
            cmd.setdefault(n["command"], []).append(n)
    bad = []
    for k in ["ps_filter", "ps_adjustment", "ps_layer_style", "ps_menu"]:
        for it in load(k)["items"]:
            c = (it.get("extra") or {}).get("menu_cmd")
            ns = cmd.get(c) if isinstance(c, int) else None
            if not ns:
                ns = [n for n in nodes if n["dpath"] == it.get("path")]
            if not ns:
                bad.append((k, it["id"], it["name"], it.get("path"), "no menu node"))
                continue
            if all(n["dpath"] != it.get("path") for n in ns) or all(n["disp"] != it["name"] for n in ns):
                bad.append((k, it["id"], it["name"], it.get("path"), [n["dpath"] for n in ns]))
    for b in bad:
        print(b)
    print(len(bad), "name/path mismatches")
    return bad



def extras():
    """harvest items whose path is not a node of the fresh menu tree (and no command id match)."""
    nodes = tree_paths()
    paths = {n["dpath"] for n in nodes}
    cmds = {n.get("command") for n in nodes}
    for k in ["ps_filter", "ps_adjustment", "ps_layer_style", "ps_menu"]:
        for it in load(k)["items"]:
            if it.get("path") not in paths:
                print(k, it["id"], repr(it["name"]), it.get("path"), "cmd-in-tree" if (it.get("extra") or {}).get("menu_cmd") in cmds else "")



# ---------------------------------------------------------------- live checks (Photoshop 2026, own document only)
DOC = "pgd_audit_ps"
TEST = (PGD / "media/test_photo.png").as_posix()


def ps():
    import psdrv
    return psdrv


def setup():
    """own 480x270 copy of the test photo named pgd_audit_ps (the opened original is closed unsaved)."""
    import urllib.parse
    src = '''
    if (!activate("%(doc)s")) {
      var o = openTest("%(p)s"); var d = o.duplicate("%(doc)s", true); o.close(SaveOptions.DONOTSAVECHANGES);
      d.resizeImage(UnitValue(480, "px"), UnitValue(270, "px"), 72, ResampleMethod.BICUBIC);
      d.artLayers[0].isBackgroundLayer = false;
    }
    activate("%(doc)s"); app.activeDocument.name + " " + app.activeDocument.layers.length''' % {
        "doc": DOC, "p": urllib.parse.quote(TEST, safe="")}
    return ps().js(src, timeout=90, tag="audit-setup")


# put a typed value into a descriptor: [key, kind, value, unit]; kind in num/int/bool/enum/unit/str
CHK_JS = r'''
(function () {
  function K(k) { return k.charAt(0) == "'" ? C2T(k.substr(1, 4)) : S2T(k); }
  function put(d, s) {
    var k = K(s[0]);
    if (s[1] == "num") d.putDouble(k, s[2]);
    else if (s[1] == "int") d.putInteger(k, s[2]);
    else if (s[1] == "bool") d.putBoolean(k, s[2]);
    else if (s[1] == "unit") d.putUnitDouble(k, K(s[3]), s[2]);
    else if (s[1] == "enum") d.putEnumerated(k, K(s[3]), K(s[2]));
    else if (s[1] == "str") d.putString(k, s[2]);
  }
  function hist() { var h = app.activeDocument.histogram, s = 0, s2 = 0; for (var i = 0; i < 256; i++) { s += h[i] * i; s2 += h[i] * i * i / 256; } return [s, Math.round(s2)]; }
  activate("%(doc)s"); var doc = app.activeDocument, h0 = doc.activeHistoryState, runs = %(runs)s, out = [];
  for (var r = 0; r < runs.length; r++) {
    var d = new ActionDescriptor(); for (var q = 0; q < runs[r].length; q++) put(d, runs[r][q]);
    var res = {sent: runs[r]}, b = hist();
    try { res.rb = d2o(executeAction(K("%(ev)s"), d, DialogModes.NO)); var a2 = hist(); res.dh = [a2[0] - b[0], a2[1] - b[1]]; }
    catch (e) { res.err = String(e); }
    try { doc.activeHistoryState = h0; } catch (e1) {}
    out.push(res);
  }
  return J(out);
})();
'''


def chk(ev, runs, timeout=90):
    """run event ev once per descriptor spec in runs (each run reverted) -> [{sent, rb|err, dh}]"""
    return ps().jsj(CHK_JS % {"doc": DOC, "ev": ev, "runs": json.dumps(runs)}, timeout=timeout, tag="audit-" + ev)


def close():
    return ps().js('closeNoSave("%s"); app.documents.length' % DOC, tag="audit-close")



UT = {"UNITDOUBLE": "unit", "INTEGERTYPE": "int", "DOUBLETYPE": "num", "BOOLEANTYPE": "bool", "ENUMERATEDTYPE": "enum"}


def spec(key, rb, value):
    """descriptor spec for key using the type Photoshop itself read back"""
    t = rb["t"]
    if t == "UNITDOUBLE":
        return [key, "unit", value, rb["unit"]]
    if t == "ENUMERATEDTYPE":
        return [key, "enum", value, rb["etype"]]
    return [key, UT[t], value]


def check_event_item(kind, it):
    """live re-check of one ps_event item: keys, default, in-range apply, out-of-range clamp. -> report dict"""
    ev = it["invoke"]["ps_event"]
    base = chk(ev, [[]])[0]
    rep = {"kind": kind, "id": it["id"], "event": ev, "problems": [], "ok": []}
    if "err" in base:
        rep["problems"].append("empty descriptor: " + base["err"][:160])
        return rep
    rb = base["rb"]
    hk = {p["key"]: p for p in it.get("params") or []}
    unknown = [k for k in rb if k not in hk]
    if unknown:
        rep["problems"].append(f"read-back keys not in harvest params: {unknown}")
    runs, plan = [], []
    for k, p in hk.items():
        if k not in rb:
            continue
        v0 = rb[k].get("v")
        if "default" in p:
            (rep["ok"] if p["default"] == v0 else rep["problems"]).append(f"{k}: default {p['default']} vs live {v0}")
        t = rb[k]["t"]
        if t in ("UNITDOUBLE", "INTEGERTYPE", "DOUBLETYPE"):
            lo, hi = p.get("min"), p.get("max")
            if lo is not None and hi is not None:
                mid = (lo + hi) / 2
                mid = int(round(mid)) if t == "INTEGERTYPE" or float(v0).is_integer() else mid
                if mid == v0:
                    mid = int(lo + (hi - lo) / 4) if t == "INTEGERTYPE" else lo + (hi - lo) / 4
                runs.append([spec(k, rb[k], mid)]); plan.append((k, "in", mid))
                big = hi + max(abs(hi), 1) * 10
                runs.append([spec(k, rb[k], int(big) if t == "INTEGERTYPE" else big)]); plan.append((k, "over", hi))
                low = lo - max(abs(lo), 1) * 10
                runs.append([spec(k, rb[k], int(low) if t == "INTEGERTYPE" else low)]); plan.append((k, "under", lo))
            else:
                nv = (v0 or 0) + (1 if t == "INTEGERTYPE" else 1.5)
                runs.append([spec(k, rb[k], nv)]); plan.append((k, "in", nv))
        elif t == "ENUMERATEDTYPE" and p.get("enum"):
            alt = [e["value"] for e in p["enum"] if e["value"] != v0][:1]
            if alt:
                runs.append([spec(k, rb[k], alt[0])]); plan.append((k, "enum", alt[0]))
        elif t == "BOOLEANTYPE":
            runs.append([spec(k, rb[k], not v0)]); plan.append((k, "bool", not v0))
    res = chk(ev, runs) if runs else []
    rep["runs"] = []
    for (k, what, want), r in zip(plan, res):
        got = (r.get("rb") or {}).get(k, {}).get("v")
        line = f"{k} {what} sent {r['sent'][0][2]} -> {got if 'err' not in r else r['err'][:100]} dh {r.get('dh')}"
        rep["runs"].append(line)
        if "err" in r:
            rep["problems" if what != "over" and what != "under" else "ok"].append(line)
        elif what in ("over", "under"):
            (rep["ok"] if got == want else rep["problems"]).append(f"{k}: {what} recorded {want}, live {got}")
        else:
            (rep["ok"] if got == want else rep["problems"]).append(f"{k}: {what} sent {want}, read back {got}")
    return rep



def restore(ev, values):
    """write values back as the plug-in's stored settings (one run on our document, reverted)."""
    rb = chk(ev, [[]])[0]["rb"]
    r = chk(ev, [[spec(k, rb[k], v) for k, v in values.items()]])[0]
    after = chk(ev, [[]])[0]["rb"]
    return {k: after[k].get("v") for k in values}



BLEND_JS = r'''
(function () {
  activate("%(doc)s"); var doc = app.activeDocument, h0 = doc.activeHistoryState, modes = %(modes)s, out = {};
  var dd = app.displayDialogs; app.displayDialogs = DialogModes.NO;
  function setMode(m) {
    var d = new ActionDescriptor(), r = new ActionReference(); r.putEnumerated(C2T("Lyr "), C2T("Ordn"), C2T("Trgt"));
    d.putReference(C2T("null"), r); var l = new ActionDescriptor(); l.putEnumerated(S2T("mode"), S2T("blendMode"), S2T(m));
    d.putObject(C2T("T   "), C2T("Lyr "), l); executeAction(C2T("setd"), d, DialogModes.NO);
  }
  function test(tag) {
    for (var i = 0; i < modes.length; i++) {
      var m = modes[i], o = out[m] || (out[m] = {});
      try { setMode("normal"); setMode(m); var ld = layerDesc(); o[tag] = tid2s(ld.getEnumerationValue(S2T("mode")));
            if (tag == "layer") try { o[tag + "_dom"] = String(app.activeDocument.activeLayer.blendMode); } catch (e2) { o[tag + "_dom"] = "ERR " + String(e2); } }
      catch (e) { o[tag] = "ERR " + String(e).substr(0, 120); }
    }
  }
  test("layer");
  doc.layerSets.add(); test("group");
  app.displayDialogs = dd;
  return J(out);
})();
'''


def blend():
    items = load("ps_blend_mode")["items"]
    modes = [i["extra"]["am_enum"] for i in items]
    ps().js('closeNoSave("%s"); 1' % DOC, tag="audit-reset")
    setup()
    r = ps().jsj(BLEND_JS % {"doc": DOC, "modes": json.dumps(modes)}, timeout=240, tag="audit-blend")
    ps().js('closeNoSave("%s"); 1' % DOC, tag="audit-reset")
    setup()
    (A / "blend_live.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
    for m in modes:
        print(m, r.get(m))



AUDIT = "audit 2026-10-04 (tools/ps/audit_ps.py)"


def note(it, msg):
    ex = it.setdefault("extra", {})
    ex.setdefault("audit", []).append(msg)


def fix_static():
    """corrections that need no live call: paths of names holding '/', cross-kind duplicates, stale dynamic title,
    a missing static command."""
    nodes = tree_paths()
    by_cmd = {}
    for n in nodes:
        if n.get("command", 0) > 0:
            by_cmd.setdefault(n["command"], []).append(n)
    for k in ["ps_filter", "ps_adjustment"]:
        doc = load(k)
        for it in doc["items"]:
            if "/" in it["name"] and it.get("path", "").endswith("/" + it["name"]):
                parent = it["path"][: -len(it["name"]) - 1]
                want = None
                c = (it.get("extra") or {}).get("menu_cmd")
                if isinstance(c, int) and c > 0 and by_cmd.get(c):
                    want = by_cmd[c][0]["dpath"]
                else:
                    cand = [n["dpath"] for n in nodes if n["disp"] == it["name"] and n["dpath"].startswith(parent.rsplit("/", 1)[0])]
                    want = cand[0] if len(cand) == 1 else None
                if want and want != it["path"]:
                    note(it, f"path was {it['path']!r}: the '/' inside the name had been split into a menu level")
                    it["path"] = want
        save(k, doc)
    other = {}
    for k in ["ps_adjustment", "ps_layer_style", "ps_filter"]:
        for it in load(k)["items"]:
            if it.get("path"):
                other[it["path"]] = (k, it["id"])
    m = load("ps_menu")
    keep = []
    for it in m["items"]:
        if it.get("path") in other:
            print("drop from ps_menu (already", other[it["path"]], "):", it["id"], it["path"])
            continue
        keep.append(it)
    m["items"] = keep
    for it in m["items"]:
        if it["id"] == "2957" and it["name"] == "Lock Group":
            note(it, "name was 'Lock Group': that title is shown only while a layer group is selected (stale state in "
                     "the harvest walk); with no document and with a plain document menuBarInfo titles this command "
                     "'Lock Layers...'")
            it["name"], it["path"] = "Lock Layers", "Layer/Lock Layers"
            it["extra"]["menu_title"] = "&Lock Layers..."
            it["extra"]["alt_titles"] = ["Lock Group"]
            it["extra"]["dynamic_title"] = True
        if it["id"] == "3382":
            it["extra"]["alt_titles"] = ["Convert to Paragraph Text", "Convert Text Shape Type"]
            it["extra"]["dynamic_title"] = True
            note(it, "title is state dependent: menuBarInfo read 'Convert to &Paragraph Text' in the audit walk, "
                     "'Convert &Text Shape Type' in the harvest walk")
    if not any(it["id"] == "2103" for it in m["items"]):
        n = by_cmd[2103][0]
        m["items"].append({"name": "Clear Recent File List", "id": "2103", "path": n["dpath"], "category": "File",
                           "extra": {"menu_cmd": 2103, "menu_title": n["title"], "menu_visible": n.get("visible"),
                                     "audit": ["added by audit: a static command inside the dynamic Open Recent list, "
                                               "left out with the recent-file entries"]},
                           "evidence": "menuBarInfo walk by the audit (executeActionGet capp/menuBarInfo, 0 documents)"})
    save("ps_menu", m)
    print("ps_menu items", len(m["items"]))



ZKEY = {"normal": "Normal", "dissolve": "Dissolve", "behind": "Behind", "clearEnum": "Clear", "multiply": "Multiply",
        "screen": "Screen", "overlay": "Overlay", "softLight": "SoftLight", "hardLight": "HardLight", "hardMix": "HardMix",
        "darken": "Darken", "lighten": "Lighten", "difference": "Difference", "hue": "Hue", "saturation": "Saturation",
        "color": "Color", "luminosity": "Luminosity", "exclusion": "Exclusion", "colorDodge": "ColorDodge",
        "colorBurn": "ColorBurn", "dodgeS": "DodgeShadows", "dodgeM": "DodgeMidtones", "dodgeH": "DodgeHighlights",
        "burnInS": "BurnShadows", "burnInM": "BurnMidtones", "burnInH": "BurnHighlights", "desaturate": "Desaturate",
        "saturate": "Saturate", "passThrough": "PassThrough", "linearDodge": "LinearDodge", "linearBurn": "LinearBurn",
        "linearHeight": "LinearHeight", "height": "Height", "linearLight": "LinearLight", "vividLight": "VividLight",
        "pinLight": "PinLight", "lighterColor": "LighterColor", "darkerColor": "DarkerColor",
        "blendSubtraction": "Subtraction", "blendDivide": "Divide"}


def fix_blend():
    live = json.loads((A / "blend_live.json").read_text(encoding="utf-8"))
    zs = json.loads((A / "transfermode_zstrings.json").read_text(encoding="utf-8"))
    doc = load("ps_blend_mode")
    for it in doc["items"]:
        am = it["extra"]["am_enum"]
        r = live.get(am, {})
        z = ZKEY.get(am)
        label = None
        if z and zs.get(z):
            vals = {v for _, v in zs[z]}
            label = sorted(vals)[0] if len(vals) == 1 else None
        if label:
            it["extra"]["terminology_label"] = it["name"]
            it["extra"]["zstring"] = f"$$$/TransferMode/{z}" if any(p == "" for p, _ in zs[z]) else f"$$$/Menu/TransferMode/{z}"
            it["name"] = label
        else:
            it["extra"]["terminology_label"] = it["name"]
            it["extra"]["zstring"] = None
        ok_l = r.get("layer") == am
        ok_g = r.get("group") == am
        it["extra"]["live"] = {"layer": r.get("layer"), "group": r.get("group")}
        dom = r.get("layer_dom", "")
        it["extra"]["dom"] = dom if ok_l and dom.startswith("BlendMode.") else None
        if ok_l and ok_g:
            it["requires"] = "pixel layer or layer group"
        elif ok_g and not ok_l:
            it["requires"] = "layer group (a pixel layer reads back 'normal')"
        else:
            it["requires"] = None
        it.pop("error", None)
        if not ok_l and not ok_g:
            it["error"] = ("refused as a layer blend mode: setting it on a pixel layer and on a layer group raised "
                           "'General Photoshop error ... not available' under DialogModes.NO; a value of the blendMode "
                           "enum used elsewhere (painting / toning tool modes), not applied through set layer mode")
        elif ok_l and not dom.startswith("BlendMode."):
            it["extra"]["hidden"] = ("accepted and read back on a layer through Action Manager, but the DOM blendMode "
                                     "getter then throws 'Internal error' (no DOM BlendMode value), so it is not a "
                                     "mode the DOM / Layers panel exposes")
        it["evidence"] = ("AM enum value from Photoshop.exe terminology (Enums.blendMode); display name from the "
                          "Photoshop.exe ZString in extra.zstring; live 2026-10-04: set layer mode through AM "
                          "(setd Lyr Trgt, DialogModes.NO) on a pixel layer and on a layer group, mode read back with "
                          "executeActionGet, DOM BlendMode read back on the layer (tools/ps/audit_ps.py blend)")
        if it.get("requires") is None:
            it.pop("requires")
        inv = {"ps_event": "set"}
        if it["extra"]["dom"]:
            inv["ps_dom"] = f"layer.blendMode = {it['extra']['dom']}"
        it["invoke"] = inv
    doc["source"] = ("blendMode enum of Photoshop.exe terminology; names from Photoshop.exe TransferMode ZStrings; each "
                     "value set on a pixel layer and a layer group and read back (AM + DOM) by the audit, tools/ps/audit_ps.py")
    save("ps_blend_mode", doc)
    for it in doc["items"]:
        print(it["id"], "|", it["name"], "|", it.get("requires"), "|", it["extra"]["dom"], "|", "ERR" if it.get("error") else "", it["extra"].get("hidden", "")[:30])



def probe_params(ev):
    """read-back of an empty run + clamp probes (+-1e6 per numeric key, one key per run); stored values restored."""
    base = chk(ev, [[]])[0]
    rb = base["rb"]
    runs, plan = [], []
    for k, v in rb.items():
        if v["t"] in ("INTEGERTYPE", "DOUBLETYPE", "UNITDOUBLE"):
            for big in (1000000, -1000000):
                runs.append([spec(k, v, big)]); plan.append((k, big))
    res = chk(ev, runs)
    after = chk(ev, [[]])[0]["rb"]
    changed = {k: rb[k]["v"] for k in rb if rb[k]["t"] in UT and after.get(k, {}).get("v") != rb[k]["v"]}
    if changed:
        restore(ev, changed)
    out = {"readback": rb, "dh": base.get("dh"), "probe": {}, "stores_last_scripted_value": bool(changed)}
    for (k, big), r in zip(plan, res):
        out["probe"].setdefault(k, {})[str(big)] = r.get("rb", {}).get(k, {}).get("v") if "err" not in r else "ERR " + r["err"][:80]
    return out



MENU_JS = r'''
(function () {
  activate("%(doc)s"); var doc = app.activeDocument, out = [], tests = %(tests)s;
  var dd = app.displayDialogs; app.displayDialogs = DialogModes.NO;
  function sel() { try { return doc.selection.bounds ? "sel" : "none"; } catch (e) { return "none"; } }
  function rul() { return String(app.preferences.rulerUnits); }
  for (var i = 0; i < tests.length; i++) {
    var t = tests[i], r = {arg: t[0], how: t[1]}, b = [sel(), doc.activeLayer.name, doc.layers.length];
    try { if (t[1] == "num") app.runMenuItem(t[0]); else app.runMenuItem(S2T(t[0])); r.ok = true; }
    catch (e) { r.err = String(e).substr(0, 140); }
    r.before = b; r.after = [sel(), doc.activeLayer.name, doc.layers.length];
    try { doc.selection.deselect(); } catch (e2) {}
    out.push(r);
  }
  app.displayDialogs = dd;
  return J(out);
})();
'''


def menu_invoke(tests):
    return ps().jsj(MENU_JS % {"doc": DOC, "tests": json.dumps(tests)}, timeout=100, tag="audit-menu")



def fix_menu_invoke():
    live = json.loads((A / "menu_invoke_live.json").read_text(encoding="utf-8"))
    ok = {k for k, v in live.items() if all(x == "ok" for x in v)}
    m = load("ps_menu")
    nver = 0
    for it in m["items"]:
        inv = it.get("invoke") or {}
        ex = it.setdefault("extra", {})
        if "ps_menu_cmd" in inv:
            ex["uxp_command_id"] = inv.pop("ps_menu_cmd")
        match = [s for s in ex.get("menu_item_type_label_match") or [] if s in ok]
        if len(match) == 1:
            inv["ps_menu_cmd"] = match[0]
            ex["ps_menu_cmd_verified"] = ("audit 2026-10-04: app.runMenuItem(stringIDToTypeID('%s')) ran without error on a "
                                          "scratch document under DialogModes.NO" % match[0])
            nver += 1
        if inv:
            it["invoke"] = inv
        else:
            it.pop("invoke", None)
        ex.setdefault("audit", []).append(
            "invoke.ps_menu_cmd held the menuBarInfo command id, which app.runMenuItem refuses ('<unknown> menu item is "
            "not currently available'; audit tried 1017, 1192, 1135): moved to extra.uxp_command_id; invoke.ps_menu_cmd "
            "is now set only where a menuItemType stringID was run live")
    m["source"] = m["source"] + "; audit 2026-10-04: invoke.ps_menu_cmd only for live-verified runMenuItem stringIDs"
    save("ps_menu", m)
    print("verified runMenuItem stringIDs:", nver)


def fix_events():
    pr = json.loads((A / "probe_bw_ds.json").read_text(encoding="utf-8"))

    def params(ev, names):
        out = []
        for k, v in pr[ev]["readback"].items():
            p = {"name": names.get(k, k), "key": k, "type": {"INTEGERTYPE": "int", "DOUBLETYPE": "number", "UNITDOUBLE": "number",
                 "BOOLEANTYPE": "bool", "ENUMERATEDTYPE": "enum", "OBJECTTYPE": "color" if v.get("cls") == "RGBColor" else "object"}[v["t"]]}
            if v["t"] in ("INTEGERTYPE", "DOUBLETYPE", "UNITDOUBLE", "BOOLEANTYPE", "ENUMERATEDTYPE"):
                p["default"] = v["v"]
            if v["t"] == "OBJECTTYPE" and v.get("cls") == "RGBColor":
                p["default"] = {kk: round(vv["v"], 3) for kk, vv in v["v"].items()}
            pb = pr[ev]["probe"].get(k)
            if pb:
                p["extra"] = {"range_probe": pb}
                if all(str(val) == key for key, val in pb.items()):
                    p["extra"]["range_note"] = "no clamp: +-1e6 read back as sent"
                elif len(set(pb.values())) == 1:
                    p["extra"]["range_note"] = "inconclusive: the read-back ignores the sent value (stored value echoed)"
            out.append(p)
        return out
    a = load("ps_adjustment")
    for it in a["items"]:
        if it["id"] == "Image/Adjustments/Black & White":
            it["id"] = "blackAndWhite"
            it.pop("error", None)
            it["invoke"] = {"ps_event": "blackAndWhite"}
            it["requires"] = "pixel layer"
            it["params"] = params("blackAndWhite", {"presetKind": "Preset Kind", "grain": "green (key 'Grn ', reads back as grain)",
                                                    "useTint": "Tint", "tintColor": "Tint Color"})
            it["evidence"] = ("audit 2026-10-04: executeAction(blackAndWhite, {}, DialogModes.NO) on a 480x270 RGB copy of "
                              "the test photo converted it (histogram changed); keys/defaults = read-back with nothing "
                              "specified; +-1e6 probes per numeric key")
            note(it, "was listed with no event ('no Action Manager event with this display name'): the name lookup failed "
                     "on '&&' in the menu title; the event blackAndWhite runs headless (the presets stage already used it)")
    save("ps_adjustment", a)
    f = load("ps_filter")
    for it in f["items"]:
        if it["id"] == "Filter/Noise/Dust & Scratches":
            it["id"] = "dustAndScratches"
            it.pop("error", None)
            it["invoke"] = {"ps_event": "dustAndScratches"}
            it["requires"] = "pixel layer"
            it["params"] = params("dustAndScratches", {"radius": "Radius", "threshold": "Threshold"})
            it["evidence"] = ("audit 2026-10-04: executeAction(dustAndScratches, {}, DialogModes.NO) on a 480x270 RGB copy "
                              "of the test photo changed the pixels; keys/defaults = read-back with nothing specified "
                              "(Photoshop's stored values); the read-back echoes the stored values whatever is sent, so "
                              "no range")
            note(it, "was listed with no event: the name lookup failed on '&&' in the menu title")
    save("ps_filter", f)



def fix_hsb():
    f = load("ps_filter")
    for it in f["items"]:
        if it["id"] != "'HsbP'":
            continue
        for p in it["params"]:
            old = [e["value"] for e in p["enum"]]
            keep = [e for e in p["enum"] if e["value"] in ("RGBColor", "HSBColorEnum")]
            keep.append({"value": "HSLColor", "extra": {"charid": "HSLC", "note": "stringID registered at run time; not a "
                                                         "value of Photoshop.exe's colorSpace enum, so no terminology label"}})
            p["enum"] = keep
            p.setdefault("extra", {})["enum_note"] = (
                "audit 2026-10-04: each colorSpace value sent with the other key at RGBColor; only RGBColor, "
                "HSBColorEnum and HSLColor ('HSLC') were kept in the read-back and changed the pixels differently; "
                "grayscale, CMYK, Lab, bitmap, indexed, multichannel, duotone and useICCProfile read back as RGBColor "
                "with no pixel change (were listed: %s)" % ", ".join(old))
        note(it, "enum lists of Input/Output mode replaced by the values the plug-in accepts (live)")
    save("ps_filter", f)



def enum_test(kind, iid, key):
    it = [i for i in load(kind)["items"] if i["id"] == iid][0]
    p = [q for q in it["params"] if q["key"] == key][0]
    ev = it["invoke"]["ps_event"]
    rb = chk(ev, [[]])[0]["rb"]
    vals = [e["value"] for e in p["enum"]]
    res = chk(ev, [[spec(key, rb[key], v)] for v in vals])
    out = {v: [(r.get("rb") or {}).get(key, {}).get("v"), r.get("dh"), r.get("err", "")[:60]] for v, r in zip(vals, res)}
    after = chk(ev, [[]])[0]["rb"]
    ch = {k: rb[k]["v"] for k in rb if rb[k]["t"] in UT and after.get(k, {}).get("v") != rb[k]["v"]}
    if ch:
        restore(ev, ch)
    return out



def fix_preset_ids():
    """duplicate preset names got ' (n)' by file order: use the preset-group path instead where it separates them."""
    import re, collections
    d = load("ps_preset")
    sets = collections.defaultdict(list)
    for it in d["items"]:
        sets[re.sub(r" \(\d+\)$", "", it["id"])].append(it)
    n = 0
    for base, v in sets.items():
        if len(v) < 2:
            continue
        f = base.split("#")[0]
        grp = [(it.get("path") or "")[len(f):].lstrip("/") if (it.get("path") or "").startswith(f) else None for it in v]
        new = [f"{f}#{g}/{it['name']}" if g else None for g, it in zip(grp, v)]
        if None in new or len(set(new)) < len(new):
            for it in v:
                note(it, "id keeps the ' (n)' file-order suffix: duplicates share the same preset group, nothing stabler")
            continue
        for it, nid in zip(v, new):
            it.setdefault("extra", {})["old_id"] = it["id"]
            it["id"] = nid
            n += 1
    ids = [it["id"] for it in d["items"]]
    assert len(ids) == len(set(ids)), "id clash"
    save("ps_preset", d)
    print("preset ids rewritten:", n)


if __name__ == "__main__":
    globals()[sys.argv[1]]()
