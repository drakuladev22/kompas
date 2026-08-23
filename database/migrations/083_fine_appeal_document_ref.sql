-- ===========================================================================
-- 083 — UX-4: CƏRİMƏ ETİRAZINA ƏLAVƏ EDİLƏN SƏNƏD (`fine_appeals.document_ref`)
-- ===========================================================================
-- Tarix : 2026-08-23
-- Səbəb : Kiosk ekranında «Sənəd (istəyə görə)» sahəsi VAR
--         (`screens/group_f.py`) və seçilmiş faylın yolu `payload["document"]`
--         ilə kontrollerə çatır — SONRA İSƏ HEÇ YERƏ getmir: nə cədvəldə
--         sütun, nə yükləmə növbəsində sahib tipi mövcud idi. Yəni işçi
--         həkim arayışını əlavə edir, «göndər» düyməsini basır, ekran isə
--         onu SÜKUTLA atır.
--
--         Nəticə pul mübahisəsində sübutun itməsidir: etiraz pəncərəsi 72
--         saatdır (bölmə 4) və HR_Admin qərarı məhz həmin sənədə baxaraq
--         verməli idi. İşçi «sənədi göndərdim» deyir, ekranda isə heç nə
--         görünmür — bu, sistemin ona verdiyi yeganə müdafiə vasitəsinin
--         işləməməsi deməkdir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `document_ref`, NİYƏ `document_url` DEYİL
-- ---------------------------------------------------------------------------
-- Sütuna yazılan dəyər URL DEYİL — `StorageReference.cache_key` formatıdır:
-- `GOOGLE_DRIVE:<connection_id>:<file_id>`. Səbəb `value_objects/storage.py`
-- başlığındadır: Drive faylları QƏSDƏN private saxlanılır («linki olan hər
-- kəs» paylaşımı YOXDUR), ona görə açıla bilən bir ünvan MÖVCUD DEYİL.
--
-- Köhnə `fines.photo_evidence_url` məhz bu səhvin qalığıdır və layihə ondan
-- artıq İMTİNA edib (CLAUDE.md §9). Yeni sütuna `_url` adı vermək həmin
-- səhvi təkrarlayardı: növbəti oxucu dəyəri brauzerə yapışdırmağa çalışar,
-- alınmayanda isə «məlumat korlanıb» qərarına gələrdi. Qonşu iki sütun
-- EYNİ formatı EYNİ ad naxışı ilə saxlayır: `employee_documents.file_ref`,
-- `support_messages.attachment_ref`.
--
-- ---------------------------------------------------------------------------
-- NİYƏ TƏK MƏTN SÜTUNU, NİYƏ `fines`-DƏKİ KİMİ İKİ SÜTUN DEYİL
-- ---------------------------------------------------------------------------
-- `fines` istinadı İKİ sütunda saxlayır (`evidence_drive_file_id` +
-- `evidence_drive_connection_id`, migrations/002), çünki orada sorğular
-- bağlantı üzrə süzgəcdən keçir (hesabat, köçürmə, sağlamlıq yoxlaması).
-- Etiraz sənədi belə süzülmür — o, YALNIZ bir etiraz kartını açanda oxunur.
-- Tək sütun ona görə seçildi ki, `employee_documents`/`support_messages`
-- ilə eyni oxucu (`StorageReference.from_cache_key`) işlədilə bilsin: üçüncü
-- format üçüncü parser deməkdir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `NULL` İCAZƏLİDİR
-- ---------------------------------------------------------------------------
-- Sahə ekranda AÇIQ şəkildə «(istəyə görə)» yazılıb — sənədsiz etiraz tam
-- qanunidir (məs. «kamera səhv işçini göstərib»). `NOT NULL` qoymaq həmin
-- etirazları DB səviyyəsində bloklayardı, boş sətir defoltu isə «sənəd var,
-- amma boşdur» vəziyyəti ilə qarışardı.
--
-- İNDEKS QOYULMUR: sütun heç bir süzgəcdə iştirak etmir, yalnız açılan
-- kartda oxunur (`WHERE id = ...` onsuz da PRIMARY KEY yolu ilə gedir).
--
-- ---------------------------------------------------------------------------
-- `schema.sql` YENİLƏNMİR — QƏSDƏN (CLAUDE.md §7)
-- ---------------------------------------------------------------------------
-- Sütun QATLANIR: bazis sxem + miqrasiyalar ardıcıl tətbiq olunur. Bazis
-- sxem YALNIZ QAYDA (trigger/indeks/constraint) dəyişəndə yenilənir, çünki
-- qayda qatlanmır — üzərinə yazılır. Burada yeni qayda yoxdur.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

ALTER TABLE fine_appeals
    ADD COLUMN IF NOT EXISTS document_ref TEXT;

COMMENT ON COLUMN fine_appeals.document_ref IS
    'Etiraza əlavə edilən sənədin (həkim arayışı, sərəncam, ezamiyyət əmri) '
    'Drive istinadı — `StorageReference.cache_key` formatı '
    '(`GOOGLE_DRIVE:<connection_id>:<file_id>`), URL DEYİL: fayllar private '
    'saxlanılır. NULL = sənəd əlavə edilməyib (sahə istəyə görədir). Dəyəri '
    'fon yükləyicisi yazır (`UploadOwnerType.FINE_APPEAL` → '
    '`PostgresFineAppealRepository.attach_document`), etiraz yaradılan anda '
    'fayl hələ Drive-da olmur (migrations/083).';

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- Sütunu silmək YÜKLƏNMİŞ sənədlərin izini itirir: fayl Drive-da qalır,
-- lakin onun HANSI etiraza aid olduğu heç yerdən bərpa oluna bilməz —
-- `evidence_uploads` növbə sətri `purge_uploaded()` ilə onsuz da silinir.
-- Yəni DOWN yalnız miqrasiyanın SƏHVƏN tətbiqi (heç bir sənəd yüklənməmiş
-- vəziyyət) üçündür.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   ALTER TABLE fine_appeals DROP COLUMN IF EXISTS document_ref;
-- COMMIT;
-- ===========================================================================
