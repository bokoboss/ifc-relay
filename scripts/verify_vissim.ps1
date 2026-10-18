# Viswalk BIM Builder - full verification on a machine with Vissim 2025.
param([switch]$SkipBuild)

$ErrorActionPreference = "Stop"
$App = Split-Path -Parent $PSScriptRoot
Set-Location $App
$VPy = Join-Path $App ".venv\Scripts\python.exe"
if (-not (Test-Path $VPy)) {
    Write-Host "Not installed yet. Run install.bat first." -ForegroundColor Yellow
    exit 1
}
$argsList = @("scripts\verify_vissim.py")
if ($SkipBuild) { $argsList += "--skip-build" }
& $VPy @argsList
exit $LASTEXITCODE
