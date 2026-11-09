// Renders desktop/plugin.js outside the app with small stand-ins for the SDK, so the pane's
// own code runs (hooks, labels, error paths) against a real report. Usage:
//   node pane_harness.mjs <plugin.js> <scenario.json>
// The scenario names the profile Desktop is on and what the report query returns.
// Prints the rendered text; exits 1 with the error message if rendering throws.
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const [pluginPath, scenarioPath] = process.argv.slice(2)
const scenario = JSON.parse(readFileSync(scenarioPath, 'utf8'))
const seenKeys = []

// Same contract as the app's lib/time.ts: milliseconds in, and Intl throws on NaN.
const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto', style: 'short' })
const sdk = {
  host: { state: { profile: { get: () => scenario.profile } } },
  useValue: store => store.get(),
  atom: value => ({ get: () => value }),
  relativeTime: (targetMs, nowMs = Date.now()) => rtf.format(Math.round((targetMs - nowMs) / 60000), 'minute'),
  useQuery: options => {
    seenKeys.push(options.queryKey)
    const q = scenario.query
    const error = q.error ? Object.assign(new Error(q.error.message), q.error.statusCode ? { statusCode: q.error.statusCode } : {}) : null
    return { isPending: false, isError: Boolean(error), error, data: q.data ?? undefined, refetch: () => {} }
  }
}
for (const name of ['Badge', 'Button', 'CopyButton', 'EmptyState', 'ErrorState', 'ScrollArea', 'Skeleton']) {
  sdk[name] = props => ({ type: name, props })
}

// A tiny renderer: function components are called, everything else keeps its props.
const render = node => {
  if (node == null || node === false) return null
  if (Array.isArray(node)) return node.map(render)
  if (typeof node !== 'object') return node
  if (typeof node.type === 'function') return render(node.type(node.props))
  return { type: node.type, props: { ...node.props, children: render(node.props?.children) } }
}
const text = node => {
  if (node == null) return ''
  if (Array.isArray(node)) return node.map(text).join(' ')
  if (typeof node !== 'object') return String(node)
  const own = ['title', 'description', 'text'].map(k => (typeof node.props?.[k] === 'string' ? node.props[k] : '')).join(' ')
  return `${own} ${text(node.props?.children)}`
}

globalThis.__tuneupSdk = sdk
globalThis.__tuneupJsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }
const source = readFileSync(pluginPath, 'utf8')
  .replace(/import \{([^}]*)\} from '@hermes\/plugin-sdk'/, 'const {$1} = globalThis.__tuneupSdk')
  .replace(/import \{([^}]*)\} from 'react\/jsx-runtime'/, 'const {$1} = globalThis.__tuneupJsx')
const file = join(mkdtempSync(join(tmpdir(), 'tuneup-pane-')), 'plugin.mjs')
writeFileSync(file, source)
const plugin = (await import(pathToFileURL(file).href)).default

let pane
plugin.register({ source: 'hermes-tuneup', rest: async () => ({}), register: c => { pane = c } })
try {
  const out = text(render(pane.render())).replace(/\s+/g, ' ').trim()
  console.log(JSON.stringify({ text: out, queryKeys: seenKeys }))
} catch (error) {
  console.error(String(error?.message ?? error))
  process.exit(1)
}
