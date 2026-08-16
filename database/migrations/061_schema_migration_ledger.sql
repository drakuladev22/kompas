-- ===========================================================================
-- 061 — MİQRASİYA REYESTRİ: HANSI FAYL TƏTBİQ OLUNUB (DB-5 FAZA 1 TAPINTISI)
-- ===========================================================================
-- Tarix : 2026-08-16
-- Səbəb : DB-5 canlı bazaya qarşı işlədi və sual cavabsız qaldı — «hansı
--         miqrasiya tətbiq olunub?». Cavabı yalnız DOLAYI yolla tapmaq
--         mümkün idi: mənbədəki `CREATE TABLE` ifadələrini canlı
--         `information_schema.tables` ilə müqayisə etmək. Nəticə: 60
--         miqrasiyadan 11-i heç vaxt tətbiq olunmamışdı və bu, aylarla
--         görünməmişdi — 32 cədvəl bazada YOX idi, tətbiq isə həmin
--         cədvəllərə yazmağa çalışırdı.
--
-- ---------------------------------------------------------------------------
-- NİYƏ CƏDVƏL MÜQAYİSƏSİ KİFAYƏT ETMİR
-- ---------------------------------------------------------------------------
-- Müqayisə yalnız CƏDVƏL yaradan miqrasiyanı görür. Sütun, indeks, trigger və
-- ya `system_limits` sətri əlavə edən miqrasiya (bu layihədə onlar
-- ÇOXLUQDADIR — 60-dan 40-ı cədvəl yaratmır) tamamilə görünməz qalır.
-- Məsələn 056 immutability trigger-i ucbatından HƏMİŞƏ uğursuz olurdu, lakin
-- heç bir cədvəl yaratmadığı üçün «çatışan cədvəl» siyahısında görünmürdü.
--
-- ---------------------------------------------------------------------------
-- NİYƏ `checksum` DA SAXLANILIR
-- ---------------------------------------------------------------------------
-- Yalnız fayl adı saxlansaydı, tətbiq olunmuş miqrasiyanın SONRADAN
-- redaktəsi görünməz qalardı: reyestr «tətbiq olunub» deyər, faylın məzmunu
-- isə artıq başqa olar. Belə fərq ən pis haldadır — iki quraşdırma eyni ad
-- altında MÜXTƏLİF sxem daşıyar. `checksum` (SHA-256) bunu aşkar edir.
--
-- ---------------------------------------------------------------------------
-- NİYƏ RLS YOXDUR VƏ NİYƏ TƏTBİQ ROLUNA GRANT VERİLMİR
-- ---------------------------------------------------------------------------
-- Reyestr KİRAYƏÇİYƏ aid deyil — o, quraşdırmanın özünə aid faktdır (eyni
-- baza bütün kirayəçilər üçün eynidir). Tətbiq onu nə oxuyur, nə yazır: yazan
-- yeganə tərəf miqrasiya icraçısıdır (`scripts/apply_migrations.py`) və o,
-- sahib rolu ilə işləyir. `GRANT` verməmək burada sadələşdirmə deyil, sərhəd:
-- tətbiq öz sxeminin tarixçəsini dəyişdirə bilməməlidir.
--
-- ---------------------------------------------------------------------------
-- BU MİQRASİYA ÖZÜNÜ QEYD ETMİR
-- ---------------------------------------------------------------------------
-- Sətirləri İCRAÇI yazır, miqrasiya yox. Əks halda burada 60 fayl adından
-- ibarət sabit siyahı olmalı idi və o siyahı ilk əlavə olunan miqrasiyada
-- köhnələrdi. İcraçı isə faylları qovluqdan oxuyur — mənbə həmişə faktdır.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

CREATE TABLE IF NOT EXISTS schema_migrations (
    filename     TEXT PRIMARY KEY,
    checksum     TEXT        NOT NULL,
    applied_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_by   TEXT        NOT NULL DEFAULT current_user,
    duration_ms  INTEGER
);

COMMENT ON TABLE schema_migrations IS
    'Tətbiq olunmuş miqrasiyaların reyestri (migrations/061). Sətirləri '
    '`scripts/apply_migrations.py` yazır; miqrasiya faylları özlərini QEYD '
    'ETMİR — bax faylın başlığı.';
COMMENT ON COLUMN schema_migrations.checksum IS
    'Faylın SHA-256 hash-ı. Tətbiqdən sonra fayl redaktə olunarsa, icraçı '
    'fərqi görüb XƏBƏRDARLIQ edir — eyni ad altında müxtəlif sxem ən çətin '
    'aşkarlanan uyğunsuzluqdur.';
COMMENT ON COLUMN schema_migrations.duration_ms IS
    'İcra müddəti. Yavaşlayan miqrasiya növbəti quraşdırmada taymauta '
    'düşməzdən ƏVVƏL görünməlidir.';

-- Reyestrin özü kirayəçiyə aid deyil, ona görə RLS QOŞULMUR (bax başlıq).
-- `system_scope()` yolundan da oxunmur: tətbiq bu cədvəli ümumiyyətlə açmır.

COMMIT;

-- ---------------------------------------------------------------------------
-- DOWN
-- ---------------------------------------------------------------------------
-- Reyestrin silinməsi sxemi DƏYİŞMİR — yalnız «hansı miqrasiya tətbiq
-- olunub» sualı yenidən cavabsız qalır. Ona görə geri qaytarma təhlükəsizdir,
-- lakin növbəti icraçı bütün faylları yenidən tətbiq edəcək (hamısı
-- idempotentdir, yəni nəticə eynidir — sadəcə uzun çəkir).
--
-- BEGIN;
--   SET search_path TO kompasos, public;
--   DROP TABLE IF EXISTS schema_migrations;
-- COMMIT;
