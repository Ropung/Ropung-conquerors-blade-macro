@echo off
setlocal
cd /d "%~dp0"
call :build > build.log 2>&1
set "BUILD_RESULT=%ERRORLEVEL%"
type build.log
echo.
if "%BUILD_RESULT%"=="0" (
  echo SUCCESS: %CD%\dist\ConquerorsBladeMacro.exe
) else (
  echo BUILD FAILED. Details are saved to: %CD%\build.log
)
echo.
pause
exit /b %BUILD_RESULT%

:build
echo [1/5] Checking Python environment...
if not exist ".venv\Scripts\python.exe" (
  echo Create the Python 3.12 x64 virtual environment first. See README.md.
  exit /b 1
)
".venv\Scripts\python.exe" --version
if errorlevel 1 (
  echo The virtual environment cannot start its base Python.
  echo Check .venv\pyvenv.cfg and the Python installation path.
  echo No EXE was created.
  exit /b 1
)
echo [2/5] Checking build dependencies...
".venv\Scripts\python.exe" -c "import PyInstaller, cv2, numpy, PySide6"
if errorlevel 1 (
  echo Install dependencies with: .venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)
echo [3/5] Running tests...
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 exit /b 1
echo [4/5] Preparing embedded calibration images...
".venv\Scripts\python.exe" package_assets.py
if errorlevel 1 exit /b 1
echo [5/5] Building single-file EXE...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --add-data "build\bundled_assets\calibration;calibration" --name ConquerorsBladeMacro main.py
if errorlevel 1 exit /b 1
echo Share dist\ConquerorsBladeMacro.exe. Calibration images are embedded; press Start to run.
exit /b 0
