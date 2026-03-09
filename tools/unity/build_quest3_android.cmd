@echo off
setlocal enableextensions enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"
set "LOG_DIR=%REPO_ROOT%\Builds\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG_FILE=%LOG_DIR%\unity_build_quest3_android.log"
set "VERSION_FILE=%REPO_ROOT%\VERSION"
set "VERSION_TMP=%REPO_ROOT%\VERSION.unity-build-tmp"

if defined UNITY_EXE (
  set "UNITY_BIN=%UNITY_EXE%"
) else (
  if exist "D:\6000.3.10f1\Editor\Unity.exe" (
    set "UNITY_BIN=D:\6000.3.10f1\Editor\Unity.exe"
  ) else if exist "C:\Program Files\Unity\Hub\Editor\6000.3.10f1\Editor\Unity.exe" (
    set "UNITY_BIN=C:\Program Files\Unity\Hub\Editor\6000.3.10f1\Editor\Unity.exe"
  ) else if exist "D:\Unity\Editor\Unity.exe" (
    set "UNITY_BIN=D:\Unity\Editor\Unity.exe"
  )
)

if not defined UNITY_BIN (
  echo [build_quest3_android] Unity executable not found.
  echo Set UNITY_EXE to your Unity.exe path, for example:
  echo   set UNITY_EXE=C:\Program Files\Unity\Hub\Editor\6000.3.10f1\Editor\Unity.exe
  exit /b 2
)

if not exist "%UNITY_BIN%" (
  echo [build_quest3_android] UNITY_EXE does not exist: "%UNITY_BIN%"
  exit /b 2
)

if not defined BYES_GRADLE_XMX (
  set "BYES_GRADLE_XMX=6144m"
)
if defined GRADLE_OPTS (
  set "GRADLE_OPTS=%GRADLE_OPTS% -Dorg.gradle.jvmargs=-Xmx%BYES_GRADLE_XMX%"
) else (
  set "GRADLE_OPTS=-Dorg.gradle.jvmargs=-Xmx%BYES_GRADLE_XMX%"
)
set "ORG_GRADLE_PROJECT_org.gradle.jvmargs=-Xmx%BYES_GRADLE_XMX%"

if not defined BYES_ANDROID_BUILD_CLEAN (
  set "BYES_ANDROID_BUILD_CLEAN=1"
)

echo [build_quest3_android] UNITY_BIN=%UNITY_BIN%
echo [build_quest3_android] GRADLE_OPTS=%GRADLE_OPTS%
echo [build_quest3_android] BYES_ANDROID_BUILD_CLEAN=%BYES_ANDROID_BUILD_CLEAN%
for %%I in ("%UNITY_BIN%") do set "UNITY_DIR=%%~dpI"
set "ANDROID_MODULE_DIR=%UNITY_DIR%Data\\PlaybackEngines\\AndroidPlayer"
if not exist "%ANDROID_MODULE_DIR%" (
  echo [build_quest3_android] Android Build Support module is missing.
  echo Expected folder: "%ANDROID_MODULE_DIR%"
  echo Install Android Build Support ^(SDK + NDK + OpenJDK^) for this Unity editor, then rerun.
  exit /b 2
)

if exist "%VERSION_TMP%" (
  echo [build_quest3_android] Temporary VERSION file already exists: "%VERSION_TMP%"
  echo Remove it manually before rerunning.
  exit /b 2
)

if exist "%VERSION_FILE%" (
  move /y "%VERSION_FILE%" "%VERSION_TMP%" >nul
  if errorlevel 1 (
    echo [build_quest3_android] Failed to relocate VERSION file before build.
    exit /b 2
  )
)

if "%BYES_ANDROID_BUILD_CLEAN%"=="1" (
  echo [build_quest3_android] Cleaning Android build caches...
  if exist "%REPO_ROOT%\Library\Bee\artifacts\Android" rmdir /s /q "%REPO_ROOT%\Library\Bee\artifacts\Android"
  if exist "%REPO_ROOT%\Library\Bee\Android" rmdir /s /q "%REPO_ROOT%\Library\Bee\Android"
  if exist "%REPO_ROOT%\.utmp" rmdir /s /q "%REPO_ROOT%\.utmp"
  if exist "%REPO_ROOT%\Project-Be-your-eyes_BurstDebugInformation_DoNotShip" rmdir /s /q "%REPO_ROOT%\Project-Be-your-eyes_BurstDebugInformation_DoNotShip"
)

"%UNITY_BIN%" -batchmode -nographics -quit ^
  -projectPath "%REPO_ROOT%" ^
  -executeMethod BYES.Editor.ByesBuildQuest3.BuildQuest3SmokeApk ^
  -logFile "%LOG_FILE%"
set "UNITY_EXIT=%ERRORLEVEL%"

if exist "%VERSION_TMP%" (
  move /y "%VERSION_TMP%" "%VERSION_FILE%" >nul
  if errorlevel 1 (
    echo [build_quest3_android] WARNING: failed to restore VERSION file from "%VERSION_TMP%".
    set "UNITY_EXIT=1"
  )
)

python "%REPO_ROOT%\tools\unity\parse_unity_build_log.py" "%LOG_FILE%"
set "PARSE_EXIT=%ERRORLEVEL%"

echo [build_quest3_android] UNITY_EXIT=%UNITY_EXIT% PARSE_EXIT=%PARSE_EXIT%

if not "%PARSE_EXIT%"=="0" (
  exit /b %PARSE_EXIT%
)

if not "%UNITY_EXIT%"=="0" (
  exit /b %UNITY_EXIT%
)

exit /b 0
