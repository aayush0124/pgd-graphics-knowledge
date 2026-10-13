export const meta = {
  name: 'pgd-harvest',
  description: 'PGD wave 1: harvest every effect, tool, menu command, preset and scripting surface from live Photoshop 2026, Illustrator 2026 and CorelDRAW 2024',
  phases: [
    { title: 'Effects', detail: 'per app: filters / effects / adjustments / layer styles / blend modes with params' },
    { title: 'Tools+menus', detail: 'per app: every tool and every menu command' },
    { title: 'Presets', detail: 'per app: shipped presets and libraries' },
    { title: 'Audit', detail: 'independent check of each app harvest against the live app' },
    { title: 'API', detail: 'scripting object models from omv.xml and typelibs (no app)' },
  ],
}

// Launch args (Workflow `args`): root (required, the PGD folder, forward slashes). Optional: hostlock (path of
// hostlock.py, default <root>/tools/hostlock.py); pve (the sibling PVE folder, whose harvesters the agents may read);
// cdr_traps_doc (a document listing CorelDRAW COM traps from an earlier automation).   {"root": "C:/src/PGD"}
if (!args || !args.root) throw new Error('pgd_harvest.js needs args.root (the PGD folder), e.g. {"root": "C:/src/PGD"}')
const ROOT = String(args.root).replace(/\\/g, '/').replace(/\/+$/, '')
const HOSTLOCK = args.hostlock || `${ROOT}/tools/hostlock.py`
const PVE = args.pve ? `(${args.pve}, the same thing for After Effects + Premiere; read pve/harvest_ae.jsx, pve/harvest_ae.py
and pve/harvest_files.py for the style of a harvester that worked)` : '(the same thing for After Effects + Premiere)'
const CDR_TRAPS = args.cdr_traps_doc ? `\n(${args.cdr_traps_doc} has the full list, read its COM section)` : ''

const COMMON = `You are building PGD ("professional graphics designer"): the verified knowledge an automated design system has of
Photoshop 2026, Illustrator 2026 and CorelDRAW 2024, harvested from the INSTALLED apps. It is the sibling of PVE
${PVE}. Everything downstream (knowledge cards, render tests,
pre-flight checks) trusts your harvest, so a value you did not read from the app or its files must not appear in it.

READ FIRST: ${ROOT}/CONTRACT.md (file format, kinds, item fields, rules). Validate every file you write with
  python ${ROOT}/check_harvest.py ${ROOT}/harvest/<app>/<kind>.json
until it reports 0 errors.

Rules that matter here:
- You own exactly ONE app (named below). Never send anything to another app. Never touch After Effects or Premiere Pro
  (other pipelines are using them right now).
- Before your first script, list the app's open documents. Anything you did not open is someone else's: leave it alone.
  Create your own test documents and close them (without saving) when done.
- Every COM / script call gets a timeout (run it in a worker thread or subprocess). A call that does not return means a
  modal dialog is up: dismiss it with input aimed at that dialog's window handle (PostMessage / UI Automation Invoke on
  its OK / Cancel button). If you must use GLOBAL keyboard or mouse input (SendKeys, pyautogui, SetForegroundWindow),
  do it only inside  with host_lock("ui", timeout=600):  from ${HOSTLOCK} (sys.path insert),
  held only around the input: two other agents are driving two other apps at the same time and a global keystroke
  goes to whichever window has focus. pip install pywinauto / comtypes / uiautomation if you need them.
- Payloads into ExtendScript: percent-encode and eval(decodeURIComponent(...)) on arrival; File(p).fsName at host calls;
  catch handlers use String(e).
- Put your scripts in ${ROOT}/tools/<app>/ (they are reused later to render the gallery) and logs / scratch in
  ${ROOT}/work/<app>/ (create both; never write generic file names anywhere shared).
- Checkpoint to disk as you go and resume from the checkpoint after a crash or restart; write each harvest file as soon
  as it is usable, then improve it. A partial file on disk beats a perfect one in your head.
- An item you cannot probe is still listed, with "error" saying why. Never drop an item to make a file look clean,
  never invent a range or a default.
- Record app_version from the app itself.
- Test image: ${ROOT}/media/test_photo.png (1920x1080 photographic test plate).
Return the summary object; "helpers" lists the scripts / modules you wrote that a later agent should reuse, "traps" the
app behaviours that cost you time (one sentence each, with the evidence), "gaps" what you could not harvest and why.`

