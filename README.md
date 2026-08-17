# KompasOS

Enterprise Leave / Fine / Break / Shift / ERP-1C / Task / Dashboard sistemi —
Bellona, İstikbal, Yataş və Enza Home brendləri ilə işləyən pərakəndə şəbəkə üçün
Windows masaüstü tətbiqi (`.exe`).

> **Status: altı fazanın hamısının qatları yazılıb.** DDD nüvəsi, domen
> məntiqi, təhlükəsizlik qatı, tam DB sxemi, CI/CD, persistence, 1C
> konnektorları, lisenziya/auto-update, dizayn sistemi + 27 maket ekranı,
> Faza 5/6 əməliyyat modulları, ROOT Control Center və GUI kompozisiya kökü
> hazırdır (naviqasiyada 28 bölmə).
> Tam plan: `kompasos.md`, bölmə 10 — həmin fayl işçi ağacında YOXDUR,
> git tarixçəsindən bərpa olunur (bax `CLAUDE.md` §0).

---

## Faza xəritəsi

| Faza | Əhatə | Status |
|---|---|---|
| 1 | DDD strukturu, Event Bus, DI, Saga, logger, şifrələmə, `schema.sql`, CI/CD | ✅ Tamamlandı |
| 2 | Domen entity-ləri, use case-lər, Guard-lar, Plugin API (sandbox), NavigationRegistry | ✅ Tamamlandı |
| 3 | Supabase repo-ları, çoxsaylı 1C konnektorları, offline buffer, lisenziya klienti, auto-update | ✅ Tamamlandı |
| 4 | PySide6 Shell (role-driven), Kiosk Mode, Camera Dashboard, dizayn sistemi, kompozisiya kökü | ✅ Tamamlandı |
| 5 | Root/CEO panelləri, növbə/tabel/cərimə modulları, özünə-xidmət alətləri | ✅ Tamamlandı |
| 6 | Satış xalları, şübhəli satış növbəsi, hesabatlar, SaaS-hazırlayıcı Lisenziya / Developer Paneli | ✅ Tamamlandı |

### Faza 5/6 — sonuncu mərhələdə bağlanan qatlar

| Modul | Yer |
|---|---|
| Interactive Shift Matrix + Növbə Dəyişmə Sorğusu | `application/use_cases/shift_scheduling.py` |
| Gündəlik Mağaza Tabeli (avto ön-doldurma, HR müqayisəsi) | `application/use_cases/daily_attendance.py` |
| Manual cərimə qeydiyyatı + 72-saatlıq etiraz | `application/use_cases/fine_management.py` |
| Custom rol yaratma (`can_manage_positions`) | `application/use_cases/position_management.py` |
| Audit Jurnalı baxışı (`can_view_audit_logs`) | `application/use_cases/audit_query.py` |
| Dəstək chat-i (tenant tərəfi) | `application/use_cases/support_chat.py` |
| Sync konfliktlərinin manual həlli | `application/use_cases/sync_conflicts.py` |
| Şübhəli satış növbəsi | `application/use_cases/sales_review_queue.py` |
| İlk Quraşdırma Sihirbazı | `application/use_cases/first_run_setup.py` |
| Hesabat fakt-mənbəyi (SQL aqreqasiya) | `infrastructure/persistence/report_repositories.py` |
| GUI obyekt qrafı (sessiya + use case-lər) | `presentation/composition.py` |

> Əlavə olaraq (spesifikasiyada bölmə 4/6-dan gələn qərar dəyişiklikləri):
> cərimə sübut şəkillərinin Google Drive-da saxlanması, aylıq cərimə icmalı
> (`PENDING_REVIEW` → `PUBLISHED`) və universal İşçi Detal Paneli.

### ROOT Control Center — Soft-Coded System Rules (bölmə 3)

Təhlükəsizlik nüvəsindən (şifrə hash-i, JWT, DB bağlantısı, Anti-Fraud,
Hierarchy/Self-Escalation Guard) **kənarda qalan hər şey** GUI-dan idarə
olunur — kodda sabit ədəd yoxdur.

