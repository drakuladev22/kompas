-- ===========================================================================
-- 034 — TƏTBİQ QATININ (application) ROOT PARAMETRLƏRİ (Faza 10.2, 2-ci dalğa)
-- ===========================================================================
-- Tarix : 2026-08-13
-- Səbəb : `src/application/use_cases/` altında 15 ədəd SABİT kimi yaşayırdı:
--         dəstək müraciətinin iki SLA hədəfi və "risk altında" zolağı, çökmə
--         panelinin kütləvilik həddi və siyahı uzunluğu, növbə dəyişmə
--         pəncərəsi, lisenziya ödənişi xatırlatma cədvəli, altı ekranın
--         səhifə ölçüsü və quraşdırma sihirbazının admin tövsiyəsi.
--
--         CLAUDE.md §5: struktur təhlükəsizlik zəmanətlərindən (anti-fraud
--         vəzifə ayrılığı, SEC-001, Strict Hierarchy / Self-Escalation Guard,
--         dörd-səviyyəli `HardlockLevel`) KƏNARDA qalan hər sabitin yeri
--         `system_limits`-dədir. Bu 15 dəyərin heç biri həmin siyahıda deyil:
--         hamısı ya xidmət səviyyəsi öhdəliyi, ya ekran həcmi, ya da bloklamayan
--         tövsiyədir.
--
--         `SystemLimitKey` + `DEFAULT_LIMITS` (src/domain/policies.py) artıq
--         açarları elan edir; bu miqrasiya onları `system_limits`-ə SEED edir
--         ki, ROOT İdarə Mərkəzi ekranında GÖRÜNSÜNLƏR və hər dəyişiklik
--         `SYSTEM_LIMIT_CHANGED` audit yazısı ilə izlənsin (migrations/
--         022–033 ilə EYNİ naxış).
--
-- Bu miqrasiya YALNIZ SƏTİR əlavə edir: heç bir cədvəl, sütun, indeks, enum
-- və ya məhdudiyyət yaradılmır, dəyişdirilmir, silinmir.
--
-- İdempotentdir — `ON CONFLICT DO NOTHING` ilə iki dəfə icra edilə bilər.
-- DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- HƏR DEFOLT KÖHNƏ HARDCODE İLƏ HƏRFƏN EYNİDİR
-- ---------------------------------------------------------------------------
-- 24/72 saat SLA, 0.75 zolaq, 3 quraşdırma, 10 sətir, 90 gün, "-7,-3,-1,1,7",
-- 200/500/100/60/50/20/100 səhifə, 2 admin. Defoltu "yaxşılaşdırsaydıq",
-- mövcud quraşdırma yenilənmədən sonra sükutla başqa cür işləyərdi və səbəbi
-- heç bir jurnalda görünməzdi.
--
-- ---------------------------------------------------------------------------
-- NİYƏ HƏR SƏHİFƏ ÖLÇÜSÜNÜN AŞAĞI HÜDUDU 1-dir
-- ---------------------------------------------------------------------------
-- `0` yazılsa siyahı HƏMİŞƏ boş qayıdardı və istifadəçi "məlumat yoxdur" ilə
-- "limit sıfırdır" arasındakı fərqi heç bir ekranda görə bilməzdi — nasazlığın
-- ən pis növü, çünki loga heç bir xəta düşmür. Kod eyni aralığı `APP_LIMIT_
-- BOUNDS`-da (src/application/root_limits.py) təkrarlayır və oxunan dəyəri ona
-- KLAMP edir; `tests/unit/test_application_root_limits.py` iki mənbənin
-- pariteti üçün qapıdır (ayrılsalar, ROOT ekranı "qəbul edilən" göstərən dəyəri
-- kod sükutla kəsərdi).
--
-- ---------------------------------------------------------------------------
-- ÜÇ SƏRT ARALIQ — NİYƏ MƏHZ BUNLAR
-- ---------------------------------------------------------------------------
-- 1. `SUPPORT_SLA_AT_RISK_RATIO` (0.10–0.99). 1.00 yazılsaydı "risk altında"
--    zolağı SIFIR enli olardı və vəziyyət `ON_TRACK`-dən birbaşa `BREACHED`-ə
--    keçərdi — yəni xəbərdarlıq mərhələsi faktiki söndürülərdi, halbuki
--    `developer_console` başlığı onu açıq tələb kimi yazır.
-- 2. `CRASH_WIDESPREAD_INSTALLATION_THRESHOLD` (2–1000). Aşağı hüdud 2-dir:
--    1 yazılsaydı HƏR çökmə "kütləvi" nişanı alardı və panel prioritetləşdirmə
--    dəyərini itirərdi (nişanın bütün mənası "lokal problem ≠ kod problemi"
--    ayrımıdır).
-- 3. `SETUP_RECOMMENDED_ADMIN_COUNT` (1–20). Sıfır tövsiyə ilə sihirbaz heç
--    vaxt xəbərdarlıq göstərməzdi və "tək hesab bloklanarsa sistemə heç kim
--    girə bilməyəcək" riski (bölmə 2) sükutla görünməz qalardı.
--
-- ---------------------------------------------------------------------------
-- `LICENSE_PAYMENT_REMINDER_OFFSET_DAYS` NİYƏ `TEXT`-dir
-- ---------------------------------------------------------------------------
-- Cədvəlin elementləri MƏNFİ ola bilər (T-7 = bitmədən yeddi gün əvvəl), yəni
-- `min_value`/`max_value` mənasızdır — hər hansı ədədi aralıq mənfi mərhələləri
-- sükutla kəsərdi. Beş ayrı açar da RƏDD EDİLDİ: mərhələlər BİRGƏ bir cədvəl
-- təşkil edir və ayrı açarlarda Root onları yanlış sıraya yaza bilərdi
-- (`EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS`, migrations/028 ilə eyni qərar).
--
-- ---------------------------------------------------------------------------
-- BURADA OLMAYAN: `root_control.MIN_CONFIRMATION_LENGTH`
-- ---------------------------------------------------------------------------
-- Struktur-kritik modulu söndürmək üçün tələb olunan təsdiq mətninin minimum
-- uzunluğu QƏSDƏN köçürülmür. Səbəb ədədin özündə deyil, onu kimin dəyişdiyində:
-- `set_limit` və `set_module_enabled` EYNİ flag-i (`can_manage_system_limits`)
-- tələb edir — yəni hədd Root parametri olsaydı, modulu söndürmək istəyən aktor
-- əvvəlcə öz qarşısındakı maneəni endirə, sonra "x" yazıb `CAMERA_VERIFICATION`-ı
-- bağlaya bilərdi. İzah `use_cases/root_control.py`-dadır.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada Root-un artıq dəyişdirdiyi dəyər
-- ÜSTÜNDƏN YAZILMIR (013/017/018/022–033 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    -- --- Dəstək inbox-u və çökmə paneli (bölmə 8) ------------------------- --
    ('SUPPORT_FIRST_RESPONSE_SLA_HOURS', '24', 'INTEGER', '1', '720',
     'Dəstək müraciətinə ilk cavab üçün hədəf (saat)'),
    ('SUPPORT_RESOLUTION_SLA_HOURS', '72', 'INTEGER', '1', '2160',
     'Dəstək müraciətinin tam həlli üçün hədəf (saat)'),
    ('SUPPORT_SLA_AT_RISK_RATIO', '0.75', 'DECIMAL', '0.10', '0.99',
     'Hədəfin hansı hissəsindən sonra müraciət «risk altında» sayılsın'),
    ('CRASH_WIDESPREAD_INSTALLATION_THRESHOLD', '3', 'INTEGER', '2', '1000',
     'Çökmə neçə fərqli quraşdırmada təkrarlananda «kütləvi» sayılsın'),
    ('CRASH_DASHBOARD_TOP_LIMIT', '10', 'INTEGER', '1', '500',
     'Çökmə panelində göstərilən ən yüksək prioritetli qrup sayı'),
    -- --- Növbə dəyişmə sorğusu (bölmə 3) --------------------------------- --
    ('SHIFT_SWAP_MAX_LEAD_DAYS', '90', 'INTEGER', '1', '365',
     'Növbə dəyişmə sorğusu ən çox neçə gün irəli üçün göndərilə bilər'),
    -- --- Lisenziya ödənişi xatırlatmaları (bölmə 8) ----------------------- --
    ('LICENSE_PAYMENT_REMINDER_OFFSET_DAYS', '-7,-3,-1,1,7', 'TEXT', NULL, NULL,
     'Ödəniş xatırlatma cədvəli (gün): mənfi = bitmədən əvvəl, müsbət = sonra'),
    -- --- Ekran səhifə ölçüləri ------------------------------------------- --
    ('SALES_REVIEW_QUEUE_PAGE_SIZE', '200', 'INTEGER', '1', '5000',
     '«Şübhəli Satışlar» növbəsinin bir oxunuşda gətirdiyi sətir sayı'),
    ('AUDIT_LOG_MAX_PAGE_SIZE', '500', 'INTEGER', '1', '5000',
     'Audit jurnalı səhifəsinin TAVANI — ekranın donmasına qarşı qoruyucu'),
    ('AUDIT_LOG_DEFAULT_PAGE_SIZE', '100', 'INTEGER', '1', '5000',
     'Audit jurnalı ekranının başlanğıc səhifə ölçüsü'),
    ('BACKUP_HISTORY_PAGE_SIZE', '60', 'INTEGER', '1', '1000',
     'Bərpa nöqtələri siyahısının bir oxunuşda gətirdiyi sətir sayı'),
    ('ANNOUNCEMENT_LIST_PAGE_SIZE', '50', 'INTEGER', '1', '1000',
     'Elan admin siyahısının bir oxunuşda gətirdiyi sətir sayı'),
    ('SUPPORT_THREAD_PAGE_SIZE', '20', 'INTEGER', '1', '500',
     'Dəstək widget-inin bir oxunuşda gətirdiyi mövzu sayı'),
    ('SYNC_CONFLICT_PAGE_SIZE', '100', 'INTEGER', '1', '2000',
     'Sinxronizasiya konflikti inbox-unun bir oxunuşda gətirdiyi sətir sayı'),
    -- --- İlk quraşdırma sihirbazı (bölmə 2) ------------------------------ --
    ('SETUP_RECOMMENDED_ADMIN_COUNT', '2', 'INTEGER', '1', '20',
     'Tövsiyə olunan minimum Root/CEO hesab sayı — BLOKLAMIR, xəbərdarlıq verir')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022–033 naxışı təkrarlanır: yeni kirayəçi yarananda
-- eyni sətirləri əlavə edən AYRICA trigger.
--
-- SƏTİRLƏR YUXARIDAKI SİYAHI İLƏ EYNİ OLMALIDIR: iki yerin fərqlənməsi ən
-- pis nasazlıq növünü doğurardı — parametr KÖHNƏ kirayəçidə görünər, YENİ
-- kirayəçidə isə yox olardı və səbəb aylarla tapılmazdı.
CREATE OR REPLACE FUNCTION seed_application_layer_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'SUPPORT_FIRST_RESPONSE_SLA_HOURS', '24', 'INTEGER', '1', '720',
         'Dəstək müraciətinə ilk cavab üçün hədəf (saat)'),
        (NEW.tenant_id, 'SUPPORT_RESOLUTION_SLA_HOURS', '72', 'INTEGER', '1', '2160',
         'Dəstək müraciətinin tam həlli üçün hədəf (saat)'),
        (NEW.tenant_id, 'SUPPORT_SLA_AT_RISK_RATIO', '0.75', 'DECIMAL', '0.10', '0.99',
         'Hədəfin hansı hissəsindən sonra müraciət «risk altında» sayılsın'),
        (NEW.tenant_id, 'CRASH_WIDESPREAD_INSTALLATION_THRESHOLD', '3', 'INTEGER', '2', '1000',
         'Çökmə neçə fərqli quraşdırmada təkrarlananda «kütləvi» sayılsın'),
        (NEW.tenant_id, 'CRASH_DASHBOARD_TOP_LIMIT', '10', 'INTEGER', '1', '500',
         'Çökmə panelində göstərilən ən yüksək prioritetli qrup sayı'),
        (NEW.tenant_id, 'SHIFT_SWAP_MAX_LEAD_DAYS', '90', 'INTEGER', '1', '365',
         'Növbə dəyişmə sorğusu ən çox neçə gün irəli üçün göndərilə bilər'),
        (NEW.tenant_id, 'LICENSE_PAYMENT_REMINDER_OFFSET_DAYS', '-7,-3,-1,1,7', 'TEXT',
         NULL, NULL,
         'Ödəniş xatırlatma cədvəli (gün): mənfi = bitmədən əvvəl, müsbət = sonra'),
        (NEW.tenant_id, 'SALES_REVIEW_QUEUE_PAGE_SIZE', '200', 'INTEGER', '1', '5000',
         '«Şübhəli Satışlar» növbəsinin bir oxunuşda gətirdiyi sətir sayı'),
        (NEW.tenant_id, 'AUDIT_LOG_MAX_PAGE_SIZE', '500', 'INTEGER', '1', '5000',
         'Audit jurnalı səhifəsinin TAVANI — ekranın donmasına qarşı qoruyucu'),
        (NEW.tenant_id, 'AUDIT_LOG_DEFAULT_PAGE_SIZE', '100', 'INTEGER', '1', '5000',
         'Audit jurnalı ekranının başlanğıc səhifə ölçüsü'),
        (NEW.tenant_id, 'BACKUP_HISTORY_PAGE_SIZE', '60', 'INTEGER', '1', '1000',
         'Bərpa nöqtələri siyahısının bir oxunuşda gətirdiyi sətir sayı'),
        (NEW.tenant_id, 'ANNOUNCEMENT_LIST_PAGE_SIZE', '50', 'INTEGER', '1', '1000',
         'Elan admin siyahısının bir oxunuşda gətirdiyi sətir sayı'),
        (NEW.tenant_id, 'SUPPORT_THREAD_PAGE_SIZE', '20', 'INTEGER', '1', '500',
         'Dəstək widget-inin bir oxunuşda gətirdiyi mövzu sayı'),
        (NEW.tenant_id, 'SYNC_CONFLICT_PAGE_SIZE', '100', 'INTEGER', '1', '2000',
         'Sinxronizasiya konflikti inbox-unun bir oxunuşda gətirdiyi sətir sayı'),
        (NEW.tenant_id, 'SETUP_RECOMMENDED_ADMIN_COUNT', '2', 'INTEGER', '1', '20',
         'Tövsiyə olunan minimum Root/CEO hesab sayı — BLOKLAMIR, xəbərdarlıq verir')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_application_layer_limits_for_new_tenant() IS
    'Yeni kirayəçiyə tətbiq qatından köçürülmüş 15 ROOT parametrini əlavə edir '
    '(migrations/034). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_application_layer_limits ON license_tenants;
