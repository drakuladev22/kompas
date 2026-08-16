KompasOS-a YENİ bir funksiya əlavə edirəm: FACE CONTROL (Üz Təsdiqi) —
iPhone FaceID məntiqi ilə, PIN-i əvəz etməyən, ona ƏLAVƏ olunan bir
anti-aldatma qatı. Bu, mövcud, artıq işləyən kodun ÜZƏRİNƏ əlavə olunur.
AŞAĞIDAKI TƏSVİR "HEÇ BİR DOLANDIRICILIQ MÜMKÜN OLMASIN" prinsipi ilə
sərtləşdirilib — hər bənd konkret bir aldatma yolunu bağlayır, buna görə
heç bir bəndi keçmə/sadələşdirmə.

===============================================================================
ADDIM 0 — MÖVCUDLUQ YOXLAMASI (HƏR ŞEYDƏN ƏVVƏL, MƏCBURİ)
===============================================================================
Kodda, sxemdə VƏ kompasos.md spesifikasiyasında Face Control-a aid HƏR
HANSI izin (`face_embedding` sütunu, `FaceVerificationUseCase`, enrollment
ekranı və s.) olub-olmadığını yoxla. TAPILSA: onu SİLİB YENİDƏN YAZMA —
mövcud olanı əsas götür, YALNIZ çatışan hissələri (aşağıdakı 9 bənddən
hansı əskikdirsə) ƏLAVƏ ET, mənə "bunlar artıq var idi, bunları əlavə
etdim" kimi dəqiq bildir. TAPILMASA (gözlənilən vəziyyət budur): aşağıdakı
bütün fazaları sıfırdan tikinti kimi icra et.

**QOVLUQ/FAYL YERLƏŞDİRMƏSİ (MƏNDƏN SORUŞMA, ÖZÜN MÜƏYYƏN ET):** Harada
hansı faylın olacağını mən demirəm — əvvəlcə mövcud layihənin qovluq
strukturunu (domain/infrastructure/presentation qatları necə adlanıb,
mövcud use case-lər harada yerləşir, adlandırma konvensiyası nədir) OXU
VƏ ANLA, sonra HƏR yeni Face Control faylını (use case-lər, migration,
GUI ekranları) EYNİ struktura, EYNİ adlandırma qaydasına UYĞUN yerləşdir.
Mövcud strukturdan FƏRQLİ, yeni bir qovluq-nümunəsi İCAD ETMƏ — nə qədər
"məntiqli" görünsə də, məqsəd mövcud layihə ilə 100% tutarlı qalmaqdır.

===============================================================================
QIRMIZI XƏTT
===============================================================================
Mövcud kodda artıq işləyən HEÇ BİR funksiyanı, ekranı, PIN-axınını, mövcud
lockout/audit/timeout-eskalasiya mexanizmlərini SİLMƏ və ya YENİDƏN YAZMA.
Face Control bunları ÇAĞIRARAQ inteqrasiya olunur (kod təkrarlanmır).
Kəsişmə tapsan — YENİSİNİ YARATMA, MÖVCUDU İSTİFADƏ ET.

===============================================================================
MƏRKƏZİ TƏLƏB — DƏYİŞƏ BİLƏN HƏR DƏYƏR ROOT-DAN İDARƏ OLUNMALIDIR
===============================================================================
Aşağıdakı təsvirdə "ROOT PARAMETRİ:" işarəli HƏR dəyər — VƏ tapılıb bura
əlavə edilməyən, amma sənin gördüyün istənilən başqa konfiqurasiya edilə
bilən ədəd/həddi/say — koda hardcode EDİLMİR, mövcud `system_limits`/ROOT
Control Center mexanizminə (`can_manage_system_limits`, YALNIZ Root)
əlavə olunur, hər dəyişiklik audit-lənir. Bunu Faza 5-də (Təhvil-vermə)
bir cədvəl kimi TƏSDİQLƏYƏCƏKSƏN.

===============================================================================
FUNKSİYA TƏSVİRİ — ANTİ-FRAUD SƏRTLƏŞDİRİLMİŞ VERSİYA
===============================================================================

