// The Windows candidate build (phase 4, P7 and P8), through the configuration packaging/build-windows.mjs selects,
// as electron-builder itself loads it, and the construction hook that configuration names, run on a Windows tree.
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

const require = createRequire(import.meta.url)
const APP = resolve(__dirname, '..')
type Config = Record<string, any>
const { getConfig, validateConfiguration } = require('app-builder-lib/out/util/config/config') as {
  getConfig(projectDir: string, configPath: string | null, options: null): Promise<Config>
  validateConfiguration(config: Config, debugLogger: unknown): Promise<void>
}
const { DebugLogger } = require('builder-util') as { DebugLogger: new (enabled: boolean) => unknown }
const sha256 = (path: string): string => createHash('sha256').update(readFileSync(path)).digest('hex')

describe('the Windows build configuration', () => {
  it('selects its own construction hook, product name and per-user installer, from the shared resources', async () => {
    const windows = await getConfig(APP, 'electron-builder.windows.yml', null)
    const shared = await getConfig(APP, null, null)
    expect(windows.afterPack).toBe('packaging/after-pack-windows.cjs')
    expect(windows.productName).toBe('Odin')
    expect(windows.appId).toBe(shared.appId)  // the AppUserModelID the app sets for itself
    expect(windows.extraResources).toEqual(shared.extraResources)
    expect(windows.win).toMatchObject({ target: [{ target: 'nsis', arch: ['x64'] }],
      artifactName: 'odin-desktop-${version}-candidate-x64-setup.${ext}' })
    expect(windows.nsis).toEqual({ oneClick: true, perMachine: false, runAfterFinish: false,
      createDesktopShortcut: false, createStartMenuShortcut: true, shortcutName: 'Odin', uninstallDisplayName: 'Odin',
      menuCategory: false, deleteAppDataOnUninstall: false, include: 'packaging/installer.nsh' })
    await validateConfiguration(windows, new DebugLogger(false))  // electron-builder's own schema check
  })

  it('leaves the Linux build as it was', async () => {
    const shared = await getConfig(APP, null, null)
    expect(shared.afterPack).toBe('packaging/after-pack.cjs')
    expect(shared.productName).toBe('odin-desktop')
    expect(shared.executableName).toBe('odin-desktop')
    expect(shared.win).toBeUndefined()
    expect(shared.nsis).toBeUndefined()
    expect(shared.linux.target).toEqual([{ target: 'deb', arch: ['x64'] }, { target: 'AppImage', arch: ['x64'] }])
  })
})

describe('the selected Windows construction hook', () => {
  const roots: string[] = []
  const saved = process.env.ODIN_BUILD_PYTHON
  afterEach(() => {
    for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true })
    if (saved === undefined) delete process.env.ODIN_BUILD_PYTHON
    else process.env.ODIN_BUILD_PYTHON = saved
  })

  // electron-builder's unpacked Windows app: Odin.exe beside resources, with the staged Windows runtime.
  function unpacked(): { appOutDir: string; resources: string; executable: string } {
    const appOutDir = mkdtempSync(join(tmpdir(), 'odin-win-unpacked-'))
    roots.push(appOutDir)
    const resources = join(appOutDir, 'resources')
    mkdirSync(join(resources, 'runtime', 'python'), { recursive: true })
    mkdirSync(join(resources, 'legal'))
    writeFileSync(join(appOutDir, 'Odin.exe'), 'MZ fixture executable')
    writeFileSync(join(resources, 'app.asar'), 'asar fixture')
    writeFileSync(join(resources, 'runtime', 'python', 'python.exe'), 'MZ fixture interpreter')
    writeFileSync(join(resources, 'legal', 'NOTICE.txt'), 'notice')
    writeFileSync(join(resources, 'bundle-manifest.json'), JSON.stringify({ schema: 1, platform: 'win32',
      source: { mode: 'worktree', immutable: false }, files: [] }))
    return { appOutDir, resources, executable: join(appOutDir, 'Odin.exe') }
  }
  const hook = async (): Promise<(context: unknown) => Promise<void>> =>
    require(join(APP, (await getConfig(APP, 'electron-builder.windows.yml', null)).afterPack))
  const context = (appOutDir: string, platform = 'win32') => ({ appOutDir, electronPlatformName: platform,
    packager: { appInfo: { productFilename: 'Odin' } } })

  it('copies the guardian and seals the resources, leaving Electron\'s executable as the app', async () => {
    const tree = unpacked()
    process.env.ODIN_BUILD_PYTHON = process.env.ODIN_ENGINE_PYTHON ?? 'python3'
    await (await hook())(context(tree.appOutDir))
    expect(readFileSync(join(tree.resources, 'ownership.py'))).toEqual(readFileSync(join(APP, 'packaging', 'ownership.py')))
    expect(readFileSync(tree.executable, 'utf8')).toBe('MZ fixture executable')  // no launcher in its place
    expect(readdirSync(tree.appOutDir).sort()).toEqual(['Odin.exe', 'resources'])
    const manifest = JSON.parse(readFileSync(join(tree.resources, 'bundle-manifest.json'), 'utf8'))
    expect(manifest.files.map((item: { path: string }) => item.path)).toEqual(
      ['app.asar', 'legal/NOTICE.txt', 'ownership.py', 'runtime/python/python.exe'])
    const guardian = manifest.files.find((item: { path: string }) => item.path === 'ownership.py')
    expect(guardian.sha256).toBe(sha256(join(APP, 'packaging', 'ownership.py')))
  })

  it('refuses outside build-windows.mjs, for another platform, or without Windows\' executable', async () => {
    const run = await hook()
    const tree = unpacked()
    delete process.env.ODIN_BUILD_PYTHON
    await expect(run(context(tree.appOutDir))).rejects.toThrow('built by packaging/build-windows.mjs')
    process.env.ODIN_BUILD_PYTHON = 'python3'
    await expect(run(context(tree.appOutDir, 'linux'))).rejects.toThrow('builds Windows only')
    rmSync(tree.executable)
    await expect(run(context(tree.appOutDir))).rejects.toThrow()
    expect(existsSync(join(tree.resources, 'ownership.py'))).toBe(false)  // refused before writing
  })
})
