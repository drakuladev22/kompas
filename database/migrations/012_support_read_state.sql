-- ===========================================================================
-- MIGRATION 012 — DƏSTƏK CHAT-İ: OXUNMA VƏZİYYƏTİ (TENANT TƏRƏFİ)
-- ===========================================================================
-- Tarix : 2026-08-10
-- Səbəb : Bölmə 8 diskret dəstək chat-i üçün deyir: "Yeni cavab gəldikdə
--         yalnız kiçik, nəzakətli bir bildiriş nöqtəsi (badge) görünür".
--         Badge-in nə vaxt SÖNƏCƏYİNİ bilmək üçün "istifadəçi haraya qədər
--         oxuyub" məlumatı lazımdır — `support_tickets`-də belə sütun yox idi,
--         yəni badge ya həmişə yanardı, ya heç vaxt.
--
-- İdempotentdir — təkrar icra təhlükəsizdir. DOWN faylın sonundadır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ TICKET SƏVİYYƏSİNDƏ, MESAJ SƏVİYYƏSİNDƏ DEYİL
-- ---------------------------------------------------------------------------
-- Mesaj-səviyyəli "oxundu" bayrağı (hər `support_messages` sətrində) daha
-- dəqiq görünür, amma burada faydasızdır: chat paneli AÇILANDA bütün thread
-- göstərilir, yəni hamısı eyni anda oxunur. Tək timestamp eyni sualı bir
-- sütunla cavablandırır və hər mesaja yazma yükü yaratmır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ TENANT TƏRƏFİ ÜÇÜNDÜR
-- ---------------------------------------------------------------------------
-- Bu sütun MÜŞTƏRİNİN oxuma vəziyyətidir. Hazırlayıcı tərəfin SLA izləməsi
-- (`first_response_at`) ayrıca sütundur və bu, onu ƏVƏZ ETMİR — ikisi fərqli
-- tərəflərin fərqli sualına cavab verir.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

ALTER TABLE support_tickets
    ADD COLUMN IF NOT EXISTS customer_last_read_at TIMESTAMPTZ;

COMMENT ON COLUMN support_tickets.customer_last_read_at IS
    'Tenant istifadəçisinin chat panelini son dəfə açdığı an. Bundan SONRA '
    'gələn hazırlayıcı mesajları "oxunmamış" sayılır (bölmə 8 badge qaydası). '
    'NULL = heç vaxt açılmayıb → bütün hazırlayıcı mesajları oxunmamışdır.';

-- Badge sorğusu hər panel açılışında işləyir — indekssiz o, bütün mesaj
-- cədvəlini skan edərdi.
CREATE INDEX IF NOT EXISTS idx_support_messages_unread
    ON support_messages (ticket_id, created_at)
    WHERE is_from_developer;

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün)
-- ===========================================================================
-- BEGIN;
-- DROP INDEX IF EXISTS idx_support_messages_unread;
-- ALTER TABLE support_tickets DROP COLUMN IF EXISTS customer_last_read_at;
-- COMMIT;
