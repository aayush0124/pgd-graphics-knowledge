# PGD: a verified knowledge base of Photoshop, Illustrator and CorelDRAW

PGD ("professional graphics designer") is what an automated design system knows about **Photoshop 2026 (27.4)**,
**Illustrator 2026 (30.2)** and **CorelDRAW 2024 (25.1)**: every filter, effect, adjustment, layer style, blend mode,
tool, menu command, shipped preset and scripting class. Nothing in it is typed from memory:

1. **harvest**: names, ids, menu paths, parameters (type, default, range when the app states one) and the scripting
   call for each item are read from the installed apps and their install folders (`harvest/<app>/<kind>.json`);
2. **cards**: an agent writes one knowledge card per harvested item (what it does, what it looks like, when to use and
   avoid it, the exact scripting call, the equivalent in the other two apps), a validator checks every card against
   the harvest, an adversarial reviewer corrects it;
3. **render test**: every visual card's `demo_settings` is rendered on a fixed test plate and the card is judged
   against its frame (`verified.verdict`); preset cards are written from rendered thumbnails.

A design system uses it to pick an effect by look (`find "neon glow"`), to get the call that applies it, to translate
a look between apps (`equiv`), and to pre-flight a plan of steps before anything is sent to an app (`check`).

Not affiliated with, endorsed or sponsored by Adobe or Corel. Photoshop, Illustrator and CorelDRAW are trademarks of
their owners. The repository holds facts read from the apps (names, ids, parameter ranges) and our own writing; it
ships no vendor preset files, thumbnails, installers or long documentation excerpts (see "Public scrub" below).

## Quick start

Python 3.12+ and the standard library are all the query tools and tests need (the tests that render, for the
galleries, the plan runner and the contact sheets, skip without Pillow and numpy; CI installs both).

```
python pgd.py find "gaussian blur"              # search cards by name, look, summary, use
python pgd.py find "neon glow" PS               # ... in one app; add a kind to narrow further (ps_filter)
python pgd.py card "Gaussian Blur" PS           # one card in full, by name, id or menu path
python pgd.py equiv "Gaussian Blur" [PS]        # the same effect in the other two apps (from that app's card)
python pgd.py items CDR "contour"               # search the raw harvest (names, ids, paths)
python pgd.py check tests/fixtures/plan_bad.json   # pre-flight a plan: exit 1 and one line per problem (2: unreadable)
python pgd.py stats                             # counts per kind and verdict
python pipeline.py status                       # what is done, per stage and per app / kind
python -m unittest discover -s tests -v         # offline test suite
```

In code: `sys.path.insert(0, "<path to PGD>"); import pgd; pgd.find("halftone", app="PS"); pgd.check_plan(plan)`.

A plan is `{"app": "PS", "steps": [{"kind": "ps_filter", "name": "Gaussian Blur", "settings": {"Radius": 12}}]}`
(a step may carry its own `"app"`; `name` or a harvest `id`; settings by parameter name or key). `check` holds a plan to a
closed schema (a key it does not know at plan, step, effect or input level, a missing `steps` list, a value of the wrong
shape: each is an issue, never a crash) and flags unknown or ambiguous items, a name that contradicts the id, unknown
parameters, wrong types (a string parameter takes a string, NaN / Infinity are not numbers, object members are checked
against their declared types), values outside the harvested range or enum, CorelDRAW object-model calls missing a
parameter the harvest marks required, card or harvest files it could not read, and items whose card says they are
hidden / unusable or whose render test failed. `check` also flags a second whole-style step on the same layer / object
(a Photoshop layer-style step writes the whole layerEffects set, an Illustrator graphic style replaces the
appearance), since a step-by-step run would keep only the last: put several layer effects in ONE step,
`{"kind": "ps_layer_style", "effects": [{"name": "Stroke", ...}, {"name": "Drop Shadow", ...}]}`, or move the step to
another layer (Duplicate Layer, a new layer, or a step `"target"` naming the layer it acts on). Find ranks a card by
the query's whole words (name first), effects, tools and menus above presets and presets above API classes (ask for
those with a kind such as `ps_api`); a render-test pass adds only a small bonus.

## Running plans in the apps

