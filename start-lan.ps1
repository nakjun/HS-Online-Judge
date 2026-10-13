Set-Location -LiteralPath $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }

$network = Get-NetIPConfiguration |
    Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } |
    Sort-Object @{ Expression = { if ($_.InterfaceAlias -eq 'Wi-Fi') { 0 } else { 1 } } } |
    Select-Object -First 1
$address = $network.IPv4Address |
    Where-Object { $_.IPAddress -notmatch '^(127|169\.254)\.' } |
    Select-Object -First 1
if (-not $address) {
    throw 'LAN에 연결된 IPv4 주소를 찾지 못했습니다.'
}

$env:JUDGE_HOST = '0.0.0.0'
$env:JUDGE_ALLOWED_SUBNETS = & $python -c "import ipaddress,sys; print(ipaddress.ip_interface(sys.argv[1]).network)" "$($address.IPAddress)/$($address.PrefixLength)"
if ($LASTEXITCODE -ne 0) { throw 'LAN 대역을 계산하지 못했습니다.' }
Write-Host "Python Judge LAN: http://$($address.IPAddress):8000"
Write-Host "허용된 대역: $env:JUDGE_ALLOWED_SUBNETS"
& $python server.py
exit $LASTEXITCODE
