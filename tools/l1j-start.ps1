param(
    [string]$DbPassword = "l1jlocal",
    [string]$PasswordSalt = "lineage-local"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$drive = "L:"
if (-not (Test-Path "$drive\")) {
    & subst $drive $root
}
$source = "$drive\l1j-classic"
$runtime = "$drive\l1j-runtime"
$maria = "$drive\local-tools\mariadb-10.11.14-winx64"

if (-not (Test-Path (Join-Path $source "l1jen.jar"))) {
    throw "l1jen.jar is missing. Run the documented build step first."
}
if (-not (Test-Path (Join-Path $maria "bin\mariadbd.exe"))) {
    throw "Portable MariaDB is missing. Run the setup instructions first."
}

$dbListener = netstat -ano | Select-String ":3307\s+.*LISTENING"
if (-not $dbListener) {
    $data = Join-Path $runtime "mariadb-data"
    $dbLog = Join-Path $runtime "mariadb.log"
    $dbError = Join-Path $runtime "mariadb.err.log"
    Start-Process -FilePath (Join-Path $maria "bin\mariadbd.exe") `
        -ArgumentList "--no-defaults", "--basedir=$maria", "--datadir=$data", `
            "--port=3307", "--bind-address=127.0.0.1" `
        -RedirectStandardOutput $dbLog -RedirectStandardError $dbError `
        -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 5
}

$gameListener = netstat -ano | Select-String ":2000\s+.*LISTENING"
if (-not $gameListener) {
    $env:DB_URL = "jdbc:mysql://127.0.0.1:3307/l1jdb?autoReconnect=true&useUnicode=True&characterEncoding=UTF-8"
    $env:DB_USER = "l1j"
    $env:DB_PASSWORD = $DbPassword
    $env:PASSWORD_SALT = $PasswordSalt
    Start-Process -FilePath "java" -ArgumentList "-Xmx1024m", "-cp", "l1jen.jar;lib\*", "l1j.server.Server" `
        -WorkingDirectory $source -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 8
}

& (Join-Path $PSScriptRoot "l1j-status.ps1")
