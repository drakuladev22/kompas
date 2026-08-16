-- ===========================================================================
-- KompasOS — TAM POSTGRESQL SXEMİ (FAZA 1)
-- ===========================================================================
-- Spesifikasiya: kompasos.md, bölmə 1-9; PHASE 1, addım 4.
--
-- Bu skript idempotentdir: təkrar icra oluna bilər (IF NOT EXISTS / ON CONFLICT).
--
-- İCRA:
--     psql "$DATABASE_URL" -v kompasos_env=DEV -f database/schema.sql
--
-- `-v kompasos_env=DEV` verilmədikdə DEV seed tenant YARADILMIR (bax bölmə 8
-- və PHASE 1 addım 4 sonundakı qeyd).
--
-- QAYDA: Bütün tətbiq sorğuları 100% parametrləşdirilmiş olmalıdır (bölmə 2).
-- Bu sxem heç bir dinamik SQL qurulmasını tələb etmir.
-- ===========================================================================

\set ON_ERROR_STOP on
\if :{?kompasos_env}
\else
    \set kompasos_env 'PRODUCTION'
\endif

BEGIN;

-- psql dəyişəni dollar-quoted blok DAXİLİNDƏ interpolyasiya OLUNMUR, ona görə
-- onu əvvəlcə sessiya GUC-una köçürürük və DO blokları current_setting() ilə oxuyur.
SET kompasos.env TO :'kompasos_env';

-- ---------------------------------------------------------------------------
-- 0. GENİŞLƏNMƏLƏR
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS citext;        -- case-insensitive e-poçt
CREATE EXTENSION IF NOT EXISTS pg_trgm;       -- axtarış/filter (İcazə Matrisi UI)
-- pg_cron Supabase-də ayrıca aktivləşdirilir; yoxdursa cron qeydiyyatı atlanır.
-- CREATE EXTENSION IF NOT EXISTS pg_cron;

CREATE SCHEMA IF NOT EXISTS kompasos;
SET search_path TO kompasos, public;


-- ---------------------------------------------------------------------------
-- 1. ENUM TİPLƏRİ
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    -- Offline-first sinxronizasiya (bölmə 5)
    IF to_regtype('sync_status') IS NULL THEN
        CREATE TYPE sync_status AS ENUM ('PENDING', 'SYNCED', 'CONFLICT');
    END IF;

    -- Lisenziya / ödəniş statusu (bölmə 8)
    IF to_regtype('license_status') IS NULL THEN
        CREATE TYPE license_status AS ENUM ('AKTIV', 'ODENIS_GOZLENILIR', 'DEAKTIV');
    END IF;

    -- Morning Check-in statusu: ⚪ / 🟡 / 🟢 / rədd (bölmə 4)
    IF to_regtype('check_in_status') IS NULL THEN
        CREATE TYPE check_in_status AS ENUM (
            'NOT_STARTED',           -- ⚪ Günə Başlamayıb
            'PENDING_VERIFICATION',  -- 🟡 Giriş Təsdiqi Gözləyir
            'VERIFIED',              -- 🟢 Mağazada
            'REJECTED'               -- Operator rədd etdi → ⚪-a qayıdır, HR-a bildiriş
        );
    END IF;

    -- 3-Step Leave Verification statusu (bölmə 4)
    IF to_regtype('leave_status') IS NULL THEN
        CREATE TYPE leave_status AS ENUM (
            'OUTSIDE',                    -- 🔵 Xaricdə (STEP 1 tamamlandı)
            'PENDING_RETURN_VERIFICATION',-- 🟡 Gözləyir (STEP 2 tamamlandı)
            'VERIFIED',                   -- STEP 3 təsdiqləndi
            'TIMEOUT_ESCALATED',          -- 45 dəq. keçdi, HR_Admin/CEO-ya getdi
            'CANCELLED'
        );
    END IF;

    -- Cərimə mənbəyi (bölmə 4 — MANUAL CƏRİMƏ QEYDİYYATI)
    IF to_regtype('fine_source') IS NULL THEN
        CREATE TYPE fine_source AS ENUM ('AUTO_DELAY', 'MANUAL_CAMERA');
    END IF;

    -- Cərimə statusu — orijinal qeyd HEÇ VAXT silinmir (bölmə 4)
    IF to_regtype('fine_status') IS NULL THEN
        CREATE TYPE fine_status AS ENUM ('PENDING_REVIEW', 'PUBLISHED', 'REVERSED', 'REDUCED');
    END IF;

    -- Etiraz statusu (cərimə və xal etirazları üçün ortaq)
    IF to_regtype('appeal_status') IS NULL THEN
        CREATE TYPE appeal_status AS ENUM ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED');
    END IF;

    -- Növbə dəyişmə sorğusu (bölmə 3)
    IF to_regtype('shift_swap_status') IS NULL THEN
        CREATE TYPE shift_swap_status AS ENUM ('PENDING_APPROVAL', 'APPROVED', 'REJECTED');
    END IF;

    -- Tapşırıq statusu (bölmə 6)
    IF to_regtype('task_status') IS NULL THEN
        CREATE TYPE task_status AS ENUM (
            'OPEN', 'EVIDENCE_SUBMITTED', 'APPROVED', 'REJECTED', 'OVERDUE', 'CANCELLED'
        );
    END IF;

    -- Manual override / dual-control (bölmə 3, 4)
    IF to_regtype('override_status') IS NULL THEN
        CREATE TYPE override_status AS ENUM (
            'AUTO_APPROVED',        -- 30 dəq.-dən az fərq
            'PENDING_DUAL_CONTROL', -- ikinci təsdiq gözlənilir
            'APPROVED',
            'REJECTED'
        );
    END IF;

    -- Saga vəziyyəti (bölmə 1 — SAGA / COMPENSATING TRANSACTION QAYDASI)
    IF to_regtype('saga_status') IS NULL THEN
        CREATE TYPE saga_status AS ENUM (
            'PENDING', 'RUNNING', 'COMPLETED', 'COMPENSATING',
            'COMPENSATED', 'PENDING_RECONCILIATION', 'FAILED'
        );
    END IF;

    -- Fərdi icazə override effekti (Discord-style, bölmə 3)
    IF to_regtype('permission_effect') IS NULL THEN
        CREATE TYPE permission_effect AS ENUM ('GRANT', 'DENY');
    END IF;

    -- 1C composite matching etibarlılığı (bölmə 6)
    IF to_regtype('match_confidence') IS NULL THEN
        CREATE TYPE match_confidence AS ENUM (
            'EXACT_MATCH', 'LOW_CONFIDENCE_MATCH', 'MANUAL_MATCH', 'UNASSIGNED'
        );
    END IF;

    -- Xal hərəkəti statusu (bölmə 6 — xal etirazı)
    IF to_regtype('points_entry_status') IS NULL THEN
        CREATE TYPE points_entry_status AS ENUM ('ACTIVE', 'REVERSED', 'CORRECTED');
    END IF;

    -- Tema seçimi (bölmə 9)
    IF to_regtype('theme_preference') IS NULL THEN
        CREATE TYPE theme_preference AS ENUM ('LIGHT', 'DARK', 'SYSTEM');
    END IF;

    -- Dəstək ticket statusu (bölmə 8)
    IF to_regtype('ticket_status') IS NULL THEN
        CREATE TYPE ticket_status AS ENUM ('OPEN', 'IN_PROGRESS', 'WAITING_CUSTOMER', 'CLOSED');
    END IF;

    -- ERP server statusu (bölmə 7)
    IF to_regtype('erp_server_status') IS NULL THEN
        CREATE TYPE erp_server_status AS ENUM ('ACTIVE', 'INACTIVE', 'ERROR');
    END IF;

    -- Plugin təsdiq statusu (bölmə 1 — SANDBOX QAYDASI)
    IF to_regtype('plugin_status') IS NULL THEN
        CREATE TYPE plugin_status AS ENUM ('PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'DISABLED');
    END IF;
END
$$;


-- ---------------------------------------------------------------------------
-- 2. ÜMUMİ TRİGGER FUNKSİYALARI
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION set_updated_at() IS
    'Hər UPDATE-də updated_at sütununu yeniləyir.';


-- ---------------------------------------------------------------------------
-- 3. TENANT & LİSENZİYA (bölmə 8)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS license_tenants (
    tenant_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_name          TEXT        NOT NULL,
    license_key_hash     TEXT        NOT NULL,           -- Argon2 hash, plaintext DEYİL
    install_date         TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Spesifikasiya bölmə 8-də bu sütunlar azərbaycanca adlandırılıb;
    -- kodda ingiliscə identifikator, izahda orijinal ad saxlanılır.
    last_payment_date    DATE,                            -- son_ödəniş_tarixi
    next_payment_date    DATE,                            -- növbəti_ödəniş_tarixi
    status               license_status NOT NULL DEFAULT 'ODENIS_GOZLENILIR',
    grace_period_days    SMALLINT    NOT NULL DEFAULT 7
                            CHECK (grace_period_days BETWEEN 0 AND 30),
    offline_grace_days   SMALLINT    NOT NULL DEFAULT 14  -- LICENSE_UNVERIFIED (bölmə 8)
                            CHECK (offline_grace_days BETWEEN 7 AND 14),
    last_check_in_at     TIMESTAMPTZ,
    -- ŞİRKƏT-SƏVİYYƏLİ ƏLAQƏ — fərdi hesabdan TAM AYRI (bölmə 2, 8).
    -- Emergency Access Recovery-də kimlik təsdiqinin YEGANƏ mənbəyi və
    -- ödəniş/lisenziya bildirişlərinin ünvanıdır. Admin girişi ilə ƏLAQƏSİ YOX.
    company_contact_email TEXT       NOT NULL,
    company_contact_phone TEXT,
    -- LICENSE_INACTIVE ekranında göstərilən şəffaf məlumat (bölmə 8)
    deactivation_reason  TEXT,
    deactivated_at       TIMESTAMPTZ,
    app_version          TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_tenant_company_contact_email
        CHECK (company_contact_email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$')
);

DROP TRIGGER IF EXISTS trg_license_tenants_updated ON license_tenants;
CREATE TRIGGER trg_license_tenants_updated BEFORE UPDATE ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_tenants_status ON license_tenants (status);
CREATE INDEX IF NOT EXISTS idx_tenants_next_payment ON license_tenants (next_payment_date)
    WHERE status <> 'DEAKTIV';

COMMENT ON TABLE license_tenants IS
    'Çox-tenant lisenziya reyestri. Aktiv/Deaktiv keçidi YALNIZ Developer Panelindən '
    'edilir — tenant öz can_manage_license flag-i ilə bunu dəyişə bilməz (bölmə 8).';


-- ---------------------------------------------------------------------------
-- 4. MAĞAZALAR
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stores (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    code          TEXT NOT NULL,                 -- 1C Mağaza Kodu ilə uyğunlaşdırma açarı
    name          TEXT NOT NULL,                 -- məs. "Yataş Crescent Mall"
    brand         TEXT NOT NULL,                 -- Bellona | İstikbal | Yataş | Enza Home
    address       TEXT,
    timezone      TEXT NOT NULL DEFAULT 'Asia/Baku',
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, code)
);

DROP TRIGGER IF EXISTS trg_stores_updated ON stores;
CREATE TRIGGER trg_stores_updated BEFORE UPDATE ON stores
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_stores_tenant ON stores (tenant_id) WHERE is_active;


-- ---------------------------------------------------------------------------
-- 5. ROLLAR (POSITIONS) — İYERARXİYA PRİORİTETİ İLƏ (bölmə 3)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS positions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    code           TEXT NOT NULL,
    name_az        TEXT NOT NULL,
    -- İYERARXİYA PRİORİTETİ: Root=0, CEO=1, Admin=2, HR/Store/Camera=3, Satıcı=4
    -- (`Root` TƏK BAŞINA 0-dadır — `CEO` ondan DƏRHAL aşağıdır, bax §21 və
    --  `RolePriority` docstring-i; miqrasiya 048 mövcud bazaları köçürür.)
    -- DİAPAZON DOMENLƏ HƏRFİ UYĞUNDUR (049): `RolePriority` yalnız 0..4-ü
    -- tanıyır. Əvvəl hədd 0..9 idi və 5..9 aralığındakı sətir BAZADA qanuni,
    -- TƏTBİQDƏ isə oxunmaz olurdu — `mappers.position_from_row` həmin sətirdə
    -- `RolePriority(...)` çağırıb `ValueError` atırdı. Yeni pillə əlavə
    -- edilərsə HƏM `RolePriority`, HƏM bu CHECK dəyişməlidir (CLAUDE.md §5).
    priority       SMALLINT NOT NULL CHECK (priority BETWEEN 0 AND 4),
    is_system      BOOLEAN NOT NULL DEFAULT FALSE,   -- 7 defolt rol silinə bilməz
    -- "kamera-tipli" custom rol işarəsi: yalnız belə rollar anti-fraud
    -- flag-lərini daşıya bilər (bölmə 3, QORUYUCU QAYDALAR)
    is_camera_type BOOLEAN NOT NULL DEFAULT FALSE,
    description    TEXT,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_by     UUID,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, code)
);

-- Sistem rolları tenant_id IS NULL ilə şablon kimi saxlanılır.
CREATE UNIQUE INDEX IF NOT EXISTS uq_positions_system_code
    ON positions (code) WHERE tenant_id IS NULL;

DROP TRIGGER IF EXISTS trg_positions_updated ON positions;
CREATE TRIGGER trg_positions_updated BEFORE UPDATE ON positions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON COLUMN positions.priority IS
    'Strict Hierarchy Guard-ın əsası: can_control_user_permissions sahibi yalnız '
    'ÖZ priority dəyərindən CİDDİ ŞƏKİLDƏ BÖYÜK (daha aşağı səlahiyyətli) '
    'istifadəçilərə toxuna bilər (bölmə 3). Model: Root=0 (TƏK BAŞINA), CEO=1, '
    'Admin=2, HR_Admin/Mağaza_Meneceri/Kamera_Nəzarətçisi=3, Satıcı=4. '
    'Domen qarşılığı `RolePriority`; mövcud bazalar üçün miqrasiya 048.';


