$repo = (Get-Item $PSScriptRoot).Parent.Parent.FullName
$logFile = "$repo\logs\backup_health.log"
$backupDir = "$repo\backups"

function Log-Message {
    param([string]$message, [string]$level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $msg = "[$timestamp] [$level] $message"
    Write-Host $msg
    Add-Content -Path $logFile -Value $msg
}

if (-not (Test-Path $backupDir)) {
    Log-Message "Backup directory does not exist: $backupDir" "ERROR"
    exit 1
}

$recentBackups = Get-ChildItem -Path $backupDir -Filter "*.db.bak" | Where-Object { $_.LastWriteTime -ge (Get-Date).AddHours(-24) }
if ($recentBackups.Count -eq 0) {
    Log-Message "CRITICAL: No recent backups found in the last 24 hours!" "ERROR"
    exit 1
}

Log-Message "Backup health check passed. Found $($recentBackups.Count) recent backup(s)." "INFO"
exit 0