**Konseptual sərhəd (vacib):** Face Control YALNIZ "kioskda duran şəxs
KİMDİR" sualına cavab verir (identity). Kamera Operatoru/iVMS "bu şəxs
FİZİKİ olaraq orda idi/davranışı normaldır" sualına cavab verir
(presence/context). Bunlar FƏRQLİDİR — Face Control Kamera Operatorunun
STEP B/C təsdiqini ƏVƏZ ETMİR, avtomatlaşdırmır. Hər ikisi PARALEL
işləyir. Camera Dashboard-da bunu operator üçün açıq mətnlə izah et.

1. QEYDİYYAT (ENROLLMENT) — NƏZARƏTLİ, SELF-SERVICE DEYİL:
   Yeni işçi yaradılarkən (mövcud, istəyə-bağlı "profil şəkli"
   yükləməsindən TAM AYRI, MƏCBURİ addım), YALNIZ `can_manage_employees`
   sahibi (admin), işçi FİZİKİ OLARAQ ORDA İKƏN, kiosk-dakı veb-kameradan
   bir neçə kadr çəkiliş edir. İşçi bunu ÖZÜ-ÖZÜNƏ edə BİLMƏZ. Foto
   SAXLANMIR — yalnız riyazi təmsil (`face_embedding`, vektor) hesablanıb
   Fernet AES-256 ilə şifrələnərək saxlanılır (mövcud şifrələmə modulunu
   İSTİFADƏ ET). Keyfiyyət-yoxlaması: kadrlar minimum aydınlıq/işıqlandırma
   həddini (**ROOT PARAMETRİ: enrollment keyfiyyət-həddi**) keçmirsə
   "[Yenidən Çək]" təklif olunur.

2. YENİDƏN-QEYDİYYAT MƏHDUDİYYƏTİ:
   Mövcud `face_embedding`-in dəyişdirilməsi EYNİ nəzarətli prosesi tələb
   edir. Köhnə embedding SİLİNMİR, `employees.face_embedding_history`-də
   `REPLACED` statusu ilə arxivlənir, dəyişiklik `audit_logs`-a yazılır.

3. DOĞRULAMA AXINI — İKİ AYRI UĞURSUZLUQ REJİMİ:
   PIN daxil edilir → kamera bir kadr çəkir → yerli (on-device, BULUDA
   GETMİR) embedding-müqayisəsi. 3 nöqtədə tətbiq olunur (PIN-dən DƏRHAL
   SONRA): Morning Check-in STEP A, STEP 1, STEP 2.

   - **NO_FACE_DETECTED:** texniki problem kimi rəftar et, yenidən cəhd
     təklif et. PIN-lockout sayğacına DAXİL EDİLMİR, AYRI saxlanılır.
   - **MISMATCH:** ƏN GÜCLÜ fırıldaqçılıq siqnalıdır. AYRI sayğacda
     izlənilir. İLK DƏFƏDƏN HR_Admin/Store Manager-ə DƏRHAL bildiriş.
     YALNIZ EYNİ MAĞAZANIN digər işçiləri ilə cross-check apar, uyğun
     gələn taparsansa `matched_other_employee_id`-ə yaz.

4. LOCKOUT:
   MISMATCH sayğacı **ROOT PARAMETRİ: MISMATCH-lockout həddinə** (PIN-in
   öz "5 ardıcıl səhv" həddindən AYRI, öz ROOT parametri — Face-mismatch
   daha ciddi siqnal olduğu üçün fərqli/aşağı dəyər ola bilər) çatarsa,
   mövcud PIN TƏHLÜKƏSİZLİYİ lockout MEXANİZMİNİ (müddət/UI) ÇAĞIR (yeni
   mexanizm yazma) — sayğac YUXARIDA deyildiyi kimi AYRI saxlanılır.

