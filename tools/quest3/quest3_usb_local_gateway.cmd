@echo off
setlocal enableextensions enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "GATEWAY_PORT=18000"
if not "%~1"=="" set "GATEWAY_PORT=%~1"

if defined ADB_EXE (
  set "ADB_BIN=%ADB_EXE%"
) else (
  if exist "D:\Downloads\platform-tools-latest-windows\platform-tools\adb.exe" (
    set "ADB_BIN=D:\Downloads\platform-tools-latest-windows\platform-tools\adb.exe"
  ) else (
    for %%I in (adb.exe) do if not "%%~$PATH:I"=="" set "ADB_BIN=%%~$PATH:I"
  )
)

if not defined ADB_BIN (
  echo [quest3_usb_local_gateway] adb.exe not found.
  echo Set ADB_EXE to your adb path, for example:
  echo   set ADB_EXE=D:\Downloads\platform-tools-latest-windows\platform-tools\adb.exe
  exit /b 2
)

if not exist "%ADB_BIN%" (
  echo [quest3_usb_local_gateway] ADB_EXE does not exist: "%ADB_BIN%"
  exit /b 2
)

echo [quest3_usb_local_gateway] ADB_BIN=%ADB_BIN%
"%ADB_BIN%" devices

set "HAS_DEVICE="
for /f "skip=1 tokens=1,2" %%A in ('"%ADB_BIN%" devices') do (
  if "%%B"=="device" set "HAS_DEVICE=1"
)

if not defined HAS_DEVICE (
  echo [quest3_usb_local_gateway] No connected adb device found.
  exit /b 3
)

echo [quest3_usb_local_gateway] Applying adb reverse tcp:%GATEWAY_PORT% to tcp:%GATEWAY_PORT%
"%ADB_BIN%" reverse tcp:%GATEWAY_PORT% tcp:%GATEWAY_PORT%
if errorlevel 1 (
  echo [quest3_usb_local_gateway] adb reverse failed.
  exit /b 4
)
echo [quest3_usb_local_gateway] Active reverse rules:
"%ADB_BIN%" reverse --list

call :check_port_free %GATEWAY_PORT%
if errorlevel 1 exit /b 5

echo.
echo [quest3_usb_local_gateway] STEP 1/2: In Quest panel use:
echo   host = 127.0.0.1
echo   port = %GATEWAY_PORT%
echo [quest3_usb_local_gateway] STEP 2/2: Then click SelfTest ^(or Refresh then SelfTest if status is stale^)
echo   - Read Text Once / Detect Once will use mock providers by default in this profile.
echo.
echo [quest3_usb_local_gateway] Starting gateway in this window. Press Ctrl+C to stop.

cd /d "%REPO_ROOT%\Gateway"
set "BYES_INFERENCE_EMIT_WS_V1=1"
set "BYES_EMIT_NET_DEBUG=1"
set "BYES_ENABLE_OCR=1"
set "BYES_ENABLE_DET=1"
set "BYES_ENABLE_DEPTH=1"
set "BYES_ENABLE_RISK=1"
set "BYES_OCR_BACKEND=mock"
set "BYES_DET_BACKEND=mock"
set "BYES_DEPTH_BACKEND=mock"
set "BYES_RISK_BACKEND=mock"
python scripts/dev_up.py --gateway-only --host 127.0.0.1 --gateway-port %GATEWAY_PORT% --no-reload
set "RC=%ERRORLEVEL%"
echo [quest3_usb_local_gateway] gateway exited with code %RC%
exit /b %RC%

:: helper: fail fast when the target port is already occupied
:check_port_free
set "CHK_PORT=%~1"
set "PORT_PID="
for /f "tokens=2,4,5" %%A in ('netstat -ano ^| findstr /R /C:"TCP.*:%CHK_PORT% .*LISTENING"') do (
  set "PORT_PID=%%C"
  goto :port_busy
)
exit /b 0

:port_busy
echo [quest3_usb_local_gateway] Port %CHK_PORT% is already in use by PID %PORT_PID%.
tasklist /fi "PID eq %PORT_PID%" 2>nul
echo Stop that process first, then rerun.
exit /b 1
