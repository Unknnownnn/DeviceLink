@echo off
setlocal enabledelayedexpansion

echo Building DeviceLink Standalone Executable
echo .
echo .
echo .

if not exist "venv\Scripts\activate.bat" (
    echo [1/3] Virtual environment not found. Creating venv.
    where python >nul 2>nul
    if %errorlevel% neq 0 (
        echo ERROR: Python is not installed or not added to PATH.
        echo Please install Python and try again.
        pause
        exit /b 1
    )
    python -m venv venv
    if %errorlevel% neq 0 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
    echo Virtual environment created successfully
) else (
    echo [1/3] Virtual environment found
)

call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /b 1
)

echo [2/3] Checking and installing dependencies
python -m pip install --upgrade pip

if exist "requirements.txt" (
    echo Installing dependencies from requirements.txt
    pip install -r requirements.txt
) else (
    echo WARNING: requirements.txt not found! Skipping pip install
)

where pyinstaller >nul 2>nul
if %errorlevel% neq 0 (
    echo Installing PyInstaller
    pip install pyinstaller
) else (
    echo PyInstaller found
)

echo [3/3] Creating Build
pyinstaller --clean DeviceLink.spec
if %errorlevel% neq 0 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

echo Build completed successfully.
echo The executable can be found in the "dist" folder.
pause
