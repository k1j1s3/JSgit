$ErrorActionPreference = "Stop"

$listening = netstat -ano | Select-String "LISTENING"
$game = $listening | Select-String ":2000\s"
$database = $listening | Select-String ":3307\s"

Write-Output ("L1J game server : " + $(if ($game) { "RUNNING (port 2000)" } else { "STOPPED" }))
Write-Output ("MariaDB        : " + $(if ($database) { "RUNNING (port 3307)" } else { "STOPPED" }))
