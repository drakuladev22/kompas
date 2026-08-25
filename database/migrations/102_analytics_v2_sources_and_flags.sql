-- ===========================================================================
-- 102 — ANALİTİKA GENİŞLƏNMƏSİ (v2backlog.md Faza 6) — MƏNBƏ + FLAG + LİMİT
-- ===========================================================================
-- Tarix : 2026-08-25
-- Mənbə : `v2backlog.md` FAZA 6 — beş yeni Dashboard widget-i üçün
--         kataloq/limit təminatı.
--
-- ---------------------------------------------------------------------------
-- 1. `DUPLICATE_FACE` İSTİSNA MƏNBƏYİ (Faza 6.2)
-- ---------------------------------------------------------------------------
-- Qayda (`DuplicateFaceExceptionRule`) tapıntını `exceptions.source_code`
-- ilə yazır, sütun isə `exception_sources`-a FOREIGN KEY-dir — kataloqda
-- sətir yoxdursa motor yazını SÜKUTLA atır və qayda TƏSİRSİZ qalır
-- (migrations/087 başlığındakı «seed olmadan qayda təsirsizdir» dərsi).
--
-- CİDDİYYƏT = HIGH: iki fərqli işçi qeydiyyatının EYNİ üzə düşməsi ya
-- təkrar-məşğulluq sui-istifadəsidir (bir adam iki maaş alır), ya da
-- kiminsə adına açılmış ikinci hesabdır — hər ikisi araşdırma tələb edir,
-- «baxılsın» deyil.
--
-- ---------------------------------------------------------------------------
-- 2. İKİ YENİ FLAG
-- ---------------------------------------------------------------------------
-- `can_view_operator_performance` (Faza 6.3) — spesifikasiya AÇIQ yazır:
-- «yalnız HR_Admin/CEO görür, operator ÖZÜ YOX». Mövcud kamera flag-i
-- `can_verify_returns` məhz OPERATORLARIN əlindədir — onu qapı etmək
-- spesifikasiyanın BİRBAŞA əksinə gedərdi. Ona görə ayrıca flag; defolt
-- sahiblik Root/CEO/HR_Admin (attrition risk ilə eyni üçlüy, migrations/
-- 021 naxışı), hardlock_level=0 — baxış flag-idir, Root sonradan genişləndirə
-- bilər.
--
-- `can_manage_campaign_periods` (Faza 6.4) — kampaniya tarixlərini daxil
-- etmək. Spesifikasiya: «Root/CEO daxil edir». Bu, HEYƏT PLANI qərarına
-- təsir edən girişdir (staffing_pattern tövsiyələrinə çəki verir), lakin
-- pul/anti-fraud yolu DEYİL — ona görə hardlock_level=0 ilə DELEGABLE
-- qalır, defolt sahiblik isə yalnız Root/CEO-dur.
--
-- ---------------------------------------------------------------------------
-- 3. ROOT PARAMETRİ — WORKLOAD_FAIRNESS_MAX_GAP (Faza 6.5)
-- ---------------------------------------------------------------------------
-- «İş-Yükü Ədalətliliyi Göstəricisi»nin **ROOT PARAMETRİ**: son 30 gündə
-- iki işçinin təyin olunmuş iş günü sayı arasındakı fərq bundan böyükdürsə,
-- sətir «əhəmiyyətli fərqli» nişanı alır. Defolt 4 gün: bir həftəlik növbə
-- dövründə iki işçi arasında 4+ günlük fərq artıq hiss edilən ədalətsizlikdir;
-- daha aşağı hədd normal planlamada da siqnal verərdi.
--
-- Aralıq 1..60: 1 — «heç bir fərqlənmə olmasın» (cəmi rejim), 60 — praktiki
-- olaraq söndürülür (iki aylıq fərq heç vaxt normal planlamada görünmur).
-- SIFIR icazəli DEYİL: 0 hər iki işçini nişanlayardı.
--
-- Seed 095/100-un İKİ BLOKLU naxışı (mövcud kirayəçilər + yeni kirayəçi
-- trigger-i). Dəyərlər `DEFAULT_LIMITS` ilə HƏRFƏN eynidir.
-- İDEMPOTENT, DOWN BLOKU SONDA.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. İSTİSNA MƏNBƏYİ
-- ---------------------------------------------------------------------------
INSERT INTO exception_sources (code, tenant_id, name_az, description_az, default_severity)
VALUES ('DUPLICATE_FACE', NULL, 'Eyni üzlü iki qeydiyyat şübhəsi',
    'Eyni kirayəçi daxilində iki FƏRQLİ işçinin üz vektorları sistemin '
    '«eyni adam» toleransından (`FACE_MATCH_TOLERANCE`) DAHA yaxındır '
    '(v2backlog.md Faza 6.2). Ya təkrar-məşğulluq, ya da başqası adına açılmış '
    'ikinci qeydiyyat. Qayda AVTOMATİK HEÇ NƏ ETMİR: hər iki qeydiyyat saxlanılır, '
    'qərar HR araşdırmasıdır.',
    'HIGH')
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. FLAG KATALOQU
-- ---------------------------------------------------------------------------
INSERT INTO permission_flags
    (code, category, name_az, description_az, hardlock_level,
     is_anti_fraud, is_camera_only)
