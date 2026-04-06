# ===========================================================
# seq2pipe -- Windows PowerShell Setup Script
# Installs: Python, Ollama, LLM model, Miniforge + QIIME2
# ===========================================================
$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

function Write-Info  { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err   { param($msg) Write-Host "[ERR ] $msg" -ForegroundColor Red }
function Write-Sep   { Write-Host ("-" * 60) -ForegroundColor DarkGray }

Write-Host @"

  seq2pipe -- Windows Setup
  sequence -> pipeline

"@ -ForegroundColor Cyan

Write-Sep

# ----------------------------------------------------------
# STEP 1: Python
# ----------------------------------------------------------
Write-Info "Checking Python..."
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    $pythonCmd = Get-Command python3 -ErrorAction SilentlyContinue
}
if ($pythonCmd) {
    $pyVer = & $pythonCmd.Name --version 2>&1
    Write-Ok "Python: $pyVer"
}
else {
    Write-Warn "Python not found."
    Write-Host "  Install from https://www.python.org/downloads/"
    Write-Host "  Check 'Add Python to PATH' during install."
    Read-Host "Press Enter after installing Python"
}

Write-Sep

# ----------------------------------------------------------
# STEP 2: Miniforge + QIIME2 conda
# ----------------------------------------------------------
Write-Info "Checking QIIME2 conda environment..."

$qiime2Found = $false
$qiime2Bin = ""

# Search common paths
$searchPaths = @(
    "$env:USERPROFILE\miniforge3\envs\qiime2*\Scripts\qiime.exe",
    "$env:USERPROFILE\miniconda3\envs\qiime2*\Scripts\qiime.exe",
    "$env:USERPROFILE\anaconda3\envs\qiime2*\Scripts\qiime.exe",
    "$env:USERPROFILE\miniforge3\envs\qiime2*\bin\qiime",
    "C:\miniforge3\envs\qiime2*\Scripts\qiime.exe"
)
foreach ($pattern in $searchPaths) {
    $found = Get-Item $pattern -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) {
        $qiime2Bin = Split-Path $found.FullName -Parent
        $qiime2Found = $true
        Write-Ok "QIIME2 found: $qiime2Bin"
        break
    }
}

