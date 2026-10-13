"""Test plan for menu_invoke.py: per ps_menu id, the fixture state, setup and the candidate routes to try.
Candidates come from (1) hand-written AM / DOM calls below, (2) menuItemType labels -> runMenuItem,
(3) event labels -> executeAction (work/ps/menuinv/candidates.json, built by menu_candidates.py)."""
import json
from pathlib import Path
import os
PGD = Path(os.environ.get("PGD_HOME") or Path(__file__).resolve().parents[2])  # repo root; PGD_HOME overrides

H = (PGD / "harvest/ps/ps_menu.json")
C = json.loads((PGD / "work/ps/menuinv/candidates.json").read_text(encoding="utf-8"))
P = (PGD / "media/test_photo.png").as_posix()
SCR = "C:/Program Files/Adobe/Adobe Photoshop 2026/Presets/Scripts/"

SKIP_PREFIX = {
    "Help/": "opens a web page / help content (skipped by rule)", "Edit/Preferences/": "preferences (skipped by rule)",
    "File/Export/": "export (skipped by rule)", "Layer/Quick Export": "export (skipped by rule)", "Layer/Export As": "export (skipped by rule)",
    "File/Save": "save (skipped by rule)", "File/Close": "close (skipped by rule)", "File/Print": "print (skipped by rule)",
    "File/Exit": "quit (skipped by rule)", "File/Invite": "share (skipped by rule)", "File/Share": "share (skipped by rule)",
    "File/Search Adobe": "opens web content (skipped by rule)", "File/Place Free Adobe Stock": "opens web content (skipped by rule)",
    "File/Package": "writes files (save, skipped by rule)", "File/Automate/PDF Presentation": "export (skipped by rule)",
    "File/Automate/Create Droplet": "saves a droplet (skipped by rule)", "File/Browse in Bridge": "launches Bridge (another app)",
    "File/Open Recent": "clears the user's recent-file list (persistent user data)", "File/Import/WIA Support": "talks to a scanner/camera device",
    "Edit/Generative Fill": "generative (spends credits)", "Edit/Generate Image": "generative (spends credits)",
    "Image/Generative Upscale": "generative (spends credits)", "Layer/Harmonize": "generative (spends credits)",
    "Layer/Rasterize/Generative": "generative layer", "Edit/Search": "opens the Discover panel (web content)",
    "Edit/Remote Connections": "preferences-type network setting", "Edit/Presets/Migrate Presets": "migrates user presets (persistent)",
    "Window/Workspace/Reset Essentials": "resets the user's workspace layout (persistent UI)",
    "Window/Find Extensions": "opens web page", "Plugins/Browse Plugins": "opens the plugin marketplace (another app)",
    "Plugins/Manage Plugins": "opens Creative Cloud desktop (another app)", "Type/More from Adobe Fonts": "opens web page",
    "Type/Save Default Type Styles": "overwrites the user's default type styles (persistent)",
    "Layer/Smart Objects/Reveal in Explorer": "opens Windows Explorer (another app)",
    "Layer/Smart Objects/Export Contents": "export (skipped by rule)", "Layer/Smart Objects/Convert to Linked": "writes a file (save dialog)",
    "Edit/Define Brush Preset": None, "File/Scripts/Image Processor": "batch converter that saves files",
}


def mrun(x):
    return 'app.runMenuItem(S2T("%s"))' % x


def erun(x, d="new ActionDescriptor()", mode="DialogModes.NO"):
    return 'executeAction(S2T("%s"), %s, %s)' % (x, d, mode)


def M(x, **kw):
    return dict(how="runMenuItem(stringIDToTypeID('%s'))" % x, run=mrun(x), kind="ps_menu_cmd", key=x, **kw)


def E(x, d=None, how=None, mode="DialogModes.NO", **kw):
    run = erun(x, d or "new ActionDescriptor()", mode)
    return dict(how=how or ("executeAction(stringIDToTypeID('%s'), %s, %s)" % (x, "desc" if d else "new ActionDescriptor()", mode)),
                run=run, kind="ps_event", key=x, desc_js=d, **kw)


def D(code, how=None, **kw):
    return dict(how=how or code, run=code, kind="ps_dom", key=code, **kw)


def DLG(x, d=None, **kw):  # event run with DialogModes.ALL: confirmation = the command's own dialog opens
    return E(x, d, mode="DialogModes.ALL", how="executeAction(stringIDToTypeID('%s'), %s, DialogModes.ALL) (opens the dialog)" % (x, "desc" if d else "undefined"), dialog=True, **kw)


# descriptor builders (JS expressions)
def dn(ref):
    return '(function(){var d=new ActionDescriptor(); d.putReference(C2T("null"), %s); return d;})()' % ref


LYR = 'tref("Lyr ")'
DOCR = 'tref("Dcmn")'
FX = 'addFx()'
SELRECT = 'app.activeDocument.selection.select([[100,80],[300,80],[300,220],[100,220]])'
MASK = 'mkMask("revealAll")'
COPY = 'app.activeDocument.selection.selectAll(); app.activeDocument.selection.copy(); app.activeDocument.selection.deselect()'


def unit(k, u, v):
    return 'd.putUnitDouble(C2T("%s"), C2T("%s"), %s);' % (k, u, v)


def desc(body):
    return '(function(){var d=new ActionDescriptor(); %s return d;})()' % body


def sel_mod(ev, key, val):
    return E(ev, desc('d.putUnitDouble(S2T("%s"), C2T("#Pxl"), %s);' % (key, val)), state="selection")


ALIGN = {"1231": "ADSTops", "1233": "ADSCentersV", "1232": "ADSBottoms", "1234": "ADSLefts", "1236": "ADSCentersH", "1235": "ADSRights"}
DIST = {"1241": "ADSTops", "1243": "ADSCentersV", "1242": "ADSBottoms", "1245": "ADSLefts", "1247": "ADSCentersH", "1246": "ADSRights",
        "1249": "ADSDistH", "1239": "ADSDistV"}
AA = {"3370": "antiAliasNone", "3374": "antiAliasSharp", "3371": "antiAliasCrisp", "3372": "antiAliasStrong", "3373": "antiAliasSmooth",
      "3375": "antiAliasPlatformLCD", "3376": "antiAliasPlatformGray"}
PROOF = {"2803": "proofCMYK", "2804": "proofCyan", "2805": "proofMagenta", "2806": "proofYellow", "2807": "proofBlack", "2808": "proofCMY",
         "2809": "proofMacintosh", "2810": "proofWindows", "2811": "proofMonitor", "2802": "proofCustom"}
ARR = {"2711": "Frnt", "2712": "Nxt ", "2713": "Prvs", "2714": "Back"}
STACK = {"Entropy": "entr", "Kurtosis": "kurt", "Maximum": "maxx", "Mean": "avrg", "Median": "medn", "Minimum": "minn", "Range": "rang",
         "Skewness": "skew", "Standard Deviation": "stdv", "Summation": "summ", "Variance": "vari"}

