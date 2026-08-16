# KompasOS — Tam Test Checklist-i

Bu sənəd, indiyə qədər spesifikasiya olunmuş/kodlaşdırılmış **bütün modulları**
sistemli şəkildə yoxlamaq üçündür. Hər sətri əl ilə (və ya QA komandanız)
sınayıb, `[ ]` → `[x]` işarələyin. "Gözlənilən Nəticə" sütunu ilə uyğun
gəlməyən hər hal — bir boşluq/xətadır, qeyd edib Claude Code-a göndərin.

**İstifadə qaydası:** Hər bölmə müstəqildir — sırayla, ya da öz prioritetinizə
görə keçə bilərsiniz. `⚠️` işarəli sətirlər — əvvəlki söhbətlərimizdə tapılan,
xüsusilə diqqətli olunmalı "kövrək" nöqtələrdir.

---

## 1) AUTENTİFİKASİYA & GİRİŞ

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 1.1 | Admin login | **İstifadəçi adı + güclü şifrə** daxil et (TƏK ADDIM) | Uğurlu giriş, Dashboard DƏRHAL açılır — ikinci-faktor ekranı ÇIXMAMALIDIR | [ ] |
| 1.2 | Admin login — səhv şifrə | Düzgün istifadəçi adı, səhv şifrə | Rədd edilir, aydın xəta mesajı; cəhd `security.log` + `security_events`-ə düşür | [ ] |
| 1.3 | Şifrə unudulub | Digər admin `[Şifrəni Yenilə]` edir | Müvəqqəti şifrə təyin olunur, ilk girişdə məcburi dəyişdirmə | [ ] |
| 1.4 | PIN handshake | Satıcı düzgün PIN daxil edir | İşçi Ana Ekranı açılır | [ ] |
| 1.5 | PIN lockout | 5 ardıcıl səhv PIN | 15 dəqiqəlik lockout, `security.log`-a yazılır | [ ] |
| 1.6 | ⚠️ Face Control — enrollment | Admin nəzarətində yeni işçi üçün üz-çəkiliş | Foto YOX, yalnız embedding saxlanılır (şifrəli) | [ ] |
| 1.7 | ⚠️ Face Control — işçi öz-özünə enrollment cəhdi | Satıcı özü enrollment ekranına çatmağa cəhd edir | Ekran görünmür/əlçatan deyil (yalnız `can_manage_employees` sahibi) | [ ] |
| 1.7a | ⚠️ Enrollment — admin ÖZ üzünü qeydiyyata salır | `can_manage_employees` sahibi olan HR admini ÖZ üçün enrollment edir | **Rədd edilir** — nəzarətli proses ikinci insan tələb edir; flag sahibi olmaq öz-qeydiyyatına icazə vermir | [ ] |
| 1.8 | Face Control — uğurlu doğrulama | Düzgün PIN + öz üzü | STEP keçir, əməliyyat davam edir; jurnalda nəticə + confidence score var (1.13-ə də bax — zolağın aşağı hissəsi "aşağı-etibarlı" işarələnir) | [ ] |
| 1.9 | ⚠️ Face Control — MISMATCH | Düzgün PIN + BAŞQA işçinin üzü | Əməliyyat bloklanır; HR_Admin-ə **İLK DƏFƏDƏN DƏRHAL** bildiriş (həddi gözləmədən). Kilid isə AYRI hadisədir — `FACE_MISMATCH_LOCKOUT_THRESHOLD` (defolt 3) dolandan sonra düşür, yəni "3-cü cəhddə bildiriş" gözləmək SƏHVDİR | [ ] |
| 1.9a | ⚠️ MISMATCH — cross-check | Eyni mağazanın BAŞQA qeydiyyatlı işçisinin üzü ilə cəhd | Sistem kioskda duran adamın kim olduğunu müəyyən edir və bunu hadisə qeydinə yazır (kimin kimin adından keçməyə çalışdığı bilinsin) | [ ] |
| 1.10 | Face Control — NO_FACE | Kameranın qarşısında heç kim yoxdursa | "Üzünüzü tutun" mesajı; **NƏ PIN sayğacına, NƏ də üz-uyğunsuzluq sayğacına** toxunulmur (texniki haldır, işçinin əleyhinə nəticə doğurmur), sətir yalnız jurnala düşür və `confidence_score` BOŞ qalır | [ ] |
| 1.11 | ⚠️ Face Control — kamera nasazlığı | Veb-kameranı söndür/ayır | SƏSSİZCƏ PIN-only rejiminə keçmir; **MÖVCUD** «manual təsdiq gözləyir» qutusuna (HR_Admin/CEO) düşür — yeni/ayrı bildiriş kanalı YARANMAMALIDIR. Nasazlığın özü ƏLAVƏ olaraq System Health Monitor-a da yazılır | [ ] |
| 1.12 | Liveness randomlaşdırma | Ardıcıl 10+ doğrulama et, tələb olunan hərəkətləri qeyd et | Hərəkət hər dəfə **təsadüfi seçilir** (göz qırpma/baş çevirmə/gülüş) — **ardıcıl iki eyni hərəkət NORMALDIR, qüsur DEYİL**. Meyar: kifayət qədər təkrarda hər üç hərəkət ən azı bir dəfə çıxmalı və sıra ÖNCƏDƏN BİLİNMƏMƏLİDİR | [ ] |
| 1.13 | ⚠️ Face Control — aşağı-etibarlı təsdiq | Üzü qismən dəyişmiş işçi (eynək/saqqal) ilə doğrulama et | Əməliyyata İCAZƏ verilir, lakin qeyd **"aşağı-etibarlı təsdiq"** kimi işarələnir və `face_verification_log`-a faktiki bal (confidence score) yazılır — nəticə binar DEYİL | [ ] |
| 1.14 | Face Control — yenidən-qeydiyyat xatırlatması | ROOT parametrini («yenidən-enrollment tövsiyə intervalı», defolt 12 ay) keçmiş profilə admin panelindən bax | Profildə "Üz-qeydiyyatı köhnəlib, yenilənməsi tövsiyə olunur" xəbərdarlığı görünür; **doğrulama BLOKLANMIR** (yalnız tövsiyədir) | [ ] |
| 1.15 | ⚠️⚠️ İstisna (PIN-only) — kim təyin edə bilər | HR_Admin (`can_manage_employees` var) bir işçiyə Face Control istisnası təyin etməyə cəhd edir | **MÜMKÜN DEYİL** — `can_manage_face_exemptions` ayrıca flag-dir və `hardlock_level = 2` daşıyır, yəni yalnız Root/CEO. UI-da seçim belə görünməməlidir | [ ] |
| 1.16 | ⚠️⚠️ İstisna — məcburi kompensasiya | İstisnalı (PIN-only) işçi ilə giriş/qayıdış təsdiqi et | HƏR təsdiq **avtomatik DUAL-CONTROL axınına** düşür (məcburi ikinci təsdiq) — sükutla adi PIN kimi keçməməlidir. Bu, istisnanın anti-fraud bypass-a çevrilməsinin qarşısını alan yeganə qorumadır | [ ] |
| 1.17 | ⚠️ İstisna — müddət bitməsi | «İstisna maksimum müddəti» (defolt 90 gün) keçən istisnaya bax | İstisna **avtomatik LƏĞV olunur**, işçi yenidən üz-doğrulamasına qayıdır; sükutla əbədi qalmır. Təyinat/uzatma/ləğv hər biri `audit_logs`-dadır | [ ] |
| 1.18 | İstisna — səbəb validasiyası | Səbəb sahəsini boş və ya 10 simvoldan qısa yaz | Rədd edilir (baza `CHECK` məhdudiyyəti güzgülənir) — səbəbsiz istisna yaradıla bilmir | [ ] |
| 1.19 | Face Control — mağaza-səviyyəli əhatə | ROOT Control Center-də "Face Control aktiv olan mağazalar" sahəsinə YALNIZ 1 mağaza seç | Seçilmiş mağazada üz-doğrulaması işləyir, **seçilməyən mağazalarda işləmir** (pilot yayımı). Sahə BOŞ buraxılsa — qlobal toggle-a tabedir, indiki davranış dəyişmir | [ ] |
| 1.20 | Log saxlama müddəti | «Verification log saxlama müddəti»ndən (defolt 12 ay) köhnə qeydlərlə gecəlik cron-u gözlə | Köhnə `face_verification_log` sətirləri **tam SİLİNİR** (anonimləşdirmə yox — qeyddə foto/vektor onsuz da yoxdur). Davranış-Anomaliyası baseline-ı (son 30 gün) POZULMUR | [ ] |

