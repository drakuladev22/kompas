-- ===========================================================================
-- 092 — `license_tenants.service_tier` (Faza 9.2) + `app_version_tenant_
--        targets` (Faza 11.1 Canary + Faza 11.2 Versiya Geri-Qaytarma)
-- ===========================================================================
-- Tarix : 2026-08-25
-- Mənbə : `v2backlog.md` FAZA 1.
--
-- ---------------------------------------------------------------------------
-- ADLANDIRMA DÜZƏLİŞİ #1 — SƏNƏD "`tenants` cədvəlinə" DEYİR
-- ---------------------------------------------------------------------------
-- Faktiki cədvəl adı `license_tenants`-dır (`tenants` adlı cədvəl mövcud
-- DEYİL) — komanda rəhbəri ilə təsdiqləndi (`service_tier` üçün 0 nəticə,
-- yəni sütun HƏQİQƏTƏN yenidir).
--
-- ---------------------------------------------------------------------------
-- ADLANDIRMA DÜZƏLİŞİ #2 (İLK CƏHDDƏ SƏHV EDİLİB) — `app_releases` YOX,
-- `app_versions`
-- ---------------------------------------------------------------------------
-- Bu miqrasiyanın İLK versiyası `app_releases(id)`-ə FK qoyurdu və icraçı
-- «relation "app_releases" does not exist» xətası verdi. Səbəb SİLİNMƏ
-- DEYİL, ADDƏYİŞMƏDİR: migration 008 kataloqu `app_releases` adı ilə
-- yaradır, migration 009 isə onu DƏRHAL `app_versions`-a köçürür
-- (`ALTER TABLE app_releases RENAME TO app_versions`, 009:88) — tələb
-- sənədinin lüğətinə uyğunlaşdırmaq üçün. Cədvəl mövcuddur, sadəcə fərqli
-- addadır; `grep "DROP TABLE"` bunu tapmadı, çünki addəyişmə `RENAME TO`-dur,
-- silmə deyil.
--
-- NƏTİCƏ: bu miqrasiya `app_versions(id)`-ə FK qoyur, cədvəlin öz adı da
-- `app_version_tenant_targets`-dir (köhnə layihə `app_release_tenant_
-- targets` idi) — köhnə adı saxlamaq növbəti oxuyucunu EYNİ addəyişmə
-- tələsinə salardı («niyə `app_release_*` amma FK `app_versions`-a gedir?»).
--
-- ---------------------------------------------------------------------------
-- NİYƏ İKİ FUNKSİYA BİR MİQRASİYADA
-- ---------------------------------------------------------------------------
-- Hər ikisi VENDOR-tərəfi (Developer Panel / `src/developer_panel/`) —
-- "Vendor Konsolu" adı sənəddə keçir, kod bazasında bu adla heç nə yoxdur,
-- funksiya HƏQİQƏTƏN `src/developer_panel/ui.py`+`console.py`-dədir (komanda
-- rəhbərinin təsdiqi). Sxem baxımından fərq yoxdur — mövcud `app_versions`
-- ARTIQ eyni RLS naxışını daşıyır (SELECT-only tenant, YAZI yalnız
-- `service_role`), bu miqrasiya ONU TƏKRARLAYIR.
--
-- ---------------------------------------------------------------------------
-- `app_version_tenant_targets` NİYƏ İKİ FUNKSİYANI (11.1 + 11.2) BİRLƏŞDİRİR
-- ---------------------------------------------------------------------------
-- Canary ("bu versiyanı YALNIZ seçilmiş tenant-lara göndər") və rollback
-- ("əvvəlki versiyaya qaytar") EYNİ sualın CAVABIDIR: "bu tenant HANSI
-- `app_versions` sətrini görsün?". Fərq YALNIZ hədəf versiyanın YENİ, yoxsa
-- KÖHNƏ olmasındadır — sxem səviyyəsində eyni sütunlar kifayət edir. İki
-- ayrı cədvəl EYNİ konsepti (tenant → hədəf buraxılış) TƏKRARLAYARDI.
--
-- `app_versions`-in GENİŞLƏNMƏSİ DEYİL: o, KANAL-səviyyəlidir (STABLE/BETA,
-- HAMISI üçün), bu isə TENANT-səviyyəli İSTİSNADIR. `app_versions`-ə
-- `target_tenant_id` sütunu əlavə etmək onun "hər kanalın bütün tenant-lara
-- aid olduğu" invariantını pozardı və mövcud auto-update sorğularının
-- (kanal üzrə süzgəc) hamısını YENİDƏN yazmağı tələb edərdi.
--
-- ---------------------------------------------------------------------------
-- RLS — `app_versions`-İN NAXIŞI TƏKRARLANIR, `tenant_isolation` DEYİL
-- ---------------------------------------------------------------------------
-- Bu, MÜŞTƏRİ məlumatı DEYİL — VENDOR-un tenant-a hədəflədiyi buraxılış
-- qərarıdır. Standart `tenant_isolation` siyasəti (`USING/WITH CHECK
-- tenant_id = current_tenant_id()`) YAZI hüququnu da AÇARDI, halbuki YAZI
-- YALNIZ vendor-a (Developer Panel, `service_role`) aiddir — `docs/
-- security_decisions.md`-dəki Master Panel `service_role` + RLS qərarı ilə
-- eynidir. Ona görə RLS ENABLE EDİLİR, LAKİN yalnız SELECT siyasəti yazılır
-- (öz tenant_id-sini oxuya bilər) — `app_versions`-in `everyone_reads_
-- app_versions` naxışının EYNİSİ (migrations/009). `service_role` RLS-i
-- BYPASS edir (Supabase-in standart davranışı), ona görə YAZI üçün əlavə
-- siyasət lazım deyil.
--
-- ---------------------------------------------------------------------------
-- TIME-1: TƏTBİQ EDİLMİR — `set_at` yalnız `service_role` (vendor)
-- tərəfindən yazılır, adi kirayəçi bağlantısı BU CƏDVƏLƏ YAZA BİLMİR (yuxarı
-- bax), yəni client-tərəfi vaxt manipulyasiyası riski STRUKTUR olaraq YOXDUR.
--
-- İDEMPOTENT, DOWN BLOKU SONDA. `schema.sql` YENİLƏNMİR (CLAUDE.md §7).
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. `license_tenants.service_tier` — Faza 9.2
-- ---------------------------------------------------------------------------
ALTER TABLE license_tenants
    ADD COLUMN IF NOT EXISTS service_tier TEXT NOT NULL DEFAULT 'ESAS'
        CHECK (service_tier IN ('ESAS', 'TAM'));

