param(
    [string]$Python = "",
    [int]$NetworkTimeoutSeconds = 5
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Evidence = Join-Path $Root ("docs\evidence\" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Force -Path $Evidence | Out-Null

if (-not $Python) {
    $Python = $env:PHOTOCHECK_PYTHON
}
if (-not $Python) {
    $Python = "python"
}

$PythonPath = (Get-Command $Python -ErrorAction SilentlyContinue).Source
if (-not $PythonPath) {
    throw "Python executable not found: $Python"
}

$Adapters = @(
    Get-NetAdapter | Select-Object Name, InterfaceDescription, Status, LinkSpeed
)
$Routes = @(
    Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
        Select-Object InterfaceAlias, NextHop, RouteMetric
)
$activeAdapters = @($Adapters | Where-Object { $_.Status -eq "Up" })
$connected = $false
try {
    $client = New-Object System.Net.Sockets.TcpClient
    $task = $client.ConnectAsync("example.com", 443)
    $connected = $task.Wait($NetworkTimeoutSeconds * 1000) -and $client.Connected
    $client.Dispose()
}
catch {
    $connected = $false
}

$network = [ordered]@{
    captured_at = (Get-Date).ToString("o")
    adapters = $Adapters
    default_routes = $Routes
    active_adapter_count = $activeAdapters.Count
    external_connection_succeeded = $connected
}
$network | ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath (Join-Path $Evidence "network-summary.json") -Encoding UTF8

$auditOutput = & $PythonPath (Join-Path $Root "photocheck\scripts\audit_offline.py") --run-smoke 2>&1
$auditCode = $LASTEXITCODE
$auditOutput | Set-Content -LiteralPath (Join-Path $Evidence "offline-audit.txt") -Encoding UTF8

Write-Output "Evidence directory: $Evidence"
Write-Output "Active adapters: $($activeAdapters.Count)"
Write-Output "External connection succeeded: $connected"
Write-Output "Offline audit exit: $auditCode"

if ($connected) {
    Write-Error "A physical external connection is still available; disconnect networking and rerun."
    exit 2
}
if ($auditCode -ne 0) {
    exit $auditCode
}
exit 0
