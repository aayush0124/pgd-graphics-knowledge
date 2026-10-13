export const meta = {
  name: 'pgd-cards',
  description: 'PGD wave 2: write a knowledge card for every harvested item of each batch, validate it against the harvest, then an adversarial reviewer corrects it',
  phases: [
    { title: 'Write', detail: 'one writer per batch, validated against the harvest' },
    { title: 'Review', detail: 'one adversarial reviewer per batch: refute and correct' },
  ],
}

// Launch args (Workflow `args`): root (required, the PGD folder, forward slashes), batches (required, batch names
// from work/batches, e.g. ["ps_filter_01", "ps_tool_02"]).   {"root": "C:/src/PGD", "batches": ["ps_filter_01"]}
if (!args || !args.root) throw new Error('pgd_cards.js needs args.root (the PGD folder), e.g. {"root": "C:/src/PGD", "batches": ["ps_filter_01"]}')
const ROOT = String(args.root).replace(/\\/g, '/').replace(/\/+$/, '')
const VISUAL = ['ps_filter', 'ps_adjustment', 'ps_layer_style', 'ps_blend_mode', 'ai_effect', 'ai_blend_mode', 'cdr_effect']
const kindOf = b => b.replace(/_x?\d+$/, '')
const tierOf = b => { const k = kindOf(b); return VISUAL.includes(k) ? 'visual' : k.split('_').slice(1).join('_') }
const APPN = {ps: 'Photoshop 2026 (27.4)', ai: 'Illustrator 2026 (30.2)', cdr: 'CorelDRAW 2024 (25.1)'}

const PLATES = `The gallery will render each visual card's demo_settings on fixed test plates, so pick values for THEM:
- Photoshop: ${ROOT}/media/plate_photo.png (1920x1080; look at it): a SOFT, slightly blurry photographic video frame
  (describe an effect by its tones, edges and texture, never the people in it), plus a crisp strip along the bottom (8 saturated colour blocks, a grey
  ramp, white "PGD 2026" type, white hairlines 1-6 px). Filters and adjustments act on the whole plate. Layer styles act on
  a white "PGD" type layer above the photo. Blend modes: a magenta-to-cyan gradient layer over the photo set to that mode.
  Because the photo is already soft, blurs need a clearly larger radius than on a sharp photo to read as blurred.
- Illustrator: ${ROOT}/media/plate_vector.svg on a white 1920x1080 artboard: orange rounded box with a dark 6 px stroke,
  blue star, yellow-to-magenta gradient circle, black "PGD" type, an open black zigzag stroke. Effects apply to that whole
  group (Photoshop Effects rasterize at the document's raster effects resolution). Blend modes: a magenta-to-cyan gradient
  rectangle over the group set to that mode.
- CorelDRAW: vector effects apply to the plate_vector.svg shapes imported on a page; bitmap effects apply to
  plate_photo.png imported as a bitmap; lenses sit over both.`

const TIER = {
  visual: `VISUAL card fields: look (keywords a designer would search: "soft focus", "neon", "halftone" ...), params (the
settings a designer actually changes, each {"name": <harvested param name or key EXACTLY>, "does", "typical"}),
demo_settings ({<harvested param name or key>: value}: values that make the effect unmistakable on the test plate while
staying inside the harvested type / min..max / enum; for an enum use a harvested value or label), enum_labels when values are
codes, pairs_with, scripting (the exact call that applies it, built from the item's "invoke" and params: PS
executeAction(stringIDToTypeID("<event>"), desc, DialogModes.NO) naming the keys; AI pageItem.applyEffect('<LiveEffect
name="..."><Dict data="..."/></LiveEffect>') or app.executeMenuCommand("..."); CDR the cdr_com signature or the effect path
in invoke), scriptable ("yes" if a script can apply it with chosen values, "partial" if only with defaults / with a dialog /
needing extra input, "no"), non_destructive (smart filter / live effect / CorelDRAW effect stack?) when the harvest says,
cost. An item whose harvest "error" says it cannot run headless is still described; say so in avoid / scripting and
set scriptable accordingly. CorelDRAW bitmap effects: the harvest notes the scripted path often accepts values beyond the
dialog range (extra.range_note): stay inside the dialog range anyway.
${PLATES}`,
  tool: `TOOL card fields: how (how a designer uses it: click / drag, modifier keys, the options that matter), shortcut (from the
harvest), scriptable ("yes" / "partial" / "no": selecting a tool by script is not the same as using it; a brush stroke
can be scripted in Photoshop via path stroking, most hand tools cannot), script_api (what a script can do instead, with
the exact id from the harvest's invoke), use_for, avoid, equivalents.`,
  menu: `MENU card fields: summary (what the command does), how (when it opens a dialog: the choices that matter), shortcut,
scriptable ("yes" when the harvest's invoke runs it, e.g. CorelDRAW FrameWork.Automation.InvokeItem("<guid>");
"partial" when it only opens a dialog; "no"), script_api (the exact call from invoke; for a command that opens a dialog,
the object-model call that does the same job if you know it, marked "(unverified)"), use_for, equivalents.`,
  api: `API card fields: how (what the class / interface is for and how a script reaches it, e.g. app.activeDocument.artLayers),
key_members (the 5-20 members that matter, each {"name": <a member name EXACTLY as in the item's extra.members>, "use"}),
gotchas (traps you know for this class in this app; mark ones you have not seen confirmed with "(unverified)"), example (a
short snippet, at most 8 lines, using only harvested members), use_for. Do not name members that are not in extra.members.`,
}

