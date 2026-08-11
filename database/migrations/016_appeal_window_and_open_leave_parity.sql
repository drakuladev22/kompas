-- ===========================================================================
-- 016 — ETİRAZ PƏNCƏRƏSİ VƏ AÇIQ İCAZƏ DƏSTİNİN DOMENƏ UYĞUNLAŞDIRILMASI
-- ===========================================================================
-- İki paritet pozuntusu: hər ikisində DOMEN DÜZGÜNDÜR, DB geri qalıb.
-- Layihə qaydası (CLAUDE.md §5) hər struktur qaydanın İKİ yerdə eyni olmasını
-- tələb edir — burada DB domenə uyğunlaşdırılır, domen qaydası DƏYİŞMİR.
--
--   (B) `trg_fine_appeal_window` 72 saatı YARADILMA anından sayırdı, halbuki
--       qayda (bölmə 4) onu NƏŞRDƏN sayır. Domen mənbəyi: `Fine.publish()` —
--       `appeal_window_closes_at := published_at + appeal_window_hours`;
--       `Fine.__init__` isə sütunu `None` saxlayır, `is_appeal_window_open`
--       `None`-u "hələ AÇIQ" kimi oxuyur (yəni export bloklanır).
--
--   (C) `uq_leave_one_open_per_employee` `TIMEOUT_ESCALATED` statusunu əhatə
--       etmirdi, `LeaveStatus.is_open` isə onu AÇIQ sayır. Nəticədə timeout-a
--       düşmüş işçi üçün DB səviyyəsində İKİNCİ açıq icazə mümkün idi.
--
-- İdempotentdir. DOWN bloku sonda şərh içindədir.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- B1. ETİRAZ PƏNCƏRƏSİ NƏŞRDƏN BAŞLAYIR
-- ---------------------------------------------------------------------------
-- KÖHNƏ DAVRANIŞ: `BEFORE INSERT` trigger-i sütun boş gəldikdə onu
-- `now() + FINE_APPEAL_WINDOW_HOURS` ilə doldururdu. Bunun iki nəticəsi var
-- idi və hər ikisi işçinin ZİYANINADIR:
--
--   1. Heç vaxt nəşr olunmamış cərimənin pəncərəsi öz-özünə "bağlanırdı" —
--      yəni `PENDING_REVIEW` sətir vaxt keçdikcə export şərtinə uyğun görünür
--      və `list_exportable`-dakı zəif filtrlə birlikdə maaş siyahısına sıza
--      bilirdi.
--   2. Cərimə icmalda həftələrlə qalıb sonra nəşr olunanda pəncərə ARTIQ
--      işləmiş olurdu: işçi cəriməni GÖRDÜYÜ gün etiraz müddəti bitmiş sayıla
--      bilərdi. Bu, `fine.py` başlığında "ƏN VACİB DETAL" kimi yazılmış
--      qaydanın birbaşa pozulmasıdır.
--
-- YENİ DAVRANIŞ (domenin hərfi qarşılığı):
--   * `published_at IS NULL` → pəncərə AÇILMIR, sütun toxunulmur;
--   * `published_at` doludur və sütun boşdur → `published_at + limit`;
--   * sütun artıq doludursa TOXUNULMUR — bu, "uzatma/qısaltma qadağası"dır:
--     bir dəfə açılmış pəncərə sonradan dəyişən Root limitindən ASILI OLMUR
--     (domen də dəyəri `publish()` anında DONDURUR).
--
-- Trigger `INSERT`-ə ƏLAVƏ olaraq `UPDATE`-i də əhatə edir, çünki nəşr məhz
-- UPDATE-dir. Əks halda SQL ilə (ekranı yan keçərək) nəşr edilən cərimənin
-- pəncərəsi heç vaxt açılmazdı.

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
-- (Bu miqrasiyada sətir UNUDULMUŞDU — CI-da 010 məhz buna görə çökürdü.)
SET search_path TO kompasos, public;

