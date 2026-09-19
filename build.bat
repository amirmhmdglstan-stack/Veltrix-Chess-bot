@echo off
REM ============================================================
REM  Veltrix 1.0 - Windows build script
REM
REM  Detects an available C++ compiler automatically:
REM    1) g++      (MinGW-w64 / MSYS2 - recommended)
REM    2) clang++  (LLVM for Windows)
REM    3) cl       (Microsoft Visual C++ "Build Tools for Visual Studio")
REM
REM  Usage (run from the project root, e.g. D:\Veltrix-Chess-bot):
REM    build.bat            - optimized build (portable baseline)
REM    build.bat native     - fastest build for this CPU (-march=native;
REM                           g++/clang only, ignored by MSVC)
REM
REM  Source files are compiled from engine\src\*.cpp.
REM  Result: engine\veltrix.exe (primary), plus convenience copies at
REM          veltrix.exe (project root) and bin\veltrix.exe so the GUI
REM          auto-detects the engine no matter which folder it checks.
REM ============================================================
setlocal enabledelayedexpansion

REM --- step 1: be in the engine\ folder no matter where we were launched from
cd /d "%~dp0engine" 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: cannot find the engine\ folder.
    echo This script ^(%~nx0^) must live in the project root, next to the
    echo engine\ gui\ tools\ folders. Do not move it or the sources.
    echo.
    exit /b 1
)

REM --- step 2: collect all C++ sources under engine\src
REM NOTE: "for %%f in (src\*.cpp)" expands %%f to "src\bitboard.cpp" etc.
REM (the path part IS included) - so %%f must be used as-is. Prepending
REM src\ again was the bug that produced "src\src\bitboard.cpp".
set SRC=
for %%f in (src\*.cpp) do set SRC=!SRC! %%f

if "%SRC%"=="" (
    echo.
    echo ERROR: no C++ source files found under engine\src.
    echo Expected files like engine\src\bitboard.cpp .. engine\src\uci.cpp.
    echo Please re-download/clone the project - never move source files.
    echo.
    exit /b 1
)
echo Compiling sources:%SRC%
echo.

REM --- step 3: pick compiler (first available on PATH wins)
set ARCHFLAG=
if /I "%~1"=="native" set ARCHFLAG=-march=native

where g++ >nul 2>nul
if %ERRORLEVEL% EQU 0 goto MINGW

where clang++ >nul 2>nul
if %ERRORLEVEL% EQU 0 goto CLANG

where cl >nul 2>nul
if %ERRORLEVEL% EQU 0 goto MSVC

echo ERROR: No C++ compiler found on PATH.
echo.
echo Install one of (any single one is enough):
echo   * MinGW-w64 (g++)       : https://www.mingw-w64.org/
echo     quick path:  winget install -e --id MSYS2.MSYS2
echo     then, in the "MSYS2 UCRT64" app, run:
echo       pacman -S --noconfirm mingw-w64-ucrt-x86_64-gcc
echo     and either run build.bat from the MSYS2 UCRT64 shell, or add
echo     C:\msys64\ucrt64\bin to your Windows PATH.
echo   * LLVM clang++          : https://releases.llvm.org/
echo   * MSVC Build Tools      : https://visualstudio.microsoft.com/visual-cpp-build-tools/
echo     (open "x64 Native Tools Command Prompt" before running build.bat)
echo.
exit /b 1

:MINGW
echo Using g++ (MinGW) ...
g++ -std=c++17 -O3 -Wall -fno-exceptions -fno-rtti -DNDEBUG -Isrc %ARCHFLAG% %SRC% -o veltrix.exe -static -static-libgcc -static-libstdc++ -pthread -Wl,--allow-multiple-definition
goto CHECK_RESULT

:CLANG
echo Using clang++ ...
clang++ -std=c++17 -O3 -Wall -fno-exceptions -fno-rtti -DNDEBUG -Isrc %ARCHFLAG% %SRC% -o veltrix.exe -pthread
goto CHECK_RESULT

:MSVC
echo Using MSVC cl (static CRT /MT; 'native' flag ignored) ...
cl /nologo /O2 /Ot /GL /std:c++17 /DNDEBUG /EHsc /MT %SRC% /Fe:veltrix.exe
goto CHECK_RESULT

:CHECK_RESULT
if errorlevel 1 goto FAIL
if not exist veltrix.exe (
    echo.
    echo ERROR: the compiler reported success but veltrix.exe was not created.
    goto FAIL
)

REM --- step 4: place the engine where the GUI auto-detects it
REM gui/engine_client.py find_engine() searches: gui\; gui\bin; gui\engine;
REM <project>\engine; <project>\bin; <project>\; CWD. We cover engine\, bin\
REM and the project root - every GUI candidate is satisfied.
copy /y veltrix.exe ..\veltrix.exe >nul && set "OKROOT=  project root : %~dp0veltrix.exe"
if not exist ..\bin mkdir ..\bin
copy /y veltrix.exe ..\bin\veltrix.exe >nul && set "OKBIN=  bin folder  : %~dp0bin\veltrix.exe"

echo ================================================================
echo  SUCCESS
echo  primary      : %CD%\veltrix.exe   (engine\veltrix.exe)
echo %OKROOT%
echo %OKBIN%
echo.
echo  The GUI finds the engine automatically - just run:
echo      python gui\veltrix_gui.py
echo  Quick manual test: type "veltrix.exe" then "uci"
echo ==========================_=====================================
exit /b 0

:FAIL
echo ================================================================
echo BUILD FAILED - see the compiler output above.
echo Most common causes:
echo   * compiler not installed / not on PATH (see the list above)
echo   * source files missing under engine\src
echo   * running from a folder other than the project where engine\src lives
echo ================================================================
exit /b 1