const APPS = {
  PS: {
    code: 'ps', name: 'Photoshop 2026 (27.4.0)',
    state: `Photoshop 2026 27.4.0 was started by the orchestrator at about 12:50 IST on 2026-10-04 and had no documents open.
Connect with win32com.client.Dispatch("Photoshop.Application") (ProgID verified to resolve to Photoshop 2026; Photoshop
2024 is also installed: never start it). .DoJavaScript(js) returns the value of the script's last expression as a string.
Verified at 12:52: executeActionGet on a reference with putProperty(charIDToTypeID("Prpr"), stringIDToTypeID("menuBarInfo"))
and putEnumerated(charIDToTypeID("capp"), charIDToTypeID("Ordn"), charIDToTypeID("Trgt")) returns the WHOLE menu tree
(878 nodes); each node descriptor has "name", "command" (integer menu command id usable with app.runMenuItem) and
"submenu" (a list of nodes). Other sources on disk: C:/Program Files/Adobe/Adobe Photoshop 2026/Required/Plug-ins/
(Filters/*.8bf, Effects/Filter Gallery.8bf: PE files whose PiPL and 'aete' resources hold a plug-in filter's event id and
parameter terminology; pefile is installed; most built-in filters live inside Photoshop.exe instead), Presets/ (3DLUTs,
Actions, Black and White, Brushes, Channel Mixer, Color Books, Color Swatches, Contours, Curves, Deco, Duotones, Exposure,
HDR Toning, Hue and Saturation, Levels, Patterns, Scripts, Styles, Tools, Video ...), Presets/Scripts/Stack Scripts
Only/Terminology.jsx (Action Manager stringID constants).`,
    effects: `kinds ps_filter, ps_adjustment, ps_layer_style, ps_blend_mode.
- ps_filter: EVERY item under the Filter menu (incl. Filter Gallery and each of its filters, Camera Raw Filter,
  Liquify, Neural Filters, Lens Correction, Adaptive Wide Angle, Vanishing Point, Convert for Smart Filters, Other,
  3D...). For each: the Action Manager event stringID ("invoke": {"ps_event": ...} and the menu command id in
  "extra.menu_cmd"), and its parameters: key, type, default value, and min / max where you can probe them. Ways that can
  work (find out which do): executeAction(event, desc, DialogModes.NO) on a test document returns a descriptor of the
  values actually used; applying the filter to a smart object and reading the layer's smartObject filterFX descriptor
  gives the full stored parameter set; app.notifiers (an "All " notifier writing typeIDToStringID(arguments[1]) and the
  descriptor to a file) reveals which event a runMenuItem(command) fires; an out-of-range value either errors (record the
  message) or is clamped (read back what was kept), which brackets the range. Filter Gallery filters share one event
  with a per-filter class: record each as its own item.
- ps_adjustment: every Image > Adjustments item AND every adjustment-layer type, with descriptor keys, defaults and enum
  values read back from a layer you created (Levels, Curves, Hue/Saturation, Color Lookup with its LUT list, Gradient
  Map, Selective Color, Black & White, Channel Mixer, Photo Filter with its filter list, ...).
- ps_layer_style: each layer effect (Drop Shadow, Inner Shadow, Outer Glow, Inner Glow, Bevel & Emboss incl. Contour
  and Texture, Satin, Color Overlay, Gradient Overlay, Pattern Overlay, Stroke) with every descriptor key, default and
  enum value read back after applying it to a layer.
- ps_blend_mode: every layer blend mode with its AM enum stringID and DOM BlendMode name.`,
    tools: `kinds ps_tool, ps_menu.
- ps_menu: every menu command from menuBarInfo that is not a Filter or Image > Adjustments item: id = the command id
  when it is > 0 and unique, otherwise the menu path; "path" = full menu path; "invoke": {"ps_menu_cmd": id}; shortcut
  if you can read it (keyboard shortcut set files: look for the default .kys under the install or user presets).
  Skip dynamic lists (Open Recent files, open documents, workspaces).
- ps_tool: every toolbar tool incl. the ones hidden in tool groups (Move, Artboard, marquees, lassos, Object Selection,
  Quick Selection, Magic Wand, Crop family, Frame, Eyedropper family, healing family incl. Remove tool, brushes,
  stamps, history brushes, erasers, Gradient, Paint Bucket, Blur/Sharpen/Smudge, Dodge/Burn/Sponge, Pen family, Type
  family, Path/Direct Selection, shape tools, Hand, Rotate View, Zoom ...): id = the tool id string that app.currentTool
  accepts (VERIFY each by setting app.currentTool and reading it back), display name, group, shortcut.`,
    presets: `kind ps_preset: everything Photoshop ships under Presets/ and its default preset libraries (brushes, swatches,
gradients, patterns, styles, shapes, contours, tool presets, actions with each action's name, scripts, 3DLUTs, Deco
scripts, duotones, curves / levels / hue-sat / black-and-white / channel-mixer / exposure / HDR toning presets, video
presets). One item per entry a designer would pick by name for its look or job (a style, a brush, a gradient, a pattern,
a shape, a LUT, an action, a curves preset); one item per LIBRARY for swatch libraries and colour books (entry names in
extra.entries). id = file path relative to the install + "#" + entry name. category = the preset type. Find where
Photoshop 2026 keeps its default brushes / gradients / patterns / shapes / styles / swatches (they are not all in
Presets/); read entry names from the app (preset manager / Action Manager) or parse the files, and say which in evidence.`,
  },
  AI: {
    code: 'ai', name: 'Illustrator 2026 (30.2.1)',
    state: `Illustrator 2026 30.2.1 has been running since 2026-10-03 11:55; at 12:52 on 2026-10-04 it had 0 documents and
userInteractionLevel DISPLAYALERTS. Connect with win32com.client.GetActiveObject("Illustrator.Application") (or Dispatch);
.DoJavaScript(js) returns the last expression. Verified: Illustrator's menus are NOT native Win32 menus (GetMenu returns 0),
so display names must come from UI Automation, plug-in resources or the app itself. On disk:
C:/Program Files/Adobe/Adobe Illustrator 2026/Presets/en_US/Keyboard Shortcuts/Illustrator Defaults.kys lists every
internal menu command id (the strings app.executeMenuCommand takes) as "/<id> { /Context /Modifiers /Represent /Key }"
blocks under "/Menus {", and (check) the tools in another section, with no display names. Plug-ins/Illustrator Filters/
*.aip (AddArrow, Distort, DropShadow, FuzzyEffect, Geometry3D, Materials, OffsetPath, Pathfinder, Punk, Roughen, Round,
Scribble, ShapeEffect, VectorEdge, ZigZag ...), Plug-ins/Photoshop Filters/ (Filter Gallery.8bf, GaussianBlur.8bf,
UnsharpMask.8bf, Standard MultiPlugin.8BF ...), Plug-ins/Tools/*.aip. Presets/en_US/: Brushes (25 files), Graphic
Styles (12), Swatches (97), Symbols (28), Actions (1), Scripts (3), Tools (1).`,
    effects: `kinds ai_effect, ai_blend_mode.
- ai_effect: EVERY item under the Effect menu: Illustrator Effects (3D and Materials, Convert to Shape, Distort &
  Transform, Path, Pathfinder, Rasterize, Stylize, SVG Filters with each filter by name, Warp with each warp style, Crop
  Marks ...) and Photoshop Effects (Effect Gallery, Artistic, Blur, Brush Strokes, Distort, Pixelate, Sketch, Stylize,
  Texture, Video). For each: display name, menu path, the executeMenuCommand id ("invoke": {"ai_menu": ...}), the
  LiveEffect name usable with pageItem.applyEffect(xml) ("invoke": {"ai_live_effect": ...}) and its parameter keys,
  types and defaults. Ways that can work: apply the effect to a path you created (applyEffect with an XML LiveEffect
  dict, or executeMenuCommand + dismissing the dialog with OK so defaults apply), then save a COPY as uncompressed .ai
  (PDF compatibility off, compression off) and parse the stored live-effect dictionary (keys, types, values); the Warp
  styles and SVG filter names are enumerable. Ranges only when the app told you.
- ai_blend_mode: every transparency blend mode (DOM BlendModes enum name + display name).`,
    tools: `kinds ai_tool, ai_menu.
- ai_menu: every menu command that is not under Effect: id = the executeMenuCommand string, display name, menu path,
  shortcut decoded from the .kys where set. Get display names and menu paths by walking the menu bar with UI Automation
  (open each top menu and submenu, read the item names, close it again; aim input at Illustrator's window, global input
  only under host_lock("ui")), or another source you can show is complete; match them to the .kys ids and say how in
  evidence. Items you cannot name keep id-only entries with "error".
- ai_tool: every toolbar tool incl. hidden group members (Selection, Direct Selection, Group Selection, Magic Wand,
  Lasso, Pen family, Curvature, Type family incl. Touch Type, line/arc/spiral/grids, shapes incl. Star / Flare / Polygon,
  Paintbrush, Blob Brush, Shaper, Pencil family, Eraser / Scissors / Knife, Rotate / Reflect / Scale / Shear / Reshape,
  Width / Warp / Twirl / Pucker / Bloat / Scallop / Crystallize / Wrinkle, Free Transform, Puppet Warp, Shape Builder,
  Live Paint, Perspective, Mesh, Gradient, Eyedropper, Measure, Blend, Symbol tools, graph tools, Artboard, Slice, Hand,
  Rotate View, Print Tiling, Zoom ...): id = the tool name app.selectTool() accepts if this version has it (verify), else
  the .kys tool id; display name; group; shortcut.`,
    presets: `kind ai_preset: every library under Presets/en_US (Brushes, Graphic Styles, Symbols, Swatches, Actions, Scripts,
Tools) plus the presets a designer picks by name inside the app (Image Trace presets, Width Profiles, arrowheads, 3D
material presets if enumerable). Open each library .ai as a document YOU opened (it is an ordinary .ai file), read the
graphicStyles / symbols / brushes / swatches names, close it without saving. One item per graphic style, brush, symbol;
one item per LIBRARY for swatch libraries (entry names in extra.entries). id = library file path relative to Presets +
"#" + entry name.`,
  },
  CDR: {
    code: 'cdr', name: 'CorelDRAW 2024 (25.1)',
    state: `CorelDRAW Graphics Suite 2024 (25.1.0.269) is installed at C:/Program Files/Corel/CorelDRAW Graphics Suite/25 and is NOT
running. CorelDRAW 2021 (ProgID CorelDRAW.Application.23) is also installed: never start it. Start 2024 with
win32com.client.gencache.EnsureDispatch("CorelDRAW.Application.25") (plain Dispatch hides typelib members); make it
Visible, wait for the start-up / welcome screen to finish. Hard-won traps from the CorelDRAW booklet automation${CDR_TRAPS}: opening a document can take
45 s - 4 min and is NOT a hang until read bytes and CPU are both flat; relative paths resolve against COM's own cwd
(always absolute); optional VT_DISPATCH arguments need None; a raw newline in Story.Text discards everything after it
(use CR); grep the generated typelib module under win32com.__gen_path__ when a member seems missing.
On disk: Draw/UIConfig/DrawUI.xml (6 MB, 12,092 itemData elements) declares every command, tool, menu and dialog control
by GUID. Effect dialogs are there with their parameters and RANGES, e.g. line ~10284: a slider bound to
"DataSource=GaussianBlurEffectDS;Path=Radius" with rangeMin="0.1" rangeMax="250.0"; buttons bound to
"EffectsDialogFactoryDS;Path=OnGaussianBlur"; check buttons "EffectsPropertiesDS;Path=ApplyOrDeleteEffect:GaussianBlurEffect".
Captions are referenced by captionRef GUIDs: resolve them with the app (FrameWork / Automation caption lookups by GUID:
find the exact member in the typelib) or the localized resources under Languages/EN. Draw/Presets/ has Blend, Contour,
Distortion, Envelope, Shadow, VectorExtrude; Programs64/TypeLibs/*.tlb (38) hold the object model.`,
    effects: `kind cdr_effect: EVERY item under CorelDRAW 2024's Effects menu: the bitmap / non-destructive effects by group
(Adjust, Art Strokes, Blur, Camera, Color Transform, Contour, Creative, Custom, Distort, Noise, Sharpen, Texture,
Transform ... whatever this version really has) and the vector effects (Contour, Blend, Extrude, Envelope, Distort,
Drop Shadow, Block Shadow, Bevel, Perspective, Lens types, Transparency, PowerClip, Inner Shadow ...). For each: display
name, menu path, GUID ("invoke": {"cdr_guid": ...}), how a script applies it ("cdr_com": e.g. "Shape.CreateContour" with
its typelib argument names, types and defaults, or the bitmap-effect command / non-destructive effect API you find in the
typelib) and its parameters with ranges from the DrawUI.xml dialog controls (data-source path = param key; rangeMin /
rangeMax; enum = the radio / combo items with captions). Prove the apply path on 3 effects of each family on a test
document (a rectangle + an imported test_photo.png bitmap) and say in evidence which items were applied for real.`,
    tools: `kinds cdr_tool, cdr_menu.
- cdr_tool: every toolbox tool incl. flyout members (Pick, Freehand Pick, Shape, Smooth, Smear, Twirl, Attract/Repel,
  Crop, Knife, Eraser, Zoom/Pan, curve tools, Artistic Media, shapes, Text, Table, dimension / connector tools,
  interactive tools Blend / Contour / Distort / Envelope / Extrude / Drop Shadow / Block Shadow / Transparency,
  Eyedropper, Interactive Fill / Mesh Fill, Smart Fill, LiveSketch, Pointillizer / PhotoCocktail if present ...): GUID,
  caption, flyout group, shortcut; the COM ActiveTool enum value where the typelib has one.
- cdr_menu: every main-menu command (File ... Help) with GUID, caption, menu path; from DrawUI.xml menu definitions
  and / or the app's CommandBars; skip dynamic lists.`,
    presets: `kind cdr_preset: everything CorelDRAW 2024 ships as a pickable preset: Draw/Presets (Blend, Contour, Distortion,
Envelope, Shadow, VectorExtrude), fills / patterns / transparency / colour palettes / styles / templates / brush strokes
under Custom Data, Content, Draw/CustomMediaStrokes and the user's content folders. One item per preset a designer picks
by name; one item per palette / colour book (entry names in extra.entries). id = path relative to the install + "#" +
entry name.`,
  },
}

