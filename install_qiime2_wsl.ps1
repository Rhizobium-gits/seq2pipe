# ===========================================================
# seq2pipe — Install WSL2 + QIIME2 on Windows (one-click)
# ===========================================================
$ErrorActionPreference = "Continue"

function Write-Info  { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Write-Err   { param($msg) Write-Host "[ERR ] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "  Installing QIIME2 via WSL2 (Ubuntu)" -ForegroundColor Cyan
Write-Host "  This is a one-time setup (~15-30 min)" -ForegroundColor DarkGray
Write-Host ""

# Step 1: Install WSL2
Write-Info "Checking WSL2..."
$wslCheck = wsl --status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Info "Installing WSL2 + Ubuntu..."
    Write-Host "  This may require a restart. After restart, run this script again." -ForegroundColor Yellow
    wsl --install -d Ubuntu
    if ($LASTEXITCODE -ne 0) {
        Write-Err "WSL install failed. Run as Administrator:"
        Write-Host "  wsl --install" -ForegroundColor Cyan
        Read-Host "Press Enter"
        exit 1
    }
    Write-Ok "WSL2 installed. Please RESTART your PC, then run this script again."
    Read-Host "Press Enter to exit"
    exit 0
}

# Check Ubuntu is available
$distros = wsl --list --quiet 2>&1
if ($distros -notmatch "Ubuntu") {
    Write-Info "Installing Ubuntu on WSL..."
    wsl --install -d Ubuntu
    Write-Ok "Ubuntu installed. It may ask you to create a username/password."
    Write-Host "  After setup, run this script again." -ForegroundColor Yellow
    Read-Host "Press Enter"
    exit 0
}

Write-Ok "WSL2 + Ubuntu ready"

# Step 2: Install Miniforge + QIIME2 inside WSL
Write-Info "Installing Miniforge + QIIME2 inside WSL (Ubuntu)..."
Write-Host "  This takes 10-20 minutes. Please wait..." -ForegroundColor DarkGray

$installScript = @'
set -e
echo "=== Installing Miniforge ==="
if [ ! -f ~/miniforge3/bin/conda ]; then
    curl -fsSL https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -o /tmp/miniforge.sh
    bash /tmp/miniforge.sh -b -p ~/miniforge3
    rm /tmp/miniforge.sh
    ~/miniforge3/bin/conda init bash
fi
export PATH=~/miniforge3/bin:$PATH

echo "=== Creating QIIME2 environment ==="
if [ ! -f ~/miniforge3/envs/qiime2-amplicon-2024.10/bin/qiime ]; then
    conda create -n qiime2-amplicon-2024.10 \
        -c https://packages.qiime2.org/qiime2/2024.10/amplicon/released \
        -c conda-forge -c bioconda -c defaults \
        qiime2-amplicon=2024.10 --yes
fi

echo "=== Verifying ==="
~/miniforge3/envs/qiime2-amplicon-2024.10/bin/qiime --version
echo "QIIME2_OK"
'@

$result = $installScript | wsl bash 2>&1
$resultStr = $result -join "`n"

if ($resultStr -match "QIIME2_OK") {
    Write-Ok "QIIME2 installed in WSL!"
    
    # Save path to .env
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
    $envFile = Join-Path $ScriptDir ".env"
    $envContent = @()
    if (Test-Path $envFile) {
        $envContent = Get-Content $envFile | Where-Object { $_ -notmatch "^QIIME2_USE_WSL=" }
    }
    $envContent += "QIIME2_USE_WSL=1"
    $envContent | Set-Content -Path $envFile -Encoding UTF8
    Write-Ok "Saved WSL config to .env"
}
else {
    Write-Err "QIIME2 install may have failed. Output:"
    Write-Host $resultStr
}

Write-Host ""
Write-Host "Setup complete! Run seq2pipe:" -ForegroundColor Green
Write-Host "  .\launch.ps1 --auto --fastq-dir C:\path\to\data" -ForegroundColor Cyan
Read-Host "Press Enter to exit"
