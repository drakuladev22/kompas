-- ===========================================================================
-- 045 — NAHAR / ÇAY FASİLƏSİ: ROOT PARAMETRLƏRİ VƏ GÜNDƏLİK SAYĞAC
-- ===========================================================================
-- Tarix : 2026-08-14
-- Səbəb : nahar.md dörd YENİ ROOT parametri tələb edir — Nahar və Çay
--         fasilələrinin HƏM müddəti (dəqiqə), HƏM DƏ gündəlik say-həddi —
--         və onların istifadəsini izləyən gündəlik sayğac.
--
-- İdempotentdir. DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- QIRMIZI XƏTT: MÖVCUD AXIN TOXUNULMUR
-- ---------------------------------------------------------------------------
--   * STEP1/STEP2/STEP3 axını (`leave_requests`) DƏYİŞMİR — nə sütun, nə
--     CHECK, nə trigger.
--   * `leave_types` KATALOQU HR_Admin-in idarəsində QALIR
--     (`can_manage_leave_types`): ad, müddət, aktivlik — hamısı əvvəlki kimi.
--     Bu miqrasiya ora YALNIZ BİR sütun əlavə edir (`break_kind`) və o sütun
--     HR ekranından yazılmır (bax aşağıdakı «İKİ QAT, İKİ SAHİB» bölməsi).
--   * PENALTY LOGIC (`Delay`/`Total` düsturu) DƏYİŞMİR — aşağıdakı müddət
--     parametrləri həmin düstura QOŞULMUR (bax «MÜDDƏT NİYƏ İKİ YERDƏ»).
--
-- ---------------------------------------------------------------------------
-- NAHAR/ÇAY NİYƏ `system_limits`-DƏ, KATALOQDA YOX
-- ---------------------------------------------------------------------------
-- İcazə Növləri Kataloqu HR_Admin-in SƏRBƏST genişləndirdiyi siyahıdır —
-- "Bank işi", "Şəxsi iş" oraya istənilən vaxt əlavə olunur və heç bir
-- struktur məna daşımır. Nahar və Çay isə nahar.md-nin açıq tələbinə görə
-- sistemin TƏMƏLİNDƏ olan, hər kirayəçidə MÜTLƏQ mövcud və YALNIZ Root-un
-- (`can_manage_system_limits`, mövcud hardlock qaydasına görə CEO-ya belə
-- verilmir) dəyişdiyi parametrlərdir. Onları kataloqa yazsaydıq, HR_Admin
-- nahar say-həddini özü dəyişə bilərdi — yəni "yalnız Root" tələbi sükutla
-- pozulardı.
--
-- ---------------------------------------------------------------------------
-- İKİ QAT, İKİ SAHİB — `break_kind` SÜTUNU NİYƏ LAZIMDIR
-- ---------------------------------------------------------------------------
-- STEP1 işçidən `leave_type_id` alır (mövcud imza). Sistem isə "bu seçim
-- NAHARDIRMI, ÇAYDIRMI?" sualına cavab verməlidir ki, doğru sayğacı artırsın.
-- Üç variant nəzərdən keçirildi:
--
--   (a) ADA GÖRƏ tanımaq (`name_az = 'Nahar Fasiləsi'`) — RƏDD EDİLDİ: HR
--       kataloq ekranından adı dəyişən kimi bağ qırılar və sayğac SÜKUTLA
--       dayanardı. Səssiz uğursuzluq ən pis formadır.
--   (b) AYRICA `system_break_types(tenant_id, break_kind, leave_type_id)`
--       cədvəli — RƏDD EDİLDİ: 1:1 bağ üçün ayrıca cədvəl hər oxuda əlavə
--       JOIN və "sətir yoxdursa nə olur?" sualı deməkdir.
--   (c) `leave_types.break_kind` sütunu — SEÇİLDİ. Bağ sətrin ÖZÜNDƏDİR,
--       ada bağlı deyil (HR adı «Nahar» → «Nahar fasiləsi (45 dəq)» edə
--       bilər, bağ qalır) və oxu əlavə JOIN tələb etmir.
--
-- SÜTUN HR-A AÇILMIR: `PostgresLeaveTypeRepository.save()` UPSERT-i yalnız
-- `default_duration_minutes` və `is_active` yazır — `break_kind` EXCLUDED
-- siyahısında YOXDUR, yəni HR sətri redaktə edəndə tip toxunulmaz qalır.
-- Bu, "iki qat, iki sahib" qaydasıdır: sətrin MƏZMUNU HR-ındır, sətrin
-- STRUKTUR ROLU Root-undur.
--
-- ---------------------------------------------------------------------------
-- MÜDDƏT NİYƏ İKİ YERDƏ GÖRÜNÜR VƏ BU NİYƏ ZİDDİYYƏT DEYİL
-- ---------------------------------------------------------------------------
-- `leave_types.default_duration_minutes` BR-001 GÜZƏŞT mənbəyidir — o,
-- `Delay`/`Total` hesablamasına DAXİL OLUR (`LeaveAllowancePolicy`).
-- `LUNCH_BREAK_DURATION_MINUTES` isə nahar.md-nin açıq tələbinə görə
-- MƏLUMATLANDIRICI göstəricidir və düstura HEÇ VAXT qoşulmur.
--
-- İki ədədin AYRI qalması qəsdidir: müəssisə "nahar 45 dəqiqədir" elan edib,
-- eyni zamanda cərimədən əvvəl 60 dəqiqəlik güzəşt saxlaya bilər. Onları
-- birləşdirsəydik, Root informativ mətni dəyişəndə CƏRİMƏ düsturu da
-- dəyişərdi — yəni nahar.md-nin qadağan etdiyi şey baş verərdi.
--
-- Buna baxmayaraq DEFOLTLAR ÜST-ÜSTƏ DÜŞÜR (nahar 60/60, çay 15/15): ilk
-- gündən bir-birini təkzib edən iki rəqəm göstərmək istifadəçidə "hansı
-- doğrudur?" sualı yaradardı. Fərqləndirmək AÇIQ Root qərarı olmalıdır,
-- defolt vəziyyət yox. (nahar.md 45 dəq təklif edir, lakin mövcud seed
-- «Nahar Fasiləsi» = 60 dəqiqədir və uyğunluq daha vacibdir — həmin sətir
-- YENİDƏN YAZILMIR.)
--
-- ---------------------------------------------------------------------------
-- SAY-HƏDDİ BLOKLAMIR (nahar.md §MƏNTİQ, bənd 2 — açıq göstəriş)
-- ---------------------------------------------------------------------------
-- Hədd aşılanda əməliyyat DAVAM EDİR, yalnız xəbərdarlıq göstərilir. Ona görə
-- `daily_break_usage`-də nə `CHECK (count_used <= limit)`, nə də bloklayıcı
-- trigger var — DB səviyyəsində hədd YOXDUR, çünki hədd bir SİYASƏTDİR və
-- siyasətin yeri `system_limits`-dir. Bu, mövcud `MonthlyLeaveUsage` ilə eyni
-- fəlsəfədir (bax `use_cases/leave_verification.py`: "NİYƏ BLOKLAMIR").
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. `leave_types.break_kind` — SİSTEM FASİLƏSİNİN STRUKTUR NİŞANI
-- ---------------------------------------------------------------------------
ALTER TABLE leave_types
    ADD COLUMN IF NOT EXISTS break_kind TEXT;

