-- ===========================================================================
-- 040 — İLLİK MƏZUNİYYƏT BALANSININ (#28) ROOT PARAMETRLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-13
-- Səbəb : `kompas1.md` Faza 4 — İllik Məzuniyyət Balansı (#28) BACKEND-i on
--         konfiqurasiya dəyəri işlədir. `SystemLimitKey` + `DEFAULT_LIMITS`
--         artıq elan edilib (`src/domain/policies.py`); bu miqrasiya həmin
--         açarları `system_limits`-ə yazır ki, ROOT İdarə Mərkəzi ekranında
--         GÖRÜNSÜNLƏR.
--
--         Seed edilməyən açar "konfiqurasiya edilə bilən" görünər, faktiki
--         olaraq isə kodda oturan fallback işləyərdi — `tests/unit/
--         test_root_control_parameter_parity.py` bu boşluğu QAPIYA çevirib
--         (`migrations/036`/`039` ilə eyni əsaslandırma).
--
-- İdempotentdir. DOWN bloku faylın sonunda şərh içindədir.
-- MÖVCUD CƏDVƏLLƏRƏ TOXUNULMUR: nə sütun dəyişir, nə ad, nə tip.
--
-- ---------------------------------------------------------------------------
-- BU MİQRASİYA NİYƏ CƏDVƏL YARATMIR
-- ---------------------------------------------------------------------------
-- `annual_leave_balances` və `annual_leave_requests` ARTIQ `migrations/037`-də
-- qurulub (`UNIQUE (tenant_id, employee_id, year)`, `chk_annual_leave_balance_
-- not_negative`, `excl_annual_leave_no_overlap`); icazə flag-i
-- (`can_manage_leave_balances`) isə `038`-də. `037` başlığı ROOT
-- parametrlərini QƏSDƏN kənarda saxlayıb: "Tavan (carry-over maksimumu,
-- «istifadə et ya itir» tarixi) BURADA SAXLANILMIR — o, siyasətdir və ROOT
-- parametridir; DB yalnız absurd vəziyyəti kəsir."
-- Bu fayl həmin vədin yerinə yetirilməsidir.
--
-- ---------------------------------------------------------------------------
-- BU AÇARLAR GÜNDAXİLİ İCAZƏYƏ AİD DEYİL
-- ---------------------------------------------------------------------------
-- KompasOS-da üç ayrı mexanizm var və onların parametrləri qarışdırılmamalıdır:
--   * `MONTHLY_LEAVE_MINUTES_LIMIT` (240 dəq.) — STEP1/STEP2 GÜNDAXİLİ
--     icazənin aylıq DƏQİQƏ tavanı (`schema.sql` §24 seed-i);
--   * Shift Matrix istirahət günü — parametri yoxdur, plandır;
--   * `ANNUAL_LEAVE_*` (bu fayl) — GÜN əsaslı illik haqq.
-- Heç biri digərindən çıxılmır və bir-birini məhdudlaşdırmır.
--
-- ---------------------------------------------------------------------------
-- `min_value`/`max_value` HÜDUDLARININ ƏSASLANDIRMASI
-- ---------------------------------------------------------------------------
--   * BASE_ENTITLEMENT_DAYS 1–60 — ALT HÜDUD 0 OLA BİLMƏZ: sıfır baza haqq
--     BÜTÜN işçiləri məzuniyyətsiz qoyardı, yəni funksiyanı bir ədədlə
--     söndürərdi; söndürmənin düzgün yolu isə Feature Toggle-dır, hədd deyil.
--     Üst hüdud 60 — ildə iki aydan çox "illik məzuniyyət" praktikada haqq
--     deyil, ayrı bir status (uzunmüddətli məzuniyyət) deməkdir və o, bu
--     cədvəldə deyil.
--   * SENIORITY_PERIOD_YEARS 1–40 — ALT HÜDUD 1-dir, 0 DEYİL: sıfır dövr
--     sıfıra bölmə deməkdir (`floor(staj / dövr)`). Üst hüdud 40 — bir
--     əmək fəaliyyətinin praktik uzunluğu; ondan uzun dövr əlavəni
--     ÜMUMİYYƏTLƏ qazanılmaz edərdi və bu, gizli söndürmədir.
--   * SENIORITY_BONUS_DAYS 0–10 — ALT HÜDUD 0-dır VƏ QANUNİDİR: staj
--     əlavəsi olmayan şirkət real haldır və qaydanı sıfırla söndürmək
--     düzgün yoldur (burada sıfır heç nəyi çökdürmür, sadəcə əlavə vermir).
--   * SENIORITY_BONUS_MAX_DAYS 0–30 — tavan. 0 = əlavə tam söndürülüb.
--   * CARRYOVER_MAX_DAYS 0–60 — ALT HÜDUD 0-dır: "heç nə köçürülmür"
--     tamamilə qanuni siyasətdir ("istifadə et ya itir"in ən sərt forması).
--     Üst hüdud baza haqqın üst hüdudu ilə eynidir — bir illik haqqdan çox
--     köçürmə iki illik öhdəlik yığmaq deməkdir.
--   * CARRYOVER_DEADLINE_MONTH 1–12, _DAY 1–31 — təqvim sərhədləri. Ayın
--     uzunluğundan artıq gün nömrəsi KODDA həmin ayın son gününə sıxılır
--     (`AnnualLeavePolicy.carryover_deadline`), çünki `date(y, 2, 31)`
--     `ValueError` atardı və gecəlik iş HƏR GECƏ çökərdi.
--   * ACCRUAL_PERIOD — `TEXT`, hüdudsuz. Dəyər ədəd deyil, sıralanmış
--     siyahıdır (`ANNUAL`/`QUARTERLY`/`MONTHLY`) və `min/max` mətn üçün
--     mənasızdır. NAMƏLUM DƏYƏR SİSTEMİ ÇÖKDÜRMÜR: `AccrualPeriod.from_value`
--     `ANNUAL`-a düşür.
--   * ACCRUAL_RATE_DAYS_PER_PERIOD 0–31 — `0` SENTİNELDİR: "dərəcəni illik
--     haqqdan törət" deməkdir və defoltdur. Üst hüdud 31 — bir dövrə (ən
--     qısası bir ay) düşən gün sayı ayın uzunluğunu keçə bilməz.
--   * DAY_COUNT_MODE — `TEXT`, hüdudsuz (yuxarıdakı ilə eyni səbəb).
--     Naməlum dəyər `WORKING_DAYS`-ə düşür.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. ROOT PARAMETRLƏRİ — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada (CI iki dəfə tətbiq edir) Root-un
-- artıq dəyişdirdiyi dəyər ÜSTÜNDƏN YAZILMIR (`036`/`039` ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('ANNUAL_LEAVE_BASE_ENTITLEMENT_DAYS', '21.00', 'DECIMAL', '1', '60',
     'Bir təqvim ilində qazanılan BAZA illik məzuniyyət haqqı (gün). Defolt '
     'Azərbaycan Əmək Məcəlləsinin 21 təqvim günlük minimumudur. GÜNDAXİLİ '
     'icazə ilə (aylıq 240 dəqiqə) heç bir əlaqəsi yoxdur'),
    ('ANNUAL_LEAVE_SENIORITY_PERIOD_YEARS', '5', 'INTEGER', '1', '40',
     'Staj əlavəsinin dövrü (il). "Hər N ildə bir addım" qaydasının N-i — '
     'qaydanın FORMASI da konfiqurasiya edilir, yalnız nəticəsi yox'),
    ('ANNUAL_LEAVE_SENIORITY_BONUS_DAYS', '1.00', 'DECIMAL', '0', '10',
     'Hər tamamlanmış staj dövrünə düşən əlavə gün. `0` = staj əlavəsi '
     'yoxdur (tamamilə qanuni siyasət)'),
    ('ANNUAL_LEAVE_SENIORITY_BONUS_MAX_DAYS', '5.00', 'DECIMAL', '0', '30',
     'Staj əlavəsinin TAVANI (gün). Tavansız qayda 40 illik stajda haqqı '
     'ikiqat artırardı'),
    ('ANNUAL_LEAVE_CARRYOVER_MAX_DAYS', '5.00', 'DECIMAL', '0', '60',
     'Keçən ildən növbəti ilə köçürülə bilən maksimum gün. Tavanı aşan '
     'hissə İTİR — mənfi balans YARANMIR'),
    ('ANNUAL_LEAVE_CARRYOVER_DEADLINE_MONTH', '3', 'INTEGER', '1', '12',
     '"İstifadə et ya itir" son tarixinin AYI. Defolt mart — birinci rübün '
     'sonu'),
    ('ANNUAL_LEAVE_CARRYOVER_DEADLINE_DAY', '31', 'INTEGER', '1', '31',
     '"İstifadə et ya itir" son tarixinin GÜNÜ. Ayın uzunluğundan artıq '
     'nömrə həmin ayın son gününə sıxılır (fevralın 31-i → 28/29)'),
    ('ANNUAL_LEAVE_ACCRUAL_PERIOD', 'ANNUAL', 'TEXT', NULL, NULL,
     'Haqqın qazanılma dövrü: ANNUAL (ilin əvvəlində tam, işə qəbul '
     'tarixinə görə proporsional), QUARTERLY və ya MONTHLY (tamamlanmış '
     'dövr başına toplanır). Naməlum dəyər ANNUAL sayılır'),
    ('ANNUAL_LEAVE_ACCRUAL_RATE_DAYS_PER_PERIOD', '0.00', 'DECIMAL', '0', '31',
     'Bir accrual dövrünə düşən gün (dərəcə). `0` = AVTOMATİK: illik haqq ÷ '
     'dövr sayı — beləliklə baza haqq dəyişəndə dərəcə də özü uyğunlaşır'),
    ('ANNUAL_LEAVE_DAY_COUNT_MODE', 'WORKING_DAYS', 'TEXT', NULL, NULL,
     'Balansdan neçə gün çıxılır: WORKING_DAYS (Shift Matrix-də istirahət '
     'olmayan günlər — defolt) və ya CALENDAR_DAYS (aralıqdakı bütün '
     'günlər). Bayram günü ayrıca kataloqda deyil, Shift Matrix-də '
     'istirahət kimi işarələnir')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. ROOT PARAMETRLƏRİ — YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022/023/036/039-dakı naxış təkrarlanır.
CREATE OR REPLACE FUNCTION seed_annual_leave_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'ANNUAL_LEAVE_BASE_ENTITLEMENT_DAYS', '21.00', 'DECIMAL', '1', '60',
         'Baza illik məzuniyyət haqqı (gün)'),
        (NEW.tenant_id, 'ANNUAL_LEAVE_SENIORITY_PERIOD_YEARS', '5', 'INTEGER', '1', '40',
         'Staj əlavəsinin dövrü (il)'),
        (NEW.tenant_id, 'ANNUAL_LEAVE_SENIORITY_BONUS_DAYS', '1.00', 'DECIMAL', '0', '10',
         'Hər staj dövrünə düşən əlavə gün'),
        (NEW.tenant_id, 'ANNUAL_LEAVE_SENIORITY_BONUS_MAX_DAYS', '5.00', 'DECIMAL', '0', '30',
         'Staj əlavəsinin tavanı (gün)'),
        (NEW.tenant_id, 'ANNUAL_LEAVE_CARRYOVER_MAX_DAYS', '5.00', 'DECIMAL', '0', '60',
         'Növbəti ilə köçürülə bilən maksimum gün'),
        (NEW.tenant_id, 'ANNUAL_LEAVE_CARRYOVER_DEADLINE_MONTH', '3', 'INTEGER', '1', '12',
         '"İstifadə et ya itir" son tarixinin ayı'),
        (NEW.tenant_id, 'ANNUAL_LEAVE_CARRYOVER_DEADLINE_DAY', '31', 'INTEGER', '1', '31',
         '"İstifadə et ya itir" son tarixinin günü'),
        (NEW.tenant_id, 'ANNUAL_LEAVE_ACCRUAL_PERIOD', 'ANNUAL', 'TEXT', NULL, NULL,
         'Haqqın qazanılma dövrü (ANNUAL / QUARTERLY / MONTHLY)'),
        (NEW.tenant_id, 'ANNUAL_LEAVE_ACCRUAL_RATE_DAYS_PER_PERIOD', '0.00', 'DECIMAL', '0', '31',
         'Dövr başına gün (0 = illik haqq ÷ dövr sayı)'),
        (NEW.tenant_id, 'ANNUAL_LEAVE_DAY_COUNT_MODE', 'WORKING_DAYS', 'TEXT', NULL, NULL,
         'Gün sayma rejimi (WORKING_DAYS / CALENDAR_DAYS)')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_annual_leave_limits_for_new_tenant() IS
    'Yeni kirayəçiyə illik məzuniyyətin on ROOT parametrini əlavə edir '
    '(migrations/040). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_annual_leave_limits ON license_tenants;
