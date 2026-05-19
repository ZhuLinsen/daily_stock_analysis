const assert = require('node:assert/strict');
const test = require('node:test');
const Module = require('node:module');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

function loadMainModule(t, options = {}) {
  const originalLoad = Module._load;
  const originalPlatform = Object.getOwnPropertyDescriptor(process, 'platform');
  const ipcMainHandlers = new Map();
  const fakeApp = {
    isPackaged: false,
    getVersion: () => '3.12.0',
    getPath: () => '/tmp/dsa-user-data',
    whenReady: () => ({ then: () => undefined }),
    on: () => undefined,
    quit: () => undefined,
    ...(options.app || {}),
  };
  const fakeDialog = {
    showMessageBox: async () => ({ response: 0 }),
    ...(options.dialog || {}),
  };
  const fakeShell = {
    openExternal: async () => true,
  };
  const fakeIpcMain = {
    handle: (channel, handler) => {
      ipcMainHandlers.set(channel, handler);
    },
  };
  function defaultBrowserWindow() {
    return {
      isDestroyed: () => false,
      getAllWindows: () => [],
      setBackgroundColor: () => undefined,
      once: () => undefined,
      webContents: {
        on: () => undefined,
        send: () => undefined,
        setWindowOpenHandler: () => undefined,
      },
      loadFile: async () => undefined,
      loadURL: async () => undefined,
    };
  }
  defaultBrowserWindow.getAllWindows = () => [];
  const fakeBrowserWindow = options.browserWindow || defaultBrowserWindow;
  const fakeNativeTheme = {
    shouldUseDarkColors: false,
    on: () => undefined,
    removeListener: () => undefined,
  };

  Module._load = function patchedLoad(request, parent, isMain) {
    if (request === 'electron') {
      return {
        app: fakeApp,
        BrowserWindow: fakeBrowserWindow,
        dialog: fakeDialog,
        ipcMain: fakeIpcMain,
        shell: fakeShell,
        nativeTheme: fakeNativeTheme,
      };
    }
    if (request === 'http' && options.http) {
      return options.http;
    }
    if (request === 'net' && options.net) {
      return options.net;
    }
    if (request === 'child_process' && options.childProcess) {
      return options.childProcess;
    }
    if (request === 'electron-updater' && options.electronUpdater) {
      return {
        autoUpdater: options.electronUpdater,
      };
    }
    return originalLoad.call(this, request, parent, isMain);
  };

  const mainPath = require.resolve('../main.js');
  delete require.cache[mainPath];

  t.after(() => {
    Module._load = originalLoad;
    if (options.platform && originalPlatform) {
      Object.defineProperty(process, 'platform', originalPlatform);
    }
    delete require.cache[mainPath];
  });

  if (options.platform) {
    Object.defineProperty(process, 'platform', { ...originalPlatform, value: options.platform });
  }

  const mainModule = require('../main.js');
  mainModule.__getIpcMainHandler = (channel) => ipcMainHandlers.get(channel);
  return mainModule;
}

test('parseSemver accepts stable and prerelease tags', (t) => {
  const mainModule = loadMainModule(t);

  assert.deepEqual(mainModule.parseSemver('v3.13.0-beta.2'), {
    major: 3,
    minor: 13,
    patch: 0,
    prerelease: ['beta', '2'],
  });
  assert.equal(mainModule.parseSemver('nightly-20260425'), null);
});

test('compareVersions follows semantic version ordering', (t) => {
  const mainModule = loadMainModule(t);

  assert.equal(mainModule.compareVersions('3.12.0', '3.13.0'), -1);
  assert.equal(mainModule.compareVersions('v3.13.0', '3.13.0'), 0);
  assert.equal(mainModule.compareVersions('3.13.0', '3.13.0-beta.1'), 1);
  assert.equal(mainModule.compareVersions('3.13.0-beta.2', '3.13.0-beta.10'), -1);
});

test('buildMainPageUrl includes desktop version and cache buster', (t) => {
  const mainModule = loadMainModule(t, {
    app: {
      getVersion: () => ' 3.17.1 ',
    },
  });

  assert.equal(
    mainModule.buildMainPageUrl(8123, 1234567890),
    'http://127.0.0.1:8123/?desktop_version=3.17.1&cache_bust=1234567890'
  );
});

