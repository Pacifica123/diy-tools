#!/usr/bin/env node
'use strict';

// Пробный прогон профилей StartDeck без Electron: показывает, что было бы
// выполнено, и ничего не запускает. Формат отчёта — docs/CONTRACT.md.

const fs = require('node:fs');
const path = require('node:path');
const core = require(path.join(__dirname, '..', 'electron', 'launch_core.cjs'));

const USAGE = [
  'Использование: node scripts/dry_run.js <конфиг.json>',
  '',
  'Читает открытый JSON-конфиг профилей и печатает в stdout JSON-отчёт пробного',
  'прогона: статус каждого элемента и то, что было бы выполнено. Ничего не',
  'запускает и ничего не записывает. Итог печатается в stderr.',
  '',
  'Коды выхода: 0 — проблем нет; 1 — есть проблемные элементы;',
  '2 — конфиг не прочитан или имеет неверный формат.'
].join('\n');

function main(argv) {
  if (argv.includes('-h') || argv.includes('--help')) {
    console.log(USAGE);
    return 0;
  }
  if (argv.length !== 1) {
    console.error(USAGE);
    return 2;
  }

  const configPath = path.resolve(argv[0]);
  let report;
  try {
    const parsed = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    if (parsed && !Array.isArray(parsed) && parsed.encrypted) {
      throw new Error('это зашифрованный конфиг (profiles.encrypted.json); расшифровать его может только само приложение StartDeck на том же компьютере. Скопируйте профили из окна «JSON» в обычный файл');
    }
    report = core.dryRunReport(parsed);
  } catch (error) {
    console.error(`Ошибка: не удалось разобрать конфиг ${configPath}: ${error.message}`);
    return 2;
  }

  console.log(JSON.stringify(report, null, 2));
  const { summary } = report;
  console.error([
    'Готово: пробный прогон, ничего не запущено.',
    `Профилей: ${summary.profiles}`,
    `Элементов: ${summary.items}`,
    `Готово к запуску: ${summary.ready}`,
    `Пропущено (отключено): ${summary.disabled}`,
    `Ошибок: ${summary.problems}`,
    'Результат: JSON-отчёт в stdout',
    `Конфиг: ${configPath}`
  ].join('\n'));
  return summary.problems > 0 ? 1 : 0;
}

process.exitCode = main(process.argv.slice(2));
