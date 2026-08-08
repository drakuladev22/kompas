# KompasOS

Enterprise Leave / Fine / Break / Shift / ERP-1C / Task / Dashboard sistemi —
Bellona, İstikbal, Yataş və Enza Home brendləri ilə işləyən pərakəndə şəbəkə üçün
Windows masaüstü tətbiqi (`.exe`).

> **Status: FAZA 1 tamamlandı.** Bu repozitoriyada hazırda yalnız DDD skeleti,
> cross-cutting infrastruktur, tam DB sxemi və CI/CD pipeline var. Domen məntiqi
> (Faza 2), infrastruktur konnektorları (Faza 3) və GUI (Faza 4+) hələ yazılmayıb.
> Tam plan: [`kompasos.md`](kompasos.md), bölmə 10.

---

## Faza xəritəsi

| Faza | Əhatə | Status |
|---|---|---|
| 1 | DDD strukturu, Event Bus, DI, Saga, logger, şifrələmə, `schema.sql`, CI/CD | ✅ Tamamlandı |
| 2 | Domen entity-ləri, use case-lər, Guard-lar, Plugin API (sandbox), NavigationRegistry | ✅ Tamamlandı |
| 3 | Supabase repo-ları, çoxsaylı 1C konnektorları, offline buffer, lisenziya klienti, auto-update | ⬜ Gözləyir |
| 4 | PySide6 Shell (role-driven), Kiosk Mode, Camera Dashboard, dizayn sistemi | ⬜ Gözləyir |
| 5 | Root/CEO panelləri, özünə-xidmət alətləri, əməliyyat modulları | ⬜ Gözləyir |
| 6 | Satış xalları, hesabatlar, Master Lisenziya / Developer Paneli | ⬜ Gözləyir |

---

## Layihə strukturu

```
KompasOS/
├── src/
│   ├── domain/              # saf biznes qaydaları (xarici asılılıq YOXDUR)
│   │   ├── entities/        # ✅ LeaveRequest, AttendanceRecord, Employee, Fine
│   │   ├── value_objects/   # ✅ Pin, Money, PermissionFlag, penalty düsturu
│   │   ├── interfaces/      # ✅ 17 repository/servis portu (Protocol)
│   │   ├── policies.py      # ✅ BR-001/BR-002, sistem limitləri
│   │   └── events/          # ✅ domen hadisələri (LeaveVerifiedEvent, ...)
│   ├── application/         # ✅ use case-lər (Saga, Guard-lar, auth)
│   ├── infrastructure/
│   │   ├── security/        # ✅ AES-256-GCM, Argon2id+pepper, TOTP 2FA
│   │   ├── persistence/     # Faza 3
│   │   ├── erp/             # Faza 3 — çoxsaylı 1C konnektorları
│   │   └── notifications/   # Faza 3 — e-poçt fallback, crash reporting
│   ├── presentation/        # Faza 4 — PySide6
│   ├── shared/              # ✅ event_bus, di_container, saga_orchestrator,
│   │                        #    saga_policies, logger
│   └── main.py              # ✅ kompozisiya kökü + təhlükəsizlik self-check
├── database/
│   ├── schema.sql           # ✅ 46 cədvəl, RLS, append-only audit, cron
│   ├── tests/               # ✅ 17 DB-səviyyəli guard testi
│   └── migrations/          # Faza 2+ — nömrələnmiş miqrasiyalar
├── scripts/
│   ├── check_contrast.py    # ✅ WCAG AA yoxlayıcısı (CI-da işləyir)
│   └── generate_placeholder_icon.ps1
├── assets/kompasos.ico      # ⚠️ placeholder — real loqo ilə əvəzlənməlidir
├── tests/
│   ├── unit/                # ✅ domen/shared/security testləri
│   ├── integration/         # Faza 3
│   └── e2e/                 # ✅ pytest-qt karkası (ssenarilər Faza 4)
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
| **TOTP replay qorunması** + ehtiyat kodları | `security/totp.py` | SEC-004 |
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
