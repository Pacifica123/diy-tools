const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
function readJson(file) {
  return JSON.parse(fs.readFileSync(path.join(root, file), 'utf8'));
}

const pkg = readJson('package.json');
for (const section of ['dependencies', 'devDependencies']) {
  for (const [name, version] of Object.entries(pkg[section] || {})) {
    if (version === 'latest' || version === '*') {
      throw new Error(`${section}.${name} uses ${version}`);
    }
  }
}

const data = readJson('data/apps.json');
if (!data || !Array.isArray(data.profiles)) {
  throw new Error('data/apps.json must contain { profiles: [] }');
}

const vite = fs.readFileSync(path.join(root, 'vite.config.js'), 'utf8');
if (!vite.includes("base: './'")) {
  throw new Error("vite.config.js must keep base: './' for packaged Electron mode");
}

const main = fs.readFileSync(path.join(root, 'electron/main.cjs'), 'utf8');
const expectedShellLine = "shell: item.type === 'command' && item.allowShell === true";
if (!main.includes('allowShell') || !main.includes(expectedShellLine)) {
  throw new Error('command launch hardening is missing');
}

console.log('react_app_launcher smoke passed');
