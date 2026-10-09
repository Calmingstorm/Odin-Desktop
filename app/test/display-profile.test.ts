import { execFileSync, spawnSync } from 'node:child_process'
import { chmodSync, mkdirSync, mkdtempSync, readdirSync, rmSync, statSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { crc32, deflateSync } from 'node:zlib'
import { buildSync } from 'esbuild'
import { afterEach, describe, expect, it } from 'vitest'
import { DisplayProfileError, DisplayProfileStore, MAX_PICTURE_BYTES, validPicture } from '../src/main/display-profile'

const dirs: string[] = []
afterEach(() => {
  for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true })
})

function root(): string {
  const dir = mkdtempSync(join(tmpdir(), 'odin-display-'))
  dirs.push(dir)
  return dir
}

const SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])

function chunk(type: string, data: Buffer): Buffer {
  const length = Buffer.alloc(4)
  length.writeUInt32BE(data.length)
  const body = Buffer.concat([Buffer.from(type, 'latin1'), data])
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(body))
  return Buffer.concat([length, body, crc])
}

interface PngOptions {
  width?: number; height?: number; rows?: number; colorType?: number; bitDepth?: number; interlace?: number
  filter?: number; shade?: number; extra?: Buffer
}

/** A genuinely decodable PNG, as a canvas writes one: 8-bit RGBA (or RGB), not interlaced, filter-0 rows. */
function png(options: PngOptions = {}): Buffer {
  const { width = 256, height = 256, colorType = 6, bitDepth = 8, interlace = 0, filter = 0, shade = 0 } = options
  const rows = options.rows ?? height
  const extra: Buffer = options.extra ?? Buffer.alloc(0)
  const header = Buffer.alloc(13)
  header.writeUInt32BE(width, 0)
  header.writeUInt32BE(height, 4)
  Object.assign(header, { 8: bitDepth, 9: colorType, 12: interlace })
  const row = 1 + width * (colorType === 2 ? 3 : 4)
  const pixels = Buffer.alloc(row * rows, shade)
  for (let y = 0; y < rows; y++) pixels[y * row] = filter
  return Buffer.concat([SIGNATURE, chunk('IHDR', header), extra, chunk('IDAT', deflateSync(pixels)), chunk('IEND', Buffer.alloc(0))])
}

const user = { target: 'user' } as const
const personality = (key: string) => ({ target: 'personality', key }) as const
const keys = (profile: { personalities: Array<{ key: string }> }) => profile.personalities.map(({ key }) => key)

describe('picture validation', () => {
  it('accepts a complete 256 x 256 PNG as a canvas writes it, RGBA or RGB', () => {
    expect(validPicture(png())).toBe(true)
    expect(validPicture(png({ colorType: 2 }))).toBe(true)
    expect(validPicture(png({ extra: chunk('tEXt', Buffer.from('Software\0canvas')) }))).toBe(true)
  })

  it('refuses a truncated, damaged or different picture', () => {
    const good = png()
    const flipped = Buffer.from(good)
    flipped.writeUInt8(flipped.readUInt8(good.length - 20) ^ 0xff, good.length - 20)  // inside IDAT: its CRC no longer matches
    const notIhdr = Buffer.concat([SIGNATURE, chunk('IDAT', Buffer.alloc(13)), good.subarray(8)])
    const twoHeaders = Buffer.concat([good.subarray(0, 33), good.subarray(8, 33), good.subarray(33)])
    const noData = Buffer.concat([good.subarray(0, 33), chunk('IEND', Buffer.alloc(0))])
    // Every chunk intact, but the image data is not a zlib stream.
    const notDeflated = Buffer.concat([good.subarray(0, 33), chunk('IDAT', Buffer.from('not image data')), chunk('IEND', Buffer.alloc(0))])
    const wrongSignature = Buffer.from(good)
    wrongSignature[0] = 0
    const damaged: Buffer[] = [
      good.subarray(0, good.length - 5), good.subarray(0, 40), good.subarray(0, 25), Buffer.alloc(10),
      Buffer.concat([good, Buffer.from('after the end')]), flipped, notIhdr, twoHeaders, noData, notDeflated, wrongSignature,
      png({ width: 128, height: 128 }), png({ height: 255 }), png({ rows: 255 }), png({ bitDepth: 16 }),
      png({ interlace: 1 }), png({ colorType: 3 }), png({ filter: 5 }),
      png({ extra: chunk('tEXt', Buffer.alloc(MAX_PICTURE_BYTES)) })
    ]
    for (const bytes of damaged) expect(validPicture(bytes)).toBe(false)
  })
})

