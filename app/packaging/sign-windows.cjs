// electron-builder's Windows signing hook (electron-builder.windows.yml's signtoolOptions.sign), for the release
// build only. It signs Odin's own executables and nothing else: Odin.exe, the NSIS uninstaller and the installer,
// with Microsoft's SignTool and the Artifact Signing library that packaging/provision-signing.py unpacked. The
// library signs in through the Azure CLI, which the release job signed in with GitHub's identity token: no stored
// secret. Every other executable electron-builder offers (the bundled runtime's and tools', some signed by their
// own publishers, as Microsoft signs ssh.exe) is left exactly as shipped. Each signature is checked before the
// build goes on: valid, by the expected publisher, and timestamped, since the certificates last three days and the
// timestamp keeps a signature valid after that. Off unless ODIN_WINDOWS_SIGNING=1, so local and CI candidate
// builds stay unsigned, as before.
const { spawnSync } = require('node:child_process')
const { existsSync } = require('node:fs')
const { basename, dirname, join } = require('node:path')

const TIMESTAMP = 'http://timestamp.acs.microsoft.com'
const TRIES = 3
// electron-builder's names in its output folder: the separate uninstaller it builds, signs and packs into the
// installer, and the installer itself (electron-builder.windows.yml's artifactName).
const UNINSTALLER = /^__uninstaller-.+\.exe$/
const INSTALLER = /^odin-desktop-.+-x64-setup\.exe$/
const TOOLS = { signtool: 'ODIN_SIGNTOOL', dlib: 'ODIN_SIGNING_DLIB', metadata: 'ODIN_SIGNING_METADATA' }
// The signature as Windows reads it, for the file named in ODIN_SIGNED_FILE (no path inside the command).
const INSPECT = "$ErrorActionPreference = 'Stop'; " +
  '$s = Get-AuthenticodeSignature -LiteralPath $env:ODIN_SIGNED_FILE; $c = $s.SignerCertificate; ' +
  "@{ status = [string]$s.Status; publisher = if ($c) { $c.GetNameInfo('SimpleName', $false) } else { '' }; " +
  'thumbprint = if ($c) { $c.Thumbprint } else { \'\' }; timestamped = [bool]$s.TimeStamperCertificate } | ' +
  'ConvertTo-Json -Compress'

/** Whose a file electron-builder offers is: Odin's own ('app', 'uninstaller', 'installer'), 'bundled', or 'unknown'. */
function classify(file) {
  // Anything below an app's resources folder (the folder beside its Odin.exe) ships as its publisher made it.
  for (let folder = dirname(file); dirname(folder) !== folder; folder = dirname(folder)) {
    if (basename(folder) === 'resources' && existsSync(join(dirname(folder), 'Odin.exe'))) return 'bundled'
  }
  const name = basename(file)
  if (name === 'Odin.exe' && existsSync(join(dirname(file), 'resources'))) return 'app'
  if (UNINSTALLER.test(name)) return 'uninstaller'
  if (INSTALLER.test(name)) return 'installer'
  return 'unknown'
}

function settings(env) {
  const found = {}
  for (const [key, name] of Object.entries(TOOLS)) {
    if (!env[name]) throw new Error(`${name} isn't set: signing needs packaging/provision-signing.py's tools`)
    if (!existsSync(env[name])) throw new Error(`${name} names a missing file: ${env[name]}`)
    found[key] = env[name]
  }
  if (!env.ODIN_SIGNING_PUBLISHER) throw new Error('ODIN_SIGNING_PUBLISHER (the expected signer) isn\'t set')
  found.publisher = env.ODIN_SIGNING_PUBLISHER
  return found
}

// Windows PowerShell started from PowerShell 7 (the release job's shell) inherits PowerShell 7's module path, and then
// can't load its own Get-AuthenticodeSignature: it gets its own path back by inheriting none.
function inspectEnv(env, file) {
  const child = Object.fromEntries(Object.entries(env).filter(([name]) => name.toUpperCase() !== 'PSMODULEPATH'))
  return { ...child, ODIN_SIGNED_FILE: file }
}

const output = (result) => `${result.error ? result.error.message : ''}\n${result.stdout || ''}\n${result.stderr || ''}`
  .trim().slice(-2000)

/** The signing hook, with what it runs injected (tests) or real (electron-builder). */
function createSigner({ env = process.env, run = spawnSync, sleep = (ms) => new Promise((done) => setTimeout(done, ms)),
  log = (line) => console.log(line) } = {}) {
  return async function sign(configuration) {
    if (env.ODIN_WINDOWS_SIGNING !== '1') return  // an unsigned build: nothing is signed
    const file = configuration.path
    if (configuration.hash && configuration.hash !== 'sha256') {
      throw new Error(`Artifact Signing signs with SHA-256 only, not ${configuration.hash}: ${file}`)
    }
    const kind = classify(file)
    if (kind === 'bundled') {
      log(`signing: left as shipped, ${file}`)
      return
    }
    if (kind === 'unknown') throw new Error(`Refusing to sign an unexpected file: ${file}`)
    const tools = settings(env)
    const args = ['sign', '/v', '/fd', 'SHA256', '/tr', TIMESTAMP, '/td', 'SHA256', '/dlib', tools.dlib,
      '/dmdf', tools.metadata, file]
    for (let attempt = 1; ; attempt += 1) {
      const result = run(tools.signtool, args, { encoding: 'utf8', windowsHide: true, timeout: 5 * 60000 })
      if (result.status === 0) break
      // A failed SignTool run leaves the file as it was, so another try is safe.
      if (attempt === TRIES) throw new Error(`SignTool failed ${TRIES} times for ${file}: ${output(result)}`)
      log(`signing: SignTool failed for ${basename(file)} (try ${attempt} of ${TRIES}), retrying`)
      await sleep(attempt * 15000)
    }
    const inspected = run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', INSPECT],
      { encoding: 'utf8', windowsHide: true, timeout: 2 * 60000, env: inspectEnv(env, file) })
    let signature = {}
    try {
      if (inspected.status !== 0) throw new Error('PowerShell failed')
      signature = JSON.parse(inspected.stdout)
    } catch {
      throw new Error(`Couldn't read the signature of ${file}: ${output(inspected)}`)
    }
    if (signature.status !== 'Valid' || signature.publisher !== tools.publisher || signature.timestamped !== true) {
      throw new Error(`${file} isn't validly signed by ${tools.publisher} with a timestamp: ${JSON.stringify(signature)}`)
    }
    log(`signing: signed the ${kind}, ${basename(file)}, as ${signature.publisher} (${signature.thumbprint})`)
  }
}

module.exports = { sign: createSigner(), createSigner, classify }
