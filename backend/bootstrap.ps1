param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root ".venv"

& $Python -m venv $venv
if ($LASTEXITCODE -ne 0) {
    throw "Python virtual environment creation failed with exit code $LASTEXITCODE."
}

$pythonExe = Join-Path $venv "Scripts/python.exe"
& $pythonExe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed with exit code $LASTEXITCODE."
}

& $pythonExe -m pip install -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Backend dependency installation failed with exit code $LASTEXITCODE."
}

Write-Host "Backend environment prepared: $venv"
