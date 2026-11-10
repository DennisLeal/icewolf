#ifndef LegacyDir
  #error LegacyDir must be supplied by the build script.
#endif

[Setup]
AppId={{BA0C846D-53A8-4E99-96E2-B90E942D33E8}
AppName=Icewolf
AppVersion=0.2.0
AppPublisher=Icewolf
DefaultDirName={localappdata}\Programs\Icewolf
DefaultGroupName=Icewolf
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Icewolf-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Icewolf.exe
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "migrate"; Description: "Copy existing project settings and agent materials if not already present"; Flags: checkedonce

[Files]
Source: "..\dist\Icewolf\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\models\kokoro\kokoro-v1.0.onnx"; DestDir: "{localappdata}\Icewolf\UserData\models\kokoro"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "..\models\kokoro\voices-v1.0.bin"; DestDir: "{localappdata}\Icewolf\UserData\models\kokoro"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\Icewolf"; Filename: "{app}\Icewolf.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Icewolf"; Filename: "{app}\Icewolf.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if WizardIsTaskSelected('migrate') and
     (FileExists('{#LegacyDir}\data\agents.sqlite3-wal') or
      FileExists('{#LegacyDir}\data\agents.sqlite3-journal')) then
    Result := 'The existing agent database may be in use. Close Icewolf and try again.';
end;

procedure CopyIfAbsent(const Source, Destination: String);
begin
  if FileExists(Source) and not FileExists(Destination) then
  begin
    if not ForceDirectories(ExtractFileDir(Destination)) then
      RaiseException('Could not create the Icewolf data directory: ' + ExtractFileDir(Destination));
    if not FileCopy(Source, Destination, True) then
      RaiseException('Could not copy existing Icewolf data: ' + Source);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  UserData: String;
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('migrate') then
  begin
    UserData := ExpandConstant('{localappdata}\Icewolf\UserData');
    CopyIfAbsent('{#LegacyDir}\icewolf-settings.ini', UserData + '\icewolf-settings.ini');
    CopyIfAbsent('{#LegacyDir}\data\agents.sqlite3', UserData + '\data\agents.sqlite3');
  end;
end;
