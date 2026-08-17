-- ===========================================================================
-- 066 — ŞİFRƏNİN MİNİMUM UZUNLUĞU 12 → 8
-- ===========================================================================
-- Tarix : 2026-08-17
-- Səbəb : İlk Quraşdırma Sihirbazında admin hesabı yaradılan an tətbiq
--         «KompasOS işə düşə bilmədi» ekranına düşürdü. Jurnalda:
--
--             WeakSecretError: Şifrə siyasətə uyğun deyil:
--             minimum 12 simvol olmalıdır, ən azı bir böyük hərf olmalıdır,
--             ən azı bir xüsusi simvol olmalıdır
--
--         Yəni proqram ÇÖKMÜRDÜ — sadəcə şifrə siyasətə uyğun deyildi.
--         Hədd 12 simvol idi və istifadəçi üçün həddindən artıq idi.
--
-- ---------------------------------------------------------------------------
-- 12 HARADAN GƏLİRDİ VƏ NİYƏ DƏYİŞİR
-- ---------------------------------------------------------------------------
-- 12 OWASP-ın admin hesabları üçün TÖVSİYƏSİ idi (migrations/032). Tövsiyə
-- pisdir demirik; lakin bu, struktur zəmanət DEYİL — `CLAUDE.md` §5-in
-- dilində desək, yeri `system_limits`-dədir və dəyəri müəssisə seçir.
--
-- Aşağı hüdud (`min_value`) ARTIQ 8-dir və DƏYİŞMİR: 8 simvol + böyük hərf +
-- kiçik hərf + rəqəm + xüsusi simvol tələbi qüvvədə qalır. Yəni zəifləyən
-- yeganə şey uzunluqdur, mürəkkəblik yox.
--
-- Müəssisə daha uzun şifrə istəyirsə ROOT panelindən 128-ə qədər qaldıra
-- bilər — bu miqrasiya defoltu dəyişir, tavanı yox.
--
-- ---------------------------------------------------------------------------
-- MÖVCUD KİRAYƏÇİLƏRDƏ YALNIZ «HƏLƏ DƏ DEFOLT» SƏTİRLƏR YENİLƏNİR
-- ---------------------------------------------------------------------------
-- `WHERE limit_value = '12'` şərti qəsdlidir: Root dəyəri artıq dəyişibsə
-- (məs. 16 qoyubsa) miqrasiya onun qərarını ÜSTÜNDƏN YAZMAMALIDIR. Bu, 032-
-- dəki `ON CONFLICT DO NOTHING` qaydasının eyni məntiqidir.
--
-- ---------------------------------------------------------------------------
-- TRIGGER FUNKSİYASI TAM YENİDƏN YAZILIR
-- ---------------------------------------------------------------------------
-- `seed_infrastructure_runtime_limits_for_new_tenant()` YENİ kirayəçiyə
-- defoltları yazır və orada dəyər 032-də `'12'` idi. Funksiya `CREATE OR
-- REPLACE` ilə bütövlükdə yenidən yazılır — bir sətri «yamaqlayan» ikinci
-- trigger əlavə etmək daha qısa olardı, lakin nəticə oxunmaz olardı: iki
-- trigger arasındakı icra sırası addan asılıdır və defoltun HƏQİQİ dəyəri
-- heç bir tək yerdə görünməzdi.
--
-- Siyahının qalan sətirləri 032-dəkinin EYNİSİDİR; dəyişən yeganə şey
-- `PASSWORD_MIN_LENGTH` sətrindəki `'12'` → `'8'`-dir.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Mövcud kirayəçilər
-- ---------------------------------------------------------------------------
UPDATE system_limits
   SET limit_value = '8'
 WHERE limit_key = 'PASSWORD_MIN_LENGTH'
   AND limit_value = '12';

