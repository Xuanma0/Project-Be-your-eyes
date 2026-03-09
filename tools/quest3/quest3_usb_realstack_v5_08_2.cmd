@echo off
setlocal enableextensions enabledelayedexpansion
if not defined BYES_PAUSE_ON_ERROR set "BYES_PAUSE_ON_ERROR=1"
if not defined BYES_PREFLIGHT_ONLY set "BYES_PREFLIGHT_ONLY=0"
set "PREFLIGHT_ONLY_FLAG="
if /I "%~1"=="--preflight-only" set "PREFLIGHT_ONLY_FLAG=1"

set "SCRIPT_NAME=quest3_usb_realstack_v5_09_1"
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "GATEWAY_PORT=18000"
set "INFERENCE_PORT=19120"
set "PYSLAM_PORT=19300"
set "SAM3_PORT=19271"
set "DA3_PORT=19281"

call :capture_user_env BYES_PROVIDER_DET
call :capture_user_env BYES_PROVIDER_SEG
call :capture_user_env BYES_PROVIDER_DEPTH
call :capture_user_env BYES_PYTHON_EXE
call :capture_user_env BYES_PYTHON_EXE_CUDA128
call :capture_user_env PYTHONPATH
call :capture_user_env PADDLE_PDX_MODEL_SOURCE
call :capture_user_env PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK
call :capture_user_env BYES_OCR_BACKEND
call :capture_user_env BYES_DET_BACKEND
call :capture_user_env BYES_DEPTH_BACKEND
call :capture_user_env BYES_RISK_BACKEND
call :capture_user_env BYES_SEG_BACKEND
call :capture_user_env BYES_SLAM_BACKEND
call :capture_user_env BYES_ENABLE_ASR
call :capture_user_env BYES_SERVICE_OCR_PROVIDER
call :capture_user_env BYES_SERVICE_DET_PROVIDER
call :capture_user_env BYES_SERVICE_DET_MODEL
call :capture_user_env BYES_SERVICE_DET_MODEL_PATH
call :capture_user_env BYES_SERVICE_SEG_PROVIDER
call :capture_user_env BYES_SERVICE_SEG_ENDPOINT
call :capture_user_env BYES_SERVICE_SAM3_CKPT
call :capture_user_env BYES_SERVICE_SEG_MODEL_PATH
call :capture_user_env BYES_SAM3_CKPT
call :capture_user_env BYES_SAM3_CKPT_PATH
call :capture_user_env BYES_SAM3_WEIGHTS
call :capture_user_env BYES_SERVICE_DEPTH_PROVIDER
call :capture_user_env BYES_SERVICE_DEPTH_ENDPOINT
call :capture_user_env BYES_SERVICE_DEPTH_MODEL_PATH
call :capture_user_env BYES_SERVICE_DEPTH_ONNX_PATH
call :capture_user_env BYES_DA3_MODEL_PATH
call :capture_user_env BYES_DA3_WEIGHTS
call :capture_user_env BYES_YOLO26_WEIGHTS
call :capture_user_env BYES_ENABLE_PYSLAM_REALTIME
call :capture_user_env BYES_PYSLAM_ROOT
call :capture_user_env BYES_ASR_BACKEND
call :capture_user_env BYES_ASR_MODEL
call :capture_user_env BYES_ASR_DEVICE
call :capture_user_env BYES_ASR_COMPUTE_TYPE
call :capture_user_env BYES_SAM3_MODE
call :capture_user_env BYES_DA3_MODE
call :capture_user_env BYES_SLAM_HTTP_URL

call :load_env_file "%REPO_ROOT%\.env.example" 0
call :load_env_file "%REPO_ROOT%\.env" 1
call :load_env_file "%REPO_ROOT%\.env.local" 1
call :load_env_file "%REPO_ROOT%\.env.user" 1
call :normalize_empty_like_value BYES_MODE_PROFILE_JSON
call :normalize_empty_like_value BYES_GATEWAY_API_KEY
call :normalize_empty_like_value BYES_GATEWAY_ALLOWED_HOSTS
call :normalize_empty_like_value BYES_GATEWAY_ALLOWED_ORIGINS
call :normalize_empty_like_value BYES_SERVICE_OCR_PROVIDER
call :normalize_empty_like_value BYES_SERVICE_DET_PROVIDER
call :normalize_empty_like_value BYES_SERVICE_DET_MODEL
call :normalize_empty_like_value BYES_SERVICE_DET_MODEL_PATH
call :normalize_empty_like_value BYES_SERVICE_SEG_PROVIDER
call :normalize_empty_like_value BYES_SERVICE_SEG_MODEL_PATH
call :normalize_empty_like_value BYES_SERVICE_SAM3_CKPT
call :normalize_empty_like_value BYES_SAM3_CKPT
call :normalize_empty_like_value BYES_SAM3_CKPT_PATH
call :normalize_empty_like_value BYES_SAM3_WEIGHTS
call :normalize_empty_like_value BYES_SERVICE_DEPTH_PROVIDER
call :normalize_empty_like_value BYES_SERVICE_DEPTH_MODEL_PATH
call :normalize_empty_like_value BYES_SERVICE_DEPTH_ONNX_PATH
call :normalize_empty_like_value BYES_DA3_MODEL_PATH
call :normalize_empty_like_value BYES_DA3_WEIGHTS
call :normalize_empty_like_value BYES_YOLO26_WEIGHTS
call :normalize_empty_like_value BYES_PYSLAM_ROOT
call :normalize_empty_like_value BYES_PYTHON_EXE
call :normalize_empty_like_value BYES_PYTHON_EXE_CUDA128
call :normalize_empty_like_value BYES_ASR_MODEL
call :normalize_empty_like_value BYES_PROVIDER_DET
call :normalize_empty_like_value BYES_PROVIDER_SEG
call :normalize_empty_like_value BYES_PROVIDER_DEPTH
call :resolve_python_bin
if errorlevel 1 goto :abort
call :resolve_cuda_python_bin
if errorlevel 1 goto :abort
call :write_cuda_probe_script
echo [%SCRIPT_NAME%] python=%PYTHON_BIN%
if defined CUDA128_PYTHON_BIN echo [%SCRIPT_NAME%] python_cuda128=%CUDA128_PYTHON_BIN%

