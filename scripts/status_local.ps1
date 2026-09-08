. (Join-Path $PSScriptRoot 'local_stack.ps1')
try {
    Initialize-LocalStack -Mode Live
    if (-not (Test-LocalDocker)) { exit 1 }
    Read-LocalConfiguration
    $null = Invoke-LocalCompose -Arguments @('ps', '--all')
    Write-Host ('Dashboard: ' + $script:DashboardUrl)
    if (@(Get-LocalStates).Count -eq 0) { Write-Host 'Stack is stopped.' }
    exit 0
} catch {
    Write-Host ('Status failed: ' + (Protect-Output $_.Exception.Message)) -ForegroundColor Red
    exit 1
}
