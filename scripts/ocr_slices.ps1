# Run Windows built-in OCR over the image slices.
# Usage (from pwsh):
#   $env:OCR_ROOT = 'F:\<workspace>'
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\ocr_slices.ps1
#
# IMPORTANT: keep this file ASCII-only, and take all paths from environment
# variables. Windows PowerShell 5.1 reads .ps1 as ANSI (GBK here), so any
# non-ASCII literal -- including a path like F:\<chinese> -- gets corrupted and
# the script breaks. Env vars are passed as UTF-16 by the OS, so they are safe.
#
# Also: PowerShell 7 (pwsh) removed the WinRT type loader, so this must run
# under Windows PowerShell 5.1.

$ErrorActionPreference = 'Stop'
$root = $env:OCR_ROOT
if (-not $root) { throw 'OCR_ROOT env var is not set' }
if (-not (Test-Path $root)) { throw "OCR_ROOT does not exist: $root" }
$slicesFile = Join-Path $root '_ocr\slices.txt'
$outFile = Join-Path $root '_ocr\ocr.txt'

Add-Type -AssemblyName System.Runtime.WindowsRuntime

# Grab the AsTask overload for IAsyncOperation<T> to await WinRT async calls.
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and
    $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime] | Out-Null

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $engine) {
    Write-Host '  no OCR for user languages, trying zh-Hans-CN'
    $lang = New-Object Windows.Globalization.Language 'zh-Hans-CN'
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
}
if (-not $engine) { throw 'no OCR language pack available' }

Write-Host ('  OCR language tag : ' + $engine.RecognizerLanguage.LanguageTag)
Write-Host ('  max image side   : ' + [Windows.Media.Ocr.OcrEngine]::MaxImageDimension)

$sb = New-Object System.Text.StringBuilder
# slices.txt is written by Python as UTF-8 WITHOUT BOM, so Get-Content must be
# told the encoding explicitly -- otherwise PS 5.1 assumes ANSI and mangles any
# non-ASCII path inside it.
$slices = Get-Content $slicesFile -Encoding UTF8
foreach ($p in $slices) {
    if (-not (Test-Path $p)) { Write-Host "  skip (missing): $p"; continue }
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($p)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

    [void]$sb.AppendLine('=== SLICE ' + (Split-Path $p -Leaf) + ' ===')
    foreach ($line in $result.Lines) { [void]$sb.AppendLine($line.Text) }

    Write-Host ('  ' + (Split-Path $p -Leaf) + ' -> ' + $result.Lines.Count + ' lines')
    $stream.Dispose()
}

[System.IO.File]::WriteAllText($outFile, $sb.ToString(), [System.Text.Encoding]::UTF8)
Write-Host ('  written: ' + $outFile)
