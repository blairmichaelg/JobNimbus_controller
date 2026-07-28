$bootTime = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$log = "C:\Users\Michael\Desktop\cold_boot_result.txt"
"=== V4 TRUCK SERVER COLD BOOT TIMINGS ===" | Out-File -FilePath $log -Encoding utf8
"System Last Boot Up Time (Power On): $bootTime" | Out-File -FilePath $log -Append -Encoding utf8
$start = Get-Date
"Boot monitoring task started at: $start" | Out-File -FilePath $log -Append -Encoding utf8
$attempts = 0
while ($true) {
    $attempts++
    try {
        $res = Invoke-WebRequest -Uri "https://app.wickhamroofing.app/health" -UseBasicParsing -UserAgent "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" -TimeoutSec 2 -ErrorAction Stop
        if ($res.StatusCode -eq 200) {
            $now = Get-Date
            $elapsedFromBoot = ($now - $bootTime).TotalSeconds
            $elapsedFromLogon = ($now - $start).TotalSeconds
            "" | Out-File -FilePath $log -Append -Encoding utf8
            "CRM publicly reachable via HTTPS at: $now" | Out-File -FilePath $log -Append -Encoding utf8
            "Total time from power-on (LastBootUpTime) to fully operational CRM: $([math]::Round($elapsedFromBoot, 2)) seconds" | Out-File -FilePath $log -Append -Encoding utf8
            "Total time from user logon/startup to operational CRM: $([math]::Round($elapsedFromLogon, 2)) seconds" | Out-File -FilePath $log -Append -Encoding utf8
            "Total HTTP verification probe attempts: $attempts" | Out-File -FilePath $log -Append -Encoding utf8
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
    if ($attempts -gt 180) {
        "Timeout waiting for CRM public reachability after 180 seconds." | Out-File -FilePath $log -Append -Encoding utf8
        break
    }
}

# Capture Task Scheduler statuses and process lists at boot completion
"" | Out-File -FilePath $log -Append -Encoding utf8
"=== POST-BOOT SERVICE HEALTH CHECK ===" | Out-File -FilePath $log -Append -Encoding utf8
Get-ScheduledTask -TaskName "WickhamCRM-0*" | Select-Object TaskName, State | Out-File -FilePath $log -Append -Encoding utf8
Get-Process uvicorn, arq, cloudflared, powershell -ErrorAction SilentlyContinue | Select-Object ProcessName, Id, CPU | Out-File -FilePath $log -Append -Encoding utf8

# Clean up task
Unregister-ScheduledTask -TaskName "WickhamCRM-BootMeasure" -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
