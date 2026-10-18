# Viswalk BIM Builder - Windows installer (no .exe)
# Creates .venv inside the app folder, installs Python packages, downloads the
# local Three.js runtime, prepares the local\ folder for the Geometry Engine and
# base_empty.inpx, and checks Vissim COM registration.
#
#   install.bat
#   install.bat -EnginePath D:\proj\05_geometry_engine_v03.py -BaseNetworkPath D:\proj\base_empty.inpx

param(
    [string]$EnginePath = "",
    [string]$BaseNetworkPath = "",
    [string]$Fixture1Ifc = ""
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$App = Split-Path -Parent $PSScriptRoot
Set-Location $App
$Local = Join-Path $App "local"
$Venv = Join-Path $App ".venv"
$VPy = Join-Path $Venv "Scripts\python.exe"

function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "   OK   $text" -ForegroundColor Green }
function Warn($text) { Write-Host "   WARN $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host "   FAIL $text" -ForegroundColor Red }

Write-Host "Viswalk BIM Builder - install" -ForegroundColor White
Write-Host "App folder: $App"

# ---------------------------------------------------------------------------
Step "1/5 Python 3.10 - 3.13"
# ---------------------------------------------------------------------------
function Test-Python([string[]]$cmd) {
    try {
        $exe = $cmd[0]; $rest = @(); if ($cmd.Length -gt 1) { $rest = $cmd[1..($cmd.Length - 1)] }
        $v = & $exe @rest -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $v) { return $null }
        $parts = $v.Trim().Split(".")
        if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10 -and [int]$parts[1] -le 13) { return $v.Trim() }
    } catch { }
    return $null
}

$PyCmd = $null
if (Test-Path $VPy) {
    $ver = Test-Python @($VPy)
    if ($ver) { $PyCmd = @($VPy); Ok "existing .venv uses Python $ver" }
}
if (-not $PyCmd) {
    foreach ($c in @(@("py", "-3.12"), @("py", "-3.13"), @("py", "-3.11"), @("py", "-3.10"), @("python"))) {
        $ver = Test-Python $c
        if ($ver) { $PyCmd = $c; Ok "found Python $ver ($($c -join ' '))"; break }
    }
}
if (-not $PyCmd) {
    Fail "Python 3.10 - 3.13 not found."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $answer = Read-Host "   Install Python 3.12 for this user with winget now? [Y/n]"
        if ($answer -eq "" -or $answer -match "^[Yy]") {
            winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
            Write-Host "   Python installed. Close this window and run install.bat again." -ForegroundColor Yellow
            exit 1
        }
    }
    Write-Host "   Install Python 3.12 from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run install.bat again."
    exit 1
}

# ---------------------------------------------------------------------------
Step "2/5 Virtual environment and packages"
# ---------------------------------------------------------------------------
if (-not (Test-Path $VPy)) {
    $exe = $PyCmd[0]; $rest = @(); if ($PyCmd.Length -gt 1) { $rest = $PyCmd[1..($PyCmd.Length - 1)] }
    & $exe @rest -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail "could not create .venv"; exit 1 }
    Ok "created .venv"
}
& $VPy -m pip install --disable-pip-version-check -q --upgrade pip
& $VPy -m pip install --disable-pip-version-check -r requirements.txt -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { Fail "pip install failed (see messages above)"; exit 1 }
Ok "packages installed"

# ---------------------------------------------------------------------------
Step "3/5 Three.js browser runtime (local copy)"
# ---------------------------------------------------------------------------
$VendorDir = Join-Path $App "static\vendor"
$ControlsDir = Join-Path $VendorDir "jsm\controls"
$ThreeVersion = "0.186.1"
$targets = @(
    @("https://cdn.jsdelivr.net/npm/three@$ThreeVersion/build/three.module.js", (Join-Path $VendorDir "three.module.js")),
    @("https://cdn.jsdelivr.net/npm/three@$ThreeVersion/build/three.core.js", (Join-Path $VendorDir "three.core.js")),
    @("https://cdn.jsdelivr.net/npm/three@$ThreeVersion/examples/jsm/controls/OrbitControls.js", (Join-Path $ControlsDir "OrbitControls.js"))
)
$allPresent = $true
foreach ($t in $targets) { if (-not (Test-Path $t[1])) { $allPresent = $false } }
if ($allPresent) {
    Ok "already present"
} else {
    New-Item -ItemType Directory -Force -Path $ControlsDir | Out-Null
    try {
        foreach ($t in $targets) { Invoke-WebRequest -UseBasicParsing -Uri $t[0] -OutFile $t[1] }
        $orbit = Join-Path $ControlsDir "OrbitControls.js"
        $text = Get-Content -Path $orbit -Raw -Encoding UTF8
        $text = $text.Replace("from 'three';", "from '../../three.module.js';").Replace('from "three";', 'from "../../three.module.js";')
        Set-Content -Path $orbit -Value $text -Encoding UTF8
        Ok "Three.js $ThreeVersion downloaded"
    } catch {
        Warn "download failed ($($_.Exception.Message)). The 3D viewer needs it; run install.bat again when online."
    }
}

# ---------------------------------------------------------------------------
Step "4/5 Geometry Engine and Vissim base network"
# ---------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $Local | Out-Null
$Parent = Split-Path -Parent $App

function Place-File([string]$given, [string]$name) {
    $dest = Join-Path $Local $name
    if ($given) {
        if (-not (Test-Path $given)) { Fail "$name not found at $given"; return $false }
        Copy-Item -Force $given $dest
        Ok "$name copied to local\"
        return $true
    }
    if (Test-Path $dest) { Ok "$name in local\"; return $true }
    if (Test-Path (Join-Path $Parent $name)) { Ok "$name found in parent folder (original layout)"; return $true }
    Warn "$name missing. Copy it into: $Local"
    return $false
}
$engineOk = Place-File $EnginePath "05_geometry_engine_v03.py"
$baseOk = Place-File $BaseNetworkPath "base_empty.inpx"
if ($Fixture1Ifc) { [void](Place-File $Fixture1Ifc "TallBuilding.ifc") }

# ---------------------------------------------------------------------------
Step "5/5 Vissim 2025 COM"
# ---------------------------------------------------------------------------
if (Test-Path "Registry::HKEY_CLASSES_ROOT\VISSIM.Vissim.2025") {
    Ok "VISSIM.Vissim.2025 is registered"
} else {
    Warn "VISSIM.Vissim.2025 not registered on this machine. The app still runs; Build Viswalk needs Vissim 2025."
}

Write-Host ""
Write-Host "Install finished." -ForegroundColor Green
if (-not ($engineOk -and $baseOk)) {
    Write-Host "Put 05_geometry_engine_v03.py and base_empty.inpx in $Local before Validate / Build." -ForegroundColor Yellow
}
Write-Host "Next: start.bat (open the app)  or  verify_vissim.bat (full check with Vissim)."
