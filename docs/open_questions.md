# AÇIQ SUALLAR

## OQ-001 — Cərimə düsturunda `Requested` nədir? ✅ HƏLL EDİLDİ (BR-001)

**Vəziyyət:** bağlandı · **Qərar tarixi:** 2026-08-08

**Qərar:** güzəşt müddətinin MƏNBƏYİ Root tərəfindən konfiqurasiya edilir
(`LEAVE_ALLOWANCE_SOURCE` sistem limiti), **defolt `LEAVE_TYPE`**.

Səbəb: iki spesifikasiya tələbi ("düstur `Requested` müddətini tələb edir" və
"İcazə Növü düsturu dəyişmir") yalnız o halda uzlaşır ki, mənbə konfiqurasiya
edilə bilən olsun — yəni qərarı Root versin, kod yox. Defolt `LEAVE_TYPE`
seçilib, çünki yalnız bu variantda 60 dəqiqəlik nahar fasiləsi "60 dəqiqə
gecikmə" sayılmır və aylıq 240 dəqiqəlik limit gündə iki fasilədən sonra
dolmur.

Üç variant `LeaveAllowanceSource` enum-unda mövcuddur: `LEAVE_TYPE` (defolt),
`FIXED`, `NONE` (ən hərfi/ən sərt). Dəyişiklik bir sistem limitidir, kod
dəyişikliyi tələb etmir.

Tətbiq: `src/domain/policies.py`, `LeaveAllowancePolicy`.

---

## (arxiv) OQ-001-in orijinal təsviri

**Təsir:** birbaşa maliyyə nəticəsi

Spesifikasiya bölmə 4, PENALTY LOGIC iki sətirdən ibarətdir:

```
Delay = max(0, Verified_Actual_Time − Requested_Time)
Total = Requested + 2 × Delay
```

Bu iki sətir hərfi oxunuşda **bir-birinə uyğun gəlmir**:

- Birinci sətir `Delay`-i *tam keçən vaxt* kimi təyin edir.
- İkinci sətirdəki `Requested` isə bir **müddət** (dəqiqə) olmalıdır, yoxsa
  toplama mənasızdır (`vaxt + 2 × vaxt` ≠ müddət).

Yeganə daxilən tutarlı oxunuş — `Requested` = icazə üçün ayrılmış müddət:

```
elapsed = actual_return − requested_time
delay   = max(0, elapsed − allowance)
total   = allowance + 2 × delay
```

### Sual: `allowance` (ayrılmış müddət) haradan gəlir?

| Variant | Nəticə (nümunə: 90 dəq. kənarda) | Qeyd |
|---|---|---|
| **A. Həmişə 0** (hərfi) | Delay = 90, Total = 180 | Ən sərt. Heç bir güzəşt yoxdur — nahar fasiləsi də tam cərimələnir. **Hazırkı defolt.** |
| **B. İcazə Növünün standart müddəti** | Nahar 60 dəq. → Delay = 30, Total = 120 | Ən məntiqli, lakin bölmə 4 deyir ki, İcazə Növü seçimi "düsturu DƏYİŞMİR" |
| **C. Sabit sistem limiti** | `system_limits`-dən tək dəyər | Root Control Center-dən idarə olunur, İcazə Növündən asılı deyil |

**Hazırkı vəziyyət:** `calculate_leave_penalty(allowance_minutes=0)` — yəni
**Variant A**. Parametr açıqdır, dəyişiklik bir sətirlik konfiqurasiyadır.

**Nə üçün vacibdir:** Variant A ilə 5 dəqiqəlik siqaret fasiləsi 10 dəqiqə
"borc" yaradır və aylıq 240 dəqiqəlik limit gündə 2-3 fasilədən sonra dolur.
Variant B ilə isə yalnız gecikmə cəzalandırılır.

---

## OQ-002 — Argon2 parametrləri zəif kiosk PC-lərində ölçülməyib

**Vəziyyət:** açıq · **Təsir:** UX (PIN yoxlaması gecikməsi)

