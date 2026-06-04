param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot "build.ps1") -Configuration $Configuration -Architecture "x64"

$output = Join-Path $root "out/build/vs2022-x64/bin/$Configuration/backend"
$bootstrap = Join-Path $output "bootstrap.ps1"
if (-not (Test-Path $bootstrap)) {
    throw "Backend files were not copied to the build output."
}

& $bootstrap
Write-Host "WebViewDA is prepared for launch."
