# Stop everything scripts\run_all.ps1 and scripts\run_dashboards.ps1 started, by port.
foreach ($port in 8000, 8101, 8102, 8103, 8104, 8080, 5174, 5175, 5176) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -Confirm:$false
        Write-Host ("stopped :{0} (pid {1})" -f $port, $_.OwningProcess)
    }
}
