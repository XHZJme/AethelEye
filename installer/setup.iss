; ================================================================
; 筱和灵眸(AethelEye) - Inno Setup 安装脚本 v2.0.0
; ================================================================
; 覆盖升级规则：
;   - 程序文件(exe/dll/dist)全量替换
;   - data/ 目录保留（数据库、截图、日志、录屏、插件）
;   - jwt_secret.key / mcp_registry.json 等配置文件保留

[Setup]
AppId={{AETHELEYE-2026-001}}
AppName=筱和灵眸(AethelEye)
AppVersion=2.0.0
AppPublisher=XHZJ
AppPublisherURL=https://github.com/XHZJme
AppSupportURL=https://github.com/XHZJme/AethelEye/issues
AppUpdatesURL=https://github.com/XHZJme/AethelEye/releases

DefaultDirName={autopf}\AethelEye
DefaultGroupName=筱和灵眸
AllowNoIcons=yes

OutputDir=.\output
OutputBaseFilename=AethelEye_Setup_v2.0.0
Compression=lzma2/ultra64
SolidCompression=yes

PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

WizardStyle=modern
WizardSizePercent=100

LicenseFile=..\LICENSE

; 允许覆盖安装（升级）
UsePreviousAppDir=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "开机自动启动"; GroupDescription: "启动选项"; Flags: unchecked

[Files]
; ── 主程序（PyInstaller onedir 产物）──────────────────────
; 注意：整个 dist/AethelEye/ 目录平铺到 {app}
Source: "..\backend\dist\AethelEye\AethelEye.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\backend\dist\AethelEye\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

; ── 前端静态文件 ──────────────────────────────────────────
Source: "..\dist\*"; DestDir: "{app}\dist"; Flags: ignoreversion recursesubdirs createallsubdirs

; ── 文档 ──────────────────────────────────────────────────
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
; data/ 目录 —— 这些目录仅在首次安装时创建，升级不会清空
Name: "{app}\data"; Permissions: users-modify
Name: "{app}\data\logs"; Permissions: users-modify
Name: "{app}\data\logs\system"; Permissions: users-modify
Name: "{app}\data\logs\collector"; Permissions: users-modify
Name: "{app}\data\logs\network"; Permissions: users-modify
Name: "{app}\data\logs\browser"; Permissions: users-modify
Name: "{app}\data\logs\audit"; Permissions: users-modify
Name: "{app}\data\logs\alert"; Permissions: users-modify
Name: "{app}\data\screenshots"; Permissions: users-modify
Name: "{app}\data\recordings"; Permissions: users-modify
Name: "{app}\data\plugins"; Permissions: users-modify
Name: "{app}\data\ai_memory"; Permissions: users-modify
Name: "{app}\data\browser_profiles"; Permissions: users-modify

[Icons]
Name: "{group}\筱和灵眸"; Filename: "{app}\AethelEye.exe"
Name: "{group}\打开后台"; Filename: "http://localhost:8686"
Name: "{group}\查看日志"; Filename: "{app}\data\logs"
Name: "{group}\{cm:UninstallProgram,筱和灵眸}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\筱和灵眸"; Filename: "{app}\AethelEye.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AethelEye.exe"; Description: "立即启动筱和灵眸"; Flags: nowait postinstall skipifsilent
Filename: "http://localhost:8686"; Description: "打开后台管理页面"; Flags: shellexec postinstall skipifsilent unchecked

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AethelEye"; ValueData: """{app}\AethelEye.exe"""; Tasks: autostart; Flags: uninsdeletevalue

[Code]
// ── 升级前：关闭正在运行的旧进程 ─────────────────────────
procedure KillRunningInstance();
var
  ResultCode: Integer;
begin
  Exec('taskkill', '/F /IM AethelEye.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  // 尝试关闭旧进程
  KillRunningInstance();
end;

// ── 安装后：创建目录结构 ─────────────────────────────────
procedure CurStepChanged(CurStep: TSetupStep);
var
  DataPath: String;
begin
  if CurStep = ssPostInstall then
  begin
    DataPath := ExpandConstant('{app}\data');
    ForceDirectories(DataPath + '\logs\system');
    ForceDirectories(DataPath + '\logs\collector');
    ForceDirectories(DataPath + '\logs\network');
    ForceDirectories(DataPath + '\logs\browser');
    ForceDirectories(DataPath + '\logs\audit');
    ForceDirectories(DataPath + '\logs\alert');
    ForceDirectories(DataPath + '\screenshots');
    ForceDirectories(DataPath + '\recordings');
    ForceDirectories(DataPath + '\backups');
    ForceDirectories(DataPath + '\plugins');
    ForceDirectories(DataPath + '\ai_memory');
    ForceDirectories(DataPath + '\browser_profiles');
  end;
end;

// ── 卸载 ─────────────────────────────────────────────────
function InitializeUninstall(): Boolean;
begin
  Result := True;
  if MsgBox('确定要卸载筱和灵眸吗？', mbConfirmation, MB_YESNO) = IDNO then
    Result := False
  else
    KillRunningInstance();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataPath: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    DataPath := ExpandConstant('{app}\data');
    if MsgBox('是否保留数据文件（数据库、截图、日志、录屏、插件）？'#13#10'选"是"保留数据，"否"全部删除。', mbConfirmation, MB_YESNO) = IDNO then
      DelTree(DataPath, True, True, True);
  end;
end;

[UninstallDelete]
Type: filesandordirs; Name: "{app}\*.tmp"
Type: filesandordirs; Name: "{app}\*.log"
Type: filesandordirs; Name: "{app}\__pycache__"
