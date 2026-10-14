@echo off
setlocal
cd /d "%~dp0\.."

echo ==========================================
echo   GOLD_AI CLIENT BUILDER
echo ==========================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [1/5] Creating client virtual environment...

  set "BOOTSTRAP_PY="

  if exist "%USERPROFILE%\Desktop\Bots\Forex\AMD1\.venv\Scripts\python.exe" (
    set "BOOTSTRAP_PY=%USERPROFILE%\Desktop\Bots\Forex\AMD1\.venv\Scripts\python.exe"
  )

  if not defined BOOTSTRAP_PY (
    where python.exe >nul 2>nul
    if not errorlevel 1 set "BOOTSTRAP_PY=python.exe"
  )

  if not defined BOOTSTRAP_PY (
    echo Could not find a working Python interpreter.
    echo Expected either:
    echo   %USERPROFILE%\Desktop\Bots\Forex\AMD1\.venv\Scripts\python.exe
    echo or a working python.exe on PATH.
    goto :fail
  )

  "%BOOTSTRAP_PY%" -m venv .venv
  if errorlevel 1 goto :fail
) else (
  echo [1/5] Client virtual environment already exists.
)

echo [2/5] Installing/updating dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [3/5] Cleaning previous build...
if exist build\pyi rmdir /s /q build\pyi
if exist dist\GOLD_AI_Client.exe del /q dist\GOLD_AI_Client.exe

echo [4/5] Compiling GOLD_AI_Client.exe...
pushd build
"..\.venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm --distpath "..\dist" --workpath "pyi" GOLD_AI_Client.spec
set BUILD_RC=%ERRORLEVEL%
popd

if not "%BUILD_RC%"=="0" goto :fail

echo [5/5] Build complete.
echo.
echo Built:
echo %CD%\dist\GOLD_AI_Client.exe
echo.
pause
exit /b 0

:fail
echo.
echo BUILD FAILED.
pause
exit /b 1
