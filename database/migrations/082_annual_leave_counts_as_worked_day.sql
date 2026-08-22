-- ===========================================================================
-- 082 — DEEP-GAP D1: `ANNUAL_LEAVE_COUNTS_AS_WORKED_DAY` ROOT PARAMETRİNİN
--   SEED-İ (MÖVCUD + YENİ KİRAYƏÇİ)
-- ===========================================================================
-- Tarix : 2026-08-22
-- Səbəb : DEEP-GAP dövrə 4-də `SystemLimitKey.ANNUAL_LEAVE_COUNTS_AS_WORKED_
--         DAY` açarı `policies.py`-a və `DEFAULT_LIMITS`-ə əlavə olundu
--         (`AttendanceCountingPolicy`, `entities/attendance_sheet.py`), lakin
--         SQL seed-i YAZILMADI. `test_root_control_parameter_parity.py`
--         qapısı bunu tutdu: üç halqadan (enum → `DEFAULT_LIMITS` → SQL seed)
--         SONUNCUSU qırıq idi.
--
-- ---------------------------------------------------------------------------
-- SEED OLMADAN NƏ OLURDU — "İDARƏ OLUNAN" GÖRÜNƏN, ƏSLİNDƏ HARDCODE
-- ---------------------------------------------------------------------------
-- `RootControlUseCase.list_limits` `for key in SystemLimitKey` üzərində dövr
-- edir, yəni açar ROOT ekranında GÖRÜNÜRDÜ — dəyəri isə `system_limits`
-- sətri olmadığı üçün `DEFAULT_LIMITS`-dən (kodda oturan fallback) gəlirdi.
-- Root "0" seçib yadda saxlasa, `UPDATE ... WHERE limit_key = ...` HEÇ BİR
-- sətrə dəyməzdi: ekran dəyişikliyi qəbul etmiş kimi görünər, sayğac isə
-- əvvəlki kimi işləyərdi. Bu, məhz `system_limits`-in mövcudluq səbəbinin
-- (bölmə 5: "sinifdəki sabit YALNIZ fallback ola bilər") sükutla pozulması
-- idi.
--
-- ---------------------------------------------------------------------------
-- NİYƏ DEFOLT "1" (SAYILIR)
-- ---------------------------------------------------------------------------
-- `AutoAttendanceStatus.OUTSIDE` (qısa fasilə/icazə ilə mağazadan kənarda
-- olmaq) ARTIQ `counts_as_worked=True`-dir. Ödənişli illik məzuniyyətin
-- əks istiqamətdə (sayılmır) başlaması eyni sistemin iki oxşar halını əks
-- qütblərə bölərdi. "0" seçimi mühasibatlıq siyasətidir və Root-a verilir —
-- bax `policies.py`-dakı `ANNUAL_LEAVE_COUNTS_AS_WORKED_DAY` şərhi.
--
-- EKRAN ETİKETİ BU AÇARDAN ASILI DEYİL: status HƏMİŞƏ "🟣 Məzuniyyətdə"
-- qalır, HEÇ VAXT "🔴 İcazəsiz qayıb" olmur. Açar YALNIZ "faktiki işlənilən
-- gün" SAYĞACINI dəyişir.
--
-- ---------------------------------------------------------------------------
-- `value_type` NİYƏ 'INTEGER', 'BOOLEAN' YOX
-- ---------------------------------------------------------------------------
-- Cədvəldə 'BOOLEAN' seçimi VAR (schema.sql §-dəki CHECK), lakin layihədə
-- HEÇ BİR seed onu işlətmir: `LOCAL_CLOCK_MANIPULATION_NOTIFY` (062) və
-- `DEVICE_APPROVAL_REQUIRED` (063) — hər ikisi eyni "bəli/xeyr" mənasını
-- daşıyır və hər ikisi `'INTEGER'` + `min='0'` / `max='1'` ilə yazılıb.
-- Səbəb: `_limit_int(...)` (və domendəki `AttendanceCountingPolicy`) dəyəri
-- `int` kimi oxuyur — 'BOOLEAN' yazılsaydı ROOT ekranı fərqli redaktor
-- göstərər, oxu yolu isə DƏYİŞMƏZ qalardı, yəni iki mənbə arasında yeni
-- fərq yaranardı. Mövcud iki presedent təkrarlanır.
--
-- ---------------------------------------------------------------------------
-- İKİ BLOK (MÖVCUD + YENİ KİRAYƏÇİ) — 062/072-NİN NAXIŞI
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` TOXUNULMUR: hər miqrasiyanın öz açarını ora
-- yazması həmin faylı bütün miqrasiyaların yığınına çevirərdi. Sətir formatı
-- iki blokda HƏRFƏN eynidir (`('AÇAR', 'dəyər', ...)`) — 062-nin şərhində
-- izah olunan səbəb: format ayrılsaydı paritet qapıları açarı "trigger-də
-- yoxdur" deyə oxuyardı.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('ANNUAL_LEAVE_COUNTS_AS_WORKED_DAY', '1', 'INTEGER', '0', '1',
     'Təsdiqlənmiş illik məzuniyyət günü Gündəlik Tabeldə «faktiki işlənilən '
     'gün» sayğacına daxil edilsinmi (1 = sayılır, 0 = yalnız fiziki iş '
     'günləri sayılır). Ekran etiketi dəyişmir — status həmişə «Məzuniyyətdə»')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

COMMIT;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR (062/072 NAXIŞI)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION seed_attendance_counting_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    SELECT NEW.tenant_id, v.limit_key, v.limit_value, v.value_type,
           v.min_value, v.max_value, v.description_az
      FROM (VALUES
        ('ANNUAL_LEAVE_COUNTS_AS_WORKED_DAY', '1', 'INTEGER', '0', '1',
         'Təsdiqlənmiş illik məzuniyyət günü Gündəlik Tabeldə «faktiki işlənilən '
         'gün» sayğacına daxil edilsinmi (1 = sayılır, 0 = yalnız fiziki iş '
         'günləri sayılır). Ekran etiketi dəyişmir — status həmişə «Məzuniyyətdə»')
      ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_attendance_counting_limits_for_new_tenant() IS
    'Yeni kirayəçiyə davamiyyət sayğacı parametrini əlavə edir '
    '(migrations/082). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_attendance_counting_limits ON license_tenants;
CREATE TRIGGER trg_seed_attendance_counting_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_attendance_counting_limits_for_new_tenant();

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- Root dəyəri əl ilə dəyişdirmişsə DOWN onu da silir — sətrin özü yenidən
-- yaransa dəyər defolta ("1") qayıdar, yəni siyasət seçimi İTƏR. Ona görə
-- DOWN yalnız miqrasiyanın SƏHVƏN tətbiqi halı üçündür:
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_attendance_counting_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_attendance_counting_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key = 'ANNUAL_LEAVE_COUNTS_AS_WORKED_DAY';
-- COMMIT;
-- ===========================================================================