set "SEG_SERVICE_PYTHON_BIN=%PYTHON_BIN%"
set "DEPTH_SERVICE_PYTHON_BIN=%PYTHON_BIN%"
set "SEG_PROBE_DEVICE=cpu"
set "SEG_PROBE_DEVICEREASON=baseline_cpu"
set "SEG_PROBE_WARMUPMS=-"
set "SEG_PROBE_TORCHVERSION=-"
set "SEG_PROBE_CUDARUNTIME=-"
set "SEG_PROBE_CUDARUNTIMELINE=-"
set "SEG_PROBE_DEVICECAPABILITY=-"
set "SEG_PROBE_DEVICENAME=-"
set "DEPTH_PROBE_DEVICE=cpu"
set "DEPTH_PROBE_DEVICEREASON=baseline_cpu"
set "DEPTH_PROBE_WARMUPMS=-"
set "DEPTH_PROBE_TORCHVERSION=-"
set "DEPTH_PROBE_CUDARUNTIME=-"
set "DEPTH_PROBE_CUDARUNTIMELINE=-"
set "DEPTH_PROBE_DEVICECAPABILITY=-"
set "DEPTH_PROBE_DEVICENAME=-"

rem ---- v5.08.2 defaults (can be overridden via shell env/.env/.env.example) ----
call :set_if_missing BYES_INFERENCE_EMIT_WS_V1 1
call :set_if_missing BYES_EMIT_NET_DEBUG 1
call :set_if_missing BYES_ENABLE_OCR 1
call :set_if_missing BYES_ENABLE_DET 1
call :set_if_missing BYES_ENABLE_DEPTH 1
call :set_if_missing BYES_ENABLE_RISK 1
call :set_if_missing BYES_ENABLE_SEG 1
call :set_if_missing BYES_ENABLE_SLAM 1
call :set_if_missing BYES_ENABLE_ASR 1
call :set_if_missing BYES_ASSET_CACHE_TTL_MS 30000

call :set_if_missing BYES_OCR_BACKEND http
call :set_if_missing BYES_OCR_HTTP_URL http://127.0.0.1:%INFERENCE_PORT%/ocr
call :set_if_missing BYES_DET_BACKEND http
call :set_if_missing BYES_DET_HTTP_URL http://127.0.0.1:%INFERENCE_PORT%/det
call :set_if_missing BYES_DEPTH_BACKEND http
call :set_if_missing BYES_DEPTH_HTTP_URL http://127.0.0.1:%INFERENCE_PORT%/depth
call :set_if_missing BYES_RISK_BACKEND http
call :set_if_missing BYES_RISK_HTTP_URL http://127.0.0.1:%INFERENCE_PORT%/risk
call :set_if_missing BYES_SEG_BACKEND http
call :set_if_missing BYES_SEG_HTTP_URL http://127.0.0.1:%INFERENCE_PORT%/seg
call :set_if_missing BYES_SLAM_BACKEND http
call :set_if_missing BYES_SLAM_HTTP_URL http://127.0.0.1:%INFERENCE_PORT%/slam/pose

call :set_if_missing BYES_PROVIDER_DET yolo26
call :set_if_missing BYES_PROVIDER_SEG sam3
call :set_if_missing BYES_PROVIDER_DEPTH da3

if not defined BYES_SERVICE_DET_PROVIDER (
  if /I "%BYES_PROVIDER_DET%"=="yolo26" (
    set "BYES_SERVICE_DET_PROVIDER=yolo26"
  ) else if /I "%BYES_PROVIDER_DET%"=="ultralytics" (
    set "BYES_SERVICE_DET_PROVIDER=ultralytics"
  ) else (
    set "BYES_SERVICE_DET_PROVIDER=mock"
  )
)
if not defined USER_DEFINED_BYES_SERVICE_DET_PROVIDER (
  if /I "%BYES_PROVIDER_DET%"=="yolo26" (
    set "BYES_SERVICE_DET_PROVIDER=yolo26"
  ) else if /I "%BYES_PROVIDER_DET%"=="ultralytics" (
    set "BYES_SERVICE_DET_PROVIDER=ultralytics"
  ) else if /I "%BYES_PROVIDER_DET%"=="mock" (
    set "BYES_SERVICE_DET_PROVIDER=mock"
  )
)

if not defined BYES_SERVICE_SEG_PROVIDER (
  if /I "%BYES_PROVIDER_SEG%"=="sam3" (
    set "BYES_SERVICE_SEG_PROVIDER=sam3"
  ) else (
    set "BYES_SERVICE_SEG_PROVIDER=mock"
  )
)
if not defined USER_DEFINED_BYES_SERVICE_SEG_PROVIDER (
  if /I "%BYES_PROVIDER_SEG%"=="sam3" (
    set "BYES_SERVICE_SEG_PROVIDER=sam3"
  ) else if /I "%BYES_PROVIDER_SEG%"=="mock" (
    set "BYES_SERVICE_SEG_PROVIDER=mock"
  )
)
if /I "%BYES_SERVICE_SEG_PROVIDER%"=="sam3" (
  call :set_if_missing BYES_SERVICE_SEG_ENDPOINT http://127.0.0.1:%SAM3_PORT%/seg
  call :set_if_missing BYES_SAM3_MODE sam3
)

if not defined BYES_SERVICE_DEPTH_PROVIDER (
  if /I "%BYES_PROVIDER_DEPTH%"=="da3" (
    set "BYES_SERVICE_DEPTH_PROVIDER=da3"
  ) else if /I "%BYES_PROVIDER_DEPTH%"=="onnx" (
    set "BYES_SERVICE_DEPTH_PROVIDER=onnx"
  ) else (
    set "BYES_SERVICE_DEPTH_PROVIDER=none"
  )
)
if not defined USER_DEFINED_BYES_SERVICE_DEPTH_PROVIDER (
  if /I "%BYES_PROVIDER_DEPTH%"=="da3" (
    set "BYES_SERVICE_DEPTH_PROVIDER=da3"
  ) else if /I "%BYES_PROVIDER_DEPTH%"=="onnx" (
    set "BYES_SERVICE_DEPTH_PROVIDER=onnx"
  ) else if /I "%BYES_PROVIDER_DEPTH%"=="none" (
    set "BYES_SERVICE_DEPTH_PROVIDER=none"
  ) else if /I "%BYES_PROVIDER_DEPTH%"=="mock" (
    set "BYES_SERVICE_DEPTH_PROVIDER=mock"
  )
)
if /I "%BYES_SERVICE_DEPTH_PROVIDER%"=="da3" (
  call :set_if_missing BYES_SERVICE_DEPTH_ENDPOINT http://127.0.0.1:%DA3_PORT%/depth
  call :set_if_missing BYES_DA3_MODE da3
)