64 MiB / t=3 OWASP tövsiyəsidir (~100 ms müasir CPU-da). Köhnə mağaza
PC-lərində bu 300–500 ms ola bilər. **Faza 4-də real cihazda ölçülməli**;
azaldılma qərarı `security_decisions.md`-də qeyd olunmalıdır.

---

## OQ-003 — `ConnectionSettings.dsn()` `sslmode=require`, `verify-full` DEYİL

**Vəziyyət:** açıq · **Təsir:** DB bağlantısının server-şəxsiyyət doğrulaması
(dövrə 1 audit, SEC-032 ilə birgə tapıldı)

`connection_file.py::ConnectionSettings.dsn()` defolt `sslmode=require`
işlədir — bu, nəqliyyatı ŞİFRƏLƏYİR, LAKİN server sertifikatını doğru
Kök Sertifikat Orqanına qarşı DOĞRULAMIR. Yəni `psycopg.connect()` özü-
imzalı sertifikatlı SAXTA bir Postgres serverinə TLS handshake-i
problemsiz tamamlayır — TLS yalnız PASSİV dinləməyə (MITM-in ilk formasına)
qarşı qoruyur, aktiv saxta-server ssenarisinə YOX (bax SEC-032: Bərpa
Konsolu bypass-ı ilə birgə bu, parolun saxta hosta göndərilməsini
ASANLAŞDIRIR — server özünü "doğru" kimi göstərmək üçün heç bir maneə
YOXDUR).

**Nə üçün bu dövrədə həll edilmir:** `verify-full`-a keçid kök sertifikat
idarəsini (Supabase-in CA zəncirinin paylanması/yenilənməsi, özünə-host
quraşdırmalarda müştərinin öz sertifikatı) tələb edir — quraşdırma
mürəkkəbliyi artırır və SEC-032-nin (Qayda A+B) əhatə etdiyi konkret hücum
zəncirindən AYRI, daha geniş qərardır.

**Növbəti addım:** Faza 3-də (və ya SEC-032-nin təqib tapşırığı kimi)
`sslrootcert` + `sslmode=verify-full` keçidi qiymətləndirilməlidir; xüsusən
Bərpa Konsolu axını üçün (orada host İSTİFADƏÇİ tərəfindən yazılır, ən
yüksək risk səthidir).

---

## OQ-004 — Evidence spool-un yetim fayl SWEEP/RECONCILE mexanizmi yoxdur

**Vəziyyət:** açıq · **Təsir:** disk yeri (dövrə 2 audit, INF2-03)

`EvidenceUploadQueue.enqueue()` (`src/infrastructure/storage/upload_queue.py`)
İNDİ `spool_path.write_bytes()`-in `OSError`-unu (disk dolu, icazə itib)
tutub yarımçıq/sıfır-baytlıq faylı `unlink(missing_ok=True)` ilə TƏMİZLƏYİR
— bu, HƏMİN KONKRET uğursuzluq yolunun ÖZÜNÜ örtür. Amma bu, YALNIZ BİR
mənbədir: yetim spool faylı NƏZƏRİ olaraq başqa yollarla da yarana bilər
(məs. proses `write_bytes`-dən SONRA, `INSERT`-dən ƏVVƏL — yəni sətir 623-ün
açdığı tranzaksiyaya çatmadan — çökürsə; və ya DB sətri sonradan silinirsə/
DB bərpa olunursa, spool isə YOX).

Ümumi bir "sweep" (DB-də sətri OLMAYAN spool faylını tap və sil) HƏLƏ
YAZILMAYIB, çünki üç sual həll edilməyib:

1. **KİM işlədir?** Açılışda bir dəfə, yoxsa dövri fon işi (`scheduled_
   job_repository.py`-nin naxışı)?
2. **Hansı YAŞ həddi ilə?** Çox gənc faylı silmək YARIŞ vəziyyəti yaradar —
   `enqueue()` hələ `INSERT`-i BİTİRMƏMİŞ ola bilər (`write_bytes()` və
   sonrakı `INSERT` ARASINDA, bax sətir 619-621 şərhi, ayrı tranzaksiyalar
   deyil, amma nəzəri pəncərə mövcuddur).
