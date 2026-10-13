export const meta = {
  name: 'pgd-preset-gallery',
  description: 'PGD wave 3a: render a thumbnail of every visual preset of one app (what it looks like when applied), so preset cards are written from renders',
  phases: [
    { title: 'Render presets', detail: 'one owner of the app renders every visual preset' },
  ],
}

// Launch args (Workflow `args`): root (required, the PGD folder, forward slashes), app (required, PS | AI | CDR);
// optional: hostlock (path of hostlock.py, default <root>/tools/hostlock.py), note.   {"root": "C:/src/PGD", "app": "AI"}
if (!args || !args.root) throw new Error('pgd_preset_gallery.js needs args.root (the PGD folder), e.g. {"root": "C:/src/PGD", "app": "AI"}')
const ROOT = String(args.root).replace(/\\/g, '/').replace(/\/+$/, '')
const HOSTLOCK = args.hostlock || `${ROOT}/tools/hostlock.py`
const A = args.app
const CODE = {PS: 'ps', AI: 'ai', CDR: 'cdr'}[A]

const SPEC = {
  CDR: `APP: CorelDRAW 2024 (25.1), COM "CorelDRAW.Application.25" (never the 2021 ProgID .23). It was left running and idle by
the harvest agents; reuse ${ROOT}/tools/cdr/cdr_com.py (Corel(): one COM owner thread, a timeout on every call, modal
dialogs dismissed through UI Automation Invoke, private makepy cache), testdoc.py (a scratch document you own) and the
apply paths proven in apply_tests.py / vector_effects.py. Traps: opening / importing can take minutes and is not a hang until
read bytes and CPU are both flat; absolute paths only; optional VT_DISPATCH args need None.
Render by category (harvest/cdr/cdr_preset.json, 1572 items, 66 categories):
- image-file presets (Brush Image, Texture Image, Bump Map Image, Canvas Image, Displace Map, Frame Effect Image, Photo
  Frame, Brush Texture, Shear Map, Image List entries that are images ...): the file itself, converted with PIL (no app).
- Artistic Media Brush / Sprayer / Painterly Brush / Artistic Media Preset / Brush Preset: applied to an S-curve.
- Fountain Fill Preset / Fill / Texture Fill / Two-Color Pattern entries: a filled rectangle (this also shows the look of
  the 89 fountain fills whose display names are unresolved resource ids).
- Transparency Preset: on a rectangle over a checker or the test photo.
- Effect presets (Lens Flare, Bevel, Drop Shadow, Inner Shadow, Glass, The Boss, Whirlpool, User Defined, Art Style,
  Adjustment, Tone Curve, Duotone, Channel Mixer, Shear ...): applied to the test photo bitmap or the vector plate shapes,
  whichever the preset is for.
- Envelope / Extrude / Blend / Contour / Distortion / Perspective presets: applied to the vector plate shapes.
- Color Palette / palette libraries: a swatch strip of the palette's colours (parse the file; no app needed).
- Not visual (New Document Preset, Template, Label Template, Color Profile, Color Management, Export, Imposition, Print /
  Preflight style, Workspace, Find and Replace, Dimension, Callout ...): no render; list them in not_renderable.json with
  the reason. Templates may be rendered as their first page if that is quick; optional.
When a real apply fails, an embedded thumbnail in the preset file (several .pst files carry a zlib thumbnail) is an
acceptable fallback: record "how": "embedded thumbnail".`,
  PS: `APP: Photoshop 2026 (27.4.0), COM "Photoshop.Application"; reuse ${ROOT}/tools/ps/psdrv.py (js / jsj with a timeout,
dismiss_dialogs by window handle, restart_ps), pslib.jsx and the templates in probe.py. Traps: Lens Blur with huge values hangs
Photoshop for 20+ min; some commands wedge it so that every later command says 'not currently available' (only taskkill and a
restart recover: keep an Invert canary between items); app.runMenuItem does not take menuBarInfo command numbers.
Render by category (harvest/ps/ps_preset.json, 3175 items):
- Custom shape: the shape filled near-black on white. Brush: an S-stroke with the brush on white. Layer style: the style
  on a bold "PGD" type layer over a mid-grey background. Gradient: a gradient-filled rectangle. Pattern: a pattern-filled
  square. Contour: the contour curve plotted (parse it, or show it via a style). 3D LUT: Color Lookup on the test photo.
  Duotone: the test photo in Duotone mode with the preset. Curves / Levels / Hue-Saturation / Black & White / Channel
  Mixer / Exposure / HDR Toning / Photo Filter presets: applied to the test photo. Sky: the sky image. Swatch library /
  Color book: a swatch strip.
- Not visual (Action, Tool preset, Document preset, Video render preset, Image Size, Save for Web settings, Script, Deco
  script, Guide layout, optimized tables, 3D widget): no render; not_renderable.json with the reason. Actions: put each
  action's step list in not_renderable.json if you can read it from the .atn (it helps the card writers).`,
  AI: `APP: Illustrator 2026 (30.2.1), COM "Illustrator.Application"; reuse ${ROOT}/tools/ai/aicom.py (js / js_watch with
timeouts and dialog answering by PostMessage), render_check.py (renders to PNG), probe_effects.py. Traps: a menu-bar click
once landed in Photoshop because Photoshop was in front: never send global input without host_lock("ui") and a check that
Illustrator is the foreground window.
Render by category (harvest/ai/ai_preset.json, 2087 items):
- Symbol: one instance placed and fitted on white. Brush: applied to an S-curve path (pattern / art / scatter /
  calligraphic / bristle as the brush type demands). Graphic Style: applied to a star and to "PGD" type. Arrowhead: a
  stroked line with the arrowhead at both ends. Width profile: a thick stroke with the profile. Image Trace preset: the
  test photo (downscaled) traced with the preset. Swatch libraries / colour books: a swatch strip. Bevel (3D Classic) and
  3D materials: applied to an extruded / 3D shape if the scripting route works, else not_renderable with the reason.
- Not visual (Action, Script, Workspace, Save for Web, PDF preset, New document profile, Flattener, Print preset, Toolbar,
  Keyboard shortcut set): not_renderable.json with the reason.`,
}

