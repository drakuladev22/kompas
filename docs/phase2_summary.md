# FAZA 2 — YEKUN, RİSKLƏR VƏ TEST SSENARİLƏRİ

> Spesifikasiya tələbi: hər fazanın sonunda açıq risklər və minimum test
> ssenariləri göstərilməlidir.

## Doğrulanmış vəziyyət

| Yoxlama | Nəticə |
|---|---|
| Testlər | **441 keçdi**, 3 skip (Faza 4 placeholder) |
| Coverage (bütün `src`) | **90.10%** (qapı 85%) |
| Ruff lint + format | `All checks passed` |
| MyPy **strict** | `no issues found in 52 source files` |
| Self-check `--strict` | `SELF_CHECK_PASSED`, çıxış 0 |
| Supabase sxemi | 46 cədvəl, 17/17 guard testi |

## Təhvil verilən

| # | Modul | Əsas məzmun |
|---|---|---|
| 2.1 | `domain/value_objects/` | `Pin`, `EmailAddress`, `Money`(Decimal), `RolePriority`, `HardlockLevel`, `PermissionFlag`, `TimeRange`, penalty düsturu, tipləşdirilmiş ID-lər |
| 2.2 | `domain/entities/` | `LeaveRequest`, `AttendanceRecord`, `Employee`, `Position`, `Fine` + `AggregateRoot` (hadisə toplama) |
| 2.3 | `domain/interfaces/ports.py` | 17 `Protocol`: repo-lar, `Clock`, `NtpVerifier`, `SystemLimits`, `FeatureToggles`, `AuditTrail`, `UnitOfWork` |
| 2.4 | `application/use_cases/` | `PermissionHierarchyGuard`, `DualControlDeadlockGuard` |
| 2.5 | `application/use_cases/` | `LeaveVerificationUseCase` (Saga ilə), `MorningCheckInUseCase` |
| 2.6 | `application/use_cases/authentication.py` | `AdminLogin`(2FA), `PinHandshake`(lockout), `CredentialReset`, `EmergencyAccessRecovery` |
| 2.7 | `infrastructure/plugins/` | Ed25519 imza, proses sandbox-u, capability whitelist |
| 2.8 | `presentation/navigation.py` | `NavigationRegistry` — "GÖRMƏK = SƏLAHİYYƏTİN OLMASI" |

---

## Faza 2-də qəbul edilən biznes qərarları

### BR-001 — İcazə güzəşt müddətinin mənbəyi

Spesifikasiyanın `Delay = max(0, Actual − Requested_Time)` və
`Total = Requested + 2 × Delay` düsturları öz-özü ilə ziddiyyətlidir.
Mənbə Root tərəfindən konfiqurasiya olunur (`LEAVE_ALLOWANCE_SOURCE`):

| Variant | 60 dəq. icazə, 90 dəq. kənarda |
|---|---|
| `LEAVE_TYPE` (**defolt**) | Delay = 30, Total = 120 |
| `FIXED` | konfiqurasiya edilən sabit dəyər |
| `NONE` (ən hərfi) | Delay = 90, Total = 180 |

Defolt `LEAVE_TYPE`, çünki `NONE` ilə aylıq 240 dəqiqəlik limit gündə iki
nahar fasiləsindən sonra dolar və sistem yararsız olardı.

### BR-002 — Gecikmənin AZN cəriməsinə çevrilməsi

Spesifikasiya `AUTO_DELAY` cəriməsini və "Premiyadan Tutulacaq Yekun Cərimə
Məbləği (AZN)" sütununu tələb edir, lakin **dəqiqə → AZN çevirmə dərəcəsini
göstərmir**. Dərəcə `DELAY_FINE_RATE_PER_MINUTE` sistem limitidir,
**defolt `0.00`**.

