param(
    [string]$TaskName = "YouTubeAgentV2-Daily",
    [string]$Time = "19:30"
)

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Pipeline = Join-Path $Root "daily_pipeline.py"

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Run: py -3.11 -m venv .venv; .\.venv\Scripts\python -m pip install -e ."
}

$Action = New-ScheduledTaskAction -Execute $Python -Argument ('"{0}" run-once' -f $Pipeline) -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Safe daily YouTube Shorts pipeline" -Force
Write-Host "Installed $TaskName for $Time. Publishing remains controlled by config.toml."