function writePrompt(b) {
  const app = b.split('_')[0]
  return `You write knowledge cards for PGD ("professional graphics designer"): what an automated design system knows about
Photoshop 2026, Illustrator 2026 and CorelDRAW 2024 (sibling of PVE for After Effects / Premiere). Read ${ROOT}/CONTRACT.md,
section "Card format", first.

Batch (the ground truth, harvested from ${APPN[app]}): ${ROOT}/work/batches/${b}.json.
Write ${ROOT}/cards/${b}.json as {"cards": [...]}: exactly one card per batch item, "id" and "name" copied exactly, "app" and
"kind" from the batch.

Where facts come from:
- names, ids, paths, params, keys, types, ranges, defaults, enum values, shortcuts, invoke: ONLY from the batch file.
- what an item does, how it looks, when to use it: your knowledge of this app, checked against the batch (its params,
  evidence, error and extra notes). Describe THIS item: never reuse a sibling's wording because the names look alike (a
  family of filters or presets shares a menu, not a look). When you are unsure what an item does, say so in the summary and
  set confidence "low" or "medium"; never fill the gap with a guess dressed as fact.
- equivalents: the closest item in each OTHER app that does the same job (same result, not just a similar name). Look the
  exact harvested name up with:  python ${ROOT}/pgd.py items <PS|AI|CDR> "<words>"   and copy a name, id or path from its
  output. Leave an app out when nothing really matches.
- status: current, unless the harvest shows it is obsolete / hidden, needs_input (needs a selection, path, text, second image,
  map file ...) or unusable.

${TIER[tierOf(b)]}

Then run:  python ${ROOT}/validate_cards.py ${ROOT}/work/batches/${b}.json ${ROOT}/cards/${b}.json
and fix the cards until it reports 0 issues. Use a private scratch folder ${ROOT}/work/agents/${b}/ for any helper file.
Return the summary.`
}

function reviewPrompt(b, w) {
  return `Adversarial review of PGD knowledge cards ${ROOT}/cards/${b}.json against their ground truth ${ROOT}/work/batches/${b}.json
(card format: ${ROOT}/CONTRACT.md "Card format"). The writer reported: ${JSON.stringify(w)}.
Assume the cards are wrong somewhere and find where. For EVERY card check:
1. The summary / look / use_for / how describe THIS item as it behaves in this app version, not a sibling or a family
   template; no claim contradicts the batch (params, evidence, error, extra notes).
2. Every number, range, default, key, shortcut and id stated anywhere in the card is in the batch; nothing invented.
3. status and scriptable are right; scripting / script_api is the call the batch's invoke supports, with real keys.
4. ${tierOf(b) === 'visual' ? 'demo_settings would make the effect unmistakable on the test plate described in the writer brief (soft 1920x1080 press photo with a crisp colour/type strip for Photoshop; the vector plate for Illustrator / CorelDRAW) and sit inside the harvested ranges / enums.' : tierOf(b) === 'api' ? 'key_members are real members of the item and the example would run.' : 'how / shortcut / script_api are right for this app.'}
5. equivalents name the real counterpart (same job and result) and exist (python ${ROOT}/pgd.py items <APP> "<words>").
Fix wrong cards in place, keeping them valid, and add to each card "review": {"by": "adversarial", "changes": "<what you
changed, or none>"}. Then run  python ${ROOT}/validate_cards.py ${ROOT}/work/batches/${b}.json ${ROOT}/cards/${b}.json
until 0 issues. Scratch: ${ROOT}/work/agents/${b}/. Return the summary.`
}

const WROTE = {type: 'object', properties: {batch: {type: 'string'}, cards: {type: 'integer'}, low_confidence: {type: 'integer'},
  validator_issues: {type: 'integer'}, notes: {type: 'string'}}, required: ['batch', 'cards', 'low_confidence', 'validator_issues', 'notes']}
const REVIEWED = {type: 'object', properties: {batch: {type: 'string'}, cards: {type: 'integer'}, corrected: {type: 'integer'},
  validator_issues: {type: 'integer'}, worst: {type: 'string'}}, required: ['batch', 'cards', 'corrected', 'validator_issues', 'worst']}

const order = b => ({visual: 0, tool: 1, menu: 2, api: 3}[tierOf(b)] ?? 4)
const batches = [...args.batches].sort((a, b) => order(a) - order(b))
const res = await pipeline(batches,
  (b) => agent(writePrompt(b), {label: `write:${b}`, phase: 'Write', schema: WROTE}),
  (w, b) => agent(reviewPrompt(b, w), {label: `review:${b}`, phase: 'Review', schema: REVIEWED}).then(r => ({b, w, r})))
const rows = res.filter(Boolean)
const failed = batches.filter(b => !rows.find(x => x.b === b && x.r))
log(`${rows.length}/${batches.length} batches reviewed; corrected ${rows.reduce((a, x) => a + ((x.r && x.r.corrected) || 0), 0)} cards`)
return {done: rows.map(x => ({b: x.b, cards: x.w && x.w.cards, low: x.w && x.w.low_confidence, corrected: x.r && x.r.corrected,
  issues: x.r && x.r.validator_issues, worst: x.r && x.r.worst})), failed}
