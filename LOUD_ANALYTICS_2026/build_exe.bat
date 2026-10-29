@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo ERRO: Python do ambiente virtual nao encontrado.
  echo Execute: py -3.13 -m venv .venv
  echo Execute: .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)
"%PYTHON%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
  echo PyInstaller nao instalado.
  echo Execute: .venv\Scripts\python.exe -m pip install pyinstaller
  pause
  exit /b 1
)
"%PYTHON%" -m PyInstaller --noconfirm --clean --onedir --windowed --collect-all vlrdevapi --name LOUD_Analytics_2026 app.py
if errorlevel 1 (
  echo ERRO: falha ao gerar o executavel. Verifique a mensagem acima.
  pause
  exit /b 1
)
if exist "loud_2026.sqlite3" (
  copy /Y "loud_2026.sqlite3" "dist\LOUD_Analytics_2026\loud_2026.sqlite3" >nul
  echo Banco local copiado para a pasta do executavel.
) else (
  echo ATENCAO: nao existe banco local para copiar.
  echo Ao abrir, o aplicativo precisara consultar a internet.
)
echo.
echo PRONTO. Abra: dist\LOUD_Analytics_2026\LOUD_Analytics_2026.exe
echo Copie a pasta inteira LOUD_Analytics_2026 para a faculdade.
pause
