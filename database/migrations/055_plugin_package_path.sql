-- ===========================================================================
-- 055 — PLUGIN PAKETİNİN YOLU (`plugins.package_path`) — audit G-3-ün icra qatı
-- ===========================================================================
-- Tarix : 2026-08-15
-- Səbəb : Plugin səhifəsi (`REGISTER_PAGE`) qeydiyyatdan keçirdi, MENYUDA
--         görünürdü, lakin plugin KODU heç vaxt icra olunmurdu — səhifə
--         yalnız manifestdə ELAN edilmiş metadata göstərirdi.
--
--         İki maneə var idi:
--           1. `PluginSandbox.invoke` bloklayan çağırışdır (`subprocess.run`
--              + taymaut) və Qt hadisə dövrəsində interfeysi dondururdu.
--              BU MANEƏ ARADAN QALXDI — `src/presentation/background_task.py`
--              fon-işçi naxışı əlavə edildi.
--           2. Sandbox `plugin_path` TƏLƏB EDİR (`[python, -I, -S, <yol>]`),
--              `plugins` cədvəlində isə paketin yolunu saxlayan sütun YOX
--              idi: `PluginManagementUseCase.install(...)` yolu YALNIZ imza
--              yoxlaması üçün alırdı və heç yerə yazmırdı. Yəni quraşdırmadan
--              sonra host paketin harada olduğunu BİLMİRDİ.
--
--         Bu miqrasiya ikinci maneəni bağlayır.
--
-- İdempotentdir. DOWN bloku faylın sonunda şərh içindədir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `manifest` JSONB-sinin İÇİNƏ YAZILMADI
-- ---------------------------------------------------------------------------
-- `manifest` sütunu İMZANIN girişidir (`plugins/signature.py:
-- canonical_payload` onun `to_dict()` çıxışını imzalayır). Ora host tərəfindən
-- hesablanan bir sahə (quraşdırma yolu) əlavə etmək manifesti "plugin-in dediyi"
-- ilə "host-un bildiyi"nin qarışığına çevirərdi və növbəti imza yoxlaması
-- uğursuz olardı. Yol PLUGIN-İN DEDİYİ bir şey deyil — o, quraşdırma FAKTIDIR,
-- ona görə ayrıca sütundadır.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `NOT NULL` DEYİL VƏ NİYƏ DEFOLT BOŞ SƏTİRDİR
-- ---------------------------------------------------------------------------
-- Cədvəldə ARTIQ quraşdırılmış sətirlər var və onların yolu geri-hesablana
-- BİLMİR (paket istifadəçinin seçdiyi ixtiyari qovluqdadır). `NOT NULL`
-- miqrasiyanı həmin sətirlərdə uğursuz edərdi, uydurma dəyər isə host-u
-- mövcud olmayan fayla göndərərdi.
--
-- Boş yol FAİL-CLOSED oxunur: `plugin_page.py` onu "icra mümkün deyil" kimi
-- şərh edir və istifadəçiyə AYDIN səbəb göstərir («paket yolu qeydə
-- alınmayıb — plugin-i yenidən quraşdırın»). Sükutla boş səhifə göstərmək ən
-- pis nəticə olardı: istifadəçi plugin-in işlədiyini sanardı.
--
-- ---------------------------------------------------------------------------
-- TƏHLÜKƏSİZLİK: YOL SƏLAHİYYƏT VERMİR
-- ---------------------------------------------------------------------------
-- Sütun icra QAPISI DEYİL — o, yalnız ünvandır. Beş qapı toxunulmaz qalır və
-- HƏR icradan əvvəl yenidən yoxlanılır (`presentation/plugin_surface.py`):
-- status = APPROVED, `signature_verified`, manifestdə capability, MƏCBURİ
-- icazə flag-i, `plugin:` ad məkanı. Yolu əl ilə dəyişdirmək bu qapıların heç
-- birini yan keçmir; üstəlik `plugins` cədvəli RLS altındadır və yazı yolu
-- `can_manage_plugins` (hardlock: ROOT_ONLY) tələb edir.
-- ===========================================================================

-- Bütün cədvəllər `kompasos` sxemindədir; bu sətir olmadan psql defolt
-- `search_path` ilə işləyir və HƏR cədvəl "does not exist" xətası verir.
SET search_path TO kompasos, public;

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. SÜTUN
-- ---------------------------------------------------------------------------
ALTER TABLE plugins
    ADD COLUMN IF NOT EXISTS package_path TEXT NOT NULL DEFAULT '';

COMMENT ON COLUMN plugins.package_path IS
    'Quraşdırılan plugin paketinin FAYL SİSTEMİNDƏKİ yolu — sandbox alt-prosesi '
    'məhz bu faylı icra edir (`[python, -I, -S, <package_path>]`). Manifestin '
    'İÇİNDƏ saxlanmır, çünki manifest imzanın girişidir və host-un hesabladığı '
    'sahə oraya düşsəydi imza yoxlaması sınardı. BOŞ SƏTİR qanuni dəyərdir və '
    '"yol qeydə alınmayıb" deməkdir (bu sütundan ƏVVƏL quraşdırılmış sətirlər): '
    'host belə plugin-in kodunu İCRA ETMİR və səhifədə aydın səbəb göstərir. '
    'Sütun səlahiyyət vermir — beş interfeys qapısı (status, imza, capability, '
    'icazə flag-i, ad məkanı) hər icradan əvvəl ayrıca yoxlanılır.';

COMMIT;

-- ===========================================================================
-- DOWN (əl ilə icra üçün — sənədləşdirilir, avtomatik işlədilmir)
-- ===========================================================================
-- Sütun silinsə plugin İDARƏETMƏSİ (siyahı, təsdiq, söndürmə, silmə) tam
-- işləməyə davam edir — itən yeganə şey plugin SƏHİFƏSİNİN məzmunudur:
-- səhifə yenidən yalnız metadata göstərər. Sətirlərə toxunulmur.
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   ALTER TABLE plugins DROP COLUMN IF EXISTS package_path;
-- COMMIT;
