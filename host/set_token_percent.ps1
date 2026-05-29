param(
  [Parameter(Mandatory=$true)]
  [int]$Percent
)

$p = [Math]::Max(0, [Math]::Min(100, $Percent))
Set-Location $PSScriptRoot
py -3 .\codex_light_serial.py send ("TOKEN:{0}" -f $p)
