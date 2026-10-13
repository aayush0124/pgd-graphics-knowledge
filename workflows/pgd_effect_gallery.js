export const meta = {
  name: 'pgd-effect-gallery',
  description: 'PGD wave 3b: render every visual card (effects, filters, adjustments, styles, blend modes) of one app with its demo_settings on the test plate',
  phases: [
    { title: 'Render effects', detail: 'one owner of the app renders every visual card' },
  ],
}

// Launch args (Workflow `args`): root (required, the PGD folder, forward slashes), app (required, PS | AI | CDR);
// optional: hostlock (path of hostlock.py, default <root>/tools/hostlock.py), note, ids or ids_file (re-render run).
//   {"root": "C:/src/PGD", "app": "PS"}
if (!args || !args.root) throw new Error('pgd_effect_gallery.js needs args.root (the PGD folder), e.g. {"root": "C:/src/PGD", "app": "PS"}')
const ROOT = String(args.root).replace(/\\/g, '/').replace(/\/+$/, '')
const HOSTLOCK = args.hostlock || `${ROOT}/tools/hostlock.py`
const A = args.app
const CODE = {PS: 'ps', AI: 'ai', CDR: 'cdr'}[A]
const KINDS = {PS: ['ps_filter', 'ps_adjustment', 'ps_layer_style', 'ps_blend_mode'], AI: ['ai_effect', 'ai_blend_mode'],
  CDR: ['cdr_effect']}[A]
const RERENDER = args.ids_file || (args.ids && args.ids.length)
const ONLY = RERENDER ? `\nRE-RENDER RUN: render ONLY these card ids (their cards' demo_settings were changed by the verifiers),
overwriting their frames and updating their index.json rows; leave every other frame alone:
${args.ids ? JSON.stringify(args.ids) : 'the ids listed in ' + args.ids_file}\n` : ''

const SPEC = {
  PS: `APP: Photoshop 2026 (27.4.0), COM "Photoshop.Application"; reuse ${ROOT}/tools/ps/psdrv.py (js / jsj with a timeout,
dismiss_dialogs by window handle, restart_ps), pslib.jsx and the PROBE_JS / ADJLAYER_JS / STYLE_JS / BLEND_JS templates in
probe.py (they already apply every kind by Action Manager). Traps from the harvest: Lens Blur with huge values hangs Photoshop
20+ min; Displace without a map file and Shear under extreme values wedge it (taskkill + restart only); Smart Blur opens its
dialog even with DialogModes.NO (BM_CLICK its win32 'Cancel'); app.runMenuItem does not take menuBarInfo numbers. Keep an
Invert canary between items and restart when wedged.
MEMORY: during the preset gallery Photoshop grew to 32.6 GB of private memory and pushed the whole machine to within
2.5 GB of its commit limit (other agents and apps share it). Restart Photoshop (restart_ps) before you start and after every
~100 items, close every document as soon as its frame is saved, and before each batch read
sys.path.insert(0, "${HOSTLOCK.replace(/\/[^/]*$/, '')}"); from hostlock import headroom; headroom() -> (free_mb, commit_used_gb,
commit_limit_gb, top): if commit_limit_gb - commit_used_gb < 4, restart Photoshop and wait until there is room.
Plate: ${ROOT}/media/plate_photo.png (1920x1080). ps_filter and ps_adjustment: on the plate (one fresh document per item).
ps_layer_style: on a light-grey (#E1E1E1) "PGD" text layer (Arial Black 360 px, centred) over a mid-grey (#808080) canvas, the
ps_preset layer-style plate at 1920x1080. ps_blend_mode: a known top layer at 100% over the photo, set to that mode: top third
colour bars (W Y C G M R B K), middle third a black-to-white ramp, bottom third magenta #FF00C8 -> cyan #00E5FF fading from
opaque to transparent. Record the plate in each index row ("plate"). Pixel-scale filters (blur, sharpen, noise, edges, high
pass, minimum / maximum ...) also get a 1:1 crop <key>_1to1.png of the plate's bottom-right 512x512 (index row "crop").
Reference frames (same pipeline, no effect): ref.png per kind (gallery/ps_filter/ref.png = plain plate; gallery/ps_layer_style/
ref.png = the plain text plate; gallery/ps_blend_mode/ref.png = plate + top layer at Normal).`,
  AI: `APP: Illustrator 2026 (30.2.1), COM "Illustrator.Application"; reuse ${ROOT}/tools/ai/aicom.py (js / js_watch with
timeouts, dialogs answered by PostMessage), verify_live.py (applyEffect with a Dict, confirmed syntax 'R k 1.5 I k 3 B k 1
S k word U k word'), render_check.py (LiveEffect XML -> PNG) and psdata.py (Photoshop-effect descriptors). Never send
global input without host_lock("ui") AND a check that Illustrator is in front (a click once landed in Photoshop).
Plate: ${ROOT}/media/plate_vector.svg opened or placed and ungrouped as needed into a 1920x1080 RGB document with a white
artboard; raster effects resolution 150 ppi. ai_effect: applied to the whole group of plate shapes (path effects such as
Roughen / Zig Zag / Offset Path / Scribble act on every path; type stays live). ai_blend_mode: a magenta (#FF00C8) to cyan
(#00E5FF) gradient rectangle over the group set to that mode. Export each artboard to PNG at 960x540 (50%).
Reference frames: gallery/ai_effect/ref.png (plate alone), gallery/ai_blend_mode/ref.png (gradient at Normal).`,
  CDR: `APP: CorelDRAW 2024 (25.1), COM "CorelDRAW.Application.25"; reuse ${ROOT}/tools/cdr/cdr_com.py (Corel(): one COM owner
thread, timeouts, UIA dialog dismissal, private makepy cache), testdoc.py, apply_tests.py (the PROVEN bitmap-effect apply
path with data-source parameter keys, and Undo between runs) and vector_effects.py (Create* calls with typelib arguments).
Traps: imports can take minutes (not a hang until read bytes and CPU are both flat); absolute paths; optional VT_DISPATCH
args need None; the scripted bitmap path accepts values beyond the dialog range: use the card values as given.
Plates: bitmap / camera / colour / texture effects: ${ROOT}/media/plate_photo.png imported as a 1920x1080 px bitmap filling a
page of that size. Vector effects (Contour, Blend, Extrude, Envelope, Distort, Drop / Inner / Block Shadow, Bevel,
Perspective, Transparency, PowerClip): the shapes of ${ROOT}/media/plate_vector.svg imported on a white page of the same size
(a Blend needs two objects: blend the orange box into the star). Lens types: a lens circle (r = 300 px, centre 960,540)
over a page holding both the photo (left half) and the vector shapes (right half). Export each page to PNG at 960x540.
Reference frames: gallery/cdr_effect/ref_photo.png, ref_vector.png, ref_lens.png.`,
}

