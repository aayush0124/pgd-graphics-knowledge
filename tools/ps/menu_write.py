"""Judge work/ps/menuinv/results.json and write invoke + extra.invoke_verified / invoke_how into harvest/ps/ps_menu.json.

    python menu_write.py review   # table of every tried command and the observation that would verify it
    python menu_write.py write    # back up ps_menu.json (work/ps/ps_menu.json.bak-invoke-<time>) and write

A try VERIFIES a route when (a) it ran without error and the scratch document / app changed in a way the command
should cause (DENY below lists the observed false positives), or (b) it opened a dialog whose window title names
the command (dismissed by window handle). Everything else is recorded with invoke_verified false.
"""
import json, re, shutil, sys, time
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).parent))
from menu_plan import PLAN, C  # noqa: E402

H = (PGD / "harvest/ps/ps_menu.json")
R = json.loads((PGD / "work/ps/menuinv/results.json").read_text(encoding="utf-8"))
TODAY = "2026-10-04"

DENY = {  # cid -> reason: the observed change is not what this command does (reviewed by hand)
    "2769": "the set wrote a history state named 'Layer Style', not 'Disable Smart Filters', and the snapshot does not read filterFXVisible",
    "133": "the first undoEvent stepped back one state, but a second undoEvent right after was refused ('Undo is not currently available'), so this route cannot be told apart from Edit > Undo",
    "1348": "disableLayerFX is 'Clear Effects': it removed an ENABLED drop shadow, while Clear Disabled Layer Styles removes only disabled effects",
}
NOTE = {k: "Layer bounds did not change because the test square is symmetric; the history state named by the command is the observation."
        for k in ("2208", "2209", "2210", "2211", "2212")}
NOTE.update({"1306": "Hide All Effects is a toggle; the document-level layerFXVisible property was set false.",
             "132": "Redo and Step Forward share this route (history state ordinal next) in a script.",
             "2982": "Find Layers brings the Layers panel forward with its search field active.",
             "5993": "post-run restored Standard Screen Mode.",
             "2860": "The observation is the Measurement Log panel opening (it opens on Record Measurements); the logged row itself was not read."})
# dialogs whose title is not the command name but is that command's own dialog (reviewed by hand)
ACCEPT = {"1137": "the File Info dialog is titled with the document's name",
          "1676": "Scripts > Browse opens the 'Load' file dialog for a script",
          "File/Import/Notes": "Import > Notes opens the 'Load' file dialog for a notes file",
          "6362": "Video Frames to Layers first opens an 'Open' file dialog for the video",
          "6340": "Relink to File opens a file picker titled 'Replace File'",
          "1103": "Layer Content Options on a Solid Color fill layer opens that layer's 'Color Picker (Solid Color)'",
          "1202": "Custom Pixel Aspect Ratio opens the 'Save Pixel Aspect Ratio' dialog",
          "7802": "Image > Variables > Define opens the 'Variables' dialog",
          "1029": "Define Brush Preset asks for the new preset's name in its 'Brush Name' dialog",
          "1038": "Define Pattern asks for the new pattern's name in its 'Pattern Name' dialog"}


def norm(s):
    s = s.lower().replace("&&", " and ").replace("&", " and ").replace("...", "")
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


def dialogs(ret):
    m = re.search(r"had to dismiss \[(.*?)\]; result", ret or "")
    if not m:
        return []
    return [x.strip().strip("'\"").split("|") for x in m.group(1).split("', '")]


def summarize(diff):
    out = []
    for k, v in diff.items():
        if k == "isDirty":
            continue
        if k == "hist":
            out.append("history states %s -> %s" % tuple(v))
            continue
        if k == "ck":
            continue
        if k == "clipboard":
            out.append("clipboard written")
            continue
        if k == "L":
            out.append("layers %d -> %d rows" % (len(v[0] or []), len(v[1] or [])))
            continue
        a, b = (json.dumps(x)[:70] if not isinstance(x, str) else x[:70] for x in v)
        out.append("%s: %s -> %s" % (k, a, b))
    return "; ".join(out)[:600]


def judge(cid, t, name):
    ret = str(t.get("ret", ""))
    diff = {k: v for k, v in (t.get("diff") or {}).items() if k not in ("isDirty",)}
    ck = diff.pop("ck", None)
    own_ck = bool(ck) and cid.lstrip("-").isdigit() and int(cid) in (ck.get("on", []) + ck.get("off", []))
    dl = dialogs(ret)
    if dl:
        titles = [d[1] if len(d) > 1 else "" for d in dl]
        n = norm(name)
        hit = [x for x in titles if x and (norm(x) == n or n in norm(x) or norm(x) in n)]
        if hit:
            return True, "opened its dialog '%s' (cancelled by window handle)" % hit[0]
        if cid in ACCEPT and titles and titles[0]:
            return True, "opened the dialog '%s' (cancelled by window handle); %s" % (titles[0], ACCEPT[cid])
        return False, "opened a dialog titled %s that does not name the command" % titles
    if ret.startswith(("ERR", "PSERR")) or "fatal" in t:
        return False, (ret or t.get("fatal", ""))[:300]
    if not diff and not own_ck:
        return False, "ran without error but no observable change"
    if cid in DENY:
        return False, DENY[cid] + " (observed: %s)" % summarize(diff)
    s = summarize(diff)
    if own_ck:
        s = (s + "; " if s else "") + "its own menu check mark flipped"
    if t.get("restore_diff") is not None:
        rd = {k: v for k, v in t["restore_diff"].items() if k not in ("isDirty", "ck")}
        s += "; running it again restored the state" if not rd else "; second run did not fully restore (%s)" % summarize(rd)
    if t.get("check"):
        s += "; check: " + str(t["check"])[:120]
    return True, s