call :normalize_model_aliases

set "HAS_PADDLEOCR=0"
set "HAS_ULTRALYTICS=0"
set "HAS_ONNXRT=0"
set "HAS_FASTER_WHISPER=0"
set "HAS_SAM3_PKG=0"
set "HAS_DA3_PKG=0"
"%PYTHON_BIN%" -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('paddleocr') else 1)" >nul 2>&1
if !ERRORLEVEL! EQU 0 set "HAS_PADDLEOCR=1"
"%PYTHON_BIN%" -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('ultralytics') else 1)" >nul 2>&1
if !ERRORLEVEL! EQU 0 set "HAS_ULTRALYTICS=1"
"%PYTHON_BIN%" -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('onnxruntime') else 1)" >nul 2>&1
if !ERRORLEVEL! EQU 0 set "HAS_ONNXRT=1"
"%PYTHON_BIN%" -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('faster_whisper') else 1)" >nul 2>&1
if !ERRORLEVEL! EQU 0 set "HAS_FASTER_WHISPER=1"
"%PYTHON_BIN%" -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('sam3') else 1)" >nul 2>&1
if !ERRORLEVEL! EQU 0 set "HAS_SAM3_PKG=1"
"%PYTHON_BIN%" -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('depth_anything_3') else 1)" >nul 2>&1
if !ERRORLEVEL! EQU 0 set "HAS_DA3_PKG=1"

if not defined BYES_SERVICE_OCR_PROVIDER (
  if "!HAS_PADDLEOCR!"=="1" (
    set "BYES_SERVICE_OCR_PROVIDER=paddleocr"
  ) else (
    set "BYES_SERVICE_OCR_PROVIDER=mock"
  )
)
if not defined BYES_ASR_BACKEND (
  if "!HAS_FASTER_WHISPER!"=="1" (
    set "BYES_ASR_BACKEND=faster_whisper"
  ) else (
    set "BYES_ASR_BACKEND=mock"
  )
)

if not defined USER_DEFINED_BYES_OCR_BACKEND (
  if /I "%BYES_SERVICE_OCR_PROVIDER%"=="mock" (
    set "BYES_OCR_BACKEND=mock"
  ) else (
    set "BYES_OCR_BACKEND=http"
  )
)
if not defined USER_DEFINED_BYES_DET_BACKEND (
  if /I "%BYES_SERVICE_DET_PROVIDER%"=="mock" (
    set "BYES_DET_BACKEND=mock"
  ) else (
    set "BYES_DET_BACKEND=http"
  )
)
if not defined USER_DEFINED_BYES_SEG_BACKEND (
  if /I "%BYES_SERVICE_SEG_PROVIDER%"=="mock" (
    set "BYES_SEG_BACKEND=mock"
  ) else (
    set "BYES_SEG_BACKEND=http"
  )
)
if not defined USER_DEFINED_BYES_DEPTH_BACKEND (
  if /I "%BYES_SERVICE_DEPTH_PROVIDER%"=="mock" (
    set "BYES_DEPTH_BACKEND=mock"
  ) else if /I "%BYES_SERVICE_DEPTH_PROVIDER%"=="none" (
    set "BYES_DEPTH_BACKEND=mock"
  ) else (
    set "BYES_DEPTH_BACKEND=http"
  )
)
if not defined USER_DEFINED_BYES_SLAM_BACKEND (
  if /I "%BYES_ENABLE_PYSLAM_REALTIME%"=="1" (
    set "BYES_SLAM_BACKEND=http"
  ) else (
    set "BYES_SLAM_BACKEND=mock"
  )
)

call :classify_ocr
call :classify_det
call :classify_seg
call :classify_depth
call :classify_pyslam_runtime
call :classify_asr

if defined CUDA128_PYTHON_BIN if /I "!STATUS_SEG!"=="READY_REAL" (
  call :probe_service_runtime seg "%CUDA128_PYTHON_BIN%" SEG_PROBE
  if /I "!SEG_PROBE_DEVICE!"=="cuda" set "SEG_SERVICE_PYTHON_BIN=%CUDA128_PYTHON_BIN%"
)
if defined CUDA128_PYTHON_BIN if /I "!STATUS_DEPTH!"=="READY_REAL" (
  call :probe_service_runtime depth "%CUDA128_PYTHON_BIN%" DEPTH_PROBE
  if /I "!DEPTH_PROBE_DEVICE!"=="cuda" set "DEPTH_SERVICE_PYTHON_BIN=%CUDA128_PYTHON_BIN%"
)

echo [%SCRIPT_NAME%] preflight summary:
echo   OCR: !STATUS_OCR! (!DETAIL_OCR!)
echo   DET: !STATUS_DET! (!DETAIL_DET!)
echo   SEG: !STATUS_SEG! (!DETAIL_SEG!)
echo   DEPTH: !STATUS_DEPTH! (!DETAIL_DEPTH!)
echo   pySLAM: !STATUS_PYSLAM! (!DETAIL_PYSLAM!)
echo   ASR: !STATUS_ASR! (!DETAIL_ASR!)
echo   PCA: READY_RUNTIME_HINT (physical Quest 3/3S + permission + non-Link/non-Simulator required)
if /I "!STATUS_SEG!"=="READY_REAL" echo   SEG CUDA probe: device=!SEG_PROBE_DEVICE! reason=!SEG_PROBE_DEVICEREASON! warmupMs=!SEG_PROBE_WARMUPMS! torch=!SEG_PROBE_TORCHVERSION! cuda=!SEG_PROBE_CUDARUNTIME! cap=!SEG_PROBE_DEVICECAPABILITY! python=!SEG_SERVICE_PYTHON_BIN!
if /I "!STATUS_DEPTH!"=="READY_REAL" echo   DEPTH CUDA probe: device=!DEPTH_PROBE_DEVICE! reason=!DEPTH_PROBE_DEVICEREASON! warmupMs=!DEPTH_PROBE_WARMUPMS! torch=!DEPTH_PROBE_TORCHVERSION! cuda=!DEPTH_PROBE_CUDARUNTIME! cap=!DEPTH_PROBE_DEVICECAPABILITY! python=!DEPTH_SERVICE_PYTHON_BIN!

