param(
    [string]$BaseUrl = "",
    [string]$Endpoint = "",
    [string]$Token = "",
    [string]$InstallId = "",
    [string]$OutputDir = "dist\streamer-widget",
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
    Write-Host ".\make-streamer-widget.bat -BaseUrl https://your-alerts-domain.example"
    Write-Host ""
    Write-Host "The streamer does not need Docker. The hosted alert service does."
    exit 1
}

if ($Endpoint -notmatch "^https://" -and $Endpoint -notmatch "^http://(127\.0\.0\.1|localhost)(:\d+)?/") {
    Write-Warning "StreamElements overlays are HTTPS pages, so a public hosted endpoint should use https://"
}

$sourcePath = Join-Path $root "streamelements\ttsmodachi-widget.js"
if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    $resolvedOutputDir = $OutputDir
} else {
    $resolvedOutputDir = Join-Path $root $OutputDir
}
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

$widget = Get-Content -Raw -LiteralPath $sourcePath
$widget = $widget.Replace("%%TTSMODACHI_ENDPOINT%%", $Endpoint)
$widget = $widget.Replace("%%TTSMODACHI_TOKEN%%", $Token)
$widget = $widget.Replace("%%TTSMODACHI_INSTALL_ID%%", $InstallId)

$widgetPath = Join-Path $resolvedOutputDir "ttsmodachi-streamelements-widget.js"
$readmePath = Join-Path $resolvedOutputDir "README.txt"

Set-Content -LiteralPath $widgetPath -Value $widget -Encoding UTF8
Set-Content -LiteralPath $readmePath -Encoding UTF8 -Value @"
TTSmodachi StreamElements widget

1. Open the StreamElements overlay the streamer already uses.
2. Add a Custom Widget.
3. Open the widget editor.
4. Replace the JavaScript with ttsmodachi-streamelements-widget.js.
5. Save the overlay.
6. Send a test cheer/bit event.

Endpoint:
$Endpoint

Install ID:
$InstallId
"@

Write-Host ""
Write-Host "Streamer widget exported:"
Write-Host $widgetPath
Write-Host "Install ID:"
Write-Host $InstallId
Write-Host ""
Write-Host "Paste that JavaScript into the StreamElements Custom Widget."

if ($OpenFolder) {
    Start-Process $resolvedOutputDir
}
