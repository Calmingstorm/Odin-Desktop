// Chooses the app's platform once: Linux, or Windows from a source checkout. Other systems are refused before any
// profile work.
import type { AppPlatform } from './contracts'
import { linuxPlatform } from './linux'
import { windowsPlatform } from './windows'

export type { AppPlatform } from './contracts'

export function currentPlatform(system: NodeJS.Platform = process.platform): AppPlatform {
  if (system === 'linux') return linuxPlatform
  if (system === 'win32') return windowsPlatform
  throw new Error('Odin Desktop runs on Linux and Windows only')
}