| Bölmə | Yer |
|---|---|
| Dinamik limitlər / taymaut-lar (`system_limits`) | `domain/policies.py`, `presentation/controllers/root_control.py` |
| Feature Toggles (`feature_toggles`) — retroaktiv-təsirsiz | `application/use_cases/root_control.py` |
| Permission Registry (yeni flag, YALNIZ Root) | `application/use_cases/root_control.py` |
| Dynamic UI Integration (söndürülmüş modul render-dən kəsilir) | `presentation/shell/menu.py`, `presentation/app.py` |

> Struktur-kritik modulu (Kamera Təsdiqi) söndürmək bir-kliklik toggle
> DEYİL: əlavə xəbərdarlıq modalı **və yazılı təsdiq sahəsi** tələb olunur;
> mətnin uzunluğu həm use case-də, həm repository qatında yoxlanılır.

### Sübut şəkli zənciri (miqrasiya 002, SEC-017)

```
Cərimə forması → lokal növbə (SQLite + disk spool) → Drive
                 ↑ şəkil ƏVVƏLCƏ diskə yazılır
```

Sıra qəsdəndir: tərsi olsaydı aradakı çökmə **sübutu olmayan cərimə**
yaradardı, bölmə 4 isə manual cəriməni sübutsuz qadağan edir. Drive hesabı
qoşulmayıbsa cərimələr yenə normal yaranır, şəkillər növbədə gözləyir və
bağlantı qurulan kimi avtomatik yüklənir.

| Hissə | Yer |
|---|---|
| Razılıq (OAuth consent) axını — loopback + PKCE | `infrastructure/storage/oauth_flow.py` |
| "Drive Bağlantısı" ekranı (`can_manage_drive_connection`) | `presentation/screens/group_d.py` |
| Lokal növbə + fon işçisi | `infrastructure/storage/upload_queue.py` |

---

## Lisenziya arxitekturası (bölmə 8)

**Ayrıca server, VPS, domen və ya hostinq YOXDUR.** Lisenziya qeydi mövcud
Supabase layihəsindəki `license_tenants` cədvəlindədir və iki tərəf var:

| | Müştəri `.exe` | Developer Paneli |
|---|---|---|
| Açar | Supabase `anon` + RLS | Supabase `service_role` |
| Hüquq | öz sətrini **yalnız oxuyur** | bütün sətirlər, oxu/yaz |
| Yerləşmə | mağaza PC-ləri | **yalnız hazırlayıcının kompüteri** |
| Şəbəkə | — | internetə host **olunmur** |

Avtomatik dayanma server-siz işləyir: klient `expires_at`-i yerli saatla
müqayisə edir → `LICENSE_INACTIVE`. Supabase tərəfdə cron/Edge Function
tələb olunmur.

### Vendor (mərkəzi) bazası — PARALEL, MÜŞTƏRİ ORA YAZMIR (DB-3)

Yuxarıdakı axın **dəyişmir**. Ondan AYRI olaraq təchizatçının öz mərkəzi
bazası var: `database/migrations/vendor/` (abunə reyestri, ödənişlər, çökmə
hesabatları, dəstək müraciətləri, vendor audit izi).

* Müştəri `.exe`-si bu bazaya **nə yazır, nə də cədvəllərini oxuyur.**
  Yeganə mümkün toxunuş `vendor.check_license_status(tenant_id, license_key)`
  RPC-sidir (bir sətir, iki sütun) və o, hazırda **çağırılmır**.
* Bütün cədvəllərdə RLS + `FORCE` aktivdir və siyasət yalnız `kompasos_vendor`
  rolunadır. `anon`/`authenticated` sxemə belə çıxa bilmir.
* **`service_role` ilə qoşulmayın:** həmin rolda `BYPASSRLS` var və bütün
  siyasətləri yan keçir. Konsol `kompasos_vendor` üzvü, `BYPASSRLS` olmayan
  ayrıca rolla qoşulmalıdır.

#### Vendor hesabının yaradılması

```bash
set KOMPASOS_VENDOR_DSN=postgresql://console_user:***@host:5432/vendor_db
.venv/Scripts/python.exe scripts/create_vendor_account.py
```

Skript e-poçt + şifrə soruşur (Argon2id ilə heşlənir), TOTP sirri yaradır və
`otpauth://` URI-ni göstərir. **Hesab yalnız siz autentifikatorun verdiyi kodu
təsdiqlədikdən sonra yazılır** — səhv qurulmuş TOTP ilə yeganə hesabın
kilidlənməsinin qarşısını alır. Sirr bir dəfə göstərilir.

