export const meta = {
  name: 'pgd-plans',
  description: 'PGD plan runs: per app, one owner agent makes every recipe plan run in the live app (inputs, targets, scripts, notes) and records the run; independent judges give each recorded run a verdict, with a second opinion on every non-pass',
  phases: [
    { title: 'Run plans', detail: 'one owner agent per app, family by family (apps run side by side, never two agents on one app)' },
    { title: 'Judge', detail: 'one judge per app and family: the final frame and the step strip against the recipe summary' },
    { title: 'Second opinion', detail: 'independent check of every non-pass verdict' },
  ],
}

// Launch args (Workflow `args`): root (required, the PGD folder, forward slashes), apps (required, e.g. ["PS", "CDR"]:
// only apps no other client is using). Optional: families (default all eight, in FAMILIES order), judge (default
// true), author_model (default 'sonnet'), judge_model (default 'opus').
//   {"root": "C:/src/PGD", "apps": ["PS", "CDR"], "families": ["text_effects"]}
if (!args || !args.root || !args.apps || !args.apps.length) {
  throw new Error('pgd_plans.js needs args.root (the PGD folder) and args.apps, e.g. {"root": "C:/src/PGD", "apps": ["PS", "CDR"]}')
}
const ROOT = String(args.root).replace(/\\/g, '/').replace(/\/+$/, '')
const FAMILIES = args.families || ['text_effects', 'cutout_social', 'news_editorial', 'photo_looks', 'retouch_cleanup',
  'poster_print', 'vector_illustration', 'print_prep']
const AUTHOR_MODEL = args.author_model || 'sonnet'
const JUDGE_MODEL = args.judge_model || 'opus'

const APP = {
  PS: {name: 'Photoshop 2026', backend: 'tools/ps/plan_ps.py', script: `ExtendScript (ES3) run inside function(d, L): d = the
working document, L = the active / target layer; helpers S2T, C2T, tk, buildDesc(spec), rgbc(r,g,b), hexc('#RRGGBB'),
setMode(blendModeStringID), adjLayer(cls, spec), selById(layerID), layerDesc(), actId(), tref, selRef, mkMaskDesc(how),
the Photoshop DOM and executeAction. Selections: d.selection.select([[x,y], ...]) in px. A Solid Color fill layer: the
contentLayer descriptor of ps_menu id 6300 (harvest/ps/ps_menu.json extra.invoke_descriptor_js) with the plan's colour`,
    inputs: `{"plate": "photo"} (label photo = the Background), {"plate": "text", "text", "background", "color"} (labels type,
background), {"plate": "photo", "text", "at": [x, y], "size", "color"} for type on the photo, {"plate": "blank", "background"}`},
  CDR: {name: 'CorelDRAW 2024', backend: 'tools/cdr/plan_cdr.py', script: `Python run with app, doc, layer (the work layer),
s (the target / active shape), labels (label -> shape), rgb('#RRGGBB'), PW, PH (page in inches, 20 x 11.25, bottom-left
origin), PX (96 px per inch); set result = <shape> to make it active, add new shapes to labels for later targets. The VGCore
object model (CreateRectangle2, CreateArtisticText, Fill.ApplyUniformFill, ConvertToBitmapEx, ConvertToCurves, Duplicate,
CreateBlend(other, ...), AddToPowerClip(container) ...); exact signatures in the cdr_api cards (python pgd.py find "<member>"
CDR cdr_api). Bitmap effects need a bitmap target: convert vector art first`,
    inputs: `{"plate": "photo"} (label photo), {"plate": "vector"} (orange_box, blue_star, grad_circle, pgd_type, zigzag; no
"art" in CorelDRAW), {"plate": "text", ...} (type, background), {"plate": "photo", "text", "at", "size", "color"},
{"plate": "blank", "background"}`},
  AI: {name: 'Illustrator 2026', backend: 'tools/ai/plan_ai.py', script: `ExtendScript run with d = the document, T = the
target / active item, g = group PGD_TEST (or null), r = the result object (r.active = an item name makes it active);
helpers byName(name), nameOf(item), rgb('#RRGGBB'), AB (the artboard rect); name every item a later step targets`,
    inputs: `{"plate": "vector"} (art = group PGD_TEST, and orange_box, blue_star, grad_circle, pgd_type, zigzag),
{"plate": "photo"} (photo), {"plate": "text", ...} (type, background), {"plate": "photo", "text", "at", "size", "color"},
{"plate": "blank", "background"}`},
}

