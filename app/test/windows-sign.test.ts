// The release build's Windows signing hook (packaging/sign-windows.cjs, electron-builder.windows.yml's
// signtoolOptions.sign): it signs only Odin's own executables, with SignTool and the Artifact Signing library,
// checks each signature, and stays off outside the release build.
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

const require = createRequire(import.meta.url)
const APP = resolve(__dirname, '..')
type Result = { status: number | null; stdout?: string; stderr?: string; error?: Error }
type Call = { command: string; args: string[]; options: { env?: Record<string, string> } }
type Signer = (configuration: { path: string; hash?: string }) => Promise<void>
const hook = require(join(APP, 'packaging', 'sign-windows.cjs')) as {
  sign: Signer
  classify(file: string): string
  createSigner(options: { env: Record<string, string | undefined>; run: (command: string, args: string[],
    options: Call['options']) => Result; sleep: (ms: number) => Promise<void>; log: (line: string) => void }): Signer
}
const VALID = { status: 'Valid', publisher: 'Aaron Charpentier', thumbprint: 'C2DEDC99', timestamped: true }

const roots: string[] = []
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }) })

// electron-builder's output folder: the unpacked app (its bundled executables included), the uninstaller it
// builds, the installer, and the provisioned signing tools elsewhere.
function tree() {
  const root = mkdtempSync(join(tmpdir(), 'odin-sign-'))
  roots.push(root)
  const out = join(root, '.packaging-candidates')
  const app = join(out, 'win-unpacked')
  const write = (path: string): string => { mkdirSync(resolve(path, '..'), { recursive: true }); writeFileSync(path, 'MZ'); return path }
  const files = {
    app: write(join(app, 'Odin.exe')),
    python: write(join(app, 'resources', 'runtime', 'python', 'python.exe')),
    ssh: write(join(app, 'resources', 'tools', 'openssh', 'ssh.exe')),
    uninstaller: write(join(out, '__uninstaller-nsis-Odin.exe')),
    installer: write(join(out, 'odin-desktop-1.0.7-candidate-x64-setup.exe')),
    other: write(join(out, 'helper.exe'))
  }
  const env = {
    ODIN_WINDOWS_SIGNING: '1',
    ODIN_SIGNTOOL: write(join(root, 'signing', 'signtool', 'signtool.exe')),
    ODIN_SIGNING_DLIB: write(join(root, 'signing', 'dlib', 'Azure.CodeSigning.Dlib.dll')),
    ODIN_SIGNING_METADATA: write(join(root, 'signing', 'metadata.json')),
    ODIN_SIGNING_PUBLISHER: 'Aaron Charpentier'
  }
  return { files, env }
}

// SignTool's and PowerShell's answers, in order; every call recorded.
function runner(signtool: number[] = [0], signature: Record<string, unknown> | string = VALID) {
  const calls: Call[] = []
  const codes = [...signtool]
  const run = (command: string, args: string[], options: Call['options']): Result => {
    calls.push({ command, args, options })
    if (command === 'powershell.exe') {
      return { status: 0, stdout: typeof signature === 'string' ? signature : JSON.stringify(signature) }
    }
    return { status: codes.length > 1 ? codes.shift()! : codes[0], stdout: '', stderr: 'SignerSign() failed' }
  }
  return { calls, run }
}

function signer(env: Record<string, string | undefined>, run: ReturnType<typeof runner>['run']) {
  const waits: number[] = []
  const log: string[] = []
  const sign = hook.createSigner({ env, run, sleep: async (ms) => { waits.push(ms) }, log: (line) => log.push(line) })
  return { sign, waits, log }
}

