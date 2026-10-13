"""PGD / Illustrator: build harvest/ai/ai_menu.json (every menu-bar command except Effect).

    python ai_menus.py pool     scan Illustrator.exe + every .aip for the kys command ids -> work/ai/tools_stage/pool.json
    python ai_menus.py build    menu walks + kys + pool (+ verify results) -> harvest/ai/ai_menu.json

Sources (all read from the installed app):
  work/ai/menu_<Top>.json   live menu walk by menu_walk.py (display names, paths, shortcuts, Win32 command numbers)
  Illustrator Defaults.kys  every executeMenuCommand id under /Menus { } with its default shortcut
  pool.json                 for each kys id: the strings next to it in the binary that defines it (the command
                            table stores "<internal name>\\0<id>" pairs, e.g. "Close All" / "closeAll")
Matching a walked item to a kys id, strongest first, one-to-one:
  shortcut   the decoded kys shortcut equals the shortcut shown in the menu label, and both are unique
  table      the internal name stored next to the id in the binary equals the menu label (normalised)
  idtext     the id itself, split into words, equals the menu label (normalised)
  verified   work/ai/tools_stage/menu_verify.json: executeMenuCommand(id) opened the dialog the label names
"""
import json, re, sys
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

ROOT = Path("C:/Program Files/Adobe/Adobe Illustrator 2026")
KYS = ROOT / "Presets/en_US/Keyboard Shortcuts/Illustrator Defaults.kys"
WORK = (PGD / "work/ai")
STAGE = WORK / "tools_stage"
OUT = (PGD / "harvest/ai/ai_menu.json")
TOPS = ["File", "Edit", "Object", "Type", "Select", "View", "Window", "Help"]
# whitespace-tolerant: 'ruler' and 'zoomin2' carry trailing tabs / extra spaces, and an exact \t/\n pattern skipped
# them (audit 2026-10-04: 610 of 612 /Menus ids had been parsed)
KYS_RE = re.compile(r"^[ \t]*/(.+?) \{\s*/Context (\d+)\s*/Modifiers (\d+)\s*/Represent (\d+)\s*/Key (\d+)\s*\}", re.M)


def key_name(code):
    if 14 <= code <= 25:
        return f"F{code - 13}"
    return {9: "Tab", 32: "Space"}.get(code, chr(code).upper() if code else "")


def kys_shortcut(mods, rep):
    """kys Modifiers bits (verified against the menu labels): 32 Shift, 64 Ctrl, 128 Alt."""
    k = key_name(rep)
    if not k:
        return ""
    m = [n for b, n in ((128, "Alt"), (32, "Shift"), (64, "Ctrl")) if mods & b]
    return "+".join(m + [k])


def sc_norm(s):
    """'Shift+Ctrl+N' / 'Ctrl+Shift+N' -> 'Ctrl+Shift+N' (order-free compare)."""
    if not s:
        return ""
    parts = s.split("+") if not s.endswith("++") else s[:-2].split("+") + ["+"]
    mods = sorted(p for p in parts[:-1] if p)
    return "+".join(mods + [parts[-1].upper()])


def read_kys(section="Menus"):
    t = KYS.read_text(encoding="latin-1")
    menus, tools = t.split("/Tools {")
    out = []
    for m in KYS_RE.findall(menus if section == "Menus" else tools):
        i, ctx, mods, rep, key = m[0].replace("\\ ", " "), int(m[1]), int(m[2]), int(m[3]), int(m[4])
        out.append({"id": i, "context": ctx, "mods": mods, "rep": rep, "key": key,
                    "shortcut": kys_shortcut(mods, rep) if key else ""})
    return out


STOP = {"adobe", "ai", "menu", "item", "the", "a", "on", "to", "of", "and", "plugin", "plug", "in", "palette", "panel",
        "dialog", "shortcut", "command", "window", "object", "edit", "view", "select", "type", "file", "help"}


