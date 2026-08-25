"""Maketdən götürülmüş ölçülər — Faza 4.2.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI MODUL, NİYƏ `tokens.py`-DA DEYİL
──────────────────────────────────────────────────────────────────────────────
`tokens.py`-dakı `METRICS` ümumi şkaladır (4/8/16/24/32) və QSS-ə token kimi
ötürülür. Buradakı dəyərlər isə KONKRET maket ölçüləridir — 226px sol panel,
62px başlıq zolağı, 38px pəncərə başlığı, 40px naviqasiya sətri. Onlar şkalaya
düşmür və QSS tokeni də deyil: Python tərəfdə `setFixedWidth`, `setSpacing`,
`setContentsMargins` çağırışlarında işlənir.

İkisini qarışdırmaq `tokens.py`-ın müqaviləsini pozardı: `check_contrast.py`
həmin faylı izolyasiya ilə `exec` edir və orada "226" kimi bir dəyər rəng
lüğətinə düşsəydi, yoxlayıcı onu rəng kimi oxumağa çalışardı.

Hər sabitin yanındakı şərh onun maketdəki mənbəyini göstərir.
"""

from __future__ import annotations

from typing import Final

# --------------------------------------------------------------------------- #
# Pəncərə
# --------------------------------------------------------------------------- #

#: Spesifikasiyanın minimum pəncərə ölçüsü (bölmə "PLATFORMA QAYDALARI").
#: Bu, pəncərənin İLK AÇILIŞ ölçüsüdür — aşağıdakı `WINDOW_HARD_MIN_*` isə
#: istifadəçinin keçə bilmədiyi mütləq həddir (səbəb orada yazılıb).
WINDOW_MIN_WIDTH: Final = 1280
WINDOW_MIN_HEIGHT: Final = 800

# --------------------------------------------------------------------------- #
# Tərtibat həddləri (breakpoint)
# --------------------------------------------------------------------------- #
# NİYƏ BURADA, NİYƏ ROOT PARAMETRİ DEYİL
# ─────────────────────────────────────────────────────────────────────────────
# `system_limits` iş qaydalarının (taymaut, limit, dərəcə) yeridir — onları
# müəssisə dəyişir. Bu iki ədəd isə UI-nin öz kompozisiya qərarıdır: 226px sol
# panel + 26px kontent boşluğu + kart şəbəkəsi məhz bu enlərdə qırılır. Root
# istifadəçisinə "sidebar neçə piksellə yığılsın" sualını vermək ona interfeys
# tərtibatının məsuliyyətini ötürərdi; səhv dəyər isə ekranı sındırardı.
#
#: Bu enddən BÖYÜK pəncərə: sol panel tam (ikon + mətn), kartlar yan-yana.
LAYOUT_BREAKPOINT_WIDE: Final = 1280
#: Bu enddən kiçik olmağa icazə verilmir (aşağıda `WINDOW_HARD_MIN_WIDTH`).
#: 1280 ilə bu hədd arasında sol panel yalnız-ikon rejiminə keçir və kartlar
#: bir sütuna yığılır — Windows-da YARIM-EKRAN snap məhz bu diapazona düşür
#: (1920px monitorda yarısı 960px, 1366px-də 683px).
LAYOUT_BREAKPOINT_COMPACT: Final = 700

#: `EmployeeHomeScreen`-in (kiosk) altı-kartlıq sırasının ÖZ təbii minimum
#: eni — `perf-screens` real Qt render ilə ölçdü.
#:
#: `LAYOUT_BREAKPOINT_WIDE` (1280) İLƏ QARIŞDIRILMIR, TƏKRARI DEYİL: o,
#: admin panelin sol-panel (226px) + kontent bölgüsünün həddidir və kiosk
#: EKRANININ HEÇ BİR sol paneli yoxdur (`group_a_kiosk.py` modul başlığı:
#: "heç bir naviqasiya yoxdur"). Tipik kiosk sensor panel enləri (1280,
#: 1366) HƏR İKİSİ `LAYOUT_BREAKPOINT_WIDE`-dan (`>= 1280`) YUXARIDADIR —
#: admin sabitini təkrar işlətsəydik, kiosk HƏMİŞƏ "WIDE" sayılıb kartlar
#: yenə sıxışardı (bax `shell/kiosk.py::KioskWindow.resizeEvent`).
KIOSK_CARDS_ROW_MIN_WIDTH: Final = 1656

