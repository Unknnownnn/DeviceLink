@echo off
echo Building DeviceLink Standalone Executable
echo [1/2] Activating virtual environment...
call venv\Scripts\activate.bat
echo [2/2] Running PyInstaller...
pyinstaller --clean DeviceLink.spec

echo Build completed. The executable can be found in the "dist" folder.
pause