> **(ÇATIŞMAZLIQ DÜZƏLİŞİ — bölmə 1, iki ayrı problem):**
>
> **(a) TOTP.** `1.1`/`1.2` əvvəllər «E-poçt + şifrə + **TOTP** kodu» yoxlayırdı.
> **SEC-016 TOTP-ni tamamilə ÇIXARIB** və giriş identifikatorunu e-poçtdan
> **istifadəçi adına** keçirib (mağaza işçilərinin çoxunun korporativ e-poçtu
> yoxdur). Yəni QA komandası mövcud olmayan bir ekranı axtarıb "2FA işləmir"
> deyə YANLIŞ qüsur yazacaqdı. Giriş indi TƏK ADDIMDIR; e-poçt yalnız ilk
> quraşdırmada soruşulan **bərpa kanalıdır**, giriş vasitəsi deyil.
>
> **(b) Liveness.** `1.12` «hər dəfə FƏRQLİ hərəkət» gözləyirdi. Kod hərəkəti
> `secrets.choice` ilə **kriptoqrafik təsadüfi** seçir — ardıcıl iki eyni
> hərəkət tamamilə normal nəticədir və onu qüsur saymaq düzgün davranışı
> "xəta" kimi qeyd etmək olardı. Əslində TƏLƏB OLUNAN xüsusiyyət
> ÖNCƏDƏN-BİLİNMƏZLİKDİR (növbəti hərəkəti hazırlayıb video/şəkil ilə keçmək
> mümkün olmasın), dövri növbələşmə DEYİL — dövri sıra əksinə proqnozlaşdırıla
> bilən olardı.
>
> **(c) ÇATIŞAN ssenarilər.** `1.13`–`1.20` sətirləri YENİ əlavə olundu:
> `facecontrol.md` bənd 12 (confidence score), 13 (yenidən-enrollment
> xatırlatması), **14 (PIN-only istisnası — ən kritiki, çünki istisna özü
> anti-fraud bypass yoluna çevrilə bilər)**, 15 (mağaza-səviyyəli əhatə) və
> 17 (log saxlama müddəti) kodda MÖVCUDDUR, lakin checklist-də heç bir sətri
> yox idi — yəni sistemin ən həssas qatı test edilmədən qalırdı.

