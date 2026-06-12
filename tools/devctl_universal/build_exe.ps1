param(
    [switch]$CleanVenv
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if ($CleanVenv -and (Test-Path ".venv")) {
    Remove-Item -Recurse -Force ".venv"
}

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip pyinstaller
if ($LASTEXITCODE -ne 0) {
    throw "pip install failed with exit code $LASTEXITCODE"
}

& ".\.venv\Scripts\pyinstaller.exe" "build\pyinstaller.spec" --clean --noconfirm
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$ExePath = Join-Path $ProjectRoot "release\devctl-gui.exe"
if (-not (Test-Path $ExePath)) {
    throw "Build finished but expected exe was not created: $ExePath"
}

Write-Host ""
Write-Host "Done: $ExePath"
