export const meta = {
  name: 'pgd-harvest-fix',
  description: 'PGD wave 1b: name and id every Illustrator menu command and tool; find a verified script route for every Photoshop menu command; finish smart-filter probing',
  phases: [
    { title: 'Fix', detail: 'one owner per app: Illustrator menus/tools, Photoshop menus/smart filters' },
  ],
}

// Launch args (Workflow `args`): root (required, the PGD folder, forward slashes); optional hostlock (path of
// hostlock.py, default <root>/tools/hostlock.py).   {"root": "C:/src/PGD"}
if (!args || !args.root) throw new Error('pgd_harvest_fix.js needs args.root (the PGD folder), e.g. {"root": "C:/src/PGD"}')
const ROOT = String(args.root).replace(/\\/g, '/').replace(/\/+$/, '')
const HOSTLOCK = args.hostlock || `${ROOT}/tools/hostlock.py`
const COMMON = `You are improving the harvest of PGD ("professional graphics designer"), the verified knowledge an automated design
system has of Photoshop 2026, Illustrator 2026 and CorelDRAW 2024, read from the INSTALLED apps. Read ${ROOT}/CONTRACT.md
first (file format and rules). Every value you add must come from the app or its files; when a match is inferred and not
confirmed by the app, say so in the item ("evidence", "error" or extra.*_verified false). Validate with
  python ${ROOT}/check_harvest.py <file>
until 0 errors. Rules: you own exactly ONE app (below); never send anything to another app; never touch After Effects or
Premiere Pro. Leave documents you did not open alone; create your own test documents and close them unsaved. Every COM call
gets a timeout; dismiss dialogs with input aimed at the dialog's window handle; GLOBAL keyboard / mouse input only inside
host_lock("ui", timeout=600) from ${HOSTLOCK}, held just around the input (another agent drives
another app right now: one stray click in this wave already landed in Photoshop). Reuse the helpers in ${ROOT}/tools/<app>/
(read them first), put new scripts there, scratch in ${ROOT}/work/<app>/. Back up a harvest file before you rewrite it
(${ROOT}/work/<app>/<file>.bak-<step>). Checkpoint and resume. Other agents are writing knowledge cards from the OTHER harvest
files right now: change ONLY the files named in your task. Return the summary object.`

const AI_TASK = `YOUR APP: Illustrator 2026 (30.2.1), COM "Illustrator.Application"; helpers in ${ROOT}/tools/ai/ (aicom.py:
js / js_watch / dismiss / dialogs; menu_walk.py; find_menu_ids.py / confirm_ids.py; ai_menus.py builds ai_menu.json).
YOUR FILES: ${ROOT}/harvest/ai/ai_menu.json and ${ROOT}/harvest/ai/ai_tool.json only.

The problem (from the harvest audit, 2026-10-04): ai_menu.json has 812 items, but 303 are .kys-only (the
executeMenuCommand id from Presets/en_US/Keyboard Shortcuts/Illustrator Defaults.kys, used as the name: not a name the app
shows) and 308 are walked menu items (real display name and menu path, id "path:..." and NO executeMenuCommand id). Both
halves carry an error. Many are the SAME command split in two. 107 shortcut, 45 words+path, 16 id-text and 13 table
matches remain unconfirmed by execution, and the auditor's sample found 2 wrong shortcut matches. ai_tool.json: 84 of
136 tools still use their internal id as the name ('Adobe Select Tool', 'Adobe Scroll Tool', ...); Illustrator.exe has
tooltip strings that likely belong to them ('Selection Tool (V)', 'Hand Tool (H)', 'Group Selection Tool (A)', 'Type on a
Path Tool (T)': _STRList/STR/275) but pairing them is inference until the app confirms it.

Do:
1. Get display names for the internal ids from the app. Edit > Keyboard Shortcuts has "Export Text...", which writes a
   text file of every Tool and Menu Command with its shortcut, in the dialog's order (check what it really writes). The
   .kys has the same commands as ids with Modifiers/Key codes. Align the two (shortcuts as anchors, order between
   anchors, menu path words), and use any other app-sourced route you find (tooltips via UI Automation while a tool is
   selected with app.selectTool, string resources).
2. CONFIRM pairs by execution wherever it is safe: executeMenuCommand(id) on a test document you made, and observe the
   effect (selection / object count / bounds / a dialog whose title names the command) as find_menu_ids.py does. Skip
   commands that quit, close, save, print, export, sign out, open web pages or change preferences.
3. Merge every matched pair into ONE item: id = the executeMenuCommand string, name and path from the walked menu,
   shortcut, "invoke": {"ai_menu": id}, extra.match = how it was matched, extra.confirmed = true/false. Remove the
   duplicate half. Unmatched items stay, each with an "error" saying what is missing.
4. ai_tool.json: give every tool its display name and shortcut from the app (confirmed by selecting it and reading the
   UI, or by the exported shortcut list); keep the id that app.selectTool() accepts.
Time box about 120 minutes; write improved files as you go. Return the summary with counts in notes: merged pairs,
confirmed by execution, unmatched ids, unmatched walked items, tools named.`

