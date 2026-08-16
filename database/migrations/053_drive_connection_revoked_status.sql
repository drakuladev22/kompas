-- ===========================================================================
-- 053 — DRIVE BAĞLANTISININ `REVOKED` VƏZİYYƏTİ
-- ===========================================================================
-- Tarix : 2026-08-15
-- Səbəb : Sənədləşdirmə auditinin tapıntısı — ÖLÜ VƏZİYYƏT.
--
--   `presentation/controllers/drive_connection.py::STATUS_TEXT` ilk gündən
--   `"REVOKED": ("İcazə ləğv edilib", "danger")` sətrini daşıyırdı, LAKİN
--   `drive_connection_status` enum-unda belə dəyər YOX İDİ və heç bir kod ora
--   keçirmirdi. Yəni istifadəçi Google hesabının təhlükəsizlik səhifəsindən
--   razılığı geri alanda ekran hələ də «Aktiv» göstərirdi; həqiqət yalnız
--   növbəti sübut şəkli yüklənməyəndə üzə çıxırdı.
--
--   Söhbət cərimə SÜBUT şəkillərindən gedir — mübahisə halında cərimənin
--   yeganə əsaslandırmasından. Ona görə boşluq ekran mətnini SİLMƏKLƏ deyil,
--   vəziyyəti REAL etməklə bağlanır (Variant A).
--
-- ---------------------------------------------------------------------------
-- NİYƏ `ARCHIVED` KİFAYƏT ETMİRDİ
-- ---------------------------------------------------------------------------
-- `ARCHIVED` ADMİNİN qərarıdır: yeni hesab qoşuldu, köhnəsi OXUNMAĞA davam
-- edir (bax `migrations/002` başlığı — «keçidlər pozulmamalıdır»).
-- `REVOKED` isə XARİCİ hadisədir və nəticəsi tam fərqlidir: refresh token
-- işləmir, yəni həmin hesabdakı şəkillər NƏ yazıla, NƏ də oxuna bilir.
-- İkisini birləşdirsəydik, ekran «Arxivlənib» yazar və administrator bunu
-- normal hal sanardı — halbuki sübut arxivinə çıxış İTİB.
--
-- ---------------------------------------------------------------------------
-- VƏZİYYƏTƏ KİM KEÇİRİR
-- ---------------------------------------------------------------------------
-- `DriveQuotaMonitor.check()` (gündəlik `DRIVE_QUOTA_CHECK` planlanmış işi):
-- Google token endpoint-i `invalid_grant` qaytardıqda
-- (`drive_api.DriveConsentRevokedError`) `mark_revoked()` çağırılır və Root/CEO
-- kritik bildiriş alır. Keçid İDEMPOTENTDİR — ikinci gün heç bir sətir
-- dəyişmir, yəni eyni xəbərdarlıq təkrarlanmır.
--
-- ---------------------------------------------------------------------------
-- MÖVCUD SƏTİRLƏRƏ TƏSİRİ YOXDUR
-- ---------------------------------------------------------------------------
-- Bu miqrasiya YALNIZ enum-a bir dəyər əlavə edir; heç bir sətir yenilənmir,
-- heç bir məhdudiyyət dəyişmir:
--   * `uq_drive_one_active_per_tenant` yalnız `status = 'ACTIVE'` üzərindədir
--     — `REVOKED` sətir yeni hesabın qoşulmasını BLOKLAMIR;
--   * `chk_drive_archived` yalnız `ARCHIVED` üçün `archived_at` tələb edir —
--     `REVOKED` ona tabe deyil;
--   * `fines.evidence_drive_connection_id` sətirdə qalır, yəni hesab yenidən
--     qoşulduqda köhnə keçidlər özündən bərpa olunur.
--
-- İdempotentdir (`ADD VALUE IF NOT EXISTS`). DOWN bloku faylın sonundadır.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 1. ENUM dəyəri
-- ---------------------------------------------------------------------------
-- `ALTER TYPE ... ADD VALUE` PostgreSQL 12+-də tranzaksiya daxilində icra
-- oluna bilir; YEGANƏ məhdudiyyət odur ki, yeni dəyər HƏMİN tranzaksiyada
-- İSTİFADƏ edilə bilməz. Aşağıda onu istifadə edən sorğu YOXDUR (yalnız
-- `COMMENT`), ona görə bölünmüş fayla ehtiyac qalmır.
ALTER TYPE drive_connection_status ADD VALUE IF NOT EXISTS 'REVOKED';

COMMENT ON TYPE drive_connection_status IS
    'Drive bağlantısının vəziyyəti. ACTIVE — yeni yükləmələr bura gedir '
    '(tenant başına TƏK). ARCHIVED — admin yeni hesab qoşdu, köhnəsi yalnız '
    'OXUMA üçün qalır. QUOTA_EXCEEDED — hesab doldu, şəkillər lokal növbədə '
    'gözləyir. REVOKED — istifadəçi Google-da razılığı GERİ ALDI: token '
    'işləmir, yəni bu hesaba nə yazmaq, nə də ondan oxumaq mümkündür; '
    'administrator hesabı yenidən qoşmalıdır (057).';

COMMENT ON COLUMN drive_connections.last_error IS
    'Son nasazlığın Azərbaycanca izahı. REVOKED vəziyyətində buraya '
    '«Google razılığı geri alınıb (invalid_grant)» yazılır — administrator '
    'ekranda «İcazə ləğv edilib» görəndə növbəti sualı «nə vaxt və niyə?» '
    'olur və cavab burada qalır.';

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: PostgreSQL enum dəyərinin SİLİNMƏSİNİ dəstəkləmir. Geri qayıtmaq
-- üçün tipin özü yenidən qurulmalıdır və bu, cədvəlin sütununa toxunur —
-- yəni DOWN burada «ucuz» deyil. Ona görə əvvəlcə sətirlər təhlükəsiz
-- vəziyyətə köçürülür.
--
-- HƏMİN SƏTİRLƏR `ARCHIVED`-a KÖÇÜRÜLÜR, `ACTIVE`-ə YOX: token işləmədiyi
-- üçün `ACTIVE` yazsaydıq, sistem yenidən dolu bir hesaba yazmağa çalışar və
-- 057-dən əvvəlki qüsur (ekran «Aktiv» göstərir) bərpa olunardı.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   UPDATE drive_connections
--      SET status = 'ARCHIVED', archived_at = COALESCE(archived_at, now())
--    WHERE status = 'REVOKED';
--   ALTER TYPE drive_connection_status RENAME TO drive_connection_status_old;
--   CREATE TYPE drive_connection_status AS ENUM
--       ('ACTIVE', 'ARCHIVED', 'QUOTA_EXCEEDED');
--   ALTER TABLE drive_connections
--       ALTER COLUMN status DROP DEFAULT,
--       ALTER COLUMN status TYPE drive_connection_status
--           USING status::text::drive_connection_status,
--       ALTER COLUMN status SET DEFAULT 'ACTIVE';
--   DROP TYPE drive_connection_status_old;
-- COMMIT;