-- CHECK ayrıca əlavə olunur ki, sütun artıq mövcud olan bazada da qoyulsun
-- (`ADD COLUMN IF NOT EXISTS` mövcud sütuna CHECK əlavə etmir).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'leave_types_break_kind_check'
           AND connamespace = current_schema()::regnamespace
    ) THEN
        ALTER TABLE leave_types
            ADD CONSTRAINT leave_types_break_kind_check
            CHECK (break_kind IS NULL OR break_kind IN ('LUNCH', 'TEA'));
    END IF;
END
$$;

-- HƏR KİRAYƏÇİDƏ ƏN ÇOXU BİR NAHAR VƏ BİR ÇAY: qismən unikal indeks.
-- Tam UNIQUE (tenant_id, break_kind) İŞLƏMƏZDİ — `NULL` dəyərlər PostgreSQL-də
-- bir-birinə bərabər sayılmır, lakin sütunu `NOT NULL` etmək bütün ADİ icazə
-- növlərinə süni bir tip yazmağı tələb edərdi. Qismən indeks tam olaraq lazım
-- olan qaydanı ifadə edir: "nişanlanmış sətirlər arasında təkrar olmasın".
CREATE UNIQUE INDEX IF NOT EXISTS ux_leave_types_break_kind
    ON leave_types (tenant_id, break_kind)
    WHERE break_kind IS NOT NULL;