-- ---------------------------------------------------------------------------
-- 2. Yeni kirayəçilər
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION seed_infrastructure_runtime_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    SELECT NEW.tenant_id, v.limit_key, v.limit_value, v.value_type,
           v.min_value, v.max_value, v.description_az
      FROM (VALUES
        ('PASSWORD_MIN_LENGTH', '8', 'INTEGER', '8', '128',
         'Admin-tier şifrənin minimum uzunluğu (simvol)'),
        ('BACKUP_MIN_RETENTION_DAYS', '30', 'INTEGER', '30', '3650',
         'Ehtiyat nüsxə saxlama müddətinin döşəməsi — 30-dan aşağı düşə bilməz'),
        ('BACKUP_RETENTION_DAYS', '30', 'INTEGER', '30', '3650',
         'Ehtiyat nüsxələrin saxlanma müddəti (gün)'),
        ('BACKUP_DUMP_TIMEOUT_SECONDS', '3600', 'INTEGER', '60', '86400',
         'pg_dump bu müddətdən uzun çəkərsə dayandırılır (saniyə)'),
        ('HEALTH_DISK_WARNING_PERCENT', '85.0', 'DECIMAL', '50', '99',
         'Disk doluluğu bu faizi keçəndə xəbərdarlıq'),
        ('HEALTH_DISK_CRITICAL_PERCENT', '95.0', 'DECIMAL', '55', '100',
         'Disk doluluğu bu faizi keçəndə kritik vəziyyət'),
        ('HEALTH_DB_PING_SLOW_MS', '500', 'INTEGER', '50', '60000',
         'DB ping bu müddətdən uzun çəkərsə "yavaş" sayılır (millisaniyə)'),
        ('DRIVE_QUOTA_WARNING_RATIO', '0.90', 'DECIMAL', '0.50', '1.00',
         'Google Drive kvota xəbərdarlığının doluluq həddi (nisbət)'),
        ('DRIVE_QUOTA_WARNING_COOLDOWN_DAYS', '7', 'INTEGER', '1', '90',
         'Kvota xəbərdarlığı bu qədər gündən tez təkrarlanmır'),
        ('NTP_POLL_INTERVAL_SECONDS', '300', 'INTEGER', '30', '86400',
         'NTP ölçmələri arasındakı aralıq (saniyə)'),
        ('NTP_QUERY_TIMEOUT_SECONDS', '3.0', 'DECIMAL', '1.0', '30.0',
         'Bir SNTP sorğusunun taymautu (saniyə)'),
        ('NTP_SAMPLE_TTL_SECONDS', '1800', 'INTEGER', '60', '86400',
         'Ölçmə bu müddətdən sonra "təzə" sayılmır (saniyə)'),
        ('NTP_MAX_ROUND_TRIP_SECONDS', '2.0', 'DECIMAL', '0.1', '30.0',
         'Gediş-dönüş gecikməsi bundan böyükdürsə ölçmə etibarsızdır (saniyə)'),
        ('ERP_MATCH_AMBIGUITY_MARGIN', '0.05', 'DECIMAL', '0.01', '0.50',
         'Ən yaxşı iki namizədin fərqi bundan azdırsa uyğunlaşma qəbul edilmir'),
        ('ERP_SYNC_MAX_PARALLEL_SERVERS', '4', 'INTEGER', '1', '32',
         'Eyni anda sinxronlaşdırılan 1C serverlərinin sayı'),
        ('ERP_SYNC_MAX_PAGES_PER_RUN', '10', 'INTEGER', '1', '1000',
         'Bir dövrdə bir serverdən oxunan maksimum səhifə sayı'),
        ('ERP_REQUEST_TIMEOUT_SECONDS', '30.0', 'DECIMAL', '5.0', '300.0',
         '1C OData sorğusunun taymautu (saniyə)'),
        ('ERP_MAX_RETRIES', '3', 'INTEGER', '1', '10',
         '1C sorğusunun təkrar cəhd sayı (429/5xx cavablarında)'),
        ('KIOSK_RESTART_WINDOW_MINUTES', '10', 'INTEGER', '1', '1440',
         'Kiosk yenidən-başlatma fırtınası pəncərəsi (dəqiqə)'),
        ('KIOSK_MAX_RESTARTS_PER_WINDOW', '5', 'INTEGER', '1', '100',
         'Pəncərə ərzində icazə verilən yenidən başlatma sayı'),
        ('KIOSK_RESTART_BACKOFF_SECONDS', '2,4,8,16,30', 'TEXT', '1', '3600',
         'Kiosk yenidən başlatma gözləmə cədvəli (vergüllü; hüdud hər elementə)'),
        ('DEVELOPER_DIRECTORY_STALE_DAYS', '3', 'INTEGER', '1', '365',
         'Bu qədər gün check-in etməyən quraşdırma "səssiz" sayılır'),
        ('NOTIFY_MAX_BATCH_SIZE', '25', 'INTEGER', '1', '500',
         'Bir dövrdə göndərilən maksimum gözləyən bildiriş'),
        ('NOTIFY_MAX_ATTEMPTS', '5', 'INTEGER', '1', '20',
         'Bu qədər uğursuz cəhddən sonra bildiriş "göndərilməz" sayılır'),
        ('NOTIFY_RETRY_BACKOFF_MINUTES', '1,5,15,60,240', 'TEXT', '1', '10080',
         'Bildiriş cəhdləri arası gözləmə cədvəli (vergüllü; hüdud hər elementə)'),
        ('NOTIFY_POLL_INTERVAL_SECONDS', '120', 'INTEGER', '5', '3600',
         'Bildiriş növbəsinin dövr aralığı (saniyə)'),
        ('EMAIL_SMTP_TIMEOUT_SECONDS', '15.0', 'DECIMAL', '1.0', '300.0',
         'SMTP soket taymautu (saniyə)'),
        ('CRASH_MAX_REPORTS_PER_FINGERPRINT', '3', 'INTEGER', '1', '100',
         'Eyni çökmə barmaq izi üçün bir sessiyada göndərilən hesabat tavanı'),
        ('REALTIME_POLL_INTERVAL_SECONDS', '30', 'INTEGER', '5', '3600',
         'Realtime kanalı polling rejimində sorğu aralığı (saniyə)'),
        ('REALTIME_RECONNECT_BACKOFF_SECONDS', '5,15,30,60', 'TEXT', '1', '3600',
         'WebSocket yenidən qoşulma gözləmə cədvəli (vergüllü; hüdud hər elementə)'),
        ('OFFLINE_SYNC_BATCH_SIZE', '100', 'INTEGER', '1', '5000',
         'Offline buferdən bir dövrdə sinxronlaşdırılan yazı sayı'),
        ('OFFLINE_RETRY_BACKOFF_SECONDS', '30,120,600', 'TEXT', '1', '86400',
         'Offline yazı təkrar cəhd cədvəli (vergüllü; hüdud hər elementə)'),
        ('OFFLINE_SQLITE_TIMEOUT_SECONDS', '10.0', 'DECIMAL', '1.0', '120.0',
         'Offline SQLite kilid gözləmə taymautu (saniyə)'),
        ('DB_POOL_MIN_SIZE', '1', 'INTEGER', '1', '32',
         'PostgreSQL bağlantı hovuzunun minimum ölçüsü'),
        ('DB_POOL_MAX_SIZE', '8', 'INTEGER', '1', '64',
         'PostgreSQL bağlantı hovuzunun maksimum ölçüsü'),
        ('DB_CONNECT_TIMEOUT_SECONDS', '15.0', 'DECIMAL', '1.0', '300.0',
         'Hovuzdan bağlantı gözləmə taymautu (saniyə)'),
        ('DRIVE_TOKEN_REFRESH_MARGIN_SECONDS', '60', 'INTEGER', '10', '600',
         'Access token bitməmişdən bu qədər əvvəl yenilənir (saniyə)'),
        ('DRIVE_REQUEST_TIMEOUT_SECONDS', '30.0', 'DECIMAL', '5.0', '300.0',
         'Google Drive API sorğusunun taymautu (saniyə)'),
        ('DRIVE_MAX_RETRIES', '3', 'INTEGER', '1', '10',
         'Drive API təkrar cəhd sayı (429/5xx cavablarında)'),
        ('DRIVE_OAUTH_FLOW_TIMEOUT_SECONDS', '300.0', 'DECIMAL', '30.0', '1800.0',
         'Drive razılıq axını bu müddətdən sonra ləğv edilir (saniyə)'),
        ('EVIDENCE_JPEG_QUALITY', '85', 'INTEGER', '40', '100',
         'Sübut şəklinin JPEG keyfiyyəti'),
        ('UPLOAD_CLAIM_STALE_AFTER_SECONDS', '600', 'INTEGER', '60', '86400',
         'Claim edilmiş yükləmə elementinin köhnəlmə müddəti (saniyə)'),
        ('IMAGE_CACHE_TTL_SECONDS', '2592000', 'INTEGER', '3600', '31536000',
         'Şəkil keşindəki faylın ömrü (saniyə; defolt 30 gün)'),
        ('IMAGE_CACHE_MAX_BYTES', '268435456', 'INTEGER', '16777216', '8589934592',
         'Şəkil keşinin disk tavanı (bayt; defolt 256 MB)'),
        ('PLUGIN_SANDBOX_TIMEOUT_SECONDS', '10.0', 'DECIMAL', '1.0', '300.0',
         'Plugin sandbox icra taymautu (saniyə)'),
        ('PLUGIN_SANDBOX_MAX_OUTPUT_BYTES', '1048576', 'INTEGER', '65536', '67108864',
         'Plugin prosesindən oxunan maksimum çıxış (bayt)'),
        ('UPDATE_VERIFY_TIMEOUT_SECONDS', '60.0', 'DECIMAL', '5.0', '600.0',
         'Authenticode imza yoxlamasının taymautu (saniyə)'),
        ('UPDATE_UPLOAD_TIMEOUT_SECONDS', '600.0', 'DECIMAL', '30.0', '7200.0',
         'Yeni buraxılışın Storage-ə yüklənmə taymautu (saniyə)'),
        ('UPDATE_DOWNLOAD_TIMEOUT_SECONDS', '300.0', 'DECIMAL', '30.0', '7200.0',
         'Yenilənmə paketinin endirilmə taymautu (saniyə)'),
        ('UPDATE_SIGNED_URL_TTL_SECONDS', '3600', 'INTEGER', '60', '86400',
         'İmzalı endirmə linkinin ömrü (saniyə)'),
        ('UPDATE_CATALOG_FETCH_LIMIT', '20', 'INTEGER', '1', '500',
         'Buraxılış kataloğu sorğusunun oxuduğu sətir tavanı')
      ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_infrastructure_runtime_limits_for_new_tenant() IS
    'Yeni kirayəçiyə infrastruktur limitlərini yazır (migrations/032, '
    'PASSWORD_MIN_LENGTH defoltu 066-da 8-ə endirildi).';

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- Geri qaytarma MÖVCUD hesabların şifrəsini uzatmır — onlar 8 simvolla
-- yaradılıb və işləməyə davam edir. Dəyişən yalnız BUNDAN SONRAKI yoxlamadır.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   UPDATE system_limits SET limit_value = '12'
--    WHERE limit_key = 'PASSWORD_MIN_LENGTH' AND limit_value = '8';
--   -- Trigger funksiyasını 032-dəki mətnlə yenidən yaradın.
-- COMMIT;
