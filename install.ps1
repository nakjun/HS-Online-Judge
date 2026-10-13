param(
    [switch]$SetupOnly,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-Location -LiteralPath $PSScriptRoot

function Find-Python {
    $ErrorActionPreference = 'Continue'
    $candidates = @()
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $detected = & $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $detected) { $candidates += $detected.Trim() }
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe')
    $candidates += (Join-Path $env:ProgramFiles 'Python313\python.exe')
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        & $candidate -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' 2>$null
        if ($LASTEXITCODE -eq 0) { return $candidate }
    }
    return $null
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

function Test-DockerCommand([string[]]$arguments) {
    $ErrorActionPreference = 'Continue'
    $output = & $script:docker @arguments 2>&1
    $succeeded = $LASTEXITCODE -eq 0
    if (-not $succeeded) { $script:lastDockerError = ($output | Out-String).Trim() }
    return $succeeded
}

function Install-Package($id) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget이 없습니다. Microsoft App Installer를 설치한 뒤 다시 실행하세요. ($id)"
    }
    Write-Host "Installing $id ..."
    & winget install --id $id --exact --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw "$id 설치에 실패했습니다. winget 출력 내용을 확인하세요." }
}

try {
    Write-Host '[1/4] Python 확인'
    $python = Find-Python
    if (-not $python) {
        Install-Package 'Python.Python.3.13'
        $python = Find-Python
        if (-not $python) { throw 'Python 설치 후 찾지 못했습니다. Windows를 다시 시작한 뒤 재실행하세요.' }
    }
    Write-Host "Python: $python"
    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & $python -m venv (Join-Path $PSScriptRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Python 가상환경 생성에 실패했습니다.' }
    }

    Write-Host '[2/4] Python 패키지 설치'
    & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Python 패키지 설치에 실패했습니다.' }

    Write-Host '[3/4] Docker 확인'
    $docker = Find-Docker
    if (-not $docker) {
        Install-Package 'Docker.DockerDesktop'
        $docker = Find-Docker
        if (-not $docker) { throw 'Docker Desktop 설치 후 찾지 못했습니다. Windows를 다시 시작한 뒤 재실행하세요.' }
    }
    $env:PATH = (Split-Path -Parent $docker) + ';' + $env:PATH
    if (-not (Test-DockerCommand @('info','--format','{{.ServerVersion}}'))) {
        $desktop = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'),
            (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe')
        ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $desktop) { throw 'Docker Desktop 실행 파일을 찾지 못했습니다.' }
        Start-Process -FilePath $desktop | Out-Null
        Write-Host 'Docker Desktop 창에서 초기 설정이 나오면 완료하세요. Linux 엔진을 기다리는 중...'
        $ready = $false
        for ($attempt = 0; $attempt -lt 90; $attempt++) {
            Start-Sleep -Seconds 2
            if (Test-DockerCommand @('info','--format','{{.ServerVersion}}')) { $ready = $true; break }
        }
        if (-not $ready) { throw "Docker Linux 엔진이 시작되지 않았습니다. Docker Desktop 초기 설정과 WSL 2 설치 상태를 확인하세요. 마지막 Docker 오류: $script:lastDockerError" }
    }
    if (-not (Test-DockerCommand @('image','inspect','python:3.13-alpine'))) {
        & $docker pull 'python:3.13-alpine'
        if ($LASTEXITCODE -ne 0) { throw '채점용 Docker 이미지를 받지 못했습니다.' }
    }

    Write-Host '[4/4] 설치 확인'
    & $venvPython (Join-Path $PSScriptRoot 'verify-install.py')
    if ($LASTEXITCODE -ne 0) { throw '채점 컨테이너 실행 확인에 실패했습니다.' }
    if ($SetupOnly) { Write-Host '설치 확인 완료.'; exit 0 }

    $url = 'http://127.0.0.1:8000/'
    $running = $false
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
        $running = $response.StatusCode -eq 200 -and $response.Content.Contains('<title>Python Judge</title>')
    } catch { }
    $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($listener -and -not $running) { throw '8000 포트를 다른 프로그램이 사용 중입니다.' }
    if (-not $running) {
        $runtime = Join-Path $PSScriptRoot 'runtime'
        New-Item -ItemType Directory -Path $runtime -Force | Out-Null
        $launcher = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + (Join-Path $PSScriptRoot 'start-lan.ps1') + '"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'server.out.log') -RedirectStandardError (Join-Path $runtime 'server.err.log') -PassThru
        $ready = $false
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            Start-Sleep -Seconds 1
            try {
                $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
                if ($response.StatusCode -eq 200 -and $response.Content.Contains('<title>Python Judge</title>')) { $ready = $true; break }
            } catch { }
            if ($launcher.HasExited) { break }
        }
        if (-not $ready) { throw "서버 시작에 실패했습니다. $(Join-Path $runtime 'server.err.log') 내용을 확인하세요." }
    }
    Write-Host "Python Judge: $url"
    if (-not $NoBrowser) { Start-Process $url | Out-Null }
    exit 0
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