---

## 2) MORNING CHECK-IN & 3-STEP İCAZƏ VERİFİKASİYASI

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 2.1 | Tam Morning Check-in axını | STEP A (PIN+Face) → STEP B (Kamera queue) → STEP C (Təsdiq) | Status `⚪`→`🟡`→`🟢` düzgün keçir | [ ] |
| 2.2 | ⚠️ STEP1 check-in-siz cəhd | `⚪`/`🟡` statusunda "[İcazə İstəyirəm]" basmağa cəhd | Düymə YOXDUR/deaktivdir | [ ] |
| 2.3 | STEP1→STEP2 tam dövrə | İcazə İstə → Mən Qayıtdım → Kamera Təsdiqi | `Requested_Time`/`Verified_Actual_Time` düzgün qeyd olunur | [ ] |
| 2.4 | Cərimə hesablaması | 20 dəqiqə gecikmə ilə qayıt | `Total = Requested + 2×Delay` düzgün hesablanır | [ ] |
| 2.5 | ⚠️ STEP2 timeout | 45 dəqiqədən çox `🟡` statusunda qal | HR_Admin/Store Manager bildirişi + manual həll imkanı (HR_Admin/CEO) | [ ] |
| 2.6 | Dual-Control tetiklənməsi | 30+ dəqiqəlik manual override | HR_Admin/CEO-nun ikinci təsdiqinə göndərilir | [ ] |
| 2.7 | Birləşmiş növbə | Eyni anda giriş+qayıdış sorğuları | BİR növbədə, tip-badge ilə fərqləndirilir | [ ] |
| 2.8 | Mağaza-scoping | 2 fərqli mağazaya təyin olunmuş Kamera Operatoru | Yalnız öz mağazalarının sorğularını görür | [ ] |
| 2.9 | ⚠️ Sıfır-təyinat fail-safe | Heç bir mağazaya təyin edilməmiş operator | Boş növbə + "mağaza təyin edilməyib" mesajı | [ ] |

---

