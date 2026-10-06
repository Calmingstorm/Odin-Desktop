// The same sealed unpacked tree feeds .deb and AppImage. This hook never publishes.
const { spawnSync } = require('node:child_process')
const { join } = require('node:path')

module.exports = async (context) => {
  const result = spawnSync('python3', [join(__dirname, 'finalize-manifest.py'), join(context.appOutDir, 'resources')], {
    stdio: 'inherit', env: process.env
  })
  if (result.status !== 0) throw new Error('Packaged resource manifest failed')
}
