-- ===========================================================================
-- VENDOR-001 — MƏRKƏZİ VENDOR BAZASININ SXEMİ (DB-3 FAZA 1)
-- ===========================================================================
-- Tarix : 2026-08-16
--
-- ---------------------------------------------------------------------------
-- BU FAYL TENANT BAZASINA AİD DEYİL
-- ---------------------------------------------------------------------------
-- `database/migrations/NNN_*.sql` MÜŞTƏRİNİN bazasını qurur. Bu qovluq
-- (`migrations/vendor/`) isə TƏCHİZATÇININ öz mərkəzi bazasını qurur: hansı
-- müştərinin ödənişi gəlib, lisenziyası nə vaxt bitir, hansı çökmə hesabatı
-- gəlib. İki baza HEÇ VAXT eyni bağlantı ilə açılmır — vendor bazasının DSN-i
-- ayrıca mühit dəyişənindədir (`KOMPASOS_VENDOR_DSN`) və müştəri
-- quraşdırmasına DAXİL EDİLMİR.
--
-- Ona görə fayl adları da ayrı nömrələnir: `vendor/001`, `vendor/002`…
-- Tenant miqrasiyaları ilə nömrə toqquşması YOXDUR, çünki onlar heç vaxt eyni
-- bazaya tətbiq olunmur.
--
-- ---------------------------------------------------------------------------
-- SXEM ADI NİYƏ `vendor`
-- ---------------------------------------------------------------------------
-- `public` işlədilmir: Supabase-in öz obyektləri (`storage`, `auth`) orada
-- yaşayır və adların qarışması RLS siyasətini oxunmaz edərdi. Ayrı ad məkanı
-- həm de siyasətləri bir yerdə görməyə imkan verir: «`vendor` sxemindəki HƏR
-- cədvəldə RLS varmı?» sualı bir sorğu ilə cavablanır (bax vendor/003 testi).
--
-- ---------------------------------------------------------------------------
-- BU FAYL YALNIZ CƏDVƏL YARADIR — RLS AYRI FAYLDADIR (vendor/002)
-- ---------------------------------------------------------------------------
-- Bölünmə qəsdlidir: sxemi oxuyan adam «hansı sütunlar var» sualına, siyasəti
-- oxuyan adam «kim nə görür» sualına baxır. Bir faylda qarışdırılsaydı,
-- siyasət dəyişikliyi cədvəl dəyişikliyi kimi görünərdi.
-- ===========================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS vendor;
SET search_path TO vendor, public;

