$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$compiler = Join-Path $PWD '.tools\InnoSetup\ISCC.exe'
if (-not (Test-Path $compiler)) {
    throw 'Inno Setup compiler not found at .tools\InnoSetup\ISCC.exe.'
}
foreach ($file in @('models\kokoro\kokoro-v1.0.onnx', 'models\kokoro\voices-v1.0.bin')) {
    if (-not (Test-Path $file)) { throw "Required local voice file not found: $file" }
}
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm packaging\icewolf.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE." }
& $compiler "/DLegacyDir=$PWD" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with exit code $LASTEXITCODE." }
Write-Output "Installer created: $PWD\dist\Icewolf-Setup.exe"
