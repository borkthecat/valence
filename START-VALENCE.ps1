param([switch]$NoBrowser)

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

function Invoke-DockerWithTimeout {
  param(
    [string[]]$Arguments,
    [int]$TimeoutSeconds,
    [string]$Phase
  )

  $LogRoot = Join-Path $env:TEMP "valence-startup"
  New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
  $Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $StdoutPath = Join-Path $LogRoot "$Stamp-$Phase.out.log"
  $StderrPath = Join-Path $LogRoot "$Stamp-$Phase.err.log"
  $Job = Start-Job -ArgumentList (,$Arguments), $StdoutPath, $StderrPath, $Root -ScriptBlock {
    param($DockerArguments, $Stdout, $Stderr, $WorkingDirectory)
    Set-Location $WorkingDirectory
    & docker @DockerArguments 1> $Stdout 2> $Stderr
    $LASTEXITCODE
  }
  $CompletedJob = Wait-Job -Job $Job -Timeout $TimeoutSeconds
  if ($null -eq $CompletedJob) {
    Stop-Job -Job $Job -ErrorAction SilentlyContinue
    Remove-Job -Job $Job -Force -ErrorAction SilentlyContinue
    Show-SetupHelp "Docker $Phase timed out" "Valence stopped Docker after $TimeoutSeconds seconds so startup could not run indefinitely." "Diagnostic logs: $LogRoot"
    exit 1
  }
  $ExitCode = Receive-Job -Job $Job | Select-Object -Last 1
  Remove-Job -Job $Job -Force
  if ($ExitCode -ne 0) {
    Show-SetupHelp "Docker $Phase failed" "Docker returned exit code $ExitCode while running the $Phase phase." "Diagnostic logs: $LogRoot"
    exit 1
  }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Show-SetupHelp "Docker Desktop is required" "Valence runs its local gateway and verifier in Docker so the release can start safely on a clean machine." "Docker was not found on this computer."
  exit 1
}

try {
  Invoke-DockerWithTimeout -Arguments @("info") -TimeoutSeconds 20 -Phase "engine-check"
} catch {
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

$ComposeArgs = $ContextArgs + @("compose", "-f", "docker-compose.yml", "-f", "docker-compose.local.yml", "--env-file", ".env.example")
Invoke-DockerWithTimeout -Arguments ($ComposeArgs + @("build")) -TimeoutSeconds 480 -Phase "build"
Invoke-DockerWithTimeout -Arguments ($ComposeArgs + @("up", "-d", "--remove-orphans")) -TimeoutSeconds 120 -Phase "startup"

$Ready = $false
$Deadline = (Get-Date).AddSeconds(90)
do {
  Start-Sleep -Seconds 2
  try {
    $Health = Invoke-RestMethod -Uri "http://localhost:8080/healthz" -TimeoutSec 3
    if ($Health.status -eq "ok") {
      $Ready = $true
      break
    }
  } catch {
  }
} while ((Get-Date) -lt $Deadline)

if (-not $Ready) {
  Show-SetupHelp "Valence health check timed out" "Containers started, but the gateway did not become healthy within 90 seconds." "Run logs are available in Docker Desktop."
  exit 1
}

Write-Host ""
Write-Host "Valence is running."
Write-Host "Gateway health: http://localhost:8080/healthz"
Write-Host "Valence dashboard: http://localhost:8090/"
Write-Host "Stage 5 API dashboard: http://localhost:8090/docs"
Write-Host "Metrics: curl.exe -H `"x-valence-key: replace-with-a-random-32-plus-character-secret`" http://localhost:8080/metrics"
Write-Host ""
if (-not $NoBrowser) {
  Write-Host "Opening the Valence dashboard..."
  Start-Process "http://localhost:8090/"
}
