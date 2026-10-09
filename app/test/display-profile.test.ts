import { chmodSync, mkdirSync, mkdtempSync, readdirSync, rmSync, statSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
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

/** A PNG header of the given size; enough for the app's check, which the window's decoder backs. */
function png(width = 256, height = 256, padding = 64): Buffer {
  const header = Buffer.alloc(33)
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(header, 0)
  header.writeUInt32BE(13, 8)
  header.write('IHDR', 12, 'latin1')
  header.writeUInt32BE(width, 16)
  header.writeUInt32BE(height, 20)
  return Buffer.concat([header, Buffer.alloc(padding)])
}

const user = { target: 'user' } as const
const personality = (key: string) => ({ target: 'personality', key }) as const

describe('display profile store', () => {
  it('keeps your name, your picture and a picture per personality in owner-only files across a restart', () => {
    const dir = join(root(), 'display-profile')
    const store = new DisplayProfileStore(dir)
    expect(store.read()).toEqual({ name: '', user: null, personalities: {} })
    store.setName('  Aaron  ')
    store.setPicture(user, png().toString('base64'))
    const saved = store.setPicture(personality('clippy-astra'), png(256, 256, 8).toString('base64'))
    expect(saved.name).toBe('Aaron')
    expect(saved.user).toBe(`data:image/png;base64,${png().toString('base64')}`)
    expect(Object.keys(saved.personalities)).toEqual(['clippy-astra'])
    expect(new DisplayProfileStore(dir).read()).toEqual(saved)
    expect(statSync(dir).mode & 0o777).toBe(0o700)
    for (const file of readdirSync(dir)) expect(statSync(join(dir, file)).mode & 0o777).toBe(0o600)
    expect(readdirSync(dir).some((file) => file.endsWith('.tmp'))).toBe(false)
  })

  it('stores any preset key under a hex file name, never as a path', () => {
    const dir = join(root(), 'display-profile')
    const store = new DisplayProfileStore(dir)
    const key = 'Clippy/../x ✓'
    expect(Object.keys(store.setPicture(personality(key), png().toString('base64')).personalities)).toEqual([key])
    expect(readdirSync(dir)).toEqual([`personality-${Buffer.from(key).toString('hex')}.png`])
    expect(() => store.setPicture(personality('k'.repeat(101)), png().toString('base64'))).toThrow(DisplayProfileError)
  })

  it('refuses names and pictures it cannot use, and writes nothing for them', () => {
    const dir = join(root(), 'display-profile')
    const store = new DisplayProfileStore(dir)
    for (const name of ['x'.repeat(41), 'two\nlines', 'tab\there']) {
      expect(() => store.setName(name)).toThrow(DisplayProfileError)
    }
    const wrongSignature = png()
    wrongSignature[0] = 0
    const notIhdr = png()
    notIhdr.write('IDAT', 12, 'latin1')
    for (const bytes of [png(128, 128), png(256, 255), wrongSignature, notIhdr, png(256, 256, MAX_PICTURE_BYTES), Buffer.alloc(10)]) {
      expect(validPicture(bytes)).toBe(false)
      expect(() => store.setPicture(user, bytes.toString('base64'))).toThrow(DisplayProfileError)
    }
    expect(store.read()).toEqual({ name: '', user: null, personalities: {} })
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
    expect(store.read()).toEqual({ name: '', user: null, personalities: {} })  // not read from it either
    expect(statSync(shared).mode & 0o777).toBe(0o755)
  })

  it('reads damaged files as not set and removes a picture', () => {
    const dir = join(root(), 'display-profile')
    const store = new DisplayProfileStore(dir)
    store.setName('Aaron')
    store.setPicture(user, png().toString('base64'))
    store.setPicture(personality('clippy'), png().toString('base64'))
    writeFileSync(join(dir, 'profile.json'), '{not json')
    writeFileSync(join(dir, `personality-${Buffer.from('clippy').toString('hex')}.png`), 'not a png')
    expect(store.read()).toMatchObject({ name: '', personalities: {} })
    expect(store.removePicture(user).user).toBeNull()
    expect(store.removePicture(user).user).toBeNull()  // already gone: still fine
    expect(store.removePicture(personality('never-set')).personalities).toEqual({})
  })
})
