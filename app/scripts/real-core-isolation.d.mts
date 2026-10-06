import type { EventEmitter } from 'node:events'

export const repositoryRoot: string

export interface LaunchOptions {
  env?: Record<string, string>
  cwd?: string
  timeoutMs?: number
  signal?: AbortSignal
}

interface IsolationHost extends EventEmitter {
  platform: string
  getuid(): number
  geteuid(): number
  getgid(): number
  getegid(): number
  pid: number
  execPath: string
  argv: string[]
  env: Record<string, string | undefined>
  kill(pid: number, signal: string): unknown
}

interface IsolationFiles {
  existsSync(path: string): boolean
  mkdtempSync(prefix: string): string
  chmodSync(path: string, mode: number): void
  mkdirSync(path: string, options: { mode: number }): unknown
  rmSync(path: string, options: { recursive: boolean; force: boolean }): void
  readlinkSync(path: string): string
  readFileSync(path: string, encoding: string): string
  lstatSync(path: string): {
    isDirectory(): boolean
    uid: number
    gid: number
    mode: number
  }
}

interface IsolationChild extends EventEmitter {
  pid?: number
  stdout: EventEmitter
  stderr: EventEmitter
}

export interface IsolationPrimitives {
  process?: IsolationHost
  files?: IsolationFiles
  spawnChild?: (command: string, args: string[], options: {
    cwd: string
    env: Record<string, string>
    detached: boolean
    stdio: string | string[]
  }) => IsolationChild
  temporaryDirectory?: () => string
  schedule?: (callback: () => void, delay: number) => object
  unschedule?: (handle: object) => unknown
}

export function createIsolationLauncher(primitives?: IsolationPrimitives): {
  assertRealCoreIsolation(mode?: '--inside-run' | '--inside-probe'): void
  launchIsolated(command: string, args?: string[], options?: LaunchOptions): Promise<void>
}

export function assertRealCoreIsolation(mode?: '--inside-run' | '--inside-probe'): void
export function launchIsolated(command: string, args?: string[], options?: LaunchOptions): Promise<void>
