param([switch]$Autostart)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$PythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.venv-portable\Scripts\python.exe')) { $PythonPath = Join-Path $PSScriptRoot '.venv-portable\Scripts\python.exe' }
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.venv-portable\Scripts\python.exe')) { $PythonPath = Join-Path $PSScriptRoot '.venv-portable\Scripts\python.exe' }
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.venv-portable\Scripts\python.exe')) { $PythonPath = Join-Path $PSScriptRoot '.venv-portable\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $PythonPath)) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 or newer and retry.' }
}
& $PythonPath -m pip install --no-cache-dir -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item '.env.example' '.env' }
& $PythonPath hermes.py init
if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed.' }
if ($Autostart) {
    $StartupDir = [Environment]::GetFolderPath('Startup')
    $ShellObject = New-Object -ComObject WScript.Shell
    $Link = $ShellObject.CreateShortcut((Join-Path $StartupDir 'Hermes News.lnk'))
    $Link.TargetPath = Join-Path $PSScriptRoot 'start.cmd'
    $Link.WorkingDirectory = $PSScriptRoot
    $Link.WindowStyle = 7
    $Link.Save()
}
Write-Host 'Configure .env, run .venv\Scripts\python.exe hermes.py login, then start_hermes.cmd.'
