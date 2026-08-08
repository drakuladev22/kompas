<#
.SYNOPSIS
    KompasOS üçün müvəqqəti çox-ölçülü .ico faylı yaradır.

.DESCRIPTION
    Müştərinin real loqosu gələnə qədər build-in qırılmaması üçün formatca
    düzgün placeholder ikon yaradır (bax assets/README.md).
    Ölçülər: 16, 32, 48, 256. Rənglər: Deep Navy #0B1D3A + Amber #F5A623.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/generate_placeholder_icon.ps1
#>

Add-Type -AssemblyName System.Drawing

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root 'assets\kompasos.ico'

$sizes = @(16, 32, 48, 256)
$navy  = [System.Drawing.ColorTranslator]::FromHtml('#0B1D3A')
$amber = [System.Drawing.ColorTranslator]::FromHtml('#F5A623')
$pngs = @()

foreach ($s in $sizes) {
    $bmp = New-Object System.Drawing.Bitmap($s, $s, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'
    $g.TextRenderingHint = 'AntiAliasGridFit'
    $g.Clear($navy)

    $pen = New-Object System.Drawing.Pen($amber, [math]::Max(1, $s / 16))
    $g.DrawEllipse($pen, $s * 0.10, $s * 0.10, $s * 0.80, $s * 0.80)

    $font = New-Object System.Drawing.Font('Segoe UI', ($s * 0.50), [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
    $brush = New-Object System.Drawing.SolidBrush($amber)
    $fmt = New-Object System.Drawing.StringFormat
    $fmt.Alignment = 'Center'
    $fmt.LineAlignment = 'Center'
    $g.DrawString('K', $font, $brush, (New-Object System.Drawing.RectangleF(0, 0, $s, $s)), $fmt)
    $g.Dispose()

    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $pngs += , ($ms.ToArray())
    $bmp.Dispose()
    $ms.Dispose()
}

$out = New-Object System.IO.MemoryStream
$bw = New-Object System.IO.BinaryWriter($out)

# ICONDIR
$bw.Write([UInt16]0)               # reserved
$bw.Write([UInt16]1)               # type = icon
$bw.Write([UInt16]$sizes.Count)

# ICONDIRENTRY (16 bayt / şəkil)
$offset = 6 + (16 * $sizes.Count)
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $s = $sizes[$i]
    $data = $pngs[$i]
    $dim = if ($s -ge 256) { 0 } else { $s }   # 256 → 0 (ICO spesifikasiyası)
    $bw.Write([Byte]$dim); $bw.Write([Byte]$dim)
    $bw.Write([Byte]0);    $bw.Write([Byte]0)
    $bw.Write([UInt16]1)               # planes
    $bw.Write([UInt16]32)              # bit depth
    $bw.Write([UInt32]$data.Length)
    $bw.Write([UInt32]$offset)
    $offset += $data.Length
}

foreach ($data in $pngs) { $bw.Write($data) }
$bw.Flush()

[System.IO.File]::WriteAllBytes($target, $out.ToArray())
$bw.Dispose()
$out.Dispose()

Write-Output "Yaradıldı: $target ($((Get-Item $target).Length) bayt, $($sizes.Count) ölçü)"