Defolt 0 seçildi, çünki təyin edilməmiş dərəcə ilə avtomatik pul kəsmək
hüquqi riskdir. 0 ilə sistem tam işləyir — gecikmə `Total` dəqiqə kimi aylıq
limitdən çıxılır, sadəcə əlavə pul cəriməsi yaranmır. Müştəri dərəcəni təyin
edən kimi `AUTO_DELAY` cərimələri kod dəyişikliyi olmadan işə düşür.

### SEC-016 — Plugin sandbox-un əhatəsi (dürüstlük qeydi)

Üç müdafiə qatı tətbiq olunub: **Ed25519 imza** → **ayrı proses + təmizlənmiş
mühit** → **capability whitelist**. Sirrlər (`KOMPASOS_*`, `SUPABASE_*`,
`DATABASE_URL`) plugin prosesinə **ötürülmür** (whitelist yanaşması).

**Bu, OS-səviyyəli TAM izolyasiya DEYİL.** Plugin prosesi hələ də istifadəçinin
fayl sistemini oxuya bilər. Tam izolyasiya Windows Job Object + AppContainer
tələb edir və Faza 5-ə saxlanılıb. Hazırkı qat əsas riski — **sirrlərin və DB
bağlantısının sızmasını** — bağlayır.

---

## Açıq risklər

### R1. Git quraşdırılmayıb — CI heç vaxt işləməyib

`ci.yml`-ın bütün addımları lokal olaraq ayrıca icra olunub və keçib, lakin
pipeline YAML-ı, job asılılıqları və artefakt yükləmələri sınaqdan keçməyib.
**Faza 3-ə keçməzdən əvvəl bağlanmalıdır.**

### R2. Faza 3 üçün RLS müqaviləsi

Repository qatı hər tranzaksiyada `SET LOCAL app.tenant_id` icra etməlidir.
Edilməzsə fail-closed siyasət bütün sorğuları **boş** qaytaracaq (sızma yox,
dayanma — qəsdən seçilmiş davranış).

### R3. `kompasos_app` rolu hələ LOGIN-siz

`ALTER ROLE kompasos_app LOGIN PASSWORD '<...>'` icra edilməlidir. Tətbiq
`postgres` ilə qoşularsa RLS və append-only qorumaları yan keçilir.

### R4. `pg_cron` Supabase-də aktiv deyil

Timeout eskalasiyası və xal sıfırlanması işləmir. Dashboard-dan aktivləşdirin
və ya xarici scheduler `run_all_scheduled_jobs()` çağırsın.

### R5. Argon2 parametrləri zəif kiosk PC-lərində ölçülməyib

64 MiB / t=3 OWASP tövsiyəsidir (~100 ms müasir CPU-da). Köhnə mağaza
PC-lərində 300–500 ms ola bilər. Faza 4-də real cihazda ölçülməli.

### R6. `AttendanceRecord.REJECTED` statusu istifadə olunmur

Enum-da var, lakin rədd axını statusu `NOT_STARTED`-ə qaytarır (bölmə 4-ün
açıq tələbi: "status ⚪-a QAYIDIR"). Enum dəyəri DB sxemi ilə uyğunluq üçün
saxlanılıb; `rejection` sahəsi və `rejection_count` rədd tarixçəsini daşıyır.

---

## Minimum test ssenariləri (Faza 2)

### Value objects (2.1)

1. Ərəb-hind rəqəmləri (`١٢٣٤`) PIN kimi **rədd edilir**
2. Zəif PIN yeni təyinatda rədd, mövcud yoxlamada qəbul
3. `Money` `float` qəbul etmir, `ROUND_HALF_UP` ilə yuvarlaqlaşdırır
4. Amber `#F5A623` ağ fonda AA **keçmir** (yalnız iri qrafik element)
5. Bərabər `RolePriority` `outranks() == False`
6. Kamera flag-i yalnız kamera-tipli rolda; dual-control təsdiqi kamera rolunda **YOX**
7. `Delay` mənfi ola bilmir; qayıdış sorğudan əvvəldirsə **istisna**

### Entity-lər (2.2)

