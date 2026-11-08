$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
Set-Location $projectRoot
$moduleRunner = Join-Path $projectRoot 'scripts\run_module.py'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& $pythonExe $moduleRunner pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
$taskTestTemp = Join-Path $projectRoot ('.local\pytest-check-' + [guid]::NewGuid().ToString('N'))
& $pythonExe $moduleRunner pytest -p pytest_asyncio.plugin -p no:cacheprovider --basetemp $taskTestTemp -c backend/pytest.ini backend/tests -q --junitxml=docs/evidence/final-pytest.xml
if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
& $pythonExe $moduleRunner (Join-Path $projectRoot 'scripts\verify_mysql.py') | Tee-Object -FilePath docs/evidence/final-foundation-mysql.json
if ($LASTEXITCODE -ne 0) { throw 'Real MySQL verification failed.' }
& $pythonExe $moduleRunner (Join-Path $projectRoot 'scripts\verify_stage2_mysql.py') | Tee-Object -FilePath docs/evidence/final-stage2-mysql.json
if ($LASTEXITCODE -ne 0) { throw 'Stage 2 MySQL verification failed.' }
& $pythonExe $moduleRunner (Join-Path $projectRoot 'scripts\verify_stage3_mysql.py')
if ($LASTEXITCODE -ne 0) { throw 'Stage 3 HTTP/MySQL verification failed.' }
& $pythonExe $moduleRunner (Join-Path $projectRoot 'scripts\verify_stage4_mysql.py')
if ($LASTEXITCODE -ne 0) { throw 'Stage 4 HTTP/MySQL verification failed.' }
& $pythonExe $moduleRunner (Join-Path $projectRoot 'scripts\verify_delivery_mysql.py')
if ($LASTEXITCODE -ne 0) { throw 'Final HTTP/MySQL verification failed.' }
Set-Location (Join-Path $projectRoot 'frontend')
& node (Join-Path $projectRoot '.tools\package\bin\npm-cli.js') run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
$env:PLAYWRIGHT_JSON_OUTPUT_NAME = '../docs/evidence/final-playwright-results.json'
& node '.\node_modules\@playwright\test\cli.js' test --reporter=list,json
if ($LASTEXITCODE -ne 0) { throw 'Browser tests failed. Ensure backend and frontend preview are running.' }