CREATE TRIGGER trg_seed_annual_leave_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_annual_leave_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlər silinsə, illik məzuniyyət İŞLƏMƏYƏ DAVAM EDİR — kod
-- `DEFAULT_LIMITS` fallback-ına düşür (21 gün / 5 il / 1 gün / 5 gün tavan /
-- 5 gün köçürmə / 31 mart / ANNUAL / avtomatik dərəcə / WORKING_DAYS).
-- İtən yeganə şey Root-un GUI-dan dəyişdirmə imkanıdır.
-- `migrations/037`-dəki cədvəllərə və `038`-dəki flag-ə TOXUNULMUR.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_annual_leave_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_annual_leave_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'ANNUAL_LEAVE_BASE_ENTITLEMENT_DAYS',
--       'ANNUAL_LEAVE_SENIORITY_PERIOD_YEARS',
--       'ANNUAL_LEAVE_SENIORITY_BONUS_DAYS',
--       'ANNUAL_LEAVE_SENIORITY_BONUS_MAX_DAYS',
--       'ANNUAL_LEAVE_CARRYOVER_MAX_DAYS',
--       'ANNUAL_LEAVE_CARRYOVER_DEADLINE_MONTH',
--       'ANNUAL_LEAVE_CARRYOVER_DEADLINE_DAY',
--       'ANNUAL_LEAVE_ACCRUAL_PERIOD',
--       'ANNUAL_LEAVE_ACCRUAL_RATE_DAYS_PER_PERIOD',
--       'ANNUAL_LEAVE_DAY_COUNT_MODE');
-- COMMIT;