const SUMMARY = {type: 'object', properties: {
  app: {type: 'string'}, stage: {type: 'string'},
  files: {type: 'array', items: {type: 'object', properties: {file: {type: 'string'}, items: {type: 'integer'},
    errors: {type: 'integer'}, with_params: {type: 'integer'}}, required: ['file', 'items', 'errors']}},
  helpers: {type: 'array', items: {type: 'string'}},
  traps: {type: 'array', items: {type: 'string'}},
  gaps: {type: 'array', items: {type: 'string'}},
  notes: {type: 'string'}},
  required: ['app', 'stage', 'files', 'helpers', 'traps', 'gaps', 'notes']}

const AUDIT = {type: 'object', properties: {
  app: {type: 'string'},
  completeness: {type: 'array', items: {type: 'string'}},
  problems: {type: 'array', items: {type: 'object', properties: {file: {type: 'string'}, item: {type: 'string'},
    problem: {type: 'string'}, fixed: {type: 'boolean'}, how: {type: 'string'}}, required: ['file', 'item', 'problem', 'fixed']}},
  spot_checks: {type: 'integer'}, spot_check_failures: {type: 'integer'},
  verdict: {type: 'string'}},
  required: ['app', 'completeness', 'problems', 'spot_checks', 'spot_check_failures', 'verdict']}

