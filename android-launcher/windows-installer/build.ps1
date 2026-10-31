# Developer build: Windows with .NET Framework 4.x and official Android Platform Tools.
param(
    [Parameter(Mandatory=$true)][string]$ApkPath,
    [Parameter(Mandatory=$true)][string]$AdbDirectory,
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'out')
)
$ErrorActionPreference = 'Stop'
$bundle = Join-Path $OutputDirectory 'MiLite-TV-Windows'
if (Test-Path $bundle) { throw 'Output bundle already exists; choose a new output directory.' }
New-Item -ItemType Directory -Path (Join-Path $bundle 'platform-tools') -Force | Out-Null
Copy-Item -LiteralPath $ApkPath -Destination (Join-Path $bundle 'MiLite-TV.apk')
$files = @('MiLite-TV.apk')
foreach ($name in @('adb.exe','AdbWinApi.dll','AdbWinUsbApi.dll','NOTICE.txt','source.properties')) {
    Copy-Item -LiteralPath (Join-Path $AdbDirectory $name) -Destination (Join-Path $bundle 'platform-tools')
    $files += "platform-tools\$name"
}
# Embed hashes in the executable so corrupted dependencies are rejected before execution.
$names = ($files | ForEach-Object { '"' + $_.Replace('\','\\') + '"' }) -join ','
$hashes = ($files | ForEach-Object { '"' + (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $bundle $_)).Hash.ToLowerInvariant() + '"' }) -join ','
$integrity = Join-Path $OutputDirectory 'BundleIntegrity.cs'
[IO.File]::WriteAllText($integrity, "namespace MiLiteInstaller { static class BundleIntegrity { public static readonly string[] Files = new string[] {$names}; public static readonly string[] Hashes = new string[] {$hashes}; } }", [Text.UTF8Encoding]::new($false))
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (!(Test-Path $csc)) { $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
& $csc /nologo /target:winexe /langversion:5 /codepage:65001 /optimize+ "/out:$bundle\Установить MiLite TV.exe" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Core.dll (Join-Path $PSScriptRoot 'Installer.cs') (Join-Path $PSScriptRoot 'InstallerCore.cs') $integrity
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Установка.txt') -Destination $bundle
$zip = Join-Path $OutputDirectory 'MiLite-TV-Windows.zip'
Compress-Archive -LiteralPath $bundle -DestinationPath $zip
Write-Host "Bundle ready: $zip"
