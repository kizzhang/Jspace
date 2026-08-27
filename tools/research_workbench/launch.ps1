param(
    [string]$Workspace = $env:JSPACE_WORKSPACE,
    [int]$Port = 7333,
    [switch]$NoBrowser,
    [switch]$Background
)

$workbenchRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceRoot = if ([string]::IsNullOrWhiteSpace($Workspace)) {
    (Resolve-Path (Join-Path $workbenchRoot "..\..")).Path
} else {
    (Resolve-Path -LiteralPath $Workspace).Path
}
$arguments = @(
    (Join-Path $workbenchRoot "app.py"),
    "--workspace", $workspaceRoot,
    "--port", $Port
)
if ($NoBrowser) { $arguments += "--no-browser" }

if ($Background) {
    $pythonPath = (Get-Command python.exe).Source
    $process = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList $arguments `
        -WorkingDirectory $workspaceRoot `
        -WindowStyle Hidden `
        -PassThru
    Write-Output "科研工作台已在后台启动：http://127.0.0.1:$Port（PID $($process.Id)）"
    exit 0
}

& python @arguments
exit $LASTEXITCODE
