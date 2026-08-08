# FAZA 1 — RİSK VƏZİYYƏTİ VƏ MİNİMUM TEST SSENARİLƏRİ

> Spesifikasiya tələbi: *"Hər fazanın sonunda: (a) həmin fazada yaranan açıq
> risklərin siyahısını, (b) test edilməli olan minimum ssenariləri də göstər."*

**Yenilənmə:** ilkin siyahıdakı 10 riskdən **8-i bağlandı** (təhlükəsizlik
sərtləşdirmə mərhələsində). Qərarların tam əsaslandırması:
[`security_decisions.md`](security_decisions.md).

---

## A. BAĞLANMIŞ RİSKLƏR

| # | Risk | Həll | Sənəd |
|---|---|---|---|
| A1 | `can_approve_dual_control_override` spesifikasiya ziddiyyəti | `is_anti_fraud` / `is_camera_only` ayrıldı; kamera rolu təsdiq flag-ini daşıya bilmir | SEC-001 |
| A2 | "Fernet AES-256" hərfi deyildi (AES-128-CBC) | **AES-256-GCM**-ə keçid + AAD kontekst bağlantısı; köhnə token-lər oxunur və miqrasiya olunur | SEC-002 |
| A3 | Saga siyasəti bütün hallara sərt tətbiq olunurdu (alert fatigue) | Açıq reyestr: 12 audit-kritik saga sərt, 5 köməkçi saga yumşaq, naməlum → **sərt** (fail-safe) | SEC-003 |
| A4 | CEO ↔ CEO bərabər-pillə boşluğu | Yalnız `ROOT` istisnadır; `CEO` digər `CEO`/`Root`-a toxuna bilmir | SEC-006 |
| A5 | RLS "NULL kontekstdə hər şeyi burax" | **Fail-closed** siyasət + alt-cədvəllər üçün `EXISTS` predikatları + `kompasos_app` rolu | SEC-008/009 |
| A6 | `audit_logs` append-only yalnız sənəddə idi | `BEFORE UPDATE OR DELETE` trigger-i (owner-i də bağlayır) + FK-nın silinməsi | SEC-007 |
| A7 | `pg_cron` yoxdursa sükutla sönürdü | `run_all_scheduled_jobs()`, `scheduled_job_runs`, `v_scheduled_job_health`, `RAISE WARNING` | SEC-010 |
| A8 | İmzasız `.exe` release-ə çıxa bilirdi | Sertifikat yoxdursa release **uğursuz olur**; təcili hal üçün açıq `allow_unsigned` girişi | SEC-012 |

### Sərtləşdirmə zamanı aşkarlanıb bağlanan ƏLAVƏ risklər

| # | Risk | Həll |
|---|---|---|
| A9 | **4-rəqəmli PIN cəmi 10 000 variantdır** — DB sızarsa Argon2 tək başına kifayət etmir | Məcburi **pepper** (`KOMPASOS_HASH_PEPPER`), HMAC-a `employee_id` daxil edilir; zəif PIN-lər rədd olunur | SEC-005 |
| A10 | TOTP kodu 30 saniyə ərzində **təkrar istifadə** oluna bilərdi | Replay qorunması: `totp_last_used_counter`; ehtiyat kodları (Argon2id) | SEC-004 |
| A11 | Şifrəli dəyəri başqa sətrə **köçürmək** mümkün idi | AES-GCM **AAD** ilə kontekst bağlantısı (`erp_server:<id>`, `totp:<id>`) | SEC-002 |
| A12 | "İstifadəçi var/yoxdur" cavab vaxtından sızırdı | Hesab olmasa da dummy Argon2 hash yoxlanılır | SEC-014 |
| A13 | Kamera operatorunun "növbə boyu" sessiyasının müddəti/ləğvi yox idi | `auth_sessions`: token hash-i, ikiqat müddət, `revoked_at` | SEC-011 |
| A14 | Tətbiq owner ilə qoşulsa bütün DB qorumaları yan keçilir | `kompasos_app` rolu (NOSUPERUSER, DDL yox, audit-ə UPDATE/DELETE yox) | SEC-009 |
| A15 | `run_scheduled_job(TEXT, TEXT)` ixtiyari SQL icra edir | Tətbiq rolundan `EXECUTE` geri alındı; yalnız `run_all_scheduled_jobs()` açıqdır | SEC-010 |
| A16 | `assets/kompasos.ico` və `scripts/check_contrast.py` yox idi → build/CI qırılırdı | Hər ikisi yaradıldı (ikon — düzgün formatlı, 4 ölçülü placeholder; kontrast skripti — testlərlə örtülü) | — |