test('extractReleaseMetadata ignores releases without semver tags', (t) => {
  const mainModule = loadMainModule(t);

  assert.equal(
    mainModule.extractReleaseMetadata({
      tag_name: 'desktop-latest',
      html_url: 'https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/desktop-latest',
    }),
    null
  );
});

test('evaluateReleaseUpdate reports update-available when release is newer', (t) => {
  const mainModule = loadMainModule(t);
  const state = mainModule.evaluateReleaseUpdate({
    currentVersion: '3.12.0',
    release: {
      tag_name: 'v3.13.0',
      html_url: 'https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v3.13.0',
      published_at: '2026-04-25T01:00:00Z',
      name: 'v3.13.0',
    },
    checkedAt: '2026-04-25T01:02:00Z',
  });

  assert.equal(state.status, mainModule.UPDATE_STATUS.UPDATE_AVAILABLE);
  assert.equal(state.currentVersion, '3.12.0');
  assert.equal(state.latestVersion, '3.13.0');
  assert.equal(state.releaseUrl, 'https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v3.13.0');
  assert.equal(state.checkedAt, '2026-04-25T01:02:00Z');
  assert.equal(state.publishedAt, '2026-04-25T01:00:00Z');
  assert.match(state.message, /发现新版本 3\.13\.0/);
});

test('evaluateReleaseUpdate reports up-to-date when version is current', (t) => {
  const mainModule = loadMainModule(t);
  const state = mainModule.evaluateReleaseUpdate({
    currentVersion: '3.13.0',
    release: {
      tag_name: 'v3.13.0',
      html_url: 'https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v3.13.0',
    },
    checkedAt: '2026-04-25T01:02:00Z',
  });

  assert.equal(state.status, mainModule.UPDATE_STATUS.UP_TO_DATE);
  assert.equal(state.latestVersion, '3.13.0');
  assert.equal(state.releaseUrl, 'https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v3.13.0');
  assert.equal(state.checkedAt, '2026-04-25T01:02:00Z');
  assert.equal(state.publishedAt, '');
});

test('evaluateReleaseUpdate reports error when current version is invalid', (t) => {
  const mainModule = loadMainModule(t);
  const state = mainModule.evaluateReleaseUpdate({
    currentVersion: 'build-20260425',
    release: {
      tag_name: 'v3.13.0',
      html_url: 'https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v3.13.0',
    },
    checkedAt: '2026-04-25T01:02:00Z',
  });

  assert.equal(state.status, mainModule.UPDATE_STATUS.ERROR);
  assert.match(state.message, /不是有效的语义化版本/);
});

test('checkForDesktopUpdates delegates to release fetcher', async (t) => {
  const mainModule = loadMainModule(t);
  const state = await mainModule.checkForDesktopUpdates({
    currentVersion: '3.12.0',
    fetchLatestRelease: async () => ({
      tag_name: 'v3.13.0',
      html_url: '',
    }),
  });

  assert.equal(state.status, mainModule.UPDATE_STATUS.UPDATE_AVAILABLE);
  assert.equal(state.releaseUrl, mainModule.RELEASES_PAGE_URL);
});

test('sanitizeReleaseUrl falls back for non-release links', (t) => {
  const mainModule = loadMainModule(t);

  assert.equal(
    mainModule.sanitizeReleaseUrl('https://example.com/not-allowed'),
    mainModule.RELEASES_PAGE_URL
  );
  assert.equal(
    mainModule.sanitizeReleaseUrl(
      `https://github.com/${mainModule.GITHUB_OWNER}/${mainModule.GITHUB_REPO}/releases/tag/v3.13.0`
    ),
    `https://github.com/${mainModule.GITHUB_OWNER}/${mainModule.GITHUB_REPO}/releases/tag/v3.13.0`
  );
});

test('fetchLatestReleaseJson rejects when response stream errors', async (t) => {
  const mainModule = loadMainModule(t);
  const response = new EventEmitter();
  response.statusCode = 200;
  response.complete = false;
  let destroyed = false;

  const request = () => {
    const req = new EventEmitter();
    req.destroyed = false;
    req.setTimeout = () => undefined;
    req.destroy = () => {
      destroyed = true;
      req.destroyed = true;
    };
    req.end = () => {
      process.nextTick(() => {
        request.onResponse(response);
        response.emit('error', new Error('stream failed'));
      });
    };
    return req;
  };
  request.onResponse = () => undefined;

  const pending = mainModule.fetchLatestReleaseJson({
    request: (_url, _options, onResponse) => {
      request.onResponse = onResponse;
      return request();
    },
  });

  await assert.rejects(pending, /stream failed/);
  assert.equal(destroyed, true);
});

