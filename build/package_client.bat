@echo off
setlocal
cd /d "%~dp0\.."

call build\build_client.bat
if errorlevel 1 goto :fail

if exist release\GOLD_AI_Client_V01 rmdir /s /q release\GOLD_AI_Client_V01
mkdir release\GOLD_AI_Client_V01

copy /Y dist\GOLD_AI_Client.exe release\GOLD_AI_Client_V01\GOLD_AI_Client.exe >nul
copy /Y CUSTOMER_README.txt release\GOLD_AI_Client_V01\README.txt >nul

powershell -NoProfile -Command "Compress-Archive -Path 'release\GOLD_AI_Client_V01\*' -DestinationPath 'release\GOLD_AI_Client_V01.zip' -Force"
if errorlevel 1 goto :fail

echo.
echo READY TO SEND:
echo %CD%\release\GOLD_AI_Client_V01.zip
pause
exit /b 0

:fail
echo.
echo PACKAGE FAILED.
pause
exit /b 1
