# Shared launch logic for two explicitly isolated modes.
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$script:RepoRoot = Split-Path -Parent $PSScriptRoot
$script:Services = @('caddy', 'api', 'worker', 'postgres', 'redis', 'camofox')
$script:SecretValues = New-Object 'System.Collections.Generic.List[string]'
$script:Docker = $null

function Add-PrivateValue([string]$Name, [string]$Value) {
    if ($Name -match '(?i)password|secret|token|key|authorization|database_url|redis_url' -and $Value) {
        $script:SecretValues.Add($Value)
    }
}

function Protect-Output([string]$Text) {
    foreach ($secret in ($script:SecretValues | Sort-Object Length -Descending)) {
        $Text = $Text.Replace($secret, '[REDACTED]')
    }
    $Text = $Text -replace '(?i)(postgres(?:ql)?(?:\+psycopg)?|rediss?)://[^\s"''<>]+', '[REDACTED_URL]'
    # Omit header/credential payload lines, including unknown session/CSRF values.
    if ($Text -match '(?i)(authorization|cookie|csrf[-_]?token|password|secret|api[-_]?key|access[-_]?key)["'']?\s*[:=]' -or $Text -match '(?i)Bearer\s+\S+') {
        return '[Sensitive diagnostic line omitted.]'
    }
    return $Text
}

