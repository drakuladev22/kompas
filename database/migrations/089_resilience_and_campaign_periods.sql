-- ===========================================================================
-- 089 — TEXNİKİ-MƏSUL ŞƏXS SAHƏSİ (Faza 5.2) + KAMPANİYA DÖVRLƏRİ (Faza 6.4)
-- ===========================================================================
-- Tarix : 2026-08-24
-- Mənbə : `v2backlog.md` FAZA 1.
--
-- ---------------------------------------------------------------------------
-- NİYƏ İKİ FƏRQLİ FAZA BİR MİQRASİYADA
-- ---------------------------------------------------------------------------
-- Hər ikisi KİÇİK, TƏK-obyektli əlavələrdir (bir sütun, bir kiçik kataloq
-- cədvəli) və heç biri digərinin davranışına toxunmur — 084/088-in eyni
-- əsaslandırması: reyestrdə tək sətir, cari buraxılışın "kiçik HR/analitika
-- əlavələri" hissəsini bir SHA ilə cavablandırır.
--
-- ---------------------------------------------------------------------------
-- `stores.technical_contact_employee_id` — NİYƏ CƏDVƏL DEYİL
-- ---------------------------------------------------------------------------
-- System Health Monitor (`infrastructure/erp/system_health.py`) CANLI/
-- HESABLANMIŞ sürətdir (DB ping, disk, NTP sürüşməsi) — server tərəfində
-- TARİXÇƏ SAXLAMIR, hər sorğuda YENİDƏN ölçülür. Faza 5.2-nin YEGANƏ sxem
-- ehtiyacı "bu mağazanın nasazlıq bildirişini kim alsın?" sualının CAVABIDIR
-- — TƏK dəyər, `stores` sətrinin bir xüsusiyyətidir, WORKFLOW deyil. Bildiriş
-- özü mövcud `notifications` cədvəlinə yazılır (yeni sxem lazım deyil);
-- nasazlıq HADİSƏSİNİN tarixçəsi ayrıca soruşulmayıb, ona görə audit-cədvəli
-- əlavə edilmir.
--
-- ---------------------------------------------------------------------------
-- `campaign_periods` — NİYƏ YENİ CƏDVƏL
-- ---------------------------------------------------------------------------
-- Heç bir mövcud cədvəldə "adlı tarix-aralığı" (kampaniya) konsepti yoxdur.
-- `staffing_pattern_suggestions` (migrations/019) bu məlumatı İSTEHLAK
-- edəcək (kampaniya tarixlərində tarixi-nümunə-təklifinə əlavə çəki
-- veriləcək), YARATMIR — mövcud cədvəli genişləndirmək YANLIŞ istiqamətdə
-- asılılıq yaradardı (təklif mühərriki kataloqa, kataloq təklif
-- mühərrikinə YOX).
--
-- ---------------------------------------------------------------------------
-- RLS: hər ikisi standart `tenant_isolation`.
-- TIME-1: TƏTBİQ EDİLMİR — hər ikisi Root/CEO-authored KATALOQ verisidir
-- (insan öz-özünə lehinə vaxt manipulyasiyası riski daşımır), `field_report_
-- types`/`feature_toggles` ilə eyni səbəb.
--
-- İDEMPOTENT, DOWN BLOKU SONDA. `schema.sql` YENİLƏNMİR (CLAUDE.md §7).
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. `stores` — TEXNİKİ-MƏSUL ŞƏXS
-- ---------------------------------------------------------------------------
ALTER TABLE stores
    ADD COLUMN IF NOT EXISTS technical_contact_employee_id UUID
        REFERENCES employees(id) ON DELETE SET NULL;

COMMENT ON COLUMN stores.technical_contact_employee_id IS
    'Faza 5.2 (v2backlog.md): Kiosk/POS aparat-nasazlığı bildirişinin '
    'göndəriləcəyi KONKRET texniki-məsul şəxs. İSTƏYƏ-BAĞLI (NULL = bildiriş '
    'System Health Monitor-un mövcud defolt kanalına gedir). ON DELETE SET '
    'NULL: məsul şəxs deaktiv/silinsə (praktikada soft delete) mağaza sətri '
    'yetim qalmamalıdır (migrations/089).';

-- ---------------------------------------------------------------------------
-- 2. `campaign_periods` — Faza 6.4
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS campaign_periods (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,

    name          TEXT NOT NULL CHECK (char_length(trim(name)) >= 2),
    start_date    DATE NOT NULL,
    end_date      DATE NOT NULL,
    CONSTRAINT chk_campaign_period_dates CHECK (end_date >= start_date),

    -- NO ACTION: "kim daxil etdi?" kampaniya tarixçəsindən uzun yaşayır
    -- (`announcements.created_by` ilə eyni əsaslandırma).
    created_by    UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,

    -- Soft delete: keçmiş kampaniya tarixi tarixi-nümunə hesablamasında
    -- İSTİFADƏ OLUNMUŞ OLA BİLƏR — fiziki silmə həmin hesablamanın izahını
    -- itirər (`catalogs.py` qaydası).
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    deactivated_at TIMESTAMPTZ,

    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE campaign_periods IS
    'Faza 6.4 (v2backlog.md): CEO/Root-un daxil etdiyi kampaniya tarix-'
    'aralığı — mövcud "tarixi-nümunə-təklifi" (`staffing_pattern_'
    'suggestions`) bu tarixlərdə ƏLAVƏ ÇƏKİ tətbiq edir. Bu cədvəl '
    'İSTEHLAK OLUNUR, istehsal etmir (migrations/089).';

CREATE INDEX IF NOT EXISTS idx_campaign_periods_range
    ON campaign_periods (tenant_id, start_date, end_date)
    WHERE is_active;

ALTER TABLE campaign_periods ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON campaign_periods;
CREATE POLICY tenant_isolation ON campaign_periods
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DROP TRIGGER IF EXISTS trg_campaign_periods_updated ON campaign_periods;
CREATE TRIGGER trg_campaign_periods_updated
    BEFORE UPDATE ON campaign_periods
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- `stores.technical_contact_employee_id` SİLİNSƏ mövcud təyinatlar İTİR —
-- YALNIZ miqrasiya SƏHVƏN tətbiq olunub və HEÇ bir sətir doldurulmayıbsa
-- işlədin. `campaign_periods` SİLİNSƏ tarixi-nümunə hesablaması artıq həmin
-- kampaniyalara ÇƏKİ tətbiq ETMƏYƏCƏK (davranış geri qayıdır, data itkisi
-- YOX — sadəcə kampaniya ADI/tarixi itir).
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_campaign_periods_updated ON campaign_periods;
--   DROP INDEX IF EXISTS idx_campaign_periods_range;
--   DROP TABLE IF EXISTS campaign_periods;
--   ALTER TABLE stores DROP COLUMN IF EXISTS technical_contact_employee_id;
-- COMMIT;
-- ===========================================================================