if /I "!BYES_PREFLIGHT_ONLY!"=="1" set "PREFLIGHT_ONLY_FLAG=1"
if /I "!PREFLIGHT_ONLY_FLAG!"=="1" (
  echo [%SCRIPT_NAME%] preflight-only mode enabled; skipping adb reverse and process launch.
  exit /b 0
)

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
  echo [%SCRIPT_NAME%] adb.exe not found. Set ADB_EXE first.
  set "RC=2"
  goto :abort
)
if not exist "%ADB_BIN%" (
  echo [%SCRIPT_NAME%] adb path does not exist: "%ADB_BIN%"
  set "RC=2"
  goto :abort
)

echo [%SCRIPT_NAME%] adb=%ADB_BIN%
"%ADB_BIN%" devices
set "HAS_DEVICE="
for /f "skip=1 tokens=1,2" %%A in ('"%ADB_BIN%" devices') do (
  if "%%B"=="device" set "HAS_DEVICE=1"
)
if not defined HAS_DEVICE (
  echo [%SCRIPT_NAME%] no adb device found.
  set "RC=3"
  goto :abort
)

echo [%SCRIPT_NAME%] adb reverse tcp:%GATEWAY_PORT% ^> tcp:%GATEWAY_PORT%
"%ADB_BIN%" reverse tcp:%GATEWAY_PORT% tcp:%GATEWAY_PORT%
"%ADB_BIN%" reverse --list

call :ensure_port_free %GATEWAY_PORT%
if errorlevel 1 goto :abort
call :ensure_port_free %INFERENCE_PORT%
if errorlevel 1 goto :abort

if /I "!STATUS_PYSLAM!"=="READY_REAL" (
  if not defined BYES_ENABLE_PYSLAM_REALTIME set "BYES_ENABLE_PYSLAM_REALTIME=1"
  set "BYES_SLAM_HTTP_URL=http://127.0.0.1:%PYSLAM_PORT%/slam/step"
) else if not defined BYES_ENABLE_PYSLAM_REALTIME (
  set "BYES_ENABLE_PYSLAM_REALTIME=0"
)

if /I "!STATUS_PYSLAM!"=="READY_REAL" if /I "%BYES_ENABLE_PYSLAM_REALTIME%"=="1" call :start_optional_service "%PYSLAM_PORT%" "BYES-pySLAM-v5.09.1" "services.pyslam_service.app:app" "%PYTHON_BIN%"
if /I "!STATUS_SEG!"=="READY_REAL" call :start_optional_service "%SAM3_PORT%" "BYES-SAM3-v5.09.1" "services.sam3_seg_service.app:app" "%SEG_SERVICE_PYTHON_BIN%"
if /I "!STATUS_DEPTH!"=="READY_REAL" if /I "%BYES_SERVICE_DEPTH_PROVIDER%"=="da3" call :start_optional_service "%DA3_PORT%" "BYES-DA3-v5.09.1" "services.da3_depth_service.app:app" "%DEPTH_SERVICE_PYTHON_BIN%"

echo [%SCRIPT_NAME%] opening desktop console at http://127.0.0.1:%GATEWAY_PORT%/ui
start "" "http://127.0.0.1:%GATEWAY_PORT%/ui"

echo [%SCRIPT_NAME%] Starting gateway + inference in this window. Press Ctrl+C to stop.
cd /d "%REPO_ROOT%\Gateway"
"%PYTHON_BIN%" scripts/dev_up.py --with-inference --host 127.0.0.1 --gateway-port %GATEWAY_PORT% --inference-port %INFERENCE_PORT% --no-reload
set "RC=%ERRORLEVEL%"
echo [%SCRIPT_NAME%] stack exited with code %RC%
exit /b %RC%

:ensure_port_free
set "PORT_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%~1 .*LISTENING"') do (
  if not defined PORT_PID set "PORT_PID=%%P"
)
if defined PORT_PID (
  echo [%SCRIPT_NAME%] Port %~1 is already in use by PID %PORT_PID%.
  tasklist /fi "PID eq %PORT_PID%" 2>nul
  set "RC=5"
  exit /b 1
)
exit /b 0

:capture_user_env
if defined %~1 set "USER_DEFINED_%~1=1"
exit /b 0

:set_if_missing
if not defined %~1 set "%~1=%~2"
exit /b 0

:resolve_python_bin
set "PYTHON_BIN=python"
if not defined BYES_PYTHON_EXE exit /b 0
if not exist "%BYES_PYTHON_EXE%" (
  echo [%SCRIPT_NAME%] BYES_PYTHON_EXE not found: "%BYES_PYTHON_EXE%"
  set "RC=2"
  exit /b 1
)
set "PYTHON_BIN=%BYES_PYTHON_EXE%"
exit /b 0

:resolve_cuda_python_bin
set "CUDA128_PYTHON_BIN="
if not defined BYES_PYTHON_EXE_CUDA128 exit /b 0
if not exist "%BYES_PYTHON_EXE_CUDA128%" (
  echo [%SCRIPT_NAME%] BYES_PYTHON_EXE_CUDA128 not found: "%BYES_PYTHON_EXE_CUDA128%"
  exit /b 0
)
set "CUDA128_PYTHON_BIN=%BYES_PYTHON_EXE_CUDA128%"
exit /b 0

