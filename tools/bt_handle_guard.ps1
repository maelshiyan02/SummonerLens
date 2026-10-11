<#
  bt_handle_guard.ps1
  --------------------------------------------------------------------------
  Guard against the MediaTek Bluetooth Service (MTKBTSVC / mtkbtsvc.exe)
  handle leak.

  Confirmed symptom (measured on ASUS B760M-AYW WIFI + MT7902 combo card):
    - mtkbtsvc.exe leaks ~1343 Event kernel objects at ~10 min uptime
    - growth ~83 handles/min idle (~5,000/h, ~120,000/day), unbounded
    - system-wide handle pool exhaustion -> any new pipe/process creation
      starts failing (ERROR_PIPE_BUSY / CreateFile failed 231)

  Root cause is inside the vendor user-mode service; the installed driver
  package (1.1044.0.556) is already the newest published by ASUS, so
  "update the driver" does NOT fix it. This script provides the practical
  options instead.

  ACTIONS
    status   : print state, handle count and measured growth rate (safe)
    watch    : foreground watchdog; restarts the service whenever handles
               exceed -Threshold (keeps Bluetooth, bounds the leak)
    restart  : restart the service once (frees leaked handles now)
    disable  : stop + disable the service entirely (test BT after)
    enable   : re-enable the service (undo 'disable')

  NOTE: watch/restart/disable/enable need an elevated (Administrator) shell.
        status works unelevated.

  EXAMPLES
    powershell -ExecutionPolicy Bypass -File tools\bt_handle_guard.ps1 -Action status
    powershell -ExecutionPolicy Bypass -File tools\bt_handle_guard.ps1 -Action watch -Threshold 20000
    powershell -ExecutionPolicy Bypass -File tools\bt_handle_guard.ps1 -Action disable
#>
param(
  [ValidateSet('status', 'watch', 'restart', 'disable', 'enable')]
  [string]$Action = 'status',

  [int]$Threshold = 20000,      # watch: restart when handles exceed this
  [int]$IntervalSec = 300,      # watch: poll interval
  [int]$SampleSec = 30,         # status: growth-rate sample window
  [int]$MaxRounds = 0           # watch: 0 = forever, else stop after N polls
)

$ErrorActionPreference = 'Stop'
$SvcName = 'MTKBTSVC'
$ProcName = 'mtkbtsvc'

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root 'build'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir 'bt_guard.log'

function Write-Log {
  param([string]$Message)
  $line = '{0}  {1}' -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $Message
  Write-Output $line
  try {
    # keep the log bounded (rotate at 512 KB) so scheduled runs do not grow it forever
    if ((Test-Path -LiteralPath $LogFile) -and ((Get-Item -LiteralPath $LogFile).Length -gt 524288)) {
      Move-Item -LiteralPath $LogFile -Destination ($LogFile + '.1') -Force
    }
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
  } catch { }
}

function Test-Admin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $pr = New-Object Security.Principal.WindowsPrincipal($id)
  return $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-SvcProcess {
  return (Get-Process -Name $ProcName -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Get-SvcState {
  $s = Get-Service -Name $SvcName -ErrorAction SilentlyContinue
  if (-not $s) { return 'Missing' }
  return [string]$s.Status
}

function Show-Status {
  $svc = Get-Service -Name $SvcName -ErrorAction SilentlyContinue
  if (-not $svc) { Write-Log "service '$SvcName' not found"; return }
  $p = Get-SvcProcess
  Write-Log ("service='{0}' state={1} startType={2}" -f $SvcName, $svc.Status, (Get-CimInstance Win32_Service -Filter "Name='$SvcName'").StartMode)
  if (-not $p) { Write-Log 'mtkbtsvc.exe not running'; return }
  $upMin = [math]::Round(((Get-Date) - $p.StartTime).TotalMinutes, 1)
  Write-Log ("pid={0}  handles={1}  uptime={2} min" -f $p.Id, $p.Handles, $upMin)

  if ($SampleSec -gt 0) {
    $h0 = $p.Handles
    Start-Sleep -Seconds $SampleSec
    $p2 = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
    if (-not $p2) { Write-Log 'process exited during sampling'; return }
    $d = $p2.Handles - $h0
    $perMin = [math]::Round($d * 60.0 / $SampleSec, 1)
    Write-Log ("sample {0}s: {1} -> {2}  delta={3}  (~{4}/min, ~{5}/h)" -f $SampleSec, $h0, $p2.Handles, $d, $perMin, [math]::Round($perMin * 60, 0))
    if ($d -le 0) { Write-Log 'no growth detected in window (leak may be load-triggered)' }
  }
}

function Restart-SvcOnce {
  if (-not (Test-Admin)) { Write-Log 'ERROR: need Administrator to restart the service'; return $false }
  $p = Get-SvcProcess
  $before = if ($p) { $p.Handles } else { -1 }
  Restart-Service -Name $SvcName -Force
  Start-Sleep -Seconds 3
  $q = Get-SvcProcess
  $after = if ($q) { $q.Handles } else { -1 }
  Write-Log ("restarted '{0}': handles {1} -> {2}" -f $SvcName, $before, $after)
  return $true
}

function Watch-Loop {
  if (-not (Test-Admin)) { Write-Log 'ERROR: need Administrator for watch mode'; return }
  Write-Log ("watch started: threshold={0} interval={1}s maxRounds={2}" -f $Threshold, $IntervalSec, $MaxRounds)
  $round = 0
  while ($true) {
    $round++
    $p = Get-SvcProcess
    if (-not $p) {
      Write-Log 'mtkbtsvc.exe not running; nothing to guard'
    }
    else {
      Write-Log ("poll #{0}: handles={1}" -f $round, $p.Handles)
      if ($p.Handles -ge $Threshold) {
        Write-Log ("threshold {0} reached (handles={1}) -> restarting" -f $Threshold, $p.Handles)
        Restart-SvcOnce | Out-Null
      }
    }
    if ($MaxRounds -gt 0 -and $round -ge $MaxRounds) { Write-Log 'watch reached MaxRounds, exiting'; break }
    Start-Sleep -Seconds $IntervalSec
  }
}

function Disable-Svc {
  if (-not (Test-Admin)) { Write-Log 'ERROR: need Administrator to disable the service'; return }
  try { Stop-Service -Name $SvcName -Force -ErrorAction SilentlyContinue } catch { }
  Set-Service -Name $SvcName -StartupType Disabled
  Start-Sleep -Seconds 2
  Write-Log ("'{0}' stopped and set to Disabled. Test Bluetooth mouse/headset now." -f $SvcName)
  Write-Log 'If Bluetooth still works, the leak is gone for good. To undo: -Action enable'
}

function Enable-Svc {
  if (-not (Test-Admin)) { Write-Log 'ERROR: need Administrator to enable the service'; return }
  Set-Service -Name $SvcName -StartupType Automatic
  Start-Service -Name $SvcName
  Start-Sleep -Seconds 2
  Write-Log ("'{0}' set to Automatic and started." -f $SvcName)
}

switch ($Action) {
  'status' { Show-Status }
  'watch' { Watch-Loop }
  'restart' { Restart-SvcOnce | Out-Null }
  'disable' { Disable-Svc }
  'enable' { Enable-Svc }
}
