-- ===========================================================================
-- 029 — #19/#20 ÜNSİYYƏT VƏ PERFORMANS ROOT PARAMETRLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-12
-- Səbəb : Faza 8 (kompasos11.md) `AnnouncementUseCase` və
--         `PerformanceReviewUseCase`-i qurur. Üç ədəd/mətn MƏRKƏZİ TƏLƏBƏ görə
--         (hər şey ROOT-dan idarə olunur) koda hardcode edilə bilməz.
--         `SystemLimitKey` + `DEFAULT_LIMITS` (src/domain/policies.py)
--         açarları artıq elan edir — bu miqrasiya onları `system_limits`-ə
--         SEED edir ki, ROOT İdarə Mərkəzi ekranında GÖRÜNSÜNLƏR
--         (migrations/022–028 ilə EYNİ naxış).
--
-- Bu miqrasiya YALNIZ SƏTİR əlavə edir: heç bir cədvəl, sütun, indeks və ya
-- məhdudiyyət yaradılmır, dəyişdirilmir, silinmir. `announcements` və
-- `performance_reviews` cədvəlləri ARTIQ migrations/020-dədir — ora
-- toxunulmur (o cümlədən `chk_review_not_self` və `enforce_announcement_
-- target_scope` trigger-i).
--
-- İdempotentdir — `ON CONFLICT DO NOTHING` ilə iki dəfə icra edilə bilər.
-- DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- ÜÇ AÇAR — NİYƏ EYNİ MİQRASİYADA
-- ---------------------------------------------------------------------------
-- #19 və #20 eyni fazada (Faza 8), eyni agentlə qurulur və hər ikisi TƏK
-- sətirlik "unudulmuş seed" boşluğunu bağlayır (`migrations/027/028`-in
-- açdığı yol). Ayrıca iki miqrasiya faylı yaratmaq yalnız iki dəfə eyni
-- boilerplate-i (trigger + `ON CONFLICT` bloku) təkrarlayardı.
--
-- ---------------------------------------------------------------------------
-- `ANNOUNCEMENT_VISIBILITY_DAYS` (1–90) — NİYƏ BU HÜDUDLARDA
-- ---------------------------------------------------------------------------
-- 0 QƏSDƏN İSTİSNA EDİLİB: tətbiq qatı (`AnnouncementUseCase._visibility_days`)
-- `<= 0` dəyərini "sərhədsiz görüntülənmə" kimi oxuyur (bax `entities/
-- announcement.py`) — bunu DB `CHECK`-inin bir hissəsi etmək domen qaydasını
-- iki yerə bölərdi. Yuxarı hüdud 90-dır: bir rüblük xəbərlər lövhəsi
-- pəncərəsindən uzağı "arxiv", "cari elan" deyil.
--
-- ---------------------------------------------------------------------------
-- `PERFORMANCE_REVIEW_PERIOD_TYPE` VƏ `..._KPI_CATALOG` NİYƏ `min_value`/
-- `max_value = NULL`
-- ---------------------------------------------------------------------------
-- Hər ikisi `TEXT` limitidir (dəyər sərbəst mətn/format) — ədədi hüdud
-- mənasızdır. Doğrulama tətbiq qatındadır: `PerformanceReviewPeriodType.
-- from_value()` naməlum dəyəri sükutla `MONTHLY`-ə salır, KPI kataloqu isə
-- yararsız hissələri sükutla ATIR (`_parse_kpi_catalog`) — `LEAVE_ALLOWANCE_
-- SOURCE`/`EXCEPTION_NOTIFY_MIN_SEVERITY` ilə EYNİ TEXT-limit fəlsəfəsi.
--
-- ---------------------------------------------------------------------------
-- NİYƏ FEATURE TOGGLE SƏTRİ ƏLAVƏ EDİLMİR
-- ---------------------------------------------------------------------------
-- #19/#20 YENİ modul açarı tələb etmir — hər ikisi `permission_flags`-dəki
-- fərdi flag-lə (`can_broadcast_announcements`/`can_conduct_performance_
-- review`, migrations/021) artıq qapılıdır. Bunlar `FeatureModule`-un təsvir
-- etdiyi "iş-prosesi modulu" (Kamera Təsdiqi, Shift Swap, ...) deyil —
-- `POS_MAX_DISCOUNT_PCT_CEILING`/`EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS`
-- kimi tək-flag-lə qapılı sənədləşdirmə/kommunikasiya funksiyalarıdır.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada Root-un artıq dəyişdirdiyi dəyər
-- ÜSTÜNDƏN YAZILMIR (013/017/018/022–028 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('ANNOUNCEMENT_VISIBILITY_DAYS', '14', 'INTEGER', '1', '90',
     '#19 — Elan İşçi Ana Ekranında NEÇƏ GÜN görünsün (geri çəkilməyibsə belə)'),
    ('PERFORMANCE_REVIEW_PERIOD_TYPE', 'MONTHLY', 'TEXT', NULL, NULL,
     '#20 — Qiymətləndirmə formasının DEFOLT dövr granulyarlığı: '
     'MONTHLY (aylıq) və ya QUARTERLY (rüblük)'),
    ('PERFORMANCE_REVIEW_KPI_CATALOG',
     'KEYFIYYET:İş Keyfiyyəti;MEHSULDARLIQ:Məhsuldarlıq;'
     'KOMANDA_ISI:Komanda İşi;MUSTERI_XIDMETI:Müştəri Xidməti',
     'TEXT', NULL, NULL,
     '#20 — Qiymətləndirmə formasının KPI siyahısı ("KOD:Ad;KOD:Ad" formatı)')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022–028-dəki naxış təkrarlanır: yeni kirayəçi
-- yarananda bu üç sətri əlavə edən AYRICA trigger.
CREATE OR REPLACE FUNCTION seed_communication_performance_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'ANNOUNCEMENT_VISIBILITY_DAYS', '14', 'INTEGER', '1', '90',
         '#19 — Elan İşçi Ana Ekranında NEÇƏ GÜN görünsün (geri çəkilməyibsə belə)'),
        (NEW.tenant_id, 'PERFORMANCE_REVIEW_PERIOD_TYPE', 'MONTHLY', 'TEXT', NULL, NULL,
         '#20 — Qiymətləndirmə formasının DEFOLT dövr granulyarlığı: '
         'MONTHLY (aylıq) və ya QUARTERLY (rüblük)'),
        (NEW.tenant_id, 'PERFORMANCE_REVIEW_KPI_CATALOG',
         'KEYFIYYET:İş Keyfiyyəti;MEHSULDARLIQ:Məhsuldarlıq;'
         'KOMANDA_ISI:Komanda İşi;MUSTERI_XIDMETI:Müştəri Xidməti',
         'TEXT', NULL, NULL,
         '#20 — Qiymətləndirmə formasının KPI siyahısı ("KOD:Ad;KOD:Ad" formatı)')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_communication_performance_limits_for_new_tenant() IS
    'Yeni kirayəçiyə #19/#20-nin üç ROOT parametrini əlavə edir (migrations/029). '
    '`seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_communication_performance_limits ON license_tenants;
CREATE TRIGGER trg_seed_communication_performance_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_communication_performance_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlərin silinməsi parametrləri ROOT ekranından yox edir; #19/#20
-- işləməyə davam edir, lakin `DEFAULT_LIMITS` dəyərləri ilə (src/domain/
-- policies.py) — yəni Root onları artıq dəyişdirə bilmir. Mövcud elan/
-- qiymətləndirmə sətirlərinə TƏSİRİ YOXDUR.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_communication_performance_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_communication_performance_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'ANNOUNCEMENT_VISIBILITY_DAYS', 'PERFORMANCE_REVIEW_PERIOD_TYPE',
--       'PERFORMANCE_REVIEW_KPI_CATALOG'
--   );
-- COMMIT;
