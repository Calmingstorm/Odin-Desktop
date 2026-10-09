// Your name and picture in chat, and a picture per personality. Display only: Odin never sees them.
import { reactive } from 'vue'
import type { DisplayPictureTarget, DisplayProfile, Result } from '../../../shared/api'
import { activePersonality } from '../assistant-name'

export const ACCEPTED_PICTURES = ['image/png', 'image/jpeg', 'image/webp']
export const MAX_PICTURE_INPUT_BYTES = 2 * 1024 * 1024
export const PICTURE_SIZE = 256

export const displayProfile = reactive({
  name: '',
  user: null as string | null,
  personalities: {} as Record<string, string>,
  loaded: false
})

let loading: Promise<void> | null = null

/** Applies a profile the app returned; otherwise the message to show where the change was made. */
function settle(result: Result<DisplayProfile>): string | null {
  if (!result.ok) return result.error.message
  displayProfile.name = result.result.name
  displayProfile.user = result.result.user
  displayProfile.personalities = { ...result.result.personalities }
  displayProfile.loaded = true
  return null
}

/** Loads once; later calls share it. A failed load is tried again by the next call. A page without the app's bridge
 * (a preview or test page) keeps the defaults. */
export function loadDisplayProfile(): Promise<void> {
  if (typeof window === 'undefined' || typeof window.odin?.getDisplayProfile !== 'function') return Promise.resolve()
  loading ??= window.odin.getDisplayProfile().then((result) => {
    if (settle(result) !== null) loading = null
  }, () => {
    loading = null
  })
  return loading
}

/** Your name in chat, or "You". */
export function userName(): string {
  return displayProfile.name || 'You'
}

export function userPicture(): string | null {
  return displayProfile.user
}

/** The active personality's picture, or null for the default Odin mark. */
export function personalityPicture(key: string | undefined = activePersonality.value?.preset): string | null {
  return key ? displayProfile.personalities[key] ?? null : null
}

/** Null when saved; otherwise why not. */
export async function saveDisplayName(name: string): Promise<string | null> {
  return settle(await window.odin.setDisplayName(name))
}

/** The centred square of a picture, so a portrait or landscape picture fills the round avatar. */
export function squareCrop(width: number, height: number): { x: number; y: number; side: number } {
  const side = Math.min(width, height)
  return { x: Math.floor((width - side) / 2), y: Math.floor((height - side) / 2), side }
}

/** A PNG, JPEG or WebP picture up to 2 MB, as a 256 x 256 PNG in base64. Throws a message the person can act on. */
export async function squarePicture(file: Blob): Promise<string> {
  if (!ACCEPTED_PICTURES.includes(file.type)) throw new Error('Choose a PNG, JPEG or WebP picture.')
  if (file.size > MAX_PICTURE_INPUT_BYTES) throw new Error('Choose a picture up to 2 MB.')
  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(file)
  } catch {
    throw new Error('That picture could not be read.')
  }
  try {
    const crop = squareCrop(bitmap.width, bitmap.height)
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = PICTURE_SIZE
    const context = canvas.getContext('2d')
    if (!context) throw new Error('That picture could not be read.')
    context.drawImage(bitmap, crop.x, crop.y, crop.side, crop.side, 0, 0, PICTURE_SIZE, PICTURE_SIZE)
    const png = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
    if (!png) throw new Error('That picture could not be read.')
    return base64(new Uint8Array(await png.arrayBuffer()))
  } finally {
    bitmap.close()
  }
}

export function base64(bytes: Uint8Array): string {
  let text = ''
  for (let start = 0; start < bytes.length; start += 0x8000) {
    text += String.fromCharCode(...bytes.subarray(start, start + 0x8000))
  }
  return btoa(text)
}

/** Null when saved; otherwise why not. */
export async function saveDisplayPicture(target: DisplayPictureTarget, file: Blob): Promise<string | null> {
  let png: string
  try {
    png = await squarePicture(file)
  } catch (error) {
    return (error as Error).message
  }
  return settle(await window.odin.setDisplayPicture(target, png))
}

/** Null when removed; otherwise why not. */
export async function removeDisplayPicture(target: DisplayPictureTarget): Promise<string | null> {
  return settle(await window.odin.removeDisplayPicture(target))
}