8. STEP 1 yalnız `🟢 Mağazada` statusundan
9. `requested_time` dəyişdirilə bilmir
10. Cərimə **faktiki qayıdış** vaxtına əsaslanır (Option B ilə)
11. Option A klik vaxtını istifadə edir (spesifikasiya davranışı)
12. 30+ dəq. override → dual-control; operator özünü təsdiqləyə bilmir
13. Timeout: `Mağaza_Meneceri` həll **edə bilmir**
14. Rədd → `⚪`-ya qayıdır, təkrar cəhd mümkündür
15. Gecikmə **cərimə yaratmır**
16. İcazəsiz Qayıb: off-day deyil + VERIFIED yoxdur
17. Kamera operatoru scope-u **fail-safe** (təyinat yoxdursa heç nə)
18. Cərimə: foto sübutu məcburi, export kilidi, REVERSED silmir

### Guard-lar (2.4)

19. `Admin` → bərabər `Admin`: **bloklanır**
20. `CEO` → digər `CEO`: **bloklanır** (SEC-006)
21. `Root` → `CEO`: icazə verilir (yeganə istisna)
22. Özünə override: **bloklanır** (Root daxil)
23. Özündə olmayan flag-i vermək: **bloklanır**; DENY üçün tələb yoxdur
24. `can_control_user_permissions` HR_Admin-ə verilə **bilmir** (hardlock 3)
25. Dual-control təsdiqçisi yoxdursa xəbərdarlıq (bloklamır)

### Use case-lər (2.5)

26. BR-001: `LEAVE_TYPE`/`FIXED`/`NONE` güzəşt mənbələri
27. BR-002: dərəcə 0 → cərimə yox; 0.50 → 30 dəq × 0.50 = 15.00 AZN
28. **Saga kompensasiyası**: cərimə yazısı çökdükdə status geri qaytarılır və `PENDING_RECONCILIATION`
29. NTP sürüşməsi 95 s → `TimeDriftError`; 12 s → keçir (qeydlə)
30. Sürüşmə həddi `system_limits`-dən konfiqurasiya olunur
31. İkinci açıq icazə **bloklanır**
32. Feature Toggle söndürüləndə modul bloklanır
33. Dual-control toggle söndürülübsə yeni override təsdiq tələb etmir
34. Timeout eskalasiyası bir dəfə bildiriş göndərir

### Autentifikasiya (2.6)

35. Naməlum e-poçt və yanlış şifrə **eyni mesaj** (enumeration qorunması)
36. 2FA aktivdirsə iki addım; ehtiyat kodu ilə giriş işləyir
37. `Kamera_Nəzarətçisi` kiosk PIN-i istifadə **edə bilmir**
38. 5 səhv → lockout; bloklanmış hesabda **doğru PIN də** rədd
39. Pepper rotasiyasından sonra köhnə hash işləyir + `needs_pepper_rehash`
40. Sıfırlama: öz sirrini sıfırlaya bilmir, aşağı pillə yuxarını sıfırlaya bilmir, **bərabər pillə icazə verilir**
41. Emergency Recovery: aktiv admin varsa **rədd**; istinad məcburi; yalnız Root/CEO

### Plugin (2.7)

42. Boş truststore → **fail-closed** (heç bir plugin yüklənmir)
43. Fayl imzalandıqdan sonra dəyişdirilirsə → rədd
44. **Manifestdə capability artırmaq imzanı pozur**
45. Sirrlər plugin mühitinə **ötürülmür** (whitelist)
46. Plugin host modullarını idxal **edə bilmir**
47. Timeout → proses öldürülür; nəhəng çıxış → rədd
48. Manifestdə olmayan capability → `PluginPermissionError`

### Naviqasiya (2.8)

49. İcazəsiz element **ümumiyyətlə qaytarılmır** (boz göstərilmir)
50. Modul söndürülübsə icazə olsa belə görünmür (iki şərt)
51. Valideyni gizli olan alt-menyu da gizlənir
52. `is_visible()` deep-link keçidini bloklayır
