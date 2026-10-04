'use strict';

// Чистое ядро StartDeck: формат конфига, проверка элементов и план запуска.
// Модуль не зависит от Electron и сам ничего не запускает, поэтому его можно
// проверять обычным Node.js (см. scripts/smoke_test.js и scripts/dry_run.js).
// Внешний контракт описан в docs/CONTRACT.md.

const path = require('node:path');
const fs = require('node:fs');

const CONTRACT_VERSION = 1;
const ENCRYPTED_FORMAT = 'startdeck.encrypted-config.v1';
const ITEM_TYPES = ['app', 'folder', 'file', 'url', 'command'];

function defaultConfig() {
  return { profiles: [] };
}

function normalizeConfigShape(data) {
  const normalized = Array.isArray(data) ? { profiles: data } : data;
  if (!normalized || !Array.isArray(normalized.profiles)) {
    throw new Error('Конфиг должен быть объектом вида: { \"profiles\": [] }');
  }
  const version = normalized.contract_version;
  if (version !== undefined && (typeof version !== 'number' || version > CONTRACT_VERSION)) {
    throw new Error(`Конфиг имеет неподдерживаемую версию контракта: ${JSON.stringify(version)} (эта версия StartDeck понимает ${CONTRACT_VERSION})`);
  }
  return normalized;
}

// Текст открытого (незашифрованного) конфига в том виде, в каком он пишется на диск.
function serializeConfig(data) {
  const { contract_version: _ignored, ...rest } = normalizeConfigShape(data);
  return JSON.stringify({ contract_version: CONTRACT_VERSION, ...rest }, null, 2);
}