MAN = {
    # File
    "10": [D('app.documents.add(UnitValue(300,"px"), UnitValue(200,"px"), 72, "pgd_mt_new")', state="doc")],
    "20": [D('app.open(new File("%s"))' % P)],
    "21": [D('app.open(new File("%s"), OpenDocumentType.PNG)' % P)],
    "22": [D('app.open(new File("%s"), undefined, true)' % P)],
    "24": [E("open", desc('d.putPath(C2T("null"), new File("%s")); d.putBoolean(S2T("openAsOCIO"), true);' % P))],
    "34": [E("revert", state="filled", pre='app.open(new File("%s")); app.activeDocument.artLayers.add()' % P)],
    "1032": [E("placeEvent", desc('d.putPath(C2T("null"), new File("%s"));' % P))],
    "3090": [E("placeEvent", desc('d.putPath(C2T("null"), new File("%s")); d.putBoolean(S2T("linked"), true);' % P))],
    "1180": [DLG("batch")],
    "File/Automate/Crop and Straighten Photos": [E("CropPhotos0001"), dict(how="executeAction(charIDToTypeID('gSCA'))", run='executeAction(C2T("gSCA"), new ActionDescriptor(), DialogModes.NO)', kind="ps_event", key="'gSCA'")],
    "File/Scripts/Delete All Empty Layers": [D('$.evalFile(new File("%sDelete All Empty Layers.jsx"))' % SCR, state="multi", pre='app.activeDocument.artLayers.add()')],
    "File/Scripts/Flatten All Layer Effects": [D('$.evalFile(new File("%sFlatten All Layer Effects.jsx"))' % SCR, state="filled", pre=FX)],
    "File/Scripts/Flatten All Masks": [D('$.evalFile(new File("%sFlatten All Masks.jsx"))' % SCR, state="filled", pre=MASK)],
    "File/Import/Notes": [DLG("importAnnots")],
    "6362": [DLG("importVideoToLayers")],
    # Edit
    "101": [E("undoEvent", state="filled")],
    "133": [E("undoEvent", state="filled", how="executeAction(stringIDToTypeID('undoEvent')) run twice (toggle test)",
              check='executeAction(S2T("undoEvent"), new ActionDescriptor(), DialogModes.NO); "after a second undoEvent: current history state = " + app.activeDocument.activeHistoryState.name + ", selection " + (function(){try{return String(app.activeDocument.selection.bounds)}catch(e){return "none"}})()')],
    "101b": [],
    "1961": [E("select", dn('(function(){var r=new ActionReference(); r.putEnumerated(C2T("HstS"), C2T("Ordn"), C2T("Prvs")); return r;})()'),
               how="executeAction(select, {null: historyState ordinal previous})", state="filled")],
    "1962": [E("select", dn('(function(){var r=new ActionReference(); r.putEnumerated(C2T("HstS"), C2T("Ordn"), C2T("Nxt ")); return r;})()'),
               how="executeAction(select, {null: historyState ordinal next})", state="filled", pre='executeAction(S2T("undoEvent"), new ActionDescriptor(), DialogModes.NO)')],
    "132": [E("select", dn('(function(){var r=new ActionReference(); r.putEnumerated(C2T("HstS"), C2T("Ordn"), C2T("Nxt ")); return r;})()'),
              how="executeAction(select, {null: historyState ordinal next}) (redo = step to the next history state)", state="filled",
              pre='executeAction(S2T("undoEvent"), new ActionDescriptor(), DialogModes.NO)')],
    "1154": [E("fade", desc(unit("Opct", "#Prc", 50) + ' d.putEnumerated(C2T("Md  "), C2T("BlnM"), C2T("Nrml"));'), state="filled",
               pre='executeAction(S2T("gaussianBlur"), (function(){var d=new ActionDescriptor(); d.putUnitDouble(S2T("radius"), C2T("#Pxl"), 8); return d;})(), DialogModes.NO)')],
    "103": [E("cut", state="selection")],
    "104": [E("copyEvent", state="selection", check='executeAction(S2T("paste"), new ActionDescriptor(), DialogModes.NO); "layers after paste: " + app.activeDocument.layers.length')],
    "1107": [E("copyMerged", state="selection", check='executeAction(S2T("paste"), new ActionDescriptor(), DialogModes.NO); "layers after paste: " + app.activeDocument.layers.length')],
    "105": [E("paste", state="filled", pre=COPY)],
    "1297": [E("paste", desc('d.putBoolean(S2T("inPlace"), true);'), state="filled", pre=COPY)],
    "1040": [E("pasteInto", state="filled", pre=COPY + "; " + SELRECT)],
    "5068": [E("pasteOutside", state="filled", pre=COPY + "; " + SELRECT)],
    "106": [E("clearEvent", state="selection"), D("app.activeDocument.selection.clear()", state="selection")],
    "3392": [DLG("spellCheck", state="text")],
    "3393": [DLG("findReplace", state="text")],
    "1042": [E("fill", desc('d.putEnumerated(C2T("Usng"), C2T("FlCn"), C2T("FrgC")); ' + unit("Opct", "#Prc", 100) + ' d.putEnumerated(C2T("Md  "), C2T("BlnM"), C2T("Nrml"));'), state="selection")],
    "1043": [E("stroke", desc('d.putInteger(C2T("Wdth"), 4); d.putEnumerated(C2T("Lctn"), C2T("StrL"), C2T("Insd")); ' + unit("Opct", "#Prc", 100)
                              + ' d.putEnumerated(C2T("Md  "), C2T("BlnM"), C2T("Nrml")); var c=new ActionDescriptor(); c.putDouble(C2T("Rd  "),0); c.putDouble(C2T("Grn "),0); c.putDouble(C2T("Bl  "),255); d.putObject(C2T("Clr "), C2T("RGBC"), c);'), state="selection"),
             D("app.activeDocument.selection.stroke(app.foregroundColor, 4)", state="selection")],
    "1510": [E("cafWorkspace", state="selection", timeout=60)],
    "2207": [E("transform", desc('d.putReference(C2T("null"), tref("Lyr ")); d.putEnumerated(C2T("FTcs"), C2T("QCSt"), C2T("Qcsa")); ' + unit("Wdth", "#Prc", 50) + unit("Hght", "#Prc", 50)), state="filled")],
    "2201": [E("transform", desc('d.putReference(C2T("null"), tref("Lyr ")); d.putEnumerated(C2T("FTcs"), C2T("QCSt"), C2T("Qcsa")); ' + unit("Wdth", "#Prc", 60) + unit("Hght", "#Prc", 60)), state="filled")],
    "2205": [E("transform", desc('d.putReference(C2T("null"), tref("Lyr ")); d.putEnumerated(C2T("FTcs"), C2T("QCSt"), C2T("Qcsa")); ' + unit("Angl", "#Ang", 30)), state="filled")],
    "2202": [E("transform", desc('d.putReference(C2T("null"), tref("Lyr ")); d.putEnumerated(C2T("FTcs"), C2T("QCSt"), C2T("Qcsa")); var s=new ActionDescriptor(); s.putUnitDouble(C2T("Hrzn"), C2T("#Ang"), 20); s.putUnitDouble(C2T("Vrtc"), C2T("#Ang"), 0); d.putObject(C2T("Skew"), C2T("Pnt "), s);'), state="filled")],
    "2208": [E("rotateEventEnum", desc('d.putReference(C2T("null"), tref("Lyr ")); ' + unit("Angl", "#Ang", 180)), state="filled")],
    "2209": [E("rotateEventEnum", desc('d.putReference(C2T("null"), tref("Lyr ")); ' + unit("Angl", "#Ang", 90)), state="filled")],
    "2210": [E("rotateEventEnum", desc('d.putReference(C2T("null"), tref("Lyr ")); ' + unit("Angl", "#Ang", -90)), state="filled")],
    "2211": [E("flip", desc('d.putReference(C2T("null"), tref("Lyr ")); d.putEnumerated(C2T("Axis"), C2T("Ornt"), C2T("Hrzn"));'), state="filled")],
    "2212": [E("flip", desc('d.putReference(C2T("null"), tref("Lyr ")); d.putEnumerated(C2T("Axis"), C2T("Ornt"), C2T("Vrtc"));'), state="filled")],
    "1237": [DLG("align", desc('d.putReference(C2T("null"), tref("Lyr ")); d.putEnumerated(C2T("Usng"), S2T("alignDistributeSelector"), S2T("ADSContent"));'), state="multi")],
    "1238": [E("mergeAlignedLayers", state="multi", timeout=60)],
    "2260": [DLG("skyReplacement", state="filled", timeout=30)],
    "1029": [DLG("defineBrush", state="selection")],
    "1038": [DLG("definePattern", state="selection")],
    "5624": [DLG("defineCustomShape", state="filled", pre='app.activeDocument.selection.select([[100,80],[300,80],[300,220],[100,220]]); app.activeDocument.selection.makeWorkPath(1)')],
    "2911": [D("app.purge(PurgeTarget.UNDOCACHES)", state="filled")],
    "2912": [D("app.purge(PurgeTarget.CLIPBOARDCACHE)", state="filled", pre=COPY)],
    "2361": [D("app.purge(PurgeTarget.HISTORYCACHES)", state="filled")],
    "2915": [D("app.purge(PurgeTarget.ALLCACHES)", state="filled")],
    "1212": [E("assignProfile", desc('d.putReference(C2T("null"), tref("Dcmn")); d.putString(S2T("profile"), "Adobe RGB (1998)");')),
             D('app.activeDocument.colorProfileName = "Adobe RGB (1998)"')],
    "1213": [E("convertToProfile", desc('d.putReference(C2T("null"), tref("Dcmn")); d.putString(C2T("T   "), "Adobe RGB (1998)");')),
             D('app.activeDocument.convertProfile("Adobe RGB (1998)", Intent.RELATIVECOLORIMETRIC, true, false)')],
    # Image
    "1006": [D('var o = new BitmapConversionOptions(); o.method = BitmapConversionType.HALFTHRESHOLD; o.resolution = 72; app.activeDocument.changeMode(ChangeMode.BITMAP, o)',
               state="doc", pre="app.activeDocument.changeMode(ChangeMode.GRAYSCALE)")],
    "1007": [E("convertMode", desc('d.putClass(C2T("T   "), C2T("Grys"));'), state="doc"), D("app.activeDocument.changeMode(ChangeMode.GRAYSCALE)", state="doc")],
    "1008": [DLG("convertMode", desc('d.putClass(C2T("T   "), C2T("DtnI"));'), state="doc", pre="app.activeDocument.changeMode(ChangeMode.GRAYSCALE)")],
    "1009": [D("var o = new IndexedConversionOptions(); o.palette = Palette.LOCALADAPTIVE; o.colors = 16; o.forced = ForcedColors.NONE; o.transparency = false; app.activeDocument.changeMode(ChangeMode.INDEXEDCOLOR, o)", state="doc")],
    "1010": [E("convertMode", desc('d.putClass(C2T("T   "), C2T("RGBM"));'), state="doc", pre="app.activeDocument.changeMode(ChangeMode.GRAYSCALE)")],
    "1011": [E("convertMode", desc('d.putClass(C2T("T   "), C2T("CMYM"));'), state="doc")],
    "1052": [E("convertMode", desc('d.putClass(C2T("T   "), C2T("LbCM"));'), state="doc")],
    "1014": [E("convertMode", desc('d.putClass(C2T("T   "), C2T("MltC"));'), state="doc")],
    "1161": [E("convertMode", desc('d.putInteger(C2T("Dpth"), 8);'), state="doc", pre="app.activeDocument.bitsPerChannel = BitsPerChannelType.SIXTEEN")],
    "1162": [E("convertMode", desc('d.putInteger(C2T("Dpth"), 16);'), state="doc")],
    "1206": [E("convertMode", desc('d.putInteger(C2T("Dpth"), 32);'), state="doc")],
    "1808": [E("levels", desc('d.putBoolean(S2T("auto"), true);'), state="filled", pre='app.activeDocument.activeLayer = app.activeDocument.backgroundLayer; app.activeDocument.selection.selectAll(); var c=new SolidColor(); c.rgb.red=120; c.rgb.green=110; c.rgb.blue=90; app.activeDocument.selection.fill(c); app.activeDocument.selection.deselect()')],
    "1810": [E("levels", desc('d.putBoolean(S2T("autoContrast"), true);'), state="filled", pre='app.activeDocument.activeLayer = app.activeDocument.backgroundLayer; app.activeDocument.selection.selectAll(); var c=new SolidColor(); c.rgb.red=120; c.rgb.green=110; c.rgb.blue=90; app.activeDocument.selection.fill(c); app.activeDocument.selection.deselect()')],
    "1817": [E("levels", desc('d.putBoolean(S2T("autoBlackWhite"), true); d.putBoolean(S2T("autoNeutrals"), true);'), state="filled", pre='app.activeDocument.activeLayer = app.activeDocument.backgroundLayer; app.activeDocument.selection.selectAll(); var c=new SolidColor(); c.rgb.red=120; c.rgb.green=110; c.rgb.blue=90; app.activeDocument.selection.fill(c); app.activeDocument.selection.deselect()')],
    "1030": [E("imageSize", desc(unit("Wdth", "#Pxl", 200) + ' d.putBoolean(S2T("constrainProportions"), true); d.putEnumerated(C2T("Intr"), C2T("Intp"), C2T("Bcbc"));')),
             D('app.activeDocument.resizeImage(UnitValue(200,"px"), UnitValue(150,"px"))')],
    "1031": [E("canvasSize", desc(unit("Wdth", "#Pxl", 500) + unit("Hght", "#Pxl", 400) + ' d.putEnumerated(C2T("Hrzn"), C2T("HrzL"), C2T("Cntr")); d.putEnumerated(C2T("Vrtc"), C2T("VrtL"), C2T("Cntr"));')),
             D('app.activeDocument.resizeCanvas(UnitValue(500,"px"), UnitValue(400,"px"), AnchorPosition.MIDDLECENTER)')],
    "2993": [E("rotateEventEnum", desc('d.putReference(C2T("null"), tref("Dcmn")); ' + unit("Angl", "#Ang", 180))), D("app.activeDocument.rotateCanvas(180)")],
    "2991": [E("rotateEventEnum", desc('d.putReference(C2T("null"), tref("Dcmn")); ' + unit("Angl", "#Ang", 90))), D("app.activeDocument.rotateCanvas(90)")],
    "2992": [E("rotateEventEnum", desc('d.putReference(C2T("null"), tref("Dcmn")); ' + unit("Angl", "#Ang", -90))), D("app.activeDocument.rotateCanvas(-90)")],
    "2994": [E("rotateEventEnum", desc('d.putReference(C2T("null"), tref("Dcmn")); ' + unit("Angl", "#Ang", 30))), D("app.activeDocument.rotateCanvas(30)")],
    "2996": [E("flip", desc('d.putReference(C2T("null"), tref("Dcmn")); d.putEnumerated(C2T("Axis"), C2T("Ornt"), C2T("Hrzn"));')), D("app.activeDocument.flipCanvas(Direction.HORIZONTAL)")],
    "2997": [E("flip", desc('d.putReference(C2T("null"), tref("Dcmn")); d.putEnumerated(C2T("Axis"), C2T("Ornt"), C2T("Vrtc"));')), D("app.activeDocument.flipCanvas(Direction.VERTICAL)")],
    "1044": [E("crop", desc('d.putBoolean(C2T("Dlt "), true);'), state="selection")],
    "1080": [E("trim", desc('d.putEnumerated(S2T("trimBasedOn"), S2T("trimBasedOn"), S2T("transparency")); d.putBoolean(C2T("Top "), true); d.putBoolean(C2T("Btom"), true); d.putBoolean(C2T("Left"), true); d.putBoolean(C2T("Rght"), true);'),
               state="filled", pre="app.activeDocument.backgroundLayer.remove()")],
    "1081": [E("revealAll", state="filled", pre='app.activeDocument.activeLayer.translate(UnitValue(300,"px"), UnitValue(0,"px"))')],
    "1134": [E("duplicate", dn(DOCR)), D("app.activeDocument.duplicate()")],
    "1153": [DLG("applyImageEvent", state="filled")],
    "1093": [E("trap", desc(unit("Wdth", "#Pxl", 2)), state="filled", pre="app.activeDocument.changeMode(ChangeMode.CMYK)")],
    # Layer
    "1099": [E("make", dn('(function(){var r=new ActionReference(); r.putClass(C2T("Lyr ")); return r;})()'), how="executeAction(make, {null: class layer})")],
    "1942": [E("set", desc('var r=new ActionReference(); r.putProperty(C2T("Lyr "), C2T("Bckg")); d.putReference(C2T("null"), r); var l=new ActionDescriptor(); ' + unit("Opct", "#Prc", 100).replace("d.put", "l.put") + ' l.putEnumerated(C2T("Md  "), C2T("BlnM"), C2T("Nrml")); d.putObject(C2T("T   "), C2T("Lyr "), l);'),
               how="executeAction(set, {null: layer property background, to: layer{opacity, mode}})", state="doc"),
             D("app.activeDocument.backgroundLayer.isBackgroundLayer = false", state="doc")],
    "2976": [E("make", dn('(function(){var r=new ActionReference(); r.putClass(S2T("layerSection")); return r;})()'), how="executeAction(make, {null: class layerSection})")],
    "2956": [E("make", desc('var r=new ActionReference(); r.putClass(S2T("layerSection")); d.putReference(C2T("null"), r); d.putReference(C2T("From"), tref("Lyr "));'),
               how="executeAction(make, {null: class layerSection, from: target layer})", state="multi")],
    "9221": [M("artboardFromLayerGroupEvent", state="group"), E("artboardFromLayerGroupEvent", dn(LYR), state="group")],
    "9252": [M("framedGroupFromLayersEvent", state="filled"), E("framedGroupFromLayersEvent", dn(LYR), state="filled")],
    "9255": [M("convertToFramedGroupEvent", state="text")],
    "1135": [E("duplicate", dn(LYR))],
    "1100": [E("delete", dn(LYR))],
    "2951": [E("delete", dn('(function(){var r=new ActionReference(); r.putEnumerated(C2T("Lyr "), C2T("Ordn"), C2T("Hddn")); return r;})()'),
               how="executeAction(delete, {null: layer ordinal hidden})", state="multi", pre='app.activeDocument.artLayers.getByName("px2").visible = false')],
    "2983": [E("set", desc('d.putReference(C2T("null"), tref("Lyr ")); var l=new ActionDescriptor(); l.putString(C2T("Nm  "), "renamed"); d.putObject(C2T("T   "), C2T("Lyr "), l);'),
               how="executeAction(set, {null: target layer, to: layer{name}})")],
    "1314": [E("copyEffects", state="filled", pre=FX, check='selLayers(["Background"]); executeAction(S2T("pasteEffects"), new ActionDescriptor(), DialogModes.NO); "pasted onto background: " + layerRow(0)')],
    "1315": [E("pasteEffects", state="multi", pre='selLayers(["px1"]); ' + FX + '; executeAction(S2T("copyEffects"), new ActionDescriptor(), DialogModes.NO); selLayers(["px2"])')],
    "1339": [E("disableLayerStyle", state="filled", pre=FX)],
    "1348": [E("disableLayerFX", state="filled", pre=FX)],
    "1306": [E("set", desc('var r=new ActionReference(); r.putProperty(C2T("Prpr"), C2T("lfxv")); r.putEnumerated(C2T("Dcmn"), C2T("Ordn"), C2T("Trgt")); d.putReference(C2T("null"), r); var t=new ActionDescriptor(); t.putBoolean(C2T("lfxv"), false); d.putObject(C2T("T   "), C2T("lfxv"), t);'),
               how="executeAction(set, {null: document property layerFXVisible, to: {layerFXVisible: false}})", state="filled", pre=FX)],
    "1327": [E("scaleEffectsEvent", desc(unit("Scl ", "#Prc", 50)), state="filled", pre=FX)],
    "1308": [E("make", desc('var r=new ActionReference(); r.putClass(C2T("Lyr ")); d.putReference(C2T("null"), r); var u=new ActionReference(); u.putProperty(C2T("Prpr"), S2T("layerEffects")); u.putEnumerated(C2T("Lyr "), C2T("Ordn"), C2T("Trgt")); d.putReference(C2T("Usng"), u);'),
               how="executeAction(make, {null: class layer, using: target layer's layerEffects})", state="filled", pre=FX)],
    "2770": [E("delete", dn('(function(){var r=new ActionReference(); r.putClass(S2T("filterFX")); r.putEnumerated(C2T("Lyr "), C2T("Ordn"), C2T("Trgt")); return r;})()'),
               how="executeAction(delete, {null: class filterFX of target layer})", state="smart", pre='executeAction(S2T("gaussianBlur"), (function(){var d=new ActionDescriptor(); d.putUnitDouble(S2T("radius"), C2T("#Pxl"), 4); return d;})(), DialogModes.NO)')],
    "2769": [E("set", desc('var r=new ActionReference(); r.putEnumerated(C2T("Lyr "), C2T("Ordn"), C2T("Trgt")); d.putReference(C2T("null"), r); var l=new ActionDescriptor(); l.putBoolean(S2T("filterFXVisible"), false); d.putObject(C2T("T   "), C2T("Lyr "), l);'),
               how="executeAction(set, {null: target layer, to: layer{filterFXVisible: false}})", state="smart", pre='executeAction(S2T("gaussianBlur"), (function(){var d=new ActionDescriptor(); d.putUnitDouble(S2T("radius"), C2T("#Pxl"), 4); return d;})(), DialogModes.NO)')],
    "5226": [E("delete", dn('(function(){var r=new ActionReference(); r.putEnumerated(C2T("Chnl"), C2T("Chnl"), S2T("filterMask")); return r;})()'),
               how="executeAction(delete, {null: channel filterMask})", state="smart", pre='executeAction(S2T("gaussianBlur"), (function(){var d=new ActionDescriptor(); d.putUnitDouble(S2T("radius"), C2T("#Pxl"), 4); return d;})(), DialogModes.NO)')],
    "3076": [E("set", desc('d.putReference(C2T("null"), tref("Lyr ")); var l=new ActionDescriptor(); l.putBoolean(S2T("filterMaskEnable"), false); d.putObject(C2T("T   "), C2T("Lyr "), l);'),
               how="executeAction(set, {null: target layer, to: layer{filterMaskEnable: false}})", state="smart", pre='executeAction(S2T("gaussianBlur"), (function(){var d=new ActionDescriptor(); d.putUnitDouble(S2T("radius"), C2T("#Pxl"), 4); return d;})(), DialogModes.NO)')],
    "6300": [E("make", desc('var r=new ActionReference(); r.putClass(S2T("contentLayer")); d.putReference(C2T("null"), r); var u=new ActionDescriptor(); var t=new ActionDescriptor(); var c=new ActionDescriptor(); c.putDouble(C2T("Rd  "),255); c.putDouble(C2T("Grn "),128); c.putDouble(C2T("Bl  "),0); t.putObject(C2T("Clr "), C2T("RGBC"), c); u.putObject(C2T("Type"), S2T("solidColorLayer"), t); d.putObject(C2T("Usng"), S2T("contentLayer"), u);'),
               how="executeAction(make, {null: class contentLayer, using: contentLayer{type: solidColorLayer{color}}})")],
    "6301": [E("make", desc('var r=new ActionReference(); r.putClass(S2T("contentLayer")); d.putReference(C2T("null"), r); var u=new ActionDescriptor(); u.putObject(C2T("Type"), S2T("gradientLayer"), new ActionDescriptor()); d.putObject(C2T("Usng"), S2T("contentLayer"), u);'),
               how="executeAction(make, {null: class contentLayer, using: contentLayer{type: gradientLayer{}}})")],
    "6302": [E("make", desc('var r=new ActionReference(); r.putClass(S2T("contentLayer")); d.putReference(C2T("null"), r); var u=new ActionDescriptor(); u.putObject(C2T("Type"), S2T("patternLayer"), new ActionDescriptor()); d.putObject(C2T("Usng"), S2T("contentLayer"), u);'),
               how="executeAction(make, {null: class contentLayer, using: contentLayer{type: patternLayer{}}})")],
    "1103": [M("adjustmentOptions", state="filled", pre='executeAction(S2T("make"), (function(){var d=new ActionDescriptor(); var r=new ActionReference(); r.putClass(S2T("contentLayer")); d.putReference(C2T("null"), r); var u=new ActionDescriptor(); var t=new ActionDescriptor(); var c=new ActionDescriptor(); c.putDouble(C2T("Rd  "),255); c.putDouble(C2T("Grn "),128); c.putDouble(C2T("Bl  "),0); t.putObject(C2T("Clr "), C2T("RGBC"), c); u.putObject(C2T("Type"), S2T("solidColorLayer"), t); d.putObject(C2T("Usng"), S2T("contentLayer"), u); return d;})(), DialogModes.NO)')],
    "1157": [E("make", "mkMaskDesc('revealAll')", how="executeAction(make, {new: channel, at: mask, using: userMaskEnabled revealAll})")],
    "1156": [E("make", "mkMaskDesc('hideAll')", how="executeAction(make, {new: channel, at: mask, using: userMaskEnabled hideAll})")],
    "1158": [E("make", "mkMaskDesc('revealSelection')", how="executeAction(make, {new: channel, at: mask, using: userMaskEnabled revealSelection})", state="selection")],
    "1168": [E("make", "mkMaskDesc('hideSelection')", how="executeAction(make, {new: channel, at: mask, using: userMaskEnabled hideSelection})", state="selection")],
    "1292": [E("make", "mkMaskDesc('transparent')", how="executeAction(make, {new: channel, at: mask, using: userMaskEnabled transparent})")],
    "5059": [E("delete", dn('(function(){var r=new ActionReference(); r.putEnumerated(C2T("Chnl"), C2T("Chnl"), C2T("Msk ")); return r;})()'),
               how="executeAction(delete, {null: channel mask})", pre=MASK)],
    "5095": [E("delete", desc('var r=new ActionReference(); r.putEnumerated(C2T("Chnl"), C2T("Chnl"), C2T("Msk ")); d.putReference(C2T("null"), r); d.putBoolean(C2T("Aply"), true);'),
               how="executeAction(delete, {null: channel mask, apply: true})", pre=MASK)],
    "1159": [E("set", desc('d.putReference(C2T("null"), tref("Lyr ")); var l=new ActionDescriptor(); l.putBoolean(S2T("userMaskEnabled"), false); d.putObject(C2T("T   "), C2T("Lyr "), l);'),
               how="executeAction(set, {null: target layer, to: layer{userMaskEnabled: false}})", pre=MASK), M("toggleLayerMask", pre=MASK)],
    "5085": [E("set", desc('d.putReference(C2T("null"), tref("Lyr ")); var l=new ActionDescriptor(); l.putBoolean(S2T("userMaskLinked"), false); d.putObject(C2T("T   "), C2T("Lyr "), l);'),
               how="executeAction(set, {null: target layer, to: layer{userMaskLinked: false}})", pre=MASK)],
    "1954": [M("vectorMaskRevealAll")],
    "1953": [M("vectorMaskHideAll")],
    "1955": [M("vectorMaskCurrentPath", pre=SELRECT + "; app.activeDocument.selection.makeWorkPath(1)")],
    "1956": [M("discardVectorMask", pre='app.runMenuItem(S2T("vectorMaskRevealAll"))')],
    "1959": [M("toggleVectorMask", pre='app.runMenuItem(S2T("vectorMaskRevealAll"))')],
    "2109": [E("set", desc('d.putReference(C2T("null"), tref("Lyr ")); var l=new ActionDescriptor(); l.putBoolean(S2T("vectorMaskLinked"), false); d.putObject(C2T("T   "), C2T("Lyr "), l);'),
               how="executeAction(set, {null: target layer, to: layer{vectorMaskLinked: false}})", pre='app.runMenuItem(S2T("vectorMaskRevealAll"))')],
    "2972": [E("groupEvent", dn(LYR), state="multi", pre='selLayers(["px2"])')],
    "22100": [E("autoMaskGenerate", state="filled", timeout=90)],
    "6343": [M("placedLayerUpdateAllModified", state="smart"), E("placedLayerUpdateAllModified", state="smart")],
    "6342": [M("placedLayerUpdateModified", state="smart")],
    "6332": [E("placedLayerEditContents", state="smart")],
    "6347": [M("placedLayerResetTransforms", state="smart", pre='app.activeDocument.activeLayer.resize(50, 50)'), E("placedLayerResetTransforms", state="smart", pre='app.activeDocument.activeLayer.resize(50, 50)')],
    "6340": [DLG("placedLayerRelinkToFile", state="smart")],
    "6333": [E("placedLayerReplaceContents", desc('d.putPath(C2T("null"), new File("%s"));' % P), state="smart")],
    "6345": [E("placedLayerConvertToEmbedded", state="filled", pre='executeAction(S2T("placeEvent"), (function(){var d=new ActionDescriptor(); d.putPath(C2T("null"), new File("%s")); d.putBoolean(S2T("linked"), true); return d;})(), DialogModes.NO)' % P)],
    "6346": [E("placedLayerEmbedAll", state="filled", pre='executeAction(S2T("placeEvent"), (function(){var d=new ActionDescriptor(); d.putPath(C2T("null"), new File("%s")); d.putBoolean(S2T("linked"), true); return d;})(), DialogModes.NO)' % P)],
    "21000": [E("placedLayerConvertToLayers", state="smart")],
    "6432": [E("imageStackConvertSmartObject", state="smart", pre='executeAction(S2T("applyImageStackPluginRenderer"), (function(){var d=new ActionDescriptor(); d.putClass(S2T("imageStackPlugin"), C2T("maxx")); d.putString(C2T("Nm  "), "Maximum"); return d;})(), DialogModes.NO)')],
    "Layer/Smart Objects/Rasterize": [E("rasterizeLayer", desc('d.putReference(C2T("null"), tref("Lyr ")); d.putEnumerated(C2T("What"), S2T("rasterizeItem"), S2T("placed"));'), state="smart"),
                                      E("rasterizePlaced", state="smart")],
    "Layer/Rasterize/Smart Object": [E("rasterizeLayer", desc('d.putReference(C2T("null"), tref("Lyr ")); d.putEnumerated(C2T("What"), S2T("rasterizeItem"), S2T("placed"));'), state="smart")],
    "Layer/Rasterize/Type": [E("rasterizeLayer", desc('d.putReference(C2T("null"), tref("Lyr ")); d.putEnumerated(C2T("What"), S2T("rasterizeItem"), S2T("type"));'), state="text")],
    "Type/Rasterize Type Layer": [E("rasterizeTypeLayer", dn(LYR), state="text"), M("rasterizeTypeLayer", state="text")],
    "3541": [E("rasterizeLayer", desc('d.putReference(C2T("null"), tref("Lyr ")); d.putEnumerated(C2T("What"), S2T("rasterizeItem"), S2T("shape"));'), state="text", pre='executeAction(S2T("convertToShape"), new ActionDescriptor(), DialogModes.NO); app.runMenuItem(S2T("convertToShape"))')],
    "3544": [E("rasterizeLayer", desc('d.putReference(C2T("null"), tref("Lyr ")); d.putEnumerated(C2T("What"), S2T("rasterizeItem"), S2T("content"));'), state="filled", pre='executeAction(S2T("make"), (function(){var d=new ActionDescriptor(); var r=new ActionReference(); r.putClass(S2T("contentLayer")); d.putReference(C2T("null"), r); var u=new ActionDescriptor(); var t=new ActionDescriptor(); var c=new ActionDescriptor(); c.putDouble(C2T("Rd  "),255); c.putDouble(C2T("Grn "),128); c.putDouble(C2T("Bl  "),0); t.putObject(C2T("Clr "), C2T("RGBC"), c); u.putObject(C2T("Type"), S2T("solidColorLayer"), t); d.putObject(C2T("Usng"), S2T("contentLayer"), u); return d;})(), DialogModes.NO)')],
    "1957": [E("rasterizeLayer", desc('d.putReference(C2T("null"), tref("Lyr ")); d.putEnumerated(C2T("What"), S2T("rasterizeItem"), S2T("vectorMask"));'), pre='app.runMenuItem(S2T("vectorMaskRevealAll"))'), M("rasterizeVectorMask", pre='app.runMenuItem(S2T("vectorMaskRevealAll"))')],
    "3557": [E("rasterizeLayer", desc('d.putReference(C2T("null"), tref("Lyr ")); d.putEnumerated(C2T("What"), S2T("rasterizeItem"), S2T("layerStyle"));'), pre=FX)],
    "3547": [E("rasterizeLayer", dn(LYR), state="text")],
    "3545": [E("rasterizeAll", state="text")],
    "6352": [E("addBlankVideoLayer", state="filled")],
    "5217": [M("sliceFromLayer", state="filled")],
    "2958": [E("make", desc('var r=new ActionReference(); r.putClass(S2T("layerSection")); d.putReference(C2T("null"), r); d.putReference(C2T("From"), tref("Lyr "));'),
               how="executeAction(make, {null: class layerSection, from: target layer})", state="filled"), E("groupLayersEvent", dn(LYR), state="filled")],
    "2959": [E("ungroupLayersEvent", dn(LYR), state="group")],
    "1114": [E("hide", desc('var l=new ActionList(); l.putReference(tref("Lyr ")); d.putList(C2T("null"), l);'), how="executeAction(hide, {null: [target layer]})")],
    "2715": [E("reverse", dn(LYR), state="multi")],
    "2957": [E("applyLocking", desc('d.putReference(C2T("null"), tref("Lyr ")); var lk=new ActionDescriptor(); lk.putBoolean(S2T("protectAll"), true); d.putObject(S2T("layerLocking"), S2T("layerLocking"), lk);'))],
    "2961": [E("linkSelectedLayers", state="multi"),
             dict(how="executeAction(charIDToTypeID('Lnk '), {null: target layers})", run='executeAction(C2T("Lnk "), %s, DialogModes.NO)' % dn(LYR),
                  kind="ps_event", key="link", desc_js=dn(LYR), state="multi")],
    "2960": [E("selectLinkedLayers", dn(LYR), state="multi", pre='executeAction(S2T("linkSelectedLayers"), new ActionDescriptor(), DialogModes.NO); selLayers(["px1"])')],
    "1166": [E("mergeLayersNew", state="multi")],
    "1037": [E("defringe", desc(unit("Wdth", "#Pxl", 2)), state="filled")],
    "2701": [E("removeBlackMatte", state="filled")],
    "2703": [E("removeWhiteMatte", state="filled")],
    # Type
    "1223": [M("horizontal", state="text", pre='app.activeDocument.activeLayer.textItem.direction = Direction.VERTICAL')],
    "1224": [M("vertical", state="text")],
    "1228": [M("createWorkPath", state="text")],
    "1229": [M("convertToShape", state="text")],
    "3382": [M("toggleTextLayerType", state="text")],
    "3390": [E("updateLayouts", state="text")],
    "9121": [E("textLoadDefaultTypeStyles", state="text")],
    # Select
    "1017": [E("set", desc('d.putReference(C2T("null"), selRef()); d.putEnumerated(C2T("T   "), C2T("Ordn"), C2T("Al  "));'), how="executeAction(set, {null: selection, to: ordinal all})")],
    "1016": [E("set", desc('d.putReference(C2T("null"), selRef()); d.putEnumerated(C2T("T   "), C2T("Ordn"), C2T("None"));'), how="executeAction(set, {null: selection, to: ordinal none})", state="selection")],
    "1943": [E("set", desc('d.putReference(C2T("null"), selRef()); d.putEnumerated(C2T("T   "), C2T("Ordn"), C2T("Prvs"));'), how="executeAction(set, {null: selection, to: ordinal previous})", state="selection",
               pre="app.activeDocument.selection.deselect()")],
    "1018": [E("inverse", state="selection")],
    "2962": [E("selectAllLayers", dn(LYR), state="multi", pre='selLayers(["px1"])')],
    "2963": [E("selectNoLayers", dn(LYR), state="multi")],
    "1152": [E("colorRange", desc('d.putInteger(C2T("Fzns"), 40); d.putEnumerated(C2T("Clrs"), C2T("Clrs"), C2T("Rds "));'))],
    "1460": [E("focusMask", timeout=60)],
    "1461": [E("autoCutout", desc('d.putBoolean(S2T("sampleAllLayers"), false);'), timeout=90)],
    "1462": [E("selectSky", timeout=90)],
    "1115": [E("refineSelectionEdge", state="selection", timeout=30)],
    "1035": [E("border", desc(unit("Wdth", "#Pxl", 10)), state="selection")],
    "1108": [sel_mod("smoothness", "radius", 20)],
    "1109": [sel_mod("expand", "by", 10)],
    "1110": [sel_mod("contract", "by", 10)],
    "1036": [sel_mod("feather", "radius", 5)],
    "1033": [E("grow", desc('d.putInteger(C2T("Tlrn"), 32); d.putBoolean(C2T("AntA"), true);'), state="filled", pre="app.activeDocument.selection.select([[60,60],[80,60],[80,80],[60,80]])")],
    "1034": [E("similar", desc('d.putInteger(C2T("Tlrn"), 32); d.putBoolean(C2T("AntA"), true);'), state="filled", pre="app.activeDocument.selection.select([[60,60],[80,60],[80,80],[60,80]])")],
    "1971": [E("transform", desc('d.putReference(C2T("null"), selRef()); d.putEnumerated(C2T("FTcs"), C2T("QCSt"), C2T("Qcsa")); ' + unit("Wdth", "#Prc", 50) + unit("Hght", "#Prc", 50)),
               how="executeAction(transform, {null: selection, width/height %})", state="selection")],
    "5069": [M("toggleQuickMaskMode", toggle=True)],
    "1200": [E("set", desc('d.putReference(C2T("null"), selRef()); var t=new ActionReference(); t.putName(C2T("Chnl"), "pgdsel"); d.putReference(C2T("T   "), t);'),
               how="executeAction(set, {null: selection, to: channel by name})", state="selection",
               pre='executeAction(S2T("duplicate"), (function(){var d=new ActionDescriptor(); d.putReference(C2T("null"), selRef()); d.putString(C2T("Nm  "), "pgdsel"); return d;})(), DialogModes.NO); app.activeDocument.selection.deselect()')],
    "1281": [E("duplicate", desc('d.putReference(C2T("null"), selRef()); d.putString(C2T("Nm  "), "pgdsel");'), how="executeAction(duplicate, {null: selection, name})", state="selection")],
    # View
    "1284": [M("flipViewHorizontal", toggle=True)],
    "1285": [M("patternPreviewMode", toggle=True)],
    "3500": [M("toggleShowExtras", toggle=True)],
    "3501": [M("toggleEdges", toggle=True, state="selection")],
    "3502": [M("togglePaths", toggle=True, pre=SELRECT + "; app.activeDocument.selection.makeWorkPath(1)")],
    "3503": [M("toggleGuides", toggle=True, pre='app.activeDocument.guides.add(Direction.VERTICAL, UnitValue(100,"px"))')],
    "3513": [M("toggleCount", toggle=True)],
    "3506": [M("toggleAnnots", toggle=True)],
    "3507": [M("showAll", post_run=mrun("showAll"))],
    "3508": [M("showNone", post_run=mrun("showAll"))],
    "3527": [M("snapAll", post_run=mrun("snapNone"))],
    "3528": [M("snapNone")],
    "3522": [M("snapToGrid", toggle=True)],
    "3523": [M("snapToSlices", toggle=True)],
    "2950": [M("clearGuides", pre='app.activeDocument.guides.add(Direction.VERTICAL, UnitValue(100,"px"))')],
    "5613": [E("make", desc('var g=new ActionDescriptor(); g.putUnitDouble(C2T("Pstn"), C2T("#Pxl"), 100); g.putEnumerated(C2T("Ornt"), C2T("Ornt"), C2T("Vrtc")); d.putObject(C2T("Nw  "), C2T("Gd  "), g);'),
               how="executeAction(make, {new: guide{position, orientation}})"), M("newGuide")],
    "5614": [E("newGuideLayout", timeout=20), M("newGuideLayout")],
    "5615": [E("newGuidesFromTarget")],
    "6400": [M("hdrOptions", state="doc", pre="app.activeDocument.bitsPerChannel = BitsPerChannelType.THIRTYTWO")],
    "1001": [M("newView")],
    "21001": [M("fitLayersOnScreen", pre='app.runMenuItem(S2T("zoomIn")); app.runMenuItem(S2T("zoomIn"))')],
    "1192": [M("fitOnScreen", pre='app.runMenuItem(S2T("zoomIn")); app.runMenuItem(S2T("zoomIn"))')],
    "1004": [M("zoomIn")], "1005": [M("zoomOut")], "1190": [M("actualPixels", pre='app.runMenuItem(S2T("zoomIn"))')],
    "1299": [M("view200Percent")], "1191": [M("printSize")],
    "5991": [M("screenModeStandard", pre=mrun("screenModeFullScreenWithMenubar"))],
    "5992": [M("screenModeFullScreenWithMenubar", post_run=mrun("screenModeStandard"))],
    "5993": [M("screenModeFullScreen", post_run=mrun("screenModeStandard"))],
    # Window
    "5933": [M("tileVertically", pre='newDoc("pgd_mt_b", 200, 200); activate("pgd_mt")')],
    "5934": [M("tileHorizontally", pre='newDoc("pgd_mt_b", 200, 200); activate("pgd_mt")')],
    "5931": [M("tile", pre='newDoc("pgd_mt_b", 200, 200); activate("pgd_mt")')],
    "1188": [M("timeline", toggle=True)],
    "4210": [M("toggleToolPresetsPalette", toggle=True)],
    # Help (safe dialogs)
    "1": [M("aboutApp")],
}
for k, v in ALIGN.items():
    MAN[k] = [E("align", desc('d.putReference(C2T("null"), tref("Lyr ")); d.putEnumerated(C2T("Usng"), S2T("alignDistributeSelector"), S2T("%s")); d.putBoolean(S2T("alignToCanvas"), false);' % v), state="multi")]