test('auto download prompt falls back to error when install path fails', async (t) => {
  const updaterEvents = {};
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dsa-desktop-updater-'));
  const exeDir = path.join(tempRoot, 'app');
  const userDataDir = path.join(tempRoot, 'userData');
  const exePath = path.join(exeDir, 'Daily Stock Analysis.exe');
  const uninstallPath = path.join(exeDir, 'Uninstall Daily Stock Analysis.exe');
  const envFile = path.join(exeDir, '.env');
  const backupRoot = path.join(userDataDir, '.dsa-desktop-update-backup');
  const originalRemove = fs.rmSync;
  const fakeUpdater = {
    autoDownload: true,
    autoInstallOnAppQuit: false,
    on: (event, handler) => {
      updaterEvents[event] = handler;
    },
    checkForUpdates: async () => {
      if (typeof updaterEvents['update-downloaded'] === 'function') {
        await updaterEvents['update-downloaded']({
          version: 'v3.13.0',
          releaseDate: '2026-04-25T01:00:00Z',
          releaseName: 'v3.13.0',
        });
      }
    },
    quitAndInstall: () => {
      throw new Error('安装进程启动失败');
    },
  };

  const mainModule = loadMainModule(t, {
    dialog: {
      showMessageBox: async () => ({ response: 1 }),
    },
    electronUpdater: fakeUpdater,
    platform: 'win32',
    app: {
      isPackaged: true,
      getPath: (name) => {
        if (name === 'exe') {
          return exePath;
        }
        return userDataDir;
      },
    },
  });

  fs.mkdirSync(exeDir, { recursive: true });
  fs.mkdirSync(userDataDir, { recursive: true });
  fs.writeFileSync(envFile, 'RUN_MODE=desktop\n');
  fs.writeFileSync(uninstallPath, '');

  mainModule.__setMainWindowForTest({
    isDestroyed: () => false,
    webContents: {
      send: () => undefined,
    },
  });

  await mainModule.__getIpcMainHandler('desktop:check-for-updates')();
  let state = await mainModule.__getIpcMainHandler('desktop:get-update-state')();
  for (let idx = 0; idx < 12 && state.status !== mainModule.UPDATE_STATUS.ERROR; idx += 1) {
    await new Promise((resolve) => {
      setTimeout(resolve, 30);
    });
    state = await mainModule.__getIpcMainHandler('desktop:get-update-state')();
  }

  assert.equal(state.status, mainModule.UPDATE_STATUS.ERROR);
  assert.match(state.message, /更新安装失败/);
  assert.equal(state.updateMode, mainModule.UPDATE_MODE.AUTO);
  assert.equal(fs.existsSync(backupRoot), false);
  assert.equal(fs.existsSync(path.join(backupRoot, 'runtime-state.json')), false);

  t.after(() => {
    originalRemove(tempRoot, { recursive: true, force: true });
  });
});

test('desktop update backup list includes WAL and SHM artifacts', (t) => {
  const mainModule = loadMainModule(t);
  const files = mainModule.DESKTOP_UPDATE_RUNTIME_RELATIVE_FILES || [];
  assert.equal(Array.isArray(files), true);
  assert.ok(files.includes(path.join('data', 'stock_analysis.db')));
  assert.ok(files.includes(path.join('data', 'stock_analysis.db-wal')));
  assert.ok(files.includes(path.join('data', 'stock_analysis.db-shm')));
  assert.ok(files.includes(path.join('logs', 'desktop.log')));
});

