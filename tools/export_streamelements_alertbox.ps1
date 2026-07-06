param(
    [string]$BaseUrl = "",
    [string]$Endpoint = "",
    [string]$Token = "",
    [string]$InstallId = "",
    [string]$Channel = "",
    [string]$Listener = "cheer-latest",
    [string]$OutputDir = "dist\streamer-alertbox",
    [switch]$OpenFolder
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Get-DotEnvValue {
    param([string]$Name)

    foreach ($file in @(".env", ".env.example")) {
        if (-not (Test-Path -LiteralPath $file)) {
            continue
        }
        foreach ($line in Get-Content -LiteralPath $file) {
            $trimmed = $line.Trim()
            if (-not $trimmed -or $trimmed.StartsWith("#")) {
                continue
            }
            $parts = $trimmed -split "=", 2
            if ($parts.Count -eq 2 -and $parts[0] -eq $Name) {
                return $parts[1].Trim().Trim('"')
            }
        }
    }

    return ""
}

if (-not $BaseUrl) {
    $BaseUrl = Get-DotEnvValue "TTSMODACHI_ALERTS_PUBLIC_BASE_URL"
}

if (-not $BaseUrl) {
    $BaseUrl = Get-DotEnvValue "TTSMODACHI_STREAM_PUBLIC_BASE_URL"
}

if (-not $Token) {
    $Token = Get-DotEnvValue "TTSMODACHI_ALERTS_SHARED_SECRET"
}

if (-not $Token) {
    $Token = Get-DotEnvValue "TTSMODACHI_STREAM_SE_SECRET"
}

if (-not $InstallId) {
    $InstallId = Get-DotEnvValue "TTSMODACHI_ALERTS_INSTALL_ID"
}

if (-not $InstallId) {
    $InstallId = Get-DotEnvValue "TTSMODACHI_STREAM_SE_INSTALL_ID"
}

if (-not $Channel) {
    $Channel = Get-DotEnvValue "TTSMODACHI_ALERTS_CHANNEL"
}

if (-not $Channel) {
    $Channel = Get-DotEnvValue "TTSMODACHI_STREAM_SE_CHANNEL"
}

if (-not $InstallId) {
    $generatedId = [guid]::NewGuid().ToString("N")
    $InstallId = "se-" + $generatedId.Substring(0, 16)
}

if (-not $Endpoint -and $BaseUrl) {
    $Endpoint = $BaseUrl.TrimEnd("/") + "/api/alerts/streamelements"
}

if (-not $Endpoint) {
    Write-Host ""
    Write-Host "Need the hosted alerts URL first."
    Write-Host "Example:"
    Write-Host ".\make-alertbox-tts.bat -BaseUrl https://your-alerts-domain.example -InstallId streamer-name"
    Write-Host ""
    exit 1
}

if ($Endpoint -notmatch "^https://" -and $Endpoint -notmatch "^http://(127\.0\.0\.1|localhost)(:\d+)?/") {
    Write-Warning "StreamElements overlays are HTTPS pages, so a public hosted endpoint should use https://"
}

$htmlPath = Join-Path $root "streamelements\alertbox\ttsmodachi-alertbox.html"
$jsPath = Join-Path $root "streamelements\alertbox\ttsmodachi-alertbox.js"
if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    $resolvedOutputDir = $OutputDir
} else {
    $resolvedOutputDir = Join-Path $root $OutputDir
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

$html = Get-Content -Raw -LiteralPath $htmlPath
$js = Get-Content -Raw -LiteralPath $jsPath
$js = $js.Replace("%%TTSMODACHI_ENDPOINT%%", $Endpoint)
$js = $js.Replace("%%TTSMODACHI_TOKEN%%", $Token)
$js = $js.Replace("%%TTSMODACHI_INSTALL_ID%%", $InstallId)
$js = $js.Replace("%%TTSMODACHI_CHANNEL%%", $Channel)
$js = $js.Replace("%%TTSMODACHI_LISTENER%%", $Listener)

$outHtml = Join-Path $resolvedOutputDir "ttsmodachi-alertbox-html.txt"
$outJs = Join-Path $resolvedOutputDir "ttsmodachi-alertbox-js.txt"
$readmePath = Join-Path $resolvedOutputDir "README.txt"

Set-Content -LiteralPath $outHtml -Value $html -Encoding UTF8
Set-Content -LiteralPath $outJs -Value $js -Encoding UTF8
Set-Content -LiteralPath $readmePath -Encoding UTF8 -Value @"
TTSmodachi StreamElements AlertBox custom TTS

This uses the streamer's existing StreamElements AlertBox queue.

1. Open the StreamElements overlay the streamer already uses.
2. Open the AlertBox widget.
3. Open the Twitch bits/cheer alert settings.
4. Enable Custom Code for that alert.
5. Append ttsmodachi-alertbox-html.txt to the HTML tab.
6. Append ttsmodachi-alertbox-js.txt to the JS tab.
7. Keep the normal alert sound enabled if you want it before TTS.
8. Disable any existing non-Tomodachi TTS for bits.
9. Set the alert duration long enough for TTS, such as 20 seconds.
10. Save the overlay and send a test cheer/bit event.

Endpoint:
$Endpoint

Install ID:
$InstallId

Listener:
$Listener
"@

Write-Host ""
Write-Host "Streamer AlertBox code exported:"
Write-Host $outHtml
Write-Host $outJs
Write-Host "Install ID:"
Write-Host $InstallId
Write-Host ""
Write-Host "Append the HTML and JS into the StreamElements AlertBox custom code tabs."

if ($OpenFolder) {
    Start-Process $resolvedOutputDir
}
