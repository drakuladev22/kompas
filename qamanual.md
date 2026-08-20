# QA-FULL: TAM AVTOMATLAŞDIRILMIŞ MANUAL-TƏRZ QA — SIFIRDAN

Bu, kod-oxuma auditi DEYİL. Tətbiqi FAKTİKİ İŞƏ SAL, hər ekranı, hər
düyməni, hər iş-axınını REAL SINAQDAN KEÇİR — insan QA mütəxəssisi kimi.
Tapılan HƏR problemi AVTOMATİK düzəlt, yenidən sına, təmiz çıxana qədər
təkrarla. Mənim buna vaxtım yoxdur — sən tam icra et.

===============================================================================
QIRMIZI XƏTT
===============================================================================
Mövcud işləyən funksionallığı SİLMƏ — yalnız tapılan konkret bug-ları
düzəlt, minimal dəyişikliklə.

===============================================================================
FAZA 0 — TEST İNFRASTRUKTURU (BİR DƏFƏLİK QURULUM)
===============================================================================

**Agentlər (varsa təkrar yaratma):**

--- performance-profiling-engineer ---
---
name: performance-profiling-engineer
description: Proqramın niyə yavaş/ağır işlədiyini konkret ölçərək tapır,
  kök-səbəbi düzəldir.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: opus
---
Sən Senior Performance Engineer-sən. "Yavaşdır" demə — HƏR əməliyyatı
ÖLÇ (millisaniyə ilə), ən yavaş 10 əməliyyatı tap, hər birinin KÖK-
SƏBƏBİNİ (N+1 DB sorğusu, lazımsız təkrar-render, sinxron şəbəkə çağırışı,
optimallaşdırılmamış şəkil/model yükləməsi, yaddaş sızması) müəyyənləşdir
və düzəlt.

`/agents` ilə təsdiqlə.

**Ölçmə alətləri qur (mövcuddursa təsdiqlə):**
1. Python `cProfile`/`time.perf_counter()` ilə hər əsas əməliyyatın
   (ekran açılışı, DB sorğusu, Face Control emalı, export generasiyası)
   icra vaxtını ölçən sadə bir "timing decorator" qur, kritik
   funksiyalara tətbiq et.
2. DB sorğu-sayını izləyən sadə bir sayğac (bir ekran açılanda neçə
   sorğu gedir? — N+1 problemi buradan tapılır).
3. Yaddaş istifadəsini (`tracemalloc` və ya oxşar) izləyən sadə bir
   yoxlama, uzun-sessiya testində istifadə üçün.

--- e2e-test-engineer ---
---
name: e2e-test-engineer
description: pytest-qt ilə hər ekranı, hər düyməni, hər iş-axınını
  sistemli sınayır — insan QA kimi.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: opus
---
Sən Senior QA Automation Engineer-sən (Qt/pytest-qt təcrübəli). Hər
ekranı, hər widget-i REAL sına — təxmin etmə, kodu oxuyub "işləyər"
demə, FAKTİKİ İCRA ET. Tapdığın hər bug-ı HƏMİN AN düzəlt, yenidən
sına, təsdiqlə. AXTARIŞ MƏHDUDİYYƏTİ: YALNIZ src/, tests/-də işlə.

--- crash-stability-engineer ---
---
name: crash-stability-engineer
description: Çökmə, donma, stress-testlər aparır, sabitlik problemlərini
  düzəldir.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: opus
---
Sən Senior Reliability Engineer-sən. Tətbiqi qəsdən "sındırmağa" çalış —
sürətli klik, qəribə input, kəsilən şəbəkə. Hər tapılan çökmə/donmanı
kök-səbəbindən düzəlt (səthi try/except ilə ÖRTMƏ).

`/agents` ilə təsdiqlə.

**Qoruyucu infrastruktur qur (mövcuddursa təsdiqlə, yoxdursa əlavə et):**