const PS_TASK = `YOUR APP: Photoshop 2026 (27.4.0), COM "Photoshop.Application"; helpers in ${ROOT}/tools/ps/ (psdrv.py: js / jsj with
timeout, dismiss_dialogs, restart_ps; pslib.jsx; probe.py; ps_terminology.py and the parsed built-in Action Manager
dictionary at ${ROOT}/work/ps/ps_terminology.json: 444 events with English labels).
YOUR FILES: ${ROOT}/harvest/ps/ps_menu.json (all of it) and ${ROOT}/harvest/ps/ps_filter.json (ONLY by adding
extra.smart_filter; do not change any name, id, path or param there: cards are being written from it).

1. ps_menu.json has 588 menu commands and only 36 carry an "invoke". The harvest found that app.runMenuItem() does NOT
   accept the menuBarInfo command numbers (runMenuItem(-510), runMenuItem(1701) both raised 'menu item is not currently
   available'), so a menu command has no known script route yet. For each command find one that works: the Action
   Manager event it fires (executeAction(stringIDToTypeID(id), desc, DialogModes.NO)), app.runMenuItem(stringIDToTypeID(id))
   or charIDToTypeID (test whether runMenuItem accepts those, on a document where the command is enabled), or a DOM call
   (omv.xml: doc.flatten(), doc.resizeImage(), ...). Candidates come from the terminology labels, Terminology.jsx and the
   DOM; then CONFIRM each on a test document you create, set up so the command is enabled (layers, a selection, a text
   layer as needed), by observing the change (layer count, document size, mode, selection bounds, a dialog whose title
   names the command). Skip commands that quit, close, save, print, export, share, sign in / out, open web pages or the
   preferences, and anything generative that spends credits. Record "invoke": {"ps_event": id} or {"ps_dom": "..."} and
   extra.invoke_verified true / false with extra.invoke_how. Keep every item's name / id / path.
2. ps_filter.json: smart-filter capability was probed for only 24 filters (python probe.py smart was stopped). Finish it
   for every filter that runs headless and store extra.smart_filter = true / false (+ extra.smart_filter_note if it
   fails). Known hazards: Lens Blur with a huge Iris Radius hangs Photoshop for 20+ minutes; Displace with no map file and
   Shear under clamp probing wedge it (only taskkill recovers); Smart Blur opens its dialog even under DialogModes.NO
   (only BM_CLICK on its win32 'Cancel' child closes it). Keep the Invert canary after every probe.
Time box about 150 minutes. Return the summary with counts in notes: commands with a verified invoke, unverified, none
found; filters with smart_filter recorded.`

const SUMMARY = {type: 'object', properties: {
  app: {type: 'string'}, stage: {type: 'string'},
  files: {type: 'array', items: {type: 'object', properties: {file: {type: 'string'}, items: {type: 'integer'},
    errors: {type: 'integer'}}, required: ['file', 'items', 'errors']}},
  helpers: {type: 'array', items: {type: 'string'}},
  traps: {type: 'array', items: {type: 'string'}},
  gaps: {type: 'array', items: {type: 'string'}},
  notes: {type: 'string'}},
  required: ['app', 'stage', 'files', 'helpers', 'traps', 'gaps', 'notes']}

phase('Fix')
const res = await parallel([
  () => agent(`${COMMON}\n\n${AI_TASK}`, {label: 'fix:AI menus+tools', phase: 'Fix', schema: SUMMARY}),
  () => agent(`${COMMON}\n\n${PS_TASK}`, {label: 'fix:PS menus+smart', phase: 'Fix', schema: SUMMARY}),
])
return {ai: res[0], ps: res[1]}
