export const meta = {
  name: 'pgd-app-chain',
  description: 'PGD, one app end to end: finish its galleries, verify every visual card against its render, re-render changed demos and recheck them; write its preset cards once its preset gallery is done',
  phases: [
    { title: 'Galleries', detail: 'preset gallery (if unfinished), then effect gallery: one owner of the app' },
    { title: 'Verify', detail: 'visual cards judged against frames, second opinion on non-pass' },
    { title: 'Rerender', detail: 'frames for cards whose demo_settings the verifiers changed' },
    { title: 'Recheck', detail: 'the re-rendered cards judged again' },
  ],
}

// Launch args (Workflow `args`), required: root (the PGD folder, forward slashes), scripts (the folder holding the PGD
// workflow scripts, normally <root>/workflows), app (PS | AI | CDR), batches (visual card batches to verify).
// Optional: hostlock (path of hostlock.py, default <root>/tools/hostlock.py), preset_note, preset_batches,
// preset_width, effect_note, gallery_ids, width. root and hostlock are passed on to every child workflow.
//   {"root": "C:/src/PGD", "scripts": "C:/src/PGD/workflows", "app": "CDR", "batches": ["cdr_effect_01"]}
if (!args || !args.root || !args.scripts) {
  throw new Error('pgd_app_chain.js needs args.root (the PGD folder) and args.scripts (the folder with the PGD workflow scripts), e.g. {"root": "C:/src/PGD", "scripts": "C:/src/PGD/workflows", "app": "PS", "batches": [...]}')
}
const S = String(args.scripts).replace(/\\/g, '/').replace(/\/+$/, '')
const PASS = {root: args.root, hostlock: args.hostlock}
const A = args.app
const out = {app: A}

let presetCards = null
if (args.preset_note) {
  phase('Galleries')
  out.preset_gallery = await workflow({scriptPath: `${S}/pgd_preset_gallery.js`}, {...PASS, app: A, note: args.preset_note})
  log(`${A} preset gallery: ${out.preset_gallery ? 'done' : 'FAILED'}`)
}
if (args.preset_batches && args.preset_batches.length) {
  // preset cards need no app: they run beside the effect gallery
  presetCards = workflow({scriptPath: `${S}/pgd_preset_cards.js`}, {...PASS, batches: args.preset_batches, width: args.preset_width || 3})
}

phase('Galleries')
out.gallery = await workflow({scriptPath: `${S}/pgd_effect_gallery.js`}, {...PASS, app: A, note: args.effect_note, ids: args.gallery_ids})
if (!out.gallery) {
  log(`${A} effect gallery FAILED: verification skipped (it would mark every card not_rendered)`)
} else {
  phase('Verify')
  out.verify = await workflow({scriptPath: `${S}/pgd_verify.js`}, {...PASS, batches: args.batches, width: args.width || 4})
  const ids = (out.verify && out.verify.rerender) || []
  log(`${A} verify: ${JSON.stringify(out.verify && out.verify.totals)}; ${ids.length} demos to re-render`)
  if (ids.length) {
    phase('Rerender')
    out.rerender = await workflow({scriptPath: `${S}/pgd_effect_gallery.js`}, {...PASS, app: A, ids,
      note: 'The effect gallery for this app is complete; this run only re-renders the listed cards with their NEW demo_settings. Start the app yourself if it is not running.'})
    if (out.rerender) {
      phase('Recheck')
      const rb = ((out.verify && out.verify.per_batch) || []).filter(p => p.rerender && p.rerender.length).map(p => p.batch)
      out.recheck = await workflow({scriptPath: `${S}/pgd_verify.js`}, {...PASS, batches: rb, recheck: true, ids, width: args.width || 4})
    }
  }
}
if (presetCards) out.preset_cards = await presetCards
return out