5. KAMERA AVADANLIQ NASAZLIĞI:
   Veb-kamera nasazdırsa, sistem SƏSSİZCƏ "yalnız PIN" rejiminə KEÇMİR.
   Mövcud TIMEOUT-eskalasiya mexanizmini ÇAĞIR: HR_Admin/CEO manual
   təsdiqinə göndər, nasazlığı System Health Monitor-a yaz.

6. LIVENESS — RANDOMLAŞDIRILMIŞ:
   Hər doğrulamada TƏSADÜFİ seçilən hərəkət tələb et (göz qırpma/baş
   çevirmə/gülümsəmə — **ROOT PARAMETRİ: aktiv liveness-hərəkətləri
   siyahısı**, Root gələcəkdə bir hərəkəti aktiv/deaktiv edə bilsin).

7. UYĞUNLUQ HƏDDİ (THRESHOLD):
   Bənzərlik həddi — **ROOT PARAMETRİ**, YALNIZ Root dəyişdirə bilsin.

8. İŞDƏN ÇIXARILMA ZAMANI SİLİNMƏ:
   İşçi mövcud "deaktiv et" əməliyyatı ilə deaktiv edildikdə,
   `face_embedding` HƏMİN ANDA avtomatik silinir — MÖVCUD deaktiv-etmə
   use case-inin İÇİNƏ əlavə et.

9. AUDIT:
   Hər doğrulama cəhdi (SUCCESS/NO_FACE_DETECTED/MISMATCH) `face_
   verification_log`-a yazılır.

10. FACE ALIGNMENT (YENİ — KEYFİYYƏT TƏKMİLLƏŞDİRMƏSİ):
    Embedding hesablamazdan ƏVVƏL, kitabxanənin landmark-aşkarlama
    funksiyasından istifadə edərək üzü düzləndir (baş-əyriliyini
    normallaşdır) — bu, tək başına dəqiqliyi əhəmiyyətli artırır, HƏM
    enrollment, HƏM hər doğrulama zamanı tətbiq olunur.

11. ÇOX-KADR ORTA ALMA (YENİ — ENROLLMENT KEYFİYYƏTİ):
    Enrollment zamanı çəkilən bir neçə kadrın (bənd 1) embedding-lərini
    AYRI-AYRI saxlamaq əvəzinə, onların RİYAZİ ORTASINI hesablayıb TƏK bir
    "istinad embedding" kimi saxla — tək kadrdan gələn təsadüfi işıq/açı
    xətasını azaldır.

12. CONFIDENCE SCORE — BİNAR DEYİL, TƏDRİCƏN (YENİ):
    Doğrulama nəticəsini sadəcə uyğun/uyğun-deyil kimi deyil, faktiki
    oxşarlıq faizi (confidence score) kimi hesabla və `face_verification_
    log`-a yaz. **ROOT PARAMETRİ: "aşağı-etibar həddi"** — score bu həddin
    ÜSTÜNDƏ amma tam-uyğunluq həddinin ALTINDadırsa, əməliyyata icazə ver,
    AMMA qeydi "aşağı-etibarlı təsdiq" kimi işarələ (Kamera Operatoru öz
    iVMS-yoxlamasında bunu görüb daha diqqətli ola bilsin).

13. DÖVRİ YENİDƏN-QEYDİYYAT XATIRLATMASI (YENİ):
    **ROOT PARAMETRİ: "yenidən-enrollment tövsiyə intervalı"** (ay) —
    bu müddət keçəndə, işçinin admin-panelindəki profilində "Üz-qeydiyyatı
    köhnəlib, yenilənməsi tövsiyə olunur" xəbərdarlığı göstərilir (insan
    üzü zamanla dəyişir — saqqal, eynək, yaş). Bu, MƏCBURİ BLOKLAMA
    YARATMIR, yalnız admin üçün görünən tövsiyədir.

