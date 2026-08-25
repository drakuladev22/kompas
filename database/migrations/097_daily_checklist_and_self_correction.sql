-- ===========================================================================
-- 097 — GÜNDƏLİK AÇILIŞ/BAĞLANIŞ CHECKLIST-İ (Faza 4.1) + ÖZ-DÜZƏLİŞ SORĞUSU
--        MƏNBƏYİ (Faza 4.2), v2backlog.md
-- ===========================================================================
-- Tarix : 2026-08-25
-- Mənbə : `domain`-in Faza 4 domen qatı (`use_cases/field_reports.py`,
--         `use_cases/task_workflow.py`, `entities/task.py`) tələb etdiyi
--         iki sxem dəyişikliyi.
--
-- ---------------------------------------------------------------------------
-- 1) `field_report_types.once_per_day` — NİYƏ KATALOQDA, KODDA DEYİL
-- ---------------------------------------------------------------------------
-- `requires_checklist`-in EYNİ naxışı (migrations/037): "gündə bir dəfə"
-- qaydası `if report_type == 'DAILY_OPEN'` kimi KOD-DAXİLİ şərtlə yazılsaydı,
-- növbəti "gündə bir dəfə" şablonu (məs. gələcək bir tələb) yeni buraxılış
-- tələb edərdi. Kataloq sütunu ilə YENİ sətir kifayətdir.
--
-- ---------------------------------------------------------------------------
-- 2) `tasks.source` — NİYƏ TEXT+CHECK, ENUM DEYİL
-- ---------------------------------------------------------------------------
-- `employee_transfer_status` (migrations/088) fərqli olaraq, `field_reports.
-- status` (migrations/037) ilə EYNİ üslub seçilib — TEXT+CHECK, çünki
-- `TaskSource` (`entities/task.py`) gələcəkdə üçüncü mənbə (məs. "SİSTEM
-- AVTOMATİK") ala bilər və CHECK dəyişikliyi ENUM `ALTER TYPE ADD VALUE`-dan
-- (silinməyən, geri qaytarıla bilməyən) daha ucuzdur.
--
-- ---------------------------------------------------------------------------
-- SEED — `DAILY_OPEN`/`DAILY_CLOSE` + kateqoriyalar
-- ---------------------------------------------------------------------------
-- `route_to_role=NULL`: gündəlik checklist heç kimin "intizam axınına"
-- getmir (`INCIDENT_OGURLUQ`-un `route_to_role='ADMIN'`-dən FƏRQLİ) — bu,
-- sadəcə Mağaza Meneceri-nin gündəlik qeydidir, kimsə marşrutlanmır.
-- Kateqoriya kodları GLOBAL UNİKALDIR (`field_report_categories.code`
-- PRIMARY KEY-dir, `report_type`-a görə DEYİL) — `AUDIT_*`/`INCIDENT_*`
-- adları ilə TOQQUŞMAMASI üçün `DAILY_OPEN_*`/`DAILY_CLOSE_*` prefiksi
-- işlədilir.
--
-- Bu sətirlər KATALOQ MƏLUMATIDIR, Root-tunable limit DEYİL (`domain`-in
-- qeydi, qəbul edilir) — `system_limits`-ə getmir.
--
-- ---------------------------------------------------------------------------
-- `uq_field_reports_once_per_day` — DB SƏVİYYƏLİ İKİNCİ QAT (CLAUDE.md §5)
-- ---------------------------------------------------------------------------
-- `domain` yoxlamanı `find_for_store_and_day()` ilə DOMEN səviyyəsində
-- qoyub, DB unikal indeksi olmadan. Bu, `fine_management.py`-dəki
-- `DuplicateFineSubmissionError`/`uq_fines_manual_camera_idempotency_key`
-- (migrations/074) NAXIŞININ EYNİSİ tələb edir: domen yoxlaması "oxu →
-- yoxla → yaz" ardıcıllığıdır və EYNİ ANDA iki göndəriş (İKİ brauzer
-- tabı, İKİ admin) arasındakı YARIŞDA hər ikisi "mövcud deyil" görüb hər
-- ikisi yazır — domen tək başına bunu QAPAYA BİLMƏZ.
--
-- QISMƏN İNDEKS, TAM CƏDVƏL DEYİL: `field_reports`-un ÜMUMİ populyasiyası
-- (STORE_AUDIT/INCIDENT) "gündə bir" məhdudiyyətinə TABE DEYİL — eyni
-- mağazada eyni gündə İKİ audit və ya İKİ insident TAM QANUNİDİR. Ona görə
-- indeks `type IN ('DAILY_OPEN', 'DAILY_CLOSE')` ŞƏRTİNƏ bağlanır.
--
-- BU SİYAHI HARDCODE-DUR VƏ BUNUN SƏBƏBİ STRUKTURALDIR, İXTİYARİ DEYİL:
-- Postgres-in QİSMƏN İNDEKS `WHERE` şərti İMMUTABLE ifadə olmalıdır və
-- `field_report_types.once_per_day`-a (BAŞQA CƏDVƏL) sorğu ATA BİLMƏZ.
-- Yəni kataloqdan DİNAMİK oxuma DB indeksi SƏVİYYƏSİNDƏ mümkün deyil —
-- YALNIZ tətbiq qatı (`template.once_per_day`) bunu bacarır. Gələcəkdə
-- kataloqa YENİ "gündə-bir" şablonu əlavə edilsə, BU MİQRASİYA NÖVBƏTİ
-- miqrasiya ilə YENİLƏNMƏLİDİR (indeksin şərti siyahısına yeni kod əlavə
-- edilməli) — bu, kataloqun "sərbəst genişlənmə" xüsusiyyətini MƏHDUDLAŞDIRIR,
-- lakin DB-səviyyəli zəmanətin qiymətidir.
--
-- `(created_at AT TIME ZONE 'UTC')::date` — SEBƏBİ TIME-1: `use_cases/
-- field_reports.py`-dəki domen yoxlaması `now.date()`-dan istifadə edir,
-- `now` isə `Clock` portundan (SERVER, UTC) gəlir. Sadə `created_at::date`
-- Postgres SESSİYASININ `TimeZone` GUC dəyərinə görə HESABLANIR — sessiya
-- UTC-dən FƏRQLİ konfiqurasiya olunsaydı (məs. `Asia/Baku`, `stores.
-- timezone` defoltu), tətbiq qatının "bu gün" tərifi ilə DB indeksinin "bu
-- gün" tərifi GECƏ YARISI ƏTRAFINDA (20:00-24:00 UTC) AYRILARDI — eyni
-- göndəriş bir tərəfdə "bu gün", digərində "sabahkı gün" sayıla bilərdi.
-- Açıq `AT TIME ZONE 'UTC'` bu asılılığı ARADAN QALDIRIR.
--
-- ---------------------------------------------------------------------------
-- İDEMPOTENT, DOWN BLOKU SONDA. `schema.sql` YENİLƏNMİR (CLAUDE.md §7) —
-- yalnız YENİ sütun/indeks/seed, mövcud qayda YENİDƏN yazılmır.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. `field_report_types.once_per_day`
-- ---------------------------------------------------------------------------
ALTER TABLE field_report_types
    ADD COLUMN IF NOT EXISTS once_per_day BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN field_report_types.once_per_day IS
    'Faza 4.1 (v2backlog.md): bu şablondan mağaza+gün başına YALNIZ BİR '
    'hesabat qəbul edilir. `requires_checklist` ilə EYNİ naxış — "if type == '
    '...''" kod-daxili şərti ƏVƏZ EDİR (migrations/097).';

