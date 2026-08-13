-- ===========================================================================
-- 035 — TƏQDİMAT QATININ ƏMƏLİYYAT PARAMETRLƏRİNİN ROOT-A KÖÇÜRÜLMƏSİ
-- ===========================================================================
-- Tarix : 2026-08-13
-- Səbəb : Faza 10.2-nin ikinci dalğası `src/presentation/` və
--         `src/developer_panel/` altında beş hardcode dəyər tapdı: növbə
--         matrisinin pəncərəsi, sübut yükləmə dövrəsinin ritmi, «zəif
--         uyğunluq» rəng həddi və Developer Panelindəki iki cədvəlin sətir
--         tavanı. CLAUDE.md §5-ə görə struktur təhlükəsizlik zəmanəti
--         OLMAYAN hər sabitin yeri `system_limits`-dədir.
--         `SystemLimitKey` + `DEFAULT_LIMITS` (src/domain/policies.py)
--         açarları artıq elan edir — bu miqrasiya onları SEED edir ki, ROOT
--         İdarə Mərkəzi ekranında GÖRÜNSÜNLƏR və Root-un dəyişikliyi DB-də
--         qalsın (migrations/022–034 ilə EYNİ naxış).
--
-- Bu miqrasiya YALNIZ SƏTİR əlavə edir: heç bir cədvəl, sütun, indeks və ya
-- məhdudiyyət yaradılmır, dəyişdirilmir, silinmir.
--
-- İdempotentdir — `ON CONFLICT DO NOTHING` ilə iki dəfə icra edilə bilər.
-- DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- DAVRANIŞ DƏYİŞMİR
-- ---------------------------------------------------------------------------
-- Hər `limit_value` köçürülən hardcode dəyərlə eynidir; yeganə çevrilmə
-- `EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS`-dədir: kodda 120_000 MİLLİSANİYƏ
-- yazılmışdı, açar isə SANİYƏ ilədir (120 san = 120_000 ms — eyni ritm).
-- Vahid qəsdən dəyişdirilib: `NOTIFY_POLL_INTERVAL_SECONDS` və
-- `REALTIME_POLL_INTERVAL_SECONDS` artıq saniyə ilədir və Root eyni panelde
-- iki fərqli vahidlə üzləşməməlidir — millisaniyəlik sahə "120000" yazıb
-- "2 dəqiqə" düşünməyi tələb edərdi.
--
-- ---------------------------------------------------------------------------
-- `min_value`/`max_value` NİYƏ MƏHZ BUNLARDIR
-- ---------------------------------------------------------------------------
-- * `SHIFT_MATRIX_WINDOW_DAYS` 1–120: `0` matrisi SÜTUNSUZ qoyardı (ekran
--   boş görünər, səbəbi görünməzdi); 120-dən uzun pəncərə isə bir ekrana
--   sığmayan üfüqi sürüşmə deməkdir.
-- * `EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS` 10–3600: `0` taymeri fasiləsiz
--   işə salardı (hər dövrə DB sessiyası açır) — aşağı hüdud məhz buna görə
--   var. `NOTIFY_POLL_INTERVAL_SECONDS` ilə eyni tavan (1 saat).
-- * `ERP_MATCH_LOW_CONFIDENCE_PERCENT` 0–100: faizdir, təbii hüdudları var.
--   `0` = heç bir sətir xəbərdarlıq rəngində DEYİL, `100` = hamısı — hər ikisi
--   mənalı seçimdir (operator komandası rəngi tamamilə söndürə bilər).
-- * `DEVELOPER_*_ROW_LIMIT` 1–200: `0` cədvəli həmişə boş göstərərdi və
--   "müraciət yoxdur" ilə "tavan sıfırdır" fərqi itərdi.
--
-- ---------------------------------------------------------------------------
-- BU MİQRASİYAYA GİRMƏYƏNLƏR (QƏSDƏN HARDCODE — DİZAYN DƏYƏRLƏRİ)
-- ---------------------------------------------------------------------------
-- * `SPLASH_DURATION_MS`, `LOADING_DELAY_MS`, animasiya müddətləri, piksel və
--   ölçü sabitləri (`widgets/metrics.py`) — bunlar dizayn sistemidir, siyasət
--   deyil; Root-dan dəyişdirilməsi interfeysin bütövlüyünü pozardı.
-- * `drive_connection.POLL_INTERVAL_MS` — LOKAL soket yoxlama sürəti
--   (razılıq axını), şəbəkədən asılı deyil.
-- * `scripts/check_contrast.py`-dəki WCAG riyazi sabitləri — standartdır.
-- * Anti-fraud vəzifə ayrılığı, SEC-001, Strict Hierarchy / Self-Escalation
--   Guard, dörd-səviyyəli `HardlockLevel` (CLAUDE.md §5).
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada Root-un artıq dəyişdirdiyi dəyər
-- ÜSTÜNDƏN YAZILMIR (013/017/018/022–034 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('SHIFT_MATRIX_WINDOW_DAYS', '14', 'INTEGER', '1', '120',
     'Növbə matrisinin göstərdiyi gün sayı'),
    ('EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS', '120', 'INTEGER', '10', '3600',
     'Sübut şəkli növbəsinin fon dövrəsi (saniyə)'),
    ('ERP_MATCH_LOW_CONFIDENCE_PERCENT', '50', 'INTEGER', '0', '100',
     'Bu faizdən aşağı uyğunluq «zəif» sayılır və xəbərdarlıq rəngi alır'),
    ('DEVELOPER_CRASH_ROW_LIMIT', '12', 'INTEGER', '1', '200',
     'Developer Panelindəki çökmə cədvəlinin sətir tavanı'),
    ('DEVELOPER_TICKET_ROW_LIMIT', '12', 'INTEGER', '1', '200',
     'Developer Panelindəki dəstək cədvəlinin sətir tavanı')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022–034 naxışı təkrarlanır: yeni kirayəçi yarananda
-- həmin sətirləri əlavə edən AYRICA trigger.
--
-- Sətirlər 1-ci bölmədəki `VALUES` siyahısından TƏKRAR OXUNUR (eyni mətn iki
-- yerdə): funksiya gövdəsi `$$` içindədir və `INSERT ... SELECT ... FROM
-- license_tenants` naxışını orada işlətmək YENİ kirayəçi üçün BÜTÜN
-- kirayəçilərə sətir yazardı.
CREATE OR REPLACE FUNCTION seed_presentation_runtime_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    SELECT NEW.tenant_id, v.limit_key, v.limit_value, v.value_type,
           v.min_value, v.max_value, v.description_az
      FROM (VALUES
        ('SHIFT_MATRIX_WINDOW_DAYS', '14', 'INTEGER', '1', '120',
         'Növbə matrisinin göstərdiyi gün sayı'),
        ('EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS', '120', 'INTEGER', '10', '3600',
         'Sübut şəkli növbəsinin fon dövrəsi (saniyə)'),
        ('ERP_MATCH_LOW_CONFIDENCE_PERCENT', '50', 'INTEGER', '0', '100',
         'Bu faizdən aşağı uyğunluq «zəif» sayılır və xəbərdarlıq rəngi alır'),
        ('DEVELOPER_CRASH_ROW_LIMIT', '12', 'INTEGER', '1', '200',
         'Developer Panelindəki çökmə cədvəlinin sətir tavanı'),
        ('DEVELOPER_TICKET_ROW_LIMIT', '12', 'INTEGER', '1', '200',
         'Developer Panelindəki dəstək cədvəlinin sətir tavanı')
      ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_presentation_runtime_limits_for_new_tenant() IS
    'Yeni kirayəçiyə Faza 10.2-nin beş təqdimat-qatı ROOT parametrini əlavə '
    'edir (migrations/035). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_presentation_runtime_limits ON license_tenants;
CREATE TRIGGER trg_seed_presentation_runtime_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_presentation_runtime_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlərin silinməsi parametrləri ROOT ekranından yox edir; ekranlar
-- İŞLƏMƏYƏ DAVAM EDİR, lakin `DEFAULT_LIMITS` fallback-ları ilə
-- (src/domain/policies.py) — yəni Root onları artıq dəyişdirə bilmir.
-- Davranış dəyişmir, çünki fallback dəyərləri seed dəyərləri ilə eynidir.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_presentation_runtime_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_presentation_runtime_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'SHIFT_MATRIX_WINDOW_DAYS',
--       'EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS',
--       'ERP_MATCH_LOW_CONFIDENCE_PERCENT',
--       'DEVELOPER_CRASH_ROW_LIMIT',
--       'DEVELOPER_TICKET_ROW_LIMIT'
--   );
-- COMMIT;
