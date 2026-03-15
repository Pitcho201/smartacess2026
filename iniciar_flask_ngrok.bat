@echo off
title Servidor Flask + ngrok

REM Caminho completo para o ngrok.exe (altere se necessário)
set NGROK_PATH=C:\Users\JP\Desktop\projectos\controle_entrada\Serv\ngrok.exe

REM Abrir Flask em uma janela separada
start cmd /k "venv39\Scripts\activate && python app.py"

REM Aguardar 3 segundos para garantir que o Flask iniciou
timeout /t 3 /nobreak >nul

REM Iniciar ngrok apontando para a porta 5000
start cmd /k "%NGROK_PATH% http 5000"
