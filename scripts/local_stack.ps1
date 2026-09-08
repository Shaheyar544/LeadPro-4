# Shared, inspected Phase 4A.2 configuration. No alternative Compose project.
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$script:RepoRoot = Split-Path -Parent $PSScriptRoot
$script:ComposeFile = Join-Path $script:RepoRoot 'compose.production.yaml'
$script:EnvironmentFile = Join-Path $script:RepoRoot '.local-integration\stack.env'
$script:CertificateFile = Join-Path $script:RepoRoot '.local-integration\caddy-root.crt'
$script:Services = @('caddy', 'api', 'worker', 'postgres', 'redis', 'camofox')
$script:ComposeArgs = @('compose', '--project-name', 'leadpro-phase4a2', '--env-file',
    $script:EnvironmentFile, '-f', $script:ComposeFile)
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
    Set-Location -LiteralPath $script:RepoRoot
    # Collect values privately before any native diagnostics can be displayed.
    Get-ChildItem Env: | ForEach-Object { Add-PrivateValue $_.Name $_.Value }
    if (Test-Path -LiteralPath $script:EnvironmentFile -PathType Leaf) {
        foreach ($line in [IO.File]::ReadAllLines($script:EnvironmentFile)) {
            if ($line -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
                Add-PrivateValue $Matches[1] $Matches[2].Trim().Trim('"', "'")
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
    foreach ($file in @($script:ComposeFile, $script:EnvironmentFile)) {
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
    $script:DashboardUrl = [string]$config.services.api.environment.APP_ORIGIN
    if ($script:DashboardUrl -ne 'https://localhost:8443') {
        throw 'The Compose origin differs from the validated local Caddy HTTPS address.'
    }
    Write-Host 'Using compose.production.yaml with .local-integration\stack.env (values hidden).'
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
