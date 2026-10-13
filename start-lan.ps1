Set-Location -LiteralPath $PSScriptRoot

$wifiAddress = Get-NetIPAddress -InterfaceAlias 'Wi-Fi' -AddressFamily IPv4 -ErrorAction Stop |
    Where-Object { $_.IPAddress -notmatch '^(127|169\.254)\.' } |
    Select-Object -First 1
if (-not $wifiAddress) {
    throw 'Wi-Fi IPv4 주소를 찾지 못했습니다.'
}

$env:JUDGE_HOST = '0.0.0.0'
$env:JUDGE_ALLOWED_SUBNETS = python -c "import ipaddress,sys; print(ipaddress.ip_interface(sys.argv[1]).network)" "$($wifiAddress.IPAddress)/$($wifiAddress.PrefixLength)"
Write-Host "Python Judge LAN: http://$($wifiAddress.IPAddress):8000"
Write-Host "허용된 대역: $env:JUDGE_ALLOWED_SUBNETS"
python server.py
