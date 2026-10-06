// Offline helper behavior. No Electron, desktop connection, input, or VM launch.
import assert from 'node:assert/strict'
import test from 'node:test'
import { requireNativeDisplay } from './native-p33-display.mjs'

const uid = 1001
const env = { XDG_RUNTIME_DIR: '/run/user/1001', XDG_SESSION_TYPE: 'wayland', WAYLAND_DISPLAY: 'wayland-0' }
function info(kind, owner = uid) {
  return { uid: owner, isDirectory: () => kind === 'directory', isSocket: () => kind === 'socket' }
}
function lstat(path) {
  if (path === env.XDG_RUNTIME_DIR) return info('directory')
  if (['/run/user/1001/wayland-0', '/tmp/.X11-unix/X0'].includes(path)) return info('socket')
  throw new Error('Missing socket')
}
test('confirmed Wayland needs no X DISPLAY', () => {
  assert.equal(requireNativeDisplay(env, uid, lstat), 'wayland')
})
test('X11 with actual local socket and DISPLAY', () => {
  assert.equal(requireNativeDisplay({ ...env, XDG_SESSION_TYPE: 'x11', DISPLAY: ':0.0' }, uid, lstat), 'x11')
})
for (const change of [
  { XDG_SESSION_TYPE: 'tty' }, { XDG_SESSION_TYPE: undefined },
  { XDG_SESSION_TYPE: 'x11' }, { WAYLAND_DISPLAY: '../wayland-0' },
  { WAYLAND_DISPLAY: '/run/user/1001/wayland-0' }, { WAYLAND_DISPLAY: '' },
  { WAYLAND_DISPLAY: 'missing' }, { DISPLAY: 'host:0' },
  { XDG_RUNTIME_DIR: '/tmp/foreign' },
]) test(`refuses ${JSON.stringify(change)}`, () => {
  assert.throws(() => requireNativeDisplay({ ...env, ...change }, uid, lstat))
})
for (const bad of ['file', 'symlink', 'foreign-uid']) test(`refuses Wayland ${bad}`, () => {
  assert.throws(() => requireNativeDisplay(env, uid, (path) => path === env.XDG_RUNTIME_DIR
    ? info('directory') : info(bad === 'foreign-uid' ? 'socket' : bad, bad === 'foreign-uid' ? 2000 : uid)))
})
test('refuses runtime symlink and foreign owner', () => {
  for (const entry of [info('symlink'), info('directory', 2000)])
    assert.throws(() => requireNativeDisplay(env, uid, () => entry))
})
test('refuses missing or non-socket X11 transport', () => {
  assert.throws(() => requireNativeDisplay({ ...env, XDG_SESSION_TYPE: 'x11', DISPLAY: ':8' }, uid, lstat))
  assert.throws(() => requireNativeDisplay({ ...env, XDG_SESSION_TYPE: 'x11', DISPLAY: ':0' }, uid,
    (path) => path === env.XDG_RUNTIME_DIR ? info('directory') : info('file')))
})
