@echo off
setlocal enableextensions enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "GATEWAY_PORT=18000"
set "INFERENCE_PORT=19120"
set "PYSLAM_PORT=19300"
if not defined BYES_ENABLE_PYSLAM_SERVICE set "BYES_ENABLE_PYSLAM_SERVICE=0"

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
  echo [quest3_usb_realstack_v5_03] adb.exe not found. Set ADB_EXE first.
  exit /b 2
)
if not exist "%ADB_BIN%" (
  echo [quest3_usb_realstack_v5_03] adb path does not exist: "%ADB_BIN%"
  exit /b 2
)

echo [quest3_usb_realstack_v5_03] adb=%ADB_BIN%
"%ADB_BIN%" devices
set "HAS_DEVICE="
for /f "skip=1 tokens=1,2" %%A in ('"%ADB_BIN%" devices') do (
  if "%%B"=="device" set "HAS_DEVICE=1"
)
if not defined HAS_DEVICE (
  echo [quest3_usb_realstack_v5_03] no adb device found.
  exit /b 3
)

echo [quest3_usb_realstack_v5_03] adb reverse tcp:%GATEWAY_PORT% ^> tcp:%GATEWAY_PORT%
"%ADB_BIN%" reverse tcp:%GATEWAY_PORT% tcp:%GATEWAY_PORT%
"%ADB_BIN%" reverse --list

set "PORT_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%GATEWAY_PORT% .*LISTENING"') do (
  set "PORT_PID=%%P"
  goto :gateway_port_busy_done
)
:gateway_port_busy_done
if defined PORT_PID (
  echo [quest3_usb_realstack_v5_03] Port %GATEWAY_PORT% is already in use by PID %PORT_PID%.
  tasklist /fi "PID eq %PORT_PID%" 2>nul
  echo Stop that process first, then rerun.
  exit /b 5
)

set "PORT_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%INFERENCE_PORT% .*LISTENING"') do (
  set "PORT_PID=%%P"
  goto :inference_port_busy_done
)
:inference_port_busy_done
if defined PORT_PID (
  echo [quest3_usb_realstack_v5_03] Port %INFERENCE_PORT% is already in use by PID %PORT_PID%.
  tasklist /fi "PID eq %PORT_PID%" 2>nul
  echo Stop that process first, then rerun.
  exit /b 5
)

set "BYES_INFERENCE_EMIT_WS_V1=1"
set "BYES_EMIT_NET_DEBUG=1"
set "BYES_ENABLE_OCR=1"
set "BYES_ENABLE_DET=1"
set "BYES_ENABLE_DEPTH=1"
set "BYES_ENABLE_RISK=1"
set "BYES_ENABLE_SEG=1"
set "BYES_OCR_BACKEND=http"
set "BYES_OCR_HTTP_URL=http://127.0.0.1:%INFERENCE_PORT%/ocr"
set "BYES_DET_BACKEND=http"
set "BYES_DET_HTTP_URL=http://127.0.0.1:%INFERENCE_PORT%/det"
set "BYES_DEPTH_BACKEND=http"
set "BYES_DEPTH_HTTP_URL=http://127.0.0.1:%INFERENCE_PORT%/depth"
set "BYES_RISK_BACKEND=http"
set "BYES_RISK_HTTP_URL=http://127.0.0.1:%INFERENCE_PORT%/risk"
set "BYES_SEG_BACKEND=http"
set "BYES_SEG_HTTP_URL=http://127.0.0.1:%INFERENCE_PORT%/seg"
set "BYES_SLAM_BACKEND=http"
set "BYES_SLAM_HTTP_URL=http://127.0.0.1:%INFERENCE_PORT%/slam"

set "BYES_SERVICE_OCR_PROVIDER=mock"
set "BYES_SERVICE_DET_PROVIDER=mock"
set "BYES_SERVICE_DET_OPENVOCAB=0"
set "BYES_SERVICE_SEG_PROVIDER=mock"
set "BYES_SERVICE_DEPTH_PROVIDER=none"
set "BYES_SERVICE_RISK_PROVIDER=reference"
set "BYES_SERVICE_SLAM_PROVIDER=mock"

set "HAS_PADDLEOCR=0"
set "HAS_ULTRALYTICS=0"
set "HAS_ONNXRT=0"
set "HAS_ONNX_MODEL=0"
python -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('paddleocr') else 1)" >nul 2>&1
if !ERRORLEVEL! EQU 0 set "HAS_PADDLEOCR=1"
python -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('ultralytics') else 1)" >nul 2>&1
if !ERRORLEVEL! EQU 0 set "HAS_ULTRALYTICS=1"
python -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('onnxruntime') else 1)" >nul 2>&1
if !ERRORLEVEL! EQU 0 set "HAS_ONNXRT=1"
if defined BYES_SERVICE_DEPTH_ONNX_PATH (
  if exist "!BYES_SERVICE_DEPTH_ONNX_PATH!" set "HAS_ONNX_MODEL=1"
)