Skript `.exe`-yə **daxil edilmir** (`src/KompasOS.spec` ona istinad etmir;
`tests/unit/test_vendor_bootstrap.py` bunu yoxlayır).

Ödəniş alındıqdan sonra `[1 Ay Uzat]` dəyişikliyi **dərhal** Supabase-ə yazır.
Bağlanmış quraşdırma onu 24 saat gözləmir: bloklanmış vəziyyətdə klientin
yoxlama ritmi **15 dəqiqəyə** enir (Force Sync-in serversiz qarşılığı).

```bash
# Developer Paneli (KOMPASOS_DEVELOPER_MODE + service_role açarı tələb olunur)
python -m src.main --developer-mode                      # tenant siyahısı
python -m src.main --developer-mode --search bellona     # axtarış
python -m src.main --developer-mode --extend <TENANT_ID> # təsdiq mətnini göstərir
python -m src.main --developer-mode --extend <ID> --yes  # 1 ay uzadır
python -m src.main --developer-mode --gui                # pəncərə rejimi
```

> `service_role` açarı **heç vaxt** müştəriyə göndərilən `.exe`-yə daxil
> edilmir — yalnız yerli `.env` faylındadır və `.gitignore` onu Git-dən kənarda
> saxlayır.

---

## Yeni versiyanın yayımlanması (bölmə 1, 7)

**Ayrıca update serveri və ya CDN YOXDUR.** İki komponent:

| Nə | Harada | Kim yazır |
|---|---|---|
| Quraşdırıcı faylı | `app-updates/{versiya}/KompasOS-Setup.exe` (**private** bucket) | `service_role` |
| Versiya metadatası | `app_versions` cədvəli | `service_role` |

Paylanma **pull** modelidir: bir dəfə yayımlayırsan, bütün tenant-lar öz
check-in dövründə (License Client ilə eyni mexanizm) EYNİ cədvəli oxuyub yeni
versiyanı özləri aşkar edir, SHA-256 + Authenticode yoxlayır və tətbiq edir.
Uyğunsuzluqda fayl silinir və yenilənmə **tətbiq edilmir** (fail-closed).

```bash
# Yoxlama: fayl faktlarını göstərir (ölçü, SHA-256, imza), heç nə yükləmir
python -m src.main --developer-mode --publish dist/KompasOS-Setup.exe \
    --publish-version 1.4.0

# Yayım: Storage-a yükləyir + `app_versions`-a sətir əlavə edir
python -m src.main --developer-mode --publish dist/KompasOS-Setup.exe \
    --publish-version 1.4.0 --publish-notes "Cərimə hesablaması düzəldildi" \
    --publish-mandatory --yes
```

GUI-də eyni əməliyyat: `--developer-mode --gui` → **"Yeni Versiya Yüklə"**
bölməsi (drag-drop fayl seçici, versiya, release notes, "Məcburi Yeniləmədir",
`[Yüklə və Yayımla]`). Köhnə versiyalar **silinmir** — geri qaytarma üçün
saxlanılır.

---

## Layihə strukturu

