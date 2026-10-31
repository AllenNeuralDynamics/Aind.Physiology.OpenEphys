param([switch]$NoLaunch)
Push-Location $PSScriptRoot
$version = "1.1.0"
if (!(Test-Path "./open-ephys.exe")) {
    $release = "https://github.com/open-ephys/plugin-GUI/releases/download/v${version}/open-ephys-v${version}-windows.zip"
    Write-Host "Downloading Open Ephys GUI v${version} from $release"
    Invoke-WebRequest $release -OutFile "temp.zip"
    Expand-Archive "temp.zip" -DestinationPath "temp" -Force
    Get-ChildItem "temp/open-ephys/*" | Move-Item -Destination "." -Force
    Remove-Item -Path "temp" -Recurse -Force
    Remove-Item -Path "temp.zip"
}
if (!$NoLaunch) { & .\open-ephys.exe }
Pop-Location