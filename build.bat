@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Create the Python 3.12 x64 virtual environment first. See README.md.
  exit /b 1
)
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name ConquerorsBladeMacro main.py
if errorlevel 1 exit /b 1
rmdir /s /q release 2>nul
mkdir release\ConquerorsBladeMacro
copy /y dist\ConquerorsBladeMacro.exe release\ConquerorsBladeMacro\ >nul
copy /y config.example.json release\ConquerorsBladeMacro\config.example.json >nul
copy /y README.md release\ConquerorsBladeMacro\README.md >nul
copy /y PLAN.txt release\ConquerorsBladeMacro\PLAN.txt >nul
if exist calibration\ (xcopy calibration release\ConquerorsBladeMacro\calibration\ /e /i /y >nul)
powershell -NoProfile -Command "Compress-Archive -Path 'release\ConquerorsBladeMacro' -DestinationPath 'dist\ConquerorsBladeMacro-Windows.zip' -Force"
if errorlevel 1 exit /b 1
echo Share dist\ConquerorsBladeMacro-Windows.zip. Recipients only need to unzip it and run ConquerorsBladeMacro.exe.