14. İSTİSNA (EXEMPTION) YOLU — SƏRT QORUMALARLA (YENİ):
    Konkret işçilər üçün (tibbi/fiziki səbəb) Face Control-u PIN-only ilə
    əvəz edən bir istisna mexanizmi lazımdır — AMMA bu, diqqətlə
    qorunmalıdır, əks halda özü bir aldatma-yolu olar:
    - **YALNIZ Root/CEO** təyin edə bilər (adi `can_manage_employees`
      KİFAYƏT ETMİR — bu, çox həssas bir səlahiyyətdir, adi HR-səviyyəli
      admin-dən yuxarı qaldırılır).
    - **MÜVƏQQƏTİDİR, DAİMİ DEYİL:** `system_limits`-də **ROOT PARAMETRİ:
      "istisna maksimum müddəti"** (məs. 90 gün) — bu müddət bitdikdə
      istisna avtomatik LƏĞV OLUNUR, yenidən əsaslandırılmalı olur (sükutla
      əbədi qalmır).
    - **MƏCBURİ KOMPENSASİYA EDİCİ NƏZARƏT:** İstisnalı işçinin HƏR
      giriş/qayıdış təsdiqi avtomatik olaraq mövcud DUAL-CONTROL axınına
      (bölmə 3) düşür — "bir az diqqətli ol" kimi qeyri-müəyyən tövsiyə
      DEYİL, MƏCBURİ ikinci-təsdiq. Bu, PIN-only-nin yaratdığı boşluğu
      konkret şəkildə əvəzləyir.
    - **KOMPENSASİYA SÖNDÜRÜLƏ BİLMƏZ (SEC-020):** yuxarıdakı "MƏCBURİ" sözü
      `DUAL_CONTROL` modulunun aç/bağla vəziyyətindən asılı ola bilməz — ona
      görə bağlantı ŞƏRTİ KİLİDDİR: aktiv istisnası olan kirayəçidə həmin
      modul söndürülə bilmir (əvvəlcə istisnalar ləğv edilməlidir) və modul
      sönükdürsə yeni istisna verilə/uzadıla bilmir; ekranı yan keçən yolla
      yaranmış vəziyyətdə isə təsdiq sükutla keçmir, bənd 5-in manual təsdiq
      axınına düşür.
    - Təyinat/uzatma/ləğv HƏR biri `audit_logs`-a tam yazılır.

15. FEATURE TOGGLE-UN MAĞAZA-SƏVİYYƏLİ İŞLƏMƏSİ (YENİ):
    Mövcud qlobal Feature Toggle mexanizminə (bölmə 3) TOXUNMADAN, Face
    Control modulu ÜÇÜN xüsusi bir genişlənmə: qlobal aç/bağladan ƏLAVƏ,
    ROOT Control Center-də "Face Control aktiv olan mağazalar" çox-seçimli
    sahəsi. Boş buraxılarsa (defolt) — qlobal togglenin dəyərinə tabe olur
    (indiki davranış DƏYİŞMİR). Seçim edilibsə — YALNIZ seçilmiş mağazalar
    üçün aktivdir, bu, pilot-mərhələli yayımı mümkün edir.

16. MISMATCH → MÖVCUD EXCEPTION ENGINE-Ə BAĞLANTI (YENİ, TƏHLÜKƏSİZLİK
    QEYDİ İLƏ):
    Əgər layihədə artıq (12-funksiya genişlənməsindən) bir Exception
    Engine mövcuddursa, MISMATCH hadisələrini ORAYA DA yaz (HR-in vahid
    yerdə görməsi üçün) — AMMA **bu, mövcud "İLK DƏFƏDƏN DƏRHAL bildiriş"
    (bənd 3) mexanizmini ƏVƏZ ETMİR, ONA ƏLAVƏ olunur.** Təhlükəsizlik
    səbəbi: Exception Engine-in ümumi siyahısı "sonra baxaram" effektini
    yarada bilər — MISMATCH kimi ən yüksək-təhlükəli siqnal ÖZ təcili
    bildiriş-kanalını itirməməlidir. Exception Engine mövcud deyilsə, bu
    bəndi keç, mənə bildir.

