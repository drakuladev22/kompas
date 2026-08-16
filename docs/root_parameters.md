# ROOT Parametr Kataloqu

`system_limits` cədvəlindəki **182 konfiqurasiya açarının** tam siyahısı: hər
birinin defoltu, icazə verilən aralığı, nəyə təsir etdiyi və kodda harada
oxunduğu.

Bu sənəd `kompasos11.md` Faza 10.1 və `kompas1.md` Faza 9.1-in açıq tələbidir.
Səbəb sadədir: Root paneldə 182 sətir görür, lakin hansı sətrin nəyi dəyişdiyi
heç bir yerdə yazılmayıb — parametrin adı («`BEHAVIOR_ANOMALY_SIGMA_MULTIPLIER`»)
onun nə etdiyini izah etmir və səhv dəyişdirilməsi sükutla yanlış ittihama və ya
pul kəsintisinə çevrilə bilər.

**Həqiqət mənbəyi kodun özüdür:**

| Nə | Harada |
|---|---|
| Açar siyahısı + defolt dəyərlər | `src/domain/policies.py` — `SystemLimitKey`, `DEFAULT_LIMITS` |
| Aralıqlar (`min_value`/`max_value`) və Azərbaycanca izahlar | `database/schema.sql` §24 + `database/migrations/*.sql` |
| İnfrastruktur klampı (sərt aralıqlar) | `src/infrastructure/config/limits.py` — `INFRA_LIMIT_BOUNDS` |
| Paritet qapısı (bu üçlüyün bütövlüyünü yoxlayan test) | `tests/unit/test_root_control_parameter_parity.py` |

---

## 1. Parametr necə dəyişdirilir

**Yol:** Sol menyu → **ROOT İdarə Mərkəzi** → **«Dinamik limitlər»** bölməsi.

Ekran dörd karta bölünüb (`src/presentation/screens/group_d.py`):

| Kart | Nə var |
|---|---|
| **Dinamik limitlər** | Bu sənəddəki parametrlərin əsas kütləsi |
| **Fasilə Parametrləri** | Nahar/çay dördlüyü — ayrıca kartda, çünki Root onları CÜTLÜKLƏ dəyişir («nahar 45 dəqiqə, gündə 1») |
| **Face Control** | Üz təsdiqinin 10 həddi (bənd 7 və 12 cütü tərs yazılanda xəbərdarlıq göstərilir) |
| **Modul açarları** | `feature_toggles` — bu sənədin mövzusu DEYİL |

**Kim dəyişə bilər:** yalnız `can_manage_system_limits` icazə flag-i olan
istifadəçi. Bu flag `hardlock_level = 1`-dir (`schema.sql` §22), yəni praktikada
**yalnız Root**; menyu maddəsi də həmin flag-lə bağlıdır
(`src/presentation/shell/menu.py`, `key="root_control"`).

**Hər dəyişiklik audit-lənir.** `RootControlUseCase.set_limit` `AuditTrail.record()`
ilə `SYSTEM_LIMIT_CHANGED` yazır (`before_state` / `after_state` daxil) və
`system_limits.changed_by` sütununa aktoru yazır. Audit yazısı uğursuz olarsa
BÜTÜN əməliyyat geri qaytarılır — sükutla keçmiş dəyişiklik yoxdur.

### Aralıqlar harada tətbiq olunur — və harada olunmur

Bu, sənədin ən çox yanlış başa düşülən hissəsidir, ona görə açıq yazılır:

| Qat | Aralıq tətbiq olunurmu? |
|---|---|
| ROOT ekranı (`QSpinBox`) | **Bəli** — `min_value`/`max_value` sətirdən oxunur (`presentation/controllers/root_control.py`, `limit_row`) |
| `RootControlUseCase.set_limit` | **Xeyr** — yalnız «boş ola bilməz» yoxlanılır |
| `system_limits` cədvəli | **Xeyr** — `limit_value` `TEXT`-dir, `CHECK` yoxdur |
| İnfrastruktur açarları (`INFRA_LIMIT_BOUNDS`) | **Bəli** — oxu anında KLAMP edilir + `INFRA_LIMIT_CLAMPED` xəbərdarlığı |
| Domen/tətbiq açarları | **Xeyr** — dəyər olduğu kimi oxunur |

Yəni ekranı yan keçən yol (birbaşa SQL, skript) infrastruktur olmayan açara
aralıqdan kənar dəyər yaza bilər. Bu, qüsur deyil, şüurlu güzəştdir:
`set_value()`-a sərt validasiya qoysaydıq, `TEXT`, siyahı və vergüllü cədvəl
tipli açarlar (məs. `NOTIFY_RETRY_BACKOFF_MINUTES = "1,5,15,60,240"`) üçün
ikinci bir validasiya dili lazım olardı. Əvəzinə **oxuyan tərəf** özünü qoruyur:
yararsız dəyər `SYSTEM_LIMIT_NOT_AN_INTEGER` / `INFRA_LIMIT_NOT_A_NUMBER`
jurnalı ilə defolta düşür və axın dayanmır.

---

## 2. Dəyişiklik nə vaxt qüvvəyə minir

**Cavab: növbəti oxunuşda — proses yenidən başladılmadan.** Heç bir qatda keş
yoxdur və bu, qərardır, təsadüf deyil:

* `PostgresSystemLimits` hər `get_int`/`get_str` çağırışında `system_limits`
  cədvəlinə birbaşa `SELECT` atır (`infrastructure/persistence/config_repositories.py`).
* `InfrastructureLimits` **vəziyyət saxlamır** — modul başlığı bunu açıq
  yazır: *«Root sürüşdürücünü tərpədən kimi növbəti çağırış yeni dəyəri
  görməlidir. Keş "niyə dəyişiklik tətbiq olunmur?" sualını doğurardı və onun
  cavabı yalnız prosesin yenidən başladılması olardı.»*

Praktikada bu, üç fərqli təsir müddəti deməkdir:

| Parametr tipi | Nə vaxt görünür | Nümunə |
|---|---|---|
| Əməliyyat başında oxunan | **Dərhal** — növbəti STEP1/təsdiq/cərimə | `MONTHLY_LEAVE_MINUTES_LIMIT`, `FINE_APPEAL_WINDOW_HOURS` |
| Ekran açılışında oxunan | Ekran yenidən açılanda | `SHIFT_MATRIX_WINDOW_DAYS`, səhifə ölçüləri |
| Fon dövrəsinin ÖZ aralığı | Cari dövr bitəndən sonra | `NOTIFY_POLL_INTERVAL_SECONDS`, `SCHEDULER_POLL_INTERVAL_MINUTES` |

Üçüncü halda gecikmə köhnə dəyər qədərdir: `SCHEDULER_POLL_INTERVAL_MINUTES`-i
60-dan 5-ə salsanız, dəyişiklik ən gec 60 dəqiqə sonra hiss olunur — çünki
işləyən dövrə növbəti oyanışını hələ köhnə aralıqla planlaşdırıb.

**Retroaktiv təsir YOXDUR.** Parametr artıq baş vermiş hadisəni yenidən
hesablamır: `FINE_APPEAL_WINDOW_HOURS`-u 72-dən 24-ə salmaq artıq açıq olan
etiraz pəncərəsini qapatmır — pəncərə cərimə `PUBLISHED` olan anda hesablanıb
sətrə yazılıb (`migrations/016`).

---

## 3. `system_limits`-də OLMAYAN — dəyişdirilə BİLMƏYƏNLƏR

⚠️ **Bu sənədə baxıb «hər şey konfiqurasiya edilə bilər» nəticəsi çıxarmaq
səhvdir.** Aşağıdakılar **struktur zəmanətlərdir** (CLAUDE.md §5,
`docs/security_decisions.md`): nə ROOT panelindən, nə Feature Toggle ilə, nə də
`system_limits` sətri ilə dəyişdirilə bilər. Onları dəyişdirmək üçün kod
buraxılışı **və** miqrasiya lazımdır, çünki hər qayda İKİ yerdədir — domendə və
DB trigger-ində.

| Zəmanət | Harada yaşayır | Niyə parametr DEYİL |
|---|---|---|
| **Anti-fraud vəzifə ayrılığı** — `can_verify_returns`, `can_override_return_time`, `can_issue_fines`, `can_approve_dual_control_override` heç vaxt `Mağaza_Meneceri`/`Satıcı`-ya verilmir | `domain/value_objects/authorization.py` + `schema.sql` §18 | Öz qayıdışını özü təsdiqləyən adam sistemi tamamilə mənasız edir |
| **SEC-001** — kamera-tipli rol dual-control təsdiqi daşıya bilməz | eyni | «İki müstəqil göz» qaydası bir gözə enərdi |
| **Strict Hierarchy Guard** — yalnız CİDDİ şəkildə aşağı pilləyə toxunmaq olar | eyni | Bərabər pillələr bir-birini idarə edə bilsəydi iyerarxiya nominal olardı |
| **Self-Escalation Guard** — aktor yalnız ÖZÜNDƏ olan flag-i verə bilər | eyni | Aktor özünə olmayan səlahiyyəti verə bilərdi |
| **Dörd-səviyyəli `HardlockLevel`** | `authorization.py` | Səviyyələrin özü icazə modelinin skeletidir |
| **Struktur-kritik modulu söndürmək üçün təsdiq mətninin minimum uzunluğu (6)** | `application/use_cases/root_control.py` — `MIN_CONFIRMATION_LENGTH` | Həm limiti, həm toggle-ı EYNİ flag idarə edir: parametr olsaydı, aktor əvvəlcə maneəni `1`-ə endirib sonra `CAMERA_VERIFICATION`-ı bağlaya bilərdi |
| **Xal 6 aylıq sıfırlanma TARİXLƏRİ (1 Yanvar / 1 İyul)** | `domain/value_objects/gamification.py` | Yalnız xəbərdarlığın qabaqcadanlığı (`SALES_POINTS_RESET_NOTICE_DAYS`) parametrdir |
| **Plugin imza/nəşriyyatçı yoxlaması (fail-closed)** | `infrastructure/plugins/` + `KOMPASOS_PLUGIN_TRUSTED_PUBLISHERS` | Boş siyahı = heç bir plugin quraşdırılmır; parametr olsaydı etibar modeli söndürülə bilərdi |
| **Mətn-uzunluğu validatorları** (`MIN_REASON_LENGTH`, `MIN_SUBJECT_LENGTH`) | müvafiq entity-lər | Məzmun keyfiyyəti qaydasıdır, əməliyyat limiti deyil |
| **DB sxem CHECK-ləri** (`erp_servers.sync_interval_seconds >= 30`, `license_tenants.offline_grace_days` 7–14, POS 0–100) | `schema.sql` / miqrasiyalar | ROOT parametri onların ALTINDA işləyir, ÜSTÜNDƏ yox — Root bandı DARALDA bilər, genişləndirə bilməz |

