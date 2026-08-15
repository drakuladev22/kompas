-- ===========================================================================
-- MIGRATION 049 — `positions.priority` DİAPAZONU 0..9-DAN 0..4-Ə DARALDILIR
-- ===========================================================================
-- Tarix : 2026-08-15
-- Səbəb : SÜKUTLU UYĞUNSUZLUQ. `positions.priority` sütunu
--         `CHECK (priority BETWEEN 0 AND 9)` ilə məhdud idi, domen isə
--         `RolePriority` üzvləri kimi YALNIZ 0..4-ü tanıyır:
--
--             Root=0, CEO=1, Admin=2, HR/Mağaza/Kamera=3, Satıcı=4
--
--         Yəni `priority = 7` olan bir sətir BAZADA QANUNİ idi, lakin tətbiq
--         onu OXUYA BİLMİRDİ: `mappers.position_from_row` həmin sətirdə
--         `RolePriority(7)` çağırır və `ValueError` atır. Nəticə istifadəçi
--         üçün "rol siyahısı açılmır" formasında görünərdi — səbəbi isə
--         ekranda YOX, stack trace-dədir.
--
--         Bu, CLAUDE.md §5-in "hər qayda İKİ yerdə, LAKİN EYNİ" tələbinin
--         pozulmasıdır: domen 0..4 deyir, DB 0..9 deyir. Ekranı yan keçən
--         birbaşa `INSERT` domenin heç vaxt qəbul etməyəcəyi bir sətir yarada
--         bilirdi — məhz bu boşluq üçün DB yarısı mövcuddur.
--
--         Bu fayl həmin qaydanın DB yarısıdır; domen yarısı `RolePriority`
--         (dəyişmir — o, onsuz da 0..4-dür) və `schema.sql`-dəki sütun
--         CHECK-idir (eyni dəyişikliklə 0..4-ə düzəldilir, yəni TƏZƏ
--         quraşdırma ilə YENİLƏNMİŞ baza eyni qaydaya tabe olur).
--
-- ---------------------------------------------------------------------------
-- 1. `priority > 4` OLAN SƏTİRLƏR NİYƏ *ENDİRİLİR*, NİYƏ MİQRASİYA ÇÖKMÜR
-- ---------------------------------------------------------------------------
-- Ən sərt variant (`RAISE EXCEPTION` ilə dayanmaq) RƏDD EDİLDİ. Səbəb: belə
-- sətir tətbiqdə ONSUZ DA işləmirdi — həmin rol nə oxunur, nə də ona bağlı
-- işçi yüklənir. Miqrasiyanı çökdürmək problemi HƏLL ETMİR, sadəcə onu bütün
-- quraşdırmanı bloklayan daha böyük problemə çevirərdi (operator gecə
-- yeniləmə pəncərəsində əlində düzəltmə skripti olmadan qalar).
--
-- Ona görə qərar: sətir SAXLANILIR, prioriteti `4`-ə (`RolePriority.STAFF`)
-- endirilir və hər biri üçün `RAISE WARNING` ilə kod/tenant/köhnə dəyər
-- jurnala yazılır. Heç bir sətir SİLİNMİR.
--
-- İSTİQAMƏT QƏSDƏN AŞAĞIDIR. `priority`-də KİÇİK rəqəm DAHA YÜKSƏK
-- səlahiyyət deməkdir, yəni `7 → 4` dəyişikliyi rolu nərdivanda YUXARI
-- qaldırır... və məhz buna görə 4 seçilir: 4 mövcud modelin ƏN AŞAĞI
-- pilləsidir. Diapazondan kənar hər dəyər (5..9) onsuz da 4-dən aşağıdır,
-- deməli 4-ə gətirmək mümkün olan ƏN AZ səlahiyyət verən nəticədir.
-- Alternativlər (0-a, yaxud "ən yaxın icazəli üst pilləyə" gətirmək) sükutla
-- SƏLAHİYYƏT ARTIRARDI — bir miqrasiyanın edə biləcəyi ən pis şey budur.
--
-- Praktikada `priority > 4` olan sətir gözlənilmir: `schema.sql` seed-i və
-- `seed_tenant_defaults()` yalnız 0..4 yazır, GUI isə `RolePriority`
-- siyahısından seçdirir. Belə sətrin yeganə mənbəyi birbaşa SQL-dir — və
-- bu miqrasiya məhz həmin yolu bağlayır.
--
-- ---------------------------------------------------------------------------
-- 2. MİQRASİYA SIRASI: 048-DƏN SONRA GƏLMƏLİDİR
-- ---------------------------------------------------------------------------
-- 048 bütün qeyri-`ROOT` sətirlərə `+1` tətbiq edir. Əgər 049 ONDAN ƏVVƏL
-- icra olunsaydı, köhnə modeldə 4-də olan bir custom rol 048-in sürüşməsində
-- 5-ə keçər və YENİ CHECK-ə ilişərək 048-i çökdürərdi. Nömrə ardıcıllığı
-- (048 → 049) bu asılılığı təmin edir; miqrasiyalar `database_deployment.md`-
-- dəki qaydaya görə nömrə sırası ilə tətbiq olunur.
--
-- 048 öz daxilində `priority >= 9` üçün ayrıca `RAISE EXCEPTION` qapısı
-- saxlayır (sürüşmə 10 verərdi). Həmin qapı 049-dan SONRA praktikada
-- əlçatmazdır, çünki 5..9 aralığı artıq mövcud olmur — 048-in mətni tarixi
-- sənəd kimi olduğu kimi saxlanılır (eyni qərar 048-in özündə 046 üçün
-- verilib).
--
-- ---------------------------------------------------------------------------
-- 3. CHECK MƏHDUDİYYƏTİ NİYƏ "ADI İLƏ" YOX, "TƏRİFİ İLƏ" TAPILIR
-- ---------------------------------------------------------------------------
-- `schema.sql`-də məhdudiyyət sütunun içində, ADSIZ yazılıb — PostgreSQL ona
-- avtomatik ad verir (`positions_priority_check`). Adın avtomatik olması
-- onu ETİBARSIZ açar edir: sütun bir dəfə yenidən yaradılsa, yaxud baza
-- `pg_dump --no-comments` kimi bir yoldan keçsə, ad dəyişə bilər.
--
-- Ona görə axtarış TƏRİFƏ görə aparılır: `positions` cədvəlindəki, tərifində
-- `priority` olan, LAKİN `is_camera_type` OLMAYAN hər CHECK. İkinci şərt
-- vacibdir — `chk_camera_role_priority` (013/048) da `priority`-dən danışır
-- və ona TOXUNULMAMALIDIR (o, ayrı qaydadır: kamera-tipli rol ən aşağı
-- pillədə ola bilməz).
--
-- Bu yanaşma həm də İDEMPOTENTLİYİ təmin edir: təkrar icra artıq daralmış
-- məhdudiyyəti tapıb silir və EYNİ tərifi yenidən qoyur — nəticə dəyişmir.
--
-- ---------------------------------------------------------------------------
-- 4. RLS / KONTEKST
-- ---------------------------------------------------------------------------
-- `positions` cədvəlində RLS siyasəti yoxdur (rol kataloqu kirayəçi-üstü
-- şablon sətirlərini də saxlayır), ona görə `SET LOCAL` tenant konteksti
-- TƏLƏB OLUNMUR. `position_permissions` sətirlərinə toxunulmur, yəni 046-nın
-- `trg_position_flag_hierarchy` trigger-i işə düşmür.
--
-- İdempotentdir. Təkrar icra təhlükəsizdir. DOWN bloku faylın sonundadır.
-- ===========================================================================

