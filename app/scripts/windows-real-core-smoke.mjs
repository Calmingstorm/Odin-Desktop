// The Windows real-app smoke runner (phase 3d, D11). Windows only, from a source checkout where `uv sync --locked`
// installed the engine and `npm run build` built the app:
// - a root it creates, whose ACL it measures (only this user, SYSTEM, Administrators and the owner placeholders);
// - a loopback scripted model (never a real one, no accounts);
// - the built app with the checkout's real engine, launched twice: a first run, then a relaunch;
// - evidence of each launch, plus the app, the engine and anything they started gone afterwards.
// Only the processes it started are ever ended. The root is removed on success and kept, with its logs, on failure.
import { execFileSync, spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

if (process.platform !== 'win32') {
  console.error('windows-smoke: Windows only')
  process.exit(2)
}
const APP = resolve(import.meta.dirname, '..')
const REPO = resolve(APP, '..')
const PYTHON = process.env.ODIN_WINDOWS_SMOKE_PYTHON ?? join(REPO, '.venv', 'Scripts', 'python.exe')
const ELECTRON = join(APP, 'node_modules', 'electron', 'dist', 'electron.exe')
const PHASE_SECONDS = 240
const powershell = (script, env = {}) => execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script],
  { encoding: 'utf8', windowsHide: true, env: { ...process.env, ...env }, timeout: 60_000 }).trim()

for (const [name, path] of [['the engine interpreter', PYTHON], ['Electron', ELECTRON], ['the built app', join(APP, 'out', 'main', 'index.js')]]) {
  if (!existsSync(path)) throw new Error(`windows-smoke: ${name} is missing: ${path}`)
}

// The root: created here, then measured. Anything beyond this user, SYSTEM, Administrators, OWNER RIGHTS and
// CREATOR OWNER refuses the run before the app starts.
const root = mkdtempSync(join(tmpdir(), 'odws-'))
const sids = powershell(
  '$acl = Get-Acl -LiteralPath $env:ODWS_ROOT; ' +
  '$acl.Access | ForEach-Object { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value }; ' +
  '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value', { ODWS_ROOT: root }).split(/\r?\n/).map((s) => s.trim()).filter(Boolean)
const user = sids.pop()
const allowed = new Set([user, 'S-1-5-18', 'S-1-5-32-544', 'S-1-3-4', 'S-1-3-0'])
const foreign = sids.filter((sid) => !allowed.has(sid))
if (foreign.length) throw new Error(`windows-smoke: the temporary root admits others (${foreign.join(', ')}); refusing`)
const nonce = randomBytes(16).toString('hex')
writeFileSync(join(root, 'smoke-root.json'), JSON.stringify({ nonce }))
const local = join(root, 'local')
mkdirSync(local)
const marker = join(root, 'tool-marker.txt')

// The scripted model: the compat provider's chat API, answering by the prompt's token.
let calls = 0
const text = (message) => typeof message.content === 'string' ? message.content
  : (message.content ?? []).map((part) => part.text ?? '').join('\n')
const model = createServer(async (request, response) => {
  const chunks = []
  for await (const chunk of request) chunks.push(chunk)
  const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : {}
  if (request.method === 'GET' && request.url === '/v1/models') {
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify({ data: [{ id: 'canned-contract', object: 'model' }] }))
    return
  }
  if (request.method !== 'POST' || request.url !== '/v1/chat/completions') {
    response.writeHead(404)
    response.end()
    return
  }
  const messages = body.messages ?? []
  const last = messages.findLastIndex((message) => message.role === 'user')
  const prompt = last >= 0 ? text(messages[last]) : ''
  const toolResults = messages.slice(last + 1).filter((message) => message.role === 'tool')
  let delta = { content: 'COMPLETE' } // asks without tools: the completion judge
  if (body.tools?.length) {
    delta = { content: 'Scripted reply: windows smoke.' }
    if (prompt.includes('[tool]')) {
      delta = toolResults.length ? { content: 'Scripted reply: the local tool ran.' } : { tool_calls: [{ index: 0,
        id: `call_${++calls}`, type: 'function', function: { name: 'run_command', arguments: JSON.stringify({
          host: 'localhost', command: `Set-Content -LiteralPath '${marker}' -Value 'windows smoke tool ran'` }) } }] }
    }
  }
  response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' })
  const frame = (value) => response.write(`data: ${JSON.stringify(value)}\n\n`)
  frame({ id: 'scripted', object: 'chat.completion.chunk', model: 'canned-contract',
    choices: [{ index: 0, delta: { role: 'assistant', ...delta }, finish_reason: null }] })
  frame({ choices: [{ index: 0, delta: {}, finish_reason: delta.tool_calls ? 'tool_calls' : 'stop' }] })
  frame({ choices: [], usage: { prompt_tokens: 100, completion_tokens: 20, total_tokens: 120 } })
  response.end('data: [DONE]\n\n')
})
await new Promise((accept) => model.listen(0, '127.0.0.1', accept))
const baseUrl = `http://127.0.0.1:${model.address().port}/v1`

