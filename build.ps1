# Builds dist\BatchFileManager\ (onedir), then dist\BatchFileManager-<version>-setup.exe, dist\BatchFileManager-<version>.zip
# and dist\SHA256SUMS.txt.
# Needs Windows Python 3 (py launcher). From WSL run ./build.sh - it uses the Windows Python over \\wsl.localhost.
# The venv and PyInstaller work dir live under %LOCALAPPDATA%\batch-file-manager: pip over \\wsl.localhost is unusably slow.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$work = Join-Path $env:LOCALAPPDATA 'batch-file-manager'
$py = "$work\venv\Scripts\python.exe"
if (-not (Test-Path $py)) { py -3 -m venv "$work\venv" }
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet -r requirements.txt -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

$version = (Get-Content "$PSScriptRoot\VERSION" -Raw).Trim()
$name = 'BatchFileManager'

# Without a version resource the exe has no publisher string at all, so Windows calls it unknown and
# SmartScreen has nothing to name. Derived from VERSION - never hardcode it. Win32 wants four fields.
$v4 = (($version.Split('.') + @('0', '0', '0', '0'))[0..3]) -join ', '
$verInfo = "$work\version_info.txt"
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($v4), prodvers=($v4), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'AragusNZ'),
      StringStruct('FileDescription', 'Batch File Manager'),
      StringStruct('FileVersion', '$version.0'),
      StringStruct('InternalName', '$name'),
      StringStruct('LegalCopyright', 'Copyright (c) AragusNZ'),
      StringStruct('OriginalFilename', '$name.exe'),
      StringStruct('ProductName', 'Batch File Manager'),
      StringStruct('ProductVersion', '$version.0')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content $verInfo -Encoding ascii

# onedir, not onefile: a onefile bootloader unpacks a Python runtime into %TEMP% and runs it, which is
# the PyInstaller behaviour antivirus flags hardest. --noupx drops the other heuristic.
# Asset paths are absolute: a relative --add-data/--icon resolves against --specpath, which is outside the repo.
& $py -m PyInstaller --noconfirm --clean --onedir --noupx --windowed --name $name `
    --icon "$PSScriptRoot\batch_file_manager\assets\icon.ico" --version-file "$verInfo" `
    --add-data "$PSScriptRoot\batch_file_manager\assets;batch_file_manager\assets" --add-data "$PSScriptRoot\VERSION;." `
    --workpath "$work\build" --specpath "$work" batch_file_manager\__main__.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

# --onedir already wrote dist\BatchFileManager\BatchFileManager.exe and its _internal\ beside it.
$stage = "dist\$name"
Copy-Item 'README.md' $stage
Copy-Item 'LICENSE' $stage

$setup = "dist\$name-$version-setup.exe"
# winget installs Inno Setup per-user under LOCALAPPDATA; the installer from jrsoftware.org and
# the choco package the release workflow uses both land in Program Files (x86).
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source }
if ($iscc) {
    if (Test-Path $setup) { Remove-Item $setup }
    & $iscc /Qp /DAppVersion=$version "$PSScriptRoot\packaging\batch-file-manager.iss"
    if ($LASTEXITCODE -ne 0) { throw 'ISCC failed' }
} else {
    Write-Warning 'Inno Setup 6 not found - skipping the installer. winget install JRSoftware.InnoSetup'
}

$zip = "dist\$name-$version.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$stage\*" -DestinationPath $zip

# Written by hand rather than with Set-Content: the PowerShell 5.1 default is UTF-16, and even
# -Encoding ascii still emits CRLF. `sha256sum -c` reads neither.
$sums = @($setup, $zip) | Where-Object { Test-Path $_ } | ForEach-Object {
    (Get-FileHash $_ -Algorithm SHA256).Hash.ToLower() + '  ' + (Split-Path $_ -Leaf)
}
[IO.File]::WriteAllText("$PSScriptRoot\dist\SHA256SUMS.txt", ($sums -join "`n") + "`n")
Write-Host "Built $($sums.Count) artifact(s) in dist\ for $version"
