param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug",
    [ValidateSet("x64", "arm64")]
    [string]$Architecture = "x64"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$preset = if ($Architecture -eq "arm64") { "vs2022-arm64" } else { "vs2022-x64" }
$buildPreset = if ($Architecture -eq "arm64") { "release-arm64" } elseif ($Configuration -eq "Release") { "release" } else { "debug" }

Push-Location $root
try {
    & cmake --preset $preset
    if ($LASTEXITCODE -ne 0) {
        throw "CMake configure failed with exit code $LASTEXITCODE."
    }

    & cmake --build --preset $buildPreset
    if ($LASTEXITCODE -ne 0) {
        throw "CMake build failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
