"""PGD/CDR: build harvest/cdr/cdr_tool.json and cdr_menu.json from the live walks (no app needed).

    python harvest_tools.py

Inputs (work/cdr): tools_live.json (tools_walk.py), menu_live.json (menu_walk.py), enabled_probe.json
(enabled_probe.py, optional), the ACTIVE workspace's shortcut tables (drawui.workspace_root, falling back to
DrawUI.xml), harvest/cdr/cdr_effect.json (its GUIDs stay there: one kind per menu item), the cdrTools enum (typelib).
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from drawui import UI, workspace_root  # noqa: E402

PGD = Path(__file__).resolve().parents[2]
WORK, HARV = PGD / "work" / "cdr", PGD / "harvest" / "cdr"
MAIN_TABLE = "bc175625-191c-4b95-9053-756e5eee26fe"   # the main shortcut table; others are context tables
PICK_STATE = "5f85cce2-041c-11d4-b32e-00a0c9e8a837"
VK = {"PRIOR": "PageUp", "NEXT": "PageDown", "BACK": "Backspace", "RETURN": "Enter", "ESCAPE": "Esc", "ADD": "Num+",
      "SUBTRACT": "Num-", "MULTIPLY": "Num*", "DIVIDE": "Num/", "DELETE": "Delete", "INSERT": "Insert"}
SKIP_TOP = {"Effects", "Debug"}   # Effects -> cdr_effect; Debug = hidden developer menu (visible only when
#                                   WAppDataSource.EnableDebugMenu), every caption empty


def clean(c):
    return (c or "").replace("&&", "\0").replace("&", "").replace("\0", "&").replace("...", "").strip()


def fmt_key(k):
    mods = [m.capitalize() for m in ("ctrl", "alt", "shift") if k.get(m) == "true"]
    t = (k.text or "").strip()
    if t.startswith("VK_"):
        t = t[3:]
        t = VK.get(t, t.replace("NUMPAD", "Num").capitalize() if t.startswith("NUMPAD") else t.title()
                   if len(t) > 3 else t)
    elif len(t) == 1:
        t = t.upper()
    return "+".join(mods + ([t] if t else []))


def shortcuts():
    """guid -> {"main": [..], "other": [{table, keys}]}; active workspace first, DrawUI.xml for anything missing."""
    out, src = {}, None
    for root, name in ((workspace_root(), "workspace _default.cdws"), (UI().root, "DrawUI.xml")):
        if root is None or root.find("shortcutKeyTables") is None:
            continue
        src = src or name
        for t in root.find("shortcutKeyTables").findall("table"):
            tid = t.get("tableID")
            for s in t.findall("keySequence"):
                g = s.get("itemRef")
                if g in out and out[g].get("src") != name:
                    continue   # the active workspace already defined this item
                d = out.setdefault(g, {"src": name, "main": [], "other": []})
                k = ", ".join(fmt_key(k) for k in s.findall("key"))
                if not k:
                    continue   # empty <key/> entries (no key, no modifier)
                if tid == MAIN_TABLE:
                    d["main"].append(k)
                else:
                    d["other"].append({"table": tid, "keys": k, **({"component": t.get("component")}
                                                                    if t.get("component") else {})})
    return out


def enum_names():
    t = json.loads((WORK / "tlb" / "VGCoreAuto.json").read_text(encoding="utf-8"))["types"]
    return {m["value"]: m["name"] for x in t if x["name"] == "cdrTools" for m in x["values"]}


def requires(en):
    """enabled_probe states -> 'open document' | 'selection' | 'bitmap selection' (only what the app showed)."""
    if not en:
        return None
    if en.get("doc") is True and en.get("no_doc") is False:
        return "open document"
    if en.get("doc") is False and en.get("rect") is True and en.get("bitmap") is True:
        return "selection"
    if en.get("doc") is False and en.get("rect") is True and en.get("bitmap") is False:
        return "vector object selection"
    if en.get("doc") is False and en.get("rect") is False and en.get("bitmap") is True:
        return "bitmap selection"
    return None


def build_tools(ui, ver, keys, enabled, menu_guids):
    tl = json.loads((WORK / "tools_live.json").read_text(encoding="utf-8"))
    caps, probe = tl["captions"], tl["probe"]
    probe_err = tl.get("probe_errors", {})
    v1 = tl.get("probe_v1", {})
    enums = enum_names()
    rows = {r["guid"]: r for r in tl["toolbox"]}
    order = [r["guid"] for r in tl["toolbox"]] + [t["guid"] for t in tl["all_tools"]]
    # Application.ActiveTool = v -> tool: the tool STATE it lands in (ActiveToolStateGuid) equals the state that
    # tool's own InvokeItem produced. A state shared by several items (Pick / Freehand Pick, Artistic Media modes,
    # Callout variants) is resolved by the toolbox data source when it agrees, else listed on every sharer.
    # Values that land back on the Pick state did nothing (cdrToolPick itself excepted).
    owners = {}
    for g in order:
        p = probe.get(g) or {}
        s = p.get("state_guid")
        if s and not p.get("activated") and s.lower() == PICK_STATE:
            continue   # never left the Pick state (print-preview tools): owns nothing
        if s and g not in owners.get(s.lower(), []):
            owners.setdefault(s.lower(), []).append(g)
    hits = [(nm, r) for nm, r in tl.get("enum_probe", {}).items()] + \
           [(None, r) for r in tl.get("readback_probe", {}).values()]
    enum_to = {}
    for nm, r in hits:
        s = (r.get("state_guid") or "").lower()
        if "error" in r or not s or (s == PICK_STATE and nm != "cdrToolPick"):
            continue
        cands = owners.get(s, [])
        agree = [g for g in cands if g.lower() == (r.get("ds_active_tool") or "").lower()]
        for g in cands:
            enum_to.setdefault(g, []).append((nm, r, bool(agree and g in agree) or len(cands) == 1,
                                              [c for c in cands if c != g]))
    pick = next(r["guid"] for r in tl["toolbox"] if r["caption"] == "Pick" and r["type"] == "groupedRadioButton")
    items = []

    def group_of(r):
        p = rows.get(r.get("parent"))
        if not p:
            return None
        fb = ui.bars.get(p.get("flyoutBarRef"))
        nm = fb.get("nonLocalizableName") if fb is not None else None
        return clean(p["caption"]) or nm

    def add(g, name, group, in_toolbox, row):
        if g in menu_guids:
            return
        it = {"name": name, "id": g, "path": "/".join(x for x in ("Toolbox" if in_toolbox else "Other tools",
                                                                   group, name) if x)}
        if group:
            it["category"] = group
        sc = keys.get(g)
        if sc and sc["main"]:
            it["shortcut"] = " | ".join(sc["main"])
        inv = {"cdr_guid": g}
        ex = {"item_type": (ui.items[g].get("type") if g in ui.items else row.get("type")),
              "in_live_toolbox": in_toolbox}
        p = probe.get(g)
        evid = ["caption: live Automation.GetCaptionText"]
        evid.append("place: live Automation toolbox walk" if in_toolbox else
                    "found in DrawUI.xml/workspace (ActiveTool-bound groupedRadioButton), not on the live toolbox")
        if sc:
            evid.append("shortcut: " + sc["src"] + " shortcut tables")
            if sc["other"]:
                ex["context_shortcuts"] = sc["other"]
        if p and "error" not in p:
            ex["activation_probe"] = {k: p[k] for k in ("method", "active_tool", "state_guid", "ds_active_tool")
                                      if k in p}
            at = p.get("active_tool")
            ex["com_active_tool_readback"] = at
            if at in enums:
                ex["com_active_tool_readback_enum"] = enums[at]
            if p.get("activated"):
                evid.append(f"activated live with {p['method']}: AppOrViewDataSource.ActiveTool read back this GUID")
            elif p.get("ds_active_tool") and p.get("state_guid") != PICK_STATE and \
                    p["ds_active_tool"] == p.get("state_guid"):
                evid.append(f"activated live with {p['method']}: tool state changed to {p['state_guid']} "
                            "(the data source reports the state GUID, not this item GUID)")
            elif p.get("ds_active_tool") and p["ds_active_tool"] != g and p["ds_active_tool"] in rows \
                    and p.get("state_guid") != PICK_STATE:
                host = clean(rows[p["ds_active_tool"]]["caption"])
                ex["activates_tool"] = {"guid": p["ds_active_tool"], "name": host}
                evid.append(f"activating it switches to the '{host}' tool (data source read-back)")
            elif "WDSSelectedFromList" in (ui.items[g].get("currentActiveOfGroup") or ""):
                it["path"] = "Print Preview/Toolbox/" + name
                it["category"] = "Print Preview"
                it["error"] = ("Print Preview window tool (DrawUI.xml bar 16b90a40 in the frame whose dataContext is "
                               "PrintDataSource.PrintPreviewDataContext, bound to WDSSelectedFromList.ActiveTool): "
                               "InvokeItem / ActiveToolStateGuid left the drawing window on Pick; not probed in "
                               "Print Preview")
            else:
                it["error"] = ("activation not proven: InvokeItem and ActiveToolStateGuid left the drawing window on "
                               "the Pick tool (bars: " + ", ".join(tl_bars.get(g, [])) + ")")
            if ex.get("activates_tool") and not in_toolbox:
                it["category"] = ex["activates_tool"]["name"]
                it["path"] = f"Property Bar/{it['category']}/{name}"
        elif g in probe_err or (p and "error" in p):
            e = (p or probe_err[g]).get("error")
            it["error"] = "activation probe hung (" + str(e)[:120] + ")"
            if g in v1:
                ex["activation_probe_first_run"] = {k: v1[g][k] for k in ("method", "active_tool", "state_guid")
                                                    if k in v1[g]}
        elif row.get("type") == "button":
            evid.append("command button (not a tool mode): runs with Automation.InvokeItem")
        hits = enum_to.get(g, [])
        if hits:
            ex["active_tool_values"] = [
                {"value": r["value"], "enum": n or "(not a cdrTools member)", "readback": r["active_tool"],
                 "state_guid": r["state_guid"], "toolbox_shows": r.get("ds_active_tool"),
                 **({"shared_with": [clean(caps.get(c) or rows.get(c, {}).get("caption")) for c in sh]} if sh else {})}
                for n, r, ok, sh in hits]
            best = [h for h in hits if h[2] and (h[1]["state_guid"].lower() != PICK_STATE or g == pick)] or \
                ([hits[0]] if g == pick else [])
            if best:
                n, r = best[0][0], best[0][1]
                inv["cdr_com"] = f"Application.ActiveTool = {r['value']}" + (f"  ({n})" if n else
                                                                            "  (value outside the cdrTools enum)")
                evid.append(f"Application.ActiveTool = {r['value']} put the app in this tool's state "
                            f"(ActiveToolStateGuid {r['state_guid']})")
            if any(h[1]["state_guid"].lower() == PICK_STATE for h in hits):
                ex["note"] =("Pick and Freehand Pick share tool state 5f85cce2-...; after ActiveTool = 1 the toolbox "
                              "showed whichever Pick-flyout member was used last (read back: Freehand Pick)")
        it["invoke"] = inv
        rq = requires(enabled.get(g))
        if rq:
            it["requires"] = rq
            ex["enabled"] = enabled[g]
        if row.get("options"):
            ex["options"] = row["options"]
        it["evidence"] = "; ".join(evid)
        it["extra"] = ex
        items.append(it)

    tl_bars = {t["guid"]: t["bars"] for t in tl["all_tools"]}
    seen = set()
    for r in tl["toolbox"]:
        if r["type"] in ("toolFlyout", "flyout"):
            continue
        parent = rows.get(r.get("parent"))
        if parent and parent["type"] == "groupedRadioButton":
            parent.setdefault("options", []).append(clean(r["caption"]))   # Pen Pressure etc. = tool options
            continue
    for r in tl["toolbox"]:
        parent = rows.get(r.get("parent"))
        if r["type"] in ("toolFlyout", "flyout") or (parent and parent["type"] == "groupedRadioButton"):
            continue
        if r["type"] not in ("groupedRadioButton", "button", "checkButton"):
            continue   # placeholders (Outline Width Presets)
        seen.add(r["guid"])
        grp = group_of(r)
        if r["type"] != "groupedRadioButton" and parent:
            grp = clean(parent["caption"]) or grp
        add(r["guid"], clean(r["caption"]), grp, True, r)
    for t in tl["all_tools"]:
        g = t["guid"]
        if g in seen:
            continue
        bars = [b for b in t["bars"] if not b.startswith("Touch Workspace")]
        add(g, clean(caps.get(g)) or g, bars[0] if bars else None, False, {"type": "groupedRadioButton"})
        items[-1].setdefault("extra", {})["listed_on_bars"] = t["bars"]
    return {"app": "CDR", "kind": "cdr_tool", "app_version": ver,
            "source": "live FrameWork.Automation toolbox walk + ActiveTool-bound items of DrawUI.xml/active workspace, "
                      "captions via GetCaptionText, activation probe (InvokeItem / ActiveTool / ActiveToolStateGuid "
                      "read back through AppOrViewDataSource), IsEnabled probe, workspace shortcut tables "
                      "(PGD/tools/cdr/tools_walk.py, enabled_probe.py, harvest_tools.py)",
            "items": items}


def build_menu(ui, ver, keys, enabled, effect_guids):
    rows = json.loads((WORK / "menu_live.json").read_text(encoding="utf-8"))
    vis = json.loads((WORK / "enabled_probe.json").read_text(encoding="utf-8")).get("visible_bind", {}) \
        if (WORK / "enabled_probe.json").exists() else {}
    items, by = [], {}
    for r in rows:
        top = r["path"].split("/")[0]
        g = r.get("guid")
        if top in SKIP_TOP or not g or not clean(r.get("caption")):
            continue
        if r["bar"] == "menubar":   # menu_walk.py types every menu-bar entry "flyout"; the XML knows better
            r = dict(r, type=(ui.items[g].get("type") if g in ui.items else r.get("type")))
        if r.get("type") in (None, "placeHolder", "flyout"):
            continue   # separators, dynamic lists (recent files, workspaces, window list, palettes), submenu titles
            # (dynamicCategory is a customization category GUID, NOT a dynamic list: Fit Objects to Path carries one)
        if g.lower() in effect_guids:
            continue   # already in cdr_effect (one kind per menu item)
        if g in by:
            by[g].setdefault("extra", {}).setdefault("also_at", []).append(r["path"])
            continue
        x = ui.items.get(g)
        a = dict(x.attrib) if x is not None else {}
        it = {"name": clean(r["caption"]), "id": g, "path": r["path"], "category": top}
        sc = keys.get(g)
        if sc and sc["main"]:
            it["shortcut"] = " | ".join(sc["main"])
        it["invoke"] = {"cdr_guid": g}
        ex = {"item_type": r.get("type")}
        if (r.get("caption") or "").rstrip().endswith("..."):
            ex["opens_dialog"] = True
        for k in ("onInvoke", "check", "visible", "enable", "dynamicCategory"):
            if a.get(k):
                ex[k] = a[k]
        if sc and sc["other"]:
            ex["context_shortcuts"] = sc["other"]
        if g in vis:
            ex["visible_now"] = vis[g]
        evid = ["path + caption: live Automation menu walk (GetItem / GetCaptionText)",
                "bindings: DrawUI.xml itemData"]
        if sc:
            evid.append("shortcut: " + sc["src"])
        rq = requires(enabled.get(g))
        if g in enabled:
            ex["enabled"] = enabled[g]
            evid.append("enabled states: live Automation.IsEnabled (no doc / doc / rectangle / bitmap selected)")
        if rq:
            it["requires"] = rq
        it["evidence"] = "; ".join(evid)
        it["extra"] = ex
        by[g] = it
        items.append(it)
    return {"app": "CDR", "kind": "cdr_menu", "app_version": ver,
            "source": "live FrameWork.Automation walk of the main menu bar (menu_walk.py -> menu_live.json) minus "
                      "Effects (cdr_effect), the hidden Debug menu, separators and dynamic lists; DrawUI.xml bindings; "
                      "active-workspace shortcut tables; IsEnabled probe (enabled_probe.py); harvest_tools.py",
            "items": items}


def main():
    ui = UI()
    ver = json.loads((WORK / "app_version.json").read_text(encoding="utf-8"))["version"]
    keys = shortcuts()
    ep = WORK / "enabled_probe.json"
    enabled = json.loads(ep.read_text(encoding="utf-8")).get("enabled", {}) if ep.exists() else {}
    eff = json.loads((HARV / "cdr_effect.json").read_text(encoding="utf-8"))["items"]
    effect_guids = {i["id"].lower() for i in eff} | {(i.get("invoke") or {}).get("cdr_guid", "").lower() for i in eff}
    menu = build_menu(ui, ver, keys, enabled, {g for g in effect_guids if g})
    menu_guids = {i["id"] for i in menu["items"]}
    tool = build_tools(ui, ver, keys, enabled, menu_guids)
    for doc in (tool, menu):
        p = HARV / f"{doc['kind']}.json"
        p.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
        print(len(doc["items"]), "->", p)
    if (WORK / "audit_live.json").exists():   # re-apply the independent audit's live verdicts (apply_audit.py)
        import apply_audit
        apply_audit.main()


if __name__ == "__main__":
    main()
