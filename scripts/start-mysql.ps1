$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $projectRoot '.local\mysql.ini'
if (-not (Test-Path -LiteralPath $configPath)) { throw 'Run scripts/init_mysql.py first.' }
$connection = New-Object Net.Sockets.TcpClient
try { $connection.Connect('127.0.0.1',3307); Write-Output 'Port 3307 is already active; no second process started.'; exit } catch {} finally { $connection.Dispose() }
$pidPath = Join-Path $projectRoot '.local\mysql.pid'
if (Test-Path -LiteralPath $pidPath) {
    $previousPid = [int](Get-Content -LiteralPath $pidPath)
    $previous = Get-Process -Id $previousPid -ErrorAction SilentlyContinue
    if ($previous -and $previous.ProcessName -eq 'mysqld') {
        Wait-Process -Id $previousPid -Timeout 30 -ErrorAction Stop
    }
}
$mysqlBin = Split-Path -Parent (Get-Command mysql.exe).Source
$instance = Start-Process -FilePath (Join-Path $mysqlBin 'mysqld.exe') -ArgumentList @("--defaults-file=$configPath") -WindowStyle Hidden -PassThru
$instance.Id | Set-Content -LiteralPath (Join-Path $projectRoot '.local\mysql.pid')
for ($attempt=0; $attempt -lt 60; $attempt++) {
    $instance.Refresh()
    if ($instance.HasExited) { throw 'MySQL exited during startup; inspect .local/mysql-error.log.' }
    $probe = New-Object Net.Sockets.TcpClient
    try { $probe.Connect('127.0.0.1',3307); Write-Output 'Project MySQL ready on 127.0.0.1:3307.'; exit } catch {} finally { $probe.Dispose() }
    Start-Sleep -Milliseconds 500
}
throw 'MySQL did not become ready within 30 seconds.'
