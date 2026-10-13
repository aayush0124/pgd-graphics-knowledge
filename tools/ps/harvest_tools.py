"""PGD Photoshop stage "tools": builds harvest/ps/ps_menu.json and harvest/ps/ps_tool.json.

    python harvest_tools.py menu        menu_tree.json (dump_menus.py) + Default Keyboard Shortcuts.kys -> ps_menu.json
    python harvest_tools.py toolbar     decode the toolbar customizations shipped in Required/Workspaces/*.psw (via PS)
    python harvest_tools.py probe       verify every candidate tool id with app.currentTool set + read-back, and read
                                        its currentToolOptions; resumable, checkpoint work/ps/probe_tools.json
    python harvest_tools.py tools       build ps_tool.json from the kys + toolbar + probe checkpoints
    python harvest_tools.py all         toolbar, probe, tools, menu

Sources are all on disk or in the running app: the menuBarInfo tree, the install's Default Keyboard Shortcuts.kys,
the workspace .psw toolbar customizations, Photoshop.exe ZStrings ($$$/Toolbar/ToolTips/...) and terminology.
"""
import json, re, sys, base64, time
import xml.etree.ElementTree as ET
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).parent))
import psdrv  # noqa: E402

PS = Path(os.environ.get("PGD_PS_DIR") or r"C:/Program Files/Adobe/Adobe Photoshop 2026")
KYS = PS / "Locales/en_US/Support Files/Shortcuts/Win/Default Keyboard Shortcuts.kys"
WS = PS / "Required/Workspaces"
EXE = PS / "Photoshop.exe"
W = psdrv.WORK
H = (PGD / "harvest/ps")


def app_version():
    """app.version from the running Photoshop (written to work/ps/app_version.txt); the file if PS is unreachable."""
    try:
        v = psdrv.js("app.version", timeout=30, tag="version")
        (W / "app_version.txt").write_text(v)
        return v
    except psdrv.PSError:
        return (W / "app_version.txt").read_text().strip() if (W / "app_version.txt").exists() else None


VERSION = None
SCRATCH = "pgd_tools_scratch"


def save(p, obj):
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def load(p, default):
    return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else default


# ---------------------------------------------------------------- keyboard shortcut file
def norm_sc(s):
    """'Alt+Shift+Ctrl+O' -> 'Ctrl+Alt+Shift+O' (the order menuBarInfo uses)."""
    parts = s.split("+")
    if s.endswith("++"):  # 'Ctrl++'
        parts = s[:-2].split("+") + ["+"]
    mods = [m for m in ("Ctrl", "Alt", "Shift", "Win") if m in parts[:-1]]
    return "+".join(mods + [parts[-1]])


def parse_kys():
    root = ET.parse(KYS).getroot()
    cmds, dyn, tools, tasks = {}, {}, [], {}
    for c in root.findall("command"):
        scs = [norm_sc(s.text) for s in c.findall("shortcut") if s.text]
        if c.get("kind") == "static":
            cmds[int(c.get("id"))] = {"name": c.get("name"), "shortcuts": scs}
        else:
            dyn[c.get("name")] = scs
    for t in root.findall("tool"):
        tools.append({"name": t.get("name"), "type": int(t.get("type")), "key": int(t.get("key")) if t.get("key") else None,
                      "shortcut": (t.text or "").strip()})
    for ts in root.findall("taskspace"):
        tasks[ts.get("name")] = [{"name": t.get("name"), "key": int(t.get("key")), "shortcut": (t.text or "").strip()}
                                 for t in ts.findall("taskspace-tool")]
    return cmds, dyn, tools, tasks


# ---------------------------------------------------------------- menus
def clean_title(t):
    t = (t or "").replace("&&", "\x01").replace("&", "").replace("\x01", "&").strip()
    return t


def strip_dots(t):
    return re.sub(r"(\.\.\.|\u2026)$", "", t).strip()


def menu_item_types():
    term = load(W / "ps_terminology.json", {})
    out = {}
    for sid, v in (term.get("Enums", {}).get("menuItemType") or {}).items():
        lab = v["z"].split("=", 1)[1] if isinstance(v, dict) and "=" in v.get("z", "") else ""
        out.setdefault(re.sub(r"[^a-z0-9]", "", lab.lower()), []).append(sid)
    return out


PANEL_MIT = ("timeline", "cloneSource", "animation", "histogramPalette", "infoPalette", "pick", "channels",
             "paths", "navigator", "layersPalette", "historyPalette", "export", "3D", "toggle3D")
