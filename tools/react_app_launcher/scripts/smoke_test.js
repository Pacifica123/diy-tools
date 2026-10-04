'use strict';

// Smoke + регрессия StartDeck без Electron и без node_modules.
// Ничего не запускает: ядро проверяется в режиме плана (dry-run), а главный
// процесс electron/main.cjs загружается с заглушками Electron и child_process.
// Пишет только во временную папку. Что именно покрыто — README, раздел «Проверка».

const assert = require('node:assert/strict');
const childProcess = require('node:child_process');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const { createRequire } = require('node:module');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const fixtureDir = path.join(root, 'examples', 'input', 'fixture');
const expectedDir = path.join(root, 'examples', 'output_expected');
const EXAMPLES = ['01_current_format', '02_legacy_array', '03_problems'];
const EXAMPLE_ENV = { STARTDECK_EXAMPLES: fixtureDir };
// Единственный режим, который пишет в капсулу: осознанное пересоздание эталонов.
const WRITE_EXPECTED = process.argv.includes('--write-expected');

const core = require(path.join(root, 'electron', 'launch_core.cjs'));

function read(file) {
  return fs.readFileSync(path.join(root, file), 'utf8');
}
function readJson(file) {
  return JSON.parse(read(file));
}
function check(condition, message) {
  if (!condition) throw new Error(message);
}

// Абсолютные пути нестабильны между машинами: заменяем известные корни метками.
function normalize(value, replacements) {
  if (typeof value === 'string') {
    let text = value;
    for (const [from, to] of replacements) text = text.split(from).join(to);
    return text;
  }
  if (Array.isArray(value)) return value.map((x) => normalize(x, replacements));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, x]) => [key, normalize(x, replacements)]));
  }
  return value;
}

function firstDifference(actual, expected, where = '$') {
  if (actual === expected) return '';
  const bothObjects = actual && expected && typeof actual === 'object' && typeof expected === 'object'
    && Array.isArray(actual) === Array.isArray(expected);
  if (!bothObjects) {
    return `${where}: получено ${JSON.stringify(actual)}, ожидалось ${JSON.stringify(expected)}`;
  }
  const keys = [...new Set([...Object.keys(expected), ...Object.keys(actual)])];
  for (const key of keys) {
    const inner = firstDifference(actual[key], expected[key], `${where}.${key}`);
    if (inner) return inner;
  }
  return '';
}

function compareWithExpected(fileName, actual) {
  const expectedPath = path.join(expectedDir, fileName);
  if (WRITE_EXPECTED) {
    fs.writeFileSync(expectedPath, `${JSON.stringify(actual, null, 2)}\n`, 'utf8');
    return;
  }
  check(fs.existsSync(expectedPath), `нет эталона examples/output_expected/${fileName}`);
  // Через JSON, чтобы сравнивать ровно то, что попадает в файл (undefined отбрасывается).
  const difference = firstDifference(JSON.parse(JSON.stringify(actual)), JSON.parse(fs.readFileSync(expectedPath, 'utf8')));
  check(!difference, `регрессия: результат не совпал с examples/output_expected/${fileName} — ${difference}`);
}

function exampleInput(name) {
  return readJson(path.join('examples', 'input', `${name}.json`));
}

// ---------------------------------------------------------------------------
// 1. Статические проверки капсулы
// ---------------------------------------------------------------------------

