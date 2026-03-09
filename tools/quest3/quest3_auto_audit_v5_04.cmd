@echo off
setlocal enableextensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"

set "BASE_URL=http://127.0.0.1:18000"
set "DEVICE_ID=quest3-smoke"
set "RECORD_SEC=6"

if not "%~1"=="" set "BASE_URL=%~1"
if not "%~2"=="" set "DEVICE_ID=%~2"
if not "%~3"=="" set "RECORD_SEC=%~3"

echo [quest3_auto_audit_v5_04] base_url=%BASE_URL%
echo [quest3_auto_audit_v5_04] device_id=%DEVICE_ID%
echo [quest3_auto_audit_v5_04] record_sec=%RECORD_SEC%

cd /d "%REPO_ROOT%"
python tools\quest3\quest3_auto_audit_v5_04.py --base-url "%BASE_URL%" --device-id "%DEVICE_ID%" --record-sec %RECORD_SEC%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo [quest3_auto_audit_v5_04] failed with code %RC%
  exit /b %RC%
)

echo [quest3_auto_audit_v5_04] completed successfully.
exit /b 0
