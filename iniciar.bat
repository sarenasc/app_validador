@echo off
REM Inicia el Validador de Etiquetas accesible desde celulares/tablets de la red (puerto 8520)
cd /d "%~dp0"
python servidor.py --red
pause