## 3) RBAC & İYERARXİYA

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 3.1 | Hierarchy Guard | Admin başqa Admin-in icazəsinə toxunmağa cəhd | Rədd edilir | [ ] |
| 3.2 | Hierarchy Guard — yuxarı | Admin CEO-nun icazəsinə toxunmağa cəhd | Rədd edilir | [ ] |
| 3.3 | Self-Escalation Guard | Admin özündə olmayan flag-i başqasına verməyə cəhd | Rədd edilir | [ ] |
| 3.4 | Self-Escalation Guard — özünə | Admin özünə əlavə icazə verməyə cəhd | UI-da seçim belə yoxdur | [ ] |
| 3.5 | ⚠️ ANTİ-FRAUD hardlock | `can_verify_returns`-i Store Manager-ə verməyə cəhd (override ilə belə) | Mümkün DEYİL, UI-dan seçilə bilmir | [ ] |
| 3.6 | ⚠️ Dual-Control flag hardlock | `can_approve_dual_control_override`-i Satıcı-ya vermə cəhdi | Mümkün DEYİL | [ ] |
| 3.7 | can_manage_permissions hardlock | CEO yeni permission flag yaratmağa cəhd edir | Mümkün DEYİL (yalnız Root) | [ ] |
| 3.8 | can_manage_positions | CEO yeni rol yaradır | Uğurlu (Root+CEO-ya icazəlidir) | [ ] |
| 3.9 | Custom rol + prioritet | Yeni rol yarat, iyerarxiya pilləsini təyin et | Rol siyahıda görünür, Hierarchy Guard-a tabedir | [ ] |
| 3.10 | GÖRMƏK=SƏLAHİYYƏT | Satıcı hesabı ilə admin panelə giriş cəhdi | Heç bir admin menyusu render olunmur (boz DEYİL, YOX) | [ ] |
| 3.11 | Feature Toggle | Root bir modulu (məs. Shift Swap) söndürür | Modul BÜTÜN istifadəçilər üçün UI-dan yox olur | [ ] |
| 3.12 | Feature Toggle — tarixi data | Söndürülmüş modulun köhnə qeydləri | Toxunulmaz qalır, export-larda görünür | [ ] |
| 3.13 | Kritik modul xəbərdarlığı | Kamera Təsdiqi modulunu söndürməyə cəhd | Əlavə xəbərdarlıq-modalı çıxır (sadə toggle deyil) | [ ] |

---

## 4) CƏRİMƏ İDARƏETMƏSİ

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 4.1 | Manual cərimə (Kamera Op.) | Cərimə Növü seç, foto yüklə, qeyd et | Cərimə yaranır, `source=MANUAL_CAMERA`, status **`PENDING_REVIEW`** | [ ] |
| 4.1a | ⚠️⚠️ Nəşrdən ƏVVƏL görünməzlik | 4.1-dən dərhal sonra həmin işçinin "Cərimələrim" ekranına, sonra Store Manager və HR_Admin görünüşlərinə bax | Cərimə **HEÇ BİRİNDƏ GÖRÜNMÜR** — `PENDING_REVIEW` sətir yalnız icmal ekranındadır. «Dərhal görünməlidir» gözləntisi KÖHNƏDİR (aşağıdakı qeydə bax) | [ ] |
| 4.1b | Aylıq icmal ekranı — səlahiyyət | `can_publish_fines` OLMAYAN admin icmal ekranını açmağa cəhd edir | Ekran render olunmur (GÖRMƏK = SƏLAHİYYƏT); flag sahibi isə bütün filialların həmin ay üçün nəşr gözləyən cərimələrini BİR cədvəldə görür | [ ] |
| 4.1c | ⚠️ Nəşr — tək əməliyyat | İcmalda bir neçə sətrə «Saxla», bir neçəsinə «Sil» qoy, `[Bütün Filiallara Göndər]` bas | Saxlananlar `PUBLISHED`, silinənlər `REVERSED` olur və **HƏMİN AN bütün filiallarda EYNİ VAXTDA** görünür — yarımçıq nəşr OLMAMALIDIR (hamısı bir tranzaksiyada) | [ ] |
| 4.1d | ⚠️ «Sil» fiziki silmə deyil | İcmalda bir sətrə «Sil» ver, sonra audit/bazaya bax | Orijinal qeyd SİLİNMİR — `REVERSED` statusunda qalır, kimin yazdığı və kimin ləğv etdiyi izlənə bilir | [ ] |
| 4.1e | ⚠️⚠️ Etiraz pəncərəsinin başlanğıcı | Cəriməni 2 həftə `PENDING_REVIEW`-də saxla, sonra nəşr et və 72 saatı ölç | Sayğac `created_at`-dan YOX, **`published_at`-dan** başlayır (`appeal_window_closes_at` yalnız nəşr anında dolur) — işçi cəriməni GÖRMƏMİŞ etiraz hüququ bitməməlidir | [ ] |
| 4.2 | ⚠️ Mağaza-scoping | Operator öz mağazasında olmayan işçiyə cərimə yazmağa cəhd | Dropdown-da o işçi görünmür | [ ] |
| 4.3 | Cərimə Növləri kataloqu | Root yeni növ əlavə edir, qiymət təyin edir | Kataloqa düşür, Kamera Op. dropdown-unda görünür | [ ] |
| 4.4 | 72-saat etiraz | İşçi cərimədən 72 saat ərzində etiraz edir | HR_Admin-ə düşür | [ ] |
| 4.5 | Etiraz — REVERSED | HR_Admin etirazı qəbul edir | Status `REVERSED`, orijinal qeyd SİLİNMİR | [ ] |
| 4.6 | ⚠️ Payroll LOCK | Etiraz pəncərəsi hələ açıq cərimə ilə export | Bu cərimə export-dan AVTOMATİK xaric olunur | [ ] |
| 4.7 | Payroll — REVERSED xaric | REVERSED statuslu cərimə ilə export | Export-a düşmür | [ ] |

