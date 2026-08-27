param(
    [string]$Workspace = $env:JSPACE_WORKSPACE
)

$workbenchRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceRoot = if ([string]::IsNullOrWhiteSpace($Workspace)) {
    (Resolve-Path (Join-Path $workbenchRoot "..\..")).Path
} else {
    (Resolve-Path -LiteralPath $Workspace).Path
}
& python (Join-Path $workbenchRoot "app.py") --workspace $workspaceRoot --sync-only --no-browser
exit $LASTEXITCODE
