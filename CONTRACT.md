# PGD contract (professional graphics designer)

PGD is what the design systems know about **Photoshop 2026 (27.4)**, **Illustrator 2026 (30.2)** and
**CorelDRAW 2024 (25.1)**: every effect, filter, adjustment, style, tool, menu command, preset and scripting surface,
harvested from the installed apps, written up as knowledge cards, validated against the harvest, and render-verified.
Sibling of PVE (the same knowledge base for After Effects + Premiere). Same pipeline:

1. **harvest** (`harvest/<app>/<kind>.json`): ground truth read from the live apps and their install folders.
2. **batches** (`prepare_batches.py` -> `work/batches/<kind>_<nn>.json`): harvest split into agent-sized batches.
3. **cards** (`cards/<kind>_<nn>.json`): one card per harvested item, checked by `validate_cards.py`.
4. **gallery** (`gallery/<app>_<kind>/`): every visual card's `demo_settings` rendered on the test plate.
5. **verify**: each card judged against its frame; verdict stored in the card.
6. **recipes + critic**, then `pgd.py` (find / card / check) and `PGD.md`.

## App codes and kinds (fixed vocabulary)

| app | kinds |
|---|---|
| `PS` | `ps_filter` (everything under Filter), `ps_adjustment` (Image > Adjustments + adjustment layers), `ps_layer_style` (each layer effect: Drop Shadow, Bevel & Emboss ...), `ps_blend_mode`, `ps_tool`, `ps_menu` (every other menu command), `ps_preset`, `ps_api` |
| `AI` | `ai_effect` (everything under Effect, incl. Photoshop Effects), `ai_blend_mode`, `ai_tool`, `ai_menu`, `ai_preset`, `ai_api` |
| `CDR` | `cdr_effect` (Effects menu: bitmap effects, lenses, interactive vector effects such as Contour / Blend / Extrude / Envelope / Drop Shadow / Block Shadow / Distort / Perspective / Transparency), `cdr_tool`, `cdr_menu`, `cdr_preset`, `cdr_api` |

Each menu item lives in exactly ONE kind: Filter items go to `ps_filter`, not `ps_menu`; Effect items to `ai_effect`;
CorelDRAW Effects items to `cdr_effect`. Leave out separators, empty names, recent-file lists, open-document and
workspace entries (dynamic content, not commands).

## Harvest file format

`harvest/<app>/<kind>.json` (app folder lower case: `ps`, `ai`, `cdr`):

```json
{"app": "PS", "kind": "ps_filter", "app_version": "27.4.0", "source": "how this file was produced (one line)",
 "items": [ <item>, ... ]}
```

Item (only `name` and `id` are required; leave a field out rather than guess):

```json
{"name": "Gaussian Blur",                 // display name exactly as the app shows it
 "id": "gaussianBlur",                    // stable, unique within the kind: event stringID, menu command string,
                                          //   GUID, preset file + entry, API member ... never a list position
 "path": "Filter/Blur/Gaussian Blur",     // menu path or preset folder/library
 "category": "Blur",
 "params": [{"name": "Radius", "key": "radius", "type": "number", "default": 1.0, "min": 0.1, "max": 1000,
             "unit": "px", "enum": [{"value": "...", "label": "..."}]}],
 "invoke": {"ps_event": "gaussianBlur"},  // how a script applies / runs it (see below)
 "shortcut": "Ctrl+F",
 "requires": "pixel layer | selection | text layer | open path | bitmap | group | ...",
 "evidence": "how params were obtained: descriptor read-back, range probe, typelib, file parse, menu walk",
 "error": "why something could not be probed (item still listed)",
 "extra": {}}
```

`params[].type` is one of `number`, `int`, `bool`, `enum`, `color`, `point`, `string`, `path`, `object`, `unknown`.
`min` / `max` only when the app told you (a range probe, a typelib, a file), never from memory. A value read from the
app beats documentation; documentation describes the newest release, not the installed one.

`invoke` keys: `ps_event` (Action Manager event stringID), `ps_menu_cmd` (runMenuItem command id), `ps_dom`
(ExtendScript DOM call), `ai_menu` (executeMenuCommand string), `ai_live_effect` (LiveEffect XML name for
`applyEffect`), `ai_dom`, `cdr_guid` (FrameWork.Automation.InvokeItem guid), `cdr_com` (object-model call, e.g.
`Shape.CreateContour`), `cdr_effect_cmd` (bitmap effect command string), `file` (preset file path).

## Card format

`cards/<kind>_<nn>.json` = `{"cards": [...]}`, one card per item of `work/batches/<kind>_<nn>.json`, matched by `id`.
`python validate_cards.py work/batches/<b>.json cards/<b>.json` must report 0 issues. Every card:

```json
{"name": "<harvested name exactly>", "id": "<harvested id>", "app": "PS|AI|CDR", "kind": "<kind>",
 "path": "<menu path>", "status": "current|obsolete|hidden|needs_input|unusable",
 "summary": "what it does and what the result looks like, one or two sentences",
 "use_for": ["concrete design jobs: poster headline, product cut-out, print-ready logo ..."],
 "avoid": ["when it goes wrong and what to use instead"],
 "confidence": "high|medium|low",
 "equivalents": {"<other app>": "<that app's harvested name, id or path>"}}
```

Extra fields by tier (`tier` is in the batch file):

