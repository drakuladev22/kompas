-- ===========================================================================
-- 085 — OP-4: AÇIQ NÖVBƏNİN GERİ BURAXILMASI VƏ AVTOMATİK MÜDDƏT BİTMƏSİ
-- ===========================================================================
-- Tarix : 2026-08-24
-- Səbəb : İki YENİ axın (`OpenShiftPostingRepository.release()` və
--         `.expire()`) DB qatında BLOKLANIRDI — hər ikisi 019-da qoyulmuş,
--         o vaxt DOĞRU olan iki qaydaya dəyirdi:
--
--           (a) `enforce_open_shift_claim_transition()` statusun `OPEN`-dən
--               ÇIXMASINDAN başqa hər keçidi rədd edir, yəni tutulmuş elanı
--               işçi GERİ VERƏ BİLMİR — nə tətbiqdən, nə də əl ilə;
--           (b) `chk_open_shift_cancel` `cancelled_by IS NOT NULL` tələb
--               edir, yəni AKTORSUZ (avtomatik) bağlanma mümkün deyil.
--
--         019 yazılanda hər iki axın YOX idi: elan ya tutulur, ya insan
--         tərəfindən ləğv edilirdi. OP-4 üçüncü və dördüncü yolu gətirdi.
--
-- ---------------------------------------------------------------------------
-- BU MİQRASİYA SÜTUN ƏLAVƏ ETMİR — QAYDA DƏYİŞİR (CLAUDE.md §7)
-- ---------------------------------------------------------------------------
-- §7-nin tələbi: qayda dəyişəndə `schema.sql`-dəki NÜSXƏ də yenilənməlidir,
-- çünki qayda QATLANMIR — üzərinə yazılır. BURADA HƏMİN NÜSXƏ YOXDUR:
-- `open_shift_postings` cədvəli `schema.sql`-də ÜMUMİYYƏTLƏ mövcud deyil
-- (yoxlandı: sıfır istinad). O, `schema.sql`-də olmayan 39 cədvəldən biridir
-- və bu fərq `tests/unit/test_schema_migration_parity.py`-dəki
-- `_MISSING_TABLE_GROUP` reyestrində SƏBƏBİ ilə qeydə alınıb.
--
-- Yəni bu faylda dəyişən trigger və CHECK üçün TƏK həqiqət mənbəyi
-- miqrasiya zənciridir (019 → 085) və pariteti pozan heç nə yaranmır.
-- `schema.sql`-dən quraşdırılan bazada cədvəl HEÇ VAXT olmayıb, ona görə
-- «qapı quraşdırma yolundan asılı olur» riski (DB-1) burada MÜMKÜN DEYİL.
--
-- ---------------------------------------------------------------------------
-- (a) TRIGGER — NƏYƏ İCAZƏ VERİLİR, NƏYƏ YOX
-- ---------------------------------------------------------------------------
-- ƏLAVƏ OLUNAN YEGANƏ İCAZƏ: `CLAIMED → OPEN`. Həmin keçiddə sahiblik
-- sütunlarının (`claimed_by`, `claimed_at`) `NULL`-a düşməsi MƏCBURİDİR —
-- əks halda `chk_open_shift_claim` onsuz da sətri rədd edərdi, lakin xəta
-- mətni «CHECK pozuntusu» olardı və səbəbi göstərməzdi. Trigger həmin şərti
-- AÇIQ mesajla tutur.
--
-- POZULMAYAN ZƏMANƏTLƏR (019-dakı ilə HƏRFƏN eyni davranış):
--   * `CLAIMED → CLAIMED` sahib dəyişikliyi — QADAĞAN («ilk basan qazanır»,
--     #16). Yoxlama geri-buraxma qolundan SONRA gəlir, yəni sahib
--     dəyişdirmək istəyən `UPDATE` yenə də açıq xəta alır.
--   * `CLAIMED → CANCELLED` — QADAĞAN. Tutulmuş növbəni ləğv etmək işçinin
--     verdiyi sözü sükutla silmək olardı; geri buraxma AÇIQ addımdır və
--     audit sətri yaradır.
--   * `CANCELLED → hər hansı` — QADAĞAN (sətir terminaldır).
--
-- NİYƏ SAHİBLİK «UNUDULUR»: geri buraxılan elan yenidən AÇIQ elandır və
-- `chk_open_shift_claim` `OPEN` sətirdə hər iki sütunun `NULL` olmasını
-- tələb edir. Köhnə sahibi «xatırlatmaq» üçün saxlamaq həmin invariantı
-- pozardı; «kim tutub geri verdi» sualının cavabı audit sətrindədir
-- (domendəki `release()` şərhi ilə eyni qərar).
--
-- ---------------------------------------------------------------------------
-- (b) CHECK — `cancelled_by` YOX, `cancelled_at` DAYAQDIR
-- ---------------------------------------------------------------------------
-- Avtomatik bağlanmada qərarı İNSAN vermir, yəni `cancelled_by` `NULL`-dur.
-- Uydurma aktor (məs. «sistem» işçisi) yazmaq audit izini YALANLAŞDIRARDI.
-- «Nə vaxt bağlandı?» isə HƏR İKİ yolda məlumdur — ona görə invariant vaxt
-- möhürünə köklənir. Domen tərəfi ARTIQ belədir
-- (`entities/open_shift.py::_require_consistent_state`), yəni bu dəyişiklik
-- İKİ nüsxəni yenidən eyniləşdirir (CLAUDE.md §5).
--
-- QALAN HİSSƏ TOXUNULMUR: ləğv edilməmiş sətirdə hər iki sütun yenə də
-- `NULL` olmalıdır — «ləğv edilməyib, amma ləğv edəni var» vəziyyəti
-- əvvəlki kimi mümkünsüzdür.
--
-- MÖVCUD SƏTİRLƏR: yeni CHECK köhnəsindən DAHA GENİŞDİR (bir şərt azalır),
-- yəni əvvəl keçən hər sətir yenə keçir — `NOT VALID`/`VALIDATE` addımına
-- ehtiyac yoxdur və cədvəl kilidi qısa qalır.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. STATUS KEÇİD TRIGGER-İ — `CLAIMED → OPEN` İCAZƏSİ
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION enforce_open_shift_claim_transition() RETURNS TRIGGER AS $$
BEGIN
    -- GERİ BURAXMA (OP-4): YALNIZ bu keçiddə sahiblik silinə bilər.
    -- Blok birinci gəlir, çünki aşağıdakı «sahib dondurulur» yoxlaması
    -- `claimed_by`-ın NULL-a düşməsini də sahib dəyişikliyi sayardı.
    IF OLD.status = 'CLAIMED' AND NEW.status = 'OPEN' THEN
        IF NEW.claimed_by IS NOT NULL OR NEW.claimed_at IS NOT NULL THEN
            RAISE EXCEPTION
                'AÇIQ NÖVBƏ POZUNTUSU: geri buraxılan elanda tutulma sahələri '
                'təmizlənməlidir (elan %) — OPEN sətirdə sahib ola bilməz (#16, OP-4)',
                OLD.id;
        END IF;
        RETURN NEW;
    END IF;

    -- Qalibin sahibliyi dondurulur: status dəyişməsə də `claimed_by` redaktə
    -- edilə bilməz.
    IF OLD.status = 'CLAIMED' AND NEW.claimed_by IS DISTINCT FROM OLD.claimed_by THEN
        RAISE EXCEPTION
            'AÇIQ NÖVBƏ POZUNTUSU: tutulmuş elanın sahibi dəyişdirilə bilməz '
            '(elan %, mövcud sahib %) — ilk basan qazanır (#16)',
            OLD.id, OLD.claimed_by;
    END IF;

    IF NEW.status = OLD.status THEN
        RETURN NEW;
    END IF;

    IF OLD.status <> 'OPEN' THEN
        RAISE EXCEPTION
            'AÇIQ NÖVBƏ KEÇİDİ RƏDD EDİLDİ: "%" statusundakı elan "%" statusuna '
            'keçə bilməz — yalnız OPEN elan tutula və ya ləğv edilə bilər, '
            'tutulmuş elan isə YALNIZ geri buraxıla bilər (#16, OP-4)',
            OLD.status, NEW.status;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_open_shift_claim_transition() IS
    '#16 "ilk basan qazanır" qaydasının DB qatı: OPEN elan tutula/ləğv edilə '
    'bilər, CLAIMED elan YALNIZ geri buraxıla bilər (CLAIMED → OPEN, OP-4) və '
    'həmin keçiddə tutulma sahələri təmizlənməlidir. Tutulmuş elanın sahibi '
    'HEÇ BİR halda dəyişdirilə bilməz (migrations/085).';

-- Trigger ADI VƏ BAĞLANMASI DƏYİŞMİR — yalnız funksiyanın gövdəsi yenilənir.
-- `DROP`/`CREATE` cütü yenə də yazılır: 019-un yanında bu faylı oxuyan adam
-- trigger-in HANSI funksiyaya bağlandığını bir yerdə görməlidir və əməliyyat
-- idempotentdir.
DROP TRIGGER IF EXISTS trg_open_shift_claim_transition ON open_shift_postings;
CREATE TRIGGER trg_open_shift_claim_transition
    BEFORE UPDATE ON open_shift_postings
    FOR EACH ROW EXECUTE FUNCTION enforce_open_shift_claim_transition();

-- ---------------------------------------------------------------------------
-- 2. LƏĞV INVARİANTI — AKTORSUZ (AVTOMATİK) BAĞLANMA
-- ---------------------------------------------------------------------------
ALTER TABLE open_shift_postings
    DROP CONSTRAINT IF EXISTS chk_open_shift_cancel;

ALTER TABLE open_shift_postings
    ADD CONSTRAINT chk_open_shift_cancel
        CHECK ((status = 'CANCELLED' AND cancelled_at IS NOT NULL)
            OR (status <> 'CANCELLED' AND cancelled_by IS NULL AND cancelled_at IS NULL));

COMMENT ON COLUMN open_shift_postings.cancelled_by IS
    'Ləğv edən şəxs. NULL = avtomatik bağlanma (müddət bitdi, OP-4) — uydurma '
    'aktor yazılmır. İnsan qərarında sütun HƏMİŞƏ doludur, çünki `cancel()` '
    'aktoru MƏCBURİ arqument kimi tələb edir (migrations/085).';
COMMENT ON COLUMN open_shift_postings.cancelled_at IS
    'Bağlanma anı — həm insan, həm avtomatik yolda MƏCBURİDİR. '
    '`chk_open_shift_cancel` invariantının dayağı məhz budur (migrations/085).';

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- DOWN İKİ ADDIMDIR VƏ SIRA MƏCBURİDİR: əvvəlcə avtomatik bağlanmış sətirlər
-- (`cancelled_by IS NULL AND status = 'CANCELLED'`) təmizlənməlidir, sonra
-- köhnə CHECK qaytarıla bilər — əks halda `ADD CONSTRAINT` mövcud sətirlərdə
-- POZUNTU tapıb miqrasiyanı dayandırar. Geri buraxılmış (yenidən `OPEN` olan)
-- elanlar isə problem yaratmır: onlar köhnə qaydaya UYĞUNDUR.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   -- Avtomatik bağlanmış elanlar YENİDƏN açılır (aktorsuz sətir saxlanıla
--   -- bilməz). Tarixi keçmiş elan yenidən görünəcək — DOWN yalnız səhvən
--   -- tətbiq halı üçündür.
--   UPDATE open_shift_postings
--      SET status = 'OPEN', cancelled_at = NULL, cancel_reason = NULL
--    WHERE status = 'CANCELLED' AND cancelled_by IS NULL;
--   ALTER TABLE open_shift_postings DROP CONSTRAINT IF EXISTS chk_open_shift_cancel;
--   ALTER TABLE open_shift_postings
--       ADD CONSTRAINT chk_open_shift_cancel
--           CHECK ((status = 'CANCELLED' AND cancelled_by IS NOT NULL
--                   AND cancelled_at IS NOT NULL)
--               OR (status <> 'CANCELLED' AND cancelled_by IS NULL
--                   AND cancelled_at IS NULL));
--   -- Trigger 019-dakı gövdəyə qaytarılır (geri buraxma icazəsi olmadan):
--   -- `git show <019-dan sonrakı hər hansı commit>:database/migrations/019_shift_intelligence_tables.sql`
-- COMMIT;
-- ===========================================================================
