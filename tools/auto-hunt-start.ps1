param(
    [string]$PythonPath = "C:\Users\k1j1s\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
    [string[]]$Devices = @("emulator-5556")
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$data = Join-Path $root "data\auto-hunt"
$pidFile = Join-Path $data "pids.json"
New-Item -ItemType Directory -Force -Path $data | Out-Null

# Some hosts expose both Path and PATH in the process environment. Windows
# PowerShell Start-Process rejects that duplicate. Normalize it inside this
# short-lived launcher process before spawning monitors.
Remove-Item Env:Path -ErrorAction SilentlyContinue
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine")

if (Test-Path -LiteralPath $pidFile) {
    $old = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
    $running = @($old | Where-Object { Get-Process -Id $_.pid -ErrorAction SilentlyContinue })
    if ($running.Count -gt 0) {
        throw "Auto-hunt monitor is already running. Run tools\auto-hunt-stop.ps1 first."
    }
}

$rows = @()
foreach ($device in $Devices) {
    $safeName = $device.Replace(":", "-")
    $logFile = Join-Path $data "$safeName.log"
    $arguments = "tools\ldplayer_auto_hunt.py --device $device --log-file `"$logFile`""
    $process = Start-Process `
        -FilePath $PythonPath `
        -ArgumentList $arguments `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -PassThru
    $rows += [pscustomobject]@{ device = $device; pid = $process.Id }
}

$rows | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8
$rows | Format-Table -AutoSize
Write-Output "Auto-hunt monitors started. Global and per-device action settings apply."