17. LOG-SAXLAMA MÜDDƏTİ (YENİ):
    **ROOT PARAMETRİ: "verification log saxlama müddəti"** (ay, defolt
    12) — bu müddətdən köhnə `face_verification_log` qeydləri gecəlik
    cron (mövcud pattern) ilə SİLİNİR (anonimləşdirmə YOX, tam silmə —
    bu qeydlərdə foto yoxdur, sadəcə nəticə+score, sadə silmə kifayətdir).
    **TƏHLÜKƏSİZLİK TƏSDİQİ:** Bu silmə, mövcud Davranış-Anomaliyası
    baseline hesablamasını (yalnız son 30 günə baxır) POZMUR — 12 aylıq
    saxlama bundan qat-qat genişdir, konflikt yoxdur.

18. DOĞRULAMA SÜRƏTİ MONİTORİNQİ — TƏHLÜKƏSİZLİYİ ZƏİFLƏTMƏMƏK ŞƏRTİ İLƏ
    (YENİ):
    **ROOT PARAMETRİ: "maksimum gözlənilən doğrulama vaxtı"** (saniyə) —
    doğrulama bu müddətdən çox çəkərsə, System Health Monitor-a (mövcud)
    performans-xəbərdarlığı yazılır (kiosk PC-nin gücü kifayət etmirmi?).
    **KRİTİK TƏHLÜKƏSİZLİK QAYDASI:** Bu monitorinq HEÇ VAXT avtomatik
    olaraq keyfiyyət-parametrlərini (kadr sayı, alignment, threshold)
    "sürətləndirmək" naminə ZƏİFLƏTMİR — yalnız hardware/performans
    diaqnostikası üçündür. Sürət problemi tapılsa, HƏLL YOLU hardware
    təkmilləşdirmə/kod-optimallaşdırma olmalıdır, TƏHLÜKƏSİZLİK-GÜZƏŞTİ
    DEYİL.

===============================================================================
KİTABXANA QƏRARI (QƏTİ, ARTIQ ARAŞDIRILIB — FAZA 3-DƏ BUNU TƏTBİQ ET)
===============================================================================
`face_recognition` (Dlib əsaslı) İSTİFADƏ ET — bu, artıq qərarlaşdırılıb,
Faza 3-də yenidən müzakirə/seçim ETMƏ. Səbəb: (1) Boost Software License
— tam kommersiya-satış-təhlükəsiz (InsightFace-in əksinə, o, kommersiya
istifadə üçün AYRICA lisenziya tələb edir — sizin məhsulunuz satılacağı
üçün bu, real hüquqi risk yaradardı), (2) CPU-da işləyir, GPU tələb etmir
(mağaza PC-lərində adətən GPU yoxdur), (3) yüngül, PyInstaller
paketləməsini ağırlaşdırmır (DeepFace-in TensorFlow asılılığından
FƏRQLİ), (4) 99.38% LFW dəqiqliyi bu istifadə-halı üçün kifayət qədər
yüksəkdir.

===============================================================================
THRESHOLD-UN İLKİN DƏYƏRİ — PILOT-ƏSASLI TƏNZİMLƏMƏ (QEYD, KOD DEYİL)
===============================================================================
Bənzərlik-həddinin (bənd 7) VƏ aşağı-etibar həddinin (bənd 12) "düzgün"
ilkin ədədini indi TƏXMİN ETMƏYƏ ÇALIŞMA — məntiqli bir defolt dəyər
qoy (kitabxananın öz sənədləşməsindəki tövsiyə olunan defolt) və mənə
"bu, ilkin dəyərdir, pilot mağazada real şəraitdə tənzimlənməlidir"
kimi AÇIQ bildir. Bu, kod-problemi deyil, empirik/əməliyyat qərarıdır.

===============================================================================
FAZA 0 — AGENTLƏRİ QUR (AVTOMATİK, TƏKRARSIZ)
===============================================================================
.claude/agents/ qovluğunu YOXLA. Hər aşağıdakı agent üçün: ARTIQ MÖVCUDDURSA
YENİDƏN YARATMA, olduğu kimi İSTİFADƏ ET. YOXDURSA yarat:

--- schema-migration-engineer (mövcud deyilsə yarat) ---
---
name: schema-migration-engineer
description: Yeni cədvəlləri miqrasiya kimi yazır və tətbiq edir.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: opus
---
Sən Senior Database Engineer-sən. Miqrasiyaları yaz, tətbiq et, test et.
Mövcud cədvəlləri SİLMƏ/DƏYİŞDİRMƏ, yalnız ƏLAVƏ et.

--- face-control-engineer (YENİ, yoxdursa yarat) ---
---
name: face-control-engineer
description: Face Control-un domain/backend məntiqini (enrollment,
  verification, lockout, threshold) qurur — anti-fraud correctness
  yüksək-riskli sahə.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: opus
---
Sən Senior Backend Engineer-sən (biometrik/təhlükəsizlik sistemləri
təcrübəli). Yuxarıdakı 9 bəndi tam, "heç bir dolandırıcılıq mümkün
olmasın" prinsipi ilə tətbiq et. HƏR "ROOT PARAMETRİ" işarəli dəyəri
system_limits-ə yaz, hardcode ETMƏ. Mövcud PIN-lockout/timeout-eskalasiya
kodunu ÇAĞIR, təkrar yazma. Yeni faylları YARATMAZDAN ƏVVƏL mövcud
qovluq-strukturunu/adlandırma konvensiyasını OXU, HƏR yeni faylı ONA
UYĞUN yerləşdir — yeni struktur icad etmə.

--- face-control-ui-engineer (YENİ, yoxdursa yarat) ---
---
name: face-control-ui-engineer
description: Face Control-un GUI hissəsini (enrollment ekranı,
  verification overlay) qurur.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: sonnet
---
Sən PySide6 Frontend Engineer-sən. Mövcud dizayn sisteminə (dark/light,
Azərbaycan dili) tam uyğun enrollment + verification ekranlarını qur.
Mövcud PIN klaviaturası strukturunu SAXLA, yalnız yeni addımı ƏLAVƏ et.
Yeni ekran fayllarını YARATMAZDAN ƏVVƏL mövcud GUI qovluq-strukturunu
(ekranlar harada saxlanılır, adlandırma qaydası) OXU, ONA UYĞUN yerləşdir.

`/agents` ilə hamısının qeydiyyatdan keçdiyini (mövcud olanlar daxil)
təsdiqlə. ADDIM 0-a (mövcudluq yoxlaması) qayıt, sonra FAZA 1-ə keç.

===============================================================================
FAZA 1 — SCHEMA — AGENT: schema-migration-engineer
===============================================================================
Miqrasiya yaz və tətbiq et:
- `employees.face_embedding` (encrypted)
- `employees.face_enrolled_at`
- `employees.face_embedding_history` (arxiv, REPLACED statuslu)
- `face_verification_log` (id, employee_id, timestamp, result
  [SUCCESS/NO_FACE_DETECTED/MISMATCH], trigger_context, matched_other_
  employee_id [nullable], lockout_triggered [bool])
- MISMATCH sayğacı üçün ayrı sahə/cədvəl (mövcud PIN-lockout strukturuna
  bax, uyğun pattern seç)
- `face_verification_log`-a `confidence_score` sütunu (bənd 12)
- `employees.face_embedding` — İZAH: bu, enrollment zamanı çəkilən bir
  neçə kadrın ORTA embedding-i olacaq (bənd 11), tək kadr deyil
- `system_limits`-ə: enrollment keyfiyyət-həddi, MISMATCH-lockout həddi,
  aktiv liveness-hərəkətləri, bənzərlik-həddi, aşağı-etibar həddi (bənd
  12), yenidən-enrollment tövsiyə intervalı (bənd 13), istisna maksimum
  müddəti (bənd 14), verification-log saxlama müddəti (bənd 17),
  maksimum gözlənilən doğrulama vaxtı (bənd 18) — 9 YENİ ROOT parametri
- `face_control_exemptions` (employee_id, granted_by [Root/CEO], reason,
  granted_at, expires_at, status [ACTIVE/EXPIRED/REVOKED]) — bənd 14
