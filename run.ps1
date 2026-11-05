param(
    [switch]$NoBrowser,
    [switch]$Restart,
    [switch]$LocalOnly,
    [ValidateRange(1, 65535)][int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Write-Host 'Python Judge - starting Python launcher...'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    Write-Host 'Python environment missing. Run install.cmd first.' -ForegroundColor Red
    exit 1
}
$launchArguments = @((Join-Path $PSScriptRoot 'launch.py'), '-Port', [string]$Port)
if ($NoBrowser) { $launchArguments += '-NoBrowser' }
if ($Restart) { $launchArguments += '-Restart' }
if ($LocalOnly) { $launchArguments += '-LocalOnly' }
& $python -u @launchArguments
exit $LASTEXITCODE
