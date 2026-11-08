$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $projectRoot 'deploy')
if (-not (Test-Path -LiteralPath '.env')) { throw 'Run scripts/init_deploy_config.py first.' }
& docker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0) { throw 'Docker engine unavailable; inspect Docker Desktop Linux engine and current account permissions.' }
& docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Invalid compose configuration.' }
& docker compose up -d
if ($LASTEXITCODE -ne 0) { throw 'Milvus startup failed; run docker compose logs --tail 100.' }
& docker compose ps
