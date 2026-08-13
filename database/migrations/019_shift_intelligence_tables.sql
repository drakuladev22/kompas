-- ===========================================================================
-- 019 — NÖVBƏ ZƏKASI: TARİXİ NÜMUNƏ, İŞ SAATI AŞIMI, AÇIQ NÖVBƏ BAZARI
-- ===========================================================================
-- Tarix : 2026-08-11
-- Səbəb : Faza 1 (kompasos11.md) mövcud Interactive Shift Matrix-ə ÜÇ köməkçi
--         funksiyanın saxlama qatını tələb edir: #13 tarixi-nümunə təklifi,
--         #15 norma üstü iş saatı jurnalı, #16 açıq növbə elanları.
--         Mövcud `shift_assignments` / `work_modes` / `attendance_records`
--         cədvəllərinə TOXUNULMUR — nə sütun dəyişir, nə ad, nə tip.
--
-- İdempotentdir. DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- 1C SƏRHƏDİ
-- ---------------------------------------------------------------------------
-- Bu üç cədvəlin heç biri 1C-yə bağlantı AÇMIR. Xüsusilə #13: əvvəlki
-- versiyada təklif 1C satış həcminə əsaslanırdı — həmin dizayn TAM ÇIXARILDI
-- (kompasos11.md struktur qərarı D). İndiki mənbə YALNIZ KompasOS-un öz
-- `attendance_records` / `shift_assignments` tarixçəsidir. Ona görə cədvəlin
-- adında da "demand" (tələb) sözü YOXDUR: bu, satış-tələbi proqnozu deyil,
-- keçmiş kadr-tərkibinin nümunəsidir — daha zəif siqnal, amma 1C-siz.
--
-- ---------------------------------------------------------------------------
-- #16-DA "İLK BASAN QAZANIR" — DB SƏVİYYƏSİNDƏ NECƏ TƏMİN OLUNUR
-- ---------------------------------------------------------------------------
-- Tətbiq qatı Faza 6-da `SELECT ... FOR UPDATE` işlədəcək. Layihə qaydası isə
-- budur: struktur zəmanət İKİ yerdə yaşayır (CLAUDE.md §5) — kilid tək
-- tranzaksiya daxilində işləyir, skript/miqrasiya/ikinci tətbiq nüsxəsi onu
-- yan keçə bilər (bax `migrations/015` başlığı). Burada ÜÇ qat qoyulur:
--
--   (a) `chk_open_shift_claim` — `CLAIMED` statusu `claimed_by` + `claimed_at`
--       OLMADAN mümkün deyil; `OPEN` sətirdə isə hər ikisi NULL olmalıdır.
--       Yəni "yarımçıq götürülmüş" sətir yaranmır.
--   (b) `trg_open_shift_claim_transition` — status YALNIZ `OPEN`-dən çıxa bilər.
--       Uduzan tranzaksiya `WHERE status = 'OPEN'` şərtini UNUTSA belə
--       (məs. `UPDATE ... WHERE id = ?`), trigger keçidi rədd edir və
--       qalibin `claimed_by` dəyəri ÜSTÜNDƏN YAZILA BİLMİR.
--   (c) `uq_open_shift_one_claim_per_employee_day` — qismən unikal indeks
--       (`WHERE status = 'CLAIMED'`): bir işçi eyni günə İKİ açıq növbə götürə
--       bilməz. Bu, mövcud `shift_assignments UNIQUE (employee_id, shift_date)`
--       qaydasının elan mərhələsindəki əkizidir — əks halda iki elanı eyni anda
--       basan işçi təyinetmə mərhələsində gözlənilməz xəta alardı.
--
-- Əlavə olaraq `uq_open_shift_one_open_per_slot` eyni (mağaza, tarix, iş rejimi)
-- üçün İKİ açıq elanın yaranmasını bloklayır — əks halda iki işçi "eyni"
-- növbəni götürüb hər ikisi qalib sayılardı.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. staffing_pattern_suggestions (#13) — TARİXİ NÜMUNƏ TƏKLİFİ
-- ---------------------------------------------------------------------------
-- HƏFTƏ GÜNÜ KONVENSİYASI — NİYƏ AÇIQ YAZILIR: PostgreSQL-in `EXTRACT(DOW)`
-- funksiyası 0=Bazar, `EXTRACT(ISODOW)` isə 1=Bazar ertəsi verir; Python-un
-- `date.weekday()` 0=Bazar ertəsi, `date.isoweekday()` 1=Bazar ertəsi. Dörd
-- fərqli nömrələmə arasında sükutla seçim etmək klassik "bir gün sürüşmə"
-- qüsurudur. SEÇİLƏN: ISO — 1=Bazar ertəsi … 7=Bazar. SQL tərəfi
-- `EXTRACT(ISODOW FROM ...)`, Python tərəfi `date.isoweekday()` işlətməlidir.
CREATE TABLE IF NOT EXISTS staffing_pattern_suggestions (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                 UUID NOT NULL REFERENCES license_tenants(tenant_id)
                                  ON DELETE CASCADE,
    -- CASCADE: təklif tam törəmə məlumatdır (istənilən an yenidən hesablanır),
    -- mağaza qeydindən sonra saxlanmasının mənası yoxdur.
    store_id                  UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,

    weekday                   SMALLINT NOT NULL CHECK (weekday BETWEEN 1 AND 7),
    avg_historical_headcount  NUMERIC(5, 2) NOT NULL
                                  CHECK (avg_historical_headcount >= 0),
    based_on_weeks            SMALLINT NOT NULL CHECK (based_on_weeks > 0),

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: təklifin YAŞI onun etibarlılığının bir
    -- hissəsidir. Ekranda "8 həftəlik nümunə" yazılıb, amma hesablama 3 ay
    -- əvvəlkidirsə, göstərici yanıldıcıdır. Yaşı bilmədən "köhnəlib" xəbərdarlığı
    -- vermək mümkün deyil.
    calculated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Bir mağaza + bir həftə günü = BİR diri təklif; yenidən hesablama UPSERT-dir.
    UNIQUE (tenant_id, store_id, weekday)
);

DROP TRIGGER IF EXISTS trg_staffing_suggestions_updated ON staffing_pattern_suggestions;
CREATE TRIGGER trg_staffing_suggestions_updated
    BEFORE UPDATE ON staffing_pattern_suggestions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_staffing_suggestions_store
    ON staffing_pattern_suggestions (store_id, weekday);

COMMENT ON TABLE staffing_pattern_suggestions IS
    '#13 — "Bu mağaza son N həftədə çərşənbə günləri orta hesabla neçə işçi ilə '
    'işləyib?" TƏKLİFİ. Mənbə YALNIZ KompasOS-un öz Attendance/Shift tarixçəsidir '
    '(1C satış datası QƏSDƏN İŞLƏDİLMİR — struktur qərar D). Bu, TƏLƏB proqnozu '
    'deyil, keçmiş nümunənin təkrarıdır: zəif siqnal, heç vaxt avtomatik təyinetmə '
    'səbəbi ola bilməz.';
COMMENT ON COLUMN staffing_pattern_suggestions.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN staffing_pattern_suggestions.tenant_id IS
    'Kirayəçi izolyasiyası — RLS açarı.';
COMMENT ON COLUMN staffing_pattern_suggestions.store_id IS 'Təklifin aid olduğu mağaza.';
COMMENT ON COLUMN staffing_pattern_suggestions.weekday IS
    'ISO həftə günü: 1 = Bazar ertəsi … 7 = Bazar. SQL `EXTRACT(ISODOW)`, '
    'Python `date.isoweekday()` ilə uyğundur — `EXTRACT(DOW)` (0 = Bazar) İŞLƏDİLMİR.';
COMMENT ON COLUMN staffing_pattern_suggestions.avg_historical_headcount IS
    'Həmin həftə günündə faktiki işləmiş işçilərin ortası (kəsr ola bilər — '
    'məs. 8 həftənin 3-ündə 2, 5-ində 3 nəfər → 2.63).';
COMMENT ON COLUMN staffing_pattern_suggestions.based_on_weeks IS
    'Ortanın neçə həftəlik pəncərədən çıxdığı. Pəncərənin uzunluğu Root '
    'parametridir (`system_limits`), burada YALNIZ faktiki dəyər saxlanılır.';
COMMENT ON COLUMN staffing_pattern_suggestions.calculated_at IS
    'Sonuncu hesablama anı (tz-aware) — köhnəlmiş təklif xəbərdarlıqla göstərilir.';
COMMENT ON COLUMN staffing_pattern_suggestions.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN staffing_pattern_suggestions.updated_at IS
    'Sonuncu dəyişiklik anı (trigger).';

-- ---------------------------------------------------------------------------
-- 2. overtime_log (#15) — NORMA ÜSTÜ İŞ SAATLARI
-- ---------------------------------------------------------------------------
-- SÜTUN ADI `date` DEYİL, `work_date`: `date` PostgreSQL-də tip adıdır və
-- sorğularda hər dəfə dırnaq tələb edərdi; üstəlik mövcud `attendance_records`
-- artıq `work_date` işlədir — eyni anlayış eyni adı daşımalıdır.
CREATE TABLE IF NOT EXISTS overtime_log (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES license_tenants(tenant_id)
                          ON DELETE CASCADE,
    -- CASCADE: jurnal sətri işçi haqqındadır; müstəqil mənası yoxdur. Əmək
    -- haqqı təsiri olan qeydlər (cərimə/xal) AYRI cədvəllərdədir və onlar
    -- SEC-015 qoruması altındadır — bu cədvəl pul hesablamır.
    employee_id       UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,

    work_date         DATE NOT NULL,

    -- ƏLAVƏ SÜTUNLAR — ƏSASLANDIRMA: "norma üstü 2.5 saat" rəqəmi TƏK BAŞINA
    -- yoxlanıla bilməz. Norma `work_modes`-dan gəlir və Root onu SONRADAN
    -- dəyişə bilər; həmin an keçmiş sətirlərin izahı itərdi ("bu 2.5 hansı
    -- normaya görə idi?"). Hər iki əsas rəqəm hesablama anında DONDURULUR.
    norm_hours        NUMERIC(5, 2) NOT NULL CHECK (norm_hours >= 0),
    actual_hours      NUMERIC(5, 2) NOT NULL CHECK (actual_hours >= 0),

    -- >= 0 (> 0 DEYİL) — ƏSASLANDIRMA: yenidən hesablama nəticəni sıfıra endirə
    -- bilər (məs. manual vaxt düzəlişindən sonra). Belə sətri SİLMƏK "aşım heç
    -- vaxt olmayıb" təəssüratı yaradardı; 0.00 isə "yenidən hesablandı, aşım
    -- qalmadı" faktının qeydidir.
    hours_over_norm   NUMERIC(5, 2) NOT NULL CHECK (hours_over_norm >= 0),

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: aşım avtomatik hesablanmışdırsa bu, sistemin
    -- iddiasıdır; HR əl ilə yazıbsa insanın iddiasıdır. İkisini ayırmadan
    -- hesabatda "sistem səhv sayır" mübahisəsi həll edilə bilmir.
    source            TEXT NOT NULL DEFAULT 'AUTO_ATTENDANCE'
                          CHECK (source IN ('AUTO_ATTENDANCE', 'MANUAL_HR')),
    recorded_by       UUID REFERENCES employees(id) ON DELETE SET NULL,

    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Bir işçi-gün = BİR sətir; yenidən hesablama UPSERT-dir. Əks halda eyni
    -- gün üçün iki sətir toplanıb aşımı İKİQAT göstərərdi.
    UNIQUE (tenant_id, employee_id, work_date),
    -- Əl ilə yazılan aşımın sahibi olmalıdır.
    CONSTRAINT chk_overtime_manual_author
        CHECK (source <> 'MANUAL_HR' OR recorded_by IS NOT NULL)
);

DROP TRIGGER IF EXISTS trg_overtime_log_updated ON overtime_log;
CREATE TRIGGER trg_overtime_log_updated BEFORE UPDATE ON overtime_log
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Aylıq/həftəlik aşım hesabatı işçi + tarix üzrə oxunur.
CREATE INDEX IF NOT EXISTS idx_overtime_employee_date
    ON overtime_log (employee_id, work_date DESC);
-- "Bu ay hansı işçilərdə aşım var?" — sıfır sətirlər hesabata düşməməlidir.
CREATE INDEX IF NOT EXISTS idx_overtime_tenant_date
    ON overtime_log (tenant_id, work_date DESC) WHERE hours_over_norm > 0;

COMMENT ON TABLE overtime_log IS
    '#15 — Norma üstü işlənmiş saatların jurnalı. MAĞAZA sütunu YOXDUR: iş '
    'günü hansı filialda keçdiyi `attendance_records` ilə join edilərək alınır — '
    'eyni faktı iki yerdə saxlamaq onların bir gün fərqlənməsi riskini yaradır.';
COMMENT ON COLUMN overtime_log.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN overtime_log.tenant_id IS 'Kirayəçi izolyasiyası — RLS açarı.';
COMMENT ON COLUMN overtime_log.employee_id IS 'Aşımı olan işçi.';
COMMENT ON COLUMN overtime_log.work_date IS
    'İş günü (spesifikasiyadakı `date`). Ad `attendance_records.work_date` ilə '
    'uyğunlaşdırılıb; `date` həm də tip adı olduğu üçün işlədilmir.';
COMMENT ON COLUMN overtime_log.norm_hours IS
    'Həmin gün üçün QÜVVƏDƏ OLAN norma (saat). Dondurulur, çünki `work_modes` '
    'sonradan dəyişsə keçmiş hesablamanın əsası itərdi.';
COMMENT ON COLUMN overtime_log.actual_hours IS
    'Faktiki işlənmiş saat. `hours_over_norm` bu iki sütunun fərqindən çıxır — '
    'fərq CHECK ilə məcbur EDİLMİR, çünki yuvarlaqlaşdırma 0.01 fərqlə '
    'qanuni sətri bloklaya bilərdi.';
COMMENT ON COLUMN overtime_log.hours_over_norm IS
    'Norma üstü saat. 0.00 = yenidən hesablandı və aşım qalmadı (sətir SİLİNMİR).';
COMMENT ON COLUMN overtime_log.source IS
    'AUTO_ATTENDANCE = davamiyyət datasından hesablandı; MANUAL_HR = HR əl ilə yazdı.';
COMMENT ON COLUMN overtime_log.recorded_by IS
    'Əl ilə yazılışda məsul şəxs. Avtomatik sətirdə NULL — sahibi sistemdir.';
COMMENT ON COLUMN overtime_log.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN overtime_log.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

-- ---------------------------------------------------------------------------
-- 3. open_shift_postings (#16) — AÇIQ NÖVBƏ ELANLARI
-- ---------------------------------------------------------------------------
-- SPESİFİKASİYADAKI `shift_id` NİYƏ `work_mode_id`-DİR: KompasOS-da `shifts`
-- adlı cədvəl YOXDUR. Növbə İKİ anlayışa bölünüb — ŞABLON (`work_modes`:
-- "08:00–17:00") və konkret TƏYİNAT (`shift_assignments`: filan işçi filan gün).
-- Açıq elan məhz o andadır ki, təyinat HƏLƏ YOXDUR (elanın bütün mənası budur),
-- ona görə elan ŞABLONA istinad edir. Elan tutulduqdan sonra Faza 6
-- `shift_assignments`-də real sətri yaradacaq.
CREATE TABLE IF NOT EXISTS open_shift_postings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES license_tenants(tenant_id)
                        ON DELETE CASCADE,
    store_id        UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    shift_date      DATE NOT NULL,

    -- NO ACTION: elan qüvvədə ikən iş rejiminin silinməsi elanı mənasız
    -- qoyardı. `work_modes` onsuz da soft delete işlədir (`is_active`), ona
    -- görə bu məhdudiyyət normal iş axınını bloklamır.
    work_mode_id    UUID NOT NULL REFERENCES work_modes(id) ON DELETE NO ACTION,

    -- 'CANCELLED' spesifikasiyada YOXDUR — ƏSASLANDIRMA: geri çəkilən elanı
    -- `DELETE` etmək onu görmüş işçilər üçün "elan heç vaxt olmayıb" halına
    -- salardı. Status ilə söndürmə soft delete-in axın versiyasıdır.
    status          TEXT NOT NULL DEFAULT 'OPEN'
                        CHECK (status IN ('OPEN', 'CLAIMED', 'CANCELLED')),

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: elanı kim açıb sualı bildirişin ünvanıdır
    -- (tutulma xəbəri elanı açana gedir) və audit izidir.
    posted_by       UUID REFERENCES employees(id) ON DELETE SET NULL,

    claimed_by      UUID REFERENCES employees(id) ON DELETE SET NULL,
    claimed_at      TIMESTAMPTZ,

    -- ƏLAVƏ SÜTUNLAR — ƏSASLANDIRMA: ləğv QƏRARDIR; kim, nə vaxt, niyə
    -- yazılmasa "elan yoxa çıxdı" şikayəti cavabsız qalır.
    cancelled_by    UUID REFERENCES employees(id) ON DELETE SET NULL,
    cancelled_at    TIMESTAMPTZ,
    cancel_reason   TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- (a) qat: yarımçıq "tutulmuş" sətir mümkün deyil.
    CONSTRAINT chk_open_shift_claim
        CHECK ((status = 'CLAIMED' AND claimed_by IS NOT NULL AND claimed_at IS NOT NULL)
            OR (status <> 'CLAIMED' AND claimed_by IS NULL AND claimed_at IS NULL)),
    CONSTRAINT chk_open_shift_cancel
        CHECK ((status = 'CANCELLED' AND cancelled_by IS NOT NULL AND cancelled_at IS NOT NULL)
            OR (status <> 'CANCELLED' AND cancelled_by IS NULL AND cancelled_at IS NULL))
);

DROP TRIGGER IF EXISTS trg_open_shift_postings_updated ON open_shift_postings;
CREATE TRIGGER trg_open_shift_postings_updated BEFORE UPDATE ON open_shift_postings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- (c) qat: eyni slot üçün İKİ açıq elan olmamalıdır — əks halda iki işçi
-- "eyni" növbəni götürər və hər ikisi qalib sayılardı.
CREATE UNIQUE INDEX IF NOT EXISTS uq_open_shift_one_open_per_slot
    ON open_shift_postings (tenant_id, store_id, shift_date, work_mode_id)
    WHERE status = 'OPEN';

-- (c) qat: bir işçi eyni günə İKİ elan tuta bilməz. `shift_assignments`
-- UNIQUE (employee_id, shift_date) qaydasının elan mərhələsindəki əkizidir —
-- pozuntu təyinetmə anında yox, BASMA anında tutulur.
CREATE UNIQUE INDEX IF NOT EXISTS uq_open_shift_one_claim_per_employee_day
    ON open_shift_postings (tenant_id, claimed_by, shift_date)
    WHERE status = 'CLAIMED';

-- İşçinin gördüyü siyahı: "mənim mağazamda açıq növbələr".
CREATE INDEX IF NOT EXISTS idx_open_shift_postings_open
    ON open_shift_postings (tenant_id, store_id, shift_date)
    WHERE status = 'OPEN';

-- (b) qat — STATUS KEÇİD TRIGGER-İ: "İLK BASAN QAZANIR"IN DB TƏMİNATI.
--
-- Tətbiq qatı `SELECT ... FOR UPDATE` + `WHERE status = 'OPEN'` işlədəcək.
-- Bu trigger həmin şərt UNUDULSA da qalibi qoruyur: `CLAIMED` sətrin statusu
-- bir daha dəyişə bilmir və `claimed_by` üstündən yazıla bilmir. Uduzan
-- tranzaksiya sükutla "qalib" olmaq əvəzinə AÇIQ xəta alır — sükutla üstən
-- yazma məhz aşkarlanması ən çətin qüsur növüdür.
CREATE OR REPLACE FUNCTION enforce_open_shift_claim_transition() RETURNS TRIGGER AS $$
BEGIN
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
            'keçə bilməz — yalnız OPEN elan tutula və ya ləğv edilə bilər (#16)',
            OLD.status, NEW.status;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_open_shift_claim_transition() IS
    '#16 "ilk basan qazanır" qaydasının DB qatı: status yalnız OPEN-dən çıxa '
    'bilər və tutulmuş elanın sahibi dondurulur (bax `migrations/015` başlığı — '
    'struktur zəmanət iki yerdə yaşayır).';

DROP TRIGGER IF EXISTS trg_open_shift_claim_transition ON open_shift_postings;
CREATE TRIGGER trg_open_shift_claim_transition
    BEFORE UPDATE ON open_shift_postings
    FOR EACH ROW EXECUTE FUNCTION enforce_open_shift_claim_transition();

COMMENT ON TABLE open_shift_postings IS
    '#16 — Açıq növbə bazarı. Elan ŞABLONA (`work_modes`) istinad edir, çünki '
    'konkret təyinat (`shift_assignments`) hələ mövcud deyil — elanın mənası '
    'məhz budur. "İlk basan qazanır" üç qatla qorunur: CHECK + qismən unikal '
    'indekslər + status keçid trigger-i.';
COMMENT ON COLUMN open_shift_postings.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN open_shift_postings.tenant_id IS 'Kirayəçi izolyasiyası — RLS açarı.';
COMMENT ON COLUMN open_shift_postings.store_id IS 'Növbənin açıq olduğu mağaza.';
COMMENT ON COLUMN open_shift_postings.shift_date IS 'Növbənin tarixi.';
COMMENT ON COLUMN open_shift_postings.work_mode_id IS
    'Növbə şablonu (spesifikasiyadakı `shift_id`). KompasOS-da `shifts` cədvəli '
    'yoxdur; şablon `work_modes`, konkret təyinat isə `shift_assignments`-dədir.';
COMMENT ON COLUMN open_shift_postings.status IS
    'OPEN → CLAIMED / CANCELLED. Geri keçid YOXDUR (trigger bloklayır). '
    'CANCELLED spesifikasiyaya ƏLAVƏDİR: geri çəkilən elan silinmir, söndürülür.';
COMMENT ON COLUMN open_shift_postings.posted_by IS
    'Elanı açan şəxs — tutulma bildirişinin ünvanı və audit izi.';
COMMENT ON COLUMN open_shift_postings.claimed_by IS
    'Elanı TUTAN işçi. Dolduqdan sonra dəyişdirilə bilməz (trigger).';
COMMENT ON COLUMN open_shift_postings.claimed_at IS 'Tutulma anı (tz-aware).';
COMMENT ON COLUMN open_shift_postings.cancelled_by IS 'Elanı ləğv edən şəxs.';
COMMENT ON COLUMN open_shift_postings.cancelled_at IS 'Ləğv anı (tz-aware).';
COMMENT ON COLUMN open_shift_postings.cancel_reason IS
    'Ləğvin səbəbi — elanı görmüş işçinin "hara getdi?" sualının cavabı.';
COMMENT ON COLUMN open_shift_postings.created_at IS 'Elanın yaradılma anı (tz-aware).';
COMMENT ON COLUMN open_shift_postings.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

COMMENT ON INDEX uq_open_shift_one_claim_per_employee_day IS
    'YARIŞ QAPAĞI (#16): bir işçi eyni günə yalnız BİR açıq növbə tuta bilər. '
    'Yalnız CLAIMED sətirlər əhatə olunur — ləğv edilmiş və açıq elanlar '
    'işçinin növbəti seçimini bloklamamalıdır.';

-- ---------------------------------------------------------------------------
-- 4. RLS — fail-closed (SEC-008)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'staffing_pattern_suggestions', 'overtime_log', 'open_shift_postings'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I
                 USING (tenant_id = current_tenant_id())
                 WITH CHECK (tenant_id = current_tenant_id())', t
        );
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------------
-- 5. GRANT — tətbiq rolu
-- ---------------------------------------------------------------------------
-- `DELETE` yalnız `staffing_pattern_suggestions`-a verilir: o, tam törəmə
-- məlumatdır və mağaza bağlananda köhnə təklifin təmizlənməsi qanunidir.
-- `overtime_log` və `open_shift_postings` isə hadisə qeydidir — birincisi əmək
-- saatı iddiasının, ikincisi "kim hansı növbəni götürdü" faktının sübutudur.
--
-- AÇIQ `REVOKE` MƏCBURİDİR: `schema.sql` §28-dəki `ALTER DEFAULT PRIVILEGES`
-- yeni cədvəllərə `DELETE`-i AVTOMATİK verir. Dar `GRANT` tək başına
-- məhdudiyyət yaratmır (ətraflı izah `migrations/018`-dədir).
--
-- XÜSUSİ QEYD (#16): `open_shift_postings`-də `DELETE` olsaydı, uduzan tərəf
-- tutulmuş elanı SİLİB yenisini yarada və "ilk basan qazanır" qaydasını yan
-- keçə bilərdi — trigger yalnız `UPDATE` yolunu bağlayır.
DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON staffing_pattern_suggestions '
            'TO %I', v_role
        );
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE ON overtime_log, open_shift_postings '
            'TO %I', v_role
        );
        EXECUTE format(
            'REVOKE DELETE ON overtime_log, open_shift_postings FROM %I', v_role
        );
    ELSE
        RAISE NOTICE 'Rol "%" yoxdur — GRANT atlandı.', v_role;
    END IF;
END
$$;

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: `open_shift_postings` silinsə, "bu növbəni kim götürdü" sualının
-- cavabı YALNIZ `shift_assignments`-dəki nəticə sətrində qalır — yəni növbənin
-- könüllü götürüldüyü, admin tərəfindən təyin edilmədiyi faktı itir.
-- `overtime_log` silinməsi isə əmək saatı iddialarının struktur izini yox edir.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_open_shift_claim_transition ON open_shift_postings;
--   DROP FUNCTION IF EXISTS enforce_open_shift_claim_transition();
--   DROP TABLE IF EXISTS open_shift_postings;
--   DROP TABLE IF EXISTS overtime_log;
--   DROP TABLE IF EXISTS staffing_pattern_suggestions;
-- COMMIT;
