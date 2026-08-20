<#
.SYNOPSIS
    Hədəf maşının KompasOS üçün yararlılığını QURAŞDIRMADAN ƏVVƏL yoxlayır.

.DESCRIPTION
    ─────────────────────────────────────────────────────────────────────────
    NİYƏ BU SKRİPT VAR
    ─────────────────────────────────────────────────────────────────────────
    `Setup.exe` özü də imzasız bir `.exe`-dir — yəni Smart App Control (SAC)
    məcburi rejimdə olan maşında QURAŞDIRICI DA açılmır. Bu, ən pis
    ardıcıllıqdır: quraşdırıcı 400 MB faylı mağazaya aparır, kassa PC-sinə
    qoşulur və orada heç nə işə düşmür, səbəbi isə ekranda YAZILMIR
    (SAC istifadəçiyə «davam et» seçimi TƏKLİF ETMİR — bax SEC-027).

    Bu skript `.exe` DEYİL, PowerShell mətnidir — SAC ona toxunmur, yəni
    bloklanan maşında da işləyir və SƏBƏBİ deyir.

    Skript HEÇ NƏ QURAŞDIRMIR, HEÇ NƏ DƏYİŞMİR — yalnız oxuyur.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File check_target_machine.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# KONSOL KODLAŞMASI — Azərbaycan hərfləri üçün MƏCBURİ.
#
# Windows PowerShell 5.1 konsolu defolt olaraq sistem ANSI kod səhifəsindədir
# (mağaza PC-lərində adətən cp1252 və ya cp1251). Onsuz «ə», «ş», «ğ» sual
# işarəsinə çevrilir və məhz ƏN VACİB mətn — Smart App Control izahı —
# oxunmaz hala düşür. Skript yalnız ÖZ çıxışını dəyişir, konsol ayarına
# qalıcı toxunmur.
try {
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
} catch {
    # Yönləndirilmiş çıxışda (fayla/borulara) təyinat alınmaya bilər —
    # bu, yoxlamanın ÖZÜNÜ dayandırmamalıdır.
}

$script:Problems = @()
$script:Warnings = @()

function Write-Check {
    param(
        [string]$Label,
        [ValidateSet('OK', 'XƏTA', 'DİQQƏT')]
        [string]$State,
        [string]$Detail = ''
    )
    $color = switch ($State) {
        'OK'     { 'Green' }
        'DİQQƏT' { 'Yellow' }
        default  { 'Red' }
    }
    Write-Host ('  [{0,-6}] {1}' -f $State, $Label) -ForegroundColor $color
    if ($Detail) { Write-Host ('           ' + $Detail) -ForegroundColor DarkGray }
}

Write-Host ''
Write-Host 'KompasOS — hədəf maşın yoxlaması' -ForegroundColor Cyan
Write-Host '=================================' -ForegroundColor Cyan
Write-Host ''

# ---------------------------------------------------------------------------
# 1. Windows versiyası — Setup `MinVersion=10.0` tələb edir
# ---------------------------------------------------------------------------
$os = Get-CimInstance Win32_OperatingSystem
$build = [int]$os.BuildNumber
if ($build -ge 10240) {
    Write-Check 'Windows versiyası' 'OK' ("$($os.Caption) build $build")
} else {
    Write-Check 'Windows versiyası' 'XƏTA' ("$($os.Caption) build $build — Windows 10 və ya yenisi lazımdır")
    $script:Problems += 'Windows 10-dan köhnədir'
}

# ---------------------------------------------------------------------------
# 2. Arxitektura — `.exe` yalnız x64
# ---------------------------------------------------------------------------
if ($os.OSArchitecture -match '64') {
    Write-Check 'Arxitektura' 'OK' $os.OSArchitecture
} else {
    Write-Check 'Arxitektura' 'XƏTA' ("$($os.OSArchitecture) — 64-bit Windows lazımdır")
    $script:Problems += '32-bit Windows'
}

# ---------------------------------------------------------------------------
# 3. SMART APP CONTROL — ƏN VACİB BƏND
# ---------------------------------------------------------------------------
# `VerifiedAndReputablePolicyState`: 0 = söndürülüb, 1 = MƏCBURİ,
# 2 = qiymətləndirmə rejimi. Açar ümumiyyətlə yoxdursa SAC dəstəklənmir
# (Windows 10) — yəni problem də yoxdur.
$sacPath = 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy'
$sac = $null
try {
    $sac = (Get-ItemProperty -Path $sacPath -Name VerifiedAndReputablePolicyState -ErrorAction Stop).VerifiedAndReputablePolicyState
} catch {
    $sac = $null
}

