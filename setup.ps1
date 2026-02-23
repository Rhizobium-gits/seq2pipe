# ===========================================================
# seq2pipe -- Windows PowerShell Setup Script
# Ollama のインストール・モデルのダウンロードを自動で行います
# ===========================================================
$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

function Write-Info  { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err   { param($msg) Write-Host "[ERR ] $msg" -ForegroundColor Red; exit 1 }
function Write-Sep   { Write-Host ("-" * 60) -ForegroundColor DarkGray }

# ----------------------------------------------------------
# バナー
# ----------------------------------------------------------
Write-Host @"

  seq2pipe -- Windows セットアップ
  sequence -> pipeline

"@ -ForegroundColor Cyan

Write-Sep

# ----------------------------------------------------------
# STEP 1: Python の確認
# ----------------------------------------------------------
Write-Info "Python を確認しています..."
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    $pythonCmd = Get-Command python3 -ErrorAction SilentlyContinue
}
if ($pythonCmd) {
    $pyVer = & $pythonCmd.Name --version 2>&1
    Write-Ok "Python: $pyVer"
} else {
    Write-Warn "Python が見つかりません。"
    Write-Host "  https://www.python.org/downloads/ からインストールしてください。"
    Write-Host "  インストール時に 'Add Python to PATH' にチェックを入れてください。"
    $ans = Read-Host "インストール後に続行しますか? [y/N]"
    if ($ans -ine "y") { exit 1 }
}

Write-Sep

# ----------------------------------------------------------
# STEP 2: Ollama のインストール
# ----------------------------------------------------------
Write-Info "Ollama を確認しています..."
$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaCmd) {
    $ollamaVer = & ollama --version 2>&1
    Write-Ok "Ollama: $ollamaVer"
} else {
    Write-Info "Ollama をインストールします..."

    # winget 経由（Windows 11 / 最新 Windows 10）
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Info "winget 経由でインストールします..."
        & winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
    } else {
        # 直接ダウンロード
        Write-Info "インストーラーを直接ダウンロードします..."
        $installerUrl = "https://ollama.com/download/OllamaSetup.exe"
        $installerPath = "$env:TEMP\OllamaSetup.exe"
        Write-Info "ダウンロード中: $installerUrl"
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing
        Write-Info "インストーラーを実行します..."
        Start-Process -FilePath $installerPath -Wait
        Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
    }

    # インストール後の確認
    $ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollamaCmd) {
        Write-Ok "Ollama のインストールが完了しました"
    } else {
        Write-Warn "Ollama のインストールを確認できませんでした。"
        Write-Host "  ターミナルを再起動して再度実行してください。"
    }
}

Write-Sep

# ----------------------------------------------------------
# STEP 3: Ollama サービスの起動
# ----------------------------------------------------------
Write-Info "Ollama サービスを確認しています..."
try {
    $null = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 -UseBasicParsing
    Write-Ok "Ollama サービス: 起動中"
} catch {
    Write-Info "Ollama サービスを起動します..."
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 4
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 -UseBasicParsing
        Write-Ok "Ollama サービスが起動しました"
    } catch {
        Write-Warn "Ollama の起動確認がタイムアウトしました。しばらく待って再試行してください。"
    }
}

Write-Sep

# ----------------------------------------------------------
# STEP 4: LLM モデルの選択とダウンロード
# ----------------------------------------------------------
Write-Host ""
Write-Host "使用するモデルを選択してください:" -ForegroundColor White
Write-Host ""
Write-Host "  1) qwen2.5-coder:7b  [推奨] コード生成特化・高精度 (約 4.7GB)" -ForegroundColor White
Write-Host "     RAM 8GB 以上推奨"
Write-Host ""
Write-Host "  2) qwen2.5-coder:3b  [軽量] 高速・省メモリ (約 1.9GB)" -ForegroundColor White
Write-Host "     RAM 4GB 以上"
Write-Host ""
Write-Host "  3) llama3.2:3b       [汎用] 会話能力が高い (約 2.0GB)" -ForegroundColor White
Write-Host ""
Write-Host "  4) qwen3:8b          [最高品質] 推論も高性能 (約 5.2GB)" -ForegroundColor White
Write-Host "     RAM 16GB 以上推奨"
Write-Host ""
Write-Host "  s) スキップ (既存モデルをそのまま使用)"
Write-Host ""
$choice = Read-Host "選択 [1/2/3/4/s]"

