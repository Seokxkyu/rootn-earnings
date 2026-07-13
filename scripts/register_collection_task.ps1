<#
.SYNOPSIS
  Registers the CapIQ daily pipeline (collect -> summarize -> send) as a
  Windows scheduled task.

.EXAMPLE
  .\register_collection_task.ps1
  .\register_collection_task.ps1 -Times "07:30","13:00" -ExecutionMinutes 60
  .\register_collection_task.ps1 -PythonPath "C:\path\to\python.exe" -DryRun
  .\register_collection_task.ps1 -Unregister
#>
param(
    [switch]$Unregister,
    [string[]]$Times = @("07:30"),
    [int]$ExecutionMinutes = 30,
    [string]$PythonPath = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$taskName = "CapIQ Daily Pipeline"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pipelinePath = Join-Path $PSScriptRoot "run_daily_pipeline.py"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "Removed scheduled task: $taskName"
    return
}

function Resolve-PipelinePython {
    param([string]$RequestedPath)

    # run_daily_pipeline은 같은 Python으로 collect(Playwright)와 summarize를
    # subprocess 실행하므로, Playwright가 설치된 런타임이어야 한다.
    $candidates = @()
    if ($RequestedPath) {
        $candidates += $RequestedPath
    }
    if ($env:CAPIQ_PYTHON) {
        $candidates += $env:CAPIQ_PYTHON
    }
    # 프로젝트 .venv -> 시스템 python 순. Codex 번들 런타임은 환경 정리 시
    # 사라질 수 있어 후보에서 제외한다(시스템 python에 이미 모든 의존성이 있음).
    $candidates += Join-Path $projectRoot ".venv\Scripts\python.exe"

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $candidates += $pythonCommand.Source
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }

        # cmd로 감싸 stdout/stderr를 완전히 버리고 ERRORLEVEL만 받는다.
        # (PowerShell 5.1에서 native exe의 stderr를 직접 리다이렉트하면
        #  NativeCommandError로 래핑돼 ErrorActionPreference=Stop에서 죽는다.)
        $exit = (& cmd /c "`"$candidate`" -c `"import playwright`" >nul 2>nul & echo %ERRORLEVEL%").Trim()
        if ($exit -eq "0") {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "No Python runtime with Playwright was found. Pass -PythonPath or set CAPIQ_PYTHON."
}

if (-not (Test-Path -LiteralPath $pipelinePath -PathType Leaf)) {
    throw "Pipeline script not found: $pipelinePath"
}

$python = Resolve-PipelinePython -RequestedPath $PythonPath
$actionArgs = "`"$pipelinePath`""

if ($DryRun) {
    Write-Output "Task: $taskName"
    Write-Output "Python: $python"
    Write-Output "Script: $pipelinePath"
    Write-Output "Working directory: $projectRoot"
    Write-Output "Daily times: $($Times -join ', ')"
    Write-Output "Execution time limit: $ExecutionMinutes min"
    return
}

$action = New-ScheduledTaskAction -Execute $python -Argument $actionArgs -WorkingDirectory $projectRoot
$triggers = $Times | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes $ExecutionMinutes) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $triggers `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Output "Registered scheduled task: $taskName"
Write-Output "Daily times: $($Times -join ', ')  |  Execution limit: $ExecutionMinutes min"
Write-Output "Verify with: Get-ScheduledTask -TaskName '$taskName'"