3. **Xəta halında nə edilir?** Səhvən YAŞAYAN (DB sətri olan, amma sweep-in
   TAPMADIĞI) faylı silmək SÜBUT itkisidir (cərimə şəkli).

**Növbəti addım:** dizayn qərarı (`kim/nə vaxt/hansı yaş həddi`) ARDINCA
tapşırıq kimi yazılmalıdır — bu OQ ÖZÜ qərar deyil, YALNIZ boşluğun İZİDİR.

---

## Bağlanmış suallar

| # | Sual | Qərar | Tarix |
|---|---|---|---|
| — | `can_approve_dual_control_override` ziddiyyəti | `is_anti_fraud` / `is_camera_only` ayrıldı (SEC-001) | 2026-08-08 |
| — | Fernet vs hərfi AES-256 | AES-256-GCM-ə keçid (SEC-002) | 2026-08-08 |
| — | Saga siyasəti | Açıq reyestr, naməlum → ən sərt (SEC-003) | 2026-08-08 |
| — | CEO ↔ CEO iyerarxiya | Bloklanır, yalnız Root istisnadır (SEC-006) | 2026-08-08 |
| — | Pepper rotasiyası | Lazy migration (`employees.pepper_version`) | 2026-08-08 |
| — | Gecikmə dəqiqələri AZN-ə necə çevrilir? | Root təyin edir (`DELAY_FINE_RATE_PER_MINUTE`), **defolt 0.00** — təyin edilməmiş dərəcə ilə pul kəsmək hüquqi riskdir (BR-002) | 2026-08-09 |
| — | Aylıq 240 dəq. limiti aşıldıqda nə olur? | Spesifikasiya qadağa təyin etmir → **xəbərdarlıq, bloklama YOX**: audit + HR bildirişi (`MonthlyLeaveUsage`). Bloklamaq olmayan qadağa uydurmaq, susmaq isə Root sürüşdürücüsünü mənasız etmək olardı | 2026-08-10 |
| — | Drive razılığı hansı OAuth axını ilə? | Loopback + PKCE; `oob` Google tərəfindən 2022-də qapadılıb (SEC-017) | 2026-08-10 |
| — | Gecikmə operatorun klik anına görə hesablanmalıdırmı? | **XEYR** — klik anı təsdiq möhürüdür (`verified_at`), cərimənin bazası işçinin STEP 2 PIN möhürüdür (`return_claimed_time`). Bölmə 4-ün iki sətri (Option A «current system time» ↔ «cərimə strictly VERIFIED ACTUAL TIME») yalnız bu oxunuşla uzlaşır; əks halda kamera növbəsinin yükü işçinin cibindən ödənilirdi (M-3) | 2026-08-15 |
| — | Dual-control təsdiqi gözləyərkən hansı vaxt keçərlidir? | **Orijinal** — təsdiqlənməmiş düzəliş heç nəyə təsir etmir (fail-closed, `ManualOverride.is_effective`). Təsdiqçi `[Rədd Et]` də edə bilir (səbəb məcburi, audit + operatora bildiriş); heç kim baxmazsa `DUAL_CONTROL_APPROVAL_TIMEOUT_MINUTES` (defolt 480) sorğunu LƏĞV edir — avtomatik təsdiq dual-control-u mənasız edərdi (M-5) | 2026-08-15 |
| — | 72 saat bağlananda baxılmamış etiraz nə olur? | 72 saat İŞÇİNİN göndərmə hüququnun müddətidir, HR-ın cavab borcunun deyil: etiraz `EXPIRED` (SLA izi + HR bildirişi) olur, LAKİN sonradan da qərar ala bilir və cərimə qərar verilənə qədər export-a DÜŞMÜR. Export-dan sonrakı ləğv «maaş düzəlişi lazımdır» kritik bildirişi verir, `exported_period` isə saxlanılır (ikiqat tutulmanın qarşısı) (M-6) | 2026-08-15 |