---

## B. AÇIQ QALAN RİSKLƏR

### B1. Mühit — demək olar tam bağlandı

| Komponent | Vəziyyət |
|---|---|
| **PostgreSQL / Supabase** | ✅ Sxem canlı layihədə (ap-southeast-1, PG 17.6), idempotent, **17/17** guard testi |
| **Python 3.11.9** | ✅ Quraşdırıldı, `.venv` quruldu, bütün asılılıqlar yükləndi |
| **Testlər** | ✅ **193 keçdi**, 3 skip (Faza 4 placeholder), coverage **92.30%** (qapı 85%) |
| **MyPy strict** | ✅ `Success: no issues found in 28 source files` |
| **Ruff lint + format** | ✅ `All checks passed`, 46 fayl formatlanıb |
| **pip-audit** | ✅ `No known vulnerabilities found` |
| **Self-check `--strict`** | ✅ `SELF_CHECK_PASSED`, çıxış kodu 0 |
| **Git** | ❌ Quraşdırılmayıb → repozitoriya yoxdur, **CI heç vaxt işləməyib** |

#### Real icra 4 qüsur tapdı (statik nəzərdən keçirmə tutmazdı)

| # | Qüsur | Necə tapıldı |
|---|---|---|
| 1 | `ON DELETE RESTRICT` tenant silinməsini tamamilə bloklayırdı → `NO ACTION DEFERRABLE` (SEC-015) | Guard testlərinin təmizləmə addımı |
| 2 | `b"köhnə-sirr"` — bytes literalında ASCII-olmayan simvol (`SyntaxError`) | İlk pytest collection |
| 3 | **`extra={"message": ...}` BÜTÜN tətbiqi çökdürürdü** (`KeyError`) — `LogRecord`-un qorunan sahəsi | `python -m src.main --strict` |
| 4 | `app_version` həmişə `0.0.0` qalırdı — lazy konfiqurasiya `main()`-dəki versiyanı yeyirdi | Log çıxışının nəzərdən keçirilməsi |

**3-cü qüsur ən ciddisi idi:** istənilən modul təsadüfən `message`, `module`,
`name` kimi açar göndərsəydi tətbiq çökərdi. Loglama heç vaxt tətbiqi
dayandırmamalıdır — indi belə açarlar `ctx_` prefiksi ilə təhlükəsiz
adlandırılır (məlumat itmir) və 7 parametrli reqressiya testi ilə qorunur.

### B1a. Git hələ quraşdırılmayıb — CI doğrulanmayıb

`.github/workflows/ci.yml` yazılıb, lakin **heç vaxt işləməyib**. Lokal olaraq
CI-ın bütün addımları (ruff, mypy, pytest, coverage, pip-audit, schema, guard
testləri) ayrıca icra olunub və keçib — lakin pipeline-ın YAML-ı, job
asılılıqları və artefakt yükləmələri sınaqdan keçməyib.

### B1a. `kompasos_app` rolu LOGIN-siz yaradılıb

Rol mövcuddur və səlahiyyətləri tətbiq olunub, lakin `NOLOGIN`-dir. Faza 3-də
deployment skriptində şifrə təyin edilməlidir:

```sql
ALTER ROLE kompasos_app LOGIN PASSWORD '<güclü-şifrə>';
```