-- ---------------------------------------------------------------------------
-- 1. VENDOR HESABLARI
-- ---------------------------------------------------------------------------
-- ŞİFRƏ HEŞİ, ŞİFRƏNİN ÖZÜ YOX (tenant tərəfi ilə eyni qayda, SEC-002).
--
-- TOTP BURADA VAR — TENANT TƏRƏFİNDƏ YOXDUR (SEC-016) VƏ BU, ZİDDİYYƏT DEYİL:
-- SEC-016 2FA-nı MAĞAZA İŞÇİSİ üçün çıxarmışdı, çünki onların çoxunun
-- korporativ e-poçtu və şəxsi smartfonu yoxdur — 2FA orada girişi bloklayan
-- amilə çevrilirdi. Vendor hesabı isə TƏK bir nəfərindir (təchizatçının
-- özü), onun cihazı var və həmin hesab BÜTÜN müştərilərin lisenziyasını
-- söndürə bilir. Risk profili tamamilə fərqlidir.
--
-- `totp_secret` NULL ola bilər: hesab yaradılıb, lakin TOTP hələ
-- qeydiyyatdan keçməyib (bootstrap skriptinin aralıq vəziyyəti).
CREATE TABLE IF NOT EXISTS vendor_accounts (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email          TEXT NOT NULL UNIQUE
                       CHECK (email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    password_hash  TEXT NOT NULL,           -- Argon2id, plaintext DEYİL
    totp_secret    TEXT,                    -- base32; NULL = hələ qurulmayıb
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at  TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE vendor_accounts IS
    'Təchizatçının öz konsol hesabları. Müştəri bazasındakı `employees` ilə '
    'HEÇ BİR əlaqəsi yoxdur — ayrı sistem, ayrı baza (bax fayl başlığı).';
COMMENT ON COLUMN vendor_accounts.totp_secret IS
    'TOTP burada MƏCBURİDİR (bootstrap skripti qurur), tenant tərəfində isə '
    'SEC-016 ilə çıxarılıb — səbəb fərqi fayl başlığındadır.';

-- ---------------------------------------------------------------------------
-- 2. MÜŞTƏRİ (TENANT) REYESTRİ
-- ---------------------------------------------------------------------------
-- `tenant_id` MÜŞTƏRİ bazasındakı `license_tenants.tenant_id` ilə EYNİ UUID-dir,
-- lakin XARİCİ AÇAR YOXDUR — iki ayrı bazadır, FK fiziki olaraq mümkün deyil.
-- Uyğunluq tətbiq qatında saxlanılır; `UNIQUE` isə eyni müştərinin iki dəfə
-- qeydə alınmasının qarşısını alır.
--
-- `license_key` HEŞ DEYİL, AÇIQ SAXLANILIR — və bu, qəsdlidir: təchizatçı onu
-- müştəriyə TƏKRAR göndərə bilməlidir (quraşdırma itdikdə). Müştəri tərəfində
-- isə həmin açar `license_key_hash` kimi saxlanılır. Yəni açığı YALNIZ vendor
-- bazasındadır və o baza müştəri quraşdırmasına heç vaxt daxil edilmir.
CREATE TABLE IF NOT EXISTS tenants (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL UNIQUE,
    company_name       TEXT NOT NULL,
    license_key        TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'ODENIS_GOZLENILIR'
                           CHECK (status IN ('AKTIV', 'ODENIS_GOZLENILIR', 'DEAKTIV')),
    last_payment_date  DATE,
    next_payment_date  DATE,
    installed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_checkin_at    TIMESTAMPTZ,
    supabase_ref       TEXT,                -- müştərinin öz Supabase layihə ref-i
    contact_email      TEXT
                           CHECK (contact_email IS NULL
                                  OR contact_email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vendor_tenants_status ON tenants (status);
CREATE INDEX IF NOT EXISTS idx_vendor_tenants_next_payment
    ON tenants (next_payment_date) WHERE status <> 'DEAKTIV';

COMMENT ON TABLE tenants IS
    'Abunə reyestri. Müştəri bazasındakı `license_tenants` ilə EYNİ '
    '`tenant_id`-ni daşıyır, lakin FK YOXDUR — ayrı bazadır.';

-- ---------------------------------------------------------------------------
-- 3. ÖDƏNİŞLƏR
-- ---------------------------------------------------------------------------
-- SİLİNMİR, DÜZƏLDİLMİR: səhv yazılmış ödəniş `UPDATE` ilə deyil, TERS işarəli
-- yeni sətirlə düzəldilir (mühasibat naxışı). Ona görə `amount` mənfi ola
-- bilər, `CHECK` yalnız sıfırı qadağan edir — sıfırlıq sətir heç nə ifadə
-- etmir və yalnız hesabatı bulandırardı.
CREATE TABLE IF NOT EXISTS tenant_payments (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
    amount        NUMERIC(12, 2) NOT NULL CHECK (amount <> 0),
    currency      TEXT NOT NULL DEFAULT 'AZN' CHECK (char_length(currency) = 3),
    paid_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    period_start  DATE NOT NULL,
    period_end    DATE NOT NULL,
    recorded_by   UUID NOT NULL REFERENCES vendor_accounts(id) ON DELETE RESTRICT,
    note          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_payment_period CHECK (period_end >= period_start)
);

CREATE INDEX IF NOT EXISTS idx_vendor_payments_tenant
    ON tenant_payments (tenant_id, paid_at DESC);

COMMENT ON TABLE tenant_payments IS
    'Ödəniş jurnalı. Düzəliş TERS sətirlə edilir — `UPDATE`/`DELETE` mühasibat '
    'izini pozardı (`ON DELETE RESTRICT` də buna görədir).';

-- ---------------------------------------------------------------------------
-- 4. ÇÖKMƏ HESABATLARI
-- ---------------------------------------------------------------------------
-- PII YOXDUR (bölmə 8). `tenant_ref` ANONİMDİR: müştəri bazasındakı
-- `crash_reports.anonymous_tenant_ref` ilə eyni naxış — `tenant_id`-nin
-- birbaşa özü DEYİL, heş-i. Beləliklə eyni müştərinin çökmələri qruplaşdırıla
-- bilir, lakin hesabatı oxuyan onun KİM olduğunu görmür.
--
-- `occurrence_count`: eyni `fingerprint` təkrarlananda YENİ sətir yazılmır,
-- sayğac artır — 500 eyni çökmə cədvəli doldurmasın deyə.
CREATE TABLE IF NOT EXISTS crash_reports (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_ref       TEXT NOT NULL,          -- anonim heş, tenant_id DEYİL
    app_version      TEXT NOT NULL,
    exception_type   TEXT NOT NULL DEFAULT '',
    stack_trace      TEXT NOT NULL,
    fingerprint      TEXT NOT NULL,
    os_version       TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 1 CHECK (occurrence_count > 0),
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    occurred_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_ref, fingerprint, app_version)
);

CREATE INDEX IF NOT EXISTS idx_vendor_crash_fingerprint
    ON crash_reports (fingerprint, occurred_at DESC);

COMMENT ON TABLE crash_reports IS
    'Anonim çökmə hesabatları — PII YOXDUR. `tenant_ref` heşdir, birbaşa '
    'identifikator deyil.';

-- ---------------------------------------------------------------------------
-- 5. DƏSTƏK MÜRACİƏTLƏRİ
-- ---------------------------------------------------------------------------
-- `tenant_id` BURADA AÇIQDIR (çökmə hesabatından fərqli olaraq) və bu,
-- məcburidir: dəstək cavabı konkret müştəriyə qayıtmalıdır. Anonim müraciətə
-- cavab yazmaq mümkün olmazdı.
--
-- `is_from_vendor` sadə `BOOLEAN`-dır: göndərənin ROLU müştəri tərəfində
-- dəyişkəndir (Root, CEO, HR), vendor tərəfində isə həmişə eynidir — mühüm
-- olan mesajın HANSI TƏRƏFDƏN gəldiyidir.
CREATE TABLE IF NOT EXISTS support_tickets (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    message        TEXT NOT NULL CHECK (btrim(message) <> ''),
    sender_role    TEXT NOT NULL DEFAULT '',
    is_from_vendor BOOLEAN NOT NULL DEFAULT FALSE,
    status         TEXT NOT NULL DEFAULT 'OPEN'
                       CHECK (status IN ('OPEN', 'ANSWERED', 'CLOSED')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vendor_tickets_tenant
    ON support_tickets (tenant_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- 6. VENDOR AUDİT İZİ
-- ---------------------------------------------------------------------------
-- APPEND-ONLY: müştəri bazasındakı `audit_logs` ilə eyni prinsip. Lisenziyanı
-- söndürmək müştərinin bütün işini dayandırır — «kim, nə vaxt, nəyə görə»
-- sualının cavabı sonradan dəyişdirilə bilməməlidir.
CREATE TABLE IF NOT EXISTS vendor_audit_logs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vendor_account_id UUID REFERENCES vendor_accounts(id) ON DELETE SET NULL,
    action            TEXT NOT NULL,
    target_tenant_id  UUID,
    old_value         JSONB,
    new_value         JSONB,
    reason            TEXT,
    occurred_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vendor_audit_tenant
    ON vendor_audit_logs (target_tenant_id, occurred_at DESC);

COMMENT ON TABLE vendor_audit_logs IS
    'APPEND-ONLY (trigger vendor/002-də). Lisenziya söndürmək müştərinin '
    'işini dayandırır — səbəbi sonradan dəyişdirilə bilməz.';

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN
-- ---------------------------------------------------------------------------
-- Vendor sxeminin silinməsi BÜTÜN abunə tarixçəsini itirir. Yalnız sıfırdan
-- qurulan test bazasında mənalıdır.
--
-- BEGIN;
--   DROP SCHEMA IF EXISTS vendor CASCADE;
-- COMMIT;
