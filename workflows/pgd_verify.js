export const meta = {
  name: 'pgd-verify',
  description: 'PGD wave 4: judge every visual card against its rendered frame, record the verdict in the card, fix wrong cards, list demos to re-render; second opinion on every non-pass',
  phases: [
    { title: 'Verify', detail: 'one visual verifier per card batch' },
    { title: 'Second opinion', detail: 'independent check of every non-pass verdict and every rewrite' },
  ],
}

// Launch args (Workflow `args`): root (required, the PGD folder, forward slashes), batches (required, visual card
// batch names); optional: width, recheck + ids (judge only these re-rendered cards).
//   {"root": "C:/src/PGD", "batches": ["ps_filter_01"], "width": 4}
if (!args || !args.root) throw new Error('pgd_verify.js needs args.root (the PGD folder), e.g. {"root": "C:/src/PGD", "batches": ["ps_filter_01"]}')
const ROOT = String(args.root).replace(/\\/g, '/').replace(/\/+$/, '')
const kindOf = b => b.replace(/_\d+$/, '')
const RECHECK = args.recheck ? `\nRECHECK RUN: some cards were re-rendered after an earlier verdict ("verified" already present).
Judge ONLY the cards whose id is in this list (leave the others exactly as they are): ${JSON.stringify(args.ids || [])}.
For each, judge the NEW frame, replace the verdict, and keep the earlier verdict object as verified.previous.\n` : ''

const SETUP = {
  ps_filter: 'the plain plate (ref.png): a soft 1920x1080 photo (judge and describe tones, edges and texture, never the people in it) with a crisp strip of 8 colour blocks, a grey ramp, white "PGD 2026" type and white hairlines along the bottom; the filter acts on the whole plate. The 960x540 frame is a 2x downsample, so pixel-scale filters (Blur, Sharpen, Noise families, Diffuse, Emboss, Find / Glowing Edges, Trace Contour, High Pass, Minimum, Maximum, De-Interlace, Film Grain, Grain, Mezzotint) also have <key>_1to1.png (index row "crop"): the plate\'s bottom-right 512x512 at 100 % from the same render (ref_1to1.png is the plain plate\'s); judge pixel-level claims on it. A row with "readback_stale" lists values the filter\'s result descriptor reported although the frame was proven (pixel diffs) to use the values sent; "changed" + "changed_check" says whether a different read-back was confirmed',
  ps_adjustment: 'the same photo plate as ps_filter (ref.png, same pixels as gallery/ps_filter/ref.png); the adjustment acts on the whole plate (Image > Adjustments items destructively, Layer > New Adjustment Layer items as an adjustment layer above it); the Grain adjustment layer also has a 1:1 crop (<key>_1to1.png, ref_1to1.png)',
  ps_layer_style: 'a mid-grey (#808080) 1920x1080 canvas with a light-grey (#E1E1E1) "PGD" text layer, Arial Black 360 px, centred (ref.png); the style is on that text layer',
  ps_blend_mode: 'the photo plate with a known top layer at Normal 100 % (ref.png): top third eight colour bars (white yellow cyan green magenta red blue black), middle third a black-to-white ramp, bottom third magenta-to-cyan fading from opaque (left) to transparent (right) over the photo; the frame shows that top layer in this mode (at Normal the top two thirds hide the photo)',
  ai_effect: 'the vector plate on a white artboard (ref.png): orange rounded box with a dark stroke, blue star, yellow-to-magenta gradient circle, black "PGD" type, open zigzag stroke; the effect is on the whole group',
  ai_blend_mode: 'the vector plate with a magenta-to-cyan gradient rectangle over it at Normal (ref.png); the frame shows that rectangle in this mode',
  cdr_effect: 'bitmap effects: the photo plate as a bitmap (ref_photo.png); vector effects: the vector plate shapes (ref_vector.png); lenses: a lens circle over photo (left) + shapes (right) (ref_lens.png). The 960x540 frame is a 2x downsample, so pixel-scale bitmap effects (Blur, Sharpen, Noise, Contour, Correction, Diffuse, DeInterlace) also have <key>_1to1.png (index row "crop"): the plate\'s bottom-right 512x512 at 100 % from the same render (hairlines, colour-bar edges, grey ramp, small bright highlights); judge pixel-level claims on it against the same crop of media/plate_photo.png',
}

