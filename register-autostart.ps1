$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run install.cmd to create the Python environment first.' }
$startupFolder = [Environment]::GetFolderPath('Startup')
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $startupFolder 'HS Online Judge.lnk'))
$shortcut.TargetPath = $python
$shortcut.Arguments = '"' + (Join-Path $PSScriptRoot 'autostart.py') + '"'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.WindowStyle = 7
$shortcut.Description = 'Start Docker and HS Online Judge on port 18000 after Windows sign-in'
$shortcut.Save()
Write-Host 'HS Online Judge: Windows sign-in startup registered (port 18000).'
