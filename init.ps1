Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$requiredFiles = @(
    "AGENTS.md",
    "README.md",
    "feature_list.json",
    "init.sh",
    "init.ps1",
    "init.cmd",
    "PRD.md",
    "openspec/progress/progress.md",
    "openspec/progress/claude-progress.md"
)

foreach ($file in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        Write-Error "Missing required file: $file"
        exit 1
    }
}

$openSpecCmd = Join-Path $PSScriptRoot "node_modules/.bin/openspec.cmd"
if (-not (Test-Path -LiteralPath $openSpecCmd -PathType Leaf)) {
    Write-Error "OpenSpec is not installed. Run 'npm install' from the repository root."
    exit 1
}

& $openSpecCmd validate --all --strict
if ($LASTEXITCODE -ne 0) {
    Write-Error "OpenSpec strict validation failed. Fix the specifications before continuing."
    exit 1
}

$mdCount = @(
    Get-ChildItem -LiteralPath "openspec", "docs" -Recurse -Filter "*.md" -File
).Count

if ($mdCount -lt 8) {
    Write-Error "Expected at least 8 project markdown docs, found $mdCount"
    exit 1
}

Write-Output "Smoke test passed: OpenSpec validation and required project files passed."