**Sınaq sualı:** yeni sabit ədəd yazmazdan əvvəl özünüzə sual verin — *bu,
yuxarıdakı struktur zəmanətlərdən biridirmi?* Cavab «xeyr»dirsə, onun yeri
`system_limits`-dədir.

---

## 4. Bu sənəd ƏL İLƏ saxlanılır

⚠️ **Yeni `SystemLimitKey` əlavə edəndə BU FAYLA DA yazın.** Avtomatik generator
yoxdur; sənəd kodla sinxron qalmır — sinxron SAXLANILIR.

Yeni parametr üçün tam yol **dörd halqadır** (paritet testi hər üçünü qapı kimi
yoxlayır, dördüncüsü isə budur):

1. `SystemLimitKey`-ə açar əlavə et (`src/domain/policies.py`).
2. `DEFAULT_LIMITS`-ə defolt yaz — olmasa ROOT ekranı `KeyError` ilə çökür.
3. Miqrasiya yaz: MÖVCUD kirayəçilər üçün `INSERT ... ON CONFLICT DO NOTHING`
   **və** yeni kirayəçilər üçün trigger. `description_az` **məcburidir** — onsuz
   Root ekranda ingiliscə texniki kod görər.
4. Bu sənədə sətir əlavə et: defolt, aralıq, təsir, oxuyan modul.

Qapını yoxlamaq:

```bash
.venv/Scripts/python.exe -m pytest tests/unit/test_root_control_parameter_parity.py -q
```

Qapı hazırda **yaşıldır** — hər 182 açarın enum üzvü, defoltu, SQL seed sətri
və Azərbaycanca izahı yerindədir.

---

## Parametr qrupları

Aşağıdakı 17 qrup **182 açarın hamısını** əhatə edir. Sütunların mənası:

* **Defolt** — `DEFAULT_LIMITS`-dəki dəyər (sətir seed edilməyibsə faktiki
  işləyən dəyər də budur).
* **Hədd (min–maks)** — seed sətrindəki `min_value`/`max_value`. `—` = mətn/siyahı
  tipli açardır, ədədi aralıq mənasızdır.
* **Nəyə təsir edir** — seed sətrinin `description_az` sütunu, yəni Root-un
  ekranda GÖRDÜYÜ mətnin özü.
* **Kodda oxunur** — `src/` altındakı yol(lar); `+N` = daha N fayl da oxuyur.
  `presentation/controllers/root_control.py` (panelin özü) siyahıdan çıxarılıb.

---

### 1. İcazə, Fasilə və Davamiyyət

*12 parametr.*

Bu qrup gündəlik STEP1→STEP3 icazə axınını və gündaxili fasilələri idarə edir —
yəni işçinin iş yerindən nə qədər və hansı şərtlərlə ayrıla biləcəyini. Burada
heç bir parametr TƏK BAŞINA bloklayıcı deyil: aylıq 240 dəqiqəlik limit
aşılanda sistem xəbərdarlıq göstərir, icazəni rədd etmir (bax
`leave_verification.py` — `MonthlyLeaveUsage`), nahar/çay sayı da eyni
qaydadadır. Nahar və çay MÜDDƏTİ isə informativ göstəricidir və cərimə
düsturuna QOŞULMUR — güzəşt mövcud qaydada `LEAVE_ALLOWANCE_SOURCE`-dan
(BR-001) gəlir; birləşdirilsəydi, Root ekranda informativ bir mətni dəyişəndə
işçinin cəriməsi də sükutla dəyişərdi.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `MONTHLY_LEAVE_MINUTES_LIMIT` | `240` | 0 – 1440 | Aylıq İcazə Müddəti Limiti (dəqiqə) | `domain/attrition_rules.py`, `application/use_cases/attrition_risk.py` +2 |
| `LATE_TOLERANCE_MINUTES` | `15` | 0 – 120 | Gecikmə Tolerantlığı (dəqiqə) | `application/use_cases/morning_check_in.py` |
| `VERIFICATION_TIMEOUT_MINUTES` | `45` | 5 – 240 | STEP2 / Morning Check-in timeout (dəqiqə) | `application/use_cases/morning_check_in.py`, `application/use_cases/leave_verification.py` +1 |
| `DUAL_CONTROL_THRESHOLD_MINUTES` | `30` | 5 – 240 | Cüt nəzarət həddi (dəqiqə) | `application/use_cases/leave_verification.py`, `presentation/screens/group_b.py` +1 |
| `DUAL_CONTROL_APPROVAL_TIMEOUT_MINUTES` | `480` | 30 – 1440 | Manual vaxt düzəlişinin ikinci təsdiqi ən çox neçə dəqiqə gözləyə bilər. Müddət dolanda sorğu LƏĞV olunur (avtomatik təsdiqlənmir), icazənin orijinal vaxtı qüvvədə qalır və sorğunu yazan operator bildiriş alır. | `application/use_cases/leave_verification.py` |
| `LEAVE_ALLOWANCE_SOURCE` | `LEAVE_TYPE` | — | İcazə güzəştinin mənbəyi (BR-001): LEAVE_TYPE / FIXED / NONE | `application/use_cases/leave_verification.py` (`LeaveAllowancePolicy.from_limits`) |
| `LEAVE_ALLOWANCE_FIXED_MINUTES` | `0` | 0 – 1440 | Sabit güzəşt müddəti — yalnız mənbə FIXED olduqda tətbiq olunur | `application/use_cases/leave_verification.py` (`LeaveAllowancePolicy.from_limits`) |
| `LEAVE_TYPE_MAX_DURATION_MINUTES` | `720` | 1 – 1440 | İcazə Növünün tövsiyə olunan müddəti üçün yuxarı hədd (dəqiqə) | `domain/value_objects/catalogs.py`, `presentation/controllers/catalog_admin.py` |
| `LUNCH_BREAK_DURATION_MINUTES` | `60` | 1 – 480 | Nahar fasiləsinin müddəti (dəqiqə). YALNIZ MƏLUMATLANDIRICIDIR — işçi ekranında «Nahar fasiləniz: 60 dəqiqə» kimi göstərilir və gecikmə/cərimə düsturuna (Delay/Total) QOŞULMUR. Cərimə güzəşti mövcud qaydada «İcazə Növləri» kataloqundakı müddətdən gəlir (BR-001) | `application/use_cases/leave_verification.py` (`BreakAllowance.from_limits`) |
| `LUNCH_BREAK_DAILY_COUNT` | `1` | 0 – 10 | Nahar fasiləsinin gündə neçə dəfə nəzərdə tutulduğu. Hədd aşılanda əməliyyat BLOKLANMIR — işçi ekranında və HR panelində «2-ci nahar fasiləsi (limit: 1)» xəbərdarlığı göstərilir. 0 = bu kirayəçidə nahar fasiləsi nəzərdə tutulmayıb (hər istifadə xəbərdarlıq doğurur) | `application/use_cases/leave_verification.py` (`BreakAllowance.from_limits`) |
| `TEA_BREAK_DURATION_MINUTES` | `15` | 1 – 480 | Çay fasiləsinin müddəti (dəqiqə). Nahar müddəti ilə eyni qayda: yalnız məlumatlandırıcıdır, cərimə düsturuna təsir etmir | `application/use_cases/leave_verification.py` (`BreakAllowance.from_limits`) |
| `TEA_BREAK_DAILY_COUNT` | `2` | 0 – 10 | Çay fasiləsinin gündə neçə dəfə nəzərdə tutulduğu. Aşılma bloklamır, yalnız «3-cü çay fasiləsi (limit: 2)» xəbərdarlığı doğurur | `application/use_cases/leave_verification.py` (`BreakAllowance.from_limits`) |

---

### 2. Cərimə və Etiraz

*2 parametr.*

Cəriməyə aid yalnız İKİ parametr var və bu, təsadüf deyil: cərimənin qalan
qaydaları (kim verə bilər, kim baxa bilər, nə vaxt görünür) struktur
zəmanətdir və aşağıdakı «Dəyişdirilə BİLMƏYƏNLƏR» bölməsindədir. Etiraz
pəncərəsinin aşağı hüdudu 24 saatdır — daha qısa pəncərə etiraz hüququnu
formal saxlayıb praktiki olaraq söndürərdi. `DELAY_FINE_RATE_PER_MINUTE`
defolt **0.00 AZN**-dir (BR-002): təyin edilməmiş dərəcə ilə avtomatik pul
kəsmək hüquqi riskdir, ona görə sistem susmağı seçir, təxmin etməyi yox.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `FINE_APPEAL_WINDOW_HOURS` | `72` | 24 – 336 | Cərimə Etiraz Pəncərəsi (saat) | `application/use_cases/fine_review.py`, `application/use_cases/fine_management.py` +2 |
| `DELAY_FINE_RATE_PER_MINUTE` | `0.00` | 0 – 100 | Gecikmə dəqiqəsinin AZN dəyəri (BR-002). Defolt 0 — təyin edilməmiş dərəcə ilə avtomatik pul kəsmək hüquqi riskdir. | `application/use_cases/leave_verification.py` (`DelayFinePolicy.from_limits`) |

---

### 3. Növbə, Tabel və Əmək Normaları

*12 parametr.*

