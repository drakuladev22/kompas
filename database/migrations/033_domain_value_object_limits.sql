-- ===========================================================================
-- 033 — DOMEN VALUE OBJECT SABİTLƏRİNİN ROOT PARAMETRLƏRİ (Faza 10.2)
-- ===========================================================================
-- Tarix : 2026-08-13
-- Səbəb : `src/domain/value_objects/` altında 22 ədəd SABİT kimi yaşayırdı:
--         lisenziya yoxlama ritmi, offline qrace bandı, yenilənmə dövrü və
--         paket tavanı, 1C səhifə ölçüsü və ad-uyğunlaşma həddi, icazə növü
--         müddət tavanı, baza keçidi taymautları, sübut şəklinin kiçildilmə
--         kənarları və satış xalı sisteminin ÜÇ mərkəzi parametri.
--
--         CLAUDE.md §5: struktur təhlükəsizlik zəmanətlərindən (anti-fraud
--         vəzifə ayrılığı, SEC-001, Strict Hierarchy / Self-Escalation Guard,
--         dörd-səviyyəli `HardlockLevel`) KƏNARDA qalan hər sabitin yeri
--         `system_limits`-dədir. Bu 22 dəyərin heç biri həmin siyahıda deyil.
--
--         `SystemLimitKey` + `DEFAULT_LIMITS` (src/domain/policies.py) artıq
--         açarları elan edir; bu miqrasiya onları `system_limits`-ə SEED edir
--         ki, ROOT İdarə Mərkəzi ekranında GÖRÜNSÜNLƏR və dəyişiklikləri
--         `SYSTEM_LIMIT_CHANGED` audit yazısı ilə izlənsin (migrations/
--         022–032 ilə EYNİ naxış).
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
-- Köçürmə DAVRANIŞ dəyişikliyi deyil, İDARƏOLUNMA dəyişikliyidir: 86400 =
-- 24*60*60, 900 = 15*60, 536870912 = 512*1024*1024, 720 = 12*60 və s. Defoltu
-- "yaxşılaşdırsaydıq", mövcud quraşdırma yenilənmədən sonra sükutla başqa cür
-- işləyərdi və səbəbi heç bir jurnalda görünməzdi.
--
-- ---------------------------------------------------------------------------
-- ÜÇ SƏRT ARALIQ — NİYƏ MƏHZ BUNLAR KİLİDLƏNİB
-- ---------------------------------------------------------------------------
-- 1. `LICENSE_CLOCK_ROLLBACK_TOLERANCE_SECONDS` (30–900 san). Bu tolerantlıq
--    saat manipulyasiyasına qarşı YEGANƏ ölçü qoruyucusudur: müddət bitməsi
--    divar saatı ilə yoxlanılır və "geri çəkildi" qərarı məhz bu hədddən
--    asılıdır. Tavan olmasaydı, Root onu 24 saata qaldırıb qorumanı FAKTİKİ
--    söndürə bilərdi — hər gün bir neçə saat geri çəkilmiş PC aşkarlanmazdı.
--    900 saniyə yalançı həyəcanı örtməyə kifayətdir: NTP düzəlişi saniyələrlə
--    ölçülür, yay/qış saatı isə UTC anlarında sıçrayış YARATMIR.
-- 2. `LICENSE_*_OFFLINE_GRACE_DAYS` (1–14). Yuxarı hədd `license_tenants.
--    offline_grace_days` sütununun öz CHECK-i (7–14) ilə eyni tavandır — Root
--    bandı GENİŞLƏNDİRSƏYDİ, DB onsuz da böyük dəyəri qəbul etməzdi və
--    parametr "işləyir görünüb işləməyən" olardı. Daraltmaq (daha sərt
--    offline siyasəti) sərbəstdir.
-- 3. `ERP_NAME_MATCH_THRESHOLD` (0.70–1.00). Aşağı hədd satış xalının SƏHV
--    işçiyə yazılmasının qarşısını alır: 0.70-dən aşağı "Əliyev Elnur" ↔
--    "Əliyev Elvin" cütü keçər və xal başqasının balansına düşərdi.
--
-- ---------------------------------------------------------------------------
-- SATIŞ XALLARININ ÜÇ AÇARI — İKİ QÜSURUN BAĞLANMASI
-- ---------------------------------------------------------------------------
-- `SALES_POINTS_CURRENCY_PER_POINT`: `gamification.py` şərhi bu dəyərin "ROOT
-- İdarə Mərkəzindən dəyişdirildiyini" YAZIRDI, lakin uyğun açar HEÇ VAXT
-- mövcud olmayıb — yəni bal sisteminin mərkəzi parametri (neçə AZN = 1 xal)
-- faktiki olaraq koda bərkidilmişdi.
--
-- `SALES_POINTS_DISPUTE_WINDOW_HOURS`: şərh "cərimə ilə EYNİ" deyirdi, lakin
-- `FINE_APPEAL_WINDOW_HOURS`-a bağlı DEYİLDİ — Root cərimə pəncərəsini
-- dəyişəndə xal pəncərəsi 72-də qalırdı. AYRI AÇAR seçildi (eyni defolt ilə),
-- çünki sayğaclar fərqli andan başlayır (xal `awarded_at`-dan, cərimə
-- `publish()`-dan) və biri pul kəsintisi, digəri mükafat kursudur. Tək açara
-- bağlasaydıq, bir sətrin dəyişməsi İKİ modulun davranışını sükutla dəyişərdi.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada Root-un artıq dəyişdirdiyi dəyər
-- ÜSTÜNDƏN YAZILMIR (013/017/018/022–032 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    -- --- Satış xalları (#6) ---------------------------------------------- --
    ('SALES_POINTS_CURRENCY_PER_POINT', '100', 'DECIMAL', '1', '100000',
     'Neçə AZN brutto satış 1 xal qazandırır'),
    ('SALES_POINTS_DISPUTE_WINDOW_HOURS', '72', 'INTEGER', '1', '8760',
     'Xal etirazı pəncərəsi (saat) — cərimə pəncərəsindən AYRI parametr'),
    ('SALES_POINTS_RESET_NOTICE_DAYS', '14', 'INTEGER', '1', '90',
     '6 aylıq xal sıfırlanmasından neçə gün əvvəl bildiriş göndərilsin'),
    -- --- Lisenziya klienti (bölmə 8) ------------------------------------- --
    ('LICENSE_CHECK_IN_INTERVAL_SECONDS', '86400', 'INTEGER', '300', '604800',
     'Lisenziya sətrinin dövri yoxlama aralığı (saniyə)'),
    ('LICENSE_RETRY_INTERVAL_SECONDS', '3600', 'INTEGER', '60', '86400',
     'Uğursuz lisenziya yoxlamasından sonra növbəti cəhdə qədər gözləmə (saniyə)'),
    ('LICENSE_BLOCKED_RECHECK_INTERVAL_SECONDS', '900', 'INTEGER', '60', '86400',
     'Tətbiq bloklanmış vəziyyətdə yoxlama aralığı (saniyə)'),
    ('LICENSE_MIN_OFFLINE_GRACE_DAYS', '7', 'INTEGER', '1', '14',
     'Offline qrace bandının aşağı ucu (gün) — DB CHECK-i ilə eyni tavan'),
    ('LICENSE_MAX_OFFLINE_GRACE_DAYS', '14', 'INTEGER', '1', '14',
     'Offline qrace bandının yuxarı ucu (gün) — DB CHECK-i ilə eyni tavan'),
    ('LICENSE_DEFAULT_OFFLINE_GRACE_DAYS', '14', 'INTEGER', '1', '14',
     'Qrace dəyəri oxunmadıqda işlənən defolt (gün)'),
    ('LICENSE_EXTENSION_DAYS', '30', 'INTEGER', '1', '365',
     'Developer Panelindəki "1 Ay Uzat" düyməsinin əlavə etdiyi gün sayı'),
    ('LICENSE_CLOCK_ROLLBACK_TOLERANCE_SECONDS', '300', 'INTEGER', '30', '900',
     'Saatın geri çəkilməsinin manipulyasiya sayılma həddi (saniyə) — tavan SƏRTDİR'),
    ('LICENSE_EXPIRY_WARNING_DAYS', '7', 'INTEGER', '1', '90',
     'Lisenziya müddətinin bitməsinə neçə gün qalanda xəbərdarlıq göstərilsin'),
    -- --- Avtomatik yenilənmə --------------------------------------------- --
    ('UPDATE_CHECK_INTERVAL_SECONDS', '86400', 'INTEGER', '300', '604800',
     'Yeni buraxılış kataloqunun arxa fon yoxlama aralığı (saniyə)'),
    ('UPDATE_RETRY_INTERVAL_SECONDS', '7200', 'INTEGER', '60', '86400',
     'Uğursuz yenilənmə cəhdindən sonra gözləmə (saniyə)'),
    ('UPDATE_MAX_PACKAGE_BYTES', '536870912', 'INTEGER', '1048576', '1073741824',
     'Quraşdırıcı faylın maksimum ölçüsü (bayt) — diski dolduran fayla qarşı'),
    -- --- 1C / ERP -------------------------------------------------------- --
    ('ERP_SYNC_PAGE_SIZE', '500', 'INTEGER', '1', '5000',
     'Bir 1C sorğusunda gətirilən sənəd sayı'),
    ('ERP_NAME_MATCH_THRESHOLD', '0.87', 'DECIMAL', '0.70', '1.00',
     'Ad-əsaslı uyğunlaşmanın qəbul həddi — aşağı hüdud SƏRTDİR'),
    -- --- Kataloqlar ------------------------------------------------------ --
    ('LEAVE_TYPE_MAX_DURATION_MINUTES', '720', 'INTEGER', '1', '1440',
     'İcazə Növünün tövsiyə olunan müddəti üçün yuxarı hədd (dəqiqə)'),
    -- --- Baza keçidi (Cloud ↔ Şəxsi server) ------------------------------ --
    ('DB_MIGRATION_DRAIN_TIMEOUT_SECONDS', '300', 'INTEGER', '30', '3600',
     'Offline buferin boşalmasını gözləmə həddi (saniyə)'),
    ('DB_MIGRATION_MAX_WINDOW_MINUTES', '120', 'INTEGER', '1', '1440',
     'Texniki fasilə pəncərəsinin yuxarı həddi (dəqiqə)'),
    -- --- Sübut şəkilləri ------------------------------------------------- --
    ('EVIDENCE_THUMBNAIL_MAX_EDGE_PX', '320', 'INTEGER', '64', '1024',
     'Siyahıdakı kiçik sübut şəklinin maksimum kənarı (piksel)'),
    ('EVIDENCE_FULL_MAX_EDGE_PX', '1600', 'INTEGER', '320', '4096',
     'Açılan sübut şəklinin maksimum kənarı (piksel)')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022–032 naxışı təkrarlanır: yeni kirayəçi yarananda
-- eyni sətirləri əlavə edən AYRICA trigger.
--
-- SƏTİRLƏR YUXARIDAKI SİYAHI İLƏ EYNİ OLMALIDIR: iki yerin fərqlənməsi ən
-- pis nasazlıq növünü doğurardı — parametr KÖHNƏ kirayəçidə görünər, YENİ
-- kirayəçidə isə yox olardı və səbəb aylarla tapılmazdı.
CREATE OR REPLACE FUNCTION seed_domain_value_object_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'SALES_POINTS_CURRENCY_PER_POINT', '100', 'DECIMAL', '1', '100000',
         'Neçə AZN brutto satış 1 xal qazandırır'),
        (NEW.tenant_id, 'SALES_POINTS_DISPUTE_WINDOW_HOURS', '72', 'INTEGER', '1', '8760',
         'Xal etirazı pəncərəsi (saat) — cərimə pəncərəsindən AYRI parametr'),
        (NEW.tenant_id, 'SALES_POINTS_RESET_NOTICE_DAYS', '14', 'INTEGER', '1', '90',
         '6 aylıq xal sıfırlanmasından neçə gün əvvəl bildiriş göndərilsin'),
        (NEW.tenant_id, 'LICENSE_CHECK_IN_INTERVAL_SECONDS', '86400', 'INTEGER', '300', '604800',
         'Lisenziya sətrinin dövri yoxlama aralığı (saniyə)'),
        (NEW.tenant_id, 'LICENSE_RETRY_INTERVAL_SECONDS', '3600', 'INTEGER', '60', '86400',
         'Uğursuz lisenziya yoxlamasından sonra növbəti cəhdə qədər gözləmə (saniyə)'),
        (NEW.tenant_id, 'LICENSE_BLOCKED_RECHECK_INTERVAL_SECONDS', '900', 'INTEGER',
         '60', '86400',
         'Tətbiq bloklanmış vəziyyətdə yoxlama aralığı (saniyə)'),
        (NEW.tenant_id, 'LICENSE_MIN_OFFLINE_GRACE_DAYS', '7', 'INTEGER', '1', '14',
         'Offline qrace bandının aşağı ucu (gün) — DB CHECK-i ilə eyni tavan'),
        (NEW.tenant_id, 'LICENSE_MAX_OFFLINE_GRACE_DAYS', '14', 'INTEGER', '1', '14',
         'Offline qrace bandının yuxarı ucu (gün) — DB CHECK-i ilə eyni tavan'),
        (NEW.tenant_id, 'LICENSE_DEFAULT_OFFLINE_GRACE_DAYS', '14', 'INTEGER', '1', '14',
         'Qrace dəyəri oxunmadıqda işlənən defolt (gün)'),
        (NEW.tenant_id, 'LICENSE_EXTENSION_DAYS', '30', 'INTEGER', '1', '365',
         'Developer Panelindəki "1 Ay Uzat" düyməsinin əlavə etdiyi gün sayı'),
        (NEW.tenant_id, 'LICENSE_CLOCK_ROLLBACK_TOLERANCE_SECONDS', '300', 'INTEGER',
         '30', '900',
         'Saatın geri çəkilməsinin manipulyasiya sayılma həddi (saniyə) — tavan SƏRTDİR'),
        (NEW.tenant_id, 'LICENSE_EXPIRY_WARNING_DAYS', '7', 'INTEGER', '1', '90',
         'Lisenziya müddətinin bitməsinə neçə gün qalanda xəbərdarlıq göstərilsin'),
        (NEW.tenant_id, 'UPDATE_CHECK_INTERVAL_SECONDS', '86400', 'INTEGER', '300', '604800',
         'Yeni buraxılış kataloqunun arxa fon yoxlama aralığı (saniyə)'),
        (NEW.tenant_id, 'UPDATE_RETRY_INTERVAL_SECONDS', '7200', 'INTEGER', '60', '86400',
         'Uğursuz yenilənmə cəhdindən sonra gözləmə (saniyə)'),
        (NEW.tenant_id, 'UPDATE_MAX_PACKAGE_BYTES', '536870912', 'INTEGER',
         '1048576', '1073741824',
         'Quraşdırıcı faylın maksimum ölçüsü (bayt) — diski dolduran fayla qarşı'),
        (NEW.tenant_id, 'ERP_SYNC_PAGE_SIZE', '500', 'INTEGER', '1', '5000',
         'Bir 1C sorğusunda gətirilən sənəd sayı'),
        (NEW.tenant_id, 'ERP_NAME_MATCH_THRESHOLD', '0.87', 'DECIMAL', '0.70', '1.00',
         'Ad-əsaslı uyğunlaşmanın qəbul həddi — aşağı hüdud SƏRTDİR'),
        (NEW.tenant_id, 'LEAVE_TYPE_MAX_DURATION_MINUTES', '720', 'INTEGER', '1', '1440',
         'İcazə Növünün tövsiyə olunan müddəti üçün yuxarı hədd (dəqiqə)'),
        (NEW.tenant_id, 'DB_MIGRATION_DRAIN_TIMEOUT_SECONDS', '300', 'INTEGER', '30', '3600',
         'Offline buferin boşalmasını gözləmə həddi (saniyə)'),
        (NEW.tenant_id, 'DB_MIGRATION_MAX_WINDOW_MINUTES', '120', 'INTEGER', '1', '1440',
         'Texniki fasilə pəncərəsinin yuxarı həddi (dəqiqə)'),
        (NEW.tenant_id, 'EVIDENCE_THUMBNAIL_MAX_EDGE_PX', '320', 'INTEGER', '64', '1024',
         'Siyahıdakı kiçik sübut şəklinin maksimum kənarı (piksel)'),
        (NEW.tenant_id, 'EVIDENCE_FULL_MAX_EDGE_PX', '1600', 'INTEGER', '320', '4096',
         'Açılan sübut şəklinin maksimum kənarı (piksel)')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_domain_value_object_limits_for_new_tenant() IS
    'Yeni kirayəçiyə domen value object-lərindən köçürülmüş 22 ROOT parametrini '
    'əlavə edir (migrations/033). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_domain_value_object_limits ON license_tenants;
CREATE TRIGGER trg_seed_domain_value_object_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_domain_value_object_limits_for_new_tenant();

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
--   DROP TRIGGER IF EXISTS trg_seed_domain_value_object_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_domain_value_object_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'SALES_POINTS_CURRENCY_PER_POINT',
--       'SALES_POINTS_DISPUTE_WINDOW_HOURS',
--       'SALES_POINTS_RESET_NOTICE_DAYS',
--       'LICENSE_CHECK_IN_INTERVAL_SECONDS',
--       'LICENSE_RETRY_INTERVAL_SECONDS',
--       'LICENSE_BLOCKED_RECHECK_INTERVAL_SECONDS',
--       'LICENSE_MIN_OFFLINE_GRACE_DAYS',
--       'LICENSE_MAX_OFFLINE_GRACE_DAYS',
--       'LICENSE_DEFAULT_OFFLINE_GRACE_DAYS',
--       'LICENSE_EXTENSION_DAYS',
--       'LICENSE_CLOCK_ROLLBACK_TOLERANCE_SECONDS',
--       'LICENSE_EXPIRY_WARNING_DAYS',
--       'UPDATE_CHECK_INTERVAL_SECONDS',
--       'UPDATE_RETRY_INTERVAL_SECONDS',
--       'UPDATE_MAX_PACKAGE_BYTES',
--       'ERP_SYNC_PAGE_SIZE',
--       'ERP_NAME_MATCH_THRESHOLD',
--       'LEAVE_TYPE_MAX_DURATION_MINUTES',
--       'DB_MIGRATION_DRAIN_TIMEOUT_SECONDS',
--       'DB_MIGRATION_MAX_WINDOW_MINUTES',
--       'EVIDENCE_THUMBNAIL_MAX_EDGE_PX',
--       'EVIDENCE_FULL_MAX_EDGE_PX'
--   );
-- COMMIT;
