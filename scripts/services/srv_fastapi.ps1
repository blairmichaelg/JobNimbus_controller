$repo = "C:\Users\Michael\projects\JobNimbus_controller"
Set-Location -Path $repo
$env:VIRTUAL_ENV = "$repo\venv"
$env:PYTHONPATH = $repo
$env:Path = "$repo\venv\Scripts;" + $env:Path
$logFile = "$repo\logs\srv_fastapi.log"
if (-not (Test-Path "$repo\logs")) { New-Item -ItemType Directory -Path "$repo\logs" -Force | Out-Null }

function Invoke-LogRotation {
    if ((Test-Path $logFile) -and (Get-Item $logFile).Length -gt 10MB) {
        $ts = Get-Date -Format "yyyyMMdd-HHmmss"
        Move-Item -Path $logFile -Destination "$logFile.$ts.old" -Force -ErrorAction SilentlyContinue
    }
    $oldLogs = Get-ChildItem -Path "$repo\logs" -Filter "srv_fastapi.log.*.old" -ErrorAction SilentlyContinue | Sort-Object CreationTime -Descending
    if ($oldLogs.Count -gt 5) { $oldLogs[5..($oldLogs.Count - 1)] | Remove-Item -Force -ErrorAction SilentlyContinue }
}

$restartCount = 0
while ($true) {
    Invoke-LogRotation
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[$timestamp] Starting FastAPI server (Restart Count: $restartCount)..."
    & "$repo\venv\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port 8000 --env-file .env >> $logFile 2>&1
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[$timestamp] FastAPI server terminated. Self-healing in 3 seconds..."
    $restartCount++
    Start-Sleep -Seconds 3
}
