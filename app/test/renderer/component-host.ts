// Mounts a component's real compiled code without a browser. Vue renders onto plain objects that keep what it sets:
// tags, props and listeners, text, and the scroll geometry a test controls.
import { createRenderer, nextTick, type Component } from 'vue'

export class Host {
  parent: Host | null = null
  children: Host[] = []
  props: Record<string, unknown> = {}
  text = ''
  /** The scroll geometry: a test sets the heights, and the component sets scrollTop. */
  scrollHeight = 0
  clientHeight = 0
  /** Every scrollTop the component set, in order. */
  scrolls: number[] = []
  /** What a form control holds, as v-model and bound props read and set it. */
  value: unknown = ''
  checked = false
  private top = 0
  private readonly listeners: Record<string, Array<(event: unknown) => void>> = {}

  constructor(readonly tag: string) {}

  get scrollTop(): number {
    return this.top
  }

  set scrollTop(value: number) {
    this.top = Math.max(0, Math.min(value, this.scrollHeight - this.clientHeight))
    this.scrolls.push(this.top)
  }

  /** The first element below this one with the tag, depth first. */
  find(tag: string): Host | undefined {
    for (const child of this.children) {
      if (child.tag === tag) return child
      const found = child.find(tag)
      if (found) return found
    }
    return undefined
  }

  /** Every element below this one that matches, depth first. */
  findAll(match: (host: Host) => boolean): Host[] {
    return this.children.flatMap((child) => [...(match(child) ? [child] : []), ...child.findAll(match)])
  }

  /** The button that reads exactly this text. */
  button(text: string): Host {
    const found = this.findAll((host) => host.tag === 'button' && host.textContent().trim() === text)
    if (found.length !== 1) throw new Error(`expected one "${text}" button, found ${found.length}`)
    return found[0]!
  }

  /** v-model listens here. */
  addEventListener(type: string, listener: (event: unknown) => void): void {
    ;(this.listeners[type] ??= []).push(listener)
  }

  removeEventListener(type: string, listener: (event: unknown) => void): void {
    this.listeners[type] = (this.listeners[type] ?? []).filter((l) => l !== listener)
  }

  /** Calls every listener for an event, the one Vue set as a prop and v-model's, as the element firing it would. */
  fire(event: string, detail: Record<string, unknown> = {}): unknown {
    const prop = this.props[`on${event[0]!.toUpperCase()}${event.slice(1)}`] as ((e: unknown) => unknown) | undefined
    const listeners = this.listeners[event] ?? []
    if (!prop && !listeners.length) throw new Error(`no ${event} listener on <${this.tag}>`)
    const e = { target: this, ...detail }
    for (const listener of listeners) listener(e)
    return prop?.(e)
  }

  /** Types into a text control: what v-model and an input listener see. */
  type(text: string): unknown {
    this.value = text
    return this.fire('input')
  }

  /** The text a reader would see. */
  textContent(): string {
    if (this.tag === '#comment') return ''
    return this.text + this.children.map((child) => child.textContent()).join('')
  }
}

const renderer = createRenderer<Host, Host>({
  createElement: (tag) => new Host(tag),
  createText: (text) => Object.assign(new Host('#text'), { text }),
  createComment: (text) => Object.assign(new Host('#comment'), { text }),
  setText: (node, text) => {
    node.text = text
  },
  setElementText: (node, text) => {
    node.text = text
    node.children = []
  },
  parentNode: (node) => node.parent,
  nextSibling: (node) => {
    const siblings = node.parent?.children
    return siblings?.[siblings.indexOf(node) + 1] ?? null
  },
  patchProp: (node, key, _previous, next) => {
    node.props[key] = next
    if (key === 'value') node.value = next
    if (key === 'checked') node.checked = Boolean(next)
  },
  insert: (node, parent, anchor) => {
    if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
    const at = anchor ? parent.children.indexOf(anchor) : -1
    parent.children.splice(at < 0 ? parent.children.length : at, 0, node)
    node.parent = parent
  },
  remove: (node) => {
    if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
    node.parent = null
  }
})

export interface Mounted {
  root: Host
  /** The component's own bindings, as its template sees them: refs unwrapped, and its functions. */
  setup: Record<string, unknown>
  unmount: () => void
}

export function mount(component: Component, props?: Record<string, unknown>): Mounted {
  const root = new Host('root')
  const app = renderer.createApp(component, props)
  app.mount(root)
  const instance = (app as unknown as { _instance: { setupState: Record<string, unknown> } })._instance
  return { root, setup: instance.setupState, unmount: () => app.unmount() }
}

/** Lets promises settle and Vue apply what they changed. */
export async function flush(): Promise<void> {
  for (let i = 0; i < 8; i++) {
    await Promise.resolve()
    await nextTick()
  }
}

/** Animation frames, held until the test delivers them. */
export function heldFrames(): { pending: () => number; deliver: () => Promise<void> } {
  const frames: FrameRequestCallback[] = []
  ;(globalThis as unknown as { requestAnimationFrame: unknown }).requestAnimationFrame = (callback: FrameRequestCallback) =>
    frames.push(callback)
  return {
    pending: () => frames.length,
    deliver: async () => {
      for (const callback of frames.splice(0)) callback(0)
      await flush()
    }
  }
}
