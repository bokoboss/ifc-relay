$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $AppDir
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = "python"
}

Set-Location $AppDir
Write-Host "Starting Viswalk AI Model Builder v0.4.1..."
Write-Host "Open: http://127.0.0.1:8765"
Write-Host ""
& $Python -m uvicorn app:app --host 127.0.0.1 --port 8765
