# v2.2 build fix

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

Также скрыто стандартное меню Electron (`File / Edit / View / Window`).