function authorPrompt(app, fam) {
  const A = APP[app]
  return `You own ${A.name} for PGD's plan runner. Repo: ${ROOT} (public; code MIT, cards CC BY 4.0). Make every ${app}
plan of the recipe family "${fam}" run in ${A.name} and produce what its recipe summary describes, and record the run.
Read first: ${ROOT}/run_plan.py (docstring: plan format, commands), ${ROOT}/${A.backend} (routes, what a script gets),
pgd.py check_plan's docstring. Commands, from ${ROOT} with PYTHONIOENCODING=utf-8:
  python run_plan.py list ${app} | python run_plan.py show <key> ${app} (MANUAL / PLAN ERROR lines say what is missing)
  python run_plan.py get <key> ${app} > work/agents/plans_${app.toLowerCase()}/<key>.json ; edit ; python run_plan.py put <key> ${app} <that file>
  python run_plan.py run <key> ${app} --force (live; records the run) [--no-record to try]
Frames: gallery/recipes/${app}/<key>.png (final) and <key>_steps.png (input + every step); LOOK at both after every run.
Per plan: set "input" explicitly (${A.inputs}); give the step that leaves a layer / object a later step must act on an "as"
label and the later step a "target"; give manual steps (api / tool / preset steps, menu commands that need values or open a
dialog) a "script" that does what the note says with the plan's own values: ${A.script}. Keep scripts short; they are
published. Steps that need a human (choosing by eye, painting a mask, print dialogs) stay manual with an honest note. Never
print, change app preferences / colour settings, or write files outside ${ROOT}/work/plans/out/<key>/. put, run --force,
look, iterate (about 4 tries at most); then make each step's note state what the run showed ("Untested: ..." where not
checked). Do not write "verified" (judges do), do not touch other apps' plans or card files directly (only get / put), do
not change code (write runner bugs to work/agents/plans_${app.toLowerCase()}/BUGS.md and go on).
You are the only user of ${A.name}; never start, kill or script another app (other owners run them now). Scratch only in
${ROOT}/work/agents/plans_${app.toLowerCase()}/. Public text rules for notes and scripts: never describe or identify the
people in the test photo (only "the subject(s)", "the people"), no machine paths, personal, client or party names.
Return the family's summary.`
}

function judgePrompt(app, fam) {
  return `You judge PGD plan runs. Repo: ${ROOT}. For every ${app} plan of the recipe family "${fam}" that has a run of its
current version (python run_plan.py list ${app}: run=... without "(stale)"): read the recipe (summary, avoid, the plan's
steps and notes, and the run record: python -c "import run_plan as r; import json; x=r.select('<key>')[0];
print(json.dumps(x['plans']['${app}'], indent=1))"), open gallery/recipes/${app}/<key>.png and <key>_steps.png with the Read
tool, and judge the final frame against the summary:
  pass   the frame clearly shows the recipe's look, built the way the steps say;
  weak   the look is there but too faint, partial or off to use as is;
  wrong  something else happened (a step acted on the wrong layer / object, effects replaced each other, the order is off);
  broken nothing useful: steps failed, the frame is unchanged or garbage.
A "partial" run (manual steps skipped) is judged on what the automated steps produced; say what the manual steps would add.
Record each: python run_plan.py judge <key> ${app} --verdict <v> --note "<what you saw, one or two sentences>" --by "judge"
Notes are published: never describe or identify the people in the test photo (only "the subject(s)"). Do not edit plans.
Return the counts and the non-pass keys.`
}

function secondPrompt(app, fam, keys) {
  return `Independent second opinion on PGD plan verdicts (repo ${ROOT}, app ${app}, family "${fam}"). The first judge gave
these plans a non-pass verdict: ${keys.join(', ')}. For each: read the recipe summary, the plan and its run record and
verified note, open gallery/recipes/${app}/<key>.png and <key>_steps.png, and decide whether the verdict is right. Record:
  python run_plan.py judge <key> ${app} --second "agree"
  python run_plan.py judge <key> ${app} --second "corrected: <why>" --verdict <v> --note "<what you saw>"
Never describe or identify the people in the test photo. Do not edit plans. Return the counts.`
}

const RUN = {type: 'object', properties: {family: {type: 'string'}, complete: {type: 'integer'}, partial: {type: 'integer'},
  failed: {type: 'integer'}, blocked: {type: 'array', items: {type: 'string'}}}, required: ['family', 'complete', 'partial', 'failed', 'blocked']}
const JUDGED = {type: 'object', properties: {family: {type: 'string'}, pass: {type: 'integer'}, weak: {type: 'integer'},
  wrong: {type: 'integer'}, broken: {type: 'integer'}, non_pass: {type: 'array', items: {type: 'string'}}},
  required: ['family', 'pass', 'weak', 'wrong', 'broken', 'non_pass']}
const SECOND = {type: 'object', properties: {agreed: {type: 'integer'}, corrected: {type: 'integer'}}, required: ['agreed', 'corrected']}

const judge = (app, fam) => agent(judgePrompt(app, fam), {label: `judge:${app}:${fam}`, phase: 'Judge', schema: JUDGED, model: JUDGE_MODEL})
  .then(j => (j && j.non_pass && j.non_pass.length)
    ? agent(secondPrompt(app, fam, j.non_pass), {label: `second:${app}:${fam}`, phase: 'Second opinion', schema: SECOND, model: JUDGE_MODEL})
      .then(s => ({fam, j, s}))
    : {fam, j, s: null})

// one chain per app: its families run one after another (one owner of the app), and each family's judging starts as
// soon as its runs are recorded, while the owner moves on to the next family
const perApp = await parallel(args.apps.map(app => async () => {
  const runs = [], judging = []
  for (const fam of FAMILIES) {
    const r = await agent(authorPrompt(app, fam), {label: `run:${app}:${fam}`, phase: 'Run plans', schema: RUN, model: AUTHOR_MODEL})
    runs.push(r || {family: fam, failed: -1, blocked: ['agent died']})
    if (args.judge !== false) judging.push(judge(app, fam))
  }
  return {app, runs, judged: (await Promise.all(judging)).filter(Boolean)}
}))
const out = perApp.filter(Boolean)
for (const a of out) {
  const sum = k => a.judged.reduce((n, x) => n + ((x.j && x.j[k]) || 0), 0)
  log(`${a.app}: pass ${sum('pass')}, weak ${sum('weak')}, wrong ${sum('wrong')}, broken ${sum('broken')}`)
}
return out