const PROMPT = `You render the EFFECT GALLERY of PGD ("professional graphics designer"), the verified knowledge an automated
design system has of Photoshop 2026, Illustrator 2026 and CorelDRAW 2024. Each visual knowledge card carries
"demo_settings": values its writer chose so the effect is unmistakable on a fixed test plate. You apply exactly those values
and save one frame per card; verifiers then judge every card against its frame. Read ${ROOT}/CONTRACT.md first.
${ONLY}
${SPEC[A]}

${args.note ? 'NOTE FROM THE ORCHESTRATOR: ' + args.note : ''}

Cards: ${ROOT}/cards/{${KINDS.join(',')}}_*.json (one card per harvested item: "id", "name", "status", "scriptable",
"demo_settings" keyed by harvested param name or key, "scripting"). Harvest (keys, types, units, enums, invoke):
${ROOT}/harvest/${CODE}/<kind>.json. Render every card whose status is "current" and scriptable is not "no"; map each
demo_settings entry to the harvested param (by name or key) and the value to the type the app wants (enum value / label ->
the app's enum id, units, colours). Cards that are not current or not scriptable: not_rendered.json with the reason.

Output per kind, ${ROOT}/gallery/<kind>/:
- <key>.png, 960x540, key = first 12 hex chars of sha1(card id as UTF-8) (identity, never list position);
- index.json: [{"key", "id", "name", "applied": {<param>: <value the app actually accepted / read back>}, "dropped":
  [<demo keys the app ignored or refused>], "how": "<the call used>"}];
- failed.json {id: "<error>"} (the apply or render failed), not_rendered.json {id: "<reason>"};
- the reference frame(s) named above.
Every card of these kinds ends up in exactly one of index.json, failed.json, not_rendered.json.

Write the renderer as ${ROOT}/tools/${CODE}/effect_gallery.py: resumable (skip keys whose PNG exists unless re-rendering),
checkpointing the json files every few items, with a --ids <file> option that re-renders just those ids (the verify wave
will use it). Look at your first frames of each kind (Read the PNGs next to the ref) and fix the renderer if a frame does not
show the card's effect (unchanged plate, black, cropped, effect on the wrong object). Rules: you own only this app; never
touch any other app; leave documents you did not open alone; close yours unsaved; timeouts on every app call; dialogs
dismissed by window handle; global input only inside host_lock("ui") from ${HOSTLOCK}; the machine
runs close to its memory commit limit, so close documents as soon as their frame is saved and check headroom() (same module)
before each batch: below 4 GB of commit headroom, restart your app and wait for room. Scratch:
${ROOT}/work/${CODE}/. Time box about 150 minutes. Return the summary.`

const OUT = {type: 'object', properties: {app: {type: 'string'}, rendered: {type: 'integer'}, failed: {type: 'integer'},
  not_rendered: {type: 'integer'}, dropped_keys: {type: 'integer'}, per_kind: {type: 'string'},
  traps: {type: 'array', items: {type: 'string'}}, notes: {type: 'string'}},
  required: ['app', 'rendered', 'failed', 'not_rendered', 'dropped_keys', 'per_kind', 'traps', 'notes']}

phase('Render effects')
return await agent(PROMPT, {label: `effects:${A}${RERENDER ? ' rerender' : ''}`, phase: 'Render effects', schema: OUT})