function alive(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch (error) {
    return error.code === 'EPERM'
  }
}

/** Processes whose command line names the root: anything the app or the engine started from it. */
function leftovers() {
  const found = powershell('Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($env:ODWS_ROOT) } | ' +
    'ForEach-Object { "$($_.ProcessId) $($_.Name)" }', { ODWS_ROOT: root })
  return found ? found.split(/\r?\n/) : []
}

async function launch(phase) {
  const env = { ...process.env, LOCALAPPDATA: local, ODIN_WINDOWS_SMOKE: '1', ODIN_WINDOWS_SMOKE_ROOT: root,
    ODIN_WINDOWS_SMOKE_NONCE: nonce, ODIN_WINDOWS_SMOKE_PHASE: phase, ODIN_SMOKE_PROVIDER_BASE_URL: baseUrl,
    ODIN_DESKTOP_CORE_CMD: JSON.stringify([PYTHON, '-I', '-B', '-m', 'src']) }
  delete env.ELECTRON_RUN_AS_NODE
  // A hosted runner without a GPU may disable hardware acceleration; Electron's sandbox stays on regardless.
  const gpu = process.env.ODIN_WINDOWS_SMOKE_NO_GPU === '1' ? ['--disable-gpu'] : []
  const child = spawn(ELECTRON, [APP, '--smoke-test', ...gpu], { env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: false })
  let output = ''
  child.stdout.on('data', (data) => { output += data })
  child.stderr.on('data', (data) => { output += data })
  const exitCode = await new Promise((accept) => {
    const timer = setTimeout(() => {
      // Only the tree this runner started: the app, its engine and anything they started.
      execFileSync('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' })
      accept('timed out')
    }, PHASE_SECONDS * 1_000)
    child.once('exit', (code) => { clearTimeout(timer); accept(code) })
  })
  const evidencePath = join(root, `evidence-${phase}.json`)
  const evidence = existsSync(evidencePath) ? JSON.parse(readFileSync(evidencePath, 'utf8')) : { ok: false, error: 'no evidence' }
  const corePid = evidence.session?.corePid
  const deadline = Date.now() + 30_000
  while (corePid && alive(corePid) && Date.now() < deadline) await new Promise((accept) => setTimeout(accept, 250))
  return { phase, exitCode, evidence, coreGone: corePid ? !alive(corePid) : 'unknown', leftovers: leftovers(),
    log: output.slice(-4_000) }
}

function revision() {
  if (process.env.ODIN_WINDOWS_SMOKE_REVISION) return process.env.ODIN_WINDOWS_SMOKE_REVISION
  try { return execFileSync('git', ['-C', REPO, 'rev-parse', 'HEAD'], { encoding: 'utf8', windowsHide: true }).trim() }
  catch { return 'unknown' }
}
const report = { revision: revision(),
  python: execFileSync(PYTHON, ['-V'], { encoding: 'utf8' }).trim(), node: process.version,
  rootAcl: { measured: sids.length + 1, foreign: [] }, launches: [] }
let ok = false
try {
  for (const phase of ['first', 'relaunch']) {
    const result = await launch(phase)
    report.launches.push(result)
    if (result.exitCode !== 0 || !result.evidence.ok || result.coreGone !== true || result.leftovers.length) break
  }
  ok = report.launches.length === 2 && report.launches.every((result) => result.exitCode === 0 && result.evidence.ok
    && result.coreGone === true && result.leftovers.length === 0)
} finally {
  model.close()
  report.ok = ok
  if (!ok) report.keptRoot = root
  const out = process.env.ODIN_WINDOWS_SMOKE_REPORT ?? join(APP, 'windows-smoke-report.json')
  writeFileSync(out, JSON.stringify(report, null, 2))
  if (ok) rmSync(root, { recursive: true, force: true })
  console.log(`windows-smoke: ${ok ? 'ok' : 'FAILED'} (report ${out}${ok ? '' : `, root kept at ${root}`})`)
}
process.exit(ok ? 0 : 1)
