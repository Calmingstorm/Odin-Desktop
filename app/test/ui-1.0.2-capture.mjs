// Source-build UI evidence only. No live profile, desktop, real tools or provider calls.
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, realpathSync, readdirSync, writeFileSync } from 'node:fs'
import { dirname, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { launchIsolated, repositoryRoot } from '../scripts/real-core-isolation.mjs'

export const EPOCH = '2026-10-08T22:35:00.000Z'
export function fixtureCommand(python, fixture) {
  const bootstrap = `import asyncio, datetime, json, runpy, sys
class FrozenDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls.fromisoformat('2026-10-08T22:35:00+00:00')
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)
datetime.datetime = FrozenDateTime
fixture = sys.argv.pop(1)
sys.argv[0] = fixture
module = runpy.run_path(fixture, run_name='ui_102_fixture')
Core, Error = module['Core'], module['CoreError']
original_status = module['METHODS']['status.get']
def status(core, params, writer):
    value = original_status(core, params, writer)
    value['first_run'] = {'state': 'degraded', 'reason': 'provider_health_degraded', 'keyring_unavailable': False}
    return value
module['METHODS']['status.get'] = status
old_emit = Core.emit
def emit(core, type_, kind, entity_id, payload):
    if type_ == 'tool.started':
        class ToolDateTime(FrozenDateTime):
            @classmethod
            def now(cls, tz=None):
                value = cls.fromisoformat('2026-10-08T22:33:50+00:00')
                return value.astimezone(tz) if tz else value.replace(tzinfo=None)
        previous = module['now'].__globals__['datetime']
        module['now'].__globals__['datetime'] = ToolDateTime
        try: old_emit(core, type_, kind, entity_id, payload)
        finally: module['now'].__globals__['datetime'] = previous
    else: old_emit(core, type_, kind, entity_id, payload)
Core.emit = emit
def fixture_action(core, params, writer):
    action = params.get('action')
    if action == 'seed':
        mode = params['mode']
        conv = core.m_conv_create({'title': 'Evidence ' + mode}, writer)['conversation']
        cid, rid = conv['id'], 'request-' + mode
        if mode != 'empty':
            count = 30 if mode == 'history' else 1
            for i in range(count):
                core.commit_message(cid, {'id': cid + '-user-' + str(i), 'role': 'user', 'text': 'Inspect the disposable fixture. ' + ('Earlier context. ' * 20 if mode == 'history' else ''), 'created_at': module['now'](), 'request_id': rid})
                if mode == 'history': core.commit_message(cid, {'id': cid + '-reply-' + str(i), 'role': 'assistant', 'text': 'Synthetic earlier reply. ' * 25, 'created_at': module['now']()})
            if mode != 'history':
                core.commit_message(cid, {'id': cid + '-reply', 'role': 'assistant', 'text': 'The fixture is isolated. This is visual test data, not an executed command.', 'created_at': module['now']()})
                core.commit_message(cid, {'id': cid + '-notice', 'role': 'notice', 'text': 'Scheduled reminder: review the evidence at the same text column.', 'created_at': module['now']()})
        if mode in ('running', 'stopping', 'stopping-plain'):
            core.requests[rid] = {'id': rid, 'conversation_id': cid, 'generation': 1, 'message_id': cid + '-user-0', 'state': 'running', 'started_at': module['now'](), 'task': None, 'steers': [], 'stop_commands': []}
            core.active[cid] = rid
            core.record_control('steer-' + mode, 'steer', core.requests[rid], 'consumed', emit=False)
        if mode.startswith('cancelled') or mode == 'unresolved':
            core.recent[cid] = [{'request_id': rid, 'generation': 1, 'outcome': 'cancelled', 'unknown_effects': 1 if mode == 'unresolved' else 0, 'at': module['now']()}]
            if mode == 'cancelled-reply': core.commit_message(cid, {'id': cid + '-stop-reply', 'role': 'assistant', 'request_id': rid, 'text': 'Task stopped by user. No further steps ran.', 'created_at': module['now']()})
            if mode == 'unresolved': core.unresolved[cid] = list(core.recent[cid])
            core.controls['old-' + mode] = {'control_command_id': 'old-' + mode, 'kind': 'stop', 'request_id': rid, 'generation': 1, 'disposition': 'confirmed'}
        if mode == 'work':
            core.schedules.clear()
            for kind, title, state, detail in [('agent', 'Inspect disks', 'running', {'result': 'All fixture disks have room.'}), ('task', 'Capture review', 'completed', {'result': 'Review saved.'}), ('schedule', 'Evening report', 'scheduled', {'next_run': '2026-10-08T23:45:00Z', 'last_run': '2026-10-08T21:25:00Z', 'last_error': 'Synthetic endpoint timed out.'})]:
                core.work[kind] = {'kind': kind, 'id': kind, 'manager_id': 'hidden-manager', 'manager_generation': 'hidden-owner', 'run_id': 'hidden-run', 'generation': 71, 'conversation_id': cid, 'title': title, 'state': state, 'started_at': '2026-10-08T21:25:00Z', 'detail': dict(detail, revision=9), 'settlement': {'state': 'settled', 'resource_release': 'fixture_finished'}, 'actions': []}
        return {'conversation_id': cid, 'request_id': rid, 'title': conv['title']}
    if action == 'tool':
        cid, rid = params['conversation_id'], params['request_id']
        entry = {'invocation_id': rid + '-tool', 'tool': 'run_command', 'summary': 'run_command'}
        core.tools[rid] = [entry]
        core.emit('tool.started', 'invocation', entry['invocation_id'], dict(entry, conversation_id=cid, request_id=rid, generation=1))
        return {'emitted': True}
    if action == 'queue':
        cid = params['conversation_id']
        rid, mid = 'queued-request', 'queued-message'
        core.commit_message(cid, {'id': mid, 'role': 'user', 'text': 'A queued fixture follow-up. No tool will run.', 'created_at': module['now'](), 'request_id': rid})
        core.requests[rid] = {'id': rid, 'conversation_id': cid, 'generation': 1, 'message_id': mid, 'state': 'queued', 'started_at': None, 'task': None, 'text': 'Fixture queue'}
        core.queued.setdefault(cid, []).append(rid)
        core.emit('request.queued', 'request', rid, {'conversation_id': cid, 'request_id': rid, 'generation': 1, 'message_id': mid})
        return {'queued': True}
    if action == 'acknowledgements': return {'calls': getattr(core, 'evidence_acks', [])}
    raise Error('bad_request', 'Unknown evidence action')
def acknowledge(core, params, writer):
    core.evidence_acks = getattr(core, 'evidence_acks', []) + [dict(params)]
    cid, rid = params['conversation_id'], params['request_id']
    before = core.unresolved.get(cid, [])
    core.unresolved[cid] = [row for row in before if not (row['request_id'] == rid and row['generation'] == params['generation'])]
    core.emit('effects.resolved', 'request', rid, {'conversation_id': cid, 'request_id': rid, 'generation': params['generation'], 'remaining': 0})
    return {'disposition': 'acknowledged', 'remaining': 0}
module['METHODS']['ui_102.fixture'] = fixture_action
module['METHODS']['effects.acknowledge'] = acknowledge
sys.exit(asyncio.run(module['main']()))`
  return [python, '-B', '-P', '-c', `exec(${JSON.stringify(bootstrap)})`, fixture]
}
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex')
function provenance(app) {
  const files = []
  function visit(directory) {
    for (const item of readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const path = join(directory, item.name)
      if (item.isDirectory()) visit(path)
      else if (item.isFile()) files.push({ path: relative(repositoryRoot, path), sha256: hash(readFileSync(path)) })
    }
  }
  for (const directory of ['src', 'out', 'scripts', 'fixture-core', 'test']) visit(join(app, directory))
  return { files, digest: hash(JSON.stringify(files)) }
}
export async function capture() {
  if (process.env.ODIN_APP_UI_TREE_STABLE !== '1') throw new Error('Wait for parent stable-tree authorization')
  if (process.getuid?.() === 0) throw new Error('Run as nonprivileged odin')
  const app = join(repositoryRoot, 'app')
  const root = resolve(process.env.ODIN_APP_E2E_OUT || '/home/odin/reviews/desktop-1.0.2/ui-evidence')
  let ancestor = root
  while (!existsSync(ancestor)) ancestor = dirname(ancestor)
  const resolved = resolve(realpathSync(ancestor), relative(ancestor, root))
  const repo = realpathSync(repositoryRoot)
  if (resolved === repo || resolved.startsWith(repo + sep)) throw new Error('Evidence must remain outside repo')
  const output = join(resolved, `capture-${new Date().toISOString().replace(/[:.]/g, '-')}-${process.pid}`)
  mkdirSync(output, { recursive: true, mode: 0o700 })
  const manifest = { outcome: 'running', output, scope: 'Actual source-build Electron/Chromium pixels and browser DOM overflow; augmented synthetic fixture backend, no mocked renderer/preload.', limitations: ['Not real-engine effects acknowledgement qualification.', 'No provider/tool execution, installed/native desktop qualification or live desktop input.'], isolation: 'Unchanged launchIsolated, private PID/proc/HOME/XDG/D-Bus/Xvfb, sandbox enabled', artifacts: [] }
  let failure
  try {
    execFileSync('npm', ['run', 'typecheck'], { cwd: app, stdio: 'inherit', timeout: 180000 })
    execFileSync('npm', ['run', 'build'], { cwd: app, stdio: 'inherit', timeout: 180000 })
    manifest.source = provenance(app)
    manifest.git = { head: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repositoryRoot, encoding: 'utf8' }).trim(), diffSha256: hash(execFileSync('git', ['diff', 'HEAD', '--', 'app'], { cwd: repositoryRoot, maxBuffer: 16000000 })) }
    writeFileSync(join(output, 'plan.json'), JSON.stringify({ epoch: EPOCH, command: fixtureCommand(join(repositoryRoot, '.venv/bin/python'), join(app, 'fixture-core/fixture_core.py')) }, null, 2))
    const config = join(output, 'capture.config.ts')
    writeFileSync(config, `import base from ${JSON.stringify(join(app, 'playwright.config.ts'))}\nexport default { ...base, testDir: ${JSON.stringify(join(app, 'test/e2e'))}, testMatch: ['ui-1.0.2-capture.spec.ts'], outputDir: ${JSON.stringify(join(output, 'playwright-results'))}, timeout: 240000, retries: 0, workers: 1, reporter: [['list']], use: { trace: 'off', video: 'off', screenshot: 'off' } }\n`)
    await launchIsolated('dbus-run-session', ['--config-file', join(repositoryRoot, 'tests/desktop_fixtures/private-session.conf'), '--', 'xvfb-run', '-a', '-s', '-screen 0 2048x1200x24 -nolisten tcp', process.execPath, join(app, 'node_modules/@playwright/test/cli.js'), 'test', '--config', config], { cwd: repositoryRoot, timeoutMs: 300000, env: { ODIN_APP_E2E: '1', ODIN_APP_E2E_OUT: output, ODIN_APP_UI_102: '1', ODIN_APP_UI_PLAN: join(output, 'plan.json') } })
    if (provenance(app).digest !== manifest.source.digest) throw new Error('Source/build changed during capture')
    const receipt = JSON.parse(readFileSync(join(output, 'receipt.json'), 'utf8'))
    if (receipt.outcome !== 'passed') throw new Error('Behavioral receipt failed')
    manifest.outcome = 'passed'
  } catch (error) { failure = error; manifest.outcome = 'failed'; manifest.error = String(error.stack || error) }
  finally {
    manifest.artifacts = readdirSync(output).filter((name) => /\.(png|json)$/.test(name)).map((name) => { const path = join(output, name), bytes = readFileSync(path); return { path, bytes: bytes.length, sha256: hash(bytes) } })
    writeFileSync(join(output, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n')
    console.log(`UI 1.0.2 ${manifest.outcome}: ${output}`)
  }
  if (failure) throw failure
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) capture().catch((error) => { console.error(error); process.exitCode = 1 })