:write_cuda_probe_script
set "CUDA_PROBE_SCRIPT=%TEMP%\byes_cuda_probe_v5091.py"
> "%CUDA_PROBE_SCRIPT%" echo import sys
>> "%CUDA_PROBE_SCRIPT%" echo import os
>> "%CUDA_PROBE_SCRIPT%" echo sys.path.insert^(0, os.getcwd^(^)^)
>> "%CUDA_PROBE_SCRIPT%" echo.
>> "%CUDA_PROBE_SCRIPT%" echo def emit(key, value):
>> "%CUDA_PROBE_SCRIPT%" echo     print(f"{key}={value if value is not None else ''}")
>> "%CUDA_PROBE_SCRIPT%" echo.
>> "%CUDA_PROBE_SCRIPT%" echo def main():
>> "%CUDA_PROBE_SCRIPT%" echo     kind = ^(sys.argv[1] if sys.argv[1:] else ''^).strip^(^).lower^(^)
>> "%CUDA_PROBE_SCRIPT%" echo     try:
>> "%CUDA_PROBE_SCRIPT%" echo         if kind == 'seg':
>> "%CUDA_PROBE_SCRIPT%" echo             from services.sam3_seg_service.app import _load_state, _ensure_sam3_runtime
>> "%CUDA_PROBE_SCRIPT%" echo             state = _load_state^(^)
>> "%CUDA_PROBE_SCRIPT%" echo             runtime = _ensure_sam3_runtime^(state^)
>> "%CUDA_PROBE_SCRIPT%" echo         elif kind == 'depth':
>> "%CUDA_PROBE_SCRIPT%" echo             from services.da3_depth_service.app import _load_state, _ensure_da3_runtime
>> "%CUDA_PROBE_SCRIPT%" echo             state = _load_state^(^)
>> "%CUDA_PROBE_SCRIPT%" echo             runtime = _ensure_da3_runtime^(state^)
>> "%CUDA_PROBE_SCRIPT%" echo         else:
>> "%CUDA_PROBE_SCRIPT%" echo             raise RuntimeError^(f'unknown_kind:{kind}'^)
>> "%CUDA_PROBE_SCRIPT%" echo         emit^('device', state.get^('actualDevice'^) or state.get^('device'^) or 'cpu'^)
>> "%CUDA_PROBE_SCRIPT%" echo         emit^('deviceReason', state.get^('deviceReason'^) or ''^)
>> "%CUDA_PROBE_SCRIPT%" echo         emit^('warmupMs', ^(runtime or {}^).get^('warmupMs'^)^)
>> "%CUDA_PROBE_SCRIPT%" echo         emit^('torchVersion', state.get^('torchVersion'^) or ^(runtime or {}^).get^('torchVersion'^)^)
>> "%CUDA_PROBE_SCRIPT%" echo         emit^('cudaRuntime', state.get^('cudaRuntime'^) or ^(runtime or {}^).get^('cudaRuntime'^)^)
>> "%CUDA_PROBE_SCRIPT%" echo         emit^('cudaRuntimeLine', state.get^('cudaRuntimeLine'^) or ^(runtime or {}^).get^('cudaRuntimeLine'^)^)
>> "%CUDA_PROBE_SCRIPT%" echo         emit^('deviceCapability', state.get^('deviceCapabilityToken'^) or ^(runtime or {}^).get^('deviceCapabilityToken'^)^)
>> "%CUDA_PROBE_SCRIPT%" echo         emit^('deviceName', state.get^('deviceName'^) or ^(runtime or {}^).get^('deviceName'^)^)
>> "%CUDA_PROBE_SCRIPT%" echo     except Exception as exc:
>> "%CUDA_PROBE_SCRIPT%" echo         emit^('device', 'cpu'^)
>> "%CUDA_PROBE_SCRIPT%" echo         emit^('deviceReason', f'probe_failed:{exc.__class__.__name__}:{exc}'^)
>> "%CUDA_PROBE_SCRIPT%" echo         emit^('warmupMs', -1^)
>> "%CUDA_PROBE_SCRIPT%" echo         emit^('torchVersion', ''^)
>> "%CUDA_PROBE_SCRIPT%" echo         emit^('cudaRuntime', ''^)
>> "%CUDA_PROBE_SCRIPT%" echo         emit^('cudaRuntimeLine', ''^)
>> "%CUDA_PROBE_SCRIPT%" echo         emit^('deviceCapability', ''^)
>> "%CUDA_PROBE_SCRIPT%" echo         emit^('deviceName', ''^)
>> "%CUDA_PROBE_SCRIPT%" echo.
>> "%CUDA_PROBE_SCRIPT%" echo if __name__ == '__main__':
>> "%CUDA_PROBE_SCRIPT%" echo     main^(^)
exit /b 0

:probe_service_runtime
set "%~3_DEVICE=cpu"
set "%~3_DEVICEREASON=probe_not_run"
set "%~3_WARMUPMS=-1"
set "%~3_TORCHVERSION="
set "%~3_CUDARUNTIME="
set "%~3_CUDARUNTIMELINE="
set "%~3_DEVICECAPABILITY="
set "%~3_DEVICENAME="
set "CUDA_PROBE_OUT=%TEMP%\byes_cuda_probe_%~1.out"
pushd "%REPO_ROOT%\Gateway" >nul
"%~2" "%CUDA_PROBE_SCRIPT%" %~1 > "%CUDA_PROBE_OUT%" 2>nul
for /f "usebackq tokens=1* delims==" %%A in ("%CUDA_PROBE_OUT%") do (
  if /I "%%A"=="device" set "%~3_DEVICE=%%B"
  if /I "%%A"=="deviceReason" set "%~3_DEVICEREASON=%%B"
  if /I "%%A"=="warmupMs" set "%~3_WARMUPMS=%%B"
  if /I "%%A"=="torchVersion" set "%~3_TORCHVERSION=%%B"
  if /I "%%A"=="cudaRuntime" set "%~3_CUDARUNTIME=%%B"
  if /I "%%A"=="cudaRuntimeLine" set "%~3_CUDARUNTIMELINE=%%B"
  if /I "%%A"=="deviceCapability" set "%~3_DEVICECAPABILITY=%%B"
  if /I "%%A"=="deviceName" set "%~3_DEVICENAME=%%B"
)
popd >nul
del /q "%CUDA_PROBE_OUT%" >nul 2>&1
if not defined %~3_DEVICE set "%~3_DEVICE=cpu"
if not defined %~3_DEVICEREASON set "%~3_DEVICEREASON=probe_no_output"
if not defined %~3_WARMUPMS set "%~3_WARMUPMS=-1"
if not defined %~3_TORCHVERSION set "%~3_TORCHVERSION="
if not defined %~3_CUDARUNTIME set "%~3_CUDARUNTIME="
if not defined %~3_CUDARUNTIMELINE set "%~3_CUDARUNTIMELINE="
if not defined %~3_DEVICECAPABILITY set "%~3_DEVICECAPABILITY="
if not defined %~3_DEVICENAME set "%~3_DEVICENAME="
exit /b 0