Tətbiq **bu roldan** istifadə etməlidir, `postgres`-dən yox — əks halda RLS və
append-only qorumaları yan keçilir (SEC-009).

### B1b. Supabase-də `pg_cron` aktiv deyil

Sxem bunu xəbərdarlıqla qeyd etdi və `scheduled_job_runs`-a yazdı. İki variant:
Supabase Dashboard → Database → Extensions → `pg_cron` aktivləşdirin, **və ya**
xarici scheduler `run_all_scheduled_jobs()` çağırsın
([`scheduler_setup.md`](scheduler_setup.md)). Bu edilməyənə qədər timeout
eskalasiyası və xal sıfırlanması **işləmir**.

### B1c. DB şifrəsi söhbətdə açıq yazıldı

`Kompas.123!` bu sessiyada göründü. Supabase → Settings → Database →
**Reset database password** ilə dəyişdirilməlidir.

### B2. Pepper dəyişdirilməsi geri qaytarıla bilməz

`KOMPASOS_HASH_PEPPER` dəyişilərsə **bütün PIN və şifrələr** etibarsız olur.
Şifrələmə açarından fərqli olaraq "previous pepper" mexanizmi **yoxdur**
(hash birtərəflidir — köhnə pepper ilə yenidən hash-ləmək mümkün deyil).

**Azaldıcı tədbir (Faza 2 qərarı):** ya (a) `employees.pepper_version` sütunu
əlavə edilib çoxlu pepper dəstəklənsin, ya da (b) rotasiya yalnız kütləvi
PIN/şifrə sıfırlaması ilə birlikdə planlaşdırılsın. **Sizin qərarınızı gözləyir.**

### B3. Argon2 parametrləri zəif kiosk PC-lərində ölçülməyib

64 MiB / t=3 OWASP tövsiyəsidir, lakin köhnə mağaza PC-lərində PIN yoxlaması
gözlə görünən gecikmə yarada bilər. **Faza 4-də real cihazda ölçülməli**;
azaldılma qərarı `security_decisions.md`-də qeyd olunmalıdır.

### B4. `SET LOCAL app.tenant_id` müqaviləsi hələ tətbiq olunmayıb

RLS fail-closed-dur, lakin onu **işlədən** repozitoriya qatı Faza 3-dədir.
O vaxta qədər heç bir tətbiq sorğusu yoxdur, ona görə risk gizlidir — lakin
Faza 3-də unudulsa, bütün sorğular boş nəticə qaytaracaq (fail-closed olduğu
üçün **sızma yox, dayanma** olacaq — bu, qəsdən seçilmiş davranışdır).

### B5. Hüquqi məsləhət (spesifikasiyanın öz tələbi)

Bölmə 6 UYĞUNLUQ QEYDİ: kamera izləmə + cərimə sistemi tətbiqə düşməzdən
əvvəl **yerli Əmək Məcəlləsi və şəxsi məlumatların qorunması qanunvericiliyi**
üzrə hüquqi məsləhət alınmalıdır. Bu, texniki deyil, təşkilati riskdir.

---

## C. FAZA 2-DƏN ƏVVƏL İCRA EDİLMƏLİ ADDIMLAR

```powershell
# 1. Python 3.11+ (quraşdırarkən "Add python.exe to PATH" seçin)
#    https://www.python.org/downloads/
# 2. Git — https://git-scm.com/download/win

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

Copy-Item .env.example .env
# .env-ə iki açar yazın:
python -c "from src.infrastructure.security.encryption import generate_key; print(generate_key())"
python -c "from src.infrastructure.security.hashing import generate_pepper; print(generate_pepper())"

ruff check src tests scripts
ruff format --check src tests scripts
mypy src
pytest tests/unit -v
python -m src.main --strict

# 3. PostgreSQL (və ya Supabase)
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -v kompasos_env=DEV -f database/schema.sql
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -v kompasos_env=DEV -f database/schema.sql  # idempotentlik
psql "$env:DATABASE_URL" -v ON_ERROR_STOP=1 -f database/tests/test_guards.sql
```

