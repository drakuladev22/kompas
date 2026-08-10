# RİSK REYESTRİ — cari vəziyyət

> Faza 1 və Faza 2-nin bütün açıq riskləri. Hər sətir ya **BAĞLI** (sübutla),
> ya da aydın sahibi/tarixi olan **AÇIQ** vəziyyətdədir.

**Son yenilənmə:** 2026-08-10 · **Açıq risk sayı: 2** (R7, R8 — hər ikisi
istismar riskidir, kod qüsuru deyil)

---

## Bağlanmış risklər

| # | Risk | Necə bağlandı | Sübut |
|---|---|---|---|
| **R1** | Git yox idi, CI heç vaxt işləməmişdi | Git 2.55 quraşdırıldı, repozitoriya inisializasiya olundu (111 fayl, 25 660 sətir), `.gitattributes` ilə LF normallaşdırması | `git log` · `scripts/ci_local.ps1` — **13/13 addım keçdi** |
| **R2** | RLS fail-closed doğrulanmamışdı | Real `kompasos_app` rolu ilə uçdan-uca yoxlandı | kontekstsiz **0 sətir**, düzgün kontekstlə **1 sətir**, yanlış tenant **0 sətir** |
| **R3** | `kompasos_app` rolu `NOLOGIN` idi | `ALTER ROLE ... LOGIN PASSWORD`, şifrə `.env`-də (gitignore) | `rolcanlogin=true`, `rolsuper=false`, `rolcreatedb=false` |
| **R4** | `pg_cron` aktiv deyildi | `CREATE EXTENSION pg_cron` + sxem yenidən tətbiq olundu | **9 cron job** qeydiyyatdadır (`cron.job`) |
| **R5** | Argon2 parametrləri ölçülməmişdi | `scripts/benchmark_argon2.py` yazıldı və icra olundu | İstehsalat parametrləri **34 ms** (hədd 250 ms) — 7× zəif PC-də belə uyğun |
| **R6** | `CheckInStatus.REJECTED` istifadə olunmurdu | Səbəb kodda açıq sənədləşdirildi (DB paritet üçün saxlanılır) | `attendance_record.py` şərhi + `rejection_count` testi |

---

## Açıq risklər — sübut şəkillərinin saxlanması (miqrasiya 002, SEC-017)

| # | Risk | Təsir | Azaldıcı tədbir | Sahib |
|---|---|---|---|---|
| **R7** | Drive hesabı heç vaxt qoşulmaya bilər (OAuth açarları boş, administrator ekranı açmır) | Sübut şəkilləri mağaza PC-sində toplanır; disk dolarsa yeni yükləmə uğursuz olur | Cərimə YARADILMASI bloklanmır (bölmə 4 tələbi); növbə statusu `evidence_upload_status = 'PENDING'` ilə görünür və `idx_fines_evidence_pending` üzərindən sorğulana bilir | müştəri |
| **R8** | Drive kvotası dolur | Yeni şəkillər yüklənmir | Bağlantı `QUOTA_EXCEEDED` statusuna keçir, `quota_monitor` xəbərdarlıq göndərir, elementlər növbədə eksponensial backoff ilə qalır — yeni hesab qoşulan kimi avtomatik yüklənir | müştəri |

**Nə qəsdən EDİLMƏYİB.** Növbədə gözləyən şəkillər üçün avtomatik təmizləmə
(retention) YOXDUR: sübut şəkli real pul kəsintisinin əsasıdır və mübahisə
halında lazım ola bilər — yer qənaətinə görə onu silmək cəriməni sübutsuz
qoyardı. Disk idarəetməsi administratorun qərarıdır.

### R2 doğrulama detalları

`kompasos_app` rolu altında (owner DEYİL, ona görə RLS tətbiq olunur):

| Yoxlama | Nəticə |
|---|---|
| Kontekstsiz `SELECT ... FROM employees` | **0 sətir** (fail-closed) |
| `SET LOCAL app.tenant_id` ilə | **1 sətir** (işləyir) |
| Yanlış tenant kontekstində | **0 sətir** (izolyasiya) |
| `UPDATE audit_logs` | **bloklandı** (append-only trigger) |
| `run_scheduled_job()` (ixtiyari SQL) | **bloklandı** (EXECUTE geri alınıb) |
| `CREATE TABLE` | **bloklandı** (DDL hüququ yoxdur) |

---

## CI vəziyyəti

`scripts/ci_local.ps1` — `.github/workflows/ci.yml`-dəki bütün `dev` mərhələ
addımlarını eyni ardıcıllıqla lokal icra edir.

| Job | Addım | Nəticə |
|---|---|---|
| lint | Ruff lint / format | PASS |
| typecheck | MyPy strict | PASS |
| test | Self-check `--strict` | PASS |
| test | Pytest + 85% coverage qapısı | PASS |
| test | Pytest E2E (pytest-qt) | PASS |
| db-schema | Sxem tətbiqi | PASS |
| db-schema | İdempotentlik | PASS |
| db-schema | 17 guard trigger testi | PASS |
| security-scan | pip-audit | PASS |
| security-scan | İzlənən sirr faylları | PASS |
| security-scan | SBOM (CycloneDX) | PASS |
| accessibility | WCAG AA kontrast | PASS |

**13/13 keçdi.** YAML sintaksisi `yaml.safe_load` ilə doğrulandı, 8 job aşkarlandı.

### Nə hələ doğrulanmayıb

GitHub Actions **serverdə** icra olunmayıb — bunun üçün GitHub repozitoriyası və
autentifikasiya lazımdır (`gh auth login` interaktivdir). Lokal simulyasiya
addımların özünü sübut edir, lakin bunları ÖRTMÜR:

- runner-də `actions/setup-python`, `actions/upload-artifact` işləməsi
- `gitleaks` action-ı (lokalda `git ls-files` ilə əvəzlənib)
- Job asılılıqları (`needs:`) və paralel icra
- Linux-a xas Qt sistem asılılıqları (`libegl1` və s.)
- `staging-build` / `production-release` (Windows runner + PyInstaller)

`gh` CLI 2.97 quraşdırılıb — autentifikasiyadan sonra bir əmrlə push edilə bilər.

---

## Faza 3-ə keçən açıq öhdəliklər (risk deyil, iş maddəsi)

| # | Öhdəlik | Fazа |
|---|---|---|
| 1 | Repository qatı hər tranzaksiyada `SET LOCAL app.tenant_id` icra etməlidir (SEC-008 müqaviləsi) | 3 |
| 2 | Tətbiq `DATABASE_URL`-dən (`kompasos_app`) istifadə etməlidir, `postgres`-dən YOX | 3 |
| 3 | Köhnə Fernet token-lərinin toplu miqrasiyası (`needs_rotation` + `rotate_token`) | 3 |
| 4 | Plugin üçün OS-səviyyəli izolyasiya (Windows Job Object) — SEC-016 | 5 |
| 5 | Argon2 ölçməsi REAL kiosk PC-də təkrarlanmalı (`scripts/benchmark_argon2.py`) | 4 |
| 6 | Hüquqi məsləhət: kamera izləmə + cərimə (bölmə 6 UYĞUNLUQ QEYDİ) | müştəri |
| 7 | DB şifrəsinin dəyişdirilməsi (söhbətdə göründü) | müştəri |