:normalize_model_aliases
if not defined BYES_YOLO26_WEIGHTS if defined BYES_SERVICE_DET_MODEL_PATH set "BYES_YOLO26_WEIGHTS=%BYES_SERVICE_DET_MODEL_PATH%"
if not defined BYES_SERVICE_DET_MODEL_PATH if defined BYES_YOLO26_WEIGHTS set "BYES_SERVICE_DET_MODEL_PATH=%BYES_YOLO26_WEIGHTS%"
if not defined BYES_SERVICE_DET_MODEL if defined BYES_SERVICE_DET_MODEL_PATH set "BYES_SERVICE_DET_MODEL=%BYES_SERVICE_DET_MODEL_PATH%"

if not defined BYES_SAM3_CKPT if defined BYES_SERVICE_SEG_MODEL_PATH set "BYES_SAM3_CKPT=%BYES_SERVICE_SEG_MODEL_PATH%"
if not defined BYES_SAM3_CKPT if defined BYES_SERVICE_SAM3_CKPT set "BYES_SAM3_CKPT=%BYES_SERVICE_SAM3_CKPT%"
if not defined BYES_SAM3_CKPT if defined BYES_SAM3_WEIGHTS set "BYES_SAM3_CKPT=%BYES_SAM3_WEIGHTS%"
if not defined BYES_SAM3_CKPT_PATH if defined BYES_SAM3_CKPT set "BYES_SAM3_CKPT_PATH=%BYES_SAM3_CKPT%"
if not defined BYES_SERVICE_SAM3_CKPT if defined BYES_SAM3_CKPT_PATH set "BYES_SERVICE_SAM3_CKPT=%BYES_SAM3_CKPT_PATH%"

if not defined BYES_DA3_MODEL_PATH if defined BYES_SERVICE_DEPTH_MODEL_PATH set "BYES_DA3_MODEL_PATH=%BYES_SERVICE_DEPTH_MODEL_PATH%"
if not defined BYES_DA3_MODEL_PATH if defined BYES_SERVICE_DEPTH_ONNX_PATH set "BYES_DA3_MODEL_PATH=%BYES_SERVICE_DEPTH_ONNX_PATH%"
if not defined BYES_DA3_MODEL_PATH if defined BYES_DA3_WEIGHTS set "BYES_DA3_MODEL_PATH=%BYES_DA3_WEIGHTS%"
if not defined BYES_SERVICE_DEPTH_MODEL_PATH if defined BYES_DA3_MODEL_PATH set "BYES_SERVICE_DEPTH_MODEL_PATH=%BYES_DA3_MODEL_PATH%"
if not defined BYES_SERVICE_DEPTH_ONNX_PATH if defined BYES_DA3_MODEL_PATH set "BYES_SERVICE_DEPTH_ONNX_PATH=%BYES_DA3_MODEL_PATH%"
exit /b 0

:classify_ocr
if /I "%BYES_SERVICE_OCR_PROVIDER%"=="mock" (
  set "STATUS_OCR=READY_MOCK"
  set "DETAIL_OCR=provider=mock"
  exit /b 0
)
if "!HAS_PADDLEOCR!"=="1" (
  set "STATUS_OCR=READY_REAL"
  set "DETAIL_OCR=provider=%BYES_SERVICE_OCR_PROVIDER%"
) else (
  set "STATUS_OCR=UNAVAILABLE_RUNTIME"
  set "DETAIL_OCR=missing_dependency:paddleocr"
)
exit /b 0

:classify_det
set "DET_PROVIDER=%BYES_SERVICE_DET_PROVIDER%"
if /I "!DET_PROVIDER!"=="mock" (
  set "STATUS_DET=READY_MOCK"
  set "DETAIL_DET=provider=mock"
  exit /b 0
)
if /I "!DET_PROVIDER!"=="yolo26" (
  if "!HAS_ULTRALYTICS!" NEQ "1" (
    set "STATUS_DET=UNAVAILABLE_RUNTIME"
    set "DETAIL_DET=missing_dependency:ultralytics"
    exit /b 0
  )
  if not defined BYES_YOLO26_WEIGHTS (
    set "STATUS_DET=UNAVAILABLE_MISSING_PATH"
    set "DETAIL_DET=yolo26_weights empty"
    exit /b 0
  )
  if not exist "%BYES_YOLO26_WEIGHTS%" (
    set "STATUS_DET=UNAVAILABLE_MISSING_PATH"
    set "DETAIL_DET=yolo26_weights_not_found:%BYES_YOLO26_WEIGHTS%"
    exit /b 0
  )
  set "STATUS_DET=READY_REAL"
  set "DETAIL_DET=provider=yolo26 weights=%BYES_YOLO26_WEIGHTS%"
  exit /b 0
)
if /I "!DET_PROVIDER!"=="ultralytics" (
  if "!HAS_ULTRALYTICS!" NEQ "1" (
    set "STATUS_DET=UNAVAILABLE_RUNTIME"
    set "DETAIL_DET=missing_dependency:ultralytics"
    exit /b 0
  )
  if defined BYES_SERVICE_DET_MODEL_PATH if not exist "%BYES_SERVICE_DET_MODEL_PATH%" (
    set "STATUS_DET=UNAVAILABLE_MISSING_PATH"
    set "DETAIL_DET=det_model_not_found:%BYES_SERVICE_DET_MODEL_PATH%"
    exit /b 0
  )
  if not defined BYES_SERVICE_DET_MODEL if not defined BYES_SERVICE_DET_MODEL_PATH (
    set "STATUS_DET=UNAVAILABLE_MISSING_PATH"
    set "DETAIL_DET=det_model empty"
    exit /b 0
  )
  set "STATUS_DET=READY_REAL"
  if defined BYES_SERVICE_DET_MODEL_PATH (
    set "DETAIL_DET=provider=ultralytics model=%BYES_SERVICE_DET_MODEL_PATH%"
  ) else (
    set "DETAIL_DET=provider=ultralytics model=%BYES_SERVICE_DET_MODEL%"
  )
  exit /b 0
)
set "STATUS_DET=UNAVAILABLE_RUNTIME"
set "DETAIL_DET=unsupported_provider:%DET_PROVIDER%"
exit /b 0