---

## D. MİNİMUM TEST SSENARİLƏRİ

### D1. Mühit və startup

| # | Ssenari | Gözlənilən nəticə |
|---|---|---|
| 1 | `pip install -r requirements-dev.txt` | Xətasız |
| 2 | `python -m src.main` (açar YOXDUR) | Çıxış kodu 1, `SELF_CHECK_FAILED_ITEM` (`encryption`) |
| 3 | Açar var, pepper YOX, `KOMPASOS_ENV=DEV` | Çıxış kodu 0, `hash_pepper` XƏBƏRDARLIQ |
| 4 | Açar var, pepper YOX, `KOMPASOS_ENV=PRODUCTION` | Çıxış kodu **1** — pepper istehsalatda məcburidir |
| 5 | Hər ikisi var, `--strict` | Çıxış kodu 0, `SELF_CHECK_PASSED` |

### D2. Event Bus

| # | Ssenari | Gözlənilən nəticə |
|---|---|---|
| 6 | Sync + async handler eyni hadisəyə | Hər ikisi çağırılır |
| 7 | Bir handler istisna atır | Digərləri işləyir, `error.log`-da `EVENT_HANDLER_FAILED` |
| 8 | `DomainEvent` bazisinə abunə | Bütün törəmə hadisələr tutulur (audit dinləyicisi) |
| 9 | İki 50 ms-lik async handler | Ümumi vaxt < 90 ms (paralel) |

### D3. DI Container

| # | Ssenari | Gözlənilən nəticə |
|---|---|---|
| 10 | `A → B → A` dövr | `CircularDependencyError`, zəncir mesajda |
| 11 | Qeydiyyatsız tip | `DependencyNotRegisteredError` |
| 12 | Scope-lu `Disposable` | Scope bitəndə `dispose()` çağırılır |

### D4. Saga + siyasət reyestri

| # | Ssenari | Gözlənilən nəticə |
|---|---|---|
| 13 | 3 addım, 3-cü çökür | Kompensasiyalar **tərs sırada** |
| 14 | `LeaveVerification` çökür, kompensasiya uğurlu | `PENDING_RECONCILIATION` (audit-kritik) |
| 15 | `NotificationDispatch` çökür, kompensasiya uğurlu | `COMPENSATED` (best-effort) |
| 16 | Reyestrdə **olmayan** saga çökür | `PENDING_RECONCILIATION` (fail-safe default) |
| 17 | Kompensasiyanın özü çökür | `PARTIALLY_COMPENSATED` / `COMPENSATION_FAILED` |
| 18 | `PENDING_RECONCILIATION` | `SagaPendingReconciliationEvent` bus-a düşür |
| 19 | `retries=3`, 3-cü cəhddə uğur | `COMPLETED`, `attempts == 3` |

### D5. Şifrələmə (AES-256-GCM)

| # | Ssenari | Gözlənilən nəticə |
|---|---|---|
| 20 | Token formatı | `v1.<8 hex>.<base64>` |
| 21 | Eyni mətn 2 dəfə | Fərqli token (təsadüfi nonce) |
| 22 | **Yanlış AAD kontekstlə açma** | `DecryptionError` — cut-and-paste bağlıdır |
| 23 | Kontekstsiz açma (kontekstlə şifrələnib) | `DecryptionError` |
| 24 | Şifrətəki 1 simvol dəyişdirilir | `DecryptionError` (GCM teqi) |
| 25 | Naməlum `key_id` | Xəta mesajı `KOMPASOS_FERNET_KEY_PREVIOUS`-u göstərir |
| 26 | Köhnə **Fernet** token-i | Oxunur, `needs_rotation() == True` |
| 27 | `rotate_token()` Fernet üzərində | `v1.`-ə keçir, `needs_rotation() == False` |
| 28 | `repr(KeyMaterial)` | Açar görünmür |

