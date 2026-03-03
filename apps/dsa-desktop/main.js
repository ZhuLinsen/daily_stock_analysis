const { app, BrowserWindow, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const net = require('net');
const http = require('http');

let mainWindow = null;
let backendProcess = null;
let logFilePath = null;
let backendStartError = null;

const isWindows = process.platform === 'win32';
const appRootDev = path.resolve(__dirname, '..', '..');

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
    launchMode = 'development';
    launchCommand = formatCommand(pythonPath, [scriptPath, ...args]);
    launchCwd = appRootDev;
    backendProcess = spawn(pythonPath, [scriptPath, ...args], {
      env,
      cwd: launchCwd,
      stdio: 'pipe',
      windowsHide: true,
    });
  }

  if (backendProcess) {
    let firstStdoutLogged = false;
    let firstStderrLogged = false;

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
      logLine(`[backend] ${String(data).trim()}`);
    });
    backendProcess.stderr.on('data', (data) => {
      if (!firstStderrLogged) {
        firstStderrLogged = true;
        logLine(`[backend] first stderr after ${Date.now() - launchStartedAt}ms`);
      }
      logLine(`[backend] ${String(data).trim()}`);
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

async function createWindow() {
  initLogging();
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
    backgroundColor: '#0f172a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });
  logStartup('BrowserWindow created');

  const loadingPath = path.join(__dirname, 'renderer', 'loading.html');
  const loadingPageStartedAt = Date.now();
  await mainWindow.loadFile(loadingPath);
  logStartup(`Loading page rendered in ${Date.now() - loadingPageStartedAt}ms`);

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
