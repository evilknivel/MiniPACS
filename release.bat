@echo off
REM ============================================================
REM MiniPACS - release packaging script (Windows)
REM
REM   1. Builds dist\MiniPACS.exe via build.bat
REM   2. Stages the EXE + docs + third-party licenses
REM   3. Zips everything into release\MiniPACS-<version>.zip
REM
REM Usage:  release.bat [version]
REM   release.bat 1.2.0   -> release\MiniPACS-1.2.0.zip
REM   release.bat         -> release\MiniPACS-<yyyy.MM.dd>.zip, then pause
REM ============================================================

setlocal enabledelayedexpansion

REM Always operate from the script's own directory
pushd "%~dp0"

REM --- Version ---
if not "%~1"=="" (
    set "VERSION=%~1"
) else (
    for /f %%D in ('powershell -NoProfile -Command "Get-Date -Format yyyy.MM.dd"') do set "VERSION=%%D"
)

set "STAGE=release\MiniPACS"
set "ZIP=release\MiniPACS-%VERSION%.zip"
set "FILES=dist\MiniPACS.exe README.md LICENSE NOTICE.txt LICENSE_pynetdicom.txt LICENSE_pydicom.txt LICENSE_Pillow.txt"

echo [RELEASE] Version: %VERSION%
echo.

REM --- 1. Build the EXE (arg suppresses build.bat's pause) ---
echo [RELEASE] Building executable...
call "%~dp0build.bat" nopause || goto :fail
if not exist "dist\MiniPACS.exe" (
    echo [RELEASE] ERROR - dist\MiniPACS.exe not found
    goto :fail
)

REM --- 2. Stage release files ---
echo.
echo [RELEASE] Staging files...
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%" || goto :fail
for %%F in (%FILES%) do (
    if not exist "%%F" (
        echo [RELEASE] ERROR - missing required file: %%F
        goto :fail
    )
    copy /y "%%F" "%STAGE%\" >nul || goto :fail
    echo [RELEASE]   + %%~nxF
)

REM --- 3. Zip ---
echo.
echo [RELEASE] Creating %ZIP% ...
if exist "%ZIP%" del /q "%ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path '%STAGE%\*' -DestinationPath '%ZIP%' -Force" || goto :fail
rmdir /s /q "%STAGE%"

if not exist "%ZIP%" (
    echo [RELEASE] ERROR - %ZIP% not created
    goto :fail
)

echo.
for %%A in ("%ZIP%") do echo [RELEASE] SUCCESS - %%~fA ^(%%~zA bytes^)
echo [RELEASE] Done.
popd
if "%~1"=="" pause
endlocal
exit /b 0

:fail
echo.
echo [RELEASE] FAILED
popd
if "%~1"=="" pause
endlocal
exit /b 1
