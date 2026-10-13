"""PGD / Illustrator: confirm executeMenuCommand strings by what the app does with them -> work/ai/menu_id_tests.json

    python find_menu_ids.py "Drop Shadow=Live Adobe Drop Shadow,Live DropShadow" "Round Corners=Live Adobe Round Corners"

For each candidate, on a selected rectangle in a fresh document: app.executeMenuCommand(candidate); a dialog whose
title is the expected item name confirms it (the dialog is cancelled with Escape). Illustrator answers an unknown id
with "Error 1200 ... ('BKey')". Candidates come from strings inside the effect's own plug-in (never invented names).
"""
import json, sys
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aicom import js, js_watch  # noqa: E402
from probe_effects import NEW_DOC  # noqa: E402

OUT = (PGD / "work/ai/menu_id_tests.json")


def test(cand):
    name = js(NEW_DOC, 60)
    try:
        r, e, seen = js_watch('app.executeMenuCommand("%s"); "ok";' % cand, 30, key="escape")
    finally:
        js('for (var i = 0; i < app.documents.length; i++) if (app.documents[i].name == "%s") '
           '{ app.documents[i].close(SaveOptions.DONOTSAVECHANGES); break; } "closed";' % name, 60)
    return {"result": r, "error": e, "dialogs": seen}


def main(specs):
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    for spec in specs:
        want, cands = spec.split("=", 1)
        for c in cands.split(","):
            t = test(c)
            t["confirmed"] = want in (t["dialogs"] or [])
            res[c] = dict(t, expected=want)
            OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
            print(c, "->", t)


if __name__ == "__main__":
    main(sys.argv[1:])