for k, v in DIST.items():
    MAN[k] = [dict(how="executeAction(charIDToTypeID('Dstr'), {null: target layers, using: alignDistributeSelector %s})" % v,
                   run='executeAction(C2T("Dstr"), %s, DialogModes.NO)' % desc('d.putReference(C2T("null"), tref("Lyr ")); d.putEnumerated(C2T("Usng"), S2T("alignDistributeSelector"), S2T("%s"));' % v),
                   kind="ps_event", key="'Dstr'", desc_js="", state="multi3")]
for k, v in AA.items():
    pre = 'app.activeDocument.activeLayer.textItem.antiAliasMethod = AntiAlias.%s' % ("SHARP" if v == "antiAliasNone" else "NONE")
    MAN[k] = [M(v, state="text", pre=pre)]
for k, v in PROOF.items():
    MAN[k] = [M(v, post_run=mrun("proofCMYK"), pre=mrun("proofCyan") if v == "proofCMYK" else "")]
for k, v in ARR.items():
    MAN[k] = [E("move", desc('d.putReference(C2T("null"), tref("Lyr ")); var t=new ActionReference(); t.putEnumerated(C2T("Lyr "), C2T("Ordn"), C2T("%s")); d.putReference(C2T("T   "), t);' % v),
                how="executeAction(move, {null: target layer, to: layer ordinal %s})" % v.strip(), state="multi",
                pre='selLayers(["%s"])' % ("px1" if v in ("Frnt", "Nxt ") else "px2"))]