CREATE OR REPLACE FUNCTION set_fine_appeal_window() RETURNS TRIGGER AS $$
DECLARE
    v_hours INTEGER;
BEGIN
    -- (a) Artıq təyin olunub — DONDURULMUŞ dəyər dəyişdirilmir.
    IF NEW.appeal_window_closes_at IS NOT NULL THEN
        RETURN NEW;
    END IF;

    -- (b) Hələ nəşr olunmayıb — sayğac BAŞLAMIR (72 saat nəşrdən sayılır).
    --     Sütun QƏSDƏN NULL saxlanılır: `Fine.is_appeal_window_open` NULL-u
    --     "hələ açıq" kimi oxuyur, yəni export bloklanır (fail-safe).
    IF NEW.published_at IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT COALESCE(limit_value::INTEGER, 72) INTO v_hours
    FROM system_limits
    WHERE tenant_id = NEW.tenant_id AND limit_key = 'FINE_APPEAL_WINDOW_HOURS';

    NEW.appeal_window_closes_at :=
        NEW.published_at + make_interval(hours => COALESCE(v_hours, 72));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION set_fine_appeal_window() IS
    'Etiraz pəncərəsi NƏŞRDƏN (published_at) hesablanır, yaradılışdan YOX '
    '(bölmə 4). 016: köhnə variant `now()`-dan sayırdı və nəşr olunmamış '
    'cərimənin pəncərəsini öz-özünə bağlayırdı.';

DROP TRIGGER IF EXISTS trg_fine_appeal_window ON fines;
CREATE TRIGGER trg_fine_appeal_window BEFORE INSERT OR UPDATE ON fines
    FOR EACH ROW EXECUTE FUNCTION set_fine_appeal_window();

-- ---------------------------------------------------------------------------
-- B2. MÖVCUD SƏTİRLƏR — GERİYƏ-UYĞUNLUQ
-- ---------------------------------------------------------------------------
-- ⚠️ ƏN HƏSSAS ADDIM. Aşağıdakı UPDATE YALNIZ bir dəsti hədəfləyir:
--
--     status = 'PENDING_REVIEW' AND published_at IS NULL
--
-- Yəni köhnə trigger tərəfindən SƏHVƏN doldurulmuş, HEÇ VAXT nəşr
-- olunmamış sətirlər. Onlarda sütun NULL-a qaytarılır ki, nəşr anında
-- düzgün dəyər (published_at + limit) yazıla bilsin.
--
-- NƏŞR OLUNMUŞ SƏTİRLƏRƏ TOXUNULMUR (`published_at IS NOT NULL`):
--   * pəncərəni YENİDƏN hesablasaydıq, artıq başlamış müddəti UZADAR və ya
--     QISALDARDIQ — işçinin etiraz hüququ ilə oynamaq deməkdir;
--   * `REVERSED`/`REDUCED` sətirlərdə qərar artıq verilib, sütun tarixi
--     sənəddir;
--   * `chk_fine_published` nəşr olunmuş sətirdə sütunun DOLU olmasını tələb
--     edir — NULL-a çevirmək məhdudiyyəti pozardı.
--
-- Yeni dəyər YAZILMIR, yalnız NULL-a qaytarılır: bu, ciddi şəkildə DAHA
-- MÜHAFİZƏKAR vəziyyətdir (`is_appeal_window_open` → TRUE → export bağlı).
-- Miqrasiya təkrar icra olunsa heç nə dəyişmir (idempotent).

DO $$
DECLARE
    v_cleared INTEGER;
BEGIN
    UPDATE fines
       SET appeal_window_closes_at = NULL
     WHERE status = 'PENDING_REVIEW'
       AND published_at IS NULL
       AND appeal_window_closes_at IS NOT NULL;

    GET DIAGNOSTICS v_cleared = ROW_COUNT;
    IF v_cleared > 0 THEN
        RAISE NOTICE
            '016: % nəşr olunmamış cərimədə etiraz pəncərəsi sıfırlandı — '
            'sayğac artıq nəşr anında başlayacaq.', v_cleared;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- B3. `v_exportable_fines` DONDURULMUŞ PƏNCƏRƏYƏ KEÇİR