Növbə planlaması və əmək normaları bir qrupdadır, çünki hər ikisi eyni suala
xidmət edir: «bu işçini bu vaxta yazmaq olarmı?». `LABOR_*` qaydaları
BLOKLAMIR — yalnız xəbərdarlıq göstərir (bax `domain/labor_rules.py`), çünki
əmək hüququ məsləhəti proqramın işi deyil; ona görə hər dördü `0` yazılmaqla
tamamilə susdurula bilər. `OPEN_SHIFT_MAX_LEAD_DAYS` (30) və
`SHIFT_SWAP_MAX_LEAD_DAYS` (90) QƏSDƏN fərqlidir: birincidə hələ heç kimə aid
olmayan slot elan olunur, ikincidə işçi ÖZ mövcud gününü dəyişir.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `OVERTIME_DAILY_NORM_HOURS` | `8.00` | 1 – 24 | #15 — Gündəlik norma iş saatı; bundan çoxu `overtime_log`-a norma üstü kimi yazılır | `domain/work_norm.py`, `application/use_cases/reporting.py` +2 |
| `OVERTIME_WEEKLY_NORM_HOURS` | `40.00` | 1 – 168 | #15 — Həftəlik (Bazar ertəsi–Bazar) norma iş saatı; gündəlik norma aşılmasa belə həftəlik aşım qeydə alınır | `application/use_cases/overtime_tracking.py` |
| `OVERTIME_NOTIFY_THRESHOLD_HOURS` | `1.00` | 0 – 24 | #15 — Bu hədddən (daxil olmaqla) böyük aşım HR_Admin-ə bildiriş doğurur; jurnala isə aşımın hamısı yazılır | `application/use_cases/overtime_tracking.py` |
| `LABOR_MIN_REST_HOURS` | `12` | 0 – 24 | #14 — İki ardıcıl növbə arasında minimum istirahət (saat). 0 = qayda susur. Gecə növbəsi nəzərə alınır: hesablama növbənin bitmə ANINDAN aparılır | `domain/labor_rules.py`, `application/use_cases/labor_compliance.py` |
| `LABOR_MANDATORY_BREAK_MINUTES` | `60` | 0 – 240 | #14 — Uzun növbədə nəzərdə tutulmalı fasilənin müddəti (dəqiqə). 0 = qayda susur | `domain/labor_rules.py`, `application/use_cases/labor_compliance.py` |
| `LABOR_BREAK_REQUIRED_AFTER_HOURS` | `6` | 0 – 24 | #14 — Neçə saatdan uzun növbədə fasilə məcburi sayılsın. 0 = qayda susur | `domain/labor_rules.py`, `application/use_cases/labor_compliance.py` |
| `LABOR_MAX_CONSECUTIVE_WORK_DAYS` | `6` | 0 – 31 | #14 — İstirahət günü olmadan ardıcıl neçə gün işləmək olar. 0 = qayda susur | `domain/labor_rules.py`, `application/use_cases/labor_compliance.py` |
| `STAFFING_PATTERN_BASED_ON_WEEKS` | `8` | 2 – 52 | #13 — Kadr təklifi neçə həftəlik tarixçəyə baxsın (yalnız KompasOS davamiyyət datası — 1C satış həcmi İŞLƏDİLMİR) | `application/use_cases/staffing_pattern.py`, `presentation/controllers/screen_data.py` |
| `OPEN_SHIFT_MAX_LEAD_DAYS` | `30` | 1 – 90 | #16 — Açıq növbə elanı ən çox neçə gün irəli üçün verilə bilər | `application/use_cases/open_shift_market.py`, `presentation/controllers/open_shift.py` |
| `OPEN_SHIFT_MAX_CLAIMS_PER_MONTH` | `8` | 1 – 31 | #16 — Bir işçinin bir təqvim ayında götürə biləcəyi açıq növbə sayı | `application/use_cases/open_shift_market.py` |
| `SHIFT_SWAP_MAX_LEAD_DAYS` | `90` | 1 – 365 | Növbə dəyişmə sorğusu ən çox neçə gün irəli üçün göndərilə bilər | `application/root_limits.py`, `application/use_cases/shift_scheduling.py` |
| `SHIFT_MATRIX_WINDOW_DAYS` | `14` | 1 – 120 | Növbə matrisinin göstərdiyi gün sayı | `presentation/controllers/screen_data.py` |

---

### 4. İllik Məzuniyyət Balansı

*10 parametr.*

İllik məzuniyyət balansı gündaxili icazə ilə (1-ci qrup) HEÇ BİR ƏLAQƏSİ
OLMAYAN ayrıca mexanizmdir — `MONTHLY_LEAVE_MINUTES_LIMIT` dəqiqələri, bu qrup
isə günləri sayır. On açarın hamısı ROOT-dadır, çünki illik məzuniyyət
siyasəti ölkə qanunundan, kollektiv müqavilədən və şirkət praktikasından
asılıdır: bir kirayəçinin 21 günü digərinin 28 günüdür. Staj əlavəsində
qaydanın NƏTİCƏSİ deyil, FORMASI da konfiqurasiya edilir (dövr + addım +
tavan = üç ayrı açar), çünki «hər 5 ildə 1 gün, ən çoxu 5» cümləsinin hər üç
ədədi şirkətdən şirkətə dəyişir.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `ANNUAL_LEAVE_BASE_ENTITLEMENT_DAYS` | `21.00` | 1 – 60 | Bir təqvim ilində qazanılan BAZA illik məzuniyyət haqqı (gün). Defolt Azərbaycan Əmək Məcəlləsinin 21 təqvim günlük minimumudur. GÜNDAXİLİ icazə ilə (aylıq 240 dəqiqə) heç bir əlaqəsi yoxdur | `domain/annual_leave_rules.py`, `presentation/preview_data.py` |
| `ANNUAL_LEAVE_SENIORITY_PERIOD_YEARS` | `5` | 1 – 40 | Staj əlavəsinin dövrü (il). "Hər N ildə bir addım" qaydasının N-i — qaydanın FORMASI da konfiqurasiya edilir, yalnız nəticəsi yox | `domain/annual_leave_rules.py` |
| `ANNUAL_LEAVE_SENIORITY_BONUS_DAYS` | `1.00` | 0 – 10 | Hər tamamlanmış staj dövrünə düşən əlavə gün. `0` = staj əlavəsi yoxdur (tamamilə qanuni siyasət) | `domain/annual_leave_rules.py` |
| `ANNUAL_LEAVE_SENIORITY_BONUS_MAX_DAYS` | `5.00` | 0 – 30 | Staj əlavəsinin TAVANI (gün). Tavansız qayda 40 illik stajda haqqı ikiqat artırardı | `domain/annual_leave_rules.py` |
| `ANNUAL_LEAVE_CARRYOVER_MAX_DAYS` | `5.00` | 0 – 60 | Keçən ildən növbəti ilə köçürülə bilən maksimum gün. Tavanı aşan hissə İTİR — mənfi balans YARANMIR | `domain/annual_leave_rules.py` |
| `ANNUAL_LEAVE_CARRYOVER_DEADLINE_MONTH` | `3` | 1 – 12 | "İstifadə et ya itir" son tarixinin AYI. Defolt mart — birinci rübün sonu | `domain/annual_leave_rules.py`, `presentation/preview_data.py` |
| `ANNUAL_LEAVE_CARRYOVER_DEADLINE_DAY` | `31` | 1 – 31 | "İstifadə et ya itir" son tarixinin GÜNÜ. Ayın uzunluğundan artıq nömrə həmin ayın son gününə sıxılır (fevralın 31-i → 28/29) | `domain/annual_leave_rules.py`, `presentation/preview_data.py` |
| `ANNUAL_LEAVE_ACCRUAL_PERIOD` | `ANNUAL` | — | Haqqın qazanılma dövrü: ANNUAL (ilin əvvəlində tam, işə qəbul tarixinə görə proporsional), QUARTERLY və ya MONTHLY (tamamlanmış dövr başına toplanır). Naməlum dəyər ANNUAL sayılır | `domain/annual_leave_rules.py` |
| `ANNUAL_LEAVE_ACCRUAL_RATE_DAYS_PER_PERIOD` | `0.00` | 0 – 31 | Bir accrual dövrünə düşən gün (dərəcə). `0` = AVTOMATİK: illik haqq ÷ dövr sayı — beləliklə baza haqq dəyişəndə dərəcə də özü uyğunlaşır | `domain/annual_leave_rules.py` |
| `ANNUAL_LEAVE_DAY_COUNT_MODE` | `WORKING_DAYS` | — | Balansdan neçə gün çıxılır: WORKING_DAYS (Shift Matrix-də istirahət olmayan günlər — defolt) və ya CALENDAR_DAYS (aralıqdakı bütün günlər). Bayram günü ayrıca kataloqda deyil, Shift Matrix-də istirahət kimi işarələnir | `domain/annual_leave_rules.py` |

---

### 5. Face Control — Üz Təsdiqi

*10 parametr.*

⚠️ **Bu qrupun bənzərlik və keyfiyyət hədləri İLKİN DƏYƏRDİR, «düzgün» dəyər
DEYİL.** `facecontrol.md`-nin açıq göstərişi budur: doğru ədədi indi təxmin
etməyə çalışma — kitabxananın sənədləşdirilmiş defoltunu götür və PİLOT
MAĞAZADA real işıq/kamera şəraitində ölçüb tənzimlə. `FACE_MATCH_TOLERANCE`
və `FACE_LOW_CONFIDENCE_TOLERANCE` MƏSAFƏ vahidindədir (kiçik = daha oxşar) —
faizə çevrilsəydi, Root-un gördüyü ədədlə kitabxananın cavabı arasında gizli
bir çevirmə düsturu oturardı və həmin düstur özü hardcode edilmiş qərara
çevrilərdi. `FACE_ENROLLMENT_FRAME_COUNT` performans xəbərdarlığına görə HEÇ
VAXT avtomatik azaldılmır: yavaşlığın həlli hardware-dir, kadr sayının sükutla
endirilməsi isə təhlükəsizlik güzəştidir.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `FACE_ENROLLMENT_MIN_QUALITY` | `0.50` | 0.10 – 0.95 | Üz qeydiyyatında kadrın qəbul edilməsi üçün minimum keyfiyyət balı (0–1: aydınlıq/işıqlandırma). Kadrlar bu həddi keçmirsə operatora «Yenidən Çək» təklif olunur. İLKİN DƏYƏRDİR — pilot mağazanın real işıq şəraitində ölçülüb tənzimlənməlidir | `application/use_cases/face_control.py` |
| `FACE_ENROLLMENT_FRAME_COUNT` | `5` | 3 – 15 | Üz qeydiyyatında çəkilən kadr sayı. Kadrların embedding-lərinin RİYAZİ ORTASI tək istinad vektoru kimi saxlanılır (bənd 11) — tək kadr təsadüfi işıq/açı xətasını istinad nöqtəsinə çevirərdi. İLKİN DƏYƏRDİR: doğru say kameradan asılıdır və pilot mağazada tənzimlənməlidir. Bu parametr performans xəbərdarlığına görə AVTOMATİK AZALDILMIR — sürət problemi hardware ilə həll olunur | `application/use_cases/face_control.py`, `presentation/preview_data.py` +1 |
| `FACE_MISMATCH_LOCKOUT_THRESHOLD` | `3` | 1 – 10 | Ardıcıl neçə üz-uyğunsuzluğundan sonra hesab kilidlənir. PIN-in öz həddindən (`PIN_MAX_FAILED_ATTEMPTS` = 5) AYRIDIR və qəsdən daha aşağıdır: üz uyğunsuzluğu unudulmuş rəqəm deyil, kimlik siqnalıdır. Kilidin MÜDDƏTİ yeni parametr deyil — mövcud `PIN_LOCKOUT_MINUTES` işlədilir, çünki mexanizm təkrar yazılmır | `application/use_cases/face_control.py` |
| `FACE_LIVENESS_ACTIONS` | `BLINK,HEAD_TURN,SMILE` | — | Hər doğrulamada TƏSADÜFİ seçilən aktiv liveness hərəkətlərinin vergüllü kataloqu: BLINK (göz qırpma), HEAD_TURN (baş çevirmə), SMILE (gülümsəmə). Bir hərəkəti söndürmək üçün onu siyahıdan çıxarmaq kifayətdir; siyahı BOŞ qala bilməz, çünki bu, liveness qorumasını tamamilə söndürərdi | `application/use_cases/face_control.py` |
| `FACE_MATCH_TOLERANCE` | `0.60` | 0.20 – 0.99 | Üz bənzərlik həddi — kitabxananın MƏSAFƏ vahidindədir (kiçik = daha oxşar). Bu qiymətdən BÖYÜK məsafə MISMATCH sayılır. İLKİN DƏYƏR kitabxananın sənədləşdirilmiş defoltudur (0.6) və pilot mağazada real şəraitdə tənzimlənməlidir — «düzgün» ədəd empirik qərardır | `application/use_cases/face_control.py`, `presentation/preview_data.py` |
| `FACE_LOW_CONFIDENCE_TOLERANCE` | `0.50` | 0.15 – 0.98 | Tam-etibarlı uyğunluğun sərhədi (məsafə vahidi). Bu qiymətdən kiçik məsafə tam təsdiqdir; bu qiymətlə `FACE_MATCH_TOLERANCE` arasındakı zolaq isə «aşağı-etibarlı təsdiq»dir — əməliyyata icazə verilir, lakin qeyd nişanlanır ki, Kamera Operatoru öz yoxlamasında daha diqqətli olsun. Dəyər bənzərlik həddindən BÖYÜK ola bilməz | `application/use_cases/face_control.py`, `presentation/preview_data.py` |
| `FACE_REENROLLMENT_REMINDER_MONTHS` | `12` | 1 – 60 | Üz qeydiyyatının «köhnəlmiş» sayılması üçün ay sayı. Bu müddət keçəndə admin panelində tövsiyə xəbərdarlığı görünür (insan üzü zamanla dəyişir: saqqal, eynək, yaş). MƏCBURİ BLOKLAMA YARATMIR — işçi normal işləməyə davam edir | `application/use_cases/face_control.py`, `presentation/preview_data.py` +2 |
| `FACE_EXEMPTION_MAX_DAYS` | `90` | 1 – 365 | Face Control istisnasının maksimum müddəti (gün). Bu müddət bitdikdə istisna avtomatik ləğv olunur və yenidən əsaslandırılmalı olur — istisna sükutla əbədi qalmamalıdır, çünki o, üz təsdiqi qatını söndürür | `application/use_cases/face_control.py`, `presentation/preview_data.py` +1 |
| `FACE_VERIFICATION_LOG_RETENTION_MONTHS` | `12` | 1 – 60 | Üz-doğrulama jurnalının saxlanma müddəti (ay). Bundan köhnə sətirlər gecəlik işlə TAM SİLİNİR (anonimləşdirmə lazım deyil — jurnalda foto və vektor yoxdur). 12 ay mövcud Davranış Anomaliyası baseline aralığından (son 30 gün) qat-qat genişdir, konflikt yaratmır | `application/use_cases/face_control.py` |
| `FACE_VERIFICATION_MAX_SECONDS` | `5` | 1 – 60 | Gözlənilən maksimum doğrulama vaxtı (saniyə). Aşılarsa System Health Monitor-a performans xəbərdarlığı yazılır (kiosk PC-nin gücü kifayət edirmi?). Bu monitorinq HEÇ VAXT keyfiyyət parametrlərini avtomatik zəiflətmir — həll yolu hardware/kod optimallaşdırmasıdır | `application/use_cases/face_control.py` |