DYNAMIC_PREFIX = ("File/Open Recent/", "Help/About Plugins/")


def build_menu():
    tree = load(W / "menu_tree.json", [])
    cmds, _dyn, _t, _ts = parse_kys()
    mit = menu_item_types()
    claimed = set()
    for k in ("ps_filter", "ps_adjustment", "ps_layer_style", "ps_blend_mode"):
        for it in load(H / f"{k}.json", {"items": []})["items"]:
            if it.get("path"):
                claimed.add(it["path"])
    with_doc = {}  # positive command ids are stable; titles such as 'Undo <step>' change with the document
    for r in load(W / "menu_tree_doc.json", []):
        if r.get("kind") == "item":
            with_doc[r.get("command") if r.get("command", 0) > 0 else (r["path"], r.get("command"))] = r.get("enabled")
    states = load(W / "menu_states.json", {})
    items, skipped = [], {}
    scripts = {}  # menu title -> installed script that implements it (<name>$$$/...=Title</name> header)
    for f in sorted((PS / "Presets/Scripts").glob("*.jsx")):
        mm = re.search(r"<name>[^<=]*=([^<]+)</name>", f.read_text(encoding="utf-8", errors="ignore")[:8000])
        if mm:
            scripts[mm.group(1).strip()] = str(f).replace("\\", "/")

    def skip(r, why):
        skipped.setdefault(why, []).append(r["path"] + (" " + clean_title(r.get("title")) if not r["name"] else ""))

    for r in tree:
        if r.get("kind") != "item":
            continue
        p, title = r["path"], clean_title(r.get("title"))
        if p.startswith("Filter/") or p.startswith("Image/Adjustments/"):
            skip(r, "Filter / Image>Adjustments (other kinds)")
            continue
        if p in claimed:
            skip(r, "already in ps_adjustment / ps_layer_style")
            continue
        if p.startswith(DYNAMIC_PREFIX):
            skip(r, "dynamic list (recent files / plug-in about boxes)")
            continue
        if p.startswith("Window/Workspace/") and (r.get("command", 0) < 0 or title.endswith("(Default)")):
            skip(r, "workspace entries")
            continue
        if p == "Window/" and r.get("command", 0) < 0 and re.match(r"^\d+\s", title):
            skip(r, "open-document list (Window menu)")
            continue
        if p == "Help/" and r.get("command", 0) < 0:
            skip(r, "account entries (Manage My Account / Sign Out, title holds the signed-in e-mail)")
            continue
        name = r["name"]
        if not name or "  " in name:
            name = strip_dots(title)
        parent = p[:-1] if p.endswith("/") else p.rsplit("/", 1)[0] if "/" in p else ""
        if r["name"] and "  " not in r["name"]:
            path = p
        else:
            path = (parent + "/" if parent else "") + name
        extra = {"menu_cmd": r.get("command"), "menu_title": title, "menu_visible": r.get("visible"),
                 "enabled_no_document": r.get("enabled")}
        ed = with_doc.get(r.get("command") if r.get("command", 0) > 0 else (r["path"], r.get("command")))
        if ed is not None:
            extra["enabled_with_document"] = ed
        sk = str(r.get("command")) if r.get("command", 0) > 0 else r["path"] + "|" + str(r.get("command"))
        en = {k: v.get(sk) for k, v in states.items()}
        if any(x is not None for x in en.values()):
            extra["enabled_in_state"] = en
        it_requires = None
        if not r.get("enabled"):
            ok = [lab for key, lab, _ in STATES if en.get(key)]
            first = ok[:1] if en.get("doc") else ok  # enabled in a plain document: the rest add nothing
            if first:
                it_requires = " or ".join(first)
                extra["requires_observed"] = "enabled with " + it_requires + \
                    " (menuBarInfo enabled flag, one scratch document per state)"
            elif states:
                extra["requires_observed"] = "disabled in every scratch state tried (" + ", ".join(states) + ")"
        if r.get("command", 0) == 1001 and title.startswith("New Window for"):
            name, path = "New Window for <document>", parent + "/New Window for <document>"
            extra["dynamic_title"] = True
        if p == "Window/Workspace/" and title.startswith("Reset "):
            extra["dynamic_title"] = True  # 'Reset <current workspace>'
        it = {"name": name, "path": path, "category": path.split("/")[0], "extra": extra}
        if it_requires:
            it["requires"] = it_requires
        if r.get("shortcut"):
            it["shortcut"] = r["shortcut"]
        k = cmds.get(r.get("command"))
        if k and k["shortcuts"]:
            extra["kys_default_shortcuts"] = k["shortcuts"]
            it.setdefault("shortcut", k["shortcuts"][0])
        base = strip_dots(title)
        rules = [("label", base)]
        if path.startswith("View/Snap To/"):
            rules.append(("'Toggle Snap To ' + label", "Toggle Snap To " + base))
        elif path.startswith(("View/", "Type/Panels/")):
            rules.append(("'Toggle ' + label", "Toggle " + base))
        elif path.startswith("Window/"):
            rules.append(("'Toggle ' + label + ' Panel'", "Toggle " + base + " Panel"))
        for how, lab in rules:
            # panel fly-out families (timeline*, cloneSource*, ...) share generic labels with main-menu items
            m = [x for x in mit.get(re.sub(r"[^a-z0-9]", "", lab.lower()), []) if not x.startswith(PANEL_MIT)]
            if m:
                extra["menu_item_type_label_match"], extra["menu_item_type_match_rule"] = m, how
                break
        if path.startswith("File/") and title in scripts:
            it["invoke_file"] = scripts[title]
        items.append(it)

    from collections import Counter
    cnt = Counter(it["extra"]["menu_cmd"] for it in items)
    seen = set()
    for it in items:
        c = it["extra"]["menu_cmd"]
        if c and c > 0 and cnt[c] == 1:
            it["id"] = str(c)
        else:
            it["id"] = it["path"]
            if c and c > 0:
                it["extra"]["shared_cmd_with"] = [o["path"] for o in items if o["extra"]["menu_cmd"] == c and o is not it]
            elif c and c < 0:
                it["extra"]["menu_cmd_note"] = "negative command ids are assigned per session (scripts, plug-ins, " \
                                               "dynamic entries); address this item by its path"
        if it["id"] in seen:  # two identical paths (should not happen): make it unique by the session cmd
            it["id"] = f'{it["path"]}#{c}'
        seen.add(it["id"])
        it["invoke"] = {"ps_menu_cmd": c if c and c > 0 else it["id"]}
        if it.get("invoke_file"):
            it["invoke"]["file"] = it.pop("invoke_file")
            it["extra"]["script_note"] = "menu entry is the installed script named in invoke.file (its <name> header)"
        it["evidence"] = "menuBarInfo walk (executeActionGet capp/menuBarInfo, no documents open)" + \
            ("; default shortcut from Default Keyboard Shortcuts.kys" if "kys_default_shortcuts" in it["extra"] else "") + \
            ("; menuItemType enum label match from Photoshop.exe terminology (not executed)"
             if "menu_item_type_label_match" in it["extra"] else "")
    doc = {"app": "PS", "kind": "ps_menu", "app_version": VERSION,
           "source": "menuBarInfo tree (tools/ps/dump_menus.py) minus Filter, Image>Adjustments, adjustment-layer and "
                     "layer-style items and dynamic lists; shortcuts live from menuBarInfo + install Default Keyboard "
                     "Shortcuts.kys (all 85 agree: no customized set is active); requires = menuBarInfo enabled "
                     "flags in 7 scratch-document states (tools/ps/harvest_tools.py menudoc, menu). ps_menu_cmd is the menuBarInfo command id = the "
                     "UXP core.performMenuCommand commandID; ExtendScript app.runMenuItem(N) does NOT take it "
                     "(verified 2026-10-04: runMenuItem(1017) -> 'not currently available' alert); extra."
                     "menu_item_type_label_match lists menuItemType enum values whose English label matches the menu title "
                     "(rule in menu_item_type_match_rule); app.runMenuItem(stringIDToTypeID(x)) runs a menuItemType "
                     "(verified for fitOnScreen, toggleRulers, actualPixels) but each match is by label, not executed",
           "items": items}
    save(H / "ps_menu.json", doc)
    save(W / "menu_skipped.json", skipped)
    print("ps_menu", len(items), "items; skipped", {k: len(v) for k, v in skipped.items()})


