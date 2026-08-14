-- ===========================================================================
-- 044 — EXPORT TƏCRÜBƏSİNİN ROOT PARAMETRLƏRİ (kompas1.md Faza 8)
-- ===========================================================================
-- Tarix : 2026-08-13
-- Səbəb : Faza 8 export ekranına dörd yeni davranış əlavə edir —
--         pre-export doğrulama (A), manual düzəliş (D), dövr-üzrə müqayisə (F)
--         və rol filtri (G). Onlardan üçünün ARXASINDA konfiqurasiya edilə
--         bilən ədəd durur; dördüncüsü (rol filtri) heç bir hədd tələb etmir,
--         çünki siyahı `positions` KATALOQUNDAN oxunur.
--
--         `SystemLimitKey` + `DEFAULT_LIMITS` artıq elan edilib
--         (`src/domain/policies.py`); bu miqrasiya həmin dörd açarı
--         `system_limits`-ə yazır ki, ROOT İdarə Mərkəzi ekranında GÖRÜNSÜN
--         və dəyişdirilə bilsin.
--
--         Seed edilməyən açar "konfiqurasiya edilə bilən" görünər, faktiki
--         olaraq isə kodda oturan fallback işləyərdi — `tests/unit/
--         test_root_control_parameter_parity.py` bu boşluğu QAPIYA çevirib
--         (`migrations/039`–`043` ilə eyni əsaslandırma).
--
-- İdempotentdir. DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- MÖVCUD CƏDVƏLLƏRƏ TOXUNULMUR — BU MİQRASİYA SIRF `system_limits` SEED-İDİR
-- ---------------------------------------------------------------------------
--   * `export_manual_corrections` (migrations/037 §10) DƏYİŞMİR: nə sütun,
--     nə CHECK, nə indeks. Faza 8 həmin cədvəli OLDUĞU KİMİ işlədir —
--     `export_type`/`field` sərbəst mətndir və yeni export növü/sütunu
--     miqrasiya tələb etmir (037-nin öz qərarı).
--   * `reason` sütununun `char_length(trim(reason)) >= 10` CHECK-i də
--     DƏYİŞMİR. Aşağıdakı `EXPORT_CORRECTION_REASON_MIN_LENGTH` onu ƏVƏZ
--     ETMİR, ÜSTÜNƏ QOYULUR: DB-dəki 10 ABSURD cavabı ("ok", ".") kəsən
--     DÖŞƏMƏDİR, ROOT dəyəri isə SİYASƏTDİR. Ona görə `min_value = '10'` —
--     Root onu döşəmədən AŞAĞI sala bilməz, əks halda GUI qəbul edər, `INSERT`
--     isə DB CHECK-inə dəyib xəta verərdi və HR "səbəb yazdım, yenə qəbul
--     etmir" vəziyyətində qalardı.
--   * `fines.exported_period` və `work_modes` — TOXUNULMUR (043 ilə eyni).
--
-- ---------------------------------------------------------------------------
-- `min_value`/`max_value` HÜDUDLARININ ƏSASLANDIRMASI
-- ---------------------------------------------------------------------------
-- EXPORT_STORE_ABSENCE_ANOMALY_PCT (DECIMAL, defolt 15.0)
--   * min = 0.1 — 0 HƏR mağazanı işarələyərdi (nisbət həmişə > 0 olardı) və
--     doğrulama ekranı ilk gündən yararsız olardı. Mənfi dəyər isə mənasızdır.
--   * max = 100 — nisbətin özü qayıb ÷ norma gün olduğu üçün 100%-dən yuxarı
--     hədd heç vaxt işə düşməzdi (yəni qaydanı SÜKUTLA söndürərdi). Söndürmək
--     istəyən Root 100 yazır — bu, AÇIQ və oxunan seçimdir.
--
-- EXPORT_STORE_ANOMALY_MIN_EMPLOYEES (INTEGER, defolt 3)
--   * min = 1 — bir nəfərlik filialı da yoxlamaq İSTƏYƏN müəssisə olacaq;
--     0 isə "işçisi olmayan mağaza" deməkdir, mənasızdır.
--   * max = 100 — bir mağazanın praktik heyət tavanı. Daha böyük dəyər qaydanı
--     bütün şəbəkədə söndürərdi, halbuki söndürmənin AÇIQ yolu yuxarıdakı
--     faizdir.
--
-- EXPORT_PERIOD_DELTA_SIGNIFICANT (INTEGER, defolt 3)
--   * min = 1 — 0 hər dövrü "əhəmiyyətli fərq" elan edərdi, hətta 0 fərqi.
--   * max = 1000 — 21 filialın aylıq qayıb sayı praktikada üç rəqəmi keçmir;
--     tavan yalnız yazı səhvini (məs. 30000) kəsir.
--
-- EXPORT_CORRECTION_REASON_MIN_LENGTH (INTEGER, defolt 10)
--   * min = 10 — DB CHECK-inin döşəməsi (yuxarı bax).
--   * max = 500 — `reason` `TEXT`-dir, lakin 500 simvoldan uzun MƏCBURİ izah
--     düzəlişi praktikada mümkünsüz edərdi (HR onun əvəzinə heç düzəltməzdi —
--     yəni sərtlik öz məqsədinin əksinə işləyərdi).
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. ROOT PARAMETRLƏRİ — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada (CI iki dəfə tətbiq edir) Root-un
-- artıq dəyişdirdiyi dəyər ÜSTÜNDƏN YAZILMIR (039–043 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('EXPORT_STORE_ABSENCE_ANOMALY_PCT', '15.0', 'DECIMAL', '0.1', '100',
     'Pre-export doğrulamasında mağazanı «anomal yüksək icazəsiz-qayıb» kimi '
     'işarələyən hədd (faiz). Nisbət: mağazanın icazəsiz qayıb sayı ÷ '
     'planlaşdırılmış norma günü. İşçi sayına bölmə QƏSDƏN seçilmədi — yarım-'
     'ştat heyəti çox olan mağazanı həmişə pis göstərərdi. Hədd aşılanda '
     'export BLOKLANMIR: HR xəbərdarlığı görüb «Təsdiqlə və Export Et» ilə '
     'davam edir'),
    ('EXPORT_STORE_ANOMALY_MIN_EMPLOYEES', '3', 'INTEGER', '1', '100',
     'Mağaza anomaliyasının hesablanması üçün minimum işçi sayı. Bundan az '
     'işçisi olan mağaza yoxlanmır: bir nəfərlik filialda tək qayıb nisbəti '
     'faizi 100-ə qaldırır və qayda hər ay yalançı siqnal verərdi'),
    ('EXPORT_PERIOD_DELTA_SIGNIFICANT', '3', 'INTEGER', '1', '1000',
     'Dövr-üzrə müqayisədə «əhəmiyyətli fərq» sayılan mütləq hədd. Keçən '
     'EYNİ-UZUNLUQDA dövrlə fərq bu qiymətə çatarsa ekranda vurğulanır '
     '(məs. «icazəsiz qayıb: +3»). Hədd olmasa hər ±1 dalğalanma vurğulanar '
     've HR vurğuları görməzdən gəlməyə öyrəşərdi'),
    ('EXPORT_CORRECTION_REASON_MIN_LENGTH', '10', 'INTEGER', '10', '500',
     'Manual export düzəlişində səbəb sahəsinin minimum uzunluğu. '
     '`export_manual_corrections.reason` CHECK-i (>= 10) DÖŞƏMƏDİR — bu '
     'parametr onun ÜSTÜNDƏ siyasətdir və audit tələbi sərtləşəndə miqrasiya '
     'gözləmədən artırıla bilər. Döşəmədən aşağı düşmək mümkün deyil')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. ROOT PARAMETRLƏRİ — YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/036/039–043-dəki naxış təkrarlanır.
CREATE OR REPLACE FUNCTION seed_export_preflight_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'EXPORT_STORE_ABSENCE_ANOMALY_PCT', '15.0', 'DECIMAL', '0.1', '100',
         'Mağaza üzrə anomal icazəsiz-qayıb həddi (faiz)'),
        (NEW.tenant_id, 'EXPORT_STORE_ANOMALY_MIN_EMPLOYEES', '3', 'INTEGER', '1', '100',
         'Mağaza anomaliyası üçün minimum işçi sayı'),
        (NEW.tenant_id, 'EXPORT_PERIOD_DELTA_SIGNIFICANT', '3', 'INTEGER', '1', '1000',
         'Dövr-üzrə müqayisədə əhəmiyyətli fərq həddi'),
        (NEW.tenant_id, 'EXPORT_CORRECTION_REASON_MIN_LENGTH', '10', 'INTEGER', '10', '500',
         'Manual export düzəlişində səbəbin minimum uzunluğu')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_export_preflight_limits_for_new_tenant() IS
    'Yeni kirayəçiyə export təcrübəsinin dörd ROOT parametrini əlavə edir '
    '(migrations/044). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_export_preflight_limits ON license_tenants;
