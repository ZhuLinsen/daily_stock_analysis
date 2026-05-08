const { app, BrowserWindow, dialog, ipcMain, shell, nativeTheme } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const net = require('net');
const http = require('http');
const https = require('https');
const { TextDecoder } = require('util');

let mainWindow = null;
let backendProcess = null;
let logFilePath = null;
let backendStartError = null;
let desktopUpdateState = null;
let lastNotifiedUpdateVersion = '';

function resolveWindowBackgroundColor() {
  return nativeTheme.shouldUseDarkColors ? '#08080c' : '#f4f7fb';
}

const isWindows = process.platform === 'win32';
const appRootDev = path.resolve(__dirname, '..', '..');
const GITHUB_OWNER = 'ZhuLinsen';
const GITHUB_REPO = 'daily_stock_analysis';
const RELEASES_PAGE_URL = `https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/releases`;
const LATEST_RELEASE_API_URL = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/latest`;
const DEFAULT_REQUEST_TIMEOUT_MS = 5000;

const UPDATE_STATUS = Object.freeze({
  IDLE: 'idle',
  CHECKING: 'checking',
  UP_TO_DATE: 'up-to-date',
  UPDATE_AVAILABLE: 'update-available',
  ERROR: 'error',
});

function normalizeVersionString(version) {
  return String(version || '')
    .trim()
    .replace(/^v/i, '')
    .replace(/\+.*$/, '');
}

function parseSemver(version) {
  const normalized = normalizeVersionString(version);
  const match = normalized.match(/^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/);
  if (!match) {
    return null;
  }

  return {
    major: Number.parseInt(match[1], 10),
    minor: Number.parseInt(match[2], 10),
    patch: Number.parseInt(match[3], 10),
    prerelease: match[4] ? match[4].split('.') : [],
  };
}

function comparePrereleaseIdentifiers(left, right) {
  const leftIsNumeric = /^\d+$/.test(left);
  const rightIsNumeric = /^\d+$/.test(right);

  if (leftIsNumeric && rightIsNumeric) {
    const leftNumber = Number.parseInt(left, 10);
    const rightNumber = Number.parseInt(right, 10);
    if (leftNumber === rightNumber) {
      return 0;
    }
    return leftNumber > rightNumber ? 1 : -1;
  }

  if (leftIsNumeric !== rightIsNumeric) {
    return leftIsNumeric ? -1 : 1;
  }

  if (left === right) {
    return 0;
  }
  return left > right ? 1 : -1;
}

function compareVersions(leftVersion, rightVersion) {
  const left = parseSemver(leftVersion);
  const right = parseSemver(rightVersion);
  if (!left || !right) {
    return null;
  }

  for (const key of ['major', 'minor', 'patch']) {
    if (left[key] !== right[key]) {
      return left[key] > right[key] ? 1 : -1;
    }
  }

  if (!left.prerelease.length && !right.prerelease.length) {
    return 0;
  }
  if (!left.prerelease.length) {
    return 1;
  }
  if (!right.prerelease.length) {
    return -1;
  }

  const length = Math.max(left.prerelease.length, right.prerelease.length);
  for (let index = 0; index < length; index += 1) {
    const leftPart = left.prerelease[index];
    const rightPart = right.prerelease[index];
    if (leftPart === undefined) {
      return -1;
    }
    if (rightPart === undefined) {
      return 1;
    }

    const compared = comparePrereleaseIdentifiers(leftPart, rightPart);
    if (compared !== 0) {
      return compared;
    }
  }

  return 0;
}

function buildUpdateState(state = {}) {
  return {
    status: state.status || UPDATE_STATUS.IDLE,
    currentVersion: normalizeVersionString(state.currentVersion),
    latestVersion: normalizeVersionString(state.latestVersion),
    releaseUrl:
      typeof state.releaseUrl === 'string' && state.releaseUrl.trim()
        ? state.releaseUrl.trim()
        : RELEASES_PAGE_URL,
    checkedAt: typeof state.checkedAt === 'string' ? state.checkedAt : '',
    publishedAt: typeof state.publishedAt === 'string' ? state.publishedAt : '',
    message: typeof state.message === 'string' ? state.message : '',
    releaseName: typeof state.releaseName === 'string' ? state.releaseName : '',
    tagName: typeof state.tagName === 'string' ? state.tagName : '',
  };
}

function extractReleaseMetadata(release) {
  if (!release || typeof release !== 'object') {
    return null;
  }

  const tagName = typeof release.tag_name === 'string' ? release.tag_name.trim() : '';
  const version = normalizeVersionString(tagName);
  if (!parseSemver(version)) {
    return null;
  }

  return {
    tagName,
    version,
    releaseName: typeof release.name === 'string' ? release.name.trim() : '',
    releaseUrl:
      typeof release.html_url === 'string' && release.html_url.trim()
        ? release.html_url.trim()
        : RELEASES_PAGE_URL,
    publishedAt: typeof release.published_at === 'string' ? release.published_at : '',
  };
}

function evaluateReleaseUpdate({ currentVersion, release, checkedAt = new Date().toISOString() }) {
  const normalizedCurrentVersion = normalizeVersionString(currentVersion);
  if (!parseSemver(normalizedCurrentVersion)) {
    return buildUpdateState({
      status: UPDATE_STATUS.ERROR,
      currentVersion: normalizedCurrentVersion,
      checkedAt,
      message: '当前桌面端版本不是有效的语义化版本，无法检查更新。',
    });
  }

  const releaseMetadata = extractReleaseMetadata(release);
  if (!releaseMetadata) {
    return buildUpdateState({
      status: UPDATE_STATUS.ERROR,
      currentVersion: normalizedCurrentVersion,
      checkedAt,
      message: 'GitHub Release 未返回可识别的语义化版本标签。',
    });
  }

  const compared = compareVersions(normalizedCurrentVersion, releaseMetadata.version);
  if (compared === null) {
    return buildUpdateState({
      status: UPDATE_STATUS.ERROR,
      currentVersion: normalizedCurrentVersion,
      latestVersion: releaseMetadata.version,
      releaseUrl: releaseMetadata.releaseUrl,
      checkedAt,
      releaseName: releaseMetadata.releaseName,
      tagName: releaseMetadata.tagName,
      message: '版本比较失败，无法判断是否存在可用更新。',
    });
  }

  if (compared < 0) {
    return buildUpdateState({
      status: UPDATE_STATUS.UPDATE_AVAILABLE,
      currentVersion: normalizedCurrentVersion,
      latestVersion: releaseMetadata.version,
      releaseUrl: releaseMetadata.releaseUrl,
      checkedAt,
      publishedAt: releaseMetadata.publishedAt,
      releaseName: releaseMetadata.releaseName,
      tagName: releaseMetadata.tagName,
      message: `发现新版本 ${releaseMetadata.version}，可前往 GitHub Releases 下载更新。`,
    });
  }

  return buildUpdateState({
    status: UPDATE_STATUS.UP_TO_DATE,
    currentVersion: normalizedCurrentVersion,
    latestVersion: releaseMetadata.version,
    releaseUrl: releaseMetadata.releaseUrl,
    checkedAt,
    publishedAt: releaseMetadata.publishedAt,
    releaseName: releaseMetadata.releaseName,
    tagName: releaseMetadata.tagName,
    message: '当前桌面端已是最新版本。',
  });
}

function fetchLatestReleaseJson({
  requestUrl = LATEST_RELEASE_API_URL,
  timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
  request = https.request,
} = {}) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let response = null;

    const cleanupResponseListeners = () => {
      if (!response) {
        return;
      }
      response.removeAllListeners('data');
      response.removeAllListeners('end');
      response.removeAllListeners('error');
      response.removeAllListeners('aborted');
      response.removeAllListeners('close');
    };

    const finishWithError = (error) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanupResponseListeners();
      if (!req.destroyed) {
        req.destroy();
      }
      reject(error instanceof Error ? error : new Error(String(error)));
    };

    const finishWithResult = (value) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanupResponseListeners();
      resolve(value);
    };

    const req = request(
      requestUrl,
      {
        method: 'GET',
        headers: {
          Accept: 'application/vnd.github+json',
          'User-Agent': 'daily-stock-analysis-desktop',
        },
      },
      (incomingResponse) => {
        response = incomingResponse;
        const chunks = [];

        response.on('data', (chunk) => {
          chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)));
        });

        response.on('end', () => {
          if (settled) {
            return;
          }
          const body = Buffer.concat(chunks).toString('utf-8');
          if (response.statusCode !== 200) {
            finishWithError(new Error(`GitHub API responded with status ${response.statusCode || 'unknown'}`));
            return;
          }

          try {
            finishWithResult(JSON.parse(body));
          } catch (_error) {
            finishWithError(new Error('Failed to parse GitHub release response.'));
          }
        });

        response.on('error', (error) => {
          finishWithError(error);
        });
        response.on('aborted', () => {
          finishWithError(new Error('GitHub API response was aborted.'));
        });
        response.on('close', () => {
          if (!response.complete) {
            finishWithError(new Error('GitHub API response closed before completion.'));
          }
        });
      }
    );

    req.setTimeout(timeoutMs, () => {
      req.destroy(new Error(`GitHub API timeout after ${timeoutMs}ms`));
    });
    req.on('error', finishWithError);
    req.end();
  });
}

async function checkForDesktopUpdates({
  currentVersion,
  timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
  fetchLatestRelease = fetchLatestReleaseJson,
} = {}) {
  const release = await fetchLatestRelease({ timeoutMs });
  return evaluateReleaseUpdate({ currentVersion, release });
}

desktopUpdateState = buildUpdateState();

function resolveEnvExamplePath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, '.env.example');
  }
  return path.join(appRootDev, '.env.example');
}

function resolveAppDir() {
  if (app.isPackaged) {
    // exe 所在目录
    return path.dirname(app.getPath('exe'));
  }
  return app.getPath('userData');
}

function resolveBackendPath() {
  if (process.env.DSA_BACKEND_PATH) {
    return process.env.DSA_BACKEND_PATH;
  }

  if (app.isPackaged) {
    const backendDir = path.join(process.resourcesPath, 'backend');
    const exeName = isWindows ? 'stock_analysis.exe' : 'stock_analysis';
    const oneDirPath = path.join(backendDir, 'stock_analysis', exeName);
    if (fs.existsSync(oneDirPath)) {
      return oneDirPath;
    }
    return path.join(backendDir, exeName);
  }

  return null;
}

function initLogging() {
  const appDir = app.isPackaged ? path.dirname(app.getPath('exe')) : app.getPath('userData');
  logFilePath = path.join(appDir, 'logs', 'desktop.log');
  
  // 确保日志目录存在
  const logDir = path.dirname(logFilePath);
  if (!fs.existsSync(logDir)) {
    fs.mkdirSync(logDir, { recursive: true });
  }
  
  logLine('Desktop app starting');
}

function logLine(message) {
  const timestamp = new Date().toISOString();
  const line = `[${timestamp}] ${message}\n`;
  try {
    if (logFilePath) {
      fs.appendFileSync(logFilePath, line, 'utf-8');
    }
  } catch (error) {
    console.error(error);
  }
  console.log(line.trim());
}

function decodeBackendOutput(data, decoder) {
  if (typeof data === 'string') {
    return data.trim();
  }
  if (!Buffer.isBuffer(data)) {
    return String(data).trim();
  }

  let decoded = decoder.decode(data, { stream: true });

  // Windows 控制台 / 子进程有时仍会吐出本地代码页字节，优先在明显乱码时回退到 GBK。
  if (isWindows && decoded.includes('\uFFFD')) {
    try {
      decoded = new TextDecoder('gbk', { fatal: false }).decode(data, { stream: true });
    } catch (_error) {
    }
  }

  return decoded.trim();
}

function formatCommand(command, args = []) {
  return [command, ...args]
    .map((part) => {
      const value = String(part);
      return value.includes(' ') ? `"${value}"` : value;
    })
    .join(' ');
}

function resolvePythonPath() {
  return process.env.DSA_PYTHON || 'python';
}

function ensureEnvFile(envPath) {
  if (fs.existsSync(envPath)) {
    return;
  }

  const envExample = resolveEnvExamplePath();
  if (fs.existsSync(envExample)) {
    fs.copyFileSync(envExample, envPath);
    return;
  }

  fs.writeFileSync(envPath, '# Configure your API keys and stock list here.\n', 'utf-8');
}

function findAvailablePort(startPort = 8000, endPort = 8100) {
  return new Promise((resolve, reject) => {
    const tryPort = (port) => {
      if (port > endPort) {
        reject(new Error('No available port'));
        return;
      }

      const server = net.createServer();
      server.once('error', () => {
        tryPort(port + 1);
      });
      server.once('listening', () => {
        server.close(() => resolve(port));
      });
      server.listen(port, '127.0.0.1');
    };

    tryPort(startPort);
  });
}

function waitForHealth(
  url,
  timeoutMs = 60000,
  intervalMs = 250,
  requestTimeoutMs = 1500,
  shouldAbort = null,
  onProgress = null
) {
  const start = Date.now();
  let attempts = 0;

  return new Promise((resolve, reject) => {
    let settled = false;
    let retryTimer = null;
    let activeRequest = null;

    const emitProgress = (payload) => {
      if (typeof onProgress !== 'function') {
        return;
      }
      try {
        onProgress(payload);
      } catch (_error) {
      }
    };

    const finish = (error, result) => {
      if (settled) {
        return;
      }
      settled = true;

      if (retryTimer) {
        clearTimeout(retryTimer);
        retryTimer = null;
      }

      if (activeRequest && !activeRequest.destroyed) {
        activeRequest.destroy();
      }

      if (error) {
        emitProgress({
          type: 'final_error',
          elapsedMs: Date.now() - start,
          attempts,
          message: error.message,
        });
      }

      if (error) {
        reject(error);
      } else {
        resolve(result);
      }
    };

    const scheduleNext = () => {
      if (settled) {
        return;
      }
      retryTimer = setTimeout(attempt, intervalMs);
    };

    const attempt = () => {
      if (settled) {
        return;
      }

      if (typeof shouldAbort === 'function') {
        const abortReason = shouldAbort();
        if (abortReason) {
          emitProgress({
            type: 'aborted',
            elapsedMs: Date.now() - start,
            attempts,
            reason: abortReason,
          });
          finish(new Error(`Health check aborted: ${abortReason}`));
          return;
        }
      }

      const elapsedMs = Date.now() - start;
      if (elapsedMs > timeoutMs) {
        emitProgress({
          type: 'total_timeout',
          elapsedMs,
          attempts,
          timeoutMs,
        });
        finish(new Error(`Health check timeout after ${elapsedMs}ms`));
        return;
      }

      attempts += 1;
      emitProgress({
        type: 'probe_start',
        elapsedMs,
        attempts,
      });

      activeRequest = http.get(url, (res) => {
        if (settled) {
          return;
        }

        res.resume();
        if (res.statusCode === 200) {
          const readyElapsedMs = Date.now() - start;
          emitProgress({
            type: 'ready',
            elapsedMs: readyElapsedMs,
            attempts,
          });
          finish(null, { elapsedMs: readyElapsedMs, attempts });
          return;
        }

        emitProgress({
          type: 'probe_status',
          elapsedMs: Date.now() - start,
          attempts,
          statusCode: res.statusCode,
        });
        scheduleNext();
      });

      activeRequest.setTimeout(requestTimeoutMs, () => {
        emitProgress({
          type: 'probe_timeout',
          elapsedMs: Date.now() - start,
          attempts,
          requestTimeoutMs,
        });
        activeRequest.destroy(new Error(`Health probe request timeout after ${requestTimeoutMs}ms`));
      });

      activeRequest.on('error', (error) => {
        if (settled) {
          return;
        }

        emitProgress({
          type: 'probe_error',
          elapsedMs: Date.now() - start,
          attempts,
          errorCode: error.code || 'unknown',
          errorMessage: error.message,
        });
        scheduleNext();
      });
    };

    attempt();
  });
}

function startBackend({ port, envFile, dbPath, logDir }) {
  const backendPath = resolveBackendPath();
  backendStartError = null;
  const launchStartedAt = Date.now();

  const env = {
    ...process.env,
    DSA_DESKTOP_MODE: 'true',
    ENV_FILE: envFile,
    DATABASE_PATH: dbPath,
    LOG_DIR: logDir,
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
    SCHEDULE_ENABLED: 'false',
    WEBUI_ENABLED: 'false',
    BOT_ENABLED: 'false',
    DINGTALK_STREAM_ENABLED: 'false',
    FEISHU_STREAM_ENABLED: 'false',
  };

  const args = ['--serve-only', '--host', '127.0.0.1', '--port', String(port)];
  let launchMode = '';
  let launchCommand = '';
  let launchCwd = '';

  if (backendPath) {
    if (!fs.existsSync(backendPath)) {
      throw new Error(`Backend executable not found: ${backendPath}`);
    }
    launchMode = 'packaged';
    launchCommand = formatCommand(backendPath, args);
    launchCwd = path.dirname(backendPath);
    backendProcess = spawn(backendPath, args, {
      env,
      cwd: launchCwd,
      stdio: 'pipe',
      windowsHide: true,
    });
  } else {
    const pythonPath = resolvePythonPath();
    const scriptPath = path.join(appRootDev, 'main.py');
    const pythonArgs = ['-X', 'utf8', scriptPath, ...args];
    launchMode = 'development';
    launchCommand = formatCommand(pythonPath, pythonArgs);
    launchCwd = appRootDev;
    backendProcess = spawn(pythonPath, pythonArgs, {
      env,
      cwd: launchCwd,
      stdio: 'pipe',
      windowsHide: true,
    });
  }

  if (backendProcess) {
    let firstStdoutLogged = false;
    let firstStderrLogged = false;
    const stdoutDecoder = new TextDecoder('utf-8', { fatal: false });
    const stderrDecoder = new TextDecoder('utf-8', { fatal: false });

    backendProcess.once('spawn', () => {
      logLine(`[backend] spawned pid=${backendProcess.pid} in ${Date.now() - launchStartedAt}ms`);
    });
    backendProcess.on('error', (error) => {
      backendStartError = error;
      logLine(`[backend] failed to start: ${error.message}`);
    });
    backendProcess.stdout.on('data', (data) => {
      if (!firstStdoutLogged) {
        firstStdoutLogged = true;
        logLine(`[backend] first stdout after ${Date.now() - launchStartedAt}ms`);
      }
      logLine(`[backend] ${decodeBackendOutput(data, stdoutDecoder)}`);
    });
    backendProcess.stderr.on('data', (data) => {
      if (!firstStderrLogged) {
        firstStderrLogged = true;
        logLine(`[backend] first stderr after ${Date.now() - launchStartedAt}ms`);
      }
      logLine(`[backend] ${decodeBackendOutput(data, stderrDecoder)}`);
    });
    backendProcess.on('exit', (code, signal) => {
      logLine(`[backend] exited with code ${code}, signal ${signal || 'none'}`);
    });
  }

  return {
    mode: launchMode,
    command: launchCommand,
    cwd: launchCwd,
  };
}

function stopBackend() {
  if (!backendProcess || backendProcess.killed) {
    return;
  }

  if (isWindows) {
    spawn('taskkill', ['/PID', String(backendProcess.pid), '/T', '/F']);
    return;
  }

  backendProcess.kill('SIGTERM');
  setTimeout(() => {
    if (!backendProcess.killed) {
      backendProcess.kill('SIGKILL');
    }
  }, 3000);
}

function resolveDesktopVersion() {
  return String(app.getVersion() || '').trim();
}

function sanitizeReleaseUrl(candidateUrl) {
  if (typeof candidateUrl !== 'string' || !candidateUrl.trim()) {
    return RELEASES_PAGE_URL;
  }

  try {
    const parsed = new URL(candidateUrl.trim());
    const allowedReleasePathPrefix = `/${GITHUB_OWNER}/${GITHUB_REPO}/releases`;
    const isGithubHost = parsed.origin === 'https://github.com';
    const isRepositoryReleasePath =
      parsed.pathname === allowedReleasePathPrefix ||
      parsed.pathname.startsWith(`${allowedReleasePathPrefix}/`);
    return isGithubHost && isRepositoryReleasePath ? parsed.toString() : RELEASES_PAGE_URL;
  } catch (_error) {
    return RELEASES_PAGE_URL;
  }
}

function broadcastDesktopUpdateState() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.webContents.send('desktop:update-state', desktopUpdateState);
}

function setDesktopUpdateState(nextState) {
  desktopUpdateState = buildUpdateState({
    currentVersion: resolveDesktopVersion(),
    ...nextState,
  });
  broadcastDesktopUpdateState();
  return desktopUpdateState;
}

async function maybePromptDesktopUpdate(state) {
  if (!state || state.status !== UPDATE_STATUS.UPDATE_AVAILABLE) {
    return;
  }
  if (!state.latestVersion || state.latestVersion === lastNotifiedUpdateVersion) {
    return;
  }
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }

  lastNotifiedUpdateVersion = state.latestVersion;
  const currentVersion = state.currentVersion || resolveDesktopVersion() || '当前版本';
  const result = await dialog.showMessageBox(mainWindow, {
    type: 'info',
    buttons: ['稍后', '前往下载'],
    defaultId: 1,
    cancelId: 0,
    title: '发现新版本',
    message: `检测到桌面端新版本 ${state.latestVersion}`,
    detail: `当前版本 ${currentVersion}。新版本将跳转到 GitHub Releases 下载页，不会静默下载或自动安装。`,
    noLink: true,
  });

  if (result.response === 1) {
    await shell.openExternal(sanitizeReleaseUrl(state.releaseUrl));
  }
}

async function performDesktopUpdateCheck({ manual = false, notify = false } = {}) {
  const currentVersion = resolveDesktopVersion();
  setDesktopUpdateState({
    status: UPDATE_STATUS.CHECKING,
    currentVersion,
    message: manual ? '正在检查桌面端更新...' : '正在后台检查桌面端更新...',
  });

  try {
    const nextState = await checkForDesktopUpdates({ currentVersion });
    const resolvedState = setDesktopUpdateState(nextState);
    logLine(
      `[update] status=${resolvedState.status} current=${resolvedState.currentVersion || 'unknown'} latest=${resolvedState.latestVersion || 'unknown'}`
    );
    if (notify) {
      await maybePromptDesktopUpdate(resolvedState);
    }
    return resolvedState;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    logLine(`[update] check failed: ${message}`);

    if (manual) {
      return setDesktopUpdateState({
        status: UPDATE_STATUS.ERROR,
        currentVersion,
        checkedAt: new Date().toISOString(),
        message: `检查更新失败：${message}`,
      });
    }

    return setDesktopUpdateState({
      status: UPDATE_STATUS.IDLE,
      currentVersion,
      checkedAt: new Date().toISOString(),
      message: '',
    });
  }
}

ipcMain.handle('desktop:get-update-state', () => desktopUpdateState);
ipcMain.handle('desktop:check-for-updates', () => performDesktopUpdateCheck({ manual: true }));
ipcMain.handle('desktop:open-release-page', async (_event, releaseUrl) => {
  await shell.openExternal(sanitizeReleaseUrl(releaseUrl));
  return true;
});

async function createWindow() {
  initLogging();
  setDesktopUpdateState({
    status: UPDATE_STATUS.IDLE,
    currentVersion: resolveDesktopVersion(),
    message: '',
  });
  const startupStartedAt = Date.now();
  const logStartup = (message) => {
    logLine(`[startup +${Date.now() - startupStartedAt}ms] ${message}`);
  };

  logStartup('createWindow started');

  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 960,
    minHeight: 640,
    backgroundColor: resolveWindowBackgroundColor(),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      additionalArguments: [`--dsa-desktop-version=${app.getVersion()}`],
    },
  });
  logStartup('BrowserWindow created');

  const loadingPath = path.join(__dirname, 'renderer', 'loading.html');
  const loadingPageStartedAt = Date.now();
  await mainWindow.loadFile(loadingPath);
  logStartup(`Loading page rendered in ${Date.now() - loadingPageStartedAt}ms`);

  const applyThemeBackground = () => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return;
    }
    mainWindow.setBackgroundColor(resolveWindowBackgroundColor());
  };
  nativeTheme.on('updated', applyThemeBackground);
  mainWindow.once('closed', () => {
    nativeTheme.removeListener('updated', applyThemeBackground);
  });

  const webViewStartedAt = Date.now();
  mainWindow.webContents.on('did-start-loading', () => {
    logStartup('WebContents did-start-loading');
  });
  mainWindow.webContents.on('dom-ready', () => {
    logStartup(`WebContents dom-ready (+${Date.now() - webViewStartedAt}ms after events attached)`);
  });
  mainWindow.webContents.on('did-finish-load', () => {
    logStartup(`WebContents did-finish-load (+${Date.now() - webViewStartedAt}ms after events attached)`);
  });
  mainWindow.webContents.on(
    'did-fail-load',
    (_event, errorCode, errorDescription, validatedURL, isMainFrame) => {
      logStartup(
        `WebContents did-fail-load code=${errorCode} mainFrame=${isMainFrame} url=${validatedURL} reason=${errorDescription}`
      );
    }
  );

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  const appDir = resolveAppDir();
  const envPath = path.join(appDir, '.env');
  ensureEnvFile(envPath);
  logStartup(`Env file ready: ${envPath}`);

  const portFindStartedAt = Date.now();
  const port = await findAvailablePort(8000, 8100);
  logStartup(`Using port ${port} (selected in ${Date.now() - portFindStartedAt}ms)`);
  logStartup(`App directory=${appDir}`);

  const dbPath = path.join(appDir, 'data', 'stock_analysis.db');
  const logDir = path.join(appDir, 'logs');

  try {
    const launchInfo = startBackend({ port, envFile: envPath, dbPath, logDir });
    logStartup(`Backend launch mode=${launchInfo.mode}`);
    logStartup(`Backend launch command=${launchInfo.command}`);
    logStartup(`Backend launch cwd=${launchInfo.cwd}`);
    logStartup('Waiting for backend health check');
  } catch (error) {
    logStartup(`Backend launch failed: ${String(error)}`);
    const errorUrl = `file://${loadingPath}?error=${encodeURIComponent(String(error))}`;
    await mainWindow.loadURL(errorUrl);
    return;
  }

  const healthUrl = `http://127.0.0.1:${port}/api/health`;
  let lastHealthProgressLogAt = 0;
  const healthProgressLogIntervalMs = 2000;

  const onHealthProgress = (event) => {
    if (!event || event.type === 'probe_start') {
      return;
    }

    if (event.type === 'ready') {
      logStartup(`Health ready in ${event.elapsedMs}ms (attempts=${event.attempts})`);
      return;
    }

    if (event.type === 'aborted' || event.type === 'total_timeout' || event.type === 'final_error') {
      const details = event.reason || event.message || '';
      logStartup(`Health ${event.type} after ${event.elapsedMs}ms (attempts=${event.attempts}) ${details}`.trim());
      return;
    }

    const now = Date.now();
    if (now - lastHealthProgressLogAt < healthProgressLogIntervalMs) {
      return;
    }

    lastHealthProgressLogAt = now;
    let detail = '';
    if (event.type === 'probe_status') {
      detail = `status=${event.statusCode}`;
    } else if (event.type === 'probe_timeout') {
      detail = `probeTimeout=${event.requestTimeoutMs}ms`;
    } else if (event.type === 'probe_error') {
      detail = `error=${event.errorCode}:${event.errorMessage}`;
    }

    logStartup(
      `Waiting for backend health... elapsed=${event.elapsedMs}ms attempts=${event.attempts}${detail ? ` ${detail}` : ''}`
    );
  };

  try {
    const healthInfo = await waitForHealth(
      healthUrl,
      60000,
      250,
      1500,
      () => {
        if (backendStartError) {
          return `backend start error: ${backendStartError.message}`;
        }
        if (!backendProcess) {
          return 'backend process is unavailable';
        }
        if (backendProcess.exitCode !== null) {
          return `backend exited with code ${backendProcess.exitCode}`;
        }
        if (backendProcess.signalCode) {
          return `backend exited by signal ${backendProcess.signalCode}`;
        }
        return null;
      },
      onHealthProgress
    );
    logStartup(`Backend ready in ${healthInfo.elapsedMs}ms (${healthInfo.attempts} probes)`);
    const mainPageStartedAt = Date.now();
    await mainWindow.loadURL(`http://127.0.0.1:${port}/`);
    logStartup(`Main page loadURL resolved in ${Date.now() - mainPageStartedAt}ms`);
    logStartup(`Main UI loaded in ${Date.now() - startupStartedAt}ms`);
    void performDesktopUpdateCheck({ notify: true });
  } catch (error) {
    logStartup(`Startup failed while waiting for health: ${String(error)}`);
    const errorUrl = `file://${loadingPath}?error=${encodeURIComponent(String(error))}`;
    await mainWindow.loadURL(errorUrl);
  }
}

app.whenReady().then(createWindow);

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

app.on('window-all-closed', () => {
  stopBackend();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  stopBackend();
});

module.exports = {
  DEFAULT_REQUEST_TIMEOUT_MS,
  GITHUB_OWNER,
  GITHUB_REPO,
  LATEST_RELEASE_API_URL,
  RELEASES_PAGE_URL,
  UPDATE_STATUS,
  buildUpdateState,
  checkForDesktopUpdates,
  compareVersions,
  evaluateReleaseUpdate,
  extractReleaseMetadata,
  fetchLatestReleaseJson,
  normalizeVersionString,
  parseSemver,
  sanitizeReleaseUrl,
};
