-- ===========================================================================
-- MIGRATION 009 — `app_versions` KATALOQU VƏ PRIVATE `app-updates` BUCKET-İ
-- ===========================================================================
-- Tarix : 2026-08-09
-- Səbəb : Auto-Update paylanma qərarının dəqiqləşdirilməsi — "yeni versiya
--         HARA yüklənir və klient onu NECƏ tapır". Miqrasiya 008 kataloqu
--         `app_releases` adı ilə qurmuşdu; tələb sənədi cədvəli `app_versions`,
--         sütunları isə `version_number` / `sha256_hash` / `is_mandatory` /
--         `release_notes` / `release_date` kimi müəyyən edir. Bu miqrasiya
--         008-i ƏVƏZ ETMİR, onu yeni adlara KÖÇÜRÜR (rename) — beləliklə 008
--         artıq icra olunmuş mühitdə də, təmiz bazada da eyni nəticə alınır.
--
-- İdempotentdir — təkrar icra təhlükəsizdir. DOWN faylın sonundadır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ RENAME, NİYƏ İKİNCİ CƏDVƏL DEYİL
-- ---------------------------------------------------------------------------
-- İki cədvəl (`app_releases` + `app_versions`) saxlamaq bir gün "hansı
-- doğrudur?" sualını yaradardı: Developer Paneli birinə yazar, klient
-- digərini oxuyar və yenilənmə SÜKUTLA dayanardı — heç bir xəta olmadan,
-- sadəcə "yeni versiya yoxdur" kimi. Tək kataloq bu sinif səhvi struktur
-- olaraq mümkünsüz edir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ BUCKET PRIVATE-DİR
-- ---------------------------------------------------------------------------
-- Public bucket-də fayl URL-i təxmin edilə bilər (`.../app-updates/1.4.0/
-- KompasOS-Setup.exe`) və indeksləşdirilə bilər — quraşdırıcı hər kəsə açıq
-- olardı. Private bucket-də isə endirmə `apikey` başlığı tələb edir: açar
-- yalnız quraşdırılmış `.exe`-nin daxilindədir.
--
-- DİQQƏT — BUNUN NƏ OLMADIĞI: bu, gizlilik qatı DEYİL. `anon` açarı
-- quraşdırıcıdan çıxarıla bilər. Qoruma budur: (1) fayl təsadüfən tapılmır,
-- (2) endirilmiş fayl SHA-256 + Authenticode ilə yoxlanılır (bax
-- `updates/verification.py`) — yəni bucket-ə çıxış ƏLDƏ ETMƏK saxta paket
-- YERİDƏ BİLMƏK demək deyil. Yazma icazəsi isə yalnız `service_role`-dadır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ KÖHNƏ VERSİYALAR SİLİNMİR
-- ---------------------------------------------------------------------------
-- `app_versions`-də sətir, bucket-də isə fayl qalır. Geri qaytarma
-- (`AutoUpdateClient.rollback`) yerli nüsxə ilə işləyir, lakin yerli nüsxə
-- itibsə (disk təmizlənib, PC dəyişib) yeganə mənbə bucket-dir. Onlarla
-- meqabayt saxlamaq bir filialın günlük dayanmasından ucuzdur.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 1. Kataloq: `app_releases` → `app_versions` (və ya sıfırdan yaratma)
-- ---------------------------------------------------------------------------
-- SXEM ADI SABİT YAZILMIR: `to_regclass('app_versions')` axtarış yoluna görə
-- həll olunur. `'kompasos.app_versions'` yazılsaydı, sxem adı fərqli olan
-- quraşdırma (test sxemi, çox-sxemli instansiya) HƏMİŞƏ `NULL` alar və
-- miqrasiya cədvəli təkrar yaratmağa çalışardı.
DO $$
DECLARE
    v_stray_rows BIGINT;
