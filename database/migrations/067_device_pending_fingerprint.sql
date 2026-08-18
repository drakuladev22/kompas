-- ===========================================================================
-- 067 — GÖZLƏYƏN APARAT İZİ (`registered_devices.pending_fingerprint`)
-- ===========================================================================
-- Tarix : 2026-08-18
-- Səbəb : Aparat izi uyğunsuzluğu HƏLL EDİLƏ BİLMİRDİ.
--
--         `verify_fingerprint()` uyğunsuzluğu qeydə alır, lakin saxlanmış izi
--         QƏSDƏN dəyişmir (köçürməni sükutla qanuniləşdirməmək üçün). İzi
--         qəbul edən metod isə YOX idi — `approve()` yalnız
--         `PENDING_APPROVAL` vəziyyətindən işləyir. Nəticə üç qüsur idi:
--
--             * legitim disk təmirindən sonra xəbərdarlıq ƏBƏDİ qalırdı;
--             * cihaz hər açılışda qeydiyyatdan keçdiyi üçün EYNİ audit
--               sətri hər dəfə təkrar yazılır və həqiqi İKİNCİ dəyişikliyi
--               həmin yığının içində gizlədirdi;
--             * admin-in yeganə alternativi işlək cihazı BLOKLAMAQ idi —
--               yəni səhv cavab.
--
--         `entities/registered_device.py` başlığı «qərarı adam verir» deyir;
--         bu sütun həmin cümlənin birinci şərtidir — adam qəbul edəcəyi
--         dəyəri GÖRMƏLİDİR.
--
-- ---------------------------------------------------------------------------
-- NİYƏ AYRI SÜTUN, NİYƏ `hardware_fingerprint`-in ÜSTÜNƏ YAZILMIR
-- ---------------------------------------------------------------------------
-- Müşahidə olunan izi birbaşa `hardware_fingerprint`-ə yazmaq detektoru ləğv
-- edərdi: `device.json`-u başqa maşına köçürən adam BİR audit sətrindən sonra
-- «qanuni» olardı və sistem bir daha xəbərdarlıq verməzdi. Ayrı sütunda dəyər
-- GÖZLƏYİR; keçid yalnız admin-in açıq qərarı ilə baş verir və o qərar
-- `DEVICE_FINGERPRINT_ACCEPTED` audit yazısında kim/nə vaxt/hansı dəyər kimi
-- qalır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `NULL`, NİYƏ BOŞ SƏTİR DEFOLTU DEYİL
-- ---------------------------------------------------------------------------
-- `NULL` = «gözləyən dəyişiklik yoxdur». Boş sətir defoltu bu vəziyyəti
-- «boş iz gözləyir»dən ayırd etməyə imkan verməzdi və admin ekranı HƏR cihaz
-- üçün həll ediləsi xəbərdarlıq göstərərdi — yəni siqnal dərhal dəyərini
-- itirərdi.
--
-- İndeks QOYULMUR: cihaz sayı kirayəçi başına onlarladır və ekran onsuz da
-- bütün sətirləri oxuyur (`list_all`). İndeks yazma qiymətini artırar,
-- oxunuşu isə ölçülə bilən qədər sürətləndirməzdi.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

ALTER TABLE registered_devices
    ADD COLUMN IF NOT EXISTS pending_fingerprint TEXT;

COMMENT ON COLUMN registered_devices.pending_fingerprint IS
    'Müşahidə olunan, lakin admin tərəfindən hələ QƏBUL EDİLMƏMİŞ aparat izi. '
    'NULL = gözləyən dəyişiklik yoxdur. Qəbul `accept_fingerprint()` ilə olur '
    've dəyəri `hardware_fingerprint`-ə köçürür (migrations/067).';

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- Sütunu silmək gözləyən qərarları itirir: uyğunsuzluğu görülmüş, lakin hələ
-- təsdiqlənməmiş cihazlar yenidən «səbəbsiz xəbərdarlıq» vəziyyətinə düşür.
-- Audit sətirləri qalır, ona görə itki bərpa oluna bilər — lakin əl ilə.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   ALTER TABLE registered_devices DROP COLUMN IF EXISTS pending_fingerprint;
-- COMMIT;
