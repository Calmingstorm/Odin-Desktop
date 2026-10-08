import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { describe, expect, it } from 'vitest'

const require = createRequire(import.meta.url)
const { load } = require('js-yaml')
const { AppInfo } = require('app-builder-lib/out/appInfo')
const { LinuxTargetHelper } = require('app-builder-lib/out/targets/LinuxTargetHelper')
const { default: AppImageTarget } = require('app-builder-lib/out/targets/AppImageTarget')

function builder() {
  // Feed actual configuration data to electron-builder's real entry generators.
  // No package build, installer, graphical session or /opt access is involved.
  const config = load(readFileSync(new URL('../electron-builder.yml', import.meta.url), 'utf8'))
  const metadata = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))
  const packager = {
    config, appInfo: new AppInfo({ config, metadata }, undefined, config.linux),
    executableName: config.executableName, platformSpecificBuildOptions: config.linux,
    fileAssociations: []
  }
  return { config, metadata, packager, helper: new LinuxTargetHelper(packager) }
}

describe('packaged desktop identity', () => {
  it('uses the independent install directory but keeps the deb launcher name Odin', async () => {
    const { config, metadata, packager, helper } = builder()
    expect(metadata.productName).toBe('odin-desktop')
    expect(packager.appInfo.sanitizedProductName).toBe('odin-desktop')
    const desktop = await helper.computeDesktopEntry({ ...config.linux, ...config.deb })
    expect(desktop).toContain('\nName=Odin\n')
    expect(desktop).toContain('\nExec=/opt/odin-desktop/odin-desktop %U\n')
    expect(desktop).toContain('\nStartupWMClass=odin-desktop\n')
    expect(desktop).toContain('\n[Desktop Action exit]\nName=Exit Odin\n')
  })

  it('keeps the generated AppImage desktop name Odin rather than the install productName', async () => {
    const { packager, helper } = builder()
    const target = new AppImageTarget('AppImage', packager, helper, '/temporary/output')
    const desktop = await target.desktopEntry.value
    expect(desktop).toContain('\nName=Odin\n')
    expect(desktop).toContain('\nExec=AppRun ')
    expect(desktop).not.toContain('/opt/')
    expect(desktop).toContain('\nStartupWMClass=odin-desktop\n')
    expect(desktop).toContain('\n[Desktop Action exit]\nName=Exit Odin\n')
  })
})
