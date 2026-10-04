const { app, BrowserWindow, ipcMain, shell, dialog, Menu, safeStorage } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { spawn, execFile } = require('node:child_process');
const core = require('./launch_core.cjs');

const isDev = Boolean(process.env.VITE_DEV_SERVER_URL);
const rootDir = app.getAppPath();
const bundledConfigPath = path.join(rootDir, 'data', 'apps.json');

function isEncryptionAvailable() {
  try {
    return Boolean(safeStorage?.isEncryptionAvailable?.());
  } catch (_error) {
    return false;
  }
}

function getUserConfigPath() {
  const fileName = isEncryptionAvailable() ? 'profiles.encrypted.json' : 'profiles.json';
  return path.join(app.getPath('userData'), fileName);
}

function getLegacyConfigPath() {
  return path.join(app.getPath('userData'), 'apps.json');
}

function getPossibleLegacyConfigPaths() {
  return core.legacyConfigCandidates(app.getPath('userData'), app.getPath('appData'));
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1180,
    height: 780,
    minWidth: 960,
    minHeight: 620,
    title: 'StartDeck',
    backgroundColor: '#0d1117',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });

  if (isDev) {
    win.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    win.loadFile(path.join(rootDir, 'dist', 'index.html'));
  }
}

const { defaultConfig, normalizeConfigShape, getTarget } = core;

function encryptConfigPayload(data) {
  const raw = core.serializeConfig(data);
  if (!isEncryptionAvailable()) return raw;

  const encryptedBuffer = safeStorage.encryptString(raw);
  return JSON.stringify({
    format: core.ENCRYPTED_FORMAT,
    encrypted: true,
    payload: encryptedBuffer.toString('base64')
  }, null, 2);
}

function decryptConfigPayload(raw) {
  const parsed = JSON.parse(raw);
  if (!parsed?.encrypted) return normalizeConfigShape(parsed);
  if (!parsed.payload) throw new Error('В зашифрованном конфиге отсутствует payload');

  if (!isEncryptionAvailable()) {
    throw new Error('Система сейчас не дала доступ к расшифровке конфига');
  }

  const decrypted = safeStorage.decryptString(Buffer.from(parsed.payload, 'base64'));
  return normalizeConfigShape(JSON.parse(decrypted));
}

