<#
.SYNOPSIS
    `.github/workflows/ci.yml`-dəki bütün `dev` mərhələ addımlarını LOKAL icra edir.

.DESCRIPTION
    GitHub Actions-a push etməzdən ƏVVƏL pipeline-ın keçəcəyini yoxlamaq üçün.
    Addımlar YAML-dakı ilə EYNİ ardıcıllıqla və eyni əmrlərlə icra olunur.

    FƏRQLƏR (və niyə):
      * `db-schema` job-u CI-da postgres service container istifadə edir;
        burada mövcud Supabase layihəsinə bağlanır (SB_* mühit dəyişənləri).
      * `gitleaks` GitHub action-dır; burada `git` əsaslı sadə sirr skanı ilə
        əvəzlənir (tam əvəz DEYİL — real gitleaks yalnız CI-da işləyir).
      * `staging-build`/`production-release` yalnız main/tag-da işə düşür,
        ona görə burada icra olunmur.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/ci_local.ps1
#>

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Error "Virtual mühit tapılmadı: $py — əvvəlcə 'python -m venv .venv' icra edin"
}

$script:failed = @()
$script:passed = @()

function Invoke-CiStep {
    param(
        [Parameter(Mandatory)][string] $Job,
        [Parameter(Mandatory)][string] $Name,
        [Parameter(Mandatory)][scriptblock] $Action
    )
    $label = "$Job / $Name"
    Write-Host "`n=== $label ===" -ForegroundColor Cyan
    $started = Get-Date
    try {
        & $Action
        if ($LASTEXITCODE -ne $null -and $LASTEXITCODE -ne 0) {
            throw "çıxış kodu $LASTEXITCODE"
        }
        $seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
        Write-Host ("PASS  {0}  ({1}s)" -f $label, $seconds) -ForegroundColor Green
        $script:passed += $label
    }
    catch {
        Write-Host ("FAIL  {0}  -- {1}" -f $label, $_) -ForegroundColor Red
        $script:failed += $label
    }
}

# --- CI mühiti (ci.yml `env` bloku ilə eyni) --------------------------------
$env:KOMPASOS_ENV = 'DEV'
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'

if (-not $env:KOMPASOS_FERNET_KEY) {
    $env:KOMPASOS_FERNET_KEY = & $py -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
    Write-Host "notice: KOMPASOS_FERNET_KEY yoxdur — birdəfəlik açar yaradıldı" -ForegroundColor Yellow
}
if (-not $env:KOMPASOS_HASH_PEPPER) {
    $env:KOMPASOS_HASH_PEPPER = & $py -c "import secrets; print(secrets.token_hex(32))"
    Write-Host "notice: KOMPASOS_HASH_PEPPER yoxdur — birdəfəlik pepper yaradıldı" -ForegroundColor Yellow
}

# ============================================================================
# job: lint
# ============================================================================
Invoke-CiStep 'lint' 'Ruff — lint' { & $py -m ruff check src tests scripts }
Invoke-CiStep 'lint' 'Ruff — format yoxlaması' { & $py -m ruff format --check src tests scripts }

# ============================================================================
# job: typecheck
# ============================================================================
Invoke-CiStep 'typecheck' 'MyPy — strict' { & $py -m mypy src }

# ============================================================================
# job: test
# ============================================================================
Invoke-CiStep 'test' 'Self-check (--strict)' { & $py -m src.main --strict | Out-Null }
Invoke-CiStep 'test' 'Pytest — unit + coverage qapısı' {
    & $py -m pytest tests/unit `
        --cov=src/domain --cov=src/shared --cov=src/infrastructure/security `
        --cov-report=term-missing --cov-fail-under=85 `
        --junitxml=junit-unit.xml -q
}
Invoke-CiStep 'test' 'Pytest — E2E (pytest-qt)' {
    & $py -m pytest tests/e2e -m e2e --junitxml=junit-e2e.xml -q
}

# ============================================================================
# job: db-schema
# ============================================================================
if ($env:SB_HOST -and $env:SB_REF -and $env:SB_PASSWORD) {
    Invoke-CiStep 'db-schema' 'Sxemi tətbiq et (DEV)' {
        node scripts/db/apply.js database/schema.sql DEV | Out-Null
    }
    Invoke-CiStep 'db-schema' 'İdempotentlik yoxlaması' {
        node scripts/db/apply.js database/schema.sql DEV | Out-Null
    }
    Invoke-CiStep 'db-schema' 'Guard trigger testləri' {
        node scripts/db/apply.js database/tests/test_guards.sql | Out-Null
    }
}
else {
    Write-Host "`n=== db-schema (ATLANDI) ===" -ForegroundColor Yellow
    Write-Host "SB_HOST/SB_REF/SB_PASSWORD təyin edilməyib — DB addımları atlandı" -ForegroundColor Yellow
}

# ============================================================================
# job: security-scan
# ============================================================================
Invoke-CiStep 'security-scan' 'pip-audit' {
    & $py -m pip_audit --requirement requirements.txt --strict --desc
}
Invoke-CiStep 'security-scan' 'İzlənən sirr fayllarını yoxla' {
    $git = (Get-Command git -ErrorAction SilentlyContinue).Source
    if (-not $git) { $git = 'C:\Program Files\Git\cmd\git.exe' }
    $tracked = & $git ls-files
    if ($tracked -contains '.env') { throw '.env repozitoriyada izlənilir' }
    $secrets = $tracked | Where-Object { $_ -match '\.(pfx|p12|pem|key)$' -and $_ -notmatch '\.example$' }
    if ($secrets) { throw "Sertifikat/açar faylı izlənilir: $secrets" }
    Write-Host 'İzlənən sirr faylı tapılmadı.'
}
Invoke-CiStep 'security-scan' 'SBOM yarat (CycloneDX)' {
    & $py -m cyclonedx_py requirements requirements.txt -o sbom.json --output-format json
    if (-not (Test-Path sbom.json)) { throw 'sbom.json yaranmadı' }
}

# ============================================================================
# job: accessibility
# ============================================================================
Invoke-CiStep 'accessibility' 'WCAG AA kontrast' {
    & $py scripts/check_contrast.py --include-high-contrast
}

# ============================================================================
# Yekun
# ============================================================================
Write-Host "`n$('=' * 60)" -ForegroundColor Cyan
Write-Host "CI LOKAL NƏTİCƏ" -ForegroundColor Cyan
Write-Host ('=' * 60) -ForegroundColor Cyan
Write-Host ("Uğurlu: {0}" -f $script:passed.Count) -ForegroundColor Green
if ($script:failed.Count -gt 0) {
    Write-Host ("Uğursuz: {0}" -f $script:failed.Count) -ForegroundColor Red
    $script:failed | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
Write-Host "Bütün dev-mərhələ addımları keçdi." -ForegroundColor Green
exit 0
