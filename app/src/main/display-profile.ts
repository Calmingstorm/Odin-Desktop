// Your name and picture in chat, and a picture per personality. Display only: none of it reaches Odin's prompt.
// Kept in the profile's config folder as owner-only files: profile.json, user.png and personality-<key>.png.
import { randomBytes } from 'node:crypto'
import { lstatSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import type { DisplayPictureTarget, DisplayProfile } from '../shared/api'

export const MAX_NAME_CHARS = 40
/** A personality key is at most this many UTF-8 bytes, so its file name stays well under 255 bytes. */
export const MAX_KEY_BYTES = 100
export const PICTURE_SIZE = 256
export const MAX_PICTURE_BYTES = 512 * 1024

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
const PERSONALITY_FILE = /^personality-((?:[0-9a-f]{2})+)\.png$/

/** A refusal the person can act on; its message is shown as is. */
export class DisplayProfileError extends Error {}

/** A 256 x 256 PNG of at most 512 KB, by its signature and header. The window decodes it in its sandbox. */
export function validPicture(bytes: Buffer): boolean {
  return bytes.length > 24 && bytes.length <= MAX_PICTURE_BYTES &&
    bytes.subarray(0, 8).equals(PNG_SIGNATURE) && bytes.toString('latin1', 12, 16) === 'IHDR' &&
    bytes.readUInt32BE(16) === PICTURE_SIZE && bytes.readUInt32BE(20) === PICTURE_SIZE
}

function pictureFile(target: DisplayPictureTarget): string {
  if (target.target === 'user') return 'user.png'
  const key = Buffer.from(target.key, 'utf8')
  if (!target.key || key.length > MAX_KEY_BYTES) throw new DisplayProfileError('That personality name is too long for a picture.')
  return `personality-${key.toString('hex')}.png`
}

export class DisplayProfileStore {
  constructor(private readonly dir: string) {}

  /** What chat shows. A missing, unsafe or damaged file reads as not set. */
  read(): DisplayProfile {
    const empty: DisplayProfile = { name: '', user: null, personalities: {} }
    if (!this.privateFolder()) return empty
    const personalities: Record<string, string> = {}
    for (const entry of readdirSync(this.dir)) {
      const match = PERSONALITY_FILE.exec(entry)
      const picture = match ? this.picture(entry) : null
      if (match && picture) personalities[Buffer.from(match[1]!, 'hex').toString('utf8')] = picture
    }
    return { name: this.name(), user: this.picture('user.png'), personalities }
  }

  /** An empty name shows as "You" again. */
  setName(name: string): DisplayProfile {
    const value = name.trim()
    if (value.length > MAX_NAME_CHARS || /[\u0000-\u001f\u007f]/.test(value)) {
      throw new DisplayProfileError(`Use up to ${MAX_NAME_CHARS} characters on one line.`)
    }
    this.write('profile.json', Buffer.from(JSON.stringify({ name: value })))
    return this.read()
  }

  setPicture(target: DisplayPictureTarget, pngBase64: string): DisplayProfile {
    const bytes = Buffer.from(pngBase64, 'base64')
    if (!validPicture(bytes)) throw new DisplayProfileError('That picture could not be used. Choose a PNG, JPEG or WebP picture.')
    this.write(pictureFile(target), bytes)
    return this.read()
  }

  removePicture(target: DisplayPictureTarget): DisplayProfile {
    const file = pictureFile(target)
    if (this.privateFolder()) rmSync(join(this.dir, file), { force: true })
    return this.read()
  }

  /** The folder, when it is a real directory this user owns with no group or other access. Never a link. */
  private privateFolder(): boolean {
    try {
      const info = lstatSync(this.dir)
      return info.isDirectory() && info.uid === process.getuid?.() && (info.mode & 0o077) === 0
    } catch {
      return false
    }
  }

  private write(file: string, bytes: Buffer): void {
    try {
      mkdirSync(this.dir, { mode: 0o700 })
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error
    }
    if (!this.privateFolder()) throw new DisplayProfileError('The pictures folder is not private, so nothing was saved.')
    const temporary = join(this.dir, `.${file}.${randomBytes(6).toString('hex')}.tmp`)
    writeFileSync(temporary, bytes, { mode: 0o600, flag: 'wx' })
    try {
      renameSync(temporary, join(this.dir, file))
    } catch (error) {
      rmSync(temporary, { force: true })
      throw error
    }
  }

  private name(): string {
    try {
      const data: unknown = JSON.parse(readFileSync(join(this.dir, 'profile.json'), 'utf8'))
      const name = data && typeof data === 'object' ? (data as { name?: unknown }).name : undefined
      return typeof name === 'string' && name.length <= MAX_NAME_CHARS && !/[\u0000-\u001f\u007f]/.test(name) ? name : ''
    } catch {
      return ''
    }
  }

  private picture(file: string): string | null {
    try {
      if (!lstatSync(join(this.dir, file)).isFile()) return null
      const bytes = readFileSync(join(this.dir, file))
      return validPicture(bytes) ? `data:image/png;base64,${bytes.toString('base64')}` : null
    } catch {
      return null
    }
  }
}