function prompt(b) {
  const k = kindOf(b)
  return `You verify knowledge cards of PGD (an automated design system's knowledge of Photoshop 2026, Illustrator 2026 and
CorelDRAW 2024) against real renders. Card file: ${ROOT}/cards/${b}.json. Ground truth (names, params, ranges):
${ROOT}/work/batches/${b}.json. Card format: ${ROOT}/CONTRACT.md "Card format".
${RECHECK}
Frames: ${ROOT}/gallery/${k}/index.json lists {key, id, name, applied, dropped, how}; the frame for a card is
${ROOT}/gallery/${k}/<key>.png (960x540) where key matches the card's id in index.json. The render set-up: ${SETUP[k]}.
Reference frame(s) in ${ROOT}/gallery/${k}/ (ref*.png). Cards in ${ROOT}/gallery/${k}/failed.json broke the render (verdict
"broken", quote the error); cards in not_rendered.json or absent from index.json were not rendered ("not_rendered").
"applied" is what the app accepted; "dropped" lists demo keys it ignored: a dropped key means that part of the demo did not
happen.

For EVERY card: open its frame and the reference with the Read tool and compare. Decide:
 "pass"   the frame clearly shows what the summary / look describe;
 "weak"   the effect is there but too subtle to judge or to be useful: raise demo_settings (stay inside the batch ranges /
          enums) and set rerender true;
 "wrong"  something visible happened but not what the card says: rewrite summary / look / use_for / avoid to match what the
          frame shows (and what you know of the effect), or fix demo_settings if they caused it (rerender true);
 "broken" the frame is unchanged, black, transparent or garbage: fix demo_settings if they are the cause (a no-op value, an
          off-frame point, a mode that hides the image) with rerender true, otherwise status "needs_input" or "unusable"
          and explain;
 "not_rendered" no frame.
Judge the claim against the frame itself: a family description copied from a sibling is exactly what this check exists to
catch, and a relative claim ("warmer", "lighter") must be visible against the reference, not assumed.
Write into each card "verified": {"verdict": ..., "frame": "<frame path>", "note": "<what you saw, one sentence>",
"rerender": true | false}. Keep everything else valid and names exact. Then run
  python ${ROOT}/validate_cards.py ${ROOT}/work/batches/${b}.json ${ROOT}/cards/${b}.json
until 0 issues. Return the summary ("rerender" = ids whose demo_settings you changed).`
}

function second(b, v) {
  const k = kindOf(b)
  return `Independent second check of PGD card batch ${b} (${ROOT}/cards/${b}.json; ground truth ${ROOT}/work/batches/${b}.json;
frames ${ROOT}/gallery/${k}/<key>.png via ${ROOT}/gallery/${k}/index.json; references ${ROOT}/gallery/${k}/ref*.png; set-up:
${SETUP[k]}). The first verifier gave these cards a non-pass verdict and may have rewritten them: ${v.non_pass.join('; ')}.
For each, look at the frame yourself and check BOTH the verdict and any rewrite or new demo_settings: is the verdict right,
is the rewritten text true of the frame and of the effect, are new demo_settings inside the batch ranges and likely to
show the effect (not a no-op, not destructive)? Correct what is wrong. Add "second_opinion": "agree" | "corrected: <what>"
inside each card's "verified". Then run python ${ROOT}/validate_cards.py ${ROOT}/work/batches/${b}.json ${ROOT}/cards/${b}.json
until 0 issues. Return the summary.`
}

const OUT = {type: 'object', properties: {batch: {type: 'string'}, pass: {type: 'integer'}, weak: {type: 'integer'},
  wrong: {type: 'integer'}, broken: {type: 'integer'}, not_rendered: {type: 'integer'},
  non_pass: {type: 'array', items: {type: 'string'}}, rerender: {type: 'array', items: {type: 'string'}}},
  required: ['batch', 'pass', 'weak', 'wrong', 'broken', 'not_rendered', 'non_pass', 'rerender']}
const SECOND = {type: 'object', properties: {batch: {type: 'string'}, agreed: {type: 'integer'}, corrected: {type: 'integer'},
  rerender: {type: 'array', items: {type: 'string'}}}, required: ['batch', 'agreed', 'corrected', 'rerender']}

const one = (b) => agent(prompt(b), {label: `verify:${b}`, phase: 'Verify', schema: OUT})
  .then(v => (v && v.non_pass && v.non_pass.length)
    ? agent(second(b, v), {label: `second:${b}`, phase: 'Second opinion', schema: SECOND}).then(s => ({b, v, s}))
    : {b, v, s: null})
// args.width bounds how many batches run at once (each agent carries ~1.3 GB of tool servers: obs 605)
let res = []
const W = args.width || args.batches.length
for (let i = 0; i < args.batches.length; i += W) {
  res = res.concat(await parallel(args.batches.slice(i, i + W).map(b => () => one(b))))
}
const rows = res.filter(Boolean)
const tot = k => rows.reduce((a, r) => a + ((r.v && r.v[k]) || 0), 0)
log(`pass ${tot('pass')}, weak ${tot('weak')}, wrong ${tot('wrong')}, broken ${tot('broken')}, not rendered ${tot('not_rendered')}`)
return {totals: {pass: tot('pass'), weak: tot('weak'), wrong: tot('wrong'), broken: tot('broken'), not_rendered: tot('not_rendered')},
  rerender: [...new Set(rows.flatMap(r => [].concat((r.v && r.v.rerender) || [], (r.s && r.s.rerender) || [])))],
  failed: args.batches.filter(b => !rows.find(r => r.b === b && r.v)),
  per_batch: rows.map(r => ({batch: r.b, pass: r.v && r.v.pass, non_pass: r.v && r.v.non_pass, corrected: r.s && r.s.corrected,
    rerender: [...new Set([].concat((r.v && r.v.rerender) || [], (r.s && r.s.rerender) || []))]}))}
