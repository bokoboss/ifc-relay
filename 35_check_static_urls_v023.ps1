$ErrorActionPreference = "Stop"

$Urls = @(
    "http://127.0.0.1:8765/static/app3d.js?v=023",
    "http://127.0.0.1:8765/static/vendor/three.module.js",
    "http://127.0.0.1:8765/static/vendor/three.core.js",
    "http://127.0.0.1:8765/static/vendor/jsm/controls/OrbitControls.js"
)

Write-Host "Static module URL check v0.2.3"
Write-Host "============================================================"

foreach ($Url in $Urls) {
    try {
        $Response = Invoke-WebRequest -Uri $Url -UseBasicParsing
        $ContentType = $Response.Headers["Content-Type"]
        Write-Host "PASS: $($Response.StatusCode) $ContentType $Url"
    }
    catch {
        Write-Host "FAIL: $Url"
        throw
    }
}

Write-Host ""
Write-Host "STATIC URL CHECK: PASS"