-- ---------------------------------------------------------------------------
-- Görünüşün STATUS şərti (miqrasiya 003) ƏVVƏLCƏDƏN DÜZGÜN idi —
-- `PENDING_REVIEW` heç vaxt ora düşmürdü; tapıntı yalnız repository
-- sorğusuna aid idi. Fərqin səbəbi: 003 görünüşü yenilədi, `list_exportable`
-- isə köhnə (`status <> 'REVERSED'`) modeldə qaldı.
--
-- Burada YALNIZ pəncərənin MƏNBƏYİ dəyişir: görünüş onu hər sorğuda
-- `published_at + CARİ limit` kimi YENİDƏN hesablayırdı. Root limiti
-- 72 → 24 saata endirsəydi, artıq nəşr olunmuş cərimələrin pəncərəsi
-- RETROAKTİV bağlanardı — halbuki domen dəyəri `publish()` anında dondurur
-- (`Fine.publish`) və `Fine.is_appeal_window_open` məhz dondurulmuş sütunu
-- oxuyur. İki qat eyni sualı fərqli cavablandırırdı.
--
-- Nəticə: görünüş də dondurulmuş sütuna baxır → domen, repository və görünüş
-- ÜÇÜ də eyni şərti tətbiq edir.

CREATE OR REPLACE VIEW v_exportable_fines AS
SELECT f.*
FROM fines f
-- `REDUCED` DAXİLDİR: qismən qəbul olunmuş etirazdan sonra işçi
-- azaldılmış məbləği yenə ödəyir (bax `Fine.is_exportable`).
WHERE f.status IN ('PUBLISHED', 'REDUCED')
  AND f.published_at IS NOT NULL
  AND f.appeal_window_closes_at IS NOT NULL
  AND f.appeal_window_closes_at <= now()
  AND f.exported_period IS NULL;

COMMENT ON VIEW v_exportable_fines IS
    'Premiya&Cərimə export-una (FAYL 2) düşə bilən cərimələr. Ayın 1-də '
    'nəşr olunan cərimə həmin ayın export-una DÜŞMÜR (72 saat keçməyib) — '
    'bu, gözlənilən davranışdır, xəta deyil. 016: pəncərə DONDURULMUŞ '
    '`appeal_window_closes_at` sütunundan oxunur, cari limitdən yenidən '
    'hesablanmır (`Fine.is_appeal_window_open` ilə paritet).';

-- ---------------------------------------------------------------------------
-- C1. AÇIQ İCAZƏ DƏSTİ — ÖN-YOXLAMA
-- ---------------------------------------------------------------------------
-- Genişlənən unikal indeks mövcud dublikatlar üzərində qurulmur. `OUTSIDE` +
-- `TIMEOUT_ESCALATED` cütü köhnə indeksdə QANUNİ idi, ona görə real bazada
-- belə sətirlər OLA BİLƏR. Düzəliş əl ilə edilməlidir: hansı sorğunun ləğv
-- olunacağı iş qərarıdır (biri işçinin faktiki xaricdə olduğu icazə ola bilər).

DO $$
DECLARE
    v_dupes INTEGER;
BEGIN
    SELECT count(*) INTO v_dupes
      FROM (
           SELECT employee_id
             FROM leave_requests
            WHERE status IN ('OUTSIDE', 'PENDING_RETURN_VERIFICATION', 'TIMEOUT_ESCALATED')
            GROUP BY employee_id
           HAVING count(*) > 1
      ) AS d;

    IF v_dupes > 0 THEN
        RAISE WARNING
            'DİQQƏT: % işçinin birdən çox AÇIQ icazə sorğusu var (TIMEOUT_ESCALATED '
            'daxil). Artıq sətirləri CANCELLED edin, sonra bu miqrasiyanı təkrar '
            'icra edin.', v_dupes;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- C2. İNDEKS `LeaveStatus.is_open` DƏSTİNƏ UYĞUNLAŞDIRILIR
