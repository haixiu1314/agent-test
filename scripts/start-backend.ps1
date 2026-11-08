$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
New-Item -ItemType Directory -Path (Join-Path $projectRoot '.local') -Force | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) { throw 'Run scripts/init_local_config.py and configure .env first.' }
Set-Location (Join-Path $projectRoot 'backend')
& $pythonExe (Join-Path $projectRoot 'scripts\run_module.py') uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --log-config logging.json
