$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Show-SetupHelp {
  param(
    [string]$Title,
    [string]$Message,
    [string]$Detail
  )

  $HelpPath = Join-Path $Root "VALENCE-SETUP-HELP.html"
  $Html = @"
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Valence Setup</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      background: #f5f7fa;
      color: #111827;
      font-family: Aptos, "Segoe UI Variable", "Segoe UI", Arial, sans-serif;
    }
    main {
      width: min(760px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 48px 0;
    }
    section {
      background: #fff;
      border: 1px solid #d9e0ea;
      border-radius: 8px;
      padding: 24px;
    }
    h1 {
      margin: 0 0 10px;
      font-size: 26px;
      letter-spacing: 0;
    }
    p, li {
      color: #475467;
      line-height: 1.55;
    }
    a {
      color: #1f4e79;
      font-weight: 700;
    }
    code {
      background: #eef2f7;
      border-radius: 4px;
      padding: 2px 5px;
    }
  </style>
</head>
<body>
  <main>
    <section>
      <h1>$Title</h1>
      <p>$Message</p>
      <p>$Detail</p>
      <ol>
        <li>Install Docker Desktop from <a href="https://www.docker.com/products/docker-desktop/">docker.com/products/docker-desktop</a>.</li>
        <li>Open Docker Desktop and wait until it says the engine is running.</li>
        <li>Double-click <code>START-VALENCE.cmd</code> again.</li>
      </ol>
    </section>
  </main>
</body>
</html>
"@
  Set-Content -Path $HelpPath -Value $Html -Encoding UTF8
  Start-Process $HelpPath
  Write-Host $Title
  Write-Host $Message
  Write-Host $Detail
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Show-SetupHelp "Docker Desktop is required" "Valence runs its local gateway and verifier in Docker so the release can start safely on a clean machine." "Docker was not found on this computer."
  exit 1
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Show-SetupHelp "Docker Desktop is not running" "Valence found Docker, but the Docker engine is not accepting requests yet." "Start Docker Desktop, wait for it to finish loading, then launch Valence again."
  exit 1
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
