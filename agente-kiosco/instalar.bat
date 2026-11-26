@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if %ERRORLEVEL%==0 (
  set "PY=python"
) else (
  where py >nul 2>nul
  if %ERRORLEVEL%==0 (
    set "PY=py -3"
  ) else (
    echo Instala Python 3.10+ y vuelve a correr este script.
    exit /b 1
  )
)

echo Creando entorno virtual en .venv ...
%PY% -m venv .venv
if errorlevel 1 exit /b 1

echo Instalando dependencias del lector ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo.
echo Listo. Conecta el lector USB y corre arrancar.bat
exit /b 0
