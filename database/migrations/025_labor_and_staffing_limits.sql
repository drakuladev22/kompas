-- ===========================================================================
-- 025 — #14 ƏMƏK QANUNU VƏ #13 TARİXİ NÜMUNƏ TƏKLİFİNİN ROOT PARAMETRLƏRİ
-- ===========================================================================
-- Tarix : 2026-08-12
-- Səbəb : Faza 6 (kompasos11.md) İKİ köməkçi funksiya qurur:
--           #14 — əmək qanunu xəbərdarlığı (min istirahət, məcburi fasilə,
--                 max ardıcıl iş günü) — BLOKLAMIR, yalnız xəbərdarlıq;
--           #13 — tarixi-nümunə əsaslı kadr təklifi (son N həftə).
--         Hər iki funksiyanın bütün ədədi həddi MƏRKƏZİ TƏLƏBƏ görə ROOT-dan
--         idarə olunur. `SystemLimitKey` + `DEFAULT_LIMITS`
--         (src/domain/policies.py) onları artıq elan edir — bu miqrasiya
--         həmin açarları `system_limits`-ə SEED edir ki, ROOT İdarə Mərkəzi
--         ekranında GÖRÜNSÜNLƏR (miqrasiya 022/023/024 ilə EYNİ naxış).
--
-- Bu miqrasiya YALNIZ SƏTİR əlavə edir: heç bir cədvəl, sütun və ya
-- məhdudiyyət yaradılmır, dəyişdirilmir, silinmir.
-- `staffing_pattern_suggestions` cədvəlinin ÖZÜ artıq migrations/019-dadır.
--
-- İdempotentdir — `ON CONFLICT DO NOTHING` ilə iki dəfə icra edilə bilər.
-- DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ SEED LAZIMDIR — `DEFAULT_LIMITS` NİYƏ KİFAYƏT ETMİR
-- ---------------------------------------------------------------------------
-- Kod tərəfi `SystemLimits.get_int(tenant, key, default)` işlədir, yəni sətir
-- olmasa da qayda DOĞRU dəyərlə işləyir — funksional qüsur YOXDUR. Lakin ROOT
-- paneli `describe()` ilə `system_limits` cədvəlini oxuyur: seed edilməmiş
-- açar orada ÜMUMİYYƏTLƏ görünmür və Root onu dəyişə bilmir. Yəni parametr
-- "konfiqurasiya edilə bilən" olmaqdan çıxıb sükutla sabitə çevrilərdi
-- (miqrasiya 022/023/024 eyni boşluğu bağlamışdı).
--
-- ---------------------------------------------------------------------------
-- ƏMƏK HÜQUQU QEYDİ — DEFOLTLAR MƏSLƏHƏT DEYİL
-- ---------------------------------------------------------------------------
-- Aşağıdakı dəyərlər layihənin BAŞLANĞIC dəyərləridir, hüquqi rəy deyil.
-- Qaydaların özü onsuz da BLOKLAMIR — nəticə yalnız admin ekranındakı
-- xəbərdarlıq mətnidir. Müəssisə öz hüquqşünasının göstərişinə görə hər dörd
-- həddi ROOT panelindən dəyişir; kod dəyişikliyi TƏLƏB OLUNMUR.
--
-- ---------------------------------------------------------------------------
-- `min_value` / `max_value` NİYƏ BU HÜDUDLARDADIR
-- ---------------------------------------------------------------------------
--   * LABOR_MIN_REST_HOURS (0–24): 0 = QAYDA SUSUR (Root bu bir qaydanı
--     söndürmək üçün ayrıca modul açarına ehtiyac duymamalıdır); 24-dən çox
--     "istirahət" gündəlik növbə anlayışının özünü mənasızlaşdırardı.
--   * LABOR_MANDATORY_BREAK_MINUTES (0–240): 0 = qayda susur; 240 (4 saat)
--     TAVANDIR — ondan yuxarısı fasilə deyil, iki ayrı növbə deməkdir.
--   * LABOR_BREAK_REQUIRED_AFTER_HOURS (0–24): 0 = qayda susur. Praktikada
--     4-dən aşağı hədd demək olar ki, HƏR növbədə xəbərdarlıq verər və kanal
--     dəyərini itirər — lakin bu, seçim məsələsidir, sxem qadağası deyil.
--   * LABOR_MAX_CONSECUTIVE_WORK_DAYS (0–31): 0 = qayda susur; 31 bir ayın
--     maksimum uzunluğudur — ondan artıq "ardıcıl gün" saymağın praktik
--     mənası yoxdur.
--   * STAFFING_PATTERN_BASED_ON_WEEKS (2–52): 1 həftə "nümunə" deyil, TƏK
--     müşahidədir (hər həftə günü üçün cəmi bir gün) — ona görə minimum 2;
--     52 (bir il) tavandır, ondan uzun pəncərə keçən ilin kadr tərkibini
--     bugünkü ilə qarışdırardı. DİQQƏT: `staffing_pattern_suggestions.
--     based_on_weeks` sütununda `CHECK (> 0)` var, yəni 0 BURADA DA qadağandır
--     — "qayda sussun" halı digər dördündən fərqli olaraq bu açarda YOXDUR,
--     çünki təklif onsuz da heç nə bloklamır: söndürməyə ehtiyac yaranmır.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada Root-un artıq dəyişdirdiyi dəyər
-- ÜSTÜNDƏN YAZILMIR (013/017/018/022/023/024 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('LABOR_MIN_REST_HOURS', '12', 'INTEGER', '0', '24',
     '#14 — İki ardıcıl növbə arasında minimum istirahət (saat). 0 = qayda '
     'susur. Gecə növbəsi nəzərə alınır: hesablama növbənin bitmə ANINDAN '
     'aparılır'),
    ('LABOR_MANDATORY_BREAK_MINUTES', '60', 'INTEGER', '0', '240',
     '#14 — Uzun növbədə nəzərdə tutulmalı fasilənin müddəti (dəqiqə). '
     '0 = qayda susur'),
    ('LABOR_BREAK_REQUIRED_AFTER_HOURS', '6', 'INTEGER', '0', '24',
     '#14 — Neçə saatdan uzun növbədə fasilə məcburi sayılsın. 0 = qayda susur'),
    ('LABOR_MAX_CONSECUTIVE_WORK_DAYS', '6', 'INTEGER', '0', '31',
     '#14 — İstirahət günü olmadan ardıcıl neçə gün işləmək olar. '
     '0 = qayda susur'),
    ('STAFFING_PATTERN_BASED_ON_WEEKS', '8', 'INTEGER', '2', '52',
     '#13 — Kadr təklifi neçə həftəlik tarixçəyə baxsın (yalnız KompasOS '
     'davamiyyət datası — 1C satış həcmi İŞLƏDİLMİR)')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022/023/024-dəki naxış təkrarlanır: yeni kirayəçi
-- yarananda bu beş sətri əlavə edən AYRICA trigger.
CREATE OR REPLACE FUNCTION seed_labor_and_staffing_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'LABOR_MIN_REST_HOURS', '12', 'INTEGER', '0', '24',
         '#14 — İki ardıcıl növbə arasında minimum istirahət (saat). '
         '0 = qayda susur'),
        (NEW.tenant_id, 'LABOR_MANDATORY_BREAK_MINUTES', '60', 'INTEGER', '0', '240',
         '#14 — Uzun növbədə nəzərdə tutulmalı fasilənin müddəti (dəqiqə). '
         '0 = qayda susur'),
        (NEW.tenant_id, 'LABOR_BREAK_REQUIRED_AFTER_HOURS', '6', 'INTEGER', '0', '24',
         '#14 — Neçə saatdan uzun növbədə fasilə məcburi sayılsın. '
         '0 = qayda susur'),
        (NEW.tenant_id, 'LABOR_MAX_CONSECUTIVE_WORK_DAYS', '6', 'INTEGER', '0', '31',
         '#14 — İstirahət günü olmadan ardıcıl neçə gün işləmək olar. '
         '0 = qayda susur'),
        (NEW.tenant_id, 'STAFFING_PATTERN_BASED_ON_WEEKS', '8', 'INTEGER', '2', '52',
         '#13 — Kadr təklifi neçə həftəlik tarixçəyə baxsın (yalnız KompasOS '
         'davamiyyət datası)')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_labor_and_staffing_limits_for_new_tenant() IS
    'Yeni kirayəçiyə #14 əmək qanunu xəbərdarlığının dörd və #13 kadr '
    'təklifinin bir ROOT parametrini əlavə edir (migrations/025). '
    '`seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_labor_and_staffing_limits ON license_tenants;
CREATE TRIGGER trg_seed_labor_and_staffing_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_labor_and_staffing_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlərin silinməsi parametrləri ROOT ekranından yox edir;
-- qaydalar işləməyə davam edir, lakin `DEFAULT_LIMITS` dəyərləri ilə — yəni
-- Root onları artıq dəyişdirə bilmir. Növbə təyinatı və kadr təklifi
-- funksional olaraq POZULMUR.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_labor_and_staffing_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_labor_and_staffing_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'LABOR_MIN_REST_HOURS', 'LABOR_MANDATORY_BREAK_MINUTES',
--       'LABOR_BREAK_REQUIRED_AFTER_HOURS', 'LABOR_MAX_CONSECUTIVE_WORK_DAYS',
--       'STAFFING_PATTERN_BASED_ON_WEEKS'
--   );
-- COMMIT;
