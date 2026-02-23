@echo off
:: ===========================================================
:: seq2pipe -- Windows Setup Launcher
:: PowerShell 経由で setup.ps1 を実行します
:: ===========================================================
chcp 65001 >nul 2>&1

echo seq2pipe Windows Setup
echo.

:: 管理者権限の確認（winget 使用時に必要な場合あり）
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] 管理者権限なしで実行します。
    echo        Ollama のインストールに失敗した場合は右クリックから
    echo        "管理者として実行" を選択してください。
    echo.
)

PowerShell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"

if %errorlevel% neq 0 (
    echo.
    echo セットアップ中にエラーが発生しました。
    pause
)
