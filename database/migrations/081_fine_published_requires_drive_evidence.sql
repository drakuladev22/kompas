-- ===========================================================================
-- 081 — T3 (DEEP-GAP dövrə 4): NƏŞR OLUNMUŞ MANUAL_CAMERA CƏRİMƏ HƏQİQƏTƏN
--   DRIVE-A YÜKLƏNMİŞ SÜBUT TƏLƏB EDİR
-- ===========================================================================
-- Tarix : 2026-08-22
-- Səbəb : `domain2`-nin DEEP-GAP tapıntısı, `team-lead`-in TƏSDİQ etdiyi qərar.
--         `chk_fine_manual_requires_evidence` (migrations/002) YARADILIŞ
--         anında `photo_evidence_url IS NOT NULL OR evidence_drive_file_id
--         IS NOT NULL OR evidence_upload_status = 'PENDING'` deyir.
--         MANUAL_CAMERA axınında `photo_evidence_url` LOKAL NÖVBƏ AÇARINI
--         saxlayır (`fine_entry.py` şəkli əvvəlcə diskə/spool-a yazır,
--         `upload_queue.py`) — yəni "sütun dolu" şərti şəkil HEÇ VAXT Drive-a
--         getməsə də ödənilir. Növbə faylı (`%PROGRAMDATA%\KompasOS\data`)
--         admin hüququ OLMADAN silinə bilir → sübutsuz cərimə NƏŞR oluna
--         (işçiyə görünə, export-a düşə) bilirdi.
--
--         Tətbiq qatının qapısı (T3, `MonthlyFineReviewUseCase` +
--         `FineEvidenceSyncReader.unsynced_evidence_ids`, migrations/080-dən
--         sonra `infra2`-nin yazdığı `PostgresFineRepository` adapteri) bunu
--         ARTIQ tutur. Bu miqrasiya İKİNCİ qatdır (CLAUDE.md §5) — ekranı
--         yan keçən skript üçün.
--
-- ---------------------------------------------------------------------------
-- NİYƏ YARADILIŞ ANI YOX, NƏŞR ANI
-- ---------------------------------------------------------------------------
-- `evidence_drive_file_id` cərimə yaradılan anda hələ YOXDUR (upload asinxron
-- növbədə gedir, `migrations/002`-nin öz izahı) — yaradılış anına qadağa
-- qoysaq HƏR MANUAL_CAMERA cərimə INSERT-i çökərdi. Ona görə şərt YALNIZ
-- `status IN ('PUBLISHED', 'REDUCED')`-ə aiddir — `EXPORTABLE_STATUSES`
-- (`domain/entities/fine.py`) ilə eynidir, çünki sübut məhz EXPORT olunan
-- (real pul kəsintisi) sətirdə lazımdır.
--
-- ---------------------------------------------------------------------------
-- KÖHNƏ SƏTİRLƏR — `team-lead`-in QƏRARI (Variant A, ölçmə mümkün olmadığı
-- üçün)
-- ---------------------------------------------------------------------------
-- Bu maşında canlı baza əlçatan deyil (`DATABASE_URL` yoxdur, inteqrasiya
-- testləri məhz bu səbəbdən atlanır) — miqrasiya 002-dən ƏVVƏLKİ (sübutu
-- Supabase Storage URL-ində olan) MANUAL_CAMERA sətirlərinin sayı ÖLÇÜLƏ
-- BİLMİR. `NOT VALID` bu sətirləri yoxlamır, LAKİN onlara SONRAKI hər
-- `UPDATE`-i (export işarəsi, etiraz nəticəsi, `REDUCED`-a keçid) bloklayardı
-- — sükutlu deyil, ay sonu üzə çıxan AÇIQ çökmə.
--
-- Qərar: məhdudiyyətə İRS sətirləri açıq buraxan budaq əlavə olunur —
-- `photo_evidence_url LIKE 'http%'`. 002-dən ƏVVƏLKİ sətirlərin sübut
-- istinadı HTTP URL-idir (Supabase Storage), YENİ spool açarı isə DEYİL
-- (`fine_entry.py` lokal fayl yolu/UUID yazır, `http` ilə BAŞLAMIR) — budaq
-- ÖZÜNÜ SƏNƏDLƏŞDİRİR: yalnız irs sətirləri buraxır, YENİ MANUAL_CAMERA
-- sətri bu yolla qadağanı yan keçə BİLMƏZ (`fine_entry.py` heç vaxt HTTP
-- URL-i `photo_evidence_url`-a yazmır — o, YALNIZ lokal növbə açarıdır).
--
-- ---------------------------------------------------------------------------
-- 015-in ÖZÜ DƏYİŞMİR, YENİ MİQRASİYA YARADILIR
-- ---------------------------------------------------------------------------
-- `015_race_condition_guards.sql` ARTIQ TƏTBİQ OLUNMUŞ miqrasiyadır —
-- checksum-u dəyişməmək üçün 013→048/080 naxışı təkrarlanır: YENİ `DROP
-- CONSTRAINT` + `ADD CONSTRAINT` cütü, 015-in ÜÇ budağını SAXLAYARAQ,
-- DÖRDÜNCÜ budağı (evidence) ƏLAVƏ EDİR. Saga kompensasiyasının `REVERSED
-- AND published_at IS NULL` istisnası İTİRİLMİR — itsəydi `publish_batch`-in
-- DISCARD qolu və `LeaveVerificationUseCase` kompensasiyası çökərdi.
--
-- `schema.sql`-in İNLİNE `chk_fine_published`-i BU MİQRASİYA ilə
-- YENİLƏNMİR: `evidence_drive_file_id` sütunu `schema.sql`-in bazis `fines`
-- tərifində YOXDUR (CLAUDE.md §7 — "schema.sql miqrasiya SÜTUNLARINI ehtiva
-- etmir", sütun YALNIZ migrations/002-dədir). Referans etsəydi, `schema.sql`
-- tək başına quraşdırma "column does not exist" ilə ÇÖKƏRDİ. Bu, `chk_fine_
-- manual_requires_evidence`-in ÖZÜNDƏ ARTIQ mövcud olan EYNİ vəziyyətdir
-- (schema.sql-in nüsxəsi 002-dən ƏVVƏLKİ, dar versiyadır) — `fines` cədvəli
-- `test_schema_migration_parity.py::_pairs()`-in müqayisə etdiyi adlar
-- siyahısına HEÇ VAXT DÜŞMÜR (`_TABLE` yalnız `CREATE TABLE`-i tutur,
-- migrasiyalar isə `ALTER TABLE` işlədir — parity boşluğu QƏSDLİDİR, D4
-- audit qeydinin "ALTER TABLE ADD COLUMN QƏSDLİ dizayndır" bəndinin EYNİSİ).
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

ALTER TABLE fines DROP CONSTRAINT IF EXISTS chk_fine_published;
ALTER TABLE fines ADD CONSTRAINT chk_fine_published
    CHECK (
        (status = 'PENDING_REVIEW'
            OR (published_at IS NOT NULL AND appeal_window_closes_at IS NOT NULL)
            OR (status = 'REVERSED' AND published_at IS NULL))
        AND (status NOT IN ('PUBLISHED', 'REDUCED')
            OR source <> 'MANUAL_CAMERA'
            OR evidence_drive_file_id IS NOT NULL
            -- İRS SƏTİR İSTİSNASI (yuxarı şərh): 002-dən ƏVVƏLKİ sübut
            -- HTTP URL-idir, YENİ spool açarı DEYİL.
            OR photo_evidence_url LIKE 'http%')
    );

COMMENT ON CONSTRAINT chk_fine_published ON fines IS
    'Nəşr olunmuş cərimənin HƏM anı, HƏM etiraz son tarixi olmalıdır (015). '
    'T3 (081): EXPORTABLE statusda (PUBLISHED/REDUCED) MANUAL_CAMERA cərimə '
    'HƏQİQƏTƏN Drive-a yüklənmiş sübut (evidence_drive_file_id) tələb edir — '
    'photo_evidence_url MANUAL_CAMERA axınında lokal növbə açarıdır, Drive-a '
    'çatdığını sübut etmir. `LIKE ''http%''` budağı YALNIZ 002-dən ƏVVƏLKİ '
    'irs sətirlərini buraxır (o zaman sübut Supabase Storage URL-i idi).';

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--   ALTER TABLE fines DROP CONSTRAINT IF EXISTS chk_fine_published;
--   ALTER TABLE fines ADD CONSTRAINT chk_fine_published
--       CHECK (status = 'PENDING_REVIEW'
--           OR (published_at IS NOT NULL AND appeal_window_closes_at IS NOT NULL)
--           OR (status = 'REVERSED' AND published_at IS NULL));
-- COMMIT;
-- ===========================================================================
