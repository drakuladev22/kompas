---
name: kompasos-ui
description: KompasOS interfeys qaydaları — brend palitrası və tokenlər, dark/light + WCAG AA, «görmək = səlahiyyət», UI thread bloklanmır, masaüstü konvensiyaları. PySide6 ekranlarına toxunmazdan əvvəl oxu.
---

# KompasOS — İnterfeys Qaydaları

## 1. Rəng — token-dən, əl ilə YOX

Brend: Deep Navy `#0B1D3A` + Amber `#F5A623`. Turkuaz/yaşıl YALNIZ loqoda,
proqram daxilində YOX.

**Amma rəngi koda əl ilə YAZMA.** `src/presentation/theme/tokens.py`-dən
götür (`BRAND_NAVY`, `BRAND_AMBER` və rejim tokenləri). Səbəb ölçülmüşdür:
`#F5A623` ağ fonda cəmi **2.03:1** verir — iri qrafik element üçün lazım olan
3:1-i belə keçmir. Ona görə light rejimdə eyni heks işlədilmir, token rejimə
görə tənzimlənir. Heksi əl ilə yazsan bu tənzimləməni yan keçirsən.

## 2. Dark VƏ light — hər ikisi məcburi

WCAG AA kontrast hər iki rejimdə. Yoxlayıcı qapıdır:

```bash
.venv/Scripts/python.exe scripts/check_contrast.py --include-high-contrast
```

Bu skript həm `tokens.py` cütlərini, həm də `qss.py`-dəki FAKTİKİ istifadəni
ölçür (`::placeholder`, `:disabled`, `:focus`, `:hover`, sərhədlər). Yalnız
tokenləri yoxlamaq kifayət etmirdi — dörd kontrast qüsuru məhz bu boşluqda
gizlənmişdi. Yeni rəng cütü və ya yeni QSS selektoru əlavə edirsənsə,
skriptin son sətrindən cari sayı oxu.

## 3. «GÖRMƏK = SƏLAHİYYƏTİN OLMASI»

İcazəsi olmayan element **boz DEYİL — tamamilə render olunmur.**

Boz düymə istifadəçiyə sistemin strukturunu açıqlayır və «niyə mən bunu edə
bilmirəm?» sualını yaradır. Yoxdursa sual da yoxdur.

Bu, təhlükəsizlik qatı DEYİL (bax `kompasos-security`) — həqiqi qapı
serverdədir. Bu, yalnız erqonomikadır.

## 4. UI THREAD BLOKLANMIR

DB / şəbəkə / üz-tanıma / export əməliyyatları `QThread` və ya `QThreadPool`
ilə arxa planda işləyir. Hər uzun əməliyyatda progress göstəricisi olur.

**Bloklamadan ƏVVƏL ekranı çəkdir** (UX-1): `flush_ui`
(`presentation/controllers/ui_feedback.py`) — əks halda istifadəçi düyməni
basır və ekran «donmuş» görünür, çünki dəyişiklik hələ render olunmayıb.

**MƏNBƏ:** `docs/performance_notes.md`, `tests/unit/test_session_roundtrips.py`.

## 5. Ekran quruluşu

* Ekranlar yalnız `theme` alır və setter API-si təqdim edir.
* Məlumat İKİ yoldan gəlir: `preview_screens.populate()` (maket) və
  `controllers/screen_data.py` (canlı). **İkisi EYNİ AÇARLARI işlətməlidir** —
  maket öz ad məkanını qursa, uyğunsuzluq maketdə görünməz qalır və yalnız
  istehsalatda üzə çıxır (layihədə məhz bu qüsur olub).
* Yalnız OXUYAN ekran → `screen_data.py`. Həm oxuyub həm YAZAN ekranın ÖZ
  kontrolleri olur — çünki hər yazıdan sonra siyahı yenidən oxunmalıdır.
* Kontroller sessiyanı SAXLAMIR: hər əməliyyat üçün yenisini açır və commit
  edir. Panel saatlarla açıq qala bilər; uzun-ömürlü tranzaksiya bu müddət
  boyu kilid saxlayardı.
* **`Screen` törəməsi İKİNCİ layout QURMUR** (LAYOUT-1) — pozulsa ekran BOŞ
  render olunur. `tests/unit/test_screen_layout_ownership.py` bunu tutur.

## 6. Ölçülər

Dizayn tokenlərindən. Hardcode YOX. Kodda qalan
`design_reference/dashboard.jpg` tipli istinadlar həmin ölçünün HANSI
maketdən gəldiyini deyir — açılacaq fayl deyil, ölçü qərarının sübutudur.

## 7. Masaüstü konvensiyaları

* Sabit sol panel — hamburger menyu YOX (bu, mobil naxışdır).
* Custom title bar.
* Native Aero Snap işləməlidir.
* Fokus halqası yalnız klaviatura ilə gələndə görünür (FOCUS-1,
  `presentation/widgets/buttons.py` → `input_modality_tracker`).
* Tema keçidi giriş-ÖNCƏSİ ekranlara da ötürülür (THEME-1).

## 8. Dil

Bütün istifadəçi mətnləri Azərbaycan dilindədir — yeganə interfeys dili.
Sətri koda birbaşa yazmadan əvvəl mövcud ekranlarda eyni anlayışın necə
adlandırıldığına bax; terminologiya dağılmamalıdır.
