# KompasOS

Enterprise Leave / Fine / Break / Shift / ERP-1C / Task / Dashboard sistemi —
Bellona, İstikbal, Yataş və Enza Home brendləri ilə işləyən pərakəndə şəbəkə üçün
Windows masaüstü tətbiqi (`.exe`).

> **Status: altı fazanın hamısının qatları yazılıb.** DDD nüvəsi, domen
> məntiqi, təhlükəsizlik qatı, tam DB sxemi, CI/CD, persistence, 1C
> konnektorları, lisenziya/auto-update, dizayn sistemi + 27 ekran, Faza 5/6
> əməliyyat modulları və GUI kompozisiya kökü hazırdır.
> Tam plan: [`kompasos.md`](kompasos.md), bölmə 10.

---

## Faza xəritəsi

| Faza | Əhatə | Status |
|---|---|---|
| 1 | DDD strukturu, Event Bus, DI, Saga, logger, şifrələmə, `schema.sql`, CI/CD | ✅ Tamamlandı |
| 2 | Domen entity-ləri, use case-lər, Guard-lar, Plugin API (sandbox), NavigationRegistry | ✅ Tamamlandı |
| 3 | Supabase repo-ları, çoxsaylı 1C konnektorları, offline buffer, lisenziya klienti, auto-update | ✅ Tamamlandı |
| 4 | PySide6 Shell (role-driven), Kiosk Mode, Camera Dashboard, dizayn sistemi, kompozisiya kökü | ✅ Tamamlandı |
| 5 | Root/CEO panelləri, növbə/tabel/cərimə modulları, özünə-xidmət alətləri | ✅ Tamamlandı |
| 6 | Satış xalları, şübhəli satış növbəsi, hesabatlar, Master Lisenziya / Developer Paneli | ✅ Tamamlandı |

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
│   ├── presentation/        # Faza 4 — PySide6
│   ├── shared/              # ✅ event_bus, di_container, saga_orchestrator,
│   │                        #    saga_policies, logger
│   └── main.py              # ✅ kompozisiya kökü + təhlükəsizlik self-check
├── database/
│   ├── schema.sql           # ✅ 46 cədvəl, RLS, append-only audit, cron
│   ├── tests/               # ✅ 17 DB-səviyyəli guard testi
│   └── migrations/          # ✅ 001 username-auth · 002 Drive · 003 cərimə
│                            #    icmalı · 004 1C konnektoru · 005 lisenziya
│                            #    telemetriyası · 006 lisenziya RLS + expires_at
│                            #    · 007 bildiriş e-poçt növbəsi · 008 yenilənmə
│                            #    kataloqu + backup sağlamlığı · 009 app_versions
│                            #    + private `app-updates` bucket-i
├── scripts/
│   ├── check_contrast.py    # ✅ WCAG AA yoxlayıcısı (CI-da işləyir)
│   └── generate_placeholder_icon.ps1
├── assets/kompasos.ico      # ⚠️ placeholder — real loqo ilə əvəzlənməlidir
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

### Baza — ✅ QURULUB VƏ DOĞRULANIB

Sxem canlı Supabase layihəsinə tətbiq olunub (ap-southeast-1, PostgreSQL 17.6):
**46 cədvəl, 42 RLS siyasəti, 18 enum, 21 funksiya, 4 view, 23 trigger,
110 indeks**, seed tam. **Guard testləri 17/17 ✅**, idempotentlik doğrulanıb.

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
mypy src                       # 100% tip yoxlaması (strict)
pytest tests/unit -v           # unit testlər
pytest tests/unit --cov=src/domain --cov=src/shared --cov-fail-under=85
pytest tests/e2e -m e2e        # pytest-qt karkası
pip-audit -r requirements.txt  # asılılıq zəiflik skanı
```

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

## Faza 4-dən əvvəl əvəzlənməli

- **`assets/kompasos.ico`** — hazırda avtomatik yaradılmış placeholder
  (Deep Navy + Amber "K", 4 ölçü). Müştərinin real loqosu ilə əvəzlənməlidir
  (bax [`assets/README.md`](assets/README.md)).
- **`src/presentation/theme/tokens.py`** — dizayn tokenləri Faza 4-də yaranır;
  yarandığı an `scripts/check_contrast.py` avtomatik "atlandı" rejimindən
  "yoxlanılır" rejiminə keçir, CI-a toxunmaq lazım deyil.

---

## Sənədlər

- [`kompasos.md`](kompasos.md) — tam texniki spesifikasiya (mənbə həqiqət)
- [`docs/security_decisions.md`](docs/security_decisions.md) — SEC-001…SEC-014 qərarları
- [`docs/key_rotation.md`](docs/key_rotation.md) — şifrələmə açarının rotasiyası
- [`docs/scheduler_setup.md`](docs/scheduler_setup.md) — pg_cron / xarici scheduler
- [`docs/phase1_risks.md`](docs/phase1_risks.md) — risk vəziyyəti və 96 test ssenarisi