> **(ÇATIŞMAZLIQ DÜZƏLİŞİ — bölmə 4 köhnə cərimə modelinə görə yazılmışdı):**
> Bu bölmədə `PENDING_REVIEW`, aylıq icmal və `can_publish_fines` **heç bir
> sətirdə keçmirdi** — yəni checklist cəriməni "yaradıldığı an görünür" sayan
> köhnə axını yoxlayırdı və QA komandası `4.1`-dən sonra işçinin ekranına baxıb
> "cərimə görünmür, QÜSUR" yazacaqdı. Faktiki axın: **`PENDING_REVIEW` → aylıq
> icmal → tək `[Bütün Filiallara Göndər]` → `PUBLISHED`**. Səbəb (bax
> `use_cases/fine_review.py` və `migrations/003` başlıqları): operatorun səhvən
> yazdığı cərimə işçiyə çatmadan geri götürülə bilməlidir, «bir andan bütün
> filiallarda» isə texniki tələbdir — yarımçıq nəşr bəzi filialların cəriməni
> görməsi, bəzilərinin görməməsi demək olardı. `4.1a`–`4.1e` sətirləri məhz bu
> axını yoxlamaq üçün əlavə edildi.

---

## 5) NÖVBƏ/ŞİFT İDARƏETMƏSİ

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 5.1 | Shift Matrix planlama | HR_Admin/Admin off-day təyin edir | Təqvimdə görünür, audit-lənir | [ ] |
| 5.2 | ⚠️ Store Manager scoping | Store Manager Shift Matrix planlamağa cəhd | Yalnız Gündəlik Tabel görür, PLANLAMA görmür | [ ] |
| 5.3 | Shift Swap Request | İşçi sorğu göndərir | `PENDING_APPROVAL`, təqvim DƏYİŞMİR | [ ] |
| 5.4 | Swap təsdiqi | HR_Admin/Admin təsdiqləyir | Təqvim avtomatik yenilənir | [ ] |
| 5.5 | Açıq Növbə Bazarı | Admin boş növbəni "açıq" elan edir | Uyğun işçilərə görünür | [ ] |
| 5.6 | ⚠️ Race condition | 2 işçi eyni açıq növbəni eyni anda "götür" edir | Yalnız BİRİ uğurlu olur (DB-lock) | [ ] |
| 5.7 | İş Rejimi yaratma | Root/CEO "9:00-15:00" adlı şablon yaradır | Şablon Shift Matrix dropdown-unda görünür | [ ] |
| 5.8 | Gecikmə hesablaması | İşçi öz İş Rejimindən gec check-in edir | Gündəlik Tabeldə "Gecikib" işarəsi | [ ] |
| 5.9 | Əmək qanunu xəbərdarlığı | Minimum istirahət-saatını pozan növbə təyin et | Xəbərdarlıq göstərilir (bloklamır) | [ ] |
| 5.10 | Overtime izləmə | Normadan çox iş saatı | `overtime_log`-a yazılır, HR_Admin bildirişi | [ ] |
| 5.11 | Gündəlik Tabel ön-doldurma | Tabeli aç | Check-in/leave qeydlərindən AVTOMATİK doldurulub | [ ] |
| 5.12 | Tabel — HR planla müqayisə | Uyğunsuzluq olan gün | HR_Admin-ə xəbərdarlıq | [ ] |