---

### 6. Kamera, Kiosk, Sübut Şəkli və Drive

*17 parametr.*

Bu qrup sübut şəklinin kamera qarşısından Google Drive-a qədər keçdiyi bütün
yolu — çəkiliş, kiçildilmə, növbə, yükləmə, keş və kvota — bir yerdə saxlayır;
memarlıq izahı üçün bax [`drive_integration.md`](drive_integration.md). Kiosk
nəzarətçisinin (`KIOSK_*`) parametrləri də buradadır, çünki onlar eyni fiziki
avadanlığa (mağaza PC-si + kamera) aiddir. Diqqət: nəzarətçi bu dəyərləri baza
əlçatmaz olduqda FALLBACK ilə oxuyur və bu, şüurlu seçimdir — limit oxumaq
üçün baza tələb etsəydik, bazanın çökməsi yenidən-başlatma məntiqinin ÖZÜNÜ
dayandırardı, yəni qoruma məhz lazım olduğu anda yox olardı.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `MAX_UPLOAD_SIZE_BYTES` | `5242880` | 1048576 – 20971520 | Maksimum şəkil ölçüsü (bayt) | `presentation/composition.py` (`_upload_limit`), `infrastructure/storage/upload_queue.py` |
| `EVIDENCE_THUMBNAIL_MAX_EDGE_PX` | `320` | 64 – 1024 | Siyahıdakı kiçik sübut şəklinin maksimum kənarı (piksel) | `domain/value_objects/storage.py`, `infrastructure/storage/google_drive.py` |
| `EVIDENCE_FULL_MAX_EDGE_PX` | `1600` | 320 – 4096 | Açılan sübut şəklinin maksimum kənarı (piksel) | `domain/value_objects/storage.py`, `infrastructure/storage/google_drive.py` |
| `DRIVE_QUOTA_WARNING_RATIO` | `0.90` | 0.50 – 1.00 | Google Drive kvota xəbərdarlığının doluluq həddi (nisbət) | `infrastructure/storage/quota_monitor.py` |
| `DRIVE_QUOTA_WARNING_COOLDOWN_DAYS` | `7` | 1 – 90 | Kvota xəbərdarlığı bu qədər gündən tez təkrarlanmır | `infrastructure/storage/quota_monitor.py` |
| `KIOSK_RESTART_WINDOW_MINUTES` | `10` | 1 – 1440 | Kiosk yenidən-başlatma fırtınası pəncərəsi (dəqiqə) | `infrastructure/kiosk/watchdog.py` |
| `KIOSK_MAX_RESTARTS_PER_WINDOW` | `5` | 1 – 100 | Pəncərə ərzində icazə verilən yenidən başlatma sayı | `infrastructure/kiosk/watchdog.py` |
| `KIOSK_RESTART_BACKOFF_SECONDS` | `2,4,8,16,30` | 1 – 3600 | Kiosk yenidən başlatma gözləmə cədvəli (vergüllü; hüdud hər elementə) | `infrastructure/kiosk/watchdog.py` |
| `DRIVE_TOKEN_REFRESH_MARGIN_SECONDS` | `60` | 10 – 600 | Access token bitməmişdən bu qədər əvvəl yenilənir (saniyə) | `infrastructure/storage/drive_api.py` |
| `DRIVE_REQUEST_TIMEOUT_SECONDS` | `30.0` | 5.0 – 300.0 | Google Drive API sorğusunun taymautu (saniyə) | `infrastructure/storage/drive_api.py` |
| `DRIVE_MAX_RETRIES` | `3` | 1 – 10 | Drive API təkrar cəhd sayı (429/5xx cavablarında) | `infrastructure/storage/drive_api.py` |
| `DRIVE_OAUTH_FLOW_TIMEOUT_SECONDS` | `300.0` | 30.0 – 1800.0 | Drive razılıq axını bu müddətdən sonra ləğv edilir (saniyə) | `infrastructure/storage/oauth_flow.py`, `presentation/controllers/drive_connection.py` |
| `EVIDENCE_JPEG_QUALITY` | `85` | 40 – 100 | Sübut şəklinin JPEG keyfiyyəti | `infrastructure/storage/google_drive.py` |
| `UPLOAD_CLAIM_STALE_AFTER_SECONDS` | `600` | 60 – 86400 | Claim edilmiş yükləmə elementinin köhnəlmə müddəti (saniyə) | `infrastructure/storage/upload_queue.py` |
| `IMAGE_CACHE_TTL_SECONDS` | `2592000` | 3600 – 31536000 | Şəkil keşindəki faylın ömrü (saniyə; defolt 30 gün) | `infrastructure/storage/image_cache.py` |
| `IMAGE_CACHE_MAX_BYTES` | `268435456` | 16777216 – 8589934592 | Şəkil keşinin disk tavanı (bayt; defolt 256 MB) | `infrastructure/storage/image_cache.py` |
| `EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS` | `120` | 10 – 3600 | Sübut şəkli növbəsinin fon dövrəsi (saniyə) | `presentation/app.py` |

---

### 7. ERP / 1C İnteqrasiyası

*9 parametr.*

1C parametrləri iki işi görür: uyğunlaşma DƏQİQLİYİ (`ERP_NAME_MATCH_*`,
`ERP_MATCH_AMBIGUITY_MARGIN`) və sinxronizasiya RİTMİ (qalanları).
`ERP_NAME_MATCH_THRESHOLD`-un aşağı hüdudu SƏRTDİR (0.70) — ondan aşağı
«Əliyev Elnur» ↔ «Əliyev Elvin» keçər və satış xalı SƏHV işçiyə yazılardı;
yəni bu hədd rahatlıq deyil, doğruluq məsələsidir.
`ERP_MATCH_LOW_CONFIDENCE_PERCENT` isə qərar VERMİR, yalnız operatorun
ekranında rəng seçir — ikisi qarışdırılmamalıdır.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `ERP_SYNC_PAGE_SIZE` | `500` | 1 – 5000 | Bir 1C sorğusunda gətirilən sənəd sayı | `domain/value_objects/erp.py` |
| `ERP_NAME_MATCH_THRESHOLD` | `0.87` | 0.70 – 1.00 | Ad-əsaslı uyğunlaşmanın qəbul həddi — aşağı hüdud SƏRTDİR | `domain/value_objects/erp.py` |
| `ERP_MATCH_AMBIGUITY_MARGIN` | `0.05` | 0.01 – 0.50 | Ən yaxşı iki namizədin fərqi bundan azdırsa uyğunlaşma qəbul edilmir | `infrastructure/erp/matching.py` |
| `ERP_SYNC_MAX_PARALLEL_SERVERS` | `4` | 1 – 32 | Eyni anda sinxronlaşdırılan 1C serverlərinin sayı | `infrastructure/erp/sync_worker.py` |
| `ERP_SYNC_MAX_PAGES_PER_RUN` | `10` | 1 – 1000 | Bir dövrdə bir serverdən oxunan maksimum səhifə sayı | `infrastructure/erp/sync_worker.py` |
| `ERP_REQUEST_TIMEOUT_SECONDS` | `30.0` | 5.0 – 300.0 | 1C OData sorğusunun taymautu (saniyə) | `infrastructure/erp/one_c_connector.py` |
| `ERP_MAX_RETRIES` | `3` | 1 – 10 | 1C sorğusunun təkrar cəhd sayı (429/5xx cavablarında) | `infrastructure/erp/one_c_connector.py` |
| `ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS` | `86400` | 300 – 604800 | Fayl-mübadiləsi tipli 1C serverinin defolt sinxronizasiya dövrü (saniyə). Defolt 86400 = gündə bir dəfə, çünki fayl mübadiləsi real-vaxt deyil və yeni məlumat yalnız 1C-dəki gecəlik ixrac işlədikdə yaranır. Bu dəyər YALNIZ yeni serverin defoltudur — mövcud serverin dövrü sətrin öz sahəsindədir və sihirbazdan dəyişdirilir. HTTP/COM serverlərinə TƏSİR ETMİR (onların defoltu 300 saniyədir) | `domain/value_objects/erp.py`, `application/use_cases/erp_connection.py` |
| `ERP_MATCH_LOW_CONFIDENCE_PERCENT` | `50` | 0 – 100 | Bu faizdən aşağı uyğunluq «zəif» sayılır və xəbərdarlıq rəngi alır | `presentation/screens/group_f.py`, `presentation/controllers/sales_review.py` |