- `system_limits`-ə (və ya ROOT Control Center-in mövcud Feature Toggle
  cədvəlinə) Face Control üçün "aktiv mağazalar" siyahı-sahəsi — bənd 15

Test et. **DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 2 — DOMAIN LAYER — AGENT: face-control-engineer
===============================================================================
`FaceEnrollmentUseCase`, `FaceVerificationUseCase`, `FaceReEnrollmentUseCase`
— mövcud Morning Check-in/STEP1/STEP2 use case-lərini DƏYİŞDİRMƏDƏN,
ÇAĞIRARAQ inteqrasiya et. Mövcud "işçini deaktiv et" use case-inə silmə-
çağırışını əlavə et.

ƏLAVƏ (bənd 14-18):
- `FaceControlExemptionUseCase` — YALNIZ Root/CEO çağıra bilər, müddət-
  bitmə cron-yoxlaması (mövcud pattern), istisnalı işçinin HƏR təsdiqini
  mövcud Dual-Control axınına (bölmə 3) ƏLAVƏ EDƏN inteqrasiya.
- MISMATCH-ı mövcud Exception Engine-ə YAZ (VARSA — kod bazasında axtar,
  yoxdursa bu addımı keç, mənə bildir) — mövcud dərhal-bildiriş
  mexanizmini ƏVƏZ ETMİR, ONA ƏLAVƏ olaraq.
- Log-saxlama-müddəti cron-təmizləməsi (mövcud cron pattern).
- Doğrulama-vaxtı ölçümü + System Health Monitor-a yazma (mövcud modul).

Test yaz — MISMATCH→dərhal-bildiriş, NO_FACE→sayğaca-daxil-olmama,
kamera-nasazlığı→eskalasiya, istisnalı-işçi→Dual-Control-a düşməsi,
müddəti-bitmiş-istisna→avtomatik-ləğv. **DAYAN, nəticəni göstər, təsdiq
gözlə.**

===============================================================================
FAZA 3 — INFRASTRUCTURE — AGENT: face-control-engineer
===============================================================================
Yuxarıdakı "KİTABXANA QƏRARI" bölməsinə görə `face_recognition` (Dlib)
əlavə et, `requirements.txt`-ə yaz, PyInstaller hiddenimports qeyd et.
Bu, qəti qərardır — alternativ kitabxana təklif etmə.
**DAYAN, quraşdırmanın uğurlu olduğunu (import test) təsdiqlə, nəticəni
göstər, təsdiq gözlə.**

===============================================================================
FAZA 4 — GUI — AGENT: face-control-ui-engineer
===============================================================================
Enrollment ekranı (yalnız admin girişində) + Verification overlay
(randomlaşdırılmış liveness göstəricisi ilə) + Camera Dashboard-a
izahedici qeyd + **İstisna İdarəetməsi ekranı (yalnız Root/CEO girişində
— işçi seç, səbəb yaz, müddət göstərilir, "[Ləğv Et]" seçimi)** +
**ROOT Control Center-ə Face Control mağaza-seçimi sahəsi (bənd 15)**.
Test et (dark/light). **DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 5 — TƏHVİL-VERMƏ
===============================================================================
1. `git diff --stat` — heç nə silinməyib təsdiqlə.
2. Tam axını simulyasiya et (enroll→verify→MISMATCH/NO_FACE→kamera-
   nasazlığı→deaktiv-etmə-silinməsi).
3. **ROOT-PARAMETR CƏDVƏLİ:** bütün 9 "ROOT PARAMETRİ" dəyərinin
   system_limits-də olduğunu, hardcode qalmadığını cədvəl kimi göstər —
   ilkin dəyərlərin pilot-əsaslı tənzimlənməli olduğunu QEYD ET.
4. Git-də "face-control-hardened-v1" tag-i ilə commit et.
5. Yekun hesabat: 18 bənddən (9 anti-fraud + 9 keyfiyyət/təhlükəsizlik-
   təkmilləşdirməsi) hansı tam/qismən.

QAYDA: Hər fazadan sonra DAYAN, mən "davam et" deməyincə növbətiyə keçmə.