describe('display profile store', () => {
  it('keeps your name, your picture and a picture per personality in owner-only files across a restart', () => {
    const dir = join(root(), 'display-profile')
    const store = new DisplayProfileStore(dir)
    expect(store.read()).toEqual({ name: '', user: null, personalities: [] })
    store.setName('  Aaron  ')
    store.setPicture(user, png().toString('base64'))
    const saved = store.setPicture(personality('clippy-astra'), png({ shade: 9 }).toString('base64'))
    expect(saved.name).toBe('Aaron')
    expect(saved.user).toBe(`data:image/png;base64,${png().toString('base64')}`)
    expect(saved.personalities).toEqual([{ key: 'clippy-astra', picture: `data:image/png;base64,${png({ shade: 9 }).toString('base64')}` }])
    expect(new DisplayProfileStore(dir).read()).toEqual(saved)
    expect(statSync(dir).mode & 0o777).toBe(0o700)
    for (const file of readdirSync(dir)) expect(statSync(join(dir, file)).mode & 0o777).toBe(0o600)
    expect(readdirSync(dir).some((file) => file.endsWith('.tmp'))).toBe(false)
  })

  it('stores any preset key under a hex file name, never as a path', () => {
    const dir = join(root(), 'display-profile')
    const store = new DisplayProfileStore(dir)
    const key = 'Clippy/../x ✓'
    expect(keys(store.setPicture(personality(key), png().toString('base64')))).toEqual([key])
    expect(readdirSync(dir)).toEqual([`personality-${Buffer.from(key).toString('hex')}.png`])
    expect(() => store.setPicture(personality('k'.repeat(101)), png().toString('base64'))).toThrow(DisplayProfileError)
  })

  it('keeps pictures for preset keys such as __proto__ and constructor, across a restart', () => {
    const dir = join(root(), 'display-profile')
    const store = new DisplayProfileStore(dir)
    store.setPicture(personality('__proto__'), png({ shade: 1 }).toString('base64'))
    const saved = store.setPicture(personality('constructor'), png({ shade: 2 }).toString('base64'))
    expect(keys(saved).sort()).toEqual(['__proto__', 'constructor'])
    const again = new DisplayProfileStore(dir).read()
    expect(again).toEqual(saved)
    expect(again.personalities.find(({ key }) => key === '__proto__')?.picture)
      .toBe(`data:image/png;base64,${png({ shade: 1 }).toString('base64')}`)
    expect(keys(store.removePicture(personality('__proto__')))).toEqual(['constructor'])
  })

  it('refuses names and pictures it cannot use, and writes nothing for them', () => {
    const dir = join(root(), 'display-profile')
    const store = new DisplayProfileStore(dir)
    for (const name of ['x'.repeat(41), 'two\nlines', 'tab\there']) {
      expect(() => store.setName(name)).toThrow(DisplayProfileError)
    }
    for (const bytes of [png({ width: 128, height: 128 }), png().subarray(0, 60), png({ filter: 5 }), Buffer.alloc(10)]) {
      expect(() => store.setPicture(user, bytes.toString('base64'))).toThrow(DisplayProfileError)
    }
    expect(store.read()).toEqual({ name: '', user: null, personalities: [] })
    expect(store.setName('Aaron').name).toBe('Aaron')
    expect(store.setName('   ').name).toBe('')
  })

  it('never writes through a link or into a folder others can reach, and never fixes its mode', () => {
    const base = root()
    const elsewhere = join(base, 'elsewhere')
    mkdirSync(elsewhere, { mode: 0o777 })
    chmodSync(elsewhere, 0o777)
    const linked = join(base, 'linked')
    symlinkSync(elsewhere, linked, 'dir')
    expect(() => new DisplayProfileStore(linked).setName('Aaron')).toThrow(DisplayProfileError)
    expect(readdirSync(elsewhere)).toEqual([])
    const shared = join(base, 'shared')
    mkdirSync(shared, { mode: 0o755 })
    chmodSync(shared, 0o755)
    writeFileSync(join(shared, 'user.png'), png())
    const store = new DisplayProfileStore(shared)
    expect(() => store.setPicture(user, png().toString('base64'))).toThrow(DisplayProfileError)
    expect(store.read()).toEqual({ name: '', user: null, personalities: [] })  // not read from it either
    expect(statSync(shared).mode & 0o777).toBe(0o755)
  })

  it('reads a file only when it is a regular file, never through a link', () => {
    const base = root()
    const dir = join(base, 'display-profile')
    const store = new DisplayProfileStore(dir)
    store.setName('Aaron')
    const foreign = join(base, 'foreign')
    mkdirSync(foreign)
    writeFileSync(join(foreign, 'profile.json'), JSON.stringify({ name: 'Someone else' }))
    writeFileSync(join(foreign, 'user.png'), png())
    rmSync(join(dir, 'profile.json'))
    symlinkSync(join(foreign, 'profile.json'), join(dir, 'profile.json'))
    symlinkSync(join(foreign, 'user.png'), join(dir, 'user.png'))
    expect(store.read()).toEqual({ name: '', user: null, personalities: [] })
  })

  it('reads damaged files as not set and removes a picture', () => {
    const dir = join(root(), 'display-profile')
    const store = new DisplayProfileStore(dir)
    store.setName('Aaron')
    store.setPicture(user, png().toString('base64'))
    store.setPicture(personality('clippy'), png().toString('base64'))
    writeFileSync(join(dir, 'profile.json'), '{not json')
    // The header survives but the image data is cut off: not a picture, so chat shows the default mark.
    writeFileSync(join(dir, `personality-${Buffer.from('clippy').toString('hex')}.png`), png().subarray(0, 60))
    expect(store.read()).toMatchObject({ name: '', personalities: [] })
    expect(store.removePicture(user).user).toBeNull()
    expect(store.removePicture(user).user).toBeNull()  // already gone: still fine
    expect(store.removePicture(personality('never-set')).personalities).toEqual([])
  })
})

