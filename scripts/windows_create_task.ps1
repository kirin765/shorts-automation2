param(
  [string]$TaskName = "shorts-daily",
  [string]$Time = "09:00",
  [string]$RepoPathWsl = "/home/kwan7/shorts",
  [string]$Distro = ""
)

# Creates a daily Windows Task Scheduler task that runs the WSL pipeline.
# You can run this from PowerShell (non-admin usually works for per-user tasks).

$wsl = "$env:WINDIR\System32\wsl.exe"
if (!(Test-Path $wsl)) { throw "wsl.exe not found: $wsl" }

$distroArg = ""
if ($Distro -ne "") { $distroArg = "-d $Distro" }

# Run the daily pipeline; it will generate topics, draft render jobs, then run the queue.
$bashCmd = "cd $RepoPathWsl && if [ -f .venv/bin/activate ]; then . .venv/bin/activate; fi && python -m shorts pipeline daily --config ENV"
$taskCmd = "`"$wsl`" $distroArg -- bash -lc `"$bashCmd`""

Write-Host "Creating task '$TaskName' at $Time"
Write-Host "Command: $taskCmd"

schtasks.exe /Create /F `
  /SC DAILY `
  /TN $TaskName `
  /TR $taskCmd `
  /ST $Time

Write-Host "Done. Check with: schtasks.exe /Query /TN $TaskName /V /FO LIST"
