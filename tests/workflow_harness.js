// Offline dry run of a PGD workflow script: the Workflow hooks (agent, parallel, pipeline, phase, log, workflow) are
// stubs that record every call instead of starting agents, so a script can be checked without an LLM.
//   node tests/workflow_harness.js <script.js> '<args JSON>'   ->  stdout: {"ok": bool, "error", "calls": [...]}
// "--check-only" as the second argument only compiles the wrapped body.
const fs = require('fs')

const [file, rawArgs] = process.argv.slice(2)
const src = fs.readFileSync(file, 'utf8').replace(/^export const meta\s*=/m, 'const meta =')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const HOOKS = ['args', 'agent', 'parallel', 'pipeline', 'phase', 'log', 'workflow', 'budget']
let body
try {
  body = new AsyncFunction(...HOOKS, src)
} catch (e) {
  console.log(JSON.stringify({ok: false, error: `syntax: ${e.message}`, calls: []}))
  process.exit(1)
}
if (rawArgs === '--check-only') {
  console.log(JSON.stringify({ok: true, calls: []}))
  process.exit(0)
}

const calls = []
// a result shaped like every schema the PGD scripts read from (so their follow-up stages run too)
const fake = () => ({non_pass: ['id-1'], rerender: [], totals: {}, per_batch: [], cards: 1, corrected: 0, pass: 1})
const agent = async (prompt, opts) => { calls.push({hook: 'agent', label: (opts || {}).label || '', prompt}); return fake() }
const parallel = async (thunks) => Promise.all(thunks.map(t => t()))
const pipeline = async (items, ...stages) => Promise.all(items.map(async (it, i) => {
  let r = it
  for (const [k, s] of stages.entries()) r = await s(k === 0 ? it : r, it, i)
  return r
}))
const workflow = async (ref, a) => { calls.push({hook: 'workflow', ref, args: a}); return fake() }
const budget = {total: null, spent: () => 0, remaining: () => Infinity}
const args = rawArgs === undefined || rawArgs === '' ? undefined : JSON.parse(rawArgs)

body(args, agent, parallel, pipeline, () => {}, () => {}, workflow, budget)
  .then(() => console.log(JSON.stringify({ok: true, calls})))
  .catch(e => { console.log(JSON.stringify({ok: false, error: String(e && e.message || e), calls})); process.exit(1) })
