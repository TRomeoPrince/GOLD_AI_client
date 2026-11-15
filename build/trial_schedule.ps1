# Registers a visible current-user task; no administrator account or hidden service.
param(
    [Parameter(Mandatory=$true)][string]$Executable
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "Friends trial executable is missing."
}
$taskName = 'AZT Friends Trial Expiry'
$action = New-ScheduledTaskAction -Execute $Executable -Argument '--trial-guard'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
