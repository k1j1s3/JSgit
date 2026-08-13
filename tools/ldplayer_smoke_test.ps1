param(
    [string]$AdbPath = "C:\LDPlayer\LDPlayer9\adb.exe",
    [string]$OutputDir = "$PSScriptRoot\..\data\smoke-test"
)

$ErrorActionPreference = "Stop"
$package = "com.tuhota.tuhota"
$activity = "org.cocos2dx.lua.AppActivity"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

& $AdbPath devices -l
& $AdbPath shell am force-stop $package
& $AdbPath shell am start -n "$package/$activity"

# The Cocos title scene is not exposed through Android UIAutomator.
# These coordinates target the verified 1280x720 LDPlayer layout.
Start-Sleep -Seconds 20
& $AdbPath shell input tap 640 300
Start-Sleep -Seconds 30
& $AdbPath shell input tap 1090 662
Start-Sleep -Seconds 30

& $AdbPath shell screencap -p /sdcard/codex-smoke-world.png
& $AdbPath pull /sdcard/codex-smoke-world.png "$OutputDir\world.png"

# Close the initial stats panel and open inventory.
& $AdbPath shell input tap 359 110
Start-Sleep -Seconds 2
& $AdbPath shell input tap 1006 48
Start-Sleep -Seconds 4
& $AdbPath shell screencap -p /sdcard/codex-smoke-inventory.png
& $AdbPath pull /sdcard/codex-smoke-inventory.png "$OutputDir\inventory.png"

Write-Output "Smoke-test screenshots saved to $OutputDir"
