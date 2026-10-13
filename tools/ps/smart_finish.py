"""Finish the smart-filter probe for ps_filter.json and write ONLY extra.smart_filter (+ smart_filter_note).

    python smart_finish.py probe   # probe every headless filter not yet in work/ps/probe_smart.json (checkpointed)
    python smart_finish.py write   # back up ps_filter.json, then add extra.smart_filter / smart_filter_note

Probe = probe.SMART_JS: duplicate the test layer, Convert to Smart Object, executeAction(event, {}, DialogModes.NO),
read the layer's smartObject.filterFX list back. Invert canary + restart after every probe (probe.run_simple).
Filters that do not run headless are left alone: Displace (no map file wedges Photoshop), Lens Blur (already
recorded), the Render Deco filters / Custom / Filter Gallery / Adaptive Wide Angle (refused an empty descriptor).
"""
import json, shutil, sys, time
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).parent))
import probe, psdrv  # noqa: E402

H = (PGD / "harvest/ps/ps_filter.json")
NEVER = {"displace": "not probed: Displace with no displacement-map file wedges Photoshop (only taskkill recovers)"}


PF = probe.ck_load("filter")


def fd_js(sid):
    """descriptor for events whose empty descriptor was refused in the filter probe: the simple values probe.py sent then."""
    spec = (PF.get(sid) or {}).get("base_sent")
    if not spec:
        return "new ActionDescriptor()"
    b = ["var fd = new ActionDescriptor();"]
    for k, f in spec.items():
        kk = 'C2T("%s")' % k[1:5] if k.startswith("'") else 'S2T("%s")' % k
        if f[0] == "int":
            b.append("fd.putInteger(%s, 1);" % kk)
        elif f[0] == "unit":
            b.append('fd.putUnitDouble(%s, S2T("%s"), 1);' % (kk, f[1]))
        elif f[0] == "double":
            b.append("fd.putDouble(%s, 1);" % kk)
        elif f[0] == "bool":
            b.append("fd.putBoolean(%s, false);" % kk)
        elif f[0] == "enum":
            b.append('fd.putEnumerated(%s, S2T("%s"), S2T("%s"));' % (kk, f[1], f[2]))
    return "(function(){ %s return fd; })()" % " ".join(b)


def _tid(x):
    return 'C2T("%s")' % x[1:5] if x.startswith("'") else 'S2T("%s")' % x


def rb_js(o, var="fd"):
    """JS that rebuilds the descriptor Photoshop read back in the filter probe (probe_filter.json readback)."""
    b = []
    for k, v in o.items():
        t, val, kk = v.get("t"), v.get("v"), _tid(k)
        if t == "INTEGERTYPE":
            b.append("%s.putInteger(%s, %d);" % (var, kk, val))
        elif t == "DOUBLETYPE":
            b.append("%s.putDouble(%s, %r);" % (var, kk, val))
        elif t == "UNITDOUBLE":
            b.append("%s.putUnitDouble(%s, %s, %r);" % (var, kk, _tid(v["unit"]), val))
        elif t == "BOOLEANTYPE":
            b.append("%s.putBoolean(%s, %s);" % (var, kk, "true" if val else "false"))
        elif t == "ENUMERATEDTYPE":
            b.append("%s.putEnumerated(%s, %s, %s);" % (var, kk, _tid(v["etype"]), _tid(val)))
        elif t == "STRINGTYPE":
            b.append('%s.putString(%s, "%s");' % (var, kk, str(val).replace('"', "'")))
        elif t == "OBJECTTYPE" and isinstance(val, dict):
            sub = var + "o"
            b.append("var %s = new ActionDescriptor(); %s %s.putObject(%s, %s, %s);" % (sub, rb_js(val, sub), var, kk, _tid(v["cls"]), sub))
    return " ".join(b)


def readback_desc(sid):
    rb = (PF.get(sid) or {}).get("readback")
    return "(function(){ var fd = new ActionDescriptor(); %s return fd; })()" % rb_js(rb) if rb else None