#: Pəncərənin MÜTLƏQ minimumu.
#:
#: NİYƏ 1280 DEYİL: minimum en 1280 qaldıqca Windows-un yarım-ekran snap-i
#: fiziki olaraq mümkün deyildi — OS pəncərəni 960px-ə sığışdırmağa çalışır,
#: Qt isə 1280-dən aşağı buraxmır və snap "işləmir" görünür. Yəni bu bir ədəd
#: bütün Aero Snap ssenarisini bloklayırdı. Spesifikasiyanın 1280×800 tələbi
#: İLK AÇILIŞ ölçüsü kimi qorunur (`WINDOW_MIN_WIDTH` yuxarıda).
WINDOW_HARD_MIN_WIDTH: Final = LAYOUT_BREAKPOINT_COMPACT
#: Hündürlük üçün eyni səbəb: şaquli (dörddə-bir) snap və 1366×768 noutbuk.
WINDOW_HARD_MIN_HEIGHT: Final = 560

#: Custom title bar hündürlüyü — maketdə `height: 38px`.
TITLEBAR_HEIGHT: Final = 38
#: Loqo kvadratı — `width/height: 16px; border-radius: 5px`.
TITLEBAR_LOGO_SIZE: Final = 16
#: Pəncərə düymələrinin eni (—, □, ×).
WINDOW_BUTTON_WIDTH: Final = 46

# --------------------------------------------------------------------------- #
# 8-PUNKTLU ŞƏBƏKƏ (`appl.md` FAZA 1)
# --------------------------------------------------------------------------- #
# Aşağıdakı doldurma/aralıq dəyərləri 8-in mislərinə gətirildi. ƏVVƏLKİ
# dəyərlər `design_reference/` maketlərindən piksel-piksel götürülmüşdü (22,
# 26, 18, 20, 14, 10) və hər biri AYRILIQDA düzgün idi; problem ONLARIN
# BİRLİKDƏ yaratdığı ritmdə idi — kartın içindəki sətir 20-dən, header 26-dan,
# kontent 22-dən başlayırdı, yəni ekranda ÜÇ fərqli şaquli xətt vardı və
# ekranlar arasında keçəndə məzmun "tərpənirdi".
#
# ŞƏBƏKƏDƏN KƏNARDA QALAN İKİ QRUP QƏSDƏNDİR:
#   * 12 (`SPACE_MS`, aşağıda; `SIDEBAR_PADDING_H`, `NAV_ITEM_ICON_SPACING`) —
#     8-in misli deyil, lakin Apple şkalasının yarım-pilləsidir; 8-ə
#     endirilsəydi ikon ilə mətn "bir söz" kimi oxunardı (bax `NAV_ITEM_ICON_
#     SPACING` izahı), 16-ya qaldırılsaydı panelin eni də böyüməli olardı.
#   * 44 (`NAV_ITEM_HEIGHT`, `ROW_HEIGHT_DENSE`) — toxunma hədəfinin minimumu
#     (`--touch-target-min`), yəni erqonomik hədd, ritm dəyəri deyil.
#
# Pəncərə çərçivəsinin ölçüləri (`TITLEBAR_HEIGHT`, `WINDOW_BUTTON_WIDTH`)
# TOXUNULMUR: onlar Windows konvensiyasıdır (`appl.md` qırmızı xətti).

