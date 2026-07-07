param(
    [string]$ServerHost = "49.233.71.82",
    [int]$RtmpPort = 9090,
    [int]$HttpFlvPort = 8080,
    [int]$BackendPort = 5000,
    [string]$StreamName = "test",
    [int]$SampleCount = 3,
    [int]$TimeoutSec = 5,
    [switch]$AutoTuneLocalConfig
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$colors = @{
    Title = "Cyan"
    Section = "Magenta"
    Info = "White"
    Success = "Green"
    Warning = "Yellow"
    Error = "Red"
}

$script:Recommendations = New-Object System.Collections.Generic.List[string]

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host "========================================" -ForegroundColor $colors.Title
    Write-Host "  $Text" -ForegroundColor $colors.Section
    Write-Host "========================================" -ForegroundColor $colors.Title
}

function Write-Info {
    param([string]$Text, [string]$Color = "White")
    Write-Host "  $Text" -ForegroundColor $Color
}

function Add-Recommendation {
    param([string]$Text)
    if (-not [string]::IsNullOrWhiteSpace($Text) -and -not $script:Recommendations.Contains($Text)) {
        $script:Recommendations.Add($Text)
    }
}

function Measure-TcpConnect {
    param(
        [string]$RemoteHost,
        [int]$Port,
        [int]$Count = 3,
        [int]$TimeoutMs = 3000
    )

    $samples = @()
    for ($i = 0; $i -lt $Count; $i++) {
        $client = New-Object System.Net.Sockets.TcpClient
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        try {
            $async = $client.BeginConnect($RemoteHost, $Port, $null, $null)
            if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs)) {
                throw "timeout"
            }
            $client.EndConnect($async)
            $sw.Stop()
            $samples += [math]::Round($sw.Elapsed.TotalMilliseconds, 2)
        } catch {
            $samples += $null
        } finally {
            $client.Close()
        }
    }

    $okSamples = @($samples | Where-Object { $_ -ne $null })
    [pscustomobject]@{
        Host = $RemoteHost
        Port = $Port
        SuccessCount = $okSamples.Count
        TotalCount = $Count
        AvgMs = if ($okSamples.Count) { [math]::Round((($okSamples | Measure-Object -Average).Average), 2) } else { $null }
        MinMs = if ($okSamples.Count) { ($okSamples | Measure-Object -Minimum).Minimum } else { $null }
        MaxMs = if ($okSamples.Count) { ($okSamples | Measure-Object -Maximum).Maximum } else { $null }
    }
}

function Measure-HttpFirstByte {
    param(
        [string]$Url,
        [int]$Count = 3,
        [int]$TimeoutMs = 5000
    )

    $samples = @()
    $contentType = $null

    for ($i = 0; $i -lt $Count; $i++) {
        try {
            $request = [System.Net.HttpWebRequest]::Create($Url)
            $request.Method = "GET"
            $request.Timeout = $TimeoutMs
            $request.ReadWriteTimeout = $TimeoutMs
            $request.AllowReadStreamBuffering = $false
            $request.KeepAlive = $false

            $sw = [System.Diagnostics.Stopwatch]::StartNew()
            $response = $request.GetResponse()
            $stream = $response.GetResponseStream()
            $buffer = New-Object byte[] 1
            [void]$stream.Read($buffer, 0, 1)
            $sw.Stop()

            $contentType = $response.ContentType
            $samples += [math]::Round($sw.Elapsed.TotalMilliseconds, 2)

            $stream.Close()
            $response.Close()
        } catch {
            $samples += $null
        }
    }

    $okSamples = @($samples | Where-Object { $_ -ne $null })
    [pscustomobject]@{
        Url = $Url
        SuccessCount = $okSamples.Count
        TotalCount = $Count
        AvgMs = if ($okSamples.Count) { [math]::Round((($okSamples | Measure-Object -Average).Average), 2) } else { $null }
        MinMs = if ($okSamples.Count) { ($okSamples | Measure-Object -Minimum).Minimum } else { $null }
        MaxMs = if ($okSamples.Count) { ($okSamples | Measure-Object -Maximum).Maximum } else { $null }
        ContentType = $contentType
    }
}

