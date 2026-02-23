# ===========================================================
# seq2pipe -- Windows PowerShell Launcher
# ===========================================================
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

# .env からモデル設定を読み込む
$EnvFile = Join-Path $ScriptDir ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^([^=]+)=(.*)$") {
            [System.Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
        }
    }
}
if (-not $env:QIIME2_AI_MODEL) { $env:QIIME2_AI_MODEL = "qwen2.5-coder:7b" }

# カラー出力ヘルパー
function Write-Info  { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err   { param($msg) Write-Host "[ERR ] $msg" -ForegroundColor Red }

# ----------------------------------------------------------
# Ollama 起動確認・自動起動
# ----------------------------------------------------------
function Test-OllamaRunning {
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 -UseBasicParsing
        return $true
    } catch { return $false }
}

if (-not (Test-OllamaRunning)) {
    Write-Warn "Ollama が起動していません。自動起動を試みます..."
    $ollamaExe = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollamaExe) {
        Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
        Write-Info "Ollama を起動しました。起動待機中..."
        $waited = 0
        while (-not (Test-OllamaRunning) -and $waited -lt 20) {
            Start-Sleep -Seconds 1
            $waited++
        }
        if (Test-OllamaRunning) {
            Write-Ok "Ollama 起動確認"
        } else {
            Write-Err "Ollama の起動に失敗しました。"
            Write-Host "  別のターミナルで 'ollama serve' を実行してから再試行してください。"
            Read-Host "Enter キーで終了"
            exit 1
        }
    } else {
        Write-Err "Ollama がインストールされていません。"
        Write-Host "  先に setup.bat を実行してください。"
        Read-Host "Enter キーで終了"
        exit 1
    }
}

# ----------------------------------------------------------
# モデル確認
# ----------------------------------------------------------
try {
    $tags = (Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing).Content | ConvertFrom-Json
    $models = $tags.models | ForEach-Object { $_.name }
    if (-not $models) {
        Write-Warn "Ollama にモデルがインストールされていません。"
        $ans = Read-Host "今すぐ qwen2.5-coder:7b をダウンロードしますか? [y/N]"
        if ($ans -ieq "y") {
            & ollama pull qwen2.5-coder:7b
        } else { exit 1 }
    }
} catch {
    Write-Warn "モデル一覧の取得に失敗しました: $_"
}

# ----------------------------------------------------------
# Docker Desktop 確認（警告のみ）
# ----------------------------------------------------------
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd) {
    try {
        $null = & docker info 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Docker Desktop が起動していません。QIIME2 コマンド実行時に起動してください。"
        }
    } catch { Write-Warn "Docker の状態確認に失敗しました。" }
} else {
    Write-Warn "Docker Desktop が見つかりません。QIIME2 解析には Docker Desktop が必要です。"
}

# ----------------------------------------------------------
# Python エージェント起動
# ----------------------------------------------------------
Write-Host ""
Write-Info "seq2pipe を起動しています... (モデル: $env:QIIME2_AI_MODEL)"
Write-Host ""

$AgentScript = Join-Path $ScriptDir "qiime2_agent.py"
& python $AgentScript
if ($LASTEXITCODE -ne 0) {
    Write-Err "エージェントがエラーで終了しました。"
    Read-Host "Enter キーで終了"
}
