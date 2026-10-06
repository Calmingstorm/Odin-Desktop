// The parent runner owns the PID namespace, bus and Xvfb. This owns only its explicit notification receiver.
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { readFileSync, readlinkSync, existsSync } from 'node:fs'
import { connect } from 'node:net'
import { resolve, join } from 'node:path'

export interface NativeNotificationRequest {
  id: number
  summary: string
  body: string
  actions: string[]
  accepted: boolean
}
export interface NotificationBusSnapshot {
  pid: number
  pid_namespace: string
  requests: NativeNotificationRequest[]
  actions: Array<{ id: number; key: string }>
  closes: number[]
}
interface ProcessIdentity { pid: number; startTicks: string; uid: number; pidNamespace: string }

export class PrivateNotificationBus {
  readonly socket = join(process.env.HOME!, `notify-${randomUUID()}.sock`)
  private child: ChildProcessWithoutNullStreams | null = null
  private output = ''
  private error = ''
  private identity: ProcessIdentity | null = null

  async start(): Promise<void> {
    if (process.getuid?.() === 0 || process.env.ODIN_APP_E2E !== '1' || !process.env.DBUS_SESSION_BUS_ADDRESS ||
        !process.env.ODIN_REAL_CORE_OUTER_PID_NS ||
        readlinkSync('/proc/self/ns/pid') === process.env.ODIN_REAL_CORE_OUTER_PID_NS ||
        process.env.HOME !== process.env.ODIN_REAL_CORE_ROOT) {
      throw new Error('Use npm test:e2e: receiver refused unisolated execution')
    }
    const python = process.env.ODIN_DESKTOP_ENGINE_PYTHON
    if (!python) throw new Error('Project Python venv required for dbus-next fixture')
    const child = this.child = spawn(python, [resolve('tests/desktop_fixtures/private_notification_server.py'), '--socket', this.socket])
    if (!child.pid) throw new Error('Receiver did not get a PID')
    this.identity = {
      pid: child.pid,
      startTicks: readFileSync(`/proc/${child.pid}/stat`, 'utf8').split(') ')[1]!.split(' ')[19]!,
      uid: process.getuid!(), pidNamespace: readlinkSync(`/proc/${child.pid}/ns/pid`)
    }
    child.stdout.on('data', (data) => { this.output += String(data) })
    child.stderr.on('data', (data) => { this.error += String(data) })
    await new Promise<void>((accept, reject) => {
      const timer = setTimeout(() => reject(new Error(`Receiver startup timeout: ${this.error}`)), 10_000)
      const ready = (data: Buffer): void => {
        if (!String(data).includes('"ready": true')) return
        clearTimeout(timer)
        child.stdout.removeListener('data', ready)
        accept()
      }
      child.stdout.on('data', ready)
      child.once('error', (error) => { clearTimeout(timer); reject(error) })
      child.once('exit', (code) => { clearTimeout(timer); reject(new Error(`Receiver exited ${code}: ${this.error}`)) })
    })
  }

  control<T>(request: Record<string, unknown>): Promise<T> {
    return new Promise((accept, reject) => {
      const client = connect(this.socket)
      let text = ''
      client.setTimeout(5000, () => client.destroy(new Error('Receiver control timeout')))
      client.once('connect', () => client.write(`${JSON.stringify(request)}\n`))
      client.on('data', (data) => { text += String(data) })
      client.once('error', reject)
      client.once('end', () => {
        try {
          const response = JSON.parse(text) as { ok: boolean; result: T; error: string }
          if (!response.ok) reject(new Error(response.error))
          else accept(response.result)
        } catch (error) { reject(error) }
      })
    })
  }

  snapshot(): Promise<NotificationBusSnapshot> { return this.control({ action: 'snapshot' }) }

  async stop(): Promise<{ socketRemoved: boolean; code: number | null; receipt: string; identity: ProcessIdentity | null }> {
    const child = this.child
    if (!child) throw new Error('Receiver was not started')
    const exited = new Promise<number | null>((accept) => {
      if (child.exitCode !== null) accept(child.exitCode)
      else child.once('exit', accept)
    })
    const signalOwned = (signal: NodeJS.Signals): void => {
      if (!this.identity || child.exitCode !== null || child.signalCode !== null) return
      try {
        const start = readFileSync(`/proc/${this.identity.pid}/stat`, 'utf8').split(') ')[1]!.split(' ')[19]
        const uid = Number(/^Uid:\s+(\d+)/m.exec(readFileSync(`/proc/${this.identity.pid}/status`, 'utf8'))?.[1])
        if (start === this.identity.startTicks && uid === this.identity.uid &&
            readlinkSync(`/proc/${this.identity.pid}/ns/pid`) === this.identity.pidNamespace) child.kill(signal)
      } catch { /* Gone is not proof of the fixture's bus/socket cleanup. The receipt below decides that. */ }
    }
    const timer = setTimeout(() => signalOwned('SIGTERM'), 5000)
    const escalation = setTimeout(() => signalOwned('SIGKILL'), 7000)
    let deadline: ReturnType<typeof setTimeout> | undefined
    try {
      await this.control({ action: 'stop' }).catch(() => undefined)
      const code = await Promise.race([exited, new Promise<never>((_accept, reject) => {
        deadline = setTimeout(() => reject(new Error(`Receiver cleanup unknown: ${JSON.stringify(this.identity)}`)), 10_000)
      })])
      return { socketRemoved: !existsSync(this.socket), code, receipt: this.output, identity: this.identity }
    } finally { clearTimeout(timer); clearTimeout(escalation); clearTimeout(deadline) }
  }
}