describe('special files', () => {
  it('refuses FIFOs at once instead of waiting for a writer', () => {
    // A FIFO opened for reading waits for a writer unless opened non-blocking, which would stall Electron's main
    // thread. The real store runs in a child process with a time limit, so a regression fails here, never hangs.
    const base = root()
    const dir = join(base, 'display-profile')
    const store = new DisplayProfileStore(dir)
    store.setName('Aaron')
    const clippy = `personality-${Buffer.from('clippy').toString('hex')}.png`
    store.setPicture(personality('clippy'), png().toString('base64'))
    rmSync(join(dir, 'profile.json'))
    rmSync(join(dir, clippy))
    for (const file of ['profile.json', 'user.png', clippy]) execFileSync('mkfifo', ['-m', '600', join(dir, file)])
    const bundle = join(base, 'store.mjs')
    buildSync({ entryPoints: [resolve(__dirname, '../src/main/display-profile.ts')], bundle: true, platform: 'node',
      format: 'esm', outfile: bundle, logLevel: 'silent' })
    const script = `import { DisplayProfileStore } from ${JSON.stringify(pathToFileURL(bundle).href)}
console.log(JSON.stringify(new DisplayProfileStore(${JSON.stringify(dir)}).read()))`
    const child = spawnSync(process.execPath, ['--input-type=module', '-e', script], { encoding: 'utf8', timeout: 10_000 })
    expect(child.error).toBeUndefined()  // ETIMEDOUT had it blocked on a FIFO
    expect(child.status).toBe(0)
    expect(JSON.parse(child.stdout)).toEqual({ name: '', user: null, personalities: [] })
  })
})
