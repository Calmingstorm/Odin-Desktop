import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { test } from 'node:test'
import { capture, fixtureCommand, EPOCH } from './ui-1.0.2-capture.mjs'

test('capture refuses unstable tree before build/namespace/display work', async () => {
  const previous = process.env.ODIN_APP_UI_TREE_STABLE
  delete process.env.ODIN_APP_UI_TREE_STABLE
  try { await assert.rejects(capture(), /Wait for parent stable-tree authorization/) }
  finally {
    if (previous === undefined) delete process.env.ODIN_APP_UI_TREE_STABLE
    else process.env.ODIN_APP_UI_TREE_STABLE = previous
  }
})
test('disposable fixture command is printable argv and valid Python, never runs core in this test', () => {
  const command = fixtureCommand('/fixture/python', '/fixture/core.py')
  assert.deepEqual(command.slice(0, 4), ['/fixture/python', '-B', '-P', '-c'])
  assert.equal(command.at(-1), '/fixture/core.py')
  assert.equal(EPOCH, '2026-10-08T22:35:00.000Z')
  for (const arg of command) assert.doesNotMatch(arg, /[\x00-\x1f]/)
  const source = JSON.parse(command[4].slice(5, -1))
  execFileSync('python3', ['-P', '-c', 'import sys; compile(sys.argv[1], "evidence-fixture", "exec")', source])
  assert.match(source, /module\['METHODS'\]\['effects.acknowledge'\]/)
  assert.match(source, /ui_102.fixture/)
  assert.match(source, /request.queued/)
})