test('restorePackagedRuntimeStateFromBackup keeps backup when copy fails', (t) => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dsa-desktop-restore-'));
  const appDir = path.join(tempRoot, 'app');
  const userDataDir = path.join(tempRoot, 'userData');
  const backupRoot = path.join(userDataDir, '.dsa-desktop-update-backup');
  const backupDbPath = path.join(backupRoot, 'data', 'stock_analysis.db');
  fs.mkdirSync(path.dirname(backupDbPath), { recursive: true });
  fs.mkdirSync(appDir, { recursive: true });
  fs.writeFileSync(path.join(appDir, 'Uninstall Daily Stock Analysis.exe'), '');
  fs.writeFileSync(backupDbPath, 'backup-db');
  fs.writeFileSync(
    path.join(backupRoot, 'runtime-state.json'),
    JSON.stringify({ files: [path.join('data', 'stock_analysis.db')] }),
    'utf-8'
  );

  const mainModule = loadMainModule(t, {
    platform: 'win32',
    app: {
      isPackaged: true,
      getPath: (name) => {
        if (name === 'exe') {
          return path.join(appDir, 'Daily Stock Analysis.exe');
        }
        return userDataDir;
      },
    },
  });
  const originalCopyFileSync = fs.copyFileSync;
  let failedCopyAttempted = false;

  fs.copyFileSync = (source, target) => {
    if (source === backupDbPath) {
      failedCopyAttempted = true;
      throw new Error('target locked');
    }
    return originalCopyFileSync(source, target);
  };

  t.after(() => {
    fs.copyFileSync = originalCopyFileSync;
    fs.rmSync(tempRoot, { recursive: true, force: true });
  });

  const restoreResult = mainModule.restorePackagedRuntimeStateFromBackup();
  assert.equal(failedCopyAttempted, true);
  assert.equal(Array.isArray(restoreResult.failed), true);
  assert.equal(restoreResult.failed.length > 0, true);
  assert.equal(fs.existsSync(backupRoot), true);
  assert.equal(fs.existsSync(path.join(backupRoot, 'runtime-state.json')), true);
  assert.equal(restoreResult.failed[0].includes('target locked'), true);
});

test('restorePackagedRuntimeStateFromBackup removes restored files from pending manifest', (t) => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dsa-desktop-partial-restore-'));
  const appDir = path.join(tempRoot, 'app');
  const userDataDir = path.join(tempRoot, 'userData');
  const backupRoot = path.join(userDataDir, '.dsa-desktop-update-backup');
  const backupEnvPath = path.join(backupRoot, '.env');
  const backupDbPath = path.join(backupRoot, 'data', 'stock_analysis.db');
  const targetEnvPath = path.join(appDir, '.env');
  const manifestPath = path.join(backupRoot, 'runtime-state.json');
  const dbRelativePath = path.join('data', 'stock_analysis.db');

  fs.mkdirSync(path.dirname(backupDbPath), { recursive: true });
  fs.mkdirSync(appDir, { recursive: true });
  fs.writeFileSync(path.join(appDir, 'Uninstall Daily Stock Analysis.exe'), '');
  fs.writeFileSync(backupEnvPath, 'backup-env\n', 'utf-8');
  fs.writeFileSync(backupDbPath, 'backup-db');
  fs.writeFileSync(targetEnvPath, 'current-env\n', 'utf-8');
  fs.writeFileSync(
    manifestPath,
    JSON.stringify({ files: ['.env', dbRelativePath] }),
    'utf-8'
  );

  const mainModule = loadMainModule(t, {
    platform: 'win32',
    app: {
      isPackaged: true,
      getPath: (name) => {
        if (name === 'exe') {
          return path.join(appDir, 'Daily Stock Analysis.exe');
        }
        return userDataDir;
      },
    },
  });
  const originalCopyFileSync = fs.copyFileSync;

  fs.copyFileSync = (source, target) => {
    if (source === backupDbPath) {
      throw new Error('target locked');
    }
    return originalCopyFileSync(source, target);
  };

  t.after(() => {
    fs.copyFileSync = originalCopyFileSync;
    fs.rmSync(tempRoot, { recursive: true, force: true });
  });

  const firstRestore = mainModule.restorePackagedRuntimeStateFromBackup();
  assert.deepEqual(firstRestore.restored, ['.env']);
  assert.equal(firstRestore.failed.length, 1);
  assert.equal(fs.readFileSync(targetEnvPath, 'utf-8'), 'backup-env\n');
  assert.deepEqual(JSON.parse(fs.readFileSync(manifestPath, 'utf-8')).files, [dbRelativePath]);

  fs.writeFileSync(targetEnvPath, 'user-change-after-partial-failure\n', 'utf-8');
  const secondRestore = mainModule.restorePackagedRuntimeStateFromBackup();
  assert.deepEqual(secondRestore.restored, []);
  assert.equal(secondRestore.failed.length, 1);
  assert.equal(fs.readFileSync(targetEnvPath, 'utf-8'), 'user-change-after-partial-failure\n');
  assert.deepEqual(JSON.parse(fs.readFileSync(manifestPath, 'utf-8')).files, [dbRelativePath]);
});

