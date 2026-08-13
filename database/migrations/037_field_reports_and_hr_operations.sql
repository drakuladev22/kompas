-- ===========================================================================
-- 037 — SAHƏ HESABATLARI (#26+#27), İLLİK MƏZUNİYYƏT (#28), TOPLU ƏMƏLİYYAT
--       (#29), İCRA XÜLASƏSİ (#30) VƏ EXPORT DÜZƏLİŞLƏRİ (HR-D)
-- ===========================================================================
-- Tarix : 2026-08-13
-- Səbəb : `kompas1.md` Faza 1 — beş yeni funksiya sahəsinin SAXLAMA qatı.
--         Bu miqrasiya YALNIZ cədvəl əlavə edir: mövcud cədvəlin nə sütunu,
--         nə adı, nə tipi dəyişir (QIRMIZI XƏTT).
--
-- İdempotentdir. DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- `work_modes` NİYƏ BU FAYLDA YOXDUR
-- ---------------------------------------------------------------------------
-- `kompas1.md` Faza 1 siyahısında `work_modes` var, LAKİN şərti ilə: "yalnız
-- əgər mövcud deyilsə". O, ARTIQ MÖVCUDDUR — `schema.sql` §11 (`start_time`,
-- `end_time`, `is_overnight`, `is_active`, `created_by`, soft delete,
-- `UNIQUE (tenant_id, name)`), icazə flag-i `can_manage_work_modes`
-- (`schema.sql` §22), `WorkModeCatalogUseCase` və 31-ci ekran hazırdır.
--
-- Təkrar yazsaydıq, `CREATE TABLE IF NOT EXISTS` SÜKUTLA heç nə etməzdi
-- (cədvəl onsuz da var) və `schema.sql` ilə miqrasiya arasında iki fərqli
-- "həqiqət" yaranardı — səhv yalnız istehsalatda üzə çıxardı. Eyni tələ
-- `036`-da yaşandı (`scheduled_job_runs` adı tutulmuşdu → `app_` prefiksi).
--
-- `daily_norm_hours` sütunu da QƏSDƏN ƏLAVƏ EDİLMİR: norma
-- `end_time − start_time`-dan çıxır (`TimeRange.duration`), `migrations/019`
-- isə düzgün naxışı artıq qurub — norma CANLI hesablanır, `overtime_log`-da
-- həmin günə DONDURULUR. Sütun kimi saxlansaydı iki mənbə sürüşərdi.
--
-- ---------------------------------------------------------------------------
-- AD TOQQUŞMASI YOXLAMASI (ad seçməzdən ƏVVƏL icra edilib)
-- ---------------------------------------------------------------------------
-- `schema.sql` + `migrations/001–036` mətnində bu on ad axtarıldı:
--   field_report_types, field_report_categories, field_reports,
--   field_report_checklist_items, annual_leave_balances,
--   annual_leave_requests, bulk_import_log, store_templates,
--   executive_digest_config, export_manual_corrections
-- Nəticə: HEÇ BİRİ mövcud deyil — prefiks/ad dəyişikliyi lazım olmadı.
-- Kəsişən mövcud cədvəllər var, lakin onlar BAŞQA şeydir:
--   * `leave_requests`  — GÜNDAXİLİ icazə (STEP1/STEP2/STEP3, dəqiqə əsaslı
--     cərimə düsturu). `annual_leave_requests` isə GÜN əsaslı, illik balansdan
--     çıxılan, təsdiq axını olan məzuniyyətdir — ikisinin nə vahidi, nə statusu,
--     nə də iş axını üst-üstə düşür (aşağıda ətraflı).
--   * `shift_assignments` — Shift Matrix-in istirahət günü (off-day) sistemi;
--     o, PLAN qurur, məzuniyyət isə HAQQ sərf edir.
--   * `exceptions` (#9) — MAŞIN aşkarlayır; `field_reports` isə İNSAN yazır.
--   * `tasks` — düzəliş tapşırığı ARTIQ orada yaşayır; bu miqrasiya yeni
--     tapşırıq sistemi QURMUR (Struktur Qərar B).
--
-- ---------------------------------------------------------------------------
-- #26 + #27 — NİYƏ BİR CƏDVƏL, NİYƏ İKİ KATALOQ
-- ---------------------------------------------------------------------------
-- Struktur Qərar A: Mağaza Auditi (#26) və İnsident Bildirişi (#27) EYNİ
-- axındır (forma → foto → tapşırıq → bağlanma), yalnız ŞABLONU fərqlidir.
-- Ona görə bir `field_reports` gövdəsi + iki genişlənə bilən kataloq var:
--
--   * `field_report_types`      — şablon reyestri (STORE_AUDIT, INCIDENT)
--   * `field_report_categories` — həmin şablonun kateqoriyaları
--
-- SƏRT `CHECK (type IN (...))` NİYƏ RƏDD EDİLDİ: `migrations/018`-in
-- `exceptions.source` qərarı ilə eyni səbəb — yeni şablon/kateqoriya BİR
-- `INSERT` olmalıdır, miqrasiya yox. Mağaza şəbəkəsi "vitrin" yanına "işıq
-- sistemi" kateqoriyasını əlavə etmək istəyəndə buraxılış gözləməməlidir.
-- ENUM tipi də rədd edildi: `ALTER TYPE ... ADD VALUE` geri qaytarıla bilmir
-- və köhnəlmiş dəyər əbədi qalır (kataloqda `is_active = FALSE` kifayətdir).
--
-- BİRLƏŞMİŞ FK `(type, category) → (report_type, code)` isə kataloq dizaynının
-- ÖDƏNİŞİDİR: iki ayrı tək-sütunlu FK "insident kateqoriyası audit hesabatına"
-- yazılmasını bloklamazdı və uyğunsuzluq yalnız hesabat ekranında görünərdi
-- (`announcement_targets`-dəki birləşmiş FK ilə eyni əsaslandırma).
--
-- ---------------------------------------------------------------------------
-- `photo_refs` NİYƏ `TEXT[]` — MASSİV, JSONB DEYİL, UŞAQ CƏDVƏL DEYİL
-- ---------------------------------------------------------------------------
-- Fayl BAYTI burada saxlanılmır: yükləmə qatı `upload_queue` (lokal SQLite
-- spool) + Google Drive-dır və `owner_type`/`owner_id` ilə onsuz da
-- ümumiləşdirilib. Yəni burada YALNIZ istinad var.
--
--   (a) UŞAQ CƏDVƏL rədd edildi — `announcement_targets`-dən FƏRQLİ olaraq
--       burada FK HƏDƏFİ YOXDUR: növbə cədvəli PostgreSQL-də deyil, terminalın
--       lokal SQLite faylındadır. Uşaq cədvəl bütövlük qazandırmaz, yalnız
--       birləşmə (JOIN) əlavə edərdi. Oxu naxışı da tam-oxumadır: "hesabatı aç
--       → bütün şəkillərini göstər"; "bu şəklə görə hesabat tap" sorğusu yoxdur.
--   (b) JSONB rədd edildi — `jsonb_typeof(...) = 'array'` yalnız MASSİV
--       olduğunu yoxlayır, ELEMENTİN mətn olduğunu YOX: `[{"a":1}, 5]` sükutla
--       qəbul edilərdi. `TEXT[]` element tipini struktur şəkildə zəmanət verir.
--   (c) Per-şəkil metadata (kim, nə vaxt) lazım deyil: hesabatın hamısı BİR
--       təqdimat seansında çəkilir, yəni cavab `reported_by` + `created_at`-dədir.
--
-- ---------------------------------------------------------------------------
-- `passed` NİYƏ ÜÇ VƏZİYYƏTLİ `BOOLEAN NULL`, AYRI SÜTUN DEYİL
-- ---------------------------------------------------------------------------
-- Checklist bəndinin üç cavabı var: keçdi / keçmədi / hələ yoxlanılmadı.
--   * İKİ SÜTUN (`is_checked` + `passed`) rədd edildi: o, ZİDDİYYƏTLİ cütü
--     (`is_checked = FALSE AND passed = TRUE`) mümkün edir və onu bağlamaq
--     üçün yenə CHECK lazım gəlir — yəni mürəkkəblik artır, zəmanət artmır.
--   * ÜÇ-DƏYƏRLİ MƏTN (`PASSED`/`FAILED`/`NOT_CHECKED`) rədd edildi: tətbiq
--     onsuz da üç mətni məntiqi cavaba çevirməli olacaq, üstəlik mətn sahəsi
--     dördüncü, sənədsiz dəyərə açıq qalır.
--   * SEÇİLDİ: `BOOLEAN NULL`, çünki NULL SQL-in "cavab yoxdur" işarəsidir və
--     `count(passed)` (NULL-ları saymır) "neçə bənd cavablanıb?" sualını TƏK
--     aqreqatla verir.
-- NULL-un məlum tələsi (`WHERE passed = FALSE` cavabsız bəndi ATLAYIR) açıq
-- şəkildə bağlanır: Task Engine sorğusunun işlətdiyi qismən indeks məhz
-- `WHERE passed IS FALSE AND is_blocking` predikatı ilə qurulub — düzgün
-- predikat həm də SÜRƏTLİ yoldur.
--
-- ---------------------------------------------------------------------------
-- #28 — ÜST-ÜSTƏ DÜŞƏN MƏZUNİYYƏT: `EXCLUDE USING gist`
-- ---------------------------------------------------------------------------
-- İki nəfər eyni anda təsdiq düyməsini basanda "əvvəlcə oxu, sonra yaz"
-- yoxlaması UDUZUR (`migrations/015` və `036`-dakı eyni dərs). Ona görə qərarı
-- DB verir: təsdiqlənmiş sorğuların tarix aralıqları eyni işçi üçün KƏSİŞƏ
-- BİLMƏZ — `EXCLUDE USING gist (employee_id WITH =, daterange(...) WITH &&)`.
--
--   * Qismən (`WHERE status = 'APPROVED'`) — gözləyən və rədd edilmiş sorğular
--     sərbəst kəsişə bilər, əks halda işçi eyni həftəyə ikinci variant təklif
--     edə bilməzdi.
--   * `tenant_id` QƏSDƏN daxil EDİLMİR: `employee_id` onsuz da bir kirayəçiyə
--     bağlıdır, ona görə əlavə etmək qorumanı GÜCLƏNDİRMƏZ, ƏKSİNƏ zəiflədərdi
--     (tenant sütunu sürüşmüş iki sətir toqquşmaz sayılardı).
--   * `[]` (qapalı-qapalı) aralıq: son gün MƏZUNİYYƏTƏ DAXİLDİR; `[)` yazılsaydı
--     bir sorğunun son günü digərinin ilk günü ilə üst-üstə düşərdi.
--
-- `btree_gist` GENİŞLƏNMƏSİ: `uuid` sütununun `=` operatoru gist indeksində
-- yalnız bu modulla işləyir. YENİ QURAŞDIRMA ASILILIĞI YARATMIR — `schema.sql`
-- §0 onsuz da `pg_trgm` tələb edir və hər ikisi EYNİ `postgresql-contrib`
-- paketindədir (Supabase-də də standart olaraq mövcuddur).
--
-- ---------------------------------------------------------------------------
-- İLLİK MƏZUNİYYƏT MÖVCUD İCAZƏ SİSTEMİ İLƏ BİRLƏŞDİRİLMƏDİ — NİYƏ
-- ---------------------------------------------------------------------------
-- Bu, gələcəkdə "eyni şeydir, birləşdirək" deyilməməsi üçün AÇIQ yazılır:
--   * `leave_requests` DƏQİQƏ ilə işləyir (Requested/Delay/Total düsturu),
--     kamera təsdiqi tələb edir, cərimə yaradır və eyni gün içindədir.
--     İllik məzuniyyət GÜN ilə işləyir, kamera görmür, cərimə yaratmır və
--     həftələrlə davam edir.
--   * Balans anlayışı (`entitled/used/carried_over`) `leave_requests`-də
--     ÜMUMİYYƏTLƏ yoxdur; onu ora əlavə etmək hər gündaxili fasilə sətrinə boş
--     balans sütunları gətirərdi.
--   * Shift Matrix-in off-day sistemi PLANDIR (kim hansı gün işləmir), illik
--     məzuniyyət isə HAQQDIR (neçə gün qalıb). Birinin dəyişməsi digərinin
--     rəqəmini dəyişməməlidir.
--
-- ---------------------------------------------------------------------------
-- AUDİT SƏTİRLƏRİ — FİZİKİ SİLMƏ YOXDUR
-- ---------------------------------------------------------------------------
-- `bulk_import_log` və `export_manual_corrections` audit qeydidir. Onlar üçün
-- açıq `REVOKE` MƏCBURİDİR, dar `GRANT` KİFAYƏT ETMİR: `schema.sql` §28-dəki
-- `ALTER DEFAULT PRIVILEGES` sonradan yaradılan HƏR cədvələ `DELETE` verir
-- (ətraflı izah `migrations/018`-dədir).
-- `export_manual_corrections`-dan `UPDATE` də geri alınır: düzəlişin özü
-- düzəldilə bilsəydi, "kim nəyi nəyə dəyişdi" izi geri yazıla bilərdi. Yenidən
-- düzəliş YENİ sətirdir (`old_value` = əvvəlki `new_value`).
--
-- ROOT PARAMETRLƏRİ: bu miqrasiya `system_limits`-ə HEÇ NƏ yazmır — həddlər
-- (audit xatırlatma intervalı, illik haqq, carry-over tavanı, minimum səbəb
-- uzunluğu) müvafiq fazaların root-control miqrasiyasında seed edilir. Buradakı
-- ədədlər yalnız ABSURD dəyəri kəsən DÖŞƏMƏDİR, siyasət deyil.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- `EXCLUDE USING gist (employee_id WITH =, ...)` üçün — bax fayl başlığı.
-- `public` sxeminə qoyulur ki, `schema.sql` §0-dakı digər genişlənmələrlə eyni
-- yerdə olsun; artıq quraşdırılıbsa `IF NOT EXISTS` sükutla keçir.
CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public;

-- ---------------------------------------------------------------------------
-- 1. field_report_types (#26+#27) — ŞABLON REYESTRİ
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS field_report_types (
    -- Kod QLOBAL unikaldır (`exception_sources.code` naxışı): tətbiq qatındakı
    -- şablon reyestri məhz bu açarla bağlanır, iki kirayəçi eyni kodu fərqli
    -- mənada işlətsəydi reyestr hansı formanı açacağını bilməzdi.
    code                TEXT PRIMARY KEY
                            CHECK (code = upper(code)
                               AND char_length(trim(code)) >= 3),

    -- NULL = SİSTEM şablonu (bütün kirayəçilər görür) — `positions` naxışı.
    tenant_id           UUID REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,

    name_az             TEXT NOT NULL CHECK (char_length(trim(name_az)) >= 2),
    description_az      TEXT,

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA (Struktur Qərar A): #26 checklist tələb edir,
    -- #27 etmir. Bu fərq KODDA `if type == 'STORE_AUDIT'` kimi yazılsaydı,
    -- üçüncü şablon (məs. "Təchizat yoxlaması") əlavə etmək buraxılış tələb
    -- edərdi — halbuki kataloqun bütün məqsədi bunun qarşısını almaqdır.
    requires_checklist  BOOLEAN NOT NULL DEFAULT FALSE,

    -- Soft delete: köhnəlmiş şablon söndürülür, SİLİNMİR — keçmiş hesabatlar
    -- hansı formadan doğduğunu göstərə bilməlidir (`catalogs.py` qaydası).
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    deactivated_at      TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_field_report_type_deactivation
        CHECK (is_active OR deactivated_at IS NOT NULL)
);

DROP TRIGGER IF EXISTS trg_field_report_types_updated ON field_report_types;
CREATE TRIGGER trg_field_report_types_updated BEFORE UPDATE ON field_report_types
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE field_report_types IS
    '#26+#27 — Sahə hesabatının ŞABLON reyestri (STORE_AUDIT, INCIDENT). '
    'Vahid `field_reports` gövdəsi üzərində iki fərqli forma məhz bu kataloqla '
    'ayrılır (Struktur Qərar A). Yeni şablon DDL-siz, sadə INSERT ilə əlavə olunur.';
COMMENT ON COLUMN field_report_types.code IS
    'Şablon kodu (BÖYÜK hərflərlə, ən azı 3 simvol). Tətbiq qatı formanı bu '
    'açarla seçir, ona görə QLOBAL unikaldır.';
COMMENT ON COLUMN field_report_types.tenant_id IS
    'NULL = bütün kirayəçilər üçün sistem şablonu (`positions` naxışı); '
    'dolu = yalnız həmin kirayəçinin öz şablonu. RLS açarı.';
COMMENT ON COLUMN field_report_types.name_az IS
    'Ekranda görünən ad — Azərbaycanca (bölmə 9). Mətn BAZADADIR ki, ekran '
    'ikinci ad məkanı qurmasın (`menu.py` başlığındakı qüsur növü).';
COMMENT ON COLUMN field_report_types.description_az IS
    'Şablonun nə üçün olduğunun izahı — formanı ilk dəfə açan üçün kontekst.';
COMMENT ON COLUMN field_report_types.requires_checklist IS
    'TRUE = təqdimat checklist bəndləri olmadan tamamlana bilməz (#26). '
    'Davranış KODDA şablon adına görə yazılmır — fərq MƏLUMATDADIR.';
COMMENT ON COLUMN field_report_types.is_active IS
    'Soft delete: FALSE = yeni hesabat üçün seçilmir, mövcud sətirlər toxunulmaz '
    'qalır (Feature Toggle-ın retroaktiv olmaması qaydası ilə eyni məntiq).';
COMMENT ON COLUMN field_report_types.deactivated_at IS 'Söndürülmə anı (tz-aware).';
COMMENT ON COLUMN field_report_types.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN field_report_types.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

-- İki sistem şablonu. `ON CONFLICT DO NOTHING`: təkrar icrada müştərinin
-- redaktə etdiyi mətn ÜSTÜNDƏN YAZILMIR (`017` və `018` ilə eyni qayda).
INSERT INTO field_report_types (code, tenant_id, name_az, description_az, requires_checklist)
VALUES
    ('STORE_AUDIT', NULL, 'Mağaza ziyarəti / audit',
     'Strukturlaşdırılmış checklist üzrə mağaza yoxlaması (#26). Uğursuz '
     'bloklayıcı bənd mövcud Tapşırıq Mühərrikində düzəliş tapşırığı yaradır.',
     TRUE),
    ('INCIDENT', NULL, 'İnsident bildirişi',
     'Baş vermiş hadisənin (oğurluq, qəza, avadanlıq nasazlığı, şikayət) '
     'bildirilməsi (#27). Checklist tələb etmir, foto istəyə bağlıdır.',
     FALSE)
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. field_report_categories (#26+#27) — KATEQORİYA KATALOQU
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS field_report_categories (
    code                TEXT PRIMARY KEY
                            CHECK (code = upper(code)
                               AND char_length(trim(code)) >= 3),

    -- NO ACTION: kateqoriyaları qalan şablon kataloqdan çıxarıla bilməz;
    -- söndürmə yolu `is_active = FALSE`-dır, ona görə normal axın bloklanmır.
    report_type         TEXT NOT NULL REFERENCES field_report_types(code)
                            ON DELETE NO ACTION,

    tenant_id           UUID REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,

    name_az             TEXT NOT NULL CHECK (char_length(trim(name_az)) >= 2),
    description_az      TEXT,

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA (#27, ROOT PARAMETRİ): "hansı kateqoriya hansı
    -- rola gedir" qaydasının yeri budur. Kodda `dict` kimi saxlansaydı,
    -- marşrutun dəyişməsi buraxılış tələb edərdi.
    -- FK QOYULA BİLMİR — SƏBƏB: `positions.code` yalnız `(tenant_id, code)`
    -- cütü ilə unikaldır və sistem rolları `tenant_id IS NULL` sətirlərdir;
    -- buradan gedən birləşmiş FK (bu cədvəlin `tenant_id`-si NULL ola bilər)
    -- sistem rollarına ÇATA BİLMƏZDİ. Ona görə dəyər normallaşdırılmış mətndir,
    -- mövcudluğu tətbiq qatı yoxlayır.
    route_to_role       TEXT CHECK (route_to_role IS NULL
                                    OR (route_to_role = upper(route_to_role)
                                        AND char_length(trim(route_to_role)) >= 2)),

    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    deactivated_at      TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Birləşmiş FK-nın HƏDƏFİ (aşağıda `field_reports`). `code` onsuz da
    -- unikaldır; bu məhdudiyyət yalnız cütü FK hədəfi kimi açır.
    UNIQUE (report_type, code),

    CONSTRAINT chk_field_report_category_deactivation
        CHECK (is_active OR deactivated_at IS NOT NULL)
);

DROP TRIGGER IF EXISTS trg_field_report_categories_updated ON field_report_categories;
CREATE TRIGGER trg_field_report_categories_updated
    BEFORE UPDATE ON field_report_categories
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Forma açılanda "bu şablonun aktiv kateqoriyaları" sorğusu — hər təqdimatda.
CREATE INDEX IF NOT EXISTS idx_field_report_categories_type
    ON field_report_categories (report_type) WHERE is_active;

COMMENT ON TABLE field_report_categories IS
    '#26+#27 — Sahə hesabatının kateqoriya kataloqu. Sərt CHECK siyahısı '
    'QƏSDƏN rədd edildi (`migrations/018` `exceptions.source` qərarı): yeni '
    'kateqoriya bir INSERT olmalıdır, miqrasiya yox.';
COMMENT ON COLUMN field_report_categories.code IS
    'Kateqoriya kodu (BÖYÜK hərflərlə). Şablon prefiksi ilə yazılır '
    '(AUDIT_… / INCIDENT_…) ki, hesabat ixracında kod tək başına oxunaqlı olsun.';
COMMENT ON COLUMN field_report_categories.report_type IS
    'Kateqoriyanın aid olduğu şablon. `field_reports` birləşmiş FK ilə buna '
    'bağlanır — insident kateqoriyası audit hesabatına yazıla bilmir.';
COMMENT ON COLUMN field_report_categories.tenant_id IS
    'NULL = sistem kateqoriyası (hamı görür); dolu = kirayəçinin öz kateqoriyası. '
    'RLS açarı.';
COMMENT ON COLUMN field_report_categories.name_az IS
    'Formada görünən ad — Azərbaycanca (bölmə 9).';
COMMENT ON COLUMN field_report_categories.description_az IS
    'Kateqoriyanın nəyi əhatə etdiyi — səhv kateqoriya seçimini azaldır.';
COMMENT ON COLUMN field_report_categories.route_to_role IS
    'ROOT PARAMETRİ (#27): hesabat hansı rola marşrutlanır (`positions.code` '
    'dəyəri, BÖYÜK hərflərlə). NULL = marşrutlama yoxdur — audit kateqoriyaları '
    'belədir, çünki onların nəticəsi rola deyil, Tapşırıq Mühərrikinə gedir. '
    'FK yoxdur: `positions.code` yalnız kirayəçi daxilində unikaldır.';
COMMENT ON COLUMN field_report_categories.is_active IS
    'Soft delete: FALSE = yeni hesabatda seçilmir; keçmiş hesabatlar toxunulmaz.';
COMMENT ON COLUMN field_report_categories.deactivated_at IS 'Söndürülmə anı (tz-aware).';
COMMENT ON COLUMN field_report_categories.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN field_report_categories.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

COMMENT ON INDEX idx_field_report_categories_type IS
    'Forma açılışının sorğusu: şablonun AKTİV kateqoriyaları. Qismən indeks — '
    'söndürülmüş kateqoriyalar heç bir formada göstərilmir.';

-- `kompas1.md` Faza 3-də sadalanan kateqoriyalar sistem sətri kimi verilir ki,
-- Faza 3 heç bir DDL yazmadan işə düşsün. Marşrut dəyərləri DEFOLTDUR — Root
-- onları buraxılışsız dəyişə bilər (bu, kataloq dizaynının bütün məqsədidir).
INSERT INTO field_report_categories
    (code, report_type, tenant_id, name_az, description_az, route_to_role)
VALUES
    ('AUDIT_TEMIZLIK', 'STORE_AUDIT', NULL, 'Təmizlik',
     'Salon, anbar və işçi sahələrinin təmizlik vəziyyəti.', NULL),
    ('AUDIT_VITRIN', 'STORE_AUDIT', NULL, 'Vitrin və məhsul düzümü',
     'Vitrin standartı, etiket və məhsul düzümünün uyğunluğu.', NULL),
    ('AUDIT_TEHLUKESIZLIK', 'STORE_AUDIT', NULL, 'Təhlükəsizlik',
     'Yanğın təhlükəsizliyi, çıxış yolları, avadanlığın təhlükəsiz istifadəsi.', NULL),
    ('AUDIT_KASSA', 'STORE_AUDIT', NULL, 'Kassa və sənədləşmə',
     'Kassa intizamı, çek və sənəd qaydalarına riayət.', NULL),
    ('INCIDENT_OGURLUQ', 'INCIDENT', NULL, 'Oğurluq',
     'Məhsul və ya əmlak itkisi şübhəsi. İntizam/hüquq axınına gedir.', 'ADMIN'),
    ('INCIDENT_QEZA', 'INCIDENT', NULL, 'Qəza / xəsarət',
     'İşçi və ya müştəri ilə bağlı hadisə — əməyin təhlükəsizliyi sahəsi.', 'HR_ADMIN'),
    ('INCIDENT_AVADANLIQ', 'INCIDENT', NULL, 'Avadanlıq nasazlığı',
     'Texniki avadanlığın sıradan çıxması və ya təhlükəli vəziyyəti.', 'ADMIN'),
    ('INCIDENT_SIKAYET', 'INCIDENT', NULL, 'Şikayət',
     'Müştəri və ya işçi şikayəti.', 'HR_ADMIN')
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. field_reports (#26+#27) — VAHİD SAHƏ HESABATI
-- ---------------------------------------------------------------------------
-- `status` NİYƏ SƏRT SİYAHIDIR (kateqoriyadan fərqli olaraq): status İŞ AXININ
-- ÖZÜDÜR — yeni dəyər yeni ekran/keçid deməkdir və kod dəyişikliyi olmadan
-- mənasızdır. Genişlənmə nöqtəsi şablon və kateqoriyadır, axın deyil
-- (`migrations/018` `exceptions.status` ilə eyni ayrım).
CREATE TABLE IF NOT EXISTS field_reports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES license_tenants(tenant_id)
                        ON DELETE CASCADE,

    -- `type` adı spesifikasiyadan gəlir və PostgreSQL-də qeyri-rezerv açardır
    -- (sitat tələb etmir). NO ACTION: şablon kataloqu hesabatlar qalarkən
    -- çıxarıla bilməz.
    type            TEXT NOT NULL REFERENCES field_report_types(code)
                        ON DELETE NO ACTION,
    category        TEXT NOT NULL,

    -- NO ACTION (CASCADE DEYİL): insident hesabatı mübahisədə SÜBUTDUR və
    -- mağaza sətri ilə birlikdə sükutla yox olmamalıdır. Mağazalar praktikada
    -- soft delete edilir (`stores.is_active`), ona görə bu qayda normal işi
    -- bloklamır — yalnız fiziki silməni dayandırır.
    store_id        UUID NOT NULL REFERENCES stores(id) ON DELETE NO ACTION,

    -- NO ACTION: "bu hesabatı kim yazdı?" sualı hesabatdan uzun yaşayır
    -- (`announcements.created_by` ilə eyni əsaslandırma).
    reported_by     UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,

    detail          TEXT NOT NULL CHECK (char_length(trim(detail)) >= 5),

    -- Bax fayl başlığı (massiv seçiminin əsaslandırması). Boş sətir elementi
    -- bloklanır — o, "şəkil var" kimi görünüb heç nəyə açılmayan istinaddır.
    -- NULL elementi üçün DB yoxlaması QOYULMUR: onu ifadə edən yeganə yol
    -- massiv funksiyalarıdır və onlar CHECK ifadəsində IMMUTABLE zəmanəti
    -- daşımır; həmin yoxlama tətbiq qatındadır.
    photo_refs      TEXT[] NOT NULL DEFAULT '{}'::text[]
                        CHECK (NOT ('' = ANY (photo_refs))),

    status          TEXT NOT NULL DEFAULT 'SUBMITTED'
                        CHECK (status IN ('SUBMITTED', 'IN_PROGRESS',
                                          'RESOLVED', 'DISMISSED')),

    -- ƏLAVƏ SÜTUNLAR — ƏSASLANDIRMA: hesabatın bağlanması QƏRARDIR; kim, nə
    -- vaxt və hansı əsasla bağladığı yazılmasa "həll edildi" sözünün sahibi
    -- olmaz (`exceptions.reviewed_*` ilə eyni naxış).
    resolved_by     UUID REFERENCES employees(id) ON DELETE SET NULL,
    resolved_at     TIMESTAMPTZ,
    resolution_note TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Uşaq cədvəlin (checklist) BİRLƏŞMİŞ FK-sı üçün lazımdır.
    UNIQUE (tenant_id, id),

    -- KATEQORİYA ŞABLONA UYĞUN OLMALIDIR — iki ayrı FK bunu zəmanət verməzdi.
    FOREIGN KEY (type, category)
        REFERENCES field_report_categories (report_type, code) ON DELETE NO ACTION,

    CONSTRAINT chk_field_report_resolution
        CHECK (status IN ('SUBMITTED', 'IN_PROGRESS')
            OR (resolved_by IS NOT NULL AND resolved_at IS NOT NULL))
);

DROP TRIGGER IF EXISTS trg_field_reports_updated ON field_reports;
CREATE TRIGGER trg_field_reports_updated BEFORE UPDATE ON field_reports
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- "Açıq hesabatlar" — ekranın ƏSAS sorğusu, ən yenisi əvvəldə. Qismən indeks:
-- bağlanmış minlərlə sətri indeksləmək yazı yükü verər, oxu faydası verməzdi.
CREATE INDEX IF NOT EXISTS idx_field_reports_open
    ON field_reports (tenant_id, created_at DESC)
    WHERE status IN ('SUBMITTED', 'IN_PROGRESS');
-- Mağaza üzrə süzgəc (Mağaza Meneceri yalnız öz filialını görür).
CREATE INDEX IF NOT EXISTS idx_field_reports_store
    ON field_reports (store_id, created_at DESC);
-- Dashboard metriki (Struktur Qərar C): şablon üzrə dövri say/bal.
CREATE INDEX IF NOT EXISTS idx_field_reports_type_period
    ON field_reports (tenant_id, type, created_at DESC);

COMMENT ON TABLE field_reports IS
    '#26+#27 — Sahə hesabatının VAHİD gövdəsi: mağaza auditi və insident '
    'bildirişi EYNİ axındır, yalnız şablonu fərqlidir (Struktur Qərar A). '
    'Mövcud `exceptions` ilə birləşdirilmədi: o, MAŞIN aşkarlamasıdır, bu isə '
    'İNSAN müşahidəsidir və Tapşırıq Mühərrikinə bağlanır.';
COMMENT ON COLUMN field_reports.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN field_reports.tenant_id IS 'Kirayəçi izolyasiyası — RLS açarı.';
COMMENT ON COLUMN field_reports.type IS
    'Şablon kodu — `field_report_types` kataloquna FK (STORE_AUDIT / INCIDENT). '
    'Sərt CHECK siyahısı QƏSDƏN işlədilmir: yeni şablon DDL tələb etməməlidir.';
COMMENT ON COLUMN field_reports.category IS
    'Kateqoriya kodu. `(type, category)` cütü kataloqa BİRLƏŞMİŞ FK ilə bağlıdır '
    '— yəni şablona aid olmayan kateqoriya yazıla bilmir.';
COMMENT ON COLUMN field_reports.store_id IS
    'Hesabatın aid olduğu mağaza. Hesabat sübutdur, ona görə mağazanın FİZİKİ '
    'silinməsi bloklanır (soft delete normal yoldur).';
COMMENT ON COLUMN field_reports.reported_by IS
    'Hesabatı yazan şəxs. `ON DELETE NO ACTION` — müəllifsiz sübut mənasızdır.';
COMMENT ON COLUMN field_reports.detail IS
    'İnsan-oxunaqlı təsvir (Azərbaycanca) — nə müşahidə edildi.';
COMMENT ON COLUMN field_reports.photo_refs IS
    'Foto istinadları (`StorageReference` açarları). Fayl BAYTI burada deyil: '
    'yükləmə mövcud növbə + Drive kanalındadır, yeni saxlama kanalı açılmır. '
    'JSONB əvəzinə mətn massivi seçildi — element tipi struktur şəkildə '
    'zəmanətlidir (bax fayl başlığı).';
COMMENT ON COLUMN field_reports.status IS
    'SUBMITTED → IN_PROGRESS → RESOLVED / DISMISSED. Siyahı SƏRTDİR, çünki hər '
    'dəyər iş axınının addımıdır və kod dəstəyi tələb edir.';
COMMENT ON COLUMN field_reports.resolved_by IS 'Hesabatı bağlayan şəxs.';
COMMENT ON COLUMN field_reports.resolved_at IS 'Bağlanma anı (tz-aware).';
COMMENT ON COLUMN field_reports.resolution_note IS
    'Bağlanmanın əsası — "nə edildi / niyə əsassız sayıldı".';
COMMENT ON COLUMN field_reports.created_at IS 'Təqdimat anı (tz-aware).';
COMMENT ON COLUMN field_reports.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

COMMENT ON INDEX idx_field_reports_open IS
    'Açıq hesabatlar siyahısı — ekranın əsas sorğusu. Qismən indeks: bağlanmış '
    'sətirlər bu suala aid deyil.';

-- ---------------------------------------------------------------------------
-- 4. field_report_checklist_items (#26) — CHECKLIST BƏNDLƏRİ
-- ---------------------------------------------------------------------------
-- `position` sözü PostgreSQL-də funksiya/açar sözdür və sütun adı kimi
-- sitatsız işlədilə bilmir — ona görə sıra sütunu `position_no` adlanır.
-- Sıra sütunu ÜMUMİYYƏTLƏ niyə var: sətirlərin fiziki oxunma sırası SQL-də
-- təyin olunmayıb, checklist isə addım-addım naviqasiya ilə göstərilir (Faza 3);
-- sıra saxlanılmasaydı, bəndlər hər açılışda başqa ardıcıllıqla görünə bilərdi.
CREATE TABLE IF NOT EXISTS field_report_checklist_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES license_tenants(tenant_id)
                        ON DELETE CASCADE,
    report_id       UUID NOT NULL,

    position_no     SMALLINT NOT NULL CHECK (position_no >= 1),
    item_text       TEXT NOT NULL CHECK (char_length(trim(item_text)) >= 3),

    -- ÜÇ VƏZİYYƏT: TRUE = keçdi, FALSE = keçmədi, NULL = hələ yoxlanılmadı
    -- (bax fayl başlığındakı əsaslandırma).
    passed          BOOLEAN,

    is_blocking     BOOLEAN NOT NULL DEFAULT FALSE,
    photo_required  BOOLEAN NOT NULL DEFAULT FALSE,

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: `photo_required = TRUE` təqdim edilən şəklin
    -- YAZILACAĞI yer olmadan mənasızdır.
    -- DB `photo_required`-i MƏCBUR ETMİR (CHECK yoxdur) — SƏBƏB: yükləmə
    -- ASİNXRONDUR (lokal növbə → Drive), yəni istinad sətirdən SONRA gəlir.
    -- Məcburiyyət qoysaydıq, oflayn terminal checklist-i ÜMUMİYYƏTLƏ yaza
    -- bilməzdi (`migrations/002`-dəki eyni səbəb).
    photo_ref       TEXT,

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: uğursuz bloklayıcı bənd Tapşırıq Mühərrikində
    -- tapşırıq yaradır (Struktur Qərar B); tapşırığın mətni "nə səhvdir?"
    -- cavabından qurulur — qeyd olmasa tapşırıq məzmunsuz olardı.
    note            TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (report_id, position_no),

    -- BİRLƏŞMİŞ FK: bəndin `tenant_id`-si valideyn hesabatınkı ilə EYNİ
    -- olmalıdır. Adi tək-sütunlu FK bunu zəmanət verməzdi və denormalizasiya
    -- sükutla sürüşərdi (`announcement_targets` naxışı).
    -- CASCADE: hesabat sətri getsə (yalnız DOWN blokunda) bəndlər yetim qalmamalıdır.
    FOREIGN KEY (tenant_id, report_id)
        REFERENCES field_reports (tenant_id, id) ON DELETE CASCADE
);

DROP TRIGGER IF EXISTS trg_field_report_items_updated ON field_report_checklist_items;
CREATE TRIGGER trg_field_report_items_updated
    BEFORE UPDATE ON field_report_checklist_items
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- "Hesabatın bəndlərini sıra ilə oxu" sorğusu üçün AYRICA indeks QOYULMUR:
-- `UNIQUE (report_id, position_no)` onsuz da məhz həmin sütun cütü üzərində
-- btree indeks yaradır. Təkrar indeks yalnız yazı yükü və disk əlavə edərdi.
--
-- TASK ENGINE SORĞUSU (Struktur Qərar B): uğursuz BLOKLAYICI bəndlər.
-- Predikat `passed IS FALSE`-dır, `= FALSE` deyil — cavabsız bənd (NULL)
-- uğursuz sayılmamalıdır.
CREATE INDEX IF NOT EXISTS idx_field_report_items_failed_blocking
    ON field_report_checklist_items (tenant_id, report_id)
    WHERE passed IS FALSE AND is_blocking;

COMMENT ON TABLE field_report_checklist_items IS
    '#26 — Mağaza auditi checklist bəndləri. Uğursuz BLOKLAYICI bənd mövcud '
    'Tapşırıq Mühərrikində düzəliş tapşırığı yaradır (Struktur Qərar B) — bu '
    'miqrasiya yeni tapşırıq sistemi QURMUR.';
COMMENT ON COLUMN field_report_checklist_items.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN field_report_checklist_items.tenant_id IS
    'Kirayəçi izolyasiyası. Valideyndən sürüşməsi birləşmiş FK ilə qadağandır.';
COMMENT ON COLUMN field_report_checklist_items.report_id IS
    'Bəndin aid olduğu sahə hesabatı.';
COMMENT ON COLUMN field_report_checklist_items.position_no IS
    'Bəndin sırası (1-dən). Addım-addım naviqasiya sabit ardıcıllıq tələb edir; '
    'SQL sətir sırasına zəmanət vermir.';
COMMENT ON COLUMN field_report_checklist_items.item_text IS
    'Yoxlanılan bəndin mətni (Azərbaycanca) — şablondan KÖÇÜRÜLÜR. Şablon '
    'sonradan dəyişsə də, keçmiş auditdə NƏYİN yoxlandığı dəyişməməlidir.';
COMMENT ON COLUMN field_report_checklist_items.passed IS
    'TRUE = keçdi, FALSE = keçmədi, NULL = hələ yoxlanılmadı. Üç vəziyyət üçün '
    'ayrı sütun QƏSDƏN yaradılmadı — o, ziddiyyətli cütə imkan verərdi.';
COMMENT ON COLUMN field_report_checklist_items.is_blocking IS
    'TRUE = bu bəndin uğursuzluğu avtomatik düzəliş tapşırığı yaradır (#26).';
COMMENT ON COLUMN field_report_checklist_items.photo_required IS
    'TRUE = bənd üçün foto-sübut gözlənilir. DB MƏCBUR ETMİR: yükləmə '
    'asinxrondur, istinad sətirdən sonra gəlir — məcburiyyət oflayn terminalda '
    'checklist yazılmasını tam bloklayardı.';
COMMENT ON COLUMN field_report_checklist_items.photo_ref IS
    'Bəndə aid foto istinadı (`StorageReference`). NULL = hələ yüklənməyib '
    'və ya tələb olunmur.';
COMMENT ON COLUMN field_report_checklist_items.note IS
    'Bəndə aid qeyd — uğursuz bənddə yaranan tapşırığın mətninin mənbəyi.';
COMMENT ON COLUMN field_report_checklist_items.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN field_report_checklist_items.updated_at IS
    'Sonuncu dəyişiklik anı (trigger).';

COMMENT ON INDEX idx_field_report_items_failed_blocking IS
    'Tapşırıq Mühərrikinin sorğusu: uğursuz bloklayıcı bəndlər. Predikat '
    '`passed IS FALSE`-dır — cavabsız (NULL) bənd uğursuz sayılmır.';

-- ---------------------------------------------------------------------------
-- 5. annual_leave_balances (#28) — İLLİK MƏZUNİYYƏT HAQQI
-- ---------------------------------------------------------------------------
-- GÜNLƏR NİYƏ `NUMERIC(5,2)`, `INTEGER` DEYİL: yarım-gün məzuniyyət real HR
-- praktikasıdır; tam ədəd onu ya qadağan edər, ya da yuvarlaqlaşdırma ilə
-- sükutla gün itirərdi. `FLOAT` isə ümumiyyətlə rədd edilir — ikilik kəsr
-- 0.1-i dəqiq saxlamır və balans illər boyu sürüşərdi (pul sütunları ilə eyni
-- qərar).
CREATE TABLE IF NOT EXISTS annual_leave_balances (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL REFERENCES license_tenants(tenant_id)
                           ON DELETE CASCADE,

    -- CASCADE: balans işçi sətrinin törəməsidir və onsuz mənası yoxdur. İşçilər
    -- praktikada soft delete edilir, ona görə bu yol yalnız kirayəçi tam ləğv
    -- olunanda işə düşür (`employee_documents` ilə eyni əsaslandırma).
    employee_id        UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,

    -- Təqvim ili. `SMALLINT` + ağlabatan aralıq: 1900 və ya 9999 ili yazılan
    -- sətir sükutla "keçmiş balans" kimi görünüb hesabatı korlayardı.
    year               SMALLINT NOT NULL CHECK (year BETWEEN 2000 AND 2100),

    entitled_days      NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (entitled_days >= 0),
    used_days          NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (used_days >= 0),
    carried_over_days  NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (carried_over_days >= 0),

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: balans PUL dəyəri daşıyır (istifadə edilməmiş
    -- gün kompensasiya oluna bilər). "Bu rəqəmi kim dəyişdi?" sualı mübahisədə
    -- ilk sualdır; mətn izi `audit_logs`-da qalsa da, struktur cavab burada olmalıdır.
    updated_by         UUID REFERENCES employees(id) ON DELETE SET NULL,

    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- MƏCBURİ: işçi + il üçün BİR balans sətri. Olmasaydı, paralel iki
    -- `INSERT` iki balans yaradar və "neçə gün qalıb?" sualının iki cavabı olardı.
    UNIQUE (tenant_id, employee_id, year),

    -- BALANS MƏNFİYƏ DÜŞƏ BİLMƏZ — qayda İKİ yerdədir (CLAUDE.md §5): burada
    -- və `AnnualLeaveBalanceUseCase`-də. Ekranı yan keçən skript də ona tabedir.
    -- Tavan (carry-over maksimumu, "istifadə et ya itir" tarixi) BURADA
    -- SAXLANILMIR — o, siyasətdir və ROOT parametridir; DB yalnız absurd
    -- vəziyyəti kəsir.
    CONSTRAINT chk_annual_leave_balance_not_negative
        CHECK (used_days <= entitled_days + carried_over_days)
);

DROP TRIGGER IF EXISTS trg_annual_leave_balances_updated ON annual_leave_balances;
CREATE TRIGGER trg_annual_leave_balances_updated
    BEFORE UPDATE ON annual_leave_balances
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- "Bu ilin bütün balansları" — HR ekranının siyahı sorğusu. `UNIQUE` indeksi
-- `(tenant_id, employee_id)` prefiksi ilə işləyir, ilə görə süzgəc üçün yox.
CREATE INDEX IF NOT EXISTS idx_annual_leave_balances_year
    ON annual_leave_balances (tenant_id, year);

COMMENT ON TABLE annual_leave_balances IS
    '#28 — İllik məzuniyyət haqqı və istifadəsi (işçi + il). Mövcud GÜNDAXİLİ '
    'icazə sistemi (`leave_requests`, STEP1/STEP2) və Shift Matrix istirahət '
    'günü sistemi ilə TAM AYRIDIR: biri dəqiqə və cərimə, digəri plan, bu isə '
    'gün haqqıdır — sonradan birləşdirilməməlidir (bax fayl başlığı).';
COMMENT ON COLUMN annual_leave_balances.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN annual_leave_balances.tenant_id IS 'Kirayəçi izolyasiyası — RLS açarı.';
COMMENT ON COLUMN annual_leave_balances.employee_id IS 'Balansın aid olduğu işçi.';
COMMENT ON COLUMN annual_leave_balances.year IS
    'Təqvim ili (2000–2100). Hər il AYRI sətirdir — keçmiş ilin haqqı sonrakı '
    'ilin düzəlişi ilə üstündən yazılmamalıdır.';
COMMENT ON COLUMN annual_leave_balances.entitled_days IS
    'Həmin il üçün qazanılmış haqq (gün). Baza haqq və staj əlavəsi ROOT '
    'parametrləridir — hesablama tətbiq qatındadır, nəticə burada saxlanılır.';
COMMENT ON COLUMN annual_leave_balances.used_days IS
    'İstifadə edilmiş gün. Təsdiqlənmiş sorğunun `deducted_days` cəmi ilə '
    'uyğunlaşdırılır; yarım-gün üçün kəsr dəyər mümkündür.';
COMMENT ON COLUMN annual_leave_balances.carried_over_days IS
    'Keçən ildən köçürülmüş gün. Köçürmə TAVANI burada deyil — o, ROOT '
    'parametridir və dəyişəndə köhnə sətirlər yenidən yazılmamalıdır.';
COMMENT ON COLUMN annual_leave_balances.updated_by IS
    'Balansı sonuncu dəfə əl ilə dəyişən şəxs — rəqəm pul dəyəri daşıyır.';
COMMENT ON COLUMN annual_leave_balances.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN annual_leave_balances.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

-- ---------------------------------------------------------------------------
-- 6. annual_leave_requests (#28) — MƏZUNİYYƏT SORĞUSU
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS annual_leave_requests (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES license_tenants(tenant_id)
                       ON DELETE CASCADE,
    employee_id    UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,

    start_date     DATE NOT NULL,
    end_date       DATE NOT NULL,

    status         TEXT NOT NULL DEFAULT 'PENDING_APPROVAL'
                       CHECK (status IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED')),

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: balansdan ÇIXILAN gün sayı təqvim günü DEYİL
    -- (istirahət günləri Shift Matrix-dən asılıdır). Dəyər hər oxunuşda yenidən
    -- hesablansaydı, matris sonradan dəyişəndə KEÇMİŞ sorğunun çıxılan günü də
    -- sükutla dəyişər və balans uyğunsuz olardı. Ona görə təsdiq anında
    -- DONDURULUR — `overtime_log.norm_hours` ilə eyni naxış (`migrations/019`).
    -- SIFIR İCAZƏLİDİR, MƏNFİ DEYİL: tam olaraq istirahət günlərinə düşən sorğu
    -- balansdan heç nə çıxarmır və bu, qanuni haldır — `> 0` yazılsaydı, DB
    -- həmin təsdiqi çökdürər və ekran anlaşılmaz xəta göstərərdi. Mənfi dəyər
    -- isə balansı ARTIRARDI: "məzuniyyət götürdüm, günüm çoxaldı".
    deducted_days  NUMERIC(5, 2) CHECK (deducted_days IS NULL OR deducted_days >= 0),

    -- Qərar bloku. Sütun adı spesifikasiyadan gəlir, lakin RƏDD qərarının da
    -- sahibi buradadır (aşağıdakı şərhə bax).
    approved_by    UUID REFERENCES employees(id) ON DELETE SET NULL,
    decided_at     TIMESTAMPTZ,
    decision_note  TEXT,

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_annual_leave_request_range CHECK (end_date >= start_date),

    -- `shift_swap_requests.chk_swap_decision` naxışı: qərar statusu qərar
    -- verəni tələb edir.
    CONSTRAINT chk_annual_leave_request_decision
        CHECK (status = 'PENDING_APPROVAL'
            OR (approved_by IS NOT NULL AND decided_at IS NOT NULL)),

    -- Təsdiqlənmiş sorğu balansdan nə qədər çıxdığını GÖSTƏRMƏLİDİR; əks halda
    -- `used_days` ilə sorğular arasında uzlaşdırma mümkün olmazdı.
    CONSTRAINT chk_annual_leave_request_deduction
        CHECK (status <> 'APPROVED' OR deducted_days IS NOT NULL),

    -- ÜST-ÜSTƏ DÜŞMƏ QAPAĞI — bax fayl başlığı. Bu, "əlavə qoruma" deyil:
    -- paralel iki təsdiqdə tətbiq qatının oxu-yaz yoxlaması uduzur.
    CONSTRAINT excl_annual_leave_no_overlap
        EXCLUDE USING gist (
            employee_id WITH =,
            daterange(start_date, end_date, '[]') WITH &&
        ) WHERE (status = 'APPROVED')
);

DROP TRIGGER IF EXISTS trg_annual_leave_requests_updated ON annual_leave_requests;
CREATE TRIGGER trg_annual_leave_requests_updated
    BEFORE UPDATE ON annual_leave_requests
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Təsdiq növbəsi — HR ekranının əsas sorğusu (ən erkən başlayan əvvəldə).
CREATE INDEX IF NOT EXISTS idx_annual_leave_requests_pending
    ON annual_leave_requests (tenant_id, start_date)
    WHERE status = 'PENDING_APPROVAL';
-- İşçi profilində "məzuniyyət tarixçəsi".
CREATE INDEX IF NOT EXISTS idx_annual_leave_requests_employee
    ON annual_leave_requests (employee_id, start_date DESC);

COMMENT ON TABLE annual_leave_requests IS
    '#28 — İllik məzuniyyət sorğusu və təsdiqi. Təsdiqlənmiş aralıqlar eyni '
    'işçi üçün KƏSİŞƏ BİLMİR: qapaq `EXCLUDE USING gist` ilə DB qatındadır, '
    'çünki paralel iki təsdiqdə tətbiq qatının yoxlaması uduzur.';
COMMENT ON COLUMN annual_leave_requests.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN annual_leave_requests.tenant_id IS 'Kirayəçi izolyasiyası — RLS açarı.';
COMMENT ON COLUMN annual_leave_requests.employee_id IS 'Sorğunu verən işçi.';
COMMENT ON COLUMN annual_leave_requests.start_date IS
    'Məzuniyyətin ilk günü (DAXİLDİR).';
COMMENT ON COLUMN annual_leave_requests.end_date IS
    'Məzuniyyətin son günü (DAXİLDİR) — kəsişmə qapağı `[]` aralığı ilə işləyir. '
    '`end_date >= start_date` DB-də yoxlanılır.';
COMMENT ON COLUMN annual_leave_requests.status IS
    'PENDING_APPROVAL → APPROVED / REJECTED. Siyahı SƏRTDİR: hər dəyər təsdiq '
    'axınının addımıdır və ekran dəstəyi tələb edir.';
COMMENT ON COLUMN annual_leave_requests.deducted_days IS
    'Balansdan çıxılan gün — TƏSDİQ anında dondurulur. Təqvim günü deyil: '
    'istirahət günləri Shift Matrix-dən asılıdır və matris sonradan dəyişsə, '
    'keçmiş sorğunun rəqəmi dəyişməməlidir.';
COMMENT ON COLUMN annual_leave_requests.approved_by IS
    'QƏRARI verən şəxs — həm təsdiq, həm rədd halında. Ad spesifikasiyadan '
    'gəlir; rədd üçün ayrıca sütun yaradılmadı, çünki qərar HƏMİŞƏ birdir və '
    'iki sütundan yalnız biri dolu olardı.';
COMMENT ON COLUMN annual_leave_requests.decided_at IS 'Qərar anı (tz-aware).';
COMMENT ON COLUMN annual_leave_requests.decision_note IS
    'Qərarın əsası — xüsusilə rəddin səbəbi işçiyə izah edilməlidir.';
COMMENT ON COLUMN annual_leave_requests.created_at IS 'Sorğunun verilmə anı (tz-aware).';
COMMENT ON COLUMN annual_leave_requests.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

COMMENT ON CONSTRAINT excl_annual_leave_no_overlap ON annual_leave_requests IS
    'Eyni işçinin TƏSDİQLƏNMİŞ məzuniyyət aralıqları kəsişə bilməz. Qismən '
    'şərtdir: gözləyən/rədd edilmiş sorğular sərbəst kəsişir, əks halda işçi '
    'eyni həftəyə ikinci variant təklif edə bilməzdi.';

-- ---------------------------------------------------------------------------
-- 7. bulk_import_log (#29) — TOPLU ƏMƏLİYYAT JURNALI
-- ---------------------------------------------------------------------------
-- Spesifikasiyadakı `timestamp` sütunu burada `performed_at` adlanır: (a) tip
-- adı ilə eyni adlı sütun sorğuları oxunmaz edir, (b) layihənin bütün vaxt
-- sütunları `_at` şəkilçisi daşıyır. Ayrıca `created_at` YOXDUR — sətir
-- əməliyyat BAŞLAYANDA yaranır, yəni iki sütun eyni anı göstərər və zamanla
-- bir-birindən sürüşərdi.
CREATE TABLE IF NOT EXISTS bulk_import_log (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES license_tenants(tenant_id)
                       ON DELETE CASCADE,

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: "row_count = 500" tək başına NƏYİN 500 olduğunu
    -- demir. Sərt siyahı QOYULMUR (`employee_documents.doc_type` naxışı):
    -- növ yalnız etiketdir, davranışı idarə etmir — normallaşdırma kifayətdir.
    import_type    TEXT NOT NULL
                       CHECK (import_type = upper(import_type)
                          AND char_length(trim(import_type)) >= 3),

    -- NO ACTION: "bu toplu əməliyyatı kim etdi?" audit sualıdır və icraçının
    -- sətri silinsə belə cavabsız qalmamalıdır.
    performed_by   UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,

    -- NULL ola bilər — ƏSASLANDIRMA: #29 yalnız fayl idxalı deyil; ekrandan
    -- seçilmiş 20 işçiyə toplu dəyişiklik də toplu əməliyyatdır və onun faylı
    -- yoxdur. Məcburi etsəydik, tətbiq uydurma dəyər yazmalı olardı.
    file_ref       TEXT,

    row_count      INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    success_count  INTEGER NOT NULL DEFAULT 0 CHECK (success_count >= 0),
    error_count    INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: "12 sətir uğursuz" məlumatı ilə heç nə etmək
    -- olmur. Səbəbsiz uğursuzluq diaqnostikanı dayandırır və növbəti idxalda
    -- eyni səhv təkrarlanır (`app_scheduled_job_runs.last_error` ilə eyni qərar).
    error_summary  TEXT,

    performed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- NULL = əməliyyat yarımçıq qalıb (proses çöküb). Bu, GÖRÜNƏN qalmalıdır:
    -- yarımçıq idxal sükutla "uğurlu" kimi görünsəydi, natamam məlumat aşkar
    -- edilməzdi.
    finished_at    TIMESTAMPTZ,

    CONSTRAINT chk_bulk_import_counts
        CHECK (success_count + error_count <= row_count),
    CONSTRAINT chk_bulk_import_error_detail
        CHECK (error_count = 0
            OR (error_summary IS NOT NULL AND char_length(trim(error_summary)) > 0))
);

-- "Son toplu əməliyyatlar" — Root panelinin siyahısı.
CREATE INDEX IF NOT EXISTS idx_bulk_import_log_recent
    ON bulk_import_log (tenant_id, performed_at DESC);

COMMENT ON TABLE bulk_import_log IS
    '#29 — Toplu əməliyyatların audit jurnalı. Fiziki silmə QADAĞANDIR: 500 '
    'sətri bir kliklə dəyişən əməliyyatın izi, məhz o əməliyyatı edən tərəf '
    'üçün ən əlverişli silinəsi qeyddir (`REVOKE DELETE` aşağıdadır).';
COMMENT ON COLUMN bulk_import_log.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN bulk_import_log.tenant_id IS 'Kirayəçi izolyasiyası — RLS açarı.';
COMMENT ON COLUMN bulk_import_log.import_type IS
    'Əməliyyatın növü, BÖYÜK hərflərlə (məs. ISCI_IDXALI, NOVBE_IDXALI). Sərt '
    'siyahı yoxdur — növ etiketdir, davranışı idarə etmir.';
COMMENT ON COLUMN bulk_import_log.performed_by IS
    'Əməliyyatı icra edən şəxs (`can_perform_bulk_operations` sahibi).';
COMMENT ON COLUMN bulk_import_log.file_ref IS
    'Mənbə faylın istinadı. NULL = əməliyyat fayldan deyil, ekrandan seçimlə '
    'aparılıb — #29 hər iki yolu əhatə edir.';
COMMENT ON COLUMN bulk_import_log.row_count IS
    'Emal üçün götürülmüş ümumi sətir sayı.';
COMMENT ON COLUMN bulk_import_log.success_count IS 'Uğurla tətbiq edilən sətir sayı.';
COMMENT ON COLUMN bulk_import_log.error_count IS
    'Rədd edilən sətir sayı. Sıfırdan böyükdürsə `error_summary` MƏCBURİDİR.';
COMMENT ON COLUMN bulk_import_log.error_summary IS
    'Uğursuzluğun qısa izahı (hansı sətir, hansı səbəb). Səbəbsiz uğursuzluq '
    'növbəti idxalda eynilə təkrarlanardı.';
COMMENT ON COLUMN bulk_import_log.performed_at IS
    'Əməliyyatın başlama anı (tz-aware). Spesifikasiyadakı vaxt sütunu budur; '
    'ayrıca yaradılma sütunu saxlanılmır — sətir məhz bu anda yaranır.';
COMMENT ON COLUMN bulk_import_log.finished_at IS
    'Bitmə anı. NULL = əməliyyat yarımçıq qalıb (proses çöküb) — bu vəziyyət '
    'GÖRÜNƏN saxlanılır, sükutla "uğurlu" sayılmır.';

-- ---------------------------------------------------------------------------
-- 8. store_templates (#29) — MAĞAZA ŞABLONU
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS store_templates (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL REFERENCES license_tenants(tenant_id)
                           ON DELETE CASCADE,

    name               TEXT NOT NULL CHECK (char_length(trim(name)) >= 2),

    -- SET NULL — ƏSASLANDIRMA (spesifikasiya tələbi): şablon mənbə mağazadan
    -- MÜSTƏQİL yaşayır. CASCADE olsaydı, nümunə götürülmüş mağazanın silinməsi
    -- ondan qurulmuş bütün şablonları da aparardı; NO ACTION isə mağazanın
    -- silinməsini şablona görə bloklayardı — hər ikisi səhvdir, çünki şablonun
    -- DƏYƏRİ `config_snapshot`-dadır, mənbədə deyil.
    based_on_store_id  UUID REFERENCES stores(id) ON DELETE SET NULL,

    -- Boş obyekt QADAĞANDIR: parametrsiz şablondan yaradılan mağaza heç bir
    -- ayar almaz və bu, yalnız istifadə anında üzə çıxardı.
    config_snapshot    JSONB NOT NULL
                           CHECK (jsonb_typeof(config_snapshot) = 'object'
                                  AND config_snapshot <> '{}'::jsonb),

    created_by         UUID REFERENCES employees(id) ON DELETE SET NULL,

    -- Kataloq xarakterli cədvəl → soft delete (CLAUDE.md §4 `catalogs.py` qaydası):
    -- şablon silinsəydi, ondan qurulmuş mağazanın ayarlarının HARADAN gəldiyi
    -- sualı cavabsız qalardı.
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    deactivated_at     TIMESTAMPTZ,

    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (tenant_id, name),

    CONSTRAINT chk_store_template_deactivation
        CHECK (is_active OR deactivated_at IS NOT NULL)
);

DROP TRIGGER IF EXISTS trg_store_templates_updated ON store_templates;
CREATE TRIGGER trg_store_templates_updated BEFORE UPDATE ON store_templates
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE store_templates IS
    '#29 — Yeni mağazanın adlandırılmış konfiqurasiya şablonu. Şablon mənbə '
    'mağazadan MÜSTƏQİLDİR: mənbə silinsə `based_on_store_id` NULL olur, '
    'şablonun özü qalır.';
COMMENT ON COLUMN store_templates.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN store_templates.tenant_id IS 'Kirayəçi izolyasiyası — RLS açarı.';
COMMENT ON COLUMN store_templates.name IS
    'Şablonun adı (kirayəçi daxilində unikal) — istifadəçi onu bu adla seçir.';
COMMENT ON COLUMN store_templates.based_on_store_id IS
    'Nümunə götürülmüş mağaza. NULL = mənbə mağaza artıq yoxdur (SET NULL) və '
    'ya şablon sıfırdan qurulub. Şablonun dəyəri `config_snapshot`-dadır.';
COMMENT ON COLUMN store_templates.config_snapshot IS
    'Şablonun ayar toplusu (JSONB obyekt). Sabit sütun siyahısı rədd edildi: '
    'hər yeni ayar miqrasiya tələb edərdi və köhnə şablonlar həmin sütunu boş '
    'daşıyardı (`dashboard_layout` və `ratings_json` ilə eyni qərar). Boş obyekt '
    'QADAĞANDIR — parametrsiz şablon sükutla mənasızdır.';
COMMENT ON COLUMN store_templates.created_by IS 'Şablonu yaradan şəxs.';
COMMENT ON COLUMN store_templates.is_active IS
    'Soft delete: FALSE = yeni mağaza üçün seçilmir; sətir SİLİNMİR, çünki '
    'mövcud mağazaların ayarlarının mənbəyi odur.';
COMMENT ON COLUMN store_templates.deactivated_at IS 'Söndürülmə anı (tz-aware).';
COMMENT ON COLUMN store_templates.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN store_templates.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

-- ---------------------------------------------------------------------------
-- 9. executive_digest_config (#30) — İCRA XÜLASƏSİNİN KONFİQURASİYASI
-- ---------------------------------------------------------------------------
-- `frequency` NİYƏ SƏRT SİYAHIDIR, `recipient_role` İSƏ SƏRBƏST MƏTNDİR:
-- tezlik planlayıcının iş açarına bağlıdır (`app_scheduled_job_runs`) — kod
-- dəstəyi olmayan "hər 3 gündən bir" dəyəri sükutla heç vaxt göndərilməzdi.
-- Rol isə kirayəçinin ÖZ rol kataloqundan gəlir və Root yeni rol yarada bilər.
CREATE TABLE IF NOT EXISTS executive_digest_config (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES license_tenants(tenant_id)
                          ON DELETE CASCADE,

    -- FK QOYULA BİLMİR — səbəb `field_report_categories.route_to_role`-dakı ilə
    -- eynidir: `positions.code` yalnız `(tenant_id, code)` cütü ilə unikaldır və
    -- sistem rolları `tenant_id IS NULL` sətirlərdir.
    recipient_role    TEXT NOT NULL
                          CHECK (recipient_role = upper(recipient_role)
                             AND char_length(trim(recipient_role)) >= 2),

    frequency         TEXT NOT NULL
                          CHECK (frequency IN ('DAILY', 'WEEKLY', 'MONTHLY')),

    -- Boş xülasə = boş e-poçt. Massiv seçimi `photo_refs` ilə eyni əsaslandırma:
    -- element tipi (metrik açarı) struktur şəkildə zəmanətlidir.
    metrics_included  TEXT[] NOT NULL
                          CHECK (cardinality(metrics_included) >= 1
                                 AND NOT ('' = ANY (metrics_included))),

    -- NULL = heç vaxt göndərilməyib. Planlayıcı "vaxtı çatıbmı?" sualını buna
    -- görə cavablandırır; sütun olmasaydı, yenidən işə salınan sistem eyni
    -- xülasəni təkrar göndərərdi.
    last_sent_at      TIMESTAMPTZ,

    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    deactivated_at    TIMESTAMPTZ,

    created_by        UUID REFERENCES employees(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Eyni rola eyni tezlikdə İKİ konfiqurasiya = iki eyni e-poçt. Fərqli
    -- tezliklər (həm gündəlik, həm aylıq) isə QANUNİDİR — ona görə tezlik
    -- açarın hissəsidir.
    UNIQUE (tenant_id, recipient_role, frequency),

    CONSTRAINT chk_executive_digest_deactivation
        CHECK (is_active OR deactivated_at IS NOT NULL)
);

DROP TRIGGER IF EXISTS trg_executive_digest_updated ON executive_digest_config;
CREATE TRIGGER trg_executive_digest_updated BEFORE UPDATE ON executive_digest_config
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Planlayıcının sorğusu: "hansı aktiv konfiqurasiyanın vaxtı çatıb?"
CREATE INDEX IF NOT EXISTS idx_executive_digest_due
    ON executive_digest_config (tenant_id, frequency, last_sent_at)
    WHERE is_active;

COMMENT ON TABLE executive_digest_config IS
    '#30 — Planlaşdırılmış icra xülasəsinin kirayəçi başına konfiqurasiyası: '
    'kimə, nə tezlikdə, hansı metriklər. Göndərmə mexanizmi mövcud planlayıcı '
    've bildiriş kanallarındadır — yeni kanal açılmır.';
COMMENT ON COLUMN executive_digest_config.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN executive_digest_config.tenant_id IS 'Kirayəçi izolyasiyası — RLS açarı.';
COMMENT ON COLUMN executive_digest_config.recipient_role IS
    'Alıcı rolun kodu (`positions.code`, BÖYÜK hərflərlə). Konkret işçi deyil, '
    'ROL saxlanılır: şəxs dəyişəndə xülasə avtomatik yeni vəzifə sahibinə gedir. '
    'FK yoxdur — `positions.code` yalnız kirayəçi daxilində unikaldır.';
COMMENT ON COLUMN executive_digest_config.frequency IS
    'DAILY / WEEKLY / MONTHLY. Siyahı SƏRTDİR: hər dəyər planlayıcının iş '
    'açarına bağlıdır, kod dəstəyi olmayan tezlik heç vaxt göndərilməzdi.';
COMMENT ON COLUMN executive_digest_config.metrics_included IS
    'Xülasəyə daxil edilən metrik açarları. Ən azı bir element MƏCBURİDİR — '
    'boş siyahı boş e-poçt deməkdir.';
COMMENT ON COLUMN executive_digest_config.last_sent_at IS
    'Sonuncu göndərmə anı (tz-aware). NULL = heç vaxt göndərilməyib. Planlayıcı '
    'təkrar göndərmənin qarşısını məhz bu sütunla alır.';
COMMENT ON COLUMN executive_digest_config.is_active IS
    'Soft delete: FALSE = xülasə göndərilmir. Sətir SİLİNMİR ki, keçmiş '
    'göndərmələrin hansı ayarla edildiyi görünsün.';
COMMENT ON COLUMN executive_digest_config.deactivated_at IS 'Söndürülmə anı (tz-aware).';
COMMENT ON COLUMN executive_digest_config.created_by IS 'Konfiqurasiyanı yaradan şəxs.';
COMMENT ON COLUMN executive_digest_config.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN executive_digest_config.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

-- ---------------------------------------------------------------------------
-- 10. export_manual_corrections (HR-D) — EXPORT ƏL İLƏ DÜZƏLİŞLƏRİ
-- ---------------------------------------------------------------------------
-- Spesifikasiyadakı `date` sütunu burada `target_date` adlanır: `date` həm tip
-- adı, həm literal prefiksidir (`date '2026-01-01'`) və sütun kimi işlədilməsi
-- sorğuları oxunmaz edir. Məna dəyişmir — düzəlişin aid olduğu təqvim günü.
CREATE TABLE IF NOT EXISTS export_manual_corrections (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES license_tenants(tenant_id)
                      ON DELETE CASCADE,

    -- Sərt siyahı yoxdur (`import_type` ilə eyni əsaslandırma): export növləri
    -- artır (davamiyyət, bonus/cərimə, ...), hər yenisi miqrasiya tələb etməməlidir.
    export_type   TEXT NOT NULL
                      CHECK (export_type = upper(export_type)
                         AND char_length(trim(export_type)) >= 3),

    -- NO ACTION: düzəliş qeydi işçinin ÖDƏNİŞİNƏ təsir edir və işçi sətrindən
    -- uzun yaşamalıdır.
    employee_id   UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,

    target_date   DATE NOT NULL,

    field         TEXT NOT NULL CHECK (char_length(trim(field)) >= 2),

    -- Hər ikisi mətndir və NULL ola bilər — ƏSASLANDIRMA: düzəlişə düşən sahələr
    -- fərqli tiplidir (dəqiqə, məbləğ, saat, bayraq); tipli sütun dəsti hər
    -- sahə üçün ayrı sütun tələb edərdi. NULL isə real vəziyyətdir: sahə boş
    -- idi (köhnə dəyər yoxdur) və ya düzəliş dəyəri təmizləyir.
    old_value     TEXT,
    new_value     TEXT,

    -- MƏCBURİ VƏ BOŞ OLA BİLMƏZ: səbəbsiz düzəliş auditdə dəyərsizdir — sətir
    -- yalnız "kimsə nəyisə dəyişdi" deyər, "niyə" sualını cavabsız qoyardı.
    -- 10 simvol DÖŞƏMƏDİR, siyasət deyil ("Səhv" kimi cavab kəsilir); həqiqi
    -- minimum ROOT parametridir və use case-də tətbiq olunur (CLAUDE.md §5).
    reason        TEXT NOT NULL CHECK (char_length(trim(reason)) >= 10),

    corrected_by  UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,
    corrected_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Dəyişməyən "düzəliş" auditdə səs-küydür və delta-müqayisə ekranında
    -- yalançı fərq kimi görünərdi.
    CONSTRAINT chk_export_correction_changes
        CHECK (old_value IS DISTINCT FROM new_value)
);

-- Export yığılarkən əsas sorğu: "bu növ, bu tarix aralığı üçün düzəlişlər".
CREATE INDEX IF NOT EXISTS idx_export_corrections_lookup
    ON export_manual_corrections (tenant_id, export_type, target_date);
-- İşçi profilində "mənim tabelimə edilən düzəlişlər".
CREATE INDEX IF NOT EXISTS idx_export_corrections_employee
    ON export_manual_corrections (employee_id, target_date DESC);

COMMENT ON TABLE export_manual_corrections IS
    'HR-yaxşılaşdırması D — export cədvəlinə edilən ƏL İLƏ düzəlişlərin '
    'dəyişməz audit izi. Sətir nə silinir, nə yenilənir: yenidən düzəliş YENİ '
    'sətirdir (`old_value` = əvvəlki `new_value`). Düzəlişin özü düzəldilə '
    'bilsəydi, "kim nəyi nəyə dəyişdi" izi geri yazıla bilərdi.';
COMMENT ON COLUMN export_manual_corrections.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN export_manual_corrections.tenant_id IS 'Kirayəçi izolyasiyası — RLS açarı.';
COMMENT ON COLUMN export_manual_corrections.export_type IS
    'Hansı export düzəldilib (məs. DAVAMIYYET, BONUS_CERIME). Sərt siyahı yoxdur '
    '— yeni export növü miqrasiya tələb etməməlidir.';
COMMENT ON COLUMN export_manual_corrections.employee_id IS
    'Düzəlişin aid olduğu işçi — sətir onun ödənişinə təsir edir.';
COMMENT ON COLUMN export_manual_corrections.target_date IS
    'Düzəlişin aid olduğu təqvim günü. Ad spesifikasiyadan bir qədər fərqlidir, '
    'çünki qısa variant SQL-də tip adı ilə eyni yazılır.';
COMMENT ON COLUMN export_manual_corrections.field IS
    'Düzəldilən sahənin adı (export sütunu) — hansı rəqəmin dəyişdiyi.';
COMMENT ON COLUMN export_manual_corrections.old_value IS
    'Düzəlişdən ƏVVƏLKİ dəyər (mətn). NULL = sahə boş idi.';
COMMENT ON COLUMN export_manual_corrections.new_value IS
    'Düzəlişdən SONRAKI dəyər (mətn). NULL = düzəliş dəyəri təmizləyir. '
    'Köhnə və yeni dəyərin eyni olması DB səviyyəsində bloklanır.';
COMMENT ON COLUMN export_manual_corrections.reason IS
    'Düzəlişin səbəbi — MƏCBURİ. Səbəbsiz düzəliş auditdə dəyərsizdir. DB-dəki '
    'minimum uzunluq yalnız absurd cavabı kəsən döşəmədir.';
COMMENT ON COLUMN export_manual_corrections.corrected_by IS
    'Düzəlişi edən şəxs (`can_manage_export_corrections` sahibi).';
COMMENT ON COLUMN export_manual_corrections.corrected_at IS 'Düzəliş anı (tz-aware).';

-- ---------------------------------------------------------------------------
-- 11. RLS — YENİ CƏDVƏLLƏR DƏ FAIL-CLOSED OLMALIDIR (SEC-008)
-- ---------------------------------------------------------------------------
-- `app.tenant_id` təyin edilməyibsə tətbiq rolu HEÇ BİR sətir görmür.
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'field_reports', 'field_report_checklist_items',
        'annual_leave_balances', 'annual_leave_requests',
        'bulk_import_log', 'store_templates',
        'executive_digest_config', 'export_manual_corrections'
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

-- İki kataloq — `exception_sources` / `positions` naxışı: sistem sətirləri
-- (`tenant_id IS NULL`) hər kirayəçiyə GÖRÜNÜR, lakin heç kim öz sətrini sistem
-- sətri kimi yaza bilmir (`WITH CHECK` yalnız öz `tenant_id`-sinə icazə verir).
ALTER TABLE field_report_types ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON field_report_types;
CREATE POLICY tenant_isolation ON field_report_types
    USING (tenant_id = current_tenant_id() OR tenant_id IS NULL)
    WITH CHECK (tenant_id = current_tenant_id());

ALTER TABLE field_report_categories ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON field_report_categories;
CREATE POLICY tenant_isolation ON field_report_categories
    USING (tenant_id = current_tenant_id() OR tenant_id IS NULL)
    WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- 12. GRANT — tətbiq rolu
-- ---------------------------------------------------------------------------
-- `DELETE` HEÇ BİR CƏDVƏLDƏ VERİLMİR:
--   * kataloqlar (`field_report_types`, `field_report_categories`,
--     `store_templates`, `executive_digest_config`) soft delete ilə idarə olunur;
--   * `field_reports` + checklist bəndləri müşahidənin sübutudur;
--   * `annual_leave_*` pul dəyəri daşıyır (istifadə edilməmiş gün kompensasiya
--     oluna bilər) — sətrin silinməsi balansı sükutla bərpa edərdi;
--   * `bulk_import_log` və `export_manual_corrections` audit qeydidir.
--
-- ⚠️ AÇIQ `REVOKE` MƏCBURİDİR: `schema.sql` §28-dəki `ALTER DEFAULT PRIVILEGES`
-- bundan SONRA yaradılan hər cədvələ `DELETE`-i AVTOMATİK verir; dar `GRANT`
-- tək başına məhdudiyyət yaratmır (ətraflı izah `migrations/018`-dədir).
--
-- `export_manual_corrections`-dan `UPDATE` də geri alınır — sətir DƏYİŞMƏZDİR
-- (yuxarıdakı cədvəl şərhinə bax). Ona görə həmin cədvəldə `updated_at`/trigger
-- də yoxdur: dəyişmək mümkün olmayan sətrin "sonuncu dəyişiklik anı" olmaz.
DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE ON field_report_types, '
            'field_report_categories, field_reports, '
            'field_report_checklist_items, annual_leave_balances, '
            'annual_leave_requests, bulk_import_log, store_templates, '
            'executive_digest_config TO %I', v_role
        );
        EXECUTE format(
            'REVOKE DELETE ON field_report_types, field_report_categories, '
            'field_reports, field_report_checklist_items, '
            'annual_leave_balances, annual_leave_requests, bulk_import_log, '
            'store_templates, executive_digest_config FROM %I', v_role
        );
        EXECUTE format(
            'GRANT SELECT, INSERT ON export_manual_corrections TO %I', v_role
        );
        EXECUTE format(
            'REVOKE UPDATE, DELETE ON export_manual_corrections FROM %I', v_role
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
-- DİQQƏT: bu blok SÜBUT və AUDİT sətirlərini məhv edir —
--   * `export_manual_corrections` "kim tabeli əl ilə dəyişdi?" sualının
--     YEGANƏ struktur cavabıdır;
--   * `bulk_import_log` 500 sətri bir kliklə dəyişən əməliyyatın izidir;
--   * `annual_leave_balances` işçinin qazanılmış (və pul dəyəri olan) haqqıdır.
-- Ona görə geri qaytarma yalnız həmin funksiyaların giriş nöqtələri də
-- söndürüldükdə təhlükəsizdir.
--
-- `work_modes` bu miqrasiyanın MƏHSULU DEYİL (`schema.sql` §11) — DOWN bloku
-- ona TOXUNMUR. `btree_gist` genişlənməsi də saxlanılır: onu geri götürmək
-- başqa obyektləri sındıra bilər.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TABLE IF EXISTS export_manual_corrections;
--   DROP TABLE IF EXISTS executive_digest_config;
--   DROP TABLE IF EXISTS store_templates;
--   DROP TABLE IF EXISTS bulk_import_log;
--   DROP TABLE IF EXISTS annual_leave_requests;
--   DROP TABLE IF EXISTS annual_leave_balances;
--   DROP TABLE IF EXISTS field_report_checklist_items;
--   DROP TABLE IF EXISTS field_reports;
--   DROP TABLE IF EXISTS field_report_categories;
--   DROP TABLE IF EXISTS field_report_types;
-- COMMIT;