- **visual** (`ps_filter`, `ps_adjustment`, `ps_layer_style`, `ps_blend_mode`, `ai_effect`, `ai_blend_mode`,
  `cdr_effect`): `look` (keywords), `params` (`[{"name": <harvested param name or key>, "does", "typical"}]`),
  `demo_settings` (`{<param name or key>: value}` inside the harvested type / range / enum, chosen so the effect is
  clearly visible on the test plate; required for a current item with settable params), `enum_labels`, `pairs_with`,
  `scripting` (the exact call that applies it, from the harvest's `invoke`), `non_destructive` (smart filter /
  live effect / effect stack?), `cost`.
- **tool**: `how` (how a designer uses it), `shortcut`, `scriptable` (`yes|partial|no`), `script_api`.
- **menu**: `scriptable`, `script_api` (runMenuItem id / executeMenuCommand string / InvokeItem GUID / DOM call),
  `how` when it opens a dialog worth explaining.
- **preset**: `applies_to` (layer / object type it works on), `look`, `how_to_apply`.
- **api**: `how` (what the class is for, how to reach it), `key_members` (`[{"name", "use"}]`), `gotchas`, `example`.

Verification (written by the verify wave): `"verified": {"verdict": "pass|weak|wrong|broken|not_rendered", "frame",
"note", "rerender", "second_opinion"}`.

## Plan format (recipes and run_plan.py)

A recipe card (`cards/recipe_*.json`, kind `recipe`) holds one plan per app in `plans.<APP>`:

```json
{"app": "PS",
 "input": {"plate": "photo", "text": "HEADLINE", "at": [960, 900], "size": 150, "color": "#FFFFFF"},
 "steps": [
  {"kind": "ps_menu", "id": "1135", "as": "copy", "note": "Duplicate Layer: the copy is the active layer"},
  {"kind": "ps_filter", "id": "gaussianBlur", "settings": {"radius": 30}, "target": "photo", "note": "..."},
  {"kind": "ps_layer_style", "effects": [{"name": "Stroke", "settings": {"size": 4}}, {"name": "Drop Shadow"}],
   "target": "copy", "note": "one layerEffects set: a set replaces the layer's whole style"},
  {"kind": "ps_api", "id": "class:Selection", "script": "d.selection.select([[0,0],[960,0],[960,1080],[0,1080]]);",
   "note": "..."}],
 "run": {"...": "written by run_plan.py run"}, "verified": {"...": "written by run_plan.py judge"}}
```

- `input.plate`: `photo` (media/plate_photo.png; label `photo`), `text` (grey ground + one type layer / text object;
  labels `type`, `background`), `vector` (media/plate_vector.svg; labels `orange_box`, `blue_star`, `grad_circle`,
  `pgd_type`, `zigzag`, and `art` for the whole group in Illustrator; not for Photoshop), `blank` (label
  `background`). `text` on any plate adds a type layer / text object labelled `type` (`at` its centre in px, `size`
  px, `color`, `font`); `background` fills the ground. `damage` on the photo plate (`noise`, `dust`, `scratches`,
  `jpeg`, `blur`, `haze`, `tilt`; run_plan.DAMAGE) gives clean-up recipes a synthetic, reproducible fault to remove.
- A step acts on its `target` (a label), else on what the previous step left active. `as` labels what a step leaves
  active. When a step replaces the layer / shape it acted on (Layer from Background, Convert to Smart Object, Merge,
  Convert to Bitmap / Curves) its labels follow the result.
- `script` replaces the item's route with app-native code: ExtendScript for Photoshop (`d` = document, `L` = layer)
  and Illustrator (`d`, `T` = target item, `g`, `r`); Python for CorelDRAW (`app`, `doc`, `layer`, `s`, `labels`,
  `rgb`, `PW`, `PH`, `PX`; set `result`). Scripts never print, change app preferences or write outside
  `work/plans/out/<key>/`.
- Steps with no route (API / tool / preset steps without a script, menu commands that need values, open a dialog or
  act outside the document) run as `manual`: skipped and reported.
- `pgd.py check` validates all of it (plus: CorelDRAW object-model calls must set every parameter that has no
  default); `run_plan.py put` refuses a plan it rejects. `run` and `verified` carry the `plan_hash` of the version
  they describe (its runnable content: notes are left out, so a corrected note keeps both).

## Rules for anyone driving an app

- **One owner per app.** Exactly one agent / process drives Photoshop, one Illustrator, one CorelDRAW. Never send
  a script to an app you do not own; never touch After Effects or Premiere Pro (other pipelines use them).
- Before the first script, read the app's open documents. A document you did not open belongs to someone else: do not
  close or modify it; work in a new document you create and close.
- **Global keyboard / mouse input** (SendKeys, pyautogui, focus changes) only inside
  `host_lock("ui")` from `tools/hostlock.py` (the host-wide named mutex every pipeline on the machine shares), held
  just around the input. Prefer input targeted at a
  window handle (PostMessage / UI Automation Invoke on the dialog's button), which needs no lock.
- Timeouts on every app call; a call that hangs means a modal dialog. Record the item with an `error` and move on.
- **Stop processes only by the PID you launched and recorded.** Never kill by name or command-line pattern: the three
  apps' renderers share script names (`preset_gallery.py`, `effect_gallery.py`), and pattern kills have twice killed
  another agent's renderer (2026-10-04 and 2026-10-06).
- Long harvests checkpoint to disk every batch and resume from the checkpoint; never restart from zero.
- Payloads cross COM percent-encoded and are decoded first thing (`eval(decodeURIComponent("..."))`); native paths
  (`File(p).fsName`) at every host call; in catch handlers build messages with `String(e)`, never `"..." + e`.
- Check harvest files with `python check_harvest.py` (in the PGD folder) until it reports no errors.