test('restorePackagedRuntimeStateFromBackup skips backup when app version did not change', (t) => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dsa-desktop-same-version-restore-'));
  const appDir = path.join(tempRoot, 'app');
  const userDataDir = path.join(tempRoot, 'userData');
  const backupRoot = path.join(userDataDir, '.dsa-desktop-update-backup');
  const backupEnvPath = path.join(backupRoot, '.env');
  const targetEnvPath = path.join(appDir, '.env');
  const manifestPath = path.join(backupRoot, 'runtime-state.json');

  fs.mkdirSync(backupRoot, { recursive: true });
  fs.mkdirSync(appDir, { recursive: true });
  fs.writeFileSync(path.join(appDir, 'Uninstall Daily Stock Analysis.exe'), '');
  fs.writeFileSync(backupEnvPath, 'pre-update-env\n', 'utf-8');
  fs.writeFileSync(targetEnvPath, 'user-change-after-aborted-install\n', 'utf-8');
  fs.writeFileSync(
    manifestPath,
    JSON.stringify({ appVersion: 'v3.12.0', files: ['.env'] }),
    'utf-8'
  );

  const mainModule = loadMainModule(t, {
    platform: 'win32',
    app: {
      isPackaged: true,
      getPath: (name) => {
        if (name === 'exe') {
          return path.join(appDir, 'Daily Stock Analysis.exe');
        }
        return userDataDir;
      },
    },
  });

  t.after(() => {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  });

  const restoreResult = mainModule.restorePackagedRuntimeStateFromBackup();
  assert.deepEqual(restoreResult.restored, []);
  assert.deepEqual(restoreResult.failed, []);
  assert.equal(restoreResult.skipped.length, 1);
  assert.match(restoreResult.skipped[0], /stale backup target 3\.12\.0 was discarded/);
  assert.equal(fs.readFileSync(targetEnvPath, 'utf-8'), 'user-change-after-aborted-install\n');
  assert.equal(fs.existsSync(backupRoot), false);
  assert.equal(fs.existsSync(manifestPath), false);
});