:classify_seg
set "SEG_PROVIDER=%BYES_SERVICE_SEG_PROVIDER%"
if /I "!SEG_PROVIDER!"=="mock" (
  set "STATUS_SEG=READY_MOCK"
  set "DETAIL_SEG=provider=mock"
  exit /b 0
)
if /I "!SEG_PROVIDER!"=="sam3" (
  if "!HAS_SAM3_PKG!" NEQ "1" (
    set "STATUS_SEG=UNAVAILABLE_RUNTIME"
    set "DETAIL_SEG=missing_dependency:sam3_package"
    exit /b 0
  )
  if not defined BYES_SAM3_CKPT_PATH (
    set "STATUS_SEG=UNAVAILABLE_MISSING_PATH"
    set "DETAIL_SEG=sam3_ckpt empty"
    exit /b 0
  )
  if not exist "%BYES_SAM3_CKPT_PATH%" (
    set "STATUS_SEG=UNAVAILABLE_MISSING_PATH"
    set "DETAIL_SEG=sam3_ckpt_not_found:%BYES_SAM3_CKPT_PATH%"
    exit /b 0
  )
  set "STATUS_SEG=READY_REAL"
  set "DETAIL_SEG=provider=sam3 ckpt=%BYES_SAM3_CKPT_PATH%"
  exit /b 0
)
set "STATUS_SEG=UNAVAILABLE_RUNTIME"
set "DETAIL_SEG=unsupported_provider:%SEG_PROVIDER%"
exit /b 0

:classify_depth
set "DEPTH_PROVIDER=%BYES_SERVICE_DEPTH_PROVIDER%"
if /I "!DEPTH_PROVIDER!"=="mock" (
  set "STATUS_DEPTH=READY_MOCK"
  set "DETAIL_DEPTH=provider=mock"
  exit /b 0
)
if /I "!DEPTH_PROVIDER!"=="none" (
  set "STATUS_DEPTH=UNAVAILABLE_RUNTIME"
  set "DETAIL_DEPTH=provider=none"
  exit /b 0
)
if /I "!DEPTH_PROVIDER!"=="da3" (
  if "!HAS_DA3_PKG!" NEQ "1" (
    set "STATUS_DEPTH=UNAVAILABLE_RUNTIME"
    set "DETAIL_DEPTH=missing_dependency:depth_anything_3"
    exit /b 0
  )
  if not defined BYES_DA3_MODEL_PATH (
    set "STATUS_DEPTH=UNAVAILABLE_MISSING_PATH"
    set "DETAIL_DEPTH=depth_model empty"
    exit /b 0
  )
  if not exist "%BYES_DA3_MODEL_PATH%" (
    set "STATUS_DEPTH=UNAVAILABLE_MISSING_PATH"
    set "DETAIL_DEPTH=depth_model_not_found:%BYES_DA3_MODEL_PATH%"
    exit /b 0
  )
  set "STATUS_DEPTH=READY_REAL"
  set "DETAIL_DEPTH=provider=da3 model=%BYES_DA3_MODEL_PATH%"
  exit /b 0
)
if /I "!DEPTH_PROVIDER!"=="onnx" (
  if "!HAS_ONNXRT!" NEQ "1" (
    set "STATUS_DEPTH=UNAVAILABLE_RUNTIME"
    set "DETAIL_DEPTH=missing_dependency:onnxruntime"
    exit /b 0
  )
  if not defined BYES_SERVICE_DEPTH_ONNX_PATH (
    set "STATUS_DEPTH=UNAVAILABLE_MISSING_PATH"
    set "DETAIL_DEPTH=depth_model empty"
    exit /b 0
  )
  if not exist "%BYES_SERVICE_DEPTH_ONNX_PATH%" (
    set "STATUS_DEPTH=UNAVAILABLE_MISSING_PATH"
    set "DETAIL_DEPTH=depth_model_not_found:%BYES_SERVICE_DEPTH_ONNX_PATH%"
    exit /b 0
  )
  set "STATUS_DEPTH=READY_REAL"
  set "DETAIL_DEPTH=provider=onnx model=%BYES_SERVICE_DEPTH_ONNX_PATH%"
  exit /b 0
)
set "STATUS_DEPTH=UNAVAILABLE_RUNTIME"
set "DETAIL_DEPTH=unsupported_provider:%DEPTH_PROVIDER%"
exit /b 0

