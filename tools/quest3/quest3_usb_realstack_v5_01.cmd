@echo off
setlocal enableextensions enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "GATEWAY_PORT=18000"
set "INFERENCE_PORT=19120"

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
  echo [quest3_usb_realstack_v5_01] adb.exe not found.
  echo Set ADB_EXE, for example:
  echo   set ADB_EXE=D:\Downloads\platform-tools-latest-windows\platform-tools\adb.exe
  exit /b 2
)
if not exist "%ADB_BIN%" (
  echo [quest3_usb_realstack_v5_01] adb path does not exist: "%ADB_BIN%"
  exit /b 2
)

echo [quest3_usb_realstack_v5_01] adb=%ADB_BIN%
"%ADB_BIN%" devices

set "HAS_DEVICE="
for /f "skip=1 tokens=1,2" %%A in ('"%ADB_BIN%" devices') do (
  if "%%B"=="device" set "HAS_DEVICE=1"
)
if not defined HAS_DEVICE (
  echo [quest3_usb_realstack_v5_01] no adb device found.
  exit /b 3
)

echo [quest3_usb_realstack_v5_01] adb reverse tcp:%GATEWAY_PORT% ^> tcp:%GATEWAY_PORT%
"%ADB_BIN%" reverse tcp:%GATEWAY_PORT% tcp:%GATEWAY_PORT%
if errorlevel 1 (
  echo [quest3_usb_realstack_v5_01] adb reverse failed.
  exit /b 4
)
"%ADB_BIN%" reverse --list

set "BYES_INFERENCE_EMIT_WS_V1=1"
set "BYES_ENABLE_OCR=1"
set "BYES_ENABLE_DET=1"
set "BYES_ENABLE_DEPTH=1"
set "BYES_ENABLE_RISK=1"
set "BYES_OCR_BACKEND=http"
set "BYES_OCR_HTTP_URL=http://127.0.0.1:%INFERENCE_PORT%/ocr"
set "BYES_DET_BACKEND=http"
set "BYES_DET_HTTP_URL=http://127.0.0.1:%INFERENCE_PORT%/det"
set "BYES_DEPTH_BACKEND=http"
set "BYES_DEPTH_HTTP_URL=http://127.0.0.1:%INFERENCE_PORT%/depth"
set "BYES_RISK_BACKEND=http"
set "BYES_RISK_HTTP_URL=http://127.0.0.1:%INFERENCE_PORT%/risk"

set "BYES_SERVICE_OCR_PROVIDER=paddleocr"
set "BYES_SERVICE_DET_PROVIDER=ultralytics"
set "BYES_SERVICE_DEPTH_PROVIDER=onnx"
set "BYES_SERVICE_RISK_PROVIDER=heuristic"

python -c "import importlib.util;print('[check] paddleocr=' + ('ok' if importlib.util.find_spec('paddleocr') else 'missing'))"
python -c "import importlib.util;print('[check] ultralytics=' + ('ok' if importlib.util.find_spec('ultralytics') else 'missing'))"
python -c "import importlib.util;print('[check] onnxruntime=' + ('ok' if importlib.util.find_spec('onnxruntime') else 'missing'))"

if "%BYES_SERVICE_DEPTH_ONNX_PATH%"=="" (
  echo [warn] BYES_SERVICE_DEPTH_ONNX_PATH is empty. Depth/Risk may return 503 until model path is set.
  echo        Example: set BYES_SERVICE_DEPTH_ONNX_PATH=D:\models\depth_anything_v2_small.onnx
)

echo [quest3_usb_realstack_v5_01] Starting Gateway + inference_service on 127.0.0.1 ...
start "BYES-RealStack-v5.01" cmd /c "cd /d \"%REPO_ROOT%\Gateway\" && python scripts/dev_up.py --with-inference --host 127.0.0.1 --gateway-port %GATEWAY_PORT% --inference-port %INFERENCE_PORT% --no-reload"

echo.
echo [quest3_usb_realstack_v5_01] Quest validation steps:
echo   1) Launch Quest app (Quest3SmokeScene build)
echo   2) In wrist menu: run SelfTest
echo   3) Actions: Read Text Once / Detect Once
echo   4) Observe Last OCR / Last DET / Last RISK and TTS behavior

echo [quest3_usb_realstack_v5_01] Troubleshooting:
echo   - Install OCR deps: python -m pip install -r Gateway\services\inference_service\requirements-paddleocr.txt
echo   - Install DET deps: python -m pip install -r Gateway\services\inference_service\requirements-ultralytics.txt
echo   - Install depth deps: python -m pip install -r Gateway\services\inference_service\requirements-onnx-depth.txt

exit /b 0
