"""Konfiqurasiya edilə bilən biznes siyasətləri (spesifikasiya bölmə 3).

ROOT CONTROL CENTER-dəki `system_limits` dəyərləri burada tipləşdirilmiş
formada təqdim olunur. Domen qatı DB-ni tanımır — dəyərlər `SystemLimits`
portu (bax `interfaces.ports`) vasitəsilə ötürülür.

QAYDA: sistem limiti OLMAYAN sabit dəyər domen kodunda hardcode edilə bilməz
(bölmə 3, DİNAMİK LİMİT VƏ TAYMAUT İDARƏETMƏSİ) — istisna yalnız struktur
təhlükəsizlik zəmanətləridir (hardlock, anti-fraud, guard-lar).

──────────────────────────────────────────────────────────────────────────────
BU MODUL YARPAQDIR — RUNTIME-DA HEÇ BİR DOMEN MODULUNU İDXAL ETMİR
──────────────────────────────────────────────────────────────────────────────
`value_objects/*` modulları (licensing, updates, erp, catalogs, storage,
gamification, infrastructure) fallback sabitlərini artıq `DEFAULT_LIMITS`-dən
oxuyur — yəni oxu istiqaməti `value_objects → policies`-dir. Əgər bu fayl
`Money`-ni modul səviyyəsində idxal etsəydi, əks istiqamət də yaranardı:
`import src.domain.policies` əvvəlcə `src/domain/value_objects/__init__.py`-ni
TAM icra edərdi (alt-modul idxalı paket `__init__`-ini işə salır), o isə
yarımçıq qalmış `policies`-dən `DEFAULT_LIMITS` istəyərdi — dairəvi idxal.

Ona görə `Money` YALNIZ `TYPE_CHECKING` altında və `amount_for` daxilində
idxal olunur. Alternativ (fallback sabitlərini ayrı bir modula köçürmək) rədd
edildi: onda "defolt haradadır?" sualının İKİ cavabı olardı və parity qapısı
(`tests/unit/test_root_control_parameter_parity.py`) yalnız birini görərdi.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from src.domain.value_objects.money import Money


class SystemLimitKey(str, Enum):
    """`system_limits.limit_key` dəyərləri — DB seed-i ilə eyni."""

    MONTHLY_LEAVE_MINUTES_LIMIT = "MONTHLY_LEAVE_MINUTES_LIMIT"
    FINE_APPEAL_WINDOW_HOURS = "FINE_APPEAL_WINDOW_HOURS"
    LATE_TOLERANCE_MINUTES = "LATE_TOLERANCE_MINUTES"
    VERIFICATION_TIMEOUT_MINUTES = "VERIFICATION_TIMEOUT_MINUTES"
    DUAL_CONTROL_THRESHOLD_MINUTES = "DUAL_CONTROL_THRESHOLD_MINUTES"
    #: İkinci təsdiq nə qədər gözləyə bilər (M-5). AYRI açardır, çünki
    #: `DUAL_CONTROL_THRESHOLD_MINUTES` "hansı düzəliş təsdiq TƏLƏB EDİR"
    #: sualına, bu isə "təsdiq NƏ QƏDƏR gözləyə bilər" sualına cavab verir —
    #: biri hadisənin ölçüsü, digəri prosesin SLA-sıdır. Bir açara
    #: bağlansaydılar, Root həddi 45-ə qaldıranda gözləmə müddəti də
    #: sükutla dəyişərdi.
    DUAL_CONTROL_APPROVAL_TIMEOUT_MINUTES = "DUAL_CONTROL_APPROVAL_TIMEOUT_MINUTES"
    PIN_MAX_FAILED_ATTEMPTS = "PIN_MAX_FAILED_ATTEMPTS"
    PIN_LOCKOUT_MINUTES = "PIN_LOCKOUT_MINUTES"
    NTP_MAX_DRIFT_SECONDS = "NTP_MAX_DRIFT_SECONDS"
    MAX_UPLOAD_SIZE_BYTES = "MAX_UPLOAD_SIZE_BYTES"
    # --- BR-001 ilə əlavə olunanlar (bax aşağı) ---
    LEAVE_ALLOWANCE_SOURCE = "LEAVE_ALLOWANCE_SOURCE"
    LEAVE_ALLOWANCE_FIXED_MINUTES = "LEAVE_ALLOWANCE_FIXED_MINUTES"
    # --- DEEP-GAP D1: Gündəlik Tabeldə təsdiqlənmiş illik məzuniyyət ---
    #
    # Təsdiqlənmiş illik məzuniyyət günü Attendance Report-un "faktiki
    # işlənilən gün" sayğacına DÜŞSÜNMÜ? Bu, mühasibatlıq SİYASƏTİDİR: bəzi
    # müəssisə ödənişli məzuniyyəti norma/bonus hesablamasında iş günü kimi
    # sayır, bəzisi YALNIZ fiziki iş günlərini sayır. `AttendanceCountingPolicy`
    # (bax `entities.attendance_sheet`) bu açarı oxuyur. EKRAN ETİKETİ bu
    # açardan ASILI DEYİL — status HƏMİŞƏ "🟣 Məzuniyyətdə"dir və HEÇ VAXT
    # "🔴 İcazəsiz qayıb" olmur (struktur zəmanət, §5-in xaricindədir çünki
    # anti-fraud/hardlock deyil, lakin `derive_status` sırasında HƏMİŞƏ
    # `ABSENT`-dən ƏVVƏL yoxlanır — bu açar yalnız SAYĞACI dəyişir).
    ANNUAL_LEAVE_COUNTS_AS_WORKED_DAY = "ANNUAL_LEAVE_COUNTS_AS_WORKED_DAY"
    # --- BR-002 ilə əlavə olunan (bax aşağı) ---
    DELAY_FINE_RATE_PER_MINUTE = "DELAY_FINE_RATE_PER_MINUTE"
    # --- Vahid İstisna Motoru (#9, kompasos11.md Faza 3) ---
    #
    # DÖRDÜ DƏ ROOT PARAMETRİDİR. Motorda sabit ədəd QALMIR: hər biri
    # `system_limits`-dən oxunur və `DEFAULT_LIMITS` yalnız DB sətri hələ
    # seed edilməmiş yollar üçün fallback-dır (seed: migrations/022).
    EXCEPTION_PAGE_SIZE = "EXCEPTION_PAGE_SIZE"
    EXCEPTION_MAX_FINDINGS_PER_RULE = "EXCEPTION_MAX_FINDINGS_PER_RULE"
    EXCEPTION_NOTIFY_MIN_SEVERITY = "EXCEPTION_NOTIFY_MIN_SEVERITY"
    EXCEPTION_REVIEW_NOTE_MIN_LENGTH = "EXCEPTION_REVIEW_NOTE_MIN_LENGTH"
    # --- #7 POS Səlahiyyət Siyasəti (kompasos11.md Faza 4, sənədləşdirmə) ---
    #
    # YEGANƏ ROOT PARAMETRİ: DB `CHECK`-i (migrations/018) 0–100 sxem
    # sərhədidir və dəyişməz; bu açar isə Root-un ONUN DA altında öz biznes
    # siyasətini tətbiq edə biləcəyi ƏLAVƏ tavandır (məs. "heç bir işçiyə
    # 40%-dən çox endirim səlahiyyəti verilməsin"). Defolt 100 = sxem
    # sərhədi ilə eyni, yəni başlanğıcda ƏLAVƏ məhdudiyyət YOXDUR.
    POS_MAX_DISCOUNT_PCT_CEILING = "POS_MAX_DISCOUNT_PCT_CEILING"
    # --- #8 İşçi Davranış Baz Xətti (kompasos11.md Faza 5) ---
    #
    # DÖRDÜ DƏ ROOT PARAMETRİDİR (tapşırığın açıq tələbi). Sinifdə (bax
    # `application.use_cases.behavior_baseline`) qalan ədəd YALNIZ
    # `system_limits` sətri hələ seed edilməyibsə işə düşən fallback-dır
    # (seed: migrations/024).
    #
    # Baxılan gün sayı — kompasos11.md açıq şəkildə "son 30 günün orta
    # check-in vaxtı" deyir, ona görə defolt 30-dur, lakin Root onu dəyişə
    # bilməlidir (məs. mövsümi mağazada daha qısa pəncərə lazım ola bilər).
    BEHAVIOR_BASELINE_WINDOW_DAYS = "BEHAVIOR_BASELINE_WINDOW_DAYS"
    # Bugünkü check-in baz xəttindən neçə dəqiqə sapanda anomaliya elan
    # edilsin. Spesifikasiyanın açıq tələbi (kompasos11.md Faza 5, addım 2).
    BEHAVIOR_ANOMALY_THRESHOLD_MINUTES = "BEHAVIOR_ANOMALY_THRESHOLD_MINUTES"
    # MİNİMUM NÜMUNƏ HƏDDİ — migrations/018 `sample_size` şərhinin açıq
    # tələbi: "3 günlük müşahidədən çıxan baz xətt ilə anomaliya elan etmək
    # yanlış ittihamdır". Bu hədddən az müşahidəsi olan işçi üçün qayda HEÇ
    # NƏ elan etmir (baz xətti yenə də yazılır — yalnız istifadəsi bloklanır).
    BEHAVIOR_BASELINE_MIN_SAMPLE_SIZE = "BEHAVIOR_BASELINE_MIN_SAMPLE_SIZE"
    # σ VURUĞU — sapmanın CİDDİYYƏTİNİ dərəcələndirmək üçün: kənarlaşma işçinin
    # ÖZ standart kənarlaşmasının bu qat qədərini keçəndə ciddiyyət bir pillə
    # yuxarı qalxır (statistik cəhətdən "adətdən çıxma" nə qədər ekstremdir).
    # Əsas AÇMA/BAĞLAMA qapısı YENƏ DƏ dəqiqə həddidir — σ yalnız artıq
    # aşkarlanmış anomaliyanın rəngini (LOW→CRITICAL) təyin edir.
    BEHAVIOR_ANOMALY_SIGMA_MULTIPLIER = "BEHAVIOR_ANOMALY_SIGMA_MULTIPLIER"
    # --- #15 Norma üstü iş saatlarının izlənməsi (kompasos11.md Faza 6) ---
    #
    # ÜÇÜ DƏ ROOT PARAMETRİDİR. Norma saatı ƏMƏK QANUNVERİCİLİYİ dəyəridir və
    # kirayəçidən kirayəçiyə (hətta mövsümdən mövsümə) fərqlənə bilər — onu
    # koda yazmaq "8" rəqəmini dəyişdirmək üçün yeni buraxılış tələb edərdi.
    # `application.use_cases.overtime_tracking`-dəki sabitlər YALNIZ
    # `system_limits` sətri hələ seed edilməyibsə işə düşən fallback-dır
    # (seed: migrations/026).
    #
    # GÜNDƏLİK norma: bir iş gününün neçə saatdan sonra "norma üstü" saydığı.
    OVERTIME_DAILY_NORM_HOURS = "OVERTIME_DAILY_NORM_HOURS"
    # HƏFTƏLİK norma: gündəlik norma heç vaxt aşılmasa belə, həftədə çox GÜN
    # işləmək aşım yaradır (6 × 7 saat = 42). İki norma bir-birini əvəz etmir,
    # TAMAMLAYIR — ona görə hər ikisi ayrıca parametrdir.
    OVERTIME_WEEKLY_NORM_HOURS = "OVERTIME_WEEKLY_NORM_HOURS"
    # BİLDİRİŞ HƏDDİ — bu hədddən (daxil olmaqla) böyük aşım HR_Admin-ə
    # bildiriş doğurur. Jurnala isə aşımın HAMISI yazılır: hədd yalnız
    # bildiriş kanalının səs-küydən qorunmasıdır (15 dəqiqəlik aşıma görə
    # hər gün e-poçt getsəydi, kanal bir həftədə görməzdən gəlinərdi).
    OVERTIME_NOTIFY_THRESHOLD_HOURS = "OVERTIME_NOTIFY_THRESHOLD_HOURS"
    # --- #14 Əmək qanunu xəbərdarlığı (kompasos11.md Faza 6) ---
    #
    # DÖRDÜ DƏ ROOT PARAMETRİDİR. Qayda BLOKLAMIR, yalnız xəbərdarlıq göstərir
    # (bax `domain.labor_rules` başlığı) — ona görə hədlər "təhlükəsizlik
    # zəmanəti" DEYİL və CLAUDE.md §5-ə görə yerləri məhz `system_limits`-dədir.
    # `LaborLimits.defaults()` yalnız DB sətri hələ seed edilməyibsə işə düşür
    # (seed: migrations/025).
    #
    # İki ardıcıl növbə arasındakı minimum istirahət (saat). Gecə növbəsi
    # nəzərə alınır: hesablama növbənin BİTMƏ ANINDAN aparılır, bitmə
    # saatından yox.
    LABOR_MIN_REST_HOURS = "LABOR_MIN_REST_HOURS"
    # Uzun növbədə nəzərdə tutulmalı fasilənin MÜDDƏTİ (dəqiqə).
    LABOR_MANDATORY_BREAK_MINUTES = "LABOR_MANDATORY_BREAK_MINUTES"
    # Fasilənin MƏCBURİ olduğu hədd (saat). Müddət və hədd AYRI parametrdir,
    # çünki müəssisələr onları müstəqil təyin edir; tək parametr ya hər
    # növbədə xəbərdarlıq verərdi (səs-küy), ya da heç vaxt.
    LABOR_BREAK_REQUIRED_AFTER_HOURS = "LABOR_BREAK_REQUIRED_AFTER_HOURS"
    # İstirahət günü olmadan ardıcıl neçə gün işləmək olar.
    LABOR_MAX_CONSECUTIVE_WORK_DAYS = "LABOR_MAX_CONSECUTIVE_WORK_DAYS"
    # --- #13 Tarixi-nümunə əsaslı kadr təklifi (kompasos11.md Faza 6) ---
    #
    # TAPŞIRIĞIN AÇIQ TƏLƏBİ: "neçə həftəlik tarixçəyə baxılsın" ROOT
    # parametridir. Pəncərənin uzunluğu təklifin keyfiyyətini birbaşa təyin
    # edir (qısa = təsadüfi, uzun = köhnəlmiş), yəni bu, müəssisənin öz
    # mövsümi ritminə görə tənzimlədiyi dəyərdir — koda yazıla bilməz.
    STAFFING_PATTERN_BASED_ON_WEEKS = "STAFFING_PATTERN_BASED_ON_WEEKS"
    # --- #16 Açıq Növbə Bazarı (kompasos11.md Faza 6) ---
    #
    # HƏR İKİSİ ROOT PARAMETRİDİR. `application.use_cases.open_shift_market`
    # sinfindəki sabitlər YALNIZ `system_limits` sətri hələ seed edilməyibsə
    # işə düşən fallback-dır (seed: migrations/027).
    #
    # Elan neçə gün irəli üçün verilə bilər. Növbə DƏYİŞMƏ sorğusundakı 90
    # günlük pəncərədən (bax `shift_scheduling.MAX_SWAP_LEAD_DAYS`) qəsdən
    # FƏRQLİDİR: orada işçi ÖZ mövcud gününü dəyişir, burada isə hələ heç
    # kimə aid olmayan slot elan olunur. Üç ay əvvəldən "açıq" qalan elan
    # bazarı yox, planlaşdırılmamış təqvimi göstərərdi — o iş Shift
    # Matrix-indir.
    OPEN_SHIFT_MAX_LEAD_DAYS = "OPEN_SHIFT_MAX_LEAD_DAYS"
    # Bir işçinin BİR TƏQVİM AYINDA götürə biləcəyi açıq növbə sayı. Tavan
    # olmasa açıq bazar sükutla "daimi əlavə iş" mexanizminə çevrilərdi:
    # eyni işçi hər elanı tutar, norma üstü saatı (#15) və istirahət qaydası
    # (#14) isə yalnız FAKT baş verdikdən SONRA xəbərdarlıq verərdi.
    OPEN_SHIFT_MAX_CLAIMS_PER_MONTH = "OPEN_SHIFT_MAX_CLAIMS_PER_MONTH"
    # --- #17 İşçi Sənədləri (kompasos11.md Faza 7) --------------------------- #
    #
    # ROOT PARAMETRİDİR (tapşırığın açıq tələbi: "bu gün ədədləri hardcode
    # edilməməlidir"). ÜÇ AYRI AÇAR ƏVƏZİNƏ BİR SİYAHI-AÇAR seçildi: üç hədd
    # BİRGƏ bir "xatırlatma cədvəli" təşkil edir (30 → 14 → 7 gün) və ayrı
    # açarlarda Root onları YANLIŞ SIRAYA (məs. FAR=7, NEAR=30) yaza bilərdi —
    # bu, "hansı ədəd hansı pillədir" sualını sükutla pozardı. Tək sətirdə
    # (`"30,14,7"`) Root bir dəfəyə bütöv cədvəli görür və dəyişdirir; format
    # `EXCEPTION_NOTIFY_MIN_SEVERITY` kimi digər `TEXT` limitlərlə eynidir —
    # `min_value`/`max_value` mənasızdır (bax migrations/022 şərhi).
    EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS = "EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS"
    # --- #19 Elan (Broadcast) (kompasos11.md Faza 8) ------------------------- #
    #
    # ROOT PARAMETRİDİR: elanın İşçi Ana Ekranında NEÇƏ GÜN görünəcəyi. Geri
    # çəkmə (`withdraw`) əl ilədir və HƏMİŞƏ mövcuddur, lakin admin unudanda
    # köhnə elan əbədi qalmamalıdır — kiosk ekranı köhnəlmiş göstərişlərlə
    # dolardı. Sətir SİLİNMİR/deaktiv EDİLMİR: yalnız YENİ görüntülənmə
    # dayanır (`is_active`-dan MÜSTƏQİL bir ölçüdür, `Announcement.
    # is_within_visibility_window` başlığına bax).
    ANNOUNCEMENT_VISIBILITY_DAYS = "ANNOUNCEMENT_VISIBILITY_DAYS"
    # --- #20 Performans Qiymətləndirməsi (kompasos11.md Faza 8) -------------- #
    #
    # ROOT PARAMETRİ: dövr GRANULYARLIĞI (aylıq/rüblük) — tapşırığın açıq
    # tələbi. Dəyər `PerformanceReviewPeriodType`-a uyğunlaşdırılır; forma
    # bugünkü tarixdən DEFOLT dövr sətrini bu açara görə hesablayır, lakin
    # `performance_reviews.period` sərbəst formatı (illik də) qəbul etməyə
    # davam edir (bax `entities/performance_review.py`).
    PERFORMANCE_REVIEW_PERIOD_TYPE = "PERFORMANCE_REVIEW_PERIOD_TYPE"
    # KPI KATALOQU — SƏRT SİYAHI KODA YAZILMIR (tapşırığın açıq tələbi).
    # Format: "KOD:Ad;KOD:Ad;..." — `EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS`-in
    # vergüllü siyahı naxışının İKİ SƏVİYYƏLİ variantı (KPI kodu VƏ Azərbaycanca
    # etiketi birlikdə). Ayrı "KOD" və "ETİKET" açarları RƏDD EDİLDİ: onlar
    # sıra ilə uyğunlaşdırılmalı olardı (n-ci kod → n-ci etiket) və Root iki
    # siyahını fərqli uzunluqda saxlaya bilərdi — sükutla "hansı etiket hansı
    # koda aiddir" sualını pozardı (`EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS`-in
    # eyni əsaslandırması, migrations/028).
    PERFORMANCE_REVIEW_KPI_CATALOG = "PERFORMANCE_REVIEW_KPI_CATALOG"
    # --- #21 İşdən Çıxma Riski Balı (kompasos11.md Faza 9) ------------------- #
    #
    # YEDDİSİ DƏ ROOT PARAMETRİDİR (tapşırığın açıq tələbi: "hər siqnalın
    # çəkisi ... bunlar system_limits-də, kod-hardcode DEYİL"). Sinifdə
    # (bax `domain.attrition_rules.AttritionWeights.defaults`) qalan ədəd
    # YALNIZ `system_limits` sətri hələ seed edilməyibsə işə düşən fallback-dır
    # (seed: migrations/030). "Yüksək risk" sayılan bal həddi də BURADADIR —
    # sabit 70/80 kimi bir ədəd Root-un öz müəssisəsinin normal dövriyyə
    # səviyyəsini bilmədən doğru olmazdı.
    #
    # Son `ATTRITION_WINDOW_MONTHS` ayı iki yarıya bölüb sonuncu yarımdakı
    # cərimə sayının əvvəlkindən artımına verilən bal (mütləq say YOX, artım —
    # bax `attrition_rules.py` başlığı).
    ATTRITION_FINE_TREND_WEIGHT = "ATTRITION_FINE_TREND_WEIGHT"
    # Eyni pəncərədə hər icazəsiz davamiyyət pozuntusuna verilən bal.
    ATTRITION_ATTENDANCE_VIOLATION_WEIGHT = "ATTRITION_ATTENDANCE_VIOLATION_WEIGHT"
    # Staj `ATTRITION_NEW_HIRE_THRESHOLD_MONTHS`-dan az olduqda verilən SABİT bal
    # ("onboarding riski") — iki parametr AYRIDIR, çünki müəssisələr "nə qədər
    # bal" və "neçə aya qədər yeni sayılır" suallarını müstəqil tənzimləyir
    # (`LABOR_MANDATORY_BREAK_MINUTES`/`LABOR_BREAK_REQUIRED_AFTER_HOURS`
    # cütü ilə eyni əsaslandırma).
    ATTRITION_NEW_HIRE_RISK_POINTS = "ATTRITION_NEW_HIRE_RISK_POINTS"
    ATTRITION_NEW_HIRE_THRESHOLD_MONTHS = "ATTRITION_NEW_HIRE_THRESHOLD_MONTHS"
    # Cari ay icazə istifadəsinin aylıq limitə (`MONTHLY_LEAVE_MINUTES_LIMIT`)
    # nisbəti 100%-ə çatanda verilən MAKSİMUM bal (nisbətlə xətti miqyaslanır).
    ATTRITION_LEAVE_USAGE_WEIGHT = "ATTRITION_LEAVE_USAGE_WEIGHT"
    # Cərimə artımı/davamiyyət pozuntusu siqnallarının baxdığı ay sayı —
    # "son 3 ayda cərimə artımı" tapşırığın öz nümunəsidir, lakin ədəd
    # koda yazılmır.
    ATTRITION_WINDOW_MONTHS = "ATTRITION_WINDOW_MONTHS"
    # Bu bal həddindən (daxil olmaqla) yuxarı "yüksək risk" sayılır və
    # bildiriş zəncirini (Store Manager → HR_Admin) işə salır.
    ATTRITION_HIGH_RISK_THRESHOLD = "ATTRITION_HIGH_RISK_THRESHOLD"
    # --- #24 Çox-Mağaza Benchmark Dashboard (kompasos11.md Faza 9A) --------- #
    #
    # İKİSİ DƏ ROOT PARAMETRİDİR (tapşırığın açıq tələbi: "6 ay/2σ hardcode
    # edilməməlidir"). Sinifdə (bax `application.use_cases.multi_store_
    # benchmark`) qalan ədəd YALNIZ `system_limits` sətri hələ seed
    # edilməyibsə işə düşən fallback-dır (seed: migrations/031).
    #
    # Zaman-üzrə Trend widget-inin geriyə baxdığı ay sayı.
    BENCHMARK_TREND_MONTHS = "BENCHMARK_TREND_MONTHS"
    # Kritik-Kənar (Outlier) kartının standart-sapma həddi —
    # `BEHAVIOR_ANOMALY_SIGMA_MULTIPLIER` ilə EYNİ statistik məntiq, fərqli
    # domende (mağaza müqayisəsi, işçi baz xətti YOX).
    BENCHMARK_OUTLIER_SIGMA_MULTIPLIER = "BENCHMARK_OUTLIER_SIGMA_MULTIPLIER"
    # --- Faza 10.2 — DOMEN VALUE OBJECT PARAMETRLƏRİ ------------------------ #
    #
    # AŞAĞIDAKI 22 AÇAR `src/domain/value_objects/` faylarında SABİT ƏDƏD kimi
    # yaşayırdı. Heç biri CLAUDE.md §5-in struktur zəmanətlərinə aid deyil
    # (anti-fraud, SEC-001, hierarchy/self-escalation guard, `HardlockLevel`
    # toxunulmaz qalır) — hamısı müəssisənin şəbəkəsindən, kommersiya
    # şərtindən və ya iş rejimindən asılı ƏMƏLİYYAT/SİYASƏT dəyəridir.
    #
    # DAVRANIŞ DƏYİŞMİR: hər defolt köçürmədən ƏVVƏLKİ hardcode ilə HƏRFƏN
    # eynidir. Value object-lərdəki sabitlər YERİNDƏ QALIR, lakin artıq ədəd
    # SAXLAMIR — dəyəri `DEFAULT_LIMITS`-dən oxuyur və yalnız `system_limits`
    # sətri əlçatmaz olduqda işə düşən FALLBACK-dır (seed: migrations/033).
    # Naxış `domain.labor_rules.LaborLimits.defaults()` ilə eynidir.
    #
    # Satış xalları (#6). `SALES_POINTS_CURRENCY_PER_POINT` — bal sisteminin
    # MƏRKƏZİ parametri: neçə AZN brutto satış 1 xal qazandırır. Əvvəl
    # `gamification.py` şərhi onun "ROOT-dan idarə olunduğunu" YAZIRDI, halbuki
    # belə açar heç vaxt mövcud olmayıb — yəni mükafat kursu faktiki olaraq
    # koda bərkidilmişdi və kampaniya dövründə dəyişdirilə bilmirdi.
    SALES_POINTS_CURRENCY_PER_POINT = "SALES_POINTS_CURRENCY_PER_POINT"
    # Xal etirazı pəncərəsi. `FINE_APPEAL_WINDOW_HOURS`-a BAĞLANMADI, AYRI
    # AÇAR verildi — səbəb: (a) sayğaclar FƏRQLİ andan başlayır (xal
    # `awarded_at`-dan, cərimə `publish()`-dan), (b) biri pul kəsintisi, digəri
    # mükafat kursudur və müəssisə pul mübahisəsinə daha uzun müddət verə
    # bilər, (c) bağlansaydı, Root cərimə pəncərəsini dəyişəndə xal pəncərəsi
    # də SÜKUTLA dəyişərdi — ekranda isə yalnız bir sətir görünərdi.
    # Defolt HƏR İKİSİNDƏ 72-dir (bölmə 6: "eyni məntiqlə").
    SALES_POINTS_DISPUTE_WINDOW_HOURS = "SALES_POINTS_DISPUTE_WINDOW_HOURS"
    # 6 aylıq sıfırlanmadan neçə gün əvvəl işçiyə bildiriş gedir. Sıfırlanma
    # TARİXLƏRİ (1 Yanvar / 1 İyul) parametr DEYİL və qalır (bax `gamification`
    # başlığı) — dəyişən yalnız xəbərdarlığın qabaqcadanlığıdır.
    SALES_POINTS_RESET_NOTICE_DAYS = "SALES_POINTS_RESET_NOTICE_DAYS"
    # Lisenziya klienti (bölmə 8). Yoxlama ritmi kommersiya qərarıdır: sutkalıq
    # dövr 21 filial üçün seçilib, lakin zəif internetli quraşdırmada seyrək,
    # ödəniş gecikməsi olan müştəridə isə sıx ritm lazım ola bilər.
    LICENSE_CHECK_IN_INTERVAL_SECONDS = "LICENSE_CHECK_IN_INTERVAL_SECONDS"
    LICENSE_RETRY_INTERVAL_SECONDS = "LICENSE_RETRY_INTERVAL_SECONDS"
    LICENSE_BLOCKED_RECHECK_INTERVAL_SECONDS = "LICENSE_BLOCKED_RECHECK_INTERVAL_SECONDS"
    # Offline qrace aralığı. Bu üç açar `license_tenants.offline_grace_days`
    # CHECK-inin (7–14) GÜZGÜSÜDÜR, onun ƏVƏZİ DEYİL: sütun dəyəri onsuz da
    # CHECK ilə bağlıdır, buradakı sıxma isə oxunan dəyəri həmin bandda
    # saxlayır. Miqrasiyadakı `max_value` 14-də kilidlənib — Root bandı
    # GENİŞLƏNDİRƏ bilməz (DB onsuz da 14-dən böyüyünü qəbul etməz),
    # yalnız DARALDA bilər (daha sərt offline siyasəti).
    LICENSE_MIN_OFFLINE_GRACE_DAYS = "LICENSE_MIN_OFFLINE_GRACE_DAYS"
    LICENSE_MAX_OFFLINE_GRACE_DAYS = "LICENSE_MAX_OFFLINE_GRACE_DAYS"
    LICENSE_DEFAULT_OFFLINE_GRACE_DAYS = "LICENSE_DEFAULT_OFFLINE_GRACE_DAYS"
    # Developer Panelindəki "[1 Ay Uzat]" düyməsinin əlavə etdiyi gün sayı —
    # kommersiya şərti (aylıq abunə) dəyişəndə kod buraxılışı gözlənilməməlidir.
    LICENSE_EXTENSION_DAYS = "LICENSE_EXTENSION_DAYS"
    # Saatın geri çəkilməsinin "manipulyasiya" sayılma həddi. TAVANI SƏRTDİR
    # (migrations/033: 30–900 saniyə) — bu, müddət bitməsinin yeganə qoruyucu
    # ölçüsüdür və böyük tolerantlıq onu faktiki söndürərdi: 6 saatlıq tolerantlıq
    # hər gün 6 saat geri çəkilməyə icazə verərdi. Yuxarı hədd 15 dəqiqədir,
    # çünki NTP düzəlişi saniyələrlə ölçülür və yay/qış saatı UTC-də sıçrayış
    # YARATMIR (müqayisə tz-aware UTC anları üzərindədir).
    LICENSE_CLOCK_ROLLBACK_TOLERANCE_SECONDS = "LICENSE_CLOCK_ROLLBACK_TOLERANCE_SECONDS"
    # Müddətin bitməsinə neçə gün qalanda banner göstərilsin (bloklamır).
    LICENSE_EXPIRY_WARNING_DAYS = "LICENSE_EXPIRY_WARNING_DAYS"
    # Avtomatik yenilənmə klienti. Yoxlama/təkrar cəhd ritmi lisenziya ilə eyni
    # səbəbdən parametrdir; paket tavanı isə fail-closed qoruyucudur (diski
    # dolduran nəhəng fayl) — ona görə miqrasiyada 2 GB tavanı var.
    UPDATE_CHECK_INTERVAL_SECONDS = "UPDATE_CHECK_INTERVAL_SECONDS"
    UPDATE_RETRY_INTERVAL_SECONDS = "UPDATE_RETRY_INTERVAL_SECONDS"
    UPDATE_MAX_PACKAGE_BYTES = "UPDATE_MAX_PACKAGE_BYTES"
    # 1C sinxronizasiyası. Səhifə ölçüsü mağaza PC-sinin yaddaşı və 1C
    # serverinin yükü ilə balanslaşdırılır — 21 filialda eyni ədəd optimal
    # olmaya bilər. (`ERP_SYNC_MAX_PAGES_PER_RUN` DÖVRDƏKİ SƏHİFƏ SAYIDIR,
    # bu isə BİR səhifədəki sənəd sayı — iki fərqli ölçü.)
    ERP_SYNC_PAGE_SIZE = "ERP_SYNC_PAGE_SIZE"
    # Ad-əsaslı fallback uyğunlaşmasının qəbul həddi. AŞAĞI HÜDUD SƏRTDİR
    # (0.70): ondan aşağı "Əliyev Elnur" ↔ "Əliyev Elvin" keçər və satış xalı
    # SƏHV işçiyə yazılardı. Yuxarı hüdud 1.00 = yalnız hərfi bərabərlik.
    ERP_NAME_MATCH_THRESHOLD = "ERP_NAME_MATCH_THRESHOLD"
    # İcazə Növü kataloqunda tövsiyə olunan müddətin tavanı. Sxem CHECK-i
    # DEYİL (DB `default_duration_minutes` üçün belə hədd saxlamır) — bu,
    # kataloq ekranının biznes qaydasıdır: müəssisə tam iş günü (12 saat)
    # əvəzinə daha qısa/uzun tavan seçə bilər.
    LEAVE_TYPE_MAX_DURATION_MINUTES = "LEAVE_TYPE_MAX_DURATION_MINUTES"
    # Baza keçidi (Cloud ↔ Şəxsi server). Hər iki dəyər TEXNİKİ FASİLƏ
    # planlamasına aiddir və müəssisənin iş qrafikindən asılıdır: gecə
    # bağlanan mağaza uzun pəncərə seçə bilər, 24 saat işləyən isə yox.
    DB_MIGRATION_DRAIN_TIMEOUT_SECONDS = "DB_MIGRATION_DRAIN_TIMEOUT_SECONDS"
    DB_MIGRATION_MAX_WINDOW_MINUTES = "DB_MIGRATION_MAX_WINDOW_MINUTES"
    # Sübut şəklinin kiçildilmə kənarları (piksel). Drive kvotası, şəbəkə
    # sürəti və ekran ölçüsü quraşdırmadan-quraşdırmaya fərqlənir; kiçik
    # kənar kvotaya qənaət edir, böyük kənar mübahisədə şəklin oxunaqlığını
    # saxlayır — bu balansı Root seçir.
    EVIDENCE_THUMBNAIL_MAX_EDGE_PX = "EVIDENCE_THUMBNAIL_MAX_EDGE_PX"
    EVIDENCE_FULL_MAX_EDGE_PX = "EVIDENCE_FULL_MAX_EDGE_PX"
    # --- Faza 10.2 — İNFRASTRUKTUR ƏMƏLİYYAT PARAMETRLƏRİ ------------------- #
    #
    # AŞAĞIDAKILARIN HAMISI `src/infrastructure/` qatındakı əməliyyat
    # sabitləridir (taymaut, təkrar cəhd, hədd, dövr aralığı). Onlar CLAUDE.md
    # §5-in "struktur təhlükəsizlik zəmanəti" siyahısına DAXİL DEYİL — heç biri
    # anti-fraud, hardlock və ya guard qaydası deyil; hamısı müəssisənin
    # şəbəkəsindən, disk sürətindən və 1C serverinin yükündən asılı olan
    # ƏMƏLİYYAT dəyərləridir. Ona görə yerləri `system_limits`-dədir.
    #
    # KÖÇÜRMƏ DAVRANIŞI DƏYİŞMİR: hər defolt aşağıda mövcud hardcode dəyərlə
    # HƏRFƏN eynidir. Modul sabitləri `FALLBACK_*` adı ilə YERİNDƏ QALIR və
    # yalnız `system_limits` sətri oxunmadıqda (bağlantı yoxdur, sətir hələ
    # seed edilməyib) işə düşür — seed: migrations/032.
    #
    # SƏRT ARALIQ MƏCBURİDİR: bu dəyərlərin bir qismi (DB hovuzu, taymautlar)
    # səhv yazılsa tətbiq işləməz vəziyyətə düşərdi. Ona görə migrations/032
    # hər açara `min_value`/`max_value` yazır və oxuyan kod dəyəri həmin
    # aralığa KLAMP edir (bax `infrastructure/config/limits.py`).
    #
    # Admin-tier şifrənin minimum uzunluğu. PIN tərəfi ARTIQ
    # `PIN_MAX_FAILED_ATTEMPTS`/`PIN_LOCKOUT_MINUTES` ilə idarə olunurdu —
    # şifrə tərəfi isə qalmışdı.
    # `noqa: S105` — bu, ŞİFRƏNİN ÖZÜ deyil, onun uzunluq siyasətinin
    # `system_limits` açarıdır; linter adda "PASSWORD" görüb sirr güman edir.
    PASSWORD_MIN_LENGTH = "PASSWORD_MIN_LENGTH"  # noqa: S105
    # Gecəlik ehtiyat nüsxə: saxlama müddətinin DÖŞƏMƏSİ, faktiki müddət və
    # `pg_dump` taymautu. Döşəmə də parametrdir, çünki müəssisənin daxili
    # saxlama siyasəti spesifikasiyanın 30 günündən UZUN ola bilər; aşağı
    # hüdud (30) miqrasiyada kilidlənib, yəni Root onu 30-dan aşağı SALA
    # BİLMƏZ — spesifikasiya tələbi qorunur.
    BACKUP_MIN_RETENTION_DAYS = "BACKUP_MIN_RETENTION_DAYS"
    BACKUP_RETENTION_DAYS = "BACKUP_RETENTION_DAYS"
    BACKUP_DUMP_TIMEOUT_SECONDS = "BACKUP_DUMP_TIMEOUT_SECONDS"
    # System Health Monitor hədləri. Disk faizi quraşdırmadan-quraşdırmaya
    # fərqlənir (128 GB SSD-li kiosk ilə 2 TB serverdə "85% doludur" tamam
    # fərqli qalıq yer deməkdir), DB ping həddi isə şəbəkə məsafəsindən asılıdır.
    HEALTH_DISK_WARNING_PERCENT = "HEALTH_DISK_WARNING_PERCENT"
    HEALTH_DISK_CRITICAL_PERCENT = "HEALTH_DISK_CRITICAL_PERCENT"
    HEALTH_DB_PING_SLOW_MS = "HEALTH_DB_PING_SLOW_MS"
    # Yaddaş (RAM) hədləri — `v2backlog.md` Faza 5.2. Disk ilə EYNİ səbəbdən
    # Root parametridir: 4 GB RAM-lı kiosk ilə 32 GB-lıq mağaza serverində
    # "85% doludur" tamam fərqli qalıq deməkdir. Disk hədləri ilə EYNİ
    # defoltlar seçilib — ikisi də "faktiki tükənmədən xeyli əvvəl xəbər ver"
    # məntiqindədir və fərqli ədəd seçmək üçün ölçülmüş səbəb yoxdur.
    HEALTH_MEMORY_WARNING_PERCENT = "HEALTH_MEMORY_WARNING_PERCENT"
    HEALTH_MEMORY_CRITICAL_PERCENT = "HEALTH_MEMORY_CRITICAL_PERCENT"
    # Aparat-nasazlığı bildirişinin təkrar-susma pəncərəsi (Faza 5.2):
    # `DRIVE_QUOTA_WARNING_COOLDOWN_DAYS` ilə eyni naxış, lakin SAAT vahidli —
    # dolu disk gün ərzində həll olunmalı nasazlıqdır, kvota isə həftələrlə
    # dözə bilər.
    HEALTH_HARDWARE_ALERT_COOLDOWN_HOURS = "HEALTH_HARDWARE_ALERT_COOLDOWN_HOURS"
    # Google Drive kvota xəbərdarlığı: hansı doluluqda və nə qədər seyrək.
    DRIVE_QUOTA_WARNING_RATIO = "DRIVE_QUOTA_WARNING_RATIO"
    DRIVE_QUOTA_WARNING_COOLDOWN_DAYS = "DRIVE_QUOTA_WARNING_COOLDOWN_DAYS"
    # NTP ölçmə rejimi. `NTP_MAX_DRIFT_SECONDS` ARTIQ MÖVCUDDUR (yuxarıda) —
    # burada təkrarlanmır; yalnız ölçmənin TEZLİYİ, taymautu, nümunənin
    # köhnəlmə müddəti və qəbul edilən maksimum gediş-dönüş vaxtı əlavə olunur.
    NTP_POLL_INTERVAL_SECONDS = "NTP_POLL_INTERVAL_SECONDS"
    NTP_QUERY_TIMEOUT_SECONDS = "NTP_QUERY_TIMEOUT_SECONDS"
    NTP_SAMPLE_TTL_SECONDS = "NTP_SAMPLE_TTL_SECONDS"
    NTP_MAX_ROUND_TRIP_SECONDS = "NTP_MAX_ROUND_TRIP_SECONDS"
    # Server-lövbərli vaxt (TIME-1). NTP açarlarından AYRIDIR və onları ƏVƏZ
    # ETMİR: NTP lokal saatın yanlışlığını ÖLÇÜR, Postgres isə qeydin vaxtını
    # YAZIR. İkisi fərqli tezliklərdə işləyə bilər — NTP şəbəkədən asılıdır,
    # baza sorğusu isə onsuz da açıq bağlantı üzərindən gedir və ucuzdur.
    SERVER_TIME_SYNC_INTERVAL_SECONDS = "SERVER_TIME_SYNC_INTERVAL_SECONDS"
    # Bu müddətdən uzun server-siz qalmış quraşdırmanın qeydləri «vaxt-dəqiqliyi
    # şübhəli» kimi işarələnir. BLOKLAMA DEYİL — bax `time_integrity.py`.
    SERVER_TIME_MAX_OFFLINE_TRUST_SECONDS = "SERVER_TIME_MAX_OFFLINE_TRUST_SECONDS"
    # Windows saatının server vaxtından icazə verilən maksimum fərqi. Aşılarsa
    # audit yazısı + HR_Admin bildirişi (fırıldaqçılıq siqnalı), əməliyyat isə
    # BLOKLANMIR — vaxt onsuz da serverdən gəlir.
    LOCAL_CLOCK_MANIPULATION_THRESHOLD_SECONDS = "LOCAL_CLOCK_MANIPULATION_THRESHOLD_SECONDS"
    # Həmin bildirişin açıq/qapalı olması (1/0).
    #
    # NİYƏ `FeatureModule` DEYİL: modul toggle-ı BİZNES modulunu söndürür və
    # retroaktiv təsir etmir (`CLAUDE.md` §5) — burada isə söndürülən şey bir
    # BİLDİRİŞ KANALIDIR, modul deyil. Ayrıca, aşkarlamanın özü (audit yazısı)
    # bu açardan ASILI DEYİL və söndürülə bilməz: susdurula bilən şey yalnız
    # xəbərdarlığın çatdırılmasıdır, faktın qeydə alınması yox.
    LOCAL_CLOCK_MANIPULATION_NOTIFY = "LOCAL_CLOCK_MANIPULATION_NOTIFY"
    # Cihaz qeydiyyatı (DEVICE-1). `INFRA_LIMIT_BOUNDS`-a YAZILMIR: onlar
    # `src/infrastructure/` modul sabitləridir, bunlar isə use case-in biznes
    # qərarlarıdır (lisenziya həddi, təsdiq siyasəti) və `SystemLimits` portu
    # ilə oxunur — `MONTHLY_LEAVE_MINUTES_LIMIT` ilə eyni kateqoriya.
    MAX_REGISTERED_DEVICES = "MAX_REGISTERED_DEVICES"
    # Təsdiq məcburiliyi (1/0). Root söndürsə yeni cihaz DƏRHAL aktiv olur —
    # kiçik müştəri üçün nəzərdə tutulub. Söndürmə RETROAKTİV DEYİL: artıq
    # gözləyən cihazlar avtomatik təsdiqlənmir, çünki onların hansı filiala
    # aid olduğunu sistem BİLMİR (filialı yalnız adam təyin edə bilər).
    DEVICE_APPROVAL_REQUIRED = "DEVICE_APPROVAL_REQUIRED"
    DEVICE_INACTIVITY_DAYS = "DEVICE_INACTIVITY_DAYS"
    # 1C: ad uyğunlaşmasının qərarsızlıq marjası, sinxronizasiya paralelliyi,
    # dövr başına səhifə tavanı, HTTP taymautu və təkrar cəhd sayı.
    ERP_MATCH_AMBIGUITY_MARGIN = "ERP_MATCH_AMBIGUITY_MARGIN"
    ERP_SYNC_MAX_PARALLEL_SERVERS = "ERP_SYNC_MAX_PARALLEL_SERVERS"
    ERP_SYNC_MAX_PAGES_PER_RUN = "ERP_SYNC_MAX_PAGES_PER_RUN"
    ERP_REQUEST_TIMEOUT_SECONDS = "ERP_REQUEST_TIMEOUT_SECONDS"
    ERP_MAX_RETRIES = "ERP_MAX_RETRIES"
    # Fayl-mübadiləsi tipli 1C serverinin DEFOLT sinxronizasiya dövrü.
    #
    # NİYƏ AYRICA AÇAR — HTTP/COM üçün belə açar YOXDUR: onların dövrü
    # `erp_servers.sync_interval_seconds` sütunundadır və sxem defolt 300
    # saniyə verir. Fayl mübadiləsi isə real-vaxt DEYİL (1c.md: "hər gecə bir
    # dəfə sinxronlaşır") — 300 saniyəlik dövr həm mənasız fayl oxumaları
    # yaradar, həm də sağlamlıq görünüşünü yanıldar: `v_erp_server_health`
    # STALE həddini `interval * 3` kimi hesablayır, yəni gecəlik ixracı olan
    # server 15 dəqiqədən sonra "köhnəlmiş" görünərdi.
    #
    # Dəyər KİRAYƏÇİYƏ görə dəyişir (kimsə gündə iki dəfə ixrac edir), ona
    # görə yeri `system_limits`-dir, koddakı sabit deyil.
    ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS = "ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS"
    # Kiosk nəzarətçisi: yenidən-başlatma fırtınasının pəncərəsi, tavanı və
    # artan gözləmə cədvəli.
    KIOSK_RESTART_WINDOW_MINUTES = "KIOSK_RESTART_WINDOW_MINUTES"
    KIOSK_MAX_RESTARTS_PER_WINDOW = "KIOSK_MAX_RESTARTS_PER_WINDOW"
    KIOSK_RESTART_BACKOFF_SECONDS = "KIOSK_RESTART_BACKOFF_SECONDS"
    # Developer Paneli: quraşdırmanın "səssiz" sayılma həddi.
    DEVELOPER_DIRECTORY_STALE_DAYS = "DEVELOPER_DIRECTORY_STALE_DAYS"
    # Bildiriş növbəsi: dövr başına paket ölçüsü, cəhd tavanı, cəhdlərarası
    # artan gözləmə cədvəli və dövr aralığı.
    NOTIFY_MAX_BATCH_SIZE = "NOTIFY_MAX_BATCH_SIZE"
    NOTIFY_MAX_ATTEMPTS = "NOTIFY_MAX_ATTEMPTS"
    NOTIFY_RETRY_BACKOFF_MINUTES = "NOTIFY_RETRY_BACKOFF_MINUTES"
    NOTIFY_POLL_INTERVAL_SECONDS = "NOTIFY_POLL_INTERVAL_SECONDS"
    # SMTP soket taymautu (portlar 587/465 STANDARTDIR — onlar köçürülmür).
    EMAIL_SMTP_TIMEOUT_SECONDS = "EMAIL_SMTP_TIMEOUT_SECONDS"
    # Eyni çökmə barmaq izi üçün bir sessiyada göndərilən hesabat tavanı.
    CRASH_MAX_REPORTS_PER_FINGERPRINT = "CRASH_MAX_REPORTS_PER_FINGERPRINT"
    # Realtime kanalı: polling aralığı və yenidən-qoşulma gözləmə cədvəli.
    REALTIME_POLL_INTERVAL_SECONDS = "REALTIME_POLL_INTERVAL_SECONDS"
    REALTIME_RECONNECT_BACKOFF_SECONDS = "REALTIME_RECONNECT_BACKOFF_SECONDS"
    # Offline bufer: sinxronizasiya paketi, təkrar cəhd cədvəli və SQLite
    # kilid gözləmə taymautu.
    OFFLINE_SYNC_BATCH_SIZE = "OFFLINE_SYNC_BATCH_SIZE"
    OFFLINE_RETRY_BACKOFF_SECONDS = "OFFLINE_RETRY_BACKOFF_SECONDS"
    OFFLINE_SQLITE_TIMEOUT_SECONDS = "OFFLINE_SQLITE_TIMEOUT_SECONDS"
    # Uzatılmış offline rejim (`v2backlog.md` Faza 5.1). Yuxarıdakı ÜÇ açar
    # buferin NECƏ işlədiyini deyir (paket, təkrar cəhd, kilid) — bu ÜÇÜ isə
    # "nə vaxt artıq NORMAL deyil" sualına cavab verir və HR-ə xəbərdarlıq
    # göndərir. İKİ ayrı hədd QƏSDƏNDİR: bir kassa səhəri boyu şəbəkəsiz işlə-
    # yən mağaza AZ sətirlə UZUN müddət (yaş həddi), bir günlük inventarizasiya
    # isə QISA müddətdə ÇOX sətir (say həddi) yığır — biri digərini görmür.
    OFFLINE_BACKLOG_MAX_HOURS = "OFFLINE_BACKLOG_MAX_HOURS"
    OFFLINE_BACKLOG_MAX_ENTRIES = "OFFLINE_BACKLOG_MAX_ENTRIES"
    OFFLINE_BACKLOG_WARNING_COOLDOWN_HOURS = "OFFLINE_BACKLOG_WARNING_COOLDOWN_HOURS"
    # PostgreSQL bağlantı hovuzu. ƏN HƏSSAS ÜÇLÜKDÜR: hovuz ölçüsü 0 olsa
    # tətbiq heç bir sorğu edə bilməz. Miqrasiyadakı aralıq (1–32 / 1–64 /
    # 1–300 san) və koddakı klamp məhz buna görə SƏRTDİR.
    DB_POOL_MIN_SIZE = "DB_POOL_MIN_SIZE"
    DB_POOL_MAX_SIZE = "DB_POOL_MAX_SIZE"
    DB_CONNECT_TIMEOUT_SECONDS = "DB_CONNECT_TIMEOUT_SECONDS"
    # Google Drive API: tokenin vaxtından əvvəl yenilənmə marjası, HTTP
    # taymautu, təkrar cəhd sayı, OAuth razılıq axınının ömrü, sübut şəklinin
    # JPEG keyfiyyəti və növbədə "claim" edilmiş elementin köhnəlmə müddəti.
    # `noqa: S105` — açar ADIDIR, token DEYİL (linter "TOKEN" sözünə reaksiya
    # verir; eyni istisna `storage/drive_api.TOKEN_ENDPOINT`-də də var).
    DRIVE_TOKEN_REFRESH_MARGIN_SECONDS = "DRIVE_TOKEN_REFRESH_MARGIN_SECONDS"  # noqa: S105
    DRIVE_REQUEST_TIMEOUT_SECONDS = "DRIVE_REQUEST_TIMEOUT_SECONDS"
    DRIVE_MAX_RETRIES = "DRIVE_MAX_RETRIES"
    DRIVE_OAUTH_FLOW_TIMEOUT_SECONDS = "DRIVE_OAUTH_FLOW_TIMEOUT_SECONDS"
    EVIDENCE_JPEG_QUALITY = "EVIDENCE_JPEG_QUALITY"
    UPLOAD_CLAIM_STALE_AFTER_SECONDS = "UPLOAD_CLAIM_STALE_AFTER_SECONDS"
    # Şəkil keşi: ömür və disk tavanı.
    IMAGE_CACHE_TTL_SECONDS = "IMAGE_CACHE_TTL_SECONDS"
    IMAGE_CACHE_MAX_BYTES = "IMAGE_CACHE_MAX_BYTES"
    # Plugin sandbox-u: icra taymautu və çıxış tavanı. BUNLAR ETİBAR
    # SİYASƏTİ DEYİL — imza/nəşriyyatçı yoxlaması (fail-closed) toxunulmaz
    # qalır; burada yalnız "nə qədər gözləyək, nə qədər oxuyaq" var.
    PLUGIN_SANDBOX_TIMEOUT_SECONDS = "PLUGIN_SANDBOX_TIMEOUT_SECONDS"
    PLUGIN_SANDBOX_MAX_OUTPUT_BYTES = "PLUGIN_SANDBOX_MAX_OUTPUT_BYTES"
    # Auto-update: imza yoxlaması, yayım yükləməsi və endirmə taymautları,
    # imzalı linkin ömrü, kataloq sorğusunun sətir tavanı.
    UPDATE_VERIFY_TIMEOUT_SECONDS = "UPDATE_VERIFY_TIMEOUT_SECONDS"
    UPDATE_UPLOAD_TIMEOUT_SECONDS = "UPDATE_UPLOAD_TIMEOUT_SECONDS"
    UPDATE_DOWNLOAD_TIMEOUT_SECONDS = "UPDATE_DOWNLOAD_TIMEOUT_SECONDS"
    UPDATE_SIGNED_URL_TTL_SECONDS = "UPDATE_SIGNED_URL_TTL_SECONDS"
    UPDATE_CATALOG_FETCH_LIMIT = "UPDATE_CATALOG_FETCH_LIMIT"
    # --- Faza 10.2 — TƏTBİQ QATININ (application) PARAMETRLƏRİ -------------- #
    #
    # AŞAĞIDAKI 15 AÇAR `src/application/use_cases/` altında SABİT ƏDƏD kimi
    # yaşayırdı: SLA hədəfləri, səhifə ölçüləri, xatırlatma cədvəli, növbə
    # dəyişmə pəncərəsi və quraşdırma tövsiyəsi. Heç biri CLAUDE.md §5-in
    # struktur zəmanətlərinə aid deyil (anti-fraud vəzifə ayrılığı, SEC-001,
    # Strict Hierarchy / Self-Escalation Guard, dörd-səviyyəli `HardlockLevel`
    # toxunulmaz qalır) — hamısı xidmət səviyyəsi, ekran həcmi və ya kommersiya
    # ritmi ilə bağlı ƏMƏLİYYAT dəyəridir.
    #
    # DAVRANIŞ DƏYİŞMİR: hər defolt köçürmədən ƏVVƏLKİ hardcode ilə HƏRFƏN
    # eynidir. Modul sabitləri YERİNDƏ QALIR, lakin artıq ədəd SAXLAMIR —
    # dəyəri `DEFAULT_LIMITS`-dən götürür və yalnız `system_limits` sətri
    # əlçatmaz olduqda işə düşən FALLBACK-dır (seed: migrations/034).
    #
    # Dəstək müraciətinin İKİ AYRI SLA sayğacı (bax `developer_console` başlığı:
    # "saatlarla susub sonra bir dəqiqəyə bağlanan müraciət yaxşı xidmət kimi
    # görünərdi"). Hər ikisi kommersiya öhdəliyidir — müqavilə dəyişəndə kod
    # buraxılışı gözlənilməməlidir.
    SUPPORT_FIRST_RESPONSE_SLA_HOURS = "SUPPORT_FIRST_RESPONSE_SLA_HOURS"
    SUPPORT_RESOLUTION_SLA_HOURS = "SUPPORT_RESOLUTION_SLA_HOURS"
    # Hədəfin son neçə hissəsi "risk altında" zolağıdır (0.75 = son 25%).
    # AYRI AÇARDIR, çünki zolağın eni SLA-nın ÖZÜNDƏN müstəqil qərardır:
    # 24 saatlıq hədəfdə 6 saatlıq xəbərdarlıq kifayətdir, 72 saatlıqda isə
    # eyni nisbət 18 saat verir və komanda daha erkən siqnal istəyə bilər.
    SUPPORT_SLA_AT_RISK_RATIO = "SUPPORT_SLA_AT_RISK_RATIO"
    # Çökmə neçə FƏRQLİ quraşdırmada təkrarlananda "kütləvi" sayılsın. Aşağı
    # hüdud 2-dir: 1 yazılsaydı HƏR çökmə kütləvi görünərdi və nişan öz
    # prioritetləşdirmə dəyərini itirərdi (bax `CrashGroup.is_widespread`).
    CRASH_WIDESPREAD_INSTALLATION_THRESHOLD = "CRASH_WIDESPREAD_INSTALLATION_THRESHOLD"
    # Çökmə panelinin "ən çox təkrarlanan N qrup" siyahısının uzunluğu.
    CRASH_DASHBOARD_TOP_LIMIT = "CRASH_DASHBOARD_TOP_LIMIT"
    # Növbə DƏYİŞMƏ sorğusu neçə gün irəli üçün göndərilə bilər. Açıq növbə
    # bazarının `OPEN_SHIFT_MAX_LEAD_DAYS` açarından QƏSDƏN AYRIDIR — səbəb
    # həmin açarın şərhindədir (orada işçi ÖZ gününü dəyişir, burada hələ heç
    # kimə aid olmayan slot elan olunur).
    SHIFT_SWAP_MAX_LEAD_DAYS = "SHIFT_SWAP_MAX_LEAD_DAYS"
    # Lisenziya ödənişi xatırlatma cədvəli: MƏNFİ = bitmədən əvvəl, MÜSBƏT =
    # sonra. Vergüllü siyahı naxışı `EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS` ilə
    # eynidir: beş mərhələ BİRGƏ bir cədvəl təşkil edir və ayrı açarlarda Root
    # onları yanlış sıraya yaza bilərdi. `min_value`/`max_value` mənasızdır
    # (mənfi element var), ona görə `TEXT` tipindədir.
    LICENSE_PAYMENT_REMINDER_OFFSET_DAYS = "LICENSE_PAYMENT_REMINDER_OFFSET_DAYS"
    # Ekran səhifə ölçüləri. HAMISININ AŞAĞI HÜDUDU 1-dir: 0 yazılsa siyahı
    # HƏMİŞƏ boş qayıdardı və istifadəçi "məlumat yoxdur" ilə "limit sıfırdır"
    # arasındakı fərqi heç bir ekranda görə bilməzdi.
    SALES_REVIEW_QUEUE_PAGE_SIZE = "SALES_REVIEW_QUEUE_PAGE_SIZE"
    AUDIT_LOG_MAX_PAGE_SIZE = "AUDIT_LOG_MAX_PAGE_SIZE"
    AUDIT_LOG_DEFAULT_PAGE_SIZE = "AUDIT_LOG_DEFAULT_PAGE_SIZE"
    BACKUP_HISTORY_PAGE_SIZE = "BACKUP_HISTORY_PAGE_SIZE"
    ANNOUNCEMENT_LIST_PAGE_SIZE = "ANNOUNCEMENT_LIST_PAGE_SIZE"
    SUPPORT_THREAD_PAGE_SIZE = "SUPPORT_THREAD_PAGE_SIZE"
    #: Telegram bildiriş rejimi — `TelegramNotifyMode` dəyərlərindən biri.
    #:
    #: SƏHİFƏ ÖLÇÜSÜ DEYİL, DAVRANIŞ AÇARIDIR: bu siyahıdakı yeganə mətn
    #: dəyərlərindən biridir və qəsdən buradadır — Root onu digər limitlərlə
    #: EYNİ ekranda görməlidir. Ayrıca «Telegram parametrləri» sahəsinə
    #: qoysaydıq, bot konfiqurasiyası (token/chat) ilə bildiriş SİYASƏTİ
    #: qarışardı: birincisi bağlantıdır, ikincisi seçimdir.
    TELEGRAM_NOTIFY_MODE = "TELEGRAM_NOTIFY_MODE"
    TELEGRAM_REQUEST_TIMEOUT_SECONDS = "TELEGRAM_REQUEST_TIMEOUT_SECONDS"
    TELEGRAM_POLL_INTERVAL_SECONDS = "TELEGRAM_POLL_INTERVAL_SECONDS"
    #: Status avtomatikası (tg1.md Faza 6) — ikisi də GÜN ölçüsündədir.
    SUPPORT_AUTO_CLOSE_DAYS = "SUPPORT_AUTO_CLOSE_DAYS"
    SUPPORT_WAITING_REMINDER_DAYS = "SUPPORT_WAITING_REMINDER_DAYS"
    SYNC_CONFLICT_PAGE_SIZE = "SYNC_CONFLICT_PAGE_SIZE"
    # DB-2 hardcode auditinin tapdığı İKİ sabit (`workflow_repositories.py`).
    #
    # Onlar digər səhifə ölçülərindən FƏRQLİ formada gizlənmişdi: dəyər
    # repozitoriya metodunun DEFOLT ARQUMENTİ idi (`limit: int = 50`) və
    # çağıran tərəf onu ötürmürdü. Yəni ekranda "səhifə ölçüsü" adlı bir
    # parametr görünmürdü, faktiki hədd isə vardı — işçi 50-dən çox sorğusu
    # olduqda tarixçəsinin qalanını HEÇ BİR yolla görə bilmirdi və bunun
    # limitdən qaynaqlandığını da bilmirdi.
    SHIFT_SWAP_HISTORY_PAGE_SIZE = "SHIFT_SWAP_HISTORY_PAGE_SIZE"
    FINE_APPEAL_HISTORY_PAGE_SIZE = "FINE_APPEAL_HISTORY_PAGE_SIZE"
    # İlk quraşdırma sihirbazının "ən azı bu qədər admin olsun" TÖVSİYƏSİ.
    # BLOKLAMIR — yalnız xəbərdarlıq göstərir (bax `first_run_setup`), ona görə
    # struktur zəmanət deyil və yeri `system_limits`-dədir.
    SETUP_RECOMMENDED_ADMIN_COUNT = "SETUP_RECOMMENDED_ADMIN_COUNT"
    # --- Faza 10.2 — TƏQDİMAT QATININ (presentation) PARAMETRLƏRİ ----------- #
    #
    # AŞAĞIDAKI BEŞ AÇAR `src/presentation/` və `src/developer_panel/` altında
    # SABİT ƏDƏD idi: ekranın göstərdiyi pəncərə, fon dövrəsinin ritmi, "zəif
    # uyğunluq" rəng həddi və panel cədvəllərinin sətir tavanı. Heç biri
    # CLAUDE.md §5-in struktur zəmanətlərinə aid deyil — hamısı GÖRÜNÜŞ və
    # ƏMƏLİYYAT dəyəridir, yəni yeri `system_limits`-dədir.
    #
    # DAVRANIŞ DƏYİŞMİR: hər defolt köçürmədən ƏVVƏLKİ hardcode ilə eynidir;
    # modul sabitləri `FALLBACK_*` adı ilə yerində qalır və dəyərini məhz
    # `DEFAULT_LIMITS`-dən götürür (seed: migrations/035).
    #
    # Növbə matrisinin və işçi təqviminin göstərdiyi gün sayı. 21 filialın
    # planlaması eyni ritmdə getmir: bəzi müəssisə həftəlik (7), bəzisi aylıq
    # (30) planlayır və ekranın pəncərəsi həmin ritmə uyğunlaşmalıdır.
    SHIFT_MATRIX_WINDOW_DAYS = "SHIFT_MATRIX_WINDOW_DAYS"
    # Sübut şəkli növbəsinin FON dövrəsi. Hədd DEYİL, ritmdir: cərimə yaradılan
    # anda növbə onsuz da bir dəfə boşaldılır (`FineEntryController._issue`) —
    # bu dövrə yalnız şəbəkə qayıdanda qalanları götürür. Zəif internetli
    # filialda daha seyrək, ofisdə daha sıx ritm seçilə bilər.
    EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS = "EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS"
    # SAAS-6 — YÜKLƏNMİŞ sübut sətri və HƏLL EDİLMİŞ sinxronizasiya münaqişəsi
    # lokal SQLite-da nə qədər saxlanılır. Hədd DEYİL, SAXLAMA MÜDDƏTİDİR:
    # heç bir əməliyyat bloklanmır, yalnız artıq öz işini görmüş sətir təmizlənir.
    #
    # NİYƏ HƏR İKİ CƏDVƏL ÜÇÜN TƏK AÇAR: ikisi də EYNİ sualın cavabıdır —
    # «bu terminaldakı diaqnostika izi nə qədər lazımdır?». Ayrı açarlar
    # olsaydı, Root birini dəyişib digərini unudar və eyni diskdə iki fərqli
    # ritmlə böyüyən iki cədvəl qalardı.
    EVIDENCE_UPLOAD_RETENTION_DAYS = "EVIDENCE_UPLOAD_RETENTION_DAYS"
    # UX-7 — işə götürüldükdən sonra üz qeydiyyatı üçün verilən möhlət (gün).
    # BLOKLAMA HƏDDİ DEYİL, GÖRÜNMƏ həddidir: möhlət bitəndə işçiyə heç nə
    # olmur, sətir menecerin «İstisnalar» siyahısına düşür (bax
    # `OverdueFaceEnrollmentRule` — niyə bloklama seçilmədiyi orada yazılıb).
    FACE_ENROLLMENT_GRACE_DAYS = "FACE_ENROLLMENT_GRACE_DAYS"
    # «Şübhəli Satışlar» ekranında uyğunluq faizinin XƏBƏRDARLIQ rənginə
    # keçdiyi hədd. `ERP_NAME_MATCH_THRESHOLD` (qəbul həddi) ilə QARIŞDIRILMIR:
    # o, satışın işçiyə BAĞLANIB-bağlanmamasını həll edir, bu isə operatorun
    # gözünə hansı sətrin şübhəli göründüyünü deyir — biri qərar, digəri rəng.
    ERP_MATCH_LOW_CONFIDENCE_PERCENT = "ERP_MATCH_LOW_CONFIDENCE_PERCENT"
    # Developer Panelindəki iki diaqnostika cədvəlinin sətir tavanı. Kəsilmə
    # SƏSSİZ deyil — status sətri "neçəsindən neçəsi göstərilir" sualını
    # cavablandırır. Tətbiq qatındakı `CrashDashboard.top()` defoltundan
    # AYRIDIR: ora "təhlil üçün ən çox təkrarlanan N qrup" deməkdir, bura isə
    # "panel pəncərəsinə neçə sətir sığır" — biri analiz, digəri düzülüş.
    DEVELOPER_CRASH_ROW_LIMIT = "DEVELOPER_CRASH_ROW_LIMIT"
    DEVELOPER_TICKET_ROW_LIMIT = "DEVELOPER_TICKET_ROW_LIMIT"
    # --- Faza 11 — PLANLANMIŞ İŞ PLANLAYICISI (seed: migrations/036) --------- #
    #
    # DÖRDÜ DƏ ƏMƏLİYYAT PARAMETRİDİR, struktur zəmanət DEYİL (CLAUDE.md §5):
    # nə anti-fraud, nə hardlock, nə guard qaydası. Hamısı quraşdırmanın
    # RİTMİNƏ aiddir və 21 filialda eyni ola bilməz — gecə bağlanan mağazada
    # ağır iş 03:00-da, 24 saat işləyəndə isə səhərə yaxın planlaşdırıla bilər.
    #
    # Planlayıcı dövrəsinin YOXLAMA aralığı. Bu, işin nə vaxt işlədiyini
    # DEYİL, "vaxtı çatıbmı?" sualının nə tezliklə verildiyini təyin edir:
    # kiçik dəyər gecikmiş işi tez tutur, böyük dəyər bataryaya/şəbəkəyə
    # qənaət edir.
    SCHEDULER_POLL_INTERVAL_MINUTES = "SCHEDULER_POLL_INTERVAL_MINUTES"
    # Gecə işlərinin MAĞAZA YERLİ saatı (0–23). Dəqiqə YOXDUR və bu qəsdəndir:
    # slot sərhədi hər gün eyni yerdə olmalıdır ki, `scheduled_for` unikal
    # açarı sabit qalsın; "03:17" kimi dəyər heç bir əməliyyat faydası
    # vermir, lakin yay/qış və miqrasiya hesablarını çətinləşdirərdi.
    SCHEDULER_NIGHTLY_HOUR = "SCHEDULER_NIGHTLY_HOUR"
    # İcarənin ömrü (dəqiqə). SEÇİM QAYDASI: ƏN UZUN işin gözlənilən icra
    # müddətindən BÖYÜK olmalıdır. Kiçik olsa, hələ işləyən instansiyanın
    # icarəsi bitər və ikinci terminal EYNİ işi paralel başladar — yəni
    # parametr yanlış seçiləndə qoruma özü yarış yaradır. Ona görə
    # migrations/036 alt hüdudu 5 dəqiqədə saxlayır və `COMMENT` bu riski
    # açıq yazır.
    SCHEDULER_LEASE_MINUTES = "SCHEDULER_LEASE_MINUTES"
    # Uğursuz (və ya icraçısı çökmüş) işin ümumi cəhd tavanı. Tavan
    # MƏCBURİDİR: tətbiqi öldürən iş hər dəfə `RUNNING` qalıb icarəsi bitəcək
    # və tavansız planlayıcı terminalı sonsuz yenidən-başlatma döngəsinə
    # salardı (bax `ScheduledJobRun.is_reclaimable`).
    SCHEDULER_MAX_ATTEMPTS = "SCHEDULER_MAX_ATTEMPTS"
    # --- #26+#27 SAHƏ HESABATLARI (seed: migrations/039) --------------------- #
    #
    # DÖRDÜ DƏ ƏMƏLİYYAT PARAMETRİDİR, struktur zəmanət DEYİL (CLAUDE.md §5):
    # nə anti-fraud, nə hardlock, nə vəzifə ayrılığı. Hər biri şəbəkənin öz
    # iş ritmindən asılıdır — 21 filialı olan kirayəçi ilə tək mağazalı
    # kirayəçinin audit tezliyi eyni ola bilməz.
    #
    # Mağazanın NEÇƏ GÜNDƏN BİR auditə çəkilməli olduğu. Bu ədəd auditi
    # BLOKLAMIR (gec qalmış mağazada iş dayanmır) — yalnız `FIELD_REPORT_
    # AUDIT_REMINDER` gecəlik işinin "hansı filial gözdən qaçıb?" sualına
    # cavabıdır. Bloklayıcı olsaydı, bayram/inventar dövründə normal iş
    # dayanardı; xatırlatma isə heç nəyi dayandırmır, yalnız görünən edir.
    FIELD_REPORT_AUDIT_INTERVAL_DAYS = "FIELD_REPORT_AUDIT_INTERVAL_DAYS"
    # Bir hesabata əlavə edilə bilən maksimum foto sayı. `photo_refs` `TEXT[]`
    # massivdir və hər element Drive-da BİR fayl deməkdir — tavansız massiv
    # səhvən dövrəyə düşmüş yükləmə ilə kvotanı tək hesabatla yandırardı.
    FIELD_REPORT_MAX_PHOTOS = "FIELD_REPORT_MAX_PHOTOS"
    # Hesabatın təsvirinin (və bağlanma qeydinin) minimum uzunluğu.
    # `migrations/037`-dəki `CHECK (... >= 5)` bu dəyəri ƏVƏZ ETMİR: o,
    # ABSURD sətri kəsən döşəmədir (miqrasiya başlığı bunu açıq yazır),
    # siyasət isə buradadır. İKİ SAHƏ ÜÇÜN TƏK AÇAR qəsdəndir: hər ikisi
    # "nə baş verdi / nə edildi" sualını cavablandırır və Root panelində iki
    # ayrı ədəd saxlamaq eyni qərarı iki yerdə soruşmaq olardı.
    FIELD_REPORT_MIN_DETAIL_LENGTH = "FIELD_REPORT_MIN_DETAIL_LENGTH"
    # Uğursuz BLOKLAYICI bənddən doğan düzəliş tapşırığının son tarixi (gün).
    # Tapşırıq mövcud Tapşırıq Mühərrikində yaranır (Struktur Qərar B) və
    # `Task.deadline` MƏCBURİDİR — yəni bu ədəd olmadan avtomatik tapşırıq
    # ÜMUMİYYƏTLƏ yaradıla bilməz. Sinifdə sabit kimi yazılsaydı, "vitrin
    # düzümü" ilə "yanğın çıxışının bağlı olması" eyni möhləti alardı.
    FIELD_REPORT_TASK_DEADLINE_DAYS = "FIELD_REPORT_TASK_DEADLINE_DAYS"
    # Düzəliş tapşırığının hansı ROLA təyin edildiyi (`positions.code`).
    # `migrations/038` başlığı qaydanı yazır: "uğursuz bloklayıcı bənd mağaza
    # rəhbərinə qarşı tapşırıq yaradır". Rol adı KODDA sabit olsaydı, öz
    # struktura (məs. "Filial Direktoru", "Rayon Meneceri") uyğunlaşdırmaq
    # buraxılış tələb edərdi — halbuki `positions` kataloqu onsuz da
    # kirayəçi-spesifik rollara açıqdır. Boş dəyər = tapşırıq hesabatı
    # YAZAN şəxsə qalır (tapşırıqsız qalmaq ən pis haldır).
    FIELD_REPORT_TASK_ASSIGNEE_ROLE = "FIELD_REPORT_TASK_ASSIGNEE_ROLE"
    # --- #28 İLLİK MƏZUNİYYƏT BALANSI (seed: migrations/040) ----------------- #
    #
    # ON AÇAR DA ƏMƏLİYYAT PARAMETRİDİR, struktur zəmanət DEYİL (CLAUDE.md §5):
    # heç biri anti-fraud, hardlock və ya vəzifə ayrılığı qaydası deyil. İllik
    # məzuniyyət siyasəti ölkə qanunundan, kollektiv müqavilədən və şirkət
    # praktikasından asılıdır — bir kirayəçinin 21 günü digərinin 28 günüdür.
    #
    # DİQQƏT — BU AÇARLAR GÜNDAXİLİ İCAZƏYƏ AİD DEYİL: `MONTHLY_LEAVE_MINUTES_
    # LIMIT` (240 dəq.) STEP1/STEP2 axınının aylıq DƏQİQƏ tavanıdır və bura
    # heç bir əlaqəsi yoxdur. Üç ayrı mexanizmin izahı üçün bax
    # `domain/entities/annual_leave.py` başlığı.
    #
    # İşçinin bir təqvim ilində qazandığı BAZA haqq (gün). Azərbaycan Əmək
    # Məcəlləsinin minimumu 21 təqvim günüdür — defolt qanunun ÖZÜNÜ
    # təkrarlayır, lakin qanun dəyişəndə (və ya kollektiv müqavilə daha
    # səxavətli olduqda) kod deyil, ROOT sətri dəyişir.
    ANNUAL_LEAVE_BASE_ENTITLEMENT_DAYS = "ANNUAL_LEAVE_BASE_ENTITLEMENT_DAYS"
    # Staj əlavəsinin QAYDA FORMASI üç açarla ifadə olunur — məhz ona görə ki,
    # "hər 5 ildə 1 gün, ən çoxu 5 gün" cümləsinin HƏR ÜÇ ədədi şirkətdən
    # şirkətə dəyişir. Tək açar (məs. "bonus_days") formanı kodda dondurardı.
    # Düstur: `min(maks, floor(staj_ili / dövr) * dövr_başına_gün)`.
    ANNUAL_LEAVE_SENIORITY_PERIOD_YEARS = "ANNUAL_LEAVE_SENIORITY_PERIOD_YEARS"
    ANNUAL_LEAVE_SENIORITY_BONUS_DAYS = "ANNUAL_LEAVE_SENIORITY_BONUS_DAYS"
    ANNUAL_LEAVE_SENIORITY_BONUS_MAX_DAYS = "ANNUAL_LEAVE_SENIORITY_BONUS_MAX_DAYS"
    # Keçən ildən növbəti ilə KÖÇÜRÜLƏ bilən maksimum gün. Tavanı aşan hissə
    # İTİR — mənfi balans YARANMIR (bax `AnnualLeavePolicy.carry_over`).
    ANNUAL_LEAVE_CARRYOVER_MAX_DAYS = "ANNUAL_LEAVE_CARRYOVER_MAX_DAYS"
    # "İSTİFADƏ ET YA İTİR" SON TARİXİ — ay + gün kimi İKİ açar, çünki HR
    # siyasəti həmişə təqvim tarixi kimi ifadə olunur ("31 mart"), gün sayı
    # kimi yox. Ayın uzunluğundan artıq gün nömrəsi (məs. fevralın 31-i)
    # həmin ayın SON gününə sıxılır (bax `AnnualLeavePolicy.carryover_deadline`).
    ANNUAL_LEAVE_CARRYOVER_DEADLINE_MONTH = "ANNUAL_LEAVE_CARRYOVER_DEADLINE_MONTH"
    ANNUAL_LEAVE_CARRYOVER_DEADLINE_DAY = "ANNUAL_LEAVE_CARRYOVER_DEADLINE_DAY"
    # Haqqın QAZANILMA (accrual) dövrü: `ANNUAL` = ilin əvvəlində tam verilir
    # (işə yeni düşəndə işə qəbul tarixinə görə proporsional), `MONTHLY` /
    # `QUARTERLY` = tamamlanmış dövr başına toplanır.
    ANNUAL_LEAVE_ACCRUAL_PERIOD = "ANNUAL_LEAVE_ACCRUAL_PERIOD"
    # Bir accrual dövrünə düşən gün (DƏRƏCƏ). `0` = AVTOMATİK: illik haqq ÷
    # dövr sayı. Sentinel qəsdəndir və sənədləşdirilib: defolt halda dərəcə
    # baza haqqla HƏMİŞƏ uzlaşır (Root 21-i 24-ə qaldıranda dərəcə də özü
    # dəyişir), lakin qeyri-standart cədvəl lazım olarsa açıq dəyər yazılır.
    ANNUAL_LEAVE_ACCRUAL_RATE_DAYS_PER_PERIOD = "ANNUAL_LEAVE_ACCRUAL_RATE_DAYS_PER_PERIOD"
    # Sorğunun neçə gün SAYILDIĞI: `WORKING_DAYS` (defolt) = Shift Matrix-də
    # istirahət günü olmayan günlər, `CALENDAR_DAYS` = aralıqdakı bütün günlər.
    # Defolt seçimin əsaslandırması `migrations/037`-dəki `deducted_days`
    # şərhindədir və `AnnualLeaveUseCase._deducted_days`-də təkrarlanır.
    ANNUAL_LEAVE_DAY_COUNT_MODE = "ANNUAL_LEAVE_DAY_COUNT_MODE"
    # --- #29 TOPLU ƏMƏLİYYATLAR (seed: migrations/041) ------------------------ #
    #
    # İKİSİ DƏ ROOT PARAMETRİDİR, struktur zəmanət DEYİL (CLAUDE.md §5): nə
    # anti-fraud, nə hardlock qaydası — `can_perform_bulk_operations`-un ÖZÜ
    # artıq DELEGABLE hardlock (səviyyə 3) ilə qorunur (migrations/038); bu
    # ikisi YALNIZ əməliyyat həcminin döşəməsidir.
    #
    # MAKSIMUM FAYL ÖLÇÜSÜ ÜÇÜN AYRI AÇAR QƏSDƏN YOXDUR: mövcud
    # `MAX_UPLOAD_SIZE_BYTES` (defolt 5 MB, `google_drive.MAX_UPLOAD_BYTES`
    # fallback-ının güzgüsü) artıq sübut ŞƏKİLLƏRİ üçün Root-dan idarə olunan
    # döşəmədir; CSV mətn faylı üçün fərqli (adətən daha kiçik) hədd lazım
    # DEYİL — 300 sətirlik işçi CSV-si bir neçə on KB-dır, şəkil kvotasından
    # min qat kiçikdir. İkinci açar yaratmaq eyni sualı ("faylım nə qədər ola
    # bilər?") iki fərqli cavabla verər və Root-u çaşdırardı.
    #
    # Sətir tavanı NİYƏ VAR: `bulk_import_log`-da `REVOKE DELETE` var (audit
    # qeydidir) — səhvən 50,000 sətirlik fayl yüklənsə, yarım saat sürən idxanı
    # LƏĞV ETMƏK MÜMKÜN DEYİL, yalnız GÖZLƏMƏK olar. Tavan bu riski YÜKLƏMƏ
    # ANINDA kəsir, idxal başlamazdan ƏVVƏL.
    BULK_IMPORT_MAX_ROWS = "BULK_IMPORT_MAX_ROWS"
    # Önizləmə ekranında göstərilən XƏTA sətri sayının tavanı. 300 sətirlik
    # fayldan 250-si səhv poçt formatı ilə uğursuz olsa, ekranın 250 sətri
    # BİRDƏN göstərməsi faydalı DEYİL — HR "ilk N səhv"i görüb faylın ÜMUMİ
    # nasazlığını (məs. səhv ayırıcı seçilib) anlayır və faylı düzəldib YENİDƏN
    # yükləyir. Aqreqat rəqəm (`error_count`) ISƏ HƏMİŞƏ TAM göstərilir — yalnız
    # SƏTİR-SƏTİR siyahı kəsilir.
    BULK_IMPORT_PREVIEW_ERROR_LIMIT = "BULK_IMPORT_PREVIEW_ERROR_LIMIT"
    # --- #30 Planlaşdırılmış İcra Xülasəsi (seed: migrations/042) ------------- #
    #
    # ÜÇÜ DƏ SİYASƏTDİR, `executive_digest_config` SƏTRİNİN SÜTUNU DEYİL —
    # ətraflı əsaslandırma `domain/value_objects/executive_digest.py` modul
    # başlığındadır ("İKİ HƏQİQƏT MƏNBƏYİ ARASINDAKI SƏRHƏD").
    #
    # Yeni sətir yaradılanda `frequency` AÇIQ VERİLMƏSƏ tətbiq olunan defolt
    # (`ExecutiveDigestUseCase._resolve_frequency`) — `LEAVE_ALLOWANCE_SOURCE`
    # ilə EYNİ "defolt mənbə konfiqurasiya edilir" naxışı (BR-001, OQ-001).
    EXECUTIVE_DIGEST_DEFAULT_FREQUENCY = "EXECUTIVE_DIGEST_DEFAULT_FREQUENCY"
    # Toggle-lənə bilən metrik açarlarının KATALOQU — vergüllü siyahı naxışı
    # `EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS` ilə EYNİDİR (kompas1.md açıq
    # tələbi). `configure()` yalnız BU siyahıdakı açarları qəbul edir; `run()`
    # göndərmə anında YENİDƏN yoxlayır — kataloqdan çıxmış açar mövcud sətirdə
    # sükutla ATLANIR, sətir ÖZÜ pozulmur (Feature Toggle-ın retroaktiv təsir
    # ETMƏMƏSİ qaydası ilə eyni fəlsəfə).
    EXECUTIVE_DIGEST_METRIC_CATALOG = "EXECUTIVE_DIGEST_METRIC_CATALOG"
    # `JobCadence`-də `WEEKLY` YOXDUR (`job_runner.py`: "ÜÇÜNCÜ VARİANT
    # YOXDUR") — HƏFTƏLİK tezlikli xülasə HANSI gün göndərilsin sualının
    # YEGANƏ cavabı budur (ISO həftə günü, 1=Bazar ertəsi..7=Bazar).
    EXECUTIVE_DIGEST_WEEKLY_WEEKDAY = "EXECUTIVE_DIGEST_WEEKLY_WEEKDAY"
    # --- Faza 7 — HESABAT TARİX ARALIĞI (seed: migrations/043) --------------- #
    #
    # PERFORMANS QORUYUCUSUDUR, struktur zəmanət DEYİL (CLAUDE.md §5): export
    # ekranı `[Tam Ay]`-dan `[Xüsusi Aralıq]`-a genişləndikdə istifadəçi
    # "2020-01-01 – 2030-12-31" yaza bilər. Həmin sorğu 21 filialın 235 işçisi
    # üzrə ~2.5 milyon davamiyyət/plan sətrini bir aqreqasiyada tarayardı və
    # GUI dondurardı.
    #
    # HARDCODE QADAĞANDIR: hədd quraşdırmadan asılıdır — 3 mağazalı kirayəçi
    # rahatlıqla iki illik aralıq çıxara bilər, 21 mağazalı isə yox. Ona görə
    # ədəd kodda deyil, ROOT sətrindədir.
    #
    # NİYƏ GÜN, NİYƏ AY: aralıq artıq günlə ifadə olunur (`ReportRange`), ay
    # ilə ifadə etmək dəyişən uzunluqlu ayları (28–31) yenidən gün sayına
    # çevirməyi tələb edərdi — yəni eyni parametr iki fərqli mənaya gələrdi.
    REPORT_RANGE_MAX_DAYS = "REPORT_RANGE_MAX_DAYS"
    # --- Faza 8 — EXPORT TƏCRÜBƏSİ (seed: migrations/044) --------------------- #
    #
    # DÖRDÜ DƏ SİYASƏTDİR, struktur zəmanət DEYİL (CLAUDE.md §5): heç biri
    # anti-fraud vəzifə ayrılığına, hardlock-a və ya Self-Escalation Guard-a
    # toxunmur — export axınının HƏSSASLIĞINI tənzimləyir.
    #
    # «Anomal yüksək icazəsiz-qayıb» faizi. HARDCODE QADAĞANDIR, çünki normal
    # səviyyə quraşdırmadan asılıdır: mövsümi işçi ilə işləyən şəbəkədə 15%
    # adi, sabit heyətli mağazada 5% artıq təhlükə siqnalıdır. Sabit ədəd
    # birinci şəbəkədə hər ay yalançı siqnal, ikincidə isə SÜKUT verərdi.
    EXPORT_STORE_ABSENCE_ANOMALY_PCT = "EXPORT_STORE_ABSENCE_ANOMALY_PCT"
    # Anomaliya hesablanması üçün mağazadakı MİNİMUM işçi sayı. Bir nəfərlik
    # filialda tək işçinin bir günlük qayıbı nisbəti 100%-ə qaldırır və qayda
    # hər ay «anomaliya» deyərdi — statistik cəhətdən mənasız siqnal isə bütün
    # doğrulama ekranının etibarını aşındırır (`BEHAVIOR_BASELINE_MIN_SAMPLE_
    # SIZE` ilə eyni əsaslandırma).
    EXPORT_STORE_ANOMALY_MIN_EMPLOYEES = "EXPORT_STORE_ANOMALY_MIN_EMPLOYEES"
    # Dövr-üzrə müqayisədə «ƏHƏMİYYƏTLİ fərq» sayılan hədd (mütləq say).
    # kompas1.md Faza 8, bənd F-in AÇIQ ROOT tələbi. Hədd olmadan ekran hər
    # ±1 fərqi qırmızı göstərərdi və HR onları görməzdən gəlməyə öyrəşərdi.
    EXPORT_PERIOD_DELTA_SIGNIFICANT = "EXPORT_PERIOD_DELTA_SIGNIFICANT"
    # Manual düzəlişin səbəb sahəsinin MİNİMUM uzunluğu. DB-də `>= 10` CHECK-i
    # var (migrations/037), lakin o, ABSURD cavabı kəsən DÖŞƏMƏDİR — həqiqi
    # siyasət burada: audit tələbi sərtləşəndə Root onu 10-dan 40-a qaldıra
    # bilməlidir, miqrasiya gözləmədən (`EXCEPTION_REVIEW_NOTE_MIN_LENGTH` ilə
    # eyni naxış). DÖŞƏMƏDƏN AŞAĞI düşmək mümkün deyil: `min_value = 10`.
    EXPORT_CORRECTION_REASON_MIN_LENGTH = "EXPORT_CORRECTION_REASON_MIN_LENGTH"
    # --- NAHAR / ÇAY FASİLƏSİ (nahar.md, seed: migrations/045) --------------- #
    #
    # DÖRDÜ DƏ ROOT PARAMETRİDİR VƏ BU, TAPŞIRIĞIN AÇIQ TƏLƏBİDİR: Nahar/Çay
    # ümumi İcazə Növləri Kataloqundan (HR_Admin, `can_manage_leave_types`)
    # FƏRQLİ olaraq sistemin təməlindədir və yalnız `can_manage_system_limits`
    # sahibi — mövcud hardlock qaydasına görə YALNIZ Root — dəyişə bilər.
    #
    # MÜDDƏT PARAMETRLƏRİ CƏRİMƏ DÜSTURUNA QOŞULMUR (nahar.md §MƏNTİQ, bənd 3
    # — əvvəlcədən verilmiş qərar): `Delay`/`Total` hesablaması mövcud qaydada
    # `LeaveAllowancePolicy`-dən (BR-001) qidalanır. Buradakı dəqiqə yalnız
    # İşçi Ana Ekranındakı «Nahar fasiləniz: 60 dəqiqə» göstəricisidir.
    # Birləşdirmək cazibədar görünür, LAKİN onda Root informativ mətni
    # dəyişəndə işçinin cəriməsi də dəyişərdi — yəni məlumatlandırıcı sahə
    # sükutla pul qərarına çevrilərdi.
    LUNCH_BREAK_DURATION_MINUTES = "LUNCH_BREAK_DURATION_MINUTES"
    # SAY-HƏDDİ BLOKLAMIR (nahar.md-nin açıq göstərişi): aşılanda yalnız
    # xəbərdarlıq göstərilir, STEP1 davam edir. Eyni fəlsəfə layihədə artıq
    # var — `MonthlyLeaveUsage` (aylıq 240 dəq.) da bloklamır.
    LUNCH_BREAK_DAILY_COUNT = "LUNCH_BREAK_DAILY_COUNT"
    TEA_BREAK_DURATION_MINUTES = "TEA_BREAK_DURATION_MINUTES"
    TEA_BREAK_DAILY_COUNT = "TEA_BREAK_DAILY_COUNT"
    # --- FACE CONTROL — ÜZ TƏSDİQİ (facecontrol.md, seed: migrations/047) ---- #
    #
    # ONU DA `facecontrol.md`-nin "ROOT PARAMETRİ" işarəli (və ya MƏRKƏZİ
    # TƏLƏBİN əhatə etdiyi) dəyəridir və sənəd onların hardcode edilməsini
    # AÇIQ şəkildə qadağan edir. Heç biri CLAUDE.md §5-dəki struktur zəmanət
    # DEYİL: anti-fraud vəzifə ayrılığına, hardlock iyerarxiyasına və
    # dual-control axınına toxunmurlar — biometrik qatın HƏSSASLIĞINI
    # tənzimləyirlər. Səlahiyyət tərəfi isə struktur zəmanətdir və ayrıca
    # yaşayır (`can_manage_face_exemptions`, hardlock 2).
    #
    # Enrollment kadrının minimum keyfiyyət balı. HARDCODE QADAĞANDIR, çünki
    # doğru hədd KAMERADAN və İŞIQDAN asılıdır: vitrin işığı altındakı kiosk
    # ilə anbar dəhlizindəki kiosk eyni bala çatmır. Sabit ədəd birincidə
    # mənasız, ikincidə isə enrollment-i tamamilə mümkünsüz edərdi.
    FACE_ENROLLMENT_MIN_QUALITY = "FACE_ENROLLMENT_MIN_QUALITY"
    # Enrollment-də çəkilən KADR SAYI (bənd 11 — çox-kadr orta alma).
    # HARDCODE QADAĞANDIR VƏ BU, TAPŞIRIĞIN AÇIQ TƏLƏBİDİR: ədəd keyfiyyət
    # ilə vaxt arasındakı MÜBADİLƏDİR və doğru nöqtəsi avadanlıqdan asılıdır.
    # Zəif veb-kamerada beş kadrın ortası daha sabitdir; güclü kamerada isə
    # üç kadr eyni nəticəni yarı vaxta verir və 235 işçilik şəbəkədə bu, real
    # fərqdir. Kodda sabit ədəd hər iki quraşdırmanın birində səhv olardı.
    #
    # BU PARAMETR HEÇ VAXT PERFORMANSA GÖRƏ AVTOMATİK AZALDILMIR (bənd 18-in
    # kritik qaydası): doğrulama yavaşdırsa həll yolu hardware/optimallaşdırma
    # olmalıdır — kadr sayının sükutla endirilməsi TƏHLÜKƏSİZLİK GÜZƏŞTİDİR.
    FACE_ENROLLMENT_FRAME_COUNT = "FACE_ENROLLMENT_FRAME_COUNT"
    # Ardıcıl MISMATCH kilid həddi. PIN-in öz həddindən (`PIN_MAX_FAILED_
    # ATTEMPTS` = 5) AYRI açardır və bu, qəsdlidir: unudulmuş rəqəm ilə
    # tanınmayan üz eyni ağırlıqda siqnal deyil. Kilidin MÜDDƏTİ üçün YENİ
    # açar yaradılmır — `PIN_LOCKOUT_MINUTES` işlədilir, çünki facecontrol.md
    # bənd 4 lockout mexanizminin təkrar yazılmasını qadağan edir.
    FACE_MISMATCH_LOCKOUT_THRESHOLD = "FACE_MISMATCH_LOCKOUT_THRESHOLD"
    # Aktiv liveness hərəkətlərinin VERGÜLLÜ kataloqu (bənd 6). Kataloq
    # formatı `EXECUTIVE_DIGEST_METRIC_CATALOG` ilə eynidir: Root bir hərəkəti
    # söndürmək üçün onu siyahıdan çıxarır, yeni buraxılış lazım deyil.
    FACE_LIVENESS_ACTIONS = "FACE_LIVENESS_ACTIONS"
    # Bənzərlik həddi (bənd 7) — kitabxananın MƏSAFƏ vahidində (kiçik = daha
    # oxşar). VAHİD SEÇİMİ QƏSDLİDİR: hədd faizə çevrilsəydi, Root-un gördüyü
    # ədədlə kitabxananın cavabı arasında gizli bir çevirmə düsturu oturardı
    # və həmin düstur özü hardcode edilmiş qərara çevrilərdi.
    FACE_MATCH_TOLERANCE = "FACE_MATCH_TOLERANCE"
    # Aşağı-etibar həddi (bənd 12) — nəticə BİNAR DEYİL. Bu qiymətlə
    # `FACE_MATCH_TOLERANCE` arasındakı zolaq "icazə ver, amma nişanla"
    # deməkdir. İki AYRI açar lazımdır, çünki tək hədd yalnız keç/keçmə
    # verərdi və Kamera Operatoru sərhəd hallarını heç vaxt görməzdi.
    FACE_LOW_CONFIDENCE_TOLERANCE = "FACE_LOW_CONFIDENCE_TOLERANCE"
    # Yenidən-qeydiyyat tövsiyəsinin intervalı (ay, bənd 13). BLOKLAMIR —
    # `MonthlyLeaveUsage` ilə eyni fəlsəfə: xəbərdarlıq göstərilir, iş davam
    # edir. İnsan üzünün nə qədər sürətlə "köhnəldiyi" empirik sualdır.
    FACE_REENROLLMENT_REMINDER_MONTHS = "FACE_REENROLLMENT_REMINDER_MONTHS"
    # İstisnanın maksimum ömrü (gün, bənd 14). Parametr olmasaydı, "müvəqqəti"
    # istisna sükutla əbədiyə çevrilərdi — təhlükəsizlik aşınmasının ən çox
    # rast gəlinən formasıdır.
    FACE_EXEMPTION_MAX_DAYS = "FACE_EXEMPTION_MAX_DAYS"
    # Doğrulama jurnalının saxlanma müddəti (ay, bənd 17). Hüquqi tələb
    # yurisdiksiyaya görə dəyişir; sabit ədəd bir müştəridə çox, digərində az
    # olardı. 12 ay mövcud Davranış Anomaliyası aralığından (30 gün) qat-qat
    # genişdir, yəni baseline hesablaması pozulmur.
    FACE_VERIFICATION_LOG_RETENTION_MONTHS = "FACE_VERIFICATION_LOG_RETENTION_MONTHS"
    # Gözlənilən maksimum doğrulama vaxtı (saniyə, bənd 18). YALNIZ hardware
    # diaqnostikasıdır: aşılma System Health Monitor-a xəbərdarlıq yazır və
    # HEÇ VAXT keyfiyyət parametrlərini avtomatik zəiflətmir.
    FACE_VERIFICATION_MAX_SECONDS = "FACE_VERIFICATION_MAX_SECONDS"
    # --- G-5/G-6 audit boşluqları (seed: migrations/054) --------------------- #
    #
    # HƏR İKİSİ GÖRÜNÜŞ PARAMETRİDİR, struktur zəmanət DEYİL (CLAUDE.md §5):
    # nə anti-fraud vəzifə ayrılığına, nə hardlock iyerarxiyasına, nə də
    # dual-control axınına toxunurlar. Heç biri SƏLAHİYYƏT genişləndirmir —
    # ikisi də yalnız ARTIQ icazəli məlumatın necə göstərildiyini təyin edir.
    #
    # Kamera Operatorunun mağaza süzgəci NEÇƏ MAĞAZADAN SONRA görünsün.
    # Spesifikasiya "3-dən çox" deyir, lakin ədədin özü müəssisədən asılıdır:
    # 21 filiallı şəbəkədə operatorun 6 mağazası ola bilər, kiçik müəssisədə
    # isə 2. Sabit 3 birincidə süzgəci məcburi, ikincisində isə əlçatmaz
    # edərdi. SÜZGƏC SƏLAHİYYƏT QAPISI DEYİL — operator onsuz da yalnız ÖZ
    # təyinatlarını görür (`stores_for_operator`), bu ədəd isə sadəcə
    # "siyahı nə vaxt uzun sayılır" sualına cavab verir.
    CAMERA_QUEUE_STORE_FILTER_THRESHOLD = "CAMERA_QUEUE_STORE_FILTER_THRESHOLD"
    # Panel Qurucusundakı şəbəkənin SÜTUN SAYI. Ekran ölçüsü müəssisədən
    # müəssisəyə dəyişir: baş ofisdəki 27 düymlük monitorda üç sütun rahat
    # oxunur, filialdakı 13 düymlük noutbukda isə iki sütun belə sıxdır.
    # Sabit ədəd birində boş sahə, digərində kəsilmiş başlıq verərdi.
    #
    # DAR PƏNCƏRƏ BU DƏYƏRDƏN ASILI DEYİL: `LayoutMode.COMPACT` şəbəkəni
    # HƏMİŞƏ tək sütuna yığır (bax `dashboard_layout.collapse_to_single_column`)
    # — yəni Root böyük ədəd yazsa belə dar ekranda düzülüş sınmır.
    DASHBOARD_GRID_COLUMNS = "DASHBOARD_GRID_COLUMNS"
    # --- SEC-011 sessiya müddətləri (dövrə debatı, SEC-5 audit tapıntısı) --- #
    #
    # `schema.sql` §17b (`auth_sessions` cədvəlinin şərhi) açıq deyir:
    # "Dəyərlər system_limits-dən oxunur" — sənəd HƏMİŞƏ bunu vəd edib, kod isə
    # sətri heç vaxt yazmamışdı (SEC-5 tapıntısı). ÜÇÜ DƏ ROOT PARAMETRİDİR:
    # müştəridən müştəriyə (bank filialı vs kiçik mağaza) qəbul edilən risk
    # fərqlənir, sabit ədəd bunu koda "yazılı qanuna" çevirərdi.
    #
    # Hərəkətsizlik pəncərəsi (`ADMIN_PANEL`) — `touch()` bunu `last_seen_at`-ə
    # görə uzadır, `absolute_expiry`-ni ƏSLA aşmır (`entities/auth_session.py`).
    ADMIN_PANEL_SESSION_IDLE_TIMEOUT_MINUTES = "ADMIN_PANEL_SESSION_IDLE_TIMEOUT_MINUTES"
    # Mütləq tavan (`ADMIN_PANEL`) — hərəkətsizlik pəncərəsi nə qədər uzansa da
    # bu andan sonra sessiya bitir. SEC-011-in bütün mənası bu iki həddin
    # MÜSTƏQİL olmasıdır (biri "istifadəçi işləyirmi", digəri "nə qədər vaxtdır
    # açıqdır" sualına cavab verir).
    ADMIN_PANEL_SESSION_ABSOLUTE_TIMEOUT_HOURS = "ADMIN_PANEL_SESSION_ABSOLUTE_TIMEOUT_HOURS"
    # `CAMERA_DASHBOARD`-un YEGANƏ həddi — hərəkətsizlik yoxlaması YOXDUR
    # (`SessionContext.has_idle_timeout`), çünki operator ekrana BAXIR,
    # klikləmir. 12 saat bir NÖVBƏNİN uzunluğudur — gecə növbəsi bitəndə
    # sessiya da bitməlidir, əks halda ertəsi növbənin operatoru əvvəlkinin
    # açıq sessiyasını miras alardı (SEC-5-in kəşf etdiyi məhz bu ssenari).
    CAMERA_DASHBOARD_SESSION_ABSOLUTE_TIMEOUT_HOURS = (
        "CAMERA_DASHBOARD_SESSION_ABSOLUTE_TIMEOUT_HOURS"
    )
    # --- SEC-01/SEC-05 terminal PIN throttle (dövrə 3-4 audit tapıntısı) --- #
    #
    # `PIN_MAX_FAILED_ATTEMPTS`/`PIN_LOCKOUT_MINUTES` (yuxarıda) İŞÇİ-BAŞINA
    # sayğacdır və PIN ANONİM olduğu üçün canlı kiosk axınında YAZILMIR
    # (`PinHandshakeUseCase.authenticate()` "heç bir namizədə uyğun gəlmədi"
    # halında HANSI işçinin cəhd etdiyini bilmir — bax `group_a_kiosk.py:364`).
    # Bu İKİ açar AYRI, TERMİNAL-səviyyəli qoruma qatıdır: sayğac
    # `(tenant_id, machine_guid_hash)` cütünə bağlıdır (SEC-05 — `store_id`
    # admin hüququ olmadan dəyişdirilə bilən mühit dəyişənindən gəlir, açar
    # ola bilməzdi, bax `MachineIdentityHash`-in öz modul başlığı), konkret
    # işçiyə DEYİL. Müştəridən müştəriyə qəbul edilən risk (kassa növbəsinin
    # sıxlığı, terminalın fiziki əlçatanlığı) FƏRQLƏNİR, ona görə ROOT
    # PARAMETRİDİR.
    KIOSK_STORE_PIN_MAX_FAILED_ATTEMPTS = "KIOSK_STORE_PIN_MAX_FAILED_ATTEMPTS"
    KIOSK_STORE_PIN_LOCKOUT_MINUTES = "KIOSK_STORE_PIN_LOCKOUT_MINUTES"
    #: HR-1 — cavabsız cərimə etirazı neçə gün sonra İstisna Motoruna qalxır.
    #:
    #: `FINE_APPEAL_WINDOW_HOURS`-a BAĞLANMADI (xal pəncərəsi ilə eyni
    #: əsaslandırma, yuxarıya bax): pəncərə İŞÇİNİN nə qədər vaxtı olduğunu
    #: deyir, bu isə HR-ın cavabsızlığının nə vaxt PROBLEM sayıldığını.
    #: Root birincisini uzadanda ikincisi sükutla sürüşməməlidir.
    FINE_APPEAL_ESCALATION_DAYS = "FINE_APPEAL_ESCALATION_DAYS"
    #: HR-2 — cərimə nəşr gözləməkdə neçə gün qala bilər.
    FINE_REVIEW_OVERDUE_DAYS = "FINE_REVIEW_OVERDUE_DAYS"
    # --- HR Lifecycle v2 (`v2backlog.md` Faza 3.2/3.5) ---
    #
    # Faza 3.2 — keçmiş (DEAKTİV) işçinin PII sahələrinin (ad, telefon və s.)
    # neçə AY sonra anonimləşdiriləcəyi. `audit_logs` bu həddən İSTİSNADIR
    # (migrations/088 başlığı — hüquqi tələb ola bilər). Gecəlik cron bu
    # müddəti keçmiş, hələ anonimləşdirilməmiş sətirləri tapır
    # (`employees.data_anonymized_at IS NULL`).
    FORMER_EMPLOYEE_DATA_RETENTION_MONTHS = "FORMER_EMPLOYEE_DATA_RETENTION_MONTHS"
    #: Faza 3.5 — yeni işçi `referred_by_employee_id` ilə yaradılanda tövsiyə
    #: edən işçiyə yazılan bonus-xal sayı (mövcud `points_ledger`,
    #: `SalesPointsUseCase.award_referral_bonus`). `0` = bonus SÖNDÜRÜLÜB —
    #: sahə yenə doldurulur (kim tövsiyə etdiyi tarixi fakt kimi qalır),
    #: yalnız xal YAZILMIR.
    EMPLOYEE_REFERRAL_BONUS_POINTS = "EMPLOYEE_REFERRAL_BONUS_POINTS"
    # --- HR Lifecycle v2 (`v2backlog.md` Faza 4.2) ---
    #
    # İşçinin öz-düzəliş sorğusu (Kamera/Face Control uyğunsuzluğu). İKİSİ DƏ
    # ROOT PARAMETRİDİR: pəncərə "hansı müddətdə sayılır", tavan isə "həmin
    # müddətdə neçə sorğu icazəlidir" sualına cavab verir — `DUAL_CONTROL_
    # THRESHOLD_MINUTES`/`..._APPROVAL_TIMEOUT_MINUTES` cütü ilə EYNİ ayırma
    # səbəbi (bir açar «nə vaxt», digəri «nə qədər»).
    SELF_CORRECTION_REQUEST_WINDOW_DAYS = "SELF_CORRECTION_REQUEST_WINDOW_DAYS"
    SELF_CORRECTION_REQUEST_MAX_COUNT = "SELF_CORRECTION_REQUEST_MAX_COUNT"
    # --- Sistem davamlılığı (`v2backlog.md` Faza 5.3/5.4) ---
    #
    # Şift-handoff qeydi: mətn uzunluğu və qeydin növbəti işçiyə NEÇƏ SAAT
    # göstərilməsi. Uzunluq Root parametridir, çünki kiosk ekranının ölçüsü
    # quraşdırmadan-quraşdırmaya dəyişir (10" tablet ilə 24" monitor);
    # görünmə pəncərəsi isə mağazanın növbə uzunluğunu izləyir — 24 saatlıq
    # mağazada 8 saat, gündüz mağazasında 16 saat mənalıdır.
    SHIFT_HANDOFF_NOTE_MAX_CHARS = "SHIFT_HANDOFF_NOTE_MAX_CHARS"
    SHIFT_HANDOFF_VISIBILITY_HOURS = "SHIFT_HANDOFF_VISIBILITY_HOURS"
    #
    # Break-glass fövqəladə giriş. ÜÇ açar, ÜÇ FƏRQLİ sual:
    #   * `..._MAX_DURATION_MINUTES` — səlahiyyət NƏ QƏDƏR yaşayır;
    #   * `..._APPROVAL_WINDOW_MINUTES` — ikinci-etibarlı şəxs təsdiqi NƏ
    #     QƏDƏR müddətdə verməlidir (verməzsə sorğu ölür);
    #   * `..._MAX_GRANTS_PER_MONTH` — ayda neçə dəfə. Sonuncu təhlükəsizlik
    #     həddidir: break-glass NADİR olmalıdır, tez-tez işlənirsə bu, artıq
    #     "fövqəladə hal" deyil, gizli daimi səlahiyyətdir.
    # HEÇ BİRİ struktur zəmanət DEYİL (§5) — zəmanət olan hissə "ikinci şəxs
    # TƏLƏB OLUNUR" və "hər istifadə audit olunur" qaydalarıdır, onlar KODDA
    # sabitdir və Root tərəfindən söndürülə bilmir. Root yalnız ƏDƏDLƏRİ
    # tənzimləyir.
    BREAK_GLASS_MAX_DURATION_MINUTES = "BREAK_GLASS_MAX_DURATION_MINUTES"
    BREAK_GLASS_APPROVAL_WINDOW_MINUTES = "BREAK_GLASS_APPROVAL_WINDOW_MINUTES"
    BREAK_GLASS_MAX_GRANTS_PER_MONTH = "BREAK_GLASS_MAX_GRANTS_PER_MONTH"

    # --- Analitika genişlənməsi (`v2backlog.md` Faza 6.5) ---
    #
    # İş-Yükü Ədalətliliyi Göstəricisinin **ROOT PARAMETRİ** (spesifikasiyanın
    # öz işarəsi): son 30 gündə iki işçinin təyin olunmuş iş günü sayı
    # arasındakı fərq bu həddi aşarsa, sətir «fərqli» nişanı alır. Defolt 4:
    # bir həftəlik növbə dövründə hiss edilən ədalətsizlik həddi; daha aşağı
    # qiymət normal planlamada da siqnal verərdi.
    WORKLOAD_FAIRNESS_MAX_GAP = "WORKLOAD_FAIRNESS_MAX_GAP"

    # --- İki-nəfərlik fırıldaqçılıq aşkarlaması (`v2backlog.md` Faza 7) ---
    #
    # «Davranış-cüt» qaydasının ÜÇ açarı. `..._CORRELATION_THRESHOLD`
    # spesifikasiyanın ÖZ işarələdiyi **ROOT PARAMETRİ**-dir (korrelyasiya-
    # həddi): ortaq iş günlərinin neçə faizində iki işçi `SYNC_MINUTES`
    # içində giriş edirsə, cüt Exception Engine-ə yazılır. Qalan ikisi
    # yalan-pozitivi idarə edir: az ortaq gündən nümunə çıxmaq ittihamdır
    # (`MIN_SHARED_DAYS`, BehaviorAnomalyRule-un min-sample qaydasının
    # analoqu), sinxron pəncərəsi isə «birlikdə giriş» tərifidir.
    BEHAVIOR_PAIR_CORRELATION_THRESHOLD = "BEHAVIOR_PAIR_CORRELATION_THRESHOLD"
    BEHAVIOR_PAIR_MIN_SHARED_DAYS = "BEHAVIOR_PAIR_MIN_SHARED_DAYS"
    BEHAVIOR_PAIR_SYNC_MINUTES = "BEHAVIOR_PAIR_SYNC_MINUTES"

    # --- Lokallaşdırma (`v2backlog.md` Faza 8.1) ---
    #
    # Kirayəçi-səviyyəli interfeys dili. DƏYƏR TƏK SÖZDÜR ("az") — açar
    # indi yaradılır ki, ikinci dil gələndə KOD deyil, YALNIZ data dəyişsin:
    # Root seçimi bu açara yazılır, `configure_i18n` isə yeganə oxu nöqtəsidir.
    UI_LANGUAGE = "UI_LANGUAGE"


DEFAULT_LIMITS: Final[dict[SystemLimitKey, str]] = {
    SystemLimitKey.MONTHLY_LEAVE_MINUTES_LIMIT: "240",
    SystemLimitKey.FINE_APPEAL_WINDOW_HOURS: "72",
    SystemLimitKey.LATE_TOLERANCE_MINUTES: "15",
    SystemLimitKey.VERIFICATION_TIMEOUT_MINUTES: "45",
    SystemLimitKey.DUAL_CONTROL_THRESHOLD_MINUTES: "30",
    # 480 dəqiqə = BİR İŞ NÖVBƏSİ. Ölçü təsadüfi seçilməyib: ikinci təsdiqin
    # dəyəri hadisənin konteksti CANLI olduğu müddətdədir — təsdiqçi lazım
    # gələrsə düzəlişi yazan operatordan soruşa bilməlidir. Növbə bitəndən
    # sonra o operator artıq işdə olmur və təsdiq formal imzaya çevrilir.
    # `VERIFICATION_TIMEOUT_MINUTES` (45) ilə eyniləşdirmək RƏDD EDİLDİ:
    # 45 dəqiqə işçini limbo-da saxlamamaq üçündür (o, mağazada gözləyir),
    # burada isə heç kim gözləmir — icazə axını orijinal vaxtla onsuz da
    # davam edir (bax `ManualOverride.is_effective`).
    SystemLimitKey.DUAL_CONTROL_APPROVAL_TIMEOUT_MINUTES: "480",
    SystemLimitKey.PIN_MAX_FAILED_ATTEMPTS: "5",
    SystemLimitKey.PIN_LOCKOUT_MINUTES: "15",
    SystemLimitKey.NTP_MAX_DRIFT_SECONDS: "60",
    SystemLimitKey.MAX_UPLOAD_SIZE_BYTES: "5242880",
    SystemLimitKey.LEAVE_ALLOWANCE_SOURCE: "LEAVE_TYPE",
    SystemLimitKey.LEAVE_ALLOWANCE_FIXED_MINUTES: "0",
    SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE: "0.00",
    # İstisnalar ekranının bir səhifədə oxuduğu sətir sayı. 21 filialın açıq
    # növbəsi böyüyə bilər; limitsiz oxu ekranı dondurardı.
    SystemLimitKey.EXCEPTION_PAGE_SIZE: "200",
    # BİR qaydanın BİR icrada yarada biləcəyi maksimum tapıntı. Qüsurlu qayda
    # (məs. baz xətti sıfır olan yeni işçilər) minlərlə sətir yarada bilər və
    # `exceptions`-da `REVOKE DELETE` olduğu üçün onları TƏMİZLƏMƏK MÜMKÜN
    # DEYİL — ona görə tavan konfiqurasiya edilə bilən qoruyucudur.
    SystemLimitKey.EXCEPTION_MAX_FINDINGS_PER_RULE: "500",
    # HR-1 — 3 gün. Ədəd `FINE_APPEAL_WINDOW_HOURS`-un (72 saat) NƏTİCƏSİDİR,
    # nüsxəsi deyil: etiraz pəncərəsi bağlananda `expire_stale` sətri
    # `EXPIRED` edir, LAKİN qərar hələ gözlənilir (M-6). Bir tam pəncərə
    # qədər daha gözləmək HR-a real imkan verir; ondan sonra cavabsızlıq
    # artıq gecikmə deyil, İSTİSNA-dır. Sıfır seçilsəydi hər bağlanan
    # pəncərə dərhal istisna doğurar və jurnal normal iş axını ilə dolardı.
    SystemLimitKey.FINE_APPEAL_ESCALATION_DAYS: "3",
    # HR-2 — 30 gün. İcmal AYLIQ dövrədir (`review_month`, `fine_review.py`),
    # yəni bir tam dövrə buraxılmayınca gözləmə NORMALDIR. 30-dan çox
    # gözləyən sətir isə o deməkdir ki, icmal HEÇ KEÇİRİLMƏYİB — və məhz o
    # halda cərimə işçiyə GÖRÜNMÜR, etiraz pəncərəsi də AÇILMIR.
    SystemLimitKey.FINE_REVIEW_OVERDUE_DAYS: "30",
    # Bu ciddiyyətdən (daxil olmaqla) yuxarı tapıntı DƏRHAL bildiriş doğurur.
    # Defolt HIGH: MEDIUM-da hər gecikmə anomaliyası HR-a mesaj göndərər və
    # bildiriş kanalı bir həftədə "səs-küy" kimi görməzdən gəlinərdi.
    SystemLimitKey.EXCEPTION_NOTIFY_MIN_SEVERITY: "HIGH",
    # Rədd qərarının izahı üçün minimum uzunluq (`FineAppeal` ilə eyni dəyər).
    SystemLimitKey.EXCEPTION_REVIEW_NOTE_MIN_LENGTH: "10",
    # #7 POS həddinin Root-dan idarə olunan ƏLAVƏ tavanı. 100 = sxem
    # sərhədi ilə üst-üstə düşür (migrations/018 CHECK-i) — başlanğıcda
    # Root heç bir əlavə məhdudiyyət qoymur, istəsə aşağı sala bilər.
    SystemLimitKey.POS_MAX_DISCOUNT_PCT_CEILING: "100",
    # #8 baz xətt pəncərəsi — kompasos11.md "son 30 gün" tələbinin defoltu.
    SystemLimitKey.BEHAVIOR_BASELINE_WINDOW_DAYS: "30",
    # 45 dəqiqə: `VERIFICATION_TIMEOUT_MINUTES` ilə eyni miqyasda seçilib —
    # bundan az sapma gündəlik nəqliyyat/trafik dalğalanması ola bilər,
    # ondan çoxu isə HR-ın araşdırmalı olduğu davamlı meyl siqnalıdır.
    SystemLimitKey.BEHAVIOR_ANOMALY_THRESHOLD_MINUTES: "45",
    # 5 gün ≈ bir iş həftəsi — bundan az müşahidə statistik cəhətdən etibarsız
    # baz xətt deməkdir (migrations/018 şərhi).
    SystemLimitKey.BEHAVIOR_BASELINE_MIN_SAMPLE_SIZE: "5",
    # 2.0σ — normal paylanmada təsadüfi kənarlaşmaların ~95%-i bu hüdud
    # daxilindədir; ondan kənar sapma statistik cəhətdən "adi deyil" sayılır.
    SystemLimitKey.BEHAVIOR_ANOMALY_SIGMA_MULTIPLIER: "2.0",
    # #15 — Azərbaycan Əmək Məcəlləsinin normal iş vaxtı: gündə 8, həftədə 40
    # saat. Defolt qanunun ÖZÜNÜ təkrarlayır; qısaldılmış iş vaxtı rejimləri
    # (məs. yetkinlik yaşına çatmayanlar) üçün Root onu aşağı sala bilər.
    SystemLimitKey.OVERTIME_DAILY_NORM_HOURS: "8.00",
    SystemLimitKey.OVERTIME_WEEKLY_NORM_HOURS: "40.00",
    # 1 saat — bir növbədə bu qədər aşım artıq təsadüfi deyil (növbənin
    # uzadılması və ya əlavə iş günü deməkdir). Ondan kiçik fərqlər jurnalda
    # qalır, lakin HR-a bildiriş göndərmir.
    SystemLimitKey.OVERTIME_NOTIFY_THRESHOLD_HOURS: "1.00",
    # #14 — 12 saat: iki növbə arasında bir gecəlik yuxu + yol vaxtı. Bu, ƏMƏK
    # HÜQUQU MƏSLƏHƏTİ DEYİL, layihənin başlanğıc dəyəridir — müəssisə öz
    # hüquqşünasının göstərişinə görə Root panelindən dəyişir.
    SystemLimitKey.LABOR_MIN_REST_HOURS: "12",
    # 60 dəqiqə — mağaza praktikasındakı standart nahar fasiləsi. `LeaveType`
    # "Nahar Fasiləsi" ilə eyni miqyasda seçilib ki, plandakı xatırlatma ilə
    # faktiki icazə axını bir-birini təkzib etməsin.
    SystemLimitKey.LABOR_MANDATORY_BREAK_MINUTES: "60",
    # 6 saat — bundan qısa növbədə fasilə xatırlatması hər gün təkrarlanardı
    # və xəbərdarlıq kanalı dəyərini itirərdi.
    SystemLimitKey.LABOR_BREAK_REQUIRED_AFTER_HOURS: "6",
    # 6 gün — həftədə ən azı bir istirahət günü prinsipi. 6/1 iş rejimi
    # (`ShiftPlanningScreen.TEMPLATES`) xəbərdarlıq DOĞURMUR, 7-ci ardıcıl gün
    # doğurur.
    SystemLimitKey.LABOR_MAX_CONSECUTIVE_WORK_DAYS: "6",
    # #13 — 8 həftə ≈ 2 ay: bir mağazanın həftə-günü ritmini görmək üçün kifayət
    # qədər uzun, mövsüm dəyişikliyini "orta"ya qatmayacaq qədər qısa. DB
    # sütununun defoltu ilə eyni miqyasdadır (migrations/019 `based_on_weeks`).
    SystemLimitKey.STAFFING_PATTERN_BASED_ON_WEEKS: "8",
    # #16 — 30 gün: açıq növbə "boşluğu doldurmaq" alətidir, uzunmüddətli
    # planlama deyil. Bir aydan uzağa elan verilsəydi, işçilər hələ
    # planlaşdırılmamış təqvimi elan siyahısından oxumağa başlayardı.
    SystemLimitKey.OPEN_SHIFT_MAX_LEAD_DAYS: "30",
    # #16 — ayda 8 elan ≈ həftədə iki əlavə növbə. Bu, işçinin öz istəyi ilə
    # götürdüyü ƏLAVƏ işdir; gündə birdən çoxu onsuz da mümkün deyil (DB:
    # `uq_open_shift_one_claim_per_employee_day`), lakin AYLIQ tavan olmasa
    # bazar bir neçə işçinin daimi əlavə növbəsinə çevrilərdi.
    SystemLimitKey.OPEN_SHIFT_MAX_CLAIMS_PER_MONTH: "8",
    # #17 — 30/14/7 gün: spesifikasiyanın öz nümunəsi (üç mərhələli xatırlatma:
    # "hələ vaxt var" → "tezliklə" → "təcili"). Vergüllə ayrılmış siyahı —
    # yuxarıdakı şərhə bax.
    SystemLimitKey.EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS: "30,14,7",
    # #19 — 14 gün: bir "cari xəbərlər lövhəsi" pəncərəsi üçün ağlabatan
    # müddət (iki iş həftəsi) — bundan uzun görüntülənmə kiosk kartını köhnə
    # göstərişlərlə doldurardı.
    SystemLimitKey.ANNOUNCEMENT_VISIBILITY_DAYS: "14",
    # #20 — aylıq: `MONTHLY_LEAVE_MINUTES_LIMIT` və digər dövri hesabatlarla
    # (Aylıq Cərimə İcmalı) EYNİ ritmdə. Root rüblük rejimə keçə bilər.
    SystemLimitKey.PERFORMANCE_REVIEW_PERIOD_TYPE: "MONTHLY",
    # #20 — dörd ümumi KPI: keyfiyyət, məhsuldarlıq, komanda işi, müştəri
    # xidməti. Bunlar YALNIZ İLKİN dəyərdir — Root panelindən dəyişdirilə
    # bilər (aşağı/yuxarı hüdud mənasızdır, `EXCEPTION_NOTIFY_MIN_SEVERITY`
    # ilə eyni TEXT üslubu).
    SystemLimitKey.PERFORMANCE_REVIEW_KPI_CATALOG: (
        "KEYFIYYET:İş Keyfiyyəti;MEHSULDARLIQ:Məhsuldarlıq;"
        "KOMANDA_ISI:Komanda İşi;MUSTERI_XIDMETI:Müştəri Xidməti"
    ),
    # #21 — 5 bal hər ƏLAVƏ cərimə üçün (artım, mütləq say yox). 3 cərimədən
    # 6-ya qalxma (+3) = 15 bal — tək başına "yüksək risk" elan etmir, lakin
    # digər siqnallarla birləşəndə həlledici ola bilər.
    SystemLimitKey.ATTRITION_FINE_TREND_WEIGHT: "5",
    # #21 — 8 bal hər icazəsiz davamiyyət pozuntusuna. Cərimədən bir az ağır
    # çəkilib, çünki icazəsiz qayıb birbaşa "işə bağlılığın azalması" siqnalıdır.
    SystemLimitKey.ATTRITION_ATTENDANCE_VIOLATION_WEIGHT: "8",
    # #21 — yeni işçiyə sabit 15 bal ("onboarding riski").
    SystemLimitKey.ATTRITION_NEW_HIRE_RISK_POINTS: "15",
    # #21 — 3 ay: sınaq müddəti ilə eyni miqyasda seçilib (əksər əmək
    # müqavilələrində ilk 3 ay sınaq dövrüdür).
    SystemLimitKey.ATTRITION_NEW_HIRE_THRESHOLD_MONTHS: "3",
    # #21 — aylıq icazə limitinin TAM istifadəsinə (100%) qarşılıq 20 bal
    # (xətti miqyaslanır: 50% istifadə = 10 bal).
    SystemLimitKey.ATTRITION_LEAVE_USAGE_WEIGHT: "20",
    # #21 — 3 ay: tapşırığın öz nümunəsi ("son 3 ayda cərimə artımı").
    SystemLimitKey.ATTRITION_WINDOW_MONTHS: "3",
    # #21 — 70 bal: dörd siqnalın heç biri tək başına bu həddə çatmır (maks.
    # tək-siqnal töhfəsi leave-usage-da 20-dir), yəni bildiriş YALNIZ bir neçə
    # siqnal BİRLƏŞƏNDƏ işə düşür — tək bir pozuntu HR-ı həyəcanlandırmamalıdır.
    SystemLimitKey.ATTRITION_HIGH_RISK_THRESHOLD: "70",
    # #24 — 6 ay: tapşırığın öz nümunəsi ("son 6 ay üzrə dəyişim").
    SystemLimitKey.BENCHMARK_TREND_MONTHS: "6",
    # #24 — 2.0σ: `BEHAVIOR_ANOMALY_SIGMA_MULTIPLIER` ilə EYNİ statistik
    # əsaslandırma (normal paylanmada təsadüfi kənarlaşmaların ~95%-i bu
    # hüdud daxilindədir).
    SystemLimitKey.BENCHMARK_OUTLIER_SIGMA_MULTIPLIER: "2.0",
    # --- Faza 10.2 — domen value object parametrləri (seed: 033) ------------ #
    #
    # HƏR DEFOLT KÖÇÜRÜLƏN HARDCODE DƏYƏRLƏ HƏRFƏN EYNİDİR — köçürmə davranışı
    # DƏYİŞMİR, yalnız dəyərin harada yaşadığı dəyişir.
    #
    # #6 — 100 AZN brutto satış = 1 xal. "Hər satışa 1 xal" RƏDD EDİLİB:
    # satıcını bir çeki bir neçəyə bölməyə həvəsləndirərdi (bax `gamification`).
    SystemLimitKey.SALES_POINTS_CURRENCY_PER_POINT: "100",
    # #6 — 72 saat: `FINE_APPEAL_WINDOW_HOURS` ilə EYNİ DEFOLT, AYRI açar
    # (səbəb enum şərhindədir).
    SystemLimitKey.SALES_POINTS_DISPUTE_WINDOW_HOURS: "72",
    # #6 — 14 gün: bölmə 6-nın öz ədədi ("reset öncəsi 14 gün əvvəldən bildiriş").
    SystemLimitKey.SALES_POINTS_RESET_NOTICE_DAYS: "14",
    # Bölmə 8 — "məs. hər 24 saatda" (86 400 san). Təkrar cəhd bir saatdır:
    # qrace sayğacı işləyərkən sutkalıq gözləmə bərpa olunmuş şəbəkəni bir gün
    # gec görmək demək olardı. Bloklanmış vəziyyətdə ritm 15 dəqiqəyə enir —
    # ödənişini edib telefonda gözləyən müştəri 24 saat gözləməməlidir.
    SystemLimitKey.LICENSE_CHECK_IN_INTERVAL_SECONDS: "86400",
    SystemLimitKey.LICENSE_RETRY_INTERVAL_SECONDS: "3600",
    SystemLimitKey.LICENSE_BLOCKED_RECHECK_INTERVAL_SECONDS: "900",
    # Bölmə 8 — `license_tenants.offline_grace_days` CHECK bandı (7–14) və
    # sətir oxunmadıqda işlənən defolt (14 = bandın yuxarı ucu, çünki fail-open
    # prinsipi şübhə halında İŞLƏMƏYƏ DAVAM ETMƏYİ seçir).
    SystemLimitKey.LICENSE_MIN_OFFLINE_GRACE_DAYS: "7",
    SystemLimitKey.LICENSE_MAX_OFFLINE_GRACE_DAYS: "14",
    SystemLimitKey.LICENSE_DEFAULT_OFFLINE_GRACE_DAYS: "14",
    # "[1 Ay Uzat]" = 30 gün.
    SystemLimitKey.LICENSE_EXTENSION_DAYS: "30",
    # 300 saniyə (5 dəqiqə) — NTP düzəlişi/sinxronizasiya bir neçə saniyə geri
    # sıçraya bilər, 5 dəqiqə isə artıq qəsdli dəyişiklikdir.
    SystemLimitKey.LICENSE_CLOCK_ROLLBACK_TOLERANCE_SECONDS: "300",
    # Müddət bitməsinə 7 gün qalanda banner.
    SystemLimitKey.LICENSE_EXPIRY_WARNING_DAYS: "7",
    # Yenilənmə: sutkalıq yoxlama (lisenziya ilə eyni ritm), uğursuzluqdan
    # sonra 2 saat, paket tavanı 512 MB.
    SystemLimitKey.UPDATE_CHECK_INTERVAL_SECONDS: "86400",
    SystemLimitKey.UPDATE_RETRY_INTERVAL_SECONDS: "7200",
    SystemLimitKey.UPDATE_MAX_PACKAGE_BYTES: "536870912",
    # 1C: bir sorğuda 500 sənəd, ad oxşarlığı həddi 0.87 ("Əliyev Elvin" ↔
    # "Aliyev Elvin" keçir, "Əliyev Elnur" keçmir — bax `erp.py`).
    SystemLimitKey.ERP_SYNC_PAGE_SIZE: "500",
    SystemLimitKey.ERP_NAME_MATCH_THRESHOLD: "0.87",
    # İcazə Növü tavanı: 12 saat = 720 dəqiqə (bir iş günü).
    SystemLimitKey.LEAVE_TYPE_MAX_DURATION_MINUTES: "720",
    # Baza keçidi: bufer boşalmasına 5 dəqiqə, texniki fasiləyə 2 saat.
    SystemLimitKey.DB_MIGRATION_DRAIN_TIMEOUT_SECONDS: "300",
    SystemLimitKey.DB_MIGRATION_MAX_WINDOW_MINUTES: "120",
    # Sübut şəkli: siyahıda 320 px, açılışda 1600 px kənar.
    SystemLimitKey.EVIDENCE_THUMBNAIL_MAX_EDGE_PX: "320",
    SystemLimitKey.EVIDENCE_FULL_MAX_EDGE_PX: "1600",
    # --- Faza 10.2 — infrastruktur əməliyyat parametrləri (seed: 032) ------- #
    #
    # HƏR DEFOLT KÖÇÜRÜLƏN HARDCODE DƏYƏRLƏ HƏRFƏN EYNİDİR. Bu, təsadüf deyil,
    # köçürmənin ŞƏRTİDİR: köçürmə davranış dəyişikliyi deyil, idarəolunma
    # dəyişikliyidir. "Yaxşılaşdırılmış" defolt yazsaydıq, mövcud quraşdırma
    # yeniləmədən sonra sükutla başqa cür işləyərdi.
    #
    # `security/hashing.py`. BU AÇAR YUXARIDAKI QAYDANIN YEGANƏ İSTİSNASIDIR
    # və istisna QƏSDLİDİR — köçürmə deyil, sonrakı AÇIQ QƏRARdır:
    #
    # Köçürüləndə dəyər 12 idi (OWASP-ın admin hesabları üçün tövsiyəsi).
    # İlk Quraşdırma Sihirbazı isə məhz burada dayanırdı: istifadəçi admin
    # hesabı yaradır, `WeakSecretError` atılır və nəticə «KompasOS işə düşə
    # bilmədi» ekranı olurdu. Hədd miqrasiya 066 ilə 8-ə endirildi.
    #
    # ZƏİFLƏYƏN YEGANƏ ŞEY UZUNLUQDUR: böyük hərf, kiçik hərf, rəqəm və
    # xüsusi simvol tələbi qüvvədədir (`PasswordPolicy`), aşağı hüdud
    # (`INFRA_LIMIT_BOUNDS`) onsuz da 8 idi, tavan isə 128 olaraq qalır —
    # daha uzun şifrə istəyən müəssisə onu ROOT panelindən qaldırır.
    SystemLimitKey.PASSWORD_MIN_LENGTH: "8",
    # `backup/service.py`: spesifikasiyanın "minimum 30 gün" tələbi həm
    # döşəmə, həm də başlanğıc dəyər kimi; `pg_dump` taymautu 1 saat.
    SystemLimitKey.BACKUP_MIN_RETENTION_DAYS: "30",
    SystemLimitKey.BACKUP_RETENTION_DAYS: "30",
    SystemLimitKey.BACKUP_DUMP_TIMEOUT_SECONDS: "3600",
    # `erp/system_health.py`: 85%/95% disk, 500 ms DB ping.
    SystemLimitKey.HEALTH_DISK_WARNING_PERCENT: "85.0",
    SystemLimitKey.HEALTH_DISK_CRITICAL_PERCENT: "95.0",
    SystemLimitKey.HEALTH_DB_PING_SLOW_MS: "500",
    SystemLimitKey.HEALTH_MEMORY_WARNING_PERCENT: "85.0",
    SystemLimitKey.HEALTH_MEMORY_CRITICAL_PERCENT: "95.0",
    SystemLimitKey.HEALTH_HARDWARE_ALERT_COOLDOWN_HOURS: "12",
    # `storage/quota_monitor.py`: 90% doluluq, 7 günlük təkrar-susma.
    SystemLimitKey.DRIVE_QUOTA_WARNING_RATIO: "0.90",
    SystemLimitKey.DRIVE_QUOTA_WARNING_COOLDOWN_DAYS: "7",
    # `timekeeping/ntp.py`: 5 dəq. dövr, 3 san. taymaut, 30 dəq. nümunə ömrü,
    # 2 san. maksimum gediş-dönüş.
    SystemLimitKey.NTP_POLL_INTERVAL_SECONDS: "300",
    SystemLimitKey.NTP_QUERY_TIMEOUT_SECONDS: "3.0",
    SystemLimitKey.NTP_SAMPLE_TTL_SECONDS: "1800",
    SystemLimitKey.NTP_MAX_ROUND_TRIP_SECONDS: "2.0",
    # `timekeeping/server_time.py`: 5 dəq. sinxronizasiya, 4 saat oflayn
    # etibarlılıq, 60 san. manipulyasiya həddi, bildiriş AÇIQ.
    #
    # 4 SAAT NİYƏ: bir iş növbəsindən qısadır. Növbə ərzində server qayıtmayıbsa
    # həmin günün bütün davamiyyət qeydlərinin vaxtı şübhəlidir və HR bunu
    # növbənin SONUNDA deyil, hələ gün içində görməlidir. Daha uzun dəyər
    # (məs. 24 saat) xəbərdarlığı faydasız dərəcədə gec edərdi.
    SystemLimitKey.SERVER_TIME_SYNC_INTERVAL_SECONDS: "300",
    SystemLimitKey.SERVER_TIME_MAX_OFFLINE_TRUST_SECONDS: "14400",
    SystemLimitKey.LOCAL_CLOCK_MANIPULATION_THRESHOLD_SECONDS: "60",
    SystemLimitKey.LOCAL_CLOCK_MANIPULATION_NOTIFY: "1",
    # `use_cases/device_registry.py`: 25 cihaz həddi, təsdiq MƏCBURİ, 90 gün
    # passivlik. 25 NİYƏ: orta müştəridə (10-15 mağaza × 1-2 PC) rahat yer
    # qoyur, lakin limitsiz deyil — limitsiz dəyər sayğacı mənasız edərdi və
    # lisenziya söhbətini yalnız fakturada üzə çıxarardı.
    SystemLimitKey.MAX_REGISTERED_DEVICES: "25",
    SystemLimitKey.DEVICE_APPROVAL_REQUIRED: "1",
    SystemLimitKey.DEVICE_INACTIVITY_DAYS: "90",
    # `erp/matching.py`, `erp/sync_worker.py`, `erp/one_c_connector.py`.
    SystemLimitKey.ERP_MATCH_AMBIGUITY_MARGIN: "0.05",
    SystemLimitKey.ERP_SYNC_MAX_PARALLEL_SERVERS: "4",
    SystemLimitKey.ERP_SYNC_MAX_PAGES_PER_RUN: "10",
    SystemLimitKey.ERP_REQUEST_TIMEOUT_SECONDS: "30.0",
    SystemLimitKey.ERP_MAX_RETRIES: "3",
    # Fayl mübadiləsi = gündə bir dəfə (86400 san.). 1c.md kartın izahında
    # istifadəçiyə məhz bunu vəd edir ("hər gecə bir dəfə sinxronlaşır") —
    # defolt həmin vədlə eyni olmalıdır, əks halda ekranda yazılan ilə
    # sistemin etdiyi fərqlənərdi.
    SystemLimitKey.ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS: "86400",
    # `kiosk/watchdog.py`: 10 dəqiqədə 5 yenidən başlatma, 2→30 san. gözləmə.
    SystemLimitKey.KIOSK_RESTART_WINDOW_MINUTES: "10",
    SystemLimitKey.KIOSK_MAX_RESTARTS_PER_WINDOW: "5",
    # Vergüllü siyahı naxışı `EMPLOYEE_DOCUMENT_EXPIRY_WARNING_DAYS` ilə
    # eynidir: cədvəlin SIRASI mənalıdır və üç ayrı açar Root-a onu yanlış
    # ardıcıllıqla yazmaq imkanı verərdi.
    SystemLimitKey.KIOSK_RESTART_BACKOFF_SECONDS: "2,4,8,16,30",
    # `licensing/developer_directory.py`: 3 gün = bir uzun həftəsonu + bir iş günü.
    SystemLimitKey.DEVELOPER_DIRECTORY_STALE_DAYS: "3",
    # `notifications/notifier.py`: 25 sətir/dövr, 5 cəhd, 1→240 dəq. gözləmə,
    # 120 san. dövr aralığı.
    SystemLimitKey.NOTIFY_MAX_BATCH_SIZE: "25",
    SystemLimitKey.NOTIFY_MAX_ATTEMPTS: "5",
    SystemLimitKey.NOTIFY_RETRY_BACKOFF_MINUTES: "1,5,15,60,240",
    SystemLimitKey.NOTIFY_POLL_INTERVAL_SECONDS: "120",
    # `notifications/email.py`, `notifications/crash_reporter.py`.
    SystemLimitKey.EMAIL_SMTP_TIMEOUT_SECONDS: "15.0",
    SystemLimitKey.CRASH_MAX_REPORTS_PER_FINGERPRINT: "3",
    # `realtime/channel.py`: 30 san. polling, 5→60 san. yenidən-qoşulma.
    SystemLimitKey.REALTIME_POLL_INTERVAL_SECONDS: "30",
    SystemLimitKey.REALTIME_RECONNECT_BACKOFF_SECONDS: "5,15,30,60",
    # `offline/sync.py`, `offline/buffer.py` (spesifikasiya bölmə 5: 30s→2dq→10dq).
    SystemLimitKey.OFFLINE_SYNC_BATCH_SIZE: "100",
    SystemLimitKey.OFFLINE_RETRY_BACKOFF_SECONDS: "30,120,600",
    SystemLimitKey.OFFLINE_SQLITE_TIMEOUT_SECONDS: "10.0",
    # Faza 5.1 — 24 saat / 500 sətir. Bir iş günü (növbə + gecə) şəbəkəsiz
    # keçə bilər və bu, hələ nasazlıq deyil; İKİNCİ gün artıq nasazlıqdır.
    # 500 sətir isə bir mağazanın normal günlük yazı həcminin (davamiyyət +
    # cərimə + fasilə ≈ 100-150 sətir) təxminən dörd qatıdır.
    SystemLimitKey.OFFLINE_BACKLOG_MAX_HOURS: "24",
    SystemLimitKey.OFFLINE_BACKLOG_MAX_ENTRIES: "500",
    SystemLimitKey.OFFLINE_BACKLOG_WARNING_COOLDOWN_HOURS: "12",
    # `persistence/connection.py`: hovuz 1–8, 15 san. bağlantı taymautu.
    SystemLimitKey.DB_POOL_MIN_SIZE: "1",
    SystemLimitKey.DB_POOL_MAX_SIZE: "8",
    SystemLimitKey.DB_CONNECT_TIMEOUT_SECONDS: "15.0",
    # `storage/drive_api.py`, `storage/oauth_flow.py`, `storage/google_drive.py`,
    # `storage/upload_queue.py`.
    SystemLimitKey.DRIVE_TOKEN_REFRESH_MARGIN_SECONDS: "60",
    SystemLimitKey.DRIVE_REQUEST_TIMEOUT_SECONDS: "30.0",
    SystemLimitKey.DRIVE_MAX_RETRIES: "3",
    SystemLimitKey.DRIVE_OAUTH_FLOW_TIMEOUT_SECONDS: "300.0",
    SystemLimitKey.EVIDENCE_JPEG_QUALITY: "85",
    SystemLimitKey.UPLOAD_CLAIM_STALE_AFTER_SECONDS: "600",
    # `storage/image_cache.py`: 30 gün (saniyə ilə), 256 MB.
    SystemLimitKey.IMAGE_CACHE_TTL_SECONDS: "2592000",
    SystemLimitKey.IMAGE_CACHE_MAX_BYTES: "268435456",
    # `plugins/sandbox.py`: 10 san. icra, 1 MB çıxış.
    SystemLimitKey.PLUGIN_SANDBOX_TIMEOUT_SECONDS: "10.0",
    SystemLimitKey.PLUGIN_SANDBOX_MAX_OUTPUT_BYTES: "1048576",
    # `updates/verification.py`, `updates/publisher.py`, `updates/catalog.py`.
    SystemLimitKey.UPDATE_VERIFY_TIMEOUT_SECONDS: "60.0",
    SystemLimitKey.UPDATE_UPLOAD_TIMEOUT_SECONDS: "600.0",
    SystemLimitKey.UPDATE_DOWNLOAD_TIMEOUT_SECONDS: "300.0",
    SystemLimitKey.UPDATE_SIGNED_URL_TTL_SECONDS: "3600",
    SystemLimitKey.UPDATE_CATALOG_FETCH_LIMIT: "20",
    # --- Faza 10.2 — tətbiq qatının parametrləri (seed: 034) ---------------- #
    #
    # HƏR DEFOLT KÖÇÜRÜLƏN HARDCODE İLƏ HƏRFƏN EYNİDİR — köçürmə davranış
    # dəyişikliyi deyil, idarəolunma dəyişikliyidir.
    #
    # `developer_console.py`: 24 saat ilk cavab, 72 saat həll, son 25% risk
    # zolağı, 3 quraşdırma "kütləvi", panelin ilk 10 qrupu.
    SystemLimitKey.SUPPORT_FIRST_RESPONSE_SLA_HOURS: "24",
    SystemLimitKey.SUPPORT_RESOLUTION_SLA_HOURS: "72",
    SystemLimitKey.SUPPORT_SLA_AT_RISK_RATIO: "0.75",
    SystemLimitKey.CRASH_WIDESPREAD_INSTALLATION_THRESHOLD: "3",
    SystemLimitKey.CRASH_DASHBOARD_TOP_LIMIT: "10",
    # `shift_scheduling.py`: sorğu ən çox 90 gün irəli üçün.
    SystemLimitKey.SHIFT_SWAP_MAX_LEAD_DAYS: "90",
    # `payment_reminders.py`: T-7, T-3, T-1, T+1, T+7 (modul başlığındakı
    # cədvəlin ÖZÜ — mənfi = bitmədən əvvəl, müsbət = sonra).
    SystemLimitKey.LICENSE_PAYMENT_REMINDER_OFFSET_DAYS: "-7,-3,-1,1,7",
    # Səhifə ölçüləri: şübhəli satış növbəsi 200, audit jurnalı 500/100,
    # ehtiyat nüsxə tarixçəsi 60, elan siyahısı 50, dəstək mövzuları 20,
    # sinxronizasiya konfliktləri 100.
    SystemLimitKey.SALES_REVIEW_QUEUE_PAGE_SIZE: "200",
    SystemLimitKey.AUDIT_LOG_MAX_PAGE_SIZE: "500",
    SystemLimitKey.AUDIT_LOG_DEFAULT_PAGE_SIZE: "100",
    SystemLimitKey.BACKUP_HISTORY_PAGE_SIZE: "60",
    SystemLimitKey.ANNOUNCEMENT_LIST_PAGE_SIZE: "50",
    SystemLimitKey.SUPPORT_THREAD_PAGE_SIZE: "20",
    # Defolt `HAMISI`: bot yeni qoşulanda susmaq ən pis başlanğıcdır —
    # hazırlayıcı bildirişin gəlmədiyini yalnız gecikmiş şikayətdən bilərdi.
    SystemLimitKey.TELEGRAM_NOTIFY_MODE: "HAMISI",
    # Mağaza internetinin zəif olduğu hallar üçün geniş, lakin sonsuz
    # olmayan pəncərə: bildiriş göndərmək işçinin gözlədiyi əməliyyat
    # DEYİL, ona görə 15 saniyə mesajın yazılmasını gecikdirmir.
    SystemLimitKey.TELEGRAM_REQUEST_TIMEOUT_SECONDS: "15",
    # Cavab yoxlaması: 20 saniyə insan söhbətində hiss olunmur,
    # Telegram-ın sorğu həddindən isə çox uzaqdır.
    SystemLimitKey.TELEGRAM_POLL_INTERVAL_SECONDS: "20",
    # 3 gün: iş həftəsinin içində işçinin etiraz etməyə imkanı olur,
    # növbə isə həll olunmuş müraciətlərlə dolub qalmır.
    SystemLimitKey.SUPPORT_AUTO_CLOSE_DAYS: "3",
    # 2 gün: bir iş günü + ehtiyat. Daha qısası növbətçi olmayan
    # işçini istirahət günündə xatırlatma ilə narahat edərdi.
    SystemLimitKey.SUPPORT_WAITING_REMINDER_DAYS: "2",
    SystemLimitKey.SYNC_CONFLICT_PAGE_SIZE: "100",
    # Defolt dəyər KÖÇÜRMƏDƏN ƏVVƏLKİ sabitlə eynidir (50): köçürmə davranışı
    # dəyişdirmir, yalnız dəyəri Root-un əli çatan yerə gətirir.
    SystemLimitKey.SHIFT_SWAP_HISTORY_PAGE_SIZE: "50",
    SystemLimitKey.FINE_APPEAL_HISTORY_PAGE_SIZE: "50",
    # `first_run_setup.py`: bölmə 2 tövsiyəsi — ən azı iki admin.
    SystemLimitKey.SETUP_RECOMMENDED_ADMIN_COUNT: "2",
    # `controllers/screen_data.py`: növbə matrisi 14 günlük pəncərə göstərir.
    SystemLimitKey.SHIFT_MATRIX_WINDOW_DAYS: "14",
    # `presentation/app.py`: sübut növbəsi 2 dəqiqədən bir boşaldılır. Sabit
    # MİLLİSANİYƏ ilə yazılmışdı (120_000); açar SANİYƏ ilədir — `NOTIFY_`/
    # `REALTIME_POLL_INTERVAL_SECONDS` ilə eyni vahid olsun deyə (Root eyni
    # panelde iki fərqli vahidlə üzləşməməlidir). 120 san = 120_000 ms.
    SystemLimitKey.EVIDENCE_UPLOAD_POLL_INTERVAL_SECONDS: "120",
    # SAAS-6 — 30 gün. Ədəd MƏLUMAT İTKİSİ RİSKİ DAŞIMIR və məhz ona görə bu
    # qədər qısadır: `UPLOADED` statusuna çatmış sətir o deməkdir ki, şəkil
    # ARTIQ Google Drive-dadır (`fines.evidence_reference` ona işarə edir) —
    # lokal SQLite sətri həmin andan etibarən yalnız DİAQNOSTİKA izidir
    # («bu şəkil nə vaxt, neçə cəhddən sonra yükləndi?»). Eyni məntiq həll
    # edilmiş sinxronizasiya münaqişəsinə də aiddir: qərar artıq bazadadır,
    # lokal sətir yalnız izdir.
    #
    # NİYƏ SIFIR DEYİL (dərhal silmə): şəbəkə problemi olan filialda
    # araşdırma adətən həmin gün YOX, həftələr sonra — mühasibat ayı
    # bağlayanda başlayır. Bir tam aylıq pəncərə həmin sualın cavabını
    # saxlayır. NİYƏ 365 DEYİL: `%PROGRAMDATA%` altındakı fayl kiosk
    # maşınının diskindədir və illərlə yığılan iz orada real yer tutur;
    # DAİMİ sübut onsuz da Drive-dadır, lokal nüsxə onun əvəzi deyil.
    #
    # Root bunu dəyişə bilər — həqiqi hüdudlar `INFRA_LIMIT_BOUNDS`-dadır.
    SystemLimitKey.EVIDENCE_UPLOAD_RETENTION_DAYS: "30",
    # UX-7 — 7 gün. Qeydiyyat SELF-SERVICE DEYİL (`facecontrol.md` bənd 1):
    # işçi onu ÖZÜ edə bilmir, admin ilə üzbəüz görüş lazımdır. Bir iş
    # həftəsi həmin görüşün təbii ölçüsüdür — yeni işçi onsuz da birinci
    # həftədə sənəd, forma və təlimat üçün adminlə görüşür.
    # Sıfır seçilsəydi hər yeni işçi elə işə başladığı gün istisna doğurardı;
    # 30 seçilsəydi «Sonra» düyməsi bir ay ərzində sərbəst basıla bilərdi və
    # UX-7-nin şikayət etdiyi hal (əbədi təxirə salma) davam edərdi.
    SystemLimitKey.FACE_ENROLLMENT_GRACE_DAYS: "7",
    # `screens/group_f.py`: 50%-dən aşağı uyğunluq xəbərdarlıq rəngindədir.
    SystemLimitKey.ERP_MATCH_LOW_CONFIDENCE_PERCENT: "50",
    # `developer_panel/ui.py`: hər iki diaqnostika cədvəli 12 sətir göstərir.
    SystemLimitKey.DEVELOPER_CRASH_ROW_LIMIT: "12",
    SystemLimitKey.DEVELOPER_TICKET_ROW_LIMIT: "12",
    # --- Faza 11 — planlanmış iş planlayıcısı (seed: 036) ------------------- #
    #
    # `job_runner.py` HEÇ BİR SABİT ƏDƏD saxlamır: fallback məhz bu sətirlərdir
    # (`JobRunner._limit_int` → `DEFAULT_LIMITS[key]`). Yəni parametrin tək
    # mənbəyi `system_limits`, tək ehtiyatı isə bu lüğətdir.
    #
    # 15 dəqiqə: gecikmiş gecə işi ən pis halda 15 dəqiqə gec tutulur —
    # masaüstü tətbiq üçün görünməz gecikmə, lakin dövrə hər gün cəmi ~96
    # yüngül yoxlama edir.
    SystemLimitKey.SCHEDULER_POLL_INTERVAL_MINUTES: "15",
    # 03: mağazalar bağlıdır, 1C sinxronizasiyası bitib — ehtiyat nüsxə və
    # yenidən-hesablama üçün ən sakit saat. DB-nin ÖZ cron işləri ilə
    # (`docs/scheduler_setup.md`, hər 5 dəqiqə) qarışdırılmamalıdır: onlar
    # eskalasiya/təmizlik işləridir və bu parametrə TABE DEYİL.
    SystemLimitKey.SCHEDULER_NIGHTLY_HOUR: "3",
    # 30 dəqiqə: ən uzun işin (`pg_dump`) taymautu 1 saatdır, lakin normal
    # icrası dəqiqələrlədir. 30 dəqiqə çökmüş terminalın işini eyni gecə
    # içində geri qaytarmağa imkan verir və normal icranı kəsmir.
    SystemLimitKey.SCHEDULER_LEASE_MINUTES: "30",
    # 3 cəhd: müvəqqəti nasazlıq (şəbəkə, kilid) adətən ikinci cəhddə keçir;
    # üçüncüdən sonra problem struktur olur və təkrar yalnız log doldurur.
    SystemLimitKey.SCHEDULER_MAX_ATTEMPTS: "3",
    # --- #26+#27 sahə hesabatları (seed: 039) ------------------------------- #
    #
    # 30 gün: aylıq mağaza ziyarəti pərakəndə şəbəkələrin standart ritmidir və
    # təqvim ayı ilə üst-üstə düşür — menecer "bu ay getdimmi?" sualını
    # təqvimə baxaraq cavablandıra bilir.
    SystemLimitKey.FIELD_REPORT_AUDIT_INTERVAL_DAYS: "30",
    # 10 şəkil: bir mağaza ziyarətində problemli nöqtələrin sayı praktikada
    # birrəqəmlidir; 10 rahat başlıqdır, lakin dövrəyə düşmüş yükləməni kəsir.
    SystemLimitKey.FIELD_REPORT_MAX_PHOTOS: "10",
    # 10 simvol: "ok"/"pisdir" kimi cavab nə tapşırıq mətni qura bilər, nə də
    # mübahisədə əsas olar. Sxem döşəməsi (5) qəsdən daha aşağıdır — o, yalnız
    # absurd sətri kəsir (bax `FieldReport.__init__`).
    SystemLimitKey.FIELD_REPORT_MIN_DETAIL_LENGTH: "10",
    # 3 gün: uğursuz BLOKLAYICI bənd (yanğın çıxışı, kassa intizamı) dərhal
    # düzəldilməlidir; 3 gün həftəsonu düşən auditə də real möhlət verir.
    SystemLimitKey.FIELD_REPORT_TASK_DEADLINE_DAYS: "3",
    # `MAGAZA_MENECERI`: sistem rol kataloqundakı (`schema.sql` §21) mağaza
    # rəhbəri. O, `can_assign_tasks`/`can_approve_task_evidence` daşıyır
    # (§23), yəni tapşırıq axını onun üçün onsuz da açıqdır.
    SystemLimitKey.FIELD_REPORT_TASK_ASSIGNEE_ROLE: "MAGAZA_MENECERI",
    # --- #28 illik məzuniyyət balansı (seed: 040) --------------------------- #
    #
    # `domain/annual_leave_rules.py` HEÇ BİR SABİT ƏDƏD saxlamır: `AnnualLeave
    # Policy.defaults()` məhz bu sətirləri oxuyur (`AttritionWeights.defaults()`
    # ilə eyni naxış). Yəni parametrin tək mənbəyi `system_limits`, tək
    # ehtiyatı isə bu lüğətdir.
    #
    # 21 gün: Azərbaycan Əmək Məcəlləsinin əsas məzuniyyət minimumu. Defolt
    # qanunun ÖZÜ seçilib ki, konfiqurasiya edilməmiş quraşdırma da hüquqi
    # cəhətdən düzgün rəqəm göstərsin.
    SystemLimitKey.ANNUAL_LEAVE_BASE_ENTITLEMENT_DAYS: "21.00",
    # "Hər 5 ildə 1 əlavə gün, ən çoxu 5 gün" — yayılmış staj cədvəli. Üç ədəd
    # də ROOT-dadır, çünki qaydanın FORMASI (dövrün uzunluğu, addımın böyüklüyü,
    # tavan) şirkətdən şirkətə dəyişir.
    SystemLimitKey.ANNUAL_LEAVE_SENIORITY_PERIOD_YEARS: "5",
    SystemLimitKey.ANNUAL_LEAVE_SENIORITY_BONUS_DAYS: "1.00",
    SystemLimitKey.ANNUAL_LEAVE_SENIORITY_BONUS_MAX_DAYS: "5.00",
    # 5 gün köçürmə: işçinin ilin sonunda "yandırmaq üçün" məzuniyyət götürmək
    # məcburiyyətini yumşaldır, lakin illərlə yığılan öhdəlik (istifadə
    # edilməmiş gün PUL dəyəri daşıyır) yaratmır.
    SystemLimitKey.ANNUAL_LEAVE_CARRYOVER_MAX_DAYS: "5.00",
    # 31 mart: köçürülmüş günlərin son istifadə tarixi — birinci rübün sonu.
    # Ay və gün AYRI açardır (bax `SystemLimitKey` şərhi).
    SystemLimitKey.ANNUAL_LEAVE_CARRYOVER_DEADLINE_MONTH: "3",
    SystemLimitKey.ANNUAL_LEAVE_CARRYOVER_DEADLINE_DAY: "31",
    # `ANNUAL`: haqq ilin əvvəlində TAM verilir (işə yeni düşən üçün işə qəbul
    # tarixinə görə proporsional). Bu, İşçi Ana Ekranındakı "14/21 gün qalıb"
    # kartının gözlədiyi modeldir — aylıq toplanan modeldə həmin kart ilin
    # əvvəlində "0/1.75" göstərərdi və işçi məzuniyyət planlaya bilməzdi.
    SystemLimitKey.ANNUAL_LEAVE_ACCRUAL_PERIOD: "ANNUAL",
    # `0` = dərəcəni illik haqqdan törət (bax `SystemLimitKey` şərhi).
    SystemLimitKey.ANNUAL_LEAVE_ACCRUAL_RATE_DAYS_PER_PERIOD: "0.00",
    # `WORKING_DAYS`: balansdan yalnız İŞ günləri çıxılır — istirahət günü
    # Shift Matrix-dən oxunur (migrations/037 `deducted_days` şərhi).
    SystemLimitKey.ANNUAL_LEAVE_DAY_COUNT_MODE: "WORKING_DAYS",
    # --- #29 toplu əməliyyatlar (seed: 041) ----------------------------------- #
    #
    # 300 sətir: bir mağaza şəbəkəsinin illik işə-qəbul dalğası (yeni filial +
    # mövsümi işçi) praktikada bundan az olur; tavan REVOKE-DELETE audit
    # cədvəlinin yükünü YÜKLƏMƏ ANINDA kəsən qoruyucudur, gündəlik norma deyil.
    SystemLimitKey.BULK_IMPORT_MAX_ROWS: "300",
    # 50 sətir: ekranın bir səhifədə rahat oxuna bilən xəta siyahısı. Aqreqat
    # say (`error_count`) tavan aşılsa belə TAM göstərilir — yalnız sətir-sətir
    # DETAL siyahısı kəsilir.
    SystemLimitKey.BULK_IMPORT_PREVIEW_ERROR_LIMIT: "50",
    # --- #30 İcra xülasəsi (seed: 042) ---------------------------------------- #
    #
    # `DAILY`: gündəlik ritm ən "təhlükəsiz" defoltdur — Root heç nə seçməsə
    # belə, ilk konfiqurasiya sükutla AYLARLA gecikməz (`WEEKLY`/`MONTHLY`
    # defolt olsaydı, ilk göndəriş bir həftə/ay gözləyərdi).
    SystemLimitKey.EXECUTIVE_DIGEST_DEFAULT_FREQUENCY: "DAILY",
    # Beş açar — `kompas1.md`-nin açıq nümunələri (cərimə-sayı, açıq-istisna-
    # sayı, gecikən-check-in-sayı) VƏ mövcud use case-lərdə ARTIQ hesablanan
    # iki əlavə göstərici (overtime, turnover — `multi_store_benchmark.py`
    # provayderindən BİRBAŞA, YENİ hesablama YOXDUR).
    SystemLimitKey.EXECUTIVE_DIGEST_METRIC_CATALOG: (
        "FINE_COUNT,OPEN_EXCEPTION_COUNT,LATE_CHECK_IN_COUNT,OVERTIME_HOURS,TURNOVER_RISK"
    ),
    # 1 = Bazar ertəsi: iş həftəsinin İLK günü — həftəlik xülasə keçən HƏFTƏNİ
    # (bazar ertəsindən əvvəlki 7 gün) yekunlaşdıraraq iş həftəsinin başında
    # göndərilir, iş həftəsinin ORTASINDA yox.
    SystemLimitKey.EXECUTIVE_DIGEST_WEEKLY_WEEKDAY: "1",
    # --- Faza 7 Hesabat aralığı (seed: 043) ----------------------------------- #
    #
    # 366 gün = bir SƏNƏD ili (uzun il daxil). Defolt məhz bu rəqəmdir, çünki
    # HR-in ən uzun qanuni sorğusu «illik yekun»dur; ondan uzun aralıq isə
    # hesabat deyil, ARXİV sorğusudur və onun yeri Developer Panelidir.
    # Tam-ay yolu bu hədddən HEÇ VAXT təsirlənmir (31 ≤ 366).
    SystemLimitKey.REPORT_RANGE_MAX_DAYS: "366",
    # --- Faza 8 Export təcrübəsi (seed: 044) ---------------------------------- #
    #
    # 15%: bir mağazada planlaşdırılmış hər 100 iş günündən 15-i icazəsiz qayıb
    # deməkdir — bu, artıq fərdi hadisə deyil, İDARƏETMƏ problemidir və HR-in
    # export-dan ƏVVƏL baxmalı olduğu siqnaldır. Defolt qəsdən "yumşaqdır":
    # sərt defolt (məs. 5%) ilk aydan onlarla yalançı siqnal verər və ekran
    # etibarını itirərdi.
    SystemLimitKey.EXPORT_STORE_ABSENCE_ANOMALY_PCT: "15.0",
    # 3 işçi — `BEHAVIOR_BASELINE_MIN_SAMPLE_SIZE` (5 gün) ilə eyni fəlsəfə:
    # bundan az müşahidə ilə "mağaza anomaliyası" demək statistik cəhətdən
    # əsassızdır. 3 nəfər bir növbənin minimum heyətidir.
    SystemLimitKey.EXPORT_STORE_ANOMALY_MIN_EMPLOYEES: "3",
    # 3 hadisə: keçən dövrlə müqayisədə ±1/±2 fərq adi dalğalanmadır (bir
    # xəstəlik, bir növbə dəyişikliyi), ±3 isə artıq meyldir. kompas1.md-nin
    # öz nümunəsi də məhz "+3"-dür.
    SystemLimitKey.EXPORT_PERIOD_DELTA_SIGNIFICANT: "3",
    # 10 simvol — `EXCEPTION_REVIEW_NOTE_MIN_LENGTH` və `FineAppeal` ilə EYNİ
    # dəyər; həm də `export_manual_corrections.reason` CHECK-inin döşəməsi ilə
    # üst-üstə düşür, yəni defolt halda kod və DB eyni cavabı verir.
    SystemLimitKey.EXPORT_CORRECTION_REASON_MIN_LENGTH: "10",
    # --- Nahar / Çay fasiləsi (seed: 045) ------------------------------------ #
    #
    # 60 dəqiqə: `schema.sql` §24 hər kirayəçiyə «Nahar Fasiləsi» icazə növünü
    # məhz 60 dəqiqə ilə seed edir. nahar.md 45 təklif edir, lakin İKİ ədədin
    # ilk gündən fərqlənməsi işçidə "hansı doğrudur?" sualı yaradardı —
    # informativ göstərici ilə BR-001 güzəşti eyni başlanğıc nöqtəsindən
    # ayrılmalıdır. Fərqləndirmək AÇIQ Root qərarı olmalıdır, defolt yox.
    SystemLimitKey.LUNCH_BREAK_DURATION_MINUTES: "60",
    # 1 dəfə: nahar bir iş günündə bir dəfədir — bu, mağaza praktikasının özü
    # qədər sabitdir. Aşılma yenə də bloklanmır, sadəcə görünür.
    SystemLimitKey.LUNCH_BREAK_DAILY_COUNT: "1",
    # 15 dəqiqə / 2 dəfə: qısa fasilənin standart forması (səhər və günorta).
    # «Çay Fasiləsi» icazə növü migrations/045-də məhz 15 dəqiqə ilə yaranır,
    # yəni burada da eyni cüt saxlanılır.
    SystemLimitKey.TEA_BREAK_DURATION_MINUTES: "15",
    SystemLimitKey.TEA_BREAK_DAILY_COUNT: "2",
    # --- Face Control (seed: 047) -------------------------------------------- #
    #
    # ⚠️ AŞAĞIDAKI HƏDDLƏR İLKİN DƏYƏRLƏRDİR, "DÜZGÜN" DEYİL.
    # `facecontrol.md`-nin açıq göstərişi: bənzərlik və aşağı-etibar həddinin
    # doğru ədədini indi TƏXMİN ETMƏYƏ ÇALIŞMA — kitabxananın sənədləşdirilmiş
    # defoltunu götür və pilot mağazada real şəraitdə tənzimlə. Bu, kod
    # problemi deyil, empirik/əməliyyat qərarıdır.
    #
    # 0.50 — kadr keyfiyyətinin ORTA nöqtəsi. Sərt defolt (məs. 0.80) ilk gündən
    # enrollment-i mümkünsüz edərdi (mağaza veb-kameraları zəifdir), yumşaq
    # defolt (0.20) isə yoxlamanı faktiki olaraq söndürərdi.
    SystemLimitKey.FACE_ENROLLMENT_MIN_QUALITY: "0.50",
    # 5 kadr — İLKİN DƏYƏRDİR, "düzgün" ədəd DEYİL və PİLOT MAĞAZADA
    # TƏNZİMLƏNMƏLİDİR (yuxarıdakı xəbərdarlıq bu açara da aiddir). Seçimin
    # məntiqi: üç kadr bir uğursuz kadrdan sonra ortanı iki kadra endirir
    # (yəni tək-kadr xətasına yaxınlaşır), on kadr isə operatoru və işçini
    # kamera qarşısında lazımsız gözlədir. Beş kadr ikisi rədd edilsə belə
    # üç keçən kadr saxlayır.
    SystemLimitKey.FACE_ENROLLMENT_FRAME_COUNT: "5",
    # 3 — PIN-in 5-indən AŞAĞI. Üç ardıcıl uyğunsuzluq artıq təsadüf deyil;
    # PIN-də isə beş cəhd insanın rəqəmi unutmasına verilən qanuni ehtiyatdır.
    SystemLimitKey.FACE_MISMATCH_LOCKOUT_THRESHOLD: "3",
    # Üç hərəkətin hamısı defolt AKTİVDİR: randomlaşdırmanın dəyəri seçim
    # hovuzunun ölçüsündədir — iki hərəkətlə hovuz yarıya enir və video-təkrar
    # hücumu üçün təxmin etmək asanlaşır.
    SystemLimitKey.FACE_LIVENESS_ACTIONS: "BLINK,HEAD_TURN,SMILE",
    # 0.60 — `face_recognition` (Dlib) sənədləşməsindəki defolt `tolerance`.
    # Ədəd QƏSDƏN "yaxşılaşdırılmır": kitabxananın öz tövsiyəsindən sapmaq
    # üçün ölçmə lazımdır, ölçmə isə pilotdan sonra olacaq.
    SystemLimitKey.FACE_MATCH_TOLERANCE: "0.60",
    # 0.50 — bənzərlik həddindən bir addım sərt. Aradakı zolaq (0.50–0.60)
    # "aşağı-etibarlı təsdiq"dir. Zolağın ENİ də pilotda tənzimlənəcək; sıfır
    # enli zolaq (iki həddin bərabərliyi) bənd 12-ni söndürərdi.
    SystemLimitKey.FACE_LOW_CONFIDENCE_TOLERANCE: "0.50",
    # 12 ay — üzün gözlə görünən dəyişməsi (saqqal, eynək, çəki) üçün praktik
    # dövr. Daha qısa interval xatırlatmanı fona çevirər və admin ona
    # baxmamağa öyrəşərdi.
    SystemLimitKey.FACE_REENROLLMENT_REMINDER_MONTHS: "12",
    # 90 gün — `facecontrol.md` bənd 14-ün öz nümunəsi. Bir rüb tibbi/fiziki
    # halın həll olunması üçün kifayətdir və yenidən əsaslandırma tələbini
    # formal prosedura çevirmir.
    SystemLimitKey.FACE_EXEMPTION_MAX_DAYS: "90",
    # 12 ay — bənd 17-nin öz defoltu. Davranış baseline-ı yalnız son 30 günə
    # baxdığı üçün konflikt yoxdur (bənd 17-nin təhlükəsizlik təsdiqi).
    SystemLimitKey.FACE_VERIFICATION_LOG_RETENTION_MONTHS: "12",
    # 5 saniyə — kioskda insanın gözləməyə hazır olduğu praktik hədd. Bu, bir
    # PERFORMANS siqnalıdır: aşılma heç nəyi bloklamır və heç bir keyfiyyət
    # parametrini zəiflətmir, yalnız System Health Monitor-a yazılır.
    SystemLimitKey.FACE_VERIFICATION_MAX_SECONDS: "5",
    # 3 — spesifikasiyanın öz ədədi ("3-dən çox mağazası varsa seçim olsun").
    # Defolt DAVRANIŞI DƏYİŞMİR: 1–3 mağazalı operator süzgəci əvvəlki kimi
    # GÖRMÜR, çünki üç sətirlik siyahını süzmək lazım deyil.
    SystemLimitKey.CAMERA_QUEUE_STORE_FILTER_THRESHOLD: "3",
    # 2 sütun — mövcud İdarə Paneli maketinin faktiki düzülüşü (qrafik + ölçən,
    # liderlər + serverlər yan-yana). Defolt 1 seçilsəydi, şəbəkə funksiyası
    # ilk gündən görünməz qalardı; 3+ isə 1280px minimum pəncərədə kartları
    # 380px-dən dar edərdi (başlıqlar kəsilir).
    SystemLimitKey.DASHBOARD_GRID_COLUMNS: "2",
    # SEC-011 sənədləşdirilmiş tövsiyə (schema.sql §17b COMMENT-i) — bax
    # `SystemLimitKey`-dəki üç açarın şərhi.
    SystemLimitKey.ADMIN_PANEL_SESSION_IDLE_TIMEOUT_MINUTES: "30",
    SystemLimitKey.ADMIN_PANEL_SESSION_ABSOLUTE_TIMEOUT_HOURS: "8",
    SystemLimitKey.CAMERA_DASHBOARD_SESSION_ABSOLUTE_TIMEOUT_HOURS: "12",
    # SEC-01 dövrə 3-4: BU, YALNIZ FALLBACK-dir — həqiqi mənbə
    # `system_limits`-dir (CLAUDE.md §5), infra-nın seed miqrasiyası (075)
    # ilə HƏRFƏN EYNİ dəyər saxlanmalıdır (dövrə 4-də bir dəfə uyğunsuzluq
    # tapılıb düzəldilib: burada "10" idi, miqrasiyada "15" — DB-2 auditinin
    # xəbərdarlıq etdiyi eyni qüsur sinfi).
    #
    # `20` səhv/`15` dəqiqə: sayğac artıq SABİT-PƏNCƏRƏ modelindədir
    # (`TerminalPinThrottle.advance_after_failure`, uğurda SIFIRLANMIR) —
    # ona görə həddin özü aqreqat TAM pəncərəni tutmalıdır: növbə dəyişimi
    # (30 işçi 10 dəqiqə ərzində PIN yazır) adi typo axınından yalançı
    # bloklanma yaratmamalıdır. `20/15` hücumçunu ~1.3 cəhd/dəqiqə sürətinə
    # salır — fiziki iştirak tələb edən 10⁴-lük PIN fəzasında praktiki
    # taramanı mümkünsüz edir, hər cəhd isə audit-ə düşür. `15` dəqiqə İŞÇİ-
    # BAŞINA lockout müddəti (`PIN_LOCKOUT_MINUTES`) ilə EYNİDİR — bu alt-
    # sistemdə artıq QƏBUL EDİLMİŞ "soyuma müddəti" ölçüsüdür.
    SystemLimitKey.KIOSK_STORE_PIN_MAX_FAILED_ATTEMPTS: "20",
    SystemLimitKey.KIOSK_STORE_PIN_LOCKOUT_MINUTES: "15",
    # Defolt "1" (sayılır) — `OUTSIDE` (qısa fasilə/icazə zamanı mağazadan
    # kənarda olmaq) onsuz da `counts_as_worked=True`-dir (bax
    # `AutoAttendanceStatus`); illik məzuniyyətin defolt istiqaməti onunla
    # eynidir ki, ödənişli məzuniyyət götürən işçi sayğacda "sanki işləməyib"
    # görünməsin. Root bunu "0"-a endirərsə sayğac YALNIZ fiziki iş günlərini
    # göstərər (ekran etiketi bundan asılı deyil — həmişə "🟣 Məzuniyyətdə").
    SystemLimitKey.ANNUAL_LEAVE_COUNTS_AS_WORKED_DAY: "1",
    # HR Lifecycle v2 (Faza 3.2) — 24 ay. `v2backlog.md`-nin özü konkret ay
    # sayı vermir; 2 il HR sənədləşdirmə/əmək mübahisəsi müddətlərində (əmək
    # kodeksi iddia müddətləri) tipik minimum kimi qəbul edilib. Root
    # sahədən sahəyə (yurisdiksiyadan asılı) fərqli müddət tələb edə bilər.
    SystemLimitKey.FORMER_EMPLOYEE_DATA_RETENTION_MONTHS: "24",
    # HR Lifecycle v2 (Faza 3.5) — 50 xal. Konkret ədəd spesifikasiyada
    # verilmir; `SalesPointsUseCase`-in orta bir satışdan qazandırdığı xal
    # dərəcəsi ilə eyni miqyasda (`SALES_POINTS_CURRENCY_PER_POINT`) başlanğıc
    # nöqtəsi kimi seçilib — Root öz kampaniyasına görə dəyişdirir.
    SystemLimitKey.EMPLOYEE_REFERRAL_BONUS_POINTS: "50",
    # HR Lifecycle v2 (Faza 4.2) — 30 gündə ən çox 3 öz-düzəliş sorğusu.
    # Konkret ədədlər spesifikasiyada verilmir; ayda təxminən bir-iki real
    # uyğunsuzluq gözlənilən tezlikdir (kamera/PIN naminə üz uyğunsuzluğu
    # tez-tez BAŞ VERMİR — bax `face_control.py` MISMATCH_LOOKBACK_DAYS=7),
    # 3/30 gün bu tezliyin bir neçə qat üstündə, LAKİN sui-istifadəni
    # (gündə neçə dəfə eyni bəhanəni sınamaq) əngəlləyən tavandır.
    SystemLimitKey.SELF_CORRECTION_REQUEST_WINDOW_DAYS: "30",
    SystemLimitKey.SELF_CORRECTION_REQUEST_MAX_COUNT: "3",
    # Faza 5.3 — 1000 simvol / 12 saat. 1000 simvol bir ekran mətnidir
    # (`FIELD_REPORT_NOTE_MAX_CHARS` ilə eyni miqyas); 12 saat isə tipik
    # növbə uzunluğudur — bundan sonra qeyd KÖHNƏDİR və növbəti-növbəti
    # işçini yanılda bilər.
    SystemLimitKey.SHIFT_HANDOFF_NOTE_MAX_CHARS: "1000",
    SystemLimitKey.SHIFT_HANDOFF_VISIBILITY_HOURS: "12",
    # Faza 5.4 — 120 dəqiqə / 30 dəqiqə / ayda 2 dəfə.
    # 120 dəq.: fövqəladə hal həll etmək üçün bir iş seansıdır, bir GÜN yox.
    # 30 dəq.: ikinci şəxs telefonla çağırılır — bu, cavab vermək üçün real
    # pəncərədir, `DUAL_CONTROL_APPROVAL_TIMEOUT_MINUTES`-in 480 dəqiqəsi isə
    # burada TƏHLÜKƏLİDİR (unudulmuş sorğu gecə təsdiqlənə bilərdi).
    # 2 dəfə/ay: Root-un əlçatmazlığı NADİR hadisədir; üçüncü dəfə sistemin
    # özündə problem var deməkdir və o, break-glass ilə həll olunmur.
    SystemLimitKey.BREAK_GLASS_MAX_DURATION_MINUTES: "120",
    SystemLimitKey.BREAK_GLASS_APPROVAL_WINDOW_MINUTES: "30",
    SystemLimitKey.BREAK_GLASS_MAX_GRANTS_PER_MONTH: "2",
    # v2backlog.md Faza 6.5 — «əhəmiyyətli fərq» həddi (bax SystemLimitKey
    # şərhi). Aralıq migrations/102-də: 1..60.
    SystemLimitKey.WORKLOAD_FAIRNESS_MAX_GAP: "4",
    # v2backlog.md Faza 7 — davranış-cüt açarları (bax SystemLimitKey şərhi).
    # Aralıqlar migrations/103-də: 50..100, 3..60, 1..120.
    SystemLimitKey.BEHAVIOR_PAIR_CORRELATION_THRESHOLD: "90",
    SystemLimitKey.BEHAVIOR_PAIR_MIN_SHARED_DAYS: "10",
    SystemLimitKey.BEHAVIOR_PAIR_SYNC_MINUTES: "5",
    # v2backlog.md Faza 8.1 — kirayəçinin interfeys dili. Yeganə dəyər
    # `AVAILABLE_UI_LANGUAGES`-dədir; DB CHECK yoxdur, çünki yeni dil
    # əlavəsi MİQRASİYA deyil, kataloq faylıdır.
    SystemLimitKey.UI_LANGUAGE: "az",
}


#: Faza 8.1 — mövcud interfeys dilləri. SPESİFİKASİYANIN AÇIQ SÖZÜ: «BU FAZADA
#: RUS DİLİNİ TƏRCÜMƏ ETMƏ» — strukturu qur, doldurma YOX. Ona görə korteq
#: TƏKDİR: `RootControlUseCase.set_language` bu korteqlə yoxlayır, Root paneli
#: isə hər element üçün ad göstərir. İkinci dil = bu korteqi + `catalog_<kod>.
#: py` faylını genişləndirmək; heç bir imza dəyişmir.
AVAILABLE_UI_LANGUAGES: Final[tuple[str, ...]] = ("az",)

#: Dil kodlarının ekran adları — kombinat qutusunda KOD deyil, AD görünür.
UI_LANGUAGE_NAMES: Final[dict[str, str]] = {"az": "Azərbaycan"}


# --------------------------------------------------------------------------- #
# BR-001 — İcazə güzəşt müddətinin mənbəyi
# --------------------------------------------------------------------------- #


class LeaveAllowanceSource(str, Enum):
    """`Total = Requested + 2 × Delay` düsturundakı `Requested` haradan gəlir.

    ──────────────────────────────────────────────────────────────────────────
    BİZNES QƏRARI BR-001 (bax `docs/open_questions.md` OQ-001)
    ──────────────────────────────────────────────────────────────────────────
    Spesifikasiya bölmə 4-dəki iki düstur hərfi oxunuşda uyğun gəlmir:
    `Delay` "tam keçən vaxt" kimi təyin olunur, lakin `Total = Requested +
    2 × Delay` yalnız `Requested` bir MÜDDƏT olduqda mənalıdır.

    Eyni zamanda bölmə 4 deyir ki, İcazə Növü seçimi "düsturu DƏYİŞMİR".
    Bu iki tələb yalnız o halda uzlaşır ki, güzəşt müddətinin MƏNBƏYİ
    konfiqurasiya edilə bilən olsun — yəni Root qərar versin, kod yox.

    DEFOLT: `LEAVE_TYPE`. Səbəb: yalnız bu variantda 60 dəqiqəlik nahar
    fasiləsi "60 dəqiqə gecikmə" sayılmır. Əks halda aylıq 240 dəqiqəlik
    limit gündə iki fasilədən sonra dolar və sistem praktiki olaraq
    istifadəyə yararsız olar.
    ──────────────────────────────────────────────────────────────────────────
    """

    #: Güzəşt = seçilmiş İcazə Növünün standart müddəti (DEFOLT).
    LEAVE_TYPE = "LEAVE_TYPE"
    #: Güzəşt = `LEAVE_ALLOWANCE_FIXED_MINUTES` (növdən asılı olmayan tək dəyər).
    FIXED = "FIXED"
    #: Güzəşt yoxdur — spesifikasiyanın ən hərfi, ən sərt oxunuşu.
    NONE = "NONE"


@dataclass(frozen=True)
class LeaveAllowancePolicy:
    """Bir icazə sorğusu üçün güzəşt müddətini hesablayır."""

    source: LeaveAllowanceSource = LeaveAllowanceSource.LEAVE_TYPE
    fixed_minutes: int = 0

    def __post_init__(self) -> None:
        if self.fixed_minutes < 0:
            raise ValueError("Sabit güzəşt müddəti mənfi ola bilməz")

    def resolve(self, *, leave_type_minutes: int | None) -> int:
        """Güzəşt müddətini (dəqiqə) qaytarır.

        Args:
            leave_type_minutes: Seçilmiş İcazə Növünün standart müddəti.
                `None` (növ seçilməyib) → güzəşt 0.
        """
        if self.source is LeaveAllowanceSource.NONE:
            return 0
        if self.source is LeaveAllowanceSource.FIXED:
            return self.fixed_minutes
        return max(0, leave_type_minutes or 0)

    @classmethod
    def from_limits(cls, limits: dict[str, str]) -> LeaveAllowancePolicy:
        """`system_limits` lüğətindən qurur (naməlum dəyər → defolt)."""
        raw_source = limits.get(
            SystemLimitKey.LEAVE_ALLOWANCE_SOURCE.value,
            DEFAULT_LIMITS[SystemLimitKey.LEAVE_ALLOWANCE_SOURCE],
        )
        try:
            source = LeaveAllowanceSource(raw_source)
        except ValueError:
            source = LeaveAllowanceSource.LEAVE_TYPE

        raw_fixed = limits.get(
            SystemLimitKey.LEAVE_ALLOWANCE_FIXED_MINUTES.value,
            DEFAULT_LIMITS[SystemLimitKey.LEAVE_ALLOWANCE_FIXED_MINUTES],
        )
        try:
            fixed = max(0, int(raw_fixed))
        except (TypeError, ValueError):
            fixed = 0

        return cls(source=source, fixed_minutes=fixed)


# --------------------------------------------------------------------------- #
# BR-002 — Gecikmənin pul cəriməsinə çevrilməsi
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DelayFinePolicy:
    """Gecikmə dəqiqələrini AZN cəriməsinə çevirir.

    ──────────────────────────────────────────────────────────────────────────
    BİZNES QƏRARI BR-002
    ──────────────────────────────────────────────────────────────────────────
    Spesifikasiya `fines.source = AUTO_DELAY` cəriməsini və Premiya&Cərimə
    hesabatında "Premiyadan Tutulacaq Yekun Cərimə Məbləği (AZN)" sütununu
    tələb edir, LAKİN gecikmə DƏQİQƏLƏRİNİN AZN-ə necə çevrildiyini HEÇ YERDƏ
    göstərmir.

    QƏRAR: dərəcə (`DELAY_FINE_RATE_PER_MINUTE`) Root tərəfindən təyin olunur,
    **defolt 0.00 AZN**.

    Defolt 0 seçilib, çünki:
      * Təyin edilməmiş dərəcə ilə avtomatik pul kəsmək HÜQUQİ RİSKDİR —
        işçidən əsassız məbləğ tutula bilər.
      * 0 ilə sistem tam işləyir: gecikmə `Total` dəqiqə kimi aylıq 240
        dəqiqəlik limitdən çıxılır (spesifikasiyanın əsas mexanizmi), sadəcə
        ƏLAVƏ pul cəriməsi yaranmır.
      * Müştəri dərəcəni təyin edən kimi AUTO_DELAY cərimələri avtomatik
        işləməyə başlayır — kod dəyişikliyi lazım deyil.
    ──────────────────────────────────────────────────────────────────────────
    """

    rate_per_minute: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        if self.rate_per_minute < 0:
            raise ValueError("Gecikmə cərimə dərəcəsi mənfi ola bilməz")

    @property
    def is_enabled(self) -> bool:
        """Dərəcə təyin edilibmi — `False` olduqda AUTO_DELAY cəriməsi yaranmır."""
        return self.rate_per_minute > 0

    def amount_for(self, delay_minutes: int) -> Money:
        """Gecikmə dəqiqələrinə görə cərimə məbləği.

        İdxal FUNKSİYA DAXİLİNDƏDİR — səbəb modul başlığındakı dairəvi idxal
        izahıdır (bu fayl yarpaq qalmalıdır). Çağırış tezliyi aşağıdır (bir
        icazə qaytarılışında bir dəfə), yəni `sys.modules` axtarışının qiyməti
        ölçülə bilən deyil.
        """
        from src.domain.value_objects.money import Money  # noqa: PLC0415 — bax başlıq

        if delay_minutes <= 0 or not self.is_enabled:
            return Money.zero()
        return Money(self.rate_per_minute * Decimal(delay_minutes))

    @classmethod
    def from_limits(cls, limits: dict[str, str]) -> DelayFinePolicy:
        raw = limits.get(
            SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE.value,
            DEFAULT_LIMITS[SystemLimitKey.DELAY_FINE_RATE_PER_MINUTE],
        )
        try:
            rate = Decimal(str(raw).replace(",", "."))
        except (InvalidOperation, TypeError, ValueError):
            rate = Decimal("0.00")
        return cls(rate_per_minute=max(Decimal("0.00"), rate))


# --------------------------------------------------------------------------- #
# NAHAR / ÇAY FASİLƏSİ (nahar.md)
# --------------------------------------------------------------------------- #
#
# NİYƏ BU MODULDA, `value_objects/catalogs.py`-DA YOX
# ...........................................................................
# `BreakKind` hər bir növü İKİ `SystemLimitKey`-ə bağlayır (müddət + say).
# Onu `catalogs.py`-a yazsaydıq, həmin fayl `policies`-i idxal etdiyi üçün
# bağlantı cədvəli asılılığın SƏHV tərəfində qalardı: kataloq sətri limit
# açarını tanıyardı, halbuki əlaqə əksinədir — LİMİT açarı fasilə növünün
# xüsusiyyətidir. Bu modul isə yarpaqdır (bax modul başlığı) və hər iki
# tərəfdən oxuna bilər.


class BreakKind(str, Enum):
    """Sistem fasiləsinin növü — `leave_types.break_kind` ilə eyni siyahı.

    ──────────────────────────────────────────────────────────────────────────
    ÜMUMİ İCAZƏ NÖVLƏRİNDƏN FƏRQİ
    ──────────────────────────────────────────────────────────────────────────
    İcazə Növləri Kataloqu HR_Admin-in sərbəst genişləndirdiyi siyahıdır
    ("Bank işi", "Şəxsi iş"). Nahar və Çay isə nahar.md-yə görə sistemin
    TƏMƏLİNDƏ olan, hər kirayəçidə mütləq mövcud və YALNIZ Root-un idarə
    etdiyi xüsusi qatdır. Ona görə bu siyahı GUI-dan genişlənmir: yeni növ
    əlavə etmək iki yeni `SystemLimitKey` və bir miqrasiya deməkdir.
    """

    LUNCH = "LUNCH"
    TEA = "TEA"

    @property
    def label_az(self) -> str:
        """İstifadəçiyə göstərilən ad (bölmə 9: yeganə interfeys dili)."""
        return "Nahar fasiləsi" if self is BreakKind.LUNCH else "Çay fasiləsi"

    @property
    def possessive_label_az(self) -> str:
        """«Nahar fasiləniz» — ikinci şəxs mənsubiyyət forması.

        AYRICA XÜSUSİYYƏTDİR, ŞƏKİLÇİ ƏLAVƏSİ DEYİL: `label_az` onsuz da
        üçüncü şəxs mənsubiyyət daşıyır ("fasilə-si"), ona "-niz" qoşmaq
        "fasiləsiniz" kimi səhv forma verərdi. Azərbaycan dilində düzgün
        forma şəkilçinin ƏVƏZLƏNMƏSİDİR, əlavəsi yox.
        """
        return "Nahar fasiləniz" if self is BreakKind.LUNCH else "Çay fasiləniz"

    @property
    def duration_key(self) -> SystemLimitKey:
        """Müddət parametrinin ROOT açarı."""
        if self is BreakKind.LUNCH:
            return SystemLimitKey.LUNCH_BREAK_DURATION_MINUTES
        return SystemLimitKey.TEA_BREAK_DURATION_MINUTES

    @property
    def daily_count_key(self) -> SystemLimitKey:
        """Gündəlik say-həddinin ROOT açarı."""
        if self is BreakKind.LUNCH:
            return SystemLimitKey.LUNCH_BREAK_DAILY_COUNT
        return SystemLimitKey.TEA_BREAK_DAILY_COUNT


#: Azərbaycan dilində sıra sayı şəkilçisi — son rəqəmin saitinə görə.
#:
#: TƏK ŞƏKİLÇİ İŞLƏMİR: "3-cü" (üçüncü) ilə "2-ci" (ikinci) fərqlidir və
#: səhv şəkilçi işçiyə göstərilən xəbərdarlığı savadsız göstərərdi. Cədvəl
#: 1–9 üçün son rəqəmə baxır (11, 12 … eyni qayda ilə işləyir: "11-ci").
_ORDINAL_SUFFIX_AZ: Final[dict[int, str]] = {
    1: "ci",  # birinci
    2: "ci",  # ikinci
    3: "cü",  # üçüncü
    4: "cü",  # dördüncü
    5: "ci",  # beşinci
    6: "cı",  # altıncı
    7: "ci",  # yeddinci
    8: "ci",  # səkkizinci
    9: "cu",  # doqquzuncu
}

#: Onluqlar ayrıca cədvəldədir, çünki onların şəkilçisi son rəqəmdən (0)
#: deyil, onluğun ÖZ adından gəlir: "10-cu" (onuncu), "20-ci" (iyirminci).
_ORDINAL_SUFFIX_AZ_TENS: Final[dict[int, str]] = {
    10: "cu",  # onuncu
    20: "ci",  # iyirminci
    30: "cu",  # otuzuncu
    40: "cı",  # qırxıncı
    50: "ci",  # əllinci
    60: "cı",  # altmışıncı
    70: "ci",  # yetmişinci
    80: "ci",  # səksəninci
    90: "cı",  # doxsanıncı
}


def ordinal_az(number: int) -> str:
    """`3` → `"3-cü"`. Cədvəldən kənar hallarda ən çox yayılan şəkilçi qalır.

    Fallback ("ci") praktikada işə düşmür — gündəlik fasilə sayı iki rəqəmi
    keçmir — lakin funksiya sıra sayı gözlənilən HƏR yerdə çağırıla bilsin
    deyə istisna ATMIR: xəbərdarlıq mətninin qrammatikası heç bir halda
    əməliyyatı dayandırmamalıdır.
    """
    if number <= 0:
        return str(number)
    if number % 10 == 0:
        return f"{number}-{_ORDINAL_SUFFIX_AZ_TENS.get(number % 100, 'cu')}"
    return f"{number}-{_ORDINAL_SUFFIX_AZ.get(number % 10, 'ci')}"


@dataclass(frozen=True)
class BreakAllowance:
    """Bir fasilə növünün ROOT parametrləri + həmin günkü istifadə.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ BLOKLAMIR (nahar.md §MƏNTİQ, bənd 2 — açıq göstəriş)
    ──────────────────────────────────────────────────────────────────────────
    Say-həddi aşılanda əməliyyat DAVAM EDİR; yalnız işçi ekranında və HR
    panelində xəbərdarlıq görünür. Səbəb tapşırıqda yazılıb: real mağaza
    əməliyyatının qəfil bloklanmasının qarşısını almaq. Eyni istiqamət
    layihədə artıq var — `MonthlyLeaveUsage` (aylıq 240 dəq.) da yalnız
    xəbərdarlıq edir, `ScheduleConflict` də.

    ──────────────────────────────────────────────────────────────────────────
    `duration_minutes` CƏRİMƏYƏ TƏSİR ETMİR
    ──────────────────────────────────────────────────────────────────────────
    Bu sinif `LeavePenalty`-yə HEÇ VAXT ötürülmür və `LeaveAllowancePolicy`
    ilə qarışdırılmamalıdır: müddət yalnız «Nahar fasiləniz: 60 dəqiqə»
    göstəricisi üçündür (nahar.md bənd 3).
    """

    kind: BreakKind
    duration_minutes: int
    daily_count: int
    used_count: int = 0

    def __post_init__(self) -> None:
        if self.duration_minutes < 0:
            raise ValueError("Fasilə müddəti mənfi ola bilməz")
        if self.daily_count < 0:
            raise ValueError("Gündəlik fasilə sayı mənfi ola bilməz")
        if self.used_count < 0:
            raise ValueError("İstifadə olunmuş fasilə sayı mənfi ola bilməz")

    @property
    def is_exceeded(self) -> bool:
        """Hədd aşılıbmı.

        `daily_count = 0` "bu kirayəçidə həmin fasilə nəzərdə tutulmayıb"
        deməkdir və HƏR istifadə aşılma sayılır — söndürmənin AÇIQ yolu
        məhz budur (migrations/045 `min_value = 0` izahı). `MonthlyLeaveUsage`
        0-ı "limitsiz" kimi oxuyur, çünki orada 0 dəqiqəlik icazə büdcəsi
        heç bir mağazada mənalı deyil; burada isə 0 fasilə tam mənalıdır.
        """
        return self.used_count > self.daily_count

    @property
    def remaining_count(self) -> int:
        """Qalan haqq — mənfi olmur (aşılma `is_exceeded` ilə bildirilir)."""
        return max(0, self.daily_count - self.used_count)

    def duration_label_az(self) -> str:
        """«Nahar fasiləniz: 60 dəqiqə» — işçi ekranının məlumat sətri."""
        return f"{self.kind.possessive_label_az}: {self.duration_minutes} dəqiqə"

    def usage_label_az(self) -> str:
        """«Bu gün: 1/2 çay fasiləsi istifadə edilib» (nahar.md GUI, bənd 2)."""
        return (
            f"Bu gün: {self.used_count}/{self.daily_count} "
            f"{self.kind.label_az.lower()} istifadə edilib"
        )

    def warning_az(self) -> str:
        """«3-cü çay fasiləsi (limit: 2)» — hədd aşılmayıbsa boş sətir.

        Boş sətir qaytarmaq istisna atmaqdan üstündür: çağıran tərəf ekran
        kodudur və "xəbərdarlıq varmı?" sualını `if` ilə soruşmalıdır, `try`
        ilə yox.
        """
        if not self.is_exceeded:
            return ""
        return (
            f"{ordinal_az(self.used_count)} {self.kind.label_az.lower()} "
            f"(limit: {self.daily_count})"
        )

    @classmethod
    def from_limits(
        cls, kind: BreakKind, limits: dict[str, str], *, used_count: int = 0
    ) -> BreakAllowance:
        """`system_limits` lüğətindən qurur (naməlum/pozuq dəyər → defolt).

        Pozuq sətir istisna ATMIR: `system_limits.limit_value` `TEXT`-dir və
        birbaşa SQL ilə ora "abc" yazıla bilər. Belə bir sətrə görə İşçi Ana
        Ekranının açılmaması qüsurun cəzasını səhv adama verərdi.
        """
        return cls(
            kind=kind,
            duration_minutes=_limit_as_int(limits, kind.duration_key),
            daily_count=_limit_as_int(limits, kind.daily_count_key),
            used_count=max(0, used_count),
        )


def _limit_as_int(limits: dict[str, str], key: SystemLimitKey) -> int:
    """`system_limits` sətrini tam ədədə çevirir; alınmasa `DEFAULT_LIMITS`."""
    raw = limits.get(key.value, DEFAULT_LIMITS[key])
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        return int(DEFAULT_LIMITS[key])


# --------------------------------------------------------------------------- #
# Feature Toggle-lar (bölmə 3)
# --------------------------------------------------------------------------- #


class FeatureModule(str, Enum):
    """`feature_toggles.module_key` — DB seed-i ilə eyni."""

    CAMERA_VERIFICATION = "CAMERA_VERIFICATION"
    DUAL_CONTROL = "DUAL_CONTROL"
    SHIFT_SWAP = "SHIFT_SWAP"
    FINE_MODULE = "FINE_MODULE"
    TASK_ENGINE = "TASK_ENGINE"
    SALES_POINTS = "SALES_POINTS"
    DASHBOARD_BUILDER = "DASHBOARD_BUILDER"
    SUPPORT_CHAT = "SUPPORT_CHAT"

    @property
    def is_structural(self) -> bool:
        """Söndürülməsi əlavə xəbərdarlıq modalı tələb edən modul (bölmə 3).

        "Kamera Təsdiqi" STEP1-3 və Morning Check-in axınlarının struktur
        əsasıdır — bunu söndürmək adi bir-kliklik toggle DEYİL.

        `DUAL_CONTROL` BURADA QƏSDƏN YOXDUR (SEC-020). Onu `is_structural`
        etmək cazibədar görünürdü, lakin `is_structural` STATİK bayraqdır:
        "həmişə, hər kirayəçidə yazılı təsdiq tələb et" deməkdir. Faktiki
        zəmanət isə ŞƏRTLİDİR — modul yalnız AKTİV üz-təsdiqi istisnası olan
        kirayəçidə struktur daşıyıcıdır (`FACE_EXEMPTION_COMPENSATING_MODULE`).
        Statik bayraq şərti qaydanı ifadə edə bilmir və üstəlik onu ZƏİFLƏDİR:
        6 simvolluq təsdiq mətni yazan Root istisnalı işçini kompensasiyasız
        qoymağa DAVAM edərdi. Şərti qapı `RootControlUseCase.set_module_enabled`
        + `enforce_face_exemption_compensation()` trigger-indədir.
        """
        return self is FeatureModule.CAMERA_VERIFICATION


#: Face Control istisnasının (`facecontrol.md` bənd 14) YEGANƏ kompensasiya
#: edici nəzarəti — SEC-020.
#:
#: NİYƏ AYRICA ADLANDIRILIR: `FeatureModule.DUAL_CONTROL` bir neçə yerdə oxunur
#: (manual vaxt düzəlişi həddi — `leave_verification.apply_override`), lakin
#: YALNIZ üz-istisnası yolunda o, bir STRUKTUR ZƏMANƏTİN daşıyıcısıdır: bənd
#: 14 PIN-only boşluğunun MƏCBURİ ikinci-təsdiqlə əvəzlənməsini vəd edir və
#: həmin ikinci təsdiq məhz bu moduldur. Adlandırılmış sabit bağlantını
#: grep-lə görünən edir — əks halda «`DUAL_CONTROL` söndürülsə istisnalı işçiyə
#: nə olur?» sualının cavabı üç ayrı faylda gizli qalardı və məhz bu, auditin
#: tapdığı boşluq idi.
FACE_EXEMPTION_COMPENSATING_MODULE: Final[FeatureModule] = FeatureModule.DUAL_CONTROL


# --------------------------------------------------------------------------- #
# #20 Performans Qiymətləndirməsi — dövr granulyarlığı (kompasos11.md Faza 8)
# --------------------------------------------------------------------------- #


class TelegramNotifyMode(str, Enum):
    """`SystemLimitKey.TELEGRAM_NOTIFY_MODE` dəyərləri (CHAT-1 Faza 7).

    YALNIZ TELEGRAM-A TƏSİR EDİR. Proqramdakı «Texniki Dəstək» bölməsinə
    müraciət HƏR rejimdə düşür — bu parametr mesajı SİLMİR, yalnız telefona
    zəngin gedib-getməyəcəyini təyin edir. Fərq vacibdir: `DEAKTİV` seçən
    Root mesajları itirmir, sadəcə onları proqramdan oxuyur.
    """

    #: Hər texniki mesaj Telegram-a düşür.
    ALL = "HAMISI"
    #: Yalnız işçinin AÇIQ təcili işarələdiyi müraciətlər
    #: (`support_tickets.is_urgent`, migrations/068).
    URGENT_ONLY = "YALNIZ TƏCİLİ"
    #: Telegram-a heç nə getmir.
    DISABLED = "DEAKTİV"

    @classmethod
    def from_value(cls, raw: str) -> TelegramNotifyMode:
        """Naməlum/səhv dəyər → `ALL`.

        `DISABLED`-a düşmək DAHA TƏHLÜKƏLİ olardı: səhv yazılmış bir limit
        sətri bütün bildirişləri sükutla kəsər və nasazlıq yalnız «niyə
        cavab vermirsiniz?» sualı ilə üzə çıxardı.
        """
        try:
            return cls(raw.strip().upper())
        except ValueError:
            return cls.ALL


class PerformanceReviewPeriodType(str, Enum):
    """`SystemLimitKey.PERFORMANCE_REVIEW_PERIOD_TYPE` dəyərləri.

    Yalnız FORMANIN DEFOLT DÖVR SƏTRİNİ necə hesabladığını təyin edir
    (`PerformanceReviewUseCase.default_period`) — `performance_reviews.
    period`-un ÖZÜ sərbəst formatdadır (illik/aylıq/rüblük hamısı DB
    `CHECK`-inə uyğundur, migrations/020), yəni bu parametr keçmiş qeydləri
    RETROAKTİV məhdudlaşdırmır, yalnız YENİ formanın ilkin təklifini seçir.
    """

    #: Ayın "YYYY-MM" formatı — dövri hesabatların (Aylıq Cərimə İcmalı) ritmi.
    MONTHLY = "MONTHLY"
    #: Rübün "YYYY-Qn" formatı.
    QUARTERLY = "QUARTERLY"

    def format_period(self, *, year: int, month: int) -> str:
        """Verilən təqvim ayından dövr sətri qurur.

        `QUARTERLY` üçün ay → rüb çevrilməsi: (ay-1)//3 + 1 — Yanvar-Mart
        1-ci rüb, Aprel-İyun 2-ci və s. (standart maliyyə rüb bölgüsü).
        """
        if self is PerformanceReviewPeriodType.QUARTERLY:
            quarter = (month - 1) // 3 + 1
            return f"{year:04d}-Q{quarter}"
        return f"{year:04d}-{month:02d}"

    @classmethod
    def from_value(cls, raw: str) -> PerformanceReviewPeriodType:
        """Naməlum/səhv dəyər → `MONTHLY` (ən geniş yayılmış, təhlükəsiz defolt)."""
        try:
            return cls(raw.strip().upper())
        except ValueError:
            return cls.MONTHLY


__all__ = [
    "DEFAULT_LIMITS",
    "FACE_EXEMPTION_COMPENSATING_MODULE",
    "BreakAllowance",
    "BreakKind",
    "DelayFinePolicy",
    "FeatureModule",
    "LeaveAllowancePolicy",
    "LeaveAllowanceSource",
    "PerformanceReviewPeriodType",
    "SystemLimitKey",
    "TelegramNotifyMode",
    "ordinal_az",
]