FILL = ('app.activeDocument.selection.selectAll(); app.activeDocument.selection.fill(app.foregroundColor); '
        'app.activeDocument.selection.deselect(); ')
# document states for the 'requires' dumps: each starts from a fresh RGB document (white background + one pixel layer)
STATES = [
    ("doc", "an open document", ""),
    ("filled", "a pixel layer with content", FILL),
    ("selection", "an active selection", FILL + "app.activeDocument.selection.selectAll(); "),
    ("text", "a text layer", 'var tl = app.activeDocument.artLayers.add(); tl.kind = LayerKind.TEXT; '
                             'tl.textItem.contents = "PGD"; '),
    ("smart", "a smart object layer", FILL + 'executeAction(S2T("newPlacedLayer"), undefined, DialogModes.NO); '),
    ("group", "a layer group", FILL + 'app.activeDocument.layerSets.add(); '),
    ("multi", "two or more layers selected", FILL + 'var sd = new ActionDescriptor(), sr = new ActionReference(); '
              'sr.putName(C2T("Lyr "), app.activeDocument.backgroundLayer.name); sd.putReference(C2T("null"), sr); '
              'sd.putEnumerated(S2T("selectionModifier"), S2T("selectionModifierType"), S2T("addToSelection")); '
              'executeAction(C2T("slct"), sd, DialogModes.NO); '),
]


