@echo off
setlocal
pushd "%~dp0\.." || exit /b 1

if exist ".venv\Scripts\python.exe" goto :venv_ready
where python.exe >nul 2>nul
if errorlevel 1 (
  echo Python 3.13 must be available on PATH to create the Client environment.
  goto :fail
)
python.exe -m venv .venv
if errorlevel 1 goto :fail

:venv_ready
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --distpath dist --workpath build\pyi build\GOLD_AI_Client.spec
if errorlevel 1 goto :fail
if not exist "dist\AZT_Client.exe" goto :fail

echo Built "%CD%\dist\AZT_Client.exe"
popd
exit /b 0

:fail
echo AZT Client build failed.
popd
exit /b 1
