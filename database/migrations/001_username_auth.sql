-- ===========================================================================
-- MIGRATION 001 — USERNAME-ƏSASLI ADMİN AUTENTİFİKASİYASI
-- ===========================================================================
-- Tarix   : 2026-08-09
-- Səbəb   : Qərar dəyişikliyi — admin-tier giriş "e-poçt + şifrə + TOTP 2FA"
--           modelindən "istifadəçi adı + şifrə" modelinə keçir. TOTP/2FA
--           tamamilə çıxarılır, e-poçt artıq giriş identifikatoru DEYİL.
--
-- `schema.sql` da eyni istiqamətdə yenilənib (yeni quraşdırmalar üçün).
-- Bu fayl MÖVCUD bazalar üçündür və idempotentdir — təkrar icra təhlükəsizdir.
-- Geri qaytarma (DOWN) faylın sonunda şərh içində verilib.
--
-- ---------------------------------------------------------------------------
-- İKİ DİZAYN QƏRARI (tələbdən fərqlənir — səbəbi ilə)
-- ---------------------------------------------------------------------------
-- 1) `employees.email` SİLİNMİR, `notification_email`-ə AD DƏYİŞDİRİLİR.
--    Tələb "email login identifikatoru kimi çıxarılır" + "yeni nullable
--    notification_email əlavə et" deyir. Hər ikisini AYRICA sütun kimi
--    saxlamaq iki problem yaradardı: (a) mövcud e-poçt məlumatı yeni sütuna
--    köçürülməsə itərdi, (b) eyni məlumat üçün iki mənbə qalardı və hansının
--    doğru olduğu bilinməzdi. Ad dəyişikliyi hər iki tələbi ödəyir:
--    identifikator rolu itir, məlumat qalır, təkrarlanma olmur.
--
-- 2) `license_tenants`-a YENİ `company_contact_*` sütunları ƏLAVƏ EDİLMİR —
--    mövcud `contact_email`/`contact_phone` bu ada dəyişdirilir.
--    Həmin sütunlar artıq DƏQİQ bu rolu oynayırdı: tenant-səviyyəli əlaqə,
--    fərdi hesabdan tam ayrı, ödəniş/lisenziya bildirişləri üçün. Yanına
--    eyni məzmunlu ikinci cüt əlavə etmək Emergency Access Recovery-nin
--    SƏHV sütunu yoxlaması riskini yaradardı — bu isə təhlükəsizlik qüsurudur.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 1. employees.username
-- ---------------------------------------------------------------------------
ALTER TABLE employees ADD COLUMN IF NOT EXISTS username CITEXT;

COMMENT ON COLUMN employees.username IS
    'Admin-tier giriş identifikatoru (bölmə 2). CITEXT — "Rashad" və "rashad" '
    'eyni hesabdır. Kiosk-yalnız işçilər üçün NULL ola bilər; admin-tier '
    'rollar üçün chk_employee_auth onu şifrə ilə birlikdə məcburi edir.';

-- ---------------------------------------------------------------------------
-- 2. email → notification_email (AD DƏYİŞİKLİYİ, məlumat qorunur)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_attribute
         WHERE attrelid = 'employees'::regclass AND attname = 'email' AND NOT attisdropped
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_attribute
         WHERE attrelid = 'employees'::regclass
           AND attname = 'notification_email' AND NOT attisdropped
    ) THEN
        ALTER TABLE employees RENAME COLUMN email TO notification_email;
        RAISE NOTICE 'employees.email → notification_email';
    END IF;
END
$$;

-- Sütun heç vaxt olmayıbsa (təmiz baza) yaradılır.
ALTER TABLE employees ADD COLUMN IF NOT EXISTS notification_email CITEXT;

COMMENT ON COLUMN employees.notification_email IS
    'YALNIZ bildiriş üçün, autentifikasiyadan TAM ASILI DEYİL. İstifadəçi '
    'Ayarlar ekranından özü doldurur. Boşdursa kritik bildiriş yalnız '
    'tətbiq-daxili qalır — bu, gözlənilən davranışdır, xəta deyil (bölmə 7).';

-- ---------------------------------------------------------------------------
-- 3. Mövcud sətirlər üçün username backfill
-- ---------------------------------------------------------------------------
-- Şifrəsi olan hər sətrə username lazımdır, əks halda chk_employee_auth
-- əlavə edilə bilməz. Mənbə: köhnə e-poçtun lokal hissəsi; toqquşma olarsa
-- ardıcıl rəqəm əlavə olunur.
DO $$
DECLARE
    r          RECORD;
    v_base     TEXT;
    v_candidate TEXT;
    v_suffix   INTEGER;
