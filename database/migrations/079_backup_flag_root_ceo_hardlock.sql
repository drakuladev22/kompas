-- ===========================================================================
-- 079 — T2 (DEEP-GAP dövrə 4): `can_manage_backups` HARDLOCK 0 → 2 (ROOT_CEO)
-- ===========================================================================
-- Tarix : 2026-08-22
-- Səbəb : `security`-nin DEEP-GAP tapıntısı, komanda rəhbərinin TƏSDİQ etdiyi
--         "İ8" siyahısında (T2). `can_manage_backups` (bərpa/nöqtə-zamanlı
--         restore) hardlock=0 ilə YARADILMIŞDI — DB səviyyəsində istənilən
--         rola verilə bilirdi, `backup_access.py::BackupAccessUseCase.
--         _require`-in yeganə qapısı isə TƏTBİQ tərəfindəki flag yoxlaması
--         idi. `restore()` bütün tenant-ın audit/fines/override cədvəllərini
--         DROP+CREATE edir — `db_switch` (baza keçidi) ilə EYNİ risk sinfi,
--         O İSƏ artıq `can_switch_db` üçün hardlock=1 (ROOT_ONLY) daşıyır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `ROOT_ONLY`(1) YOX, `ROOT_CEO`(2)
-- ---------------------------------------------------------------------------
-- Bərpa özünə-xidmət alətidir (bölmə 7): `Root` təchizatçının hesabıdır,
-- `CEO` isə müştərinin öz hesabıdır (`root-vs-ceo` — CEO ilə Root-u
-- QARIŞDIRMAMAQ QAYDASI). `ROOT_ONLY` seçilsəydi, müştəri öz backup-ını
-- Root-un (təchizatçının) köməyi OLMADAN bərpa edə BİLMƏZDİ — bu, alətin əsas
-- mövcudluq səbəbini ləğv edərdi. `backup_access.py::_require`-in ARTIQ
-- əlavə etdiyi İKİNCİ (açıq rol) qat da MƏHZ Root VƏ CEO-nu buraxır, heç
-- birini deyil — bu miqrasiya DB tərəfini ONUNLA UYĞUNLAŞDIRIR.
--
-- ---------------------------------------------------------------------------
-- RETROAKTİV TƏMİZLİK NİYƏ LAZIMDIR
-- ---------------------------------------------------------------------------
-- `enforce_permission_hardlock()` YALNIZ İNSERT/UPDATE-i tutur — hardlock
-- səviyyəsi YÜKSƏLƏNDƏ artıq MÖVCUD olan (köhnə hardlock=0 dövründə,
-- `position_management.py::set_role_flags` ilə əl ilə verilmiş) qeyri-
-- uyğun sətirlərə TOXUNMUR. `migrations/048`-in prioritet sürüşməsi ilə EYNİ
-- fəlsəfə: yeni qayda yalnız GƏLƏCƏK yazıları tutur, KEÇMİŞ sətirlər əl ilə
-- (və ya bu miqrasiya ilə) düzəldilməlidir — əks halda flag ROOT/CEO-dan
-- kənar bir roldan HƏLƏ DƏ oxuna bilər (`Employee.has_permission()` DB
-- sətrini oxuyur, hardlock DƏYİŞİKLİYİNDƏN XƏBƏRSİZDİR).
--
-- Silinən sətirlər `granted_by IS NULL` (seed) OLA BİLMƏZ — §23/§24 seed-i
-- `can_manage_backups`-ı YALNIZ ROOT/CEO-ya verir (schema.sql-in ROOT/CEO
-- "hamısı MİNUS ROOT_ONLY/kamera" qaydası), ona görə silinən HƏR sətir
-- `position_management.py`/`root_control.py` vasitəsilə ƏL İLƏ verilmiş
-- olmalıdır.
-- ===========================================================================

SET search_path TO kompasos, public;

BEGIN;

UPDATE permission_flags
   SET hardlock_level = 2
 WHERE code = 'can_manage_backups'
   AND hardlock_level <> 2;

-- Rol-defolt yolu: ROOT/CEO-dan kənar mövqedən silinir. `positions.code`
-- həm şablon (`tenant_id IS NULL`), həm kirayəçi nüsxəsi üçün eynidir.
DELETE FROM position_permissions pp
 USING positions p
 WHERE pp.position_id = p.id
   AND pp.flag_code = 'can_manage_backups'
   AND pp.granted
   AND p.code NOT IN ('ROOT', 'CEO');

-- Fərdi override yolu: `enforce_permission_hardlock()` `user_permission_
-- overrides`-da da eyni qaydanı tətbiq edir (`NEW.effect = 'GRANT'`) — köhnə
-- fərdi GRANT-lar da eyni şəkildə köçürülür.
DELETE FROM user_permission_overrides upo
 USING employees e, positions p
 WHERE upo.user_id = e.id
   AND e.position_id = p.id
   AND upo.flag_code = 'can_manage_backups'
   AND upo.effect = 'GRANT'
   AND p.code NOT IN ('ROOT', 'CEO');

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN (geri qaytarma) — qəsdən icra edilmir, sənədləşdirilir
-- ---------------------------------------------------------------------------
-- Silinən position_permissions/user_permission_overrides sətirləri BƏRPA
-- OLUNMUR (hansı sətirlərin silindiyi qeyd edilmir — audit_logs-da əməliyyat
-- özü görünür, lakin DOWN onu proqramla geri qaytara bilməz). Yalnız
-- hardlock geri endirilir:
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   UPDATE permission_flags SET hardlock_level = 0 WHERE code = 'can_manage_backups';
-- COMMIT;
-- ===========================================================================
