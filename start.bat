@echo off
setlocal EnableExtensions

REM Get the folder where this .bat file is located
set "DIR=%~dp0"
set "BACKEND_DIR=%DIR%backend"
set "FRONTEND_DIR=%DIR%frontend"

REM Check folders exist
if not exist "%BACKEND_DIR%" (
    echo Backend folder not found: "%BACKEND_DIR%"
    pause
    exit /b 1
)

if not exist "%FRONTEND_DIR%" (
    echo Frontend folder not found: "%FRONTEND_DIR%"
    pause
    exit /b 1
)

echo Starting CryptoOSINT Backend on http://localhost:8000
echo Starting CryptoOSINT Frontend on http://localhost:5173
echo.
echo Both servers are running. Close this window or press Ctrl+C to stop.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$backendDir = '%BACKEND_DIR%';" ^
  "$frontendDir = '%FRONTEND_DIR%';" ^
  "$backendCmd = if (Test-Path (Join-Path $backendDir 'venv\Scripts\Activate.ps1')) { '. .\venv\Scripts\Activate.ps1; python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload' } elseif (Test-Path (Join-Path $backendDir '.venv\Scripts\Activate.ps1')) { '. .\.venv\Scripts\Activate.ps1; python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload' } else { 'python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload' };" ^
  "$backend = Start-Process powershell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-NoExit','-Command', $backendCmd) -WorkingDirectory $backendDir -PassThru;" ^
  "$frontend = Start-Process powershell -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-NoExit','-Command','npm run dev') -WorkingDirectory $frontendDir -PassThru;" ^
  "try { while (-not $backend.HasExited -and -not $frontend.HasExited) { Start-Sleep -Seconds 1 } } finally { Write-Host ''; Write-Host 'Stopping CryptoOSINT...'; if (-not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }; if (-not $frontend.HasExited) { Stop-Process -Id $frontend.Id -Force } }"

endlocal
