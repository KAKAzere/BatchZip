@echo off
setlocal

python -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b 1

python -m PyInstaller --clean --noconfirm BatchZip.spec
if errorlevel 1 exit /b 1

echo.
echo.
echo ==============================
echo BatchZip build completed!
echo Output: dist\BatchZip.exe
echo ==============================