BEGIN
    FOR r IN
        SELECT id, tenant_id, notification_email
          FROM employees
         WHERE username IS NULL
           AND password_hash IS NOT NULL
         ORDER BY created_at
    LOOP
        v_base := lower(regexp_replace(
            COALESCE(split_part(r.notification_email::TEXT, '@', 1), ''),
            '[^a-z0-9._-]', '', 'g'
        ));
        IF length(v_base) < 3 THEN
            v_base := 'user' || replace(r.id::TEXT, '-', '');
        END IF;
        v_base := left(v_base, 28);

        v_candidate := v_base;
        v_suffix := 1;
        WHILE EXISTS (
            SELECT 1 FROM employees
             WHERE tenant_id = r.tenant_id AND username = v_candidate::CITEXT
        ) LOOP
            v_suffix := v_suffix + 1;
            v_candidate := v_base || v_suffix::TEXT;
        END LOOP;

        UPDATE employees SET username = v_candidate WHERE id = r.id;
        RAISE NOTICE 'username backfill: % → %', r.id, v_candidate;
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------------
-- 4. Unikallıq və format qaydaları
-- ---------------------------------------------------------------------------
-- Köhnə e-poçt unikallığı ARTIQ LAZIM DEYİL: notification_email iki işçidə
-- eyni ola bilər (məs. eyni ailə ünvanı, ortaq şöbə qutusu).
ALTER TABLE employees DROP CONSTRAINT IF EXISTS employees_tenant_id_email_key;

-- Partial unique index: NULL username-lər (kiosk-yalnız işçilər) məhdudlaşmır.
CREATE UNIQUE INDEX IF NOT EXISTS uq_employees_tenant_username
    ON employees (tenant_id, username) WHERE username IS NOT NULL;

ALTER TABLE employees DROP CONSTRAINT IF EXISTS chk_employee_username;
ALTER TABLE employees ADD CONSTRAINT chk_employee_username
    CHECK (username IS NULL OR username ~* '^[a-z0-9][a-z0-9._-]{2,31}$');

-- Köhnə e-poçt CHECK-i yeni ada uyğunlaşdırılır.
ALTER TABLE employees DROP CONSTRAINT IF EXISTS chk_employee_email;
ALTER TABLE employees DROP CONSTRAINT IF EXISTS chk_employee_notification_email;
ALTER TABLE employees ADD CONSTRAINT chk_employee_notification_email
    CHECK (notification_email IS NULL
           OR notification_email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$');

-- ƏSAS DƏYİŞİKLİK: autentifikasiya invariantı artıq USERNAME-ə bağlıdır.
ALTER TABLE employees DROP CONSTRAINT IF EXISTS chk_employee_auth;
ALTER TABLE employees ADD CONSTRAINT chk_employee_auth
    CHECK (pin_hash IS NOT NULL OR (username IS NOT NULL AND password_hash IS NOT NULL));

-- ---------------------------------------------------------------------------
-- 5. TOTP / 2FA sütunlarının SİLİNMƏSİ
-- ---------------------------------------------------------------------------
-- Bu sütunlar şifrələnmiş sirr saxlayır. Onları "istifadə etmirik" deyib
-- yerində qoymaq lazımsız risk olardı: sirr sızdırıla bilər, amma heç bir
-- funksiya ona ehtiyac duymur.
ALTER TABLE employees
    DROP COLUMN IF EXISTS totp_secret_encrypted,
    DROP COLUMN IF EXISTS totp_enabled,
    DROP COLUMN IF EXISTS totp_enrolled_at,
    DROP COLUMN IF EXISTS totp_last_used_counter,
    DROP COLUMN IF EXISTS totp_backup_code_hashes;

ALTER TABLE auth_sessions DROP COLUMN IF EXISTS totp_verified;

-- ---------------------------------------------------------------------------
-- 6. security_events: cəhd edilən identifikator artıq username-dir
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_attribute
         WHERE attrelid = 'security_events'::regclass
           AND attname = 'email_attempt' AND NOT attisdropped
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_attribute
         WHERE attrelid = 'security_events'::regclass
           AND attname = 'username_attempt' AND NOT attisdropped
    ) THEN
        ALTER TABLE security_events RENAME COLUMN email_attempt TO username_attempt;
    END IF;
