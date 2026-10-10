// Chooses the app's platform once. Only Linux is implemented; other systems are refused before any profile work.
import type { AppPlatform } from './contracts'
import { linuxPlatform } from './linux'

export type { AppPlatform } from './contracts'

export function currentPlatform(system: NodeJS.Platform = process.platform): AppPlatform {
  if (system === 'linux') return linuxPlatform
  throw new Error('Odin Desktop runs on Linux only')
}
