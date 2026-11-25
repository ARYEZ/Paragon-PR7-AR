; Paragon PR7-AR installer (Inno Setup 6): a startup manager, the way Autoruns shows what starts.
;   iscc /DAppVersion=0.1.0 installer\pr7ar.iss      (after pyinstaller pr7ar.spec has made dist\PR7-AR)
;
; Per-user (no admin rights) into %LOCALAPPDATA%\Programs\PR7-AR, with a Start menu entry. Changing machine-wide entries
; needs administrator rights: PR7-AR's As Admin restarts it elevated (nothing here asks for them).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppId is permanent: it's how a new version finds and upgrades the installed one. Never change it.
AppId={{5DD7DA56-83DC-421E-8D0F-E7FB868B3860}
AppName=Paragon PR7-AR
AppVersion={#AppVersion}
AppVerName=Paragon PR7-AR {#AppVersion}
AppPublisher=Paragon
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\PR7-AR
DefaultGroupName=Paragon PR7-AR
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=PR7-AR-Setup-{#AppVersion}
SetupIconFile=..\pr7ar\icons\app.ico
UninstallDisplayIcon={app}\PR7-AR.exe
UninstallDisplayName=Paragon PR7-AR
WizardStyle=modern
WizardImageFile=wizard-large-1x.bmp,wizard-large-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\PR7-AR\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\NOTICE.md"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Paragon PR7-AR"; Filename: "{app}\PR7-AR.exe"; Comment: "Startup manager"
Name: "{autodesktop}\Paragon PR7-AR"; Filename: "{app}\PR7-AR.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PR7-AR.exe"; Description: "{cm:LaunchProgram,Paragon PR7-AR}"; Flags: nowait postinstall skipifsilent
; Updates (Check for updates runs this installer with /SILENT /relaunch=1): start PR7-AR again when done.
Filename: "{app}\PR7-AR.exe"; Flags: nowait runasoriginaluser; Check: Relaunch

[Code]
// True only when the updater asked for it (/relaunch=1): normal and CI installs behave as before.
function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;
