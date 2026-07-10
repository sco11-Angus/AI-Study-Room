Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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

$mdCount = @(
    Get-ChildItem -LiteralPath "openspec", "docs" -Recurse -Filter "*.md" -File
).Count

if ($mdCount -lt 8) {
    Write-Error "Expected at least 8 project markdown docs, found $mdCount"
    exit 1
}

Write-Output "Smoke test passed: required files present; markdown docs found."