if (-not $qiime2Found) {
    Write-Warn "QIIME2 not found."
    Write-Host ""
    Write-Host "  QIIME2 requires Miniforge (conda) on Windows." -ForegroundColor White
    Write-Host ""
    $ans = Read-Host "Install Miniforge + QIIME2 now? (may take 10-20 min) [Y/n]"
    if ($ans -ine "n") {
        # Install Miniforge
        $condaCmd = Get-Command conda -ErrorAction SilentlyContinue
        if (-not $condaCmd) {
            Write-Info "Downloading Miniforge..."
            $mfUrl = "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Windows-x86_64.exe"
            $mfPath = "$env:TEMP\Miniforge3-Setup.exe"
            Invoke-WebRequest -Uri $mfUrl -OutFile $mfPath -UseBasicParsing
            Write-Info "Installing Miniforge (silent)..."
            Start-Process -FilePath $mfPath -ArgumentList "/S /D=$env:USERPROFILE\miniforge3" -Wait
            Remove-Item $mfPath -Force -ErrorAction SilentlyContinue

            # Add to PATH for this session
            $env:PATH = "$env:USERPROFILE\miniforge3\Scripts;$env:USERPROFILE\miniforge3\condabin;$env:PATH"
            Write-Ok "Miniforge installed"
        }
        else {
            Write-Ok "conda already available"
        }

        # Create QIIME2 environment
        Write-Info "Creating QIIME2 conda environment (this takes 10-20 min)..."
        Write-Host "  Installing qiime2-amplicon-2024.10..."
        $condaExe = "$env:USERPROFILE\miniforge3\condabin\conda.bat"
        if (-not (Test-Path $condaExe)) {
            $condaExe = "conda"
        }

        & $condaExe create -n qiime2-amplicon-2024.10 `
            -c https://packages.qiime2.org/qiime2/2024.10/amplicon/released `
            -c conda-forge -c bioconda -c defaults `
            qiime2-amplicon=2024.10 --yes 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }

        # Verify
        $qiimeCheck = Get-Item "$env:USERPROFILE\miniforge3\envs\qiime2*\Scripts\qiime.exe" -ErrorAction SilentlyContinue
        if ($qiimeCheck) {
            $qiime2Bin = Split-Path $qiimeCheck.FullName -Parent
            $qiime2Found = $true
            Write-Ok "QIIME2 installed: $qiime2Bin"
        }
        else {
            Write-Err "QIIME2 installation may have failed. Check conda output above."
        }
    }
}

# Save QIIME2 path
if ($qiime2Found) {
    $envContent = @()
    $envFile = Join-Path $ScriptDir ".env"
    if (Test-Path $envFile) {
        $envContent = Get-Content $envFile | Where-Object { $_ -notmatch "^QIIME2_CONDA_BIN=" }
    }
    $envContent += "QIIME2_CONDA_BIN=$qiime2Bin"
    $envContent | Set-Content -Path $envFile -Encoding UTF8
    Write-Ok "QIIME2 path saved to .env"
}

Write-Sep

# ----------------------------------------------------------
# STEP 3: Ollama
# ----------------------------------------------------------
Write-Info "Checking Ollama..."
$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaCmd) {
    $ollamaVer = & ollama --version 2>&1
    Write-Ok "Ollama: $ollamaVer"
}
else {
    Write-Info "Installing Ollama..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        & winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
    }
    else {
        $installerUrl = "https://ollama.com/download/OllamaSetup.exe"
        $installerPath = "$env:TEMP\OllamaSetup.exe"
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing
        Start-Process -FilePath $installerPath -Wait
        Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
    }
    $ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollamaCmd) {
        Write-Ok "Ollama installed"
    }
    else {
        Write-Warn "Ollama install not confirmed. Restart terminal and retry."
    }
}

Write-Sep

# ----------------------------------------------------------
# STEP 4: Start Ollama + pull model
# ----------------------------------------------------------
Write-Info "Checking Ollama service..."
try {
    $null = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 -UseBasicParsing
    Write-Ok "Ollama service running"
}
catch {
    Write-Info "Starting Ollama..."
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 4
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 -UseBasicParsing
        Write-Ok "Ollama started"
    }
    catch {
        Write-Warn "Ollama start timed out. Wait and retry."
    }
}

Write-Host ""
Write-Host "Select LLM model:" -ForegroundColor White
Write-Host "  1) qwen2.5-coder:7b  [recommended] (4.7 GB, RAM 8GB+)" -ForegroundColor White
Write-Host "  2) qwen2.5-coder:3b  [lightweight] (1.9 GB, RAM 4GB+)" -ForegroundColor White
Write-Host "  3) Skip (use existing model)"
Write-Host ""
$choice = Read-Host "Select [1/2/3]"

switch ($choice) {
    "1"   { $model = "qwen2.5-coder:7b" }
    "2"   { $model = "qwen2.5-coder:3b" }
    default { $model = "" }
}

if ($model) {
    Write-Info "Downloading model '$model'..."
    & ollama pull $model
    Write-Ok "Model '$model' ready"

    $envFile = Join-Path $ScriptDir ".env"
    $envContent = @()
    if (Test-Path $envFile) {
        $envContent = Get-Content $envFile | Where-Object { $_ -notmatch "^QIIME2_AI_MODEL=" }
    }
    $envContent += "QIIME2_AI_MODEL=$model"
    $envContent | Set-Content -Path $envFile -Encoding UTF8
}

Write-Sep

# ----------------------------------------------------------
# STEP 5: Python packages
# ----------------------------------------------------------
Write-Info "Installing Python packages..."
& python -m pip install --quiet matplotlib seaborn pandas numpy scipy scikit-learn networkx statsmodels 2>&1 | Out-Null
Write-Ok "Python packages installed"

Write-Sep

# ----------------------------------------------------------
# Done
# ----------------------------------------------------------
Write-Host ""
Write-Host ("=" * 60) -ForegroundColor Green
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host ("=" * 60) -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host ""
Write-Host "  Run seq2pipe:" -ForegroundColor Cyan
Write-Host "    .\launch.ps1 --smart --fastq-dir C:\path\to\data --metadata meta.tsv"
Write-Host ""
Write-Host "  Or double-click: launch.bat"
Write-Host ""
Read-Host "Press Enter to exit"
