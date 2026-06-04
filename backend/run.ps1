param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 48761,
    [string]$Token = "development"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $root ".venv/Scripts/python.exe"
$dataDir = Join-Path $env:LOCALAPPDATA "WebViewDA"
& $pythonExe -m assistant_backend --host $HostAddress --port $Port --token $Token --data-dir $dataDir
