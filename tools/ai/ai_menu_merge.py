"""PGD / Illustrator: merge the two halves of harvest/ai/ai_menu.json into one item per command.

    python ai_menu_merge.py        work/ai/ai_menu.json.bak-kbsc + kbsc/align.json + kbsc/confirm.json -> harvest/ai/ai_menu.json

Before: walked menu items (real name / path, many with no executeMenuCommand id: id "path:...") and kys-only ids (id used
as name) were separate items, often the same command twice. Now:
  walked item + id   one item: name / path / shortcut from the live menu walk, id = the executeMenuCommand string,
                     invoke.ai_menu, extra.match (how the id was paired), extra.confirmed (executeMenuCommand(id) did the
                     same as the menu item itself, confirm_menu.py; or the earlier live verification)
  dialog-only id     kys id named by the Keyboard Shortcuts dialog (Export Text) but not on the walked menu bar
                     ('Other Text' / 'Other Object' ... keyboard-only commands, Custom View 1..10): name / shortcut from
                     the dialog, path = where the dialog lists it
  leftovers          walked items with no id and ids with no name stay, each with an "error" saying what is missing
Pairing sources, strongest first: confirmed by execution > earlier live verification > old matcher and dialog alignment
agree > old matcher (shortcut / table / idtext / words+path) > dialog alignment (kbsc_align.py) with shortcut or word
evidence > dialog alignment by order only (tight run between evidence pairs). A refuted id is never used.
"""
import json, sys
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_menus import read_kys, STAGE, WORK  # noqa: E402

KB = WORK / "kbsc"
BASE = WORK / "ai_menu.json.bak-kbsc"
OUT = (PGD / "harvest/ai/ai_menu.json")
EFFECT = (PGD / "harvest/ai/ai_effect.json")
OLD_HOW = {"shortcut": "the kys default shortcut equals the shortcut in the live menu label",
           "words+path": "the id's words equal the menu label plus its parent menu (one-to-one)",
           "table": "the binary that defines the id stores this label next to it",
           "idtext": "the id split into words equals the menu label",
           "verified": "executeMenuCommand(id) live test"}


def load(p, default=None):
    return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else default