---

## 6) FASİLƏLƏR & İLLİK MƏZUNİYYƏT

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 6.1 | ⚠️ Nahar/Çay ROOT parametri | Root ROOT Control Center-dən müddət+say dəyişir | Dəyişiklik dərhal tətbiq olunur, audit-lənir | [ ] |
| 6.2 | Nahar/Çay — CEO girişi | CEO bu parametrlərə çatmağa cəhd | ƏLÇATAN DEYİL (yalnız Root) | [ ] |
| 6.3 | Gündəlik say-həddi aşımı | 3-cü çay fasiləsi (limit 2) | Bloklanmır, xəbərdarlıq göstərilir | [ ] |
| 6.4 | İllik Məzuniyyət balansı | İşçi öz balansına baxır | Doğru gün-sayı göstərilir | [ ] |
| 6.5 | Məzuniyyət sorğusu | İşçi sorğu göndərir, HR təsdiqləyir | Balansdan düzgün çıxılır | [ ] |
| 6.6 | ⚠️ Qarışdırma yoxlaması | İllik Məzuniyyət ilə gündəlik STEP1/2 arasında | TAM AYRI sistemlərdir, bir-birinə qarışmır | [ ] |

---

## 7) POS İCAZƏ SİYASƏTİ (1C-siz)

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 7.1 | Həddi təyin etmə | İşçiyə max-endirim%/void/refund icazəsi təyin et | Qeyd saxlanılır, audit-lənir | [ ] |
| 7.2 | ⚠️ 1C-bağlantı yoxluğu | Kod bazasında 1C-transaction-sync axtar | HEÇ BİR yeni bağlantı YOXDUR (yalnız sənədləşdirmə) | [ ] |

---

## 8) EXCEPTION ENGINE & ANOMALİYA

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 8.1 | Davranış-baseline hesablanması | 30 günlük check-in datası | Orta vaxt/varians düzgün hesablanır | [ ] |
| 8.2 | Anomaliya aşkarlanması | Baseline-dan kənar check-in vaxtı | `exceptions`-a yazılır | [ ] |
| 8.3 | İstisnalar ekranı | `can_view_exceptions` sahibi ekranı açır | Mənbə-badge, işçi, təfərrüat görünür | [ ] |
| 8.4 | Nəzərdən keçirmə | İstisnanı "Rədd Et"/"Nəzərdən Keçirildi" et | Status yenilənir | [ ] |

---

## 9) SƏNƏD İDARƏETMƏSİ

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 9.1 | Sənəd yükləmə | İşçiyə sənəd + bitmə-tarixi əlavə et | Saxlanılır | [ ] |
| 9.2 | Bitmə-xəbərdarlığı | 30/14/7 gün qala | E-poçt fallback işə düşür | [ ] |
| 9.3 | ⚠️ Shift-bloklama inteqrasiyası | `is_blocking=true` sənədi bitmiş işçini növbəyə təyin et | Xəbərdarlıq göstərilir | [ ] |

---

## 10) ÜNSİYYƏT & PERFORMANS

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 10.1 | Broadcast göndərmə | Bütün filiallara elan göndər | Uyğun İşçi Ana Ekranlarında görünür | [ ] |
| 10.2 | Broadcast — scoped | Yalnız 3 filiala göndər | Yalnız o filiallarda görünür | [ ] |
| 10.3 | Performans forması | Dövri rəy doldur | İşçi tarixçəsində görünür | [ ] |
| 10.4 | ⚠️ Turnover riski — çəkilər | Root çəkiləri ROOT Control Center-dən dəyişir | Hesablama YENİ çəkilərə görə dəyişir | [ ] |
| 10.5 | Turnover — bildiriş ardıcıllığı | Yüksək bal aşkarlanır | ƏVVƏLCƏ Store Manager, SONRA HR_Admin | [ ] |

---

