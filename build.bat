@echo off
setlocal

set "VENV_PYTHON=.venv\Scripts\python.exe"

python -c "import struct, sys; raise SystemExit(0 if sys.version_info[:3] == (3, 14, 7) and struct.calcsize('P') * 8 == 64 else 1)"
if errorlevel 1 (
    echo Error: BatchZip builds require Python 3.14.7 64-bit.
    exit /b 1
)

set "HOST_PYTHON="
for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)"') do set "HOST_PYTHON=%%I"
if not defined HOST_PYTHON (
    echo Error: Could not determine the Python executable path.
    exit /b 1
)

set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0"

if exist ".venv\" (
    if not exist "%VENV_PYTHON%" (
        echo Error: The existing .venv is invalid. Recreate it with Python 3.14.7 64-bit.
        exit /b 1
    )
) else (
    "%HOST_PYTHON%" -m venv .venv
    if errorlevel 1 exit /b 1
)

"%VENV_PYTHON%" -c "import struct, sys; raise SystemExit(0 if sys.version_info[:3] == (3, 14, 7) and struct.calcsize('P') * 8 == 64 else 1)"
if errorlevel 1 (
    echo Error: The existing .venv must use Python 3.14.7 64-bit.
    exit /b 1
)

"%VENV_PYTHON%" -m pip install -r requirements-lock.txt
if errorlevel 1 exit /b 1

"%VENV_PYTHON%" -m pip check
if errorlevel 1 exit /b 1

"%VENV_PYTHON%" -B tools\check_environment.py
if errorlevel 1 exit /b 1

"%VENV_PYTHON%" -B tools\generate_version_info.py
if errorlevel 1 exit /b 1

"%VENV_PYTHON%" -B -m unittest discover -s tests
if errorlevel 1 exit /b 1

"%VENV_PYTHON%" -m PyInstaller --clean --noconfirm BatchZip.spec
if errorlevel 1 exit /b 1

echo.
echo.
echo ==============================
echo BatchZip build completed!
echo Output: dist\BatchZip.exe
echo ==============================
