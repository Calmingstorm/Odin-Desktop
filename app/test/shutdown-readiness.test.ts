import { afterEach, describe, expect, it, vi } from 'vitest'
import { Broker } from '../src/main/broker'
import { boundedShutdown } from '../src/main/shutdown'

const broker = (): Broker => new Broker({ socketPath: '/unused', readToken: () => '',
  profileId: 'test', clientVersion: 'test' })

afterEach(() => vi.useRealTimers())

describe('Exit readiness within the original request bound', () => {
  it('waits for the connecting core and removes its listeners on ready', async () => {
    const link = broker()
    link.quiesce()
    const wait = link.waitForShutdownReady(500)
    link.emit('state', 'ready')
    expect(await wait).toBe(true)
    expect(link.listenerCount('state')).toBe(0)
    expect(link.listenerCount('shutdown-closed')).toBe(0)
    link.close()
  })

  it('returns immediately for an already ready core', async () => {
    const link = broker()
    Object.assign(link, { link: 'ready', welcomeFrame: { core: { instance_id: 'current' } } })
    link.quiesce()
    expect(await link.waitForShutdownReady(500)).toBe(true)
    link.close()
  })

  it('never waits for a replacement after an established connection is lost', async () => {
    const link = broker()
    Object.assign(link, { welcomeFrame: { core: { instance_id: 'old' } }, link: 'reconnecting' })
    link.quiesce()
    expect(await link.waitForShutdownReady(500)).toBe(false)
    link.close()
  })

  it('close cancels the wait and late ready cannot dispatch shutdown', async () => {
    const link = broker()
    link.quiesce()
    const wait = link.waitForShutdownReady(500)
    link.close()
    link.emit('state', 'ready')
    expect(await wait).toBe(false)
    expect(link.listenerCount('state')).toBe(0)
  })

  it('no ready keeps unknown and aborts listeners at the existing total request bound', async () => {
    vi.useFakeTimers()
    const link = broker()
    const sent = vi.fn(async () => true)
    const finish = vi.fn()
    const shutdown = boundedShutdown({
      stopAdmission: () => link.quiesce(), persist: () => {},
      requestShutdown: async (signal) => await link.waitForShutdownReady(5_000, signal) && sent(),
      stopCore: async () => { link.close(); return 'exited' }, unreceipted: () => 0,
      finish, release: () => {}, exit: () => {}, requestTimeoutMs: 100
    })
    const result = shutdown()
    await vi.advanceTimersByTimeAsync(100)
    expect(await result).toMatchObject({ state: 'unknown', shutdownAccepted: false })
    expect(sent).not.toHaveBeenCalled()
    expect(link.listenerCount('state')).toBe(0)
    expect(vi.getTimerCount()).toBe(0)
    link.emit('state', 'ready')
    expect(sent).not.toHaveBeenCalled()
  })
})