### D6. Hash + PIN lockout

| # | Ssenari | Gözlənilən nəticə |
|---|---|---|
| 29 | Eyni PIN, iki fərqli işçi | Fərqli hash (HMAC-a `employee_id` daxildir) |
| 30 | PIN başqa işçinin kontekstində | `False` |
| 31 | Pepper-siz yaradılmış hash, pepper-li servis | `False` (uyğunsuzluq aşkarlanır) |
| 32 | Fərqli pepper-lər | Bir-birini qəbul etmir |
| 33 | Zəif PIN (`0000`, `1234`, `2580`) | `WeakSecretError` |
| 34 | Zəif şifrə (5 variant) | Səbəb AZ dilində göstərilir |
| 35 | 5-ci səhv cəhd | 15 dəqiqəlik lockout |
| 36 | Bloklanmış hesabda **DOĞRU** PIN | Rədd (`ACCOUNT_LOCKED`) |
| 37 | Lockout müddəti bitib | Qəbul, sayğac sıfırlanır |
| 38 | `PinPolicy(max_attempts=3, lockout_minutes=30)` | `system_limits` konfiqurasiyası işləyir |
| 39 | Mövcud olmayan hesab | `False`, istisna YOX (enumeration) |

### D7. TOTP 2FA

| # | Ssenari | Gözlənilən nəticə |
|---|---|---|
| 40 | Qeydiyyat | Şifrəli sirr + `otpauth://` URI + 10 ehtiyat kodu |
| 41 | Sirr başqa işçinin ID-si ilə | `TotpError` (AAD) |
| 42 | Düzgün kod | `is_valid`, `used_counter` qaytarılır |
| 43 | **Eyni kod ikinci dəfə** | `REPLAY_DETECTED` |
| 44 | Köhnə pəncərənin kodu (yenisi istifadə olunub) | `REPLAY_DETECTED` |
| 45 | −30 s pəncərə (saat sürüşməsi) | Qəbul edilir |
| 46 | −90 s pəncərə | Rədd |
| 47 | Ehtiyat kodu | Bir dəfə işləyir, sonra `None` |
| 48 | Ehtiyat kodları saxlanışı | `$argon2id$`, plaintext YOX |

### D8. Loglama

| # | Ssenari | Gözlənilən nəticə |
|---|---|---|
| 49 | 4 kanala yazı | 4 ayrı fayl |
| 50 | `extra={"pin": ..., "password": ..., "totp_secret": ...}` | Heç biri faylda görünmür |
| 51 | Audit yazısı | `app.log`-a sızmır |
| 52 | `extra` + adapter `source` | **Hər ikisi** context-də olur (LoggerAdapter əvəzləmir) |

### D9. Baza sxemi (PostgreSQL tələb olunur)