```
KompasOS/
├── src/
│   ├── domain/              # saf biznes qaydaları (xarici asılılıq YOXDUR)
│   │   ├── entities/        # ✅ LeaveRequest, AttendanceRecord, Employee, Fine
│   │   ├── value_objects/   # ✅ Pin, Money, PermissionFlag, penalty, storage, erp
│   │   ├── interfaces/      # ✅ 21 repository/servis portu (Protocol)
│   │   ├── policies.py      # ✅ BR-001/BR-002, sistem limitləri
│   │   └── events/          # ✅ domen hadisələri (LeaveVerifiedEvent, ...)
│   ├── application/         # ✅ use case-lər (Saga, Guard-lar, auth, sihirbaz)
│   ├── infrastructure/
│   │   ├── security/        # ✅ AES-256-GCM, Argon2id+pepper
│   │   ├── persistence/     # ✅ UnitOfWork, repo-lar, RLS konteksti
│   │   ├── offline/         # ✅ SQLite outbox + konflikt aşkarlanması
│   │   ├── storage/         # ✅ Google Drive sübut saxlanması, kvota, növbə
│   │   ├── timekeeping/     # ✅ NTP drift yoxlayıcısı
│   │   ├── erp/             # ✅ çoxsaylı 1C konnektorları, sync worker, health
│   │   ├── licensing/       # ✅ lisenziya klienti, şifrəli keş, panel qatı
│   │   ├── updates/         # ✅ buraxılış kataloqu, Authenticode, rollback
│   │   ├── backup/          # ✅ pg_dump nüsxəsi, yoxlama, saxlama müddəti
│   │   └── notifications/   # ✅ SMTP fallback + PII-siz crash reporting
│   ├── developer_panel/     # ✅ YERLİ alət — müştəri .exe-sinə DAXİL EDİLMİR
│   ├── presentation/        # ✅ PySide6 örtük, tema/tokenlər, ekranlar,
│   │                        #    kontrollerlər (Faza 4 — bax cədvəl yuxarı)
│   ├── shared/              # ✅ event_bus, di_container, saga_orchestrator,
│   │                        #    saga_policies, logger
│   └── main.py              # ✅ kompozisiya kökü + təhlükəsizlik self-check
├── database/
│   ├── schema.sql           # ✅ 46 cədvəl, RLS, append-only audit, cron
│   ├── tests/               # ✅ 34 DB-səviyyəli guard testi
│   └── migrations/          # ✅ 001 username-auth · 002 Drive · 003 cərimə
│                            #    icmalı · 004 1C konnektoru · 005 lisenziya
│                            #    telemetriyası · 006 lisenziya RLS + expires_at
│                            #    · 007 bildiriş e-poçt növbəsi · 008 yenilənmə
│                            #    kataloqu + backup sağlamlığı · 009 app_versions
│                            #    + private `app-updates` bucket-i
├── scripts/
│   ├── check_contrast.py    # ✅ WCAG AA yoxlayıcısı (CI-da işləyir)
│   ├── build_icon.py        # ✅ assets/logo/256.png → kompasos.ico (6 pillə)
│   └── generate_placeholder_icon.ps1  # ⚠️ KÖHNƏLİB — real loqonu əvəz edər
├── assets/
│   ├── kompasos.ico         # ✅ real loqo; TÖRƏMƏ fayl — build_icon.py qurur
│   └── logo/                # ✅ 9 PNG: 256 master, başlıq işarəsi, rozet, splash
├── tests/
│   ├── unit/                # ✅ domen/shared/security/infrastruktur testləri
│   ├── integration/         # ✅ DB + Drive (DATABASE_URL yoxdursa skip)
│   └── e2e/                 # ✅ pytest-qt (Developer Paneli ekranı + karkas)
├── docs/
│   ├── security_decisions.md # ✅ SEC-001…SEC-014 (ADR)
│   ├── key_rotation.md       # ✅ açar rotasiya proseduru
│   ├── scheduler_setup.md    # ✅ pg_cron / xarici scheduler
│   └── phase1_risks.md       # ✅ risk vəziyyəti + 96 test ssenarisi
└── .github/workflows/ci.yml  # ✅ dev → staging → production
```

---

## Quraşdırma

### Tələblər

- **Python 3.11+** — https://www.python.org/downloads/
  (Microsoft Store alias-ı kifayət etmir; quraşdırarkən *Add python.exe to PATH*
  seçilməlidir)
- **Git** — https://git-scm.com/download/win
- **PostgreSQL 14+** və ya Supabase layihəsi

### Addımlar

```powershell
# 1. Virtual mühit
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Asılılıqlar
pip install -r requirements-dev.txt

# 3. Konfiqurasiya — İKİ açar tələb olunur
Copy-Item .env.example .env
python -c "from src.infrastructure.security.encryption import generate_key; print(generate_key())"   # KOMPASOS_FERNET_KEY
python -c "from src.infrastructure.security.hashing import generate_pepper; print(generate_pepper())" # KOMPASOS_HASH_PEPPER

# 4. Təhlükəsizlik və sağlamlıq yoxlaması
python -m src.main --strict
```