CREATE TRIGGER trg_seed_export_preflight_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_export_preflight_limits_for_new_tenant();

-- ---------------------------------------------------------------------------
-- 3. SÜTUN ŞƏRHİNİN GENİŞLƏNMƏSİ — `export_manual_corrections.field`
-- ---------------------------------------------------------------------------
-- Sütunun ÖZÜ dəyişmir (yenə sərbəst `TEXT`), lakin İSTİFADƏSİ konkretləşir:
-- Faza 8 kodu yalnız `CORRECTABLE_FIELDS` kataloqundakı beş açarı qəbul edir
-- (`src/domain/value_objects/export_corrections.py`). Sxemə `CHECK` ƏLAVƏ
-- EDİLMİR — 037-nin qərarı qüvvədə qalır: yeni export sütunu miqrasiya tələb
-- etməməlidir; qapı KODDADIR, çünki tanınmayan sahə heç bir Excel sütununa
-- düşməz və "düzəldilib, amma rəqəm dəyişməyib" halı yaradardı.
COMMENT ON COLUMN export_manual_corrections.field IS
    'Düzəldilən sahənin adı (export sütunu) — hansı rəqəmin dəyişdiyi. '
    'Faza 8-dən etibarən tətbiq qatının qəbul etdiyi açarlar: NORMA_GUN, '
    'FAKTIKI_GUN, OFF_DAY, ICAZESIZ_QAYIB (ədədi — export rəqəminə TƏTBİQ '
    'olunur) və QEYD (sərbəst mətn — Excel-in «Qeyd» sütununu doldurur, '
    'rəqəmə toxunmur). Siyahı sxemdə CHECK kimi SƏRTLƏŞDİRİLMİR: yeni export '
    'sütunu miqrasiya tələb etməməlidir.';

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlər silinsə, export ekranı İŞLƏMƏYƏ DAVAM EDİR — kod
-- `DEFAULT_LIMITS` fallback-larına düşür (15.0 / 3 / 3 / 10). İtən yeganə şey
-- Root-un GUI-dan həddləri dəyişdirmə imkanıdır.
--
-- `export_manual_corrections` cədvəlinə TOXUNULMUR: orada real audit sətirləri
-- var və onlar "kim tabeli əl ilə dəyişdi?" sualının YEGANƏ struktur cavabıdır
-- (migrations/037 DOWN blokundakı eyni xəbərdarlıq).
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_export_preflight_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_export_preflight_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'EXPORT_STORE_ABSENCE_ANOMALY_PCT',
--       'EXPORT_STORE_ANOMALY_MIN_EMPLOYEES',
--       'EXPORT_PERIOD_DELTA_SIGNIFICANT',
--       'EXPORT_CORRECTION_REASON_MIN_LENGTH');
-- COMMIT;