def norm(s):
    s = s.replace("&", "").replace("...", "").replace("\u2026", "").lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def id_words(i):
    s = re.sub(r"^(Adobe ?|ai_|~)", "", i)
    s = re.sub(r"\d+$", "", s)
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    return norm(s)


# ---------------------------------------------------------------- pool
def pool():
    ids = {k["id"] for k in read_kys()} | {k["id"] for k in read_kys("Tools")}
    bins = [ROOT / "Support Files/Contents/Windows/Illustrator.exe"] + sorted(ROOT.rglob("*.aip"))
    res = {}
    for b in bins:
        data = b.read_bytes()
        strs = [(m.start(), m.group().decode("latin-1")) for m in re.finditer(rb"[\x20-\x7e]{2,}", data)]
        for n, (off, s) in enumerate(strs):
            if s in ids:
                prev = [x[1] for x in strs[max(0, n - 3):n] if off - x[0] < 160]
                nxt = [x[1] for x in strs[n + 1:n + 4] if x[0] - off < 160]
                res.setdefault(s, []).append({"bin": b.name, "prev": prev, "next": nxt})
    STAGE.mkdir(parents=True, exist_ok=True)
    (STAGE / "pool.json").write_text(json.dumps(res, indent=0), encoding="utf-8")
    print(f"{len(res)}/{len(ids)} ids found in {len(bins)} binaries")


# ---------------------------------------------------------------- walked menus
DYNAMIC_PARENTS = {"Open Recent Files"}  # recent-file list: dynamic


def flatten(tree, path, top, out):
    for n in tree:
        if "name" not in n or not n["name"].strip():
            continue
        p = f"{path}/{n['name']}"
        kids = n.get("children")
        parent = path.split("/")[-1]
        if parent in DYNAMIC_PARENTS:
            continue
        if top == "Window" and parent == "Workspace" and not n["name"].endswith("...") and n["name"] != "Reset":
            continue  # saved workspace names: dynamic
        segs = p.split("/")
        if top == "Window" and len(segs) > 2 and segs[1].endswith("Libraries") \
                and not n["name"].endswith("...") and not kids:
            continue  # library files from Presets: they belong to ai_preset
        if top == "File" and parent == "Scripts" and not n["name"].endswith("..."):
            continue  # scripts from Presets/Scripts: preset content
        if kids:
            flatten(kids, p, top, out)
            continue
        name = n["name"]
        if top == "Help" and name.startswith("Sign Out"):
            name = "Sign Out..."  # the walked label carries the signed-in account; not harvested
        out.append({"name": name, "path": f"{path}/{name}", "shortcut": n.get("shortcut", ""), "cmd": n["cmd_id"],
                    "enabled_no_doc": n["enabled"], "checked": n["checked"]})


def walked(tops):
    items = []
    for t in tops:
        f = WORK / f"menu_{t}.json"
        flatten(json.loads(f.read_text(encoding="utf-8")), t, t, items)
    return items