switch ($choice) {
    "1"   { $model = "qwen2.5-coder:7b" }
    "2"   { $model = "qwen2.5-coder:3b" }
    "3"   { $model = "llama3.2:3b" }
    "4"   { $model = "qwen3:8b" }
    { $_ -in "s","S" } { $model = "" }
    default { $model = "qwen2.5-coder:7b"; Write-Warn "デフォルト ($model) を使用します" }
}

if ($model) {
    $existing = & ollama list 2>&1
    if ($existing -match $model.Split(":")[0]) {
        Write-Ok "モデル '$model' は既にインストールされています"
    } else {
        Write-Info "モデル '$model' をダウンロードします..."
        & ollama pull $model
        Write-Ok "モデル '$model' のダウンロードが完了しました"
    }
    # .env に保存
    "QIIME2_AI_MODEL=$model" | Set-Content -Path (Join-Path $ScriptDir ".env") -Encoding UTF8
    Write-Ok "モデル設定を .env に保存しました"
}

Write-Sep

# ----------------------------------------------------------
# STEP 5: Docker Desktop の確認
# ----------------------------------------------------------
Write-Info "Docker Desktop を確認しています..."
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd) {
    try {
        $null = & docker info 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Docker Desktop: 起動中"
            & docker --version
        } else {
            Write-Warn "Docker Desktop がインストールされていますが、起動していません。"
            Write-Host "  Docker Desktop を起動してから QIIME2 解析を開始してください。"
        }
    } catch {
        Write-Warn "Docker の状態確認に失敗しました: $_"
    }
} else {
    Write-Warn "Docker Desktop が見つかりません。"
    Write-Host ""
    Write-Host "  QIIME2 実行には Docker Desktop が必要です:" -ForegroundColor White
    Write-Host "  https://www.docker.com/products/docker-desktop/"
    Write-Host ""
    Write-Host "  Windows 要件:"
    Write-Host "  - Windows 10/11 64-bit (Home, Pro, Enterprise)"
    Write-Host "  - WSL2 バックエンド推奨 (wsl --install で有効化)"
}

Write-Sep

# ----------------------------------------------------------
# STEP 6: QIIME2 Docker イメージのプル（オプション）
# ----------------------------------------------------------
$dockerCmd2 = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd2) {
    try {
        $dockerOk = & docker info 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            $pullQiime = Read-Host "QIIME2 Docker イメージ (quay.io/qiime2/amplicon:2026.1) を今すぐプルしますか? [y/N]"
            if ($pullQiime -ieq "y") {
                Write-Info "QIIME2 Docker イメージをダウンロードします (約 2-4 GB)..."
                & docker pull quay.io/qiime2/amplicon:2026.1
                Write-Ok "QIIME2 Docker イメージの取得が完了しました"
            } else {
                Write-Info "スキップします (初回解析時に自動取得されます)"
            }
        }
    } catch {}
}

# ----------------------------------------------------------
# 完了
# ----------------------------------------------------------
Write-Host ""
Write-Host "=" * 60 -ForegroundColor Green
Write-Host "  セットアップが完了しました！" -ForegroundColor Green
Write-Host "=" * 60 -ForegroundColor Green
Write-Host ""
Write-Host "次のステップ:" -ForegroundColor White
Write-Host ""
Write-Host "  1. Docker Desktop を起動してください"
Write-Host ""
Write-Host "  2. エージェントを起動:"
Write-Host "     launch.bat  (ダブルクリックでも起動できます)" -ForegroundColor Cyan
Write-Host ""
Read-Host "Enter キーで終了"
