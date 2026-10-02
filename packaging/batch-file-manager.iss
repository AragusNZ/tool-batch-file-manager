; Installer for the onedir build. Compiled by build.ps1 with /DAppVersion=<VERSION>.
; Per-user by design: PrivilegesRequired=lowest means no UAC prompt, which is one less trust
; dialog on a build that is not yet code-signed, and the tool needs no machine-wide state.
; AppId is fixed forever - it is what makes the next version upgrade this one in place.

[Setup]
AppId={{9771861A-C491-4C51-B52C-D3F636EAFFC9}
AppName=Batch File Manager
AppVersion={#AppVersion}
AppVerName=Batch File Manager {#AppVersion}
AppPublisher=AragusNZ
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Batch File Manager
DefaultGroupName=Batch File Manager
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=BatchFileManager-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\batch_file_manager\assets\icon.ico
LicenseFile=..\LICENSE
UninstallDisplayIcon={app}\BatchFileManager.exe

[Files]
Source: "..\dist\BatchFileManager\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Batch File Manager"; Filename: "{app}\BatchFileManager.exe"
Name: "{userdesktop}\Batch File Manager"; Filename: "{app}\BatchFileManager.exe"; Tasks: desktopicon
; Explorer > right-click a folder > Send to > Batch File Manager opens the app scoped to it. Per-user; the uninstaller removes it.
Name: "{usersendto}\Batch File Manager"; Filename: "{app}\BatchFileManager.exe"

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"
Name: contextmenu; Description: "Add ""Open in Batch File Manager"" to the right-click menu of folders"; GroupDescription: "Explorer integration:"

; Explorer > right-click a folder (or the empty space inside one) > Open in Batch File Manager. Per-user keys under
; HKCU\Software\Classes, so no UAC. Windows 11 lists it under "Show more options": the modern menu needs packaged
; identity, which an unsigned exe cannot have. uninsdeletekey removes the whole key; the deletekey lines clear an
; entry left by an earlier install when the task is unticked this time.
[Registry]
Root: HKCU; Subkey: "Software\Classes\Directory\shell\BatchFileManager"; ValueType: string; ValueData: "Open in Batch File Manager"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\BatchFileManager"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\BatchFileManager.exe"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\BatchFileManager\command"; ValueType: string; ValueData: """{app}\BatchFileManager.exe"" ""%1"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\BatchFileManager"; ValueType: string; ValueData: "Open in Batch File Manager"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\BatchFileManager"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\BatchFileManager.exe"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\BatchFileManager\command"; ValueType: string; ValueData: """{app}\BatchFileManager.exe"" ""%V"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\BatchFileManager"; Flags: deletekey; Tasks: not contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\BatchFileManager"; Flags: deletekey; Tasks: not contextmenu

[Run]
Filename: "{app}\BatchFileManager.exe"; Description: "Launch Batch File Manager"; Flags: nowait postinstall skipifsilent
