$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
Push-Location $backend
try {
    python -m pip install -r requirements-test.txt
    $env:PYTHONPATH = $backend
    python -m unittest discover -s assistant_backend/tests -v
}
finally {
    Pop-Location
}
