# Invoked by the installed edition only after the owner-issued lease expires.
# Never removes MT5, saved client profiles, execution logs, or broker records.
param(
    [Parameter(Mandatory=$true)][string]$Uninstaller,
    [Parameter(Mandatory=$true)][string]$ClientExecutable
)
$ErrorActionPreference = 'Stop'
Start-Sleep -Seconds 7   # Allow the PyInstaller guard to finish and release its own EXE.
if (-not (Test-Path -LiteralPath $Uninstaller -PathType Leaf)) { exit 0 }
# Do not forcibly kill a trading UI/worker. Server has already denied fresh entries.
# Retry at the next scheduled check after the user has closed the app.
$active = Get-CimInstance Win32_Process -Filter "Name='AZT_Friends_Trial.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -eq $ClientExecutable }
if ($active) { exit 0 }
$process = Start-Process -FilePath $Uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait -PassThru -WindowStyle Hidden
exit $process.ExitCode
