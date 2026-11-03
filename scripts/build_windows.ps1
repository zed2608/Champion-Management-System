$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not $IsWindows) {
    throw "This script builds the Windows executable and must run on Windows."
}

python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-build.txt
python -m pytest -q tests/test_validators.py tests/test_paging.py tests/test_backup_encryption.py
python -m PyInstaller --clean --noconfirm ChampionManagement.spec

$exe = Join-Path $PWD "dist\ChampionManagement\ChampionManagement.exe"
if (-not (Test-Path $exe)) {
    throw "Build finished without the expected executable: $exe"
}

& $exe --smoke-test
if ($LASTEXITCODE -ne 0) {
    throw "Executable smoke test failed with exit code $LASTEXITCODE."
}

Write-Host "Build and smoke test passed: $exe"
