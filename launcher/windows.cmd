@echo off
rem Dvoklik na Windows-u: pokreni skriveni lokalni SSH meni.
cd /d "%~dp0.."
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw -3 "%~dp0..\prototip\server.py"
  exit /b
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "%~dp0..\prototip\server.py"
  exit /b
)
echo Potreban je Python 3 sa pyw.exe ili pythonw.exe. Instaliraj Python sa python.org i ponovo pokreni SSH UI - Windows.vbs.
exit /b 1