#: VİZUAL FAZA #5 — `tokens.METRICS["--space-ms"]` ilə EYNİ dəyər.
#:
#: YENİ ölçü YARATMIR: `setSpacing(12)` kod bazasında ~175 yerdə ARTIQ
#: işlədilirdi — `SIDEBAR_PADDING_H`/`NAV_ITEM_ICON_SPACING`-in ÜMUMİLƏŞDİRİLMİŞ
#: forması. Hər çağırış öz hərfi "12"-sini yazdığı üçün `check_symmetry.py`
#: bunu "tərtibat aralığı" rolunda ADSIZ dəyər kimi sayırdı (58-lik tavanın
#: bir vahidi). Bütün çağırış nöqtələri `setSpacing(metrics.SPACE_MS)`-ə
#: köçürüldü (VİZUAL FAZA #5) — səpələnmə bununla AZALIR, "adlı istinadlar
#: sayılmır" qaydası (`check_symmetry.py` başlığı) buna görə var.
SPACE_MS: Final = 12

# --------------------------------------------------------------------------- #
# Sol naviqasiya
# --------------------------------------------------------------------------- #

#: Sol panelin eni.
#:
#: ──────────────────────────────────────────────────────────────────────────
#: 226 → 244: MADDƏLƏR «İÇ-İÇƏ» GÖRÜNÜRDÜ
#: ──────────────────────────────────────────────────────────────────────────
#: İstifadəçi hesabatı: «naviqasiya sistemi çox iç-içədir, bir az aralarını
#: açmağını istəyirəm». Ölçülər maketdən hərfi götürülmüşdü (226/40/4), lakin
#: maketin şrifti ilə Windows-un faktiki interfeys şrifti eyni deyil: uzun
#: Azərbaycan başlıqları («ROOT İdarə Mərkəzi», «Şübhəli Satışlar») 226px-də
#: sətrin sonuna dirənir və sətirlər arası 4px boşluq onları BİR BLOK kimi
#: göstərirdi.
#:
#: Üç ölçü BİRLİKDƏ dəyişir — biri tək qalsaydı nisbət pozulardı: en (mətnə
#: yer), sətir hündürlüyü (toxunma sahəsi) və sətirlərarası boşluq (ayırma).
SIDEBAR_WIDTH: Final = 244
#: Daraldılmış rejim (yalnız ikonlar) — spesifikasiya "daralda bilər" deyir.
SIDEBAR_COLLAPSED_WIDTH: Final = 64
#: Maketdə `padding: 20px 12px` idi — şaquli dəyər 8-lik şəbəkəyə
#: qaldırıldı (bax yuxarıdakı şəbəkə qeydi), üfüqi 12 QƏSDƏN qalır.
SIDEBAR_PADDING_V: Final = 24
SIDEBAR_PADDING_H: Final = 12
#: Maddələr arası boşluq (əvvəl 4px — bax `SIDEBAR_WIDTH` izahı).
SIDEBAR_ITEM_SPACING: Final = 8
#: Maddə hündürlüyü (əvvəl 40px).
NAV_ITEM_HEIGHT: Final = 44
#: İkon ilə mətn arası aralıq (əvvəl 11px).
#:
#: `navbar.jpg` referansında bu, sətrin oxunaqlılığını müəyyən edən ən
#: görünən ölçüdür: 11px-də ikon və mətn BİR blok kimi oxunurdu. Dəyər
#: `tokens.METRICS["--nav-icon-gap"]` ilə eyni olmalıdır — biri QSS-ə,
#: digəri layout-a gedir və fərqlənsələr ikon ilə mətn iki fərqli aralıqla
#: düzülərdi.
NAV_ITEM_ICON_SPACING: Final = 12
#: Bölmə başlığının alt boşluğu (maketdə 10 → şəbəkədə 8).
SIDEBAR_LABEL_BOTTOM: Final = 8
#: Naviqasiya sətrinin SOL PADDING-i — `qss.py`-dakı `padding: 0 --space-md`
#: ilə EYNİ dəyər olmalıdır.
#:
#: Bölmə etiketi (`Naviqasiya`) bu dəyərlə hizalanır: fərqlənsələr panelin sol
#: kənarında İKİ şaquli xətt yaranır — etiket bir yerdən, ikonlar başqa
#: yerdən başlayır. `navbar.jpg` referansında «MAIN MENU» etiketi ilə
#: maddələrin ikonları dəqiq eyni xətdədir.
NAV_ITEM_TEXT_INDENT: Final = 16
#: Aç/bağla düyməsinin ölçüsü — sətir hündürlüyündən kiçikdir ki, panelin
#: başlığında «maddə» kimi oxunmasın.
SIDEBAR_TOGGLE_SIZE: Final = 28
#: `NavButton`-un mətn üçün ayırdığı sahədən İKON+DOLDURMA-nın YEDİYİ hissə
#: (`buttons.NavButton._apply_elided_text` bunu `self.width()`-dən çıxarır).
#:
#: BAZA DÜYMƏNİN ÖZÜNÜN ENİDİR, PANELİN DEYİL — bu, İLK versiyada
#: SƏHVƏN qarışdırılmışdı: sabit `SIDEBAR_WIDTH` (244) əsasında 80 kimi
#: çıxarılmışdı, halbuki `self.width()` DÜYMƏNİN eni (`SIDEBAR_WIDTH −
#: 2×SIDEBAR_PADDING_H` = 244−24 = 220), YOX panelin ÖZÜ. Nəticədə hər
#: elide hesabından 24px ARTIQ çıxılırdı və lazımsız yerə daha çox maddə
#: kəsilirdi (real ekranda ölçülüb: 1 gözlənilən yerinə 3 maddə kəsilirdi).
#:
#: ÖLÇÜLMÜŞ DƏYƏR, DÜSTUR DEYİL — düymə eni 220px-də «Performans
#: Qiymətləndirmələri» sətri ~192px tələb edir, real ekranda ölçülmüş
#: qalan yer isə ~164px-dir, yəni 220 − 164 = 56. Bu, sol/sağ
#: `--space-md` düymə padding-i (16+16=32) + ikon (16) + Qt-nin
#: `QPushButton` daxilində ikon/mətn arasında buraxdığı, QSS-dən idarə
#: OLUNMAYAN daxili boşluğun (≈8) CƏMİDİR — sonuncunu əl ilə hesablamaq
#: mümkün deyil (Qt bunu stilə görə DAXİLİ tərtib edir), ona görə dəyər
#: RENDER OLUNMUŞ pəncərədə ÖLÇÜLÜB, düsturla ÇIXARILMAYIB.
NAV_ITEM_TEXT_RESERVED_WIDTH: Final = 56

