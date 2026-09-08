param(
    [ValidateRange(1, 300)][int]$TimeoutSeconds = 120,
    [switch]$NoBrowser
)
. (Join-Path $PSScriptRoot 'local_stack.ps1')
$starting = $false
try {
    Initialize-LocalStack
    if (-not (Test-LocalDocker)) { exit 1 }
    Read-LocalConfiguration
    $curl = Get-Command curl.exe -CommandType Application -ErrorAction SilentlyContinue
    if (-not $curl) { throw 'Windows curl.exe is required for the local CA-verified HTTPS health check.' }

    Write-Host 'Starting Lead Engine (the first image build can take several minutes)...'
    $starting = $true
    $null = Invoke-LocalCompose -Arguments @('up', '-d', '--build')
    $null = Invoke-LocalCompose -Arguments @('ps', '--all')

    $timer = [Diagnostics.Stopwatch]::StartNew()
    $certificateCopied = $false
    $ready = $false
    $httpsDetail = 'HTTPS not yet checked; services are still starting'
    while ($timer.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        $states = @(Get-LocalStates)
        $waiting = @($script:Services | Where-Object {
            $name = $_
            $rows = @($states | Where-Object { $_.Service -eq $name })
            $rows.Count -eq 0 -or @($rows | Where-Object { $_.State -ne 'running' -or $_.Health -ne 'healthy' }).Count -gt 0
        })
        if ($waiting.Count -gt 0) {
            Write-Host ('Waiting for: ' + ($waiting -join ', ') + '...')
        } else {
            if (-not $certificateCopied) {
                # Export only the public CA; do not alter the Windows trust store.
                $copy = Invoke-LocalCompose -Arguments @('cp', 'caddy:/data/caddy/pki/authorities/local/root.crt', $script:CertificateFile) -Capture -AllowFailure
                $certificateCopied = $copy.ExitCode -eq 0
                if (-not $certificateCopied) { $httpsDetail = 'Could not export the local Caddy CA' }
            }
            if ($certificateCopied) {
                # Caddy's private CA has no revocation endpoint. Schannel's best-
                # effort option handles that while still verifying chain/hostname.
                # No -k / global TLS bypass; no curlrc or proxy for this loopback probe.
                & $curl.Source --disable --noproxy '*' --cacert $script:CertificateFile --ssl-revoke-best-effort --silent --fail --max-time 5 --output NUL ($script:DashboardUrl + '/health/ready')
                $httpsDetail = "HTTPS readiness probe returned curl exit $LASTEXITCODE"
                if ($LASTEXITCODE -eq 0) { $ready = $true; break }
            }
            Write-Host 'Waiting for the CA-verified HTTPS API readiness endpoint...'
        }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        throw "Startup readiness timed out after $TimeoutSeconds seconds. $httpsDetail. Check the service diagnostics below. Existing databases require the migrations documented in docs/DEPLOYMENT_DOCKER.md."
    }
    $null = Invoke-LocalCompose -Arguments @('ps')
    if (-not $NoBrowser) { Start-Process -FilePath $script:DashboardUrl }
    Write-Host ''
    Write-Host '========================================'
    Write-Host ' Local Business Lead Engine is running'
    Write-Host '========================================'
    Write-Host "Dashboard: $script:DashboardUrl"
    Write-Host 'To stop: Double-click STOP_LOCAL.bat'
    Write-Host 'The browser may request trust for Caddy''s local CA; no Windows trust settings were changed.'
    exit 0
} catch {
    Write-Host ('Startup failed: ' + (Protect-Output $_.Exception.Message)) -ForegroundColor Red
    if ($starting) { Show-LocalDiagnostics }
    exit 1
}
