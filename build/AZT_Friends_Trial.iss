#define MyAppName "AGORA ZION TRADER - Friends Trial"
#define MyAppExeName "AZT_Friends_Trial.exe"

[Setup]
AppId={{5B07FB6D-5A61-4E73-B36B-7A14FCEFC5A3}
AppName={#MyAppName}
AppVersion=1.0.0
AppPublisher=Agora Zion
DefaultDirName={localappdata}\Programs\AZT Friends Trial
DefaultGroupName=AZT Friends Trial
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\dist
OutputBaseFilename=AZT_Friends_Trial_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "trial_schedule.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "trial_auto_uninstall.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\AZT Friends Trial"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\AZT Friends Trial"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch AZT Friends Trial"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /F /TN ""AZT Friends Trial Expiry"""; Flags: runhidden; RunOnceId: "RemoveFriendsTrialScheduler"

[Code]
procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption :=
    'This is a 14-day evaluation of AGORA ZION TRADER. The clock begins on your first successful MT5 account pairing.' + #13#10 + #13#10 +
    'The AZT server blocks new automated entries after expiry. This installer creates a disclosed Windows expiry-check task after activation, which automatically uninstalls this trial edition after expiry.' + #13#10 + #13#10 +
    'MetaTrader 5, broker-side orders and your saved trading history are not uninstalled. You may remove the trial earlier from Windows Settings.';
end;
