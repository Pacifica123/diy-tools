const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
function read(file) {
  return fs.readFileSync(path.join(root, file), 'utf8');
}
function readJson(file) {
  return JSON.parse(read(file));
}
function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const pkg = readJson('package.json');
assert(pkg.name === 'startdeck', 'package.name must be startdeck');
assert(pkg.version === '0.3.1', 'package.version must be 0.3.1');
assert(pkg.build?.productName === 'StartDeck', 'build.productName must be StartDeck');
assert(!JSON.stringify(pkg).includes('build/icon.ico'), 'package.json must not reference missing build/icon.ico');

for (const section of ['dependencies', 'devDependencies']) {
  for (const [name, version] of Object.entries(pkg[section] || {})) {
    if (version === 'latest' || version === '*') {
      throw new Error(`${section}.${name} uses ${version}`);
    }
  }
}

const data = readJson('data/apps.json');
assert(data && Array.isArray(data.profiles), 'data/apps.json must contain { profiles: [] }');
assert(data.profiles.length === 0, 'data/apps.json must not contain personal starter profiles');

const example = readJson('data/example-apps.json');
assert(example && Array.isArray(example.profiles), 'data/example-apps.json must contain { profiles: [] }');
assert(example.profiles.length > 0, 'data/example-apps.json must contain safe examples');
const exampleText = JSON.stringify(example);
assert(exampleText.includes('C:\\\\Path\\\\To\\\\Program.exe'), 'example profile must use synthetic Windows paths');
const forbiddenPersonalPath = new RegExp(['C:', 'Users', 'Noir'].join('\\\\'), 'i');
assert(!forbiddenPersonalPath.test(exampleText), 'example profile must not contain personal Windows paths');

const vite = read('vite.config.js');
assert(vite.includes("base: './'"), "vite.config.js must keep base: './' for packaged Electron mode");

const main = read('electron/main.cjs');
const expectedShellLine = "shell: item.type === 'command' && item.allowShell === true";
assert(main.includes('safeStorage'), 'safeStorage support is missing');
assert(main.includes('profiles.encrypted.json'), 'encrypted profile path is missing');
assert(main.includes('getPossibleLegacyConfigPaths'), 'legacy config migration is missing');
assert(main.includes('autoHideMenuBar: true'), 'Electron menu hiding is missing');
assert(main.includes('allowShell') && main.includes(expectedShellLine), 'command launch hardening is missing');

const preload = read('electron/preload.cjs');
for (const apiName of ['getProfiles', 'saveProfiles', 'validateProfiles', 'launchProfile', 'launchItem', 'revealItem', 'choosePath', 'revealConfig', 'getConfigInfo']) {
  assert(preload.includes(apiName), `preload API is missing ${apiName}`);
}

const app = read('src/App.jsx');
assert(app.includes('StartDeck'), 'UI must display StartDeck name');
assert(app.includes('createSafeExampleProfile'), 'safe example profile action is missing');
assert(app.includes('configInfo?.encrypted'), 'UI must expose encrypted/json config status');

console.log('react_app_launcher smoke passed');
