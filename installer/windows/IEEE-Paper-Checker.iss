; Inno Setup script -> dist\IEEE-Paper-Checker-Setup-<version>.exe
; Build with:  build_windows.bat   (or: ISCC.exe /DAppVersion=1.0.0 IEEE-Paper-Checker.iss)

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "IEEE Paper Format Checker"
#define AppExe "IEEE-Paper-Checker.exe"

[Setup]
AppId={{6E0B9F4C-2D7A-4B51-9C3E-1A8F5D2E7B40}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=IEEE Paper Format Checker
DefaultDirName={autopf}\IEEE Paper Checker
DefaultGroupName=IEEE Paper Checker
DisableProgramGroupPage=yes
; Installs for the current user without admin rights; users can choose "all users".
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist
OutputBaseFilename=IEEE-Paper-Checker-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
ChangesEnvironment=yes
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "contextmenu"; Description: "Add ""Check IEEE format"" to the right-click menu of PDF files"; GroupDescription: "Integration:"
Name: "addtopath"; Description: "Add the command-line tool (ieee-check) to PATH"; GroupDescription: "Integration:"; Flags: unchecked

[Files]
Source: "..\..\dist\IEEE-Paper-Checker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Right-click on any PDF -> "Check IEEE format" (works whatever the default PDF viewer is)
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\IEEECheck"; ValueType: string; ValueName: ""; ValueData: "Check IEEE format"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\IEEECheck"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"",0"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\IEEECheck\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: contextmenu
; Shows the app in "Open with" for PDFs
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""
; PATH entry for ieee-check.exe
Root: HKA; Subkey: "{code:EnvKey}"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}')); Tasks: addtopath

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent

[Code]
function EnvRoot: Integer;
begin
  if IsAdminInstallMode then Result := HKEY_LOCAL_MACHINE else Result := HKEY_CURRENT_USER;
end;

function EnvKey(Param: String): String;
begin
  if IsAdminInstallMode then
    Result := 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
  else
    Result := 'Environment';
end;

function NeedsAddPath(Dir: String): Boolean;
var
  OrigPath: String;
begin
  if not RegQueryStringValue(EnvRoot, EnvKey(''), 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Dir) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;

procedure RemoveFromPath(Dir: String);
var
  P: String;
  i: Integer;
begin
  if not RegQueryStringValue(EnvRoot, EnvKey(''), 'Path', P) then exit;
  i := Pos(';' + Uppercase(Dir), Uppercase(P));
  if i > 0 then
  begin
    Delete(P, i, Length(Dir) + 1);
    RegWriteExpandStringValue(EnvRoot, EnvKey(''), 'Path', P);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveFromPath(ExpandConstant('{app}'));
end;