# ---------------------------------------------------------------- build
def build():
    kys = read_kys()
    pl = json.loads((STAGE / "pool.json").read_text(encoding="utf-8")) if (STAGE / "pool.json").exists() else {}
    ver = json.loads((STAGE / "menu_verify.json").read_text(encoding="utf-8")) if (STAGE / "menu_verify.json").exists() else {}
    items = walked(TOPS)
    eff = walked(["Effect"])
    allw = items + eff
    match = {}  # walked index -> (kys id, method)
    used = set()

    # 1 shortcut
    by_sc = {}
    for i, w in enumerate(allw):
        if w["shortcut"]:
            by_sc.setdefault(sc_norm(w["shortcut"]), []).append(i)
    k_sc, k_sc_all = {}, {}
    for k in kys:
        if k["shortcut"]:
            k_sc_all.setdefault(sc_norm(k["shortcut"]), []).append(k["id"])
    for k in kys:
        if k["shortcut"] and k["context"] == 0:
            k_sc.setdefault(sc_norm(k["shortcut"]), []).append(k["id"])
    kctx = {k["id"]: k["context"] for k in kys}
    for s, ks in k_sc.items():
        ws = by_sc.get(s, [])
        # a text-editing id (context 1) on the same keys belongs to the Type > Insert ... items: the one global id
        # goes to an item outside them only (audit 2026-10-04: Thin Space had been given highlightFont2, whose
        # keys it shares with ~thinSpace)
        others = [k for k in k_sc_all.get(s, []) if k not in ks]
        if len(ks) == 1 and len(ws) == 1 and all(kctx[k] == 1 for k in others) and \
                not (others and allw[ws[0]]["path"].startswith("Type/Insert")):
            match[ws[0]] = (ks[0], "shortcut")
            used.add(ks[0])
    for s, ks in k_sc_all.items():  # same shortcut in two contexts (text vs global): pair by shared words
        ws = [i for i in by_sc.get(s, []) if i not in match]
        ks = [k for k in ks if k not in used]
        if len(ks) > 1 and len(ks) == len(ws):
            for kid in ks:
                best = [i for i in ws if i not in match and set(re.findall(r"[a-z]+", id_words(kid))) and
                        (id_words(kid) in norm(allw[i]["name"]) or norm(allw[i]["name"]) in id_words(kid))]
                if len(best) == 1:
                    match[best[0]] = (kid, "shortcut")
                    used.add(kid)

    def toks(x):
        x = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", re.sub(r"([a-z])([A-Z])", r"\1 \2", x))
        x = re.sub(r"(?<![0-9])-(?=[0-9])", "negative", x)
        w = set(re.findall(r"[a-z0-9]+", x.lower())) - STOP
        return {re.sub(r"(ing|es|s|e)$", "", t) if len(t) > 4 else t for t in w}

    def explained(kid, i):
        """every word of the id is explained by the menu path, and one by the label itself. Checked when a
        non-shortcut match is made, so a wrong table pair cannot take the item from the right id (audit
        2026-10-04: highlightFont2 took View/Proof Colors in the table pass and proofColors lost it)."""
        segs = allw[i]["path"].split("/")
        tid = toks(re.sub(r"\d+$", "", kid.lstrip("~")))
        return bool(tid) and tid <= toks(" ".join(segs)) and bool(tid & toks(segs[-1]))

    # 2 internal name stored next to the id, 3 id words
    def cand_names(kid):
        names = set()
        for occ in pl.get(kid, []):
            for s in occ["prev"][-1:]:
                if not s.startswith("$$$/") and len(s) < 80:
                    names.add(norm(s))
        return names

    for method, fn in (("table", cand_names), ("idtext", lambda kid: {id_words(kid)})):
        idx = {}
        for k in kys:
            if k["id"] in used:
                continue
            for n in fn(k["id"]):
                if n:
                    idx.setdefault(n, set()).add(k["id"])
        wn = {}
        for i, w in enumerate(allw):
            if i not in match:
                wn.setdefault(norm(w["name"]), []).append(i)
        for n, ks in idx.items():
            ws = wn.get(n, [])
            ks = [k for k in ks if k not in used]
            if len(ks) == 1 and len(ws) == 1 and ws[0] not in match and explained(ks[0], ws[0]):
                match[ws[0]] = (ks[0], method)
                used.add(ks[0])

    # 4 same words, allowing the parent menu's words as context (e.g. "AISlice Make Slice" = Object/Slice/Make)
    cands = {}
    for k in kys:
        if k["id"] in used:
            continue
        tid = toks(re.sub(r"\d+$", "", k["id"]))
        if not tid:
            continue
        for i, w in enumerate(allw):
            if i in match:
                continue
            segs = w["path"].split("/")
            tn, tc = toks(segs[-1]), toks(" ".join(segs[:-1]))
            if tn and tn <= tid and tid <= tn | tc:
                cands.setdefault(k["id"], []).append(i)
    rev = {}
    for kid, ws in cands.items():
        for i in ws:
            rev.setdefault(i, []).append(kid)
    for kid, ws in cands.items():
        if len(ws) == 1 and len(rev[ws[0]]) == 1:
            match[ws[0]] = (kid, "words+path")
            used.add(kid)

    # every word of the id must be explained by the menu path, or a non-shortcut match is dropped
    # (the string-table neighbour is sometimes the previous entry's name: Assign Profile / cut2)
    for i in list(match):
        kid, meth = match[i]
        if meth == "shortcut":
            continue
        segs = allw[i]["path"].split("/")
        tid = toks(re.sub(r"\d+$", "", kid.lstrip("~")))
        if not tid or not tid <= toks(" ".join(segs)) or not tid & toks(segs[-1]):
            del match[i]
            used.discard(kid)

    # verified overrides (executeMenuCommand opened the dialog the label names); a refuted id is dropped
    for path, v in ver.items():
        if v.get("ok") is False:
            for i, w in enumerate(allw):
                if w["path"] == path and i in match and match[i][0] == v["id"]:
                    used.discard(match[i][0])
                    del match[i]
        if v.get("ok"):
            for i, w in enumerate(allw):
                if w["path"] == path:
                    if i in match and match[i][0] != v["id"]:
                        used.discard(match[i][0])
                    match[i] = (v["id"], "verified")
                    used.add(v["id"])

    kmap = {k["id"]: k for k in kys}
    effect_ids = {match[i][0] for i in range(len(items), len(allw)) if i in match}
    try:
        for it in json.loads((PGD / "harvest/ai/ai_effect.json").read_text(encoding="utf-8"))["items"]:
            if (it.get("invoke") or {}).get("ai_menu"):
                effect_ids.add(it["invoke"]["ai_menu"])
    except FileNotFoundError:
        pass

    out, seen = [], set()
    how = {"shortcut": "the kys default shortcut of this id equals the shortcut in the live menu label (unique, or split by context and matching words)",
           "words+path": "the words of the id equal the words of the menu label plus its parent menu (one-to-one)",
           "table": "the binary that defines the id stores this label next to it (command table pair)",
           "idtext": "the id, split into words, equals the live menu label",
           "verified": "executeMenuCommand(id) opened the dialog this label names (live test)"}
    for i, w in enumerate(items):
        it = {"name": w["name"], "path": w["path"], "category": w["path"].split("/")[0]}
        if i in match:
            kid, meth = match[i]
            it["id"] = kid
            it["invoke"] = {"ai_menu": kid}
            v = ver.get(w["path"])
            ev = f"name/path/shortcut from the live menu walk (menu_walk.py, Win32 command {w['cmd']}); id matched: " + (
                f"executeMenuCommand(id) live test: {v['evidence']}" if meth == "verified" and v.get("evidence") else how[meth])
            if v and v.get("ok") and meth != "verified":
                ev += "; also verified live: " + v.get("evidence", "executeMenuCommand opened the matching dialog")
            it["evidence"] = ev
            seen.add(kid)
        else:
            it["id"] = "path:" + w["path"]
            it["evidence"] = f"name/path/shortcut from the live menu walk (menu_walk.py, Win32 command {w['cmd']})"
            it["error"] = "no executeMenuCommand id could be matched to this menu item (no unique shortcut, table or id-text match); run it by its menu path / Win32 command number"
            v = ver.get(w["path"])
            if v and v.get("ok") is False:
                it["error"] += f"; the shortcut-matched id {v['id']!r} was refuted live: {v.get('evidence', '')}"
        if w["shortcut"]:
            it["shortcut"] = w["shortcut"]
        it["extra"] = {"win32_cmd": w["cmd"], "enabled_without_document": w["enabled_no_doc"]}
        if i in match:
            it["extra"]["id_match"] = match[i][1]
        if w["checked"]:
            it["extra"]["checked_at_harvest"] = True
        out.append(it)

    # kys ids that matched no menu-bar item (keyboard-only / context / hidden commands). Only ids that ai_effect itself
    # invokes are left out; before the audit every 'Live ...' id and every Effect-paired id was dropped from both
    # files (Roughen3, ZigZag2, Live DropShadow2 ...). kys_live_tests.json (audit_live.py) says what executeMenuCommand
    # did with them.
    effect_file_ids = set()
    try:
        for e in json.loads((PGD / "harvest/ai/ai_effect.json").read_text(encoding="utf-8"))["items"]:
            effect_file_ids.add((e.get("invoke") or {}).get("ai_menu"))
    except FileNotFoundError:
        pass
    kt = json.loads((STAGE / "kys_live_tests.json").read_text(encoding="utf-8")) if (STAGE / "kys_live_tests.json").exists() else {}
    for k in kys:
        if k["id"] in seen or k["id"] in effect_file_ids:
            continue
        it = {"name": k["id"], "id": k["id"], "invoke": {"ai_menu": k["id"]},
              "evidence": "id from Illustrator Defaults.kys /Menus; not matched to any item of the walked menu bar",
              "error": "display name unknown: no menu-bar item matched this id (keyboard-only, context-menu or hidden command, or a label the matcher could not pair)",
              "extra": {"kys_context": "text editing" if k["context"] == 1 else "global"}}
        if k["id"] in effect_ids:
            it["extra"]["note"] = "the matcher paired this id with an Effect-menu item; ai_effect invokes that item with another id"
        t = kt.get(k["id"])
        if t:
            it["extra"]["live_test"] = t["summary"]
            if t.get("bkey"):
                it.pop("invoke")
                it["error"] = ("not a command in this version: executeMenuCommand(id) raised Error 1200 'BKey' "
                               "(an id the shortcut file still lists)")
        if k["shortcut"]:
            it["shortcut"] = k["shortcut"]
        inames = sorted({s for occ in pl.get(k["id"], []) for s in occ["prev"][-1:] if not s.startswith("$$$/") and len(s) < 80})
        if inames:
            it["extra"]["internal_name_candidates"] = inames
        out.append(it)

    ver_str = (WORK / "app_version.txt").read_text().strip() if (WORK / "app_version.txt").exists() else ""
    doc = {"app": "AI", "kind": "ai_menu", "app_version": ver_str,
           "source": "live menu walk of File/Edit/Object/Type/Select/View/Window/Help (menu_walk.py, MN_GETHMENU) "
                     "matched to Presets/en_US/Keyboard Shortcuts/Illustrator Defaults.kys ids by tools/ai/ai_menus.py",
           "items": out}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    from collections import Counter
    c = Counter(match[i][1] for i in range(len(items)) if i in match)
    print(f"walked commands {len(items)}, matched {sum(c.values())} {dict(c)}, unmatched kys ids "
          f"{len(out) - len(items)}, effect-matched {len(effect_ids)}")


if __name__ == "__main__":
    assert sc_norm("Shift+Ctrl+N") == sc_norm("Ctrl+Shift+N") == "Ctrl+Shift+N"
    assert kys_shortcut(96, 78) == "Shift+Ctrl+N" and kys_shortcut(64, 25) == "Ctrl+F12"
    assert id_words("closeAll2") == "closeall" and norm("Close All...") == "closeall"
    _m = KYS.read_text(encoding="latin-1").split("/Tools {")[0]  # parser must see every /<id> { block
    assert len(read_kys()) == len(re.findall(r"^[ \t]+/.+? \{[ \t]*$", _m, re.M)), "kys entries skipped"
    {"pool": pool, "build": build}[sys.argv[1]]()
