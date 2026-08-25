-- ===========================================================================
-- 091 — `webhook_endpoints`: ÜMUMİ GENİŞLƏNMƏ SƏTHİ (Faza 12.2)
-- ===========================================================================
-- Tarix : 2026-08-24
-- Mənbə : `v2backlog.md` FAZA 1 / FAZA 12.2: "Gələcək üçüncü-tərəf
--         inteqrasiyaları üçün, ROOT-idarəli, açıq-qapalı ola bilən ümumi
--         bir webhook-registry (`webhook_endpoints` cədvəli: hadisə-tipi,
--         hədəf-URL, aktiv/deaktiv) — İNDİ konkret bir inteqrasiya YAZMA,
--         YALNIZ struktur."
--
-- Cədvəl adı və əsas üç sütun sənədin ÖZÜNDƏ verilib. Əlavə edilən
-- `secret` sütunu `security` agentinin (sec-v2) tələbidir — payload
-- imzalanmadan göndərilsə, hədəf server sorğunun HƏQİQƏTƏN KompasOS-dan
-- gəldiyini yoxlaya bilməz (spoofing). SSRF qorunması (localhost/daxili IP
-- qadağan, yalnız HTTPS) ÇATDIRMA QATININ işidir, sxemə aid deyil — bu
-- miqrasiya YALNIZ saxlama yerini yaradır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ YENİ CƏDVƏL
-- ---------------------------------------------------------------------------
-- Heç bir mövcud cədvəldə "hadisə-tipi → hədəf URL" abunə konsepti yoxdur.
-- `telegram_config` (migrations/068) BƏNZƏR görünə bilər, LAKİN o TƏK bir
-- kanala (Telegram bot) bağlıdır və struktur ONA GÖRƏ dardır (bot token,
-- chat_id). Webhook registry isə ÇOX-hadisəli, ÇOX-hədəfli, gələcək
-- inteqrasiyalar üçün ÜMUMİ bir strukturdur — Telegram konfiqurasiyasını
-- ora sığdırmaq sxemi lazımsız genişləndirərdi (mövcud, işlək Telegram
-- axını TOXUNULMUR, qırmızı xətt).
--
-- ---------------------------------------------------------------------------
-- `event_type` NİYƏ SƏRBƏST MƏTNDİR, ENUM DEYİL
-- ---------------------------------------------------------------------------
-- Bu miqrasiya "İNDİ konkret bir inteqrasiya YAZMA" tələbinə tabedir —
-- hansı hadisə tiplərinin mövcud olacağı HƏLƏ MƏLUM DEYİL. ENUM dəyəri
-- PostgreSQL-də SİLİNMİR (yalnız əlavə olunur), yəni erkən ENUM seçimi
-- gələcək hadisə adlarını indi TƏXMİN etmək deməkdir. `field_report_types.
-- code` ilə eyni naxış: normallaşdırılmış sərbəst mətn, mövcudluğu tətbiq
-- qatı yoxlayır.
--
-- ---------------------------------------------------------------------------
-- RLS: standart `tenant_isolation` — hər kirayəçi ÖZ webhook-larını idarə
-- edir. TIME-1: TƏTBİQ EDİLMİR — Root-authored konfiqurasiyadır (insan
-- öz-özünə lehinə vaxt manipulyasiyası riski daşımır), `feature_toggles`
-- ilə eyni səbəb.
--
-- İDEMPOTENT, DOWN BLOKU SONDA. `schema.sql` YENİLƏNMİR (CLAUDE.md §7).
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

CREATE TABLE IF NOT EXISTS webhook_endpoints (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES license_tenants(tenant_id) ON DELETE CASCADE,

    event_type    TEXT NOT NULL
                      CHECK (event_type = upper(event_type)
                         AND char_length(trim(event_type)) >= 3),
    target_url    TEXT NOT NULL CHECK (char_length(trim(target_url)) >= 8),

    -- HMAC imza açarı — hədəf server payload-un HƏQİQƏTƏN KompasOS-dan
    -- gəldiyini yoxlayır (`security`/sec-v2 tələbi). ŞİFRƏLİ SAXLANILIR
    -- (mövcud Fernet naxışı, `telegram_config.bot_token_encrypted` ilə eyni
    -- mexanizm) — DÜZ MƏTN SÜTUNU DEYİL.
    secret_encrypted TEXT NOT NULL,

    is_active     BOOLEAN NOT NULL DEFAULT TRUE,

    -- NO ACTION: "kim yaratdı?" konfiqurasiya sətrindən uzun yaşayır
    -- (`announcements.created_by` ilə eyni əsaslandırma).
    created_by    UUID NOT NULL REFERENCES employees(id) ON DELETE NO ACTION,

    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (tenant_id, event_type, target_url)
);

COMMENT ON TABLE webhook_endpoints IS
    'Faza 12.2 (v2backlog.md): ümumi genişlənmə səthi — hansı hadisə '
    'baş verəndə hansı xarici URL-ə çağırış gedəcəyini saxlayır. İNDİ heç '
    'bir konkret inteqrasiya YAZILMIR, YALNIZ struktur (sənədin öz sözü). '
    'SSRF qorunması (localhost/daxili IP qadağan, yalnız HTTPS) ÇATDIRMA '
    'QATINDADIR, bu cədvəldə YOXDUR (migrations/091).';

COMMENT ON COLUMN webhook_endpoints.event_type IS
    'SƏRBƏST NORMALLAŞDIRILMIŞ MƏTN, ENUM DEYİL — hansı hadisə tiplərinin '
    'mövcud olacağı bu miqrasiya anında MƏLUM DEYİL və PostgreSQL ENUM '
    'dəyəri SİLİNMİR (`field_report_types.code` ilə eyni naxış). '
    'Mövcudluğu tətbiq qatı yoxlayır.';

COMMENT ON COLUMN webhook_endpoints.secret_encrypted IS
    'HMAC imza açarı, Fernet ilə ŞİFRƏLİ (`telegram_config.bot_token_'
    'encrypted` naxışı). Hədəf server bunu payload-un HƏQİQƏTƏN '
    'KompasOS-dan gəldiyini yoxlamaq üçün işlədir — imzasız webhook '
    'spoofing-ə açıqdır (`security`/sec-v2 tələbi, migrations/091).';

ALTER TABLE webhook_endpoints ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON webhook_endpoints;
CREATE POLICY tenant_isolation ON webhook_endpoints
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DROP TRIGGER IF EXISTS trg_webhook_endpoints_updated ON webhook_endpoints;
CREATE TRIGGER trg_webhook_endpoints_updated
    BEFORE UPDATE ON webhook_endpoints
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- Heç bir inteqrasiya HƏLƏ İSTİFADƏ ETMİR (sənədin öz tələbi: "indi konkret
-- bir inteqrasiya yazma"), ona görə geri qaytarma DATA İTKİSİ RİSKİ AZDIR —
-- LAKİN Root artıq webhook qeydiyyatı ediblərsə (URL+imza-açarı), onlar
-- GERİ QAYITMAZ.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TRIGGER IF EXISTS trg_webhook_endpoints_updated ON webhook_endpoints;
--   DROP TABLE IF EXISTS webhook_endpoints;
-- COMMIT;
-- ===========================================================================
