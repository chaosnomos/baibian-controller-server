; TPadServer Windows 安装包脚本
; 需要安装 Inno Setup 6: https://jrsoftware.org/isdl.php
; 编译方法: ISCC.exe installer.iss

[Setup]
AppName=TPad Server
AppVersion=1.4.1
AppPublisher=TPad
AppPublisherURL=https://github.com/chaosnomos/baibian-controller-server
AppDescription=TPad 蓝牙/WiFi 远程控制服务器
DefaultDirName={pf}\TPadServer
DefaultGroupName=TPad Server
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=TPadServer_Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\BaibianController-Server.exe

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: checked
Name: "startup"; Description: "开机自启动"; GroupDescription: "附加图标:"; Flags: unchecked

[Files]
Source: "dist\BaibianController-Server.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\TPad Server"; Filename: "{app}\BaibianController-Server.exe"
Name: "{group}\卸载 TPad Server"; Filename: "{uninstallexe}"
Name: "{commondesktop}\TPad Server"; Filename: "{app}\BaibianController-Server.exe"; Tasks: desktopicon
Name: "{commonstartup}\TPad Server"; Filename: "{app}\BaibianController-Server.exe"; Tasks: startup

[Run]
Filename: "{app}\BaibianController-Server.exe"; Description: "立即启动 TPad Server"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 卸载时关闭正在运行的服务
Filename: "{cmd}"; Parameters: "/c taskkill /f /im BaibianController-Server.exe"; Flags: runhidden; RunOnceId: "KillProcess"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