BEGIN;

SET search_path TO kompasos, public;

-- ---------------------------------------------------------------------------
-- 1. DİAPAZONDAN KƏNAR SƏTİRLƏR — ƏVVƏLCƏ SƏSLƏ BİLDİRİLİR, SONRA ENDİRİLİR
-- ---------------------------------------------------------------------------
-- Xəbərdarlıq HƏR SƏTİR ÜÇÜN AYRICA verilir: "3 sətir düzəldildi" mesajı
-- operatorun HANSI rolu yoxlayacağını demir, ona görə kod, tenant və köhnə
-- dəyər ayrı-ayrılıqda jurnala düşür.
DO $$
DECLARE
    r       RECORD;
    v_count INTEGER := 0;
BEGIN
    FOR r IN
        SELECT id, tenant_id, code, priority
          FROM positions
         WHERE priority > 4
         ORDER BY tenant_id NULLS FIRST, code
    LOOP
        RAISE WARNING
            'MIGRATION 049: «%» rolu (əhatə=%, id=%) prioriteti %-dən 4-ə '
            '(RolePriority.STAFF) ENDİRİLDİ. Səbəb: domen modeli yalnız 0..4 '
            'tanıyır və bu sətir tətbiqdə onsuz da oxunmurdu '
            '(`RolePriority(%)` → ValueError). Sətir SİLİNMƏDİ; düzgün pilləni '
            'Root panelindən təyin edin.',
            r.code, COALESCE(r.tenant_id::TEXT, 'ŞABLON'), r.id, r.priority, r.priority;
        v_count := v_count + 1;
    END LOOP;

    IF v_count > 0 THEN
        -- Kamera-tipli sətirlər bura DÜŞMÜR: `chk_camera_role_priority`
        -- (013: <= 2, 048: <= 3) onlara onsuz da 4-dən kiçik hədd qoyur,
        -- yəni endirmə həmin CHECK ilə ziddiyyət yarada bilməz.
        UPDATE positions SET priority = 4 WHERE priority > 4;

        RAISE WARNING
            'MIGRATION 049: cəmi % sətir 0..4 diapazonuna gətirildi. '
            'Yuxarıdakı xəbərdarlıqların hər biri ƏL İLƏ yoxlanılmalıdır.',
            v_count;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. KÖHNƏ DİAPAZON CHECK-İ SİLİNİR (tərifə görə tapılır — başlıq, bölmə 3)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT c.conname, pg_get_constraintdef(c.oid) AS def
          FROM pg_constraint c
          JOIN pg_class     t ON t.oid = c.conrelid
          JOIN pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname  = 'kompasos'
           AND t.relname  = 'positions'
           AND c.contype  = 'c'
           AND pg_get_constraintdef(c.oid) LIKE '%priority%'
           -- `chk_camera_role_priority` DA `priority`-dən danışır, lakin o,
           -- AYRI qaydadır və toxunulmamalıdır.
           AND pg_get_constraintdef(c.oid) NOT LIKE '%is_camera_type%'
    LOOP
        EXECUTE format('ALTER TABLE positions DROP CONSTRAINT %I', r.conname);
        RAISE NOTICE 'MIGRATION 049: köhnə diapazon CHECK-i silindi: % → %',
            r.conname, r.def;
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------------
-- 3. YENİ, DOMENLƏ EYNİ DİAPAZON
-- ---------------------------------------------------------------------------
-- Ad AÇIQ verilir (`schema.sql`-dəki adsız variantdan fərqli olaraq) ki,
-- gələcək miqrasiyalar onu tərif axtarmadan da tapa bilsin. Tərif eynidir,
-- yəni təzə quraşdırma ilə yenilənmiş baza EYNİ qaydaya tabe olur.
ALTER TABLE positions
    ADD CONSTRAINT chk_positions_priority_range CHECK (priority BETWEEN 0 AND 4);

