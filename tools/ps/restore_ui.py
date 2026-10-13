"""Put Photoshop's panels / tool / screen mode back to what they were before the menu test run.
    python restore_ui.py   (target = panels visible in the first recorded snapshot of the run)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import psdrv  # noqa: E402

TARGET = ["Tools", "Move Options", "Color", "Layers"]  # visible before the run (snapshot 2026-10-04 16:5x)
MIT = {"Tools": "toggleToolsPalette", "Color": "toggleColorPalette", "Layers": "toggleLayersPalette",
       "Measurement Log": "toggleMeasurementLogPalette", "Character": "toggleCharacterPalette", "Paragraph": "toggleParagraphPalette",
       "Properties": "togglePropertiesPanel", "Adjustments": "toggleCreatePanel", "History": "toggleHistoryPalette",
       "Swatches": "toggleSwatchesPalette", "Channels": "toggleChannelsPalette", "Paths": "togglePathsPalette",
       "Navigator": "toggleNavigatorPalette", "Info": "toggleInfoPalette", "Histogram": "toggleHistogramPalette",
       "Actions": "toggleActionsPalette", "Styles": "toggleStylesPalette", "Gradients": "toggleGradientsPalette",
       "Patterns": "togglePatternsPalette", "Shapes": "toggleCustomShapesPalette", "Brushes": "toggleBrushPresetsPalette",
       "Brush Settings": "toggleBrushesPalette", "Clone Source": "toggleCloneSourcePalette", "Layer Comps": "toggleCompsPalette",
       "Notes": "toggleAnnotationPalette", "Tool Presets": "toggleToolPresetsPalette", "Character Styles": "toggleCharacterStylesPalette",
       "Paragraph Styles": "toggleParagraphStylesPalette"}
VIS = '''var pr = new ActionReference(); pr.putProperty(C2T("Prpr"), S2T("panelList")); pr.putEnumerated(C2T("capp"), C2T("Ordn"), C2T("Trgt"));
var pl = executeActionGet(pr).getList(S2T("panelList")), pv = [];
for (var i = 0; i < pl.count; i++) { var d = pl.getObjectValue(i); if (d.getBoolean(S2T("visible"))) pv.push(d.getString(S2T("name"))); } J(pv)'''


def visible():
    return psdrv.jsj(VIS, timeout=30)


if __name__ == "__main__":
    psdrv.js('app.displayDialogs = DialogModes.NO; try { app.runMenuItem(S2T("screenModeStandard")); } catch (e) {} try { app.currentTool = "moveTool"; } catch (e) {} app.displayDialogs = DialogModes.ERROR; 1', timeout=30)
    for _ in range(3):
        v = visible()
        todo = [p for p in TARGET if p not in v and p in MIT] + [p for p in v if p not in TARGET and p in MIT]
        if not todo:
            break
        for p in todo:
            try:
                psdrv.js('app.runMenuItem(S2T("%s")); 1' % MIT[p], timeout=20)
            except psdrv.PSError as e:
                print("could not toggle", p, str(e)[:100])
    print("visible now:", visible())
