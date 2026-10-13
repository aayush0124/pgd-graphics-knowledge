export const meta = {
  name: 'pgd-recipes',
  description: 'PGD wave 6: build verified design recipes (looks, text effects, print prep ...) from the verified cards, each step checked by pgd.py, then a completeness critic',
  phases: [
    { title: 'Recipes', detail: 'one agent per recipe family, only from verified cards' },
    { title: 'Critic', detail: 'what PGD still does not know' },
  ],
}

// Launch args (Workflow `args`): root (required, the PGD folder, forward slashes); optional only_critic / skip_critic.
//   {"root": "C:/src/PGD"}
if (!args || !args.root) throw new Error('pgd_recipes.js needs args.root (the PGD folder), e.g. {"root": "C:/src/PGD"}')
const ROOT = String(args.root).replace(/\\/g, '/').replace(/\/+$/, '')
const FAMILIES = [
  {key: 'photo_looks', ask: 'photo grades and looks: clean news correction, cinematic teal-orange, warm nostalgic, faded matte film, high-contrast black-and-white, duotone poster, cross-process, saffron / brand accent, night-time cool'},
  {key: 'text_effects', ask: 'headline and text effects: neon glow, gold / metallic, chrome, 3D extruded, long shadow, outline + offset stroke, embossed / letterpress, glitch / RGB split, sticker outline, retro 80s'},
  {key: 'poster_print', ask: 'poster and print textures: halftone, risograph, screen print, posterize pop art / comic, grunge and paper texture, newspaper print, torn-paper collage, woodcut / engraving'},
  {key: 'vector_illustration', ask: 'vector illustration treatments: hand-drawn roughen / scribble, isometric or extruded 3D, blend steps and contour lines, patterns and repeats, warp / envelope type, line-art icon style, flat long-shadow icons'},
  {key: 'cutout_social', ask: 'cut-outs and social graphics: subject cut-out with white sticker outline and drop shadow, glow outline around a person, background blur / bokeh, YouTube-style thumbnail punch (saturation, rim light, outline), frame / border treatments'},
  {key: 'retouch_cleanup', ask: 'photo repair and retouch: denoise, sharpen for print and for web, remove objects / blemishes, dodge and burn, skin smoothing that keeps texture, straighten / perspective fix, upscale, dehaze'},
  {key: 'print_prep', ask: 'print production: CMYK conversion, rich black vs 100K, overprint, bleed and crop marks, outline text, flatten transparency, PDF/X export, colour proofing, spot colours, minimum line and type sizes'},
  {key: 'news_editorial', ask: 'generic news and explainer graphics treatments: press-photo frame with caption strip, quote card with a speaker cut-out, breaking-news strap, data highlight (glow / stroke / marker), map callout, before/after split, document or screenshot zoom with highlighter'},
]

function recipePrompt(f) {
  return `You are designing RECIPES for PGD ("professional graphics designer"), the knowledge base of an automated design
system that drives Photoshop 2026, Illustrator 2026 and CorelDRAW 2024 by script. Cards (one per effect / filter /
adjustment / style / blend mode / tool / menu command / preset, written from the apps' own harvested data) are in
${ROOT}/cards/*.json; visual cards carry "verified": {"verdict": "pass"} when their render matched the description
(frames in ${ROOT}/gallery/). Search and read them with:
  python ${ROOT}/pgd.py find "<words>" [PS|AI|CDR]      python ${ROOT}/pgd.py card "<name or id>" [PS|AI|CDR]
  python ${ROOT}/pgd.py equiv "<name>"                    python ${ROOT}/pgd.py items <PS|AI|CDR> "<words>"
Card format and plan format: ${ROOT}/CONTRACT.md and the docstring of ${ROOT}/pgd.py (check_plan).

Family: ${f.ask}.
Write 8-16 recipes to ${ROOT}/cards/recipe_${f.key}.json as {"cards": [ ... ]}, each:
{"kind": "recipe", "family": "${f.key}", "name": "<short name>", "id": "recipe:${f.key}:<slug>", "app": "PS" | "AI" | "CDR"
 | "multi", "status": "current", "summary": "<the look / job in one sentence>", "use_for": [...], "avoid": [...],
 "plans": {"PS": {"app": "PS", "steps": [{"kind": "<card kind>", "name" | "id": "<harvested name or id>", "settings":
 {<param name or key>: value}, "note": "<what this step does, layer / object it acts on>"}]}, "AI": {...}, "CDR": {...}},
 "manual_steps": ["steps a script cannot do (a tool used by hand), if any"], "built_from": ["<card ids used>"],
 "confidence": "high" | "medium" | "low"}.
Rules: use ONLY items that have cards; prefer cards whose verified verdict is "pass" and whose scriptable is "yes"; use exact
names / ids and param names / keys with values inside the harvested ranges (read each card's params, demo_settings and
scripting before using it); give a plan for every app that can do the job (Photoshop for pixels, Illustrator / CorelDRAW for
vector and print), and leave an app out when it cannot. Check EVERY plan with
  python ${ROOT}/pgd.py check <a temp file holding that one plan>
(scratch folder ${ROOT}/work/agents/recipe_${f.key}/) and fix it until pgd.py reports nothing. Return the summary.`
}

const CRITIC = `You are the completeness critic for PGD (${ROOT}): an automated design system's knowledge of Photoshop 2026,
Illustrator 2026 and CorelDRAW 2024. Run  python ${ROOT}/build_docs.py  then read ${ROOT}/PGD.md, run
python ${ROOT}/pgd.py stats, sample the cards in ${ROOT}/cards/ and the harvest in ${ROOT}/harvest/ (items carrying "error"
are known gaps), and the gallery failure lists (${ROOT}/gallery/*/failed.json). Answer:
1. Which capabilities a professional graphic designer relies on are NOT covered by any card or recipe (for example:
   Photoshop smart objects / layer masks / clipping / selections / channels / Camera Raw / Generative Fill; Illustrator
   appearance stacks, Pathfinder, Image Trace, Recolor Artwork, type on a path, artboards export; CorelDRAW PowerClip,
   styles and colour styles, print merge, Corel Font Manager, page layout and master pages)?
2. Which cards look thin, wrong or contradictory (spot-check 40 at random across kinds, against your knowledge and the
   harvest)?
3. Which verified verdicts look doubtful (open 15 frames and judge them yourself)?
4. Which harvest gaps matter most to fill next, and how (concrete commands / files)?
Write ${ROOT}/cards/zz_critic.json as {"gaps": [...], "weak_cards": [...], "doubtful": [...], "next_steps": [...]} and return a
short summary.`

const SUM = {type: 'object', properties: {family: {type: 'string'}, recipes: {type: 'integer'}, apps: {type: 'string'},
  notes: {type: 'string'}}, required: ['family', 'recipes', 'apps', 'notes']}
const A = args || {}
let made = []
if (!A.only_critic) {
  phase('Recipes')
  made = await parallel(FAMILIES.map(f => () => agent(recipePrompt(f), {label: `recipes:${f.key}`, phase: 'Recipes', schema: SUM})))
}
if (A.skip_critic) return {recipes: made.filter(Boolean)}
phase('Critic')
const critic = await agent(CRITIC, {label: 'critic', phase: 'Critic'})
return {recipes: made.filter(Boolean), critic}
