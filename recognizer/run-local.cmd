@echo off
rem Local recognizer for development on Windows (GPU through DirectML).
rem The service token must match ARGUS_SERVICE_TOKEN in backend\.env.
cd /d "%~dp0"
set ARGUS_BACKEND_URL=http://127.0.0.1:8000
set ARGUS_SERVICE_TOKEN=dev-token
.venv\Scripts\uvicorn argus_recognizer.main:app --host 127.0.0.1 --port 8100
