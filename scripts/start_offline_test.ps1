param([ValidateRange(1,300)][int]$TimeoutSeconds=120, [switch]$NoBrowser)
& (Join-Path $PSScriptRoot 'start_stack.ps1') -Mode OfflineTest -TimeoutSeconds $TimeoutSeconds -NoBrowser:$NoBrowser
exit $LASTEXITCODE
