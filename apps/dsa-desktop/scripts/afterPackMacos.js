const path = require('node:path')
const { execFileSync } = require('node:child_process')

exports.default = async function afterPackMacos(context) {
  if (context.electronPlatformName !== 'darwin') {
    return
  }

  const appPath = path.join(
    context.appOutDir,
    `${context.packager.appInfo.productFilename}.app`,
  )
  const auditScript = path.resolve(
    __dirname,
    '..',
    '..',
    '..',
    'scripts',
    'macos-signature-audit.sh',
  )

  execFileSync('bash', [auditScript, 'normalize', appPath], {
    stdio: 'inherit',
  })
}
