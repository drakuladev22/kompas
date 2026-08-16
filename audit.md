Layihədəki BÜTÜN `.md` fayllarını (əsas spesifikasiya + bütün əlavə-
funksiya promptları, harada saxlanılırsa — layihə kökü, `docs_archive/`
və s.) oxu, real kodla çarpaz-yoxla, VƏ mənə tam bir HESABAT ver. Bu,
YALNIZ ANALİZDİR — heç nəyi indi düzəltmə, sadəcə tap və göstər, mən
sonra hansını düzəltmək istədiyimi seçəcəm.

===============================================================================
QIRMIZI XƏTT
===============================================================================
Bu tapşırıqda HEÇ BİR fayl/kod YAZMA/DƏYİŞDİRMƏ — yalnız oxu, analiz et,
hesabat ver.

===============================================================================
ADDIM 1 — BÜTÜN .MD FAYLLARINI TAP
===============================================================================
Layihə kökündə, `docs_archive/` qovluğunda (əgər varsa) və digər ağla-
batan yerlərdə bütün `.md` fayllarını tap (`find . -name "*.md"` tipli
axtarışla). Onların tam siyahısını mənə göstər (fayl adı + təxmini
mövzu, bir cümlə).

===============================================================================
ADDIM 2 — FAYLLAR ARASI ZİDDİYYƏT AXTARIŞI (ƏN VACİB)
===============================================================================
Bu layihə zaman ərzində bir neçə DÜZƏLİŞ keçib (məs. Root/CEO iyerarxiya
prioriteti səhv-idi-sonra-düzəldi, lisenziya modeli tier-sistemindən
tək-sistemə keçdi, POS icazələri 1C-inteqrasiyalı idi-sonra 1C-siz oldu).
Fərqli `.md` fayllar FƏRQLİ VAXTLARDA yazıldığı üçün, KÖHNƏ faylda hələ
DÜZƏLİŞDƏN ƏVVƏLKİ (artıq səhv sayılan) versiya qala bilər. Bunu tap:
- Eyni mövzuda (məs. Root/CEO iyerarxiyası, lisenziya modeli, permission
  kataloqu) fərqli fayllarda BİR-BİRİNƏ ZİDD ifadələr axtar.
- Tapılan hər ziddiyyət üçün: [Mövzu] | [Fayl A-nın dediyi] | [Fayl B-nin
  dediyi] | [Sənin fikrincə hansı DOĞRUDUR, niyə] formatında göstər.

===============================================================================
ADDIM 3 — SPESİFİKASİYA vs KOD (İKİ İSTİQAMƏTLİ)
===============================================================================
1. **Spesifikasiyada VAR, kodda YOXDUR:** `.md` fayllarında təsvir
   olunan, amma kodda (use case, schema, GUI) tapılmayan funksiyaları
   siyahıya al.
2. **Kodda VAR, spesifikasiyada YOXDUR:** Kodda mövcud olan, amma heç
   bir `.md` faylda təsvir olunmayan funksionallıq varsa, onu da göstər
   (bu, gələcəkdə "niyə bu belədir?" sualının cavabsız qalmaması üçündür).

===============================================================================
ADDIM 4 — MƏNTİQİ BOŞLUQLAR (SPESİFİKASİYANIN ÖZÜNDƏ)
===============================================================================
Fayllardakı yazılmış qaydaların ÖZÜNDƏ (kodla müqayisə etmədən, sadəcə
məntiqi oxuyaraq) boşluq/ziddiyyət/tərif-olunmamış-davranış axtar:
- Bir qaydanın "kim edə bilər" dediyi ilə başqa yerdə "kim edə bilməz"
  dediyi üst-üstə düşməyən yerlər.
- Bir prosesin (məs. bir iş-axını) "sonra nə olur" sualının cavabsız
  qaldığı yerlər.
- ROOT PARAMETRİ kimi işarələnmiş, amma hansı fayldasa "hardcode
  edilə bilər" kimi səhvən yazılmış yerlər.

===============================================================================
ADDIM 5 — İRƏLİYƏ-BAXAN TÖVSİYƏLƏR
===============================================================================
Bütün bu materialı (bütün `.md` fayllar + kod) oxuduqdan sonra, sənin
öz mühəndis fikrincə, məntiqi olaraq ƏLAVƏ OLUNMASI DƏYƏRLİ olan, amma
HEÇ BİR faylda hələ YAZILMAYAN 3-5 funksiya/təkmilləşdirmə təklif et —
niyə dəyərli olduğunu qısaca izah et. Bunlar TƏKLİFDİR, indi tikmə.

===============================================================================
YEKUN HESABAT FORMATI
===============================================================================
1. Tapılan bütün `.md` fayllarının siyahısı
2. Fayllar-arası ziddiyyətlər (cədvəl)
3. Spesifikasiya↔Kod uyğunsuzluqları (iki istiqamətli, cədvəl)
4. Spesifikasiyanın öz məntiqi boşluqları (siyahı)
5. İrəliyə-baxan 3-5 tövsiyə

QAYDA: Bitirdikdən sonra DAYAN, heç nə dəyişdirmə — yalnız hesabatı göstər,
mən hansı maddələri düzəltmək/tikmək istədiyimi sonra seçəcəm.
