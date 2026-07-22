# start_production.ps1
# Master switch for local production deployment

Write-Host "Initializing Production Environment..." -ForegroundColor Cyan

# Step 1: Launch the Engine
Write-Host "[1/3] Launching background services (Redis, FastAPI, ARQ)..." -ForegroundColor Yellow
try {
    Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", ".\start_prod.ps1" -WindowStyle Normal
} catch {
    Write-Error "Failed to launch start_prod.ps1. Error: $_"
    exit 1
}

# Step 2: The Buffer
Write-Host "[2/3] Waiting 10 seconds for Uvicorn web server to bind to port 8000..." -ForegroundColor Cyan
Start-Sleep -Seconds 10

# Step 3: The Tunnel
Write-Host "[3/3] Locating cloudflared..." -ForegroundColor Yellow
if (!(Test-Path -Path ".\cloudflared.exe")) {
    Write-Error "FATAL: cloudflared.exe not found! Please run setup_network.ps1 first."
    exit 1
}

Write-Host "Launching Cloudflare Tunnel..." -ForegroundColor Green
try {
    Start-Process ".\cloudflared.exe" -ArgumentList "tunnel", "--url", "http://127.0.0.1:8000" -WindowStyle Normal
    Write-Host "`nDeployment scripts initiated successfully!" -ForegroundColor Green
    Write-Host "Check the new cloudflared window for your public '.trycloudflare.com' URL." -ForegroundColor Cyan
} catch {
    Write-Error "Failed to start Cloudflare tunnel. Error: $_"
    exit 1
}
