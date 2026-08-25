-- ===========================================================================
-- 106 — CANARY/ROLLBACK AKTORLUĞU (v2backlog.md Faza 11) — `set_by` İXTİYARİ
-- ===========================================================================
-- Tarix : 2026-08-25
-- Mənbə : Faza 11-nin tətbiqi (092 sxemi ilə birlikdə planlaşdırılmışdı,
--         lakin Vendor Konsolunun AKTOR MODELİ yalnız burada üzə çıxdı).
--
-- PROBLEM
-- ---------------------------------------------------------------------------
-- 092-də `app_version_tenant_targets.set_by UUID NOT NULL REFERENCES
-- employees(id)` yazıldı və şərh «VENDOR tərəfinin ÖZ employees sətridir»
-- deyirdi. Lakin Vendor Konsolunun mövcud bütün əməliyyatları (`[1 Ay Uzat]`,
-- `[Deaktiv Et]`, `set_forced_version`) HEÇ BİR employee kimliyi ilə işləmir —
-- panel hazırlayıcının yerli alətidir (`--developer-mode`), login axını YOXDUR
-- və `license_audit_log` da onsuz da aktorsuzdur (`performed_at` + `note`).
-- NOT NULL qalsaydı, hər canary/rollback yazısı ya UYDURULMUŞ employee id
-- ilə gedərdi (audit üçün YALAN sübut), ya da funksiya heç işləməzdi.
--
-- HƏLL
-- ---------------------------------------------------------------------------
-- `set_by` NULL-ləşir. AUDİT ZƏİFLƏMİR:
--   * `reason` CHECK (>= 5 simvol) MƏCBURİ qalır — «kim» bilmirsə də,
--     «niyə» həmişə yazılmalıdır;
--   * `set_at` DEFAULT now() ilə möhürlənir;
--   * FK QALIR: gələcəkdə Root öz panelindan rollback istəsə (tenant
--     kontekstli yol), employee kimliyi məhz o zaman dolur.
-- İDEMPOTENT, DOWN BLOKU SONDA.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

ALTER TABLE app_version_tenant_targets
    ALTER COLUMN set_by DROP NOT NULL;

COMMENT ON COLUMN app_version_tenant_targets.set_by IS
    'MƏZUNİYYƏTİ DƏYİŞDİ (migrations/106): Vendor Konsolu employee kimliyi '
    'daşımayan yerli alətdir — onun əməliyyatları `reason` (məcburi) və '
    '`set_at` ilə audit-lənir. Tenant kontekstli gələcək yollar (Root-un öz '
    'rollback-i) bu sütunu DOLDURUR; FK qalır ki, o zaman kimlik saxtalaşmasın.';

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- BEGIN;
--   SET search_path TO kompasos, public;
--   UPDATE app_version_tenant_targets SET set_by = '00000000-0000-0000-0000-000000000000'
--    WHERE set_by IS NULL;   -- NOT NULL-a qayıtmazdan ƏVVƏL boşları bağlamaq lazımdır
--   ALTER TABLE app_version_tenant_targets ALTER COLUMN set_by SET NOT NULL;
-- COMMIT;
-- ===========================================================================
