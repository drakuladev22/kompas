KompasOS-un BÜTÜN ekranlarının VİZUAL dizaynını `design_reference/`
qovluğundakı skrinşotlara əsasən yenidən qururam. 3 SƏRT QAYDA var —
bunlardan HEÇ BİRİ pozulmamalıdır.

===============================================================================
3 SƏRT QAYDA (BUNLAR MÜZAKİRƏ EDİLMİR)
===============================================================================

1. **RƏNGLƏR SABİTDİR, SKRİNŞOTLARDAN GƏLMİR:** Proqramın DAXİLİ dizaynının
   yeganə rəng-palitrası: Deep Navy (`#0B1D3A`) + Amber (`#F5A623`) —
   bunlar bütün ekranlarda İSTİFADƏ OLUNMALIDIR (bu, layihənin ƏVVƏLKİ,
   əsas brend-rəngləridir). **DİQQƏT — QARIŞDIRMA:** Turkuaz/Yaşıl
   (`#0D3B3B`/`#2DD4BF`/`#34D399`) palitrası YALNIZ loqoya aiddir (icon/
   splash-screen loqosu) — proqramın DAXİLİNDƏKİ ekranlara (Dashboard,
   cədvəllər, düymələr və s.) TƏTBİQ EDİLMİR, bunu qarışdırma. `design_
   reference/`-dəki şəkillərin ÖZ rənglərini (əgər fərqlidirsə) KÖPYALAMA
   — YALNIZ onların LAYOUT/STRUKTUR/KOMPONENT-TƏRZİNİ (kart-formaları,
   boşluq-nisbətləri, tipoqrafiya-iyerarxiyası, ikon-stili) çıxar,
   rənglərini Navy/Amber palitramızla ƏVƏZLƏ.

2. **HEÇ BİR FUNKSİYA İTMƏMƏLİDİR — BU, YALNIZ VİZUAL DƏYİŞİKLİKDİR:**
   Hər ekranın mövcud BÜTÜN sahələri, düymələri, permission-əsaslı
   görünmə-qaydaları ("GÖRMƏK=SƏLAHİYYƏTİN OLMASI"), data-bağlantıları
   (`.connect()` siqnalları) — hamısı EYNİ QALMALIDIR. Sən dizaynı
   YENİDƏN QURURSAN, FUNKSİYANI YOX. Redizayn edərkən hər hansı bir
   sahə/düymə "yeni dizaynda yaraşmır" deyə ÇIXARILA BİLMƏZ.

3. **DARK/LIGHT HƏR İKİSİ QORUNUR:** Yeni dizayn hər iki temada işləməli,
   WCAG AA kontrastını qorumalıdır.

===============================================================================
QIRMIZI XƏTT
===============================================================================
Mövcud use case-ləri, siqnal-bağlantılarını, permission-yoxlamalarını
SİLMƏ/DƏYİŞDİRMƏ — YALNIZ QSS/layout-səviyyəli kodu dəyiş.

===============================================================================
ADDIM 0 — REFERANS TƏHLİLİ
===============================================================================
`design_reference/` qovluğundakı HƏR şəkli aç, təhlil et: kart-formaları
(künc-radiusu, kölgə), spacing-ritmi (sıx/geniş), tipoqrafiya-iyerarxiyası
(başlıq/gövdə fərqi necədir), naviqasiya-tərzi, düymə-formaları. Bunu
qısa bir "Dizayn Dili Xülasəsi" kimi yaz (mənə göstər) — sonra bu
xülasəni HƏR ekrana tətbiq edəcəksən.

===============================================================================
ADDIM 1 — FUNKSİONAL SİYAHI ÇIXAR (REDİZAYNDAN ƏVVƏL, TƏHLÜKƏSİZLİK ÜÇÜN)
===============================================================================
Redizayn etməzdən ƏVVƏL, hər ekranın mövcud bütün sahə/düymə/element
siyahısını çıxar (bu, sənin öz "əvvəl" siyahındır — Addım 3-də bunun
hamısının YENİ dizaynda da mövcud olduğunu bu siyahı ilə TƏSDİQLƏYƏCƏKSƏN).

===============================================================================
ADDIM 2 — EKRAN-BE-EKRAN REDİZAYN (BATCH DEYİL)
===============================================================================
Ekranları BİR-BİR (ən çox istifadə olunan/görünən ekranlardan başlayaraq:
İşçi Ana Ekranı → Admin Dashboard → Camera Dashboard → qalanlar) yenidən
qur. HƏR ekrandan sonra:
1. Yeni skrinşotu al.
2. Addım 1-dəki "əvvəl" siyahısı ilə müqayisə et — HƏR element hələ
   mövcuddurmu?
3. Mənə göstər, **DAYAN**, təsdiqimi gözlə, SONRA növbəti ekrana keç.

Bu, "hamısını bir dəfəyə dəyişib sonra problem tapmaq" riskini azaldır —
mən hər addımda görüb, istiqaməti lazım gələrsə erkən düzəldə bilərəm.

===============================================================================
YEKUN (HƏR EKRAN BİTDİKDƏ)
===============================================================================
[Ekran adı] | [Əvvəlki element-sayı] | [Yeni dizaynda mövcud element-
sayı — BƏRABƏR OLMALIDIR] | [Dark/Light təsdiqi] | Skrinşot-cütü yolu.

QAYDA: Addım 0-1-i bitirdikdən sonra DAYAN, "Dizayn Dili Xülasəsi"ni
göstər, təsdiq gözlə. Sonra Addım 2-yə ekran-ekran keç, HƏR ekrandan
sonra DAYAN.