VALUES
    ('can_view_operator_performance', 'HR', 'Kamera operatoru performansına bax',
     'v2backlog.md Faza 6.3 - operatorların orta cavab vaxtı və gecikmə '
     'tezliyi üzrə widget. Spesifikasiya AÇIQ qadağan edir: OPERATOR ÖZÜ bu '
     'göstəricini GÖRMƏMƏLİDİR - `can_verify_returns` daşıyan rol buraya defolt '
     'almır. Defolt: Root/CEO/HR_Admin.',
     0, FALSE, FALSE),
    ('can_manage_campaign_periods', 'HR', 'Kampaniya dövrlərini idarə et',
     'v2backlog.md Faza 6.4 - promosyon/kampaniya tarix-aralıqlarının daxil '
     'edilməsi. Bu tarixlər heyət-planlama tövsiyələrinə ƏLAVƏ ÇƏKİ verir, '
     'ona görə giriş planlama qərarıdır; defolt yalnız Root/CEO.',
     0, FALSE, FALSE)
ON CONFLICT (code) DO NOTHING;

DO $$
DECLARE
    v_wrong TEXT;
BEGIN
    SELECT string_agg(code, ', ')
      INTO v_wrong
      FROM permission_flags
     WHERE code IN ('can_view_operator_performance', 'can_manage_campaign_periods')
       AND ((code = 'can_view_operator_performance'
             AND (category <> 'HR' OR hardlock_level <> 0
                  OR is_anti_fraud <> FALSE OR is_camera_only <> FALSE))
         OR (code = 'can_manage_campaign_periods'
             AND (category <> 'HR' OR hardlock_level <> 0
                  OR is_anti_fraud <> FALSE OR is_camera_only <> FALSE)));

    IF v_wrong IS NOT NULL THEN
        RAISE EXCEPTION
            'MİQRASİYA DAYANDI: bu flag(lər) ARTIQ mövcuddur, lakin '
            'atributları gözlənilənlə uyğun deyil: %', v_wrong;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 3. DEFOLT SAHİBLİK
-- ---------------------------------------------------------------------------
-- Operator performansı: Root/CEO/HR_Admin üçlüyü — 021-in attrition naxışı.
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_view_operator_performance', TRUE
  FROM positions p
 WHERE p.code IN ('ROOT', 'CEO', 'HR_ADMIN')
ON CONFLICT DO NOTHING;

-- Kampaniya dövrləri: yalnız Root/CEO (spesifikasiyanın açıq sözü).
INSERT INTO position_permissions (position_id, flag_code, granted)
SELECT p.id, 'can_manage_campaign_periods', TRUE
  FROM positions p
 WHERE p.code IN ('ROOT', 'CEO')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. ROOT PARAMETRİ — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('WORKLOAD_FAIRNESS_MAX_GAP', '4', 'INTEGER', '1', '60',
     'Son 30 gündə iki işçinin təyin olunmuş iş günü sayı arasındakı fərq bu '
     'həddi aşarsa, «İş-Yükü Ədalətliliyi» widget-ində «fərqli» nişanı alır '
     '(v2backlog.md Faza 6.5)')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

COMMIT;

-- ---------------------------------------------------------------------------
-- 5. ROOT PARAMETRİ — YENİ KİRAYƏÇİLƏR (095/100 NAXIŞI)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION seed_analytics_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    SELECT NEW.tenant_id, v.limit_key, v.limit_value, v.value_type,
           v.min_value, v.max_value, v.description_az
      FROM (VALUES
        ('WORKLOAD_FAIRNESS_MAX_GAP', '4', 'INTEGER', '1', '60',
         'Son 30 gündə iki işçinin təyin olunmuş iş günü sayı arasındakı fərq bu '
         'həddi aşarsa, «İş-Yükü Ədalətliliyi» widget-ində «fərqli» nişanı alır '
         '(v2backlog.md Faza 6.5)')
     ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_analytics_limits_for_new_tenant() IS
    'Yeni kirayəçi yaradlanda analitika (v2backlog.md Faza 6) ROOT '
    'parametrlərini seedləyir (migrations/102) — 095/100-un eyni naxışı.';

DROP TRIGGER IF EXISTS trg_seed_analytics_limits ON license_tenants;
CREATE TRIGGER trg_seed_analytics_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_analytics_limits_for_new_tenant();

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_analytics_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_analytics_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key = 'WORKLOAD_FAIRNESS_MAX_GAP';
--   DELETE FROM position_permissions
--    WHERE flag_code IN ('can_view_operator_performance',
--                        'can_manage_campaign_periods');
--   DELETE FROM permission_flags
--    WHERE code IN ('can_view_operator_performance', 'can_manage_campaign_periods');
--   DELETE FROM exception_sources WHERE code = 'DUPLICATE_FACE';
-- COMMIT;
-- ===========================================================================