BEGIN
    IF to_regclass('app_versions') IS NOT NULL THEN
        -- ------------------------------------------------------------------
        -- TƏKRAR İCRADAN QALAN ARTIQ CƏDVƏL
        -- ------------------------------------------------------------------
        -- 008 `app_releases`-i `IF NOT EXISTS` ilə yaradır. Bütün dəst İKİNCİ
        -- dəfə tətbiq olunanda `app_versions` artıq mövcud olur, yəni aşağıdakı
        -- addəyişmə ATLANIR — nəticədə 008-in yenidən yaratdığı BOŞ
        -- `app_releases` sxemdə qalır və iki eyni məzmunlu kataloq görünür.
        -- DB-1 FAZA 4-ün idempotentlik təkrarı bunu aşkarladı (87 → 88 cədvəl).
        --
        -- BOŞ olduğu halda silinir: bu, məlumat itkisi deyil, 009-un ÖZÜNÜN
        -- etməli olduğu addəyişmənin tamamlanmasıdır. Sətir varsa TOXUNULMUR —
        -- kimsə ora yazıbsa, qərar insanındır.
        IF to_regclass('app_releases') IS NOT NULL THEN
            EXECUTE 'SELECT count(*) FROM app_releases' INTO v_stray_rows;
            IF v_stray_rows = 0 THEN
                DROP TABLE app_releases;
                RAISE NOTICE 'Təkrar icradan qalan boş `app_releases` silindi.';
            ELSE
                RAISE WARNING
                    '`app_releases` cədvəlində % sətir var və `app_versions` da '
                    'mövcuddur — hansının doğru olduğuna ƏL İLƏ qərar verin.',
                    v_stray_rows;
            END IF;
        END IF;
        RAISE NOTICE '`app_versions` artıq mövcuddur — köçürmə atlandı.';
    ELSIF to_regclass('app_releases') IS NOT NULL THEN
        ALTER TABLE app_releases RENAME TO app_versions;
        RAISE NOTICE '`app_releases` → `app_versions` adı dəyişdirildi.';
    ELSE
        CREATE TABLE app_versions (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            version      TEXT NOT NULL,
            channel      TEXT NOT NULL DEFAULT 'STABLE'
                             CHECK (channel IN ('STABLE', 'BETA')),
            storage_path TEXT NOT NULL,
            sha256       TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            size_bytes   BIGINT CHECK (size_bytes IS NULL OR size_bytes > 0),
            mandatory_below  TEXT,
            release_notes_az TEXT NOT NULL DEFAULT '',
            published_at TIMESTAMPTZ,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (version, channel)
        );
        RAISE NOTICE '`app_versions` sıfırdan yaradıldı.';
    END IF;
END
$$;

-- Sütun adlarını tələb sənədinin lüğətinə gətiririk. Hər addım ayrıca
-- yoxlanılır ki, qismən tətbiq olunmuş miqrasiya da tamamlana bilsin.
DO $$
DECLARE
    v_pairs CONSTANT TEXT[][] := ARRAY[
        ARRAY['version',          'version_number'],
        ARRAY['sha256',           'sha256_hash'],
        ARRAY['release_notes_az', 'release_notes']
    ];
    v_pair TEXT[];
BEGIN
    FOREACH v_pair SLICE 1 IN ARRAY v_pairs LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'kompasos' AND table_name = 'app_versions'
               AND column_name = v_pair[1]
        ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'kompasos' AND table_name = 'app_versions'
               AND column_name = v_pair[2]
        ) THEN
            EXECUTE format('ALTER TABLE app_versions RENAME COLUMN %I TO %I', v_pair[1], v_pair[2]);
        END IF;
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. Tələb sənədindəki yeni sütunlar
-- ---------------------------------------------------------------------------
ALTER TABLE app_versions
    ADD COLUMN IF NOT EXISTS release_date DATE NOT NULL DEFAULT CURRENT_DATE,
    ADD COLUMN IF NOT EXISTS is_mandatory BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON TABLE app_versions IS
    'Buraxılış kataloqu (bölmə 1, 7). Ayrıca update serveri/CDN YOXDUR — '
    'quraşdırıcı `app-updates` bucket-ində, metadata isə buradadır. '
    'Bütün tenant-lar EYNİ bu cədvəli oxuyur (pull model). Yazma: service_role.';
COMMENT ON COLUMN app_versions.version_number IS
    'Semantik versiya, məs. "1.4.0". Klient öz versiyası ilə müqayisə edir.';
COMMENT ON COLUMN app_versions.storage_path IS
    'Bucket-daxili açar, məs. "1.4.0/KompasOS-Setup.exe".';
COMMENT ON COLUMN app_versions.sha256_hash IS
    'Endirilən faylın gözlənilən SHA-256-sı. Uyğun gəlmirsə fayl SİLİNİR və '
    'yenilənmə tətbiq EDİLMİR (sertifikatsız hash-əsaslı doğrulama qərarı).';
COMMENT ON COLUMN app_versions.is_mandatory IS
    'Developer Panelindəki "Məcburi Yeniləmədir" checkbox-u — bu buraxılışdan '
    'KÖHNƏ bütün quraşdırmalar üçün məcburi. Daha dar hədəf üçün '
    '`mandatory_below` istifadə olunur (yalnız ondan köhnələr).';
COMMENT ON COLUMN app_versions.mandatory_below IS
    'Məcburiliyin dar variantı: yalnız bu versiyadan köhnə quraşdırmalar. '
    'NULL + is_mandatory = FALSE → yenilənmə isteğe bağlıdır.';
COMMENT ON COLUMN app_versions.published_at IS
    'NULL olduqda buraxılış klientlərə GÖRÜNMÜR — hazırlıq mərhələsi.';
COMMENT ON COLUMN app_versions.release_date IS
    'Buraxılış tarixi (insan üçün). Sıralama `published_at` ilə aparılır — '
    'o, dəqiq AN-dır və eyni gün iki buraxılış olduqda fərqi saxlayır.';

DROP INDEX IF EXISTS idx_releases_channel_published;
CREATE INDEX IF NOT EXISTS idx_app_versions_channel_published
    ON app_versions (channel, published_at DESC)
 WHERE published_at IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 3. RLS — hamı OXUYUR, heç kim YAZMIR (service_role RLS-dən azaddır)