-- ---------------------------------------------------------------------------
-- 2. `tasks.source`
-- ---------------------------------------------------------------------------
ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'ASSIGNED'
        CHECK (source IN ('ASSIGNED', 'EMPLOYEE_SELF_CORRECTION'));

COMMENT ON COLUMN tasks.source IS
    'Faza 4.2 (v2backlog.md): tapşırığın mənbəyi. `EMPLOYEE_SELF_CORRECTION` '
    '= işçi Kamera/Face Control uyğunsuzluğuna öz-düzəliş sorğusu göndərib '
    '(`assignee_id == assigned_by`), `ASSIGNED` = adi HR/menecer təyinatı. '
    'Sui-istifadə tavanının (`SELF_CORRECTION_REQUEST_WINDOW_DAYS`) sayğac '
    'sütunudur (migrations/097).';

-- ---------------------------------------------------------------------------
-- 3. Seed: `DAILY_OPEN`/`DAILY_CLOSE` + kateqoriyaları
-- ---------------------------------------------------------------------------
INSERT INTO field_report_types
    (code, tenant_id, name_az, description_az, requires_checklist, once_per_day)
VALUES
    ('DAILY_OPEN', NULL, 'Gündəlik Açılış Checklist-i',
     'Mağaza Meneceri hər gün açılışda doldurur (kassa, təhlükəsizlik-sistemi, '
     'təmizlik bəndləri, Root-idarəli). Mağaza+gün başına YALNIZ BİR dəfə (#4.1).',
     TRUE, TRUE),
    ('DAILY_CLOSE', NULL, 'Gündəlik Bağlanış Checklist-i',
     'Mağaza Meneceri hər gün bağlanışda doldurur — açılışın EYNİ struktur '
     'analoqu. Mağaza+gün başına YALNIZ BİR dəfə (#4.1).',
     TRUE, TRUE)
