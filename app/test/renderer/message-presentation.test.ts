import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ArtifactRef, Message as ChatMessage } from '../../src/shared/api'
import Message from '../../src/renderer/src/components/Message.vue'
import appIcon from '../../resources/icon.svg'
import { flush, mount, type Mounted } from './component-host'

vi.mock('../../src/renderer/src/markdown', () => ({ renderMarkdown: (text: string) => `<p>${text}</p>` }))
vi.mock('../../src/renderer/src/artifacts', () => ({
  showsInline: (a: ArtifactRef) => a.kind === 'image' && a.available,
  images: { acquire: () => ({ url: Promise.resolve('blob:fixture'), release: vi.fn() }) }
}))
vi.mock('../../src/renderer/src/components/FileCard.vue', () => ({ default: { render: () => null } }))
vi.mock('../../src/renderer/src/components/ReportViewer.vue', () => ({ default: { render: () => null } }))

let mounted: Mounted | undefined
afterEach(() => { mounted?.unmount(); mounted = undefined })

const artifact = (kind: ArtifactRef['kind']): ArtifactRef => ({
  ref: 'tool-output', name: 'Generated output', mime: kind === 'image' ? 'image/png' : 'text/plain',
  size: 42, kind, available: true
})
const message = (patch: Partial<ChatMessage> = {}): ChatMessage => ({
  id: 'message', role: 'notice', text: 'Published output.', created_at: '2026-10-08T12:00:00Z', ...patch
})

describe('message authorship and app avatar', () => {
  it.each(['image', 'file'] as const)('presents a tool-delivered %s as Odin without changing transcript role', async (kind) => {
    const original = message({ author: 'odin', request_id: 'tool-request', artifacts: [artifact(kind)] })
    mounted = mount(Message, { message: original, conversationId: 'chat' })
    await flush()
    const article = mounted.root.find('article')!
    expect(article.props.class).toContain('assistant')
    expect(article.props['aria-label']).toMatch(/^Odin message at /)
    expect(mounted.root.textContent()).toContain('Odin')
    const avatar = mounted.root.findAll((n) => n.props.class === 'avatar')[0]!
    expect(avatar.find('img')!.props.src).toBe(appIcon)
    expect(original.role).toBe('notice')
  })

  it.each([
    message(),
    message({ request_id: 'task' }),
    message({ artifacts: [artifact('image')] }),
    message({ request_id: 'task', artifacts: [artifact('image')] }),
    message({ request_id: 'task', artifacts: [artifact('file')] }),
    message({ request_id: 'task', artifacts: [artifact('report')] })
  ])('keeps genuine system notices named Notice', async (notice) => {
    mounted = mount(Message, { message: notice, conversationId: 'chat' })
    await flush()
    expect(mounted.root.find('article')!.props.class).toContain('notice')
    expect(mounted.root.find('article')!.props['aria-label']).toMatch(/^Notice message at /)
    expect(mounted.root.findAll((n) => n.props.class === 'avatar')[0]!.find('img')).toBeUndefined()
  })

  it('uses the exact bundled SVG, sized and decorative, for a normal Odin reply', async () => {
    mounted = mount(Message, { message: message({ role: 'assistant' }), conversationId: 'chat' })
    await flush()
    const avatar = mounted.root.findAll((n) => n.props.class === 'avatar')[0]!
    const logo = avatar.find('img')!
    expect(avatar.props['aria-hidden']).toBe('true')
    expect(logo.props.src).toBe(appIcon)
    expect(logo.props.alt).toBe('')
    expect(logo.props.width).toBe('36')
    expect(logo.props.height).toBe('36')
  })

  it('does not attribute user attachments to Odin', async () => {
    mounted = mount(Message, { message: message({ role: 'user', request_id: 'task', artifacts: [artifact('file')] }), conversationId: 'chat' })
    await flush()
    expect(mounted.root.find('article')!.props['aria-label']).toMatch(/^You message at /)
    expect(mounted.root.findAll((n) => n.props.class === 'avatar')[0]!.find('img')).toBeUndefined()
  })
})