> **`KOMPASOS_HASH_PEPPER` istehsalatda MƏCBURİDİR.** 4-rəqəmli PIN-in cəmi
> 10 000 variantı var — pepper olmadan baza sızarsa bütün PIN-lər dəqiqələr
> içində bərpa oluna bilər (bax [SEC-005](docs/security_decisions.md)).
> Bu dəyər dəyişdirilərsə bütün mövcud PIN/şifrələr etibarsız olur.

### Google Drive — sübut şəkilləri (isteğe bağlı, bax SEC-017)

Cərimə sübut şəkilləri müştərinin ÖZ Drive hesabında saxlanılır. Google Cloud
Console-da OAuth klienti yaradın — **tip mütləq "Desktop app" olmalıdır**
(razılıq axını `http://127.0.0.1:<port>`-a yönləndirir; port hər dəfə OS
tərəfindən seçildiyi üçün Console-da konkret port qeydiyyatdan keçirilmir):

```powershell
# .env
KOMPASOS_GOOGLE_CLIENT_ID=...
KOMPASOS_GOOGLE_CLIENT_SECRET=...
```

Sonra tətbiqdə **Drive Bağlantısı** bölməsini açıb (`can_manage_drive_connection`
— defolt Root/CEO) hesabı qoşun. Açarlar boş buraxıla bilər: cərimələr yenə
normal yaranır, şəkillər lokal növbədə gözləyir.

### Baza — ✅ QURULUB VƏ DOĞRULANIB

Sxem canlı Supabase layihəsinə tətbiq olunub (ap-southeast-1, PostgreSQL 17.6):
**46 cədvəl, 42 RLS siyasəti, 18 enum, 21 funksiya, 4 view, 23 trigger,
110 indeks**, seed tam. **Guard testləri tətbiq anında 17/17 ✅**, idempotentlik
doğrulanıb. **Diqqət: 17/17 həmin tətbiq anının nəticəsidir** — fayl o vaxtdan
bəri **34 teste** qədər genişlənib və yuxarıdakı sxem rəqəmləri də (cədvəl,
RLS, trigger sayı) eyni ana aiddir. Cari sayı canlı bazada özünüz yoxlayın.

Ətraflı: [`docs/database_deployment.md`](docs/database_deployment.md).

> ⚠️ **Bağlantı:** Supabase-in birbaşa host-u (`db.<ref>.supabase.co`) yalnız
> **IPv6**-dır və IPv4 şəbəkələrindən çatmır. **Session Pooler** istifadə edin:
> `aws-0-ap-southeast-1.pooler.supabase.com:5432`, user `postgres.<ref>`.

```powershell
# psql ilə
psql -h aws-0-ap-southeast-1.pooler.supabase.com -U postgres.<ref> -d postgres `
     -v ON_ERROR_STOP=1 -v kompasos_env=DEV -f database/schema.sql

