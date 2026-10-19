# Build dist\SplunkSequence\ (one-folder, windowed). Run from the repo root with PyInstaller installed.
$ErrorActionPreference = "Stop"
pyinstaller --noconfirm --clean --windowed --name SplunkSequence `
    --collect-all playwright `
    --add-data "config.example.yaml;." `
    app.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Copy-Item config.example.yaml, README.md dist\SplunkSequence\
