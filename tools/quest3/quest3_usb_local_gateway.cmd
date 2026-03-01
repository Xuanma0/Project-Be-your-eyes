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

echo [quest3_usb_local_gateway] Applying adb reverse tcp:%GATEWAY_PORT% -> tcp:%GATEWAY_PORT%
"%ADB_BIN%" reverse tcp:%GATEWAY_PORT% tcp:%GATEWAY_PORT%
if errorlevel 1 (
  echo [quest3_usb_local_gateway] adb reverse failed.
  exit /b 4
)
echo [quest3_usb_local_gateway] Active reverse rules:
"%ADB_BIN%" reverse --list

echo [quest3_usb_local_gateway] STEP 1/2: Starting gateway window on 127.0.0.1:%GATEWAY_PORT% ...
start "BYES-Gateway" cmd /c "cd /d "%REPO_ROOT%\Gateway" && set BYES_INFERENCE_EMIT_WS_V1=1 && set BYES_EMIT_NET_DEBUG=1 && python scripts/dev_up.py --gateway-only --host 127.0.0.1 --gateway-port %GATEWAY_PORT% --no-reload"

echo.
echo [quest3_usb_local_gateway] STEP 2/2: In Quest panel use:
echo   host = 127.0.0.1
echo   port = %GATEWAY_PORT%
echo Then click: SelfTest (or Refresh then SelfTest if status is stale)

exit /b 0
