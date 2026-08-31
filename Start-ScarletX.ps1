$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = 'python'
try { & $python --version | Out-Null } catch { Write-Error 'Python 3.11+ is required.'; exit 1 }
New-Item -ItemType Directory -Force -Path data, backups, 'downloads\incomplete', 'downloads\complete', 'downloads\failed' | Out-Null
if (!(Test-Path 'data\scarletx.db') -and (Test-Path 'data\scenecore.db')) {
    Copy-Item 'data\scenecore.db' 'data\scarletx.db'
    Write-Host 'Copied data\scenecore.db to data\scarletx.db for migration; original preserved.'
}
if (!(Test-Path '.venv\Scripts\python.exe')) { & $python -m venv .venv }
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $venvPython -c 'import fastapi,httpx,sqlalchemy,uvicorn,PIL,watchdog,orjson' 2>$null
if ($LASTEXITCODE -ne 0) {
    & $venvPython -m pip install --disable-pip-version-check -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install ScarletX Python dependencies.' }
}
if ($env:SCARLETX_SKIP_ACCEL_INSTALL -ne '1') {
    & $venvPython -c 'import sabctools' 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing optional ScarletX SIMD download acceleration...'
        & $venvPython -m pip install --disable-pip-version-check -r requirements-performance.txt
        if ($LASTEXITCODE -ne 0) { Write-Warning 'SABCTools acceleration unavailable; ScarletX will use its built-in yEnc decoder.' }
    }
}
if (!$env:SCARLETX_DATABASE_URL) { $env:SCARLETX_DATABASE_URL = "sqlite:///$($PSScriptRoot.Replace('\','/'))/data/scarletx.db" }
$hostAddress = if ($env:SCARLETX_HOST) { $env:SCARLETX_HOST } else { '127.0.0.1' }
$port = if ($env:SCARLETX_PORT) { [int]$env:SCARLETX_PORT } else { 8690 }
if (!$env:SCARLETX_PORT) {
    while ($port -lt 8700) {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $port)
        try { $listener.Start(); $listener.Stop(); break } catch { try { $listener.Stop() } catch {}; $port++ }
    }
    if ($port -ge 8700) { throw 'No free ScarletX port found in 8690-8699.' }
}
$url = "http://${hostAddress}:$port"
Write-Host ''
Write-Host 'ScarletX 0.3.8'
Write-Host 'Based on SceneCore 0.7.16 adult functionality'
Write-Host "Opening: $url"
Write-Host ''
Start-Job -ScriptBlock {
    param($url)
    for ($i=0; $i -lt 120; $i++) {
        try {
            $h = Invoke-RestMethod "$url/api/health" -TimeoutSec 1
            if ($h.app -eq 'ScarletX' -and $h.version -eq '0.3.7') { Start-Process $url; return }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
} -ArgumentList $url | Out-Null
& $venvPython -m uvicorn scarletx.main:app --host $hostAddress --port $port
