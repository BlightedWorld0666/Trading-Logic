# Run locally to opt into user sign-in startup. Host policy may require additional permissions.
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonExe = (& py -3 -c "import sys; print(sys.executable)").Trim()
$managerFile = Join-Path $projectRoot 'server_manager.py'
$taskAction = New-ScheduledTaskAction -Execute $pythonExe -Argument ('"' + $managerFile + '"') -WorkingDirectory $projectRoot
$taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$taskSettings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'BlightedWorld-TradingManager' -Action $taskAction -Trigger $taskTrigger -Settings $taskSettings -Description 'Paper trading service manager; restart retains safety stop.' | Out-Null
Write-Host 'Installed sign-in startup. This does not run before Windows sign-in.'