---

### 8. Bildiriş, E-poçt və Planlayıcı

*9 parametr.*

Bildiriş növbəsi və planlayıcı eyni qrupdadır, çünki hər ikisi fon
dövrəsidir və hər ikisinin əsas riski eynidir: səs-küy ya sükut.
`SCHEDULER_LEASE_MINUTES` xüsusi diqqət tələb edir — o, ƏN UZUN işin icra
müddətindən BÖYÜK olmalıdır; kiçik seçilsə, hələ işləyən terminalın icarəsi
bitər və ikinci terminal EYNİ işi paralel başladar, yəni parametr yanlış
qoyulanda qoruma özü yarış yaradır. `SCHEDULER_NIGHTLY_HOUR`-un DƏQİQƏSİ
YOXDUR və bu qəsdəndir: slot sərhədi hər gün eyni yerdə olmalıdır ki,
`scheduled_for` unikal açarı sabit qalsın.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `NOTIFY_MAX_BATCH_SIZE` | `25` | 1 – 500 | Bir dövrdə göndərilən maksimum gözləyən bildiriş | `infrastructure/notifications/notifier.py` |
| `NOTIFY_MAX_ATTEMPTS` | `5` | 1 – 20 | Bu qədər uğursuz cəhddən sonra bildiriş "göndərilməz" sayılır | `infrastructure/notifications/notifier.py` |
| `NOTIFY_RETRY_BACKOFF_MINUTES` | `1,5,15,60,240` | 1 – 10080 | Bildiriş cəhdləri arası gözləmə cədvəli (vergüllü; hüdud hər elementə) | `infrastructure/notifications/notifier.py` |
| `NOTIFY_POLL_INTERVAL_SECONDS` | `120` | 5 – 3600 | Bildiriş növbəsinin dövr aralığı (saniyə) | `infrastructure/notifications/notifier.py` |
| `EMAIL_SMTP_TIMEOUT_SECONDS` | `15.0` | 1.0 – 300.0 | SMTP soket taymautu (saniyə) | `infrastructure/notifications/email.py` |
| `SCHEDULER_POLL_INTERVAL_MINUTES` | `15` | 1 – 1440 | Planlayıcının "vaxtı çatan iş varmı?" yoxlama aralığı (dəqiqə). Kiçik dəyər gecikmiş gecə işini tez tutur, böyük dəyər fon yükünü azaldır | `application/use_cases/job_runner.py`, `presentation/app.py` |
| `SCHEDULER_NIGHTLY_HOUR` | `3` | 0 – 23 | Gecə işlərinin MAĞAZA YERLİ saatı (0–23). Mağazalar bağlı, 1C sinxronizasiyası bitmiş olmalıdır | `application/use_cases/job_runner.py` |
| `SCHEDULER_LEASE_MINUTES` | `30` | 5 – 720 | İcarənin ömrü (dəqiqə). ƏN UZUN işin icra müddətindən BÖYÜK olmalıdır — əks halda hələ işləyən terminalın icarəsi bitər və ikinci terminal eyni işi paralel başladar | `application/use_cases/job_runner.py` |
| `SCHEDULER_MAX_ATTEMPTS` | `3` | 1 – 10 | Uğursuz (və ya icraçısı çökmüş) işin ümumi cəhd tavanı. Tavan tətbiqi öldürən işin sonsuz təkrarlanmasının qarşısını alır | `application/use_cases/job_runner.py` |

---

### 9. Təhlükəsizlik, Sessiya və Vaxt

*11 parametr.*

Bu qrupda PIN/şifrə sərtliyi və VAXT ölçməsi birlikdədir, çünki vaxtın
etibarlılığı burada təhlükəsizlik məsələsidir: `NTP_MAX_DRIFT_SECONDS`
aşılanda sistem `TIME_DRIFT_DETECTED` yazır və vaxt-həssas qaydalar (timeout,
lockout, etiraz pəncərəsi) şübhə altına düşür. `PIN_MAX_FAILED_ATTEMPTS`,
`PIN_LOCKOUT_MINUTES` və `NTP_MAX_DRIFT_SECONDS` infrastruktur klampından
QƏSDƏN kənarda saxlanılıb (bax `infrastructure/config/limits.py` sonundakı
şərh): ikinci bir aralıq elan etsəydik, ekranın göstərdiyi hədd bloklamanın
faktiki həddindən fərqlənərdi və istifadəçi «ekran normal deyir, amma sistem
bloklayır» vəziyyətinə düşərdi.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `PIN_MAX_FAILED_ATTEMPTS` | `5` | 3 – 10 | PIN lockout həddi | `application/use_cases/authentication.py`, `infrastructure/security/hashing.py` +1 |
| `PIN_LOCKOUT_MINUTES` | `15` | 5 – 60 | PIN lockout müddəti (dəqiqə) | `application/use_cases/face_control.py`, `application/use_cases/authentication.py` +2 |
| `NTP_MAX_DRIFT_SECONDS` | `60` | 10 – 300 | TIME_DRIFT_DETECTED həddi (saniyə) | `application/use_cases/morning_check_in.py`, `application/use_cases/leave_verification.py` +3 |
| `PASSWORD_MIN_LENGTH` | `12` | 8 – 128 | Admin-tier şifrənin minimum uzunluğu (simvol) | `infrastructure/security/hashing.py` |
| `NTP_POLL_INTERVAL_SECONDS` | `300` | 30 – 86400 | NTP ölçmələri arasındakı aralıq (saniyə) | `infrastructure/timekeeping/ntp.py` |
| `NTP_QUERY_TIMEOUT_SECONDS` | `3.0` | 1.0 – 30.0 | Bir SNTP sorğusunun taymautu (saniyə) | `infrastructure/timekeeping/ntp.py` |
| `NTP_SAMPLE_TTL_SECONDS` | `1800` | 60 – 86400 | Ölçmə bu müddətdən sonra "təzə" sayılmır (saniyə) | `infrastructure/timekeeping/ntp.py` |
| `NTP_MAX_ROUND_TRIP_SECONDS` | `2.0` | 0.1 – 30.0 | Gediş-dönüş gecikməsi bundan böyükdürsə ölçmə etibarsızdır (saniyə) | `infrastructure/timekeeping/ntp.py` |
| `AUDIT_LOG_MAX_PAGE_SIZE` | `500` | 1 – 5000 | Audit jurnalı səhifəsinin TAVANI — ekranın donmasına qarşı qoruyucu | `application/root_limits.py`, `application/use_cases/audit_query.py` |
| `AUDIT_LOG_DEFAULT_PAGE_SIZE` | `100` | 1 – 5000 | Audit jurnalı ekranının başlanğıc səhifə ölçüsü | `application/root_limits.py`, `application/use_cases/audit_query.py` |
| `SETUP_RECOMMENDED_ADMIN_COUNT` | `2` | 1 – 20 | Tövsiyə olunan minimum Root/CEO hesab sayı — BLOKLAMIR, xəbərdarlıq verir | `application/root_limits.py`, `application/use_cases/first_run_setup.py` |

---

### 10. Lisenziya və Avtomatik Yenilənmə

*18 parametr.*

Lisenziya və avtomatik yenilənmə eyni ritm ailəsindəndir (sutkalıq yoxlama,
uğursuzluqda təkrar cəhd) və hər ikisi kommersiya qərarıdır — zəif internetli
quraşdırmada seyrək, ödəniş gecikməsi olan müştəridə sıx ritm lazım ola bilər.
`LICENSE_*_OFFLINE_GRACE_DAYS` üçlüyü `license_tenants.offline_grace_days`
CHECK bandının (7–14) GÜZGÜSÜDÜR, ONUN ƏVƏZİ DEYİL: `max_value` 14-də
kilidlənib, yəni Root bandı GENİŞLƏNDİRƏ bilmir, yalnız DARALDA bilər (daha
sərt offline siyasəti). `LICENSE_CLOCK_ROLLBACK_TOLERANCE_SECONDS`-in tavanı
da sərtdir (900 saniyə) — böyük tolerantlıq müddət bitməsinin yeganə qoruyucu
ölçüsünü faktiki söndürərdi.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `LICENSE_CHECK_IN_INTERVAL_SECONDS` | `86400` | 300 – 604800 | Lisenziya sətrinin dövri yoxlama aralığı (saniyə) | `domain/value_objects/licensing.py`, `infrastructure/licensing/client.py` |
| `LICENSE_RETRY_INTERVAL_SECONDS` | `3600` | 60 – 86400 | Uğursuz lisenziya yoxlamasından sonra növbəti cəhdə qədər gözləmə (saniyə) | `domain/value_objects/licensing.py`, `infrastructure/licensing/client.py` |
| `LICENSE_BLOCKED_RECHECK_INTERVAL_SECONDS` | `900` | 60 – 86400 | Tətbiq bloklanmış vəziyyətdə yoxlama aralığı (saniyə) | `domain/value_objects/licensing.py`, `infrastructure/licensing/client.py` |
| `LICENSE_MIN_OFFLINE_GRACE_DAYS` | `7` | 1 – 14 | Offline qrace bandının aşağı ucu (gün) — DB CHECK-i ilə eyni tavan | `domain/value_objects/licensing.py`, `infrastructure/licensing/client.py` |
| `LICENSE_MAX_OFFLINE_GRACE_DAYS` | `14` | 1 – 14 | Offline qrace bandının yuxarı ucu (gün) — DB CHECK-i ilə eyni tavan | `domain/value_objects/licensing.py`, `infrastructure/licensing/client.py` |
| `LICENSE_DEFAULT_OFFLINE_GRACE_DAYS` | `14` | 1 – 14 | Qrace dəyəri oxunmadıqda işlənən defolt (gün) | `domain/value_objects/licensing.py`, `infrastructure/licensing/client.py` |
| `LICENSE_EXTENSION_DAYS` | `30` | 1 – 365 | Developer Panelindəki "1 Ay Uzat" düyməsinin əlavə etdiyi gün sayı | `domain/value_objects/licensing.py`, `infrastructure/licensing/client.py` |
| `LICENSE_CLOCK_ROLLBACK_TOLERANCE_SECONDS` | `300` | 30 – 900 | Saatın geri çəkilməsinin manipulyasiya sayılma həddi (saniyə) — tavan SƏRTDİR | `domain/value_objects/licensing.py`, `infrastructure/licensing/state_store.py` |
| `LICENSE_EXPIRY_WARNING_DAYS` | `7` | 1 – 90 | Lisenziya müddətinin bitməsinə neçə gün qalanda xəbərdarlıq göstərilsin | `domain/value_objects/licensing.py`, `infrastructure/licensing/client.py` |
| `UPDATE_CHECK_INTERVAL_SECONDS` | `86400` | 300 – 604800 | Yeni buraxılış kataloqunun arxa fon yoxlama aralığı (saniyə) | `domain/value_objects/updates.py`, `infrastructure/updates/client.py` |
| `UPDATE_RETRY_INTERVAL_SECONDS` | `7200` | 60 – 86400 | Uğursuz yenilənmə cəhdindən sonra gözləmə (saniyə) | `domain/value_objects/updates.py`, `infrastructure/updates/client.py` |
| `UPDATE_MAX_PACKAGE_BYTES` | `536870912` | 1048576 – 1073741824 | Quraşdırıcı faylın maksimum ölçüsü (bayt) — diski dolduran fayla qarşı | `domain/value_objects/updates.py`, `infrastructure/updates/catalog.py` +1 |
| `UPDATE_VERIFY_TIMEOUT_SECONDS` | `60.0` | 5.0 – 600.0 | Authenticode imza yoxlamasının taymautu (saniyə) | `infrastructure/updates/verification.py` |
| `UPDATE_UPLOAD_TIMEOUT_SECONDS` | `600.0` | 30.0 – 7200.0 | Yeni buraxılışın Storage-ə yüklənmə taymautu (saniyə) | `infrastructure/updates/publisher.py` |
| `UPDATE_DOWNLOAD_TIMEOUT_SECONDS` | `300.0` | 30.0 – 7200.0 | Yenilənmə paketinin endirilmə taymautu (saniyə) | `infrastructure/updates/catalog.py` |
| `UPDATE_SIGNED_URL_TTL_SECONDS` | `3600` | 60 – 86400 | İmzalı endirmə linkinin ömrü (saniyə) | `infrastructure/updates/catalog.py` |
| `UPDATE_CATALOG_FETCH_LIMIT` | `20` | 1 – 500 | Buraxılış kataloğu sorğusunun oxuduğu sətir tavanı | `infrastructure/updates/catalog.py` |
| `LICENSE_PAYMENT_REMINDER_OFFSET_DAYS` | `-7,-3,-1,1,7` | — | Ödəniş xatırlatma cədvəli (gün): mənfi = bitmədən əvvəl, müsbət = sonra | `application/use_cases/payment_reminders.py` |