## 11) ANALİTİKA & EXPORT

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 11.1 | Tam Ay export | Standart aylıq Attendance export | Əvvəlki kimi işləyir | [ ] |
| 11.2 | ⚠️ Xüsusi Aralıq export | 01.04–15.04 aralığı seç | Norma/say bu aralığa görə hesablanır | [ ] |
| 11.3 | Pro-Rata | Aralığın ortasında işə başlayan işçi | Norma proporsional hesablanır | [ ] |
| 11.4 | ⚠️ LOCK aralıq-üstü | Aralığın son günü hələ 72saat-açıq cərimə | Yenə də avtomatik xaric olunur | [ ] |
| 11.5 | Pre-Export doğrulama | Şübhəli sətir (deaktiv-amma-görünən işçi) | Qırmızı işarələnir, təsdiq tələb olunur | [ ] |
| 11.6 | Manual düzəliş | HR bir sətirə düzəliş edir (səbəblə) | `export_manual_corrections`-a yazılır | [ ] |
| 11.7 | Dövr-müqayisəsi | Keçən dövrlə fərq göstərilir | Delta düzgün hesablanır | [ ] |
| 11.8 | Rol-filtri | Yalnız "Satıcı" rolunu export et | Digər rollar export-da yoxdur | [ ] |
| 11.9 | Benchmark — reytinq | 21 filialı bir metrikə görə sırala | Düzgün sıralanır, trend-ox görünür | [ ] |
| 11.10 | Benchmark — drill-down | Bir filiala klik et | Onun Gündəlik Tabelinə keçir | [ ] |
| 11.11 | Benchmark — scoping | Store Manager Benchmark-a çatmağa cəhd | ƏLÇATAN DEYİL | [ ] |
| 11.12 | İcra Xülasəsi | Planlaşdırılmış vaxt gəlir | CEO/Root-a e-poçt gedir | [ ] |

---

## 12) MAĞAZA ZİYARƏTİ & İNSİDENT

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 12.1 | Audit checklist doldurma | Bəndləri işarələ, foto yüklə (məcburi olanlar) | Saxlanılır | [ ] |
| 12.2 | ⚠️ Uğursuz bənd → Task | `is_blocking` bənd uğursuz | Task Engine-də avtomatik tapşırıq yaranır | [ ] |
| 12.3 | Audit balı → Dashboard | Checklist bitir | Bal Benchmark Dashboard-da görünür | [ ] |
| 12.4 | İnsident bildirişi | Store Manager insident bildirir | Kateqoriyaya görə düzgün rola marşrutlanır | [ ] |

---

## 13) TOPLU ƏMƏLİYYATLAR

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 13.1 | CSV idxal — təmiz fayl | Düzgün formatlı CSV yüklə | Bütün sətirlər uğurla idxal olunur | [ ] |
| 13.2 | ⚠️ CSV idxal — qismən xəta | Bəzi sətirləri qəsdən səhv et | Uğurlu sətirlər idxal olunur, xətalılar aydın göstərilir | [ ] |
| 13.3 | Mağaza-şablon köçürmə | Yeni filial üçün mövcud filialı əsas götür | Rol/shift-quruluşu köçürülür | [ ] |

---

## 14) ROOT CONTROL CENTER

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 14.1 | System Limits dəyişikliyi | Bir limiti dəyiş, saxla | Dərhal tətbiq olunur, audit-lənir | [ ] |
| 14.2 | ⚠️ Hardcode qalığı yoxlaması | Kodda sabit ədəd axtar (grep) — tapılan HƏR birini üç kateqoriyaya ayır | Sabitin MÖVCUDLUĞU özü qüsur DEYİL. Hər tapılan sabit bunlardan biri olmalıdır: **(1)** struktur təhlükəsizlik zəmanəti (hardlock səviyyələri, vəzifə ayrılığı — bunlar QƏSDƏN soft-coded DEYİL), **(2)** sxem məhdudiyyətinin güzgüsü (məs. minimum uzunluq `CHECK`-i), və ya **(3)** şərhində açıq şəkildə «**fallback** — həqiqi mənbə `system_limits`» yazılmış müvəqqəti dəyər. QÜSUR = bu üç izahdan heç birinə uymayan, şərhsiz sabit, VƏ YA `system_limits`-dəki dəyəri oxumaq əvəzinə sabiti işlədən kod yolu | [ ] |
| 14.2a | Fallback sabitinin real davranışı | `system_limits`-də dəyəri OLAN bir limiti dəyiş, sonra həmin sətri sil | Dəyər varkən **DB dəyəri qalib gəlir** (sabit yox); sətir silinəndə kod sabitə düşür və işləməyə davam edir — yəni sabit yalnız «baza cavab vermədi» halının cavabıdır | [ ] |
| 14.3 | Permission Registry | Root yeni flag yaradır | CEO/Admin-in istifadəsinə açılır | [ ] |

