KompasOS-da NAHAR FASİLƏSİ və ÇAY FASİLƏSİ üçün Root-un birbaşa, xüsusi
idarə etdiyi parametrlər əlavə edirəm: HƏR İKİSİNİN müddəti (dəqiqə) VƏ
gündə neçə dəfə istifadə edilə biləcəyi (say).

===============================================================================
QIRMIZI XƏTT
===============================================================================
Mövcud kodda artıq işləyən heç bir funksiyanı (STEP1/STEP2 axını, mövcud
İcazə Növləri Kataloqu, PENALTY LOGIC) SİLMƏ/YENİDƏN YAZMA — yalnız əlavə et.

===============================================================================
TƏSVİR
===============================================================================

Nahar və Çay fasilələri, ümumi (HR_Admin-in sərbəst əlavə edə biləcəyi)
İcazə Növləri kataloqundan FƏRQLİ olaraq — sistemin TƏMƏLİNDƏ olan, hər
tenant-da mütləq mövcud, YALNIZ ROOT-un idarə etdiyi 4 xüsusi parametrdir:

1. **Nahar Fasiləsi Müddəti** (dəqiqə) — ROOT PARAMETRİ
2. **Nahar Fasiləsi — Gündə Neçə Dəfə** (say) — ROOT PARAMETRİ
3. **Çay Fasiləsi Müddəti** (dəqiqə) — ROOT PARAMETRİ
4. **Çay Fasiləsi — Gündə Neçə Dəfə** (say) — ROOT PARAMETRİ

Bu 4 dəyər `system_limits`-ə (ROOT Control Center) əlavə olunur —
`can_manage_system_limits` (YALNIZ Root, mövcud hardlock qaydasına
görə — CEO-ya belə verilmir) sahibi dəyişdirə bilər. Mövcud, HR_Admin-in
idarə etdiyi ümumi İcazə Növləri Kataloqu (`can_manage_leave_types`)
TOXUNULMUR — Nahar/Çay bundan AYRI, xüsusi bir qatdır.

===============================================================================
SCHEMA (ƏLAVƏ)
===============================================================================
- `system_limits`-ə 4 yeni sətir: `lunch_break_duration_minutes`,
  `lunch_break_daily_count`, `tea_break_duration_minutes`,
  `tea_break_daily_count` (defolt dəyərləri sən təklif et, məs. nahar 45
  dəq/1 dəfə, çay 15 dəq/2 dəfə — amma bunlar sadəcə İLKİN dəyərlərdir,
  Root istənilən vaxt dəyişə bilər).
- `daily_break_usage` (employee_id, date, break_type [LUNCH/TEA],
  count_used) — gündəlik neçə dəfə istifadə edildiyini izləmək üçün.

===============================================================================
MƏNTİQ
===============================================================================

1. STEP1-də (`[İcazə İstəyirəm]`) işçi "Nahar Fasiləsi" və ya "Çay
   Fasiləsi" seçdikdə, `daily_break_usage`-da həmin gün üçün sayğac
   artırılır.

2. **DAVRANIŞ QƏRARI (BUNU MƏNDƏN SORUŞMADAN ÖZÜN SEÇMƏ, AŞAĞIDAKI
   DEFOLTU TƏTBİQ ET):** Əgər işçi gündəlik say-həddini (ROOT PARAMETRİ)
   aşırsa, sistem əməliyyatı BLOKLAMIR (mövcud "aylıq icazə limiti"
   pattern-i ilə EYNİ fəlsəfə — yalnız məlumatlandırıcı) — İşçi Ana
   Ekranında və HR_Admin dashboard-unda "3-cü çay fasiləsi (limit: 2)"
   kimi xəbərdarlıq göstərilir, əməliyyatın özü davam edir. Bu, real
   mağaza operasiyasının qəfil bloklanmasının qarşısını alır.

3. Müddət (dəqiqə) dəyəri — mövcud STEP1/STEP2 PENALTY LOGIC-ə (Delay/
   Total düsturuna) TƏSİR ETMİR (bu, əvvəlcədən qərar verilmiş prinsipdir,
   dəyişdirmə) — yalnız İşçi Ana Ekranında "Nahar Fasiləniz: 45 dəqiqə"
   kimi məlumatlandırıcı göstərici üçün istifadə olunur, VƏ yuxarıdakı
   say-hesablamasında "hansı fasilə hansı gündə artıq bitmiş sayılır"
   müəyyənləşdirmək üçün (əgər STEP2 hələ basılmayıbsa, aktiv sayılır).

===============================================================================
GUI
===============================================================================
1. ROOT Control Center-ə yeni bölmə: "Fasilə Parametrləri" — 4 sahə
   (Nahar müddəti, Nahar sayı, Çay müddəti, Çay sayı), hər biri sadə
   rəqəm-daxiletmə, "[Yadda Saxla]" düyməsi, dəyişiklik audit-lənir.
2. İşçi Ana Ekranında (mövcud), STEP1 seçimi zamanı seçilmiş fasilə
   növünün gündəlik status-göstəricisi ("Bu gün: 1/2 çay fasiləsi
   istifadə edilib").

Test yaz. Nəticəni göstər.

QAYDA: Bitirdikdən sonra DAYAN, mənə nəticəni göstər, təsdiq gözlə.