def dump_menu_with_doc():
    """menuBarInfo again in our own scratch document, once per document state (STATES) ->
    menu_tree_doc.json (plain document) and menu_states.json {state: {cmd or path|cmd: enabled}}, so ps_menu can say
    what a command needs before it is enabled. Resumable per state."""
    import dump_menus
    out = load(W / "menu_states.json", {})
    for key, _label, setup in STATES:
        if key in out:
            continue
        try:
            tree = psdrv.jsj('closeNoSave("%s"); newDoc("%s", 400, 240); app.activeDocument.artLayers.add(); %s %s'
                             % (SCRATCH, SCRATCH, setup, dump_menus.JS), timeout=180, tag="menus-" + key)
        except psdrv.PSError as e:
            print("state", key, "failed:", str(e)[:200])
            continue
        finally:
            psdrv.js('closeNoSave("%s"); app.documents.length' % SCRATCH, timeout=60, tag="close")
        if key == "doc":
            save(W / "menu_tree_doc.json", tree)
        out[key] = {str(r.get("command")) if r.get("command", 0) > 0 else r["path"] + "|" + str(r.get("command")):
                    r.get("enabled") for r in tree if r.get("kind") == "item"}
        save(W / "menu_states.json", out)
        print("state", key, sum(1 for v in out[key].values() if v), "enabled of", len(out[key]))


# ---------------------------------------------------------------- toolbar customizations shipped with the install
DECODE_JS = ('var h="%s", s=""; for (var i=0;i<h.length;i+=2) s+=String.fromCharCode(parseInt(h.substr(i,2),16));'
             'var d=new ActionDescriptor(); d.fromStream(s); var L=d.getList(C2T("tlst")), g=[];'
             'for (var a=0;a<L.count;a++){var l=L.getList(a), m=[]; for (var b=0;b<l.count;b++){var o=l.getObjectValue(b);'
             'm.push(o.getInteger(S2T("toolKey")));} g.push(m);} J(g)')


def decode_toolbars():
    out = {}
    for f in sorted(WS.glob("*.psw")):
        m = re.search(r"<photoshop-toolbar-customization>(.*?)</photoshop-toolbar-customization>",
                      f.read_text(encoding="utf-8-sig"), re.S)
        if not m:
            continue
        out[f.name] = psdrv.jsj(DECODE_JS % base64.b64decode(m.group(1)).hex(), timeout=60, tag="toolbar " + f.name)
    save(W / "toolbar_groups.json", out)
    print("toolbars", {k: len(v) for k, v in out.items()})
    return out


# ---------------------------------------------------------------- tool candidates + live verification
KEYS_JS = r'''
var ks = %s, o = {};
for (var i = 0; i < ks.length; i++) { var s = "", c = "";
  try { s = typeIDToStringID(ks[i]); } catch (e) {} try { c = typeIDToCharID(ks[i]); } catch (e2) {}
  o[String(ks[i])] = {s: s, c: c}; }
J(o)
'''