def best(cid, name):
    rec = R.get(cid)
    if not rec:
        return None, None, []
    tried = []
    for t in rec["tries"]:
        ok, why = judge(cid, t, name)
        tried.append((t, ok, why))
        if ok:
            return t, why, tried
    return None, None, tried


def cand_by_how(cid, how):
    for c in PLAN[cid]["cands"]:
        if c["how"] == how:
            return c
    return None


def invoke_of(c, item):
    if c["kind"] == "ps_dom":
        inv = {"ps_dom": c["run"]}
    else:
        inv = {c["kind"]: c["key"]}
    if (item.get("invoke") or {}).get("file"):
        inv = dict(item["invoke"], **inv)
    return inv


def review():
    for it in json.loads(H.read_text(encoding="utf-8"))["items"]:
        cid = it["id"]
        p = PLAN.get(cid)
        if not p or p["skip"] or cid not in R:
            continue
        t, why, tried = best(cid, it["name"])
        tag = "OK " if t else "-- "
        print(tag, cid[:22].ljust(22), it["path"][:44].ljust(44), (t["how"] if t else (tried[-1][0]["how"] if tried else ""))[:70].ljust(70),
              (why or (tried[-1][2] if tried else ""))[:230])


def write():
    d = json.loads(H.read_text(encoding="utf-8"))
    bak = (PGD / ("work/ps/ps_menu.json.bak-invoke-" + time.strftime("%H%M%S")))
    shutil.copy2(H, bak)
    counts = {"verified": 0, "unverified": 0, "none": 0}
    for it in d["items"]:
        cid, e = it["id"], it.setdefault("extra", {})
        p = PLAN[cid]
        for k in ("invoke_verified", "invoke_how", "invoke_descriptor_js", "invoke_tried", "invoke_events_seen"):
            e.pop(k, None)
        t, why, tried = best(cid, it["name"])
        if t:
            c = cand_by_how(cid, t["how"])
            it["invoke"] = invoke_of(c, it)
            e["invoke_verified"] = True
            e["invoke_how"] = "%s on a scratch %s document (fixture state '%s'%s), %s: %s%s" % (
                t["how"], "400x300 RGB", t.get("state"), ", setup: " + c["pre"][:160] if c.get("pre") else "", TODAY, why,
                (" " + NOTE[cid]) if cid in NOTE else "")
            if c.get("desc_js"):
                e["invoke_descriptor_js"] = c["desc_js"]
            ev = [x.split(" ", 1)[0] for x in t.get("events") or []]
            if ev:
                e["invoke_events_seen"] = sorted(set(ev))[:8]
            it["evidence"] = (it.get("evidence", "") + "; script route run live and the change observed (extra.invoke_how)").lstrip("; ")
            counts["verified"] += 1
            continue
        # not verified: keep the best candidate, say why
        cand = None
        if tried:
            cand = cand_by_how(cid, tried[0][0]["how"])
        elif p["cands"]:
            cand = p["cands"][0]
        lab = C.get(cid, {})
        if p["skip"]:
            why_not = "not run: " + p["skip"]
        elif tried:
            why_not = "tried live %s: %s" % (TODAY, " | ".join("%s -> %s" % (x[0]["how"][:90], x[2][:160]) for x in tried[:4]))
        else:
            why_not = "not run"
        if p.get("interactive_mit"):
            cand = cand or dict(kind="ps_menu_cmd", key=p["interactive_mit"][0], run="", how="")
            why_not += "; runMenuItem('%s') would enter an interactive transform/edit mode, so it was not run" % p["interactive_mit"][0]
        if cand and cand.get("key"):
            it["invoke"] = invoke_of(cand, it)
            src = "label match in the terminology (menuItemType / event English label)" if cand["key"] in lab.get("mit", []) + lab.get("ev", []) \
                else "hand-mapped candidate (AM event / menuItemType / DOM call written for this command)"
            e["invoke_verified"] = False
            e["invoke_how"] = "candidate from %s, NOT confirmed: %s" % (src, why_not)
            if cand.get("desc_js"):
                e["invoke_descriptor_js"] = cand["desc_js"]
            counts["unverified"] += 1
        else:
            if (it.get("invoke") or {}).get("file"):
                e["invoke_verified"] = False
                e["invoke_how"] = "installed script (invoke.file) not run: " + why_not
                counts["unverified"] += 1
                continue
            if "ps_menu_cmd" in (it.get("invoke") or {}):
                it.pop("invoke")
            e["invoke_verified"] = False
            e["invoke_how"] = "no script route found: " + (why_not if p["skip"] or tried else
                                                           "no menuItemType or event label matches this command and no DOM/AM equivalent is known")
            counts["none"] += 1
    if "invoke verification" not in d["source"]:
        d["source"] += ("; invoke verification 2026-10-04 (tools/ps/menu_invoke.py + menu_plan.py + menu_write.py): each candidate "
                        "(runMenuItem(stringIDToTypeID(menuItemType)), executeAction(event, desc), DOM call) run on a fresh scratch document "
                        "in the state the command needs; invoke_verified true only when the document / app state changed as the "
                        "command should or the command's own dialog opened")
    H.with_suffix(".tmp").write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    H.with_suffix(".tmp").replace(H)
    print(counts, "backup", bak)


if __name__ == "__main__":
    {"review": review, "write": write}[sys.argv[1]]()