function prior(results) {
  const r = results.filter(Boolean)
  if (!r.length) return ''
  return `\nWhat the earlier stage(s) for this app reported (reuse their helpers; do not redo their files):\n` +
    r.map(x => JSON.stringify(x)).join('\n') + '\n'
}

function stagePrompt(appKey, stage, earlier) {
  const a = APPS[appKey]
  const budget = {effects: 150, tools: 75, presets: 60}[stage]
  return `${COMMON}

YOUR APP: ${a.name}. App code "${appKey}", harvest folder ${ROOT}/harvest/${a.code}/, scripts ${ROOT}/tools/${a.code}/,
scratch ${ROOT}/work/${a.code}/.
${a.state}
${prior(earlier)}
STAGE "${stage}". Deliver ${a[stage]}

Time box about ${budget} minutes. Order: get a first complete-by-name file on disk for each kind early (names, ids, paths:
within the first third of the time box), then deepen it (params, defaults, ranges, verification). Before you return,
check_harvest.py must show 0 errors for every file you wrote.`
}

function auditPrompt(appKey, stages) {
  const a = APPS[appKey]
  return `${COMMON}

YOUR APP: ${a.name}. You are the INDEPENDENT AUDITOR of its harvest in ${ROOT}/harvest/${a.code}/ (you now own the app;
the harvesting agents have finished). Scripts they wrote are in ${ROOT}/tools/${a.code}/.
${a.state}
What the harvesting stages reported:
${stages.filter(Boolean).map(x => JSON.stringify(x)).join('\n')}

Assume the harvest is wrong somewhere and find where. Within about 60 minutes:
1. Completeness: count the app's real items (menu items under each top menu and each Effect/Filter submenu, toolbar
   tools, preset files) from the app or its files YOURSELF, by a different route than the harvester used where you can,
   and compare with the harvest. List every missing or extra item; add missing ones (name, id, path at least).
2. Truth: pick at least 25 items at random across the kinds that carry params or invoke data and re-check them against
   the live app: does the invoke really run that item (apply it to a test document you create), are the param keys real,
   are defaults right, does an in-range value apply and an out-of-range one fail or clamp as recorded? Fix what is wrong;
   if a whole family is wrong, fix the family.
3. Ids unique and stable (no list positions), names exactly as the app shows them, no invented ranges.
4. check_harvest.py: 0 errors on every file.
Return the audit object; "fixed" true only for problems you corrected in the files.`
}

