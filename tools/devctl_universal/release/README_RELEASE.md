# release/

После сборки на Windows командой

```powershell
pyinstaller build\pyinstaller.spec --clean --noconfirm
```

здесь появится файл:

```text
devctl-gui.exe
```

В этом архиве исходников `.exe` не приложен: Windows-бинарник нужно собрать на Windows-машине или в Windows VM, чтобы корректно проверить Tkinter, Git, кодировки, длинные пути и кириллицу в путях.