def retry_dialogs():
    """filters that opened their dialog on the smart object with an empty descriptor: rerun with the full read-back descriptor."""
    ck = probe.ck_load("smart")
    redo = [k for k, v in ck.items() if "DIALOG" in str(v.get("err", "")) and readback_desc(k) and not v.get("full_desc")]
    print(len(redo), "to retry with the full read-back descriptor", flush=True)
    for k in redo:
        ck.pop(k)
    probe.ck_save("smart", ck)
    print(probe.setup())
    for sid in redo:
        js = probe.SMART_JS.replace("executeAction(ev, new ActionDescriptor(), DialogModes.NO);", "executeAction(ev, %s, DialogModes.NO);" % readback_desc(sid))
        r = probe.run_simple("smart", sid, js % {"doc": probe.WORKDOC, "ev": probe.ev_expr(sid)}, timeout=60)
        ck = probe.ck_load("smart")
        ck[sid]["full_desc"] = True
        probe.ck_save("smart", ck)
    psdrv.js('closeNoSave("%s"); closeNoSave("test_photo.png"); app.documents.length' % probe.WORKDOC, timeout=60)


def targets(items):
    out = []
    for it in items:
        ev = (it.get("invoke") or {}).get("ps_event")
        e = it.get("extra", {})
        if not ev or "smart_filter" in e or it["id"] in NEVER:
            continue
        if e.get("exec_ms") is None and it["id"] != "dustAndScratches":  # never ran headless in the filter probe
            continue
        out.append(ev)
    return out


def do_probe():
    items = json.loads(H.read_text(encoding="utf-8"))["items"]
    evs = targets(items)
    print(len(evs), "filters to probe", flush=True)
    print(probe.setup())
    for sid in evs:
        js = probe.SMART_JS.replace("executeAction(ev, new ActionDescriptor(), DialogModes.NO);", "executeAction(ev, %s, DialogModes.NO);" % fd_js(sid))
        probe.run_simple("smart", sid, js % {"doc": probe.WORKDOC, "ev": probe.ev_expr(sid)}, timeout=120)
    psdrv.js('closeNoSave("%s"); closeNoSave("test_photo.png"); app.documents.length' % probe.WORKDOC, timeout=60)


def verdict(r):
    if r.get("err"):
        msg = r["err"]
        if "DIALOG" in msg:
            return None, "not determinable headless: the filter opened its dialog under DialogModes.NO (dismissed by window handle): " + msg[:160]
        if "HANG" in msg or "COM " in msg:
            return None, "probe hung / COM error: " + msg[:160]
        return False, "applying it to a smart object failed: " + msg[:200]
    if r.get("n", 0) >= 1:
        return True, None
    return False, "event ran on the smart object but no filterFX entry was stored (keys: %s)" % ",".join(r.get("keys") or [])


def write():
    d = json.loads(H.read_text(encoding="utf-8"))
    ck = probe.ck_load("smart")
    bak = (PGD / ("work/ps/ps_filter.json.bak-smart-" + time.strftime("%H%M%S")))
    shutil.copy2(H, bak)
    n = 0
    for it in d["items"]:
        ev = (it.get("invoke") or {}).get("ps_event")
        e = it.setdefault("extra", {})
        if "smart_filter" in e:
            continue
        if it["id"] in NEVER:
            e["smart_filter_note"] = NEVER[it["id"]]
            continue
        if not ev or ev not in ck:
            continue
        v, note = verdict(ck[ev])
        if v is not None:
            e["smart_filter"] = v
            n += 1
            if v and ck[ev].get("filterFX", {}).get("filter"):
                e["smart_filter_stored_keys"] = sorted(ck[ev]["filterFX"]["filter"].get("v", {}).keys()) if isinstance(ck[ev]["filterFX"]["filter"].get("v"), dict) else []
        if ck[ev].get("full_desc"):
            note = ((note + "; ") if note else "") + ("probed with the full descriptor read back in the filter probe: with an empty descriptor "
                                                      "the filter opened its own dialog on the smart object even under DialogModes.NO, so pass every parameter")
            if ev == "oilPaint":
                note += "; IOError both with the empty and the full descriptor (Oil Paint is GPU-dependent: may differ on another machine)"
        if (PF.get(ev) or {}).get("base_sent") and v:
            note = ((note + "; ") if note else "") + "probed with the fallback descriptor the filter probe used (its empty descriptor is refused)"
        if note:
            e["smart_filter_note"] = note
    H.with_suffix(".tmp").write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    H.with_suffix(".tmp").replace(H)
    print("smart_filter written for", n, "more filters; backup", bak)


if __name__ == "__main__":
    {"probe": do_probe, "write": write, "retry": retry_dialogs}[sys.argv[1]]()