# --------------------------------------------------------------------------- #
# Səhifə başlığı (header)
# --------------------------------------------------------------------------- #

#: Maketdə `height: 62px` — 64 həm 8-lik şəbəkəyə düşür, həm də 34px
#: ikon düyməsinin üstündə/altında bərabər pay saxlayır.
HEADER_HEIGHT: Final = 64
#: Maketdə `padding: 0 26px` — kontentlə EYNİ şaquli xətt üçün 24.
HEADER_PADDING_H: Final = 24
#: Başlıq ilə alt-başlıq arası (maketdə `gap: 14px`).
HEADER_SPACING: Final = 16
#: Header-dəki dairəvi/kvadrat ikon düymələri `34×34`.
HEADER_ICON_BUTTON: Final = 34
#: İstifadəçi avatarı `32×32`.
AVATAR_SIZE: Final = 32

# --------------------------------------------------------------------------- #
# Kontent
# --------------------------------------------------------------------------- #

#: Maketdə `padding: 22px 26px` — hər ikisi 24-dür: kontentin sol kənarı
#: indi header-in sol kənarı ilə EYNİ xətdədir.
CONTENT_PADDING_V: Final = 24
CONTENT_PADDING_H: Final = 24
#: Alt boşluq — üzən dəstək düyməsi (54px) + kənar məsafəsi (28px) +
#: nəfəs payı. Məzmun onun altında qalmasın deyə.
CONTENT_BOTTOM_SAFE_AREA: Final = 96
#: Kartlar arası (maketdə `gap: 18px`) — şəbəkədə 16.
CARD_SPACING: Final = 16
#: Kartın İÇİNDƏKİ elementlər arasındakı aralıq.
#:
#: `appl.md` FAZA 3 — ƏVVƏL BU DƏYƏR HƏR ÇAĞIRIŞ YERİNDƏ AYRICA YAZILIRDI:
#: 12 (67 yer), 16 (32 yer), 20 (5 yer). Üç dəyər eyni ROLU daşıyırdı, yəni
#: kart-kartdan fərqlənirdi və ekranlar arasında keçəndə məzmun «tərpənirdi»
#: (`scripts/check_symmetry.py` bunu ölçür).
#:
#: 16 seçilib, 12 YOX: başlıq altındakı ayırıcı xətlər silinəndən sonra
#: (qayda 9) sərhədi məhz BOŞLUQ çəkir və 12-də başlıqla məzmun bir-birinə
#: yapışırdı. Sıx siyahı sətirləri üçün `Card(spacing=8)` QALIR — o, ayrı
#: roldur (bir-birinin ardınca gələn eyni tipli sətirlər), ona görə tokenə
#: çevrilmir.
CARD_CONTENT_SPACING: Final = 16

