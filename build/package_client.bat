@echo off
setlocal
set "AZT_PACKAGE_BINARY=%~f1"
pushd "%~dp0\.." || exit /b 1

if defined AZT_PACKAGE_BINARY goto :package
call build\build_client.bat
if errorlevel 1 goto :fail
set "AZT_PACKAGE_BINARY=%CD%\dist\AZT_Client.exe"

:package
if not exist "%AZT_PACKAGE_BINARY%" goto :fail
if not exist "CUSTOMER_README.txt" goto :fail
if not exist ".venv\Scripts\python.exe" goto :fail
if not exist "release" (
  mkdir "release"
  if errorlevel 1 goto :fail
)
".venv\Scripts\python.exe" -m zipfile -c "release\AZT_Client.zip.tmp" "%AZT_PACKAGE_BINARY%" "CUSTOMER_README.txt"
if errorlevel 1 goto :fail
move /Y "release\AZT_Client.zip.tmp" "release\AZT_Client.zip" >nul
if errorlevel 1 goto :fail
if not exist "release\AZT_Client.zip" goto :fail

echo Packaged "%CD%\release\AZT_Client.zip"
popd
exit /b 0

:fail
echo AZT Client packaging failed.
popd
exit /b 1
