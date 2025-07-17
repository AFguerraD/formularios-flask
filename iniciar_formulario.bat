@echo off
echo Iniciando sistema de Formularios...
cd /d "%~dp0"

REM Crear entorno virtual si no existe
IF NOT EXIST "venv" (
    python -m venv venv
)

REM Activar entorno virtual
call venv\Scripts\activate

REM Instalar Flask si no está
pip install -r requirements.txt > nul 2>&1

REM Ejecutar la app
python app.py
pause
