-- ===========================================================================
-- 094 — `checklist_item_templates.category` (v2backlog.md Faza 3.4 sxem
--        boşluğu, `domain` tapıntısı)
-- ===========================================================================
-- Tarix : 2026-08-25
-- Səbəb : `domain` Faza 3-ü yazarkən tapdı: `checklist_item_templates`
--         (migrations/088) `category` sütunu DAŞIMIR, halbuki `employee_
--         offboarding_checklist_items.category` `NOT NULL CHECK (EQUIPMENT/
--         SETTLEMENT/EXIT_INTERVIEW)`-dir — şablondan checklist qurulanda
--         kateqoriya HARADAN gələcəyi bilinmirdi. `domain` müvəqqəti fallback
--         (`EQUIPMENT` + audit sayğacı) ilə keçib, bu miqrasiya DAİMİ
--         həllidir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ CHECK `owner_type`-A GÖRƏ ŞƏRTLƏNDİRİLİB — TƏK DƏST DEYİL
-- ---------------------------------------------------------------------------
-- `checklist_item_templates` İKİ domenin ORTAQ cədvəlidir (088 başlığı):
-- `owner_type = 'OFFBOARDING'` və `owner_type = 'FIELD_REPORT'`. Yoxladım —
-- `field_report_checklist_items`-in (migrations/037) HEÇ BİR `category`
-- sütunu YOXDUR: instansiya sətirləri yalnız `position_no`/`item_text`/
-- `passed`/`is_blocking`/`photo_required` daşıyır. Yəni "kateqoriya"
-- konsepti YALNIZ offboarding tərəfinə aiddir — `EQUIPMENT`/`SETTLEMENT`/
-- `EXIT_INTERVIEW` dəsti gündəlik açılış/bağlanış checklist-i (Faza 4.1)
-- üçün MƏNASIZDIR (kassa/təhlükəsizlik/təmizlik bəndləri bu üç kateqoriyaya
-- sığmır).
--
-- Sütunu HƏR İKİ tərəf üçün `NOT NULL` etmək FIELD_REPORT tərəfinə
-- mənasız dəyər UYDURMAĞA MƏCBUR edərdi (`v2backlog.md`-nin "uydurma
-- dəyər yazma" prinsipi eyni burada da tətbiq olunur). Ona görə sütun
-- NULLABLE-dir, LAKİN CHECK constraint `owner_type`-a görə DƏQİQ nə vaxt
-- NULL, nə vaxt dolu olmalı olduğunu MƏCBUR EDİR:
--   * `owner_type = 'OFFBOARDING'` → `category` `employee_offboarding_
--     checklist_items.category`-nin EYNİ üç dəyərindən BİRİ olmalıdır
--     (parite qorunur, iki tərəf ayrılmır — komanda rəhbərinin tələbi).
--   * `owner_type = 'FIELD_REPORT'` → `category` MÜTLƏQ NULL olmalıdır
--     (konsepsiya YOXDUR, sükutla boş qalmır — açıq qadağan).
--
-- ---------------------------------------------------------------------------
-- MÖVCUD SƏTİRLƏR
-- ---------------------------------------------------------------------------
-- Yoxlandı: `checklist_item_templates` HAZIRDA BOŞDUR (088 yalnız cədvəli
-- yaratdı, heç bir sətir seed etmədi) — miqrasiya nə DEFAULT dəyər, nə də
-- geriyə-doldurma tələb edir.
--
-- ---------------------------------------------------------------------------
-- İDEMPOTENT, DOWN BLOKU SONDA. `schema.sql` YENİLƏNMİR (CLAUDE.md §7) —
-- `checklist_item_templates` `schema.sql`-də ÜMUMİYYƏTLƏ yoxdur (088-in
-- naxışı), yeni sütun da ora düşmür.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

ALTER TABLE checklist_item_templates
    ADD COLUMN IF NOT EXISTS category TEXT;

ALTER TABLE checklist_item_templates
    DROP CONSTRAINT IF EXISTS chk_checklist_template_category_by_owner;
ALTER TABLE checklist_item_templates
    ADD CONSTRAINT chk_checklist_template_category_by_owner
    CHECK (
        (owner_type = 'OFFBOARDING'
             AND category IN ('EQUIPMENT', 'SETTLEMENT', 'EXIT_INTERVIEW'))
        OR (owner_type = 'FIELD_REPORT' AND category IS NULL)
    );

COMMENT ON COLUMN checklist_item_templates.category IS
    'YALNIZ `owner_type = OFFBOARDING` üçün dolu — `employee_offboarding_'
    'checklist_items.category` ilə EYNİ üç dəyər (parite qorunur, '
    'migrations/094). `owner_type = FIELD_REPORT` üçün MÜTLƏQ NULL: '
    '`field_report_checklist_items`-də kateqoriya konsepti yoxdur (bax fayl '
    'başlığı).';

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə, ehtiyat nüsxədən SONRA)
-- ---------------------------------------------------------------------------
-- Cədvəl HAZIRDA BOŞDUR (bax fayl başlığı) — sütun silinsə data itkisi YOX,
-- LAKİN offboarding use-case-i `category`-ni oxumağa çalışsa (`domain`-in
-- daimi köçü ARTIQ TƏTBİQ OLUNUBSA) runtime xətası verər. ƏVVƏLCƏ `domain`
-- kodunu geri qaytarın, SONRA sütunu silin.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   ALTER TABLE checklist_item_templates DROP CONSTRAINT IF EXISTS chk_checklist_template_category_by_owner;
--   ALTER TABLE checklist_item_templates DROP COLUMN IF EXISTS category;
-- COMMIT;
-- ===========================================================================
