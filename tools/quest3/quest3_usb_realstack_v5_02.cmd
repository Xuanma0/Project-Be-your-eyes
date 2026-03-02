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
  echo [quest3_usb_realstack_v5_02] adb.exe not found.
  echo Set ADB_EXE, for example:
  echo   set ADB_EXE=D:\Downloads\platform-tools-latest-windows\platform-tools\adb.exe
  exit /b 2
)
if not exist "%ADB_BIN%" (
  echo [quest3_usb_realstack_v5_02] adb path does not exist: "%ADB_BIN%"
  exit /b 2
)

echo [quest3_usb_realstack_v5_02] adb=%ADB_BIN%
"%ADB_BIN%" devices

set "HAS_DEVICE="
for /f "skip=1 tokens=1,2" %%A in ('"%ADB_BIN%" devices') do (
  if "%%B"=="device" set "HAS_DEVICE=1"
)
if not defined HAS_DEVICE (
  echo [quest3_usb_realstack_v5_02] no adb device found.
  exit /b 3
)

echo [quest3_usb_realstack_v5_02] adb reverse tcp:%GATEWAY_PORT% ^> tcp:%GATEWAY_PORT%
"%ADB_BIN%" reverse tcp:%GATEWAY_PORT% tcp:%GATEWAY_PORT%
if errorlevel 1 (
  echo [quest3_usb_realstack_v5_02] adb reverse failed.
  exit /b 4
)
"%ADB_BIN%" reverse --list

set "BYES_INFERENCE_EMIT_WS_V1=1"
set "BYES_EMIT_NET_DEBUG=1"
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
set "BYES_SERVICE_DET_OPENVOCAB=1"
set "BYES_SERVICE_DEPTH_PROVIDER=onnx"
set "BYES_SERVICE_RISK_PROVIDER=heuristic"

echo [quest3_usb_realstack_v5_02] dependency probe:
python -c "import importlib.util;print('  paddleocr=' + ('ok' if importlib.util.find_spec('paddleocr') else 'missing'))"
python -c "import importlib.util;print('  ultralytics=' + ('ok' if importlib.util.find_spec('ultralytics') else 'missing'))"
python -c "import importlib.util;print('  onnxruntime=' + ('ok' if importlib.util.find_spec('onnxruntime') else 'missing'))"

if "%BYES_SERVICE_DET_MODEL_PATH%"=="" (
  echo [warn] BYES_SERVICE_DET_MODEL_PATH is empty.
  echo        Open-vocabulary Find will fallback based on provider defaults.
)
if "%BYES_SERVICE_DEPTH_ONNX_PATH%"=="" (
  echo [warn] BYES_SERVICE_DEPTH_ONNX_PATH is empty.
  echo        Depth/Risk may return 503 until model path is set.
)

echo [quest3_usb_realstack_v5_02] starting Gateway + inference_service ...
start "BYES-RealStack-v5.02" cmd /k "cd /d \"%REPO_ROOT%\Gateway\" && set BYES_INFERENCE_EMIT_WS_V1=%BYES_INFERENCE_EMIT_WS_V1% && set BYES_EMIT_NET_DEBUG=%BYES_EMIT_NET_DEBUG% && set BYES_ENABLE_OCR=%BYES_ENABLE_OCR% && set BYES_ENABLE_DET=%BYES_ENABLE_DET% && set BYES_ENABLE_DEPTH=%BYES_ENABLE_DEPTH% && set BYES_ENABLE_RISK=%BYES_ENABLE_RISK% && set BYES_OCR_BACKEND=%BYES_OCR_BACKEND% && set BYES_OCR_HTTP_URL=%BYES_OCR_HTTP_URL% && set BYES_DET_BACKEND=%BYES_DET_BACKEND% && set BYES_DET_HTTP_URL=%BYES_DET_HTTP_URL% && set BYES_DEPTH_BACKEND=%BYES_DEPTH_BACKEND% && set BYES_DEPTH_HTTP_URL=%BYES_DEPTH_HTTP_URL% && set BYES_RISK_BACKEND=%BYES_RISK_BACKEND% && set BYES_RISK_HTTP_URL=%BYES_RISK_HTTP_URL% && set BYES_SERVICE_OCR_PROVIDER=%BYES_SERVICE_OCR_PROVIDER% && set BYES_SERVICE_DET_PROVIDER=%BYES_SERVICE_DET_PROVIDER% && set BYES_SERVICE_DET_OPENVOCAB=%BYES_SERVICE_DET_OPENVOCAB% && set BYES_SERVICE_DEPTH_PROVIDER=%BYES_SERVICE_DEPTH_PROVIDER% && set BYES_SERVICE_RISK_PROVIDER=%BYES_SERVICE_RISK_PROVIDER% && set BYES_SERVICE_DET_MODEL_PATH=%BYES_SERVICE_DET_MODEL_PATH% && set BYES_SERVICE_DEPTH_ONNX_PATH=%BYES_SERVICE_DEPTH_ONNX_PATH% && python scripts/dev_up.py --with-inference --host 127.0.0.1 --gateway-port %GATEWAY_PORT% --inference-port %INFERENCE_PORT% --no-reload"

echo.
echo [quest3_usb_realstack_v5_02] Quest smoke checklist:
echo   1) Open app, ensure Base URL is http://127.0.0.1:%GATEWAY_PORT%
echo   2) Run SelfTest
echo   3) Use Find actions in wrist menu (Door/Exit/Stairs/...)
echo   4) Start Record -> run a short flow -> Stop Record
echo.
echo [quest3_usb_realstack_v5_02] Install optional real deps if missing:
echo   python -m pip install -r Gateway\services\inference_service\requirements-paddleocr.txt
echo   python -m pip install -r Gateway\services\inference_service\requirements-ultralytics.txt
echo   python -m pip install -r Gateway\services\inference_service\requirements-onnx-depth.txt

exit /b 0