COMMENT ON COLUMN license_tenants.service_tier IS
    'Faza 9.2 (v2backlog.md): Xidmət-Səviyyəsi (Tier) Fərqləndirməsi. '
    '"ESAS"/"TAM" — mövcud Feature Toggle sisteminə TİER-ƏSASLI DEFOLT-DƏST '
    'verir (Developer Panel/Vendor Konsolundan Root tənzimləyir). Bu sütun '
    'YALNIZ defolt dəsti təyin edir, FeatureToggles-i ƏVƏZ ETMİR — tenant '
    'daxilində Root hər hansı flag-i AYRICA söndürə/aça bilər (migrations/092).';

-- ---------------------------------------------------------------------------
-- 2. `app_version_tenant_targets` — Faza 11.1 + 11.2
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_version_tenant_targets (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,
    target_version_id UUID NOT NULL REFERENCES app_versions(id) ON DELETE CASCADE,

    -- Sərbəst mətn — canary ("bu qrupa erkən buraxılış") və rollback
    -- ("bu versiyada kritik xəta tapıldı") FƏRQLİ SƏBƏBLƏRDİR, lakin
    -- struktur EYNİDİR (bax fayl başlığı).
    reason            TEXT NOT NULL CHECK (char_length(trim(reason)) >= 5),

    -- NO ACTION: "kim hədəflədi?" konfiqurasiya sətrindən uzun yaşayır.
    set_by            UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,
    set_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- BİR tenant üçün BİR AKTİV hədəf — iki eyni-vaxtlı hədəf ("bu versiyaya
    -- keç" + "o versiyaya qaytar") mənasız ziddiyyət yaradardı.
    UNIQUE (tenant_id)
);

COMMENT ON TABLE app_version_tenant_targets IS
    'Faza 11.1 (Canary) + Faza 11.2 (Versiya Geri-Qaytarma), v2backlog.md: '
    '"bu tenant HANSI `app_versions` sətrini görsün?" sualının CAVABI. Sətir '
    'YOXDURSA tenant öz KANALININ (STABLE/BETA) son nəşrini alır (mövcud '
    'auto-update davranışı DƏYİŞMİR) — sətir YALNIZ İSTİSNA halında yaranır. '
    'Bir cədvəl İKİ funksiyanı örtür: hədəf versiya YENİDİRSƏ canary, '
    'KÖHNƏDİRSƏ rollback — məntiq eynidir. Ad `app_versions`-a uyğunlaşdırılıb '
    '(migrations/009), köhnə `app_releases` DEYİL (migrations/092).';

COMMENT ON COLUMN app_version_tenant_targets.set_by IS
    '`employees.id`-yə istinad edir — Developer Panel/Vendor Konsolu '
    'əməliyyatçısı VENDOR tərəfin öz `employees` sətridir (öz tenant-ı '
    'daxilindəki kimi), MÜŞTƏRİ işçisi DEYİL.';

-- `app_versions`-in NAXIŞI TƏKRARLANIR (bax fayl başlığı) — `tenant_
-- isolation` DEYİL, YALNIZ SELECT.
ALTER TABLE app_version_tenant_targets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_reads_own_target ON app_version_tenant_targets;
CREATE POLICY tenant_reads_own_target ON app_version_tenant_targets
    FOR SELECT
    USING (tenant_id = current_tenant_id());

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- `app_version_tenant_targets` SİLİNSƏ bütün tenant-lar öz KANALININ son
-- nəşrinə qayıdır (data itkisi YOX, YALNIZ İSTİSNALAR itir — bu, hər hansı
-- davam edən canary/rollback razılaşmasını LƏĞV EDƏR, ehtiyatla işlədin).
-- `license_tenants.service_tier` SİLİNSƏ Feature Toggle-in tier-əsaslı
-- defolt-dəst MƏNTİQİ mövcud olmayan sütuna İSTİNAD EDƏR — ƏVVƏLCƏ tətbiq
-- qatındakı oxunuş söndürülməli, SONRA sütun silinməlidir.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP POLICY IF EXISTS tenant_reads_own_target ON app_version_tenant_targets;
--   DROP TABLE IF EXISTS app_version_tenant_targets;
--   ALTER TABLE license_tenants DROP COLUMN IF EXISTS service_tier;
-- COMMIT;
-- ===========================================================================
