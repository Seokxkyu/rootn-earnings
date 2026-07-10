<#
.SYNOPSIS
  Registers the Capital IQ transcript collector as a Windows scheduled task.

.EXAMPLE
  .\register_collection_task.ps1
  .\register_collection_task.ps1 -Times "07:30","13:00"
  .\register_collection_task.ps1 -PythonPath "C:\path\to\python.exe" -DryRun
  .\register_collection_task.ps1 -Unregister
#>
param(
    [switch]$Unregister,
    [string[]]$Times = @("07:30"),
    [string]$PythonPath = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$taskName = "CapIQ Transcript Collector"
$projectRoot = Split-Path -Parent $PSScriptRoot
$collectorPath = Join-Path $PSScriptRoot "collect_capiq_transcripts.py"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "Removed scheduled task: $taskName"
    return
}

function Resolve-CollectorPython {
    param([string]$RequestedPath)

    $candidates = @()
    if ($RequestedPath) {
        $candidates += $RequestedPath
    }
    if ($env:CAPIQ_PYTHON) {
        $candidates += $env:CAPIQ_PYTHON
    }
    $candidates += Join-Path $projectRoot ".venv\Scripts\python.exe"
    $candidates += Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $candidates += $pythonCommand.Source
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }

        & $candidate -c "import playwright" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "No Python runtime with Playwright was found. Pass -PythonPath or set CAPIQ_PYTHON."
}

if (-not (Test-Path -LiteralPath $collectorPath -PathType Leaf)) {
    throw "Collector script not found: $collectorPath"
}

$python = Resolve-CollectorPython -RequestedPath $PythonPath
$actionArgs = "`"$collectorPath`""

if ($DryRun) {
    Write-Output "Task: $taskName"
    Write-Output "Python: $python"
    Write-Output "Script: $collectorPath"
    Write-Output "Working directory: $projectRoot"
    Write-Output "Daily times: $($Times -join ', ')"
    return
}

$action = New-ScheduledTaskAction -Execute $python -Argument $actionArgs -WorkingDirectory $projectRoot
$triggers = $Times | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $triggers `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Output "Registered scheduled task: $taskName"
Write-Output "Daily times: $($Times -join ', ')"
Write-Output "Verify with: Get-ScheduledTask -TaskName '$taskName'"
