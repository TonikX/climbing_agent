param([Parameter(Mandatory=$true)][string]$Directory)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStreamWithContentType, Windows.Storage.Streams, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
function Await-Operation($Operation, $ResultType) {
    $task = $asTask.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    try { $task.Wait() } catch { throw $task.Exception.Flatten().InnerExceptions[0] }
    return $task.Result
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('en-US'))
if (-not $engine) { throw 'Windows English OCR language is unavailable' }
$groups = Get-ChildItem -LiteralPath (Join-Path $Directory 'images') -Filter '*.jpg' | Group-Object { $_.BaseName.Split('-')[0] }
foreach ($group in $groups) {
    $target = Join-Path $Directory ('page-' + $group.Name + '.csv')
    if (Test-Path -LiteralPath $target) { continue }
    $rows = @()
    foreach ($image in $group.Group) {
        $parts = $image.BaseName.Split('-')
        $file = Await-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($image.FullName)) ([Windows.Storage.StorageFile])
        $stream = Await-Operation ($file.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
        try {
            $decoder = Await-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
            $bitmap = Await-Operation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
            try {
                $result = Await-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
                foreach ($line in $result.Lines) {
                    $rects = @($line.Words | ForEach-Object { $_.BoundingRect })
                    if (-not $rects.Count) { continue }
                    $x = ($rects.X | Measure-Object -Minimum).Minimum
                    $y = ($rects.Y | Measure-Object -Minimum).Minimum
                    $right = ($rects | ForEach-Object { $_.X + $_.Width } | Measure-Object -Maximum).Maximum
                    $bottom = ($rects | ForEach-Object { $_.Y + $_.Height } | Measure-Object -Maximum).Maximum
                    $zone = if ($y -lt $bitmap.PixelHeight * .16) { 'header' } else { 'table' }
                    # Confidence is unavailable in Windows OCR, never manufacture it.
                    $rows += [pscustomobject]@{page=[int]$parts[0]; image=$parts[1]; panel=$parts[2]; zone=$zone;
                        x=[math]::Round($x); y=[math]::Round($y); width=[math]::Round($right-$x);
                        height=[math]::Round($bottom-$y); text=$line.Text; confidence=0}
                }
            } finally { $bitmap.Dispose() }
        } finally { $stream.Dispose() }
    }
    $temporary = $target + '.part'
    if ($rows.Count) { $rows | Export-Csv -LiteralPath $temporary -NoTypeInformation -Encoding UTF8 }
    else { 'page,image,panel,zone,x,y,width,height,text,confidence' | Set-Content -LiteralPath $temporary -Encoding UTF8 }
    Move-Item -LiteralPath $temporary -Destination $target -Force
    Write-Output ('Page ' + [int]$group.Name + ': ' + $rows.Count + ' OCR lines')
}
