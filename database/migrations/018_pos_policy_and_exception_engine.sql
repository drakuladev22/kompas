-- ===========================================================================
-- 018 — POS SƏLAHİYYƏT SİYASƏTİ, DAVRANIŞ BAZ XƏTTİ VƏ İSTİSNA MOTORU
-- ===========================================================================
-- Tarix : 2026-08-11
-- Səbəb : Faza 1 (kompasos11.md) üç yeni funksiyanın SAXLAMA qatını tələb edir:
--         #7 POS icazə həddi (siyasət-qeydi), #8 işçi davranış baz xətti,
--         #9 vahid İstisna Motoru. Bu miqrasiya YALNIZ cədvəl ƏLAVƏ EDİR —
--         heç bir mövcud cədvəlin sütunu dəyişdirilmir, silinmir, adı
--         dəyişdirilmir.
--
-- İdempotentdir — `IF NOT EXISTS` / `DROP ... IF EXISTS` cütləri ilə iki dəfə
-- icra edilə bilər. DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- 1C SƏRHƏDİ (kompasos11.md, MÜTLƏQ QAYDA)
-- ---------------------------------------------------------------------------
-- Buradakı HEÇ BİR cədvəl 1C-yə yeni bağlantı/sync/oxuma nöqtəsi AÇMIR.
-- Sistemdə 1C-yə toxunan yeganə kanal Satış Xalları axınıdır
-- (`sales_transactions` → `points_ledger`) və ona TOXUNULMUR.
--
-- Xüsusilə `pos_permission_thresholds`: adında "POS" olsa da, KompasOS-un öz
-- kassa ekranı YOXDUR və bu cədvəl heç bir kassa əməliyyatını yoxlamır. O,
-- SƏNƏDLƏŞDİRMƏ qeydidir — "bu işçiyə rəsmən hansı endirim/ləğv/geri-qaytarma
-- səlahiyyəti verilib?" sualının HR/audit cavabı. Avtomatik pozuntu-aşkarlama
-- hissəsi qəsdən ÇIXARILIB (o, 1C əməliyyat-sync-i tələb edirdi) — cədvəl
-- İstisna Motoruna heç nə göndərmir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `exception_sources` KATALOQU VAR — SƏRT `CHECK` SİYAHISI NİYƏ RƏDD EDİLDİ
-- ---------------------------------------------------------------------------
-- `exceptions.source` bu partiyada YALNIZ `BEHAVIOR_ANOMALY` dəyərini alır,
-- lakin motorun bütün dəyəri gələcək mənbələrin ASAN əlavə olunmasındadır
-- (kompasos11.md, struktur qərar B). Üç variant nəzərdən keçirildi:
--
--   (a) `CREATE TYPE ... AS ENUM` — PostgreSQL-də ENUM dəyəri SİLİNMİR və
--       hər yeni mənbə DDL (miqrasiya + deploy) tələb edir. Üstəlik ENUM
--       dəyərinə insan-oxunaqlı ad/izah/defolt ciddiyyət BAĞLANA BİLMİR —
--       ekran yenə kodda ikinci sözlük saxlamalı olardı (məhz `menu.py`
--       başlığındakı ikili-ad-məkanı qüsuru).
--   (b) `TEXT ... CHECK (source IN (...))` — eyni problem: hər yeni mənbə
--       üçün `DROP CONSTRAINT` + `ADD CONSTRAINT` miqrasiyası.
--   (c) SEÇİLDİ: kataloq cədvəli + `FOREIGN KEY`. Yeni mənbə bir `INSERT`-dir,
--       adı və izahı bazadadır (Azərbaycanca, bölmə 9), köhnəlmiş mənbə isə
--       `is_active = FALSE` ilə söndürülür — SİLİNMİR, çünki keçmiş istisna
--       sətirləri hansı qaydadan doğduğunu SÜBUT etməlidir (soft delete
--       qaydası, `catalogs.py` başlığı).
--
-- `tenant_id` NULL = sistem mənbəyi (bütün tenant-lar görür). Bu, `positions`
-- cədvəlindəki mövcud naxışın eynidir və RLS siyasəti də oradan köçürülüb.
-- Kod tərəfindəki qayda reyestri (Faza 3) `code` üzərindən bağlanır, ona görə
-- `code` QLOBAL unikaldır: iki tenant eyni kodu fərqli mənada işlətsəydi,
-- reyestr hansı implementasiyanı seçəcəyini bilməzdi.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
-- (Son 6 miqrasiyada bu sətir unudulmuşdu — CI-da 010 məhz buna görə çökürdü.)
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. pos_permission_thresholds (#7) — SİYASƏT QEYDİ, YOXLAMA MOTORU DEYİL
-- ---------------------------------------------------------------------------
-- NİYƏ TARİXÇƏ CƏDVƏLİ DEYİL: hər dəyişikliyin kim/nə vaxt/nədən izi onsuz da
-- `audit_logs`-a düşür (CLAUDE.md §5 — audit yazısı istisna udmur). Ayrıca
-- versiya cədvəli EYNİ məlumatı İKİNCİ mənbədə saxlayardı və "hansı doğrudur?"
-- sualı yaranardı. Ona görə burada işçi başına BİR DİRİ sətir var, tarixçə isə
-- mərkəzi audit jurnalındadır.
CREATE TABLE IF NOT EXISTS pos_permission_thresholds (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL REFERENCES license_tenants(tenant_id)
                           ON DELETE CASCADE,
    -- CASCADE: siyasət qeydinin işçidən ayrı mənası yoxdur. Qərarın DAİMİ izi
    -- `audit_logs`-dadır, ona görə bu sətrin itməsi sübut itkisi DEYİL.
    employee_id        UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,

    max_discount_pct   NUMERIC(5, 2) NOT NULL DEFAULT 0
                           CHECK (max_discount_pct >= 0 AND max_discount_pct <= 100),
    can_void           BOOLEAN NOT NULL DEFAULT FALSE,
    can_refund         BOOLEAN NOT NULL DEFAULT FALSE,

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: səlahiyyət rəqəmi tək başına müdafiə oluna
    -- bilmir. Mübahisədə soruşulan sual "hədd nə idi?" deyil, "NİYƏ bu hədd
    -- verildi?"dir. Səbəbsiz siyasət qeydi sənəd sayılmır.
    note               TEXT,

    -- ƏLAVƏ SÜTUNLAR — ƏSASLANDIRMA (soft delete qaydası): səlahiyyətin GERİ
    -- ALINMASI fiziki `DELETE` ilə edilsəydi, keçmiş hadisənin araşdırılması
    -- zamanı "o gün bu işçinin nə səlahiyyəti vardı?" sualı cavabsız qalardı.
    -- `is_active = FALSE` sətri saxlayır, `deactivated_*` isə kim/nə vaxt
    -- sualını cavablandırır.
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    deactivated_at     TIMESTAMPTZ,
    deactivated_by     UUID REFERENCES employees(id) ON DELETE SET NULL,

    -- Sonuncu dəyişikliyi edən şəxs (spesifikasiyadakı `updated_by`).
    -- SET NULL: qeyd sətri işçi profilindən daha uzun yaşamalıdır.
    updated_by         UUID REFERENCES employees(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Bir işçinin EYNİ anda iki fərqli rəsmi həddi ola bilməz.
    UNIQUE (tenant_id, employee_id),
    CONSTRAINT chk_pos_threshold_deactivation
        CHECK (is_active OR deactivated_at IS NOT NULL)
);

DROP TRIGGER IF EXISTS trg_pos_thresholds_updated ON pos_permission_thresholds;
CREATE TRIGGER trg_pos_thresholds_updated BEFORE UPDATE ON pos_permission_thresholds
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_pos_thresholds_tenant
    ON pos_permission_thresholds (tenant_id) WHERE is_active;

COMMENT ON TABLE pos_permission_thresholds IS
    '#7 — İşçinin RƏSMİ kassa səlahiyyəti (endirim/ləğv/geri-qaytarma). '
    'YALNIZ sənədləşdirmə: heç bir əməliyyat bu cədvələ görə bloklanmır və '
    'İstisna Motoruna heç nə göndərilmir (avtomatik aşkarlama 1C sync-i tələb '
    'edirdi — kompasos11.md struktur qərarı A ilə çıxarıldı).';
COMMENT ON COLUMN pos_permission_thresholds.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN pos_permission_thresholds.tenant_id IS
    'Kirayəçi izolyasiyası — RLS `tenant_isolation` siyasətinin açarı.';
COMMENT ON COLUMN pos_permission_thresholds.employee_id IS
    'Səlahiyyəti daşıyan işçi. Bir işçiyə bir diri sətir (UNIQUE).';
COMMENT ON COLUMN pos_permission_thresholds.max_discount_pct IS
    'İcazə verilən maksimum endirim faizi (0–100). DEFOLT 0 — səlahiyyət '
    'açıq verilməyibsə YOXDUR (fail-closed, SEC-008 fəlsəfəsi).';
COMMENT ON COLUMN pos_permission_thresholds.can_void IS
    'Satışı ləğv etmə səlahiyyəti verilibmi (sənəd qeydi).';
COMMENT ON COLUMN pos_permission_thresholds.can_refund IS
    'Geri-qaytarma səlahiyyəti verilibmi (sənəd qeydi).';
COMMENT ON COLUMN pos_permission_thresholds.note IS
    'Səlahiyyətin NİYƏ verildiyi — səbəbsiz hədd mübahisədə müdafiə olunmur.';
COMMENT ON COLUMN pos_permission_thresholds.is_active IS
    'Soft delete: FALSE = səlahiyyət geri alınıb. Sətir SİLİNMİR, çünki '
    'keçmiş hadisənin araşdırılması "o gün hədd nə idi?" sualını verir.';
COMMENT ON COLUMN pos_permission_thresholds.deactivated_at IS
    'Səlahiyyətin geri alınma anı (tz-aware).';
COMMENT ON COLUMN pos_permission_thresholds.deactivated_by IS
    'Səlahiyyəti geri alan şəxs. İşçi qeydi silinsə NULL olur, sətir qalır.';
COMMENT ON COLUMN pos_permission_thresholds.updated_by IS
    'Həddi sonuncu dəfə təyin/dəyişən şəxs. TAM tarixçə `audit_logs`-dadır.';
COMMENT ON COLUMN pos_permission_thresholds.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN pos_permission_thresholds.updated_at IS
    'Sonuncu dəyişiklik anı — `set_updated_at()` trigger-i doldurur.';

-- ---------------------------------------------------------------------------
-- 2. employee_behavior_baseline (#8) — DAVRANIŞ BAZ XƏTTİ
-- ---------------------------------------------------------------------------
-- NİYƏ `TIME` DEYİL, DƏQİQƏ: "orta check-in vaxtı" STATİSTİKADIR, an deyil.
-- `TIME` üzərində çıxma `INTERVAL` verir və onu `variance` (kvadrat vahid) ilə
-- müqayisə etmək mənasızdır; həmçinin orta hesablamaq üçün hər dəfə çevirmə
-- lazım gələrdi. Ona görə dəyər GECƏYARIDAN keçən dəqiqə sayı kimi saxlanılır.
--
-- TZ QAYDASI İLƏ ZİDDİYYƏT YOXDUR: CLAUDE.md `datetime`-ın tz-aware olmasını
-- tələb edir — bu sütun `datetime` DEYİL, günün-vaxtı statistikasıdır və
-- MAĞAZANIN yerli zaman qurşağındadır (`stores.timezone`). Hesablayan tərəf
-- UTC damğasını yerli vaxta çevirdikdən SONRA bura yazmalıdır; əks halda
-- qurşaq dəyişikliyi baz xəttini bir saat sürüşdürərdi.
CREATE TABLE IF NOT EXISTS employee_behavior_baseline (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id              UUID NOT NULL REFERENCES license_tenants(tenant_id)
                               ON DELETE CASCADE,
    -- CASCADE: baz xətti tam törəmə məlumatdır — istənilən an yenidən
    -- hesablana bilər, ona görə saxlanmasına ehtiyac yoxdur.
    employee_id            UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,

    avg_checkin_minutes    NUMERIC(6, 2) NOT NULL
                               CHECK (avg_checkin_minutes >= 0
                                  AND avg_checkin_minutes < 1440),
    -- SPESİFİKASİYADAKI `variance` — ƏSASLANDIRMA: kvadrat vahid əvəzinə
    -- STANDART KƏNARLAŞMA saxlanılır. Anomaliya yoxlaması "orta ± k×σ"
    -- şəklindədir; variance saxlansaydı hər müqayisədə kvadrat kök alınardı və
    -- vahid ortanın vahidi ilə uyğun gəlməzdi. Variance = stddev².
    stddev_minutes         NUMERIC(6, 2) NOT NULL DEFAULT 0
                               CHECK (stddev_minutes >= 0),

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: 3 günlük müşahidədən çıxan "baz xətt" ilə
    -- anomaliya elan etmək yanlış ittihamdır. İstehlakçı (Faza 5) minimum
    -- nümunə həddini yoxlamalıdır və bunun üçün nümunə sayını BİLMƏLİDİR.
    sample_size            INTEGER NOT NULL DEFAULT 0 CHECK (sample_size >= 0),

    last_calculated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Bir işçinin bir diri baz xətti olur; yenidən hesablama UPSERT-dir.
    UNIQUE (tenant_id, employee_id)
);

DROP TRIGGER IF EXISTS trg_behavior_baseline_updated ON employee_behavior_baseline;
CREATE TRIGGER trg_behavior_baseline_updated BEFORE UPDATE ON employee_behavior_baseline
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Köhnəlmiş baz xətlərini tapmaq üçün (planlaşdırılmış yenidən hesablama).
CREATE INDEX IF NOT EXISTS idx_behavior_baseline_stale
    ON employee_behavior_baseline (tenant_id, last_calculated_at);

COMMENT ON TABLE employee_behavior_baseline IS
    '#8 — İşçinin ADƏTİ davranışı (orta check-in vaxtı və yayılması). '
    'Törəmə məlumatdır: `attendance_records`-dan yenidən hesablana bilər, '
    'ona görə ehtiyat nüsxə/bərpa üçün kritik deyil.';
COMMENT ON COLUMN employee_behavior_baseline.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN employee_behavior_baseline.tenant_id IS
    'Kirayəçi izolyasiyası — RLS açarı.';
COMMENT ON COLUMN employee_behavior_baseline.employee_id IS
    'Baz xətti aid olan işçi (işçi başına BİR sətir).';
COMMENT ON COLUMN employee_behavior_baseline.avg_checkin_minutes IS
    'Orta check-in vaxtı — MAĞAZANIN yerli gecəyarısından keçən dəqiqə '
    '(məs. 08:30 → 510.00). `TIME` deyil, çünki statistik hesablama tələb olunur.';
COMMENT ON COLUMN employee_behavior_baseline.stddev_minutes IS
    'Standart kənarlaşma (dəqiqə). Spesifikasiyadakı "variance" bunun '
    'kvadratıdır; kənarlaşma saxlanılır ki, ortanın vahidi ilə müqayisə oluna bilsin.';
COMMENT ON COLUMN employee_behavior_baseline.sample_size IS
    'Baz xəttinin neçə günlük müşahidədən çıxdığı. Az nümunədə anomaliya '
    'elan edilməməlidir — həddi Faza 5-də `system_limits`-dən oxunur.';
COMMENT ON COLUMN employee_behavior_baseline.last_calculated_at IS
    'Sonuncu hesablama anı (tz-aware). Köhnə baz xətti yanlış siqnal verir.';
COMMENT ON COLUMN employee_behavior_baseline.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN employee_behavior_baseline.updated_at IS
    'Sonuncu dəyişiklik anı — trigger doldurur.';

-- ---------------------------------------------------------------------------
-- 3. exception_sources (#9) — GENİŞLƏNƏ BİLƏN MƏNBƏ KATALOQU
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS exception_sources (
    code               TEXT PRIMARY KEY
                           CHECK (code = upper(code)
                              AND char_length(trim(code)) >= 3),
    -- NULL = SİSTEM mənbəyi (bütün tenant-lar görür) — `positions` naxışı.
    -- Dolu = yalnız həmin tenant-ın öz mənbəyi.
    tenant_id          UUID REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    name_az            TEXT NOT NULL,
    description_az     TEXT,

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA (MƏRKƏZİ TƏLƏB: ROOT-dan idarə): motor
    -- istisnanı yaradarkən ciddiyyəti həmişə hesablaya bilmir. Defolt dəyər
    -- KODDA sabit yazılsaydı, onu dəyişmək üçün yeni buraxılış lazım olardı.
    default_severity   TEXT NOT NULL DEFAULT 'MEDIUM'
                           CHECK (default_severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),

    -- Soft delete: köhnəlmiş mənbə söndürülür, SİLİNMİR — keçmiş istisnalar
    -- hansı qaydadan doğduğunu göstərə bilməlidir.
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    deactivated_at     TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_exception_source_deactivation
        CHECK (is_active OR deactivated_at IS NOT NULL)
);

DROP TRIGGER IF EXISTS trg_exception_sources_updated ON exception_sources;
CREATE TRIGGER trg_exception_sources_updated BEFORE UPDATE ON exception_sources
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE exception_sources IS
    '#9 — İstisna Motorunun MƏNBƏ kataloqu. Yeni mənbə DDL-siz, sadə `INSERT` '
    'ilə əlavə olunur (ENUM/CHECK siyahısı qəsdən rədd edildi — hər ikisi '
    'miqrasiya tələb edərdi). `tenant_id IS NULL` = sistem mənbəyi.';
COMMENT ON COLUMN exception_sources.code IS
    'Mənbə kodu (BÖYÜK hərflərlə). Faza 3 qayda reyestri KODDA bu açarla '
    'bağlanır, ona görə QLOBAL unikaldır — iki tenant eyni kodu fərqli mənada '
    'işlətsəydi reyestr hansı qaydanı seçəcəyini bilməzdi.';
COMMENT ON COLUMN exception_sources.tenant_id IS
    'NULL = bütün tenant-lar üçün sistem mənbəyi (`positions` naxışı); '
    'dolu = yalnız həmin kirayəçinin mənbəyi.';
COMMENT ON COLUMN exception_sources.name_az IS
    'İstisnalar ekranında görünən ad — Azərbaycanca (bölmə 9). Mətn BAZADADIR '
    'ki, ekran ikinci ad məkanı qurmasın (`menu.py` başlığındakı qüsur növü).';
COMMENT ON COLUMN exception_sources.description_az IS
    'Mənbənin nə aşkarladığının izahı — istisnaya baxan şəxs üçün kontekst.';
COMMENT ON COLUMN exception_sources.default_severity IS
    'Motor ciddiyyəti təyin etmədikdə istifadə olunan defolt. Kodda sabit '
    'YAZILMIR — dəyişikliyi Root buraxılışsız edə bilməlidir.';
COMMENT ON COLUMN exception_sources.is_active IS
    'Soft delete: FALSE = yeni istisna YARATMIR, mövcud sətirlər toxunulmaz qalır '
    '(Feature Toggle-ın retroaktiv olmaması qaydası ilə eyni məntiq).';
COMMENT ON COLUMN exception_sources.deactivated_at IS 'Söndürülmə anı (tz-aware).';
COMMENT ON COLUMN exception_sources.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN exception_sources.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

-- Bu partiyanın YEGANƏ mənbəyi (kompasos11.md struktur qərarı B).
-- `ON CONFLICT DO NOTHING`: təkrar icrada mətn ÜSTÜNDƏN YAZILMIR — müştərinin
-- öz redaktəsi miqrasiya tərəfindən geri qaytarılmamalıdır (017 ilə eyni qayda).
INSERT INTO exception_sources (code, tenant_id, name_az, description_az, default_severity)
VALUES ('BEHAVIOR_ANOMALY', NULL, 'Davranış anomaliyası',
        'İşçinin check-in vaxtı öz baz xəttindən əhəmiyyətli dərəcədə '
        'kənarlaşdıqda yaranır (#8).', 'MEDIUM')
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. exceptions (#9) — VAHİD İSTİSNA JURNALI
-- ---------------------------------------------------------------------------
-- NİYƏ `severity` və `status` SƏRT SİYAHIDIR, `source` İSƏ YOX:
--   * `severity` UI davranışını idarə edir (sıralama, rəng, bildiriş həddi) —
--     yeni dəyər KOD dəyişikliyi olmadan mənasızdır, ona görə sərt siyahı
--     doğru qapıdır;
--   * `status` iş axınının özüdür (OPEN → REVIEWED/DISMISSED) — genişlənməsi
--     yeni ekran deməkdir;
--   * `source` isə YENİ MƏNBƏ deməkdir və məhz genişlənmə nöqtəsidir → kataloq.
CREATE TABLE IF NOT EXISTS exceptions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES license_tenants(tenant_id)
                       ON DELETE CASCADE,

    -- NO ACTION: mənbə kataloqu istisna sətirləri qalarkən SİLİNƏ BİLMƏZ.
    -- Söndürmə yolu `is_active = FALSE`-dır (soft delete), ona görə bu
    -- məhdudiyyət normal iş axınını bloklamır.
    source         TEXT NOT NULL REFERENCES exception_sources(code) ON DELETE NO ACTION,

    -- CASCADE: istisna işçi haqqındadır; işçi qeydi fiziki silinərsə (praktikada
    -- soft delete işlədilir) istisnanın subyekti qalmır.
    employee_id    UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    store_id       UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,

    detail         TEXT NOT NULL CHECK (char_length(trim(detail)) >= 5),

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: `detail` insan üçün cümlədir, lakin istisnaya
    -- baxan şəxs "hansı rəqəmlər bu nəticəni verdi?" soruşur. Qara-qutu siqnal
    -- HR/intizam qərarını əsaslandıra bilməz (eyni prinsip #21-in
    -- `factors_json` sütununda da tətbiq olunur).
    context_json   JSONB NOT NULL DEFAULT '{}'::jsonb
                       CHECK (jsonb_typeof(context_json) = 'object'),

    severity       TEXT NOT NULL DEFAULT 'MEDIUM'
                       CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    status         TEXT NOT NULL DEFAULT 'OPEN'
                       CHECK (status IN ('OPEN', 'REVIEWED', 'DISMISSED')),

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: aşkarlama planlaşdırılmış işdir
    -- (`scheduled_job_runs`) və hər gün yenidən işləyir. Açar olmasaydı EYNİ
    -- tapıntı hər icrada təkrar yaranar, "DISMISSED" qərarı isə sabah yenidən
    -- açılardı. Açar qayda + işçi + tarixi kodlamalıdır.
    dedupe_key     TEXT,

    -- ƏLAVƏ SÜTUNLAR — ƏSASLANDIRMA: `status` dəyişikliyi QƏRARDIR; kim, nə
    -- vaxt və hansı əsasla bağladığı yazılmasa "baxılıb" sözünün sahibi olmaz.
    reviewed_by    UUID REFERENCES employees(id) ON DELETE SET NULL,
    reviewed_at    TIMESTAMPTZ,
    review_note    TEXT,

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- `shift_swap_requests.chk_swap_decision` ilə eyni naxış: qərar statusu
    -- qərar verəni tələb edir.
    CONSTRAINT chk_exception_review
        CHECK (status = 'OPEN'
            OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);

DROP TRIGGER IF EXISTS trg_exceptions_updated ON exceptions;
CREATE TRIGGER trg_exceptions_updated BEFORE UPDATE ON exceptions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- "İstisnalar" ekranının ƏSAS sorğusu — açıq istisnalar, ən yenisi əvvəldə.
CREATE INDEX IF NOT EXISTS idx_exceptions_open
    ON exceptions (tenant_id, created_at DESC) WHERE status = 'OPEN';
-- İşçi detal panelində "bu işçinin istisnaları" bölməsi.
CREATE INDEX IF NOT EXISTS idx_exceptions_employee
    ON exceptions (employee_id, created_at DESC);
-- Mağaza üzrə süzgəc (Mağaza Meneceri yalnız öz filialını görür).
CREATE INDEX IF NOT EXISTS idx_exceptions_store
    ON exceptions (store_id, created_at DESC);

-- TƏKRAR-YARATMA QAPAĞI: statusdan ASILI OLMAYAN unikallıq. Şərtə
-- `status = 'OPEN'` əlavə edilsəydi, rədd edilmiş (DISMISSED) tapıntı növbəti
-- gecə yenidən yaranar və "bir dəfə rədd etdim" qərarı mənasını itirərdi.
CREATE UNIQUE INDEX IF NOT EXISTS uq_exceptions_dedupe
    ON exceptions (tenant_id, source, dedupe_key)
    WHERE dedupe_key IS NOT NULL;

COMMENT ON TABLE exceptions IS
    '#9 — Vahid İstisna Jurnalı. Bu partiyada yeganə mənbə `BEHAVIOR_ANOMALY` '
    'olsa da, motor çox-mənbəli dizayn edilib (kompasos11.md struktur qərarı B). '
    '#7 bura heç nə göndərmir — o, avtomatik aşkarlama etmir.';
COMMENT ON COLUMN exceptions.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN exceptions.tenant_id IS 'Kirayəçi izolyasiyası — RLS açarı.';
COMMENT ON COLUMN exceptions.source IS
    'Mənbə kodu — `exception_sources` kataloquna FK. Sərt CHECK siyahısı '
    'QƏSDƏN işlədilmir: yeni mənbə DDL tələb etməməlidir.';
COMMENT ON COLUMN exceptions.employee_id IS 'İstisnanın aid olduğu işçi.';
COMMENT ON COLUMN exceptions.store_id IS
    'Hadisənin baş verdiyi mağaza — mağaza-əhatəli süzgəc üçün AYRICA saxlanılır; '
    'işçi sonradan başqa filiala keçsə, tarixi istisna öz filialında qalmalıdır.';
COMMENT ON COLUMN exceptions.detail IS
    'İnsan-oxunaqlı izah (Azərbaycanca) — ekranda göstərilən mətn.';
COMMENT ON COLUMN exceptions.context_json IS
    'Aşkarlamanın RƏQƏMLƏRİ (baz xətt, faktiki dəyər, kənarlaşma). Qara-qutu '
    'siqnal intizam qərarını əsaslandıra bilməz.';
COMMENT ON COLUMN exceptions.severity IS
    'LOW/MEDIUM/HIGH/CRITICAL — sıralama və bildiriş həddini idarə edir. '
    'Siyahı SƏRTDİR, çünki yeni dəyər kod dəyişikliyi olmadan mənasızdır.';
COMMENT ON COLUMN exceptions.status IS
    'OPEN → REVIEWED / DISMISSED. Sətir heç vaxt SİLİNMİR: rədd edilmiş '
    'istisna da "buna baxıldı və əsassız sayıldı" faktının sübutudur.';
COMMENT ON COLUMN exceptions.dedupe_key IS
    'Təkrar-yaratma açarı (qayda+işçi+tarix). Planlaşdırılmış aşkarlama hər gün '
    'işləyir; açar olmadan eyni tapıntı hər icrada təzələnərdi.';
COMMENT ON COLUMN exceptions.reviewed_by IS 'Qərarı verən şəxs (OPEN-dən çıxaran).';
COMMENT ON COLUMN exceptions.reviewed_at IS 'Qərar anı (tz-aware).';
COMMENT ON COLUMN exceptions.review_note IS 'Qərarın əsası — "niyə rədd edildi?".';
COMMENT ON COLUMN exceptions.created_at IS 'Aşkarlanma anı (tz-aware).';
COMMENT ON COLUMN exceptions.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

-- ---------------------------------------------------------------------------
-- 5. RLS — YENİ CƏDVƏLLƏR DƏ FAIL-CLOSED OLMALIDIR (SEC-008)
-- ---------------------------------------------------------------------------
-- `app.tenant_id` təyin edilməyibsə tətbiq rolu HEÇ BİR sətir görmür.
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'pos_permission_thresholds', 'employee_behavior_baseline', 'exceptions'
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

-- `exception_sources` — `positions` naxışı: sistem sətirləri (tenant_id IS NULL)
-- hər kirayəçiyə GÖRÜNÜR, lakin heç kim onları öz adına yaza bilmir
-- (`WITH CHECK` yalnız öz tenant_id-sinə icazə verir).
ALTER TABLE exception_sources ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON exception_sources;
CREATE POLICY tenant_isolation ON exception_sources
    USING (tenant_id = current_tenant_id() OR tenant_id IS NULL)
    WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- 6. GRANT — tətbiq rolu (schema.sql-dəki GRANT yalnız həmin an mövcud
--    cədvəllərə tətbiq olunub)
-- ---------------------------------------------------------------------------
-- `DELETE` QƏSDƏN VERİLMİR: bu cədvəllərin hamısı ya sübut sətridir
-- (`exceptions`, `pos_permission_thresholds`), ya da soft delete ilə idarə
-- olunan kataloqdur (`exception_sources`). Yeganə istisna
-- `employee_behavior_baseline`-dır — o, tam törəmə məlumatdır və işçi
-- siyahısı dəyişəndə köhnə sətirlərin təmizlənməsi qanuni əməliyyatdır.
--
-- ⚠️ NİYƏ `GRANT`-I DAR SAXLAMAQ KİFAYƏT ETMİR — AÇIQ `REVOKE` MƏCBURİDİR
-- ─────────────────────────────────────────────────────────────────────────
-- `schema.sql` §28 sonda belə bir sətir icra edir:
--     ALTER DEFAULT PRIVILEGES IN SCHEMA kompasos
--         GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kompasos_app;
-- Yəni BUNDAN SONRA yaradılan HƏR cədvəl `DELETE` səlahiyyətini AVTOMATİK
-- alır. Sadəcə dar `GRANT` yazsaydıq, məhdudiyyət sükutla mövcud olmazdı və
-- soft delete qaydası yalnız kod nəzakətinə çevrilərdi. Ona görə `audit_logs`
-- və `permission_flags` üçün işlədilən EYNİ naxış təkrarlanır: açıq `REVOKE`.
DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE ON pos_permission_thresholds, '
            'exception_sources, exceptions TO %I', v_role
        );
        EXECUTE format(
            'REVOKE DELETE ON pos_permission_thresholds, exception_sources, '
            'exceptions FROM %I', v_role
        );
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON employee_behavior_baseline '
            'TO %I', v_role
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
-- DİQQƏT: `exceptions` sətirlərinin silinməsi "buna baxıldı və rədd edildi"
-- qərarlarını da yox edir; həmin qərarlar audit sualının cavabıdır.
-- `pos_permission_thresholds` isə "bu işçiyə hansı səlahiyyət verilmişdi?"
-- sualının YEGANƏ struktur cavabıdır (mətn izi `audit_logs`-da qalır).
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TABLE IF EXISTS exceptions;
--   DROP TABLE IF EXISTS exception_sources;
--   DROP TABLE IF EXISTS employee_behavior_baseline;
--   DROP TABLE IF EXISTS pos_permission_thresholds;
-- COMMIT;
