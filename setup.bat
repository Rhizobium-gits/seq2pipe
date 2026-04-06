@echo off
:: ===========================================================
:: seq2pipe -- Windows Setup (double-click to run)
:: ===========================================================
chcp 65001 >nul 2>&1

echo.
echo  seq2pipe Windows Setup
echo  This will install: Python packages, Ollama, QIIME2
echo.

PowerShell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"

if %errorlevel% neq 0 (
    echo.
    echo Setup encountered an error.
    pause
)
