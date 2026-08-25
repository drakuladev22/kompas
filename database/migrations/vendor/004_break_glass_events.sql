-- ===========================================================================
-- VENDOR 004 — FÖVQƏLADƏ (BREAK-GLASS) GİRİŞ HADİSƏLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-25
-- Mənbə : `v2backlog.md` Faza 5.4 — «hər istifadə mərkəzi vendor bazasına da
--         yazılsın».
--
-- ---------------------------------------------------------------------------
-- NİYƏ `vendor_audit_logs` TƏKRAR İSTİFADƏ EDİLMİR
-- ---------------------------------------------------------------------------
-- `vendor_audit_logs` VENDOR ƏMƏLİYYATLARININ jurnalıdır: sətirlərin aktoru
-- `vendor_account_id`-dir, yəni hazırlayıcının öz işçisi. Break-glass isə
-- MÜŞTƏRİ tərəfində, hazırlayıcının heç bir iştirakı olmadan baş verir —
-- həmin cədvələ yazılsaydı, `vendor_account_id IS NULL` sətirləri «kimin
-- etdiyi bilinməyən vendor əməliyyatı» kimi oxunardı və audit izinin mənası
-- pozulardı.
--
-- ---------------------------------------------------------------------------
-- `tenant_id` NİYƏ AÇIQDIR (`crash_reports`-un anonim heşi DEYİL)
-- ---------------------------------------------------------------------------
-- Çökmə hesabatı statistikadır — hansı müştəridə baş verdiyi əhəmiyyətsizdir.
-- Break-glass isə KONKRET müştəridə KONKRET şəxsin Root səlahiyyəti almasıdır:
-- hazırlayıcı zəng edib «sizin sistemdə fövqəladə giriş açılıb, xəbəriniz
-- varmı?» soruşa bilməlidir. Anonim sətir bu sualı verməyə imkan verməzdi.
-- `support_tickets`-in eyni qərarı (bax vendor/001, bölmə 5).
--
-- ---------------------------------------------------------------------------
-- İŞÇİNİN ADI YAZILMIR — YALNIZ UUID
-- ---------------------------------------------------------------------------
-- Vendor bazası müştərinin PII-sini saxlamır (vendor/001 prinsipi). UUID
-- «kim» sualını müştəri tərəfdə cavablandırmağa kifayət edir: hazırlayıcı
-- zəng edir, müştəri öz `audit_logs`-una baxıb adı özü görür.
--
-- APPEND-ONLY: `tenant_payments`/`vendor_audit_logs` ilə eyni qrant naxışı
-- (`SELECT, INSERT` — `UPDATE`/`DELETE` YOXDUR). Fövqəladə giriş qeydinin
-- sonradan dəyişdirilə bilməsi onu sübut olmaqdan çıxarardı.
--
-- İDEMPOTENT, DOWN BLOKU SONDA.
-- ===========================================================================

SET search_path TO vendor, public;

BEGIN;

CREATE TABLE IF NOT EXISTS break_glass_events (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- FK YOX: müştəri quraşdırması `tenants` sətrindən ƏVVƏL də (test/
    -- staging, hələ qeydiyyatdan keçməmiş kirayəçi) hadisə göndərə bilər və
    -- FK həmin halda yazını RƏDD edərdi — yəni ən şübhəli hadisə məhz
    -- qeydiyyatsız quraşdırmada itərdi.
    tenant_id         UUID NOT NULL,

    -- Müştəri bazasındakı `break_glass_grants.id` — İKİ baza arasındakı
    -- yeganə bağ. UNIQUE: təkrar-cəhd (`retry_vendor_reports`) eyni sətri
    -- iki dəfə yazmamalıdır.
    grant_id          UUID NOT NULL UNIQUE,

    requested_by      UUID NOT NULL,
    approved_by       UUID,
    status            TEXT NOT NULL,
    reason            TEXT NOT NULL,

    requested_at      TIMESTAMPTZ NOT NULL,
    expires_at        TIMESTAMPTZ,

    -- Vendor tərəfin öz vaxtı — müştəri saatından ASILI DEYİL (TIME-1 ruhu).
    received_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vendor_break_glass_tenant
    ON break_glass_events (tenant_id, received_at DESC);

COMMENT ON TABLE break_glass_events IS
    'Müştəri quraşdırmasında fövqəladə (break-glass) Root səlahiyyətinin hər '
    'istifadəsi (v2backlog.md Faza 5.4). PII YOXDUR — yalnız UUID-lər. '
    'APPEND-ONLY.';

GRANT SELECT, INSERT ON vendor.break_glass_events TO kompasos_vendor;

ALTER TABLE break_glass_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE break_glass_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS vendor_only ON break_glass_events;
CREATE POLICY vendor_only ON break_glass_events FOR ALL TO kompasos_vendor
    USING (TRUE) WITH CHECK (TRUE);

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə)
-- ---------------------------------------------------------------------------
-- DİQQƏT: bu cədvəl fövqəladə giriş SÜBUTUDUR — silinməsi «kim, nə vaxt Root
-- səlahiyyəti aldı» sualını mərkəzi tərəfdə cavabsız qoyur.
--
-- BEGIN;
--   SET search_path TO vendor, public;
--   DROP TABLE IF EXISTS break_glass_events;
-- COMMIT;
-- ===========================================================================