COMMENT ON COLUMN leave_types.break_kind IS
    'Sistem fasiləsinin növü: LUNCH (Nahar) / TEA (Çay) / NULL (adi icazə '
    'növü). Bu sütun HR_Admin ekranından YAZILMIR — `can_manage_leave_types` '
    'sətrin adını və müddətini idarə edir, struktur rolunu isə Root '
    '(migrations/045). Sütun `daily_break_usage` sayğacının hansı sətrə '
    'aid olduğunu təyin edir; NULL olan növ sayğaca ümumiyyətlə düşmür.';

-- ---------------------------------------------------------------------------
-- 2. MÖVCUD KİRAYƏÇİLƏRDƏ NAHAR/ÇAY SƏTİRLƏRİ
-- ---------------------------------------------------------------------------
-- 2a. Artıq mövcud olan «Nahar Fasiləsi» sətri NİŞANLANIR — YENİSİ
-- YARADILMIR. Səbəb: `schema.sql` §24 onu hər kirayəçiyə 60 dəqiqə ilə seed
-- edir və həmin sətrə keçmiş `leave_requests` istinad edir. Yeni sətir
-- yaratsaydıq, kataloqda eyni adlı iki qeyd görünərdi (UNIQUE onsuz da
-- buraxmazdı) və ya tarixi qeydlər «köhnə» sətirdə qalıb sayğacdan kənarda
-- düşərdi.
--
-- `NOT EXISTS` şərti: kirayəçidə artıq LUNCH nişanlı sətir varsa (miqrasiya
-- təkrar icra olunur) heç nə dəyişmir — idempotentlik.
UPDATE leave_types lt
   SET break_kind = 'LUNCH'
 WHERE lt.break_kind IS NULL
   AND lt.name_az = 'Nahar Fasiləsi'
   AND NOT EXISTS (
        SELECT 1 FROM leave_types other
         WHERE other.tenant_id = lt.tenant_id AND other.break_kind = 'LUNCH'
   );

UPDATE leave_types lt
   SET break_kind = 'TEA'
 WHERE lt.break_kind IS NULL
   AND lt.name_az = 'Çay Fasiləsi'
   AND NOT EXISTS (
        SELECT 1 FROM leave_types other
         WHERE other.tenant_id = lt.tenant_id AND other.break_kind = 'TEA'
   );

-- 2b. Çatışan sətirlər yaradılır. «Çay Fasiləsi» sistemdə İLK DƏFƏ yaranır
-- (schema.sql seed-ində yox idi) — 15 dəqiqə, mağaza praktikasındakı qısa
-- fasilə. Nahar sətri isə yalnız adı dəyişdirilmiş/silinmiş kirayəçilərdə
-- yaranır.
INSERT INTO leave_types (tenant_id, name_az, default_duration_minutes, break_kind)
SELECT t.tenant_id, v.name_az, v.minutes, v.break_kind
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('Nahar Fasiləsi', 60, 'LUNCH'),
    ('Çay Fasiləsi',   15, 'TEA')
 ) AS v(name_az, minutes, break_kind)
 WHERE NOT EXISTS (
        SELECT 1 FROM leave_types l
         WHERE l.tenant_id = t.tenant_id AND l.break_kind = v.break_kind
   )