test('createWindow startup path does not throw ReferenceError after restore result handling', async (t) => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dsa-desktop-startup-'));
  const appDir = path.join(tempRoot, 'app');
  const userDataDir = path.join(tempRoot, 'userData');
  const exePath = path.join(appDir, 'Daily Stock Analysis.exe');
  const uninstallPath = path.join(appDir, 'Uninstall Daily Stock Analysis.exe');
  const loadedFiles = [];
  const loadedUrls = [];
  let startupError;
  let updateCheckRequested = false;
  const originalResourcesPathDescriptor = Object.getOwnPropertyDescriptor(process, 'resourcesPath');
  const resourcesPath = path.join(tempRoot, 'resources');
  const backupRoot = path.join(userDataDir, '.dsa-desktop-update-backup');
  const manifestPath = path.join(backupRoot, 'runtime-state.json');

  function fakeBrowserWindow() {
    return {
      isDestroyed: () => false,
      setBackgroundColor: () => undefined,
      once: () => undefined,
      webContents: {
        on: () => undefined,
        setWindowOpenHandler: () => undefined,
        send: () => undefined,
      },
      loadFile: async (file) => {
        loadedFiles.push(file);
        return undefined;
      },
      loadURL: async (url) => {
        loadedUrls.push(url);
        return undefined;
      },
    };
  }

  const fakeBackendProcess = new EventEmitter();
  fakeBackendProcess.pid = 12345;
  fakeBackendProcess.exitCode = null;
  fakeBackendProcess.signalCode = null;
  fakeBackendProcess.stdout = new EventEmitter();
  fakeBackendProcess.stderr = new EventEmitter();

  const fakeWhenReady = () => ({
    then: (handler) => {
      return Promise.resolve()
        .then(() => handler())
        .catch((error) => {
          startupError = error;
        });
    },
  });

  const fakeNet = {
    createServer: () => {
      const server = new EventEmitter();
      server.once = (event, handler) => {
        server.on(event, handler);
        return server;
      };
      server.listen = () => {
        process.nextTick(() => {
          server.emit('listening');
        });
        return server;
      };
      server.close = (callback) => {
        if (callback) {
          process.nextTick(callback);
        }
      };
      return server;
    },
  };

  const fakeHttp = {
    get: (_url, onResponse) => {
      const request = new EventEmitter();
      const response = new EventEmitter();
      request.setTimeout = () => undefined;
      request.destroy = () => undefined;
      response.statusCode = 200;
      response.resume = () => undefined;
      process.nextTick(() => {
        onResponse(response);
      });
      return request;
    },
  };

  if (originalResourcesPathDescriptor) {
    Object.defineProperty(process, 'resourcesPath', {
      ...originalResourcesPathDescriptor,
      value: resourcesPath,
    });
  } else {
    process.resourcesPath = resourcesPath;
  }

  fs.mkdirSync(appDir, { recursive: true });
  fs.mkdirSync(userDataDir, { recursive: true });
  fs.mkdirSync(backupRoot, { recursive: true });
  fs.mkdirSync(path.join(resourcesPath, 'backend', 'stock_analysis'), { recursive: true });
  fs.writeFileSync(exePath, '');
  fs.writeFileSync(uninstallPath, '');
  fs.writeFileSync(path.join(backupRoot, '.env'), 'stale-backup-env\n', 'utf-8');
  fs.writeFileSync(manifestPath, JSON.stringify({ appVersion: '3.12.0', files: ['.env'] }), 'utf-8');
  fs.writeFileSync(path.join(resourcesPath, 'backend', 'stock_analysis', 'stock_analysis.exe'), '');

  const mainModule = loadMainModule(t, {
    platform: 'win32',
    browserWindow: fakeBrowserWindow,
    http: fakeHttp,
    net: fakeNet,
    childProcess: {
      spawn: () => fakeBackendProcess,
    },
    app: {
      isPackaged: true,
      getVersion: () => '3.12.0',
      getPath: (name) => {
        if (name === 'exe') {
          return exePath;
        }
        return userDataDir;
      },
      whenReady: fakeWhenReady,
      on: () => undefined,
      quit: () => undefined,
    },
    electronUpdater: {
      autoDownload: true,
      autoInstallOnAppQuit: false,
      on: () => undefined,
      checkForUpdates: async () => {
        updateCheckRequested = true;
        return undefined;
      },
    },
  });

  await new Promise((resolve) => {
    setTimeout(resolve, 80);
  });

  assert.equal(loadedFiles.length >= 1, true);
  assert.equal(loadedUrls.length >= 1, true);
  assert.match(
    loadedUrls[0],
    /^http:\/\/127\.0\.0\.1:\d+\/\?desktop_version=3\.12\.0&cache_bust=\d+$/
  );
  assert.equal(updateCheckRequested, true);
  assert.equal(startupError, undefined);
  assert.equal(fs.existsSync(backupRoot), false);
  const updateState = await mainModule.__getIpcMainHandler('desktop:get-update-state')();
  assert.notEqual(updateState.status, mainModule.UPDATE_STATUS.ERROR);
  assert.equal(updateState.updateMode, mainModule.UPDATE_MODE.AUTO);

  t.after(() => {
    if (originalResourcesPathDescriptor) {
      Object.defineProperty(process, 'resourcesPath', originalResourcesPathDescriptor);
    } else {
      delete process.resourcesPath;
    }
    fs.rmSync(tempRoot, { recursive: true, force: true });
  });
});

test('stopBackend waits for backend process exit', async (t) => {
  const mainModule = loadMainModule(t);
  const killSignals = [];
  const fakeBackend = new EventEmitter();

  fakeBackend.pid = 4321;
  fakeBackend.killed = false;
  fakeBackend.exitCode = null;
  fakeBackend.signalCode = null;
  fakeBackend.kill = (signal) => {
    killSignals.push(signal);
    fakeBackend.killed = true;
    if (signal === 'SIGTERM' || signal === 'SIGKILL') {
      process.nextTick(() => {
        fakeBackend.exitCode = 0;
        fakeBackend.emit('exit', 0, null);
      });
    }
  };

  mainModule.__setBackendProcessForTest(fakeBackend);

  t.after(() => {
    mainModule.__setBackendProcessForTest(null);
  });

  await Promise.race([
    mainModule.stopBackend(),
    new Promise((_, reject) => setTimeout(() => reject(new Error('stopBackend did not resolve')), 200)),
  ]);

  assert.equal(killSignals.includes('SIGTERM'), true);
});
