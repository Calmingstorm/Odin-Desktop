// Your name and picture in chat, and a picture per personality. Display only: none of it reaches Odin's prompt.
// Kept in the profile's config folder as owner-only files: profile.json, user.png and personality-<key>.png.
import { randomBytes } from 'node:crypto'
import { closeSync, constants, fstatSync, lstatSync, mkdirSync, openSync, readdirSync, readFileSync, renameSync, rmSync,
  writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { crc32, inflateSync } from 'node:zlib'
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

/** A complete 256 x 256 PNG of at most 512 KB, as the window's canvas writes it: 8-bit truecolour, with or without
 * alpha, not interlaced. Every chunk's CRC matches, the image data inflates to exactly its rows, each row has a valid
 * filter, and nothing follows IEND. A truncated or damaged file is not a picture. */
export function validPicture(bytes: Buffer): boolean {
  if (bytes.length > MAX_PICTURE_BYTES || bytes.length < 8 || !bytes.subarray(0, 8).equals(PNG_SIGNATURE)) return false
  const data: Buffer[] = []
  let bytesPerPixel = 0
  let offset = 8
  for (let index = 0; offset + 12 <= bytes.length; index++) {
    const length = bytes.readUInt32BE(offset)
    const type = bytes.toString('latin1', offset + 4, offset + 8)
    const end = offset + 12 + length
    if (end > bytes.length || bytes.readUInt32BE(end - 4) !== crc32(bytes.subarray(offset + 4, end - 4))) return false
    const body = bytes.subarray(offset + 8, end - 4)
    if (index === 0) {
      if (type !== 'IHDR' || length !== 13) return false
      // Bytes per pixel for the 8-bit colour types a canvas writes: truecolour (2) and with alpha (6).
      bytesPerPixel = body[9] === 2 ? 3 : body[9] === 6 ? 4 : 0
      if (body.readUInt32BE(0) !== PICTURE_SIZE || body.readUInt32BE(4) !== PICTURE_SIZE || body[8] !== 8 ||
          !bytesPerPixel || body[10] !== 0 || body[11] !== 0 || body[12] !== 0) return false
    } else if (type === 'IHDR') {
      return false
    } else if (type === 'IDAT') {
      data.push(body)
    } else if (type === 'IEND') {
      if (end !== bytes.length || !data.length) return false
      const row = 1 + PICTURE_SIZE * bytesPerPixel
      let pixels: Buffer
      try {
        pixels = inflateSync(Buffer.concat(data), { maxOutputLength: row * PICTURE_SIZE + 1 })
      } catch {
        return false
      }
      if (pixels.length !== row * PICTURE_SIZE) return false
      for (let start = 0; start < pixels.length; start += row) if (pixels[start]! > 4) return false
      return true
    }
    offset = end
  }
  return false
}

function pictureFile(target: DisplayPictureTarget): string {
  if (target.target === 'user') return 'user.png'
  const key = Buffer.from(target.key, 'utf8')
  if (!target.key || key.length > MAX_KEY_BYTES) throw new DisplayProfileError('That personality name is too long for a picture.')
  return `personality-${key.toString('hex')}.png`
}

export class DisplayProfileStore {
  constructor(private readonly dir: string) {}

  /** What chat shows. A missing, unsafe or damaged file reads as not set. Personality pictures are a list, so no
   * preset key (such as `__proto__`) can meet an object's own machinery on either side of the bridge. */
  read(): DisplayProfile {
    if (!this.privateFolder()) return { name: '', user: null, personalities: [] }
    const personalities: DisplayProfile['personalities'] = []
    for (const entry of readdirSync(this.dir).sort()) {
      const match = PERSONALITY_FILE.exec(entry)
      const picture = match ? this.picture(entry) : null
      if (match && picture) personalities.push({ key: Buffer.from(match[1]!, 'hex').toString('utf8'), picture })
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

  /** Removing from a folder that exists but is not private is refused, never reported as done: the picture would come
   * back once the folder is private again. */
  removePicture(target: DisplayPictureTarget): DisplayProfile {
    const file = pictureFile(target)
    if (this.privateFolder()) rmSync(join(this.dir, file), { force: true })
    else if (this.present()) throw new DisplayProfileError('The pictures folder is not private, so nothing was removed.')
    return this.read()
  }

  private present(): boolean {
    try {
      lstatSync(this.dir)
      return true
    } catch {
      return false
    }
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

  /** A regular file's bytes, opened without following a link; null for anything else. Non-blocking, so a FIFO or other
   * special file opens at once instead of waiting for a writer on the main thread, and the descriptor check refuses it.
   * A regular file reads the same either way. */
  private readFile(file: string): Buffer | null {
    let descriptor: number | undefined
    try {
      descriptor = openSync(join(this.dir, file), constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK)
      const info = fstatSync(descriptor)
      return info.isFile() && info.size <= MAX_PICTURE_BYTES ? readFileSync(descriptor) : null
    } catch {
      return null
    } finally {
      if (descriptor !== undefined) closeSync(descriptor)
    }
  }

  private name(): string {
    try {
      const bytes = this.readFile('profile.json')
      const data: unknown = bytes ? JSON.parse(bytes.toString('utf8')) : null
      const name = data && typeof data === 'object' ? (data as { name?: unknown }).name : undefined
      return typeof name === 'string' && name.length <= MAX_NAME_CHARS && !/[\u0000-\u001f\u007f]/.test(name) ? name : ''
    } catch {
      return ''
    }
  }

  private picture(file: string): string | null {
    const bytes = this.readFile(file)
    return bytes && validPicture(bytes) ? `data:image/png;base64,${bytes.toString('base64')}` : null
  }
}
