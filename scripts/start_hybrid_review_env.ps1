[CmdletBinding()]
param(
    [switch]$RebuildPiiPack
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is required. Install and start Docker Desktop, then rerun this script."
}

$pack = Join-Path $root ".benchmark-data/review-pack-pii-v1.13.5"
$reviewerA = Join-Path $pack "pii-tasks-reviewer_a.json"
$reviewerB = Join-Path $pack "pii-tasks-reviewer_b.json"
if ($RebuildPiiPack -or -not (Test-Path $reviewerA) -or -not (Test-Path $reviewerB)) {
    python scripts/build_hybrid_review_pack.py `
        --pii-source .benchmark-data/nemotron-pii-test-1000.jsonl `
        --pii-predictions .benchmark-data/gretel-pii-v114-score-cache.jsonl `
        --pii-limit 500 `
        --output-dir .benchmark-data/review-pack-pii-v1.13.5
    if ($LASTEXITCODE -ne 0) { throw "Unable to build the PII review pack." }
}

New-Item -ItemType Directory -Force -Path .valence-data/label-studio | Out-Null
docker compose -f docker-compose.review.yml up -d
if ($LASTEXITCODE -ne 0) { throw "Label Studio did not start." }

$ready = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    & curl.exe --fail --silent --show-error --max-time 2 --output NUL http://127.0.0.1:8081/user/login/
    if ($LASTEXITCODE -eq 0) {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 2
}
if (-not $ready) {
    docker compose -f docker-compose.review.yml logs --tail 40
    throw "Label Studio did not become reachable on localhost:8081."
}

Write-Output "Label Studio is ready at http://127.0.0.1:8081"
Write-Output "Reviewer A import: $reviewerA"
Write-Output "Reviewer B import: $reviewerB"
Write-Output "PII configuration: $root/review/label-studio/pii-config.xml"
Write-Output "Follow docs/HYBRID_HUMAN_REVIEW.md to create the two blind PII projects."
