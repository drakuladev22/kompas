-- ===========================================================================
-- 071 — BİLDİRİŞ PANELİ: PRİORİTETLİ SIRA ÜÇÜN İNDEKS (D8)
-- ===========================================================================
-- Tarix : 2026-08-19
-- Səbəb : `PostgresNotificationRepository.list_for_recipient()`
--         (`notification_repositories.py`) `ORDER BY created_at DESC LIMIT 50`
--         işlədirdi — `is_critical`/`read_at` heç bir rol oynamırdı. 50-dən
--         çox bildirişi olan istifadəçidə KÖHNƏ, hələ OXUNMAMIŞ və ya KRİTİK
--         sətir YENİ, ADİ sətirlər tərəfindən pəncərədən İTƏLƏNİRDİ —
--         pagination olmadığı üçün bir daha HEÇ VAXT görünmürdü və
--         `mark_read` ona çata bilmirdi.
--
--         Düzəliş (`notification_repositories.py`) sıranı
--         `(read_at IS NULL) DESC, is_critical DESC, created_at DESC`-ə
--         dəyişdi. `PANEL_LIMIT` (50) DƏYİŞMİR — CLAUDE.md-də "Root parametri
--         DEYİL" siyahısındadır (620px panel hündürlüyünün nəticəsi).
--
-- ---------------------------------------------------------------------------
-- NİYƏ SCHEMA.SQL-Ə YOX, YALNIZ MİQRASİYAYA
-- ---------------------------------------------------------------------------
-- Bu, MÖVCUD bir indeksin YENİDƏN YAZILMASI DEYİL (müq. `idx_notifications_
-- unread`-in miqrasiya 007-də əvəzlənməsi) — TAMAMİLƏ YENİ indeksdir. Yeni
-- struktur elementləri (sütun, indeks) CLAUDE.md §7-nin naxışına görə
-- YALNIZ miqrasiya ilə gəlir; bazis sxem "ardıcıl tətbiq" zəncirinin BİRİNCİ
-- halqasıdır, hər yeni addımı təkrarlamır (schema.sql migrasiya sütunlarını
-- da ehtiva etmir — eyni prinsip).
--
-- ---------------------------------------------------------------------------
-- SÜTUN SIRASI SORĞUNUN ÖZÜ İLƏ HƏRFƏN EYNİDİR
-- ---------------------------------------------------------------------------
-- `(read_at IS NULL)` ifadə-indeksdir (expression index) — Postgres bunu
-- YALNIZ sorğuda EYNİ ifadə HƏRFƏN göründükdə tanıyır. Ona görə indeks
-- definisiyası `notification_repositories.py::list_for_recipient`-dəki
-- `ORDER BY` ilə SÖZ-BƏ-SÖZ üst-üstə düşməlidir — biri dəyişəndə digəri də
-- dəyişməlidir (CLAUDE.md §5-in "hər qayda iki yerdə" prinsipinin SORĞU
-- SƏVİYYƏSİNDƏ analoqu).
--
-- ---------------------------------------------------------------------------
-- İDEMPOTENT
-- ---------------------------------------------------------------------------
-- `CREATE INDEX IF NOT EXISTS` — təkrar icra heç nə dəyişmir.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

CREATE INDEX IF NOT EXISTS idx_notifications_panel_priority
    ON notifications (tenant_id, (read_at IS NULL) DESC, is_critical DESC, created_at DESC);

COMMENT ON INDEX idx_notifications_panel_priority IS
    'list_for_recipient()-in ORDER BY-ı ilə HƏRFƏN eyni sütun sırası — '
    'panel LIMIT 50 dolanda əvvəlcə oxunmuş+adi sətirlər atılsın deyə '
    '(migrations/071, D8).';

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP INDEX IF EXISTS idx_notifications_panel_priority;
-- COMMIT;
