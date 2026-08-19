-- ===========================================================================
-- 074 — D7: MANUAL CƏRİMƏNİN İKİQAT GÖNDƏRİŞDƏN QORUNMASI
-- ===========================================================================
-- Tarix : 2026-08-19
-- Səbəb : D7 audit tapıntısı (dövrə debatı, `domain`) — `ManualFineUseCase.
--         issue()`-nin idempotentlik qoruması TAMAMİLƏ yox idi: hər çağırış
--         `fine_id or new_fine_id()` ilə yeni TƏSADÜFİ ID alırdı. DB-də
--         yeganə unikal qapı (`uq_fines_one_live_auto_delay_per_leave`,
--         schema.sql) YALNIZ `AUTO_DELAY` mənbəyini örtür — `MANUAL_CAMERA`
--         üçün nə domen, nə DB qapısı var idi. Nəticə: iki klik və ya
--         şəbəkə təkrarı EYNİ hadisəyə İKİ keçərli cərimə yaza bilirdi —
--         cərimə REAL PUL kəsintisidir, bu, satış blokeri idi.
--
--         `domain` bunu (`ManualFineUseCase.issue(idempotency_key=...)`,
--         `Fine.idempotency_key`, `DuplicateFineSubmissionError`) artıq
--         yazıb. Bu miqrasiya DB YARISINI (sütun + qismən unikal indeks)
--         verir — ƏSAS zəmanət BURADANDIR, tətbiq qatındakı `_find_recent_
--         duplicate()` YALNIZ sürətli, qeyri-mütləq yoxlamadır (CLAUDE.md
--         §5: hər qayda iki yerdə).
--
-- ---------------------------------------------------------------------------
-- NİYƏ `(tenant_id, photo_evidence_url, fine_type_id)` YOX,
-- `idempotency_key` AYRICA SÜTUN
-- ---------------------------------------------------------------------------
-- `infra`-nın ilkin texniki tövsiyəsi (`photo_evidence_url` + `fine_type_id`
-- cütünə görə unikallıq) `domain` tərəfindən RƏDD EDİLDİ: GUI forma AÇILAN
-- anda BİR açar yaradır (`ManualFineUseCase.issue()` başlığı) və həmin açar
-- FORMANIN ÖZÜNƏ bağlıdır, foto seçiminə YOX — operator eyni formada foto-nu
-- DƏYİŞSƏ belə (yenidən çəksə) İKİQAT GÖNDƏRİŞ yenə DƏ eyni açarla gedir.
-- Əks halda foto dəyişəndə qoruma sükutla YOX olardı.
--
-- ---------------------------------------------------------------------------
-- NİYƏ QİSMƏN İNDEKS (`WHERE source = 'MANUAL_CAMERA' AND ... IS NOT NULL`)
-- ---------------------------------------------------------------------------
-- `AUTO_DELAY` sətirləri bu sütunu HEÇ VAXT doldurmur (Saga-nın öz qapısı
-- artıq var, `uq_fines_one_live_auto_delay_per_leave`) — onları TAM indeksə
-- qoşmaq iki müstəqil qoruma mexanizmini QARIŞDIRARDI. `NULL` sərbəstdir:
-- Postgres UNIQUE indeksində `NULL`-lar bir-biri ilə TOQQUŞMUR, ona görə
-- köhnə (bu miqrasiyadan ƏVVƏLKİ) sətirlər VƏ digər mənbələr POZULMUR.
--
-- ---------------------------------------------------------------------------
-- İDEMPOTENT
-- ---------------------------------------------------------------------------
-- `ADD COLUMN IF NOT EXISTS`, `CREATE UNIQUE INDEX IF NOT EXISTS`.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

ALTER TABLE fines
    ADD COLUMN IF NOT EXISTS idempotency_key UUID;

COMMENT ON COLUMN fines.idempotency_key IS
    'D7: GUI forma AÇILAN anda BİR dəfə yaranan açar (hər klikdə YOX) — '
    'ikiqat manual cərimə göndərişinin qarşısını alır. Yalnız MANUAL_CAMERA '
    'üçün mənalıdır (bax uq_fines_manual_camera_idempotency_key, '
    'migrations/074).';

CREATE UNIQUE INDEX IF NOT EXISTS uq_fines_manual_camera_idempotency_key
    ON fines (tenant_id, idempotency_key)
    WHERE source = 'MANUAL_CAMERA' AND idempotency_key IS NOT NULL;

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP INDEX IF EXISTS uq_fines_manual_camera_idempotency_key;
--   ALTER TABLE fines DROP COLUMN IF EXISTS idempotency_key;
-- COMMIT;