const API_PROMPT = `${COMMON}

YOUR JOB uses NO app at all (do not start or script any application). Harvest the scripting surfaces from files:
- ps_api -> ${ROOT}/harvest/ps/ps_api.json from C:/Program Files (x86)/Common Files/Adobe/Scripting Dictionaries CC/photoshop/omv.xml
  (the ExtendScript object model: classes, properties, methods, enumerations, with descriptions), plus
  C:/Program Files/Adobe/Adobe Photoshop 2026/TypeLibrary.tlb (the COM type library: compare, note differences) and
  C:/Program Files/Adobe/Adobe Photoshop 2026/Presets/Scripts/Stack Scripts Only/Terminology.jsx (Action Manager
  constants: one item "am:terminology" with the constants in extra).
- ai_api -> ${ROOT}/harvest/ai/ai_api.json from C:/Program Files/Common Files/Adobe/Scripting Dictionaries CC/Illustrator 2026/omv.xml
  (757 KB, Mar 13 2026; an older Feb 4 copy sits under Program Files (x86): diff them and say which is newer / which matches
  30.2.1).
- cdr_api -> ${ROOT}/harvest/cdr/cdr_api.json from C:/Program Files/Corel/CorelDRAW Graphics Suite/25/Programs64/TypeLibs/*.tlb
  via pythoncom.LoadTypeLib (no app needed): the main CorelDRAW / VGCore object model in full (every interface / coclass,
  every member with its argument names, types, optional flag and default value, and every enum with its values); the
  other 37 libraries at least by name with their interface count, in full when they are tool object models a designer
  script would call (BevelToolOM, CalloutToolOM, ExportToolOM ...).
Item = one per class / interface ("id": "class:<Name>") and one per enumeration ("id": "enum:<Name>"); members go in
extra.members as [{"name", "kind": "property"|"method", "type", "readonly", "params": [{"name", "type", "optional",
"default"}], "description"}]; enumeration values go in extra.values as [{"name", "value", "description"}]. "category" =
the source library. Write the three files, validate with check_harvest.py, return the summary (app "API", stage "api").
Time box about 60 minutes.`

phase('Effects')
const appRuns = pipeline(Object.keys(APPS),
  (k) => agent(stagePrompt(k, 'effects', []), {label: `effects:${k}`, phase: 'Effects', schema: SUMMARY})
    .then(r => ({k, res: [r]})),
  (s) => agent(stagePrompt(s.k, 'tools', s.res), {label: `tools:${s.k}`, phase: 'Tools+menus', schema: SUMMARY})
    .then(r => ({k: s.k, res: s.res.concat([r])})),
  (s) => agent(stagePrompt(s.k, 'presets', s.res), {label: `presets:${s.k}`, phase: 'Presets', schema: SUMMARY})
    .then(r => ({k: s.k, res: s.res.concat([r])})),
  (s) => agent(auditPrompt(s.k, s.res), {label: `audit:${s.k}`, phase: 'Audit', schema: AUDIT})
    .then(r => ({k: s.k, res: s.res, audit: r})))
const apiRun = agent(API_PROMPT, {label: 'api:all', phase: 'API', schema: SUMMARY})
const [apps, api] = await Promise.all([appRuns, apiRun])
log(`harvest done: ${apps.filter(Boolean).length}/3 apps, api ${api ? 'ok' : 'failed'}`)
return {apps: apps.filter(Boolean), api}
