"""PGD / Illustrator: harvest/ai/ai_blend_mode.json

    python ai_blend_modes.py

Enum names + numbers from the installed scripting dictionary (omv.xml, BlendModes), display names + panel order from
the Transparency panel's own popup definition inside TransparencyPalette.aip (items [{name:"$$$/...=Label", value:N}]),
joined on the number. Then verified in the live app: one rectangle per mode in a new document, blendingMode set from
the enum and read back, the document saved uncompressed and the blend-mode operand of each object's 'Xy' operator read
from the file. The test document is closed without saving.
"""
import json, re, sys
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aicom import js  # noqa: E402

OMV = Path(r"C:/Program Files/Common Files/Adobe/Scripting Dictionaries CC/Illustrator 2026/omv.xml")
TP = Path(r"C:/Program Files/Adobe/Adobe Illustrator 2026/Plug-ins/Extensions/TransparencyPalette.aip")
OUT = (PGD / "harvest/ai/ai_blend_mode.json")
WORK = (PGD / "work/ai")


def enum():
    x = OMV.read_text(encoding="utf-8")
    blk = x[x.index('<classdef name="BlendModes"'):]
    blk = blk[:blk.index("</classdef>")]
    return [(n, int(v)) for n, v in re.findall(
        r'<property name="(\w+)"[^>]*>\s*<datatype>\s*<type>int</type>\s*<value>(\d+)</value>', blk)]


def labels():
    """[(label, value, zstring key)] in the order the Transparency panel lists them."""
    b = TP.read_bytes().decode("latin-1")
    i = b.index('identifier: "BlendingModePopup"')
    items = b[i:b.index("bind:", i)]
    return [(lab, int(v), key) for key, lab, v in
            re.findall(r'\{name:"(\$\$\$/TransparencyPalette/Mnu/Mode/\w+)=([^"]+)"\s*,\s*value:(\d+)\}', items)]


LIVE = r'''
var names = %s, out = [];
var d = app.documents.add(DocumentColorSpace.RGB, 800, 600);
for (var i = 0; i < names.length; i++) {
  var p = d.pathItems.rectangle(580 - 35 * i, 10, 30, 30);
  p.name = "bm_" + names[i];
  try { p.blendingMode = BlendModes[names[i]]; out.push(names[i] + "=" + String(p.blendingMode)); }
  catch (e) { out.push(names[i] + "=ERR " + String(e)); }
}
var o = new IllustratorSaveOptions(); o.compressed = false;
d.saveAs(new File(File("%s").fsName), o);
d.close(SaveOptions.DONOTSAVECHANGES);
out.join("\n");'''


def main(offline=False):
    en, lab = enum(), labels()
    f = WORK / "blend_modes_probe.ai"
    if offline:  # files only (Illustrator busy): first version of the harvest file
        back, t = {n: "not yet read back" for n, _ in en}, ""
    else:
        back = dict(l.split("=", 1) for l in js(LIVE % (json.dumps([n for n, _ in en]), f.as_posix()), 120).split("\n"))
        t = f.read_bytes().decode("latin-1")
    # each rectangle is written as ... '<mode> <opacity> <isolated> <knockout> <alphaIsShape> Xy' then its path;
    # read the Xy operands in file order (objects are written bottom-up = creation order)
    xy = [int(m) for m in re.findall(r"^(\d+) [\d.]+ \d \d \d Xy$", t.replace("\r\n", "\n").replace("\r", "\n"), re.M)]
    # the art comes last in the file, one Xy per rectangle in creation order (= omv order): operand per enum name
    file_mode = dict(zip([n for n, _ in en], xy[-len(en):])) if len(xy) >= len(en) else {}
    items = []
    for order, (label, v, key) in enumerate(lab):
        name = next((n for n, ev in en if ev == v), None)
        it = {"name": label, "id": name or f"value_{v}", "path": f"Window/Transparency/Blending Mode/{label}",
              "category": "Transparency", "invoke": {"ai_dom": f"pageItem.blendingMode = BlendModes.{name}"},
              "evidence": "label + number from the Transparency panel popup definition in TransparencyPalette.aip "
                          f"({key}); enum name + number from omv.xml; set and read back in Illustrator: "
                          f"{back.get(name)}",
              "extra": {"value": v, "panel_order": order, "zstring": key}}
        if name in file_mode:
            it["extra"]["file_xy_operand"] = file_mode[name]
            it["evidence"] += f"; saved uncompressed, the object's Xy blend operand is {file_mode[name]}"
            if file_mode[name] != v:
                it["error"] = f"file stores blend operand {file_mode[name]}, enum value is {v}"
        if not offline and back.get(name) != f"BlendModes.{name}":
            it["error"] = f"read back {back.get(name)!r}"
        items.append(it)
    for n, v in en:
        if not any(i["extra"]["value"] == v for i in items):
            items.append({"name": n, "id": n, "error": "enum value has no Transparency panel label",
                          "invoke": {"ai_dom": f"pageItem.blendingMode = BlendModes.{n}"}, "extra": {"value": v}})
    doc = {"app": "AI", "kind": "ai_blend_mode", "app_version": (WORK / "app_version.txt").read_text().strip() if offline else js("app.version", 30),
           "source": "omv.xml BlendModes + TransparencyPalette.aip popup items, set/read back live (ai_blend_modes.py)",
           "items": items}
    if xy:
        doc["source"] += f"; Xy operands in the saved test file: {sorted(set(xy))}"
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    print(len(items), "blend modes ->", OUT, "| Xy operands seen:", sorted(set(xy)))
    assert len(items) == 16, len(items)


if __name__ == "__main__":
    main(offline="--offline" in sys.argv)
