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
type Names = { productName: string; productFilename: string }
const { AppInfo } = require('app-builder-lib/out/appInfo') as {
  AppInfo: new (info: { config: Config; metadata: Config }, buildVersion: null, platform: Config | null) => Names
}
const { getWindowsInstallationDirName } = require('app-builder-lib/out/targets/targetUtil') as {
  getWindowsInstallationDirName(appInfo: Names, tryProductName: boolean): string
}
// The names electron-builder derives, with extraMetadata merged into the package as its packager does.
function names(config: Config, platform: Config | null): Names {
  const metadata = { ...JSON.parse(readFileSync(join(APP, 'package.json'), 'utf8')), ...config.extraMetadata }
  return new AppInfo({ config, metadata }, null, platform)
}
const sha256 = (path: string): string => createHash('sha256').update(readFileSync(path)).digest('hex')

describe('the Windows build configuration', () => {
  it('selects its own construction hook, product name and per-user installer, from the shared resources', async () => {
    const windows = await getConfig(APP, 'electron-builder.windows.yml', null)
    const shared = await getConfig(APP, null, null)
    expect(windows.afterPack).toBe('packaging/after-pack-windows.cjs')
    const installed = names(windows, windows.win)
    expect(installed.productName).toBe('Odin')  // Apps, the shortcut and the executable's description
    expect(installed.productFilename).toBe('Odin')  // Odin.exe
    // A per-user one-click installer's folder: %LOCALAPPDATA%\Programs\Odin.
    expect(getWindowsInstallationDirName(installed, windows.nsis.oneClick === false)).toBe('Odin')
    expect(windows.appId).toBe(shared.appId)  // the AppUserModelID the app sets for itself
    expect(windows.extraResources).toEqual(shared.extraResources)
    expect(windows.win).toMatchObject({ target: [{ target: 'nsis', arch: ['x64'] }],
      artifactName: 'odin-desktop-${version}-candidate-x64-setup.${ext}' })
    // Signing goes through the release build's own hook, never electron-builder's certificate lookup.
    expect(windows.win.signtoolOptions).toEqual({ sign: 'packaging/sign-windows.cjs', signingHashAlgorithms: ['sha256'] })
    expect(windows.nsis).toEqual({ oneClick: true, perMachine: false, runAfterFinish: false,
      createDesktopShortcut: false, createStartMenuShortcut: true, shortcutName: 'Odin', uninstallDisplayName: 'Odin',
      menuCategory: false, deleteAppDataOnUninstall: false, packElevateHelper: false,
      include: 'packaging/installer.nsh' })
    await validateConfiguration(windows, new DebugLogger(false))  // electron-builder's own schema check
  })

  it('carries electron-builder 26.0.12\'s installer script and per-user folder with only Odin\'s named changes', () => {
    const builder = JSON.parse(readFileSync(join(APP, 'node_modules/app-builder-lib/package.json'), 'utf8'))
    expect(builder.version).toBe('26.0.12')
    const template = (name: string): string =>
      readFileSync(join(APP, 'node_modules/app-builder-lib/templates/nsis', name), 'utf8')
    const ours = (name: string): string => readFileSync(join(APP, 'packaging/nsis', name), 'utf8')
    const change = (text: string, from: string, to: string): string => {
      expect(text.split(from)).toHaveLength(2)  // each change applies to exactly one place
      return text.replace(from, to)
    }
    const preInit = '  !ifmacrodef preInit\n    !insertmacro preInit\n  !endif\n'
    const setOutPath = '  SetOutPath $INSTDIR\n  ${LogSet} on\n'
    const installer = change(template('installer.nsi'), `${setOutPath}\n${preInit}`, `${preInit}\n${setOutPath}`)
    expect(ours('installer.nsi')).toBe(
      '; Odin for Windows: electron-builder 26.0.12\'s templates/nsis/installer.nsi with one change, written over the\n'
      + '; template for the Windows build (packaging/nsis-templates.mjs) and pinned by app/test/windows-build.test.ts:\n'
      + '; preInit runs before .onInit\'s SetOutPath, so its refusals come before any folder exists (SetOutPath would\n'
      + '; create a /D destination).\n' + installer)
    const users = template('multiUser.nsh')
    const start = users.indexOf('    # \u0441hecks registry for previous installation path')
    const end = users.indexOf('    # allow /D switch to override installation path')
    expect(start).toBeGreaterThan(0)
    expect(end).toBeGreaterThan(start)
    const ourUsers = ours('multiUser.nsh')
    const header = '; Odin for Windows: electron-builder 26.0.12\'s templates/nsis/multiUser.nsh with one change, written over the\n'
      + '; template for the Windows build (packaging/nsis-templates.mjs) and pinned by app/test/windows-build.test.ts:\n'
      + '; the per-user folder is fixed (see setInstallModePerUser).\n'
    expect(ourUsers.startsWith(header + users.slice(0, start))).toBe(true)
    expect(ourUsers.endsWith(users.slice(end))).toBe(true)
    // The one changed block: a fixed folder, a record elsewhere refused by the installer, followed by the uninstaller.
    const block = ourUsers.slice(header.length + start, ourUsers.length - (users.length - end))
    expect(block).toContain('StrCpy $INSTDIR "$LocalAppData\\Programs\\${APP_FILENAME}"')
    expect(block).toContain('!insertmacro odinRefuse')
    expect(block).not.toMatch(/System::Call[^\n]*SHGetKnownFolderPath/)
  })

  it('writes the copies over the pinned templates for one build only, refusing any other template', async () => {
    const { withPinnedTemplates } = await import('../packaging/nsis-templates.mjs')
    const templates = mkdtempSync(join(tmpdir(), 'odin-nsis-templates-'))
    try {
      for (const name of ['installer.nsi', 'multiUser.nsh']) {
        writeFileSync(join(templates, name), readFileSync(join(APP, 'node_modules/app-builder-lib/templates/nsis', name)))
      }
      const original = readFileSync(join(templates, 'installer.nsi'), 'utf8')
      const seen = withPinnedTemplates(templates, join(APP, 'packaging/nsis'),
        () => readFileSync(join(templates, 'installer.nsi'), 'utf8'))
      expect(seen).toBe(readFileSync(join(APP, 'packaging/nsis/installer.nsi'), 'utf8'))
      expect(readFileSync(join(templates, 'installer.nsi'), 'utf8')).toBe(original)
      expect(() => withPinnedTemplates(templates, join(APP, 'packaging/nsis'), () => { throw new Error('build failed') }))
        .toThrow('build failed')
      expect(readFileSync(join(templates, 'installer.nsi'), 'utf8')).toBe(original)  // restored after a failure too
      writeFileSync(join(templates, 'multiUser.nsh'), 'not the pinned template')
      expect(() => withPinnedTemplates(templates, join(APP, 'packaging/nsis'), () => 'built'))
        .toThrow('isn\'t the pinned 26.0.12 template')
      expect(readFileSync(join(templates, 'installer.nsi'), 'utf8')).toBe(original)  // nothing was replaced
    } finally {
      rmSync(templates, { recursive: true, force: true })
    }
  })

  it('leaves the Linux build as it was', async () => {
    const shared = await getConfig(APP, null, null)
    expect(shared.afterPack).toBe('packaging/after-pack.cjs')
    expect(names(shared, shared.linux)).toMatchObject({ productName: 'odin-desktop', productFilename: 'odin-desktop' })
    expect(shared.extraMetadata).toBeUndefined()
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
