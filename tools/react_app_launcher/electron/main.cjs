const { app, BrowserWindow, ipcMain, shell, dialog, Menu } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { spawn, execFile } = require('node:child_process');

const isDev = Boolean(process.env.VITE_DEV_SERVER_URL);
const rootDir = app.getAppPath();
const bundledConfigPath = path.join(rootDir, 'data', 'apps.json');

function getUserConfigPath() {
  return path.join(app.getPath('userData'), 'apps.json');
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1180,
    height: 780,
    minWidth: 960,
    minHeight: 620,
    title: 'App Launcher',
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

function ensureConfig() {
  const userConfigPath = getUserConfigPath();
  const dir = path.dirname(userConfigPath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  if (fs.existsSync(userConfigPath)) return;

  if (fs.existsSync(bundledConfigPath)) {
    fs.copyFileSync(bundledConfigPath, userConfigPath);
    return;
  }
  fs.writeFileSync(userConfigPath, JSON.stringify(defaultConfig(), null, 2), 'utf8');
}

function readConfig() {
  ensureConfig();
  const userConfigPath = getUserConfigPath();
  const raw = fs.readFileSync(userConfigPath, 'utf8');
  const data = JSON.parse(raw);
  if (!data || !Array.isArray(data.profiles)) {
    throw new Error('В apps.json должен быть объект вида: { "profiles": [] }');
  }
  return data;
}

function readProfiles() {
  return readConfig().profiles;
}

function saveProfiles(profiles) {
  if (!Array.isArray(profiles)) {
    throw new Error('profiles должен быть массивом');
  }
  ensureConfig();
  const userConfigPath = getUserConfigPath();
  fs.writeFileSync(userConfigPath, JSON.stringify({ profiles }, null, 2), 'utf8');
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
  if (item.type === 'command') {
    return target
      ? { ok: true, kind: 'command', issue: item.allowShell ? 'Команда будет запущена через shell' : '' }
      : { ok: false, kind: 'command', issue: 'Не указана команда или исполняемый файл' };
  }
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
  if (item.type === 'command' && item.allowShell !== true && !exists) {
    throw new Error('Для command без allowShell нужен существующий исполняемый файл. Для raw shell-команды явно добавьте allowShell: true в JSON.');
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
