"""PGD/CDR: read CorelDRAW 2024's preset lists from the RUNNING app -> work/cdr/presets_live.json (checkpointed per
section; delete a section key to re-read it). Read-only: nothing is opened, applied or saved; the only document is our
own TestDoc (closed unsaved) used to give the property-bar preset lists a selection context.

Sections:
  palettes        Application.PaletteManager.GetPalette(i): Name, FileName, Identifier, ColorCount (+ entry names for
                  palettes whose XML has unnamed entries: Palette.Color(j).Name)
  arrowheads      Application.ArrowHeads.Item(i): Name, DisplayName
  outline_styles  Application.OutlineStyles.Item(i): DashCount, DashLength(j), GapLength(j)
  workspaces      Application.Workspaces.Item(i): Name, Description, Default, Active
  ds_lists        preset lists bound in DrawUI.xml (…;Path=PresetList / PresetItems …) read with
                  FrameWork.Application.DataContext.GetDataSource(ds).GetProperty(path), cold and then in a TestDoc with
                  a rectangle selected and the owning tool active (Automation.InvokeItem(tool guid))
"""
import json, re, sys, time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cdr_com import Corel  # noqa: E402

OUT = HERE.parents[1] / "work" / "cdr" / "presets_live.json"
PAL_DIR = Path(r"C:/Program Files/Corel/CorelDRAW Graphics Suite/25/Color/Palettes")

# (data source, list path, category, UI path, requires, tool guid giving the context or None)
LISTS = [
    ("WDropShadowPresentationDS", "PresetList", "Shadow Preset (property bar)", "Shadow tool/Property Bar/Preset", "vector object", "e65d1597-722d-4afb-82fe-964d7ddff531"),
    ("WBlendPresentationDS", "PresetList", "Blend Preset (property bar)", "Blend tool/Property Bar/Preset", "two vector objects", "d72c98e8-59be-4a31-b9db-1d0e83bdd218"),
    ("WContourDataSource", "PresetList", "Contour Preset (property bar)", "Contour tool/Property Bar/Preset", "vector object", "441d6b88-877e-4d00-951f-4521b9987650"),
    ("WDistortionDataSource", "PresetList", "Distortion Preset (property bar)", "Distort tool/Property Bar/Preset", "vector object", "f42edc69-976b-4917-802a-1c4fed6297ef"),
    ("WEnvelopeDockerDS", "DockerPresetListItems", "Envelope Preset (docker)", "Effects/Envelope docker/Preset", "vector object", "1f16cb33-9819-4fa7-a3cd-5c4d61ba2db2"),
    ("EnvelopeDataSource", "PresetListItems", "Envelope Preset (property bar)", "Envelope tool/Property Bar/Preset", "vector object", "1f16cb33-9819-4fa7-a3cd-5c4d61ba2db2"),
    ("WExtrudeDataSource", "PresetList", "Extrude Preset (property bar)", "Extrude tool/Property Bar/Preset", "vector object", "c5555cfc-1c54-4c5b-ad28-60a4ec569798"),
    ("TransparencyStyleDS", "UniformPresetList", "Transparency Preset (property bar)", "Transparency tool/Property Bar/Preset", "vector object or bitmap", "b4b2ecec-4dc4-4c76-aa55-abcb1c862cde"),
    ("ArtisticMediaDS", "PresetStrokeList", "Artistic Media Preset Stroke (property bar)", "Artistic Media tool/Property Bar/Preset stroke", "open path or curve", "5d09b650-fdad-462e-93c0-12859111f480"),
    ("DimensionDataSource", "PresetList", "Dimension Preset (property bar)", "Dimension tool/Property Bar/Preset", "dimension line", "f1b16e8a-9f6f-05b4-4610-451172f5fff2"),
    ("PerspectiveGroupToolDS", "PresetList", "Perspective Preset", "Perspective tool/Property Bar/Preset", "vector object", None),
    ("WOutlineDataSource", "OutlineFlyoutPresetList", "Outline Width Preset (toolbox flyout)", "Toolbox/Outline Pen flyout", "outline", None),
    ("WNewDocumentDataSource", "PaperPresetItems", "New Document Preset", "File/New/Preset", None, None),
    ("WNewDocumentDataSource", "PresetCategoryList", "New Document Preset Category", "File/New/Preset category", None, None),
    ("WGuidePresetsSettingsDS", "GuidePresetsItems", "Guideline Preset", "Tools/Options/Document/Guidelines/Presets", "open document", None),
    ("FindObjectsDockerDS", "PresetList", "Find and Replace Preset (docker)", "Edit/Find and Replace docker/Preset", "open document", None),
    ("PDFSavePresetDS", "PresetItems", "PDF Preset", "File/Publish to PDF/PDF preset", "open document", None),
    ("SVGGeneralDS", "PresetsItems", "SVG Export Preset", "File/Export/SVG/Preset", "open document", None),
    ("ColorViewDS", "ProofPresetList", "Color Proof Preset", "View/Proof Colors/Preset", "open document", None),
    ("WCuiColorSystemDS", "PresetSettingsList", "Color Management Preset (dialog)", "Tools/Color Management/Default Settings/Preset", None, None),
    ("PalettedDS", "PresetsList", "Paletted Conversion Preset", "Bitmaps/Mode/Paletted/Preset", "bitmap", None),
    ("NNArtStyleEffectDS", "StylePresets", "Art Style Preset", "Effects/Creative/Art Style/Style", "bitmap", None),
] + [(ds, "PresetItems", f"{lab} Effect Preset", f"Effects/{lab}/Preset", "bitmap", None) for ds, lab in (
    ("BevelFactoryEffectDS", "Bevel"), ("BumpMapEffectDS", "Bump Map"), ("ChannelMixerEffectDS", "Channel Mixer"),
    ("FrameEffectDS", "Frame"), ("GlassEffectDS", "Glass"), ("LensFlareEffectDS", "Lens Flare"),
    ("LightingEffectDS", "Lighting"), ("ShearEffectDS", "Shear"), ("SpotFilterEffectDS", "Spot Filter"),
    ("StoneEffectDS", "Stone"), ("TheBossEffectDS", "The Boss"), ("ToneCurveEffectDS", "Tone Curve"),
    ("UserDefinedEffectDS", "User Defined"), ("WhirlpoolEffectDS", "Whirlpool"))]


