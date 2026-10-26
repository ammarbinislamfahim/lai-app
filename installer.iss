; ==============================================================================
; installer.iss — Inno Setup 6 Script for LeafArea & LAI Analyzer (Windows x64)
; Installs per-user into %LOCALAPPDATA%\Programs\LeafAreaAnalyzer with
; PrivilegesRequired=lowest (no Administrator privileges required).
; Built automatically in GitHub Actions on windows-latest:
;   iscc /DMyAppVersion=1.5.6 installer.iss
; ==============================================================================

#ifndef MyAppVersion
  #define MyAppVersion "1.5.6"
#endif

#define MyAppName "LeafArea & LAI Analyzer"
#define MyAppShortName "LeafAreaAnalyzer"
#define MyAppPublisher "Scientific Leaf Area Research Project"
#define MyAppExeName "LeafAreaAnalyzer.exe"

[Setup]
AppId={{8F4C9D2A-51B3-4E7A-9C1E-3B7D8A2F6E14}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppShortName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist
OutputBaseFilename=LeafAreaAnalyzer-Setup-v{#MyAppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} v{#MyAppVersion}
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\LeafAreaAnalyzer\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\LeafAreaAnalyzer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\_internal\assets\icon.ico"; Comment: "Launch LeafArea & LAI Analyzer v{#MyAppVersion} in your browser"
Name: "{group}\User Guide (README_USER.md)"; Filename: "{app}\README_USER.md"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\_internal\assets\icon.ico"; Tasks: desktopicon; Comment: "Launch LeafArea & LAI Analyzer v{#MyAppVersion}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Open Leaf Area Analyzer when setup finishes"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{localappdata}\LeafAreaAnalyzer\port.txt"
