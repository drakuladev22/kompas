-- ===========================================================================
-- 052 — DUAL-CONTROL TƏSDİQ TIMEOUT-U + MÜBAHİSƏLİ CƏRİMƏNİN EXPORT KİLİDİ
-- ===========================================================================
-- Tarix : 2026-08-15
-- Səbəb : Məntiq auditinin M-5 və M-6 tapıntıları.
--
--   M-5 — `[Vaxtı Əllə Təyin Et]` sorğusu ikinci təsdiqi ƏBƏDİ gözləyə
--         bilirdi. Bölmə 3 (Dual-Control Deadlock Guard) açıq tələb edir ki,
--         "gözləyən override-lar sonsuza qədər təsdiqsiz qalmasın"; guard
--         yalnız XƏBƏRDARLIQ edirdi, müddət isə heç yerdə təyin olunmamışdı.
--         Bu miqrasiya həmin müddəti ROOT parametri kimi seed edir.
--
--   M-6 — 72 saatlıq pəncərə bağlananda hələ BAXILMAMIŞ etiraz cəriməni
--         export-a buraxırdı. `cron_close_expired_appeals`-ın öz şərhi bunu
--         hərfən yazırdı: "export kilidini açır". Nəticə: HR baxmadığı üçün
--         işçidən pul kəsilirdi. Görünüş artıq qərarsız etirazı olan cəriməni
--         BURAXMIR.
--
-- Bu miqrasiya CƏDVƏL/SÜTUN YARATMIR VƏ SİLMİR: bir `system_limits` sətri,
-- bir trigger funksiyası və bir görünüşün yenidən təyini.
--
-- İdempotentdir (`ON CONFLICT DO NOTHING`, `CREATE OR REPLACE`).
-- DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `system_limits`, NİYƏ KODDA SABİT
-- ---------------------------------------------------------------------------
-- CLAUDE.md §5: struktur zəmanət olmayan hər hədd Root-dan idarə olunur.
-- 480 dəqiqə (bir iş növbəsi) yalnız FALLBACK-dır (`DEFAULT_LIMITS`) —
-- 21 filialın növbə uzunluğu eyni deyil və HR onu öz rejiminə uyğunlaşdıra
-- bilməlidir.
--
-- DİAPAZON (30–1440) NİYƏ MƏHZ BELƏDİR:
--   * ALT sərhəd 30 — `DUAL_CONTROL_THRESHOLD_MINUTES` defoltu ilə eynidir.
--     Bundan qısa müddət sorğunu təsdiqçi bildirişi AÇMAMIŞ ləğv edərdi,
--     yəni ikinci təsdiq praktikada heç vaxt baş verməzdi.
--   * ÜST sərhəd 1440 (bir sutka) — bundan uzun müddət "əbədi gözləmə"
--     probleminin özünü geri gətirərdi; bu miqrasiya məhz onu bağlayır.
--
-- ---------------------------------------------------------------------------
-- TIMEOUT DOLANDA NƏ OLUR — VƏ NƏ OLMUR
-- ---------------------------------------------------------------------------
-- Sorğu LƏĞV olunur (`manual_time_overrides.status = 'REJECTED'`,
-- `rejection_reason` mətnində səbəb), orijinal vaxt qüvvədə qalır və sorğunu
-- yazan operator bildiriş alır.
--
-- AVTOMATİK TƏSDİQ QƏSDƏN YOXDUR: "heç kim baxmadısa təsdiqlənmiş say"
-- qaydası dual-control-u tamamilə mənasız edərdi — operator sadəcə
-- gözləməklə istənilən düzəlişi keçirə bilərdi.
--
-- YENİ ENUM DƏYƏRİ ƏLAVƏ EDİLMİR: `override_status` onsuz da `REJECTED`
-- daşıyır və `rejection_reason` sütunu `schema.sql`-dan bəri mövcuddur.
-- Timeout ləğvini insan rəddindən `approved_by IS NULL` ayırır.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. MÖVCUD KİRAYƏÇİLƏR (M-5)
-- ---------------------------------------------------------------------------
-- `ON CONFLICT DO NOTHING`: təkrar icrada Root-un artıq dəyişdirdiyi dəyər
-- ÜSTÜNDƏN YAZILMIR (013/017/018/022/023 ilə eyni qayda).
INSERT INTO system_limits
    (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
SELECT t.tenant_id, v.limit_key, v.limit_value, v.value_type,
       v.min_value, v.max_value, v.description_az
  FROM license_tenants t
 CROSS JOIN (VALUES
    ('DUAL_CONTROL_APPROVAL_TIMEOUT_MINUTES', '480', 'INTEGER', '30', '1440',
     'Manual vaxt düzəlişinin ikinci təsdiqi ən çox neçə dəqiqə gözləyə bilər. '
     'Müddət dolanda sorğu LƏĞV olunur (avtomatik təsdiqlənmir), icazənin '
     'orijinal vaxtı qüvvədə qalır və sorğunu yazan operator bildiriş alır.')
 ) AS v(limit_key, limit_value, value_type, min_value, max_value, description_az)
ON CONFLICT (tenant_id, limit_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. YENİ KİRAYƏÇİLƏR (M-5)
-- ---------------------------------------------------------------------------
-- `seed_tenant_defaults()` `schema.sql` §24-dədir və bu miqrasiya ondan SONRA
-- tətbiq olunur. Funksiyanın ÖZÜNÜ dəyişdirmirik (schema.sql tək mənbədir) —
-- əvəzinə migrations/013/022/023-dəki naxış təkrarlanır: yeni kirayəçi
-- yarananda bu açarı əlavə edən AYRICA trigger.
CREATE OR REPLACE FUNCTION seed_dual_control_timeout_for_new_tenant()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO system_limits
        (tenant_id, limit_key, limit_value, value_type, min_value, max_value, description_az)
    VALUES
        (NEW.tenant_id, 'DUAL_CONTROL_APPROVAL_TIMEOUT_MINUTES', '480', 'INTEGER', '30', '1440',
         'Manual vaxt düzəlişinin ikinci təsdiqi ən çox neçə dəqiqə gözləyə bilər. '
         'Müddət dolanda sorğu LƏĞV olunur, orijinal vaxt qüvvədə qalır.')
    ON CONFLICT (tenant_id, limit_key) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION seed_dual_control_timeout_for_new_tenant() IS
    'Yeni kirayəçiyə dual-control təsdiq müddətini əlavə edir (migrations/052). '
    '`seed_tenant_defaults()` toxunulmadan qalır.';

DROP TRIGGER IF EXISTS trg_seed_dual_control_timeout ON license_tenants;
CREATE TRIGGER trg_seed_dual_control_timeout
    AFTER INSERT ON license_tenants
    FOR EACH ROW EXECUTE FUNCTION seed_dual_control_timeout_for_new_tenant();

-- ---------------------------------------------------------------------------
-- 3. `v_exportable_fines` — DÖRDÜNCÜ ŞƏRT (M-6)
-- ---------------------------------------------------------------------------
-- Görünüşün üç şərti (003 + 016) TOXUNULMADAN qalır; yalnız DÖRDÜNCÜSÜ
-- əlavə olunur: qərarı verilməmiş etirazı olan cərimə hesabata düşmür.
--
-- `PENDING` VƏ `EXPIRED` BİRLİKDƏ: birincisi "hələ baxılmayıb", ikincisi
-- "72 saat keçdi, YENƏ baxılmayıb". Hər ikisi QƏRARSIZDIR. `EXPIRED`-i
-- kənarda saxlamaq qüsurun məhz özü olardı — pəncərənin bağlanması işçinin
-- deyil, HR-ın hərəkətsizliyinin nəticəsidir.
--
-- Qayda İKİ YERDƏDİR (CLAUDE.md §5): domendə `Fine.is_exportable`-in
-- dördüncü şərti, burada `NOT EXISTS`. Yalnız birində olsaydı, ekranı yan
-- keçən export skripti mübahisəli cəriməni yenə tutardı.
CREATE OR REPLACE VIEW v_exportable_fines AS
SELECT f.*
FROM fines f
-- `REDUCED` DAXİLDİR: qismən qəbul olunmuş etirazdan sonra işçi
-- azaldılmış məbləği yenə ödəyir (bax `Fine.is_exportable`).
WHERE f.status IN ('PUBLISHED', 'REDUCED')
  AND f.published_at IS NOT NULL
  AND f.appeal_window_closes_at IS NOT NULL
  AND f.appeal_window_closes_at <= now()
  AND f.exported_period IS NULL
  AND NOT EXISTS (
      SELECT 1
        FROM fine_appeals fa
       WHERE fa.fine_id = f.id
         AND fa.status IN ('PENDING', 'EXPIRED')
  );

COMMENT ON VIEW v_exportable_fines IS
    'Premiya&Cərimə export-una (FAYL 2) düşə bilən cərimələr. Ayın 1-də '
    'nəşr olunan cərimə həmin ayın export-una DÜŞMÜR (72 saat keçməyib) — '
    'bu, gözlənilən davranışdır, xəta deyil. 016: pəncərə DONDURULMUŞ '
    '`appeal_window_closes_at` sütunundan oxunur. 052: qərarı verilməmiş '
    'etirazı (PENDING/EXPIRED) olan cərimə hesabata DÜŞMÜR — HR-ın '
    'baxmaması işçinin pul itkisinə çevrilə bilməz.';

-- ---------------------------------------------------------------------------
-- 4. `cron_close_expired_appeals` — ŞƏRHİN DÜZƏLİŞİ (M-6)
-- ---------------------------------------------------------------------------
-- Funksiyanın GÖVDƏSİ dəyişmir: `PENDING` → `EXPIRED` keçidi qalır, çünki
-- "HR cavab vermədi" halını "işçi etiraz etmədi" halından ayıran yeganə
-- əlamət odur. Dəyişən onun MƏNASIDIR: `EXPIRED` artıq export kilidini
-- AÇMIR (yuxarıdakı görünüş) və etiraz bu vəziyyətdən də qərar ala bilir
-- (`FineAppeal._require_decidable`). Şərh həmin köhnə mənanı yazırdı, ona
-- görə yenilənir — səhv şərh növbəti oxucunu qüsuru geri qaytarmağa
-- yönəldərdi.
COMMENT ON FUNCTION cron_close_expired_appeals() IS
    'Cavabsız qalmış etirazı `EXPIRED` kimi işarələyir (SLA pozuntusu izi). '
    '052-dən sonra bu, export kilidini AÇMIR və qərar vermə imkanını '
    'BAĞLAMIR — HR etiraza sonradan da baxa bilər, cərimə isə qərar '
    'verilənə qədər hesabata düşmür.';

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- DİQQƏT: (a) limit sətrinin silinməsi parametri ROOT ekranından yox edir;
-- use case işləməyə davam edir, lakin `DEFAULT_LIMITS` dəyəri (480) ilə.
-- (b) görünüşün geri qaytarılması M-6 qüsurunu BƏRPA edir — qərarsız etirazı
-- olan cərimə yenidən export-a düşər.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_seed_dual_control_timeout ON license_tenants;
--   DROP FUNCTION IF EXISTS seed_dual_control_timeout_for_new_tenant();
--   DELETE FROM system_limits WHERE limit_key = 'DUAL_CONTROL_APPROVAL_TIMEOUT_MINUTES';
--   CREATE OR REPLACE VIEW v_exportable_fines AS
--   SELECT f.* FROM fines f
--    WHERE f.status IN ('PUBLISHED', 'REDUCED')
--      AND f.published_at IS NOT NULL
--      AND f.appeal_window_closes_at IS NOT NULL
--      AND f.appeal_window_closes_at <= now()
--      AND f.exported_period IS NULL;
-- COMMIT;