function Get-NginxStat {
    param(
        [string]$Url,
        [int]$TimeoutMs = 5000
    )

    try {
        $request = [System.Net.HttpWebRequest]::Create($Url)
        $request.Method = "GET"
        $request.Timeout = $TimeoutMs
        $request.ReadWriteTimeout = $TimeoutMs
        $response = $request.GetResponse()
        $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
        $xmlText = $reader.ReadToEnd()
        $reader.Close()
        $response.Close()

        [xml]$xml = $xmlText
        return $xml
    } catch {
        return $null
    }
}

function Get-StreamEntry {
    param(
        [xml]$StatXml,
        [string]$ExpectedStreamName
    )

    if (-not $StatXml) { return $null }

    $applications = @($StatXml.rtmp.server.application)
    foreach ($app in $applications) {
        $streams = @($app.live.stream)
        foreach ($stream in $streams) {
            if ($stream.name -eq $ExpectedStreamName) {
                return $stream
            }
        }
    }

    return $null
}

function Invoke-LocalConfigTune {
    param([string]$ConfigPath)

    if (-not (Test-Path $ConfigPath)) {
        Write-Info -Text "Local nginx.conf not found, skip auto tune" -Color "Yellow"
        return
    }

    $raw = Get-Content -Path $ConfigPath -Raw -Encoding UTF8
    $updated = $raw

    if ($updated -notmatch '(?m)^\s*sendfile\s+off;') {
        $updated = $updated -replace 'http\s*\{', ('http {' + "`r`n" + '    sendfile off;')
    }
    if ($updated -notmatch '(?m)^\s*tcp_nodelay\s+on;') {
        $updated = $updated -replace 'http\s*\{', ('http {' + "`r`n" + '    tcp_nodelay on;')
    }
    if ($updated -notmatch '(?m)^\s*keepalive_timeout\s+15;') {
        $updated = $updated -replace 'http\s*\{', ('http {' + "`r`n" + '    keepalive_timeout 15;')
    }
    if ($updated -notmatch '(?m)^\s*gop_cache\s+off;') {
        $updated = $updated -replace 'application live \{', ('application live {' + "`r`n" + '            gop_cache off;')
    }

    if ($updated -ne $raw) {
        Set-Content -Path $ConfigPath -Value $updated -Encoding UTF8
        Write-Info -Text ("Local nginx low-latency config updated: {0}" -f $ConfigPath) -Color "Green"
    } else {
        Write-Info -Text "Local nginx config already contains key low-latency settings" -Color "Green"
    }
}