CREATE TRIGGER trg_seed_application_layer_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_application_layer_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlərin silinməsi parametrləri ROOT ekranından yox edir; tətbiq
-- İŞLƏMƏYƏ DAVAM EDİR, lakin `DEFAULT_LIMITS` fallback dəyərləri ilə
-- (src/domain/policies.py) — yəni Root onları artıq dəyişdirə bilmir və
-- davranış köçürmədən ƏVVƏLKİ ilə eyni olur (defoltlar hərfən eynidir).
-- HEÇ BİR MƏLUMAT İTMİR: bu miqrasiya yalnız konfiqurasiya sətirləri əlavə
-- edib, iş məlumatına toxunmayıb.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_application_layer_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_application_layer_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'SUPPORT_FIRST_RESPONSE_SLA_HOURS',
--       'SUPPORT_RESOLUTION_SLA_HOURS',
--       'SUPPORT_SLA_AT_RISK_RATIO',
--       'CRASH_WIDESPREAD_INSTALLATION_THRESHOLD',
--       'CRASH_DASHBOARD_TOP_LIMIT',
--       'SHIFT_SWAP_MAX_LEAD_DAYS',
--       'LICENSE_PAYMENT_REMINDER_OFFSET_DAYS',
--       'SALES_REVIEW_QUEUE_PAGE_SIZE',
--       'AUDIT_LOG_MAX_PAGE_SIZE',
--       'AUDIT_LOG_DEFAULT_PAGE_SIZE',
--       'BACKUP_HISTORY_PAGE_SIZE',
--       'ANNOUNCEMENT_LIST_PAGE_SIZE',
--       'SUPPORT_THREAD_PAGE_SIZE',
--       'SYNC_CONFLICT_PAGE_SIZE',
--       'SETUP_RECOMMENDED_ADMIN_COUNT'
--   );
-- COMMIT;
