// Shared local/Actions entrypoint. Never uploads or publishes.
import { spawnSync } from 'node:child_process'
import { mkdtempSync, existsSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

export function buildEnvironment(source, home) {
  const allowed = ['PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'ODIN_PACKAGING_CACHE', 'SOURCE_DATE_EPOCH']
  const env = Object.fromEntries(allowed.filter(key => source[key]).map(key => [key, source[key]]))
  return { ...env, HOME: home, XDG_CACHE_HOME: resolve(home, '.cache'),
    npm_config_userconfig: '/dev/null', npm_config_globalconfig: '/dev/null', CI: 'true' }
}

export function buildCommands() {
  return [['npm', ['ci', '--ignore-scripts']], ['node', ['node_modules/electron/install.js']],
    ['npm', ['run', 'package:candidate']]]
}

export function run(argv) {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
  const args = Object.fromEntries(argv.map(value => {
    if (!value.startsWith('--') || !value.includes('=')) throw Error('Use --key=value arguments')
    const index = value.indexOf('=')
    return [value.slice(2, index), value.slice(index + 1)]
  }))
  for (const key of Object.keys(args)) {
    if (!['build', 'output', 'source', 'workflow-sha', 'run-id', 'tag'].includes(key)) throw Error('Unknown rehearsal option')
  }
  if (!['true', 'false'].includes(args.build ?? 'false')) throw Error('build must be true or false')
  for (const key of ['output', 'source', 'workflow-sha', 'run-id']) if (!args[key]) throw Error('Missing ' + key)
  if (existsSync(resolve(args.output))) throw Error('Evidence output must be fresh')
  const home = mkdtempSync(resolve(tmpdir(), 'odin-release-build-'))
  const env = buildEnvironment(process.env, home)
  try {
    const preflight = spawnSync('python3', ['-B', '-c',
      'from release_helper import *; import sys; v=versions(load_json(sys.argv[1]),load_json(sys.argv[2]),sys.argv[4] or None); release_notes(Path(sys.argv[3]).read_text(),v)',
      resolve(root, 'app/package.json'), resolve(root, 'app/package-lock.json'), resolve(root, 'CHANGELOG.md'), args.tag ?? ''],
      { cwd: resolve(root, 'scripts/release'), stdio: 'inherit', env })
    if (preflight.status !== 0) throw Error('Release metadata preflight failed')
    if (args.build === 'true') {
      if (existsSync(resolve(root, '.packaging-candidates'))) throw Error('Candidate directory must be fresh; use a clean isolated checkout')
      for (const [command, commandArgs] of buildCommands()) {
        const result = spawnSync(command, commandArgs, { cwd: resolve(root, 'app'), stdio: 'inherit', env })
        if (result.status !== 0) throw Error('Pinned candidate build failed: ' + command)
      }
    }
    const validation = ['-B', resolve(root, 'scripts/release/release_helper.py'), 'rehearse',
      '--repo', root, '--candidates', resolve(root, '.packaging-candidates')]
    for (const key of ['output', 'source', 'workflow-sha', 'run-id', 'tag']) if (args[key]) validation.push('--' + key, args[key])
    const result = spawnSync('python3', validation, { cwd: root, stdio: 'inherit', env })
    if (result.status !== 0) throw Error('Offline candidate validation failed')
    console.log('Nonpublishing rehearsal passed; no tags, releases or uploads.')
  } finally {
    rmSync(home, { recursive: true, force: true })
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { run(process.argv.slice(2)) } catch (error) { console.error(error.message); process.exitCode = 1 }
}
