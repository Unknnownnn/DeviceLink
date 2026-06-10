@echo off
echo ==============================================
echo Building DeviceLink Standalone Executable
echo ==============================================
echo [1/2] Activating virtual environment...
call venv\Scripts\activate.bat

echo [2/2] Running PyInstaller...
pyinstaller --noconsole --onefile --collect-all customtkinter --hidden-import=_cffi_backend --icon=icon.ico --add-data "icon.ico;." --add-data "icon.png;." --name DeviceLink DeviceLink.pyw

echo ==============================================
echo Build completed successfully!
echo The executable can be found in the "dist" folder.
echo ==============================================
pause
