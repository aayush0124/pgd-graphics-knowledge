"""PGD/CDR: fold the independent audit's live results (work/cdr/audit_live.json, written by audit_live.py) into the
harvest files. Idempotent: run it after any rebuild of cdr_effect / cdr_tool / cdr_menu (harvest_effects.py calls it).

    python apply_audit.py            patch harvest/cdr/*.json in place, print what changed
    python apply_audit.py --selftest

Effects verdict per tested item (A/B in-range values on one ranged param, B run twice for determinism, the recorded
max, an out-of-range value, and an unknown key):
  key honoured   A != B and B == B2         -> invoke.cdr_effect_cmd = the A command, cmd_status = proven by audit
  key ignored    A == B, base != A           -> error (template key not read)
  no effect      base == A == B              -> error (command does nothing)
  server fault   the call raised             -> error with the exception
  range          MAX != OVER                 -> param extra.range_note: ApplyBitmapEffect does not clamp to the
                                                dialog range (recorded min/max stay: they are the dialog's)
"""
import json, sys
from pathlib import Path

PGD = Path(__file__).resolve().parents[2]
AUDIT = PGD / "work" / "cdr" / "audit_live.json"
TAG = "independent audit 2026-10-04 (tools/cdr/audit_live.py)"


def zero(v):
    return v == 0 or v == 0.0


def effect_verdict(r):
    errs = {k: v for k, v in r.items() if k.startswith("err_")}
    if errs and r.get("A_B") is None:
        return "fault", "ApplyBitmapEffect('" + r["cmds"]["A"] + "') raised " + next(iter(errs.values()))
    if r.get("A_B") is None:
        return "unknown", "no result"
    nondet = r.get("B_B2") not in (None, 0, 0.0)
    if not zero(r["A_B"]) and not nondet:
        return "honoured", None
    if nondet:
        return "nondeterministic", "two runs of the same command gave different pixels (B vs B2 " + str(r["B_B2"]) + ")"
    if zero(r["A_B"]) and not zero(r.get("base_A") or 0):
        return "ignored", ("the effect ran but '" + r["param"] + "' A and B gave the same pixels (and the same as an "
                           "unknown key): either the key is not read or it does nothing while the other params "
                           "are at their current values; cmd_template unproven for this key")
    return "noop", "ApplyBitmapEffect changed no pixels for '" + r["cmds"]["A"] + "'"


def patch_effects(doc, res):
    by_id = {it["id"]: it for it in doc["items"]}
    log = []
    for name, r in (res.get("effects") or {}).items():
        it = by_id.get(r.get("id"))
        if it is None or "cmds" not in r:
            continue
        v, why = effect_verdict(r)
        ex = it.setdefault("extra", {})
        ex["audit"] = {"verdict": v, "param": r["param"], **{k: r[k] for k in r if "_" in k and not k.startswith("err")
                                                              and k not in ("ds_value_now",)},
                       "cmds": r["cmds"], "ds_value_now": r.get("ds_value_now")}
        ev = f"; {TAG}: " + (f"'{r['cmds']['A']}' vs '{r['cmds']['B']}' gave different, repeatable pixels "
                             f"(A/B {r['A_B']}, B/B2 {r['B_B2']}): key honoured" if v == "honoured" else why)
        if TAG not in it.get("evidence", ""):
            it["evidence"] = it.get("evidence", "") + ev
        if v == "honoured":
            it["invoke"]["cdr_effect_cmd"] = r["cmds"]["A"]
            ex["cmd_status"] = f"command string proven by the {TAG} on key {r['param']}; other keys of cmd_template " \
                               "follow the same rule but were not each applied"
        elif v in ("fault", "ignored", "noop"):
            it["invoke"].pop("cdr_effect_cmd", None)
            if TAG not in it.get("error", ""):   # idempotent: harvest_effects and harvest_tools both re-apply
                it["error"] = (it.get("error", "") + "; " if it.get("error") else "") + f"{TAG}: {why}"
            ex["cmd_status"] = "cmd_template NOT working: " + why
        for p in it.get("params") or []:
            if p.get("key") != r["param"]:
                continue
            if r.get("MAX_OVER") not in (None, 0, 0.0) and v == "honoured":
                over = r["cmds"]["OVER"].split("=")[-1]
                p.setdefault("extra", {})["range_note"] = (
                    f"min/max are the dialog's; ApplyBitmapEffect accepted {r['param']}={over} (beyond max "
                    f"{p.get('max')}) and gave pixels different from max (not clamped, not rejected)")
            elif zero(r.get("MAX_OVER")) and v == "honoured":
                p.setdefault("extra", {})["range_note"] = (
                    f"ApplyBitmapEffect with {r['cmds']['OVER'].split('=')[-1]} gave the same pixels as max: clamped")
            dv = r.get("ds_value_now")
            if isinstance(dv, (int, float)) and isinstance(p.get("default"), (int, float)) and dv != p["default"]:
                p.setdefault("extra", {})["audit_ds_value"] = dv
        log.append((it["name"], v))
    lv = res.get("levels_retest")
    it = by_id.get("cebbcfb6-8412-4568-8301-93ea5eeb95b5")   # Effects/Adjust/Levels (EqualizeEffect)
    if lv and it is not None and "full key set" not in it.get("error", ""):
        it["error"] += ("; the full key set ('" + lv["cmds"]["full"] + "') and 'EqualizeEffect Gamma=2' also raised "
                        "RPC_E_SERVERFAULT: EqualizeEffect with any real key is not scriptable through ApplyBitmapEffect")
        it["extra"]["audit"]["levels_retest"] = lv
    return log