`check` proves a plan is well formed; `run_plan.py` proves what it does. It runs a recipe's plan step by step in the
live app (Photoshop, Illustrator or CorelDRAW, started by the runner itself, never one another client started), on a
known input document, and records what every step did:

```
python run_plan.py list PS                         # every Photoshop plan: steps with a route / manual, last run, verdict
python run_plan.py show text_effects.neon_glow PS  # the compiled steps: what each one will send (offline)
python run_plan.py run text_effects.neon_glow PS   # run it; resumable: "run all PS" skips plans already run as they are
python run_plan.py get <key> PS plan.json          # edit the plan (written as UTF-8), then save it back
python run_plan.py put <key> PS plan.json          # (check with the plan's default input + compile must accept it)
python run_plan.py judge <key> PS --verdict pass --note "..." --by "judge"
```

A runnable plan adds three things to the format `check` knows: `"input"` (the document it starts from:
`{"plate": "photo" | "text" | "vector" | "blank", "text": "...", "background": "#hex", ...}`, and on the photo plate
`"damage": {"noise": 12, "dust": 80, "jpeg": 12, "tilt": 2, ...}` for clean-up recipes; each plate names its
layers / objects as labels such as `photo`, `type`, `background`, `blue_star`), `"as"` on a step (label what it leaves
active) with `"target"` on a later one (act on that label), and `"script"` (the app's own code for a step whose item
has no route of its own: API classes, tools, menu commands that need values or open a dialog). Steps with no route
run as "manual": skipped and reported. Each run writes `gallery/recipes/<APP>/<key>.png` (the result) and
`<key>_steps.png` (the input and the document after every step), and a `run` record in the recipe card
(`result`: complete / partial / failed / manual, per-step status and notes, the final layer list; a Photoshop or
Illustrator step that ran without a setting it could not send is marked `unsent` and makes the run partial); a judge adds
`verified` from the frames. A record names the plan version it ran (`plan_hash`, over everything that runs; notes are
left out), so a plan whose steps changed shows as stale while a corrected note does not. A new run moves the verdict
on the run before it to `verified_history`: a verdict never outlives the frames it judged, so a re-run (a fresh clone
re-runs every plan whose frame is missing) needs a judge again. `run` exits 1 when a plan failed or crashed; get, put
and judge take exactly one recipe.
Backends: `tools/ps/plan_ps.py`, `tools/ai/plan_ai.py`, `tools/cdr/plan_cdr.py`; each reuses its app's effect gallery,
so a plan step sends exactly what a render-verified card frame sent.

## Data model