1. **Qlobal exception tutucusu:** `main.py`-də (və ya tətbiqin giriş
   nöqtəsində) HEÇ bir exception-un səssizcə itməməsi üçün qlobal hook
   qur — hər tutulan xəta tam traceback ilə `crash.log`-a yazılsın,
   İSTİFADƏÇİYƏ aydın mesaj göstərilsin (mövcud error-handling pattern-i
   varsa ONU genişləndir).
2. **Donma (freeze) aşkarlanması:** Əsas thread-i izləyən bir "heartbeat"
   mexanizmi qur (`QTimer` ilə, hər 500ms bir "canlıyam" siqnalı) — 3
   saniyədən artıq siqnal gəlməzsə, bu, DONMA kimi qeyd olunsun (test
   mühitində).
3. **Headless test rejimi:** `QT_QPA_PLATFORM=offscreen` mühit-dəyişəni
   ilə tətbiqi ekran açmadan işə salmağı təsdiqlə (sürətli, avtomatlaşdırıla
   bilən test dövrü üçün).

**DAYAN, infrastrukturu göstər, təsdiq gözlə.**

===============================================================================
FAZA 1 — KOD-ƏSASLI FUNKSİYA KƏŞFİYYATI (SƏNƏD OXUMA YOXDUR)
===============================================================================
Heç bir `.md` spesifikasiya faylı OXUMA — onlar silinib/köhnəlib ola
bilər. Bunun əvəzinə BİRBAŞA KODUN ÖZÜNDƏN kəşf et:

1. **Ekranlar:** `src/`-də bütün GUI-sinif təriflərini tap (`QWidget`,
   `QMainWindow`, `QDialog`-dan miras alan bütün siniflər). Hər birinin
   adını, faylını, təxmini interaktiv element sayını (grep ilə
   `.clicked`, `QPushButton`, `QLineEdit` və s. say) çıxar.
2. **Biznes məntiqi:** `src/domain/` (və ya use case-lərin olduğu hər
   qovluqda) bütün use case/servis siniflərini tap — hər birinin adı,
   nə etdiyi (bir cümlə, koddan çıxar).
3. **DB/şəbəkə əməliyyatları:** Supabase-ə/1C-yə/Telegram-a gedən bütün
   funksiya çağırışlarını tap.
4. **Permission flag-ləri:** kodda mövcud bütün `can_*` flag adlarını
   tap (bunlar test zamanı rol-əsaslı görünmə yoxlaması üçün lazımdır).
5. **Naviqasiya strukturu:** hansı ekran hansından açılır (sol menyu/
   keçidlər) — bir "sayt xəritəsi" kimi çıxar.

Bunların hamısını BİR MASTER FUNKSİYA SİYAHISINA yığ: [Ekran/Funksiya] |
[Fayl] | [Nə edir] | [Hansı rol əlçatır] | [Test edilməli əsas hallar
(sən öz mühəndis mühakimənlə müəyyənləşdir — uğurlu keçid, səhv-input,
icazəsiz-çıxış)].

**DAYAN, master siyahının ÜMUMİ SAYINI (neçə ekran, neçə use case, neçə
DB-əməliyyatı) göstər, təsdiq gözlə.**

===============================================================================
FAZA 2 — EKRAN İNVENTARLAŞDIRMASININ DƏQİQLƏŞDİRİLMƏSİ
===============================================================================
Faza 1-də kəşf etdiyin ekran siyahısını GUI-naviqasiya kodunu izləyərək
təsdiqlə/tamamla — hər ekranın hansı menyudan/keçiddən açıldığını,
hansı rolun ona çata bildiyini (kodda `can_*` yoxlamalarını izləyərək)
dəqiqləşdir. Cədvəl kimi göstər: [Ekran] | [Fayl] | [Açan naviqasiya] |
[Əlçatan rollar] | [Faza 1-dən: neçə funksiya/element].
**DAYAN, siyahını göstər, təsdiq gözlə.**

===============================================================================
FAZA 3 — EKRAN-BE-EKRAN SINAQ (AGENT: e2e-test-engineer)
===============================================================================
Faza 2-dəki HƏR ekran üçün, ardıcıl (ən çox istifadə olunandan
başlayaraq):