# psql yoxdursa — Node ilə (bax scripts/db/README.md)
cd scripts/db; npm install; cd ../..
node scripts/db/apply.js database/schema.sql DEV
node scripts/db/apply.js database/tests/test_guards.sql
```

Skript **idempotentdir** — təkrar icra oluna bilər. İstehsalatda
`PRODUCTION` verin (DEV seed tenant yaradılmır).

---

## Yoxlama əmrləri

```powershell
ruff check src tests           # lint
ruff format --check src tests  # format
mypy src                       # 100% tip yoxlaması (strict) — 200 fayl
pytest tests/ -q               # 1363 test (43 skip: DB tələb edənlər)
pytest tests/unit --cov=src/domain --cov=src/shared --cov-fail-under=85
pytest tests/e2e -m e2e        # pytest-qt karkası
python scripts/check_contrast.py --include-high-contrast  # WCAG AA
pip-audit -r requirements.txt  # asılılıq zəiflik skanı
```

> İnteqrasiya testləri `DATABASE_URL` təyin edilmədikdə atlanır — lokalda
> "43 skipped" normaldır. Windows konsolunda Azərbaycan hərfləri üçün
> `PYTHONIOENCODING=utf-8` verin.

---

## Faza 1-də tətbiq olunan əsas zəmanətlər

| Zəmanət | Harada | Qərar |
|---|---|---|
| Modullar birbaşa əlaqə saxlamır — yalnız Event Bus | `src/shared/event_bus.py` | — |
| Çox-aqreqatlı əməliyyat yarımçıq qalmır (Saga + kompensasiya) | `src/shared/saga_orchestrator.py` | — |
| `PENDING_RECONCILIATION` heç vaxt sükutla itmir | `SagaPendingReconciliationEvent` | — |
| Saga siyasəti açıq reyestrdə, naməlum saga → ən sərt | `src/shared/saga_policies.py` | SEC-003 |
| **AES-256-GCM** + AAD kontekst bağlantısı | `security/encryption.py` | SEC-002 |
| Master açar DB/config-də plaintext saxlanılmır | `EnvironmentKeyProvider`, `WindowsDpapiKeyProvider` | — |
| **4-rəqəmli PIN üçün pepper** (10 000 variant problemi) | `security/hashing.py` | SEC-005 |
| Argon2id + zəif PIN/şifrə rədd + timing-safe verify | `security/hashing.py` | SEC-014 |
| **Username + şifrə girişi** (2FA yoxdur) | `use_cases/authentication.py` | SEC-016 |
| Sessiya: token hash-i, ikiqat müddət, ləğv | `auth_sessions` | SEC-011 |
| PIN/şifrə/token/sirr log-a düşmür | `logger.REDACTED_KEYS` | SEC-013 |
| Anti-fraud vəzifə ayrılığı (DB trigger-i) | `schema.sql` §18 | SEC-001 |
| Dörd-səviyyəli hardlock iyerarxiyası | `permission_flags.hardlock_level` | — |
| Strict Hierarchy (CEO↔CEO daxil) + Self-Escalation Guard | `schema.sql` §18 | SEC-006 |
| **`audit_logs` append-only** (owner-i də bağlayır) | `schema.sql` §26 | SEC-007 |
| **RLS fail-closed** + alt-cədvəl predikatları | `schema.sql` §27 | SEC-008 |
| Ayrıca tətbiq DB rolu (`kompasos_app`) | `schema.sql` §28, §30 | SEC-009 |
| Scheduler sükutla sönmür | `run_all_scheduled_jobs()`, `v_scheduled_job_health` | SEC-010 |
| `Delay = max(0, ...)`, `Total = Req + 2 × Delay` | `calculate_leave_penalty()` | — |
| Cərimə export kilidi (72 saat + REVERSED) | `v_exportable_fines` | — |
| Kamera operatoru fail-safe scoping | `camera_operator_store_assignment` | — |
| İmzasız istehsalat buraxılışı qadağandır | `.github/workflows/ci.yml` | SEC-012 |

Tam əsaslandırma: [`docs/security_decisions.md`](docs/security_decisions.md).

---

## İlk müştəri təhvilindən əvvəl əvəzlənməli — ARTIQ BOŞDUR

Bu bölmədə açıq maddə QALMADI. Aşağıdakı qeydlər bölmənin tarixçəsidir və
qəsdən saxlanılır: hər biri sənədin bir dəfə koddan geri qaldığını göstərir və
səbəbi ilə birlikdə oxunmalıdır.

**(BAĞLANDI — `assets/logo/` üçün 256×256 ixracı.** Burada yazılırdı ki, `.ico`
16/24/32/48/64 pillələrini daşıyır, «256 pilləsi ümumiyyətlə YOXDUR və qəsdən
yoxdur», çünki 64-ü böyütmək bulanıq nəticə verərdi. İzah yarımçıq idi:
məhdudiyyət qərar deyil, **MƏNBƏ çatışmazlığı** idi — əldəki ən böyük rastr
64×64 idi. `assets/logo/256.png` gətirildi, `scripts/build_icon.py` artıq BÜTÜN
pillələri həmin tək masterdən qurur və `.ico` 16/24/32/48/64/**256** daşıyır.
Windows-un «Böyük ikonlar» görünüşü daha 64-ü miqyaslamır.

Qapı da tərsinə çevrildi: `test_the_missing_large_tier_is_documented` (pillənin
YOXLUĞUNU qapılayırdı) yerinə
`test_the_large_tier_exists_and_is_not_upscaled` gəldi — o, pillənin
mövcudluğunu VƏ masterin həqiqətən 256×256 olduğunu birlikdə yoxlayır. İkincisi
olmasa, dizayn faylı bir gün kiçik ölçüdə ixrac edilsə `.ico` sükutla böyütmə
ilə qurulardı və reqressiya adı dəyişməmiş qapının altından keçərdi.**)**

**(BAĞLANDI — `assets/kompasos.ico` «placeholder»:** burada əvvəllər «hazırda
avtomatik yaradılmış placeholder (Deep Navy + Amber "K", 4 ölçü) … real loqosu
ilə əvəzlənməlidir» yazılırdı. Bu, `3ae2484` commit-indən sonra YANLIŞ idi —
real pərgar loqosu gətirilib, `.ico` ondan qurulur, splash və başlıq zolağı da
həmin fayl dəstini işlədir. Həmin commit README-yə toxunmadığı üçün sənəd
görülmüş bir işi hələ də görüləsi kimi göstərirdi.**)**

**Bu siyahıdan ÇIXARILAN maddə — `src/presentation/theme/tokens.py`:** əvvəlki
mətn «dizayn tokenləri Faza 4-də YARANIR; yarandığı an `check_contrast.py`
avtomatik "atlandı" rejimindən "yoxlanılır" rejiminə keçir» deyirdi. Fayl artıq
MÖVCUDDUR, yoxlayıcı isə "atlandı" rejimində deyil — real olaraq işləyir və
`tokens.py` ilə yanaşı `qss.py`-dəki FAKTİKİ istifadəni (`::placeholder`,
`:disabled`, `:focus`, `:hover`, sərhədlər) də ölçür. Yəni bu maddə "gözlənilən
iş" deyil, keçilmiş qapıdır — əmr üçün bax yuxarıdakı keyfiyyət qapıları
bölməsinə.

---

## Sənədlər

- `kompasos.md` — tam texniki spesifikasiya (mənbə həqiqət). **İşçi ağacında
  yoxdur:** repozitoriyadan çıxarılıb, mətn git tarixçəsindədir —
  `git show "$(git rev-list -1 HEAD -- kompasos.md)^:kompasos.md"`.
  Koddakı `kompasos.md bölmə N` istinadları mənbə göstəricisidir və
  qəsdən saxlanılır (bax `CLAUDE.md` §0)
- [`docs/security_decisions.md`](docs/security_decisions.md) — SEC-001…SEC-017 qərarları
- [`docs/open_questions.md`](docs/open_questions.md) — açıq/bağlanmış biznes sualları (BR-NNN)
- [`docs/risk_register.md`](docs/risk_register.md) — risk reyestri: bağlanmış
  risklər + hələ AÇIQ olan istismar riskləri, üstəgəl «Faza 3-ə keçən açıq
  öhdəliklər» cədvəli (risk deyil, iş maddəsi). **(ÇATIŞMAZLIQ DÜZƏLİŞİ:**
  burada sadəcə «(cari)» yazılırdı, halbuki faylın son bölməsi hələ də faza-
  bağlı öhdəlik siyahısıdır — «cari» sözü oxucuya sənədin tam yenilənmiş
  olduğunu vəd edirdi. Faylın ÖZ «Son yenilənmə» sətri həqiqi tarixi göstərir;
  vəziyyəti oradan oxuyun.**)**
- [`docs/dependency_policy.md`](docs/dependency_policy.md) — versiya hədləri və yeniləmə proseduru
- [`docs/key_rotation.md`](docs/key_rotation.md) — şifrələmə açarının rotasiyası
- [`docs/scheduler_setup.md`](docs/scheduler_setup.md) — pg_cron / xarici scheduler
- [`docs/phase1_risks.md`](docs/phase1_risks.md) — risk vəziyyəti və 96 test ssenarisi
- [`docs/root_parameters.md`](docs/root_parameters.md) — ROOT panelindən idarə olunan
  bütün limit və modul açarlarının kataloqu
- [`docs/drive_integration.md`](docs/drive_integration.md) — Google Drive razılığı,
  sübut şəkillərinin növbəsi və kvota nəzarəti
- [`docs/cli_reference.md`](docs/cli_reference.md) — `main.py`-ın bütün əmr sətri
  açarları (quraşdırma, diaqnostika, planlaşdırılmış işlər)