def parse_items(raw):
    """'<container><itemData guid= text= value= .../>' -> [{text, guid, value, ...}] (text falls back to tooltip/caption)."""
    if not isinstance(raw, str) or "itemData" not in raw:
        return []
    try:
        x = ET.fromstring(raw)
        rows = [dict(e.attrib) for e in x.iter("itemData")]
    except ET.ParseError:
        rows = [dict(re.findall(r'(\w+)="([^"]*)"', m)) for m in re.findall(r"<itemData([^>]*)/?>", raw)]
    out = []
    for r in rows:
        t = r.get("text") or r.get("tooltip") or r.get("caption") or r.get("name")
        if not t:
            continue
        e = {"text": t}
        e.update({k: v for k, v in r.items() if k in ("guid", "value", "icon", "type", "tooltip") and v and v != t})
        out.append(e)
    names = [e["text"] for e in out]
    for e in out:
        if names.count(e["text"]) > 1:
            e["dup"] = True
    return out


def save(res):
    OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")


def unnamed_palette_files():
    out = set()
    for f in PAL_DIR.rglob("*.xml"):
        try:
            x = ET.parse(f).getroot()
        except ET.ParseError:
            continue
        cols = x.find("colors")
        if cols is not None and any(not c.get("name") for c in cols.iter("color")):
            out.add(str(f.resolve()).lower())
    return out