1. Ekranı REAL aç (headless rejimdə).
2. **Hər interaktiv elementi** (düymə, sahə, dropdown, checkbox) tap və
   sına:
   - Düymə klik edilir → gözlənilən nəticə baş verirmi (bağlantı varmı,
     yoxsa heç nə olmurmu)?
   - Sahəyə düzgün data yazılır → qəbul edilirmi?
   - Sahəyə SƏHV/QƏRİBƏ data yazılır (boş, çox uzun, xüsusi simvollar,
     emoji, mənfi ədəd, SQL-bənzər mətn) → düzgün rədd edilir, aydın
     xəta göstərilirmi, YOXSA ÇÖKÜRMÜ?
   - Permission-gated elementlər fərqli rollarla düzgün görünür/
     gizlənirmi?
3. Tapılan HƏR bug-ı DƏRHAL düzəlt (RED LINE-a əməl edərək), yenidən
   sına, təsdiqlə.
4. Hər ekrandan sonra qısa nəticə: [Ekran] | [Sınanan element sayı] |
   [Tapılan bug sayı] | [Düzəldilən sayı].

**Hər 5 ekrandan sonra DAYAN**, xülasəni göstər, "davam et" gözlə
(token nəzarəti üçün).

===============================================================================
FAZA 4 — MASTER SİYAHININ TAM İCRASI (AGENT: e2e-test-engineer)
===============================================================================
Faza 1-də KODDAN kəşf etdiyin master funksiya siyahısının HƏR sətrini,
bölmə-bölmə, REAL icra et:

- Hər use case/ekranı FAKTİKİ işə sal (təsvir edib "keçər" demə).
- Uğurlu keçid + səhv-input + icazəsiz-çıxış hallarının HAMISINI sına.
- Tapılan HƏR bug-ı DƏRHAL düzəlt, yenidən sına.

Bölmə bitdikcə qısa nəticə göstər: [Bölmə] | [Funksiya sayı] | [Tapılan
bug] | [Düzəldilən]. **Hər bölmədən sonra DAYAN**, "davam et" gözlə.

===============================================================================
FAZA 5 — PERFORMANS ARAŞDIRMASI: "NİYƏ AĞIR İŞLƏYİR?" (AGENT:
performance-profiling-engineer)
===============================================================================
Bu, ayrıca, xüsusi diqqət tələb edən fazadır — "yavaşdır" hissi ilə
kifayətlənmə, KONKRET ÖLÇ:

1. **Açılma vaxtı:** Splash-dan əsas ekrana qədər neçə saniyə? Hansı
   addım (DB bağlantısı? lisenziya check-in? model yükləməsi?) ən çox
   vaxt aparır?
2. **Hər əsas ekranın açılma vaxtı:** 27+ ekranın HƏR birini aç, vaxtı
   ölç, ƏN YAVAŞ 10-u sırala.
3. **DB sorğu-sayı auditi:** bir ekran açılanda NEÇƏ ayrı DB sorğusu
   gedir? 1 ekranda 20+ kiçik sorğu varsa, bu, N+1 problemi ola bilər —
   tək, birləşmiş sorğuya çevir.
4. **Face Control emalı vaxtı:** doğrulama neçə saniyə çəkir? (əvvəlki
   tələbdə max 3 saniyə hədəflənmişdi — buna çatırmı?)
5. **Export/hesabat generasiyası vaxtı:** böyük data ilə (məs. 1000+
   sətirlik Excel) neçə vaxt aparır?
6. **UI thread bloklanması:** hər hansı əməliyyat hələ də əsas thread-i
   bloklayır, YOXSA arxa-plana köçürülüb (əvvəlki threading-işi
   yoxlanılıbmı)?
7. **Yaddaş artımı:** 27 ekranı ardıcıl aç-bağla (30+ dövr), yaddaş
   istifadəsi ARDICIL ARTIRMI (sızma əlaməti)?
8. **Başlanğıc paketinin ağırlığı:** istifadə olunmayan Qt modulları
   (`QtWebEngine` və s.) hələ də paketlənibmi (bax əvvəlki "excludes"
   tələbi)?

