@echo off
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  py -m venv .venv
  if errorlevel 1 goto :fail
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

if exist build\pyi rmdir /s /q build\pyi
if exist dist\GOLD_AI_Client.exe del /q dist\GOLD_AI_Client.exe

pushd build
"..\.venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm --distpath "..\dist" --workpath "pyi" GOLD_AI_Client.spec
set BUILD_RC=%ERRORLEVEL%
popd

if not "%BUILD_RC%"=="0" goto :fail
echo.
echo Built: %CD%\dist\GOLD_AI_Client.exe
pause
exit /b 0

:fail
echo.
echo BUILD FAILED.
pause
exit /b 1