def main():
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    cd = Corel()
    docs = cd.call(lambda a: [a.Documents.Item(i + 1).Title for i in range(a.Documents.Count)], 30)
    res["app_version"] = cd.call(lambda a: f"{a.VersionMajor}.{a.VersionMinor}.0.{a.VersionBuild}", 30)
    res["documents_at_start"] = docs
    save(res)

    if "palettes" not in res or len(res["palettes"]) < 50:
        # PaletteManager.PaletteCount / GetPalette(i) only covers the ~5 palettes already loaded in the session (first run
        # 2026-10-04 returned 5 of 176), so every shipped palette file is loaded by name instead. LoadPalette does not
        # open it in the palette bar; if OpenPalettes grows anyway, the palette is closed again.
        want = unnamed_palette_files()
        res["palette_manager_count"] = cd.call(lambda a: a.PaletteManager.PaletteCount, 60)
        pals = []
        for i, f in enumerate(sorted(PAL_DIR.rglob("*.xml")), 1):
            def job(a, f=f, i=i):
                pm = a.PaletteManager
                before = pm.OpenPalettes.Count
                p = pm.LoadPalette(str(f))
                if p is None:
                    return {"index": i, "file": str(f), "error": "LoadPalette returned None"}
                r = {"index": i, "name": p.Name, "file": p.FileName or str(f), "identifier": p.Identifier,
                     "color_count": p.ColorCount, "type": p.Type, "locked": p.Locked}
                if str(f.resolve()).lower() in want:
                    r["entries"] = [p.Color(j).Name for j in range(1, p.ColorCount + 1)]
                if pm.OpenPalettes.Count > before and p.IsOpen:
                    p.Close()
                    r["closed_after_load"] = True
                return r
            try:
                pals.append(cd.call(job, 120, note=f"palette {f.name}"))
            except Exception as e:  # noqa: BLE001
                pals.append({"index": i, "file": str(f), "error": str(e)[:200]})
            if i % 25 == 0:
                res["palettes"] = pals
                save(res)
        res["palettes"] = pals
        save(res)
        print("palettes", len(pals), "errors", sum(1 for p in pals if p.get("error")))

    if "arrowheads" not in res:
        def job(a):
            ah = a.ArrowHeads
            return [{"index": i, "name": ah.Item(i).Name, "display_name": ah.Item(i).DisplayName} for i in range(1, ah.Count + 1)]
        res["arrowheads"] = cd.call(job, 120)
        save(res)
        print("arrowheads", len(res["arrowheads"]))

    if "outline_styles" not in res:
        def job(a):
            os_ = a.OutlineStyles
            out = []
            for i in range(1, os_.Count + 1):
                s = os_.Item(i)
                k = s.DashCount
                out.append({"index": i, "dash_count": k, "dashes": [s.DashLength(j) for j in range(1, k + 1)],
                            "gaps": [s.GapLength(j) for j in range(1, k + 1)]})
            return out
        res["outline_styles"] = cd.call(job, 120)
        save(res)
        print("outline styles", len(res["outline_styles"]))

    if "workspaces" not in res:
        def job(a):
            w = a.Workspaces
            return [{"name": w.Item(i).Name, "description": w.Item(i).Description, "default": w.Item(i).Default,
                     "active": w.Item(i).Active} for i in range(1, w.Count + 1)]
        res["workspaces"] = cd.call(job, 60)
        save(res)

    if "ds_lists" not in res:
        rows = []

        def read(ds, path):
            def job(a):
                s = a.FrameWork.Application.DataContext.GetDataSource(ds)
                if s is None:
                    return None, "data source None (not instantiated)"
                v = s.GetProperty(path)
                return (v if isinstance(v, str) else (None if v is None else str(v))), None
            try:
                return cd.call(job, 45, note=f"{ds}.{path}")
            except Exception as e:  # noqa: BLE001
                return None, str(e)[:200]

        for ds, path, cat, ui, req, tool in LISTS:      # cold: no document
            raw, err = read(ds, path)
            rows.append({"ds": ds, "path": path, "category": cat, "ui_path": ui, "requires": req, "tool": tool,
                         "context": "no document", "raw": (raw or "")[:20000], "error": err, "entries": parse_items(raw)})
        res["ds_lists"] = rows
        save(res)

        from testdoc import TestDoc
        td = TestDoc(cd)
        try:
            cd.call(lambda a: (td.doc.ClearSelection(), td.rect.CreateSelection()), 30)
            for row in rows:
                if row["entries"] or not row["tool"]:
                    continue
                def act(a, g=row["tool"]):
                    a.FrameWork.Automation.InvokeItem(g)
                    return True
                try:
                    cd.call(act, 45, note="tool " + row["category"])
                    time.sleep(1.0)
                except Exception as e:  # noqa: BLE001
                    row["tool_error"] = str(e)[:200]
                raw, err = read(row["ds"], row["path"])
                row.update(context="TestDoc, rectangle selected, tool active", raw=(raw or "")[:20000], error=err,
                           entries=parse_items(raw))
                save(res)
            cd.call(lambda a: a.FrameWork.Automation.InvokeItem("f1aee54d-c9aa-4e6f-9193-82f496b0b72b"), 30)  # Pick
        finally:
            print("closed testdoc", td.close())
        res["documents_at_end"] = cd.call(lambda a: [a.Documents.Item(i + 1).Title for i in range(a.Documents.Count)], 30)
        save(res)
    for r in res["ds_lists"]:
        print(f'{len(r["entries"]):4d} {r["ds"]}.{r["path"]}  {r.get("error") or ""}  {r["context"]}')


if __name__ == "__main__":
    main()