END
$$;

ALTER TABLE security_events ADD COLUMN IF NOT EXISTS username_attempt CITEXT;

-- ---------------------------------------------------------------------------
-- 7. license_tenants — tenant-səviyyəli əlaqə (Emergency Access Recovery)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_attribute
         WHERE attrelid = 'license_tenants'::regclass
           AND attname = 'contact_email' AND NOT attisdropped
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_attribute
         WHERE attrelid = 'license_tenants'::regclass
           AND attname = 'company_contact_email' AND NOT attisdropped
    ) THEN
        ALTER TABLE license_tenants RENAME COLUMN contact_email TO company_contact_email;
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_attribute
         WHERE attrelid = 'license_tenants'::regclass
           AND attname = 'contact_phone' AND NOT attisdropped
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_attribute
         WHERE attrelid = 'license_tenants'::regclass
           AND attname = 'company_contact_phone' AND NOT attisdropped
    ) THEN
        ALTER TABLE license_tenants RENAME COLUMN contact_phone TO company_contact_phone;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_constraint
         WHERE conname = 'chk_tenant_email'
           AND connamespace = current_schema()::regnamespace) THEN
        ALTER TABLE license_tenants RENAME CONSTRAINT chk_tenant_email
            TO chk_tenant_company_contact_email;
    END IF;
END
$$;

ALTER TABLE license_tenants ADD COLUMN IF NOT EXISTS company_contact_email TEXT;
ALTER TABLE license_tenants ADD COLUMN IF NOT EXISTS company_contact_phone TEXT;

COMMENT ON COLUMN license_tenants.company_contact_email IS
    'Şirkət-səviyyəli əlaqə — fərdi hesabdan TAM AYRI. Emergency Access '
    'Recovery-də kimlik təsdiqi və ödəniş/lisenziya bildirişləri üçün '
    'YEGANƏ mənbədir (bölmə 2, 8).';
COMMENT ON COLUMN license_tenants.company_contact_phone IS
    'Şirkət-səviyyəli əlaqə telefonu — Emergency Access Recovery-də '
    'alternativ kimlik təsdiqi kanalı (bölmə 2).';

COMMIT;

-- ===========================================================================
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ===========================================================================
-- DİQQƏT: TOTP sütunlarındakı MƏLUMAT geri qaytarıla bilməz (şifrələnmiş
-- sirrlər silinib). Aşağıdakı skript yalnız STRUKTURU bərpa edir; 2FA yenidən
-- tələb olunarsa hər admin yenidən enrol olmalıdır.
--
-- BEGIN;
--   ALTER TABLE license_tenants RENAME COLUMN company_contact_email TO contact_email;
--   ALTER TABLE license_tenants RENAME COLUMN company_contact_phone TO contact_phone;
--   ALTER TABLE license_tenants RENAME CONSTRAINT chk_tenant_company_contact_email
--       TO chk_tenant_email;
--   ALTER TABLE security_events RENAME COLUMN username_attempt TO email_attempt;
--   ALTER TABLE auth_sessions ADD COLUMN totp_verified BOOLEAN NOT NULL DEFAULT FALSE;
--   ALTER TABLE employees
--       ADD COLUMN totp_secret_encrypted TEXT,
--       ADD COLUMN totp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
--       ADD COLUMN totp_enrolled_at TIMESTAMPTZ,
--       ADD COLUMN totp_last_used_counter BIGINT,
--       ADD COLUMN totp_backup_code_hashes TEXT[] NOT NULL DEFAULT '{}';
--   ALTER TABLE employees DROP CONSTRAINT chk_employee_auth;
--   ALTER TABLE employees RENAME COLUMN notification_email TO email;
--   ALTER TABLE employees ADD CONSTRAINT chk_employee_auth
--       CHECK (pin_hash IS NOT NULL OR (email IS NOT NULL AND password_hash IS NOT NULL));
--   ALTER TABLE employees ADD CONSTRAINT employees_tenant_id_email_key UNIQUE (tenant_id, email);
--   DROP INDEX IF EXISTS uq_employees_tenant_username;
--   ALTER TABLE employees DROP CONSTRAINT IF EXISTS chk_employee_username;
--   ALTER TABLE employees DROP COLUMN username;
-- COMMIT;
