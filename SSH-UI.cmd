@echo off
rem Dvoklik na Windows-u: pokreni lokalni SSH meni i otvori ga u pregledaču.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0prototip\server.py"
  goto end
)
where python >nul 2>nul
if %errorlevel%==0 (
  python "%~dp0prototip\server.py"
  goto end
)
echo Potreban je Python 3. Instaliraj ga sa python.org i ponovo pokreni SSH-UI.cmd.
pause
:end