-- ---------------------------------------------------------------------------
-- Versiya nömrəsi həssas məlumat deyil, ona görə oxumaq üçün `anon` kifayətdir
-- və tenant konteksti TƏLƏB OLUNMUR (kataloq tenant-a aid deyil — buraxılış
-- hamı üçün eynidir). YAZMA isə kritikdir: kataloqa sətir əlavə edə bilən
-- tərəf bütün quraşdırmalara paket təklif edərdi. `INSERT`/`UPDATE`/`DELETE`
-- üçün siyasət QƏSDƏN yaradılmır — RLS-də siyasəti olmayan əməliyyat qadağandır.
ALTER TABLE app_versions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS everyone_reads_releases ON app_versions;
DROP POLICY IF EXISTS everyone_reads_app_versions ON app_versions;
CREATE POLICY everyone_reads_app_versions ON app_versions
    FOR SELECT
    USING (published_at IS NOT NULL);

DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        RAISE NOTICE 'Rol "%" yoxdur — GRANT/REVOKE atlandı.', v_role;
        RETURN;
    END IF;
    EXECUTE format('GRANT SELECT ON app_versions TO %I', v_role);
    EXECUTE format('REVOKE INSERT, UPDATE, DELETE ON app_versions FROM %I', v_role);
END
$$;

-- ---------------------------------------------------------------------------
-- 4. Supabase Storage: `app-updates` bucket-i (PRIVATE)
-- ---------------------------------------------------------------------------
-- `storage` sxeması yalnız Supabase-də mövcuddur. Yerli/özəl PostgreSQL-də
-- (bölmə 2 — "Hybrid DB Switcher" özəl server rejimi) bu blok sükutla
-- atlanır, çünki orada Storage ümumiyyətlə yoxdur və miqrasiyanın bütövlükdə
-- uğursuz olması bütün digər dəyişiklikləri də geri qaytarardı.
DO $$
BEGIN
    IF to_regclass('storage.buckets') IS NULL THEN
        RAISE NOTICE 'storage.buckets yoxdur (Supabase deyil) — bucket qurulmadı.';
        RETURN;
    END IF;

    INSERT INTO storage.buckets (id, name, public)
         VALUES ('app-updates', 'app-updates', FALSE)
    ON CONFLICT (id) DO UPDATE SET public = FALSE;

    -- Endirmə üçün oxuma icazəsi: `anon` açarı ilə MÜMKÜNDÜR, imzasız public
    -- link ilə DEYİL. Yükləmə (INSERT/UPDATE/DELETE) üçün siyasət
    -- yaradılmır → yalnız `service_role` yazır, yəni yalnız Developer Paneli.
    DROP POLICY IF EXISTS clients_read_app_updates ON storage.objects;
    CREATE POLICY clients_read_app_updates ON storage.objects
        FOR SELECT
        TO anon, authenticated
        USING (bucket_id = 'app-updates');

    RAISE NOTICE '`app-updates` bucket-i hazırdır (private, yalnız oxuma siyasəti).';
EXCEPTION WHEN insufficient_privilege THEN
    -- `storage.objects` üzərində siyasət yaratmaq üçün icazə hər Supabase
    -- rolunda yoxdur. Bu, miqrasiyanın QALANINI geri qaytarmamalıdır: kataloq
    -- dəyişiklikləri müstəqildir və onlarsız yenilənmə ümumiyyətlə işləməz.
    -- Bucket-i Supabase UI-dan əl ilə yaratmaq bir dəqiqəlik işdir.
    RAISE WARNING
        'storage.objects üçün icazə yoxdur — `app-updates` bucket-ini Supabase '
        'UI-dan PRIVATE olaraq yaradın və anon/authenticated üçün SELECT '
        'siyasəti əlavə edin. Kataloq dəyişiklikləri tətbiq olundu.';
END
$$;

COMMIT;

-- ===========================================================================
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ===========================================================================
-- DİQQƏT: adları geri qaytarmaq klienti (`updates/catalog.py`) SINDIRIR —
-- kataloq oxunmaz olar və yenilənmə SÜKUTLA dayanar (klient "yeni buraxılış
-- yoxdur" halını normal sayır). Geri qaytarma yalnız kod da geri alınarsa
-- mənalıdır.
--
-- BEGIN;
--   DROP POLICY IF EXISTS clients_read_app_updates ON storage.objects;
--   DELETE FROM storage.buckets WHERE id = 'app-updates';  -- fayllar əvvəlcə silinməlidir
--   DROP POLICY IF EXISTS everyone_reads_app_versions ON app_versions;
--   DROP INDEX IF EXISTS idx_app_versions_channel_published;
--   ALTER TABLE app_versions DROP COLUMN IF EXISTS is_mandatory;
--   ALTER TABLE app_versions DROP COLUMN IF EXISTS release_date;
--   ALTER TABLE app_versions RENAME COLUMN release_notes TO release_notes_az;
--   ALTER TABLE app_versions RENAME COLUMN sha256_hash TO sha256;
--   ALTER TABLE app_versions RENAME COLUMN version_number TO version;
--   ALTER TABLE app_versions RENAME TO app_releases;
-- COMMIT;
