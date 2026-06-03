@echo off
title chongyue-jianyuan - All Services
cd /d "%~dp0"

echo.
echo ======================================================
echo   chongyue-jianyuan - Start All Services
echo ======================================================
echo   8088 - Math Competition Server  (background)
echo   8888 - Unified Entry Server     (background)
echo         Cloudflare Tunnel          (foreground)
echo ======================================================
echo.

REM =========================================
REM 0. Kill leftover processes from previous runs
REM =========================================
echo [0/3] Cleaning up leftover processes...
taskkill /FI "WINDOWTITLE eq MathServer*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq UnifiedServer*" /F >nul 2>&1
REM Also free ports 8088 and 8888 (works on any language Windows)
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8088 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8888 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
echo     Cleanup done
echo.

REM =========================================
REM 1. Start Math Competition Server (8088)
REM =========================================
echo [1/3] Starting Math Server (port 8088)...

start "MathServer" cmd /c "cd /d C:\Users\hanji\math-competition-viewer && python server.py"

REM Wait for port 8088
echo     Waiting for port 8088...
:wait_8088
timeout /t 3 /nobreak >nul
powershell -NoProfile -Command "$tcp = New-Object Net.Sockets.TcpClient; try { $tcp.Connect('127.0.0.1', 8088); $tcp.Dispose(); exit 0 } catch { $tcp.Dispose(); exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo     Port 8088 not ready, retrying...
    goto wait_8088
)
echo     Math Server started [OK]
echo.

REM =========================================
REM 2. Start Unified Entry Server (8888)
REM =========================================
echo [2/3] Starting Unified Server (port 8888)...

start "UnifiedServer" cmd /c "cd /d %~dp0 && python unified_server.py"

REM Wait for port 8888
echo     Waiting for port 8888...
:wait_8888
timeout /t 3 /nobreak >nul
powershell -NoProfile -Command "$tcp = New-Object Net.Sockets.TcpClient; try { $tcp.Connect('127.0.0.1', 8888); $tcp.Dispose(); exit 0 } catch { $tcp.Dispose(); exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo     Port 8888 not ready, retrying...
    goto wait_8888
)
echo     Unified Server started [OK]
echo.

REM =========================================
REM 3. Start Cloudflare Tunnel
REM =========================================
echo [3/3] Starting Cloudflare Tunnel...
echo.
echo -----------------------------------------------------
echo   Cloudflare Tunnel is connecting...
echo   A public URL (trycloudflare.com) will appear below
echo   Share the URL to give others access
echo.
echo   Press Ctrl+C to stop all services
echo -----------------------------------------------------
echo.

REM Start cloudflared tunnel (foreground)
REM Using --protocol http2 (port 443) since QUIC/7844 is blocked
REM Using --edge-ip-version 4 for IPv4-only connections
echo.
echo ======================================================
echo   [!] Look for the URL below (trycloudflare.com):
echo ======================================================
echo.
cloudflared tunnel --url http://localhost:8888 --protocol http2 --edge-ip-version 4

REM =========================================
REM Cleanup after Ctrl+C
REM =========================================
echo.
echo Stopping all services...
taskkill /FI "WINDOWTITLE eq MathServer*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq UnifiedServer*" /F >nul 2>&1
echo All services stopped.
pause
