-- ===========================================================================
-- 032 — İNFRASTRUKTUR ƏMƏLİYYAT PARAMETRLƏRİNİN ROOT-A KÖÇÜRÜLMƏSİ
-- ===========================================================================
-- Tarix : 2026-08-13
-- Səbəb : Faza 10.2 auditi `src/infrastructure/` qatında 51 hardcode
--         əməliyyat dəyəri tapdı (taymaut, təkrar cəhd sayı, hədd, dövr
--         aralığı, paket ölçüsü). CLAUDE.md §5-ə görə struktur təhlükəsizlik
--         zəmanəti OLMAYAN hər sabitin yeri `system_limits`-dədir.
--         `SystemLimitKey` + `DEFAULT_LIMITS` (src/domain/policies.py) artıq
--         açarları elan edir — bu miqrasiya onları SEED edir ki, ROOT İdarə
--         Mərkəzi ekranında GÖRÜNSÜNLƏR və Root-un dəyişikliyi DB-də qalsın
--         (migrations/022–031 ilə EYNİ naxış).
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
-- Hər `limit_value` köçürülən hardcode dəyərlə HƏRFƏN eynidir. Köçürmə
-- davranış dəyişikliyi DEYİL, idarəolunma dəyişikliyidir: bu miqrasiyadan
-- sonra sistem eyni cür işləyir, sadəcə dəyərlər artıq Root-dan dəyişdirilə
-- bilir və hər dəyişiklik `system_limits.changed_by`/`changed_at` ilə
-- audit-lənir (ROOT ekranı `RootControlUseCase.update_limit` üzərindən yazır,
-- o isə `audit_logs`-a `SYSTEM_LIMIT_CHANGED` sətri qoyur).
--
-- ---------------------------------------------------------------------------
-- `min_value`/`max_value` NİYƏ SƏRTDİR
-- ---------------------------------------------------------------------------
-- Bu açarların bir qismi tətbiqin İŞLƏMƏ QABİLİYYƏTİNƏ birbaşa təsir edir:
-- `DB_POOL_MAX_SIZE = 0` heç bir sorğunun icra oluna bilməməsi, `NTP_QUERY_
-- TIMEOUT_SECONDS = 0` saatın heç vaxt yoxlanılmaması, `BACKUP_DUMP_TIMEOUT_
-- SECONDS = 0` isə gecəlik nüsxənin həmişə uğursuz olması deməkdir. Ona görə
-- hər açara aralıq yazılır və kod oxuduğu dəyəri həmin aralığa KLAMP edir
-- (bax `src/infrastructure/config/limits.py` — `INFRA_LIMIT_BOUNDS`). Yəni
-- səhv konfiqurasiya "tətbiq açılmır" DEYİL, "dəyər hüduda sıxıldı +
-- xəbərdarlıq jurnalı" ilə nəticələnir.
--
-- Aralıqlar `INFRA_LIMIT_BOUNDS` ilə HƏRFƏN eyni olmalıdır; pariteti
-- `tests/unit/test_infrastructure_root_limits.py` qapı kimi yoxlayır.
--
-- ---------------------------------------------------------------------------
-- SİYAHI-TİPLİ AÇARLAR (`TEXT`)
-- ---------------------------------------------------------------------------
-- Dörd açar vergüllü cədvəldir (`KIOSK_RESTART_BACKOFF_SECONDS`,
-- `NOTIFY_RETRY_BACKOFF_MINUTES`, `REALTIME_RECONNECT_BACKOFF_SECONDS`,
-- `OFFLINE_RETRY_BACKOFF_SECONDS`) — `EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS`
-- (migrations/028) naxışının eynisi: cədvəlin SIRASI mənalıdır və ayrı-ayrı
-- açarlarda Root onları yanlış ardıcıllıqla yaza bilərdi.
--
-- Onlarda `min_value`/`max_value` CƏDVƏLƏ DEYİL, HƏR ELEMENTƏ aiddir: mənasız
-- ola bilən tək addımdır (məs. `0` saniyəlik gözləmə = fasiləsiz təkrar cəhd
-- dövrü), cəm deyil. Kod da klampı elementə tətbiq edir.
--
-- ---------------------------------------------------------------------------
-- BU MİQRASİYAYA GİRMƏYƏNLƏR (QƏSDƏN HARDCODE)
-- ---------------------------------------------------------------------------
-- * Kripto sabitləri (Argon2 parametrləri, nonce/açar ölçüləri, pepper
--   uzunluğu) — bunları Root-dan aşağı salmaq hash-i zəiflədərdi.
-- * SEC-018 uzantı ağ siyahısı (`storage/google_drive._ALLOWED_BY_OWNER`).
-- * NTP protokol sabitləri (RFC 4330: paket ölçüsü, port 123, stratum
--   hüdudları, fraksiya böləni) — bunlar standartdır, siyasət deyil.
-- * HTTP status kodları və SMTP standart portları (587/465).
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
-- ÜSTÜNDƏN YAZILMIR (013/017/018/022–031 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('PASSWORD_MIN_LENGTH', '12', 'INTEGER', '8', '128',
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

-- ---------------------------------------------------------------------------
-- 2. MÖVCUD AÇARLARA TOXUNULMUR — YENİ AÇAR DA YARADILMIR
-- ---------------------------------------------------------------------------
-- `PIN_MAX_FAILED_ATTEMPTS`, `PIN_LOCKOUT_MINUTES` və `NTP_MAX_DRIFT_SECONDS`
-- ARTIQ `schema.sql` §24-də öz dəyəri VƏ hüdudları (3–10 / 5–60 / 10–300) ilə
-- seed olunur. `security/hashing.py` və `timekeeping/ntp.py` indi məhz onlara
-- BAĞLANIR — ikinci ad YARADILMIR, çünki eyni dəyərin iki açarı olsaydı Root
-- birini dəyişər, digəri qüvvədə qalardı və "niyə tətbiq olunmur?" sualının
-- cavabı tapılmazdı.
--
-- Bu miqrasiya onların NƏ dəyərinə, NƏ hüduduna toxunur: `schema.sql` həmin
-- üç sətir üçün TƏK MƏNBƏDİR. `INFRA_LIMIT_BOUNDS` də onları qəsdən EHTİVA
-- ETMİR — səbəb `config/limits.py`-dakı şərhdə (tətbiq qatı onları klampsız
-- oxuyur; infrastruktur onları sıxsaydı, ekrandakı hədd bloklamanın faktiki
-- həddindən fərqlənərdi).

-- ---------------------------------------------------------------------------
-- 3. YENİ KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022–031 naxışı təkrarlanır: yeni kirayəçi yarananda
-- həmin sətirləri əlavə edən AYRICA trigger.
--
-- Sətirlər 1-ci bölmədəki `VALUES` siyahısından TƏKRAR OXUNUR (eyni mətn iki
-- yerdə): funksiya gövdəsi `$$` içindədir və `INSERT ... SELECT ... FROM
-- license_tenants` naxışını orada işlətmək YENİ kirayəçi üçün BÜTÜN
-- kirayəçilərə sətir yazardı.
CREATE OR REPLACE FUNCTION seed_infrastructure_runtime_limits_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    SELECT NEW.tenant_id, v.limit_key, v.limit_value, v.value_type,
           v.min_value, v.max_value, v.description_az
      FROM (VALUES
        ('PASSWORD_MIN_LENGTH', '12', 'INTEGER', '8', '128',
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
    'Yeni kirayəçiyə Faza 10.2-nin 51 infrastruktur ROOT parametrini əlavə '
    'edir (migrations/032). `seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_infrastructure_runtime_limits ON license_tenants;
CREATE TRIGGER trg_seed_infrastructure_runtime_limits
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_infrastructure_runtime_limits_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: sətirlərin silinməsi parametrləri ROOT ekranından yox edir;
-- infrastruktur işləməyə DAVAM EDİR, lakin `DEFAULT_LIMITS` fallback-ları ilə
-- (src/domain/policies.py) — yəni Root onları artıq dəyişdirə bilmir.
-- Davranış dəyişmir, çünki fallback dəyərləri seed dəyərləri ilə eynidir.
--
-- `PIN_*` və `NTP_MAX_DRIFT_SECONDS` sətirlərinə bu miqrasiya HEÇ VAXT
-- toxunmayıb (bax 2-ci bölmə) — DOWN blokunda da onlar yoxdur.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_infrastructure_runtime_limits ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_infrastructure_runtime_limits_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'PASSWORD_MIN_LENGTH',
--       'BACKUP_MIN_RETENTION_DAYS', 'BACKUP_RETENTION_DAYS',
--       'BACKUP_DUMP_TIMEOUT_SECONDS',
--       'HEALTH_DISK_WARNING_PERCENT', 'HEALTH_DISK_CRITICAL_PERCENT',
--       'HEALTH_DB_PING_SLOW_MS',
--       'DRIVE_QUOTA_WARNING_RATIO', 'DRIVE_QUOTA_WARNING_COOLDOWN_DAYS',
--       'NTP_POLL_INTERVAL_SECONDS', 'NTP_QUERY_TIMEOUT_SECONDS',
--       'NTP_SAMPLE_TTL_SECONDS', 'NTP_MAX_ROUND_TRIP_SECONDS',
--       'ERP_MATCH_AMBIGUITY_MARGIN', 'ERP_SYNC_MAX_PARALLEL_SERVERS',
--       'ERP_SYNC_MAX_PAGES_PER_RUN', 'ERP_REQUEST_TIMEOUT_SECONDS',
--       'ERP_MAX_RETRIES',
--       'KIOSK_RESTART_WINDOW_MINUTES', 'KIOSK_MAX_RESTARTS_PER_WINDOW',
--       'KIOSK_RESTART_BACKOFF_SECONDS',
--       'DEVELOPER_DIRECTORY_STALE_DAYS',
--       'NOTIFY_MAX_BATCH_SIZE', 'NOTIFY_MAX_ATTEMPTS',
--       'NOTIFY_RETRY_BACKOFF_MINUTES', 'NOTIFY_POLL_INTERVAL_SECONDS',
--       'EMAIL_SMTP_TIMEOUT_SECONDS', 'CRASH_MAX_REPORTS_PER_FINGERPRINT',
--       'REALTIME_POLL_INTERVAL_SECONDS', 'REALTIME_RECONNECT_BACKOFF_SECONDS',
--       'OFFLINE_SYNC_BATCH_SIZE', 'OFFLINE_RETRY_BACKOFF_SECONDS',
--       'OFFLINE_SQLITE_TIMEOUT_SECONDS',
--       'DB_POOL_MIN_SIZE', 'DB_POOL_MAX_SIZE', 'DB_CONNECT_TIMEOUT_SECONDS',
--       'DRIVE_TOKEN_REFRESH_MARGIN_SECONDS', 'DRIVE_REQUEST_TIMEOUT_SECONDS',
--       'DRIVE_MAX_RETRIES', 'DRIVE_OAUTH_FLOW_TIMEOUT_SECONDS',
--       'EVIDENCE_JPEG_QUALITY', 'UPLOAD_CLAIM_STALE_AFTER_SECONDS',
--       'IMAGE_CACHE_TTL_SECONDS', 'IMAGE_CACHE_MAX_BYTES',
--       'PLUGIN_SANDBOX_TIMEOUT_SECONDS', 'PLUGIN_SANDBOX_MAX_OUTPUT_BYTES',
--       'UPDATE_VERIFY_TIMEOUT_SECONDS', 'UPDATE_UPLOAD_TIMEOUT_SECONDS',
--       'UPDATE_DOWNLOAD_TIMEOUT_SECONDS', 'UPDATE_SIGNED_URL_TTL_SECONDS',
--       'UPDATE_CATALOG_FETCH_LIMIT'
--   );
-- COMMIT;