PROBE_JS = r'''
var ids = %s, out = {};
if (!activate("%s")) newDoc("%s", 400, 240);
for (var i = 0; i < ids.length; i++) {
  var rec = {};
  // screen with an AM select under DialogModes.NO: an unknown / unavailable tool throws here, whereas
  // app.currentTool = id raises a modal 'The command "Select" is not currently available' alert
  try { var sr = new ActionReference(); sr.putClass(S2T(ids[i])); var sd = new ActionDescriptor();
        sd.putReference(C2T("null"), sr); executeAction(C2T("slct"), sd, DialogModes.NO); rec.am = true;
  } catch (e0) { rec.am = false; rec.err = String(e0).replace(/\s+/g, " ").substr(0, 200); }
  if (rec.am) try { app.currentTool = "moveTool"; app.currentTool = ids[i]; rec.back = String(app.currentTool); } catch (e) { rec.err = String(e); }
  if (rec.back == ids[i]) {
    try { rec.c4 = typeIDToCharID(S2T(ids[i])); } catch (e1) {}
    try {
      var r = new ActionReference(); r.putProperty(C2T("Prpr"), S2T("tool")); r.putEnumerated(C2T("capp"), C2T("Ordn"), C2T("Trgt"));
      var d = executeActionGet(r);
      if (d.hasKey(S2T("currentToolOptions"))) rec.opts = d2o(d.getObjectValue(S2T("currentToolOptions")), 6);
    } catch (e2) { rec.opterr = String(e2); }
  }
  out[ids[i]] = rec;
}
try { app.currentTool = "moveTool"; } catch (e3) {}
J(out)
'''


def exe_tool_strings():
    b = EXE.read_bytes()
    found = set(m.group(1).decode() for m in re.finditer(rb"\x00([A-Za-z][A-Za-z0-9]{1,48}Tool)\x00", b))
    return found


def candidates(kys_tools, tasks, toolbars):
    keys = {t["key"] for t in kys_tools if t["key"]} | {t["key"] for v in tasks.values() for t in v} | \
           {k for g in toolbars.values() for grp in g for k in grp}
    km = psdrv.jsj(KEYS_JS % json.dumps(sorted(keys)), timeout=60, tag="keys")
    save(W / "tool_keys.json", km)
    cand = {v["s"] for v in km.values() if v["s"]}
    term = load(W / "ps_terminology.json", {})
    raw = (W / "ps_terminology_raw.txt").read_text(encoding="utf-8", errors="ignore")
    cand |= set(re.findall(r"\b([a-z][A-Za-z0-9]*Tool)\b", raw))
    for s in exe_tool_strings():
        cand.add(s)
        if s[0].isupper():
            cand.add(s[0].lower() + s[1:])
    cand |= {k for k in term.get("Classes", {}) if k.endswith("Tool")}
    # tool classes whose stringID does not end in Tool: terminology labels them "patch selection" and
    # "move selection" (Patch / Content-Aware Move tools)
    cand |= {k for k in ("patchSelection", "recomposeSelection") if k in term.get("Classes", {})}
    return sorted(cand), km


def probe_tools(batch=25):
    cmds, dyn, kys_tools, tasks = parse_kys()
    toolbars = load(W / "toolbar_groups.json", None) or decode_toolbars()
    cand, _ = candidates(kys_tools, tasks, toolbars)
    ck = load(W / "probe_tools.json", {})
    todo = [c for c in cand if c not in ck]
    print(len(cand), "candidates,", len(todo), "to probe")
    try:
        for i in range(0, len(todo), batch):
            part = todo[i:i + batch]
            try:
                r = psdrv.jsj(PROBE_JS % (json.dumps(part), SCRATCH, SCRATCH), timeout=90, tag="toolprobe")
            except psdrv.PSError as e:  # one id took Photoshop into a modal: probe this batch one by one
                r = {}
                for c in part:
                    try:
                        r.update(psdrv.jsj(PROBE_JS % (json.dumps([c]), SCRATCH, SCRATCH), timeout=60, tag="tool " + c))
                    except psdrv.PSError as e1:
                        r[c] = {"err": "PSError: " + str(e1)[:300]}
            ck.update(r)
            save(W / "probe_tools.json", ck)
            ok = [k for k, v in r.items() if v.get("back") == k]
            print(time.strftime("%X"), i + len(part), "/", len(todo), "ok:", ok, flush=True)
    finally:
        try:
            psdrv.js('try { app.currentTool = "moveTool"; } catch (e) {} closeNoSave("%s"); app.documents.length' % SCRATCH,
                     timeout=60, tag="close")
        except psdrv.PSError as e:
            print("close failed", e)


# ---------------------------------------------------------------- build ps_tool.json
DVT2P = {"BOOLEANTYPE": "bool", "DOUBLETYPE": "number", "UNITDOUBLE": "number", "INTEGERTYPE": "int",
         "LARGEINTEGERTYPE": "int", "ENUMERATEDTYPE": "enum", "STRINGTYPE": "string", "OBJECTTYPE": "object",
         "LISTTYPE": "object", "CLASSTYPE": "string", "ALIASTYPE": "path", "RAWTYPE": "unknown",
         "REFERENCETYPE": "unknown"}


