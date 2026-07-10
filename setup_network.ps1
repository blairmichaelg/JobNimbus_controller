# setup_network.ps1
# Automates the download of Cloudflare Tunnel for secure public access

$exeName = "cloudflared.exe"
$downloadUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"

if (Test-Path -Path $exeName) {
    Write-Host "cloudflared.exe already exists. Skipping download." -ForegroundColor Green
} else {
    Write-Host "Downloading cloudflared.exe from GitHub..." -ForegroundColor Yellow
    try {
        # Using basic parsing for faster download on older PS versions
        Invoke-WebRequest -Uri $downloadUrl -OutFile $exeName -UseBasicParsing
        Write-Host "Download complete! cloudflared.exe is ready." -ForegroundColor Green
    } catch {
        Write-Error "Failed to download cloudflared.exe. Please check your internet connection or GitHub status. Error: $_"
        exit 1
    }
}
