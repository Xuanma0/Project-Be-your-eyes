@echo off
setlocal enableextensions enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "GATEWAY_PORT=18000"
set "INFERENCE_PORT=19120"
set "PYSLAM_PORT=19300"

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
  echo [quest3_usb_realstack_v5_05] adb.exe not found. Set ADB_EXE first.
  exit /b 2
)
if not exist "%ADB_BIN%" (
  echo [quest3_usb_realstack_v5_05] adb path does not exist: "%ADB_BIN%"
  exit /b 2
)

echo [quest3_usb_realstack_v5_05] adb=%ADB_BIN%
"%ADB_BIN%" devices
set "HAS_DEVICE="
for /f "skip=1 tokens=1,2" %%A in ('"%ADB_BIN%" devices') do (
  if "%%B"=="device" set "HAS_DEVICE=1"
)
if not defined HAS_DEVICE (
  echo [quest3_usb_realstack_v5_05] no adb device found.
  exit /b 3
)

echo [quest3_usb_realstack_v5_05] adb reverse tcp:%GATEWAY_PORT% ^> tcp:%GATEWAY_PORT%
"%ADB_BIN%" reverse tcp:%GATEWAY_PORT% tcp:%GATEWAY_PORT%
"%ADB_BIN%" reverse --list

set "PORT_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%GATEWAY_PORT% .*LISTENING"') do (
  set "PORT_PID=%%P"
  goto :gateway_port_done
)
:gateway_port_done
if defined PORT_PID (
  echo [quest3_usb_realstack_v5_05] Port %GATEWAY_PORT% is already in use by PID %PORT_PID%.
  tasklist /fi "PID eq %PORT_PID%" 2>nul
  exit /b 5
)

set "PORT_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%INFERENCE_PORT% .*LISTENING"') do (
  set "PORT_PID=%%P"
  goto :inference_port_done
)
:inference_port_done
if defined PORT_PID (
  echo [quest3_usb_realstack_v5_05] Port %INFERENCE_PORT% is already in use by PID %PORT_PID%.
  tasklist /fi "PID eq %PORT_PID%" 2>nul
  exit /b 5
)

rem ---- v5.05 defaults (can be overridden before launching) ----
set "BYES_INFERENCE_EMIT_WS_V1=1"
set "BYES_EMIT_NET_DEBUG=1"
set "BYES_ENABLE_OCR=1"
set "BYES_ENABLE_DET=1"
set "BYES_ENABLE_DEPTH=1"
set "BYES_ENABLE_RISK=1"
set "BYES_ENABLE_SEG=1"
set "BYES_ENABLE_SLAM=1"
set "BYES_ENABLE_ASR=1"

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

if not defined BYES_PROVIDER_DET set "BYES_PROVIDER_DET=yolo26"
if not defined BYES_PROVIDER_SEG set "BYES_PROVIDER_SEG=sam3"
if not defined BYES_PROVIDER_DEPTH set "BYES_PROVIDER_DEPTH=da3"

if /I "%BYES_PROVIDER_DET%"=="yolo26" (
  set "BYES_SERVICE_DET_PROVIDER=yolo26"
) else if /I "%BYES_PROVIDER_DET%"=="ultralytics" (
  set "BYES_SERVICE_DET_PROVIDER=ultralytics"
) else (
  set "BYES_SERVICE_DET_PROVIDER=mock"
)

if /I "%BYES_PROVIDER_SEG%"=="sam3" (
  set "BYES_SERVICE_SEG_PROVIDER=sam3"
) else (
  set "BYES_SERVICE_SEG_PROVIDER=mock"
)

if /I "%BYES_PROVIDER_DEPTH%"=="da3" (
  set "BYES_SERVICE_DEPTH_PROVIDER=da3"
) else if /I "%BYES_PROVIDER_DEPTH%"=="onnx" (
  set "BYES_SERVICE_DEPTH_PROVIDER=onnx"
) else (
  set "BYES_SERVICE_DEPTH_PROVIDER=none"
)

if not defined BYES_YOLO26_WEIGHTS if defined BYES_SERVICE_DET_MODEL_PATH set "BYES_YOLO26_WEIGHTS=%BYES_SERVICE_DET_MODEL_PATH%"
if not defined BYES_SERVICE_DET_MODEL_PATH if defined BYES_YOLO26_WEIGHTS set "BYES_SERVICE_DET_MODEL_PATH=%BYES_YOLO26_WEIGHTS%"
if not defined BYES_SERVICE_DET_MODEL if defined BYES_SERVICE_DET_MODEL_PATH set "BYES_SERVICE_DET_MODEL=%BYES_SERVICE_DET_MODEL_PATH%"
if not defined BYES_DA3_WEIGHTS if defined BYES_SERVICE_DEPTH_ONNX_PATH set "BYES_DA3_WEIGHTS=%BYES_SERVICE_DEPTH_ONNX_PATH%"
if not defined BYES_SERVICE_DEPTH_ONNX_PATH if defined BYES_DA3_WEIGHTS set "BYES_SERVICE_DEPTH_ONNX_PATH=%BYES_DA3_WEIGHTS%"
if not defined BYES_SAM3_WEIGHTS if defined BYES_SERVICE_SAM3_CKPT set "BYES_SAM3_WEIGHTS=%BYES_SERVICE_SAM3_CKPT%"
if not defined BYES_SERVICE_SAM3_CKPT if defined BYES_SAM3_WEIGHTS set "BYES_SERVICE_SAM3_CKPT=%BYES_SAM3_WEIGHTS%"