def zlabel(z):
    return z["z"].split("=", 1)[1] if isinstance(z, dict) and "=" in z.get("z", "") else None


def key_labels(term):
    """stringID key -> English label, from every event/class key in the terminology."""
    lab = {}
    for sect in ("Events", "Classes"):
        for v in term.get(sect, {}).values():
            for part in v if isinstance(v, list) else []:
                if isinstance(part, dict):
                    for k, kv in part.items():
                        if isinstance(kv, list) and kv and isinstance(kv[0], dict) and zlabel(kv[0]):
                            lab.setdefault(k, zlabel(kv[0]))
    return lab


def opts_to_params(opts, term, labels):
    ps = []
    for k, v in (opts or {}).items():
        t = DVT2P.get(v.get("t"), "unknown")
        p = {"name": labels.get(k, k.strip("'")), "key": k, "type": t}
        if t in ("bool", "number", "int", "string") and "v" in v:
            p["default"] = v["v"]
        if v.get("unit"):
            p["unit"] = v["unit"].replace("Unit", "")
        if t == "enum":
            p["default"] = v.get("v")
            ev = term.get("Enums", {}).get(v.get("etype"), {})
            if ev:
                p["enum"] = [{"value": e, "label": zlabel(z)} for e, z in ev.items()]
            p.setdefault("enum", [{"value": v.get("v"), "label": None}])
            p["enum_type"] = v.get("etype")
        if t == "object" and v.get("cls"):
            p["object_class"] = v["cls"]
        ps.append(p)
    return ps


def exe_names(kind):
    """ZString key -> English name from Photoshop.exe: kind 'tip' = $$$/Toolbar/ToolTips/<Key>=, 'title' = $$$/<Key>/Title=."""
    b = EXE.read_bytes()
    pat = rb"\$\$\$/Toolbar/ToolTips/([A-Za-z0-9_]+)=([^\x00$]{1,60})" if kind == "tip" else \
        rb"\$\$\$/([A-Za-z0-9]+Tool)/Title=([^\x00$]{1,60})"
    out = {}
    for m in re.finditer(pat, b):
        out.setdefault(m.group(1).decode(), m.group(2).decode("latin-1").split("\t")[0].strip())
    return out


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def toks(s):
    """'marqueeSingleRowTool' / 'Single Row Marquee Tool' -> ['marquee', 'row', 'single']"""
    w = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", s.replace("-", " "))
    return sorted(x.lower() for x in w if x.lower() != "tool")


def tok_match(a, b):
    """every token of the stringID is a prefix of a distinct token of the name, and the counts agree"""
    if not a or len(a) != len(b):
        return False
    left = list(b)
    for x in a:
        hit = next((y for y in left if y.startswith(x)), None)
        if hit is None:
            return False
        left.remove(hit)
    return True


def link_names(verified, kys_tools, term, titles, tips):
    """verified stringID -> (display name, kys tool or None, how). Strongest evidence first."""
    kn = {norm(t["name"]): t for t in kys_tools if t["type"] == 1}
    tn = {norm(k): v for k, v in titles.items()}
    pn = {norm(k): v for k, v in tips.items()}
    out = {}
    for sid in sorted(verified):
        c = term.get("Classes", {}).get(sid)
        lab = zlabel(c[0]) if c and isinstance(c[0], dict) else None
        hit = None
        if lab:
            for cand in (lab, lab + " tool"):
                if norm(cand) in kn:
                    hit = (kn[norm(cand)]["name"], kn[norm(cand)],
                           f'terminology class label of {sid} ("{lab}") = kys tool name')
                    break
        for nm_map, src in ((tn, "$$$/<Key>/Title"), (pn, "$$$/Toolbar/ToolTips/<Key>")):
            if hit is None and norm(sid) in nm_map:
                nm = nm_map[norm(sid)]
                hit = (kn[norm(nm)]["name"] if norm(nm) in kn else nm, kn.get(norm(nm)),
                       f"Photoshop.exe ZString {src} whose key equals the stringID" +
                       ("; name = kys tool name" if norm(nm) in kn else ""))
        if hit is None:  # 'patchSelection' <-> $$$/PatchTool/Title: same stem once Selection / Tool is dropped
            stem = norm(re.sub(r"(Selection|Tool)$", "", sid))
            ks = [k for k in titles if norm(k[:-4]) == stem and norm(titles[k]) in kn]
            if len(ks) == 1:
                nm = titles[ks[0]]
                hit = (kn[norm(nm)]["name"], kn[norm(nm)],
                       f"Photoshop.exe ZString $$$/{ks[0]}/Title has the same stem as the stringID; name = kys tool name")
        if hit is None:
            ms = [t for t in kn.values() if tok_match(toks(sid), toks(t["name"]))]
            if len(ms) == 1:
                hit = (ms[0]["name"], ms[0], "word match of the stringID to the kys tool name (weakest link)")
        out[sid] = hit
    return out