> **(ÇATIŞMAZLIQ DÜZƏLİŞİ — `14.2` icra edilə bilməyən meyar qoyurdu):**
> Sətir əvvəllər «Kodda sabit ədəd axtar (grep) → **HEÇ BİRİ TAPILMIR**»
> gözləyirdi. Bu meyar heç vaxt keçə bilməzdi və QA komandasını qəsdən
> saxlanmış dəyərləri "qüsur" kimi yazmağa aparardı: layihə **qəsdən** fallback
> sabitləri saxlayır (`MIN_APPEAL_SLA_HOURS`, `MAX_UPLOAD_BYTES`,
> `DUAL_CONTROL_THRESHOLD_MINUTES` və s.), çünki baza əlçatmaz olanda sistemin
> "limit oxuya bilmədim" deyib dayanması qəbuledilməzdir. Üstəlik struktur
> təhlükəsizlik zəmanətləri (hardlock səviyyələri, anti-fraud vəzifə ayrılığı)
> **məhz ona görə** hardcoded-dir ki, Feature Toggle və ya limit ekranı ilə
> söndürülə bilməsin. Doğru meyar rəqəmin YOXLUĞU deyil, hər rəqəmin
> ƏSASLANDIRILMASIDIR — yuxarıdakı üç kateqoriya.

---

## 15) LİSENZİYA & DEVELOPER PANEL

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 15.1 | Tenant deaktivasiyası | Developer Panel-dən `[Deaktiv Et]` | Tətbiq bağlanır, LICENSE_INACTIVE ekranı | [ ] |
| 15.2 | Tenant aktivləşdirmə | Eyni düymə ilə geri aç | Tətbiq normal işə düşür, data toxunulmamış | [ ] |
| 15.3 | Offline grace period | İnternetsiz 7-14 gün | LICENSE_UNVERIFIED, tam bloklamır | [ ] |

---

## 16) DİZAYN & UI

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 16.1 | Dark/Light keçidi | Ayarlardan tema dəyiş | Bütün ekranlar düzgün keçir | [ ] |
| 16.2 | ⚠️ İngiliscə mətn axtarışı | Bütün ekranları gəz | Heç bir İngiliscə istifadəçi-mətni QALMAYIB | [ ] |
| 16.3 | WCAG kontrast | Hər iki temada rəng-cütlərini yoxla | 4.5:1 minimum təmin olunur | [ ] |

---

## 17) TƏHLÜKƏSİZLİK

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 17.1 | ⚠️ SQL Injection sınağı | Input sahələrinə `' OR '1'='1` tipli məlumat daxil et | Sistemin sındırılması MÜMKÜN DEYİL | [ ] |
| 17.2 | XSS sınağı | Mətn sahələrinə `<script>` daxil et | HTML-ə escape olunmadan qarışmır | [ ] |
| 17.3 | Şifrələmə | DB-də `face_embedding`/həssas sahələrə birbaşa bax | Şifrəli görünür, açıq mətn deyil | [ ] |

---

## 18) SİSTEM/İNFRASTRUKTUR

| # | Ssenari | Addımlar | Gözlənilən Nəticə | ✓ |
|---|---|---|---|---|
| 18.1 | Avtomatik backup | Bir gecə gözlə | Backup yaranıb | [ ] |
| 18.2 | Restore | "Əvvəlki tarixə Bərpa Et" | Data düzgün bərpa olunur | [ ] |
| 18.3 | Audit Log Viewer | Bir neçə əməliyyatdan sonra bax | Hamısı qeyd olunub | [ ] |
| 18.4 | System Health Monitor | Server bağlantısını kəs | Status dərhal əks olunur | [ ] |

---

## YEKUN QEYD

Bu checklist-i **bir dəfəyə bitirməyə çalışmayın** — bölmə-bölmə (1-18) keçin,
hər bölmədən sonra tapılan boşluqları qeyd edib, uyğun Claude Code promptu
ilə düzəldin, sonra növbəti bölməyə keçin. `⚠️` işarəli sətirlər — əvvəlki
audit dövrlərimizdə tapılan, ən çox "kövrək" olan nöqtələrdir, bunlara
xüsusi diqqət edin.

**Tövsiyə olunan sıra:** 1→2→3 (təhlükəsizlik təməli) → 4→5→6 (əsas biznes
axını) → 17 (təhlükəsizlik sınağı, əsas axın işlədikdən sonra) → qalanlar
öz prioritetinizə görə.