ON CONFLICT (code) DO NOTHING;

INSERT INTO field_report_categories
    (code, report_type, tenant_id, name_az, description_az, route_to_role)
VALUES
    ('DAILY_OPEN_GENERAL', 'DAILY_OPEN', NULL, 'Açılış Yoxlaması',
     'Kassa, təhlükəsizlik-sistemi, təmizlik bəndlərini əhatə edən ümumi '
     'açılış kateqoriyası.', NULL),
    ('DAILY_CLOSE_GENERAL', 'DAILY_CLOSE', NULL, 'Bağlanış Yoxlaması',
     'Kassa, təhlükəsizlik-sistemi, təmizlik bəndlərini əhatə edən ümumi '
     'bağlanış kateqoriyası.', NULL)
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. `uq_field_reports_once_per_day` — DB İKİNCİ QAT (bax fayl başlığı)
-- ---------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS uq_field_reports_once_per_day
    ON field_reports (tenant_id, store_id, type, ((created_at AT TIME ZONE 'UTC')::date))
    WHERE type IN ('DAILY_OPEN', 'DAILY_CLOSE');

COMMENT ON INDEX uq_field_reports_once_per_day IS
    'Faza 4.1: mağaza+gün başına YALNIZ BİR DAILY_OPEN/DAILY_CLOSE hesabatı '
    '— domen yoxlamasının (`find_for_store_and_day`) DB-səviyyəli zəmanəti '
    '(`fine_management.py`-dəki idempotentlik açarı ilə EYNİ naxış). Siyahı '
    'HARDCODE-dur — Postgres qismən indeks şərti başqa cədvələ (`field_'
    'report_types.once_per_day`) sorğu ata bilməz. YENİ "gündə-bir" şablonu '
    'əlavə edilsə, BU İNDEKS DƏ YENİLƏNMƏLİDİR (migrations/097).';

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- İndeks/sütunlar silinsə DAILY_OPEN/DAILY_CLOSE hesabatları YENƏ mövcud
-- qalır (SEED sətirləri DƏ silinməli, əks halda `once_per_day` sütunu
-- YOXSA şablon adi checklist kimi davranar — bu, data itkisi DEYİL, YALNIZ
-- "gündə bir" qaydasının GERİ QAYITMASIDIR).
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP INDEX IF EXISTS uq_field_reports_once_per_day;
--   DELETE FROM field_report_categories WHERE code IN ('DAILY_OPEN_GENERAL', 'DAILY_CLOSE_GENERAL');
--   DELETE FROM field_report_types WHERE code IN ('DAILY_OPEN', 'DAILY_CLOSE');
--   ALTER TABLE tasks DROP COLUMN IF EXISTS source;
--   ALTER TABLE field_report_types DROP COLUMN IF EXISTS once_per_day;
-- COMMIT;
-- ===========================================================================
