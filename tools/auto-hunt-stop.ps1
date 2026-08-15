$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root "data\auto-hunt\pids.json"

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Output "Auto-hunt monitor is not registered as running."
    exit 0
}

$rows = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
foreach ($row in @($rows)) {
    $process = Get-Process -Id $row.pid -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $row.pid
        Write-Output "Stopped $($row.device) PID=$($row.pid)"
    }
}
Remove-Item -LiteralPath $pidFile