ON CONFLICT (tenant_id, name_az) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. `daily_break_usage` — GÜNDƏLİK SAYĞAC
-- ---------------------------------------------------------------------------
-- NİYƏ AYRICA CƏDVƏL, NİYƏ `leave_requests` ÜZƏRİNDƏN COUNT DEYİL:
-- Aqreqasiya BUGÜN doğru cavab verərdi, sabah yox — HR sətrin `break_kind`
-- nişanını dəyişdirsə (məs. ayrı bir «Nahar (uzun)» növü yaradıb köhnəni
-- deaktiv etsə), KEÇMİŞ günlərin sayğacı da geriyə dönük dəyişərdi. Sayğac
-- isə işçiyə göstərilmiş və HR-in gördüyü bir FAKTdır: "3-cü çay fasiləsi"
-- xəbərdarlığı verilibsə, o, sonradan 2-yə çevrilməməlidir.
--
-- İkinci səbəb performansdır: işçi ekranı hər STEP1-də göstərici oxuyur və
-- `leave_requests` × `leave_types` JOIN-i gün ərzində onlarla dəfə işləyərdi.
CREATE TABLE IF NOT EXISTS daily_break_usage (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES license_tenants(tenant_id)
                     ON DELETE CASCADE,
    -- CASCADE: sayğac işçi sətrinin törəməsidir. İşçilər praktikada fiziki
    -- silinmir (`employees.is_active` soft delete), ona görə bu yol yalnız
    -- kirayəçi tam ləğv olunanda işə düşür.
    employee_id  UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,

    -- `date` PostgreSQL-də tip adıdır; sütunu `usage_date` adlandırmaq hər
    -- sorğuda dırnaq işarəsi ehtiyacını aradan qaldırır.
    usage_date   DATE NOT NULL,

    -- SƏRT `CHECK`: `leave_types.break_kind` ilə EYNİ siyahı. Burada sərtlik
    -- doğrudur (fərqli olaraq `employee_documents.doc_type`-dan): fasilə növü
    -- ETİKET deyil, DAVRANIŞ açarıdır — hər növ öz ROOT parametr cütünə
    -- (müddət + say) bağlıdır və üçüncü növ əlavə etmək onsuz da iki yeni
    -- `SystemLimitKey` deməkdir, yəni miqrasiya hər halda lazımdır.
    break_type   TEXT NOT NULL CHECK (break_type IN ('LUNCH', 'TEA')),

    -- Həmin gün NEÇƏ DƏFƏ başlanıb. Yalnız STEP1 artırır (bax use case).
    -- Yuxarı hədd YOXDUR — say-həddi bloklamır, xəbərdarlıq doğurur.
    count_used   INTEGER NOT NULL DEFAULT 0 CHECK (count_used >= 0),

    -- Sonuncu istifadə anı (tz-aware) — "bu gün 2 dəfə" ifadəsinin YANINDA
    -- "sonuncusu 14:30-da" göstərmək üçün. Sayğacın özü NƏ QƏDƏR sualına,
    -- bu sütun NƏ VAXT sualına cavab verir.
    last_used_at TIMESTAMPTZ,

    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- UPSERT-in hədəfi: bir işçi + bir gün + bir növ = BİR sətir.
    UNIQUE (employee_id, usage_date, break_type)
);

-- HR panelinin "bugün limiti aşanlar" sorğusu kirayəçi + gün üzrə gedir.
CREATE INDEX IF NOT EXISTS ix_daily_break_usage_tenant_date
    ON daily_break_usage (tenant_id, usage_date DESC);

DROP TRIGGER IF EXISTS trg_daily_break_usage_updated ON daily_break_usage;
CREATE TRIGGER trg_daily_break_usage_updated BEFORE UPDATE ON daily_break_usage
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE daily_break_usage IS
    'İşçinin bir gün ərzində Nahar/Çay fasiləsini neçə dəfə başlatdığı '
    '(nahar.md). Sayğac YALNIZ STEP1-də artır və heç bir əməliyyatı '
    'BLOKLAMIR — ROOT say-həddi aşılanda işçi ekranında və HR panelində '
    'xəbərdarlıq göstərilir, axın davam edir (mövcud aylıq-limit naxışı).';
COMMENT ON COLUMN daily_break_usage.usage_date IS
    'Fasilənin başladığı yerli gün. Gecə yarısını keçən fasilə BAŞLANĞIC '
    'gününə yazılır — hədd "gündə neçə dəfə BAŞLADI" sualına aiddir.';
COMMENT ON COLUMN daily_break_usage.break_type IS
    'LUNCH (Nahar) / TEA (Çay) — `leave_types.break_kind` ilə eyni siyahı.';
COMMENT ON COLUMN daily_break_usage.count_used IS
    'Həmin gün başladılmış fasilə sayı. Yuxarı hədd QOYULMUR: hədd siyasətdir '
    've `system_limits`-dədir (LUNCH_BREAK_DAILY_COUNT / TEA_BREAK_DAILY_COUNT).';
COMMENT ON COLUMN daily_break_usage.last_used_at IS
    'Sonuncu başlanğıcın tz-aware anı — "sonuncusu 14:30-da" göstəricisi üçün.';
COMMENT ON COLUMN daily_break_usage.created_at IS 'Yaradılma anı (tz-aware).';
COMMENT ON COLUMN daily_break_usage.updated_at IS 'Sonuncu dəyişiklik anı (trigger).';