-- ---------------------------------------------------------------------------
-- Domen mənbəyi (`leave_request.py`):
--     is_open := OUTSIDE | PENDING_RETURN_VERIFICATION | TIMEOUT_ESCALATED
--
-- `TIMEOUT_ESCALATED` AÇIQDIR, çünki işçi hələ FİZİKİ OLARAQ xaricdədir —
-- yalnız təsdiq gecikib. Onu indeksdən kənarda saxlamaq "45 dəqiqə gözlə,
-- sonra istədiyin qədər icazə aç" yolunu açıq qoyurdu.
--
-- Qayda YALNIZ GENİŞLƏNİR (üç status ⊃ iki status) — əvvəl bloklanan heç bir
-- hal indi keçmir, yəni mövcud davranış zəifləmir.
-- `DROP` + `CREATE` məcburidir: PostgreSQL qismən indeksin predikatını
-- `ALTER` ilə dəyişmir. Hər iki addım idempotentdir.

DROP INDEX IF EXISTS uq_leave_one_open_per_employee;
CREATE UNIQUE INDEX IF NOT EXISTS uq_leave_one_open_per_employee
    ON leave_requests (employee_id)
    WHERE status IN ('OUTSIDE', 'PENDING_RETURN_VERIFICATION', 'TIMEOUT_ESCALATED');

COMMENT ON INDEX uq_leave_one_open_per_employee IS
    'Bir işçinin eyni anda yalnız BİR açıq icazəsi ola bilər. Status dəsti '
    '`LeaveStatus.is_open` ilə eynidir — 016-da TIMEOUT_ESCALATED əlavə edildi.';

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma)
-- ---------------------------------------------------------------------------
--   -- C: indeksi köhnə (dar) dəstə qaytarır
--   DROP INDEX IF EXISTS uq_leave_one_open_per_employee;
--   CREATE UNIQUE INDEX IF NOT EXISTS uq_leave_one_open_per_employee
--       ON leave_requests (employee_id)
--       WHERE status IN ('OUTSIDE', 'PENDING_RETURN_VERIFICATION');
--
--   -- B: trigger yalnız INSERT-ə qayıdır və `now()`-dan sayır
--   CREATE OR REPLACE FUNCTION set_fine_appeal_window() RETURNS TRIGGER AS $BODY$
--   DECLARE v_hours INTEGER;
--   BEGIN
--       IF NEW.appeal_window_closes_at IS NOT NULL THEN RETURN NEW; END IF;
--       SELECT COALESCE(limit_value::INTEGER, 72) INTO v_hours
--         FROM system_limits
--        WHERE tenant_id = NEW.tenant_id AND limit_key = 'FINE_APPEAL_WINDOW_HOURS';
--       NEW.appeal_window_closes_at := now() + make_interval(hours => COALESCE(v_hours, 72));
--       RETURN NEW;
--   END;
--   $BODY$ LANGUAGE plpgsql;
--   DROP TRIGGER IF EXISTS trg_fine_appeal_window ON fines;
--   CREATE TRIGGER trg_fine_appeal_window BEFORE INSERT ON fines
--       FOR EACH ROW EXECUTE FUNCTION set_fine_appeal_window();
--
--   -- B2 GERİ QAYTARILMIR: sıfırlanmış pəncərələr üçün köhnə (səhv) dəyəri
--   -- bərpa etmək mümkün deyil və mənasızdır — həmin sətirlər nəşr anında
--   -- onsuz da düzgün dəyəri alacaq.
--
--   -- B3: görünüşü 003-dəki (yenidən hesablayan) variantına qaytarın.
