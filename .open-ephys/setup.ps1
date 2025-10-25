Push-Location $PSScriptRoot
$Version = "0.1.1"
if (!(Test-Path "./open-ephys.exe")) {
    $release = "https://github.com/open-ephys/plugin-GUI/releases/download/v$Version/open-ephys-v$Version-windows.zip"
    Invoke-WebRequest $release -OutFile "temp.zip"
    Expand-Archive "temp.zip" -DestinationPath "." -Force
    Remove-Item -Path "temp.zip"
}
& .\open-ephys.exe
Pop-Location