param([switch]$DryRun)
. (Join-Path $PSScriptRoot 'local_stack.ps1')
try {
    Initialize-LocalStack -Mode Live
    if (-not (Test-LocalDocker)) { exit 1 }
    Read-LocalConfiguration
    $command = @('exec', '-T', 'api', 'python', '-m', 'lead_engine.clean_fixtures')
    $result = Invoke-LocalCompose -Arguments $command -Capture
    $plan = $result.Output | ConvertFrom-Json
    Write-Host 'DRY RUN - known fixture rows only (no data changed):'
    $plan.counts.PSObject.Properties | ForEach-Object { Write-Host ($_.Name + ': ' + $_.Value) }
    if (-not $plan.safe_to_apply) { throw 'Fixture jobs or browser cleanup are pending. Let them finish and retry.' }
    if ($DryRun -or $plan.counts.search_jobs + $plan.counts.businesses -eq 0) { exit 0 }
    $confirmation = Read-Host 'Type DELETE FIXTURES to continue; anything else cancels'
    if ($confirmation -cne 'DELETE FIXTURES') { Write-Host 'Cancelled. No data changed.'; exit 0 }
    $null = Invoke-LocalCompose -Arguments ($command + @('--plan', $plan.plan, '--confirm', $confirmation))
    Write-Host 'Fixture cleanup committed. Users, sessions, security events and unrelated records preserved.'
    exit 0
} catch {
    Write-Host ('Cleanup failed: ' + (Protect-Output $_.Exception.Message)) -ForegroundColor Red
    exit 1
}
