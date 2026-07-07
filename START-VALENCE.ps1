$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw "Docker is required. Install Docker Desktop, start it, then run this script again."
}

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
}

$env:VALENCE_VERSION = (Get-Content "VERSION" -Raw).Trim()

$ContextArgs = @()
$Contexts = docker context ls --format "{{.Name}}" 2>$null
if ($Contexts -contains "desktop-linux") {
  $ContextArgs = @("--context", "desktop-linux")
}

docker @ContextArgs compose -f docker-compose.yml -f docker-compose.local.yml --env-file .env.example up --build -d

$Deadline = (Get-Date).AddSeconds(60)
do {
  Start-Sleep -Seconds 2
  try {
    $Health = Invoke-RestMethod -Uri "http://localhost:8080/healthz" -TimeoutSec 3
    if ($Health.status -eq "ok") {
      break
    }
  } catch {
  }
} while ((Get-Date) -lt $Deadline)

Write-Host ""
Write-Host "Valence is running."
Write-Host "Gateway health: http://localhost:8080/healthz"
Write-Host "Valence dashboard: http://localhost:8090/"
Write-Host "Stage 5 API dashboard: http://localhost:8090/docs"
Write-Host "Metrics: curl.exe -H `"x-valence-key: replace-with-a-random-32-plus-character-secret`" http://localhost:8080/metrics"
Write-Host ""
Write-Host "Opening the Valence dashboard..."

Start-Process "http://localhost:8090/"
