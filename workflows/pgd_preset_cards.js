export const meta = {
  name: 'pgd-preset-cards',
  description: 'PGD wave 5: write preset cards FROM their rendered thumbnails (contact sheets), then a reviewer checks each card against its cell and records a verdict',
  phases: [
    { title: 'Write', detail: 'one writer per preset batch, from the contact sheets' },
    { title: 'Review', detail: 'one reviewer per batch: card vs thumbnail, verdict recorded' },
  ],
}

// Launch args (Workflow `args`): root (required, the PGD folder, forward slashes), batches (required, preset batch
// names, e.g. ["ai_preset_18"]); optional width (batches at once).   {"root": "C:/src/PGD", "batches": ["ai_preset_18"], "width": 3}
if (!args || !args.root) throw new Error('pgd_preset_cards.js needs args.root (the PGD folder), e.g. {"root": "C:/src/PGD", "batches": ["ai_preset_18"]}')
const ROOT = String(args.root).replace(/\\/g, '/').replace(/\/+$/, '')
const kindOf = b => b.replace(/_\d+$/, '')
const APPN = {ps: 'Photoshop 2026', ai: 'Illustrator 2026', cdr: 'CorelDRAW 2024'}

function sheets(b) {
  return `If ${ROOT}/work/sheets/${b}_sheets.json does not exist yet, build the sheets first:
  cd ${ROOT} && python make_sheets.py ${b}
Contact sheets: ${ROOT}/work/sheets/${b}_s1.png and ${b}_s2.png (if it exists): a 5 x 4 grid per sheet, each cell
labelled "<n>. <name>" where n is the item's position in the batch (1-based). ${ROOT}/work/sheets/${b}_sheets.json lists
{n, id, sheet, state, how, reason} per item: state "rendered" (how = "applied: ..." | "file image" | "embedded thumbnail" |
"swatch strip"), "not visual" (reason says why; for actions it may hold the step list), "render failed" (reason = error)
or "no render". The full-size thumbnail of a rendered item is ${ROOT}/gallery/${kindOf(b)}/<key>.png (key = first 12 hex of
sha1(id)); ${ROOT}/gallery/${kindOf(b)}/index.json maps id -> key.`
}

function writePrompt(b) {
  const app = b.split('_')[0]
  return `You write knowledge cards for PGD ("professional graphics designer"): what an automated design system knows about
Photoshop 2026, Illustrator 2026 and CorelDRAW 2024. This batch is PRESETS of ${APPN[app]}. Read ${ROOT}/CONTRACT.md,
section "Card format", first.

Ground truth: ${ROOT}/work/batches/${b}.json (name, id, path, category, invoke, requires, evidence, extra per item).
${sheets(b)}

Write ${ROOT}/cards/${b}.json as {"cards": [...]}: exactly one card per batch item, "id" and "name" copied exactly, "app"
and "kind" from the batch. Preset card fields: summary, look (keywords), use_for, avoid, applies_to (the layer / object
type it works on: from requires and category), how_to_apply (from invoke: the call or the panel route), status,
confidence, equivalents (optional: a preset of another app with the same look, found with
python ${ROOT}/pgd.py items <PS|AI|CDR> "<words>"; usually none).
- Rendered items: describe what the THUMBNAIL shows (open the sheet; open the full-size thumbnail when a cell is too small
  to read): colours, shape, texture, stroke character, mood. Never describe a preset from its name alone when you can see it;
  when the name and the picture disagree, the picture wins and the summary says so. Note when the thumbnail is the preset's
  own shipped preview ("embedded thumbnail" / "file image") rather than an application by script.
- "not visual" items: describe them from name, category, path and reason (an action's steps, a document preset's size and
  units if the name or extra says so); do not invent settings.
- "render failed" / "no render" items: describe what you can from name and category, confidence "low", and say in avoid
  that the look is unverified.
Then run  python ${ROOT}/validate_cards.py ${ROOT}/work/batches/${b}.json ${ROOT}/cards/${b}.json  until 0 issues.
Scratch: ${ROOT}/work/agents/${b}/. Return the summary.`
}

function reviewPrompt(b, w) {
  return `Review PGD preset cards ${ROOT}/cards/${b}.json against their thumbnails and ground truth
${ROOT}/work/batches/${b}.json (card format: ${ROOT}/CONTRACT.md "Card format"). The writer reported: ${JSON.stringify(w)}.
${sheets(b)}
For EVERY card: look at its cell (and the full-size thumbnail when the cell is small) and check that summary / look describe
what is really there (colour, shape, texture, style), not what the name suggests; that applies_to / how_to_apply match the
batch's requires / invoke; that nothing is invented. Fix wrong cards in place. Then add to each card
"verified": {"verdict": "pass" (the card matches its thumbnail) | "wrong" (it did not; you rewrote it from the thumbnail) |
"weak" (the thumbnail is too small or faint to confirm the description) | "not_rendered" (no thumbnail), "frame": "<thumbnail
path or empty>", "note": "<what you saw, one sentence>", "rerender": false}
and "review": {"by": "thumbnail check", "changes": "<what you changed, or none>"}. Then run
python ${ROOT}/validate_cards.py ${ROOT}/work/batches/${b}.json ${ROOT}/cards/${b}.json  until 0 issues.
Scratch: ${ROOT}/work/agents/${b}/. Return the summary.`
}

const WROTE = {type: 'object', properties: {batch: {type: 'string'}, cards: {type: 'integer'}, from_thumbnail: {type: 'integer'},
  low_confidence: {type: 'integer'}, validator_issues: {type: 'integer'}, notes: {type: 'string'}},
  required: ['batch', 'cards', 'from_thumbnail', 'low_confidence', 'validator_issues', 'notes']}
const REVIEWED = {type: 'object', properties: {batch: {type: 'string'}, pass: {type: 'integer'}, wrong: {type: 'integer'},
  weak: {type: 'integer'}, not_rendered: {type: 'integer'}, validator_issues: {type: 'integer'}, worst: {type: 'string'}},
  required: ['batch', 'pass', 'wrong', 'weak', 'not_rendered', 'validator_issues', 'worst']}

const one = (b) => agent(writePrompt(b), {label: `write:${b}`, phase: 'Write', schema: WROTE})
  .then(w => agent(reviewPrompt(b, w), {label: `review:${b}`, phase: 'Review', schema: REVIEWED}).then(r => ({b, w, r})))
// args.width bounds how many batches run at once (each agent carries ~1.3 GB of tool servers: obs 605)
let res = []
if (args.width) {
  for (let i = 0; i < args.batches.length; i += args.width) {
    res = res.concat(await parallel(args.batches.slice(i, i + args.width).map(b => () => one(b))))
    log(`${Math.min(i + args.width, args.batches.length)}/${args.batches.length} batches`)
  }
} else {
  res = await parallel(args.batches.map(b => () => one(b)))
}
const rows = res.filter(Boolean)
const tot = k => rows.reduce((a, x) => a + ((x.r && x.r[k]) || 0), 0)
log(`${rows.length}/${args.batches.length} preset batches; pass ${tot('pass')}, wrong ${tot('wrong')}, weak ${tot('weak')}, not rendered ${tot('not_rendered')}`)
return {totals: {pass: tot('pass'), wrong: tot('wrong'), weak: tot('weak'), not_rendered: tot('not_rendered')},
  failed: args.batches.filter(b => !rows.find(x => x.b === b && x.r)),
  per_batch: rows.map(x => ({b: x.b, cards: x.w && x.w.cards, pass: x.r && x.r.pass, wrong: x.r && x.r.wrong, worst: x.r && x.r.worst}))}
