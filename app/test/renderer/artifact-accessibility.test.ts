import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ArtifactRef, ReportPage, Result } from '../../src/shared/api'
import FileCard from '../../src/renderer/src/components/FileCard.vue'
import ReportViewer from '../../src/renderer/src/components/ReportViewer.vue'
import { flush, mount, type Mounted } from './component-host'

vi.mock('../../src/renderer/src/markdown', () => ({ renderMarkdown: (text: string) => `<p>${text}</p>` }))

const artifact: ArtifactRef = { ref: 'stored-report', name: 'Disk audit.md', mime: 'text/markdown', size: 200, kind: 'report', available: true }
let mounted: Mounted
let api: { reportPage: ReturnType<typeof vi.fn>; copyText: ReturnType<typeof vi.fn>; saveArtifact: ReturnType<typeof vi.fn> }
const page = (n: number): Result<ReportPage> => ({ ok: true, result: { page: n, pages: 3, text: `Stored page ${n}` } })

beforeEach(() => {
  api = {
    reportPage: vi.fn().mockResolvedValue(page(1)),
    copyText: vi.fn().mockResolvedValue({ ok: true, result: { copied: true } }),
    saveArtifact: vi.fn().mockResolvedValue({ ok: true, result: { saved: true } })
  }
  vi.stubGlobal('window', { odin: api })
})
afterEach(() => { mounted?.unmount(); vi.unstubAllGlobals() })

describe('artifact keyboard controls and live status', () => {
  it('keeps a file save control focusable during a pending save and suppresses duplicate activation', async () => {
    let resolve!: (result: Result<{ saved: boolean }>) => void
    api.saveArtifact.mockImplementation(() => new Promise((r) => { resolve = r }))
    mounted = mount(FileCard, { artifact, actionsOnly: true })
    const save = mounted.root.button('Save as…')
    expect(save.props['aria-label']).toBe('Save as… Disk audit.md')
    const pending = save.fire('click')
    await flush()
    expect(mounted.root.button('Save as…')).toBe(save)
    expect(save.props.disabled).toBeUndefined()
    expect(save.props['aria-disabled']).toBe(true)
    await save.fire('click')
    expect(api.saveArtifact).toHaveBeenCalledTimes(1)
    resolve({ ok: true, result: { saved: false } })
    await pending
    await flush()
    expect(save.props['aria-disabled']).toBe(false)
    expect(mounted.root.textContent()).toContain('Save cancelled for Disk audit.md.')
    expect(mounted.root.findAll((n) => n.props.role === 'status')).toHaveLength(1)
  })

  it('recovers file controls after bridge rejection without removing the live region', async () => {
    api.saveArtifact.mockRejectedValue(new Error('bridge closed'))
    mounted = mount(FileCard, { artifact })
    const status = mounted.root.findAll((n) => n.props.role === 'status')[0]
    await mounted.root.button('Save as…').fire('click')
    await flush()
    expect(mounted.root.button('Save as…').props['aria-disabled']).toBe(false)
    expect(mounted.root.findAll((n) => n.props.role === 'status')[0]).toBe(status)
    expect(status?.textContent()).toBe('Could not save Disk audit.md. Try again.')
  })

  it('preserves the report and paging controls while loading and on failure, then retries the failed page', async () => {
    mounted = mount(ReportViewer, { artifact })
    await flush()
    const next = mounted.root.button('Next')
    const body = mounted.root.findAll((n) => n.props.class === 'md report-body')[0]!
    let resolve!: (result: Result<ReportPage>) => void
    api.reportPage.mockImplementationOnce(() => new Promise((r) => { resolve = r }))
    const pending = next.fire('click')
    await flush()
    expect(body.props.innerHTML).toBe('<p>Stored page 1</p>')
    expect(body.props['aria-busy']).toBe(true)
    expect(mounted.root.button('Next')).toBe(next)
    expect(next.props.disabled).toBeUndefined()
    expect(next.props['aria-disabled']).toBe(true)
    await next.fire('click')
    expect(api.reportPage).toHaveBeenCalledTimes(2)
    resolve({ ok: false, error: { code: 'not_found', message: 'Page missing', disposition: 'not_dispatched' } })
    await pending
    await flush()
    expect(body.props.innerHTML).toBe('<p>Stored page 1</p>')
    expect(mounted.root.textContent()).toContain('Page missing')
    api.reportPage.mockResolvedValueOnce(page(2))
    await mounted.root.button('Retry').fire('click')
    await flush()
    expect(api.reportPage).toHaveBeenLastCalledWith({ report_id: 'stored-report', page: 2 })
    expect(body.props.innerHTML).toBe('<p>Stored page 2</p>')
    expect(next.props['aria-label']).toBe('Next page of Disk audit.md')
    expect(mounted.root.button('Previous').props['aria-label']).toBe('Previous page of Disk audit.md')
  })

  it('copies only the displayed stored page without treating the report as a downloadable file', async () => {
    mounted = mount(ReportViewer, { artifact })
    await flush()
    const copy = mounted.root.button('Copy page')
    expect(copy.props['aria-label']).toBe('Copy page of Disk audit.md')
    await copy.fire('click')
    await flush()
    expect(api.copyText).toHaveBeenCalledWith('Stored page 1')
    expect(mounted.root.textContent()).toContain('Copied page 1 of Disk audit.md.')
    expect(api.saveArtifact).not.toHaveBeenCalled()
    expect(api.reportPage).toHaveBeenCalledTimes(1)
  })

  it('keeps unavailable controls named but never dispatches them', async () => {
    mounted = mount(ReportViewer, { artifact: { ...artifact, available: false } })
    await flush()
    for (const label of ['Previous', 'Next', 'Copy page', 'Retry']) {
      expect(mounted.root.button(label).props['aria-disabled']).toBe(true)
      await mounted.root.button(label).fire('click')
    }
    expect(api.reportPage).not.toHaveBeenCalled()
    expect(api.copyText).not.toHaveBeenCalled()
    expect(api.saveArtifact).not.toHaveBeenCalled()
  })
})