| path | what | tracked |
|---|---|---|
| `harvest/<app>/<kind>.json` | ground truth read from the apps; format in [CONTRACT.md](CONTRACT.md); `check_harvest.py` audits it | yes |
| `cards/<kind>_<nn>.json` | `{"cards": [...]}`, one card per item of batch `<kind>_<nn>`; `cards/recipe_*.json` combined looks; `cards/zz_critic.json` known gaps | yes |
| `work/batches/` | the harvest cut into agent-sized batches by `prepare_batches.py` (the tests rebuild them in memory) | no |
| `work/sheets/`, `work/<app>/`, `work/agents/` | contact sheets, harvest checkpoints, agent scratch | no |
| `gallery/<kind>/` | rendered frames and preset thumbnails (some are the vendors' own shipped previews) | no |
| `gallery/recipes/<APP>/` | plan runs: the final frame and the step strip of every recipe plan | no |
| `media/plate_vector.svg`, `media/make_plates.py` | the vector test plate and the plate builder | yes |
| `media/test_photo.png` | the photo plate's source: not shipped; use any 1920x1080 photo of your own | no |
| `PGD.md` | the readable guide, built by `build_docs.py` | no (generated) |
| `tools/ps/notifier.jsx` | Photoshop event notifier, built by `tools/ps/make_notifier.py` (holds an absolute log path) | no (generated) |

App codes and kinds (fixed vocabulary, one kind per item):

| app | kinds |
|---|---|
| `PS` | `ps_filter`, `ps_adjustment`, `ps_layer_style`, `ps_blend_mode`, `ps_tool`, `ps_menu`, `ps_preset`, `ps_api` |
| `AI` | `ai_effect`, `ai_blend_mode`, `ai_tool`, `ai_menu`, `ai_preset`, `ai_api` |
| `CDR` | `cdr_effect`, `cdr_tool`, `cdr_menu`, `cdr_preset`, `cdr_api` |

Every card has `name`, `id` (both exactly as harvested), `app`, `kind`, `path`, `status`
(`current|obsolete|hidden|needs_input|unusable`), `summary`, `use_for`, `avoid`, `confidence` (`high|medium|low`) and
`equivalents` (`{"<other app>": "<its harvested name, id or path>"}`), plus fields per tier: visual cards `look`,
`params`, `demo_settings`, `scripting`, `scriptable`; tools `how`, `shortcut`, `script_api`; menus `script_api`;
presets `applies_to`, `how_to_apply`; API classes `how`, `key_members`, `gotchas`, `example`. The render verdict is
`verified: {"verdict": "pass|weak|wrong|broken|not_rendered", "frame", "note", "rerender", "second_opinion"}`.

## Pipeline

`pipeline.py` is the one entry point: `status [--json|--markdown]`, `run <stage>`, `all` (every deterministic stage
in order) and `doctor` (Python, apps, paths, free RAM). Exit codes: 0 ok, 1 failure, 10 needs attention.

| stage | type | runs |
|---|---|---|
| harvest | live | `workflows/pgd_harvest.js` (+ `pgd_harvest_fix.js`), driving `tools/{ps,ai,cdr,api}/*` |
| check_harvest | deterministic | `check_harvest.py` |
| batches | deterministic | `prepare_batches.py` -> `work/batches/` |
| skeleton | deterministic | `skeleton_cards.py` -> `cards/*_x*.json` (API enum / type-library cards, no agent) |
| cards | agent | `workflows/pgd_cards.js` |
| validate | deterministic | `validate_cards.py` (no arguments: every card file against its batch) |
| galleries | live | `workflows/pgd_preset_gallery.js`, `pgd_effect_gallery.js` (one app per run), or `pgd_app_chain.js` |
| sheets | deterministic | `make_sheets.py --kind <app>_preset` (needs Pillow) |
| preset_cards | agent | `workflows/pgd_preset_cards.js` |
| verify | agent | `workflows/pgd_verify.js` |
| recipes | agent | `workflows/pgd_recipes.js` (recipes + completeness critic) |
| plans | live | `run_plan.py run all <APP>` (one owner per app), judged with `run_plan.py judge`; or `workflows/pgd_plans.js` |
| docs | deterministic | `build_docs.py` -> `PGD.md`, and the coverage block below |

Live and agent stages never run from `pipeline.py` or CI: `pipeline.py run <stage>` prints the script to launch.

### Workflow launch args

The `workflows/*.js` files are Claude Code Workflow scripts. They hold the agent prompts
and take every path from their `args`; each throws at once when `args.root` is missing. Paths use forward slashes.

| script | required args | optional args |
|---|---|---|
| `pgd_harvest.js` | `root` | `hostlock`, `pve` (sibling PVE folder for the agents to read), `cdr_traps_doc` |
| `pgd_harvest_fix.js` | `root` | `hostlock` |
| `pgd_cards.js` | `root`, `batches` | |
| `pgd_preset_gallery.js` | `root`, `app` (`PS`/`AI`/`CDR`) | `hostlock`, `note` |
| `pgd_effect_gallery.js` | `root`, `app` | `hostlock`, `note`, `ids` or `ids_file` (re-render run) |
| `pgd_preset_cards.js` | `root`, `batches` | `width` |
| `pgd_verify.js` | `root`, `batches` | `width`, `recheck` + `ids` |
| `pgd_recipes.js` | `root` | `only_critic`, `skip_critic` |
| `pgd_app_chain.js` | `root`, `scripts` (folder of these scripts), `app`, `batches` | `hostlock`, `preset_note`, `preset_batches`, `preset_width`, `effect_note`, `gallery_ids`, `width` |
| `pgd_plans.js` | `root`, `apps` (only apps no other client is using) | `families`, `judge`, `author_model`, `judge_model` |

`hostlock` defaults to `<root>/tools/hostlock.py`. Example: `{"root": "C:/src/PGD", "app": "CDR"}` for
`pgd_effect_gallery.js`; `{"root": "C:/src/PGD", "scripts": "C:/src/PGD/workflows", "app": "PS", "batches":
["ps_filter_01"]}` for `pgd_app_chain.js`.

### Rules for anything that drives an app

These are the hard-won rules from [CONTRACT.md](CONTRACT.md), and every live script follows them:

- **One owner per app.** Exactly one agent or process drives Photoshop, one Illustrator, one CorelDRAW. Never send a
  script to an app you do not own, and never touch After Effects or Premiere Pro.
- Documents you did not open belong to someone else: leave them alone; work in a document you create and close.
- **Global keyboard / mouse input** only inside `host_lock("ui")` from `tools/hostlock.py`, held just around the
  input. It is a Win32 named mutex (`Global\aisys_host_<slot>`) shared with every other pipeline on the machine, so a
  stray keystroke never lands in another job's window. Prefer input aimed at a window handle, which needs no lock.
- Timeouts on every app call: a call that hangs means a modal dialog. Record the item with an `error` and move on.
- Stop processes only by the PID you launched and recorded, never by name or command-line pattern.
- Long harvests checkpoint to disk and resume; payloads cross COM percent-encoded; native paths at every host call.

### Environment

| variable | default | used by |
|---|---|---|
| `PGD_HOME` | the folder holding `pgd.py` | every script: where `harvest/`, `cards/`, `work/`, `gallery/` live |
| `PGD_PS_EXE` / `PGD_PS_DIR` | `C:\Program Files\Adobe\Adobe Photoshop 2026[\Photoshop.exe]` | Photoshop tools, `doctor` |
| `PGD_AI_EXE` / `PGD_AI_DIR` | `C:\Program Files\Adobe\Adobe Illustrator 2026[...\Illustrator.exe]` | Illustrator tools, `doctor` |
| `PGD_CDR_DIR` | `C:\Program Files\Corel\CorelDRAW Graphics Suite\25\Programs64` | API harvest, `doctor` |
| `PGD_CDR_USER_CONTENT` / `PGD_CDR_USER_DATA` | the CorelDRAW content / settings folders under your user profile | CorelDRAW preset harvest |
| `PGD_FONT` | Arial | contact-sheet labels |
| `PGD_LIVE=1` | off | opt-in tests against the installed apps (they never start an app) |
| `PGD_SCRUB_STRICT=1` | off locally, on in CI | card hits fail the public-scrub test |

The live tools (`tools/`) are Windows-only (COM, ExtendScript, UI Automation) and need `pywin32`, `uiautomation`,
`psutil` and Pillow; `pipeline.py doctor` reports what is missing.

## Coverage

Generated by `python pipeline.py run docs` from `pipeline.py status --markdown`; never edited by hand.

<!-- coverage:start -->
| stage | type | state | counts |
|---|---|---|---|
| harvest | live | done | 19/19 kinds, 10779 items |
| check_harvest | deterministic | done | 0 errors |
| batches | deterministic | done | 386/386 batches in work/batches |
| skeleton | deterministic | done | 0 API lookup batches without cards |
| cards | agent | done | 202/202 non-preset batches carded, 3945 cards |
| validate | deterministic | done | 386/386 batch-validated card files clean (9 recipe / critic files are checked by the test suite) |
| galleries | live | done | 10/10 galleries complete, 6315 frames |
| sheets | deterministic | done | 184/184 preset batches |
| preset_cards | agent | done | 184/184 preset batches carded, 6834 cards |
| verify | agent | done | 531/531 visual and 6834/6834 preset items have a verdict |
| recipes | agent | done | 8 recipe files, critic yes |
| plans | live | partial | 149/207 plans run on their current version {'complete': 136, 'partial': 13}, 149 judged {'pass': 136, 'weak': 13} |
| docs | deterministic | done | PGD.md fresh |

| app | kind | items | batches | card files | cards | pass | weak | wrong | broken | not_rendered | frames | sheets |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PS | ps_adjustment | 42 | 5 | 5 | 42 | 33 | 1 | 2 | 0 | 6 | 36 |  |
| PS | ps_blend_mode | 41 | 5 | 5 | 41 | 0 | 0 | 27 | 0 | 14 | 27 |  |
| PS | ps_filter | 125 | 16 | 16 | 125 | 100 | 1 | 2 | 0 | 22 | 104 |  |
| PS | ps_layer_style | 10 | 1 | 1 | 10 | 9 | 0 | 0 | 0 | 1 | 9 |  |
| PS | ps_tool | 82 | 6 | 6 | 82 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| PS | ps_menu | 588 | 21 | 21 | 588 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| PS | ps_preset | 3175 | 84 | 84 | 3175 | 2414 | 10 | 262 | 0 | 489 | 2686 | 84 |
| PS | ps_api | 241 | 7 | 7 | 241 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| AI | ai_blend_mode | 16 | 2 | 2 | 16 | 10 | 0 | 6 | 0 | 0 | 16 |  |
| AI | ai_effect | 137 | 18 | 18 | 137 | 125 | 0 | 4 | 1 | 7 | 132 |  |
| AI | ai_tool | 136 | 14 | 14 | 136 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| AI | ai_menu | 697 | 25 | 25 | 697 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| AI | ai_preset | 2087 | 55 | 55 | 2087 | 1868 | 5 | 125 | 0 | 89 | 1998 | 55 |
| AI | ai_api | 306 | 9 | 9 | 306 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| CDR | cdr_effect | 160 | 20 | 20 | 160 | 125 | 4 | 4 | 11 | 16 | 133 |  |
| CDR | cdr_tool | 77 | 10 | 10 | 77 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| CDR | cdr_menu | 380 | 15 | 15 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| CDR | cdr_preset | 1572 | 45 | 45 | 1572 | 1120 | 7 | 41 | 0 | 404 | 1174 | 45 |
| CDR | cdr_api | 907 | 28 | 28 | 907 | 0 | 0 | 0 | 0 | 0 | 0 |  |

Preset batches still without cards: none.
<!-- coverage:end -->

## Known gaps

- Read the coverage block above for what is still open: stages marked `partial` / `todo`, the preset batches
  without cards, and the `not_rendered` column (the open rendering work, mostly presets). Tools, menus and API cards
  are not render-tested by design.
- Harvested items that could not be probed are listed with an `error` field saying why (an item is never dropped).
- Vendor API descriptions in `harvest/*/*_api.json` are cut to their first 25 words (`[...]` marks the cut); the full
  text is in the vendors' own scripting references.
- The photo test plate is not shipped (it was a third-party news frame): `media/make_plates.py` builds
  `plate_photo.png` from any `media/test_photo.png` you supply, so a re-render will not match the stored verdicts
  pixel for pixel.
- Versions are pinned: Photoshop 2026 27.4, Illustrator 2026 30.2, CorelDRAW 2024 25.1. Another version needs a new
  harvest.

## Tests

`python -m unittest discover -s tests -v` runs offline (no app, no network, no LLM; with Pillow and numpy installed
the gallery, plan-runner and sheet tests run too, and `PGD_REQUIRE_DEPS=1`, as in CI, makes their absence a failure):
every `pgd.py` subcommand,
`check_harvest.py`, the validator (every card file against its batch, built in memory from the harvest), golden
queries, negative tests for `check`, reproducible docs, the workflow scripts (parsed and dry-run by node through
`tests/workflow_harness.js`, skipped without node) and `tests/test_public_scrub.py`.

### Public scrub

`tests/test_public_scrub.py` walks everything git would track and fails on machine paths, client or personal names,
personal data, credentials, vendor preset / project / binary files, media outside `docs/samples/`, files over 5 MB and
vendor API descriptions over 25 words. Card files are reported separately: locally the card check skips with a
count; with `PGD_SCRUB_STRICT=1` (as in CI) any card hit fails. `python tests/test_public_scrub.py --cards-report
hits.json` lists each hit with the card id, the field and a proposed replacement.

## License

Code: MIT ([LICENSE](LICENSE)). Cards (`cards/`) and docs (`README.md`, `CONTRACT.md`, `PGD.md`): CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/), credit "PGD by Aayush Paliwal".
