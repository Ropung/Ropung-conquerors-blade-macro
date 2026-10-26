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
copy /y config.example.json dist\config.example.json >nul
copy /y README.md dist\README.md >nul
copy /y PLAN.txt dist\PLAN.txt >nul
echo Build ready in dist. Keep EXE in a writable folder. Calibration is created beside EXE.
