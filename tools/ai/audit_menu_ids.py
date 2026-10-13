"""PGD / Illustrator audit: confirm or refute executeMenuCommand ids by running them on a test document
-> work/ai/audit/menu_id_checks.json. Each case: (menu path, id, setup selection, what proves it)."""
import json, sys, time
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aicom import js, js_watch  # noqa: E402

OUT = (PGD / "work/ai/audit/menu_id_checks.json")
SETUP = ('var d=app.documents.add(DocumentColorSpace.RGB, 800, 600);'
         'var a=d.pathItems.rectangle(450,250,300,200); a.name="A";'
         'var b=d.pathItems.ellipse(400,350,250,250); b.name="B"; d.selection=null; a.selected=true; d.name;')
STATE = ('var d=app.activeDocument, s=d.selection, n=[]; for (var i=0;i<s.length;i++) n.push(s[i].name);'
         'var a=d.pathItems.getByName("A"); "sel="+n.join(",")+" ptsA="+a.pathPoints.length;')
CASES = [("Object/Transform/Transform Each...", "Transform3", "dialog Transform Each"),
         ("Object/Transform/Transform Each...", "Transform v23", "dialog Transform Each"),
         ("Object/Transform/Rotate...", "transformrotate", "dialog Rotate"),
         ("Object/Transform/Reflect...", "transformreflect", "dialog Reflect"),
         ("Object/Transform/Scale...", "transformscale", "dialog Scale"),
         ("Object/Transform/Shear...", "transformshear", "dialog Shear"),
         ("Object/Transform/Move...", "transformmove", "dialog Move"),
         ("Object/Path/Add Anchor Points", "Add Anchor Points2", "ptsA 4 -> 8"),
         ("Select/Next Object Above", "Selection Hat 8", "sel A -> B"),
         ("Select/Next Object Below", "Selection Hat 9", "sel A -> A (nothing below A)"),
         ("Object/Group", "group", "sel A -> group"),
         ("Object/Envelope Distort/Envelope Options...", "Envelope Options", "dialog Envelope Options"),
         ("Edit/Edit Custom Dictionary...", "Edit Custom Dictionary...", "dialog Edit Custom Dictionary"),
         ("File/Export/Export for Screens...", "exportForScreens", "dialog Export for Screens"),
         ("Object/Arrange/Bring to Front", "sendToFront", "top item B -> A"),
         ("Object/Arrange/Send to Back", "sendToBack", "top item B -> B (A already at the back)")]


def main():
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    for path, mid, proof in CASES:
        key = path + " | " + mid
        if key in res:
            continue
        name = js(SETUP, 60)
        before = js(STATE, 30)
        r, e, seen = js_watch('app.executeMenuCommand("%s"); "ok";' % mid, 60, key="escape")
        time.sleep(0.4)
        try:
            after = js(STATE, 30)
        except Exception as x:  # noqa: BLE001
            after = "ERR " + str(x)[:200]
        js('for (var i=app.documents.length-1;i>=0;i--) if (app.documents[i].name=="%s")'
           ' app.documents[i].close(SaveOptions.DONOTSAVECHANGES); 1;' % name, 60)
        res[key] = {"path": path, "id": mid, "proof": proof, "result": r, "error": (e or "")[:300], "dialogs": seen,
                    "before": before, "after": after}
        OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
        print(key, "->", r, (e or "")[:90], seen, before, "=>", after, flush=True)
    print("docs:", js("app.documents.length", 30))


if __name__ == "__main__":
    main()
