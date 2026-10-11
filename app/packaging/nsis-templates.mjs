// electron-builder 26.0.12's NSIS templates with Odin's pinned changes (packaging/nsis), in place for one Windows build:
// - installer.nsi runs preInit before .onInit's SetOutPath, so the installer's refusals come before any folder exists;
// - multiUser.nsh fixes the per-user folder (no crashing known-folder read, no record elsewhere followed).
// Selecting a replacement installer.nsi through nsis.script instead would make electron-builder skip generating (and
// later signing) the separate uninstaller. Each template must be the pinned one before it's replaced, and the
// originals come back afterwards, however the build ends. app/test/windows-build.test.ts pins the copies.
import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

export const PINNED_TEMPLATES = {
  'installer.nsi': '468de2e9587b9036b3b025719c2843745d5224758851b04a56d95d90ed768b6e',
  'multiUser.nsh': 'afa9046492317e72e79e022cdb1f42edba4687ea605300bfc01c002f3106201c'
}

const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex')

/** Runs `build` with the templates in `templates` replaced by the copies in `replacements`, then restores them. */
export function withPinnedTemplates(templates, replacements, build) {
  const originals = new Map()
  for (const [name, digest] of Object.entries(PINNED_TEMPLATES)) {
    const path = join(templates, name)
    const bytes = readFileSync(path)
    if (sha256(bytes) !== digest) {
      throw new Error(`electron-builder's ${name} isn't the pinned 26.0.12 template; review packaging/nsis first`)
    }
    originals.set(path, bytes)
  }
  try {
    for (const name of Object.keys(PINNED_TEMPLATES)) {
      writeFileSync(join(templates, name), readFileSync(join(replacements, name)))
    }
    return build()
  } finally {
    for (const [path, bytes] of originals) writeFileSync(path, bytes)
  }
}
