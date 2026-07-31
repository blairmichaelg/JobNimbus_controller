$repo = (Get-Item $PSScriptRoot).Parent.Parent.FullName
Set-Location -Path $repo
$env:VIRTUAL_ENV = "$repo\venv"
$env:PYTHONPATH = $repo
$env:Path = "$repo\venv\Scripts;" + $env:Path
$logFile = "$repo\logs\srv_redis.log"
if (-not (Test-Path "$repo\logs")) { New-Item -ItemType Directory -Path "$repo\logs" -Force | Out-Null }

function Invoke-LogRotation {
    if ((Test-Path $logFile) -and (Get-Item $logFile).Length -gt 10MB) {
        $ts = Get-Date -Format "yyyyMMdd-HHmmss"
        Move-Item -Path $logFile -Destination "$logFile.$ts.old" -Force -ErrorAction SilentlyContinue
    }
    $oldLogs = Get-ChildItem -Path "$repo\logs" -Filter "srv_redis.log.*.old" -ErrorAction SilentlyContinue | Sort-Object CreationTime -Descending
    if ($oldLogs.Count -gt 5) { $oldLogs[5..($oldLogs.Count - 1)] | Remove-Item -Force -ErrorAction SilentlyContinue }
}

$restartCount = 0
while ($true) {
    Invoke-LogRotation
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[$timestamp] Starting Redis service (Restart Count: $restartCount)..."
    docker info >$null 2>&1
    if ($LASTEXITCODE -eq 0) {
        docker start -a v4-redis-server 2>>$logFile | Out-Null
        if ($LASTEXITCODE -ne 0) {
            docker run --rm -p 6379:6379 --name v4-redis-server redis redis-server --appendonly yes 2>>$logFile | Out-Null
        }
    } else {
        wsl -u root -- /usr/bin/redis-server --bind 0.0.0.0 --daemonize no --appendonly yes 2>>$logFile | Out-Null
    }
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logFile -Value "[$timestamp] Redis process terminated. Self-healing in 3 seconds..."
    $restartCount++
    Start-Sleep -Seconds 3
}
