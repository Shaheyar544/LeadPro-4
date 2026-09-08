. (Join-Path $PSScriptRoot 'local_stack.ps1')
try {
    Initialize-LocalStack
    if (-not (Test-LocalDocker)) {
        Write-Host 'No stop command was sent. PostgreSQL/Compose volumes were not changed.'
        exit 1
    }
    Read-LocalConfiguration
    Write-Host 'Stopping Lead Engine safely...'
    # Never add -v, --volumes, prune, or --remove-orphans here.
    $null = Invoke-LocalCompose -Arguments @('down')
    $remaining = @(Get-LocalStates)
    if ($remaining.Count -gt 0) { throw 'Some project containers remain. Check Docker Desktop and retry STOP_LOCAL.bat.' }
    Write-Host 'Lead Engine stopped safely.'
    Write-Host 'PostgreSQL/Compose volumes were preserved.'
    exit 0
} catch {
    Write-Host ('Stop failed: ' + (Protect-Output $_.Exception.Message)) -ForegroundColor Red
    exit 1
}
