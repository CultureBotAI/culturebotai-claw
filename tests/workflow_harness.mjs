// Offline harness for claw's workflow scripts (.claude/workflows/*.js).
//
// A real workflow run is billed and non-deterministic, so tests never make one.
// This runs a script against stubbed runtime hooks -- agent, parallel, pipeline,
// phase, log, args, budget, workflow -- with scripted agent responses, and
// prints what happened as JSON. tests/test_claude_workflows.py drives it.
//
//   node tests/workflow_harness.mjs run  <script.js> '<scenario json>'
//   node tests/workflow_harness.mjs meta <script.js>
//
// Scenario keys (all optional):
//   args        the value the script sees as `args`
//   responses   {labelPrefix: response}; the longest matching prefix of an agent's
//               label wins. {"sequence": [r1, r2, ...]} hands out one per call.
//   nullCalls   agent call indices (0-based, in call order) that return null, as
//               the runtime does for an agent that died
//   nullLabels  label prefixes whose agents return null
//
// An agent call with no scripted response is a harness error, not a null: a test
// fixture that forgot a stage must not pass by looking like a failed agent.

import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const [mode, scriptPath, scenarioJson] = process.argv.slice(2)
const source = readFileSync(scriptPath, 'utf8')
const emit = (value) => process.stdout.write(JSON.stringify(value))

// The literal after `export const meta =`, up to the first line that is `}`.
function metaLiteral(text) {
  const match = text.match(/^export const meta\s*=\s*(\{[\s\S]*?\n\})/m)
  if (!match) throw new Error('no `export const meta = {...}` block')
  return match[1]
}

if (mode === 'meta') {
  const literal = metaLiteral(source)
  // A pure literal evaluates with nothing in scope; a variable reference throws.
  const meta = vm.runInNewContext(`(${literal})`, Object.create(null))
  emit({ literal, meta, phaseCalls: [...source.matchAll(/\bphase\(\s*'([^']+)'\s*\)/g)].map((m) => m[1]) })
  process.exit(0)
}

if (mode !== 'run') throw new Error(`unknown mode ${mode}`)
const scenario = JSON.parse(scenarioJson || '{}')
const calls = []
const logs = []
const phases = []
const unscripted = []
const sequences = new Map()

function scripted(label) {
  const table = scenario.responses || {}
  const key = Object.keys(table)
    .filter((k) => label === k || label.startsWith(k))
    .sort((x, y) => y.length - x.length)[0]
  if (key === undefined) return undefined
  const value = table[key]
  if (value && typeof value === 'object' && Array.isArray(value.sequence)) {
    const next = sequences.get(key) || 0
    sequences.set(key, next + 1)
    return value.sequence[Math.min(next, value.sequence.length - 1)]
  }
  return value
}

async function agent(prompt, opts = {}) {
  const index = calls.length
  const label = opts.label || ''
  calls.push({ index, label, phase: opts.phase || null, schema: opts.schema || null, prompt: String(prompt) })
  if ((scenario.nullCalls || []).includes(index)) return null
  if ((scenario.nullLabels || []).some((p) => label === p || label.startsWith(p))) return null
  const response = scripted(label)
  if (response === undefined) {
    unscripted.push(label)
    throw new Error(`no scripted response for agent "${label}"`)
  }
  return JSON.parse(JSON.stringify(response))
}

// The runtime's semantics: a thunk that throws resolves to null; never rejects.
const parallel = async (thunks) =>
  Promise.all(thunks.map((thunk) => Promise.resolve().then(thunk).catch(() => null)))

const pipeline = async (items, ...stages) =>
  Promise.all(items.map(async (item, index) => {
    try {
      let value = item
      for (const stage of stages) value = await stage(value, item, index)
      return value
    } catch {
      return null
    }
  }))

const context = vm.createContext({
  agent,
  parallel,
  pipeline,
  phase: (title) => phases.push(String(title)),
  log: (message) => logs.push(String(message)),
  args: scenario.args,
  budget: { total: null, spent: () => 0, remaining: () => Infinity },
  workflow: async () => { throw new Error('nested workflow() is not stubbed') },
})

const body = source.replace(/^export const meta\s*=/m, 'const meta =')
try {
  const result = await vm.runInContext(`(async () => {\n${body}\n})()`, context, { filename: scriptPath })
  emit({ ok: unscripted.length === 0, result, calls, logs, phases, unscripted })
} catch (error) {
  emit({ ok: false, error: String((error && error.stack) || error), calls, logs, phases, unscripted })
}