#: Kart daxili boşluq.
#:
#: DESIGN.MD REDİZAYNI: 18 → 20. Referansların hamısında (`dashboard.jpg`,
#: `tasks.jpg`, `status card UI design.jpg`) kart daxili boşluq 4px şəbəkəsinə
#: OTURUR; 18 isə şəbəkədən kənar idi və kartın içindəki hər sətir yarım
#: piksel sürüşürdü. 20 həm şəbəkəyə düşür, həm də başlıq ilə kənar arasında
#: referanslardakı nəfəs payını verirdi.
#:
#: `appl.md` FAZA 1: 20 → 24. 20 dörd-piksellik şəbəkədə idi, səkkiz-
#: piksellikdə YOX; üstəlik Apple dizaynının ən tanınan cəhəti kartın
#: içindəki BOL boşluqdur və 20 həmin nəfəsi vermirdi.
CARD_PADDING: Final = 24

#: Sıx cədvəl sətri (`tasks.jpg`, `status card UI design.jpg`).
#:
#: NİYƏ İKİ SƏTİR HÜNDÜRLÜYÜ VAR: referanslar iki fərqli sıxlıq işlədir —
#: skan edilən cədvəl (44px) və oxunan siyahı kartı (56px). Tək dəyər
#: seçsəydik, ya cədvəl lazımsız yer tutar, ya siyahı sıxılıb oxunmaz olardı.
#: 44 həm də `--touch-target-min` ilə üst-üstə düşür: kassa PC-sinin toxunma
#: ekranında cədvəl sətri hələ də hədəf ola bilir.
ROW_HEIGHT_DENSE: Final = 44
#: Geniş siyahı sətri — iki sətirlik mətn (ad + alt-sətir) sığmalıdır.
ROW_HEIGHT_COMFORTABLE: Final = 56
#: İdarə Paneli widget sətri `grid-auto-rows: 132px`.
DASHBOARD_ROW_HEIGHT: Final = 132

# --------------------------------------------------------------------------- #
# Ümumi komponentlər
# --------------------------------------------------------------------------- #

#: Status nöqtəsi `width/height: 8px`.
STATUS_DOT_SIZE: Final = 8
#: Boş/xəta vəziyyətindəki iri ikon çərçivəsi `76×76, radius 22`.
STATE_ICON_BOX: Final = 76
STATE_ICON_BOX_RADIUS: Final = 22
#: Həmin çərçivədəki ikon `32×32`.
STATE_ICON_SIZE: Final = 32
#: Boş vəziyyət mətninin maksimum eni `max-width: 440px`.
STATE_TEXT_MAX_WIDTH: Final = 440
#: Bildiriş paneli `width: 420px`.
NOTIFICATION_PANEL_WIDTH: Final = 420
#: Dəstək chat paneli `372×486`.
SUPPORT_PANEL_WIDTH: Final = 372
SUPPORT_PANEL_HEIGHT: Final = 486
#: Dəstək düyməsi (FAB) `54×54`.
SUPPORT_FAB_SIZE: Final = 54
#: Dəstək gələnlər qutusunun sol siyahısı (CHAT-1 Faza 6).
#:
#: Ekranın YARISINI tutmur: söhbətin özü (sağ panel) uzun mətn daşıyır və
#: oxunaqlıq sətir uzunluğundan asılıdır. `NOTIFICATION_PANEL_WIDTH`-dən
#: (420) dar seçilib, çünki bu panel ekranın İÇİNDƏDİR, üzən deyil.
SUPPORT_INBOX_LIST_WIDTH: Final = 340
#: Siyahı sətri: üç sətir mətn (ad, filial·vəzifə, önizləmə) + daxili boşluq.
SUPPORT_ROW_HEIGHT: Final = 76
#: Detal paneli (developer, ERP) `width: 400px`.
DETAIL_PANEL_WIDTH: Final = 400