def build_tools():
    cmds, dyn, kys_tools, tasks = parse_kys()
    toolbars = load(W / "toolbar_groups.json", {})
    pr = load(W / "probe_tools.json", {})
    km = load(W / "tool_keys.json", {})
    term = load(W / "ps_terminology.json", {})
    labels = key_labels(term)
    titles, tips = exe_names("title"), exe_names("tip")
    verified = {k for k, v in pr.items() if v.get("back") == k}
    key2name = {t["key"]: t["name"] for t in kys_tools if t["key"]}
    for v in tasks.values():
        for t in v:
            key2name.setdefault(t["key"], t["name"])
    order = ["Graphic and Web.psw", "Painting.psw", "Photography.psw", "Motion.psw", "Core Tools_V2.psw", "Core Tools.psw"]
    group_of = {}  # kys/toolbar key -> (file, [keys]): the largest slot holding the tool in any shipped toolbar
    for f in order + [f for f in toolbars if f not in order]:
        for grp in toolbars.get(f, []):
            for k in grp:
                if k not in group_of or len(grp) > len(group_of[k][1]):
                    group_of[k] = (f, grp)
    letter_members = {}
    for t in kys_tools:
        if t["type"] == 1 and t["shortcut"]:
            letter_members.setdefault(t["shortcut"], []).append(t["name"])
    links = link_names(verified, kys_tools, term, titles, tips)
    by_kys = {}
    for sid, h in sorted(links.items()):
        if h and h[1]:
            by_kys.setdefault(h[1]["name"], []).append(sid)
    dup = {k: v for k, v in by_kys.items() if len(v) > 1}

    def group_fields(key, it, ex):
        if key in group_of:
            f, grp = group_of[key]
            names = [key2name.get(k) or f"<toolbar key '{km.get(str(k), {}).get('c') or k}'>" for k in grp]
            it["group"] = next((n for n in names if not n.startswith("<")), names[0])
            ex["group_members"], ex["group_source"] = names, f"Required/Workspaces/{f} toolbar customization"

    def tried_for(name):
        """probed ids whose words match a display name (or whose exe Title is that name), with their probe error"""
        out = {}
        for sid, rec in pr.items():
            if rec.get("back") != sid and (tok_match(toks(sid), toks(name)) or
                                           norm(titles.get(sid[:1].upper() + sid[1:], "")) == norm(name)):
                out[sid] = (rec.get("err") or "")[:100]
        return out

    items = []
    kys_order = {t["name"]: i for i, t in enumerate(kys_tools)}

    def sort_key(s):
        h = links[s]
        return (kys_order.get(h[1]["name"], 999) if h and h[1] else 999, s)

    for sid in sorted(verified, key=sort_key):
        h = links[sid]
        rec = pr[sid]
        name, kt, how = h if h else (sid, None, "no display name found in the kys, terminology or exe ZStrings")
        if kt and by_kys.get(kt["name"], [sid])[0] != sid:
            kt, how = None, how + f"; kys entry already linked to {by_kys[kt['name']][0]}"
        it = {"name": name, "id": sid}
        ex = {"name_source": how}
        if rec.get("c4"):
            ex["am_class_charid"] = rec["c4"]
        if kt:
            ex["kys_key"] = kt["key"]
            group_fields(kt["key"], it, ex)
            if kt["shortcut"]:
                it["shortcut"] = kt["shortcut"]
                if len(letter_members.get(kt["shortcut"], [])) > 1:
                    ex["shortcut_cycle"] = letter_members[kt["shortcut"]]
                    if "group" not in it:  # no shipped toolbar holds it: the tools sharing its default letter
                        it["group"] = letter_members[kt["shortcut"]][0]
                        ex["group_source"] = "tools sharing its default shortcut letter in the kys (Shift+letter cycle)"
        else:
            ex["not_in_kys"] = True
        it["invoke"] = {"ps_dom": f'app.currentTool = "{sid}"'}
        ps = opts_to_params(rec.get("opts"), term, labels)
        if ps:
            it["params"] = ps
        if rec.get("opterr"):
            ex["options_error"] = rec["opterr"]
        it["evidence"] = ("id verified 2026-10-04: AM select of the class under DialogModes.NO, then app.currentTool "
                          "set and read back on an RGB document; params = currentToolOptions read back (current, "
                          "i.e. last-used values, no ranges); shortcut = install Default Keyboard Shortcuts.kys; "
                          "group: see extra.group_source; enum params list every value of the AM enum type (terminology), "
                          "not only the ones the tool's options bar offers")
        if h is None:
            ex["unnamed"] = True
        it["extra"] = ex
        items.append(it)
    linked = set(by_kys)
    for t in kys_tools:  # kys tools no verified id links to: listed, with the ids that were tried
        if t["type"] != 1 or t["name"] in linked:
            continue
        it = {"name": t["name"], "id": "kys/" + t["name"],
              "error": "no id that app.currentTool accepts links to this kys tool; ids tried: " +
                       json.dumps(tried_for(t["name"]))[:400],
              "evidence": "listed in the install Default Keyboard Shortcuts.kys <tool> (type 1)",
              "extra": {"kys_key": t["key"]}}
        if t["shortcut"]:
            it["shortcut"] = t["shortcut"]
        group_fields(t["key"], it, it["extra"])
        items.append(it)
    main_keys = {t["key"] for t in kys_tools if t["key"]}
    for ts, tl in tasks.items():  # taskspace-only tools (Select and Mask, Content-Aware Fill, Neural Filters)
        for t in tl:
            if t["key"] in main_keys:
                continue
            it = {"name": t["name"], "id": f"taskspace/{ts}/{t['name']}", "group": ts,
                  "requires": f"the {ts} workspace",
                  "error": "taskspace tool: no id accepted by app.currentTool outside its workspace; ids tried: "
                           + json.dumps(tried_for(t["name"]))[:400],
                  "evidence": f"Default Keyboard Shortcuts.kys <taskspace name='{ts}'>",
                  "extra": {"kys_key": t["key"]}}
            if t["shortcut"]:
                it["shortcut"] = t["shortcut"]
            items.append(it)
    named = {norm(i["name"]) for i in items}
    for k, nm in sorted(tips.items()):  # toolbar tooltips naming a tool nothing above covers
        if nm.endswith("Tool") and norm(nm) not in named:
            items.append({"name": nm, "id": "tooltip/" + k,
                          "error": "named by a toolbar tooltip but no id was accepted by app.currentTool; ids tried: "
                                   + json.dumps(tried_for(nm))[:400],
                          "evidence": f"Photoshop.exe ZString $$$/Toolbar/ToolTips/{k}"})
            named.add(norm(nm))
    doc = {"app": "PS", "kind": "ps_tool", "app_version": VERSION,
           "source": "502 candidate tool ids (kys, Photoshop.exe strings, terminology) each verified by AM select + "
                     "app.currentTool set/read-back; names linked via terminology class labels, exe $$$/.../Title and "
                     "toolbar tooltip ZStrings and the install Default Keyboard Shortcuts.kys (shortcuts); groups from "
                     "Required/Workspaces toolbar customizations (tools/ps/harvest_tools.py)",
           "items": items}
    save(H / "ps_tool.json", doc)
    if dup:
        print("WARNING kys names linked by more than one id:", dup)
    print("ps_tool", len(items), "items,", sum(1 for i in items if "error" not in i), "verified")


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step == "selftest":  # pure helpers only, no Photoshop needed
        assert norm_sc("Alt+Shift+Ctrl+O") == "Ctrl+Alt+Shift+O" and norm_sc("Ctrl++") == "Ctrl++"
        assert clean_title("&Keyboard Shortcuts && Menus...") == "Keyboard Shortcuts & Menus..."
        assert tok_match(toks("marqueeSingleRowTool"), toks("Single Row Marquee Tool"))
        assert tok_match(toks("marqueeRectTool"), toks("Rectangular Marquee Tool"))
        assert not tok_match(toks("patchSelection"), toks("Patch Tool"))
        print("selftest ok")
        sys.exit(0)
    VERSION = app_version()
    if step in ("menudoc", "all"):
        dump_menu_with_doc()
    if step in ("menu", "all"):
        build_menu()
    if step in ("toolbar", "all"):
        decode_toolbars()
    if step in ("probe", "all"):
        probe_tools()
    if step in ("tools", "all"):
        build_tools()
