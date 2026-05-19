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
let lastPromptedInstallVersion = '';
let electronAutoUpdater = undefined;
let electronAutoUpdaterConfigured = false;
let electronUpdateCheckInFlight = false;

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
const DESKTOP_UPDATE_BACKUP_DIR = '.dsa-desktop-update-backup';
const DESKTOP_UPDATE_BACKUP_MANIFEST_FILE = 'runtime-state.json';
const DESKTOP_UPDATE_RUNTIME_RELATIVE_FILES = Object.freeze([
  '.env',
  path.join('data', 'stock_analysis.db'),
  path.join('data', 'stock_analysis.db-wal'),
  path.join('data', 'stock_analysis.db-shm'),
  path.join('logs', 'desktop.log'),
]);

const UPDATE_STATUS = Object.freeze({
  IDLE: 'idle',
  CHECKING: 'checking',
  UP_TO_DATE: 'up-to-date',
  UPDATE_AVAILABLE: 'update-available',
  DOWNLOADING: 'downloading',
  UPDATE_DOWNLOADED: 'update-downloaded',
  INSTALLING: 'installing',
  ERROR: 'error',
});

const UPDATE_MODE = Object.freeze({
  AUTO: 'auto',
  MANUAL: 'manual',
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

function normalizeFiniteNumber(value, fallback = null) {
  if (value === null || value === undefined || value === '') {
    return fallback;
  }
  const numberValue = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(numberValue) ? numberValue : fallback;
}

function normalizeDownloadPercent(value) {
  const percent = normalizeFiniteNumber(value);
  if (percent === null) {
    return null;
  }
  return Math.min(100, Math.max(0, Math.round(percent * 10) / 10));
}

function buildUpdateState(state = {}) {
  return {
    status: state.status || UPDATE_STATUS.IDLE,
    updateMode: state.updateMode === UPDATE_MODE.AUTO ? UPDATE_MODE.AUTO : UPDATE_MODE.MANUAL,
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
    downloadPercent: normalizeDownloadPercent(state.downloadPercent),
    downloadedBytes: normalizeFiniteNumber(state.downloadedBytes),
    totalBytes: normalizeFiniteNumber(state.totalBytes),
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

function resolveUpdateBackupRoot() {
  return path.join(app.getPath('userData'), DESKTOP_UPDATE_BACKUP_DIR);
}

function resolveUpdateBackupManifestPath() {
  return path.join(resolveUpdateBackupRoot(), DESKTOP_UPDATE_BACKUP_MANIFEST_FILE);
}

function resolveRuntimeFileEntries(baseDir = resolveAppDir()) {
  return DESKTOP_UPDATE_RUNTIME_RELATIVE_FILES.map((relativePath) => ({
    relativePath,
    absolutePath: path.join(baseDir, relativePath),
    backupPath: path.join(resolveUpdateBackupRoot(), relativePath),
  }));
}

function readUpdateBackupManifest() {
  const manifestPath = resolveUpdateBackupManifestPath();
  if (!fs.existsSync(manifestPath)) {
    return null;
  }

  try {
    const manifestText = fs.readFileSync(manifestPath, 'utf-8');
    const manifest = JSON.parse(manifestText);
    if (!manifest || typeof manifest !== 'object') {
      return null;
    }
    return manifest;
  } catch (_error) {
    return null;
  }
}

function writeUpdateBackupManifest(manifest) {
  ensureDirectory(resolveUpdateBackupRoot());
  fs.writeFileSync(resolveUpdateBackupManifestPath(), JSON.stringify(manifest, null, 2), 'utf-8');
}

function cleanupUpdateBackupRoot() {
  try {
    fs.rmSync(resolveUpdateBackupRoot(), { recursive: true, force: true });
  } catch (_error) {
  }
}

function normalizeBackupFileList(manifest) {
  if (manifest && Array.isArray(manifest.files) && manifest.files.length) {
    return manifest.files.filter((item) => typeof item === 'string' && item.trim()).map((item) => item.trim());
  }
  return DESKTOP_UPDATE_RUNTIME_RELATIVE_FILES.slice();
}

function backupPackagedRuntimeState() {
  if (!isWindowsNsisInstalledApp()) {
    return;
  }

  const runtimeEntries = resolveRuntimeFileEntries();
  const backedUpFiles = [];

  cleanupUpdateBackupRoot();
  ensureDirectory(resolveUpdateBackupRoot());

  runtimeEntries.forEach(({ relativePath, absolutePath, backupPath }) => {
    if (!fs.existsSync(absolutePath)) {
      return;
    }
    ensureDirectory(path.dirname(backupPath));
    fs.copyFileSync(absolutePath, backupPath);
    backedUpFiles.push(relativePath);
  });

  if (!backedUpFiles.length) {
    return;
  }

  writeUpdateBackupManifest({
    backedAt: new Date().toISOString(),
    appVersion: resolveDesktopVersion(),
    files: backedUpFiles,
  });
}

function restorePackagedRuntimeStateFromBackup() {
  const result = {
    backupRoot: null,
    restored: [],
    failed: [],
    skipped: [],
  };

  if (!isWindowsNsisInstalledApp()) {
    return result;
  }

  const manifest = readUpdateBackupManifest();
  if (!manifest) {
    return result;
  }

  const backupRoot = resolveUpdateBackupRoot();
  result.backupRoot = backupRoot;
  const backupAppVersion = normalizeVersionString(manifest.appVersion);
  const currentAppVersion = normalizeVersionString(resolveDesktopVersion());
  const versionComparison = backupAppVersion && currentAppVersion
    ? compareVersions(backupAppVersion, currentAppVersion)
    : null;
  const isSameAppVersion = Boolean(
    backupAppVersion &&
    currentAppVersion &&
    (versionComparison === 0 || (versionComparison === null && backupAppVersion === currentAppVersion))
  );
  if (isSameAppVersion) {
    const reason = `stale backup target ${backupAppVersion} was discarded because current version did not change`;
    result.skipped.push(reason);
    cleanupUpdateBackupRoot();
    logLine(`[update] discarded runtime restore backup because app version did not change after update attempt: ${currentAppVersion}`);
    return result;
  }

  const appDir = resolveAppDir();
  const runtimeEntries = resolveRuntimeFileEntries(appDir);
  const relativeFiles = normalizeBackupFileList(manifest);
  const failedRelativeFiles = [];

  try {
    relativeFiles.forEach((relativePath) => {
      try {
        const entry = runtimeEntries.find((candidate) => candidate.relativePath === relativePath);
        const source = path.join(backupRoot, relativePath);
        const target = entry ? entry.absolutePath : path.join(appDir, relativePath);
        if (!fs.existsSync(source)) {
          return;
        }
        ensureDirectory(path.dirname(target));
        fs.copyFileSync(source, target);
        result.restored.push(relativePath);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        failedRelativeFiles.push(relativePath);
        result.failed.push(`${relativePath} (${message})`);
      }
    });
  } finally {
    if (!result.failed.length) {
      cleanupUpdateBackupRoot();
    } else {
      try {
        writeUpdateBackupManifest({
          ...manifest,
          files: failedRelativeFiles,
          lastRestoreFailedAt: new Date().toISOString(),
        });
      } catch (error) {
        logLine(`[update] failed to rewrite pending restore manifest: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
  }

  if (result.restored.length) {
    console.log(`[update] restored runtime files from backup: ${result.restored.join(', ')}`);
  }
  if (result.failed.length) {
    logLine(`[update] skipped runtime restore files after copy failure: ${result.failed.join(', ')}`);
  }
  if (result.skipped.length) {
    logLine(`[update] skipped runtime restore: ${result.skipped.join(', ')}`);
  }

  return result;
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

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function ensureDirectory(dirPath) {
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true });
  }
}

function initLogging() {
  const appDir = app.isPackaged ? path.dirname(app.getPath('exe')) : app.getPath('userData');
  logFilePath = path.join(appDir, 'logs', 'desktop.log');
  
  // 确保日志目录存在
  const logDir = path.dirname(logFilePath);
  ensureDirectory(logDir);
  
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

function waitForBackendExit(processRef, timeoutMs = 5000) {
  if (!processRef || processRef.exitCode !== null || processRef.signalCode) {
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    let settled = false;
    let timer = null;

    const done = () => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      processRef.removeListener('exit', done);
      resolve();
    };

    timer = setTimeout(() => {
      done();
    }, timeoutMs);

    processRef.once('exit', done);
  });
}

function __setBackendProcessForTest(processRef = null) {
  backendProcess = processRef;
}

function stopBackend() {
  if (!backendProcess || backendProcess.killed) {
    return Promise.resolve();
  }
  const processToStop = backendProcess;

  if (isWindows) {
    spawn('taskkill', ['/PID', String(processToStop.pid), '/T', '/F'], { windowsHide: true }).on('error', () => {
    });
    return waitForBackendExit(processToStop, 10000);
  }

  processToStop.kill('SIGTERM');
  setTimeout(() => {
    if (processToStop.killed || processToStop.exitCode !== null || processToStop.signalCode) {
      return;
    }
    try {
      processToStop.kill('SIGKILL');
    } catch (_error) {
    }
  }, 3000);

  return waitForBackendExit(processToStop, 10000);
}

function resolveDesktopVersion() {
  return String(app.getVersion() || '').trim();
}

function buildMainPageUrl(port, timestamp = Date.now()) {
  const url = new URL(`http://127.0.0.1:${port}/`);
  url.searchParams.set('desktop_version', resolveDesktopVersion() || 'unknown');
  url.searchParams.set('cache_bust', String(timestamp));
  return url.toString();
}

function isWindowsNsisInstalledApp() {
  if (!isWindows || !app.isPackaged) {
    return false;
  }

  const appDir = path.dirname(app.getPath('exe'));
  return fs.existsSync(path.join(appDir, 'Uninstall Daily Stock Analysis.exe'));
}

function getElectronAutoUpdater() {
  if (electronAutoUpdater !== undefined) {
    return electronAutoUpdater;
  }

  if (!isWindowsNsisInstalledApp()) {
    electronAutoUpdater = null;
    return electronAutoUpdater;
  }

  try {
    electronAutoUpdater = require('electron-updater').autoUpdater;
  } catch (error) {
    electronAutoUpdater = null;
    logLine(`[update] electron-updater unavailable: ${error instanceof Error ? error.message : String(error)}`);
  }

  return electronAutoUpdater;
}

function canUseElectronAutoUpdater() {
  return Boolean(getElectronAutoUpdater());
}

function resolveReleasePageUrlForVersion(version) {
  const normalizedVersion = normalizeVersionString(version);
  if (!normalizedVersion) {
    return RELEASES_PAGE_URL;
  }
  return `${RELEASES_PAGE_URL}/tag/v${normalizedVersion}`;
}

function resolveUpdaterLatestVersion(updateInfo = {}) {
  return normalizeVersionString(updateInfo.version || updateInfo.tag || updateInfo.releaseName);
}

function buildElectronUpdaterState(status, updateInfo = {}, extraState = {}) {
  const latestVersion = normalizeVersionString(extraState.latestVersion || resolveUpdaterLatestVersion(updateInfo));
  return buildUpdateState({
    status,
    updateMode: UPDATE_MODE.AUTO,
    currentVersion: resolveDesktopVersion(),
    latestVersion,
    releaseUrl: resolveReleasePageUrlForVersion(latestVersion),
    publishedAt: typeof updateInfo.releaseDate === 'string' ? updateInfo.releaseDate : '',
    releaseName: typeof updateInfo.releaseName === 'string' ? updateInfo.releaseName : '',
    tagName: latestVersion ? `v${latestVersion}` : '',
    ...extraState,
  });
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
  if (state.updateMode === UPDATE_MODE.AUTO) {
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

async function installDownloadedUpdate() {
  const updater = getElectronAutoUpdater();
  if (!updater) {
    throw new Error('当前运行模式不支持自动安装更新。');
  }
  if (desktopUpdateState?.status !== UPDATE_STATUS.UPDATE_DOWNLOADED) {
    throw new Error('更新尚未下载完成，无法自动安装。');
  }

  setDesktopUpdateState({
    status: UPDATE_STATUS.INSTALLING,
    updateMode: UPDATE_MODE.AUTO,
    latestVersion: desktopUpdateState?.latestVersion || '',
    releaseUrl: desktopUpdateState?.releaseUrl || RELEASES_PAGE_URL,
    message: '正在重启并安装更新...',
  });
  let backupRoot = null;
  try {
    logLine('[update] stop backend and backup runtime data before install');
    await stopBackend();
    backupRoot = resolveUpdateBackupRoot();
    cleanupUpdateBackupRoot();

    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        backupPackagedRuntimeState();
        break;
      } catch (error) {
        if (attempt === 3) {
          setDesktopUpdateState({
            status: UPDATE_STATUS.ERROR,
            updateMode: UPDATE_MODE.AUTO,
            currentVersion: resolveDesktopVersion(),
            latestVersion: desktopUpdateState?.latestVersion || '',
            releaseUrl: desktopUpdateState?.releaseUrl || RELEASES_PAGE_URL,
            checkedAt: new Date().toISOString(),
            message: `更新安装准备失败：${error instanceof Error ? error.message : String(error)}`,
          });
          throw error;
        }

        await sleep(300 * attempt);
      }
    }

    logLine('[update] quit and install requested');
    updater.quitAndInstall(false, true);
    return true;
  } catch (error) {
    if (backupRoot) {
      cleanupUpdateBackupRoot();
    }
    logLine(`[update] install downloaded update failed: ${error instanceof Error ? error.message : String(error)}`);
    throw error;
  }
}

async function maybePromptInstallDownloadedUpdate(state) {
  if (!state || state.status !== UPDATE_STATUS.UPDATE_DOWNLOADED || state.updateMode !== UPDATE_MODE.AUTO) {
    return;
  }
  if (!state.latestVersion || state.latestVersion === lastPromptedInstallVersion) {
    return;
  }
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }

  lastPromptedInstallVersion = state.latestVersion;
  const result = await dialog.showMessageBox(mainWindow, {
    type: 'info',
    buttons: ['稍后', '立即重启安装'],
    defaultId: 1,
    cancelId: 0,
    title: '更新已下载',
    message: `桌面端新版本 ${state.latestVersion} 已下载`,
    detail: '重启应用后会自动完成安装。未保存的设置草稿请先保存。',
    noLink: true,
  });

  if (result.response === 1) {
    try {
      await installDownloadedUpdate();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      logLine(`[update] auto install prompt failed: ${message}`);
      setDesktopUpdateState({
        status: UPDATE_STATUS.ERROR,
        updateMode: UPDATE_MODE.AUTO,
        currentVersion: resolveDesktopVersion(),
        latestVersion: state.latestVersion || desktopUpdateState?.latestVersion || '',
        releaseUrl: state.releaseUrl || desktopUpdateState?.releaseUrl || RELEASES_PAGE_URL,
        checkedAt: new Date().toISOString(),
        message: `更新安装失败：${message}。可先保存草稿并前往下载页，或稍后重试。`,
      });
    }
  }
}

function configureElectronAutoUpdater() {
  const updater = getElectronAutoUpdater();
  if (!updater || electronAutoUpdaterConfigured) {
    return updater;
  }

  updater.autoDownload = true;
  updater.autoInstallOnAppQuit = false;

  updater.on('checking-for-update', () => {
    setDesktopUpdateState({
      status: UPDATE_STATUS.CHECKING,
      updateMode: UPDATE_MODE.AUTO,
      currentVersion: resolveDesktopVersion(),
      message: '正在检查桌面端更新...',
    });
  });

  updater.on('update-available', (info = {}) => {
    const latestVersion = resolveUpdaterLatestVersion(info) || '最新版本';
    const nextState = buildElectronUpdaterState(UPDATE_STATUS.UPDATE_AVAILABLE, info, {
      message: `发现新版本 ${latestVersion}，正在后台下载更新...`,
    });
    setDesktopUpdateState(nextState);
    logLine(`[update] auto update available latest=${nextState.latestVersion || 'unknown'}`);
  });

  updater.on('update-not-available', (info = {}) => {
    const nextState = buildElectronUpdaterState(UPDATE_STATUS.UP_TO_DATE, info, {
      message: '当前桌面端已是最新版本。',
    });
    setDesktopUpdateState(nextState);
    logLine(`[update] auto update not available current=${nextState.currentVersion || 'unknown'}`);
  });

  updater.on('download-progress', (progress = {}) => {
    const percent = normalizeDownloadPercent(progress.percent);
    const nextState = setDesktopUpdateState({
      status: UPDATE_STATUS.DOWNLOADING,
      updateMode: UPDATE_MODE.AUTO,
      latestVersion: desktopUpdateState?.latestVersion || '',
      releaseUrl: desktopUpdateState?.releaseUrl || RELEASES_PAGE_URL,
      downloadPercent: percent,
      downloadedBytes: progress.transferred,
      totalBytes: progress.total,
      message:
        percent === null
          ? '正在下载桌面端更新...'
          : `正在下载桌面端更新（${percent.toFixed(percent % 1 === 0 ? 0 : 1)}%）...`,
    });
    logLine(`[update] download progress percent=${nextState.downloadPercent ?? 'unknown'}`);
  });

  updater.on('update-downloaded', (info = {}) => {
    const latestVersion = resolveUpdaterLatestVersion(info) || desktopUpdateState?.latestVersion || '';
    const nextState = buildElectronUpdaterState(UPDATE_STATUS.UPDATE_DOWNLOADED, info, {
      latestVersion,
      downloadPercent: 100,
      message: latestVersion
        ? `新版本 ${latestVersion} 已下载，可重启应用完成安装。`
        : '新版本已下载，可重启应用完成安装。',
    });
    setDesktopUpdateState(nextState);
    logLine(`[update] downloaded latest=${nextState.latestVersion || 'unknown'}`);
    void maybePromptInstallDownloadedUpdate(nextState);
  });

  updater.on('error', (error) => {
    const message = error instanceof Error ? error.message : String(error);
    logLine(`[update] auto updater failed: ${message}`);
    setDesktopUpdateState({
      status: UPDATE_STATUS.ERROR,
      updateMode: UPDATE_MODE.AUTO,
      currentVersion: resolveDesktopVersion(),
      latestVersion: desktopUpdateState?.latestVersion || '',
      releaseUrl: desktopUpdateState?.releaseUrl || RELEASES_PAGE_URL,
      checkedAt: new Date().toISOString(),
      message: `自动更新失败：${message}`,
    });
  });

  electronAutoUpdaterConfigured = true;
  return updater;
}

async function performElectronUpdaterCheck({ manual = false } = {}) {
  const updater = configureElectronAutoUpdater();
  if (!updater) {
    throw new Error('当前平台不支持自动安装更新。');
  }
  if (electronUpdateCheckInFlight) {
    return desktopUpdateState;
  }

  electronUpdateCheckInFlight = true;
  setDesktopUpdateState({
    status: UPDATE_STATUS.CHECKING,
    updateMode: UPDATE_MODE.AUTO,
    currentVersion: resolveDesktopVersion(),
    message: manual ? '正在检查桌面端更新...' : '正在后台检查桌面端更新...',
  });

  try {
    await updater.checkForUpdates();
    return desktopUpdateState;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    logLine(`[update] auto updater check failed: ${message}`);
    const nextState = setDesktopUpdateState({
      status: manual ? UPDATE_STATUS.ERROR : UPDATE_STATUS.IDLE,
      updateMode: UPDATE_MODE.AUTO,
      currentVersion: resolveDesktopVersion(),
      checkedAt: new Date().toISOString(),
      message: manual ? `检查更新失败：${message}` : '',
    });
    return nextState;
  } finally {
    electronUpdateCheckInFlight = false;
  }
}

async function performDesktopUpdateCheck({ manual = false, notify = false } = {}) {
  if (canUseElectronAutoUpdater()) {
    return performElectronUpdaterCheck({ manual, notify });
  }

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
ipcMain.handle('desktop:install-downloaded-update', () => installDownloadedUpdate());
ipcMain.handle('desktop:open-release-page', async (_event, releaseUrl) => {
  await shell.openExternal(sanitizeReleaseUrl(releaseUrl));
  return true;
});

async function createWindow() {
  const restoreResult = isWindowsNsisInstalledApp() ? restorePackagedRuntimeStateFromBackup() : null;
  initLogging();
  const restoreFailed = Boolean(restoreResult && restoreResult.failed.length);
  const restoreIssueDetails = restoreResult
    ? restoreResult.failed.join('；')
    : '';
  const restoreErrorMessage = restoreFailed
    ? `上次更新安装未完成或恢复运行时文件失败，已保留备份目录 ${restoreResult.backupRoot}，请确认后手动恢复并重启应用。明细：${restoreIssueDetails}`
    : '';
  setDesktopUpdateState({
    status: restoreFailed ? UPDATE_STATUS.ERROR : UPDATE_STATUS.IDLE,
    currentVersion: resolveDesktopVersion(),
    updateMode: restoreFailed ? UPDATE_MODE.MANUAL : UPDATE_MODE.AUTO,
    message: restoreErrorMessage,
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
    const mainPageUrl = buildMainPageUrl(port);
    await mainWindow.loadURL(mainPageUrl);
    logStartup(`Main page loadURL resolved in ${Date.now() - mainPageStartedAt}ms url=${mainPageUrl}`);
    logStartup(`Main UI loaded in ${Date.now() - startupStartedAt}ms`);
    if (!restoreFailed) {
      void performDesktopUpdateCheck({ notify: true });
    }
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
  void stopBackend();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  void stopBackend();
});

module.exports = {
  DEFAULT_REQUEST_TIMEOUT_MS,
  GITHUB_OWNER,
  GITHUB_REPO,
  LATEST_RELEASE_API_URL,
  RELEASES_PAGE_URL,
  DESKTOP_UPDATE_RUNTIME_RELATIVE_FILES,
  UPDATE_MODE,
  UPDATE_STATUS,
  buildUpdateState,
  checkForDesktopUpdates,
  compareVersions,
  evaluateReleaseUpdate,
  extractReleaseMetadata,
  fetchLatestReleaseJson,
  buildMainPageUrl,
  normalizeVersionString,
  parseSemver,
  restorePackagedRuntimeStateFromBackup,
  sanitizeReleaseUrl,
  stopBackend,
  __setBackendProcessForTest,
  __setMainWindowForTest(mainWindowRef = null) {
    mainWindow = mainWindowRef;
  },
  waitForBackendExit,
};
