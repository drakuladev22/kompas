-- ===========================================================================
-- 073 — SEC-8: `fines.review_batch_id` FK-Sİ ƏLAVƏ OLUNUR
-- ===========================================================================
-- Tarix : 2026-08-19
-- Səbəb : SEC-8 audit tapıntısı (dövrə debatı, `domain` FK boşluğunu tapdı).
--         `fines.review_batch_id UUID` (migrations/003) heç vaxt
--         `monthly_fine_review_batches(id)`-ə FK daşımayıb — sütun
--         `PostgresFineRepository.save()`/`fine_to_params`/`fine_from_row`-da
--         (bu miqrasiyadan ƏVVƏLKİ commit-də düzəldildi) HEÇ VAXT
--         yazılmadığı üçün bu, PRAKTİKİ TƏHLÜKƏ YARATMIRDI, lakin indi
--         sütun FAKTİKİ dolduğu üçün istinad bütövlüyü qorunmalıdır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ ORPHAN YOXLAMASI TƏLƏB OLUNMUR (yoxlanıldı, sənədləşdirilir)
-- ---------------------------------------------------------------------------
-- Adətən bu tip FK əlavəsindən ƏVVƏL mövcud yararsız dəyərləri yoxlamaq
-- MƏCBURİDİR. Burada ehtiyac YOXDUR — bütün kod bazası (`src/`) axtarıldı:
-- bu miqrasiyadan ƏVVƏLKİ HEÇ BİR kod yolu `review_batch_id`-i yazmayıb
-- (`PostgresFineRepository.save()`-in INSERT/UPDATE siyahısında sütun
-- YOX idi — bax əvvəlki commit-in şərhi). Yəni istehsalatda mövcud olan
-- HƏR sətirdə bu sütun MÖVCUD OLARAQ `NULL`-dur, `NULL` isə FK-ni HEÇ VAXT
-- pozmur (yoxlama yalnız QEYRİ-NULL dəyərlərə tətbiq olunur). Orphan sətir
-- RİYAZİ OLARAQ mümkün deyil.
--
-- ---------------------------------------------------------------------------
-- NİYƏ ADİ (DEFERRABLE OLMAYAN) FK TƏHLÜKƏSİZDİR
-- ---------------------------------------------------------------------------
-- `controllers/fine_review.py` (`ui`) yazı sırası: `publish_batch(...)`
-- (batch sətrini `_record()` daxilində DƏRHAL yazır) → hər cərimə üçün
-- `session.uow.fines.save(...)` → `session.commit()`. Batch sətri HƏR
-- ZAMAN eyni tranzaksiyada, fines-dən ƏVVƏL yazılır — Postgres eyni
-- tranzaksiya daxilində "özünün yazdığını" dərhal görür, ona görə adi
-- (immediate) FK bu axını POZMUR. `DEFERRABLE`-ə ehtiyac yoxdur.
--
-- ---------------------------------------------------------------------------
-- İDEMPOTENT
-- ---------------------------------------------------------------------------
-- `pg_constraint`-də yoxlama — migrations/062-nin `chk_attendance_time_
-- trust_level` naxışı. `ON DELETE SET NULL`: partiya YOXLANILAN sətir SİLİNMİR
-- (`monthly_fine_review_batches`-in heç bir DELETE yolu yoxdur — audit
-- sətridir), lakin gələcəkdə əl ilə təmizləmə aparılsa, cərimənin ÖZÜ
-- (real pul qeydidir) FK-nin `RESTRICT`/`CASCADE`-i ilə silinməyə MƏCBUR
-- edilməməli — `SET NULL` yalnız "hansı partiyada" izini itirir, cəriməni YOX.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_fines_review_batch'
    ) THEN
        ALTER TABLE fines
            ADD CONSTRAINT fk_fines_review_batch
            FOREIGN KEY (review_batch_id)
            REFERENCES monthly_fine_review_batches(id)
            ON DELETE SET NULL;
    END IF;
END
$$;

COMMENT ON COLUMN fines.review_batch_id IS
    'Bu cərimənin nəşr/rədd qərarının aid olduğu Aylıq İcmal partiyası. '
    'FK migrations/073-də əlavə olunub (SEC-8) — sütunun özü migrations/003-də '
    'yaranıb, lakin heç vaxt yazılmayıb (bax `PostgresFineRepository.save`).';

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--   ALTER TABLE fines DROP CONSTRAINT IF EXISTS fk_fines_review_batch;
-- COMMIT;