MAN["2714"].append(E("move", desc('d.putReference(C2T("null"), tref("Lyr ")); var t=new ActionReference(); t.putEnumerated(C2T("Lyr "), C2T("Ordn"), C2T("Bckw")); d.putReference(C2T("T   "), t);'),
                     how="executeAction(move, {null: target layer, to: layer ordinal Bckw})", state="multi", pre='selLayers(["px2"])'))
for name, code in STACK.items():
    MAN["Layer/Smart Objects/Stack Mode/" + name] = [dict(
        how="executeAction(stringIDToTypeID('applyImageStackPluginRenderer'), {imageStackPlugin: class '%s', name: '%s'})" % (code, name),
        run=erun("applyImageStackPluginRenderer", desc('d.putClass(S2T("imageStackPlugin"), C2T("%s")); d.putString(C2T("Nm  "), "%s");' % (code, name))),
        kind="ps_event", key="applyImageStackPluginRenderer", state="smart")]

TOGGLE_PREFIX = ("toggle", "snap")
# label matches that name a different command (checked by hand): never tried
DROP = {"View/Snap To/Guides": {"toggleGuides"}, "View/Snap To/Grid": {"toggleGrid", "toggleSnapToGrid"},
        "View/Snap To/Layers": {"toggleLayersPalette"}, "View/Snap To/Slices": {"toggleSlices"},
        "File/Import/Notes": {"toggleAnnots", "toggleAnnotationPalette"}, "View/Show/Notes": {"toggleAnnotationPalette"},
        "Edit/Keyboard Shortcuts": {"timelineEnableShortcutKeys"}, "Layer/Smart Objects/Reset Transform": {"cloneSourceResetTransform"},
        "Layer/Rasterize/3D": {"toggle3DPanel"}, "Layer/Rasterize/Vector Mask": {"toggleVectorMask"},
        "Edit/Paste": {"animationPasteFrames"}, "Window/OpenColorIO": {"adjustmentLayerOCIOAdjustment"},
        "Layer/Video Layers/Rasterize": {"rasterizeLayer"}, "Layer/Smart Objects/Rasterize": {"rasterizeAllPlaced"},
        "Layer/New Fill Layer/Gradient": {"gradientClassEvent"}}


