# IFC Relay - qualify the installed Vissim releases.
#   qualify_vissim.bat                                every registered release, synthetic model
#   qualify_vissim.bat -Release 2026                  one release
#   qualify_vissim.bat -Ifc "D:\Models\building.ifc" [-Redact]
#                                                     also build and check a real IFC
param(
    [int[]]$Release = @(),
    [string]$Ifc = "",
    [switch]$Redact
)

$ErrorActionPreference = "Stop"
$App = Split-Path -Parent $PSScriptRoot
Set-Location $App
$VPy = Join-Path $App ".venv\Scripts\python.exe"
if (-not (Test-Path $VPy)) {
    Write-Host "Not installed yet. Run install.bat first." -ForegroundColor Yellow
    exit 1
}
$argsList = @("scripts\qualify_vissim.py")
foreach ($r in $Release) { $argsList += @("--release", "$r") }
if ($Ifc) {
    if (-not (Test-Path -LiteralPath $Ifc)) {
        Write-Host "IFC not found: $Ifc" -ForegroundColor Red
        exit 1
    }
    $argsList += @("--ifc", $Ifc)
}
if ($Redact) { $argsList += "--redact" }
& $VPy @argsList
exit $LASTEXITCODE
