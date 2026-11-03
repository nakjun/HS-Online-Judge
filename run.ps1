param(
    [switch]$NoBrowser,
    [switch]$Restart,
    [switch]$LocalOnly,
    [ValidateRange(1, 65535)][int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-Location -LiteralPath $PSScriptRoot
$serverPath = Join-Path $PSScriptRoot 'server.py'
$url = "http://127.0.0.1:$Port/"
$runtime = Join-Path $PSScriptRoot 'runtime'

function Test-Judge {
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200 -and $response.Content.Contains('<title>Python Judge</title>')
    } catch { return $false }
}

function Test-NativeCommand([string]$executable, [string[]]$arguments) {
    $ErrorActionPreference = 'Continue'
    $output = & $executable @arguments 2>&1
    $succeeded = $LASTEXITCODE -eq 0
    if (-not $succeeded) { $script:lastCheckError = ($output | Out-String).Trim() }
    return $succeeded
}

function Find-Docker {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
        (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
    )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

$originalEnvironment = @{}
foreach ($key in @('PATH', 'JUDGE_HOST', 'JUDGE_PORT', 'JUDGE_ALLOWED_SUBNETS')) {
    $originalEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}

try {
    $running = Test-Judge
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0 -and -not $running) { throw "Port $Port is used by another application." }
    if ($running -and $Restart) {
        $owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
        if ($owners.Count -ne 1) { throw 'Cannot identify the server process. Stop the old server manually.' }
        $serverProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($owners[0])"
        if (-not $serverProcess -or $serverProcess.Name -notmatch '^python(w)?\.exe$' -or
            -not $serverProcess.CommandLine -or
            $serverProcess.CommandLine.IndexOf($serverPath, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
            throw 'The old server was not started with this project path. Close its terminal, then run run.cmd again.'
        }
        Stop-Process -Id $owners[0] -ErrorAction Stop
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 250
        }
        if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
            throw "Port $Port did not close after stopping the server."
        }
        $running = $false
    }
    if ($running) {
        Write-Host 'Using the existing server. After git pull, use run.cmd -Restart to reload server code.'
    } else {
        $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $python)) { throw 'Python environment missing. Run install.cmd first.' }
        if (-not (Test-NativeCommand $python @('-c', 'import sys, openpyxl; raise SystemExit(sys.version_info < (3, 10))'))) {
            throw "Python dependencies unavailable. Run install.cmd first. $script:lastCheckError"
        }
        $docker = Find-Docker
        if (-not $docker) { throw 'Docker is missing. Run install.cmd first.' }
        $env:PATH = (Split-Path -Parent $docker) + ';' + $env:PATH
        if (-not (Test-NativeCommand $docker @('info', '--format', '{{.ServerVersion}}'))) {
            $desktop = @(
                (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'),
                (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe')
            ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
            if (-not $desktop) { throw "Start Docker Desktop, then try again. $script:lastCheckError" }
            Start-Process -FilePath $desktop -WindowStyle Hidden | Out-Null
            Write-Host 'Waiting for Docker Desktop...'
            $dockerReady = $false
            for ($attempt = 0; $attempt -lt 60; $attempt++) {
                Start-Sleep -Seconds 2
                if (Test-NativeCommand $docker @('info', '--format', '{{.ServerVersion}}')) { $dockerReady = $true; break }
            }
            if (-not $dockerReady) { throw "Docker did not become ready. $script:lastCheckError" }
        }
        $image = if ($env:JUDGE_IMAGE) { $env:JUDGE_IMAGE } else { 'python:3.13-alpine' }
        if (-not (Test-NativeCommand $docker @('image', 'inspect', $image))) {
            throw "Grading image missing: $image. Run install.cmd first."
        }
        $env:JUDGE_PORT = [string]$Port
        $env:JUDGE_HOST = '127.0.0.1'
        $env:JUDGE_ALLOWED_SUBNETS = ''
        if (-not $LocalOnly) {
            $network = Get-NetIPConfiguration |
                Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } |
                Sort-Object @{ Expression = { if ($_.InterfaceAlias -eq 'Wi-Fi') { 0 } else { 1 } } } |
                Select-Object -First 1
            $address = $network.IPv4Address |
                Where-Object { $_.IPAddress -notmatch '^(127|169\.254)\.' } |
                Select-Object -First 1
            if (-not $address) { throw 'LAN IPv4 address unavailable. Use run.cmd -LocalOnly for this PC only.' }
            $subnet = & $python -c 'import ipaddress,sys; print(ipaddress.ip_interface(sys.argv[1]).network)' "$($address.IPAddress)/$($address.PrefixLength)"
            if ($LASTEXITCODE -ne 0) { throw 'Could not determine the LAN subnet.' }
            $env:JUDGE_HOST = '0.0.0.0'
            $env:JUDGE_ALLOWED_SUBNETS = $subnet.Trim()
            Write-Host "Student LAN URL: http://$($address.IPAddress):$Port/"
        }
        New-Item -ItemType Directory -Path $runtime -Force | Out-Null
        $process = Start-Process -FilePath $python -ArgumentList @('"' + $serverPath + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'server.out.log') -RedirectStandardError (Join-Path $runtime 'server.err.log') -PassThru
        $ready = $false
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            Start-Sleep -Seconds 1
            if (Test-Judge) { $ready = $true; break }
            if ($process.HasExited) { break }
        }
        if (-not $ready) { throw "Server startup failed. Check $runtime\server.err.log" }
    }
    Write-Host "Python Judge: $url"
    if (-not $NoBrowser) { Start-Process $url | Out-Null }
    exit 0
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    foreach ($key in $originalEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($key, $originalEnvironment[$key], 'Process')
    }
}
