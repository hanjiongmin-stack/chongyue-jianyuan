@echo off
title chongyue-jianyuan - Install Dependencies
cd /d "%~dp0"

echo.
echo ======================================================
echo   chongyue-jianyuan - Install Dependencies
echo ======================================================
echo.

REM =========================================
REM 1. Install Python dependencies
REM =========================================
echo [1/2] Installing Python dependencies...
echo.
echo   From requirements.txt:
echo     - fastapi
echo     - uvicorn
echo     - httpx
echo.
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [FAIL] pip install failed. Please check:
    echo    1. Python 3.11+ is installed
    echo    2. Network connection is working
    echo    3. pip is in PATH
    goto :end
)
echo.
echo   Python dependencies installed [OK]
echo.

REM =========================================
REM 2. Install cloudflared
REM =========================================
echo [2/2] Checking Cloudflare Tunnel (cloudflared)...

where cloudflared >nul 2>&1
if errorlevel 1 (
    echo   cloudflared not found, installing via winget...
    echo.
    winget install Cloudflare.cloudflared --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo.
        echo [!] winget install failed. Please download manually:
        echo   https://github.com/cloudflare/cloudflared/releases
        echo   Download cloudflared-windows-amd64.exe and add to PATH
        echo   Or copy to C:\Windows\System32\
    ) else (
        echo.
        echo   cloudflared installed [OK]
    )
) else (
    echo   cloudflared already installed [OK]
)
echo.

REM =========================================
REM Done
REM =========================================
echo ======================================================
echo   All dependencies installed!
echo.
echo   Next step:
echo     Double-click start_all.bat to start all services
echo ======================================================
echo.

:end
pause