---

### 11. Hesabat, Export və İcra Xülasəsi

*8 parametr.*

Bu qrupda iki fərqli iş görülür: `REPORT_RANGE_MAX_DAYS` PERFORMANS
qoruyucusudur (uzun aralıq 21 filialın milyonlarla davamiyyət/plan sətrini bir
aqreqasiyada tarayardı), qalanları isə HR-in export-dan ƏVVƏL nəyi görməli
olduğunu tənzimləyir. Heç biri export-u BLOKLAMIR — hədd aşılanda ekran
xəbərdarlıq göstərir və HR «Təsdiqlə və Export Et» ilə davam edir; bloklayıcı
olsaydı, ay bağlanışı bir statistik həddə görə dayanardı. İcra Xülasəsinin
(`EXECUTIVE_DIGEST_*`) metrik kataloqu da buradadır: kataloqdan çıxarılan açar
MÖVCUD konfiqurasiyanı pozmur, göndərmə anında sükutla ötürülür — Feature
Toggle-ın retroaktiv təsir etməməsi qaydası ilə eyni fəlsəfə.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `EXECUTIVE_DIGEST_DEFAULT_FREQUENCY` | `DAILY` | — | Yeni icra xülasəsi konfiqurasiyası tezlik seçilmədən yaradılanda tətbiq olunan defolt (DAILY/WEEKLY). Mövcud konfiqurasiyaların tezliyinə TƏSİR ETMİR — o, `executive_digest_config.frequency` sütunundadır | `application/use_cases/executive_digest.py` |
| `EXECUTIVE_DIGEST_METRIC_CATALOG` | `FINE_COUNT,OPEN_EXCEPTION_COUNT,LATE_CHECK_IN_COUNT,OVERTIME_HOURS,TURNOVER_RISK` | — | Toggle-lənə bilən icra xülasəsi göstəricilərinin vergüllü kataloqu. Yeni konfiqurasiya YALNIZ bu siyahıdan metrik seçə bilər; kataloqdan çıxarılan açar MÖVCUD konfiqurasiyanı pozmur, göndərmə anında sükutla ötürülür | `application/use_cases/executive_digest.py` |
| `EXECUTIVE_DIGEST_WEEKLY_WEEKDAY` | `1` | 1 – 7 | Həftəlik tezlikli icra xülasəsinin göndərildiyi ISO həftə günü (1=Bazar ertəsi..7=Bazar). Planlayıcıda ayrıca HƏFTƏLİK slot yoxdur (yalnız DAILY/HOURLY) — bu dəyər gündəlik yoxlama dövrəsinin "bu gün həftəlik göndəriş günüdürmü?" sualını cavablandırır | `application/use_cases/executive_digest.py` |
| `REPORT_RANGE_MAX_DAYS` | `366` | 1 – 1100 | Hesabat export-unda seçilə bilən maksimum tarix aralığı (gün). `[Tam Ay]` yolu bu hədddən təsirlənmir (31 ≤ 366) — hədd yalnız `[Xüsusi Aralıq]` seçimini cilovlayır və məqsədi performansdır: çox uzun aralıq 21 filialın bütün davamiyyət/plan sətirlərini bir aqreqasiyada tarayıb GUI-ni dondurardı. Hədd aşılanda əməliyyat SÜKUTLA rədd edilmir — istifadəçiyə aydın mesaj göstərilir | `application/use_cases/reporting.py` |
| `EXPORT_STORE_ABSENCE_ANOMALY_PCT` | `15.0` | 0.1 – 100 | Pre-export doğrulamasında mağazanı «anomal yüksək icazəsiz-qayıb» kimi işarələyən hədd (faiz). Nisbət: mağazanın icazəsiz qayıb sayı ÷ planlaşdırılmış norma günü. İşçi sayına bölmə QƏSDƏN seçilmədi — yarım-ştat heyəti çox olan mağazanı həmişə pis göstərərdi. Hədd aşılanda export BLOKLANMIR: HR xəbərdarlığı görüb «Təsdiqlə və Export Et» ilə davam edir | `application/use_cases/export_preflight.py` |
| `EXPORT_STORE_ANOMALY_MIN_EMPLOYEES` | `3` | 1 – 100 | Mağaza anomaliyasının hesablanması üçün minimum işçi sayı. Bundan az işçisi olan mağaza yoxlanmır: bir nəfərlik filialda tək qayıb nisbəti faizi 100-ə qaldırır və qayda hər ay yalançı siqnal verərdi | `application/use_cases/export_preflight.py` |
| `EXPORT_PERIOD_DELTA_SIGNIFICANT` | `3` | 1 – 1000 | Dövr-üzrə müqayisədə «əhəmiyyətli fərq» sayılan mütləq hədd. Keçən EYNİ-UZUNLUQDA dövrlə fərq bu qiymətə çatarsa ekranda vurğulanır (məs. «icazəsiz qayıb: +3»). Hədd olmasa hər ±1 dalğalanma vurğulanar ve HR vurğuları görməzdən gəlməyə öyrəşərdi | `application/use_cases/export_preflight.py` |
| `EXPORT_CORRECTION_REASON_MIN_LENGTH` | `10` | 10 – 500 | Manual export düzəlişində səbəb sahəsinin minimum uzunluğu. `export_manual_corrections.reason` CHECK-i (>= 10) DÖŞƏMƏDİR — bu parametr onun ÜSTÜNDƏ siyasətdir və audit tələbi sərtləşəndə miqrasiya gözləmədən artırıla bilər. Döşəmədən aşağı düşmək mümkün deyil | `application/use_cases/export_preflight.py`, `presentation/controllers/report_export.py` |

---

### 12. Analitika — Davranış, İstisna Motoru, Turnover, Benchmark

*17 parametr.*

