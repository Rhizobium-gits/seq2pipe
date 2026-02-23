@echo off
:: ===========================================================
:: seq2pipe -- Windows Batch Launcher
:: PowerShell 経由で launch.ps1 を実行します
:: ===========================================================
chcp 65001 >nul 2>&1

echo seq2pipe - Windows Launcher
echo.

:: Python の確認
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python が見つかりません。
    echo   https://www.python.org/downloads/ からインストールしてください。
    pause
    exit /b 1
)

:: PowerShell 経由で launch.ps1 を実行
PowerShell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1"

if %errorlevel% neq 0 (
    echo.
    echo エラーが発生しました。
    pause
)