Hər tapılan yavaşlığın KÖK-SƏBƏBİNİ (N+1 sorğu, sinxron şəbəkə çağırışı,
optimallaşdırılmamış render, lazımsız təkrar-hesablama) DƏQİQLƏŞDİR VƏ
DÜZƏLT. Düzəltdikdən sonra EYNİ ölçünü TƏKRAR apar, "əvvəl X saniyə,
indi Y saniyə" formatında təsdiqlə.

**DAYAN, ölçmə cədvəlini (əvvəl/sonra) göstər, təsdiq gözlə.**

===============================================================================
FAZA 6 — STRESS VƏ XAOS TESTLƏRİ (AGENT: crash-stability-engineer)
===============================================================================
Tətbiqi qəsdən "sındırmağa" çalış:

1. **Sürətli təkrar-klik:** eyni düyməni 20+ dəfə ardıcıl, sürətli klik
   et (race condition axtar — məs. eyni cərimənin 2 dəfə yaranması, eyni
   açıq-növbənin 2 işçiyə düşməsi).
2. **Ekstremal input:** hər mətn-sahəsinə çox uzun (10,000+ simvol),
   yalnız boşluq, emoji-yığını, RTL/qarışıq-dil mətn yaz.
3. **Şəbəkə kəsilməsi simulyasiyası:** Supabase bağlantısını əməliyyat
   ORTASINDA kəs (məs. mock ilə) → tətbiq aydın xəta göstərirmi, yoxsa
   çökürmü/donurmu?
4. **Paralel əməliyyat:** eyni resursa (məs. eyni açıq növbə) iki
   "eyni-anda" sorğu simulyasiya et.

Hər tapılan çökmə/donma/qeyri-sabitliyi KÖK-SƏBƏBİNDƏN düzəlt (səthi
əhatələmə YOX), yenidən eyni stress-testi işə sal, təsdiqlə.
**DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 7 — TAM REGRESSION (TƏKRAR YOXLAMA)
===============================================================================
Faza 3-6-da düzəlişlər edildiyi üçün, YENİ problem yaranıb-yaranmadığını
yoxlamaq üçün:
1. `pytest` tam paketini yenidən işə sal.
2. Faza 1-dəki master siyahıdan ən yüksək-risk 15-20 funksiyanı (özün
   seç) BİR DAHA icra et.
3. Faza 5-in performans ölçülərini BİR DAHA apar — düzəlişlər regressiya
   yaratmadı mı?
4. Hər hansı REQRESSİYA tapsan, düzəlt, Faza 7-ni təkrarla — TƏMİZ
   çıxana qədər.
**DAYAN, nəticəni göstər.**

===============================================================================
FAZA 8 — YEKUN HESABAT
===============================================================================
1. **Ümumi statistika:** koddan neçə ekran/funksiya/DB-əməliyyatı kəşf
   olundu, neçəsi sınandı.
2. **Funksional bug-lar:** tapılan/düzəldilən sayı, ən ciddi olanlar.
3. **Performans:** əvvəl/sonra müqayisə cədvəli (Faza 5-dən).
4. **Sabitlik:** çökmə/donma tapılıb-tapılmadığı.
5. `git diff --stat`
6. Git-də "qa-full-comprehensive-v1" tag-i ilə commit et.
7. **Aydın, birmənalı YEKUN:** "Tətbiq stabildir və sürətlidir, [N]
   bug düzəldildi, açılma vaxtı Xs-dən Ys-ə düşdü, canlıya çıxmağa
   hazırdır" — VƏ YA hələ nəyin qaldığını dəqiq de.

===============================================================================
ÜMUMİ QAYDA
===============================================================================
- Hər problem tapılanda AVTOMATİK düzəlt, MƏNDƏN İCAZƏ SORUŞMA (yalnız
  faza-sərhədlərində dayan, hər bug üçün yox).
- "Kod belə görünür, işləyir" demə — FAKTİKİ İCRA EDİB TƏSDİQLƏ.
- Əmin olmadığın yerdə "əmin deyiləm" yaz, təxmin etmə.