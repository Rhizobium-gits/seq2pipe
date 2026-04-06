# ===========================================================
# seq2pipe -- Windows PowerShell Launcher
# ===========================================================
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

# .env
$EnvFile = Join-Path $ScriptDir ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^([^=]+)=(.*)$") {
            [System.Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
        }
    }
}
if (-not $env:QIIME2_AI_MODEL) { $env:QIIME2_AI_MODEL = "qwen2.5-coder:7b" }

# Color helpers
function Write-Info  { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err   { param($msg) Write-Host "[ERR ] $msg" -ForegroundColor Red }

# ----------------------------------------------------------
# Ollama
# ----------------------------------------------------------
function Test-OllamaRunning {
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 -UseBasicParsing
        return $true
    }
    catch {
        return $false
    }
}

if (-not (Test-OllamaRunning)) {
    Write-Warn "Ollama is not running. Attempting to start..."
    $ollamaExe = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollamaExe) {
        Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
        Write-Info "Starting Ollama..."
        $waited = 0
        while (-not (Test-OllamaRunning) -and $waited -lt 20) {
            Start-Sleep -Seconds 1
            $waited++
        }
        if (Test-OllamaRunning) {
            Write-Ok "Ollama is running"
        }
        else {
            Write-Err "Failed to start Ollama."
            Write-Host "  Run 'ollama serve' in another terminal and try again."
            Read-Host "Press Enter to exit"
            exit 1
        }
    }
    else {
        Write-Err "Ollama is not installed."
        Write-Host "  Run setup.bat first."
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# ----------------------------------------------------------
# Model check
# ----------------------------------------------------------
try {
    $tags = (Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing).Content | ConvertFrom-Json
    $models = $tags.models | ForEach-Object { $_.name }
    if (-not $models) {
        Write-Warn "No models found in Ollama."
        $ans = Read-Host "Download qwen2.5-coder:7b now? [y/N]"
        if ($ans -ieq "y") {
            & ollama pull qwen2.5-coder:7b
        }
        else {
            exit 1
        }
    }
}
catch {
    Write-Warn "Failed to get model list: $_"
}

# ----------------------------------------------------------
# Docker check (warning only)
# ----------------------------------------------------------
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd) {
    try {
        $null = & docker info 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Docker Desktop is not running. Start it if you need QIIME2 commands."
        }
    }
    catch {
        Write-Warn "Failed to check Docker status."
    }
}
else {
    Write-Warn "Docker Desktop not found. Docker is needed for QIIME2 analysis."
}

# ----------------------------------------------------------
# QIIME2 conda environment check
# ----------------------------------------------------------
if ($env:QIIME2_CONDA_BIN) {
    Write-Ok "QIIME2: $env:QIIME2_CONDA_BIN"
}
else {
    # Auto-detect
    $qiimeSearch = Get-Item "$env:USERPROFILE\miniforge3\envs\qiime2*\Scripts\qiime.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $qiimeSearch) {
        $qiimeSearch = Get-Item "$env:USERPROFILE\miniconda3\envs\qiime2*\Scripts\qiime.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($qiimeSearch) {
        $env:QIIME2_CONDA_BIN = Split-Path $qiimeSearch.FullName -Parent
        Write-Ok "QIIME2 auto-detected: $env:QIIME2_CONDA_BIN"
    }
    else {
        Write-Warn "QIIME2 not found. Run setup.bat to install."
        Write-Host "  Or set QIIME2_CONDA_BIN in .env"
    }
}

# ----------------------------------------------------------
# Launch Python agent
# ----------------------------------------------------------
Write-Host ""
Write-Info "Starting seq2pipe... (model: $env:QIIME2_AI_MODEL)"
Write-Host ""

# Use QIIME2 conda Python if available
$pythonExe = "python"
if ($env:QIIME2_CONDA_BIN -and (Test-Path "$env:QIIME2_CONDA_BIN\python.exe")) {
    $pythonExe = "$env:QIIME2_CONDA_BIN\python.exe"
    Write-Info "Using QIIME2 Python: $pythonExe"
}

$AgentScript = Join-Path $ScriptDir "cli.py"
& $pythonExe $AgentScript @args
if ($LASTEXITCODE -ne 0) {
    Write-Err "Agent exited with error."
    Read-Host "Press Enter to exit"
}