describe('the release build\'s Windows signing hook', () => {
  it('is what the Windows build configuration names, as electron-builder resolves it', async () => {
    const { getConfig } = require('app-builder-lib/out/util/config/config') as {
      getConfig(projectDir: string, configPath: string, options: null): Promise<Record<string, any>> }
    const windows = await getConfig(APP, 'electron-builder.windows.yml', null)
    expect(windows.win.signtoolOptions).toEqual({ sign: 'packaging/sign-windows.cjs', signingHashAlgorithms: ['sha256'] })
    expect(typeof hook.sign).toBe('function')  // the named export electron-builder takes
  })

  it('stays off unless the release build asks for signing', async () => {
    const { files, env } = tree()
    const { calls, run } = runner()
    const { sign } = signer({ ...env, ODIN_WINDOWS_SIGNING: undefined }, run)
    for (const file of Object.values(files)) await sign({ path: file, hash: 'sha256' })
    expect(calls).toEqual([])
  })

  it('signs Odin.exe, the uninstaller and the installer, then checks each signature', async () => {
    const { files, env } = tree()
    const { calls, run } = runner()
    const { sign, log } = signer(env, run)
    for (const file of [files.app, files.uninstaller, files.installer]) await sign({ path: file, hash: 'sha256' })
    expect(calls.map((call) => call.command)).toEqual([env.ODIN_SIGNTOOL, 'powershell.exe', env.ODIN_SIGNTOOL,
      'powershell.exe', env.ODIN_SIGNTOOL, 'powershell.exe'])
    expect(calls[0].args).toEqual(['sign', '/v', '/fd', 'SHA256', '/tr', 'http://timestamp.acs.microsoft.com', '/td',
      'SHA256', '/dlib', env.ODIN_SIGNING_DLIB, '/dmdf', env.ODIN_SIGNING_METADATA, files.app])
    // The file reaches PowerShell through the environment, never inside the command.
    expect(calls[1].options.env?.ODIN_SIGNED_FILE).toBe(files.app)
    expect(calls[1].args.join(' ')).not.toContain(files.app)
    expect(calls[5].options.env?.ODIN_SIGNED_FILE).toBe(files.installer)
    expect(log).toEqual([
      'signing: signed the app, Odin.exe, as Aaron Charpentier (C2DEDC99)',
      'signing: signed the uninstaller, __uninstaller-nsis-Odin.exe, as Aaron Charpentier (C2DEDC99)',
      'signing: signed the installer, odin-desktop-1.0.7-candidate-x64-setup.exe, as Aaron Charpentier (C2DEDC99)'])
  })

  it('leaves every bundled executable as its publisher shipped it', async () => {
    const { files, env } = tree()
    const { calls, run } = runner()
    const { sign } = signer(env, run)
    await sign({ path: files.python, hash: 'sha256' })
    await sign({ path: files.ssh, hash: 'sha256' })
    expect(calls).toEqual([])
    expect(hook.classify(files.ssh)).toBe('bundled')
  })

  it('refuses a file it doesn\'t know, and any digest but SHA-256', async () => {
    const { files, env } = tree()
    const { calls, run } = runner()
    const { sign } = signer(env, run)
    await expect(sign({ path: files.other, hash: 'sha256' })).rejects.toThrow('unexpected file')
    await expect(sign({ path: files.app, hash: 'sha1' })).rejects.toThrow('SHA-256 only')
    expect(calls).toEqual([])
  })

  it('refuses without the provisioned tools or the expected publisher', async () => {
    const { files, env } = tree()
    const { run } = runner()
    for (const name of ['ODIN_SIGNTOOL', 'ODIN_SIGNING_DLIB', 'ODIN_SIGNING_METADATA', 'ODIN_SIGNING_PUBLISHER']) {
      await expect(signer({ ...env, [name]: undefined }, run).sign({ path: files.app })).rejects.toThrow(name)
    }
    await expect(signer({ ...env, ODIN_SIGNING_DLIB: join(env.ODIN_SIGNING_DLIB, 'missing') }, run)
      .sign({ path: files.app })).rejects.toThrow('missing file')
  })

  it('fails the build on a signature that isn\'t valid, isn\'t the publisher\'s, or has no timestamp', async () => {
    const { files, env } = tree()
    for (const signature of [{ ...VALID, status: 'NotSigned' }, { ...VALID, publisher: 'Someone Else' },
      { ...VALID, timestamped: false }, 'not json']) {
      const { run } = runner([0], signature)
      await expect(signer(env, run).sign({ path: files.installer })).rejects.toThrow(files.installer)
    }
  })

  it('tries SignTool three times, waiting longer each time, then fails the build', async () => {
    const { files, env } = tree()
    const flaky = runner([1, 1, 0])
    const recovered = signer(env, flaky.run)
    await recovered.sign({ path: files.installer })
    expect(flaky.calls.map((call) => call.command)).toEqual([env.ODIN_SIGNTOOL, env.ODIN_SIGNTOOL, env.ODIN_SIGNTOOL,
      'powershell.exe'])
    expect(recovered.waits).toEqual([15000, 30000])
    const broken = runner([1])
    const failing = signer(env, broken.run)
    await expect(failing.sign({ path: files.installer })).rejects.toThrow('SignTool failed 3 times')
    expect(broken.calls).toHaveLength(3)  // no signature check of an unsigned file
  })
})
