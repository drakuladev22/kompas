-- ===========================================================================
-- 043 — HESABAT TARİX ARALIĞININ ROOT PARAMETRİ (kompas1.md Faza 7)
-- ===========================================================================
-- Tarix : 2026-08-13
-- Səbəb : Faza 7 export ekranına `[Xüsusi Aralıq]` seçimi əlavə edir
--         (`ReportRange`, `src/application/use_cases/reporting.py`). Aralığın
--         uzunluğu artıq təqvim ayı ilə məhdud DEYİL — istifadəçi ixtiyari
--         başlanğıc/bitmə yaza bilər. `SystemLimitKey.REPORT_RANGE_MAX_DAYS`
--         + `DEFAULT_LIMITS` artıq elan edilib (`src/domain/policies.py`);
--         bu miqrasiya həmin açarı `system_limits`-ə yazır ki, ROOT İdarə
--         Mərkəzi ekranında GÖRÜNSÜN və dəyişdirilə bilsin.
--
--         Seed edilməyən açar "konfiqurasiya edilə bilən" görünər, faktiki
--         olaraq isə kodda oturan fallback işləyərdi — `tests/unit/
--         test_root_control_parameter_parity.py` bu boşluğu QAPIYA çevirib
--         (`migrations/039`–`042` ilə eyni əsaslandırma).
--
-- İdempotentdir. DOWN bloku faylın sonunda şərh içindədir.
--
-- MÖVCUD CƏDVƏLLƏRƏ TOXUNULMUR — bu miqrasiya SIRF `system_limits` seed-idir:
--   * `fines.exported_period` (schema.sql §-də `TEXT`) DƏYİŞMİR. Tam ay yolu
--     ORADA `'YYYY-MM'` yazmağa DAVAM EDİR; xüsusi aralıq isə
--     `'YYYY-MM-DD_YYYY-MM-DD'` yazır. Sütun `TEXT` olduğu üçün nə tip, nə
--     uzunluq dəyişikliyi lazımdır — və mövcud sətirlərin mənası qorunur.
--   * `work_modes` (schema.sql §8) DƏYİŞMİR: Faza 7 gündəlik norma saatını
--     `end_time − start_time` fərqindən HESABLAYIR (`TimeRange.duration`),
--     ayrıca `daily_norm_hours` SÜTUNU YARATMIR. Sütun olsaydı, saat aralığı
--     redaktə ediləndə iki dəyər sükutla sürüşərdi; donmuş norma isə ARTIQ
--     `overtime_log.norm_hours`-dadır (migrations/019) — həmin GÜNƏ aiddir və
--     kataloq sətrinə deyil.
--
-- ---------------------------------------------------------------------------
-- `min_value`/`max_value` HÜDUDLARININ ƏSASLANDIRMASI
-- ---------------------------------------------------------------------------
--   * min = 1 — bir günlük aralıq QANUNİDİR (bir günün tabelini çıxarmaq
--     real HR ehtiyacıdır). 0 mənasızdır: heç bir günü olmayan hesabat.
--   * max = 1100 — təxminən üç il. Bu, "istənilən ədəd" ilə "praktik hədd"
--     arasındakı sərhəddir: üç ildən uzun sorğu hesabat deyil, arxiv
--     ixracıdır və onun yolu ayrıdır. Hədd sxem sərhədi DEYİL, performans
--     siyasətidir — ona görə Root onu 1–1100 arasında sərbəst seçir.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. ROOT PARAMETRİ — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada (CI iki dəfə tətbiq edir) Root-un
-- artıq dəyişdirdiyi dəyər ÜSTÜNDƏN YAZILMIR (039–042 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('REPORT_RANGE_MAX_DAYS', '366', 'INTEGER', '1', '1100',
     'Hesabat export-unda seçilə bilən maksimum tarix aralığı (gün). '
     '`[Tam Ay]` yolu bu hədddən təsirlənmir (31 ≤ 366) — hədd yalnız '
     '`[Xüsusi Aralıq]` seçimini cilovlayır və məqsədi performansdır: '
     'çox uzun aralıq 21 filialın bütün davamiyyət/plan sətirlərini bir '
     'aqreqasiyada tarayıb GUI-ni dondurardı. Hədd aşılanda əməliyyat '
     'SÜKUTLA rədd edilmir — istifadəçiyə aydın mesaj göstərilir')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. ROOT PARAMETRİ — YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/036/039–042-dəki naxış təkrarlanır.
CREATE OR REPLACE FUNCTION seed_report_range_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'REPORT_RANGE_MAX_DAYS', '366', 'INTEGER', '1', '1100',
         'Hesabat export-unda seçilə bilən maksimum tarix aralığı (gün)')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_report_range_limits_for_new_tenant() IS
    'Yeni kirayəçiyə hesabat aralığının ROOT parametrini əlavə edir '
    '(migrations/043). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_report_range_limits ON license_tenants;
CREATE TRIGGER trg_seed_report_range_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_report_range_limits_for_new_tenant();

-- ---------------------------------------------------------------------------
-- 3. SÜTUN ŞƏRHİNİN GENİŞLƏNMƏSİ — `fines.exported_period`
-- ---------------------------------------------------------------------------
-- Sütunun ÖZÜ dəyişmir (yenə `TEXT`), lakin MƏNASI genişlənir: artıq yalnız
-- `'YYYY-MM'` deyil, xüsusi aralıq açarı da yazıla bilər. Şərhi yeniləməmək
-- gələcək oxucunu "niyə burada iki fərqli format var?" sualı ilə tək qoyardı.
COMMENT ON COLUMN fines.exported_period IS
    'Cərimənin HANSI export dövründə tutulduğu. Tam ay: ''YYYY-MM''. '
    'Xüsusi aralıq (Faza 7): ''YYYY-MM-DD_YYYY-MM-DD''. '
    'DOLU olması cərimənin BİR DƏFƏ tutulduğunun zəmanətidir — '
    '`Fine.is_exportable()` dolu sətri bir daha export-a buraxmır, ona görə '
    'ÜST-ÜSTƏ DÜŞƏN iki aralıq işçidən ikiqat pul kəsə BİLMƏZ. Üst-üstə düşən '
    'aralıqda artıq tutulmuş cərimə sükutla atılmır: `BonusPenaltySelection.'
    'already_exported_count` onu sayır və ekranda göstərilir.';

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətir silinsə, hesabat export-u İŞLƏMƏYƏ DAVAM EDİR — kod
-- `DEFAULT_LIMITS` fallback-ına düşür (366 gün). İtən yeganə şey Root-un
-- GUI-dan həddi dəyişdirmə imkanıdır. `fines.exported_period` sütununa və
-- `work_modes` cədvəlinə TOXUNULMUR.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_report_range_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_report_range_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key = 'REPORT_RANGE_MAX_DAYS';
-- COMMIT;