function writeConfig(data) {
  const userConfigPath = getUserConfigPath();
  const dir = path.dirname(userConfigPath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(userConfigPath, encryptConfigPayload(data), 'utf8');
}

function readPlainConfigFile(configPath) {
  const raw = fs.readFileSync(configPath, 'utf8');
  return normalizeConfigShape(JSON.parse(raw));
}

function ensureConfig() {
  const userConfigPath = getUserConfigPath();
  const dir = path.dirname(userConfigPath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  if (fs.existsSync(userConfigPath)) return;

  const legacyPath = getPossibleLegacyConfigPaths().find((candidate) => fs.existsSync(candidate));
  if (legacyPath) {
    writeConfig(readPlainConfigFile(legacyPath));
    return;
  }

  if (fs.existsSync(bundledConfigPath)) {
    writeConfig(readPlainConfigFile(bundledConfigPath));
    return;
  }

  writeConfig(defaultConfig());
}

function readConfig() {
  ensureConfig();
  const userConfigPath = getUserConfigPath();
  const raw = fs.readFileSync(userConfigPath, 'utf8');
  return decryptConfigPayload(raw);
}

function readProfiles() {
  return readConfig().profiles;
}

function saveProfiles(profiles) {
  if (!Array.isArray(profiles)) {
    throw new Error('profiles должен быть массивом');
  }
  writeConfig({ profiles });
  return profiles;
}

function validateProfiles() {
  return core.validateProfiles(readProfiles());
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isProcessRunning(imageName) {
  return new Promise((resolve) => {
    if (process.platform !== 'win32' || !imageName) {
      resolve(false);
      return;
    }
    execFile('tasklist', ['/FI', `IMAGENAME eq ${imageName}`], { windowsHide: true }, (error, stdout) => {
      if (error || !stdout) {
        resolve(false);
        return;
      }
      resolve(stdout.toLowerCase().includes(imageName.toLowerCase()));
    });
  });
}

async function launch(item) {
  const delayMs = core.launchDelayMs(item);
  if (delayMs > 0) await sleep(delayMs);

  const plan = core.planLaunch(item);
  if (plan.action === 'skip') return { ok: true, skipped: true, reason: plan.reason };

  if (plan.action === 'openExternal') {
    await shell.openExternal(plan.url);
    return { ok: true };
  }

  if (plan.action === 'openPath') {
    const errorMessage = await shell.openPath(plan.target);
    if (errorMessage) throw new Error(errorMessage);
    return { ok: true };
  }

  if (plan.skipIfRunning) {
    const running = await isProcessRunning(plan.imageName);
    if (running) return { ok: true, skipped: true, reason: 'already_running' };
  }

  return core.spawnDetached(plan, spawn);
}

function findProfileAndItem(profileId, itemId) {
  const profiles = readProfiles();
  const profile = profiles.find((p) => p.id === profileId);
  if (!profile) throw new Error(`Профиль не найден: ${profileId}`);
  const item = (profile.items || []).find((x) => x.id === itemId);
  if (!item) throw new Error(`Элемент не найден: ${itemId}`);
  return { profile, item };
}

ipcMain.handle('profiles:get', () => readProfiles());
ipcMain.handle('profiles:save', (_event, profiles) => saveProfiles(profiles));
ipcMain.handle('profiles:validate', () => validateProfiles());

ipcMain.handle('profile:launch', async (_event, profileId) => {
  const profiles = readProfiles();
  const profile = profiles.find((p) => p.id === profileId);
  if (!profile) throw new Error(`Профиль не найден: ${profileId}`);

  const results = [];
  for (const item of profile.items || []) {
    try {
      const result = await launch(item);
      results.push({ id: item.id, name: item.name, ok: true, skipped: Boolean(result.skipped), reason: result.reason || '' });
    } catch (error) {
      results.push({ id: item?.id, name: item?.name, ok: false, error: error.message });
    }
  }
  return results;
});

ipcMain.handle('item:launch', async (_event, profileId, itemId) => {
  const { item } = findProfileAndItem(profileId, itemId);
  return launch(item);
});

ipcMain.handle('item:reveal', async (_event, profileId, itemId) => {
  const { item } = findProfileAndItem(profileId, itemId);
  if (item.type === 'url') {
    await shell.openExternal(String(item.url));
    return { ok: true };
  }
  const target = getTarget(item);
  if (!target || !fs.existsSync(target)) throw new Error('Путь не найден');
  if (fs.statSync(target).isDirectory()) {
    const errorMessage = await shell.openPath(target);
    if (errorMessage) throw new Error(errorMessage);
  } else {
    shell.showItemInFolder(target);
  }
  return { ok: true };
});

ipcMain.handle('dialog:choose-path', async (_event, kind) => {
  const properties = kind === 'folder' ? ['openDirectory'] : ['openFile'];
  const filters = kind === 'app'
    ? [{ name: 'Программы Windows', extensions: ['exe', 'bat', 'cmd', 'lnk'] }, { name: 'Все файлы', extensions: ['*'] }]
    : [{ name: 'Все файлы', extensions: ['*'] }];
  const result = await dialog.showOpenDialog({ properties, filters });
  if (result.canceled || !result.filePaths[0]) return null;
  return result.filePaths[0];
});

ipcMain.handle('config:reveal', async () => {
  ensureConfig();
  shell.showItemInFolder(getUserConfigPath());
  return { ok: true };
});

ipcMain.handle('config:path', () => {
  ensureConfig();
  return getUserConfigPath();
});

ipcMain.handle('config:info', () => {
  ensureConfig();
  return {
    path: getUserConfigPath(),
    encrypted: isEncryptionAvailable(),
    legacyPath: getLegacyConfigPath(),
    legacyPaths: getPossibleLegacyConfigPaths()
  };
});

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  createWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
