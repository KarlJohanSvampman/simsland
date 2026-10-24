<#
Restart the API gateways one at a time, waiting for each to be healthy (its world replica synced)
before touching the next, so the site keeps answering throughout.

    powershell -File scripts/rolling_restart_api.ps1
#>
$ids = docker compose ps -q api
if (-not $ids) { Write-Error "no api containers running"; exit 1 }
foreach ($id in $ids) {
    $name = (docker inspect $id --format '{{.Name}}').TrimStart('/')
    Write-Host "restarting $name"
    docker restart $id | Out-Null
    $healthy = $false
    foreach ($i in 1..60) {
        $status = docker inspect $id --format '{{.State.Health.Status}}'
        if ($status -eq 'healthy') { $healthy = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) { Write-Error "$name did not become healthy"; exit 1 }
    Write-Host "$name is healthy"
}
