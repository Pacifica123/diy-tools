# Build notes

## 0.3.1-devctl

Актуализация капсулы `react_app_launcher` до варианта StartDeck по правилам DIY Tool Standard и devctl-патчей:

- публичное имя изменено на StartDeck;
- дефолтный `data/apps.json` очищен до пустого `{ "profiles": [] }`;
- безопасный пример вынесен в `data/example-apps.json`;
- добавлена миграция старых конфигов из `apps.json` и старых userData-папок;
- добавлено сохранение пользовательского конфига через Electron `safeStorage`, если оно доступно;
- сохранён фикс `base: './'` для portable Electron;
- сохранено скрытие меню Electron;
- сохранено devctl-ограничение: `command` запускается без shell, если в JSON явно не стоит `allowShell: true`;
- зависимости закреплены конкретными версиями, без `latest`.

Сборка:

```powershell
npm install
npm run dist:win
```

## 0.2.2

Исправлено пустое окно после сборки portable `.exe`.

Причина: Vite по умолчанию собирает ассеты с абсолютными путями `/assets/...`, а Electron `loadFile()` открывает локальный `file://.../index.html`. В итоге JS/CSS не подгружались и окно оставалось пустым.

Фикс:

```js
// vite.config.js
export default defineConfig({
  base: './',
  plugins: [react()],
  ...
})
```

Также скрыто стандартное меню Electron.
