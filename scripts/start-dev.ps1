param(
  [string]$ApiHost = "127.0.0.1",
  [int]$ApiPort = 8010,
  [int]$DashboardPort = 5174
)

$brainRoot = Split-Path -Parent $PSScriptRoot
$dashboardRoot = Join-Path $brainRoot "dashboard"

Write-Host "Starting Chaster Brain API on $ApiHost`:$ApiPort ..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$brainRoot'; python -m uvicorn app.main:app --reload --host $ApiHost --port $ApiPort"

Write-Host "Starting Chaster Brain Dashboard on port $DashboardPort ..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$dashboardRoot'; npm run dev -- --port $DashboardPort"

Write-Host "Both services launched in new terminals."
