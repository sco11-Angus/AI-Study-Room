param(
    [string]$ServerHost = "49.233.71.82",
    [string]$ServerUser = "ubuntu",
    [string]$RemoteRepoPath = "/home/ubuntu/AI-Study-Room",
    [string]$RemoteComposePath = "/home/ubuntu/AI-Study-Room/deploy/docker-compose.yml",
    [string]$RemoteNginxConfigPath = "/home/ubuntu/AI-Study-Room/streaming/nginx.conf",
    [string]$RemoteVideoDir = "/usr/local/rtmp_video",
    [switch]$UseDockerCompose,
    [switch]$UseSystemNginx
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Write-Step {
    param([string]$Text)
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Magenta
    Write-Host "========================================" -ForegroundColor Cyan
}

function Write-Info {
    param([string]$Text, [string]$Color = "White")
    Write-Host "  $Text" -ForegroundColor $Color
}

function Test-CommandExists {
    param([string]$Name)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    return $null -ne $cmd
}

function Invoke-Checked {
    param(
        [string]$Command,
        [string]$ErrorMessage
    )

    Write-Info $Command "Gray"
    Invoke-Expression $Command
    if ($LASTEXITCODE -ne 0) {
        throw $ErrorMessage
    }
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$localConfigPath = Join-Path $projectRoot "streaming\nginx.conf"
$sshOptions = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL"
$remote = "$ServerUser@$ServerHost"

if (-not (Test-Path $localConfigPath)) {
    throw "Local nginx config not found: $localConfigPath"
}

if (-not (Test-CommandExists "ssh")) {
    throw "ssh not found in PATH. Please install OpenSSH client first."
}

if (-not (Test-CommandExists "scp")) {
    throw "scp not found in PATH. Please install OpenSSH client first."
}

Write-Step "Deploy Remote Nginx Config"
Write-Info ("Server: {0}" -f $ServerHost) "Yellow"
Write-Info ("Remote user: {0}" -f $ServerUser) "Yellow"
Write-Info ("Local config: {0}" -f $localConfigPath) "Yellow"
Write-Info "You may be asked for the server password by ssh/scp." "Yellow"

Write-Step "Copy to temp path (avoid CJK encoding issues)"
$tempConfig = Join-Path $env:TEMP "nginx-deploy.conf"
Copy-Item -Path $localConfigPath -Destination $tempConfig -Force
Write-Info ("Temp copy: {0}" -f $tempConfig) "Gray"

Write-Step "Ensure remote directory"
$remoteDir = Split-Path $RemoteNginxConfigPath -Parent
Invoke-Checked `
    -Command ("ssh {0} {1} `"mkdir -p {2}`"" -f $sshOptions, $remote, $remoteDir) `
    -ErrorMessage "Failed to create remote directory: $remoteDir"

Write-Step "Upload nginx.conf"
Invoke-Checked `
    -Command ("scp {0} `"{1}`" `"{2}:{3}`"" -f $sshOptions, $tempConfig, $remote, $RemoteNginxConfigPath) `
    -ErrorMessage "Upload failed. Check server connectivity, password, and remote path."

Write-Step "Ensure video directory"
Invoke-Checked `
    -Command ("ssh {0} {1} `"sudo mkdir -p {2} && sudo chmod 777 {2}`"" -f $sshOptions, $remote, $RemoteVideoDir) `
    -ErrorMessage "Failed to create remote video directory."

$remoteModeDetect = @"
set -e
if command -v docker >/dev/null 2>&1; then
  if docker compose version >/dev/null 2>&1; then
    echo docker_compose_v2
    exit 0
  fi
fi
if command -v docker-compose >/dev/null 2>&1; then
  echo docker_compose_v1
  exit 0
fi
if command -v nginx >/dev/null 2>&1; then
  echo system_nginx
  exit 0
fi
echo unknown
"@

$selectedMode = ""
if ($UseDockerCompose) {
    $selectedMode = "docker"
} elseif ($UseSystemNginx) {
    $selectedMode = "system"
} else {
    Write-Step "Detect Remote Runtime"
    $detectOutput = ssh $sshOptions $remote $remoteModeDetect 2>$null
    $selectedMode = switch -Regex ($detectOutput) {
        "docker_compose_v2" { "docker_v2"; break }
        "docker_compose_v1" { "docker_v1"; break }
        "system_nginx" { "system"; break }
        default { "unknown" }
    }
    Write-Info ("Detected mode: {0}" -f $selectedMode) "Green"
}

if ($UseDockerCompose) {
    $selectedMode = "docker_v2"
}

if ($selectedMode -eq "docker_v2") {
    Write-Step "Reload nginx-rtmp with docker compose"
    $remoteReload = @"
set -e
cd "$RemoteRepoPath"
docker compose -f "$RemoteComposePath" up -d nginx-rtmp
docker compose -f "$RemoteComposePath" ps
"@
    Invoke-Checked `
        -Command ("ssh {0} {1} '{2}'" -f $sshOptions, $remote, $remoteReload.Replace("'", "'\''")) `
        -ErrorMessage "Remote docker compose reload failed."
} elseif ($selectedMode -eq "docker_v1") {
    Write-Step "Reload nginx-rtmp with docker-compose"
    $remoteReload = @"
set -e
cd "$RemoteRepoPath"
docker-compose -f "$RemoteComposePath" up -d nginx-rtmp
docker-compose -f "$RemoteComposePath" ps
"@
    Invoke-Checked `
        -Command ("ssh {0} {1} '{2}'" -f $sshOptions, $remote, $remoteReload.Replace("'", "'\''")) `
        -ErrorMessage "Remote docker-compose reload failed."
} elseif ($selectedMode -eq "system") {
    Write-Step "Validate and reload system nginx"
    $remoteReload = @"
set -e
sudo nginx -t
sudo systemctl reload nginx || sudo service nginx reload
sudo systemctl status nginx --no-pager -n 20 || true
"@
    Invoke-Checked `
        -Command ("ssh {0} {1} '{2}'" -f $sshOptions, $remote, $remoteReload.Replace("'", "'\''")) `
        -ErrorMessage "Remote nginx reload failed."
} else {
    throw "Unable to detect remote runtime. Re-run with -UseDockerCompose or -UseSystemNginx."
}

Write-Step "Remote Smoke Check"
$remoteCheck = @"
set -e
echo "--- ports ---"
(ss -lntp 2>/dev/null || netstat -lntp 2>/dev/null || true) | grep -E ':1935|:8080' || true
echo "--- stat ---"
curl -I -m 5 http://127.0.0.1:8080/stat || true
echo "--- live ---"
curl -I -m 5 'http://127.0.0.1:8080/live?app=live&stream=test' || true
"@
Invoke-Checked `
    -Command ("ssh {0} {1} '{2}'" -f $sshOptions, $remote, $remoteCheck.Replace("'", "'\''")) `
    -ErrorMessage "Remote smoke check failed."

Write-Step "Done"
Write-Info "Remote nginx config has been replaced." "Green"
Write-Info "Next checks:" "Yellow"
Write-Info ("1. Open http://{0}:8080/stat" -f $ServerHost) "White"
Write-Info ("2. Push stream to rtmp://{0}:9090/live/test" -f $ServerHost) "White"
Write-Info ("3. Open http://{0}:8080/live?app=live&stream=test" -f $ServerHost) "White"