COMMENT ON CONSTRAINT chk_positions_priority_range ON positions IS
    'İyerarxiya pilləsinin ədədi diapazonu — domendəki `RolePriority` üzvləri '
    'ilə EYNİ (0..4: Root, CEO, Admin, operativ, Satıcı). 049-a qədər hədd '
    '0..9 idi və 5..9 aralığındakı sətir bazada qanuni, tətbiqdə isə oxunmaz '
    'olurdu (`RolePriority(...)` → ValueError). Yeni pillə əlavə edilərsə '
    'HƏM `RolePriority`, HƏM bu CHECK dəyişməlidir (CLAUDE.md §5).';

COMMENT ON COLUMN positions.priority IS
    'Strict Hierarchy Guard-ın əsası: can_control_user_permissions sahibi '
    'yalnız ÖZ priority dəyərindən CİDDİ ŞƏKİLDƏ BÖYÜK (daha aşağı '
    'səlahiyyətli) istifadəçilərə toxuna bilər (bölmə 3). Model (048): '
    'Root=0 (TƏK BAŞINA), CEO=1, Admin=2, HR_Admin/Mağaza_Meneceri/'
    'Kamera_Nəzarətçisi=3, Satıcı=4. Diapazon (049): 0..4 — domendəki '
    '`RolePriority` üzvləri ilə hərfi uyğunluqda.';

COMMIT;

-- ===========================================================================
-- DOWN (geri qaytarma)
-- ===========================================================================
-- DİQQƏT: aşağıdakı blok DB-ni domenin oxuya bilmədiyi dəyərlərə yenidən
-- açır (5..9). Yalnız 049-un özündə qüsur aşkarlandıqda istifadə edilməlidir.
--
-- ENDİRİLMİŞ SƏTİRLƏR BƏRPA OLUNMUR — köhnə dəyərləri yalnız miqrasiya
-- jurnalındakı `WARNING` sətirlərində qalır. Bu, QƏSDƏNDİR: köhnə dəyəri
-- saxlamaq üçün ayrıca "arxiv" sütunu/cədvəli yaratmaq həmin sətirlərin
-- ömürlük qalması demək olardı, halbuki onlar onsuz da yanlış məlumatdır
-- (heç bir domen pilləsinə uyğun gəlmir). Bərpa lazımdırsa jurnaldakı
-- kod/tenant cütü ilə əl ilə edilir.
--
-- BEGIN;
-- SET search_path TO kompasos, public;
--
-- ALTER TABLE positions DROP CONSTRAINT IF EXISTS chk_positions_priority_range;
-- ALTER TABLE positions
--     ADD CONSTRAINT positions_priority_check CHECK (priority BETWEEN 0 AND 9);
--
-- COMMENT ON COLUMN positions.priority IS
--     '... 048-dəki mətni bərpa edin (diapazon qeydi olmadan) ...';
-- COMMIT;
-- ===========================================================================
