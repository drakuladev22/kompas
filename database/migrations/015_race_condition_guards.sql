-- ===========================================================================
-- 015 — YARIŞ VƏZİYYƏTİ (RACE CONDITION) QAPAQLARI
-- ===========================================================================
-- Sərhəd-hal auditi STEP 3-də (`LeaveVerificationUseCase.verify_return`) açıq
-- pəncərə aşkarladı: iki Kamera Operatoru EYNİ icazə sorğusunu eyni anda
-- təsdiqləyə bilirdi. Axın `get()` → `verify_return()` → `save(fine)`
-- ardıcıllığındadır və hər iki tranzaksiya oxu anında statusu hələ
-- `PENDING_RETURN_VERIFICATION` görürdü. Nəticə: `fines` cədvəlində eyni
-- `leave_request_id`-yə bağlı İKİ ayrı `AUTO_DELAY` sətri, yəni işçidən eyni
-- gecikməyə görə İKİ dəfə pul kəsilməsi.
--
-- Tətbiq qatında qapaq artıq qoyulub (sətir kilidi — `SELECT ... FOR UPDATE`),
-- lakin layihə qaydası budur: struktur zəmanət İKİ yerdə yaşayır (CLAUDE.md
-- §5). Kilid tək-tranzaksiya səviyyəsində işləyir; skript, miqrasiya və ya
-- gələcək ikinci tətbiq nüsxəsi onu yan keçə bilər — DB indeksi keçə bilməz.
--
-- İdempotentdir. DOWN bloku sonda şərh içindədir.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD DUBLİKATLARIN ÖN-YOXLAMASI
-- ---------------------------------------------------------------------------
-- Unikal indeks mövcud dublikatlar üzərində QURULMUR — belə halda miqrasiya
-- anlaşılmaz `could not create unique index` xətası ilə dayanardı və operator
-- nə edəcəyini bilməzdi. Ona görə indeksdən ƏVVƏL açıq diaqnostika verilir.
--
-- Düzəliş ƏL İLƏ edilməlidir: hansı sətrin ləğv olunacağı PUL qərarıdır və
-- miqrasiya onu avtomatik verə bilməz (bölmə 4, hüquqi risk). Xəbərdarlıqdan
-- sonra indeks yenə də qurulmağa çalışır — susmaqdansa yüksək səslə dayanmaq
-- yaxşıdır, çünki əks halda qoruma "quraşdırıldı" sayılıb əslində olmazdı.

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
-- (Bu miqrasiyada sətir UNUDULMUŞDU — CI-da 010 məhz buna görə çökürdü.)
SET search_path TO kompasos, public;

DO $$
DECLARE
    v_dupes INTEGER;
BEGIN
    SELECT count(*) INTO v_dupes
      FROM (
           SELECT leave_request_id
             FROM fines
            WHERE source = 'AUTO_DELAY'
              AND leave_request_id IS NOT NULL
              AND status IN ('PENDING_REVIEW', 'PUBLISHED', 'REDUCED')
            GROUP BY leave_request_id
           HAVING count(*) > 1
      ) AS d;

    IF v_dupes > 0 THEN
        RAISE WARNING
            'DİQQƏT: % icazə sorğusunda birdən çox DİRİ AUTO_DELAY cəriməsi var. '
            'Artıq sətirləri fine_review "Sil" axını ilə REVERSED edin, sonra bu '
            'miqrasiyanı təkrar icra edin.', v_dupes;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. BİR İCAZƏ SORĞUSUNA BİR DİRİ `AUTO_DELAY` CƏRİMƏSİ
-- ---------------------------------------------------------------------------
-- ⚠️ İNDEKSİN ŞƏRTİ NİYƏ MƏHZ BELƏDİR
-- ─────────────────────────────────────────────────────────────────────────
-- (a) `source = 'AUTO_DELAY'` — `MANUAL_CAMERA` cərimələri icazə sorğusuna
--     bağlanmır (`leave_request_id` NULL-dur) və bir işçi eyni gündə birdən
--     çox manual cərimə ala bilər. Onları indeksə salmaq qanuni əməliyyatı
--     bloklayardı.
--
-- (b) STATUS ŞƏRTİ — ƏN İNCƏ NÖQTƏ. Saga kompensasiyası uğursuz təsdiqdə
--     cəriməni `discard_in_review()` ilə `REVERSED`-ə keçirir (məbləğ 0.00,
--     qeyd silinmir — bölmə 4). Əgər indeks `REVERSED` sətirləri də əhatə
--     etsəydi, ölü sətir indeks yerini TUTARDI və işçinin həmin STEP 3-ü
--     TƏKRAR təsdiqlətməsi ƏBƏDİ bloklanardı: hər yeni cəhd unikal indeksə
--     dəyər, halbuki real dünyada heç bir cərimə qüvvədə deyil.
--
--     Ona görə indeks yalnız DİRİ statusları əhatə edir:
--         PENDING_REVIEW — hələ icmal gözləyir, aylıq icmalda nəşr oluna bilər;
--         PUBLISHED      — işçiyə görünür, pul kəsintisi qüvvədədir;
--         REDUCED        — etiraz qismən qəbul olunub, AZALDILMIŞ məbləğ HƏLƏ
--                          DƏ ödənilir (bax `Fine.is_exportable` izahı), yəni
--                          ikinci cərimə yenə ikiqat kəsinti olardı.
--     `REVERSED` isə YEGANƏ ölü statusdur — tam ləğv, sıfır məbləğ, export-dan
--     kənar. Məhz o, indeksdən çıxarılır.