:classify_pyslam_runtime
if not defined BYES_PYSLAM_ROOT (
  set "STATUS_PYSLAM=UNAVAILABLE_MISSING_PATH"
  set "DETAIL_PYSLAM=root empty"
  exit /b 0
)
if "%BYES_PYSLAM_ROOT%"=="=" (
  set "STATUS_PYSLAM=UNAVAILABLE_MISSING_PATH"
  set "DETAIL_PYSLAM=root empty"
  exit /b 0
)
if "%BYES_PYSLAM_ROOT%"=="""" (
  set "STATUS_PYSLAM=UNAVAILABLE_MISSING_PATH"
  set "DETAIL_PYSLAM=root empty"
  exit /b 0
)
if not exist "%BYES_PYSLAM_ROOT%" (
  set "STATUS_PYSLAM=UNAVAILABLE_MISSING_PATH"
  set "DETAIL_PYSLAM=root_not_found:%BYES_PYSLAM_ROOT%"
  exit /b 0
)
if not exist "%BYES_PYSLAM_ROOT%\.git" (
  set "STATUS_PYSLAM=UNAVAILABLE_RUNTIME"
  set "DETAIL_PYSLAM=root_not_repo:%BYES_PYSLAM_ROOT%"
  exit /b 0
)
call :check_pyslam_submodules "%BYES_PYSLAM_ROOT%"
if "!PYSLAM_SUBMODULES_OK!" NEQ "1" (
  set "STATUS_PYSLAM=UNAVAILABLE_RUNTIME"
  set "DETAIL_PYSLAM=!PYSLAM_SUBMODULE_DETAIL!"
  exit /b 0
)
set "STATUS_PYSLAM=READY_REAL"
set "DETAIL_PYSLAM=root=%BYES_PYSLAM_ROOT%"
exit /b 0

:classify_asr
set "ASR_BACKEND_NORMALIZED=%BYES_ASR_BACKEND%"
if /I "!ASR_BACKEND_NORMALIZED!"=="mock" (
  set "STATUS_ASR=READY_MOCK"
  if not defined BYES_ASR_MODEL (
    set "DETAIL_ASR=backend=mock model=mock-asr-v1"
  ) else (
    set "DETAIL_ASR=backend=mock model=%BYES_ASR_MODEL%"
  )
  exit /b 0
)
if /I "!ASR_BACKEND_NORMALIZED!"=="faster_whisper" (
  if "!HAS_FASTER_WHISPER!" NEQ "1" (
    set "STATUS_ASR=UNAVAILABLE_RUNTIME"
    set "DETAIL_ASR=missing_dependency:faster_whisper"
    exit /b 0
  )
  if not defined BYES_ASR_MODEL set "BYES_ASR_MODEL=small"
  set "STATUS_ASR=READY_REAL"
  set "DETAIL_ASR=backend=faster_whisper model=%BYES_ASR_MODEL%"
  exit /b 0
)
set "STATUS_ASR=UNAVAILABLE_RUNTIME"
set "DETAIL_ASR=unsupported_backend:%BYES_ASR_BACKEND%"
exit /b 0

:load_env_file
set "ENV_FILE=%~1"
set "ALLOW_OVERRIDE=%~2"
if not exist "%ENV_FILE%" exit /b 0
for /f "usebackq tokens=* delims=" %%L in ("%ENV_FILE%") do (
  set "ENV_LINE=%%L"
  if defined ENV_LINE (
    if not "!ENV_LINE:~0,1!"=="#" (
      for /f "tokens=1* delims==" %%A in ("!ENV_LINE!") do (
        set "ENV_KEY=%%A"
        set "ENV_VALUE=%%B"
        if defined ENV_KEY (
          call :trim_value ENV_KEY
          call :trim_value ENV_VALUE
          if defined ENV_KEY call :assign_env_var "!ENV_KEY!" "!ENV_VALUE!" !ALLOW_OVERRIDE!
        )
      )
    )
  )
)
exit /b 0

:assign_env_var
set "ASSIGN_KEY=%~1"
set "ASSIGN_VALUE=%~2"
if "!ASSIGN_VALUE:~0,1!"=="\"" if "!ASSIGN_VALUE:~-1!"=="\"" set "ASSIGN_VALUE=!ASSIGN_VALUE:~1,-1!"
if defined USER_DEFINED_!ASSIGN_KEY! exit /b 0
if "%~3"=="1" (
  set "!ASSIGN_KEY!=!ASSIGN_VALUE!"
  exit /b 0
)
if not defined !ASSIGN_KEY! set "!ASSIGN_KEY!=!ASSIGN_VALUE!"
exit /b 0

:trim_value
set "%~1=!%~1: = !"
for /f "tokens=* delims= " %%Z in ("!%~1!") do set "%~1=%%Z"
:trim_value_loop
if "!%~1:~-1!"==" " set "%~1=!%~1:~0,-1!" & goto :trim_value_loop
exit /b 0

:normalize_empty_like_value
if not defined %~1 exit /b 0
if "!%~1!"=="=" set "%~1="
if "!%~1!"=="\"\"" set "%~1="
exit /b 0

:check_pyslam_submodules
set "PYSLAM_SUBMODULES_OK=1"
set "PYSLAM_SUBMODULE_DETAIL=submodules_ok"
for /f "delims=" %%S in ('git -C "%~1" submodule status 2^>nul') do (
  set "SUBMODULE_LINE=%%S"
  if defined SUBMODULE_LINE (
    set "SUBMODULE_PREFIX=!SUBMODULE_LINE:~0,1!"
    if "!SUBMODULE_PREFIX!"=="-" (
      set "PYSLAM_SUBMODULES_OK=0"
      set "PYSLAM_SUBMODULE_DETAIL=incomplete_submodules"
    )
    if "!SUBMODULE_PREFIX!"=="+" (
      set "PYSLAM_SUBMODULES_OK=0"
      set "PYSLAM_SUBMODULE_DETAIL=incomplete_submodules"
    )
    if "!SUBMODULE_PREFIX!"=="U" (
      set "PYSLAM_SUBMODULES_OK=0"
      set "PYSLAM_SUBMODULE_DETAIL=incomplete_submodules"
    )
  )
)
exit /b 0

:start_optional_service
set "PORT_TO_CHECK=%~1"
set "WINDOW_TITLE=%~2"
set "UVICORN_MODULE=%~3"
set "SERVICE_PYTHON_BIN=%~4"
if not defined SERVICE_PYTHON_BIN set "SERVICE_PYTHON_BIN=%PYTHON_BIN%"
set "PORT_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT_TO_CHECK% .*LISTENING"') do (
  if not defined PORT_PID set "PORT_PID=%%P"
)
if not defined PORT_PID (
  echo [%SCRIPT_NAME%] starting optional service %UVICORN_MODULE% on %PORT_TO_CHECK%...
  start "%WINDOW_TITLE%" cmd /c "cd /d \"%REPO_ROOT%\Gateway\" ^&^& \"%SERVICE_PYTHON_BIN%\" -m uvicorn %UVICORN_MODULE% --host 127.0.0.1 --port %PORT_TO_CHECK%"
  timeout /t 1 >nul
) else (
  echo [%SCRIPT_NAME%] service %UVICORN_MODULE% already listening on %PORT_TO_CHECK%, PID=%PORT_PID%.
)
exit /b 0

:abort
if not defined RC set "RC=1"
echo [%SCRIPT_NAME%] aborted with code %RC%
if "%BYES_PAUSE_ON_ERROR%"=="1" pause
exit /b %RC%