def build():
    items = json.loads(H.read_text(encoding="utf-8"))["items"]
    plan = {}
    for it in items:
        cid, path = it["id"], it["path"]
        skip = next((r for p, r in SKIP_PREFIX.items() if path.startswith(p) and r), None)
        st = it["extra"].get("enabled_in_state") or {}
        state = next((s for s in ("filled", "doc", "selection", "text", "smart", "group", "multi") if st.get(s)), "filled")
        cands = list(MAN.get(cid, []))
        c = C.get(cid, {})
        have = {x["how"] for x in cands}
        for m in c.get("mit", []):
            x = M(m, toggle=m.startswith(TOGGLE_PREFIX) and path.split("/")[0] in ("View", "Window", "Type"))
            if x["how"] not in have:
                cands.append(x)
        for e in c.get("ev", []):
            x = E(e)
            if x["how"] not in have and e not in ("open", "close", "save", "print", "printOneCopy", "batch", "createDroplet", "revealAll",
                                                    "delete", "apply", "applyStyle", "applyComp", "enable", "link", "custom", "maximum",
                                                    "median", "minimum", "smoothness", "undoEvent", "trap", "syntheticFill",
                                                    "syntheticTextToImage", "generativeUpscale", "syntheticGenHarmonize", "imageSize",
                                                    "canvasSize", "crop", "duplicate", "reverse", "rasterize", "fill", "stroke",
                                                    "showFileBrowserPalette", "showMiniBridge", "systemCall", "quit",
                                                    "PSOpenFileDialog", "syncSettings", "syncSettingsPush", "syncSettingsPull",
                                                    "syncManageAcct", "export", "packageFile", "PDFExport", "exportDataSet",
                                                    "placedLayerExportContents", "editInImageReady", "runJavaScript",
                                                    "rigidTransform", "perspectiveWarpTransform", "blurbTransform"):
                cands.append(x)
        cands = [x for x in cands if x["key"] not in DROP.get(path, ())]
        plan[cid] = {"path": path, "state": state, "cands": cands, "skip": skip}
    return plan


# runMenuItem candidates that would enter an interactive transform / edit mode: recorded, never run
INTERACTIVE = {"freeTransform", "scale", "rotateEventEnum", "skew", "distort", "perspective", "warp", "rigidTransform",
               "perspectiveWarpTransform", "contentAware", "renameLayer", "placedLayerReplaceMissing"}
PLAN = build()
for _cid, _p in PLAN.items():
    _p["cands"] = [x for x in _p["cands"] if not (x["kind"] == "ps_menu_cmd" and x["key"] in INTERACTIVE)]
    _p["interactive_mit"] = [m for m in C.get(_cid, {}).get("mit", []) if m in INTERACTIVE]

if __name__ == "__main__":
    n = sum(1 for p in PLAN.values() if p["skip"])
    print(len(PLAN), "commands,", n, "skipped,", sum(1 for p in PLAN.values() if not p["skip"] and p["cands"]), "with candidates,",
          sum(1 for p in PLAN.values() if not p["skip"] and not p["cands"]), "without")
    for cid, p in PLAN.items():
        if not p["skip"] and not p["cands"]:
            print("  none:", cid, p["path"])