| # | Ssenari | Gözlənilən nəticə |
|---|---|---|
| 53 | `schema.sql` təmiz bazada | Xətasız |
| 54 | **İkinci dəfə** icra | Xətasız (idempotentlik) |
| 55 | `-v kompasos_env=DEV` | Seed tenant `AKTIV` |
| 56 | `-v kompasos_env=PRODUCTION` | Seed tenant **yaranmır** |
| 57 | `test_guards.sql` | **17/17** test uğurlu |
| 58 | `can_issue_fines` → `Mağaza_Meneceri` | Bloklanır (TEST 1) |
| 59 | Anti-fraud override yolu ilə | Bloklanır (TEST 2) |
| 60 | `can_manage_permissions` → `CEO` | Bloklanır (TEST 3) |
| 61 | `can_manage_positions` → `HR_Admin` | Bloklanır (TEST 4) |
| 62 | Özünə override | Bloklanır (TEST 5) |
| 63 | Admin → Root | Bloklanır (TEST 6) |
| 64 | Admin → Satıcı | **İcazə verilir** (TEST 7) |
| 65 | Kamera rolu → dual-control təsdiqi | Bloklanır (TEST 8) |
| 66 | `Delay` mənfi olardı | `0` (TEST 9) |
| 67 | 60 dəq. icazə, 90 dəq. qayıdış | `Delay=30`, `Total=120` (TEST 9) |
| 68 | Foto sübutsuz `MANUAL_CAMERA` | Bloklanır (TEST 10) |
| 69 | `approved_by = operator_id` | Bloklanır (TEST 11) |
| 70 | Cərimə yaradılır | `appeal_window_closes_at` = +72 saat (TEST 12) |
| 71 | **CEO → CEO** | Bloklanır; **Root → CEO** icazə verilir (TEST 13) |
| 72 | `audit_logs` UPDATE / DELETE | **Hər ikisi bloklanır** (TEST 14) |
| 73 | Kontekstsiz `current_tenant_id()` | `NULL`, 0 sətir görünür (TEST 15) |
| 74 | Yararsız UUID mətni | `NULL` (istisna YOX) (TEST 15) |
| 75 | `expires_at > absolute_expiry` | Bloklanır (TEST 16) |
| 76 | `run_all_scheduled_jobs()` | 9 job, hamısı uğurlu (TEST 17) |
| 77 | `v_scheduled_job_health` | `is_stale` sütunu hesablanır |
| 78 | Eyni işçi üçün ikinci açıq icazə | Unikal indeks bloklayır |
| 79 | `v_exportable_fines` | Açıq pəncərəli və `REVERSED` cərimələr çıxmır |

### D10. WCAG kontrast

| # | Ssenari | Gözlənilən nəticə |
|---|---|---|
| 80 | Qara/ağ | 21.00:1 |
| 81 | `#0B1D3A` ağ fonda | AA keçir (əsas mətn) |
| 82 | `#F5A623` ağ fonda | AA **keçmir** — yalnız iri qrafik element |
| 83 | `#F5A623` navy fonda | 3:1 keçir |
| 84 | Tokenlər yoxdur (Faza 1-3) | Çıxış kodu 0, "atlandı" |
| 85 | Zəif kontrastlı tokenlər | Çıxış kodu 1, `::error::` |

### D11. CI/CD

| # | Ssenari | Gözlənilən nəticə |
|---|---|---|
| 86 | PR açılır | 6 job işə düşür (lint, typecheck, test, db-schema, security-scan, accessibility) |
| 87 | Ruff / MyPy xətası | Pipeline qırmızı |
| 88 | Coverage < 85% | Pipeline qırmızı |
| 89 | Zəiflikli asılılıq | `pip-audit` qırır |
| 90 | `.env` commit edilir | `gitleaks` + `git ls-files` qapısı tutur |
| 91 | `.pfx`/`.pem` commit edilir | Qapı tutur |
| 92 | SBOM | `sbom.json` artefaktı yaranır |
| 93 | `main`-ə merge | `staging-build`, **imzasız** artefakt |
| 94 | `v0.1.0` teq-i, sertifikat **YOX** | Release **UĞURSUZ** (SEC-012) |
| 95 | `workflow_dispatch` + `allow_unsigned=true` | İmzasız buraxılır, xəbərdarlıqla |
| 96 | Sertifikat var | İmzalanır, `Get-AuthenticodeSignature` = `Valid`, SHA256 checksum |

---

## E. FAZA 2-YƏ KEÇİD ÜÇÜN QƏRARINIZ LAZIM OLAN YEGANƏ MƏSƏLƏ

**B2 — pepper rotasiyası:** çoxlu pepper versiyası dəstəklənsin
(`employees.pepper_version` sütunu), yoxsa rotasiya yalnız kütləvi
PIN/şifrə sıfırlaması ilə birlikdə planlaşdırılsın?

Digər bütün təhlükəsizlik qərarları qəbul edilib və tətbiq olunub
([`security_decisions.md`](security_decisions.md), SEC-001…SEC-014).
