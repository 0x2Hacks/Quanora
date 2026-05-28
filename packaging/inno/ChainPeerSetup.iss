#define MyAppName "ChainPeer"
#define MyAppExeName "chainpeer.exe"
#define MyAppPublisher "ChainPeer"
#define MyAppVersion GetEnv("CHAINPEER_VERSION")
#if MyAppVersion == ""
  #define MyAppVersion "0.1.0"
#endif
#define GitBundleDir "..\..\dist\chainpeer\portable-git"
#define HasGitBundle DirExists(GitBundleDir)

[Setup]
AppId={{6F02B7C9-5B44-4EB9-8B1E-8A6FC894F0D6}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\ChainPeer
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\release
OutputBaseFilename=ChainPeerSetup-{#MyAppVersion}
Compression=lzma2/fast
SolidCompression=no
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\..\dist\chainpeer\chainpeer.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: core
Source: "..\..\dist\chainpeer\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: core
Source: "..\..\dist\chainpeer\templates\*"; DestDir: "{app}\templates"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: core
#if HasGitBundle
Source: "{#GitBundleDir}\*"; DestDir: "{app}\portable-git"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: git
#endif

[Types]
Name: "full"; Description: "Full installation"
Name: "compact"; Description: "Compact installation"
Name: "custom"; Description: "Custom installation"; Flags: iscustom

[Components]
Name: "core"; Description: "ChainPeer CLI"; Types: full compact custom; Flags: fixed
#if HasGitBundle
Name: "git"; Description: "Bundled Git command support (recommended)"; Types: full custom
#endif

[Tasks]
Name: "add_chainpeer_path"; Description: "Add ChainPeer to user PATH"; Flags: checkedonce
#if HasGitBundle
Name: "add_git_path"; Description: "Add bundled git to user PATH"; Components: git; Flags: checkedonce
Name: "add_bash_path"; Description: "Add bundled POSIX shell tools to user PATH"; Components: git; Flags: unchecked
#endif

[Icons]
Name: "{group}\ChainPeer"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall ChainPeer"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{code:AddPaths|{app}}"; Check: AnyPathTaskSelected()

[Code]
const
  WM_SETTINGCHANGE = $001A;

function SendMessageTimeout(hWnd: LongWord; Msg: LongWord; wParam: LongWord; lParam: String;
  fuFlags: LongWord; uTimeout: LongWord; var lpdwResult: LongWord): LongWord;
  external 'SendMessageTimeoutW@user32.dll stdcall';

function CurrentUserPath(): String;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Result) then
    Result := '';
end;

function PathContains(Dir, PathValue: String): Boolean;
var
  Parts: TArrayOfString;
  I: Integer;
  CleanDir: String;
  CleanPart: String;
begin
  Result := False;
  CleanDir := RemoveBackslashUnlessRoot(Dir);
  StringChangeEx(CleanDir, '/', '\', True);
  Parts := StringSplit(PathValue, [';'], stExcludeEmpty);
  for I := 0 to GetArrayLength(Parts) - 1 do
  begin
    CleanPart := RemoveBackslashUnlessRoot(ExpandConstant(Parts[I]));
    StringChangeEx(CleanPart, '/', '\', True);
    if CompareText(CleanPart, CleanDir) = 0 then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function NeedsAddPath(Dir: String): Boolean;
begin
  Result := not PathContains(Dir, CurrentUserPath());
end;

function AddPath(PathValue, Dir: String): String;
begin
  if PathValue = '' then
    Result := Dir
  else if PathContains(Dir, PathValue) then
    Result := PathValue
  else
    Result := PathValue + ';' + Dir;
end;

function AddExistingPath(PathValue, Dir: String): String;
begin
  if DirExists(Dir) then
    Result := AddPath(PathValue, Dir)
  else
    Result := PathValue;
end;

function AddPaths(Param: String): String;
var
  PathValue: String;
begin
  PathValue := CurrentUserPath();
  if WizardIsTaskSelected('add_chainpeer_path') then
    PathValue := AddPath(PathValue, ExpandConstant('{app}'));
#if HasGitBundle
  if WizardIsTaskSelected('add_git_path') then
    PathValue := AddPath(PathValue, ExpandConstant('{app}\portable-git\cmd'));
  if WizardIsTaskSelected('add_bash_path') then
  begin
    PathValue := AddExistingPath(PathValue, ExpandConstant('{app}\portable-git\bin'));
    PathValue := AddExistingPath(PathValue, ExpandConstant('{app}\portable-git\usr\bin'));
  end;
#endif
  Result := PathValue;
end;

function AnyPathTaskSelected(): Boolean;
begin
  Result := WizardIsTaskSelected('add_chainpeer_path')
#if HasGitBundle
    or WizardIsTaskSelected('add_git_path') or WizardIsTaskSelected('add_bash_path')
#endif
    ;
end;

function RemovePath(PathValue, Dir: String): String;
var
  Parts: TArrayOfString;
  I: Integer;
  NewPath: String;
  CleanDir: String;
  CleanPart: String;
begin
  Parts := StringSplit(PathValue, [';'], stExcludeEmpty);
  NewPath := '';
  CleanDir := RemoveBackslashUnlessRoot(Dir);
  StringChangeEx(CleanDir, '/', '\', True);
  for I := 0 to GetArrayLength(Parts) - 1 do
  begin
    CleanPart := RemoveBackslashUnlessRoot(ExpandConstant(Parts[I]));
    StringChangeEx(CleanPart, '/', '\', True);
    if CompareText(CleanPart, CleanDir) <> 0 then
    begin
      if NewPath <> '' then
        NewPath := NewPath + ';';
      NewPath := NewPath + Parts[I];
    end;
  end;
  Result := NewPath;
end;

procedure RemoveInstallPaths();
var
  PathValue: String;
begin
  PathValue := CurrentUserPath();
  PathValue := RemovePath(PathValue, ExpandConstant('{app}'));
  PathValue := RemovePath(PathValue, ExpandConstant('{app}\portable-git\cmd'));
  PathValue := RemovePath(PathValue, ExpandConstant('{app}\portable-git\bin'));
  PathValue := RemovePath(PathValue, ExpandConstant('{app}\portable-git\usr\bin'));
  RegWriteExpandStringValue(HKCU, 'Environment', 'Path', PathValue);
end;

procedure BroadcastEnvironmentChange();
var
  ResultCode: LongWord;
begin
  SendMessageTimeout($FFFF, WM_SETTINGCHANGE, 0, 'Environment', 2, 5000, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    BroadcastEnvironmentChange();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RemoveInstallPaths();
    BroadcastEnvironmentChange();
  end;
end;