Clear-Host
Write-Section "Nginx Push Pull Latency Monitor"
Write-Info -Text ("Time: {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -Color "Yellow"
Write-Info -Text ("Server: {0}" -f $ServerHost) -Color "Yellow"
Write-Info -Text ("Stream: {0}" -f $StreamName) -Color "Yellow"

$httpFlvUrl = ('http://{0}:{1}/live?app=live&stream={2}' -f $ServerHost, $HttpFlvPort, $StreamName)
$statUrl = ('http://{0}:{1}/stat' -f $ServerHost, $HttpFlvPort)
$backendPreviewUrl = ('http://localhost:{0}/video_feed/{1}' -f $BackendPort, $StreamName)
$localNginxConfig = Join-Path (Split-Path -Parent $PSScriptRoot) "streaming\nginx.conf"

Write-Section "1. Port Connectivity"
$rtmpTcp = Measure-TcpConnect -RemoteHost $ServerHost -Port $RtmpPort -Count $SampleCount
$httpTcp = Measure-TcpConnect -RemoteHost $ServerHost -Port $HttpFlvPort -Count $SampleCount

if ($rtmpTcp.SuccessCount -gt 0) {
    Write-Info -Text ("RTMP({0}) avg connect: {1} ms" -f $RtmpPort, $rtmpTcp.AvgMs) -Color "Green"
} else {
    Write-Info -Text ("RTMP({0}) connect failed" -f $RtmpPort) -Color "Red"
    Add-Recommendation "RTMP port unreachable. Check security group, firewall, and port mapping first."
}

if ($httpTcp.SuccessCount -gt 0) {
    Write-Info -Text ("HTTP-FLV({0}) avg connect: {1} ms" -f $HttpFlvPort, $httpTcp.AvgMs) -Color "Green"
} else {
    Write-Info -Text ("HTTP-FLV({0}) connect failed" -f $HttpFlvPort) -Color "Red"
    Add-Recommendation "HTTP-FLV port unreachable. Check nginx 8080 exposure and reverse proxy config."
}

if ($rtmpTcp.AvgMs -and $rtmpTcp.AvgMs -gt 150) {
    Add-Recommendation "RTMP connect latency is high. Keep encoder and server in the same region and avoid unstable WiFi."
}
if ($httpTcp.AvgMs -and $httpTcp.AvgMs -gt 150) {
    Add-Recommendation "HTTP-FLV connect latency is high. Prefer nearby access or edge distribution/CDN."
}

Write-Section "2. Nginx Stat"
$statXml = Get-NginxStat -Url $statUrl -TimeoutMs ($TimeoutSec * 1000)
$streamEntry = Get-StreamEntry -StatXml $statXml -ExpectedStreamName $StreamName

if ($statXml) {
    Write-Info -Text "/stat reachable" -Color "Green"
    if ($streamEntry) {
        $nclients = [string]$streamEntry.nclients
        $bwIn = [string]$streamEntry.bw_in
        $bwOut = [string]$streamEntry.bw_out
        $timeValue = [string]$streamEntry.time
        Write-Info -Text ("Active stream found: {0}" -f $StreamName) -Color "Green"
        Write-Info -Text ("Clients: {0}" -f $nclients) -Color "White"
        if ($bwIn) { Write-Info -Text ("bw_in: {0}" -f $bwIn) -Color "White" }
        if ($bwOut) { Write-Info -Text ("bw_out: {0}" -f $bwOut) -Color "White" }
        if ($timeValue) { Write-Info -Text ("uptime(ms): {0}" -f $timeValue) -Color "White" }

        if ($nclients -and [int]$nclients -gt 5) {
            Add-Recommendation "Concurrent viewers are high. Let frontend play HTTP-FLV directly and keep backend pull separate for AI."
        }
    } else {
        Write-Info -Text ("Target stream not found in /stat: {0}" -f $StreamName) -Color "Yellow"
        Add-Recommendation ("Target stream not found. Confirm push URL is rtmp://{0}:{1}/live/{2}" -f $ServerHost, $RtmpPort, $StreamName)
    }
} else {
    Write-Info -Text "/stat unreachable or timed out" -Color "Yellow"
    Add-Recommendation "Expose /stat for runtime monitoring so you can verify publisher status, viewer count, and bandwidth."
}

Write-Section "3. HTTP-FLV First Byte"
$httpFlv = Measure-HttpFirstByte -Url $httpFlvUrl -Count $SampleCount -TimeoutMs ($TimeoutSec * 1000)

if ($httpFlv.SuccessCount -gt 0) {
    Write-Info -Text ("HTTP-FLV avg first-byte: {0} ms" -f $httpFlv.AvgMs) -Color "Green"
    if ($httpFlv.ContentType) {
        Write-Info -Text ("HTTP-FLV content-type: {0}" -f $httpFlv.ContentType) -Color "White"
    }
} else {
    Write-Info -Text "HTTP-FLV first-byte failed" -Color "Red"
    Add-Recommendation "HTTP-FLV pull failed. Check active publisher first, then verify nginx live app and /live route."
}

if ($httpFlv.AvgMs -and $httpFlv.AvgMs -gt 1200) {
    Add-Recommendation "HTTP-FLV first-byte > 1.2s. Set GOP to 1-2s, reduce fps to 15-20, and keep bitrate around 800-1500 kbps."
}
if ($httpFlv.AvgMs -and $httpFlv.AvgMs -gt 2500) {
    Add-Recommendation "HTTP-FLV first-byte > 2.5s. Further reduce resolution to 480p and check for cross-region or weak-network hops."
}

Write-Section "4. Backend Relay First Byte"
$backendRelay = Measure-HttpFirstByte -Url $backendPreviewUrl -Count 1 -TimeoutMs ($TimeoutSec * 1000)

if ($backendRelay.SuccessCount -gt 0) {
    Write-Info -Text ("Flask /video_feed avg first-byte: {0} ms" -f $backendRelay.AvgMs) -Color "Green"
    if ($backendRelay.ContentType) {
        Write-Info -Text ("Backend content-type: {0}" -f $backendRelay.ContentType) -Color "White"
    }
} else {
    Write-Info -Text "Flask /video_feed first-byte failed" -Color "Yellow"
    Add-Recommendation "If frontend playback is okay but Flask relay is slow, keep frontend on HTTP-FLV and reserve Flask MJPEG for preview/debug."
}

if ($httpFlv.AvgMs -and $backendRelay.AvgMs) {
    $extraRelayMs = [math]::Round(($backendRelay.AvgMs - $httpFlv.AvgMs), 2)
    Write-Info -Text ("Backend relay overhead: {0} ms" -f $extraRelayMs) -Color "White"
    if ($extraRelayMs -gt 500) {
        Add-Recommendation "Relay overhead > 500ms. Do not use Flask MJPEG as the main playback path."
    }
}

Write-Section "5. Local Config Check"
if (Test-Path $localNginxConfig) {
    $raw = Get-Content -Path $localNginxConfig -Raw -Encoding UTF8
    $hasGopCacheOff = $raw -match 'gop_cache\s+off;'
    $hasChunkedTransfer = $raw -match 'chunked_transfer_encoding\s+on;'
    $hasSendfileOff = $raw -match 'sendfile\s+off;'
    $hasTcpNoDelay = $raw -match 'tcp_nodelay\s+on;'

    Write-Info -Text ("Local config: {0}" -f $localNginxConfig) -Color "Green"
    Write-Info -Text ("gop_cache off: {0}" -f $(if ($hasGopCacheOff) { 'yes' } else { 'no' })) -Color "White"
    Write-Info -Text ("chunked_transfer_encoding on: {0}" -f $(if ($hasChunkedTransfer) { 'yes' } else { 'no' })) -Color "White"
    Write-Info -Text ("sendfile off: {0}" -f $(if ($hasSendfileOff) { 'yes' } else { 'no' })) -Color "White"
    Write-Info -Text ("tcp_nodelay on: {0}" -f $(if ($hasTcpNoDelay) { 'yes' } else { 'no' })) -Color "White"

    if (-not $hasSendfileOff) {
        Add-Recommendation "Add sendfile off in the http block to reduce buffering side effects for live traffic."
    }
    if (-not $hasTcpNoDelay) {
        Add-Recommendation "Add tcp_nodelay on in the http block to reduce packet waiting time."
    }

    if ($AutoTuneLocalConfig) {
        Invoke-LocalConfigTune -ConfigPath $localNginxConfig
    }
} else {
    Write-Info -Text "Local nginx.conf not found" -Color "Yellow"
}

Write-Section "6. Recommendations"
if ($script:Recommendations.Count -eq 0) {
    Write-Info -Text "No obvious issue found. If latency still feels high, compare GOP, bitrate, and resolution with A/B tests." -Color "Green"
} else {
    foreach ($item in $script:Recommendations) {
        Write-Info -Text ("- {0}" -f $item) -Color "Yellow"
    }
}

Write-Section "7. Suggested Low-Latency Settings"
Write-Info -Text "Resolution: 640x360 or 854x480" -Color "White"
Write-Info -Text "FPS: 15-20" -Color "White"
Write-Info -Text "Bitrate: 800-1500 kbps" -Color "White"
Write-Info -Text "GOP: 1-2 seconds" -Color "White"
Write-Info -Text "Frontend playback: prefer direct HTTP-FLV" -Color "White"
Write-Info -Text "Backend analysis: pull RTMP/RTSP separately" -Color "White"

Write-Section "Run Examples"
Write-Info -Text ".\scripts\collect-info.ps1" -Color "Gray"
Write-Info -Text ".\scripts\collect-info.ps1 -StreamName test -AutoTuneLocalConfig" -Color "Gray"
