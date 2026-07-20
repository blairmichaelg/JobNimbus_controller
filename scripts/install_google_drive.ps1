# Wickham Roofing V4 - Google Drive Setup Script
# Run from the project root directory.
# Requires PowerShell 5.1+ and internet access.
# Right-click -> Run as Administrator.

$ErrorActionPreference = "Stop"
$gdrivePath = "$env:ProgramFiles\Google\Drive File Stream\GoogleDriveFS.exe"

Write-Host ""
Write-Host "=== Wickham Roofing V4: Google Drive for Desktop Setup ===" -ForegroundColor Cyan
Write-Host ""

# -- STEP 1: Check if already installed --
if (Test-Path $gdrivePath) {
    Write-Host "V Google Drive already installed. Skipping download." -ForegroundColor Green
} else {
    # -- STEP 2: Download installer --
    Write-Host "Downloading Google Drive for Desktop installer..." -ForegroundColor Yellow
    $url = "https://dl.google.com/drive-file-stream/GoogleDriveSetup.exe"
    $out = "$env:TEMP\GoogleDriveSetup.exe"

    try {
        Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
        Write-Host "V Download complete: $out" -ForegroundColor Green
    } catch {
        Write-Host "ERROR: Download failed. Check your internet connection." -ForegroundColor Red
        Write-Host "Download manually from: https://google.com/drive/download"
        exit 1
    }

    # -- STEP 3: Run the installer silently --
    Write-Host "Installing Google Drive for Desktop (silent mode)..." -ForegroundColor Yellow
    Start-Process -FilePath $out -ArgumentList "--silent --desktop_shortcut" -Wait
    Write-Host "V Installation complete." -ForegroundColor Green
}

# -- STEP 4: Launch Google Drive --
if (Test-Path $gdrivePath) {
    Write-Host ""
    Write-Host "Launching Google Drive for Desktop..." -ForegroundColor Yellow
    Start-Process $gdrivePath
    Write-Host "V Google Drive launched." -ForegroundColor Green
    Write-Host ""
    Write-Host "ACTION REQUIRED:" -ForegroundColor Magenta
    Write-Host "  Sign in with the Wickham Roofing Google account"
    Write-Host "  in the browser window that opens."
    Write-Host "  Then proceed to Step 2 below."
} else {
    Write-Host ""
    Write-Host "WARNING: Could not find GoogleDriveFS.exe after install." -ForegroundColor Red
    Write-Host "  Please install manually from: https://google.com/drive/download"
}

# -- STEP 5: Print folder sync instructions --
Write-Host ""
Write-Host "=== STEP 2: Configure Folder Sync ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. Click the Google Drive icon in the Windows system tray."
Write-Host "  2. Click the gear icon (Settings) -> Preferences."
Write-Host "  3. Under 'My Computer', click 'Add folder'."

# Resolve the backup path relative to the project root
try {
    $backupPath = Resolve-Path ".\data\backups" -ErrorAction Stop
    Write-Host "  4. Select this folder: $backupPath" -ForegroundColor Yellow
} catch {
    Write-Host "  4. Select the 'data\backups' folder in the project directory." -ForegroundColor Yellow
    Write-Host "     (Folder will be created on first database backup.)"
}

Write-Host "  5. Choose 'Sync with Google Drive' -> Done -> Save."
Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Green
Write-Host "  The data\backups folder will now sync automatically to Google Drive."
Write-Host "  Backups run every 24 hours and are retained for the last 10 snapshots."
Write-Host ""
