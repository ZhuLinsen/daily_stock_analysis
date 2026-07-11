const { contextBridge, ipcRenderer } = require('electron');

const DESKTOP_VERSION_ARG_PREFIX = '--dsa-desktop-version=';
const DESKTOP_GET_UPDATE_STATE_CHANNEL = 'desktop:get-update-state';
const DESKTOP_CHECK_FOR_UPDATES_CHANNEL = 'desktop:check-for-updates';
const DESKTOP_INSTALL_DOWNLOADED_UPDATE_CHANNEL = 'desktop:install-downloaded-update';
const DESKTOP_OPEN_RELEASE_PAGE_CHANNEL = 'desktop:open-release-page';
const DESKTOP_UPDATE_STATE_EVENT = 'desktop:update-state';

function readDesktopVersion(argv = process.argv) {
  const versionArg = argv.find(
    (value) => typeof value === 'string' && value.startsWith(DESKTOP_VERSION_ARG_PREFIX)
  );
  return versionArg ? versionArg.slice(DESKTOP_VERSION_ARG_PREFIX.length) : '';
}

function createDesktopBridge({
  version = readDesktopVersion(),
  renderer = ipcRenderer,
} = {}) {
  return {
    version,
    getUpdateState() {
      return renderer.invoke(DESKTOP_GET_UPDATE_STATE_CHANNEL);
    },
    checkForUpdates() {
      return renderer.invoke(DESKTOP_CHECK_FOR_UPDATES_CHANNEL);
    },
    installDownloadedUpdate() {
      return renderer.invoke(DESKTOP_INSTALL_DOWNLOADED_UPDATE_CHANNEL);
    },
    openReleasePage(releaseUrl) {
      return renderer.invoke(DESKTOP_OPEN_RELEASE_PAGE_CHANNEL, releaseUrl);
    },
    onUpdateStateChange(listener) {
      if (typeof listener !== 'function') {
        return () => undefined;
      }

      const handler = (_event, payload) => {
        listener(payload);
      };
      renderer.on(DESKTOP_UPDATE_STATE_EVENT, handler);
      return () => {
        renderer.removeListener(DESKTOP_UPDATE_STATE_EVENT, handler);
      };
    },
  };
}

contextBridge.exposeInMainWorld('dsaDesktop', createDesktopBridge());

module.exports = {
  DESKTOP_CHECK_FOR_UPDATES_CHANNEL,
  DESKTOP_GET_UPDATE_STATE_CHANNEL,
  DESKTOP_INSTALL_DOWNLOADED_UPDATE_CHANNEL,
  DESKTOP_OPEN_RELEASE_PAGE_CHANNEL,
  DESKTOP_UPDATE_STATE_EVENT,
  DESKTOP_VERSION_ARG_PREFIX,
  createDesktopBridge,
  readDesktopVersion,
};
