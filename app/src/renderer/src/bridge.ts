import { reactive, readonly, shallowReactive, shallowReadonly } from 'vue'
import type { OdinApi } from '../../shared/api'

/**
 * A plain copy of renderer data, safe to hand to the preload. Electron's contextBridge refuses Vue's reactive
 * proxies ("An object could not be cloned."), so a list or object read from reactive state must never cross as is.
 * Arrays and plain objects are copied with their members unwrapped; anything else (strings, numbers, binary data,
 * functions such as event listeners) passes unchanged.
 */
export function toPlain<T>(value: T): T {
  const raw: unknown = value !== null && typeof value === 'object' ? unwrap(value) : value
  if (Array.isArray(raw)) return raw.map(toPlain) as T
  if (raw !== null && typeof raw === 'object') {
    const prototype = Object.getPrototypeOf(raw)
    if (prototype === Object.prototype || prototype === null) {
      return Object.fromEntries(Object.entries(raw).map(([key, member]) => [key, toPlain(member)])) as T
    }
  }
  return raw as T
}

const VIEWS: ReadonlyArray<(target: object) => unknown> = [reactive, readonly, shallowReactive, shallowReadonly]

/**
 * The data behind a genuine Vue proxy, or the value itself. Vue's marker keys (`__v_raw`, `__v_isReactive`,
 * `__v_isReadonly`) can be ordinary data in a plain object, so Vue's own toRaw, isProxy and isReactive prove nothing:
 * a value counts as a proxy only when Vue maps the target it names back to this very object.
 */
function unwrap(value: object): object {
  const target = (value as Record<string, unknown>).__v_raw
  if (target === null || typeof target !== 'object' || target === value) return value
  return VIEWS.some((view) => view(target) === value) ? unwrap(target) : value
}

/**
 * The preload API, for every call the renderer makes. Each call's arguments are copied to plain data first, and a
 * member the preload doesn't offer reads as missing, exactly as on `window.odin`. The preload object itself is
 * frozen by contextBridge, so this is the one place the copy can happen. Use this, never `window.odin` directly.
 */
export const odin: OdinApi = new Proxy({} as OdinApi, {
  get(_target, name) {
    const api = window.odin as unknown as Record<PropertyKey, unknown> | undefined
    const member = api?.[name]
    if (typeof member !== 'function') return member
    return (...args: unknown[]) => (member as (...values: unknown[]) => unknown).apply(api, args.map(toPlain))
  }
})
