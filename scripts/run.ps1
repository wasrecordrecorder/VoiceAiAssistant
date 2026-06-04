param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot "build.ps1") -Configuration $Configuration -Architecture "x64"

$executable = Join-Path $root "out/build/vs2022-x64/bin/$Configuration/WebViewDA.exe"
if (-not (Test-Path $executable)) {
    throw "WebViewDA.exe was not produced by the build."
}

& $executable
