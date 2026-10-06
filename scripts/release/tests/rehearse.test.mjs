import test from 'node:test'
import assert from 'node:assert/strict'
import { buildEnvironment, buildCommands, run } from '../rehearse.mjs'

test('allowlist strips credentials and graphical state before every build', () => {
  const env = buildEnvironment({PATH: '/usr/bin', GITHUB_TOKEN: 'fixture', GH_TOKEN: 'fixture',
    AWS_SECRET_ACCESS_KEY: 'fixture', SSH_AUTH_SOCK: '/socket', DISPLAY: ':0',
    DBUS_SESSION_BUS_ADDRESS: 'fixture', NODE_OPTIONS: '--inspect', HOME: '/real-home',
    ODIN_PACKAGING_CACHE: '/isolated/cache'}, '/temporary/home')
  assert.deepEqual(Object.keys(env).sort(), ['CI', 'HOME', 'ODIN_PACKAGING_CACHE', 'PATH',
    'XDG_CACHE_HOME', 'npm_config_globalconfig', 'npm_config_userconfig'].sort())
  assert.equal(env.HOME, '/temporary/home')
  assert.equal(env.npm_config_userconfig, '/dev/null')
})

test('only pinned nonpublishing builder is selected', () => {
  assert.deepEqual(buildCommands(), [['npm', ['ci', '--ignore-scripts']],
    ['node', ['node_modules/electron/install.js']], ['npm', ['run', 'package:candidate']]])
})

test('invalid build options fail without launching build', () => {
  assert.throws(() => run(['--build=publish']), /build must/)
  assert.throws(() => run(['--publish=true']), /Unknown/)
  assert.throws(() => run(['--build=true']), /Missing/)
})
