"""PGD / Illustrator: confirm executeMenuCommand candidates for items with no dialog by the effect they store.

    python confirm_ids.py "<menu path>=<cand1>,<cand2>" ...

Each candidate runs through probe_effects.probe() (fresh doc, rectangle, invoke, uncompressed save, parse); it is
confirmed when the stored live effect + its operation keys equal what the WM_COMMAND probe of that menu item stored.
Results -> work/ai/menu_id_tests.json (shared with find_menu_ids.py)."""
import json, sys
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_effects import probe, baseline, live_blocks, parse_block, text  # noqa: E402

WORK = (PGD / "work/ai")
OUT = WORK / "menu_id_tests.json"
OPKEYS = ("Geometry3DkOperationTypeKey", "styl", "SVGFilterUIDName", "DeformStyle", "Command", "Shape")


def sig(rec):
    return [(e["live_effect"], {p["key"]: p.get("value") for p in e["params"] if p["key"] in OPKEYS})
            for e in rec.get("effects", [])]


def main(specs):
    ck = json.loads((WORK / "probe_ckpt.json").read_text(encoding="utf-8"))
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    base = baseline()
    for spec in specs:
        path, cands = spec.split("=", 1)
        r0 = ck[path]  # re-parse the WM_COMMAND probe file (older checkpoints were parsed by an older parser)
        want = sig({"effects": [parse_block(b) for b in live_blocks(text(r0["file"])) if b not in base]})
        for c in cands.split(","):
            rec = probe({"path": "confirm/" + c, "invoke": {"ai_menu": c}}, base)
            got = sig(rec)
            res[c] = {"expected_path": path, "error": rec.get("error"), "dialogs": rec.get("dialogs"),
                      "stored": got, "wm_command_stored": want, "confirmed": bool(got) and got == want and not rec.get("error")}
            OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
            print(c, "->", res[c]["confirmed"], got, (rec.get("error") or "")[:120])


if __name__ == "__main__":
    main(sys.argv[1:])