-- ---------------------------------------------------------------------------
-- 4. RLS — fail-closed (SEC-008)
-- ---------------------------------------------------------------------------
ALTER TABLE daily_break_usage ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON daily_break_usage;
CREATE POLICY tenant_isolation ON daily_break_usage
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- 5. GRANT — tətbiq rolu
-- ---------------------------------------------------------------------------
-- `DELETE` VERİLMİR. Sayğac törəmə görünsə də, bərpa EDİLƏ BİLMƏZ: onu
-- `leave_requests`-dən yenidən hesablamaq üçün həmin günün `break_kind`
-- nişanlarının dəyişməmiş olması lazımdır (bax §3 başlığı). Bir `DELETE`
-- işçiyə göstərilmiş xəbərdarlığın əsasını izsiz yox edərdi.
--
-- AÇIQ `REVOKE` MƏCBURİDİR: `schema.sql` §28-dəki `ALTER DEFAULT PRIVILEGES`
-- yeni cədvəllərə `DELETE`-i AVTOMATİK verir, yəni dar `GRANT` tək başına
-- heç nə məhdudlaşdırmır (ətraflı izah `migrations/018`-dədir).
DO $$
DECLARE
    v_role TEXT := 'kompasos_app';
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        EXECUTE format('GRANT SELECT, INSERT, UPDATE ON daily_break_usage TO %I', v_role);
        EXECUTE format('REVOKE DELETE ON daily_break_usage FROM %I', v_role);
    ELSE
        RAISE NOTICE 'Rol "%" yoxdur — GRANT atlandı.', v_role;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 6. ROOT PARAMETRLƏRİ — MÖVCUD KİRAYƏÇİLƏR
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada (CI iki dəfə tətbiq edir) Root-un
-- artıq dəyişdirdiyi dəyər ÜSTÜNDƏN YAZILMIR (039–044 ilə eyni qayda).
--
-- `min_value`/`max_value` ƏSASLANDIRMASI
-- ......................................
-- MÜDDƏT (hər iki fasilə): min = 1 — 0 dəqiqəlik fasilə anlayış olaraq
--   mövcud deyil və ekranda "Nahar fasiləniz: 0 dəqiqə" mənasız mətn verərdi.
--   max = 480 (8 saat) — bir tam növbənin uzunluğu; bundan uzun "fasilə"
--   artıq fasilə deyil, növbənin özüdür. Tavan yalnız yazı səhvini (məs.
--   4500) kəsir, real siyasəti məhdudlaşdırmır.
-- SAY (hər iki fasilə): min = 0 — bu, AÇIQ şəkildə "bu kirayəçidə həmin
--   fasilə nəzərdə tutulmayıb" deməkdir; həmin halda hər istifadə dərhal
--   xəbərdarlıq doğurur, LAKİN yenə bloklanmır. Söndürmənin oxunan yolu
--   məhz budur. max = 10 — bir növbədə praktik tavan; daha böyük dəyər
--   həddi sükutla söndürərdi, halbuki söndürmənin açıq yolu 0-dır.
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('LUNCH_BREAK_DURATION_MINUTES', '60', 'INTEGER', '1', '480',
     'Nahar fasiləsinin müddəti (dəqiqə). YALNIZ MƏLUMATLANDIRICIDIR — işçi '
     'ekranında «Nahar fasiləniz: 60 dəqiqə» kimi göstərilir və gecikmə/'
     'cərimə düsturuna (Delay/Total) QOŞULMUR. Cərimə güzəşti mövcud qaydada '
     '«İcazə Növləri» kataloqundakı müddətdən gəlir (BR-001)'),
    ('LUNCH_BREAK_DAILY_COUNT', '1', 'INTEGER', '0', '10',
     'Nahar fasiləsinin gündə neçə dəfə nəzərdə tutulduğu. Hədd aşılanda '
     'əməliyyat BLOKLANMIR — işçi ekranında və HR panelində «2-ci nahar '
     'fasiləsi (limit: 1)» xəbərdarlığı göstərilir. 0 = bu kirayəçidə nahar '
     'fasiləsi nəzərdə tutulmayıb (hər istifadə xəbərdarlıq doğurur)'),
    ('TEA_BREAK_DURATION_MINUTES', '15', 'INTEGER', '1', '480',
     'Çay fasiləsinin müddəti (dəqiqə). Nahar müddəti ilə eyni qayda: yalnız '
     'məlumatlandırıcıdır, cərimə düsturuna təsir etmir'),
    ('TEA_BREAK_DAILY_COUNT', '2', 'INTEGER', '0', '10',
     'Çay fasiləsinin gündə neçə dəfə nəzərdə tutulduğu. Aşılma bloklamır, '
     'yalnız «3-cü çay fasiləsi (limit: 2)» xəbərdarlığı doğurur')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 7. YENİ KİRAYƏÇİLƏR — LİMİTLƏR VƏ FASİLƏ SƏTİRLƏRİ
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/036/039–044-dəki naxış təkrarlanır.
--
-- SIRA MƏSƏLƏSİ — NİYƏ FASİLƏ SƏTİRLƏRİ DƏ BURADADIR:
-- Bu trigger `license_tenants`-ə INSERT anında işləyir, `seed_tenant_defaults()`
-- isə quraşdırma sihirbazı tərəfindən DAHA SONRA çağırılır. Yəni trigger
-- «Nahar Fasiləsi» sətrini BİRİNCİ yaradır (nişanı ilə birlikdə), sihirbazın
-- öz `INSERT`-i isə `ON CONFLICT DO NOTHING` ilə həmin sətrə dəyib heç nə
-- etmir — nişan qorunur. Əks sıra (əvvəlcə sihirbaz, sonra nişanlama)
-- trigger-dən idarə edilə bilməzdi, çünki trigger sətir hələ yaranmamış
-- işləyir.
CREATE OR REPLACE FUNCTION seed_break_parameters_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'LUNCH_BREAK_DURATION_MINUTES', '60', 'INTEGER', '1', '480',
         'Nahar fasiləsinin müddəti (dəqiqə) — yalnız məlumatlandırıcı'),
        (NEW.tenant_id, 'LUNCH_BREAK_DAILY_COUNT', '1', 'INTEGER', '0', '10',
         'Nahar fasiləsi gündə neçə dəfə — aşılma bloklamır, xəbərdarlıq edir'),
        (NEW.tenant_id, 'TEA_BREAK_DURATION_MINUTES', '15', 'INTEGER', '1', '480',
         'Çay fasiləsinin müddəti (dəqiqə) — yalnız məlumatlandırıcı'),
        (NEW.tenant_id, 'TEA_BREAK_DAILY_COUNT', '2', 'INTEGER', '0', '10',
         'Çay fasiləsi gündə neçə dəfə — aşılma bloklamır, xəbərdarlıq edir')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;

    INSERT INTO leave_types (tenant_id, name_az, default_duration_minutes, break_kind)
    VALUES
        (NEW.tenant_id, 'Nahar Fasiləsi', 60, 'LUNCH'),
        (NEW.tenant_id, 'Çay Fasiləsi',   15, 'TEA')
    ON CONFLICT (tenant_id, name_az) DO NOTHING;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_break_parameters_for_new_tenant() IS
    'Yeni kirayəçiyə Nahar/Çay fasiləsinin dörd ROOT parametrini və iki '
    'nişanlanmış icazə növü sətrini əlavə edir (migrations/045). '
    '`seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_break_parameters ON license_tenants;
