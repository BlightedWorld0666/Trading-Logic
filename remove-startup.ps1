$ErrorActionPreference = 'Stop'
Unregister-ScheduledTask -TaskName 'BlightedWorld-TradingManager' -Confirm:$false
Write-Host 'Removed sign-in startup task. Running services are unchanged.'