def main():
    base = load(BASE)
    al = load(KB / "align.json")
    conf = load(KB / "confirm.json", {})
    ver = load(STAGE / "menu_verify.json", {})
    kys = {k["id"]: k for k in read_kys()}
    effect_ids = {(e.get("invoke") or {}).get("ai_menu") for e in load(EFFECT)["items"]}

    walked = [it for it in base["items"] if it.get("path")]
    kys_only = {it["id"]: it for it in base["items"] if not it.get("path")}
    dlg = {r["walked_path"]: r for r in al["menus"] if r.get("walked_path")}
    from confirm_menu import verdict_rec
    cv = {}  # (path, id) -> verdict, recomputed from the stored runs (the running job may use an older rule)
    for v in conf.values():
        if v.get("verdict") == "error":
            continue
        vv, why = verdict_rec(v)
        cv[(v["path"], v["id"])] = dict(v, verdict=vv, why=why)

    def verdict(p, i):
        v = cv.get((p, i))
        return (v["verdict"], v["why"]) if v else (None, None)

    used, out, stats = set(), [], {"merged": 0, "confirmed": 0, "refuted": 0, "disagree": 0, "by_dialog_title": 0}
    plan = []
    # an id whose run opened a dialog titled exactly like another walked item's label names that item (the
    # find_menu_ids.py criterion): 'make mesh' opened 'Create Gradient Mesh' while being tested for Pattern/Make
    norm = lambda s: s.replace("...", "").replace("…", "").strip().lower()  # noqa: E731
    by_label = {}
    for w in walked:
        by_label.setdefault(norm(w["name"]), []).append(w)
    title_hits = {}
    for v in conf.values():
        for t in set((v.get("a") or {}).get("dialogs") or []) - {"", "Adobe Illustrator"}:
            ws = by_label.get(norm(t), [])
            if len(ws) == 1 and ws[0]["path"] != v["path"]:
                title_hits.setdefault(ws[0]["path"], (v["id"], t))
    for w in walked:
        p = w["path"]
        old = None if w["id"].startswith("path:") else w["id"]
        meth = (w.get("extra") or {}).get("id_match")
        d = dlg.get(p)
        new = d.get("id") if d else None
        how = d.get("how") if d else None
        cands = []
        evd = (d.get("ev") or {}) if d else {}
        # partial: the id's own words mostly contradict the menu path ('Expand Image Tracing' at Live Paint/Expand)
        partial = 0 < evd.get("w_path", 0) < 0.5 and evd.get("sc") != 1 and not evd.get("table")
        for i in dict.fromkeys(x for x in (old, new) if x):
            vv, why = verdict(p, i)
            vo = ver.get(p)
            if vv == "refuted" or (vo and vo.get("ok") is False and vo.get("id") == i):
                stats["refuted"] += 1
                continue
            rank = 0 if vv == "confirmed" else 1 if (vo and vo.get("ok") and vo.get("id") == i) else \
                2 if (i == old and i == new) else 3 if i == old else \
                4 if how and how not in ("order", "some-words") and not partial else 9
            cands.append((rank, i, vv, why))
        th = title_hits.get(p)
        if th and th[0] not in [c[1] for c in cands]:
            cands.append((0, th[0], "confirmed", f"executeMenuCommand({th[0]!r}) opened the dialog '{th[1]}', this item's label"))
            stats["by_dialog_title"] += 1
        cands.sort()
        if old and new and old != new:
            stats["disagree"] += 1
        plan.append((w, cands, old, meth, d, new, how))

    # one id per item: lower rank wins; a contested id goes to the better-ranked item
    owner = {}
    for n, (w, cands, *_r) in enumerate(plan):
        for rank, i, vv, why in cands:
            if rank >= 9:
                continue
            if i not in owner or rank < owner[i][0]:
                owner[i] = (rank, n)
    for n, (w, cands, old, meth, d, new, how) in enumerate(plan):
        p = w["path"]
        it = {"name": w["name"], "path": p, "category": w.get("category", p.split("/")[0])}
        ex = {k: v for k, v in (w.get("extra") or {}).items() if k in ("win32_cmd", "enabled_without_document", "checked_at_harvest")}
        pick = next(((r, i, vv, why) for r, i, vv, why in cands if r < 9 and owner.get(i, (0, -1))[1] == n), None)
        th = title_hits.get(p)
        walk_ev = f"name/path/shortcut from the live menu walk (menu_walk.py, Win32 command {ex.get('win32_cmd')})"
        if d:
            ex["kbsc_name"] = d["name"]
            if d.get("shortcut"):
                ex["kbsc_shortcut"] = d["shortcut"]
        if pick:
            rank, i, vv, why = pick
            it["id"] = i
            it["invoke"] = {"ai_menu": i}
            m = []
            if old == i:
                m.append(f"{meth} ({OLD_HOW.get(meth, meth)})")
            if th and th[0] == i:
                m.append("dialog title (the id's executeMenuCommand opened a dialog named like this item)")
            if new == i:
                m.append(f"keyboard-shortcuts dialog alignment: {how}")
            ex["match"] = "; ".join(m) or "live test"
            vo = ver.get(p)
            if vv == "confirmed":
                ex["confirmed"] = True
                ex["confirm"] = (why if why.startswith("executeMenuCommand(") else
                                 f"executeMenuCommand(id) vs the menu item (WM_COMMAND {ex.get('win32_cmd')}): {why}") + " (confirm_menu.py)"
                stats["confirmed"] += 1
            elif vo and vo.get("ok") and vo.get("id") == i:
                ex["confirmed"] = True
                ex["confirm"] = vo.get("evidence", "executeMenuCommand(id) live test")
                stats["confirmed"] += 1
            else:
                ex["confirmed"] = False
                if vv:
                    ex["confirm"] = f"tested, {vv}: {why}"
            ev = walk_ev + "; id paired by " + ex["match"]
            if not ex["confirmed"]:
                ev += "; inferred, not confirmed by execution"
            it["evidence"] = ev
            if old and new and old != new:
                other = new if i == old else old
                ex["alternative_id"] = other
                if not ex["confirmed"]:
                    it["error"] = f"the two matchers disagree (old matcher {old!r}, dialog alignment {new!r}); not confirmed by execution"
            elif not ex["confirmed"] and new == i and old != i and how and ("order" == how or how.startswith("order")):
                it["error"] = "id inferred from the Keyboard Shortcuts dialog order only (no shortcut or word evidence); not confirmed by execution"
            used.add(i)
            if i in kys:
                ex["kys_context"] = "text editing" if kys[i]["context"] == 1 else "global"
            stats["merged"] += i in kys_only
        else:
            it["id"] = w["id"] if w["id"].startswith("path:") else "path:" + p
            it["evidence"] = walk_ev
            refuted = [c for c in (old, new) if c and verdict(p, c)[0] == "refuted"]
            it["error"] = ("no executeMenuCommand id could be paired with this menu item" +
                           (f" (candidate {refuted} refuted by execution)" if refuted else "") +
                           "; run it by its menu path / Win32 command number")
        if w.get("shortcut"):
            it["shortcut"] = w["shortcut"]
        it["extra"] = ex
        out.append(it)

    # ids the dialog names that are not on the walked menu bar (keyboard-only / hidden / state-dependent items)
    seen_ids = set(used)
    for r in al["menus"]:
        i = r.get("id")
        if not i or i in seen_ids or i in effect_ids or r["section"] == "Effect":
            continue
        how = r.get("how", "")
        if how == "order" or r.get("walked_path"):
            # pure order (adjacency) pairs are not trusted; the id a walked item did not take is not a second item
            continue
        sec = r["section"]
        path = (f"Edit/Keyboard Shortcuts.../Menu Commands/{r['path']}" if sec.startswith("Other ") else r["path"])
        it = {"name": r["name"], "id": i, "path": path, "category": sec, "invoke": {"ai_menu": i}}
        if r.get("shortcut"):
            it["shortcut"] = r["shortcut"]
        ex = {"match": f"keyboard-shortcuts dialog alignment: {how}", "confirmed": False,
              "kys_context": "text editing" if kys.get(i, {}).get("context") == 1 else "global",
              "path_from": "Keyboard Shortcuts dialog (Export Text) section" if sec.startswith("Other ") else r.get("path_from")}
        old_it = kys_only.get(i)
        if old_it and (old_it.get("extra") or {}).get("live_test"):
            ex["live_test"] = old_it["extra"]["live_test"]
        it["evidence"] = ("name, shortcut and place from Edit > Keyboard Shortcuts > Export Text (kbsc_export.py); id "
                          f"from Illustrator Defaults.kys, paired by {how} (kbsc_align.py); inferred, not confirmed by execution")
        if how.startswith("order") or how == "order":
            it["error"] = "id inferred from the Keyboard Shortcuts dialog order only; not confirmed by execution"
        it["extra"] = ex
        out.append(it)
        seen_ids.add(i)
        stats["merged"] += i in kys_only

    # kys ids still without a name
    nod = set(al["kys_not_in_dialog"])
    for i, old_it in kys_only.items():
        if i in seen_ids:
            continue
        it = dict(old_it)
        ex = dict(it.get("extra") or {})
        if i in nod:
            reason = "not listed in the Keyboard Shortcuts dialog of 30.2.1 (Export Text)"
        else:
            r = next((x for x in al["menus"] if x.get("id") == i), None)
            reason = (f"the Keyboard Shortcuts dialog alignment put it at {r['path']!r} ({r.get('how')}), which is an Effect item or "
                      "an item already paired with another id" if r else "no pairing")
        ex["kbsc"] = reason
        if "BKey" not in it.get("error", ""):
            it["error"] = "display name unknown: no menu item or dialog entry paired with this id; " + reason
        it["extra"] = ex
        out.append(it)

    doc = dict(base, items=out)
    doc["source"] = ("live menu walk of File/Edit/Object/Type/Select/View/Window/Help (menu_walk.py) + "
                     "Presets/en_US/Keyboard Shortcuts/Illustrator Defaults.kys ids, paired by tools/ai/ai_menus.py and by the "
                     "Keyboard Shortcuts dialog's Export Text (kbsc_export.py, kbsc_align.py), merged by ai_menu_merge.py; "
                     "pairs confirmed by executeMenuCommand(id) vs WM_COMMAND(menu item) on a test document (confirm_menu.py)")
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    walked_noid = sum(1 for x in out if x["id"].startswith("path:"))
    named_no_path = sum(1 for x in out if not x.get("path"))
    pairs = sum(1 for x in out if x.get("path") and not x["id"].startswith("path:"))
    print(f"items {len(out)}; walked items with id {pairs - sum(1 for x in out if (x.get('extra') or {}).get('path_from'))}, "
          f"dialog-only named ids {sum(1 for x in out if (x.get('extra') or {}).get('path_from'))}, "
          f"walked without id {walked_noid}, ids without name {named_no_path}; "
          f"confirmed {sum(1 for x in out if (x.get('extra') or {}).get('confirmed'))}; {stats}")


if __name__ == "__main__":
    main()
