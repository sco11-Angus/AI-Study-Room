param(
    [int]$CameraId = 6,
    [string]$StreamKey = "cam6",
    [string]$RtmpServer = "49.233.71.82",
    [int]$RtmpPort = 9090,
    [string]$DatabaseUri = "",
    [string]$ModelDir = "C:\AIStudyRoomModels"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not $DatabaseUri) {
    $localDb = Join-Path $repoRoot "backend\local_e2e.db"
    $DatabaseUri = "sqlite:///" + $localDb.Replace("\", "/")
}

$requiredModels = @(
    "shape_predictor_68_face_landmarks.dat",
    "dlib_face_recognition_resnet_model_v1.dat",
    "yolov8n.pt"
)
foreach ($name in $requiredModels) {
    if (-not (Test-Path (Join-Path $ModelDir $name))) {
        throw "Missing model: $(Join-Path $ModelDir $name)"
    }
}

$streamUrl = "rtmp://$RtmpServer`:$RtmpPort/live/$StreamKey"
$env:DATABASE_URI = $DatabaseUri
$env:MODEL_DIR = $ModelDir
$env:STREAM_CAMERA_ID = "$CameraId"
$env:CAMERA_ID = "$CameraId"
$env:STREAM_URLS = $streamUrl
$env:STREAM_LOCAL_CAMERA = ""
$env:STREAM_NAME = ""
$env:STREAM_URL = ""

Write-Host "Camera ID: $CameraId" -ForegroundColor Cyan
Write-Host "RTMP source: $streamUrl" -ForegroundColor Cyan
Write-Host "Database: $DatabaseUri" -ForegroundColor Cyan
Write-Host "Model directory: $ModelDir" -ForegroundColor Cyan

& python .\backend\run.py
