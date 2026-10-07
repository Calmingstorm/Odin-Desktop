// Offline-testable source helper only. The guest VM/UID marker guard still runs first.
import { lstatSync } from 'node:fs'

export function requireNativeDisplay(env, uid, lstat = lstatSync) {
  const runtime = `/run/user/${uid}`
  const info = lstat(runtime)
  if (env.XDG_RUNTIME_DIR !== runtime || !info.isDirectory() || info.uid !== uid)
    throw new Error('Requires owned guest runtime')
  const display = env.DISPLAY ?? ''
  if (display && !/^:\d+(?:\.\d+)?$/.test(display))
    throw new Error('Forwarded or malformed X11 display refused')
  if (env.XDG_SESSION_TYPE === 'wayland') {
    const name = env.WAYLAND_DISPLAY ?? ''
    if (!/^[a-zA-Z0-9_-][a-zA-Z0-9_.-]*$/.test(name))
      throw new Error('Unsafe Wayland socket name')
    const socket = lstat(`${runtime}/${name}`)
    if (!socket.isSocket() || socket.uid !== uid)
      throw new Error('Requires actual owned guest Wayland socket')
  } else if (env.XDG_SESSION_TYPE !== 'x11' || !display) {
    throw new Error('Requires confirmed native X11 or Wayland session')
  }
  if (display && !lstat(`/tmp/.X11-unix/X${display.slice(1).split('.')[0]}`).isSocket())
    throw new Error('Requires actual local X11 socket')
  return env.XDG_SESSION_TYPE
}