CREATE TRIGGER trg_seed_break_parameters
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_break_parameters_for_new_tenant();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: `daily_break_usage` silinməsi işçiyə göstərilmiş xəbərdarlıqların
-- əsasını yox edir və bərpa edilə bilmir (bax §3 başlığı). `leave_types`
-- sətirlərinə TOXUNULMUR — onlara keçmiş `leave_requests` istinad edir;
-- yalnız `break_kind` nişanı təmizlənir.
--
-- Sətirlər silinsə, sistem İŞLƏMƏYƏ DAVAM EDİR: kod `DEFAULT_LIMITS`
-- fallback-larına düşür (60/1/15/2), nişanı olmayan icazə növü isə sadəcə
-- sayğaca düşmür.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_break_parameters ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_break_parameters_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key IN (
--       'LUNCH_BREAK_DURATION_MINUTES', 'LUNCH_BREAK_DAILY_COUNT',
--       'TEA_BREAK_DURATION_MINUTES',   'TEA_BREAK_DAILY_COUNT');
--   DROP TABLE IF EXISTS daily_break_usage;
--   DROP INDEX IF EXISTS ux_leave_types_break_kind;
--   ALTER TABLE leave_types DROP CONSTRAINT IF EXISTS leave_types_break_kind_check;
--   ALTER TABLE leave_types DROP COLUMN IF EXISTS break_kind;
-- COMMIT;
