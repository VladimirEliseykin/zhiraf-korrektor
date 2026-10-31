@echo off
rem End-to-end job: the built folder in a Windows 7 VM. ASCII only: cmd runs in the OEM codepage.
rem %1 = drive letter of this CD (e.g. E:). The Cyrillic target folder is created by Python, not by cmd.
set P=%1
set R=
for %%d in (D E F G H I J K) do (
  vol %%d: 2>nul | find "RESULTS" >nul && set R=%%d:
)
if "%R%"=="" exit /b 1
set LOG=%R%\log7.txt
echo === job %DATE% %TIME% === > %LOG%
type %P%\job\id.txt >> %LOG%
%P%\dist\python\python.exe %P%\job\win_check.py driver %R% %P%\dist %P%\job >> %LOG% 2>&1
echo exit=%ERRORLEVEL% %TIME% >> %LOG%
echo === done %TIME% === >> %LOG%
