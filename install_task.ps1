<#
.SYNOPSIS
    Registers (or removes) the Task Scheduler entry that runs the notifier in the background.

.EXAMPLE
    .\install_task.ps1              # install, or update an existing install, then start it
    .\install_task.ps1 -Uninstall   # stop it and remove the task
#>
param(
    [string]$PythonW = "$env:USERPROFILE\anaconda3\envs\rerun-notifs\pythonw.exe",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$TaskName = "Rerun Notifier"
$ProjectDir = $PSScriptRoot
$AppDir = Join-Path $env:APPDATA "YouTubeNotifier"
$User = "$env:USERDOMAIN\$env:USERNAME"

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed '$TaskName'. Your settings and state in $AppDir were left alone."
    } else {
        Write-Host "'$TaskName' isn't installed."
    }
    return
}

if (-not (Test-Path $PythonW)) {
    throw "Can't find $PythonW. Create the conda env first, or pass -PythonW <path to pythonw.exe>."
}

# -s ignores the shared %APPDATA%\Python user folder, so only the env's own packages are used.
$action = New-ScheduledTaskAction -Execute $PythonW -Argument "-s main.py" -WorkingDirectory $ProjectDir

# Start when you sign in to Windows. Runs as you, so it can read your %APPDATA% files.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited

# Task Scheduler's defaults would stop the notifier after 3 days and refuse to run it on battery.
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -Priority 7  # 7 = below normal

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "Registered '$TaskName': starts at sign-in using $PythonW"

# Only start it now if setup is finished; otherwise it would just log an error and exit.
$missing = @("config.json", "token.json") | Where-Object { -not (Test-Path (Join-Path $AppDir $_)) }
if ($missing) {
    Write-Host "Not starting yet: missing $($missing -join ', ') in $AppDir."
    Write-Host "Finish setup, then run: Start-ScheduledTask -TaskName '$TaskName'"
    return
}

# -Force on Register doesn't stop a copy that's already running, so restart it to pick up changes.
Stop-ScheduledTask -TaskName $TaskName
Start-ScheduledTask -TaskName $TaskName
Write-Host "Started. Progress is logged to $AppDir\notifier.log"