function checkStatic() {
  const pkg = readJson('package.json');
  check(pkg.name === 'startdeck', 'package.name must be startdeck');
  check(pkg.version === '0.4.0', 'package.version must be 0.4.0');
  check(pkg.build?.productName === 'StartDeck', 'build.productName must be StartDeck');
  check(pkg.build?.files?.includes('electron/**/*'), 'build.files must package electron/ (main.cjs + launch_core.cjs)');
  check(!JSON.stringify(pkg).includes('build/icon.ico'), 'package.json must not reference missing build/icon.ico');
  check(!fs.existsSync(path.join(root, 'package-lock.json')), 'package-lock.json must not be in the capsule');

  for (const section of ['dependencies', 'devDependencies']) {
    for (const [name, version] of Object.entries(pkg[section] || {})) {
      if (version === 'latest' || version === '*') {
        throw new Error(`${section}.${name} uses ${version}`);
      }
    }
  }

  const toolIni = read('tool.ini').replace(/\r\n/g, '\n');
  check(toolIni.includes(`\nversion = ${pkg.version}\n`), 'tool.ini version must match package.json version');
  check(toolIni.includes(`\ncontract_version = ${core.CONTRACT_VERSION}\n`), 'tool.ini contract_version must match launch_core.cjs');
  check(read('CHANGELOG.md').includes(`## ${pkg.version}`), 'CHANGELOG.md must describe the current version');
  check(read('docs/CONTRACT.md').includes(`Версия контракта: ${core.CONTRACT_VERSION}`), 'docs/CONTRACT.md must state the contract version');

  const data = readJson('data/apps.json');
  check(data && Array.isArray(data.profiles), 'data/apps.json must contain { profiles: [] }');
  check(data.profiles.length === 0, 'data/apps.json must not contain personal starter profiles');

  const example = readJson('data/example-apps.json');
  check(example && Array.isArray(example.profiles), 'data/example-apps.json must contain { profiles: [] }');
  check(example.profiles.length > 0, 'data/example-apps.json must contain safe examples');
  const exampleText = JSON.stringify(example);
  check(exampleText.includes('C:\\\\Path\\\\To\\\\Program.exe'), 'example profile must use synthetic Windows paths');
  const forbiddenPersonalPath = new RegExp(['C:', 'Users', 'Noir'].join('\\\\'), 'i');
  check(!forbiddenPersonalPath.test(exampleText), 'example profile must not contain personal Windows paths');
  const exampleReport = core.dryRunReport(example, {});
  check(exampleReport.summary.items === exampleReport.summary.disabled, 'every item of data/example-apps.json must be disabled');

  const vite = read('vite.config.js');
  check(vite.includes("base: './'"), "vite.config.js must keep base: './' for packaged Electron mode");

  const main = read('electron/main.cjs');
  check(main.includes("require('./launch_core.cjs')"), 'main.cjs must use electron/launch_core.cjs');
  check(main.includes('safeStorage'), 'safeStorage support is missing');
  check(main.includes('profiles.encrypted.json'), 'encrypted profile path is missing');
  check(main.includes('autoHideMenuBar: true'), 'Electron menu hiding is missing');
  check(main.includes('core.spawnDetached(plan, spawn)'), 'main.cjs must spawn only through the launch plan');
  for (const source of [main, read('electron/launch_core.cjs')]) {
    check(!/shell:\s*true/.test(source), 'unconditional shell: true is not allowed');
    check(!/\bexec(Sync|FileSync)?\(/.test(source), 'exec/execSync/execFileSync are not allowed in the launcher');
  }

  const preload = read('electron/preload.cjs');
  for (const apiName of ['getProfiles', 'saveProfiles', 'validateProfiles', 'launchProfile', 'launchItem', 'revealItem', 'choosePath', 'revealConfig', 'getConfigInfo']) {
    check(preload.includes(apiName), `preload API is missing ${apiName}`);
  }

  const app = read('src/App.jsx');
  check(app.includes('StartDeck'), 'UI must display StartDeck name');
  check(app.includes('createSafeExampleProfile'), 'safe example profile action is missing');
  check(app.includes('configInfo?.encrypted'), 'UI must expose encrypted/json config status');
  // Всё, что UI вызывает у window.launcherApi, должно существовать в preload и в main.
  const usedApi = [...new Set([...app.matchAll(/\bapi\.([A-Za-z]+)/g)].map((match) => match[1]))];
  check(usedApi.length >= 9, 'App.jsx must call window.launcherApi');
  const exposed = new Map([...preload.matchAll(/(\w+): \([^)]*\) => ipcRenderer\.invoke\('([^']+)'/g)].map((match) => [match[1], match[2]]));
  for (const apiName of usedApi) check(exposed.has(apiName), `App.jsx calls launcherApi.${apiName}, but preload.cjs does not expose it`);
  for (const [apiName, channel] of exposed) {
    check(main.includes(`ipcMain.handle('${channel}'`), `preload ${apiName} uses channel ${channel}, but main.cjs does not handle it`);
  }

  for (const launcher of ['run.sh', 'run.bat']) {
    const text = read(launcher);
    check(text.includes('npm не найден') && text.includes('node_modules'), `${launcher} must explain missing npm / node_modules in Russian`);
  }
}

// ---------------------------------------------------------------------------
// 2. Регрессия ядра: examples/input -> examples/output_expected (dry-run)
// ---------------------------------------------------------------------------

function buildDryRun(name) {
  return normalize(core.dryRunReport(exampleInput(name), EXAMPLE_ENV), [[fixtureDir, '<EXAMPLES>']]);
}

function checkCoreRegression() {
  for (const name of EXAMPLES) {
    const report = buildDryRun(name);
    check(report.launched === 0 && report.mode === 'dry-run', `${name}: dry-run must not launch anything`);
    compareWithExpected(`${name}.dry_run.json`, report);
  }
}

// ---------------------------------------------------------------------------
// 3. Точечные проверки ядра: формат конфига, защита allowShell, аргументы
// ---------------------------------------------------------------------------

function fakeChild() {
  const child = new EventEmitter();
  child.unrefCalled = 0;
  child.unref = () => { child.unrefCalled += 1; };
  return child;
}

async function checkCoreRules(tempDir) {
  // Формат и миграция конфига.
  assert.deepEqual(core.defaultConfig(), { profiles: [] });
  assert.deepEqual(core.normalizeConfigShape([{ id: 'a' }]), { profiles: [{ id: 'a' }] });
  for (const bad of [null, {}, 'text', 5, { profiles: {} }, { profiles: 'x' }]) {
    assert.throws(() => core.normalizeConfigShape(bad), /Конфиг должен быть объектом/, `shape ${JSON.stringify(bad)} must be rejected`);
  }
  for (const version of [2, 1.5, '1', null]) {
    assert.throws(() => core.normalizeConfigShape({ contract_version: version, profiles: [] }), /неподдерживаемую версию контракта/);
  }
  const serialized = core.serializeConfig([{ id: 'a', items: [] }]);
  assert.deepEqual(JSON.parse(serialized), { contract_version: 1, profiles: [{ id: 'a', items: [] }] });
  assert.equal(Object.keys(JSON.parse(serialized))[0], 'contract_version');
  assert.equal(core.serializeConfig(JSON.parse(serialized)), serialized, 'serializeConfig must be idempotent');
  assert.deepEqual(
    core.legacyConfigCandidates(path.join('U', 'StartDeck'), 'A'),
    [
      path.join('U', 'StartDeck', 'profiles.json'),
      path.join('U', 'StartDeck', 'apps.json'),
      path.join('A', 'App Launcher', 'apps.json'),
      path.join('A', 'react-app-launcher', 'apps.json')
    ]
  );

  // Подстановка окружения.
  const env = { HOME: '/home/пользователь', A: 'значение' };
  assert.equal(core.expandEnv('~', env), '/home/пользователь');
  assert.equal(core.expandEnv('~/Папка', env), '/home/пользователь/Папка');
  assert.equal(core.expandEnv('~user/x', env), '~user/x');
  assert.equal(core.expandEnv('%A%/%НЕТ%', env), 'значение/%НЕТ%');
  assert.equal(core.expandEnv('~/x', { USERPROFILE: 'C:\\U', HOME: '/h' }), 'C:\\U/x');
  assert.equal(core.expandEnv('~/x', { HOME: '/h/$&$1' }), '/h/$&$1/x');
  assert.equal(core.expandEnv(undefined, env), undefined);

  // Аргументы: всегда массив строк.
  assert.deepEqual(core.normalizeArgs(['a b', 7, '', null, '--x']), ['a b', '7', 'null', '--x']);
  assert.deepEqual(core.normalizeArgs(' один \n\n два слова\n'), ['один', 'два слова']);
  assert.deepEqual(core.normalizeArgs({ a: 1 }), []);
  assert.deepEqual(core.normalizeArgs(undefined), []);

  // Защита command/allowShell: shell только при type = command и allowShell строго true.
  const existingFile = path.join(fixtureDir, 'программа заглушка.bin');
  const nastyArgs = ['; rm -rf ~', '&& calc.exe', '$(id)', '`id`', '| more', 'обычный аргумент'];
  for (const type of [undefined, 'app', 'command']) {
    for (const allowShell of [undefined, false, true, 'true', 1, 'yes']) {
      const plan = core.planLaunch({ id: 'x', type, path: existingFile, args: nastyArgs, allowShell }, {});
      const expectedShell = type === 'command' && allowShell === true;
      assert.equal(plan.action, 'spawn');
      assert.strictEqual(plan.options.shell, expectedShell, `type=${type} allowShell=${JSON.stringify(allowShell)}`);
      assert.equal(plan.file, existingFile, 'path must not be concatenated with arguments');
      assert.deepEqual(plan.args, nastyArgs, 'arguments must stay a separate array');
      assert.equal(plan.options.detached, true);
      assert.equal(plan.options.stdio, 'ignore');
    }
  }
  for (const type of ['folder', 'file', 'url']) {
    const plan = core.planLaunch({ type, path: existingFile, url: 'https://example.com', allowShell: true, args: nastyArgs }, {});
    check(plan.action !== 'spawn' && plan.options === undefined, `${type} must never be spawned`);
  }

  // URL передаётся как есть: списка разрешённых схем нет (см. docs/CONTRACT.md).
  assert.deepEqual(core.planLaunch({ type: 'url', url: 'steam://run/1' }, {}), { action: 'openExternal', url: 'steam://run/1' });
  assert.deepEqual(core.planLaunch({ type: 'url', url: 12 }, {}), { action: 'openExternal', url: '12' });

  // Неизвестный тип — ошибка, а не «программа по умолчанию».
  assert.throws(() => core.planLaunch({ type: 'Command', path: existingFile }, {}), /Неизвестный тип элемента: Command/);
  assert.equal(core.getItemStatus({ type: 'exe', path: existingFile }, {}).ok, false);
  assert.throws(() => core.planLaunch(null, {}), /Некорректный элемент запуска/);
  assert.deepEqual(
    core.validateProfiles([{ id: 'p', items: [null] }, { id: 'q', items: 'не массив' }, null], {}),
    [{ id: 'p', items: [{ id: undefined, ok: false, kind: 'unknown', issue: 'Некорректный элемент', resolvedPath: '' }] }, { id: 'q', items: [] }, { id: undefined, items: [] }]
  );
  assert.throws(() => core.planLaunch({ type: 'app', path: path.join(tempDir, 'нет файла.exe') }, {}), /не найдены/);

  // Задержка.
  assert.equal(core.launchDelayMs({ delayMs: '300' }), 300);
  assert.equal(core.launchDelayMs({ delayMs: -5 }), 0);
  assert.equal(core.launchDelayMs({ delayMs: 'abc' }), 0);
  assert.equal(core.launchDelayMs({ delayMs: 300, enabled: false }), 0);

  // spawnDetached с подставной функцией spawn: ничего реально не запускается.
  const plan = core.planLaunch({ type: 'command', path: 'startdeck-example-command', args: ['a b'] }, {});
  const seen = [];
  const okChild = fakeChild();
  const okPromise = core.spawnDetached(plan, (...args) => { seen.push(args); return okChild; });
  okChild.emit('spawn');
  assert.deepEqual(await okPromise, { ok: true });
  assert.deepEqual(seen, [['startdeck-example-command', ['a b'], { detached: true, stdio: 'ignore', shell: false, windowsHide: false }]]);
  assert.equal(okChild.unrefCalled, 1);

  const badChild = fakeChild();
  const badPromise = core.spawnDetached(plan, () => badChild);
  badChild.emit('error', Object.assign(new Error('spawn ENOENT'), { code: 'ENOENT' }));
  await assert.rejects(badPromise, /Не удалось запустить: startdeck-example-command \(ENOENT\)/);

  await assert.rejects(
    core.spawnDetached(plan, () => { throw Object.assign(new Error('spawn EINVAL'), { code: 'EINVAL' }); }),
    /Не удалось запустить: startdeck-example-command \(EINVAL\)/
  );
}

// ---------------------------------------------------------------------------
// 4. CLI пробного прогона scripts/dry_run.js (отдельный процесс node, чужой cwd)
// ---------------------------------------------------------------------------

function runDryRunCli(tempDir, args) {
  const env = { ...process.env, ...EXAMPLE_ENV };
  delete env.STARTDECK_NO_SUCH_VARIABLE;
  return childProcess.spawnSync(process.execPath, [path.join(root, 'scripts', 'dry_run.js'), ...args], {
    cwd: tempDir,
    env,
    encoding: 'utf8'
  });
}

function checkDryRunCli(tempDir) {
  const replacements = [[fixtureDir, '<EXAMPLES>']];
  const expectedStatus = { '01_current_format': 0, '02_legacy_array': 0, '03_problems': 1 };
  for (const name of EXAMPLES) {
    const result = runDryRunCli(tempDir, [path.join(root, 'examples', 'input', `${name}.json`)]);
    check(result.status === expectedStatus[name], `dry_run.js ${name}: код выхода ${result.status}, ожидался ${expectedStatus[name]}\n${result.stderr}`);
    compareWithExpected(`${name}.dry_run.json`, normalize(JSON.parse(result.stdout), replacements));
    check(result.stderr.includes('Готово: пробный прогон, ничего не запущено.'), `dry_run.js ${name}: нет итоговой строки`);
  }

  const brokenPath = path.join(tempDir, 'битый конфиг.json');
  fs.writeFileSync(brokenPath, '{ "profiles": {} }', 'utf8');
  const broken = runDryRunCli(tempDir, ['битый конфиг.json']);
  check(broken.status === 2 && broken.stdout === '' && broken.stderr.includes('Ошибка: не удалось разобрать конфиг'), 'dry_run.js must exit 2 on a bad config');

  const encryptedPath = path.join(tempDir, 'profiles.encrypted.json');
  fs.writeFileSync(encryptedPath, JSON.stringify({ format: core.ENCRYPTED_FORMAT, encrypted: true, payload: 'AAAA' }), 'utf8');
  const encrypted = runDryRunCli(tempDir, [encryptedPath]);
  check(encrypted.status === 2 && encrypted.stderr.includes('зашифрованный конфиг'), 'dry_run.js must explain encrypted configs');

  const missing = runDryRunCli(tempDir, [path.join(tempDir, 'нет файла.json')]);
  check(missing.status === 2, 'dry_run.js must exit 2 on a missing file');
  const usage = runDryRunCli(tempDir, []);
  check(usage.status === 2 && usage.stderr.includes('Использование'), 'dry_run.js must print usage');
}

// ---------------------------------------------------------------------------
// 5. Главный процесс electron/main.cjs с заглушками Electron и child_process
// ---------------------------------------------------------------------------

// «Шифрование» заглушки обратимо и нужно только для проверки обёртки файла;
// настоящий safeStorage (DPAPI/keychain) здесь не проверяется.
const stubCipher = (buffer) => Buffer.from(buffer.map((byte) => byte ^ 0x5a));

function loadMainWithStubs({ userData, appData, encryption = false, failSpawnFor = '' }) {
  const calls = [];
  const handlers = new Map();
  const windows = [];
  const electron = {
    app: {
      getAppPath: () => root,
      getPath: (name) => ({ userData, appData })[name],
      whenReady: () => Promise.resolve(),
      on: () => {},
      quit: () => {}
    },
    BrowserWindow: class {
      constructor(options) { this.options = options; windows.push(this); }
      loadURL(url) { this.loaded = url; }
      loadFile(file) { this.loaded = file; }
      static getAllWindows() { return windows; }
    },
    ipcMain: { handle: (channel, handler) => handlers.set(channel, handler) },
    shell: {
      openExternal: async (url) => { calls.push({ api: 'shell.openExternal', url }); },
      openPath: async (target) => { calls.push({ api: 'shell.openPath', target }); return ''; },
      showItemInFolder: (target) => { calls.push({ api: 'shell.showItemInFolder', target }); }
    },
    dialog: { showOpenDialog: async () => ({ canceled: true, filePaths: [] }) },
    Menu: { setApplicationMenu: () => {} },
    safeStorage: {
      isEncryptionAvailable: () => encryption,
      encryptString: (text) => stubCipher(Buffer.from(text, 'utf8')),
      decryptString: (buffer) => stubCipher(buffer).toString('utf8')
    }
  };
  const childProcessStub = {
    spawn: (file, args, options) => {
      calls.push({ api: 'child_process.spawn (заглушка)', file, args, options });
      const child = fakeChild();
      setImmediate(() => {
        if (failSpawnFor && file === failSpawnFor) child.emit('error', Object.assign(new Error(`spawn ${file} ENOENT`), { code: 'ENOENT' }));
        else child.emit('spawn');
      });
      return child;
    },
    // tasklist (проверка «уже запущено» на Windows) тоже не выполняется.
    execFile: (_file, _args, _options, callback) => callback(null, '')
  };

  const mainPath = path.join(root, 'electron', 'main.cjs');
  const realRequire = createRequire(mainPath);
  const stubRequire = (request) => {
    if (request === 'electron') return electron;
    if (request === 'node:child_process' || request === 'child_process') return childProcessStub;
    return realRequire(request);
  };
  const moduleStub = { exports: {} };
  const compiled = vm.compileFunction(
    fs.readFileSync(mainPath, 'utf8'),
    ['require', 'module', 'exports', '__dirname', '__filename'],
    { filename: mainPath }
  );
  compiled(stubRequire, moduleStub, moduleStub.exports, path.dirname(mainPath), mainPath);

  const invoke = async (channel, ...args) => {
    check(handlers.has(channel), `main.cjs не регистрирует IPC-канал ${channel}`);
    return handlers.get(channel)({}, ...args);
  };
  return { calls, invoke, windows, handlers };
}

async function buildStubLaunch(name, tempDir) {
  const caseDir = path.join(tempDir, 'данные пользователя', name);
  const userData = path.join(caseDir, 'userData', 'StartDeck');
  const appData = path.join(caseDir, 'appData');
  const main = loadMainWithStubs({ userData, appData });

  const profiles = core.normalizeConfigShape(exampleInput(name)).profiles
    // Задержки в заглушечном запуске не нужны: сократить, чтобы тест не ждал.
    .map((profile) => (Array.isArray(profile.items)
      ? { ...profile, items: profile.items.map((item) => (item && item.delayMs ? { ...item, delayMs: 5 } : item)) }
      : profile));
  await main.invoke('profiles:save', profiles);
  assert.deepEqual(await main.invoke('profiles:get'), profiles, `${name}: profiles:get must return what profiles:save stored`);

  const validation = await main.invoke('profiles:validate');
  const launches = [];
  for (const profile of profiles) {
    const before = main.calls.length;
    const results = await main.invoke('profile:launch', profile.id);
    launches.push({ profileId: profile.id, results, requested: main.calls.slice(before) });
  }
  return normalize({ contract_version: core.CONTRACT_VERSION, mode: 'stub-launch', validation, launches }, [[fixtureDir, '<EXAMPLES>']]);
}

async function checkMainProcess(tempDir) {
  const savedEnv = { examples: process.env.STARTDECK_EXAMPLES, missing: process.env.STARTDECK_NO_SUCH_VARIABLE, dev: process.env.VITE_DEV_SERVER_URL };
  process.env.STARTDECK_EXAMPLES = fixtureDir;
  delete process.env.STARTDECK_NO_SUCH_VARIABLE;
  delete process.env.VITE_DEV_SERVER_URL;
  try {
    // 5.1. Регрессия: сохранить пример, проверить и «запустить» через IPC-обработчики.
    for (const name of EXAMPLES) {
      compareWithExpected(`${name}.stub_launch.json`, await buildStubLaunch(name, tempDir));
    }

    const base = path.join(tempDir, 'данные пользователя');
    const privateProfiles = [{ id: 'p', name: 'Личное', items: [{ id: 'i', name: 'Секретная папка', type: 'folder', path: path.join(base, 'очень личный путь') }] }];

    // 5.2. Первый запуск без шифрования: из пустого data/apps.json создаётся profiles.json.
    const freshUser = path.join(base, 'fresh', 'userData');
    const fresh = loadMainWithStubs({ userData: freshUser, appData: path.join(base, 'fresh', 'appData') });
    await new Promise((resolve) => setImmediate(resolve));
    check(fresh.windows.length === 1 && fresh.windows[0].loaded === path.join(root, 'dist', 'index.html'), 'packaged mode must load dist/index.html');
    check(fresh.windows[0].options.webPreferences.contextIsolation === true && fresh.windows[0].options.webPreferences.nodeIntegration === false, 'renderer isolation must stay enabled');
    assert.deepEqual(await fresh.invoke('profiles:get'), []);
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(freshUser, 'profiles.json'), 'utf8')), { contract_version: 1, profiles: [] });
    const freshInfo = await fresh.invoke('config:info');
    check(freshInfo.encrypted === false && freshInfo.path === path.join(freshUser, 'profiles.json'), 'config:info must report the plain config path');
    assert.equal(await fresh.invoke('config:path'), path.join(freshUser, 'profiles.json'));
    await assert.rejects(async () => fresh.invoke('profiles:save', { profiles: [] }), /profiles должен быть массивом/);
    await assert.rejects(async () => fresh.invoke('item:launch', 'нет', 'нет'), /Профиль не найден: нет/);
    assert.deepEqual(fresh.calls, [], 'nothing may be opened or spawned on start');
    assert.deepEqual(readJson('data/apps.json'), { profiles: [] }, 'bundled data/apps.json must stay untouched');

    // 5.3. Шифрованный режим: profiles.encrypted.json, открытого текста в файле нет.
    const encUser = path.join(base, 'encrypted', 'userData');
    const enc = loadMainWithStubs({ userData: encUser, appData: path.join(base, 'encrypted', 'appData'), encryption: true });
    await enc.invoke('profiles:save', privateProfiles);
    const encFile = path.join(encUser, 'profiles.encrypted.json');
    const encRaw = fs.readFileSync(encFile, 'utf8');
    const encParsed = JSON.parse(encRaw);
    check(encParsed.format === 'startdeck.encrypted-config.v1' && encParsed.encrypted === true && typeof encParsed.payload === 'string', 'encrypted wrapper fields are wrong');
    assert.deepEqual(Object.keys(encParsed).sort(), ['encrypted', 'format', 'payload']);
    check(!encRaw.includes('очень личный путь') && !encRaw.includes('Секретная папка'), 'encrypted config must not contain plain profile text');
    check(!fs.existsSync(path.join(encUser, 'profiles.json')), 'plain profiles.json must not be written in encrypted mode');
    assert.deepEqual(await enc.invoke('profiles:get'), privateProfiles);
    assert.equal((await enc.invoke('config:info')).encrypted, true);

    // Зашифрованный файл при недоступном шифровании не читается и не затирается.
    const lockedUser = path.join(base, 'locked', 'userData');
    fs.mkdirSync(lockedUser, { recursive: true });
    fs.writeFileSync(path.join(lockedUser, 'profiles.json'), encRaw, 'utf8');
    const locked = loadMainWithStubs({ userData: lockedUser, appData: path.join(base, 'locked', 'appData') });
    await assert.rejects(async () => locked.invoke('profiles:get'), /не дала доступ к расшифровке/);
    assert.equal(fs.readFileSync(path.join(lockedUser, 'profiles.json'), 'utf8'), encRaw);

    // 5.4. Миграция старого apps.json (массив профилей) из старой папки appData.
    const legacyApp = path.join(base, 'legacy', 'appData');
    const legacyUser = path.join(base, 'legacy', 'userData');
    fs.mkdirSync(path.join(legacyApp, 'App Launcher'), { recursive: true });
    const legacyFile = path.join(legacyApp, 'App Launcher', 'apps.json');
    fs.writeFileSync(legacyFile, JSON.stringify(privateProfiles), 'utf8');
    const legacy = loadMainWithStubs({ userData: legacyUser, appData: legacyApp });
    assert.deepEqual(await legacy.invoke('profiles:get'), privateProfiles);
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(legacyUser, 'profiles.json'), 'utf8')), { contract_version: 1, profiles: privateProfiles });
    assert.deepEqual(JSON.parse(fs.readFileSync(legacyFile, 'utf8')), privateProfiles, 'legacy file must be left as is');

    // 5.5. Открытый profiles.json переносится, когда шифрование стало доступно.
    const upgradeUser = path.join(base, 'upgrade', 'userData');
    fs.mkdirSync(upgradeUser, { recursive: true });
    fs.writeFileSync(path.join(upgradeUser, 'profiles.json'), JSON.stringify({ profiles: privateProfiles }), 'utf8');
    const upgrade = loadMainWithStubs({ userData: upgradeUser, appData: path.join(base, 'upgrade', 'appData'), encryption: true });
    assert.deepEqual(await upgrade.invoke('profiles:get'), privateProfiles);
    check(fs.existsSync(path.join(upgradeUser, 'profiles.encrypted.json')), 'plain profiles.json must migrate to profiles.encrypted.json');

    // 5.6. Конфиг из будущей версии контракта не читается молча.
    const futureUser = path.join(base, 'future', 'userData');
    fs.mkdirSync(futureUser, { recursive: true });
    fs.writeFileSync(path.join(futureUser, 'profiles.json'), JSON.stringify({ contract_version: 2, profiles: [] }), 'utf8');
    const future = loadMainWithStubs({ userData: futureUser, appData: path.join(base, 'future', 'appData') });
    await assert.rejects(async () => future.invoke('profiles:get'), /неподдерживаемую версию контракта/);

    // 5.7. Ошибка старта процесса попадает в результат, а не роняет главный процесс.
    const failing = loadMainWithStubs({ userData: path.join(base, 'failing', 'userData'), appData: path.join(base, 'failing', 'appData'), failSpawnFor: 'startdeck-no-such-command' });
    await failing.invoke('profiles:save', [{ id: 'f', name: 'f', items: [
      { id: 'bad', name: 'Нет такой команды', type: 'command', path: 'startdeck-no-such-command' },
      null,
      { id: 'good', name: 'После ошибки', type: 'url', url: 'https://example.com' }
    ] }]);
    assert.deepEqual(await failing.invoke('profile:launch', 'f'), [
      { id: 'bad', name: 'Нет такой команды', ok: false, error: 'Не удалось запустить: startdeck-no-such-command (ENOENT)' },
      { id: undefined, name: undefined, ok: false, error: 'Некорректный элемент запуска' },
      { id: 'good', name: 'После ошибки', ok: true, skipped: false, reason: '' }
    ]);

    // 5.8. item:reveal: файл показывается в папке, папка открывается, url открывается.
    const reveal = loadMainWithStubs({ userData: path.join(base, 'reveal', 'userData'), appData: path.join(base, 'reveal', 'appData') });
    await reveal.invoke('profiles:save', exampleInput('01_current_format').profiles);
    await reveal.invoke('item:reveal', 'work', 'file');
    await reveal.invoke('item:reveal', 'work', 'folder');
    await reveal.invoke('item:reveal', 'work', 'site');
    await assert.rejects(async () => reveal.invoke('item:reveal', 'work', 'command-no-shell'), /Путь не найден/);
    assert.deepEqual(reveal.calls, [
      { api: 'shell.showItemInFolder', target: path.join(fixtureDir) + '/Рабочая папка/заметки проекта.txt' },
      { api: 'shell.openPath', target: path.join(fixtureDir) + '/Рабочая папка' },
      { api: 'shell.openExternal', url: 'https://example.com/путь?q=1' }
    ]);
  } finally {
    for (const [name, value] of [['STARTDECK_EXAMPLES', savedEnv.examples], ['STARTDECK_NO_SUCH_VARIABLE', savedEnv.missing], ['VITE_DEV_SERVER_URL', savedEnv.dev]]) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
}

// ---------------------------------------------------------------------------

async function main() {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'startdeck smoke тест '));
  try {
    checkStatic();
    checkCoreRegression();
    await checkCoreRules(tempDir);
    checkDryRunCli(tempDir);
    await checkMainProcess(tempDir);
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
  console.log('Проверено без Electron: статические проверки, ядро запуска (dry-run), scripts/dry_run.js, main.cjs с заглушками Electron.');
  console.log('Не проверено: настоящее окно Electron/React, реальный запуск программ, safeStorage, сборка portable EXE.');
  if (WRITE_EXPECTED) {
    console.log('Эталоны в examples/output_expected пересозданы. Просмотрите разницу и запустите тест ещё раз без --write-expected.');
    return;
  }
  console.log('react_app_launcher smoke passed');
}

if (require.main === module) {
  main().catch((error) => {
    console.error(`react_app_launcher smoke FAILED: ${error.message}`);
    process.exitCode = 1;
  });
} else {
  module.exports = { buildDryRun, buildStubLaunch, EXAMPLES };
}
