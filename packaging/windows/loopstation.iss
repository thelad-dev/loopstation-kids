; Inno Setup script for the Loopstation installer (Inno Setup 6.3 or newer).
;
;   iscc /DAppVersion=1.0.0 packaging\windows\loopstation.iss
;
; Expects the PyInstaller output in dist\Loopstation and the icon in
; build\loopstation.ico (both relative to the repository root).
; Result: dist\Loopstation-Setup-<version>.exe
;
; Settings, recordings and the event log live in %LOCALAPPDATA%\Loopstation
; (see loopstation/installed.py). This installer never touches that folder,
; so recordings survive updates and uninstalling.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Loopstation"
#define AppExe "Loopstation.exe"
#define Root AddBackslash(SourcePath) + "..\.."

[Setup]
; Fixed AppId: a newer setup updates the existing installation in place.
AppId={{3555A137-A4D8-4624-9E8D-0A896949B211}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=thelad-dev
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Installs for the current user without admin rights; the dialog still offers "all users".
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#Root}\dist
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile={#Root}\build\loopstation.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Closes a running Loopstation before files are replaced.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Remove files of the previous version so no stale library is left behind.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#Root}\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