-- ---------------------------------------------------------------------------
-- 6. İCAZƏ REYESTRİ (SYSTEM PERMISSION REGISTRY) — bölmə 3
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS permission_flags (
    code            TEXT PRIMARY KEY,
    category        TEXT NOT NULL,        -- HR, KAMERA_CERIME, SATIS_MUKAFAT, ...
    name_az         TEXT NOT NULL,
    description_az  TEXT,
    -- DÖRD-SƏVİYYƏLİ HARDLOCK İYERARXİYASI (bölmə 3):
    --   0 = hardlock yoxdur (adi operativ flag)
    --   1 = YALNIZ Root (CEO-ya belə verilmir)
    --   2 = Root VƏ CEO
    --   3 = Root/CEO tərəfindən Admin-ə həvalə edilə bilər
    hardlock_level  SMALLINT NOT NULL DEFAULT 0 CHECK (hardlock_level BETWEEN 0 AND 3),
    -- ANTI-FRAUD: bu flag heç vaxt Mağaza_Meneceri/Satıcı-ya verilə bilməz
    is_anti_fraud   BOOLEAN NOT NULL DEFAULT FALSE,
    -- `is_camera_only`-nin ƏKSİ: flag kamera-tipli rola HEÇ VAXT verilmir
    -- (cərimə YARADAN ilə cərimə TƏSDİQ EDƏN ayrılmalıdır — migration 003).
    excludes_camera_role BOOLEAN NOT NULL DEFAULT FALSE,
    -- ANTI-FRAUD-un DAR alt-çoxluğu: yalnız Kamera_Nəzarətçisi və ya açıq
    -- şəkildə "kamera-tipli" işarələnmiş custom rollarda ola bilər.
    -- SPESİFİKASİYA ZİDDİYYƏTİNİN HƏLLİ: bölmə 3 dörd flag-i eyni cümlədə
    -- sadalayır, lakin `can_approve_dual_control_override` HR_Admin/CEO-ya
    -- lazımdır (bölmə 3 DUAL-CONTROL QAYDASI: "ikinci təsdiqə göndərilir").
    -- Əgər o da "yalnız kamera-tipli rollarda" olsaydı, dual-control heç vaxt
    -- təsdiqlənə bilməzdi. Ona görə iki qayda AYRILIR: hər dördü
    -- Mağaza_Meneceri/Satıcı-ya QADAĞANDIR (is_anti_fraud), lakin yalnız
    -- əməliyyat aparan üçü kamera-rolla məhdudlaşır (is_camera_only).
    is_camera_only  BOOLEAN NOT NULL DEFAULT FALSE,
    is_system       BOOLEAN NOT NULL DEFAULT TRUE,  -- FALSE = Root-un sonradan yaratdığı
    created_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE permission_flags IS
    'System Permission Registry (bölmə 3): YENİ flag yaratmaq yalnız Root-un '
    'inhisarındadır (can_manage_permissions, hardlock_level=1); yaradıldıqdan '
    'sonra CEO/Admin istifadə edə bilər.';


-- Rol → flag defolt təyinatı
CREATE TABLE IF NOT EXISTS position_permissions (
    position_id  UUID NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    flag_code    TEXT NOT NULL REFERENCES permission_flags(code) ON DELETE CASCADE,
    granted      BOOLEAN NOT NULL DEFAULT TRUE,
    granted_by   UUID,
    granted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (position_id, flag_code)
);

-- Fərdi (Discord-style) override — rol-defoltdan ÜSTÜNDÜR
CREATE TABLE IF NOT EXISTS user_permission_overrides (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL,   -- FK aşağıda, employees yaradıldıqdan sonra
    flag_code   TEXT NOT NULL REFERENCES permission_flags(code) ON DELETE CASCADE,
    effect      permission_effect NOT NULL,
    reason      TEXT,
    granted_by  UUID NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ,
    UNIQUE (user_id, flag_code)
);

CREATE INDEX IF NOT EXISTS idx_overrides_user ON user_permission_overrides (user_id);


-- ---------------------------------------------------------------------------
-- 7. İŞÇİLƏR (bölmə 2, 3, 6)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS employees (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    store_id              UUID REFERENCES stores(id) ON DELETE SET NULL,
    position_id           UUID NOT NULL REFERENCES positions(id),

    first_name            TEXT NOT NULL,
    last_name             TEXT NOT NULL,
    employee_code         TEXT,

    -- ADMIN-TIER AUTENTİFİKASİYA (bölmə 2): istifadəçi adı + Argon2 şifrə.
    -- Kamera_Nəzarətçisi də bu tier-dədir (sadə PIN-dən istisna edilib).
    -- 2FA/TOTP YOXDUR — bax migrations/001_username_auth.sql.
    username              CITEXT,                     -- giriş identifikatoru
    password_hash         TEXT,                       -- Argon2id
    must_change_password  BOOLEAN NOT NULL DEFAULT FALSE,
    password_changed_at   TIMESTAMPTZ,

    -- YALNIZ BİLDİRİŞ ÜÇÜN — autentifikasiyadan TAM ASILI DEYİL (bölmə 7).
    -- Boşdursa kritik bildiriş yalnız tətbiq-daxili qalır (gözlənilən davranış).
    notification_email    CITEXT,

    -- KIOSK PIN (bölmə 2, 4): YALNIZ Satıcı və digər işçi rolları üçün.
    -- Admin panelə giriş üçün İSTİFADƏ OLUNMUR.
    pin_hash              TEXT,                       -- Argon2id, plaintext DEYİL
    -- PEPPER LAZY MIGRATION (SEC-005): hash-in hansı pepper versiyası ilə
    -- yaradıldığını göstərir. Pepper rotasiyası zamanı köhnə sətirlər köhnə
    -- pepper ilə yoxlanılır, uğurlu girişdən SONRA yeni pepper ilə yenidən
    -- yazılır — kütləvi PIN/şifrə sıfırlaması LAZIM DEYİL.
    pepper_version        SMALLINT NOT NULL DEFAULT 1 CHECK (pepper_version >= 1),
    pin_failed_attempts   SMALLINT NOT NULL DEFAULT 0 CHECK (pin_failed_attempts >= 0),
    pin_locked_until      TIMESTAMPTZ,                -- 5 səhv → 15 dəq. lockout
    pin_last_reset_by     UUID,
    pin_last_reset_at     TIMESTAMPTZ,

    profile_photo_url     TEXT,                       -- Supabase Storage (bölmə 6)
    -- HƏSSAS: yalnız `can_view_employee_reports` sahibi (öz profilindən
    -- başqa) görür — yoxlama sorğu qatında da aparılır (migration 003).
    date_of_birth         DATE,
    hire_date             DATE,
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    deactivated_at        TIMESTAMPTZ,

    -- 1C COMPOSITE MATCHING açarının bir hissəsi (bölmə 6)
    one_c_seller_id       TEXT,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    sync_status           sync_status NOT NULL DEFAULT 'SYNCED',

    -- `notification_email` UNİKAL DEYİL: iki işçi eyni ünvanı göstərə bilər
    -- (ortaq şöbə qutusu). Unikallıq yalnız GİRİŞ identifikatoruna aiddir.
    UNIQUE (tenant_id, employee_code),
    CONSTRAINT chk_employee_username
        CHECK (username IS NULL OR username ~* '^[a-z0-9][a-z0-9._-]{2,31}$'),
    CONSTRAINT chk_employee_notification_email
        CHECK (notification_email IS NULL
               OR notification_email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    -- Hər işçinin ən azı bir autentifikasiya vasitəsi olmalıdır
    CONSTRAINT chk_employee_auth
        CHECK (pin_hash IS NOT NULL OR (username IS NOT NULL AND password_hash IS NOT NULL))
);

-- Partial unique: kiosk-yalnız işçilərdə `username` NULL-dur və məhdudlaşmır.
CREATE UNIQUE INDEX IF NOT EXISTS uq_employees_tenant_username
    ON employees (tenant_id, username) WHERE username IS NOT NULL;

DROP TRIGGER IF EXISTS trg_employees_updated ON employees;
CREATE TRIGGER trg_employees_updated BEFORE UPDATE ON employees
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_employees_store ON employees (store_id) WHERE is_active;
CREATE INDEX IF NOT EXISTS idx_employees_position ON employees (position_id);
CREATE INDEX IF NOT EXISTS idx_employees_tenant ON employees (tenant_id) WHERE is_active;
CREATE INDEX IF NOT EXISTS idx_employees_1c ON employees (one_c_seller_id)
    WHERE one_c_seller_id IS NOT NULL;

-- Mövcud bazalar üçün idempotent əlavə (CREATE TABLE IF NOT EXISTS köhnə
-- cədvələ sütun əlavə etmir).
ALTER TABLE employees
    ADD COLUMN IF NOT EXISTS pepper_version SMALLINT NOT NULL DEFAULT 1;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'chk_employee_pepper_version'
           AND connamespace = current_schema()::regnamespace
    ) THEN
        ALTER TABLE employees ADD CONSTRAINT chk_employee_pepper_version
            CHECK (pepper_version >= 1);
    END IF;
END
$$;

COMMENT ON COLUMN employees.pepper_version IS
    'Hash-in hansı pepper versiyası ilə yaradıldığı (SEC-005). Rotasiyadan '
    'sonra köhnə sətirlər köhnə pepper ilə yoxlanılır və uğurlu girişdən SONRA '
    'yeni pepper ilə yenidən yazılır (lazy migration) — kütləvi sıfırlama yoxdur.';

-- Gecikmiş FK-lar
ALTER TABLE user_permission_overrides
    DROP CONSTRAINT IF EXISTS fk_override_user,
    ADD CONSTRAINT fk_override_user
        FOREIGN KEY (user_id) REFERENCES employees(id) ON DELETE CASCADE;

-- QEYD (SEC-015): `NO ACTION` + `DEFERRABLE INITIALLY DEFERRED`.
--
-- `RESTRICT` DƏRHAL yoxlanılır — referens edən sətir EYNİ əməliyyatda silinsə
-- belə xəta verir. `NO ACTION` yoxlamanı STATEMENT sonuna saxlayır, lakin
-- tenant silinərkən cascade sırası zəmanətli olmadığı üçün bu da kifayət etmir:
-- A işçisi B-yə override veribsə, A silinərkən B-nin sətri hələ mövcud ola bilər.
--
-- `DEFERRABLE INITIALLY DEFERRED` yoxlamanı COMMIT anına keçirir — həmin an
-- bütün cascade silinmələri artıq bitib. Qoruma İTMİR: əgər tranzaksiya
-- sonunda hələ də orfan sətir varsa (məs. işçini TƏK-TƏK silmək cəhdi),
-- COMMIT uğursuz olur.
ALTER TABLE user_permission_overrides
    DROP CONSTRAINT IF EXISTS fk_override_granted_by,
    ADD CONSTRAINT fk_override_granted_by
        FOREIGN KEY (granted_by) REFERENCES employees(id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;


-- İstifadəçi tərcihləri — tema (bölmə 9) + dil (arxitektur-hazır, hazırda yalnız 'az')
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id     UUID PRIMARY KEY REFERENCES employees(id) ON DELETE CASCADE,
    theme       theme_preference NOT NULL DEFAULT 'SYSTEM',
    language    TEXT NOT NULL DEFAULT 'az' CHECK (language IN ('az')),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON COLUMN user_preferences.language IS
    'i18n arxitektura səviyyəsində hazırdır, lakin ilk buraxılışda YEGANƏ dil '
    'Azərbaycan dilidir (bax bölmə 9 və Faza 4). CHECK qəsdən dardır ki, '
    'tərcüməsi olmayan dil təsadüfən seçilməsin.';

DROP TRIGGER IF EXISTS trg_user_preferences_updated ON user_preferences;
CREATE TRIGGER trg_user_preferences_updated BEFORE UPDATE ON user_preferences
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- KAMERA OPERATORU — MAĞAZA TƏYİNATI (bölmə 4): many-to-many, fail-safe boş
CREATE TABLE IF NOT EXISTS camera_operator_store_assignment (
    operator_id  UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    store_id     UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    assigned_by  UUID NOT NULL REFERENCES employees(id),
    assigned_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (operator_id, store_id)
);

COMMENT ON TABLE camera_operator_store_assignment IS
    'DEFOLT-TƏHLÜKƏSİZ (fail-safe): sətir yoxdursa operator HEÇ BİR mağaza/işçi '
    'görmür. Defolt "hər şeyi göstər" DEYİL (bölmə 4).';

CREATE INDEX IF NOT EXISTS idx_camera_assignment_store
    ON camera_operator_store_assignment (store_id);


-- ---------------------------------------------------------------------------
-- 8. İŞ REJİMLƏRİ, NÖVBƏ MATRİSİ, SWAP (bölmə 3, 4)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS work_modes (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    name         TEXT NOT NULL,               -- "08:00–17:00", "Növbəli 2/2"
    start_time   TIME NOT NULL,
    end_time     TIME NOT NULL,
    is_overnight BOOLEAN NOT NULL DEFAULT FALSE,  -- end_time < start_time halı
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_by   UUID REFERENCES employees(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

DROP TRIGGER IF EXISTS trg_work_modes_updated ON work_modes;
CREATE TRIGGER trg_work_modes_updated BEFORE UPDATE ON work_modes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE work_modes IS
    'İş Rejimləri Konstruktoru (bölmə 4). start_time "Gecikib" təyinetməsinin '
    'istinad nöqtəsidir — Morning Check-in VERIFIED vaxtı bundan gec olarsa, '
    'Gündəlik Tabeldə "Gecikib" işarələnir (ayrıca cərimə YARATMIR).';


-- Interactive Shift Matrix (admin-kontrollu planlama)
CREATE TABLE IF NOT EXISTS shift_assignments (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    employee_id   UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    shift_date    DATE NOT NULL,
    work_mode_id  UUID REFERENCES work_modes(id),
    is_off_day    BOOLEAN NOT NULL DEFAULT FALSE,
    assigned_by   UUID REFERENCES employees(id),
    source        TEXT NOT NULL DEFAULT 'ADMIN_MATRIX'
                     CHECK (source IN ('ADMIN_MATRIX', 'SHIFT_SWAP')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (employee_id, shift_date),
    -- İş günüdürsə iş rejimi məcburidir; off-day-də olmamalıdır
    CONSTRAINT chk_shift_mode
        CHECK ((is_off_day AND work_mode_id IS NULL)
            OR (NOT is_off_day AND work_mode_id IS NOT NULL))
);

DROP TRIGGER IF EXISTS trg_shift_assignments_updated ON shift_assignments;
CREATE TRIGGER trg_shift_assignments_updated BEFORE UPDATE ON shift_assignments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_shift_date ON shift_assignments (shift_date);
CREATE INDEX IF NOT EXISTS idx_shift_employee_date
    ON shift_assignments (employee_id, shift_date DESC);


CREATE TABLE IF NOT EXISTS shift_swap_requests (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    employee_id       UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    target_date       DATE NOT NULL,
    requested_mode_id UUID REFERENCES work_modes(id),
    reason            TEXT NOT NULL CHECK (char_length(trim(reason)) >= 5),
    status            shift_swap_status NOT NULL DEFAULT 'PENDING_APPROVAL',
    -- Store Manager TƏSDİQ ETMİR, yalnız tövsiyə yazır (bölmə 3)
    manager_note      TEXT,
    manager_id        UUID REFERENCES employees(id),
    decided_by        UUID REFERENCES employees(id),
    decision_reason   TEXT,
    decided_at        TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    sync_status       sync_status NOT NULL DEFAULT 'SYNCED',
    CONSTRAINT chk_swap_decision
        CHECK ((status = 'PENDING_APPROVAL' AND decided_by IS NULL)
            OR (status <> 'PENDING_APPROVAL' AND decided_by IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_swap_pending ON shift_swap_requests (tenant_id, status)
    WHERE status = 'PENDING_APPROVAL';


-- ---------------------------------------------------------------------------
-- 9. DAVAMİYYƏT: MORNING CHECK-IN & GÜNDƏLİK TABEL (bölmə 4)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attendance_records (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    employee_id       UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    store_id          UUID NOT NULL REFERENCES stores(id),
    work_date         DATE NOT NULL,

    check_in_status   check_in_status NOT NULL DEFAULT 'NOT_STARTED',
    requested_at      TIMESTAMPTZ,      -- STEP A: [İşə Başladım] klik anı
    verified_at       TIMESTAMPTZ,      -- STEP C: günün RƏSMİ başlama vaxtı
    verified_by       UUID REFERENCES employees(id),   -- Kamera Operatoru
    reject_reason     TEXT,             -- STEP C rədd yolu (bölmə 4)
    rejected_at       TIMESTAMPTZ,

    is_late           BOOLEAN NOT NULL DEFAULT FALSE,  -- work_modes.start_time ilə müqayisə
    late_minutes      INTEGER NOT NULL DEFAULT 0 CHECK (late_minutes >= 0),
    is_unauthorized_absence BOOLEAN NOT NULL DEFAULT FALSE,

    ntp_verified      BOOLEAN NOT NULL DEFAULT FALSE,  -- TIME_DRIFT qorunması
    escalated_at      TIMESTAMPTZ,                     -- 45 dəq. timeout
    escalation_resolved_by UUID REFERENCES employees(id),

    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    sync_status       sync_status NOT NULL DEFAULT 'SYNCED',

    UNIQUE (employee_id, work_date),
    CONSTRAINT chk_attendance_verified
        CHECK (check_in_status <> 'VERIFIED'
            OR (verified_at IS NOT NULL AND verified_by IS NOT NULL)),
    CONSTRAINT chk_attendance_rejected
        CHECK (check_in_status <> 'REJECTED'
            OR (reject_reason IS NOT NULL AND char_length(trim(reject_reason)) >= 10))
);

DROP TRIGGER IF EXISTS trg_attendance_updated ON attendance_records;
CREATE TRIGGER trg_attendance_updated BEFORE UPDATE ON attendance_records
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_attendance_pending
    ON attendance_records (store_id, check_in_status)
    WHERE check_in_status = 'PENDING_VERIFICATION';
CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance_records (work_date);


CREATE TABLE IF NOT EXISTS daily_attendance_sheets (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    store_id           UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    sheet_date         DATE NOT NULL,
    is_confirmed       BOOLEAN NOT NULL DEFAULT FALSE,
    confirmed_by       UUID REFERENCES employees(id),   -- Mağaza_Meneceri
    confirmed_at       TIMESTAMPTZ,
    manager_note       TEXT,             -- məs. "PIN sistemi işləmirdi, şifahi təsdiq"
    mismatch_count     SMALLINT NOT NULL DEFAULT 0,     -- HR planı ilə uyğunsuzluq
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store_id, sheet_date)
);

DROP TRIGGER IF EXISTS trg_sheets_updated ON daily_attendance_sheets;
CREATE TRIGGER trg_sheets_updated BEFORE UPDATE ON daily_attendance_sheets
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE daily_attendance_sheets IS
    'AVTOMATİK ÖN-DOLDURMA: tabel BOŞ başlamır — attendance_records-dan '
    'doldurulur. Store Manager yalnız NƏZƏRDƏN KEÇİRİR və təsdiqləyir (bölmə 4).';


CREATE TABLE IF NOT EXISTS daily_attendance_sheet_lines (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sheet_id       UUID NOT NULL REFERENCES daily_attendance_sheets(id) ON DELETE CASCADE,
    employee_id    UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    auto_status    TEXT NOT NULL,   -- VERIFIED | LATE | OUTSIDE | ABSENT | OFF_DAY
    planned_off    BOOLEAN NOT NULL DEFAULT FALSE,
    has_mismatch   BOOLEAN NOT NULL DEFAULT FALSE,
    manager_note   TEXT,
    UNIQUE (sheet_id, employee_id)
);


-- ---------------------------------------------------------------------------
-- 10. İCAZƏ NÖVLƏRİ & 3-STEP LEAVE VERIFICATION (bölmə 4)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leave_types (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                 UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    name_az                   TEXT NOT NULL,   -- "Nahar Fasiləsi", "Siqaret Fasiləsi"
    default_duration_minutes  INTEGER NOT NULL CHECK (default_duration_minutes > 0),
    is_active                 BOOLEAN NOT NULL DEFAULT TRUE,
    created_by                UUID REFERENCES employees(id),
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name_az)
);

COMMENT ON TABLE leave_types IS
    'Seçim YALNIZ kateqoriyalaşdırma/hesabat məqsədlidir — Requested_Time/Delay/Total '
    'düsturunu DƏYİŞMİR (bölmə 4).';


CREATE TABLE IF NOT EXISTS leave_requests (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    employee_id           UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    store_id              UUID NOT NULL REFERENCES stores(id),
    leave_type_id         UUID REFERENCES leave_types(id),

    -- STEP 1: NTP-yə qarşı yoxlanılmış rəsmi sorğu vaxtı — cərimə düsturunun əsası
    requested_time        TIMESTAMPTZ NOT NULL,
    requested_ntp_verified BOOLEAN NOT NULL DEFAULT FALSE,

    -- STEP 2: işçi [Mən Qayıtdım] basdı
    return_claimed_time   TIMESTAMPTZ,

    -- STEP 3: Kamera Operatorunun təsdiqlədiyi FAKTİKİ qayıdış vaxtı.
    -- Spesifikasiya PHASE 1 addım 4 bu sütunu açıq şəkildə tələb edir.
    actual_return_time    TIMESTAMPTZ,
    verified_at           TIMESTAMPTZ,   -- operatorun düyməni kliklədiyi an (≠ hesablama əsası)
    verified_by           UUID REFERENCES employees(id),

    status                leave_status NOT NULL DEFAULT 'OUTSIDE',

    -- PENALTY LOGIC: Delay = max(0, actual_return_time − requested_time)
    --                Total = Requested + 2 × Delay
    requested_minutes     INTEGER NOT NULL DEFAULT 0 CHECK (requested_minutes >= 0),
    delay_minutes         INTEGER NOT NULL DEFAULT 0 CHECK (delay_minutes >= 0),
    total_minutes         INTEGER NOT NULL DEFAULT 0 CHECK (total_minutes >= 0),

    was_manual_override   BOOLEAN NOT NULL DEFAULT FALSE,
    escalated_at          TIMESTAMPTZ,    -- 45 dəq. timeout eskalasiyası
    escalation_resolved_by UUID REFERENCES employees(id),

    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    sync_status           sync_status NOT NULL DEFAULT 'SYNCED',

    -- Qayıdış vaxtı sorğu vaxtından əvvəl ola bilməz (bölmə 4, validasiya 1)
    CONSTRAINT chk_return_after_request
        CHECK (actual_return_time IS NULL OR actual_return_time >= requested_time),
    CONSTRAINT chk_verified_complete
        CHECK (status <> 'VERIFIED'
            OR (actual_return_time IS NOT NULL AND verified_by IS NOT NULL))
);

DROP TRIGGER IF EXISTS trg_leave_requests_updated ON leave_requests;
CREATE TRIGGER trg_leave_requests_updated BEFORE UPDATE ON leave_requests
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Bir işçinin eyni anda yalnız BİR açıq icazəsi ola bilər (STEP 2 düyməsinin şərti)
-- ---------------------------------------------------------------------------
-- Status dəsti domendəki `LeaveStatus.is_open` ilə EYNİDİR (miqrasiya 016).
-- `TIMEOUT_ESCALATED` DAXİLDİR: işçi hələ fiziki olaraq xaricdədir, sadəcə
-- təsdiq gecikib. Onu kənarda saxlamaq "45 dəqiqə gözlə, sonra istədiyin
-- qədər icazə aç" yolunu açıq qoyurdu — domen bloklayır, DB isə buraxırdı.
CREATE UNIQUE INDEX IF NOT EXISTS uq_leave_one_open_per_employee
    ON leave_requests (employee_id)
    WHERE status IN ('OUTSIDE', 'PENDING_RETURN_VERIFICATION', 'TIMEOUT_ESCALATED');

CREATE INDEX IF NOT EXISTS idx_leave_pending_queue
    ON leave_requests (store_id, status)
    WHERE status = 'PENDING_RETURN_VERIFICATION';
CREATE INDEX IF NOT EXISTS idx_leave_employee ON leave_requests (employee_id, requested_time DESC);


-- Cərimə düsturunun DB-səviyyəli təkrar-hesablaması (tək həqiqət mənbəyi)
CREATE OR REPLACE FUNCTION calculate_leave_penalty(
    p_requested_time     TIMESTAMPTZ,
    p_actual_return_time TIMESTAMPTZ,
    p_requested_minutes  INTEGER
) RETURNS TABLE (delay_minutes INTEGER, total_minutes INTEGER) AS $$
DECLARE
    v_delay INTEGER;
BEGIN
    IF p_actual_return_time IS NULL THEN
        RETURN QUERY SELECT 0, COALESCE(p_requested_minutes, 0);
        RETURN;
    END IF;

    -- Delay = max(0, Verified_Actual_Time − Requested_Time) — mənfi ola bilməz
    v_delay := GREATEST(
        0,
        CEIL(EXTRACT(EPOCH FROM (p_actual_return_time - p_requested_time)) / 60.0)::INTEGER
             - COALESCE(p_requested_minutes, 0)
    );

    -- Total = Requested + 2 × Delay
    RETURN QUERY SELECT v_delay, COALESCE(p_requested_minutes, 0) + 2 * v_delay;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION calculate_leave_penalty IS
    'PENALTY LOGIC (bölmə 4): Delay = max(0, Actual − Requested − icazə müddəti); '
    'Total = Requested + 2 × Delay. Hesablama YALNIZ təsdiqlənmiş faktiki vaxta '
    'əsaslanır, operatorun klik vaxtına YOX.';


-- MANUAL TIME OVERRIDE & DUAL-CONTROL (bölmə 3, 4)
CREATE TABLE IF NOT EXISTS manual_time_overrides (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    leave_request_id      UUID REFERENCES leave_requests(id) ON DELETE CASCADE,
    attendance_record_id  UUID REFERENCES attendance_records(id) ON DELETE CASCADE,
    operator_id           UUID NOT NULL REFERENCES employees(id),
    employee_id           UUID NOT NULL REFERENCES employees(id),

    system_time           TIMESTAMPTZ NOT NULL,
    overridden_time       TIMESTAMPTZ NOT NULL,
    delta_minutes         INTEGER NOT NULL,
    reason                TEXT NOT NULL CHECK (char_length(trim(reason)) >= 10),

    status                override_status NOT NULL DEFAULT 'AUTO_APPROVED',
    approved_by           UUID REFERENCES employees(id),   -- ikinci təsdiqçi
    approved_at           TIMESTAMPTZ,
    rejection_reason      TEXT,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    sync_status           sync_status NOT NULL DEFAULT 'SYNCED',

    -- Gələcək vaxt qəbul edilmir (bölmə 4, validasiya 2)
    CONSTRAINT chk_override_not_future CHECK (overridden_time <= system_time + INTERVAL '1 minute'),
    CONSTRAINT chk_override_target
        CHECK (num_nonnulls(leave_request_id, attendance_record_id) = 1),
    CONSTRAINT chk_override_dual_control
        CHECK (status <> 'APPROVED' OR approved_by IS NOT NULL),
    -- Kamera Operatoru öz override-ını ÖZÜ təsdiqləyə bilməz
    CONSTRAINT chk_override_self_approval CHECK (approved_by IS NULL OR approved_by <> operator_id)
);

CREATE INDEX IF NOT EXISTS idx_override_pending
    ON manual_time_overrides (tenant_id, status)
    WHERE status = 'PENDING_DUAL_CONTROL';

COMMENT ON TABLE manual_time_overrides IS
    'AUDIT (bölmə 4): hər override operator ID, işçi ID, sistem vaxtı, override '
    'vaxtı, məcburi səbəb və (30+ dəq. halında) ikinci təsdiqçinin ID-si ilə qeyd olunur.';


-- ---------------------------------------------------------------------------
-- 11. CƏRİMƏLƏR & ETİRAZLAR (bölmə 4, 6)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fine_types (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    name_az          TEXT NOT NULL,     -- "Formaya uyğun geyinməmək"
    standard_amount  NUMERIC(10, 2) NOT NULL CHECK (standard_amount >= 0),  -- AZN
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,   -- soft delete
    created_by       UUID REFERENCES employees(id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name_az)
);

COMMENT ON TABLE fine_types IS
    'ANTI-FRAUD (bölmə 4): Kamera Operatoru SƏRBƏST məbləğ təyin edə bilmir — '
    'yalnız CEO-nun təsdiqlədiyi növ və standart qiymətdən seçir.';


CREATE TABLE IF NOT EXISTS fines (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    -- NO ACTION + DEFERRABLE (RESTRICT DEYİL) — bax SEC-015 qeydi, bölmə 7
    employee_id              UUID NOT NULL REFERENCES employees(id)
                                 ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    store_id                 UUID NOT NULL REFERENCES stores(id),

    source                   fine_source NOT NULL,
    fine_type_id             UUID REFERENCES fine_types(id),      -- MANUAL_CAMERA üçün
    leave_request_id         UUID REFERENCES leave_requests(id),  -- AUTO_DELAY üçün

    amount                   NUMERIC(10, 2) NOT NULL CHECK (amount >= 0),
    fine_date                DATE NOT NULL DEFAULT CURRENT_DATE,
    issued_by                UUID REFERENCES employees(id),
    photo_evidence_url       TEXT,       -- MANUAL_CAMERA üçün MƏCBURİ

    -- AYLIQ İCMAL (migration 003): cərimə GÖRÜNMƏYƏN vəziyyətdə doğulur.
    status                   fine_status NOT NULL DEFAULT 'PENDING_REVIEW',
    -- "[Bütün Filiallara Göndər]" anı. 72-saatlıq etiraz pəncərəsi BUNDAN
    -- hesablanır, `created_at`-dan DEYİL — işçi cəriməni görmədən etiraz
    -- hüququnu itirməsin.
    published_at             TIMESTAMPTZ,
    reviewed_by              UUID REFERENCES employees(id),
    review_decision_reason   TEXT,
    review_batch_id          UUID,
    reversed_by              UUID REFERENCES employees(id),
    reversed_at              TIMESTAMPTZ,
    reversal_reason          TEXT,

    -- LOCK MEXANİZMİ (bölmə 6): export yalnız pəncərə bağlandıqdan sonra
    -- Nəşrdən ƏVVƏL NULL-dur; `chk_fine_published` PUBLISHED sətirdə
    -- onun dolu olmasını tələb edir.
    appeal_window_closes_at  TIMESTAMPTZ,
    exported_period          TEXT,       -- 'YYYY-MM' — təkrar export qorunması
    exported_at              TIMESTAMPTZ,

    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    sync_status              sync_status NOT NULL DEFAULT 'SYNCED',

    -- Mənbəyə görə məcburi sahələr
    CONSTRAINT chk_fine_manual_requires_evidence
        CHECK (source <> 'MANUAL_CAMERA'
            OR (fine_type_id IS NOT NULL
                AND photo_evidence_url IS NOT NULL
                AND issued_by IS NOT NULL)),
    CONSTRAINT chk_fine_auto_requires_leave
        CHECK (source <> 'AUTO_DELAY' OR leave_request_id IS NOT NULL),
    -- Nəşr olunmuş cərimənin HƏM anı, HƏM etiraz son tarixi olmalıdır.
    -- İSTİSNA (miqrasiya 015 ilə eyni qayda): icmalda "Sil" qərarı və saga
    -- kompensasiyası cəriməni HEÇ VAXT NƏŞR ETMƏDƏN `REVERSED` edir — belə
    -- sətirdə `published_at` NULL qalır. Şərt `appeal_window_closes_at`
    -- üzərində qurulmur, çünki `trg_fine_appeal_window` onu INSERT anında
    -- onsuz da doldurur; həqiqi görünürlük göstəricisi `published_at`-dır.
    CONSTRAINT chk_fine_published
        CHECK (status = 'PENDING_REVIEW'
            OR (published_at IS NOT NULL AND appeal_window_closes_at IS NOT NULL)
            OR (status = 'REVERSED' AND published_at IS NULL)),
    CONSTRAINT chk_fine_reversal
        CHECK (status <> 'REVERSED' OR (reversed_by IS NOT NULL AND reversal_reason IS NOT NULL))
);

DROP TRIGGER IF EXISTS trg_fines_updated ON fines;
CREATE TRIGGER trg_fines_updated BEFORE UPDATE ON fines
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_fines_employee ON fines (employee_id, fine_date DESC);
CREATE INDEX IF NOT EXISTS idx_fines_store_month ON fines (store_id, fine_date);
CREATE INDEX IF NOT EXISTS idx_fines_export_ready
    ON fines (tenant_id, published_at)
    WHERE status IN ('PUBLISHED', 'REDUCED') AND exported_period IS NULL;
CREATE INDEX IF NOT EXISTS idx_fines_pending_review
    ON fines (tenant_id, fine_date) WHERE status = 'PENDING_REVIEW';

-- YARIŞ QAPAĞI (miqrasiya 015 ilə eyni qayda — hər ikisi ardıcıl tətbiq olunur)
-- ---------------------------------------------------------------------------
-- İki Kamera Operatoru eyni icazə sorğusunu eyni anda təsdiqləyə bilir: oxu
-- ilə yazı arasındakı pəncərədə hər ikisi statusu hələ `PENDING_RETURN_
-- VERIFICATION` görür. İndeks olmasa nəticə eyni gecikməyə görə İKİ cərimə,
-- yəni ikiqat pul kəsintisi olardı.
--
-- Şərtdə `REVERSED` QƏSDƏN YOXDUR: Saga kompensasiyası uğursuz təsdiqdə
-- cəriməni `REVERSED` edir (məbləğ 0.00, qeyd silinmir). Ölü sətir indeks
-- yerini tutsaydı, işçinin həmin STEP 3-ü TƏKRAR təsdiqlətməsi əbədi
-- bloklanardı. `REDUCED` isə daxildir — azaldılmış məbləğ hələ də ödənilir.
CREATE UNIQUE INDEX IF NOT EXISTS uq_fines_one_live_auto_delay_per_leave
    ON fines (leave_request_id)
    WHERE source = 'AUTO_DELAY'
      AND leave_request_id IS NOT NULL
      AND status IN ('PENDING_REVIEW', 'PUBLISHED', 'REDUCED');

-- Mövcud bazalarda köhnə `RESTRICT` qaydasını `NO ACTION`-a keçirir
-- (yuxarıdakı inline tərif yalnız YENİ quraşdırmalara təsir edir).
DO $$
BEGIN
    -- Mövcud bazalarda köhnə (RESTRICT və ya deferrable OLMAYAN) qaydanı yeniləyir;
    -- yeni quraşdırmalarda inline tərif onsuz da düzgündür, blok isə idempotentdir.
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fines_employee_id_fkey'
          AND (confdeltype = 'r' OR NOT condeferrable)
    ) THEN
        ALTER TABLE fines DROP CONSTRAINT fines_employee_id_fkey;
        ALTER TABLE fines ADD CONSTRAINT fines_employee_id_fkey
            FOREIGN KEY (employee_id) REFERENCES employees(id)
            ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
        RAISE NOTICE
            'fines_employee_id_fkey → NO ACTION DEFERRABLE olaraq yeniləndi (SEC-015)';
    END IF;
END
$$;

COMMENT ON COLUMN fines.exported_period IS
    'LOCK MEXANİZMİ (bölmə 6, HÜQUQİ RİSK): cərimə export-a YALNIZ (a) etiraz '
    'pəncərəsi bağlandıqdan sonra VƏ (b) statusu REVERSED olmadıqda düşür.';


CREATE TABLE IF NOT EXISTS fine_appeals (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    fine_id        UUID NOT NULL REFERENCES fines(id) ON DELETE CASCADE,
    employee_id    UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    reason         TEXT NOT NULL CHECK (char_length(trim(reason)) >= 10),
    status         appeal_status NOT NULL DEFAULT 'PENDING',
    decided_by     UUID REFERENCES employees(id),      -- HR_Admin
    decision_note  TEXT,
    decided_at     TIMESTAMPTZ,
    new_amount     NUMERIC(10, 2) CHECK (new_amount IS NULL OR new_amount >= 0),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    sync_status    sync_status NOT NULL DEFAULT 'SYNCED',
    UNIQUE (fine_id)   -- hər cəriməyə bir etiraz
);

CREATE INDEX IF NOT EXISTS idx_appeals_pending ON fine_appeals (tenant_id, status)
    WHERE status = 'PENDING';


-- ---------------------------------------------------------------------------
-- 12. TAPŞIRIQLAR (bölmə 6)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tasks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    store_id      UUID REFERENCES stores(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    description   TEXT,
    assignee_id   UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    assigned_by   UUID NOT NULL REFERENCES employees(id),
    deadline      TIMESTAMPTZ NOT NULL,
    status        task_status NOT NULL DEFAULT 'OPEN',
    completed_at  TIMESTAMPTZ,
    reviewed_by   UUID REFERENCES employees(id),   -- can_approve_task_evidence sahibi
    reviewed_at   TIMESTAMPTZ,
    reject_reason TEXT,
    escalated_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    sync_status   sync_status NOT NULL DEFAULT 'SYNCED',
    CONSTRAINT chk_task_reject CHECK (status <> 'REJECTED' OR reject_reason IS NOT NULL)
);

DROP TRIGGER IF EXISTS trg_tasks_updated ON tasks;
CREATE TRIGGER trg_tasks_updated BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks (assignee_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_overdue ON tasks (deadline)
    WHERE status IN ('OPEN', 'EVIDENCE_SUBMITTED');


CREATE TABLE IF NOT EXISTS task_evidence (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id      UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    file_url     TEXT NOT NULL,
    file_size    INTEGER CHECK (file_size IS NULL OR file_size <= 5242880),  -- maks. 5 MB
    mime_type    TEXT CHECK (mime_type IN ('image/jpeg', 'image/png', 'image/webp')),
    uploaded_by  UUID NOT NULL REFERENCES employees(id),
    uploaded_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_task_evidence_task ON task_evidence (task_id);


-- ---------------------------------------------------------------------------
-- 13. ERP / 1C ÇOXSAYLI SERVERLƏR (bölmə 7)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS erp_servers (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    server_name           TEXT NOT NULL,          -- "Bellona — Bakı Anbarı"
    host                  TEXT NOT NULL,
    port                  INTEGER NOT NULL CHECK (port BETWEEN 1 AND 65535),
    username              TEXT NOT NULL,
    password_encrypted    TEXT NOT NULL,          -- Fernet — plaintext QADAĞANDIR
    status                erp_server_status NOT NULL DEFAULT 'INACTIVE',
    last_successful_sync  TIMESTAMPTZ,
    last_error            TEXT,
    last_error_at         TIMESTAMPTZ,
    sync_interval_seconds INTEGER NOT NULL DEFAULT 300 CHECK (sync_interval_seconds >= 30),
    created_by            UUID REFERENCES employees(id),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, server_name)
);

DROP TRIGGER IF EXISTS trg_erp_servers_updated ON erp_servers;
CREATE TRIGGER trg_erp_servers_updated BEFORE UPDATE ON erp_servers
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- Hər server üçün ƏVVƏLKİ İŞLƏK konfiqurasiya (bir kliklə rollback, bölmə 7)
CREATE TABLE IF NOT EXISTS erp_server_config_backups (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id     UUID NOT NULL REFERENCES erp_servers(id) ON DELETE CASCADE,
    config_json_encrypted TEXT NOT NULL,   -- bütöv konfiqurasiya, Fernet ilə
    backed_up_by  UUID REFERENCES employees(id),
    backed_up_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    was_verified  BOOLEAN NOT NULL DEFAULT TRUE   -- yalnız test uğurlu olan konfiqurasiya
);

CREATE INDEX IF NOT EXISTS idx_erp_backup_server
    ON erp_server_config_backups (server_id, backed_up_at DESC);


CREATE TABLE IF NOT EXISTS store_server_mapping (
    store_id       UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    server_id      UUID NOT NULL REFERENCES erp_servers(id) ON DELETE CASCADE,
    one_c_store_code TEXT NOT NULL,       -- composite matching açarının bir hissəsi
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (store_id, server_id)
);


-- ---------------------------------------------------------------------------
-- 14. SATIŞ & XAL SİSTEMİ (bölmə 6)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sales_transactions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    server_id         UUID NOT NULL REFERENCES erp_servers(id),
    -- 1C COMPOSITE MATCHING açarı (bölmə 6)
    one_c_seller_id   TEXT NOT NULL,
    one_c_store_code  TEXT NOT NULL,
    one_c_document_id TEXT NOT NULL,
    employee_id       UUID REFERENCES employees(id),   -- NULL = təyin olunmamış
    store_id          UUID REFERENCES stores(id),
    gross_amount      NUMERIC(14, 2) NOT NULL CHECK (gross_amount >= 0),
    transaction_date  DATE NOT NULL,
    confidence        match_confidence NOT NULL DEFAULT 'UNASSIGNED',
    matched_by        UUID REFERENCES employees(id),   -- manual həll edildikdə
    matched_at        TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    sync_status       sync_status NOT NULL DEFAULT 'SYNCED',
    UNIQUE (server_id, one_c_document_id)
);

CREATE INDEX IF NOT EXISTS idx_sales_review_queue
    ON sales_transactions (tenant_id, confidence)
    WHERE confidence IN ('LOW_CONFIDENCE_MATCH', 'UNASSIGNED');
CREATE INDEX IF NOT EXISTS idx_sales_employee_date
    ON sales_transactions (employee_id, transaction_date);

COMMENT ON COLUMN sales_transactions.confidence IS
    'Mətn-əsaslı ad uyğunlaşdırması YALNIZ fallback-dır; nəticə '
    'LOW_CONFIDENCE_MATCH kimi işarələnib "Təyin Olunmamış / Şübhəli '
    'Uyğunlaşma" növbəsinə düşür (bölmə 6).';


CREATE TABLE IF NOT EXISTS points_ledger (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    employee_id       UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    delta_points      INTEGER NOT NULL,
    reason            TEXT NOT NULL,
    source_transaction_id UUID REFERENCES sales_transactions(id),
    period_start      DATE NOT NULL,   -- 6 aylıq dövr: 01-01 və ya 07-01
    status            points_entry_status NOT NULL DEFAULT 'ACTIVE',
    corrected_by      UUID REFERENCES employees(id),
    corrected_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_points_employee_period
    ON points_ledger (employee_id, period_start) WHERE status = 'ACTIVE';

COMMENT ON TABLE points_ledger IS
    'Xal hərəkətləri ledger formatındadır — orijinal qeyd SİLİNMİR, yalnız '
    'REVERSED/CORRECTED statusu əlavə olunur (bölmə 6, etiraz mexanizmi).';


CREATE TABLE IF NOT EXISTS points_appeals (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    ledger_id      UUID NOT NULL REFERENCES points_ledger(id) ON DELETE CASCADE,
    employee_id    UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    reason         TEXT NOT NULL CHECK (char_length(trim(reason)) >= 10),
    status         appeal_status NOT NULL DEFAULT 'PENDING',
    window_closes_at TIMESTAMPTZ NOT NULL,   -- 72 saat, cərimə ilə eyni model
    decided_by     UUID REFERENCES employees(id),
    decision_note  TEXT,
    decided_at     TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ledger_id)
);


CREATE TABLE IF NOT EXISTS rewards (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    name_az      TEXT NOT NULL,
    cost_points  INTEGER NOT NULL CHECK (cost_points > 0),
    stock        INTEGER,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);


CREATE TABLE IF NOT EXISTS reward_redemptions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    reward_id     UUID NOT NULL REFERENCES rewards(id),
    employee_id   UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    points_spent  INTEGER NOT NULL CHECK (points_spent > 0),
    approved_by   UUID REFERENCES employees(id),   -- can_manage_sales_points
    approved_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ---------------------------------------------------------------------------
-- 15. ROOT CONTROL CENTER: LİMİTLƏR & FEATURE TOGGLE-LAR (bölmə 3)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS system_limits (
    tenant_id      UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    limit_key      TEXT NOT NULL,
    limit_value    TEXT NOT NULL,
    value_type     TEXT NOT NULL DEFAULT 'INTEGER'
                      CHECK (value_type IN ('INTEGER', 'DECIMAL', 'BOOLEAN', 'TEXT')),
    min_value      TEXT,
    max_value      TEXT,
    description_az TEXT,
    changed_by     UUID REFERENCES employees(id),
    changed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, limit_key)
);

COMMENT ON TABLE system_limits IS
    'YALNIZ Root (can_manage_system_limits, hardlock_level=1). Bu dəyərlər bütün '
    'tenant-ın davranışına təsir etdiyi üçün hər dəyişiklik audit_logs-a düşür.';


CREATE TABLE IF NOT EXISTS feature_toggles (
    tenant_id            UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    module_key           TEXT NOT NULL,
    is_enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    -- Struktur-kritik modullar (məs. Kamera Təsdiqi) söndürülərkən əlavə
    -- xəbərdarlıq modalı + yazılı təsdiq tələb olunur (bölmə 3)
    is_structural        BOOLEAN NOT NULL DEFAULT FALSE,
    description_az       TEXT,
    changed_by           UUID REFERENCES employees(id),
    changed_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    disable_confirmation TEXT,   -- struktur modul üçün yazılı təsdiq mətni
    PRIMARY KEY (tenant_id, module_key)
);

COMMENT ON TABLE feature_toggles IS
    'RETROAKTİV TƏSİR QAYDASI (bölmə 3): deaktivasiya YALNIZ yeni instansiyalara '
    'təsir edir — mövcud/tarixi qeydlər toxunulmaz qalır, silinmir, export-lardan '
    'yox olmur.';


-- ---------------------------------------------------------------------------
-- 16. AUDIT, TƏHLÜKƏSİZLİK, SAGA, MİQRASİYA
-- ---------------------------------------------------------------------------
-- QEYD (SEC-007): `tenant_id` QƏSDƏN foreign key DEYİL. Audit qeydləri
-- tenant silinsə belə YAŞAMALIDIR — `ON DELETE SET NULL` isə audit sətrinə
-- UPDATE deməkdir və aşağıdakı dəyişməzlik trigger-i ilə ziddiyyət təşkil edərdi.
CREATE TABLE IF NOT EXISTS audit_logs (
    id             BIGSERIAL PRIMARY KEY,
    tenant_id      UUID,
    occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id       UUID REFERENCES employees(id) ON DELETE SET NULL,
    actor_role     TEXT,
    action         TEXT NOT NULL,        -- MANUAL_TIME_OVERRIDE, PERMISSION_GRANTED, ...
    entity_type    TEXT NOT NULL,
    entity_id      UUID,
    before_state   JSONB,
    after_state    JSONB,
    reason         TEXT,
    correlation_id UUID,                 -- saga/iş axını izi
    ip_address     INET,
    machine_name   TEXT,
    app_version    TEXT,
    sync_status    sync_status NOT NULL DEFAULT 'SYNCED'
);

CREATE INDEX IF NOT EXISTS idx_audit_tenant_time ON audit_logs (tenant_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_logs (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs (actor_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_correlation ON audit_logs (correlation_id)
    WHERE correlation_id IS NOT NULL;

COMMENT ON TABLE audit_logs IS
    'Append-only. Silmə/redaktə tətbiq səviyyəsində qadağandır; DB rolu üçün '
    'yalnız INSERT/SELECT verilməlidir (bax bölmə 17 RLS/GRANT qeydi).';


-- db_migration_events — DB switcher tarixçəsi (bölmə 2)
CREATE TABLE IF NOT EXISTS db_migration_events (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    initiated_by         UUID NOT NULL REFERENCES employees(id),
    source_target        TEXT NOT NULL,   -- CLOUD | PRIVATE_SERVER
    destination_target   TEXT NOT NULL,
    maintenance_window_start TIMESTAMPTZ NOT NULL,
    maintenance_window_end   TIMESTAMPTZ,
    preflight_checksum   TEXT,
    postflight_checksum  TEXT,
    checksum_matched     BOOLEAN,
    pending_buffer_flushed BOOLEAN NOT NULL DEFAULT FALSE,
    rolled_back          BOOLEAN NOT NULL DEFAULT FALSE,
    rollback_reason      TEXT,
    status               TEXT NOT NULL DEFAULT 'IN_PROGRESS'
                            CHECK (status IN ('IN_PROGRESS', 'COMPLETED', 'ROLLED_BACK', 'FAILED')),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE db_migration_events IS
    'Cloud ↔ Private Server keçidi yalnız maintenance window rejimində, məcburi '
    'pre-flight checksum və avtomatik rollback ilə icra olunur (bölmə 2).';


-- Saga instansiyaları (bölmə 1)
CREATE TABLE IF NOT EXISTS saga_instances (
    saga_id           UUID PRIMARY KEY,
    tenant_id         UUID REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    saga_name         TEXT NOT NULL,
    status            saga_status NOT NULL,
    compensation_outcome TEXT,
    failed_step       TEXT,
    error_message     TEXT,
    correlation_id    UUID,
    step_log          JSONB NOT NULL DEFAULT '[]'::JSONB,
    started_at        TIMESTAMPTZ NOT NULL,
    finished_at       TIMESTAMPTZ,
    reconciled_by     UUID REFERENCES employees(id),
    reconciled_at     TIMESTAMPTZ,
    reconciliation_note TEXT
);

CREATE INDEX IF NOT EXISTS idx_saga_pending
    ON saga_instances (tenant_id, status)
    WHERE status = 'PENDING_RECONCILIATION';

COMMENT ON TABLE saga_instances IS
    'PENDING_RECONCILIATION sistemin ən ciddi məlumat-bütövlüyü vəziyyətidir — '
    'e-poçt fallback kanalı ilə bildirilir və heç vaxt sükutla qeyd olunmur '
    '(bölmə 1 və 7).';


-- Təhlükəsizlik hadisələri (PIN lockout, uğursuz login — bölmə 2)
CREATE TABLE IF NOT EXISTS security_events (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     UUID REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type    TEXT NOT NULL,   -- PIN_FAILED, PIN_LOCKOUT, LOGIN_FAILED, ...
    employee_id   UUID REFERENCES employees(id) ON DELETE SET NULL,
    -- Cəhd edilən GİRİŞ identifikatoru (mövcud olmayan hesab da qeyd olunur).
    username_attempt CITEXT,
    ip_address    INET,
    machine_name  TEXT,
    details       JSONB
);

CREATE INDEX IF NOT EXISTS idx_security_events_time
    ON security_events (tenant_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_security_events_employee
    ON security_events (employee_id, occurred_at DESC);


-- Aylıq Cərimə İcmalının push əməliyyatının auditi (migration 003)
CREATE TABLE IF NOT EXISTS monthly_fine_review_batches (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id              UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    reviewed_by            UUID NOT NULL REFERENCES employees(id),
    review_month           TEXT NOT NULL,      -- 'YYYY-MM'
    pushed_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_kept_count       INTEGER NOT NULL DEFAULT 0 CHECK (total_kept_count >= 0),
    total_reversed_count   INTEGER NOT NULL DEFAULT 0 CHECK (total_reversed_count >= 0),
    CONSTRAINT chk_batch_month CHECK (review_month ~ '^\d{4}-(0[1-9]|1[0-2])$')
);

CREATE INDEX IF NOT EXISTS idx_review_batches_tenant
    ON monthly_fine_review_batches (tenant_id, review_month DESC);


-- Offline sync konfliktləri (bölmə 5) — last-write-wins QADAĞANDIR
CREATE TABLE IF NOT EXISTS sync_conflicts (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    table_name     TEXT NOT NULL,
    record_id      UUID NOT NULL,
    local_version  JSONB NOT NULL,
    remote_version JSONB NOT NULL,
    detected_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_by    UUID REFERENCES employees(id),   -- HR_Admin manual həlli
    resolved_at    TIMESTAMPTZ,
    resolution     TEXT CHECK (resolution IN ('KEPT_LOCAL', 'KEPT_REMOTE', 'MERGED')),
    resolution_note TEXT
);

CREATE INDEX IF NOT EXISTS idx_sync_conflicts_open
    ON sync_conflicts (tenant_id) WHERE resolved_at IS NULL;


-- ---------------------------------------------------------------------------
-- 17. BİLDİRİŞLƏR, DƏSTƏK, CRASH, PLUGIN, BACKUP (bölmə 5, 7, 8)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    recipient_id   UUID REFERENCES employees(id) ON DELETE CASCADE,
    category       TEXT NOT NULL,   -- TIMEOUT_ESCALATION, DUAL_CONTROL_PENDING, ...
    title_az       TEXT NOT NULL,
    body_az        TEXT NOT NULL,
    is_critical    BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE → e-poçt fallback məcburi
    email_sent     BOOLEAN NOT NULL DEFAULT FALSE,
    email_sent_at  TIMESTAMPTZ,
    read_at        TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notifications_unread
    ON notifications (recipient_id, created_at DESC) WHERE read_at IS NULL;
-- BU İNDEKS MİQRASİYA 007-DƏ ƏVƏZLƏNİR — VƏ BU, QÜSUR DEYİL.
-- 007 `email_attempts` + `email_next_attempt_at` sütunlarını ƏLAVƏ EDİR və
-- indeksi həmin sütunlarla yenidən qurur (`DROP INDEX IF EXISTS` ilə).
-- Buradakı tərifi 007-nin versiyası ilə əvəz etmək MÜMKÜN DEYİL: o sütunlar
-- bu faylda mövcud deyil, yəni bazis sxem tək başına tətbiq oluna bilməzdi.
-- Yəni fərq qatlanma nizamının nəticəsidir, unudulmuş geri-köçürmə deyil
-- (müq. `enforce_anti_fraud_segregation()` — orada fərq HƏQİQİ qüsur idi).
CREATE INDEX IF NOT EXISTS idx_notifications_email_pending
    ON notifications (created_at) WHERE is_critical AND NOT email_sent;


CREATE TABLE IF NOT EXISTS support_tickets (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    opened_by     UUID NOT NULL REFERENCES employees(id),
    subject       TEXT NOT NULL,
    status        ticket_status NOT NULL DEFAULT 'OPEN',
    first_response_at TIMESTAMPTZ,     -- SLA izləməsi (bölmə 8)
    closed_at     TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_tickets_updated ON support_tickets;
CREATE TRIGGER trg_tickets_updated BEFORE UPDATE ON support_tickets
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


CREATE TABLE IF NOT EXISTS support_messages (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id   UUID NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
    sender_id   UUID REFERENCES employees(id),   -- NULL = hazırlayıcı tərəf
    is_from_developer BOOLEAN NOT NULL DEFAULT FALSE,
    body        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_support_messages_ticket
    ON support_messages (ticket_id, created_at);


-- Anonimləşdirilmiş crash hesabatları — PII YOXDUR (bölmə 8)
CREATE TABLE IF NOT EXISTS crash_reports (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    anonymous_tenant_ref TEXT NOT NULL,   -- tenant_id-nin hash-ı, birbaşa ID DEYİL
    app_version       TEXT NOT NULL,
    exception_type    TEXT NOT NULL,
    stack_trace       TEXT NOT NULL,
    fingerprint       TEXT NOT NULL,      -- tezliyə görə qruplaşdırma açarı
    os_version        TEXT,
    occurred_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_crash_fingerprint ON crash_reports (fingerprint, occurred_at DESC);

COMMENT ON TABLE crash_reports IS
    'HEÇ BİR PII saxlanılmır (bölmə 8): yalnız stack-trace + versiya + anonim '
    'tenant referansı. İşçi PII-sinə uzaqdan çıxış yoxdur.';


CREATE TABLE IF NOT EXISTS plugins (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    version           TEXT NOT NULL,
    publisher         TEXT,
    signature         TEXT NOT NULL,      -- rəqəmsal imza (bölmə 1 SANDBOX QAYDASI)
    signature_verified BOOLEAN NOT NULL DEFAULT FALSE,
    status            plugin_status NOT NULL DEFAULT 'PENDING_APPROVAL',
    approved_by       UUID REFERENCES employees(id),   -- yalnız Root/CEO
    approved_at       TIMESTAMPTZ,
    manifest          JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name, version),
    CONSTRAINT chk_plugin_approved
        CHECK (status <> 'APPROVED' OR (signature_verified AND approved_by IS NOT NULL))
);


CREATE TABLE IF NOT EXISTS backup_records (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    backup_type   TEXT NOT NULL CHECK (backup_type IN ('NIGHTLY_AUTO', 'PRE_MIGRATION', 'MANUAL')),
    storage_ref   TEXT NOT NULL,
    size_bytes    BIGINT,
    checksum      TEXT NOT NULL,
    retention_until DATE NOT NULL,      -- minimum 30 gün (bölmə 7)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    restored_at   TIMESTAMPTZ,
    restored_by   UUID REFERENCES employees(id)
);

CREATE INDEX IF NOT EXISTS idx_backups_tenant ON backup_records (tenant_id, created_at DESC);


-- ---------------------------------------------------------------------------
-- 17b. AUTENTİFİKASİYA SESSİYALARI (SEC-011)
-- ---------------------------------------------------------------------------
-- Bölmə 2: "Kamera_Nəzarətçisi növbə başında bir dəfə e-poçt+şifrə ilə
-- Dashboard-a daxil olur və növbə boyu sessiya açıq qalır."
-- Sessiyanın "növbə boyu" açıq qalması o deməkdir ki, onun MÜDDƏTİ və LƏĞVİ
-- idarə olunmalıdır — əks halda gecə növbəsinə qalan açıq sessiya ertəsi gün
-- başqasının əlinə keçə bilər.
CREATE TABLE IF NOT EXISTS auth_sessions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    user_id          UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    -- Token-in ÖZÜ saxlanılmır, yalnız SHA-256 daycesti (DB sızsa belə
    -- mövcud sessiyalar oğurlana bilməz).
    token_hash       TEXT NOT NULL UNIQUE,
    context          TEXT NOT NULL CHECK (context IN ('ADMIN_PANEL', 'CAMERA_DASHBOARD', 'KIOSK')),
    issued_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at       TIMESTAMPTZ NOT NULL,
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Mütləq maksimum: sessiya aktiv olsa belə bu vaxtdan sonra bitir
    absolute_expiry  TIMESTAMPTZ NOT NULL,
    revoked_at       TIMESTAMPTZ,
    revoked_by       UUID REFERENCES employees(id),
    revocation_reason TEXT,
    machine_name     TEXT,
    ip_address       INET,
    CONSTRAINT chk_session_expiry CHECK (expires_at <= absolute_expiry)
);

CREATE INDEX IF NOT EXISTS idx_sessions_active
    ON auth_sessions (user_id, expires_at DESC)
    WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_sessions_cleanup ON auth_sessions (absolute_expiry);

COMMENT ON TABLE auth_sessions IS
    'Sessiya müddətləri (tövsiyə): ADMIN_PANEL — 30 dəq. hərəkətsizlik / 8 saat '
    'mütləq; CAMERA_DASHBOARD — 12 saat mütləq (bir növbə), hərəkətsizlik '
    'yoxlaması YOX (operator ekrana baxır, klikləmir); KIOSK — sessiya yoxdur, '
    'hər əməliyyat üçün PIN. Dəyərlər system_limits-dən oxunur (Faza 2).';

CREATE OR REPLACE FUNCTION cron_prune_expired_sessions() RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    WITH pruned AS (
        DELETE FROM auth_sessions
        WHERE absolute_expiry < now() - INTERVAL '7 days'
        RETURNING 1
    )
    SELECT count(*) INTO v_count FROM pruned;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- ---------------------------------------------------------------------------
-- 18. HARDCODED TƏHLÜKƏSİZLİK ZƏMANƏTLƏRİ (DB-SƏVİYYƏLİ MÜDAFİƏ)
-- ---------------------------------------------------------------------------
-- Bunlar bölmə 3-də "HARDCODED CORE SAFETY RULES" kimi təsvir olunub və
-- Feature Toggle ilə söndürülə BİLMƏZ. Tətbiq qatındakı Guard use case-lərinə
-- (Faza 2) ƏLAVƏ olaraq, burada defense-in-depth kimi təkrarlanır.

-- ---------------------------------------------------------------------------
-- BU GÖVDƏ MİQRASİYA 013 + 048 İLƏ EYNİ OLMALIDIR (DB-1 konsolidasiyası)
-- ---------------------------------------------------------------------------
-- Auditdə tapılan qüsur: `schema.sql`-dəki versiya 013-ün gətirdiyi PRİORİTET
-- qaydasını heç vaxt almamışdı. Yəni tam miqrasiya zənciri tətbiq olunmuş baza
-- düzgün davranırdı, `schema.sql` tək başına quraşdırılmış baza isə ZƏİF qapı
-- alırdı: "satıcı-pilləli" CUSTOM rol (kod `SATICI` deyil, prioritet 4) bütün
-- anti-fraud flag-lərini DB səviyyəsində qəbul edərdi. Domen qatı onu
-- bloklayırdı — yəni qayda İKİ yerdə EYNİ deyildi (CLAUDE.md §5-in pozulması)
-- və müdafiənin ikinci qatı sükutla yox idi.
--
-- İkinci fərq erkən çıxışda idi: köhnə gövdə YALNIZ `is_anti_fraud` bayrağına
-- baxırdı, yəni `is_camera_only` və `excludes_camera_role` yoxlamaları
-- anti-fraud OLMAYAN flag üçün heç vaxt işə düşmürdü.
--
-- Aşağıdakı gövdə miqrasiya 048-in son versiyasının HƏRFƏN eynisidir. Onu
-- dəyişəndə 048-i də dəyişin — `tests/unit/test_schema_migration_parity.py`
-- bu cütü avtomatik müqayisə edir.
CREATE OR REPLACE FUNCTION enforce_anti_fraud_segregation()
RETURNS TRIGGER AS $$
DECLARE
    v_is_anti_fraud   BOOLEAN;
    v_is_camera_only  BOOLEAN;
    v_excl_camera     BOOLEAN;
    v_position_code   TEXT;
    v_priority        SMALLINT;
    v_is_camera_type  BOOLEAN;
BEGIN
    SELECT is_anti_fraud, is_camera_only, excludes_camera_role
      INTO v_is_anti_fraud, v_is_camera_only, v_excl_camera
      FROM permission_flags
     WHERE code = NEW.flag_code;

    IF NOT COALESCE(v_is_anti_fraud, FALSE)
       AND NOT COALESCE(v_is_camera_only, FALSE)
       AND NOT COALESCE(v_excl_camera, FALSE) THEN
        RETURN NEW;
    END IF;

    IF TG_TABLE_NAME = 'position_permissions' THEN
        SELECT code, priority, is_camera_type
          INTO v_position_code, v_priority, v_is_camera_type
          FROM positions WHERE id = NEW.position_id;
    ELSE
        SELECT p.code, p.priority, p.is_camera_type
          INTO v_position_code, v_priority, v_is_camera_type
          FROM employees e JOIN positions p ON p.id = e.position_id
         WHERE e.id = NEW.user_id;
    END IF;

    -- (a) Sistem rolları — adbaad qadağa (dəyişmir).
    -- (b) Prioritet 4 (ən aşağı pillə, `RolePriority.STAFF`) — HƏR rol,
    --     custom da daxil. Domen `_PRIORITY_TO_ROLE[STAFF] = SELLER` ilə
    --     eyni nəticəni verir. 048-ə qədər burada 3 yazılırdı.
    IF v_position_code IN ('MAGAZA_MENECERI', 'SATICI')
       OR COALESCE(v_priority, 0) >= 4 THEN
        RAISE EXCEPTION
            'ANTI-FRAUD POZUNTUSU: "%" flag-i "%" rolundakı istifadəçiyə verilə bilməz '
            '(bölmə 3, vəzifə ayrılığı hardlock-u; prioritet=%)',
            NEW.flag_code, COALESCE(v_position_code, '?'), COALESCE(v_priority, -1);
    END IF;

    IF COALESCE(v_excl_camera, FALSE) AND COALESCE(v_is_camera_type, FALSE) THEN
        RAISE EXCEPTION
            'VƏZİFƏ AYRILIĞI: "%" flag-i kamera-tipli rola verilə bilməz '
            '(cəriməni yaradan onu təsdiq edə bilməz)', NEW.flag_code;
    END IF;

    IF COALESCE(v_is_camera_only, FALSE) AND NOT COALESCE(v_is_camera_type, FALSE) THEN
        RAISE EXCEPTION
            'ANTI-FRAUD POZUNTUSU: "%" flag-i yalnız kamera-tipli rollarda ola bilər',
            NEW.flag_code;
    END IF;

    -- SEC-001: kamera-tipli rol dual-control TƏSDİQİNİ daşıya bilməz.
    IF NEW.flag_code = 'can_approve_dual_control_override'
       AND COALESCE(v_is_camera_type, FALSE) THEN
        RAISE EXCEPTION
            'SEC-001: dual-control təsdiqi kamera-tipli rola verilə bilməz';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_anti_fraud_position ON position_permissions;
CREATE TRIGGER trg_anti_fraud_position
    BEFORE INSERT OR UPDATE ON position_permissions
    FOR EACH ROW EXECUTE FUNCTION enforce_anti_fraud_segregation();

DROP TRIGGER IF EXISTS trg_anti_fraud_override ON user_permission_overrides;
CREATE TRIGGER trg_anti_fraud_override
    BEFORE INSERT OR UPDATE ON user_permission_overrides
    FOR EACH ROW EXECUTE FUNCTION enforce_anti_fraud_segregation();


CREATE OR REPLACE FUNCTION enforce_permission_hardlock() RETURNS TRIGGER AS $$
DECLARE
    v_level SMALLINT;
    v_priority SMALLINT;
    v_position_code TEXT;
BEGIN
    SELECT hardlock_level INTO v_level FROM permission_flags WHERE code = NEW.flag_code;
    IF COALESCE(v_level, 0) = 0 THEN
        RETURN NEW;
    END IF;

    IF TG_TABLE_NAME = 'position_permissions' THEN
        IF NOT NEW.granted THEN
            RETURN NEW;
        END IF;
        SELECT code, priority INTO v_position_code, v_priority
        FROM positions WHERE id = NEW.position_id;
    ELSE
        IF NEW.effect <> 'GRANT' THEN
            RETURN NEW;
        END IF;
        SELECT p.code, p.priority INTO v_position_code, v_priority
        FROM employees e JOIN positions p ON p.id = e.position_id
        WHERE e.id = NEW.user_id;
    END IF;

    -- Səviyyə 1: YALNIZ Root (CEO-ya belə verilmir)
    IF v_level = 1 AND v_position_code <> 'ROOT' THEN
        RAISE EXCEPTION
            'HARDLOCK POZUNTUSU: "%" flag-i YALNIZ Root roluna məxsusdur (bölmə 3, '
            'dörd-səviyyəli hardlock iyerarxiyası, səviyyə 1)', NEW.flag_code;
    END IF;

    -- Səviyyə 2: Root VƏ CEO
    IF v_level = 2 AND v_position_code NOT IN ('ROOT', 'CEO') THEN
        RAISE EXCEPTION
            'HARDLOCK POZUNTUSU: "%" flag-i yalnız Root/CEO rollarına verilə bilər '
            '(bölmə 3, səviyyə 2)', NEW.flag_code;
    END IF;

    -- Səviyyə 3: Admin-ə həvalə edilə bilər, amma operativ rollardan aşağı YOX.
    -- HƏDD 2-DİR (Admin), 1 DEYİL: Root/CEO prioritet ayrılığından sonra
    -- Root=0, CEO=1, Admin=2. Domen qarşılığı `HardlockLevel.allows()`-dadır
    -- və orada müqayisə SİMVOLLADIR (`<= RolePriority.ADMIN`), yəni sürüşməni
    -- avtomatik udur; burada ədəd yazılmalıdır (bax miqrasiya 048).
    IF v_level = 3 AND COALESCE(v_priority, 9) > 2 THEN
        RAISE EXCEPTION
            'HARDLOCK POZUNTUSU: "%" flag-i yalnız priority <= 2 olan rollara '
            '(Root/CEO/Admin) verilə bilər (bölmə 3, səviyyə 3)', NEW.flag_code;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_hardlock_position ON position_permissions;
CREATE TRIGGER trg_hardlock_position
    BEFORE INSERT OR UPDATE ON position_permissions
    FOR EACH ROW EXECUTE FUNCTION enforce_permission_hardlock();

DROP TRIGGER IF EXISTS trg_hardlock_override ON user_permission_overrides;
CREATE TRIGGER trg_hardlock_override
    BEFORE INSERT OR UPDATE ON user_permission_overrides
    FOR EACH ROW EXECUTE FUNCTION enforce_permission_hardlock();


-- SELF-ESCALATION GUARD, 1-ci hissə: istifadəçi öz icazə sətrinə toxuna bilməz
--
-- NİYƏ EFFEKT ŞƏRTİ YOXDUR (migration 014 ilə genişləndirildi):
-- Əvvəl burada `AND NEW.effect = 'GRANT'` şərti var idi, yəni özünə `DENY`
-- yazmaq mümkün qalırdı. Domen (`permission_guards._assert_not_self`) isə
-- EFFEKTDƏN ASILI OLMAYARAQ bloklayır — və doğru olan odur: öz səlahiyyətini
-- azaltmaq da səlahiyyət dəyişikliyidir, iyerarxiya + audit yolundan
-- keçməlidir. Üstəlik `UNIQUE (user_id, flag_code)` səbəbindən özünə yazılmış
-- `DENY` sətri sonradan `UPDATE` üçün "tutulmuş yer" rolunu oynayırdı.
-- İki qatın fərqli davranması auditə hansının həqiqət olduğunu deməyə imkan
-- vermirdi (CLAUDE.md §5 — hər qayda İKİ yerdə EYNİ olmalıdır).
CREATE OR REPLACE FUNCTION enforce_self_escalation_guard() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.granted_by = NEW.user_id THEN
        RAISE EXCEPTION
            'SELF-ESCALATION GUARD: istifadəçi öz icazə sətrinə toxuna bilməz '
            '(effekt: % — GRANT və DENY üçün eyni qayda, bölmə 3)', NEW.effect;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_self_escalation_guard() IS
    'Self-Escalation Guard, 1-ci hissə (bölmə 3): aktor öz icazə sətrinə '
    'toxuna bilməz. 014: əvvəl yalnız GRANT bloklanırdı, domen isə '
    '(`_assert_not_self`) hər iki effekti bloklayır — iki qat uyğunlaşdırıldı.';

DROP TRIGGER IF EXISTS trg_self_escalation ON user_permission_overrides;
CREATE TRIGGER trg_self_escalation
    BEFORE INSERT OR UPDATE ON user_permission_overrides
    FOR EACH ROW EXECUTE FUNCTION enforce_self_escalation_guard();


-- SELF-ESCALATION GUARD, 2-ci hissə: səlahiyyət verən həmin flag-ə SAHİB olmalıdır
--
-- NİYƏ AYRICA TRIGGER LAZIMDIR (migration 014):
-- Yuxarıdakı dörd yoxlama yalnız «flag ↔ HƏDƏF» və «aktor ↔ hədəf pilləsi»
-- əlaqələrinə baxır; «aktor ↔ FLAG» əlaqəsi heç yerdə yoxlanılmırdı. Nəticədə
-- ekranı yan keçən skript üçün belə yol açıq qalırdı: `Admin` özündə OLMAYAN
-- `can_manage_leave_types` flag-ini aşağı pilləli bir istifadəçiyə verir və
-- həmin hesabla işləyir — yəni səlahiyyət artırması bir addım dolayı yolla.
--
-- Domen qarşılıqları (semantika EYNİLƏ təkrarlanır, yenisi icad edilmir):
--   * `permission_guards._assert_actor_owns_flag` — fərdi override;
--   * `position_management._apply_flags`          — rol-defolt.
--
-- Qaydanın dörd istisnası:
--   1. Geri alma (`DENY` / `granted = FALSE`) yoxlanılmır — icazəni GERİ
--      ALMAQ səlahiyyət artırması deyil (domendəki ilk şərtin eynisi).
--   2. `granted_by IS NULL` — sistem seed-i (§23, §24, §25). O anda hələ heç
--      bir işçi yoxdur; istisna olmasaydı tenant ümumiyyətlə qurula bilməzdi.
--   3. `Root` — icazə kataloqunun sahibidir. Seed-ə görə onda kamera-əməliyyat
--      flag-ləri YOXDUR, lakin onları paylamalıdır (əks halda kamera rolunu
--      heç kim konfiqurasiya edə bilməzdi). MƏHZ rol KODU yoxlanılır, çünki
--      `Position.effective_system_role` də yalnız kodu `ROOT` olanı `ROOT`
--      sayır — prioritet 0-lı custom rol `CEO` semantikasına düşür.
--   4. Eyni sətrin təkrar yazılışı — izahı funksiyanın içindədir.
--
-- NİYƏ `v_effective_permissions` GÖRÜNÜŞÜ İŞLƏDİLMİR: o, `WHERE e.is_active`
-- filtri daşıyır və deaktiv aktoru "flag-siz" göstərərdi; domen
-- `has_permission` isə aktivlikdən asılı deyil. Fərqli semantika iki qatı
-- yenidən ayırardı.
CREATE OR REPLACE FUNCTION enforce_grantor_owns_flag() RETURNS TRIGGER AS $$
DECLARE
    v_actor        UUID;
    v_actor_code   TEXT;
    v_actor_effect permission_effect;
    v_role_granted BOOLEAN;
    v_owns         BOOLEAN;
BEGIN
    IF TG_TABLE_NAME = 'position_permissions' THEN
        IF NOT NEW.granted THEN
            RETURN NEW;
        END IF;
    ELSE  -- user_permission_overrides
        IF NEW.effect <> 'GRANT' THEN
            RETURN NEW;
        END IF;
    END IF;

    -- İDEMPOTENT TƏKRAR YAZILIŞ İSTİSNASI (istisna 4).
    -- `EmployeeRepository._sync_overrides()` işçinin HƏR yazılışında bütün
    -- override sətirlərini yenidən UPSERT edir (`ON CONFLICT DO UPDATE`), yəni
    -- bu trigger köhnə, ARTIQ TƏSDİQLƏNMİŞ sətirlər üçün də işə düşür. Səlahiyyət
    -- verənin flag-i sonradan geri alınıbsa, istisna olmadan işçinin adının
    -- redaktəsi belə çökərdi — halbuki heç bir YENİ səlahiyyət verilmir.
    -- Domen də eyni cür davranır: `apply_override()` yalnız YENİ qərarı yoxlayır,
    -- mövcud sətrin təkrar yazılışını yox. Sətir eyni qaldıqda əlavə hüquq
    -- yaranmır, ona görə istisna qoruma boşluğu açmır.
    IF TG_TABLE_NAME = 'position_permissions' THEN
        IF EXISTS (
            SELECT 1 FROM position_permissions pp
             WHERE pp.position_id = NEW.position_id
               AND pp.flag_code   = NEW.flag_code
               AND pp.granted     = NEW.granted
               AND pp.granted_by IS NOT DISTINCT FROM NEW.granted_by
        ) THEN
            RETURN NEW;
        END IF;
    ELSIF EXISTS (
        SELECT 1 FROM user_permission_overrides upo
         WHERE upo.user_id    = NEW.user_id
           AND upo.flag_code  = NEW.flag_code
           AND upo.effect     = NEW.effect
           AND upo.granted_by IS NOT DISTINCT FROM NEW.granted_by
           AND upo.expires_at IS NOT DISTINCT FROM NEW.expires_at
    ) THEN
        RETURN NEW;
    END IF;

    v_actor := NEW.granted_by;

    -- Sistem seed-i (istisna 2).
    IF v_actor IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT p.code INTO v_actor_code
      FROM employees e
      JOIN positions p ON p.id = e.position_id
     WHERE e.id = v_actor;

    -- Aktor tapılmadı: `position_permissions.granted_by`-da FK yoxdur, həmçinin
    -- RLS aktorun sətrini gizlədə bilər. `enforce_hierarchy_guard` eyni halda
    -- `RETURN NEW` edir — iki trigger eyni yazıya fərqli qərar verməməlidir.
    IF v_actor_code IS NULL THEN
        RETURN NEW;
    END IF;

    IF v_actor_code = 'ROOT' THEN   -- istisna 3
        RETURN NEW;
    END IF;

    -- Effektiv sahiblik: fərdi override → rol-defolt → FALSE
    -- (`Employee.has_permission()` ilə eyni ardıcıllıq; vaxtı keçmiş override
    --  sayılmır, `DENY` isə rol-defoltu ÜSTƏLƏYİR).
    SELECT upo.effect INTO v_actor_effect
      FROM user_permission_overrides upo
     WHERE upo.user_id = v_actor
       AND upo.flag_code = NEW.flag_code
       AND (upo.expires_at IS NULL OR upo.expires_at > now());

    IF v_actor_effect IS NOT NULL THEN
        v_owns := (v_actor_effect = 'GRANT');
    ELSE
        SELECT COALESCE(pp.granted, FALSE) INTO v_role_granted
          FROM employees e
          LEFT JOIN position_permissions pp
                 ON pp.position_id = e.position_id
                AND pp.flag_code = NEW.flag_code
         WHERE e.id = v_actor;
        v_owns := COALESCE(v_role_granted, FALSE);
    END IF;

    IF NOT v_owns THEN
        RAISE EXCEPTION
            'SELF-ESCALATION GUARD: "%" flag-i səlahiyyəti verən istifadəçidə '
            '(%) aktiv deyil — özündə olmayan icazə başqasına və ya rola '
            'verilə bilməz (bölmə 3)', NEW.flag_code, v_actor;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_grantor_owns_flag() IS
    'Self-Escalation Guard, 2-ci hissə (bölmə 3): aktor YALNIZ özündə AKTİV '
    'olan flag-i verə bilər. Domen qarşılıqları: '
    '`permission_guards._assert_actor_owns_flag` (fərdi override) və '
    '`position_management._apply_flags` (rol-defolt). Dörd istisna: geri alma '
    '(DENY / granted=FALSE), `granted_by IS NULL` (sistem seed-i), `ROOT` və '
    'dəyişməyən sətrin təkrar yazılışı (repozitoriya hər save-də UPSERT edir).';

-- Hər İKİ yazı yolu bağlanır. Rol tərəfi vacibdir, çünki əks halda qadağa bir
-- addımla yan keçilərdi: "özümdə olmayan flag-i custom rola qoyum, sonra həmin
-- rolu hədəfə təyin edim".
DROP TRIGGER IF EXISTS trg_grantor_owns_flag_override ON user_permission_overrides;
CREATE TRIGGER trg_grantor_owns_flag_override
    BEFORE INSERT OR UPDATE ON user_permission_overrides
    FOR EACH ROW EXECUTE FUNCTION enforce_grantor_owns_flag();

DROP TRIGGER IF EXISTS trg_grantor_owns_flag_position ON position_permissions;
CREATE TRIGGER trg_grantor_owns_flag_position
    BEFORE INSERT OR UPDATE ON position_permissions
    FOR EACH ROW EXECUTE FUNCTION enforce_grantor_owns_flag();


-- STRICT HIERARCHY GUARD: yalnız CİDDİ ŞƏKİLDƏ aşağı prioritetli istifadəçiyə
CREATE OR REPLACE FUNCTION enforce_hierarchy_guard() RETURNS TRIGGER AS $$
DECLARE
    v_actor_priority   SMALLINT;
    v_subject_priority SMALLINT;
    v_actor_code       TEXT;
BEGIN
    SELECT p.priority INTO v_actor_priority
    FROM employees e JOIN positions p ON p.id = e.position_id WHERE e.id = NEW.granted_by;

    SELECT p.priority INTO v_subject_priority
    FROM employees e JOIN positions p ON p.id = e.position_id WHERE e.id = NEW.user_id;

    IF v_actor_priority IS NULL OR v_subject_priority IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT p.code INTO v_actor_code
    FROM employees e JOIN positions p ON p.id = e.position_id WHERE e.id = NEW.granted_by;

    -- QƏRAR SEC-006: YALNIZ `Root` bərabər-pillə qaydasından azaddır.
    -- Bölmə 3 "eyni pillədəki istifadəçilərin icazələrinə HEÇ VAXT müdaxilə
    -- edə bilməz" deyir — ona görə CEO ↔ CEO müdaxiləsi bloklanır. Əks halda
    -- bir CEO digərinin səlahiyyətlərini sükutla ala bilərdi.
    -- CEO → Root istiqaməti isə artıq İYERARXİYANIN TƏBİİ NƏTİCƏSİDİR:
    -- Root=0, CEO=1 (miqrasiya 048), yəni `v_subject_priority(0) <=
    -- v_actor_priority(1)` şərti onsuz da işə düşür. Əvvəl ikisi də 0 idi və
    -- qadağa YALNIZ bərabər-pillə şərtindən asılı qalırdı.
    -- Root istisnası zəruridir: əks halda tenant-ın ilk Root-u heç kimə
    -- (o cümlədən digər Root-a) icazə verə bilməzdi və sistem kilidlənərdi.
    IF v_actor_code = 'ROOT' THEN
        RETURN NEW;
    END IF;

    IF v_subject_priority <= v_actor_priority THEN
        RAISE EXCEPTION
            'STRICT HIERARCHY GUARD: yalnız öz iyerarxiya pilləsindən CİDDİ ŞƏKİLDƏ '
            'aşağı istifadəçilərin icazələrinə toxunmaq olar (aktor priority=%, '
            'hədəf priority=%) (bölmə 3)', v_actor_priority, v_subject_priority;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_hierarchy_guard ON user_permission_overrides;
CREATE TRIGGER trg_hierarchy_guard
    BEFORE INSERT OR UPDATE ON user_permission_overrides
    FOR EACH ROW EXECUTE FUNCTION enforce_hierarchy_guard();


-- Etiraz pəncərəsinin avtomatik təyini (system_limits-dən oxuyur)
-- ---------------------------------------------------------------------------
-- SAYĞAC NƏŞRDƏN BAŞLAYIR (miqrasiya 016 ilə eyni qayda)
-- ---------------------------------------------------------------------------
-- Domen mənbəyi `Fine.publish()`-dir: `appeal_window_closes_at :=
-- published_at + appeal_window_hours`. Cərimə həftələrlə icmalda qala bilər;
-- sayğac yaradılışdan başlasaydı, işçi cəriməni GÖRMƏMİŞ etiraz müddəti bitə
-- bilərdi (bax `fine.py` başlığı — "ƏN VACİB DETAL").
--
-- Trigger `UPDATE`-i də əhatə edir, çünki nəşr məhz UPDATE-dir: əks halda
-- ekranı yan keçən SQL ilə nəşr olunan cərimənin pəncərəsi heç vaxt
-- açılmazdı. Dolu sütun TOXUNULMUR — bir dəfə açılmış pəncərə sonradan
-- dəyişən Root limitindən asılı olmamalıdır (domen də onu dondurur).
CREATE OR REPLACE FUNCTION set_fine_appeal_window() RETURNS TRIGGER AS $$
DECLARE
    v_hours INTEGER;
BEGIN
    -- (a) Artıq təyin olunub — DONDURULMUŞ dəyər dəyişdirilmir.
    IF NEW.appeal_window_closes_at IS NOT NULL THEN
        RETURN NEW;
    END IF;

    -- (b) Hələ nəşr olunmayıb — sayğac BAŞLAMIR. Sütun QƏSDƏN NULL qalır:
    --     `Fine.is_appeal_window_open` NULL-u "hələ açıq" kimi oxuyur, yəni
    --     export bloklanır (fail-safe).
    IF NEW.published_at IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT COALESCE(limit_value::INTEGER, 72) INTO v_hours
    FROM system_limits
    WHERE tenant_id = NEW.tenant_id AND limit_key = 'FINE_APPEAL_WINDOW_HOURS';

    NEW.appeal_window_closes_at :=
        NEW.published_at + make_interval(hours => COALESCE(v_hours, 72));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_fine_appeal_window ON fines;
CREATE TRIGGER trg_fine_appeal_window BEFORE INSERT OR UPDATE ON fines
    FOR EACH ROW EXECUTE FUNCTION set_fine_appeal_window();


-- ---------------------------------------------------------------------------
-- 19. GÖRÜNÜŞLƏR (VIEWS)
-- ---------------------------------------------------------------------------

-- İstifadəçinin EFFEKTİV icazələri: rol-defolt + fərdi override (override üstündür)
CREATE OR REPLACE VIEW v_effective_permissions AS
SELECT
    e.id                          AS user_id,
    e.tenant_id,
    pf.code                       AS flag_code,
    pf.category,
    COALESCE(
        CASE upo.effect WHEN 'GRANT' THEN TRUE WHEN 'DENY' THEN FALSE END,
        pp.granted,
        FALSE
    )                             AS is_granted,
    (upo.id IS NOT NULL)          AS is_overridden,
    p.priority                    AS actor_priority
FROM employees e
JOIN positions p ON p.id = e.position_id
CROSS JOIN permission_flags pf
LEFT JOIN position_permissions pp
       ON pp.position_id = e.position_id AND pp.flag_code = pf.code
LEFT JOIN user_permission_overrides upo
       ON upo.user_id = e.id AND upo.flag_code = pf.code
      AND (upo.expires_at IS NULL OR upo.expires_at > now())
WHERE e.is_active;

COMMENT ON VIEW v_effective_permissions IS
    'NavigationRegistry (bölmə 3, "GÖRMƏK = SƏLAHİYYƏTİN OLMASI") bu görünüşü '
    'Feature Toggle statusu ilə BİRLİKDƏ yoxlayır — iki şərt eyni vaxtda.';


-- Kamera Operatorunun BİRLƏŞMİŞ təsdiq növbəsi (Giriş + Qayıdış), mağaza-scoped
CREATE OR REPLACE VIEW v_camera_verification_queue AS
SELECT
    'CHECK_IN'::TEXT   AS request_kind,
    ar.id              AS request_id,
    ar.tenant_id,
    ar.store_id,
    s.name             AS store_name,
    ar.employee_id,
    e.first_name, e.last_name, e.profile_photo_url,
    ar.requested_at    AS waiting_since,
    ar.escalated_at
FROM attendance_records ar
JOIN stores s    ON s.id = ar.store_id
JOIN employees e ON e.id = ar.employee_id
WHERE ar.check_in_status = 'PENDING_VERIFICATION'
UNION ALL
SELECT
    'RETURN'::TEXT     AS request_kind,
    lr.id              AS request_id,
    lr.tenant_id,
    lr.store_id,
    s.name             AS store_name,
    lr.employee_id,
    e.first_name, e.last_name, e.profile_photo_url,
    lr.return_claimed_time AS waiting_since,
    lr.escalated_at
FROM leave_requests lr
JOIN stores s    ON s.id = lr.store_id
JOIN employees e ON e.id = lr.employee_id
WHERE lr.status = 'PENDING_RETURN_VERIFICATION';

COMMENT ON VIEW v_camera_verification_queue IS
    'Operator YALNIZ camera_operator_store_assignment-də təyin edilmiş '
    'mağazaların sətirlərini görməlidir — filtr sorğuda tətbiq olunur '
    '(fail-safe: təyinat yoxdursa nəticə boşdur, bölmə 4).';


-- Export-a hazır cərimələr (LOCK MEXANİZMİ, bölmə 6)
-- LOCK MEXANİZMİ — ÜÇ ŞƏRT (bölmə 6, migration 003 ilə genişləndirilib):
--   (a) PUBLISHED olmalıdır — PENDING_REVIEW HEÇ VAXT export-a düşmür;
--   (b) `published_at` + pəncərə keçmiş olmalıdır (`created_at`-dan DEYİL);
--   (c) artıq export olunmamış olmalıdır.
--
-- PƏNCƏRƏ DONDURULMUŞ SÜTUNDAN OXUNUR (miqrasiya 016). Əvvəl görünüş onu hər
-- sorğuda `published_at + CARİ limit` kimi yenidən hesablayırdı; Root limiti
-- 72 → 24 saata endirsəydi artıq nəşr olunmuş cərimələrin pəncərəsi
-- RETROAKTİV bağlanardı. Domen isə dəyəri `publish()` anında dondurur
-- (`Fine.publish`) və `Fine.is_appeal_window_open` məhz həmin sütunu oxuyur —
-- indi domen, repository və görünüş üçü də eyni şərti tətbiq edir.
-- DÖRDÜNCÜ ŞƏRT (M-6, miqrasiya 052): qərarı VERİLMƏMİŞ etirazı olan cərimə
-- hesabata düşmür. Əvvəl pəncərənin bağlanması export kilidini AÇIRDI — yəni
-- işçi 71-ci saatda etiraz göndərsə və HR baxmasa, 72-ci saatda pul kəsilir,
-- etiraza isə heç vaxt qərar verilmirdi. HR-ın baxmaması işçinin günahı deyil.
-- `PENDING` ("hələ baxılmayıb") və `EXPIRED` ("72 saat keçdi, YENƏ baxılmayıb")
-- birlikdə süzülür: hər ikisi qərarsızdır (bax `Fine.is_exportable`).
CREATE OR REPLACE VIEW v_exportable_fines AS
SELECT f.*
FROM fines f
-- `REDUCED` DAXİLDİR: qismən qəbul olunmuş etirazdan sonra işçi
-- azaldılmış məbləği yenə ödəyir (bax `Fine.is_exportable`).
WHERE f.status IN ('PUBLISHED', 'REDUCED')
  AND f.published_at IS NOT NULL
  AND f.appeal_window_closes_at IS NOT NULL
  AND f.appeal_window_closes_at <= now()
  AND f.exported_period IS NULL
  AND NOT EXISTS (
      SELECT 1
        FROM fine_appeals fa
       WHERE fa.fine_id = f.id
         AND fa.status IN ('PENDING', 'EXPIRED')
  );


-- ---------------------------------------------------------------------------
-- 20. CRON FUNKSİYALARI (pg_cron və ya xarici scheduler ilə çağırılır)
-- ---------------------------------------------------------------------------

-- (a) 45-dəqiqəlik təsdiq timeout-larının eskalasiyası (bölmə 4)
CREATE OR REPLACE FUNCTION cron_escalate_verification_timeouts() RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER := 0;
BEGIN
    WITH limits AS (
        SELECT tenant_id,
               COALESCE(MAX(limit_value::INTEGER), 45) AS timeout_minutes
        FROM system_limits
        WHERE limit_key = 'VERIFICATION_TIMEOUT_MINUTES'
        GROUP BY tenant_id
    ),
    escalated_leaves AS (
        UPDATE leave_requests lr
        SET status = 'TIMEOUT_ESCALATED', escalated_at = now()
        FROM limits l
        WHERE lr.tenant_id = l.tenant_id
          AND lr.status = 'PENDING_RETURN_VERIFICATION'
          AND lr.escalated_at IS NULL
          AND lr.return_claimed_time < now() - make_interval(mins => l.timeout_minutes)
        RETURNING 1
    ),
    escalated_checkins AS (
        UPDATE attendance_records ar
        SET escalated_at = now()
        FROM limits l
        WHERE ar.tenant_id = l.tenant_id
          AND ar.check_in_status = 'PENDING_VERIFICATION'
          AND ar.escalated_at IS NULL
          AND ar.requested_at < now() - make_interval(mins => l.timeout_minutes)
        RETURNING 1
    )
    SELECT (SELECT count(*) FROM escalated_leaves)
         + (SELECT count(*) FROM escalated_checkins) INTO v_count;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- (b) "İCAZƏSİZ QAYIB" təyinetməsi — gün sonunda (bölmə 4)
CREATE OR REPLACE FUNCTION cron_detect_unauthorized_absences(p_date DATE DEFAULT CURRENT_DATE - 1)
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    WITH expected AS (
        SELECT sa.employee_id, sa.tenant_id, e.store_id
        FROM shift_assignments sa
        JOIN employees e ON e.id = sa.employee_id
        WHERE sa.shift_date = p_date
          AND NOT sa.is_off_day
          AND e.is_active
    ),
    missing AS (
        SELECT ex.*
        FROM expected ex
        LEFT JOIN attendance_records ar
               ON ar.employee_id = ex.employee_id
              AND ar.work_date = p_date
              AND ar.check_in_status = 'VERIFIED'
        WHERE ar.id IS NULL
    ),
    inserted AS (
        INSERT INTO attendance_records
            (tenant_id, employee_id, store_id, work_date,
             check_in_status, is_unauthorized_absence)
        SELECT m.tenant_id, m.employee_id, m.store_id, p_date, 'NOT_STARTED', TRUE
        FROM missing m
        WHERE m.store_id IS NOT NULL
        ON CONFLICT (employee_id, work_date)
        DO UPDATE SET is_unauthorized_absence = TRUE
        RETURNING 1
    )
    SELECT count(*) INTO v_count FROM inserted;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- (c) Tapşırıq son-tarix eskalasiyası (bölmə 6)
CREATE OR REPLACE FUNCTION cron_escalate_task_deadlines() RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    WITH overdue AS (
        UPDATE tasks
        SET status = 'OVERDUE', escalated_at = now()
        WHERE status IN ('OPEN', 'EVIDENCE_SUBMITTED')
          AND deadline < now()
          AND escalated_at IS NULL
        RETURNING 1
    )
    SELECT count(*) INTO v_count FROM overdue;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- (d) Cavabsız qalmış etirazın SLA-pozuntusu kimi işarələnməsi (72 saat)
--
-- ŞƏRH DÜZƏLİŞİ (M-6): əvvəl burada "export kilidini açır" yazılırdı və
-- davranış da belə idi. `EXPIRED` artıq kilidi AÇMIR — `v_exportable_fines`
-- qərarsız etirazı olan cəriməni buraxmır və `FineAppeal` həmin vəziyyətdən
-- də qərar qəbul edir. Status yalnız "HR cavab vermədi" halını "işçi etiraz
-- etmədi" halından ayıran izdir.
CREATE OR REPLACE FUNCTION cron_close_expired_appeals() RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    WITH expired AS (
        UPDATE fine_appeals
        SET status = 'EXPIRED'
        WHERE status = 'PENDING'
          AND fine_id IN (SELECT id FROM fines WHERE appeal_window_closes_at <= now())
        RETURNING 1
    )
    SELECT count(*) INTO v_count FROM expired;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- (e) 6 aylıq xal sıfırlanması — 1 Yanvar və 1 İyul (bölmə 6)
CREATE OR REPLACE FUNCTION cron_reset_sales_points() RETURNS INTEGER AS $$
DECLARE
    v_period_start DATE;
    v_count INTEGER;
BEGIN
    IF NOT ((EXTRACT(MONTH FROM CURRENT_DATE) = 1 OR EXTRACT(MONTH FROM CURRENT_DATE) = 7)
            AND EXTRACT(DAY FROM CURRENT_DATE) = 1) THEN
        RETURN 0;
    END IF;

    v_period_start := CURRENT_DATE;

    WITH reset_rows AS (
        UPDATE points_ledger
        SET status = 'REVERSED', corrected_at = now()
        WHERE status = 'ACTIVE' AND period_start < v_period_start
        RETURNING 1
    )
    SELECT count(*) INTO v_count FROM reset_rows;

    INSERT INTO audit_logs (action, entity_type, reason, after_state)
    VALUES ('SALES_POINTS_SEMIANNUAL_RESET', 'points_ledger',
            '6 aylıq hard-reset (bölmə 6)',
            jsonb_build_object('period_start', v_period_start, 'reset_rows', v_count));

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- (f) Xal sıfırlanmasından 14 gün əvvəl bildiriş (bölmə 6)
CREATE OR REPLACE FUNCTION cron_notify_points_reset_upcoming() RETURNS INTEGER AS $$
DECLARE
    v_next_reset DATE;
    v_count INTEGER;
BEGIN
    v_next_reset := CASE
        WHEN CURRENT_DATE < make_date(EXTRACT(YEAR FROM CURRENT_DATE)::INT, 7, 1)
            THEN make_date(EXTRACT(YEAR FROM CURRENT_DATE)::INT, 7, 1)
        ELSE make_date(EXTRACT(YEAR FROM CURRENT_DATE)::INT + 1, 1, 1)
    END;

    IF v_next_reset - CURRENT_DATE <> 14 THEN
        RETURN 0;
    END IF;

    WITH notified AS (
        INSERT INTO notifications (tenant_id, recipient_id, category, title_az, body_az)
        SELECT DISTINCT pl.tenant_id, pl.employee_id, 'POINTS_RESET_UPCOMING',
               'Xal balansınız 14 gün sonra sıfırlanacaq',
               'İstifadə olunmamış satış xallarınız ' || v_next_reset ||
               ' tarixində sıfırlanacaq. Mükafat mübadiləsi üçün son fürsət.'
        FROM points_ledger pl
        WHERE pl.status = 'ACTIVE'
        RETURNING 1
    )
    SELECT count(*) INTO v_count FROM notified;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- (g) Lisenziya ödəniş statusunun gündəlik yenilənməsi (bölmə 8)
CREATE OR REPLACE FUNCTION cron_update_license_payment_status() RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    WITH overdue AS (
        UPDATE license_tenants
        SET status = 'ODENIS_GOZLENILIR'
        WHERE status = 'AKTIV'
          AND next_payment_date IS NOT NULL
          AND next_payment_date < CURRENT_DATE
        RETURNING 1
    )
    SELECT count(*) INTO v_count FROM overdue;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- (h) Köhnə backup qeydlərinin təmizlənməsi (30 günlük saxlama, bölmə 7)
CREATE OR REPLACE FUNCTION cron_prune_expired_backups() RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    WITH pruned AS (
        DELETE FROM backup_records
        WHERE retention_until < CURRENT_DATE AND restored_at IS NULL
        RETURNING 1
    )
    SELECT count(*) INTO v_count FROM pruned;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- pg_cron qeydiyyatı (extension mövcud olduqda)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
      BEGIN
        PERFORM cron.schedule('kompasos-timeouts',    '*/5 * * * *',  'SELECT kompasos.cron_escalate_verification_timeouts()');
        PERFORM cron.schedule('kompasos-absences',    '30 0 * * *',   'SELECT kompasos.cron_detect_unauthorized_absences()');
        PERFORM cron.schedule('kompasos-tasks',       '*/15 * * * *', 'SELECT kompasos.cron_escalate_task_deadlines()');
        PERFORM cron.schedule('kompasos-appeals',     '0 * * * *',    'SELECT kompasos.cron_close_expired_appeals()');
        PERFORM cron.schedule('kompasos-points',      '5 0 * * *',    'SELECT kompasos.cron_reset_sales_points()');
        PERFORM cron.schedule('kompasos-points-warn', '10 0 * * *',   'SELECT kompasos.cron_notify_points_reset_upcoming()');
        PERFORM cron.schedule('kompasos-license',     '15 0 * * *',   'SELECT kompasos.cron_update_license_payment_status()');
        PERFORM cron.schedule('kompasos-backups',     '20 3 * * *',   'SELECT kompasos.cron_prune_expired_backups()');
        PERFORM cron.schedule('kompasos-sessions',    '25 3 * * *',   'SELECT kompasos.cron_prune_expired_sessions()');
      EXCEPTION WHEN OTHERS THEN
        -- İdarə olunan platformalarda (Supabase) `cron` sxemasına icazə
        -- olmaya bilər — bu, sxem quraşdırmasını DAYANDIRMAMALIDIR.
        RAISE WARNING
            'pg_cron mövcuddur, lakin cədvəl qeydiyyatı alınmadı (%). Xarici '
            'scheduler istifadə edin — bax docs/scheduler_setup.md', SQLERRM;
      END;
    ELSE
        -- Sükutla keçmir: §29-dakı blok bunu `scheduled_job_runs`-a da yazır.
        RAISE WARNING 'pg_cron tapılmadı — cron funksiyaları xarici scheduler ilə çağırılmalıdır (bax §29).';
    END IF;
END
$$;


-- ---------------------------------------------------------------------------
-- 21. SEED: 7 DEFOLT ROL (bölmə 3)
-- ---------------------------------------------------------------------------
-- PRİORİTET MODELİ (bölmə 3, KONSEPTUAL DÜZƏLİŞ — miqrasiya 048):
--   Root=0 (TƏK BAŞINA), CEO=1, Admin=2, operativ rollar=3, Satıcı=4.
-- Əvvəl `ROOT` və `CEO` hər ikisi 0 idi; o model `CEO`-nu `Root` ilə BƏRABƏR
-- pilləyə qoyurdu və "CEO Root-un icazələrinə toxuna bilmir" qaydası yalnız
-- hardlock-un yan təsiri kimi işləyirdi. Mövcud quraşdırmalar üçün eyni
-- sürüşdürməni `migrations/048_root_ceo_priority_split.sql` aparır — bu
-- fayl ilə həmin miqrasiya EYNİ son vəziyyəti verməlidir.
INSERT INTO positions (tenant_id, code, name_az, priority, is_system, is_camera_type, description)
VALUES
    (NULL, 'ROOT',               'Root',                0, TRUE,  FALSE, 'Sistem sahibi — TƏK BAŞINA ən üst pillə; Permission Registry və sistem limitləri yalnız bu roldadır'),
    (NULL, 'CEO',                'CEO',                 1, TRUE,  FALSE, 'Şirkət rəhbəri — Root-dan DƏRHAL aşağı; rol yaratma və biznes konfiqurasiyası'),
    (NULL, 'ADMIN',              'Admin',               2, TRUE,  FALSE, 'CEO-dan bir pillə aşağı — gündəlik icazə idarəetməsi (həvalə edilmiş)'),
    (NULL, 'HR_ADMIN',           'HR_Admin',            3, TRUE,  FALSE, 'İşçi/növbə/cərimə/etiraz idarəetməsi'),
    (NULL, 'MAGAZA_MENECERI',    'Mağaza Meneceri',     3, TRUE,  FALSE, 'Gündəlik Tabel + öz filialının tapşırıqları (növbə PLANLAMASI YOX)'),
    (NULL, 'KAMERA_NEZARETCISI', 'Kamera Nəzarətçisi',  3, TRUE,  TRUE,  'iVMS-də görüntünü yoxlayıb təsdiq/vaxt düzəlişi/cərimə verir'),
    (NULL, 'SATICI',             'Satıcı',              4, TRUE,  FALSE, 'İşçi — Kiosk PIN handshake və İşçi Ana Ekranı')
ON CONFLICT DO NOTHING;


-- ---------------------------------------------------------------------------
-- 22. SEED: İCAZƏ FLAG KATALOQU (bölmə 3, tam siyahı)
-- ---------------------------------------------------------------------------
INSERT INTO permission_flags
    (code, category, name_az, description_az, hardlock_level, is_anti_fraud, is_camera_only)
VALUES
    -- HR & İşçi İdarəetməsi
    ('can_manage_employees',        'HR', 'İşçiləri idarə et',                 'İşçi yaratmaq/redaktə/deaktiv etmək', 0, FALSE, FALSE),
    ('can_reset_pin',               'HR', 'PIN sıfırla',                       'İşçinin 4-rəqəmli PIN-ini sıfırlamaq', 0, FALSE, FALSE),
    ('can_reset_password',          'HR', 'Şifrə yenilə',                      'Admin-tier istifadəçiyə müvəqqəti şifrə təyin etmək', 0, FALSE, FALSE),
    ('can_manage_shifts',           'HR', 'Növbələri planla',                  'Interactive Shift Matrix redaktəsi', 0, FALSE, FALSE),
    ('can_approve_shift_swap',      'HR', 'Növbə dəyişməni təsdiqlə',          'Shift Swap sorğusunu təsdiq/rədd etmək', 0, FALSE, FALSE),
    ('can_approve_leave_appeal',    'HR', 'İcazə etirazını təsdiqlə',          'Cərimə/icazə etirazına qərar vermək', 0, FALSE, FALSE),
    ('can_view_employee_reports',   'HR', 'İşçi hesabatlarına bax',            'Fərdi performans/cərimə tarixçəsinə yalnız-baxış', 0, FALSE, FALSE),
    ('can_manage_leave_types',      'HR', 'İcazə növlərini idarə et',          'İcazə Növləri kataloqu', 0, FALSE, FALSE),

    -- Kamera & Cərimə — ANTI-FRAUD (heç vaxt Mağaza_Meneceri/Satıcı-ya).
    -- İlk üçü ƏLAVƏ OLARAQ yalnız kamera-tipli rollarda ola bilər (is_camera_only).
    ('can_verify_returns',                  'KAMERA_CERIME', 'Qayıdışları təsdiqlə',        'STEP 3 və Morning Check-in təsdiqi', 0, TRUE, TRUE),
    ('can_override_return_time',            'KAMERA_CERIME', 'Vaxtı əllə təyin et',         'Manual vaxt düzəlişi', 0, TRUE, TRUE),
    ('can_issue_fines',                     'KAMERA_CERIME', 'Cərimə ver',                  'Manual cərimə qeydiyyatı', 0, TRUE, TRUE),
    -- Bu isə TƏSDİQ tərəfidir: HR_Admin/CEO daşıyır, kamera-tipli rol daşıya BİLMƏZ.
    ('can_approve_dual_control_override',   'KAMERA_CERIME', 'Cüt nəzarət təsdiqi',         '30+ dəqiqəlik vaxt düzəlişinə ikinci təsdiq (HR_Admin/CEO)', 0, TRUE, FALSE),
    ('can_manage_fine_types',               'KAMERA_CERIME', 'Cərimə növlərini idarə et',   'Cərimə Növləri kataloqu (ad + standart qiymət)', 0, FALSE, FALSE),

    -- Satış & Mükafat
    ('can_manage_sales_points',     'SATIS_MUKAFAT', 'Xalları idarə et', 'Xal korreksiyası, mükafat mübadiləsi təsdiqi', 0, FALSE, FALSE),

    -- Task & Dashboard
    ('can_assign_tasks',            'TASK_DASHBOARD', 'Tapşırıq təyin et',          'Tapşırıq yaratmaq/təyin etmək', 0, FALSE, FALSE),
    ('can_approve_task_evidence',   'TASK_DASHBOARD', 'Tapşırıq sübutunu təsdiqlə', 'Yüklənmiş sübutu təsdiq/rədd etmək', 0, FALSE, FALSE),
    ('can_view_dashboard_builder',  'TASK_DASHBOARD', 'Panel Qurucusuna bax',       'Panel Qurucusu ekranı', 0, FALSE, FALSE),
    ('can_edit_dashboard_widgets',  'TASK_DASHBOARD', 'Widget-ləri redaktə et',     'İdarə Paneli widget konfiqurasiyası', 0, FALSE, FALSE),

    ('can_publish_fines',           'KAMERA_CERIME', 'Cərimələri filiallara göndər',
        'Aylıq Cərimə İcmalından təsdiqlənmiş cərimələri işçilərə açır', 0, TRUE, FALSE),

    -- ERP & İnfrastruktur
    ('can_manage_erp_connections',  'ERP_INFRA', 'ERP bağlantılarını idarə et', 'Bağlantı Sihirbazı', 0, FALSE, FALSE),
    ('can_manage_drive_connection', 'ERP_INFRA', 'Drive bağlantısını idarə et',
        'Cərimə sübut şəkilləri üçün Google Drive hesabı', 0, FALSE, FALSE),
    ('can_manage_erp_servers',      'ERP_INFRA', 'ERP serverlərini idarə et',   'Çoxsaylı 1C server siyahısı', 0, FALSE, FALSE),
    ('can_switch_db',               'ERP_INFRA', 'Baza keçidi (DB switcher)',   'Cloud ↔ Private Server keçidi', 1, FALSE, FALSE),
    ('can_manage_plugins',          'ERP_INFRA', 'Plugin-ləri idarə et',        'İmzalanmış plugin təsdiqi/yüklənməsi', 1, FALSE, FALSE),
    ('can_view_system_health',      'ERP_INFRA', 'Sistem sağlamlığına bax',     'Yalnız monitorinq, konfiqurasiyasız', 0, FALSE, FALSE),

    -- Lisenziya, Ehtiyat Nüsxə & Sistem
    ('can_manage_license',          'SISTEM', 'Lisenziya vəziyyətinə bax', 'Lokal lisenziya vəziyyəti + aktivasiya açarı (aktiv/deaktiv etmə YOX)', 1, FALSE, FALSE),
    ('can_view_audit_logs',         'SISTEM', 'Audit log-lara bax',        'Audit Log Viewer', 0, FALSE, FALSE),
    ('can_export_reports',          'SISTEM', 'Hesabatları export et',     'Attendance + Bonus&Penalty Excel export', 0, FALSE, FALSE),
    ('can_manage_backups',          'SISTEM', 'Ehtiyat nüsxə/bərpa',       'Nöqtə-zamanlı bərpa funksiyası', 0, FALSE, FALSE),

    -- İcazə İdarəetməsi (HƏSSAS)
    ('can_manage_permissions',      'ICAZE', 'Yeni icazə flag-i yarat',     'System Permission Registry — YALNIZ Root', 1, FALSE, FALSE),
    ('can_manage_positions',        'ICAZE', 'Rol/vəzifə yarat',            'Mövcud flag-lərdən yeni rol tərtib etmək — Root VƏ CEO', 2, FALSE, FALSE),
    ('can_control_user_permissions','ICAZE', 'İstifadəçi icazələrini idarə et', 'Fərdi grant/deny — Hierarchy + Self-Escalation Guard-a tabe', 3, FALSE, FALSE),
    ('can_manage_system_limits',    'ICAZE', 'Sistem limitləri & Feature Toggle', 'ROOT İdarə Mərkəzi — YALNIZ Root', 1, FALSE, FALSE),

    -- Növbə & İş Rejimi
    ('can_manage_work_modes',       'NOVBE', 'İş rejimlərini idarə et',  'İş Rejimləri kataloqu', 0, FALSE, FALSE),
    ('can_fill_daily_attendance',   'NOVBE', 'Gündəlik tabeli doldur',   'Gündəlik Mağaza Tabeli — öz mağazası', 0, FALSE, FALSE),

    -- Dəstək
    ('can_contact_support',         'DESTEK', 'Texniki dəstəklə əlaqə', 'Diskret in-app dəstək chat-i', 0, FALSE, FALSE)
ON CONFLICT (code) DO UPDATE
    SET category       = EXCLUDED.category,
        name_az        = EXCLUDED.name_az,
        description_az = EXCLUDED.description_az,
        hardlock_level = EXCLUDED.hardlock_level,
        is_anti_fraud  = EXCLUDED.is_anti_fraud,
        is_camera_only = EXCLUDED.is_camera_only;


-- ---------------------------------------------------------------------------
-- 23. SEED: ROL → FLAG DEFOLT TƏYİNATI (bölmə 3)
-- ---------------------------------------------------------------------------
UPDATE permission_flags SET excludes_camera_role = TRUE WHERE code = 'can_publish_fines';

-- Root: bütün flag-lər, MİNUS kamera-əməliyyat flag-ləri.
-- (Root konfiqurasiya edir, gündəlik kamera əməliyyatı aparmır — vəzifə ayrılığı.)
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, pf.code, TRUE
FROM positions p CROSS JOIN permission_flags pf
WHERE p.code = 'ROOT' AND p.tenant_id IS NULL
  AND NOT pf.is_camera_only
ON CONFLICT DO NOTHING;

-- CEO: Root-un hər şeyi, MİNUS səviyyə-1 hardlock (can_manage_permissions,
-- can_manage_system_limits, can_switch_db, can_manage_plugins, can_manage_license)
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, pf.code, TRUE
FROM positions p CROSS JOIN permission_flags pf
WHERE p.code = 'CEO' AND p.tenant_id IS NULL
  AND pf.hardlock_level <> 1
  AND NOT pf.is_camera_only
ON CONFLICT DO NOTHING;

-- Admin: operativ idarəetmə + həvalə edilmiş icazə kontrolu
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, f.flag_code, TRUE
FROM positions p
CROSS JOIN unnest(ARRAY[
        'can_manage_employees', 'can_reset_pin', 'can_reset_password',
        'can_manage_shifts', 'can_approve_shift_swap', 'can_approve_leave_appeal',
        'can_view_employee_reports', 'can_assign_tasks', 'can_approve_task_evidence',
        'can_view_dashboard_builder', 'can_edit_dashboard_widgets',
        'can_view_system_health', 'can_view_audit_logs', 'can_export_reports',
        'can_control_user_permissions', 'can_contact_support', 'can_publish_fines'
     ]) AS f(flag_code)
WHERE p.code = 'ADMIN' AND p.tenant_id IS NULL
ON CONFLICT DO NOTHING;

-- HR_Admin (dual-control TƏSDİQİ burada — kamera rolunda DEYİL)
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, f.flag_code, TRUE
FROM positions p
CROSS JOIN unnest(ARRAY[
        'can_manage_employees', 'can_reset_pin', 'can_manage_shifts',
        'can_approve_shift_swap', 'can_approve_leave_appeal',
        'can_view_employee_reports', 'can_manage_leave_types',
        'can_approve_dual_control_override',
        'can_assign_tasks', 'can_approve_task_evidence',
        'can_export_reports', 'can_view_audit_logs', 'can_contact_support',
        'can_publish_fines'
     ]) AS f(flag_code)
WHERE p.code = 'HR_ADMIN' AND p.tenant_id IS NULL
ON CONFLICT DO NOTHING;

-- Mağaza Meneceri: Gündəlik Tabel + tapşırıq idarəetməsi (növbə PLANLAMASI YOX)
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, f.flag_code, TRUE
FROM positions p
CROSS JOIN unnest(ARRAY[
        'can_fill_daily_attendance', 'can_assign_tasks',
        'can_approve_task_evidence', 'can_view_employee_reports'
     ]) AS f(flag_code)
WHERE p.code = 'MAGAZA_MENECERI' AND p.tenant_id IS NULL
ON CONFLICT DO NOTHING;

-- Kamera Nəzarətçisi: YALNIZ kamera-əməliyyat flag-ləri (təsdiq flag-i YOX)
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, f.flag_code, TRUE
FROM positions p
CROSS JOIN unnest(ARRAY[
        'can_verify_returns', 'can_override_return_time', 'can_issue_fines'
     ]) AS f(flag_code)
WHERE p.code = 'KAMERA_NEZARETCISI' AND p.tenant_id IS NULL
ON CONFLICT DO NOTHING;

-- Satıcı: heç bir idarəetmə flag-i yoxdur (yalnız öz İşçi Ana Ekranı)


-- ---------------------------------------------------------------------------
-- 24. SEED FUNKSİYASI: YENİ TENANT ÜÇÜN DEFOLT KONFİQURASİYA
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION seed_tenant_defaults(p_tenant_id UUID) RETURNS VOID AS $$
BEGIN
    -- Sistem rollarının tenant-a kopyalanması
    INSERT INTO positions (tenant_id, code, name_az, priority, is_system, is_camera_type, description)
    SELECT p_tenant_id, code, name_az, priority, is_system, is_camera_type, description
    FROM positions WHERE tenant_id IS NULL
    ON CONFLICT (tenant_id, code) DO NOTHING;

    -- Rol → flag təyinatının kopyalanması
    INSERT INTO position_permissions (position_id, flag_code, granted)
    SELECT tp.id, pp.flag_code, pp.granted
    FROM position_permissions pp
    JOIN positions sp ON sp.id = pp.position_id AND sp.tenant_id IS NULL
    JOIN positions tp ON tp.code = sp.code AND tp.tenant_id = p_tenant_id
    ON CONFLICT DO NOTHING;

    -- DİNAMİK LİMİTLƏR (bölmə 3, ROOT CONTROL CENTER)
    INSERT INTO system_limits (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (p_tenant_id, 'MONTHLY_LEAVE_MINUTES_LIMIT', '240', 'INTEGER', '0',  '1440', 'Aylıq İcazə Müddəti Limiti (dəqiqə)'),
        (p_tenant_id, 'FINE_APPEAL_WINDOW_HOURS',    '72',  'INTEGER', '24', '336',  'Cərimə Etiraz Pəncərəsi (saat)'),
        (p_tenant_id, 'LATE_TOLERANCE_MINUTES',      '15',  'INTEGER', '0',  '120',  'Gecikmə Tolerantlığı (dəqiqə)'),
        (p_tenant_id, 'VERIFICATION_TIMEOUT_MINUTES','45',  'INTEGER', '5',  '240',  'STEP2 / Morning Check-in timeout (dəqiqə)'),
        (p_tenant_id, 'DUAL_CONTROL_THRESHOLD_MINUTES','30','INTEGER', '5',  '240',  'Cüt nəzarət həddi (dəqiqə)'),
        (p_tenant_id, 'PIN_MAX_FAILED_ATTEMPTS',     '5',   'INTEGER', '3',  '10',   'PIN lockout həddi'),
        (p_tenant_id, 'PIN_LOCKOUT_MINUTES',         '15',  'INTEGER', '5',  '60',   'PIN lockout müddəti (dəqiqə)'),
        (p_tenant_id, 'NTP_MAX_DRIFT_SECONDS',       '60',  'INTEGER', '10', '300',  'TIME_DRIFT_DETECTED həddi (saniyə)'),
        (p_tenant_id, 'MAX_UPLOAD_SIZE_BYTES',       '5242880', 'INTEGER', '1048576', '20971520', 'Maksimum şəkil ölçüsü (bayt)')
    ON CONFLICT DO NOTHING;

    -- FEATURE TOGGLE-LAR (bölmə 3)
    INSERT INTO feature_toggles (tenant_id, module_key, is_enabled, is_structural, description_az)
    VALUES
        (p_tenant_id, 'CAMERA_VERIFICATION', TRUE, TRUE,  'Kamera Təsdiqi — STEP1-3 və Morning Check-in-in struktur əsası'),
        (p_tenant_id, 'DUAL_CONTROL',        TRUE, FALSE, 'Cüt-nəzarətli əlavə təsdiq qatı'),
        (p_tenant_id, 'SHIFT_SWAP',          TRUE, FALSE, 'Növbə Dəyişmə Sorğusu (işçi self-service)'),
        (p_tenant_id, 'FINE_MODULE',         TRUE, FALSE, 'Cərimə Modulu (manual + avtomatik)'),
        (p_tenant_id, 'TASK_ENGINE',         TRUE, FALSE, 'Task & Workflow Engine'),
        (p_tenant_id, 'SALES_POINTS',        TRUE, FALSE, 'Gamified satış xalları və mükafat'),
        (p_tenant_id, 'DASHBOARD_BUILDER',   TRUE, FALSE, 'Panel qurucusu'),
        (p_tenant_id, 'SUPPORT_CHAT',        TRUE, FALSE, 'Diskret texniki dəstək chat-i')
    ON CONFLICT DO NOTHING;

    -- Defolt İcazə Növləri
    INSERT INTO leave_types (tenant_id, name_az, default_duration_minutes)
    VALUES
        (p_tenant_id, 'Nahar Fasiləsi',   60),
        (p_tenant_id, 'Siqaret Fasiləsi', 10),
        (p_tenant_id, 'Şəxsi İş',         30)
    ON CONFLICT DO NOTHING;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_tenant_defaults IS
    'İlk Quraşdırma Sihirbazı (bölmə 7) yeni tenant yaradarkən bu funksiyanı çağırır.';


-- ---------------------------------------------------------------------------
-- 25. DEV SEED TENANT — YALNIZ `-v kompasos_env=DEV` İLƏ
-- ---------------------------------------------------------------------------
-- Səbəb (PHASE 1, addım 4): LICENSE_INACTIVE bloku erkən fazalarda testləri
-- dayandırmasın deyə lokal development üçün "Aktiv" statuslu tenant lazımdır.
DO $$
DECLARE
    v_env    TEXT := COALESCE(current_setting('kompasos.env', TRUE), 'PRODUCTION');
    v_tenant UUID;
BEGIN
    IF upper(v_env) <> 'DEV' THEN
        RAISE NOTICE 'Mühit "%": DEV seed tenant YARADILMADI.', v_env;
        RETURN;
    END IF;

    SELECT tenant_id INTO v_tenant FROM license_tenants WHERE tenant_name = 'DEV — Lokal Test';

    IF v_tenant IS NULL THEN
        INSERT INTO license_tenants (
            tenant_name, license_key_hash, status,
            last_payment_date, next_payment_date, company_contact_email
        ) VALUES (
            'DEV — Lokal Test',
            'DEV_ONLY_NOT_A_REAL_HASH',
            'AKTIV',
            CURRENT_DATE,
            CURRENT_DATE + INTERVAL '365 days',
            'dev@kompasos.local'
        )
        RETURNING tenant_id INTO v_tenant;
    ELSE
        UPDATE license_tenants
        SET status = 'AKTIV', next_payment_date = CURRENT_DATE + INTERVAL '365 days'
        WHERE tenant_id = v_tenant;
    END IF;

    PERFORM seed_tenant_defaults(v_tenant);

    INSERT INTO stores (tenant_id, code, name, brand)
    VALUES (v_tenant, 'DEV-001', 'Yataş Babək (DEV)', 'Yataş')
    ON CONFLICT DO NOTHING;

    INSERT INTO work_modes (tenant_id, name, start_time, end_time)
    VALUES
        (v_tenant, '08:00–17:00', '08:00', '17:00'),
        (v_tenant, '14:00–23:00', '14:00', '23:00')
    ON CONFLICT DO NOTHING;

    INSERT INTO fine_types (tenant_id, name_az, standard_amount)
    VALUES
        (v_tenant, 'Formaya uyğun geyinməmək',        10.00),
        (v_tenant, 'Kassa qaydalarına əməl etməmək',  25.00)
    ON CONFLICT DO NOTHING;

    RAISE NOTICE 'DEV seed tenant hazırdır: %', v_tenant;
END
$$;


-- ---------------------------------------------------------------------------
-- 26. AUDIT LOG DƏYİŞMƏZLİYİ (SEC-007) — APPEND-ONLY, KOD SƏVİYYƏSİNDƏ
-- ---------------------------------------------------------------------------
-- Bölmə 4: "orijinal qeyd heç vaxt silinmir". GRANT/REVOKE kifayət deyil,
-- çünki cədvəl sahibi (owner) və superuser onları yan keçir. Trigger isə
-- HƏR KƏSƏ tətbiq olunur — yeganə real zəmanət budur.
CREATE OR REPLACE FUNCTION enforce_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'APPEND-ONLY POZUNTUSU: "%" cədvəlində % əməliyyatı qadağandır — '
        'audit izi dəyişdirilə və ya silinə bilməz (bölmə 4)',
        TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_logs_append_only ON audit_logs;
CREATE TRIGGER trg_audit_logs_append_only
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION enforce_append_only();

DROP TRIGGER IF EXISTS trg_security_events_append_only ON security_events;
CREATE TRIGGER trg_security_events_append_only
    BEFORE UPDATE ON security_events
    FOR EACH ROW EXECUTE FUNCTION enforce_append_only();

COMMENT ON FUNCTION enforce_append_only() IS
    'audit_logs: UPDATE və DELETE tam qadağandır. security_events: yalnız '
    'UPDATE qadağandır (tenant silinərkən CASCADE DELETE işləməlidir).';

-- Arxivləmə: audit log-u saxlama müddətindən sonra SİLMƏK əvəzinə soyuq
-- anbara köçürmək üçün ayrıca, açıq şəkildə çağırılan prosedur lazımdır.
-- Faza 6-da implementasiya olunur; trigger-i müvəqqəti söndürmək YERİNƏ
-- `ALTER TABLE ... DISABLE TRIGGER` yalnız superuser tərəfindən, sənədləşmiş
-- maintenance window daxilində edilə bilər.


-- ---------------------------------------------------------------------------
-- 27. ROW LEVEL SECURITY — ÇOX-TENANT İZOLYASİYASI (FAIL-CLOSED)
-- ---------------------------------------------------------------------------
-- QƏRAR SEC-008: siyasət FAIL-CLOSED-dur — `app.tenant_id` təyin edilməyibsə
-- tətbiq rolu HEÇ BİR sətir görmür. Əvvəlki "NULL olduqda hər şeyi buraxan"
-- variant təsadüfi kontekst itkisini sükutla çox-tenant sızmasına çevirirdi.
--
-- Sxem miqrasiyası və `database/tests/*.sql` cədvəl sahibi (owner) altında
-- işlədiyi üçün RLS-dən azaddır. Tətbiq isə aşağıdakı `kompasos_app` rolu ilə
-- qoşulur və RLS-ə TAM tabedir.
--
-- Faza 3 müqaviləsi (repository qatı): hər tranzaksiyanın əvvəlində
--     SET LOCAL app.tenant_id = '<uuid>';
--     SET LOCAL app.user_id   = '<uuid>';
-- `SET LOCAL` seçilib ki, connection pool-da dəyər növbəti istifadəçiyə
-- sızmasın (adi `SET` sessiya boyu qalır — pool ilə TƏHLÜKƏLİDİR).

CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS UUID AS $$
DECLARE
    v_raw TEXT := current_setting('app.tenant_id', TRUE);
BEGIN
    IF v_raw IS NULL OR v_raw = '' THEN
        RETURN NULL;
    END IF;
    RETURN v_raw::UUID;
EXCEPTION WHEN invalid_text_representation THEN
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

DO $$
DECLARE
    t TEXT;
    tenant_scoped TEXT[] := ARRAY[
        'employees', 'stores', 'positions', 'leave_requests', 'leave_types',
        'fines', 'fine_types', 'fine_appeals', 'attendance_records',
        'daily_attendance_sheets', 'shift_assignments', 'shift_swap_requests',
        'work_modes', 'manual_time_overrides', 'tasks', 'erp_servers',
        'sales_transactions', 'points_ledger', 'points_appeals',
        'rewards', 'reward_redemptions', 'system_limits', 'feature_toggles',
        'notifications', 'support_tickets', 'plugins', 'backup_records',
        'sync_conflicts', 'saga_instances', 'db_migration_events',
        'security_events', 'audit_logs', 'auth_sessions',
        -- `drive_connections` / `drive_folder_cache` BURADA YOXDUR: onlar
        -- yalnız `migrations/002`-də yaradılır və RLS-ini orada alır.
        -- Bu siyahı yalnız BU faylda təyin olunan cədvəlləri əhatə etməlidir,
        -- əks halda təmiz quraşdırma "relation does not exist" ilə dayanardı.
        'monthly_fine_review_batches'
    ];
BEGIN
    FOREACH t IN ARRAY tenant_scoped LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        -- `positions` sistem şablonları (tenant_id IS NULL) hər tenant üçün
        -- oxunabilən olmalıdır — yeni tenant seed-i onlardan kopyalayır.
        IF t = 'positions' THEN
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON %I
                     USING (tenant_id = current_tenant_id() OR tenant_id IS NULL)
                     WITH CHECK (tenant_id = current_tenant_id())', t
            );
        ELSE
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON %I
                     USING (tenant_id = current_tenant_id())
                     WITH CHECK (tenant_id = current_tenant_id())', t
            );
        END IF;
    END LOOP;
END
$$;


-- `tenant_id` sütunu OLMAYAN alt-cədvəllər: izolyasiya valideyn sətir
-- üzərindən EXISTS ilə tətbiq olunur. Bu cədvəllər RLS-siz qalsaydı, tətbiq
-- rolu (UUID-ni bilməklə) başqa tenant-ın icazə matrisini və ya kamera
-- təyinatlarını oxuya bilərdi.
DO $$
DECLARE
    spec RECORD;
BEGIN
    FOR spec IN
        SELECT * FROM (VALUES
            ('user_permission_overrides',
             'EXISTS (SELECT 1 FROM employees e WHERE e.id = user_permission_overrides.user_id AND e.tenant_id = current_tenant_id())'),
            ('position_permissions',
             'EXISTS (SELECT 1 FROM positions p WHERE p.id = position_permissions.position_id AND (p.tenant_id = current_tenant_id() OR p.tenant_id IS NULL))'),
            ('user_preferences',
             'EXISTS (SELECT 1 FROM employees e WHERE e.id = user_preferences.user_id AND e.tenant_id = current_tenant_id())'),
            ('camera_operator_store_assignment',
             'EXISTS (SELECT 1 FROM employees e WHERE e.id = camera_operator_store_assignment.operator_id AND e.tenant_id = current_tenant_id())'),
            ('task_evidence',
             'EXISTS (SELECT 1 FROM tasks t WHERE t.id = task_evidence.task_id AND t.tenant_id = current_tenant_id())'),
            ('support_messages',
             'EXISTS (SELECT 1 FROM support_tickets st WHERE st.id = support_messages.ticket_id AND st.tenant_id = current_tenant_id())'),
            ('erp_server_config_backups',
             'EXISTS (SELECT 1 FROM erp_servers s WHERE s.id = erp_server_config_backups.server_id AND s.tenant_id = current_tenant_id())'),
            ('daily_attendance_sheet_lines',
             'EXISTS (SELECT 1 FROM daily_attendance_sheets d WHERE d.id = daily_attendance_sheet_lines.sheet_id AND d.tenant_id = current_tenant_id())'),
            ('store_server_mapping',
             'EXISTS (SELECT 1 FROM stores s WHERE s.id = store_server_mapping.store_id AND s.tenant_id = current_tenant_id())')
        ) AS t(table_name, predicate)
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', spec.table_name);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', spec.table_name);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I USING (%s) WITH CHECK (%s)',
            spec.table_name, spec.predicate, spec.predicate
        );
    END LOOP;
END
$$;

-- `permission_flags` qlobal kataloqdur (tenant-a aid deyil) — bütün tenant-lar
-- eyni flag adlarını görür. Burada məxfi məlumat yoxdur, RLS tətbiq edilmir.


-- ---------------------------------------------------------------------------
-- 28. TƏTBİQ DB ROLU VƏ MİNİMUM SƏLAHİYYƏTLƏR (SEC-009)
-- ---------------------------------------------------------------------------
-- Tətbiq HEÇ VAXT superuser/owner ilə qoşulmamalıdır. `kompasos_app` rolu:
--   * RLS-ə tabedir (owner deyil);
--   * DDL hüququ yoxdur (cədvəl yarada/silə bilməz);
--   * `audit_logs` üzərində yalnız INSERT/SELECT.
--
-- Supabase kimi idarə olunan platformalarda CREATE ROLE mümkün olmaya bilər —
-- o halda bu blok xəbərdarlıqla atlanır və eyni GRANT-lar platformanın öz
-- rolu üçün əl ilə tətbiq edilməlidir.
DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        BEGIN
            EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE', v_role);
            RAISE NOTICE 'Rol yaradıldı: % (LOGIN və şifrə ayrıca təyin edilməlidir)', v_role;
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE WARNING
                'CREATE ROLE % üçün səlahiyyət yoxdur — GRANT-ları platformanızın '
                'tətbiq roluna ƏL İLƏ tətbiq edin (bax schema.sql §28)', v_role;
            RETURN;
        END;
    END IF;

    EXECUTE format('GRANT USAGE ON SCHEMA kompasos TO %I', v_role);
    EXECUTE format(
        'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA kompasos TO %I',
        v_role
    );
    EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA kompasos TO %I', v_role);
    EXECUTE format(
        'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA kompasos TO %I', v_role
    );

    -- Audit izi: yalnız yazmaq və oxumaq (trigger-ə əlavə, defense-in-depth)
    EXECUTE format('REVOKE UPDATE, DELETE ON audit_logs FROM %I', v_role);
    EXECUTE format('REVOKE UPDATE, DELETE ON security_events FROM %I', v_role);
    -- İcazə reyestri: yalnız Root GUI-dan dəyişir, lakin DDL-ə bənzər
    -- əməliyyat olduğu üçün silmə hüququ verilmir.
    EXECUTE format('REVOKE DELETE ON permission_flags FROM %I', v_role);
    -- Lisenziya statusu YALNIZ Developer Panelindən dəyişir (bölmə 8)
    EXECUTE format('REVOKE UPDATE, DELETE ON license_tenants FROM %I', v_role);

    -- Gələcəkdə yaradılacaq cədvəllər üçün defolt səlahiyyətlər
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES IN SCHEMA kompasos
             GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', v_role
    );

    -- §29-dakı scheduler funksiyaları bu blokdan SONRA yaradılır — onlara aid
    -- səlahiyyətlər faylın sonundakı "§30 YEKUN SƏLAHİYYƏTLƏR" blokundadır.

    RAISE NOTICE 'Tətbiq rolu üçün səlahiyyətlər tətbiq olundu: %', v_role;
END
$$;


-- ---------------------------------------------------------------------------
-- 29. pg_cron OLMADAN İŞLƏMƏ (SEC-010) — XARİCİ SCHEDULER ÜÇÜN TƏK GİRİŞ
-- ---------------------------------------------------------------------------
-- Risk: pg_cron aktiv deyilsə timeout eskalasiyası, "İcazəsiz Qayıb"
-- təyinetməsi və 6 aylıq xal sıfırlanması SÜKUTLA işləməz — bu, spesifikasiyanın
-- bir neçə əsas biznes qaydasını görünməz şəkildə söndürər.
-- Həll: (a) icra qeydiyyatı cədvəli, (b) hamısını bir çağırışla işə salan
-- funksiya, (c) uzun müddət icra olunmayan job üçün sağlamlıq göstəricisi.

CREATE TABLE IF NOT EXISTS scheduled_job_runs (
    id            BIGSERIAL PRIMARY KEY,
    job_name      TEXT NOT NULL,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    affected_rows INTEGER,
    succeeded     BOOLEAN,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_runs_name_time
    ON scheduled_job_runs (job_name, started_at DESC);

-- TƏHLÜKƏSİZLİK: `p_sql` dinamik icra olunur, ona görə bu funksiya HEÇ VAXT
-- istifadəçi girişi ilə çağırılmamalıdır. Yalnız aşağıdakı
-- `run_all_scheduled_jobs()` onu sabit sətir literalları ilə çağırır və
-- tətbiq rolundan EXECUTE hüququ §28-də geri alınır.
CREATE OR REPLACE FUNCTION run_scheduled_job(p_job_name TEXT, p_sql TEXT)
RETURNS INTEGER AS $$
DECLARE
    v_id      BIGINT;
    v_result  INTEGER;
BEGIN
    INSERT INTO scheduled_job_runs (job_name) VALUES (p_job_name) RETURNING id INTO v_id;
    BEGIN
        EXECUTE 'SELECT ' || p_sql INTO v_result;
        UPDATE scheduled_job_runs
        SET finished_at = now(), affected_rows = v_result, succeeded = TRUE
        WHERE id = v_id;
        RETURN v_result;
    EXCEPTION WHEN OTHERS THEN
        UPDATE scheduled_job_runs
        SET finished_at = now(), succeeded = FALSE, error_message = SQLERRM
        WHERE id = v_id;
        RAISE WARNING 'Planlaşdırılmış job uğursuz oldu (%): %', p_job_name, SQLERRM;
        RETURN -1;
    END;
END;
$$ LANGUAGE plpgsql;

-- Xarici scheduler (Windows Task Scheduler / systemd timer / GitHub Actions)
-- yalnız BU funksiyanı çağırır: SELECT kompasos.run_all_scheduled_jobs();
CREATE OR REPLACE FUNCTION run_all_scheduled_jobs() RETURNS TABLE (
    job_name TEXT, affected_rows INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT 'escalate_verification_timeouts'::TEXT,
           run_scheduled_job('escalate_verification_timeouts',
                             'kompasos.cron_escalate_verification_timeouts()');
    RETURN QUERY
    SELECT 'escalate_task_deadlines'::TEXT,
           run_scheduled_job('escalate_task_deadlines',
                             'kompasos.cron_escalate_task_deadlines()');
    RETURN QUERY
    SELECT 'close_expired_appeals'::TEXT,
           run_scheduled_job('close_expired_appeals',
                             'kompasos.cron_close_expired_appeals()');
    RETURN QUERY
    SELECT 'detect_unauthorized_absences'::TEXT,
           run_scheduled_job('detect_unauthorized_absences',
                             'kompasos.cron_detect_unauthorized_absences()');
    RETURN QUERY
    SELECT 'reset_sales_points'::TEXT,
           run_scheduled_job('reset_sales_points', 'kompasos.cron_reset_sales_points()');
    RETURN QUERY
    SELECT 'notify_points_reset_upcoming'::TEXT,
           run_scheduled_job('notify_points_reset_upcoming',
                             'kompasos.cron_notify_points_reset_upcoming()');
    RETURN QUERY
    SELECT 'update_license_payment_status'::TEXT,
           run_scheduled_job('update_license_payment_status',
                             'kompasos.cron_update_license_payment_status()');
    RETURN QUERY
    SELECT 'prune_expired_backups'::TEXT,
           run_scheduled_job('prune_expired_backups',
                             'kompasos.cron_prune_expired_backups()');
    RETURN QUERY
    SELECT 'prune_expired_sessions'::TEXT,
           run_scheduled_job('prune_expired_sessions',
                             'kompasos.cron_prune_expired_sessions()');
END;
$$ LANGUAGE plpgsql;

-- System Health Monitor (bölmə 6) bu görünüşü oxuyur: hansı job gecikib?
CREATE OR REPLACE VIEW v_scheduled_job_health AS
SELECT
    j.job_name,
    max(j.started_at)                                   AS last_run_at,
    now() - max(j.started_at)                           AS since_last_run,
    bool_and(COALESCE(j.succeeded, FALSE))
        FILTER (WHERE j.started_at > now() - INTERVAL '1 day') AS all_ok_last_24h,
    (now() - max(j.started_at) > INTERVAL '2 hours')     AS is_stale
FROM scheduled_job_runs j
GROUP BY j.job_name;

COMMENT ON VIEW v_scheduled_job_health IS
    'is_stale = TRUE olduqda System Health Monitor xəbərdarlıq göstərməlidir — '
    'pg_cron və ya xarici scheduler dayanıb (SEC-010).';

-- pg_cron yoxdursa bu, artıq SÜKUTLA keçmir: WARNING + sağlamlıq qeydi
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        INSERT INTO scheduled_job_runs (job_name, finished_at, succeeded, error_message)
        VALUES ('__scheduler_bootstrap__', now(), FALSE,
                'pg_cron aktiv deyil — xarici scheduler '
                'kompasos.run_all_scheduled_jobs() funksiyasını hər 5 dəqiqədən bir '
                'çağırmalıdır, əks halda timeout eskalasiyası və xal sıfırlanması işləməyəcək');
        RAISE WARNING
            'pg_cron TAPILMADI. Xarici scheduler qurulmayana qədər avtomatik '
            'eskalasiya/hesablama işləməyəcək. Bax: docs/scheduler_setup.md';
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 30. YEKUN SƏLAHİYYƏTLƏR (bütün obyektlər yaradıldıqdan SONRA)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        RAISE NOTICE 'Rol % mövcud deyil — yekun səlahiyyətlər atlandı.', v_role;
        RETURN;
    END IF;

    -- §28-dən sonra yaradılan cədvəl/funksiyalar üçün təkrar GRANT
    EXECUTE format(
        'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA kompasos TO %I',
        v_role
    );
    EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA kompasos TO %I', v_role);
    EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA kompasos TO %I', v_role);

    -- Append-only qaytarılır (yeni GRANT onları geri açmış ola bilər)
    EXECUTE format('REVOKE UPDATE, DELETE ON audit_logs FROM %I', v_role);
    EXECUTE format('REVOKE UPDATE, DELETE ON security_events FROM %I', v_role);
    EXECUTE format('REVOKE DELETE ON permission_flags FROM %I', v_role);
    EXECUTE format('REVOKE UPDATE, DELETE ON license_tenants FROM %I', v_role);

    -- KRİTİK: `run_scheduled_job(TEXT, TEXT)` ixtiyari SQL icra edir.
    -- Tətbiq roluna verilsə, kompromis halında istənilən funksiyanı çağırmaq
    -- vektoru yaranardı. Yalnız `run_all_scheduled_jobs()` açıq qalır.
    EXECUTE format(
        'REVOKE EXECUTE ON FUNCTION run_scheduled_job(TEXT, TEXT) FROM %I', v_role
    );

    RAISE NOTICE 'Yekun səlahiyyətlər tətbiq olundu: %', v_role;
END
$$;

COMMENT ON SCHEMA kompasos IS
    'KompasOS v0.1.0 — Faza 1 sxemi. Sonrakı dəyişikliklər '
    'database/migrations/ altında nömrələnmiş miqrasiya faylları ilə aparılır. '
    'Təhlükəsizlik qərarları: docs/security_decisions.md (SEC-001…SEC-014).';

COMMIT;

-- ===========================================================================
-- FAZA 1 SXEMİ TAMAMLANDI
-- ===========================================================================
