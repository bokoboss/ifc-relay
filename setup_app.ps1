$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $AppDir
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = "python"
}

Write-Host "Using Python: $Python"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $AppDir "requirements.txt")

$VendorDir = Join-Path $AppDir "static\vendor"
$ControlsDir = Join-Path $VendorDir "jsm\controls"
New-Item -ItemType Directory -Force -Path $ControlsDir | Out-Null

$ThreeVersion = "0.186.1"
$ThreeModuleUrl = "https://cdn.jsdelivr.net/npm/three@$ThreeVersion/build/three.module.js"
$ThreeCoreUrl = "https://cdn.jsdelivr.net/npm/three@$ThreeVersion/build/three.core.js"
$OrbitUrl = "https://cdn.jsdelivr.net/npm/three@$ThreeVersion/examples/jsm/controls/OrbitControls.js"

Write-Host "Downloading Three.js $ThreeVersion local runtime..."
Invoke-WebRequest -Uri $ThreeModuleUrl -OutFile (Join-Path $VendorDir "three.module.js")
Invoke-WebRequest -Uri $ThreeCoreUrl -OutFile (Join-Path $VendorDir "three.core.js")
Invoke-WebRequest -Uri $OrbitUrl -OutFile (Join-Path $ControlsDir "OrbitControls.js")

$OrbitFile = Join-Path $ControlsDir "OrbitControls.js"
$OrbitText = Get-Content -Path $OrbitFile -Raw -Encoding UTF8
$OrbitText = $OrbitText.Replace("from 'three';", "from '../../three.module.js';")
$OrbitText = $OrbitText.Replace('from "three";', 'from "../../three.module.js";')
$OrbitText = $OrbitText.Replace("from 'three'", "from '../../three.module.js'")
$OrbitText = $OrbitText.Replace('from "three"', 'from "../../three.module.js"')
Set-Content -Path $OrbitFile -Value $OrbitText -Encoding UTF8

Write-Host "PASS: Three.js module + core + OrbitControls installed locally."
Write-Host "Setup v0.4.1 complete."