if "!HAS_PADDLEOCR!"=="1" (
  set "BYES_SERVICE_OCR_PROVIDER=paddleocr"
) else (
  echo [quest3_usb_realstack_v5_03] WARN: paddleocr missing, fallback OCR provider=mock
)

if "!HAS_ULTRALYTICS!"=="1" (
  set "BYES_SERVICE_DET_PROVIDER=ultralytics"
  set "BYES_SERVICE_DET_OPENVOCAB=1"
) else (
  echo [quest3_usb_realstack_v5_03] WARN: ultralytics missing, fallback DET provider=mock
)

if "!HAS_ONNXRT!"=="1" (
  if "!HAS_ONNX_MODEL!"=="1" (
    set "BYES_SERVICE_DEPTH_PROVIDER=onnx"
    set "BYES_SERVICE_RISK_PROVIDER=heuristic"
  ) else (
    echo [quest3_usb_realstack_v5_03] WARN: ONNX depth model not configured ^(set BYES_SERVICE_DEPTH_ONNX_PATH^), fallback DEPTH provider=none and RISK=reference
  )
) else (
  echo [quest3_usb_realstack_v5_03] WARN: onnxruntime missing, fallback DEPTH provider=none and RISK=reference
)

echo [quest3_usb_realstack_v5_03] capability probe:
echo   paddleocr=!HAS_PADDLEOCR!
echo   ultralytics=!HAS_ULTRALYTICS!
echo   onnxruntime=!HAS_ONNXRT!
echo   onnx_model=!HAS_ONNX_MODEL!
echo [quest3_usb_realstack_v5_03] selected providers:
echo   OCR=!BYES_SERVICE_OCR_PROVIDER! DET=!BYES_SERVICE_DET_PROVIDER! DEPTH=!BYES_SERVICE_DEPTH_PROVIDER! RISK=!BYES_SERVICE_RISK_PROVIDER! SEG=!BYES_SERVICE_SEG_PROVIDER! SLAM=!BYES_SERVICE_SLAM_PROVIDER!

if "%BYES_ENABLE_PYSLAM_SERVICE%"=="1" (
  set "BYES_SLAM_HTTP_URL=http://127.0.0.1:%PYSLAM_PORT%/slam/step"
  set "PORT_PID="
  for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PYSLAM_PORT% .*LISTENING"') do (
    set "PORT_PID=%%P"
    goto :pyslam_port_busy_done
  )
  :pyslam_port_busy_done
  if defined PORT_PID (
    echo [quest3_usb_realstack_v5_03] Port %PYSLAM_PORT% is already in use by PID %PORT_PID%.
    tasklist /fi "PID eq %PORT_PID%" 2>nul
    echo Stop that process first, then rerun.
    exit /b 5
  )
)

echo [quest3_usb_realstack_v5_03] verifying /api/assist route exists in current code...
pushd "%REPO_ROOT%\Gateway" >nul
python -c "import sys, main; sys.exit(0 if any(getattr(r,'path',None)=='/api/assist' for r in main.app.routes) else 1)"
if errorlevel 1 (
  popd >nul
  echo [quest3_usb_realstack_v5_03] ERROR: /api/assist route missing in current Gateway code.
  echo Please update local repo to latest feature/unity-skeleton.
  exit /b 6
)
popd >nul

if "%BYES_ENABLE_PYSLAM_SERVICE%"=="1" (
  echo [quest3_usb_realstack_v5_03] starting optional pyslam_service on %PYSLAM_PORT%...
  start "BYES-pySLAM-v5.03" /D "%REPO_ROOT%\Gateway" cmd /k python -m uvicorn services.pyslam_service.app:app --host 127.0.0.1 --port %PYSLAM_PORT%
)

echo.
echo [quest3_usb_realstack_v5_03] Quest validation steps:
echo   1) Base URL = http://127.0.0.1:%GATEWAY_PORT%
echo   2) Run SelfTest (should PASS, passthrough may SKIP)
echo   3) Actions: Select ROI to Start Track to Track Step to Stop Track
echo   4) Actions: Start Record to Stop Record, verify recording path in terminal
if "%BYES_ENABLE_PYSLAM_SERVICE%"=="1" (
  echo   5^) Optional online slam bridge enabled: %BYES_SLAM_HTTP_URL%
)
echo.
echo [quest3_usb_realstack_v5_03] Optional installs:
echo   python -m pip install -r Gateway\services\inference_service\requirements-paddleocr.txt
echo   python -m pip install -r Gateway\services\inference_service\requirements-ultralytics.txt
echo   python -m pip install -r Gateway\services\inference_service\requirements-onnx-depth.txt

echo.
echo [quest3_usb_realstack_v5_03] Starting gateway + inference in this window. Press Ctrl+C to stop.
cd /d "%REPO_ROOT%\Gateway"
python scripts/dev_up.py --with-inference --host 127.0.0.1 --gateway-port %GATEWAY_PORT% --inference-port %INFERENCE_PORT% --no-reload
set "RC=%ERRORLEVEL%"
echo [quest3_usb_realstack_v5_03] stack exited with code %RC%
exit /b %RC%