# --------------------------------------------------------------------------- #
# Kiosk (PIN / işçi ekranı)
# --------------------------------------------------------------------------- #

#: PIN indikator dairəsi.
PIN_DOT_SIZE: Final = 18
#: 3×4 klaviatura düyməsi — toxunma hədəfi (bölmə 9: minimum 44px).
KEYPAD_BUTTON_SIZE: Final = 88
#: Mətn düymələri ('Təmizlə', 'Sil') — etiket kvadrata sığmır.
KEYPAD_TEXT_BUTTON_WIDTH: Final = 124

#: Kataloq cədvəllərində əməliyyat sütunu ('Redaktə' + 'Aktivləşdir').
#: Ölçü ƏN UZUN kombinasiyaya görə seçilib: dar sütunda ikinci düymənin
#: etiketi kəsilir və istifadəçi nəyə basdığını görmür.
CATALOG_ACTION_COLUMN_WIDTH: Final = 250
KEYPAD_SPACING: Final = 16

# --------------------------------------------------------------------------- #
# Tipoqrafiya (maketdəki konkret ölçülər)
# --------------------------------------------------------------------------- #
# `tokens.py`-dakı şkala 11/13/15/19/26-dır; maket aralıq dəyərlər də işlədir
# (13.5px naviqasiya, 12.5px köməkçi mətn). Qt tam ədəd gözlədiyi üçün
# yuvarlaqlaşdırılır — fərq gözlə seçilmir, lakin mənbə burada qeyd olunur.

#: Naviqasiya maddəsi — maketdə 13.5px.
FONT_NAV_ITEM: Final = 13
#: Səhifə başlığı.
#:
#: DESIGN.MD REDİZAYNI: 17 → 22. Referansların dördü də (`dashboard.jpg`,
#: `tasks.jpg`, `notification.jpg`, `Login screen.jpg`) səhifə başlığı ilə
#: kart başlığı arasında AYDIN sıçrayış qoyur — 17px kart başlığından (15px)
#: cəmi 2px böyük idi, yəni iyerarxiya faktiki olaraq yox idi və istifadəçi
#: hansı mətnin ekranın adı olduğunu formadan oxuya bilmirdi.
FONT_PAGE_TITLE: Final = 22
#: Kart/bölmə başlığı — səhifə başlığından bir pillə aşağı (referanslarda 15px).
FONT_CARD_TITLE: Final = 15
#: Köməkçi/solğun mətn — 12.5px.
FONT_CAPTION: Final = 12
#: Bölmə etiketi (böyük hərflər) — 11px.
FONT_SECTION_LABEL: Final = 11
#: Boş vəziyyət başlığı — 20px.
FONT_STATE_TITLE: Final = 20
#: Kiosk başlığı — 28px.
FONT_KIOSK_TITLE: Final = 28

#: Bölmə etiketindəki hərf aralığı.
#: QSS bunu dəstəkləmir, `QFont.setLetterSpacing` ilə verilir (piksel olaraq).
#:
#: DESIGN.MD REDİZAYNI: 1.3px (0.12em) → 0.66px (0.06em). Referanslarda
#: (`navbar.jpg` «Menu»/«Group», `status card UI design.jpg` «TEAM»/«PIPELINES»)
#: böyük-hərfli etiket AZ aralıqlıdır: 0.12em Azərbaycan hərflərində (Ə, Ğ, Ş)
#: sözü dağıdır, çünki onların diakritikası onsuz da əlavə optik boşluq yaradır.
SECTION_LABEL_LETTER_SPACING: Final = 0.66

__all__ = [name for name in dir() if name.isupper()]
