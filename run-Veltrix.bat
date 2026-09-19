@echo off
REM ============================================================
REM  run-Veltrix.bat - double-click launcher for the Veltrix GUI
REM
REM  What it does: starts gui\veltrix_gui.py with the console-less
REM  Python (pythonw), so the program opens like a normal Windows
REM  app - no command prompt window stays open.
REM
REM  Prerequisites (one-time):
REM    1. the engine is built           -> build.bat
REM    2. Python 3.9+ is installed      -> https://www.python.org/
REM       (tick "Add python.exe to PATH" during install)
REM ============================================================
setlocal
cd /d "%~dp0"

REM --- friendly guard: engine must be built first -------------
if exist "engine\veltrix.exe" goto engok
if exist "veltrix.exe" goto engok
if exist "bin\veltrix.exe" goto engok
echo.
echo  The Veltrix engine was not found - build it first:
echo    1. Open a command prompt in this folder
echo    2. Type:  build.bat
echo  Then double-click run-Veltrix.bat again.
echo.
pause
exit /b 1
:engok

REM --- 1) python.org launcher, console-less (pyw = py but pythonw)
where pyw >nul 2>nul && (start "" pyw -3 "gui\veltrix_gui.py" & exit /b 0)

REM --- 2) pythonw.exe on PATH
where pythonw >nul 2>nul && (start "" pythonw.exe "gui\veltrix_gui.py" & exit /b 0)

REM --- 3) project-local virtualenv, if one exists
if exist "tools\venv\Scripts\pythonw.exe" (
    start "" "tools\venv\Scripts\pythonw.exe" "gui\veltrix_gui.py"
    exit /b 0
)

REM --- nothing worked: tell the user plainly
echo.
echo  Python 3.9+ was not found on this PC (or it is not on PATH).
echo  Install it from https://www.python.org/downloads/
echo  and TICK the box "Add python.exe to PATH" during setup.
echo  Then double-click run-Veltrix.bat again.
echo.
pause
exit /b 1
