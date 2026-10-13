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

Python 3.12+ and the standard library are all the query tools and tests need.

```
python pgd.py find "gaussian blur"              # search cards by name, look, summary, use
python pgd.py find "neon glow" PS               # ... in one app; add a kind to narrow further (ps_filter)
python pgd.py card "Gaussian Blur" PS           # one card in full, by name, id or menu path
python pgd.py equiv "Gaussian Blur"             # the same effect in the other two apps
python pgd.py items CDR "contour"               # search the raw harvest (names, ids, paths)
python pgd.py check tests/fixtures/plan_bad.json   # pre-flight a plan: exit 1 and one line per problem
python pgd.py stats                             # counts per kind and verdict
python pipeline.py status                       # what is done, per stage and per app / kind
python -m unittest discover -s tests -v         # offline test suite
```

In code: `sys.path.insert(0, "<path to PGD>"); import pgd; pgd.find("halftone", app="PS"); pgd.check_plan(plan)`.

A plan is `{"app": "PS", "steps": [{"kind": "ps_filter", "name": "Gaussian Blur", "settings": {"Radius": 12}}]}`
(a step may carry its own `"app"`; `name` or a harvest `id`; settings by parameter name or key). `check` flags unknown
or ambiguous items, unknown parameters, wrong types, values outside the harvested range or enum, and items whose card
says they are hidden / unusable or whose render test failed. It also flags a second whole-style step on the same layer /
object (a Photoshop layer-style step writes the whole layerEffects set, an Illustrator graphic style replaces the
appearance), since a step-by-step run would keep only the last: put several layer effects in ONE step,
`{"kind": "ps_layer_style", "effects": [{"name": "Stroke", ...}, {"name": "Drop Shadow", ...}]}`, or move the step to
another layer (Duplicate Layer, a new layer, or a step `"target"` naming the layer it acts on).

## Data model

| path | what | tracked |
|---|---|---|
| `harvest/<app>/<kind>.json` | ground truth read from the apps; format in [CONTRACT.md](CONTRACT.md); `check_harvest.py` audits it | yes |
| `cards/<kind>_<nn>.json` | `{"cards": [...]}`, one card per item of batch `<kind>_<nn>`; `cards/recipe_*.json` combined looks; `cards/zz_critic.json` known gaps | yes |
| `work/batches/` | the harvest cut into agent-sized batches by `prepare_batches.py` (the tests rebuild them in memory) | no |
| `work/sheets/`, `work/<app>/`, `work/agents/` | contact sheets, harvest checkpoints, agent scratch | no |
| `gallery/<kind>/` | rendered frames and preset thumbnails (some are the vendors' own shipped previews) | no |
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
| validate | deterministic | done | 299/299 card files clean |
| galleries | live | partial | 5/10 galleries complete, 6056 frames |
| sheets | deterministic | partial | 103/184 preset batches |
| preset_cards | agent | partial | 97/184 preset batches carded, 3570 cards |
| verify | agent | partial | 73/531 visual and 3044/6834 preset items have a verdict |
| recipes | agent | todo | 0 recipe files, critic no |
| docs | deterministic | todo | PGD.md missing |

| app | kind | items | batches | card files | cards | pass | weak | wrong | broken | not_rendered | frames | sheets |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PS | ps_adjustment | 42 | 5 | 5 | 42 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| PS | ps_blend_mode | 41 | 5 | 5 | 41 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| PS | ps_filter | 125 | 16 | 16 | 125 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| PS | ps_layer_style | 10 | 1 | 1 | 10 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| PS | ps_tool | 82 | 6 | 6 | 82 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| PS | ps_menu | 588 | 21 | 21 | 588 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| PS | ps_preset | 3175 | 84 | 3 | 107 | 0 | 0 | 0 | 0 | 40 | 2686 | 3 |
| PS | ps_api | 241 | 7 | 7 | 241 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| AI | ai_blend_mode | 16 | 2 | 2 | 16 | 0 | 0 | 0 | 0 | 0 | 16 |  |
| AI | ai_effect | 137 | 18 | 18 | 137 | 10 | 0 | 1 | 1 | 53 | 85 |  |
| AI | ai_tool | 136 | 14 | 14 | 136 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| AI | ai_menu | 697 | 25 | 25 | 697 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| AI | ai_preset | 2087 | 55 | 55 | 2087 | 1686 | 13 | 121 | 0 | 72 | 1998 | 55 |
| AI | ai_api | 306 | 9 | 9 | 306 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| CDR | cdr_effect | 160 | 20 | 20 | 160 | 3 | 0 | 0 | 3 | 2 | 131 |  |
| CDR | cdr_tool | 77 | 10 | 10 | 77 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| CDR | cdr_menu | 380 | 15 | 15 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| CDR | cdr_preset | 1572 | 45 | 39 | 1376 | 837 | 4 | 30 | 0 | 241 | 1140 | 45 |
| CDR | cdr_api | 907 | 28 | 28 | 907 | 0 | 0 | 0 | 0 | 0 | 0 |  |

Preset batches still without cards: cdr_preset_40..45, ps_preset_04..84.
<!-- coverage:end -->

## Known gaps

- Read the coverage block above for what is still open: stages marked `partial` / `todo`, and the preset batches
  without cards. The Photoshop effect gallery (filters, adjustments, layer styles, blend modes) is the largest
  unrendered set, so those cards carry no render verdict yet.
- Harvested items that could not be probed are listed with an `error` field saying why (an item is never dropped).
- Vendor API descriptions in `harvest/*/*_api.json` are cut to their first 25 words (`[...]` marks the cut); the full
  text is in the vendors' own scripting references.
- The photo test plate is not shipped (it was a third-party news frame): `media/make_plates.py` builds
  `plate_photo.png` from any `media/test_photo.png` you supply, so a re-render will not match the stored verdicts
  pixel for pixel.
- Versions are pinned: Photoshop 2026 27.4, Illustrator 2026 30.2, CorelDRAW 2024 25.1. Another version needs a new
  harvest.

## Tests

`python -m unittest discover -s tests -v` runs offline (no app, no network, no LLM): every `pgd.py` subcommand,
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
