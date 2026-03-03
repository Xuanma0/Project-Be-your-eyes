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

set "BYES_SERVICE_OCR_PROVIDER=paddleocr"
set "BYES_SERVICE_DET_PROVIDER=ultralytics"
set "BYES_SERVICE_DET_OPENVOCAB=1"
set "BYES_SERVICE_SEG_PROVIDER=http"
set "BYES_SERVICE_DEPTH_PROVIDER=onnx"
set "BYES_SERVICE_RISK_PROVIDER=heuristic"
set "BYES_SERVICE_SLAM_PROVIDER=mock"

echo [quest3_usb_realstack_v5_03] capability probe:
python -c "import importlib.util;print('  paddleocr=' + ('ok' if importlib.util.find_spec('paddleocr') else 'missing'))"
python -c "import importlib.util;print('  ultralytics=' + ('ok' if importlib.util.find_spec('ultralytics') else 'missing'))"
python -c "import importlib.util;print('  onnxruntime=' + ('ok' if importlib.util.find_spec('onnxruntime') else 'missing'))"

if "%BYES_ENABLE_PYSLAM_SERVICE%"=="1" (
  set "BYES_SLAM_HTTP_URL=http://127.0.0.1:%PYSLAM_PORT%/slam/step"
)

echo [quest3_usb_realstack_v5_03] starting gateway + inference...
start "BYES-RealStack-v5.03" cmd /k "cd /d \"%REPO_ROOT%\Gateway\" && python scripts/dev_up.py --with-inference --host 127.0.0.1 --gateway-port %GATEWAY_PORT% --inference-port %INFERENCE_PORT% --no-reload"

if "%BYES_ENABLE_PYSLAM_SERVICE%"=="1" (
  echo [quest3_usb_realstack_v5_03] starting optional pyslam_service on %PYSLAM_PORT%...
  start "BYES-pySLAM-v5.03" cmd /k "cd /d \"%REPO_ROOT%\Gateway\" && python -m uvicorn services.pyslam_service.app:app --host 127.0.0.1 --port %PYSLAM_PORT%"
)

echo.
echo [quest3_usb_realstack_v5_03] Quest validation steps:
echo   1) Base URL = http://127.0.0.1:%GATEWAY_PORT%
echo   2) Run SelfTest (should PASS, passthrough may SKIP)
echo   3) Actions: Select ROI -> Start Track -> Track Step -> Stop Track
echo   4) Actions: Start Record -> Stop Record, verify recording path in terminal
if "%BYES_ENABLE_PYSLAM_SERVICE%"=="1" (
  echo   5^) Optional online slam bridge enabled: %BYES_SLAM_HTTP_URL%
)
echo.
echo [quest3_usb_realstack_v5_03] Optional installs:
echo   python -m pip install -r Gateway\services\inference_service\requirements-paddleocr.txt
echo   python -m pip install -r Gateway\services\inference_service\requirements-ultralytics.txt
echo   python -m pip install -r Gateway\services\inference_service\requirements-onnx-depth.txt

exit /b 0
