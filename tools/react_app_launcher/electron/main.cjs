const { app, BrowserWindow, ipcMain, shell, dialog, Menu, safeStorage } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { spawn, execFile } = require('node:child_process');

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
  return [
    getLegacyConfigPath(),
    path.join(app.getPath('appData'), 'App Launcher', 'apps.json'),
    path.join(app.getPath('appData'), 'react-app-launcher', 'apps.json')
  ];
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

function defaultConfig() {
  return { profiles: [] };
}

function normalizeConfigShape(data) {
  const normalized = Array.isArray(data) ? { profiles: data } : data;
  if (!normalized || !Array.isArray(normalized.profiles)) {
    throw new Error('Конфиг должен быть объектом вида: { \"profiles\": [] }');
  }
  return normalized;
}

function encryptConfigPayload(data) {
  const raw = JSON.stringify(normalizeConfigShape(data), null, 2);
  if (!isEncryptionAvailable()) return raw;

  const encryptedBuffer = safeStorage.encryptString(raw);
  return JSON.stringify({
    format: 'startdeck.encrypted-config.v1',
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

function expandEnv(value) {
  if (typeof value !== 'string') return value;
  return value
    .replace(/^~(?=$|[\\/])/, process.env.USERPROFILE || process.env.HOME || '~')
    .replace(/%([^%]+)%/g, (_, name) => process.env[name] || `%${name}%`);
}

function normalizeArgs(args) {
  if (!args) return [];
  if (Array.isArray(args)) return args.map(String).filter(Boolean);
  if (typeof args === 'string') {
    return args
      .split('\n')
      .map((x) => x.trim())
      .filter(Boolean);
  }
  return [];
}

function getTarget(item) {
  if (!item || typeof item !== 'object') return '';
  return expandEnv(item.path || '');
}

function getItemStatus(item) {
  if (!item || typeof item !== 'object') {
    return { ok: false, kind: 'unknown', issue: 'Некорректный элемент' };
  }
  if (item.enabled === false) {
    return { ok: true, kind: 'disabled', issue: 'Отключено' };
  }
  if (item.type === 'url') {
    return item.url
      ? { ok: true, kind: 'url', issue: '' }
      : { ok: false, kind: 'url', issue: 'Не указан URL' };
  }

  const target = getTarget(item);
  if (!target) return { ok: false, kind: item.type || 'app', issue: 'Не указан путь' };
  if (item.type === 'command') return { ok: true, kind: 'command', issue: '' };
  if (!fs.existsSync(target)) {
    return { ok: false, kind: item.type || 'app', issue: `Не найдено: ${target}` };
  }
  const stat = fs.statSync(target);
  return {
    ok: true,
    kind: stat.isDirectory() ? 'folder' : item.type || 'app',
    issue: '',
    resolvedPath: target
  };
}

function validateProfiles() {
  const profiles = readProfiles();
  return profiles.map((profile) => ({
    id: profile.id,
    items: (profile.items || []).map((item) => ({
      id: item.id,
      ...getItemStatus(item),
      resolvedPath: getTarget(item) || item.url || ''
    }))
  }));
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function imageNameFromItem(item) {
  if (item.processName) return String(item.processName);
  const target = getTarget(item);
  if (!target) return '';
  return path.basename(target);
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
  if (!item || typeof item !== 'object') throw new Error('Некорректный элемент запуска');
  if (item.enabled === false) return { ok: true, skipped: true, reason: 'disabled' };

  if (item.delayMs) {
    const ms = Math.max(0, Number(item.delayMs) || 0);
    if (ms > 0) await sleep(ms);
  }

  if (item.type === 'url') {
    if (!item.url) throw new Error('Для URL нужен параметр url');
    await shell.openExternal(String(item.url));
    return { ok: true };
  }

  const target = getTarget(item);
  if (!target) throw new Error('Не указан path');

  const exists = fs.existsSync(target);
  if (!exists && item.type !== 'command') {
    throw new Error(`Файл или папка не найдены: ${target}`);
  }

  if (item.type === 'folder' || (exists && fs.statSync(target).isDirectory())) {
    const errorMessage = await shell.openPath(target);
    if (errorMessage) throw new Error(errorMessage);
    return { ok: true };
  }

  if (item.type === 'file') {
    const errorMessage = await shell.openPath(target);
    if (errorMessage) throw new Error(errorMessage);
    return { ok: true };
  }

  if (item.skipIfRunning) {
    const imageName = imageNameFromItem(item);
    const running = await isProcessRunning(imageName);
    if (running) return { ok: true, skipped: true, reason: 'already_running' };
  }

  const child = spawn(target, normalizeArgs(item.args), {
    detached: true,
    stdio: 'ignore',
    shell: item.type === 'command' && item.allowShell === true,
    windowsHide: false
  });

  child.unref();
  return { ok: true };
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
      results.push({ id: item.id, name: item.name, ok: false, error: error.message });
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
