$ErrorActionPreference = "Stop"

foreach ($port in 2000, 3307) {
    $processIds = netstat -ano | Select-String ":$port\s+.*LISTENING" | ForEach-Object {
        [int](($_ -split "\s+")[-1])
    } | Sort-Object -Unique
    foreach ($processId in $processIds) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        Write-Output "Stopped process $processId on port $port"
    }
}

if (Test-Path "L:\") {
    & subst L: /D
}
