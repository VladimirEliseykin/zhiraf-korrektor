@echo off
rem Runs X:\job\run.cmd once per new X:\job\id.txt on any attached drive.
:loop
for %%d in (D E F G H I J K) do (
  if exist %%d:\job\run.cmd (
    fc /b %%d:\job\id.txt C:\lastjob.txt >nul 2>&1 || (
      copy /y %%d:\job\id.txt C:\lastjob.txt >nul
      call %%d:\job\run.cmd %%d:
    )
  )
)
timeout /t 10 /nobreak >nul
goto loop
