; Inno Setup script for the Loopstation installer (Inno Setup 6.3 or newer).
;
;   iscc /DAppVersion=1.1.1 packaging\windows\loopstation.iss
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
#include "rubberband.inc"

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
; Off by default: Rubber Band is GPL software and is not shipped. Ticking this downloads it
; (see rubberband.inc and the consent page below). Without it the app runs with the simple stretch.
Name: "rubberband"; Description: "Rubber Band (GPL) herunterladen (optional, bessere Qualität beim Strecken)"; GroupDescription: "Optionale Komponente:"; Flags: unchecked

[InstallDelete]
; Remove files of the previous version so no stale library is left behind.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#Root}\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[UninstallDelete]
Type: filesandordirs; Name: "{app}\rubberband"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  RubberBandPage: TOutputMsgWizardPage;

procedure InitializeWizard;
begin
  // The consent text: what is downloaded, under which license, from where, how big.
  RubberBandPage := CreateOutputMsgPage(wpSelectTasks, 'Rubber Band (GPL)',
    'Optionaler Download, nur mit Ihrer Zustimmung',
    'Sie haben ausgewählt, Rubber Band herunterzuladen. Bitte lesen:' + #13#10 + #13#10 +
    'Name: Rubber Band (Python-Anbindung pylibrb {#RubberBandVersion}, Bibliothek eingebaut)' + #13#10 +
    'Lizenz: GNU General Public License (GPL). Die Loopstation liefert Rubber Band nicht mit; ' +
    'es wird auf Ihren Wunsch auf diesen Rechner geladen. Die Pflichten der GPL (etwa bei einer ' +
    'Weitergabe) liegen dann bei Ihnen.' + #13#10 +
    'Herkunft: {#RubberBandUrl}' + #13#10 +
    'Größe: ca. {#RubberBandSize}' + #13#10 +
    'Prüfsumme (SHA-256): {#RubberBandSha256}' + #13#10 + #13#10 +
    'Der Download wird gegen die Prüfsumme geprüft. Schlägt er fehl, wird die Loopstation trotzdem ' +
    'installiert und nutzt den einfachen Stretch. Wer nicht zustimmt, geht zurück und nimmt den ' +
    'Haken bei "Rubber Band (GPL) herunterladen" heraus.');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = RubberBandPage.ID) and not WizardIsTaskSelected('rubberband');
end;

// Downloads the wheel, checks its SHA-256 (DownloadTemporaryFile raises on any failure or
// mismatch) and unpacks it to {app}\rubberband. Returns false on any problem; never raises.
function InstallRubberBand: Boolean;
var
  Target, Zip, Args: String;
  Code: Integer;
begin
  Result := False;
  Target := ExpandConstant('{app}\rubberband');
  try
    DelTree(Target, True, True, True);
    DownloadTemporaryFile('{#RubberBandUrl}', 'pylibrb.zip', '{#RubberBandSha256}', nil);
    Zip := ExpandConstant('{tmp}\pylibrb.zip');
    // Entry by entry instead of Expand-Archive: Windows PowerShell 5.1 does not reliably map the
    // forward-slash paths of a wheel onto folders. Creates the folders itself.
    Args := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' +
      'Add-Type -AssemblyName System.IO.Compression.FileSystem; ' +
      '$z = [IO.Compression.ZipFile]::OpenRead(''' + Zip + '''); ' +
      'try { foreach ($e in $z.Entries) { if ($e.Name) { ' +
      '$p = Join-Path ''' + Target + ''' ($e.FullName -replace ''/'', ''\''); ' +
      'New-Item -ItemType Directory -Force (Split-Path $p) | Out-Null; ' +
      '[IO.Compression.ZipFileExtensions]::ExtractToFile($e, $p, $true) } } } finally { $z.Dispose() }"';
    if Exec('powershell.exe', Args, '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0) then
    begin
      Result := FileExists(Target + '\pylibrb\__init__.py');
      if not Result then
        Log('Rubber Band download failed: pylibrb\__init__.py missing after unpacking to ' + Target);
    end
    else
      Log('Rubber Band download failed: unpacking exit code ' + IntToStr(Code));
  except
    Log('Rubber Band download failed: ' + GetExceptionMessage);
  end;
  if not Result then
    DelTree(Target, True, True, True);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('rubberband') then
    if not InstallRubberBand then
      SuppressibleMsgBox('Rubber Band konnte nicht geladen oder geprüft werden. ' +
        'Rubber Band nicht installiert, einfache Engine aktiv. Die Loopstation ist ' +
        'installiert und läuft normal. Zum Nachholen den Installer erneut ausführen und den Haken setzen.',
        mbInformation, MB_OK, IDOK);
end;
