@echo off
REM ============================================================
REM MiniPACS – PyInstaller build script
REM Output: dist\MiniPACS.exe
REM ============================================================

echo [BUILD] Installing/upgrading dependencies...
pip install --upgrade pynetdicom pydicom Pillow pyinstaller

echo.
echo [BUILD] Running PyInstaller...

pyinstaller ^
    --onefile ^
    --windowed ^
    --name MiniPACS ^
    --hidden-import pynetdicom ^
    --hidden-import pynetdicom.sop_class ^
    --hidden-import pynetdicom._handlers ^
    --hidden-import pynetdicom.transport ^
    --hidden-import pynetdicom.events ^
    --hidden-import pynetdicom.association ^
    --hidden-import pynetdicom.presentation ^
    --hidden-import pydicom ^
    --hidden-import pydicom.dataset ^
    --hidden-import pydicom.sequence ^
    --hidden-import pydicom.uid ^
    --hidden-import pydicom.data ^
    --hidden-import pydicom._storage_sopclass_uids ^
    --hidden-import PIL ^
    --hidden-import PIL.Image ^
    --hidden-import PIL.ImageTk ^
    --hidden-import PIL.ImageOps ^
    --hidden-import tkinter ^
    --hidden-import tkinter.ttk ^
    --hidden-import tkinter.scrolledtext ^
    --hidden-import tkinter.filedialog ^
    --hidden-import tkinter.messagebox ^
    --hidden-import numpy ^
    --collect-all pynetdicom ^
    --collect-all pydicom ^
    --collect-all PIL ^
    mini_pacs_server.py

echo.
if exist dist\MiniPACS.exe (
    echo [BUILD] SUCCESS – dist\MiniPACS.exe created
    for %%A in (dist\MiniPACS.exe) do echo [BUILD] Size: %%~zA bytes
) else (
    echo [BUILD] ERROR – dist\MiniPACS.exe not found, check output above
    exit /b 1
)

echo.
echo [BUILD] Done.
pause
