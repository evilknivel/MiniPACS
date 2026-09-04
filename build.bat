@echo off
REM ============================================================
REM MiniPACS - PyInstaller build script (Windows)
REM
REM Builds a single self-contained windowed EXE from the
REM packaging config in MiniPACS.spec (the source of truth).
REM
REM Output: dist\MiniPACS.exe
REM ============================================================

setlocal

echo [BUILD] Installing/upgrading build dependencies...
pip install --upgrade pynetdicom pydicom Pillow numpy pyinstaller
if errorlevel 1 (
    echo [BUILD] ERROR - dependency installation failed
    exit /b 1
)

echo.
echo [BUILD] Running PyInstaller (MiniPACS.spec)...
pyinstaller --noconfirm --clean MiniPACS.spec
if errorlevel 1 (
    echo [BUILD] ERROR - PyInstaller failed, check output above
    exit /b 1
)

echo.
if exist dist\MiniPACS.exe (
    echo [BUILD] SUCCESS - dist\MiniPACS.exe created
    for %%A in (dist\MiniPACS.exe) do echo [BUILD] Size: %%~zA bytes
) else (
    echo [BUILD] ERROR - dist\MiniPACS.exe not found, check output above
    exit /b 1
)

echo.
echo [BUILD] Done.
if "%1"=="" pause
endlocal
