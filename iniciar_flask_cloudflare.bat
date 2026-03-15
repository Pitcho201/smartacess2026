@echo off
title Servidor Flask + Cloudflare Tunnel

REM *******************************************************************
REM ** CONFIGURAÇÕES **
REM *******************************************************************
REM O Cloudflared.exe deve estar na mesma pasta deste script (SMARTACESS)
set CLOUDFLARED_PATH=cloudflared.exe
set FLASK_PORT=5000
set VENV_PATH=venv39\Scripts\activate

echo.
echo ===========================================
echo 🚀 Iniciando Servidor Flask...
echo ===========================================
echo.

REM Abrir Flask em uma janela separada e ATIVAR o ambiente virtual
REM O '/d' garante que a ativação funcione corretamente, mudando para a pasta raiz.
start "Flask Server" cmd /k "cd /d "%~dp0" && %VENV_PATH% && python app.py"

REM Aguardar 5 segundos para garantir que o Flask iniciou
timeout /t 5 /nobreak >nul

echo.
echo ===========================================
echo 🌐 Iniciando Cloudflare Tunnel (Acesso Rápido)...
echo ===========================================
echo.

REM Iniciar cloudflared a partir da pasta raiz do projeto
start "Cloudflare Tunnel" cmd /k "cd /d "%~dp0" && %CLOUDFLARED_PATH% tunnel --url http://localhost:%FLASK_PORT%"

echo.
echo Servidor Flask e Cloudflare Tunnel iniciados.
echo Verifique as novas janelas do CMD para os detalhes de acesso (URL).
echo Pressione qualquer tecla para fechar esta janela inicial.
pause >nul