function expandEnv(value, env = process.env) {
  if (typeof value !== 'string') return value;
  return value
    .replace(/^~(?=$|[\\/])/, () => env.USERPROFILE || env.HOME || '~')
    .replace(/%([^%]+)%/g, (_, name) => env[name] || `%${name}%`);
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

function getTarget(item, env = process.env) {
  if (!item || typeof item !== 'object') return '';
  return expandEnv(item.path || '', env);
}

// Отсутствующий type означает 'app' (так было во всех версиях).
// Любое другое значение вне ITEM_TYPES — ошибка, а не «программа по умолчанию».
function unknownTypeIssue(item) {
  const type = item.type || 'app';
  return ITEM_TYPES.includes(type) ? '' : `Неизвестный тип элемента: ${String(type)}`;
}

function getItemStatus(item, env = process.env) {
  if (!item || typeof item !== 'object') {
    return { ok: false, kind: 'unknown', issue: 'Некорректный элемент' };
  }
  if (item.enabled === false) {
    return { ok: true, kind: 'disabled', issue: 'Отключено' };
  }
  const typeIssue = unknownTypeIssue(item);
  if (typeIssue) return { ok: false, kind: 'unknown', issue: typeIssue };
  if (item.type === 'url') {
    return item.url
      ? { ok: true, kind: 'url', issue: '' }
      : { ok: false, kind: 'url', issue: 'Не указан URL' };
  }

  const target = getTarget(item, env);
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

function validateProfiles(profiles, env = process.env) {
  return profiles.map((profile) => ({
    id: profile?.id,
    items: (Array.isArray(profile?.items) ? profile.items : []).map((item) => ({
      id: item?.id,
      ...getItemStatus(item, env),
      resolvedPath: getTarget(item, env) || item?.url || ''
    }))
  }));
}

function imageNameFromItem(item, env = process.env) {
  if (item.processName) return String(item.processName);
  const target = getTarget(item, env);
  if (!target) return '';
  return path.basename(target);
}

function launchDelayMs(item) {
  if (!item || typeof item !== 'object') throw new Error('Некорректный элемент запуска');
  if (item.enabled === false || !item.delayMs) return 0;
  return Math.max(0, Number(item.delayMs) || 0);
}

// Превращает элемент профиля в описание того, что было бы выполнено.
// Ничего не запускает. Возможные action: skip, openExternal, openPath, spawn.
// Аргументы всегда остаются массивом и не склеиваются с путём; shell включается
// только для type = command с явным allowShell: true.
function planLaunch(item, env = process.env) {
  if (!item || typeof item !== 'object') throw new Error('Некорректный элемент запуска');
  if (item.enabled === false) return { action: 'skip', reason: 'disabled' };

  const typeIssue = unknownTypeIssue(item);
  if (typeIssue) throw new Error(typeIssue);

  if (item.type === 'url') {
    if (!item.url) throw new Error('Для URL нужен параметр url');
    return { action: 'openExternal', url: String(item.url) };
  }

  const target = getTarget(item, env);
  if (!target) throw new Error('Не указан path');

  const exists = fs.existsSync(target);
  if (!exists && item.type !== 'command') {
    throw new Error(`Файл или папка не найдены: ${target}`);
  }

  if (item.type === 'folder' || item.type === 'file' || (exists && fs.statSync(target).isDirectory())) {
    return { action: 'openPath', target };
  }

  return {
    action: 'spawn',
    file: target,
    args: normalizeArgs(item.args),
    options: {
      detached: true,
      stdio: 'ignore',
      shell: item.type === 'command' && item.allowShell === true,
      windowsHide: false
    },
    skipIfRunning: Boolean(item.skipIfRunning),
    imageName: imageNameFromItem(item, env)
  };
}

// Выполняет план action = spawn через переданную функцию spawn (node:child_process).
// Ошибка старта (например, ENOENT) приходит событием 'error'; без обработчика она
// становилась необработанным исключением главного процесса.
function spawnDetached(plan, spawnFn) {
  return new Promise((resolve, reject) => {
    const fail = (error) => reject(new Error(`Не удалось запустить: ${plan.file} (${error.code || error.message})`));
    let child;
    try {
      child = spawnFn(plan.file, plan.args, plan.options);
    } catch (error) {
      fail(error);
      return;
    }
    child.on('error', fail);
    child.once('spawn', () => resolve({ ok: true }));
    child.unref();
  });
}

// Где искать конфиг для переноса, если текущего файла ещё нет (по порядку).
function legacyConfigCandidates(userDataDir, appDataDir) {
  return [
    path.join(userDataDir, 'profiles.json'),
    path.join(userDataDir, 'apps.json'),
    path.join(appDataDir, 'App Launcher', 'apps.json'),
    path.join(appDataDir, 'react-app-launcher', 'apps.json')
  ];
}

// Пробный прогон: нормализованный конфиг + статус и план по каждому элементу.
// Ничего не запускает и ничего не пишет.
function dryRunReport(data, env = process.env) {
  const config = JSON.parse(serializeConfig(data));
  const statuses = validateProfiles(config.profiles, env);
  const summary = { profiles: config.profiles.length, items: 0, ready: 0, disabled: 0, problems: 0 };

  const profiles = config.profiles.map((profile, profileIndex) => ({
    id: profile?.id,
    name: profile?.name,
    items: statuses[profileIndex].items.map((status, itemIndex) => {
      const item = profile.items[itemIndex];
      const entry = { id: status.id, name: item?.name, status };
      try {
        entry.delayMs = launchDelayMs(item);
        entry.plan = planLaunch(item, env);
      } catch (error) {
        entry.plan = null;
        entry.error = error.message;
      }
      summary.items += 1;
      if (entry.plan === null) summary.problems += 1;
      else if (entry.plan.action === 'skip') summary.disabled += 1;
      else summary.ready += 1;
      return entry;
    })
  }));

  return { contract_version: CONTRACT_VERSION, mode: 'dry-run', launched: 0, summary, config, profiles };
}

module.exports = {
  CONTRACT_VERSION,
  ENCRYPTED_FORMAT,
  ITEM_TYPES,
  defaultConfig,
  normalizeConfigShape,
  serializeConfig,
  expandEnv,
  normalizeArgs,
  getTarget,
  getItemStatus,
  validateProfiles,
  imageNameFromItem,
  launchDelayMs,
  planLaunch,
  spawnDetached,
  legacyConfigCandidates,
  dryRunReport
};
