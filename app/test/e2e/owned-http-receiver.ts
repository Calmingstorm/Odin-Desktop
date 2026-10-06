import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { createInterface } from 'node:readline'
import { join } from 'node:path'
import { assertIsolated, isolatedEnv, repository } from './harness'

export interface EffectSnapshot {
  effect_count: number
  requests: Array<{effect: number; path: string; body: {event_type: string; data: {webhook_id: string}};
    response_sent: boolean; disconnected: boolean}>
}
export interface JournalReceipt {
  command_id: string; state: string; response: unknown; unknown_outcome: number
  created_at: number; finished_at: number | null
}
export class OwnedHttpReceiver {
  private child: ChildProcessWithoutNullStreams | null = null
  private pending = new Map<string, {resolve(value: unknown): void; reject(error: Error): void}>()
  private serial = 0
  private errors = ''
  port = 0
  identity: unknown
  cleanup: unknown
  readonly coreCommand = JSON.stringify([process.env.ODIN_DESKTOP_ENGINE_PYTHON!,
    join(repository, 'tests/desktop_fixtures/owned_http_receiver.py'), '--core-entry'])

  async start(): Promise<void> {
    assertIsolated()
    const child = this.child = spawn(process.env.ODIN_DESKTOP_ENGINE_PYTHON!,
      [join(repository, 'tests/desktop_fixtures/owned_http_receiver.py')], { env: isolatedEnv('http-receiver') })
    child.stderr.on('data', (chunk) => { this.errors += String(chunk) })
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error(`HTTP receiver startup: ${this.errors}`)), 10_000)
      child.once('error', (error) => { clearTimeout(timeout); reject(error) })
      child.once('exit', (code) => {
        clearTimeout(timeout)
        const error = new Error(`HTTP receiver exit ${code}: ${this.errors}`)
        reject(error)
        for (const waiter of this.pending.values()) waiter.reject(error)
        this.pending.clear()
      })
      createInterface({ input: child.stdout }).on('line', (line) => {
        const response = JSON.parse(line)
        if (response.ready) {
          this.port = response.port; this.identity = response; clearTimeout(timeout); resolve()
        } else if (response.cleanup) this.cleanup = response
        else {
          const waiter = this.pending.get(response.id)
          if (!waiter) return
          this.pending.delete(response.id)
          if (response.ok) waiter.resolve(response.result)
          else waiter.reject(new Error(response.error))
        }
      })
    })
  }
  control<T>(action: string, params: Record<string, unknown> = {}): Promise<T> {
    const id = String(++this.serial)
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('Owned HTTP control timeout')) }, 5_000)
      this.pending.set(id, { resolve: (value) => { clearTimeout(timer); resolve(value as T) },
        reject: (error) => { clearTimeout(timer); reject(error) } })
      this.child!.stdin.write(`${JSON.stringify({ id, action, ...params })}\n`)
    })
  }
  snapshot(): Promise<EffectSnapshot> { return this.control('snapshot') }
  journal(dataDir: string, commandId: string): Promise<JournalReceipt | null> {
    return this.control('journal', { path: join(dataDir, 'transport.sqlite3'), command_id: commandId })
  }
  async stop(): Promise<unknown> {
    if (!this.child) return null
    const child = this.child
    if (child.exitCode !== null || child.signalCode !== null) throw new Error(`HTTP receiver already exited: ${this.errors}`)
    const exit = new Promise<number | null>((resolve) => child.once('exit', resolve))
    await this.control('stop')
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
      const code = await Promise.race([exit, new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error('Owned HTTP receiver exit unknown')), 5_000)
      })])
      if (code !== 0 || !(this.cleanup as {listener_closed?: boolean} | undefined)?.listener_closed) {
        throw new Error(`Owned HTTP receiver cleanup failed: ${JSON.stringify({code, cleanup: this.cleanup, stderr: this.errors})}`)
      }
      return { code, identity: this.identity, cleanup: this.cleanup, stderr: this.errors }
    } finally { clearTimeout(timer) }
  }
}