Bu qrupun hər parametri BİR SUALA cavab verir: «bu, statistik cəhətdən
mənalı siqnaldırmı?». Ona görə burada həm həssaslıq hədləri (σ vuruğu, bal
çəkiləri), həm də MİNİMUM NÜMUNƏ hədləri var —
`BEHAVIOR_BASELINE_MIN_SAMPLE_SIZE` olmadan üç günlük müşahidədən çıxan baz
xətt ilə anomaliya elan etmək yanlış ittiham olardı. `ATTRITION_*` çəkiləri
qəsdən elə seçilib ki, heç bir TƏK siqnal 70 ballıq həddə çatmasın: bildiriş
YALNIZ bir neçə siqnal birləşəndə işə düşür. `EXCEPTION_MAX_FINDINGS_PER_RULE`
isə fərqli riski kəsir — `exceptions` cədvəlində `REVOKE DELETE` var, yəni
qüsurlu qaydanın yaratdığı minlərlə sətri TƏMİZLƏMƏK MÜMKÜN DEYİL.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `EXCEPTION_PAGE_SIZE` | `200` | 10 – 1000 | «İstisnalar» ekranının bir dəfəyə oxuduğu sətir sayı | `application/use_cases/field_reports.py`, `application/use_cases/exception_engine.py` |
| `EXCEPTION_MAX_FINDINGS_PER_RULE` | `500` | 1 – 5000 | Bir qaydanın bir icrada yarada biləcəyi maksimum istisna sayı (qüsurlu qaydaya qarşı tavan — istisna sətirləri SİLİNMİR) | `application/use_cases/exception_engine.py` |
| `EXCEPTION_NOTIFY_MIN_SEVERITY` | `HIGH` | — | Bu ciddiyyətdən (daxil olmaqla) yuxarı istisna dərhal bildiriş doğurur: LOW / MEDIUM / HIGH / CRITICAL | `application/use_cases/exception_engine.py` |
| `EXCEPTION_REVIEW_NOTE_MIN_LENGTH` | `10` | 0 – 500 | İstisna qərarı (xüsusilə «Rədd Et») üçün minimum izah uzunluğu | `application/use_cases/exception_engine.py` |
| `BEHAVIOR_BASELINE_WINDOW_DAYS` | `30` | 7 – 90 | #8 — Davranış baz xəttinin hesablandığı gün sayı (son N gün) | `application/use_cases/behavior_baseline.py` |
| `BEHAVIOR_ANOMALY_THRESHOLD_MINUTES` | `45` | 5 – 240 | #8 — Bugünkü check-in baz xəttindən neçə dəqiqə sapanda anomaliya elan edilsin | `application/use_cases/behavior_baseline.py` |
| `BEHAVIOR_BASELINE_MIN_SAMPLE_SIZE` | `5` | 1 – 90 | #8 — Anomaliya elan edilməzdən əvvəl baz xəttin minimum neçə günlük müşahidəyə əsaslanmalı olduğu (az nümunə = yanlış ittiham riski) | `application/use_cases/behavior_baseline.py` |
| `BEHAVIOR_ANOMALY_SIGMA_MULTIPLIER` | `2.0` | 0.5 – 5.0 | #8 — Sapma işçinin öz standart kənarlaşmasının neçə qatını keçəndə ciddiyyət bir pillə yuxarı qalxsın (statistik "adi deyil" həddi) | `application/use_cases/behavior_baseline.py` |
| `ATTRITION_FINE_TREND_WEIGHT` | `5` | 0 – 100 | #21 — son pəncərənin sonuncu yarımında ƏLAVƏ hər cərimə üçün bal (artım, mütləq say yox) | `domain/attrition_rules.py`, `application/use_cases/attrition_risk.py` |
| `ATTRITION_ATTENDANCE_VIOLATION_WEIGHT` | `8` | 0 – 100 | #21 — eyni pəncərədə hər icazəsiz davamiyyət pozuntusuna bal | `domain/attrition_rules.py`, `application/use_cases/attrition_risk.py` |
| `ATTRITION_NEW_HIRE_RISK_POINTS` | `15` | 0 – 100 | #21 — staj yeni-işçi həddindən az olduqda verilən sabit bal | `domain/attrition_rules.py`, `application/use_cases/attrition_risk.py` |
| `ATTRITION_NEW_HIRE_THRESHOLD_MONTHS` | `3` | 0 – 24 | #21 — bu neçə aydan az staj "yeni işçi" sayılır | `domain/attrition_rules.py`, `application/use_cases/attrition_risk.py` |
| `ATTRITION_LEAVE_USAGE_WEIGHT` | `20` | 0 – 100 | #21 — aylıq icazə limitinin TAM (100%) istifadəsinə qarşılıq maksimum bal | `domain/attrition_rules.py`, `application/use_cases/attrition_risk.py` |
| `ATTRITION_WINDOW_MONTHS` | `3` | 1 – 24 | #21 — cərimə artımı/davamiyyət pozuntusu siqnallarının baxdığı ay sayı | `domain/attrition_rules.py`, `application/use_cases/attrition_risk.py` |
| `ATTRITION_HIGH_RISK_THRESHOLD` | `70` | 0 – 100 | #21 — bu bal həddindən (daxil) yuxarı "yüksək risk" sayılır və Store Manager → HR_Admin bildiriş zəncirini işə salır | `domain/attrition_rules.py`, `application/use_cases/attrition_risk.py` |
| `BENCHMARK_TREND_MONTHS` | `6` | 1 – 24 | #24 — Zaman-üzrə Trend widget-inin geriyə baxdığı ay sayı | `application/use_cases/multi_store_benchmark.py` |
| `BENCHMARK_OUTLIER_SIGMA_MULTIPLIER` | `2.0` | 0.5 – 5.0 | #24 — Kritik-Kənar kartının şəbəkə ortalamasından kənarlaşma həddi (σ) | `application/use_cases/multi_store_benchmark.py` |

---

### 13. Satış Xalları və POS

*5 parametr.*

Satış xalları mükafat KURSUDUR və kampaniya dövründə dəyişdirilməlidir —
`SALES_POINTS_CURRENCY_PER_POINT` əvvəllər koda bərkidilmişdi, halbuki şərh
onun «ROOT-dan idarə olunduğunu» yazırdı; boşluq Faza 10.2-də bağlandı.
`SALES_POINTS_DISPUTE_WINDOW_HOURS` cərimə pəncərəsi ilə EYNİ defoltdadır (72)
lakin AYRI açardır: sayğaclar fərqli andan başlayır (xal `awarded_at`-dan,
cərimə `publish()`-dan) və biri pul kəsintisi, digəri mükafatdır.
`POS_MAX_DISCOUNT_PCT_CEILING` sxem CHECK-ini (0–100, migrations/018) ƏVƏZ
ETMİR — onun ALTINDA Root-un öz əlavə tavanıdır.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `POS_MAX_DISCOUNT_PCT_CEILING` | `100` | 0 – 100 | #7 — POS Səlahiyyət Siyasətində işçiyə təyin edilə biləcək maksimum endirim faizinin Root-dan idarə olunan yuxarı tavanı (sxem sərhədi də 0–100-dür, migrations/018) | `application/use_cases/pos_threshold.py`, `presentation/controllers/pos_threshold.py` |
| `SALES_POINTS_CURRENCY_PER_POINT` | `100` | 1 – 100000 | Neçə AZN brutto satış 1 xal qazandırır | `domain/value_objects/gamification.py`, `application/use_cases/sales_points.py` |
| `SALES_POINTS_DISPUTE_WINDOW_HOURS` | `72` | 1 – 8760 | Xal etirazı pəncərəsi (saat) — cərimə pəncərəsindən AYRI parametr | `domain/value_objects/gamification.py`, `application/use_cases/sales_points.py` |
| `SALES_POINTS_RESET_NOTICE_DAYS` | `14` | 1 – 90 | 6 aylıq xal sıfırlanmasından neçə gün əvvəl bildiriş göndərilsin | `domain/value_objects/gamification.py`, `application/use_cases/sales_points.py` |
| `SALES_REVIEW_QUEUE_PAGE_SIZE` | `200` | 1 – 5000 | «Şübhəli Satışlar» növbəsinin bir oxunuşda gətirdiyi sətir sayı | `application/root_limits.py`, `application/use_cases/sales_review_queue.py` |

---

### 14. HR Əməliyyatları — Sənəd, Elan, Performans, Sahə Hesabatı, Toplu İdxal

*12 parametr.*

