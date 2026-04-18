const { contextBridge } = require('electron');

const DESKTOP_VERSION_ARG_PREFIX = '--dsa-desktop-version=';

function readDesktopVersion(argv = process.argv) {
  const versionArg = argv.find(
    (value) => typeof value === 'string' && value.startsWith(DESKTOP_VERSION_ARG_PREFIX)
  );
  return versionArg ? versionArg.slice(DESKTOP_VERSION_ARG_PREFIX.length) : '';
}

contextBridge.exposeInMainWorld('dsaDesktop', {
  version: readDesktopVersion(),
});

module.exports = {
  DESKTOP_VERSION_ARG_PREFIX,
  readDesktopVersion,
};