const PROMPT = `You render the PRESET GALLERY of PGD ("professional graphics designer"), the verified knowledge an automated design
system has of Photoshop 2026, Illustrator 2026 and CorelDRAW 2024. Knowledge cards for presets will be written FROM your
thumbnails (what a preset looks like is only known once it is rendered), so a thumbnail must show the preset itself as
applied, clearly. Read ${ROOT}/CONTRACT.md first (rules for driving an app).

${SPEC[A]}

${args.note ? 'NOTE FROM THE ORCHESTRATOR: ' + args.note : ''}

Output folder ${ROOT}/gallery/${CODE}_preset/:
- one PNG per rendered preset, 320x320 (fit, neutral background), named <key>.png where key = the first 12 hex chars of
  sha1(item id as UTF-8) (stable identity: never number thumbnails by list position);
- index.json: [{"key", "id", "name", "category", "how": "applied: <what was done>" | "file image" | "embedded thumbnail" |
  "swatch strip"}];
- failed.json: {id: "<error>"} for presets whose render failed; not_renderable.json: {id: "<reason>"} for non-visual ones.
Every preset item ends up in exactly one of index.json, failed.json, not_renderable.json.

Rules: you own only this app; never touch any other app (Photoshop, Illustrator, CorelDRAW, After Effects, Premiere: other
agents and pipelines use them). Leave documents you did not open alone; your own documents close unsaved. Timeouts on every
app call; dismiss dialogs by window handle; global input only inside host_lock("ui") from ${HOSTLOCK}.
Write the renderer to ${ROOT}/tools/${CODE}/preset_gallery.py (resumable: skip keys whose PNG exists; checkpoint the three
json files every batch), scratch in ${ROOT}/work/${CODE}/. Look at a sample of your thumbnails (Read the PNGs) for each
category early and fix the renderer if they do not show the preset clearly (blank, tiny, clipped, wrong layer type).
Time box about 150 minutes: categories with the most items first. Return the summary.`

const OUT = {type: 'object', properties: {app: {type: 'string'}, rendered: {type: 'integer'}, failed: {type: 'integer'},
  not_renderable: {type: 'integer'}, missing: {type: 'integer'}, per_category: {type: 'string'}, traps: {type: 'array', items: {type: 'string'}},
  notes: {type: 'string'}}, required: ['app', 'rendered', 'failed', 'not_renderable', 'missing', 'per_category', 'traps', 'notes']}

phase('Render presets')
return await agent(PROMPT, {label: `presets:${A}`, phase: 'Render presets', schema: OUT})
