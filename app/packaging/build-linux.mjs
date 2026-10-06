// Local, non-publishing candidate build. Both formats share one runtime stage.
import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'

const app = resolve(import.meta.dirname, '..')
// fpm's late AppArmor copy and SquashFS must see the same permissions as the
// sealed resources, independently of the build account's collaborative umask.
process.umask(0o022)
process.env.SOURCE_DATE_EPOCH = '1791158400'
const run = (command, args) => {
  const result = spawnSync(command, args, { cwd: app, stdio: 'inherit', env: process.env })
  if (result.status !== 0) process.exit(result.status || 1)
}
const provision = spawnSync('python3', [resolve(import.meta.dirname, 'provision-builder.py')], { cwd: app, encoding: 'utf8', env: process.env })
if (provision.status !== 0) {
  process.stderr.write(provision.stderr || '')
  process.exit(provision.status || 1)
}
process.env.ELECTRON_BUILDER_CACHE = provision.stdout.trim().split('\n').at(-1)
run('python3', [resolve(import.meta.dirname, 'build-runtime.py')])
run('python3', [resolve(import.meta.dirname, 'build-deb-control.py')])
run('npm', ['run', 'build'])
run(resolve(app, 'node_modules/.bin/electron-builder'), ['--linux', 'deb', 'AppImage', '--x64', '--publish', 'never'])
