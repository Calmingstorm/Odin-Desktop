// Chooses the app's platform once: Linux, Windows or macOS. Other systems are refused before any profile work.
import type { AppPlatform } from './contracts'
import { linuxPlatform } from './linux'
import { macosPlatform } from './macos'
import { windowsPlatform } from './windows'

export type { AppPlatform } from './contracts'

export function currentPlatform(system: NodeJS.Platform = process.platform): AppPlatform {
  if (system === 'linux') return linuxPlatform
  if (system === 'win32') return windowsPlatform
  if (system === 'darwin') return macosPlatform
  throw new Error('Odin Desktop runs on Linux, Windows and macOS only')
}