set "BYES_ASR_BACKEND=mock"
python -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('faster_whisper') else 1)" >nul 2>&1
if !ERRORLEVEL! EQU 0 set "BYES_ASR_BACKEND=faster_whisper"

set "HAS_PADDLEOCR=0"
set "HAS_ULTRALYTICS=0"
set "HAS_ONNXRT=0"
python -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('paddleocr') else 1)" >nul 2>&1
if !ERRORLEVEL! EQU 0 set "HAS_PADDLEOCR=1"
python -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('ultralytics') else 1)" >nul 2>&1
if !ERRORLEVEL! EQU 0 set "HAS_ULTRALYTICS=1"
python -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('onnxruntime') else 1)" >nul 2>&1
if !ERRORLEVEL! EQU 0 set "HAS_ONNXRT=1"

if not defined BYES_SERVICE_OCR_PROVIDER (
  if "!HAS_PADDLEOCR!"=="1" (
    set "BYES_SERVICE_OCR_PROVIDER=paddleocr"
  ) else (
    set "BYES_SERVICE_OCR_PROVIDER=mock"
  )
)

if "%BYES_SERVICE_DET_PROVIDER%"=="yolo26" if "!HAS_ULTRALYTICS!"=="0" (
  echo [quest3_usb_realstack_v5_05] WARN: ultralytics missing, fallback det provider=mock
  set "BYES_SERVICE_DET_PROVIDER=mock"
)
if "%BYES_SERVICE_DEPTH_PROVIDER%"=="onnx" if "!HAS_ONNXRT!"=="0" (
  echo [quest3_usb_realstack_v5_05] WARN: onnxruntime missing, fallback depth provider=none
  set "BYES_SERVICE_DEPTH_PROVIDER=none"
)

set "BYES_ENABLE_PYSLAM_REALTIME=0"
if defined BYES_PYSLAM_ROOT (
  if exist "%BYES_PYSLAM_ROOT%" set "BYES_ENABLE_PYSLAM_REALTIME=1"
)

if "%BYES_ENABLE_PYSLAM_REALTIME%"=="1" (
  set "BYES_SLAM_HTTP_URL=http://127.0.0.1:%PYSLAM_PORT%/slam/step"
)

echo [quest3_usb_realstack_v5_05] provider preflight:
echo   OCR provider=%BYES_SERVICE_OCR_PROVIDER% (paddleocr=%HAS_PADDLEOCR%)
echo   DET provider=%BYES_SERVICE_DET_PROVIDER% (ultralytics=%HAS_ULTRALYTICS%)
echo   SEG provider=%BYES_SERVICE_SEG_PROVIDER% (sam3_ckpt=%BYES_SERVICE_SAM3_CKPT%)
echo   DEPTH provider=%BYES_SERVICE_DEPTH_PROVIDER% (onnxrt=%HAS_ONNXRT% depth_model=%BYES_SERVICE_DEPTH_ONNX_PATH%)
echo   ASR backend=%BYES_ASR_BACKEND%
echo   pySLAM realtime=%BYES_ENABLE_PYSLAM_REALTIME% (root=%BYES_PYSLAM_ROOT%)

if "%BYES_ENABLE_PYSLAM_REALTIME%"=="1" (
  set "PORT_PID="
  for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PYSLAM_PORT% .*LISTENING"') do (
    set "PORT_PID=%%P"
    goto :pyslam_port_done
  )
  :pyslam_port_done
  if defined PORT_PID (
    echo [quest3_usb_realstack_v5_05] Port %PYSLAM_PORT% already used by PID %PORT_PID%.
    tasklist /fi "PID eq %PORT_PID%" 2>nul
    exit /b 5
  )
  echo [quest3_usb_realstack_v5_05] starting optional pyslam_service on %PYSLAM_PORT%...
  start "BYES-pySLAM-v5.05" cmd /c "cd /d \"%REPO_ROOT%\Gateway\" && python -m uvicorn services.pyslam_service.app:app --host 127.0.0.1 --port %PYSLAM_PORT%"
)

echo [quest3_usb_realstack_v5_05] opening desktop console at http://127.0.0.1:%GATEWAY_PORT%/ui
start "" "http://127.0.0.1:%GATEWAY_PORT%/ui"

echo [quest3_usb_realstack_v5_05] Starting gateway + inference in this window. Press Ctrl+C to stop.
cd /d "%REPO_ROOT%\Gateway"
python scripts/dev_up.py --with-inference --host 127.0.0.1 --gateway-port %GATEWAY_PORT% --inference-port %INFERENCE_PORT% --no-reload
set "RC=%ERRORLEVEL%"
echo [quest3_usb_realstack_v5_05] stack exited with code %RC%
exit /b %RC%
