@echo off
REM ============================================================
REM  Veltrix 1.0 - Windows build script
REM
REM  Detects an available C++ compiler automatically:
REM    1) g++      (MinGW-w64 / MSYS2 - recommended)
REM    2) clang++  (LLVM for Windows)
REM    3) cl       (Microsoft Visual C++ "Build Tools for Visual Studio")
REM
REM  Usage:
REM    build.bat            - optimized build (portable baseline)
REM    build.bat native     - fastest build for this CPU (-march=native)
REM
REM  Result: veltrix.exe  (copied to the repo root and to bin\)
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0engine"

set SRC=
for %%f in (src\*.cpp) do set SRC=!SRC! src\%%f
echo Compiling:%SRC%

set ARCHFLAG=
if /I "%1"=="native" set ARCHFLAG=-march=native

where g++ >nul 2>nul
if %ERRORLEVEL% EQU 0 goto MINGW

where clang++ >nul 2>nul
if %ERRORLEVEL% EQU 0 goto CLANG

where cl >nul 2>nul
if %ERRORLEVEL% EQU 0 goto MSVC

echo.
echo ERROR: No C++ compiler found on PATH.
echo.
echo Install one of:
echo   * MinGW-w64 (g++)       : https://www.mingw-w64.org/  or  "winget install -e --id MSYS2.MSYS2"
echo   * LLVM clang++          : https://releases.llvm.org/
echo   * MSVC Build Tools      : https://visualstudio.microsoft.com/visual-cpp-build-tools/
echo     (for MSVC, open "x64 Native Tools Command Prompt" first)
echo.
exit /b 1

:MINGW
echo Using g++ (MinGW)
g++ -std=c++17 -O3 -Wall -fno-exceptions -fno-rtti -DNDEBUG -Isrc %ARCHFLAG% %SRC% -o veltrix.exe -static -static-libgcc -static-libstdc++ -pthread -Wl,--allow-multiple-definition
if errorlevel 1 goto FAIL
goto DONE

:CLANG
echo Using clang++
clang++ -std=c++17 -O3 -Wall -fno-exceptions -fno-rtti -DNDEBUG -Isrc %ARCHFLAG% %SRC% -o veltrix.exe -pthread
if errorlevel 1 goto FAIL
goto DONE

:MSVC
echo Using MSVC cl
cl /nologo /O2 /Ot /GL /std:c++17 /DNDEBUG /EHsc %SRC% /Fe:veltrix.exe
if errorlevel 1 goto FAIL
goto DONE

:DONE
echo.
if not exist ..\bin mkdir ..\bin
copy /y veltrix.exe ..\bin\veltrix.exe >nul
copy /y veltrix.exe ..\veltrix.exe >nul
echo ================================================================
echo  SUCCESS: engine\veltrix.exe
echo           (also copied to veltrix.exe and bin\veltrix.exe)
echo  Test:  veltrix.exe   then type:  uci
echo ================================================================
exit /b 0

:FAIL
echo.
echo BUILD FAILED - see the compiler output above.
exit /b 1
