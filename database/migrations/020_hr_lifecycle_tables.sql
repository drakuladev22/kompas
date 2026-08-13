-- ===========================================================================
-- 020 — HR HƏYAT DÖVRÜ: SƏNƏDLƏR, ELANLAR, PERFORMANS, İŞDƏN ÇIXMA RİSKİ
-- ===========================================================================
-- Tarix : 2026-08-11
-- Səbəb : Faza 1 (kompasos11.md) dörd HR funksiyasının saxlama qatını tələb
--         edir: #17 sənəd/müqavilə idarəetməsi, #19 elan (broadcast), #20
--         performans qiymətləndirməsi, #21 işdən çıxma riski balı.
--         Mövcud `employees`, `stores`, `fines` və s. cədvəllərə TOXUNULMUR.
--
-- İdempotentdir. DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- 1C SƏRHƏDİ
-- ---------------------------------------------------------------------------
-- Bu cədvəllərin heç biri 1C-yə bağlantı AÇMIR. #21-in bal modeli YALNIZ
-- KompasOS-un öz datasından (davamiyyət, cərimə, icazə, növbə) qidalanır.
--
-- ---------------------------------------------------------------------------
-- FAYL SAXLAMA — YENİ KANAL AÇILMIR
-- ---------------------------------------------------------------------------
-- `employee_documents.file_ref` MÖVCUD sübut-saxlama kanalını (Google Drive,
-- bax `migrations/002` başlığı) təkrar istifadə edir. Yeni bucket, yeni
-- provayder, yeni OAuth axını YARADILMIR — sütun sadəcə `StorageReference`
-- açarını saxlayır. Fayl mətnini bazaya (BYTEA) yığmaq da rədd edildi: sənəd
-- skanları onlarla meqabayt ola bilər və hər ehtiyat nüsxəni şişirdərdi.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. employee_documents (#17) — SƏNƏD VƏ MÜQAVİLƏLƏR
-- ---------------------------------------------------------------------------
-- FİZİKİ SİLMƏ YOXDUR — NİYƏ: müddəti bitmiş sənəd "lazımsız zibil" deyil.
-- O, KEÇMİŞ təyinatın niyə icazəli olduğunu SÜBUT edir: "işçi yanvarda niyə
-- növbəyə salındı?" sualının cavabı "həmin tarixdə müqaviləsi qüvvədə idi"dir.
-- Sətir silinsəydi, cavab yoxa çıxar və Faza 7-dəki bloklama məntiqi keçmişə
-- baxanda hər təyinatı "qaydasız" göstərərdi. Ona görə `is_active` + səbəb
-- saxlanılır (`catalogs.py` başlığındakı soft delete qaydası).
--
-- `doc_type` NİYƏ SƏRT `CHECK` DEYİL: sənəd növü sırf ETİKETDİR — davranışı
-- `is_blocking` sütunu təyin edir, növün adı yox. Sərt siyahı hər yeni sənəd
-- növü (məs. "Sanitar kitabça") üçün miqrasiya tələb edərdi. Əvəzinə
-- NORMALLAŞDIRMA məcburidir (böyük hərf + boş olmama), ki "Muqavile" və
-- "MUQAVILE" iki ayrı növ kimi görünməsin.
CREATE TABLE IF NOT EXISTS employee_documents (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES license_tenants(tenant_id)
                             ON DELETE CASCADE,
    -- CASCADE: sənəd qeydi işçi sətrinin törəməsidir. İşçilər praktikada
    -- fiziki silinmir (`employees.is_active` soft delete), ona görə bu yol
    -- yalnız tenant tam ləğv olunanda işə düşür.
    employee_id          UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,

    doc_type             TEXT NOT NULL
                             CHECK (doc_type = upper(doc_type)
                                AND char_length(trim(doc_type)) >= 2),
    -- NULL ola bilər — ƏSASLANDIRMA: HR bəzən sənədin MÖVCUDLUĞUNU və bitmə
    -- tarixini qeydə alır, skan isə sonra gəlir. Faylı məcbur etsək, qeyd
    -- ümumiyyətlə yazılmaz və bitmə tarixi izlənməzdi.
    file_ref             TEXT,

    -- NULL = müddətsiz sənəd (məs. diplom). Bitmə xəbərdarlığı yalnız dolu
    -- sətirlərə aiddir.
    expiry_date          DATE,

    is_blocking          BOOLEAN NOT NULL DEFAULT FALSE,

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: uyğunluq (compliance) qeydinin sahibi
    -- olmalıdır. "Kim bu sənədi sistemə saldı?" sualı auditin ilk sualıdır.
    uploaded_by          UUID REFERENCES employees(id) ON DELETE SET NULL,

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: sənədin nömrəsi/seriyası olmadan iki oxşar
    -- qeydi (köhnə və yenilənmiş müqavilə) ayırmaq mümkün deyil.
    doc_number           TEXT,

    -- Soft delete bloku (fiziki `DELETE` QADAĞANDIR — yuxarıdakı izah).
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    deactivated_at       TIMESTAMPTZ,
    deactivated_by       UUID REFERENCES employees(id) ON DELETE SET NULL,
    deactivation_reason  TEXT,

    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_employee_document_deactivation
        CHECK (is_active OR deactivated_at IS NOT NULL)
);

DROP TRIGGER IF EXISTS trg_employee_documents_updated ON employee_documents;
CREATE TRIGGER trg_employee_documents_updated BEFORE UPDATE ON employee_documents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- UNIQUE (employee_id, doc_type) QƏSDƏN YOXDUR: müqavilə yenilənəndə KÖHNƏ
-- sətir qalmalıdır (yuxarıdakı sübut arqumenti). Bir işçinin eyni növdən çox
-- sənədi normaldır; "hazırda qüvvədə olan" sualını `expiry_date` + `is_active`
-- cavablandırır.

-- Faza 7 KRİTİK SORĞUSU: Shift Matrix hər təyinetmədə "bu işçinin bloklayıcı
-- sənədi bitibmi?" soruşur. Bu sorğu ekranın hər klikində işlədiyi üçün
-- indekssiz qalması bütün matrisi yavaşladardı.
CREATE INDEX IF NOT EXISTS idx_employee_documents_blocking
    ON employee_documents (employee_id, expiry_date)
    WHERE is_active AND is_blocking;

-- "Yaxın 30 gündə bitən sənədlər" paneli.
CREATE INDEX IF NOT EXISTS idx_employee_documents_expiring
    ON employee_documents (tenant_id, expiry_date)
    WHERE is_active AND expiry_date IS NOT NULL;

COMMENT ON TABLE employee_documents IS
    '#17 — İşçi sənədləri və müqavilələri. Fiziki silmə YOXDUR: müddəti bitmiş '
    'sənəd keçmiş növbə təyinatının NİYƏ icazəli olduğunu sübut edir. Fayl '
    'özü mövcud Google Drive kanalındadır (migrations/002) — yeni saxlama '
    'kanalı açılmır.';
COMMENT ON COLUMN employee_documents.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN employee_documents.tenant_id IS 'Kirayəçi izolyasiyası — RLS açarı.';
COMMENT ON COLUMN employee_documents.employee_id IS 'Sənədin aid olduğu işçi.';
COMMENT ON COLUMN employee_documents.doc_type IS
    'Sənəd növü, BÖYÜK hərflərlə (məs. MUQAVILE, SANITAR_KITABCA). Sərt siyahı '
    'YOXDUR — davranışı `is_blocking` müəyyən edir, ad yalnız etiketdir.';
COMMENT ON COLUMN employee_documents.file_ref IS
    'Drive fayl açarı (`StorageReference`). NULL = skan hələ yüklənməyib, '
    'lakin sənədin mövcudluğu və bitmə tarixi izlənir.';
COMMENT ON COLUMN employee_documents.expiry_date IS
    'Bitmə tarixi. NULL = müddətsiz sənəd — xəbərdarlıq mexanizmindən kənardır.';
COMMENT ON COLUMN employee_documents.is_blocking IS
    'TRUE = sənəd bitibsə Shift Matrix təyinetməsi XƏBƏRDARLIĞA salınır (Faza 7). '
    'Təyinetməni SƏRT bloklamır — qərar admindədir, sistem yalnız xəbərdarlıq edir.';
COMMENT ON COLUMN employee_documents.uploaded_by IS 'Qeydi sistemə salan şəxs.';
COMMENT ON COLUMN employee_documents.doc_number IS
    'Sənəd nömrəsi/seriyası — köhnə və yenilənmiş nüsxəni ayırmaq üçün.';
COMMENT ON COLUMN employee_documents.is_active IS
    'Soft delete: FALSE = qeyd səhv salınıb və ya ləğv edilib. Sətir SİLİNMİR.';
COMMENT ON COLUMN employee_documents.deactivated_at IS 'Söndürülmə anı (tz-aware).';
COMMENT ON COLUMN employee_documents.deactivated_by IS 'Söndürən şəxs.';
COMMENT ON COLUMN employee_documents.deactivation_reason IS
    'Söndürmənin səbəbi — sənəd qeydinin yoxa çıxması izah tələb edir.';
COMMENT ON COLUMN employee_documents.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN employee_documents.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

-- ---------------------------------------------------------------------------
-- 2. announcements (#19) — ELAN (BROADCAST)
-- ---------------------------------------------------------------------------
-- `notifications` İLƏ BİRLƏŞDİRİLMƏDİ — NİYƏ: mövcud `notifications` cədvəli
-- BİR alıcıya (`recipient_id`) göndərilən, oxunma vəziyyəti izlənən SİSTEM
-- bildirişidir (timeout eskalasiyası, dual-control gözləməsi). Elan isə əks
-- istiqamətdədir: BİR mətn, ÇOX alıcı, insan tərəfindən yazılır və geri çəkilə
-- bilər. İkisini birləşdirmək üçün `notifications`-a `scope` və müəllif sütunu
-- əlavə etmək lazım gələrdi və hər sistem bildirişi bu sütunları boş daşıyardı;
-- daha pisi — elanın MƏTNİ hər alıcı üçün təkrarlanardı (100 işçi = 100 nüsxə)
-- və düzəliş halında hansının doğru olduğu bilinməzdi.
-- Çatdırılma qatı (kimə göstərildi/oxundu) Faza 8-də `notifications` üzərindən
-- qurula bilər — bu cədvəl MƏNBƏ mətnin tək nüsxəsidir.
CREATE TABLE IF NOT EXISTS announcements (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES license_tenants(tenant_id)
                         ON DELETE CASCADE,

    -- NO ACTION (CASCADE DEYİL): müəllif sistemdən çıxsa da elan qalmalıdır —
    -- "bu göstərişi kim verdi?" sualı elandan uzun yaşayır.
    created_by       UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: elan siyahısı ekranı qısa başlıq göstərməlidir.
    -- Mətnin ilk 50 simvolunu kəsmək variantı rədd edildi: kəsik söz ortasından
    -- düşür və uzun cümlələrdə mənasız başlıq verir.
    title_az         TEXT NOT NULL CHECK (char_length(trim(title_az)) >= 3),
    message          TEXT NOT NULL CHECK (char_length(trim(message)) >= 5),

    scope            TEXT NOT NULL CHECK (scope IN ('ALL', 'STORE_LIST')),

    -- Soft delete — ƏSASLANDIRMA: geri çəkilən elan SİLİNMİR. İşçilər onu artıq
    -- görüb; "belə bir göstəriş heç vaxt olmayıb" vəziyyəti yaratmaq mübahisədə
    -- zərərlidir. Geri çəkmə YENİ görüntülənməni dayandırır, tarixi qeydi yox.
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    deactivated_at   TIMESTAMPTZ,
    deactivated_by   UUID REFERENCES employees(id) ON DELETE SET NULL,

    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_announcement_deactivation
        CHECK (is_active OR deactivated_at IS NOT NULL),

    -- Uşaq cədvəlin BİRLƏŞMİŞ FK-sı üçün lazımdır (aşağıya bax). Praktik
    -- yükü yoxdur: `id` onsuz da unikaldır, bu, yalnız kirayəçi cütünü
    -- FK hədəfi kimi açır.
    UNIQUE (tenant_id, id)
);

DROP TRIGGER IF EXISTS trg_announcements_updated ON announcements;
CREATE TRIGGER trg_announcements_updated BEFORE UPDATE ON announcements
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_announcements_active
    ON announcements (tenant_id, created_at DESC) WHERE is_active;

COMMENT ON TABLE announcements IS
    '#19 — Rəhbərlikdən işçilərə elan. Mövcud `notifications` ilə BİRLƏŞDİRİLMƏDİ: '
    'o, tək-alıcılı sistem bildirişidir və elanın mətni orada hər alıcı üçün '
    'təkrarlanardı. Bu cədvəl mətnin TƏK nüsxəsidir.';
COMMENT ON COLUMN announcements.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN announcements.tenant_id IS 'Kirayəçi izolyasiyası — RLS açarı.';
COMMENT ON COLUMN announcements.created_by IS
    'Elanı yazan şəxs. `ON DELETE NO ACTION` — müəllif olmadan elan yetim qalmamalıdır.';
COMMENT ON COLUMN announcements.title_az IS
    'Qısa başlıq (Azərbaycanca, bölmə 9) — siyahı ekranı üçün. Mətndən '
    'avtomatik kəsilmir, çünki kəsik söz ortasından düşür.';
COMMENT ON COLUMN announcements.message IS 'Elanın tam mətni (Azərbaycanca).';
COMMENT ON COLUMN announcements.scope IS
    'ALL = bütün mağazalar; STORE_LIST = yalnız `announcement_targets`-dəki '
    'mağazalar. ALL halında hədəf sətri OLMAMALIDIR (trigger yoxlayır).';
COMMENT ON COLUMN announcements.is_active IS
    'Soft delete: FALSE = elan geri çəkilib, yeni göstərilmir. Sətir SİLİNMİR.';
COMMENT ON COLUMN announcements.deactivated_at IS 'Geri çəkilmə anı (tz-aware).';
COMMENT ON COLUMN announcements.deactivated_by IS 'Elanı geri çəkən şəxs.';
COMMENT ON COLUMN announcements.created_at IS 'Yaradılma (dərc) anı (tz-aware).';
COMMENT ON COLUMN announcements.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

-- ---------------------------------------------------------------------------
-- 2a. announcement_targets — `STORE_LIST` əhatəsinin hədəfləri
-- ---------------------------------------------------------------------------
-- ƏLAVƏ CƏDVƏL — ƏSASLANDIRMA: `scope = 'STORE_LIST'` bir mağaza SİYAHISI
-- tələb edir. İki variant vardı:
--   (a) `announcements.store_ids UUID[]` və ya `JSONB` massiv — FK YOXDUR,
--       yəni silinmiş/başqa kirayəçiyə aid mağaza ID-si sükutla saxlanıla
--       bilərdi və "mənim mağazama aid elanlar" sorğusu massiv açılışı tələb
--       edərdi;
--   (b) SEÇİLDİ: uşaq cədvəl — real `FOREIGN KEY`, adi indeks, mövcud
--       `camera_operator_store_assignment` / `store_server_mapping`
--       naxışının eynisi.
--
-- `tenant_id` NİYƏ TƏKRARLANIR: RLS siyasəti valideyn üzərindən `EXISTS` ilə
-- də qurula bilərdi (sxem §27-də belə cədvəllər var), lakin o, HƏR sətir üçün
-- alt-sorğu deməkdir. Sütunun valideyndən sürüşməsi isə BİRLƏŞMİŞ FK ilə
-- struktur şəkildə qadağandır — yəni denormalizasiya risksizdir.
CREATE TABLE IF NOT EXISTS announcement_targets (
    tenant_id        UUID NOT NULL REFERENCES license_tenants(tenant_id)
                         ON DELETE CASCADE,
    announcement_id  UUID NOT NULL,
    -- CASCADE: mağaza qeydi silinərsə hədəf sətrinin mənası qalmır. Mağazalar
    -- praktikada soft delete edilir (`stores.is_active`), ona görə bu yol nadir haldır.
    store_id         UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (announcement_id, store_id),
    -- BİRLƏŞMİŞ FK: hədəfin `tenant_id`-si valideyn elanınkı ilə EYNİ olmalıdır.
    -- Adi tək-sütunlu FK bu zəmanəti vermir və denormalizasiya sükutla sürüşərdi.
    -- CASCADE: elan silinərsə (yalnız DOWN blokunda) hədəfləri də getməlidir.
    FOREIGN KEY (tenant_id, announcement_id)
        REFERENCES announcements (tenant_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_announcement_targets_store
    ON announcement_targets (tenant_id, store_id);

COMMENT ON TABLE announcement_targets IS
    'ƏLAVƏ CƏDVƏL (#19): `scope = STORE_LIST` elanının hədəf mağazaları. '
    'Massiv/JSONB əvəzinə uşaq cədvəl seçildi — FK bütövlüyü və indeks üçün.';
COMMENT ON COLUMN announcement_targets.tenant_id IS
    'Kirayəçi izolyasiyası. Valideyndən sürüşməsi birləşmiş FK ilə qadağandır.';
COMMENT ON COLUMN announcement_targets.announcement_id IS 'Hədəf aid olduğu elan.';
COMMENT ON COLUMN announcement_targets.store_id IS 'Elanın göstəriləcəyi mağaza.';
COMMENT ON COLUMN announcement_targets.created_at IS 'Hədəfin əlavə olunma anı (tz-aware).';

-- `scope = 'ALL'` elana hədəf yazmaq ZİDDİYYƏTDİR: oxuma tərəfi "hamı"
-- görsəydi hədəfləri nəzərə almaz, hədəfləri görsəydi "hamı"nı. Belə sətir
-- sükutla yatıb sonradan yanlış əhatə kimi üzə çıxardı.
--
-- ƏKS TƏRƏF ("STORE_LIST-in ən azı bir hədəfi olmalıdır") burada MƏCBUR
-- EDİLMİR: onu yalnız COMMIT anında yoxlamaq olar (`DEFERRABLE` constraint
-- trigger) və bu, elanı hədəflərdən ƏVVƏL yazan hər normal axını sındırardı.
-- Həmin qayda tətbiq qatındadır (Faza 8, use case).
CREATE OR REPLACE FUNCTION enforce_announcement_target_scope() RETURNS TRIGGER AS $$
DECLARE
    v_scope TEXT;
BEGIN
    SELECT scope INTO v_scope FROM announcements WHERE id = NEW.announcement_id;
    IF v_scope IS DISTINCT FROM 'STORE_LIST' THEN
        RAISE EXCEPTION
            'ELAN ƏHATƏSİ ZİDDİYYƏTİ: "%" əhatəli elana mağaza hədəfi əlavə '
            'edilə bilməz — hədəf yalnız STORE_LIST əhatəsində mənalıdır (#19)',
            COALESCE(v_scope, 'NAMƏLUM');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION enforce_announcement_target_scope() IS
    '#19 — `scope = ALL` elana mağaza hədəfi yazılmasını bloklayır; belə sətir '
    'oxuma tərəfində yanlış əhatəyə çevrilərdi.';

DROP TRIGGER IF EXISTS trg_announcement_target_scope ON announcement_targets;
CREATE TRIGGER trg_announcement_target_scope
    BEFORE INSERT OR UPDATE ON announcement_targets
    FOR EACH ROW EXECUTE FUNCTION enforce_announcement_target_scope();

-- ---------------------------------------------------------------------------
-- 3. performance_reviews (#20) — PERFORMANS QİYMƏTLƏNDİRMƏSİ
-- ---------------------------------------------------------------------------
-- `ratings_json` NİYƏ JSONB, NİYƏ SÜTUN SİYAHISI DEYİL: KPI dəsti Faza 8-də
-- KONFİQURASİYA EDİLƏ BİLƏN olacaq (Root yeni göstərici əlavə edə bilər).
-- Sabit sütun siyahısı hər yeni KPI üçün miqrasiya tələb edərdi və söndürülmüş
-- KPI-nin sütunu əbədi qalardı. Ayrı `performance_review_items` cədvəli də
-- rədd edildi: qiymətləndirmə HƏMİŞƏ tam oxunur/tam yazılır — "üçüncü KPI-ni
-- tapıb yenilə" sorğusu yoxdur (eyni əsaslandırma `migrations/011`
-- `dashboard_layout` sütununda da işlədilib).
CREATE TABLE IF NOT EXISTS performance_reviews (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES license_tenants(tenant_id)
                       ON DELETE CASCADE,

    -- NO ACTION (CASCADE DEYİL): qiymətləndirmə HR sənədidir — işçi qeydi ilə
    -- birlikdə sükutla yox olmamalıdır. İşçilər onsuz da soft delete edilir.
    employee_id    UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,
    reviewer_id    UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,

    -- FORMAT AÇIQ YAZILIR: 'YYYY' (illik), 'YYYY-Qn' (rüblük) və ya 'YYYY-MM'
    -- (aylıq). `monthly_fine_review_batches.review_month` ilə eyni üslubda
    -- regex qoyulur — sərbəst mətn "2026 II rüb" / "Q2-2026" kimi variantlar
    -- yaradar və dövr üzrə müqayisə mümkün olmazdı.
    period         TEXT NOT NULL
                       CHECK (period ~ '^\d{4}(-(0[1-9]|1[0-2]|Q[1-4]))?$'),

    ratings_json   JSONB NOT NULL DEFAULT '{}'::jsonb
                       CHECK (jsonb_typeof(ratings_json) = 'object'),

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: "ən yüksək/ən aşağı qiymət alanlar" hesabatı
    -- konfiqurasiya edilə bilən JSONB açarları üzrə İNDEKSLƏNƏ BİLMƏZ. Çəkili
    -- yekun bir dəfə — yazı anında — hesablanır və sıralama üçün saxlanılır.
    overall_score  NUMERIC(5, 2) CHECK (overall_score IS NULL
                                    OR (overall_score >= 0 AND overall_score <= 100)),
    notes          TEXT,

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Bir işçi + bir dövr = BİR qiymətləndirmə. İki sətir olsaydı "işçinin
    -- 2026-Q1 qiyməti" sualının cavabı qeyri-müəyyən olardı. Düzəliş mövcud
    -- sətri yeniləyir, dəyişiklik izi `audit_logs`-a düşür.
    UNIQUE (tenant_id, employee_id, period),
    -- Öz-özünü qiymətləndirmə vəzifə ayrılığı pozuntusudur (CLAUDE.md §5 ruhu).
    CONSTRAINT chk_review_not_self CHECK (employee_id <> reviewer_id)
);

DROP TRIGGER IF EXISTS trg_performance_reviews_updated ON performance_reviews;
CREATE TRIGGER trg_performance_reviews_updated BEFORE UPDATE ON performance_reviews
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_performance_reviews_employee
    ON performance_reviews (employee_id, period DESC);
CREATE INDEX IF NOT EXISTS idx_performance_reviews_period
    ON performance_reviews (tenant_id, period DESC);

COMMENT ON TABLE performance_reviews IS
    '#20 — Dövri performans qiymətləndirməsi. KPI dəsti Faza 8-də konfiqurasiya '
    'ediləcəyi üçün sxem SABİT göstərici siyahısı yaratmır: qiymətlər JSONB-dədir.';
COMMENT ON COLUMN performance_reviews.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN performance_reviews.tenant_id IS 'Kirayəçi izolyasiyası — RLS açarı.';
COMMENT ON COLUMN performance_reviews.employee_id IS 'Qiymətləndirilən işçi.';
COMMENT ON COLUMN performance_reviews.reviewer_id IS
    'Qiymətləndirən şəxs. Öz-özünü qiymətləndirmə CHECK ilə bloklanır.';
COMMENT ON COLUMN performance_reviews.period IS
    'Dövr: "2026" (illik), "2026-Q1" (rüblük) və ya "2026-03" (aylıq). Sərbəst '
    'mətn qadağandır — əks halda dövrlər arası müqayisə mümkün olmazdı.';
COMMENT ON COLUMN performance_reviews.ratings_json IS
    'KPI kodu → qiymət obyekti. Sütun siyahısı QƏSDƏN sabitlənmir: göstəricilər '
    'Root tərəfindən konfiqurasiya ediləcək (Faza 8).';
COMMENT ON COLUMN performance_reviews.overall_score IS
    'Çəkili yekun bal (0–100). Sıralama/hesabat üçün yazı anında hesablanır — '
    'konfiqurasiya edilə bilən JSONB açarları indekslənə bilmir.';
COMMENT ON COLUMN performance_reviews.notes IS 'Sərbəst mətn rəy (Azərbaycanca).';
COMMENT ON COLUMN performance_reviews.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN performance_reviews.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

-- ---------------------------------------------------------------------------
-- 4. attrition_risk_scores (#21) — İŞDƏN ÇIXMA RİSKİ BALI
-- ---------------------------------------------------------------------------
-- BAL HƏMİŞƏ İZAH EDİLƏ BİLMƏLİDİR: `factors_json` BOŞ OLA BİLMƏZ (CHECK).
-- Səbəb sadədir — "bu işçinin riski 78-dir" cümləsi HR qərarını (söhbət,
-- əvəzedici axtarışı, hətta ayrılıq) əsaslandıra bilməz; əsaslandıran şey
-- "78-in 40-ı son 3 ayda 5 cərimə, 25-i icazə tezliyi..." izahıdır. Qara-qutu
-- bal insan haqqında qərarda qəbuledilməzdir.
--
-- RİSK BANDI (LOW/MEDIUM/HIGH) SAXLANILMIR — NİYƏ: bant həddi Root
-- parametridir (`system_limits`) və dəyişdirilə bilər. Bant sütunda dondurulsa,
-- həddi dəyişəndə köhnə sətirlər KÖHNƏ təsnifatla qalar və eyni ekranda iki
-- fərqli qayda ilə hesablanmış "HIGH" yan-yana görünərdi. Bant OXUMA anında
-- cari həddlə hesablanır.
CREATE TABLE IF NOT EXISTS attrition_risk_scores (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES license_tenants(tenant_id)
                       ON DELETE CASCADE,
    -- CASCADE: bal tam törəmə məlumatdır, işçi qeydi olmadan mənası yoxdur.
    employee_id    UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,

    score          NUMERIC(5, 2) NOT NULL CHECK (score >= 0 AND score <= 100),

    factors_json   JSONB NOT NULL
                       CHECK (jsonb_typeof(factors_json) = 'object'
                          AND factors_json <> '{}'::jsonb),

    -- ƏLAVƏ SÜTUN — ƏSASLANDIRMA: TARİXÇƏ. HR üçün əsas siqnal balın ÖZÜ deyil,
    -- TRENDİ-dir ("bir ayda 40-dan 75-ə qalxıb"). Yalnız cari balı saxlayan
    -- cədvəl bu siqnalı hər hesablamada məhv edərdi. Gün dəqiqliyi seçilib ki,
    -- eyni günün təkrar hesablanması sətirləri çoxaltmasın (UPSERT).
    score_date     DATE NOT NULL DEFAULT CURRENT_DATE,
    calculated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (tenant_id, employee_id, score_date)
);

DROP TRIGGER IF EXISTS trg_attrition_scores_updated ON attrition_risk_scores;
CREATE TRIGGER trg_attrition_scores_updated BEFORE UPDATE ON attrition_risk_scores
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- "Ən riskli işçilər" siyahısı — ən son hesablama tarixi üzrə, bal azalan sırada.
CREATE INDEX IF NOT EXISTS idx_attrition_scores_ranking
    ON attrition_risk_scores (tenant_id, score_date DESC, score DESC);
-- Bir işçinin trendi.
CREATE INDEX IF NOT EXISTS idx_attrition_scores_employee
    ON attrition_risk_scores (employee_id, score_date DESC);

COMMENT ON TABLE attrition_risk_scores IS
    '#21 — İşdən çıxma riski balının GÜNLÜK tarixçəsi. Yalnız cari bal '
    'saxlanılsaydı trend (əsas HR siqnalı) itərdi. Bal mənbələri YALNIZ '
    'KompasOS-un öz datasıdır — 1C-yə bağlantı yoxdur.';
COMMENT ON COLUMN attrition_risk_scores.id IS 'Sətir identifikatoru.';
COMMENT ON COLUMN attrition_risk_scores.tenant_id IS 'Kirayəçi izolyasiyası — RLS açarı.';
COMMENT ON COLUMN attrition_risk_scores.employee_id IS 'Balı hesablanan işçi.';
COMMENT ON COLUMN attrition_risk_scores.score IS
    'Çəkili risk balı (0–100). Çəkilər KODDA DEYİL, `system_limits`-dədir '
    '(kompasos11.md mərkəzi tələbi) — burada yalnız nəticə saxlanılır.';
COMMENT ON COLUMN attrition_risk_scores.factors_json IS
    'Balın PARÇALANMASI: hər amilin xam dəyəri, çəkisi və payı. BOŞ OLA BİLMƏZ — '
    'izah edilə bilməyən bal HR qərarını əsaslandıra bilməz.';
COMMENT ON COLUMN attrition_risk_scores.score_date IS
    'Balın aid olduğu gün. Gün başına bir sətir — təkrar hesablama UPSERT edir.';
COMMENT ON COLUMN attrition_risk_scores.calculated_at IS
    'Faktiki hesablama anı (tz-aware) — gecə işi neçədə işlədiyini göstərir.';
COMMENT ON COLUMN attrition_risk_scores.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN attrition_risk_scores.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

-- ---------------------------------------------------------------------------
-- 5. RLS — fail-closed (SEC-008)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'employee_documents', 'announcements', 'announcement_targets',
        'performance_reviews', 'attrition_risk_scores'
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
-- 6. GRANT — tətbiq rolu
-- ---------------------------------------------------------------------------
-- `DELETE` yalnız İKİ cədvələ verilir:
--   * `announcement_targets` — elanın mağaza siyahısını redaktə etmək sətir
--     silmək deməkdir və bu, sənəd itkisi deyil (elanın özü qalır);
--   * `attrition_risk_scores` — tam törəmə tarixçədir, yenidən hesablana bilər.
-- Qalanları (sənəd, elan mətni, performans qeydi) sübut sətirləridir və
-- soft delete ilə idarə olunur.
--
-- AÇIQ `REVOKE` MƏCBURİDİR: `schema.sql` §28-dəki `ALTER DEFAULT PRIVILEGES`
-- yeni cədvəllərə `DELETE`-i AVTOMATİK verir, yəni dar `GRANT` tək başına
-- heç nə məhdudlaşdırmır (ətraflı izah `migrations/018`-dədir). Bu, ən çox
-- məhz burada əhəmiyyətlidir: `employee_documents` sətri keçmiş növbə
-- təyinatının hüquqi əsasıdır və bir `DELETE` onu izsiz yox edərdi.
DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE ON employee_documents, announcements, '
            'performance_reviews TO %I', v_role
        );
        EXECUTE format(
            'REVOKE DELETE ON employee_documents, announcements, '
            'performance_reviews FROM %I', v_role
        );
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON announcement_targets, '
            'attrition_risk_scores TO %I', v_role
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
-- DİQQƏT: `employee_documents` silinməsi keçmiş növbə təyinatlarının hüquqi
-- əsasını (müqavilə/sanitar kitabça qüvvədə idi) yox edir — bu, sadə struktur
-- geri qaytarma DEYİL, sübut itkisidir. `performance_reviews` isə işçi ilə
-- aparılmış rəsmi söhbətlərin yeganə qeydidir.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_announcement_target_scope ON announcement_targets;
--   DROP FUNCTION IF EXISTS enforce_announcement_target_scope();
--   DROP TABLE IF EXISTS attrition_risk_scores;
--   DROP TABLE IF EXISTS performance_reviews;
--   DROP TABLE IF EXISTS announcement_targets;
--   DROP TABLE IF EXISTS announcements;
--   DROP TABLE IF EXISTS employee_documents;
-- COMMIT;
