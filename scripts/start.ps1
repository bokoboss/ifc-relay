# IFC Relay - start the local web app and open the browser.
param([int]$Port = 8765)

$ErrorActionPreference = "Stop"
$App = Split-Path -Parent $PSScriptRoot
Set-Location $App
$VPy = Join-Path $App ".venv\Scripts\python.exe"
if (-not (Test-Path $VPy)) {
    Write-Host "Not installed yet. Run install.bat first." -ForegroundColor Yellow
    exit 1
}

$url = "http://127.0.0.1:$Port"
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host "Port $Port is already in use - the app may already be running. Opening $url"
    Start-Process $url
    exit 0
}

Write-Host "IFC Relay: $url  (close this window or press Ctrl+C to stop)"
Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile", "-Command", "Start-Sleep -Seconds 3; Start-Process '$url'"
& $VPy -m uvicorn app:app --host 127.0.0.1 --port $Port
