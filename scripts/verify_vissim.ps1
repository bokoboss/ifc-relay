# IFC Relay - verification.
#   verify_vissim.bat                         full check with Vissim 2025/2026 (synthetic model)
#   verify_vissim.bat -SkipBuild              same, without the Vissim COM build
#   verify_vissim.bat -Ifc "D:\Models\building.ifc" -SkipBuild [-Redact] [-StairsReviewOnly]
#                                             dry run of a real IFC, no Vissim / base_empty.inpx needed
param(
    [switch]$SkipBuild,
    [string]$Ifc = "",
    [switch]$Redact,
    [switch]$StairsReviewOnly
)

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
if ($Ifc) {
    if (-not (Test-Path -LiteralPath $Ifc)) {
        Write-Host "IFC not found: $Ifc" -ForegroundColor Red
        exit 1
    }
    $argsList += @("--ifc", $Ifc)
    if ($Redact) { $argsList += "--redact" }
    if ($StairsReviewOnly) { $argsList += "--stairs-review-only" }
}
& $VPy @argsList
exit $LASTEXITCODE