CREATE UNIQUE INDEX IF NOT EXISTS uq_fines_one_live_auto_delay_per_leave
    ON fines (leave_request_id)
    WHERE source = 'AUTO_DELAY'
      AND leave_request_id IS NOT NULL
      AND status IN ('PENDING_REVIEW', 'PUBLISHED', 'REDUCED');

COMMENT ON INDEX uq_fines_one_live_auto_delay_per_leave IS
    'YARIŞ QAPAĞI: bir icazə sorğusuna yalnız BİR DİRİ AUTO_DELAY cəriməsi. '
    'REVERSED QƏSDƏN kənardadır — kompensasiya ilə ləğv olunmuş cərimə '
    'işçinin təkrar təsdiqini əbədi bloklamamalıdır.';

-- ---------------------------------------------------------------------------
-- 3. SAGA KOMPENSASİYASININ YAZILA BİLMƏSİ (`chk_fine_published`)
-- ---------------------------------------------------------------------------
-- Yuxarıdakı indeks "kompensasiya cəriməni REVERSED edir" fərziyyəsinə
-- söykənir. Həmin yazının DB-yə DÜŞMƏSİ isə bloklanmışdı:
--
--   `LeaveVerificationUseCase` kompensasiyası `Fine.discard_in_review()`
--   çağırır — cərimə heç vaxt nəşr olunmadığı üçün `published_at` və
--   `appeal_window_closes_at` NULL qalır, status isə `REVERSED` olur.
--   Miqrasiya 003-dəki `chk_fine_published` isə `PENDING_REVIEW`-dan
--   FƏRQLİ hər statusda hər iki sütunun dolu olmasını tələb edirdi.
--   Nəticə: kompensasiya CHECK pozuntusu ilə çökər, cərimə `PENDING_REVIEW`
--   yetim sətir kimi qalar və aylıq icmalda nəşr olunub İKİQAT kəsinti
--   verə bilərdi — yəni indeks qoyulsa da əsas qüsur bağlanmazdı.
--
-- Məhdudiyyət ZƏİFLƏMİR, DƏQİQLƏŞİR: yeni budaq YALNIZ "heç vaxt nəşr
-- olunmamış REVERSED" sətrə aiddir — sıfır məbləğli, işçiyə görünməmiş, export
-- xaricində olan ölü qeyd. `PUBLISHED`/`REDUCED`/`PENDING_REVIEW` üçün heç nə
-- dəyişmir; nəşr olunmuş cərimə hələ də HƏM `published_at`, HƏM
-- `appeal_window_closes_at` tələb edir.
--
-- ŞƏRTDƏ `appeal_window_closes_at IS NULL` NİYƏ YOXDUR
-- ─────────────────────────────────────────────────────────────────────────
-- `trg_fine_appeal_window` (schema.sql §18) BEFORE INSERT işləyir və sütun
-- boş gəldikdə onu `now() + FINE_APPEAL_WINDOW_HOURS` ilə DOLDURUR. Yəni
-- `PENDING_REVIEW` sətirdə həmin sütun praktikada NULL olmur və ona şərt
-- qoymaq kompensasiyanı yenidən bloklayardı. Həqiqi "görünürlük" göstəricisi
-- `published_at`-dır (bölmə 4: 72 saat NƏŞRDƏN hesablanır) — şərt məhz onun
-- üzərindədir.

ALTER TABLE fines DROP CONSTRAINT IF EXISTS chk_fine_published;
ALTER TABLE fines ADD CONSTRAINT chk_fine_published
    CHECK (status = 'PENDING_REVIEW'
        OR (published_at IS NOT NULL AND appeal_window_closes_at IS NOT NULL)
        OR (status = 'REVERSED' AND published_at IS NULL));

COMMENT ON CONSTRAINT chk_fine_published ON fines IS
    'Nəşr olunmuş cərimənin HƏM anı, HƏM etiraz son tarixi olmalıdır. 015: '
    'icmalda silinmiş (heç vaxt nəşr olunmamış) REVERSED sətir istisnadır — o, '
    'saga kompensasiyasının və "Sil" qərarının normal nəticəsidir.';

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma)
-- ---------------------------------------------------------------------------
--   DROP INDEX IF EXISTS uq_fines_one_live_auto_delay_per_leave;
--
--   ALTER TABLE fines DROP CONSTRAINT IF EXISTS chk_fine_published;
--   ALTER TABLE fines ADD CONSTRAINT chk_fine_published
--       CHECK (status = 'PENDING_REVIEW'
--           OR (published_at IS NOT NULL AND appeal_window_closes_at IS NOT NULL))
--       NOT VALID;
--
--   QEYD: indeksi ləğv etmək tətbiq qatındakı sətir kilidini SİLMİR, lakin
--   çox-instansiyalı quraşdırmada ikinci müdafiə qatı itir. `chk_fine_published`
--   köhnə variantına qaytarılarsa mövcud "icmalda silinmiş" REVERSED sətirlər
--   məhdudiyyəti pozacaq (`NOT VALID` ilə əlavə etmək lazım gələ bilər) —
--   geri qaytarma yalnız müvəqqəti diaqnostika üçün düşünülüb.