function Initialize-LocalStack {
    param([Parameter(Mandatory=$true)][ValidateSet('Live', 'OfflineTest')][string]$Mode)
    $script:Mode = $Mode
    $offline = $Mode -eq 'OfflineTest'
    $script:Project = if ($offline) { 'leadpro-offline-test' } else { 'leadpro-live' }
    $script:ExpectedMode = if ($offline) { 'offline_test' } else { 'live' }
    $script:DashboardUrl = if ($offline) { 'https://localhost:8444' } else { 'https://localhost:8443' }
    $script:Title = if ($offline) { 'OFFLINE TEST MODE' } else { 'LIVE LOCAL MODE' }
    $script:ComposeFiles = @((Join-Path $script:RepoRoot 'compose.production.yaml'))
    if ($offline) { $script:ComposeFiles += Join-Path $script:RepoRoot 'compose.test.yaml' }
    $script:EnvironmentFile = Join-Path $script:RepoRoot '.local-integration\stack.env'
    $script:EnvironmentFiles = @()
    $rootEnv = Join-Path $script:RepoRoot '.env'
    if (Test-Path -LiteralPath $rootEnv -PathType Leaf) { $script:EnvironmentFiles += $rootEnv }
    # Existing production secrets take precedence over the development .env.
    $script:EnvironmentFiles += $script:EnvironmentFile
    $script:CertificateFile = Join-Path $script:RepoRoot ('.local-integration\' + $script:Project + '-root.crt')
    $script:ComposeArgs = @('compose', '--project-name', $script:Project)
    foreach ($file in $script:EnvironmentFiles) { $script:ComposeArgs += @('--env-file', $file) }
    foreach ($file in $script:ComposeFiles) { $script:ComposeArgs += @('-f', $file) }
    Set-Location -LiteralPath $script:RepoRoot
    # Collect values privately before any native diagnostics can be displayed.
    Get-ChildItem Env: | ForEach-Object { Add-PrivateValue $_.Name $_.Value }
    foreach ($envFile in $script:EnvironmentFiles) {
        if (Test-Path -LiteralPath $envFile -PathType Leaf) {
            foreach ($line in [IO.File]::ReadAllLines($envFile)) {
                if ($line -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
                    Add-PrivateValue $Matches[1] $Matches[2].Trim().Trim('"', "'")
                }
            }
        }
    }
    $command = Get-Command docker.exe -CommandType Application -ErrorAction SilentlyContinue
    if ($command) { $script:Docker = $command.Source }
}

function Invoke-Docker {
    param([string[]]$Arguments, [switch]$Capture, [switch]$AllowFailure)
    $lines = New-Object 'System.Collections.Generic.List[string]'
    # Windows PowerShell treats redirected native stderr as ErrorRecords. Handle
    # exit codes explicitly, rather than treating normal Docker progress as failure.
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $script:Docker @Arguments 2>&1 | ForEach-Object {
            $line = $_.ToString()
            $lines.Add($line)
            if (-not $Capture) { Write-Host (Protect-Output $line) }
        }
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($code -ne 0 -and -not $AllowFailure) {
        if ($Capture) { $lines | ForEach-Object { Write-Host (Protect-Output $_) } }
        throw "Docker command failed (exit $code)."
    }
    return [pscustomobject]@{ ExitCode = $code; Output = ($lines -join "`n") }
}

function Invoke-LocalCompose {
    param([string[]]$Arguments, [switch]$Capture, [switch]$AllowFailure)
    Invoke-Docker -Arguments ($script:ComposeArgs + $Arguments) -Capture:$Capture -AllowFailure:$AllowFailure
}

function Test-LocalDocker {
    if (-not $script:Docker) {
        Write-Host 'Docker is not installed or is not on PATH.'
        Write-Host 'Install/start Docker Desktop, then reopen this launcher.'
        return $false
    }
    $version = Invoke-Docker -Arguments @('--version') -Capture -AllowFailure
    $compose = Invoke-Docker -Arguments @('compose', 'version') -Capture -AllowFailure
    $engine = Invoke-Docker -Arguments @('info', '--format', '{{.OSType}}') -Capture -AllowFailure
    if ($engine.ExitCode -ne 0) {
        Write-Host 'Docker is not running.'
        Write-Host 'Please start Docker Desktop and wait until the engine is ready.'
        return $false
    }
    if ($version.ExitCode -ne 0 -or $compose.ExitCode -ne 0) {
        Write-Host 'Docker Compose is unavailable. Enable/update Docker Desktop and try again.'
        return $false
    }
    if ($engine.Output.Trim() -ne 'linux') {
        Write-Host 'This stack requires Linux containers. Switch Docker Desktop to Linux containers.'
        return $false
    }
    Write-Host (Protect-Output $version.Output)
    Write-Host (Protect-Output $compose.Output)
    return $true
}

function Read-LocalConfiguration {
    param([switch]$RequireLiveConfiguration)
    foreach ($file in ($script:ComposeFiles + @($script:EnvironmentFile))) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            throw "Required configuration file is missing: $file`nSee docs/DEPLOYMENT_DOCKER.md for the existing local setup."
        }
    }
    # --quiet validates without printing interpolated credentials.
    $null = Invoke-LocalCompose -Arguments @('config', '--quiet')
    $resolved = Invoke-LocalCompose -Arguments @('config', '--format', 'json') -Capture
    try { $config = $resolved.Output | ConvertFrom-Json }
    catch { throw 'Unable to read the validated Compose configuration; its contents were not displayed.' }
    foreach ($service in $config.services.PSObject.Properties) {
        if ($service.Value.PSObject.Properties['environment']) {
            foreach ($entry in $service.Value.environment.PSObject.Properties) {
                Add-PrivateValue $entry.Name ([string]$entry.Value)
            }
        }
    }
    if (@(Compare-Object $script:Services @($config.services.PSObject.Properties.Name)).Count -ne 0) {
        throw 'Compose services differ from the validated six-service local stack.'
    }
    if ([string]$config.services.api.environment.APP_ORIGIN -ne $script:DashboardUrl -or $config.name -ne $script:Project) {
        throw 'Compose origin or project does not match the selected local mode.'
    }
    foreach ($service in @('api', 'worker')) {
        $settings = $config.services.$service.environment
        $expectedDiscovery = if ($script:Mode -eq 'Live') { 'google_places_new' } else { 'offline' }
        if ($settings.LOCAL_RUN_MODE -ne $script:ExpectedMode -or $settings.DISCOVERY_MODE -ne $expectedDiscovery) {
            throw 'Compose provider does not match the selected local mode.'
        }
        if ($RequireLiveConfiguration -and $script:Mode -eq 'Live' -and -not $settings.GOOGLE_PLACES_NEW_API_KEY) {
            throw 'Google Places API (New) is not configured. Set the existing .env discovery key; no fixture fallback is available.'
        }
        if ($script:Mode -eq 'OfflineTest' -and $settings.GOOGLE_PLACES_NEW_API_KEY) {
            throw 'Offline containers must not receive paid discovery credentials.'
        }
    }
    $expectedVolume = if ($script:Mode -eq 'Live') { 'leadpro-phase4a2_pgdata' } else { 'leadpro-offline-test_pgdata' }
    if ($config.volumes.pgdata.name -ne $expectedVolume) { throw 'PostgreSQL volume does not match the selected mode.' }
    $script:ResolvedVolumes = $config.volumes
    Write-Host ('Mode: ' + $script:Title + ' | Project: ' + $script:Project)
    Write-Host ('Compose: ' + (($script:ComposeFiles | ForEach-Object { Split-Path -Leaf $_ }) -join ' + '))
    Write-Host ('PostgreSQL volume: ' + $expectedVolume)
    if ($RequireLiveConfiguration) {
        if ($script:Mode -eq 'Live') { Write-Host 'Google Places New: configured (authorization verified by the first search request)' }
        Write-Host 'PostgreSQL: configured'
        Write-Host 'Redis: configured'
        Write-Host 'CamoFox: configured'
        Write-Host 'Session secret: configured'
    }
}

function Get-LocalStates {
    $result = Invoke-LocalCompose -Arguments @('ps', '--all', '--format', 'json') -Capture
    if (-not $result.Output.Trim()) { return @() }
    # Compose versions emit either a JSON array or one JSON object per line.
    if ($result.Output.TrimStart().StartsWith('[')) { return @($result.Output | ConvertFrom-Json) }
    return @($result.Output -split "`n" | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
}

function Show-LocalDiagnostics {
    try {
        Write-Host 'Current service status:'
        $null = Invoke-LocalCompose -Arguments @('ps', '--all') -AllowFailure
        Write-Host 'Recent API / worker / CamoFox diagnostics (redacted):'
        $null = Invoke-LocalCompose -Arguments @('logs', '--no-color', '--tail', '20', 'api', 'worker', 'camofox') -AllowFailure
    } catch { Write-Host 'Docker diagnostics are unavailable.' }
}