Bu qrupdakı bir neçə açar VERGÜLLÜ və ya `AÇAR:DƏYƏR` SİYAHISIDIR
(`EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS`, `PERFORMANCE_REVIEW_KPI_CATALOG`) və
bu, qəsdli naxışdır: üç ayrı açar Root-a xatırlatma cədvəlini YANLIŞ SIRAYA
(məs. 7 → 30) yazmaq imkanı verərdi, tək sətirdə isə bütöv cədvəl bir baxışda
görünür. `BULK_IMPORT_MAX_ROWS` ayrıca diqqət tələb edir: `bulk_import_log`-da
`REVOKE DELETE` var, yəni səhvən yüklənmiş 50 000 sətirlik faylın idxalını
LƏĞV ETMƏK MÜMKÜN DEYİL — tavan bu riski yükləmə anında, idxal başlamazdan
əvvəl kəsir.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS` | `30,14,7` | — | #17 — Sənəd bitmə tarixinə neçə gün qalanda xəbərdarlıq göndərilsin (vergüllə ayrılmış tam ədədlər, məs. "30,14,7") | `application/use_cases/employee_documents.py` |
| `ANNOUNCEMENT_VISIBILITY_DAYS` | `14` | 1 – 90 | #19 — Elan İşçi Ana Ekranında NEÇƏ GÜN görünsün (geri çəkilməyibsə belə) | `application/use_cases/announcements.py` |
| `PERFORMANCE_REVIEW_PERIOD_TYPE` | `MONTHLY` | — | #20 — Qiymətləndirmə formasının DEFOLT dövr granulyarlığı: MONTHLY (aylıq) və ya QUARTERLY (rüblük) | `application/use_cases/performance_reviews.py` |
| `PERFORMANCE_REVIEW_KPI_CATALOG` | `KEYFIYYET:İş Keyfiyyəti;MEHSULDARLIQ:Məhsuldarlıq;KOMANDA_ISI:Komanda İşi;MUSTERI_XIDMETI:Müştəri Xidməti` | — | #20 — Qiymətləndirmə formasının KPI siyahısı ("KOD:Ad;KOD:Ad" formatı) | `application/use_cases/performance_reviews.py` |
| `ANNOUNCEMENT_LIST_PAGE_SIZE` | `50` | 1 – 1000 | Elan admin siyahısının bir oxunuşda gətirdiyi sətir sayı | `application/root_limits.py`, `application/use_cases/announcements.py` |
| `FIELD_REPORT_AUDIT_INTERVAL_DAYS` | `30` | 1 – 365 | Mağaza auditinin tezliyi (gün). Bu ədəd auditi BLOKLAMIR — yalnız `FIELD_REPORT_AUDIT_REMINDER` gecəlik işinin "hansı filial gözdən qaçıb?" sualına cavabıdır | `application/use_cases/field_reports.py` |
| `FIELD_REPORT_MAX_PHOTOS` | `10` | 1 – 50 | Bir sahə hesabatına əlavə edilə bilən maksimum foto sayı. Hər şəkil Google Drive-da bir fayldır — tavansız massiv səhvən dövrəyə düşmüş yükləmə ilə kvotanı tək hesabatla yandırardı | `application/use_cases/field_reports.py`, `presentation/preview_data.py` +1 |
| `FIELD_REPORT_MIN_DETAIL_LENGTH` | `10` | 5 – 500 | Hesabat təsvirinin və bağlanma qeydinin minimum uzunluğu (simvol). Alt hüdud sxemin CHECK-i ilə eynidir (migrations/037) — daha aşağı dəyər ekranda qəbul edilib DB-də rədd edilərdi | `application/use_cases/field_reports.py`, `presentation/preview_data.py` +1 |
| `FIELD_REPORT_TASK_DEADLINE_DAYS` | `3` | 1 – 30 | Uğursuz BLOKLAYICI checklist bəndindən doğan düzəliş tapşırığının möhləti (gün). Mövcud Tapşırıq Mühərrikində yaranır (Struktur Qərar B) | `application/use_cases/field_reports.py` |
| `FIELD_REPORT_TASK_ASSIGNEE_ROLE` | `MAGAZA_MENECERI` | — | Düzəliş tapşırığının təyin edildiyi rol (`positions.code`). Boş və ya naməlum dəyər sistemi çökdürmür — tapşırıq hesabatı yazan şəxsə qalır | `application/use_cases/field_reports.py` |
| `BULK_IMPORT_MAX_ROWS` | `300` | 10 – 5000 | CSV toplu işçi idxalında qəbul edilən maksimum sətir sayı. Fayl bu tavanı aşarsa TAM RƏDD EDİLİR (sükutla kəsilmir) — HR faylı bölüb yenidən yükləməlidir. `bulk_import_log`-da DELETE olmadığı üçün səhvən yüklənmiş nəhəng fayl silinə bilməz, yalnız qarşısı alına bilər | `application/use_cases/bulk_operations.py` |
| `BULK_IMPORT_PREVIEW_ERROR_LIMIT` | `50` | 5 – 500 | Önizləmə ekranında sətir-sətir göstərilən xəta sayının tavanı. Aqreqat say (`bulk_import_log.error_count`) bu tavandan ASILI DEYİL — həmişə TAM yazılır, yalnız ətraflı siyahı kəsilir | `application/use_cases/bulk_operations.py`, `presentation/controllers/bulk_operations.py` |

---

### 15. Dəstək və Developer Paneli

*10 parametr.*

Bu qrup müştəri quraşdırmasının gündəlik işinə yox, hazırlayıcının Developer
Panelinə aiddir (bax [`cli_reference.md`](cli_reference.md)). Diqqət: sətirlər
yenə də kirayəçinin ÖZ `system_limits` cədvəlindədir və RLS ilə ona bağlıdır
(SEC-008) — Developer Panelinin çox-kirayəçi yolu onları OXUMUR, `DEFAULT_LIMITS`
fallback-ı ilə işləyir, çünki «hansı kirayəçinin sətri oxunsun?» sualının doğru
cavabı yoxdur. SLA hədləri kommersiya öhdəliyidir: müqavilə dəyişəndə kod
buraxılışı gözlənilməməlidir.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `DEVELOPER_DIRECTORY_STALE_DAYS` | `3` | 1 – 365 | Bu qədər gün check-in etməyən quraşdırma "səssiz" sayılır | `infrastructure/licensing/developer_directory.py` |
| `CRASH_MAX_REPORTS_PER_FINGERPRINT` | `3` | 1 – 100 | Eyni çökmə barmaq izi üçün bir sessiyada göndərilən hesabat tavanı | `infrastructure/notifications/crash_reporter.py` |
| `SUPPORT_FIRST_RESPONSE_SLA_HOURS` | `24` | 1 – 720 | Dəstək müraciətinə ilk cavab üçün hədəf (saat) | `application/root_limits.py`, `application/use_cases/developer_console.py` |
| `SUPPORT_RESOLUTION_SLA_HOURS` | `72` | 1 – 2160 | Dəstək müraciətinin tam həlli üçün hədəf (saat) | `application/root_limits.py`, `application/use_cases/developer_console.py` |
| `SUPPORT_SLA_AT_RISK_RATIO` | `0.75` | 0.10 – 0.99 | Hədəfin hansı hissəsindən sonra müraciət «risk altında» sayılsın | `application/root_limits.py`, `application/use_cases/developer_console.py` |
| `CRASH_WIDESPREAD_INSTALLATION_THRESHOLD` | `3` | 2 – 1000 | Çökmə neçə fərqli quraşdırmada təkrarlananda «kütləvi» sayılsın | `application/root_limits.py`, `application/use_cases/developer_console.py` |
| `CRASH_DASHBOARD_TOP_LIMIT` | `10` | 1 – 500 | Çökmə panelində göstərilən ən yüksək prioritetli qrup sayı | `application/root_limits.py`, `application/use_cases/developer_console.py` |
| `SUPPORT_THREAD_PAGE_SIZE` | `20` | 1 – 500 | Dəstək widget-inin bir oxunuşda gətirdiyi mövzu sayı | `application/root_limits.py`, `application/use_cases/support_chat.py` |
| `DEVELOPER_CRASH_ROW_LIMIT` | `12` | 1 – 200 | Developer Panelindəki çökmə cədvəlinin sətir tavanı | `developer_panel/ui.py`, `developer_panel/console.py` |
| `DEVELOPER_TICKET_ROW_LIMIT` | `12` | 1 – 200 | Developer Panelindəki dəstək cədvəlinin sətir tavanı | `developer_panel/ui.py`, `developer_panel/console.py` |

---

### 16. Plugin Sandbox

*2 parametr.*

Yalnız iki parametr var və hər ikisi «nə qədər gözləyək, nə qədər oxuyaq»
sualına cavab verir. **Bunlar ETİBAR SİYASƏTİ DEYİL:** plugin imzası,
nəşriyyatçı yoxlaması və `KOMPASOS_PLUGIN_TRUSTED_PUBLISHERS` fail-closed
qaydası (boş = heç bir plugin quraşdırılmır) struktur zəmanətdir və ROOT
panelindən dəyişdirilə bilmir.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `PLUGIN_SANDBOX_TIMEOUT_SECONDS` | `10.0` | 1.0 – 300.0 | Plugin sandbox icra taymautu (saniyə) | `infrastructure/plugins/sandbox.py` |
| `PLUGIN_SANDBOX_MAX_OUTPUT_BYTES` | `1048576` | 65536 – 67108864 | Plugin prosesindən oxunan maksimum çıxış (bayt) | `infrastructure/plugins/sandbox.py` |

---

### 17. Sistem, Baza və Saxlama

*18 parametr.*

Bu qrupun bir hissəsi tətbiqin İŞLƏMƏ QABİLİYYƏTİNƏ birbaşa təsir edir:
`DB_POOL_MAX_SIZE` 0 yazılsa heç bir sorğu icra oluna bilməz,
`BACKUP_DUMP_TIMEOUT_SECONDS` 0 olsa gecəlik nüsxə həmişə uğursuz olar. Ona
görə bu qrupun HAMISI `INFRA_LIMIT_BOUNDS` klampına tabedir — səhv dəyər
«tətbiq açılmır» deyil, «dəyər hüduda sıxıldı + `INFRA_LIMIT_CLAMPED`
xəbərdarlığı» ilə nəticələnir. `BACKUP_MIN_RETENTION_DAYS`-in aşağı hüdudu
30-da KİLİDLƏNİB: Root saxlama müddətini uzada bilər, spesifikasiyanın
minimumundan qısalda bilməz.

| Açar | Defolt | Hədd (min–maks) | Nəyə təsir edir | Kodda oxunur |
|---|---|---|---|---|
| `DB_MIGRATION_DRAIN_TIMEOUT_SECONDS` | `300` | 30 – 3600 | Offline buferin boşalmasını gözləmə həddi (saniyə) | `domain/value_objects/infrastructure.py` |
| `DB_MIGRATION_MAX_WINDOW_MINUTES` | `120` | 1 – 1440 | Texniki fasilə pəncərəsinin yuxarı həddi (dəqiqə) | `domain/value_objects/infrastructure.py` |
| `BACKUP_MIN_RETENTION_DAYS` | `30` | 30 – 3650 | Ehtiyat nüsxə saxlama müddətinin döşəməsi — 30-dan aşağı düşə bilməz | `infrastructure/backup/service.py` |
| `BACKUP_RETENTION_DAYS` | `30` | 30 – 3650 | Ehtiyat nüsxələrin saxlanma müddəti (gün) | `infrastructure/backup/service.py` |
| `BACKUP_DUMP_TIMEOUT_SECONDS` | `3600` | 60 – 86400 | pg_dump bu müddətdən uzun çəkərsə dayandırılır (saniyə) | `infrastructure/backup/service.py` |
| `HEALTH_DISK_WARNING_PERCENT` | `85.0` | 50 – 99 | Disk doluluğu bu faizi keçəndə xəbərdarlıq | `infrastructure/erp/system_health.py` |
| `HEALTH_DISK_CRITICAL_PERCENT` | `95.0` | 55 – 100 | Disk doluluğu bu faizi keçəndə kritik vəziyyət | `infrastructure/erp/system_health.py` |
| `HEALTH_DB_PING_SLOW_MS` | `500` | 50 – 60000 | DB ping bu müddətdən uzun çəkərsə "yavaş" sayılır (millisaniyə) | `infrastructure/erp/system_health.py` |
| `REALTIME_POLL_INTERVAL_SECONDS` | `30` | 5 – 3600 | Realtime kanalı polling rejimində sorğu aralığı (saniyə) | `infrastructure/realtime/channel.py` |
| `REALTIME_RECONNECT_BACKOFF_SECONDS` | `5,15,30,60` | 1 – 3600 | WebSocket yenidən qoşulma gözləmə cədvəli (vergüllü; hüdud hər elementə) | `infrastructure/realtime/channel.py` |
| `OFFLINE_SYNC_BATCH_SIZE` | `100` | 1 – 5000 | Offline buferdən bir dövrdə sinxronlaşdırılan yazı sayı | `infrastructure/offline/sync.py` |
| `OFFLINE_RETRY_BACKOFF_SECONDS` | `30,120,600` | 1 – 86400 | Offline yazı təkrar cəhd cədvəli (vergüllü; hüdud hər elementə) | `infrastructure/offline/buffer.py`, `infrastructure/storage/upload_queue.py` |
| `OFFLINE_SQLITE_TIMEOUT_SECONDS` | `10.0` | 1.0 – 120.0 | Offline SQLite kilid gözləmə taymautu (saniyə) | `infrastructure/offline/buffer.py`, `infrastructure/storage/upload_queue.py` |
| `DB_POOL_MIN_SIZE` | `1` | 1 – 32 | PostgreSQL bağlantı hovuzunun minimum ölçüsü | `infrastructure/persistence/connection.py` |
| `DB_POOL_MAX_SIZE` | `8` | 1 – 64 | PostgreSQL bağlantı hovuzunun maksimum ölçüsü | `infrastructure/persistence/connection.py` |
| `DB_CONNECT_TIMEOUT_SECONDS` | `15.0` | 1.0 – 300.0 | Hovuzdan bağlantı gözləmə taymautu (saniyə) | `infrastructure/persistence/connection.py` |
| `BACKUP_HISTORY_PAGE_SIZE` | `60` | 1 – 1000 | Bərpa nöqtələri siyahısının bir oxunuşda gətirdiyi sətir sayı | `application/root_limits.py`, `application/use_cases/backup_access.py` |
| `SYNC_CONFLICT_PAGE_SIZE` | `100` | 1 – 2000 | Sinxronizasiya konflikti inbox-unun bir oxunuşda gətirdiyi sətir sayı | `application/root_limits.py`, `application/use_cases/sync_conflicts.py` |

---

## Yekun

Sənəddə **182 parametr** sənədləşdirilib — bu, `SystemLimitKey` enum-undakı
üzvlərin **hamısıdır** (`len(SystemLimitKey) == 182`,
`len(DEFAULT_LIMITS) == 182`). Rəqəm avtomatik yoxlana bilər:

```bash
.venv/Scripts/python.exe -c "from src.domain.policies import SystemLimitKey; print(len(SystemLimitKey))"
```

Hamısı (**182/182**) `schema.sql` və ya bir miqrasiya ilə
`system_limits`-ə seed edilib, yəni ROOT ekranında görünür və dəyişdirilə bilir.

Aralıq bölgüsü: **170 açarın** ədədi `min_value`/`max_value` hüdudu var;
qalan **12-si** mətn, siyahı və ya kataloq tiplidir
(`EXCEPTION_NOTIFY_MIN_SEVERITY`, `NOTIFY_RETRY_BACKOFF_MINUTES`,
`PERFORMANCE_REVIEW_KPI_CATALOG` və s.) — onlar üçün ədədi aralıq mənasızdır və
sütunlar `NULL` saxlanılır.

Əlavə olaraq **51 açar** oxu anında `INFRA_LIMIT_BOUNDS` ilə də KLAMP edilir
(`src/infrastructure/config/limits.py`): onlar tətbiqin işləmə qabiliyyətinə
birbaşa təsir edir və səhv dəyər «tətbiq açılmır» ilə nəticələnə bilərdi.
