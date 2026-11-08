$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $projectRoot 'frontend')
if (Get-Command npm.cmd -ErrorAction SilentlyContinue) { & npm.cmd run dev }
else { & node (Join-Path $projectRoot '.tools\package\bin\npm-cli.js') run dev }
