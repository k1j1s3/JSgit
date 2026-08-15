param(
    [string]$Device,
    [datetime]$StartAt,
    [int]$Segments = 2
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$adb = "C:\LDPlayer\LDPlayer9\adb.exe"
$stamp = $StartAt.ToString("yyyyMMdd-HHmmss")
$output = Join-Path $root "data\world-boss-captures\$stamp-$Device"
New-Item -ItemType Directory -Force -Path $output | Out-Null

$delay = ($StartAt - (Get-Date)).TotalSeconds
if ($delay -gt 0) {
    Start-Sleep -Seconds $delay
}

& $adb -s $Device shell screencap -p /sdcard/world-boss-before.png
& $adb -s $Device pull /sdcard/world-boss-before.png (Join-Path $output "before.png") | Out-Null

for ($index = 1; $index -le $Segments; $index++) {
    $remote = "/sdcard/world-boss-$index.mp4"
    $local = Join-Path $output ("segment-{0:D2}.mp4" -f $index)
    & $adb -s $Device shell screenrecord --bit-rate 4000000 --time-limit 180 $remote
    & $adb -s $Device pull $remote $local | Out-Null
    & $adb -s $Device shell rm $remote
}

& $adb -s $Device shell screencap -p /sdcard/world-boss-after.png
& $adb -s $Device pull /sdcard/world-boss-after.png (Join-Path $output "after.png") | Out-Null
"Capture completed $(Get-Date -Format o)" | Set-Content -Encoding UTF8 (Join-Path $output "complete.txt")