def patch_vector(doc, res):
    by_id = {it["id"]: it for it in doc["items"]}
    log = []
    for name, r in (res.get("vector") or {}).items():
        it = by_id.get(r.get("id"))
        if it is None:
            continue
        ex = it.setdefault("extra", {})
        ex["audit"] = {k: v for k, v in r.items() if k not in ("id",)}
        ok = r.get("returned") in ("IVGEffect", "Effect") and "error" not in r
        if TAG not in it.get("evidence", ""):
            it["evidence"] = it.get("evidence", "") + f"; {TAG}: called with every optional argument omitted " + \
                (f"-> {r.get('returned')} type {r.get('effect_type')}" if ok else f"FAILED: {r.get('error')}")
        rb = r.get("readback") or {}
        for p in it.get("params") or []:
            if p.get("key") in rb and isinstance(rb[p["key"]], (int, float)) and "default" in p:
                if abs(float(rb[p["key"]]) - float(p["default"])) > 1e-6:
                    p.setdefault("extra", {})["typelib_default"] = p["default"]
                    p["extra"]["default_note"] = (f"the typelib declares {p['default']}, but an effect created with "
                                                  f"{p['default']} passed reads back {rb[p['key']]} ({TAG}): the app "
                                                  f"substitutes its own value, so {rb[p['key']]} is the effective default")
                    p["default"] = rb[p["key"]]
        log.append((it["name"], "ok" if ok else "fail"))
    return log


def patch_tools(doc, res):
    by_id = {it["id"]: it for it in doc["items"]}
    log = []
    for name, r in (res.get("tools") or {}).items():
        it = by_id.get(r.get("id"))
        if it is None:
            continue
        it.setdefault("extra", {})["audit"] = {k: v for k, v in r.items() if k not in ("id", "name")}
        good = r.get("ds_active") == it["id"] or r.get("state_match")
        if TAG not in it.get("evidence", ""):
            it["evidence"] += f"; {TAG}: set by " + str(r.get("set")) + \
                f", read back state {r.get('state')} / toolbox item {r.get('ds_active')}" + (": confirmed" if good else ": MISMATCH")
        log.append((it["name"], "ok" if good else "mismatch"))
    return log


def patch_menus(doc, res):
    by_id = {it["id"]: it for it in doc["items"]}
    log = []
    for path, r in (res.get("menucmd") or {}).items():
        it = by_id.get(r.get("id"))
        if it is None:
            continue
        it.setdefault("extra", {})["audit"] = {k: v for k, v in r.items() if k not in ("id", "name", "path")}
        did = bool(r.get("changed"))
        if TAG not in it.get("evidence", ""):
            it["evidence"] += f"; {TAG}: Automation.InvokeItem on two selected shapes " + \
                ("changed " + ", ".join(sorted(r["changed"])) if did else "changed nothing measured (shape count, "
                 "selection, type, order, lock, x)")
        log.append((it["name"], "changed" if did else "no visible change"))
    return log


def main():
    res = json.loads(AUDIT.read_text(encoding="utf-8"))
    for kind, fns in (("cdr_effect", (patch_effects, patch_vector)), ("cdr_tool", (patch_tools,)),
                      ("cdr_menu", (patch_menus,))):
        f = PGD / "harvest" / "cdr" / f"{kind}.json"
        doc = json.loads(f.read_text(encoding="utf-8"))
        for fn in fns:
            for row in fn(doc, res):
                print(kind, fn.__name__, row)
        f.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")


def selftest():
    base = {"cmds": {"A": "X K=1", "B": "X K=2", "OVER": "X K=99"}, "param": "K"}
    assert effect_verdict(dict(base, A_B=3, B_B2=0, base_A=1))[0] == "honoured"
    assert effect_verdict(dict(base, A_B=0, B_B2=0, base_A=4))[0] == "ignored"
    assert effect_verdict(dict(base, A_B=0, B_B2=0, base_A=0))[0] == "noop"
    assert effect_verdict(dict(base, A_B=None, err_A="boom"))[0] == "fault"
    assert effect_verdict(dict(base, A_B=2, B_B2=1.5, base_A=1))[0] == "nondeterministic"
    print("selftest ok")


if __name__ == "__main__":
    selftest() if sys.argv[1:] == ["--selftest"] else main()
