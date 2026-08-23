-- ===========================================================================
-- 087 — DÖRD yeni istisna mənbəyi: HR-1, HR-2, HR-3, UX-7 (DEEP-GAP)
-- ===========================================================================
-- ---------------------------------------------------------------------------
-- SEED OLMADAN QAYDA TƏSİRSİZDİR — BU, «GÖZƏLLƏŞDİRMƏ» DEYİL
-- ---------------------------------------------------------------------------
-- `ExceptionEngineUseCase` tapıntını `exceptions.source_code` ilə yazır və o
-- sütun `exception_sources(code)`-a `FOREIGN KEY` ilə bağlıdır. Kataloqda
-- sətir yoxdursa yazı POZUNTU verir və motor həmin qaydanı sükutla atır —
-- yəni qayda kodda MÖVCUD, testdə YAŞIL, istehsalatda İSƏ TƏSİRSİZ qalır
-- (`open_shift_market.py` başlığındakı eyni tələ).
--
-- ---------------------------------------------------------------------------
-- CİDDİYYƏT DƏYƏRLƏRİ — NİYƏ MƏHZ BUNLAR
-- ---------------------------------------------------------------------------
-- Dəyər KATALOQDADIR, yəni Root sonradan dəyişə bilir; buradakı seçim
-- BAŞLANĞIC nöqtəsidir:
--   * `FINE_APPEAL_UNANSWERED` → HIGH. İşçinin HÜQUQU cavabsız qalır və
--     cərimə mübahisə kilidinə görə export-dan kənarda ilişir — yəni həm
--     insan, həm pul tərəfi dayanır.
--   * `FINE_HELD_INACTIVE_EMPLOYEE` → HIGH. İşçi ARTIQ getdiyi üçün pəncərə
--     gözləməklə açılmır: gecikmə problemi öz-özünə həll etmir.
--   * `FINE_REVIEW_OVERDUE` → MEDIUM. Sətir hələ AXINDADIR (nəşr gözləyir) və
--     hədd Root açarındandır — bu, pozuntu deyil, ritmin sürüşməsidir.
--   * `FACE_ENROLLMENT_OVERDUE` → MEDIUM. Təhlükə siqnalı DEYİL, proses
--     boşluğudur: qeydiyyat self-service olmadığı üçün işçinin özü onu
--     bağlaya bilmir (bax `OverdueFaceEnrollmentRule` başlığı).
--
-- ---------------------------------------------------------------------------
-- `tenant_id = NULL` — GLOBAL KATALOQ SƏTRİ (047 naxışı)
-- ---------------------------------------------------------------------------
-- Mənbə TƏRİFİ məhsulun bir hissəsidir, kirayəçinin konfiqurasiyası deyil.
-- Kirayəçi onu `is_active` ilə söndürə bilir — sətri kirayəçi-başına
-- çoxaltmaq isə eyni tərifin N nüsxəsini yaradardı.
--
-- İDEMPOTENT: `ON CONFLICT (code) DO NOTHING` — təkrar icrada Root-un
-- dəyişdirdiyi ciddiyyət ÜSTÜNDƏN YAZILMIR (039–047 ilə eyni qayda).
-- Yeni trigger/funksiya YOXDUR, yəni `schema.sql` pariteti toxunulmur (§7).
-- DOWN bloku sonda şərh içindədir.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

INSERT INTO exception_sources (code, tenant_id, name_az, description_az, default_severity)
VALUES
    ('FINE_APPEAL_UNANSWERED', NULL, 'Cavabsız cərimə etirazı',
     'İşçi cəriməyə etiraz edib, etiraz pəncərəsi bağlanıb və HR hələ də '
     'qərar verməyib (HR-1). Cərimə mübahisə kilidinə görə export-dan '
     'kənardadır — yəni gözləmə həm işçinin hüququnu, həm maliyyə axınını '
     'dayandırır. Qayda AVTOMATİK QƏRAR VERMİR: yalnız görünən edir.',
     'HIGH'),
    ('FINE_REVIEW_OVERDUE', NULL, 'Nəşr gözləyən cərimə',
     'Cərimə `FINE_REVIEW_OVERDUE_DAYS` gündən çoxdur `PENDING_REVIEW` '
     'statusundadır (HR-2), yəni işçi onu HƏLƏ GÖRMƏYİB və etiraz pəncərəsi '
     'də başlamayıb. Qayda avtomatik NƏŞR ETMİR — aylıq icmal qərarı '
     'insanındır (CLAUDE.md bölmə 9).',
     'MEDIUM'),
    ('FINE_HELD_INACTIVE_EMPLOYEE', NULL, 'Deaktiv işçinin nəşr olunmayan cəriməsi',
     'İşçi deaktiv edilib, cəriməsi isə hələ `PENDING_REVIEW`-dədir (HR-3). '
     'HR-2-dən FƏRQLİ olaraq HƏDDİ YOXDUR: işçi getdiyi anda çıxış yolu '
     'bağlanır və gözləmək heç nəyi dəyişmir. İki qayda bir-birini İSTİSNA '
     'EDİR — eyni sətir iki mənbədə görünsəydi HR iki fərqli həll axtarardı.',
     'HIGH'),
    ('FACE_ENROLLMENT_OVERDUE', NULL, 'Üz qeydiyyatı aparılmayıb',
     'İşçi `FACE_ENROLLMENT_GRACE_DAYS` gündən çoxdur işə götürülüb, üzü isə '
     'hələ qeydiyyata alınmayıb (UX-7). Kiosk BLOKLANMIR: qeydiyyat '
     'self-service deyil (işçi öz üzünü özü qeydiyyata sala bilmir), yəni '
     'bloklama işçini başqasının hərəkətsizliyinə görə cəzalandırardı. '
     'Sətir menecerin görəcəyi YEGANƏ izdir.',
     'MEDIUM')
ON CONFLICT (code) DO NOTHING;

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- SIRA MƏCBURİDİR: mənbəyə bağlı `exceptions` sətirləri ƏVVƏLCƏ silinməlidir
-- (`FOREIGN KEY`), əks halda `DELETE` pozuntu verir. Həmin sətirlər HR-ın
-- açıq işidir — silinməzdən əvvəl həll edilməlidir.
--
-- BEGIN;
--   DELETE FROM exceptions
--    WHERE source_code IN ('FINE_APPEAL_UNANSWERED', 'FINE_REVIEW_OVERDUE',
--                          'FINE_HELD_INACTIVE_EMPLOYEE', 'FACE_ENROLLMENT_OVERDUE');
--   DELETE FROM exception_sources
--    WHERE code IN ('FINE_APPEAL_UNANSWERED', 'FINE_REVIEW_OVERDUE',
--                   'FINE_HELD_INACTIVE_EMPLOYEE', 'FACE_ENROLLMENT_OVERDUE');
-- COMMIT;
-- ===========================================================================