switch ($sac) {
    1 {
        Write-Check 'Smart App Control' 'XƏTA' 'MƏCBURİ rejim — imzasız KompasOS bu maşında AÇILMAYACAQ'
        $script:Problems += 'Smart App Control məcburi rejimdədir'
    }
    2 {
        Write-Check 'Smart App Control' 'DİQQƏT' 'Qiymətləndirmə rejimi — indi işləyir, sonradan öz-özünə məcburi ola bilər'
        $script:Warnings += 'SAC qiymətləndirmə rejimindədir'
    }
    default {
        Write-Check 'Smart App Control' 'OK' 'Söndürülüb və ya dəstəklənmir'
    }
}

# ---------------------------------------------------------------------------
# 4. `%PROGRAMDATA%` yazıla bilirmi — tətbiq məlumatı oraya düşür
# ---------------------------------------------------------------------------
$dataRoot = Join-Path $env:ProgramData 'KompasOS'
try {
    if (-not (Test-Path $dataRoot)) {
        New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
    }
    $probe = Join-Path $dataRoot ('.probe_' + [Guid]::NewGuid().ToString('N'))
    Set-Content -Path $probe -Value 'probe' -Encoding utf8
    Remove-Item -Path $probe -Force
    Write-Check 'ProgramData yazıla bilir' 'OK' $dataRoot
} catch {
    Write-Check 'ProgramData yazıla bilir' 'XƏTA' $_.Exception.Message
    $script:Problems += 'ProgramData qovluğuna yazmaq mümkün deyil'
}

# ---------------------------------------------------------------------------
# 5. Disk sahəsi — paket ~430 MB, quraşdırma zamanı müvəqqəti sahə də lazımdır
# ---------------------------------------------------------------------------
$systemDrive = (Get-Item $env:SystemDrive).Root
$free = (Get-PSDrive -Name $systemDrive.ToString().Substring(0, 1)).Free
$freeGb = [math]::Round($free / 1GB, 1)
if ($free -gt 2GB) {
    Write-Check 'Boş disk sahəsi' 'OK' "$freeGb GB"
} else {
    Write-Check 'Boş disk sahəsi' 'XƏTA' "$freeGb GB — ən azı 2 GB lazımdır"
    $script:Problems += 'Disk sahəsi çatmır'
}

# ---------------------------------------------------------------------------
# 6. Administrator hüququ — Setup `PrivilegesRequired=admin` tələb edir
# ---------------------------------------------------------------------------
$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if ($identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Check 'Administrator hüququ' 'OK' 'Bu sessiya administratordur'
} else {
    Write-Check 'Administrator hüququ' 'DİQQƏT' 'Setup açılanda UAC soruşacaq — administrator paroluna hazır olun'
    $script:Warnings += 'Cari sessiya administrator deyil'
}

# ---------------------------------------------------------------------------
# NƏTİCƏ
# ---------------------------------------------------------------------------
Write-Host ''
if ($script:Problems.Count -eq 0) {
    Write-Host 'NƏTİCƏ: bu maşında quraşdırmaq OLAR.' -ForegroundColor Green
    if ($script:Warnings.Count -gt 0) {
        Write-Host ('Diqqət ediləsi: ' + ($script:Warnings -join '; ')) -ForegroundColor Yellow
    }
    exit 0
}

Write-Host 'NƏTİCƏ: bu maşında quraşdırmayın.' -ForegroundColor Red
foreach ($problem in $script:Problems) {
    Write-Host ('  - ' + $problem) -ForegroundColor Red
}

if ($script:Problems -contains 'Smart App Control məcburi rejimdədir') {
    Write-Host ''
    Write-Host 'SMART APP CONTROL — NƏ ETMƏLİ:' -ForegroundColor Yellow
    Write-Host '  KompasOS hazırda kod imzalama sertifikatı ilə imzalanmır, SAC isə'
    Write-Host '  imzasız proqramı ÜMUMİYYƏTLƏ işə salmır (istifadəçiyə "davam et"'
    Write-Host '  seçimi təklif olunmur). İki yol var:'
    Write-Host ''
    Write-Host '   1) BAŞQA PC işlədin — Windows 10, ya da Windows 10-dan yüksəldilmiş'
    Write-Host '      Windows 11 maşınlarında SAC söndürülü olur.'
    Write-Host ''
    Write-Host '   2) MÜŞTƏRİ özü SAC-ı söndürsün:'
    Write-Host '      Windows Security > App & browser control > Smart App Control > Off'
    Write-Host '      DİQQƏT: bu, BİRYÖNLÜ əməliyyatdır — SAC-ı geri qaytarmaq üçün'
    Write-Host '      Windows-un təmiz quraşdırılması lazımdır. Qərar müştərinindir,'
    Write-Host '      quraşdırıcı bunu TƏLƏB ETMƏMƏLİDİR.'
}
exit 1
