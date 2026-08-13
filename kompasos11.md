KompasOS-a 12 YENİ funksiya əlavə edirəm. Sistemin əsas infrastrukturu (RBAC,
Hierarchy Guard, ROOT Control Center, Shift Matrix, 1C sync — YALNIZ bal
sistemi üçün, Dashboard Builder, Face Control, Fine/Points sistemi) ARTIQ
HAZIRDIR və işləyir. Bu prompt YALNIZ əlavədir.

===============================================================================
QIRMIZI XƏTT
===============================================================================
Mövcud kodda artıq işləyən HEÇ BİR funksiyanı, cədvəli, ekranı, mexanizmi
SİLMƏ və ya YENİDƏN YAZMA. Kəsişmə tapsan (oxşar mexanizm/cədvəl/ekran artıq
varsa) — YENİSİNİ YARATMA, MÖVCUDU GENİŞLƏNDİR, mənə "bunu mövcud [X] ilə
birləşdirdim" kimi qısaca bildir.

===============================================================================
MƏRKƏZİ TƏLƏB — HƏR ŞEY ROOT-DAN İDARƏ OLUNMALIDIR (BÜTÜN PROQRAM ÜÇÜN)
===============================================================================
Bu qayda YALNIZ aşağıdakı 12 YENİ funksiyaya aid DEYİL — KompasOS-un
TAMAMİLƏ BÜTÜN kod bazasına aiddir (əvvəlki fazalarda tikilmiş hər şey
daxil olmaqla: permission sistemi, Shift Matrix, Fine/Points, Face
Control, License/Lisenziya modulu və s.). İstənilən yerdə konfiqurasiya
edilə bilən ədəd/qayda/çəki/həddi/vaxt (threshold, weight, rate, timeout,
duration) TAPSAN — bu YENİ funksiyalara aid olsun-olmasın — KODA HARDCODE
QALMAMALIDIR, mövcud `system_limits`/ROOT Control Center mexanizminə
köçürülməlidir, YALNIZ Root dəyişdirə bilsin, hər dəyişiklik audit-lənsin.
Aşağıdakı 12 funksiyanın təsvirində "ROOT PARAMETRİ:" deyə işarələnmiş hər
dəyər bunun bir hissəsidir, amma BUNUNLA MƏHDUDLAŞMIR — FAZA 10 bütün
proqramı əhatə edən tam yoxlanışdır (aşağıda genişləndirilib).

===============================================================================
1C SƏRHƏDİ (YENİ, MÜTLƏQ QAYDA)
===============================================================================
Sistemdə 1C-yə TOXUNAN YEGANƏ mövcud kanal — Satış Xalları (bal) sistemidir
(brutto satış → xal hesablanması, bax Kompas.md bölmə 6). Bu 13 funksiyadan
HEÇ BİRİ 1C-yə YENİ bir bağlantı/sync/oxuma NÖQTƏSİ AÇMASIN. Aşağıdakı 3
funksiya əvvəlki versiyada 1C-yə əsaslanırdı — bunlar YENİDƏN dizayn
edilib, artıq 1C-siz işləyir (bax dəyişikliklər aşağıda):

===============================================================================
3 VACİB STRUKTUREL QƏRAR (BUNLARI OXU, BAŞQA CÜR TİKMƏ)
===============================================================================

**A) #7 (POS icazələri) — YENİDƏN ÇƏRÇİVƏLƏNDİ, 1C-SİZ:** KompasOS-un öz
kassa ekranı yoxdur VƏ bu funksiya artıq 1C-dən əməliyyat sync-i GÖZLƏMİR.
#7 indi YALNIZ bir SƏNƏDLƏŞDİRMƏ/SİYASƏT qeydidir: hər işçi üçün "icazə
verilən endirim/ləğv/geri-qaytarma həddi"ni KompasOS-da SAXLAYIR (HR/audit
məqsədilə — "bu işçiyə hansı səlahiyyət verilib" sualının rəsmi cavabı).
**AVTOMATİK AŞKARLAMA/YOXLAMA HİSSƏSİ TAM ÇIXARILDI** (bu, 1C-transaction-
sync tələb edirdi) — #7 artıq Exception Engine-ə heç nə göndərmir, sadəcə
statik siyasət-qeydidir. Bunu sizə açıq deyirəm: bu, funksiyanı xeyli
sadələşdirir (avtomatik pozuntu-tutma yoxdur, yalnız sənədləşdirmə var) —
əgər gələcəkdə 1C real-vaxt inteqrasiyası mümkün olsa, bu, güclü bir
təkmilləşdirmə istiqaməti olardı, amma indi scope-dan kənardır.

**B) #9 (Exception-Based Reporting) — MOTOR QALIR, MƏNBƏ AZALDI:** Vahid
Exception Engine dizaynı SAXLANILIR (yaxşı arxitektura qərarıdır, gələcəkdə
yeni mənbələr asanlıqla əlavə oluna bilər), amma bu partiyada YALNIZ #8-in
davranış-anomaliyası bura bəslənir (#7 artıq avtomatik aşkarlama etmir,
#25 isə tamamilə çıxarılıb — bax yuxarı).

**C) #24 (Benchmark Dashboard) — MÖVCUD DASHBOARD BUILDER-Ə QOŞUL, 1C-SİZ
METRİKLƏRLƏ:** Kompas.md-də artıq "Dashboard Builder" var. #24 üçün YENİ,
AYRI ekran QURMA — mövcud Dashboard Builder-ə YENİ WIDGET TİPLƏRİ (çox-
mağaza müqayisə cədvəli/qrafiki) əlavə et. Müqayisə METRİKLƏRİ YALNIZ
KompasOS-un öz native datasından olsun: cərimə sayı, davamiyyət faizi,
xal balansı (bu, artıq mövcud, icazəli 1C-bal-kanalından gəlir — YENİ
bağlantı deyil). Xam satış rəqəmləri/marja kimi 1C-yə məxsus göstəricilər
BU DASHBOARD-A DAXİL EDİLMİR.

**D) #13 (Tələb-əsaslı Növbə Planlaşdırma) — TAM YENİDƏN DİZAYN, 1C-SİZ:**
Əvvəlki versiya 1C satış-datasına əsaslanırdı — bu TAM ÇIXARILDI. Əvəzinə
#13 indi KompasOS-un ÖZ tarixi Attendance/Shift datasına əsaslanır: "bu
mağaza son 8 həftədə cümə günləri orta hesabla N işçi ilə işləyib" kimi
sadə, öz-daxili pattern-təklifi (satış-həcmi ilə ƏLAQƏSİZ, sırf keçmiş
kadr-tərkibinə baxaraq). Bu, "tələb-əsaslı" (demand-based) deyil, daha çox
"tarixi-nümunə-əsaslı" (pattern-based) bir təklifdir — daha zəif siqnal,
amma 1C-siz və tam KompasOS-daxili.

**#25 (1C Uzlaşdırma Modulu) TAM ÇIXARILDI** — bu funksiya öz mahiyyəti
etibarilə 1C-transaction-count-a əsaslanırdı, 1C-siz mənası qalmır. Aşağıda
heç bir fazada yoxdur, sxemdən də çıxarıldı.

===============================================================================
FAZA 0A — TOKEN-QƏNAƏT AYARLARI (HƏR ŞEYDƏN ƏVVƏL)
===============================================================================
.claude/settings.json faylını yarat/redaktə et (mövcud ayarları SİLMƏDƏN,
yalnız əlavə et — faylda artıq bu qadağalar varsa, təkrar əlavə etmə):

{
  "permissions": {
    "deny": [
      "Read(.venv/**)", "Read(venv/**)", "Read(node_modules/**)",
      "Read(dist/**)", "Read(build/**)", "Read(__pycache__/**)",
      "Read(*.pyc)", "Read(.git/**)",
      "Bash(cat .venv/**)", "Bash(find .venv*)", "Bash(grep -r .venv*)"
    ]
  }
}

===============================================================================
FAZA 0B — 12 SUBAGENT-İ YARAT (TİKİNTİYƏ UYĞUN, TOKEN-QƏNAƏTLİ)
===============================================================================
.claude/agents/ qovluğunda bu 12 subagent-i yarat. Fərq əvvəlki audit-
promptundan: bunların ƏKSƏRİYYƏTİ TİKİNTİ (build) agentidir — tapıb-
düzəltmək yox, spesifikasiyaya görə yeni kod yazmaqdır. YALNIZ Faza 10
üçün (bütün kod bazasını hardcode-dəyər üçün tarama) audit+fixer cütü
lazımdır, çünki bu, faktiki bir "tap" işidir.

--- 1. schema-migration-engineer (Faza 1) ---
---
name: schema-migration-engineer
description: Faza 1-in bütün yeni cədvəllərini miqrasiya kimi yazır və
  tətbiq edir.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: opus
---
Sən Senior Database Engineer-sən. Faza 1-də təsvir olunan bütün yeni
cədvəlləri miqrasiya kimi yaz, tətbiq et, test et. Mövcud cədvəlləri
SİLMƏ/DƏYİŞDİRMƏ, yalnız ƏLAVƏ et. AXTARIŞ MƏHDUDİYYƏTİ: YALNIZ src/ və
schema.sql ilə işlə, .venv/dist/build/node_modules/.git-ə girmə.

--- 2. rbac-flag-engineer (Faza 2) ---
---
name: rbac-flag-engineer
description: Faza 2-nin yeni permission flag-lərini mövcud RBAC-a
  inteqrasiya edir.
tools: Read, Write, Edit, Grep, Glob
permissionMode: default
model: sonnet
---
Sən RBAC Integration Engineer-sən. Faza 2-də təsvir olunan yeni flag-ləri
mövcud permission_flags kataloquna əlavə et, mövcud Hierarchy Guard/Self-
Escalation Guard-a avtomatik tabe olduğunu təsdiqlə (yeni guard yazma).
AXTARIŞ MƏHDUDİYYƏTİ: YALNIZ src/-də permission-related fayllarla işlə.

--- 3. exception-engine-architect (Faza 3) ---
---
name: exception-engine-architect
description: Vahid Exception Engine-in nüvə arxitekturasını qurur.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: opus
---
Sən Senior Domain Architect-sən. Faza 3-də təsvir olunan rule-registry
pattern-li Exception Engine-i qur — gələcək mənbələr üçün genişlənə bilən
dizaynla. Test yaz. AXTARIŞ MƏHDUDİYYƏTİ: YALNIZ src/domain qovluğunda işlə.

--- 4. pos-policy-engineer (Faza 4) ---
---
name: pos-policy-engineer
description: #7 POS icazə siyasəti qeydini (sənədləşdirmə, 1C-siz) qurur.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: sonnet
---
Sən Backend Engineer-sən. Faza 4-də təsvir olunan POSThresholdUseCase-i
qur — YALNIZ siyasət-qeydi, avtomatik yoxlama YOXDUR (1C-yə toxunma).

--- 5. anomaly-exception-ui-engineer (Faza 5) ---
---
name: anomaly-exception-ui-engineer
description: #8 davranış-anomaliyası hesablaması + #9-un "İstisnalar"
  ekranını qurur.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: sonnet
---
Sən Full-Stack Engineer-sən. Faza 5-də təsvir olunan BehaviorBaseline
UseCase-i və "İstisnalar" ekranını qur, mövcud dizayn sisteminə uyğunlaş.

--- 6. shift-intelligence-engineer (Faza 6) ---
---
name: shift-intelligence-engineer
description: #13+#14+#15+#16 — Shift Matrix-ə 4 köməkçi funksiya əlavə
  edir. Ən yüksək-riskli faza (mövcud kritik Shift Matrix-ə toxunur).
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: opus
---
Sən Senior Backend Engineer-sən. Faza 6-nın 4 alt-funksiyasını (tarixi-
nümunə təklifi, əmək-qanunu xəbərdarlığı, overtime izləmə, açıq növbə
bazarı) qur. MÖVCUD Shift Matrix-in əsas təyinetmə məntiqini SİLMƏ/
YENİDƏN YAZMA — yalnız əlavə et. Race-condition-a diqqət et (#16).

--- 7. document-compliance-engineer (Faza 7) ---
---
name: document-compliance-engineer
description: #17 sənəd/müqavilə idarəetməsi + Shift Matrix-bloklama
  inteqrasiyasını qurur.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: sonnet
---
Sən Backend Engineer-sən. Faza 7-ni qur — xüsusilə "KRİTİK İNTEQRASİYA"
bəndinə diqqət et: mövcud Shift Matrix təyinetmə use case-inə YALNIZ bir
yoxlama əlavə et, əsas funksiyanı YENİDƏN YAZMA.

--- 8. hr-communication-engineer (Faza 8) ---
---
name: hr-communication-engineer
description: #19 Broadcast + #20 Performans modulunu qurur.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: sonnet
---
Sən Full-Stack Engineer-sən. Faza 8-in hər iki alt-funksiyasını qur,
mövcud store-scoping pattern-indən istifadə et.

--- 9. people-analytics-engineer (Faza 9) ---
---
name: people-analytics-engineer
description: #21 Turnover Riski çəkili-bal modelini qurur.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: sonnet
---
Sən Backend Engineer-sən. Faza 9-u qur — HƏR bal-çəkisi system_limits-də
olsun, hardcode ETMƏ.

--- 10. benchmark-dashboard-engineer (Faza 9A) ---
---
name: benchmark-dashboard-engineer
description: #24 — mövcud Dashboard Builder-ə 4 yeni benchmark widget-i
  əlavə edir.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: sonnet
---
Sən Frontend Engineer-sən. Faza 9A-nın 4 widget tipini mövcud Dashboard
Builder-ə əlavə et (AYRI ekran yaratma), drill-down naviqasiyasını qur.

--- 11. hardcode-value-auditor (Faza 10.2, AUDITOR — yalnız tapır) ---
---
name: hardcode-value-auditor
description: Bütün tarixi kod bazasında hardcode-edilmiş konfiqurasiya
  dəyərlərini (magic numbers) tapır. YALNIZ tapır, düzəltmir.
tools: Read, Grep, Glob
permissionMode: plan
model: sonnet
---
Bütün src/ qovluğunda (bu promptdan ƏVVƏLKİ kod daxil) koda birbaşa
yazılmış ədəd/müddət/faiz/həddi tap. Hər tapıntını fayl/sətir ilə göstər.
AXTARIŞ MƏHDUDİYYƏTİ: Əvvəlcə grep -l (yalnız fayl adları), sonra
lazım gələrsə grep -n -A3 -B3 (yalnız kontekst). Bütöv faylı Read etmə,
məcburi olmadıqca. SƏRT TAVAN: 8000 tokendan çox işlətməyə başlasan,
DAYAN, indiyədək tapdığını QISMƏN hesabat kimi ver.

--- 12. root-control-migration-engineer (Faza 10.2, FIXER) ---
---
name: root-control-migration-engineer
description: hardcode-value-auditor-ın tapdığı dəyərləri ROOT Control
  Center-ə köçürür.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: opus
---
Sən Senior Platform Engineer-sən. Tapılan HƏR hardcode dəyəri system_
limits-ə köçür, kodu bu yeni parametrdən oxuyacaq şəkildə YENİLƏ (silmə,
YENİLƏ). Hər dəyişikliyi test et.

/agents ilə bütün 12-nin qeydiyyatdan keçdiyini yoxla, hər birini kiçik
sınaqla işə sal. Mənə "12 agent hazır və işlək" təsdiqini ver, sonra
FAZA 1-ə keç.

===============================================================================
FAZA 1 — SCHEMA (ƏLAVƏ, MÖVCUD CƏDVƏLLƏRƏ TOXUNMADAN) — AGENT: schema-migration-engineer
===============================================================================
Miqrasiya yaz və tətbiq et (hamısı bir fazada, sonrakı fazalar bunları
istifadə edəcək):
- `pos_permission_thresholds` (employee_id, max_discount_pct, can_void,
  can_refund, updated_by, audit) — #7 (siyasət-qeydi, avtomatik yoxlama YOX)
- `employee_behavior_baseline` (employee_id, avg_checkin_time, variance,
  last_calculated) — #8
- `exceptions` (id, source [BEHAVIOR_ANOMALY], employee_id, store_id,
  detail, severity, status [OPEN/REVIEWED/DISMISSED], created_at) — #9,
  vahid Exception Engine üçün (gələcək mənbələr üçün genişlənə bilən dizayn)
- `staffing_pattern_suggestions` (store_id, weekday, avg_historical_headcount,
  based_on_weeks) — #13, YALNIZ KompasOS-un öz Attendance/Shift datasından
- `overtime_log` (employee_id, date, hours_over_norm) — #15
- `open_shift_postings` (store_id, date, shift_id, status
  [OPEN/CLAIMED], claimed_by) — #16
- `employee_documents` (employee_id, doc_type, file_ref, expiry_date,
  is_blocking) — #17
- `announcements` (id, created_by, scope [ALL/STORE_LIST], message,
  created_at) — #19
- `performance_reviews` (employee_id, reviewer_id, period, ratings_json,
  notes) — #20
- `attrition_risk_scores` (employee_id, score, factors_json,
  calculated_at) — #21

Mövcud `employees`, `fines`, `attendance_records` və s. cədvəllərinin başqa
heç bir sütununu dəyişdirmə. Test et.
**DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 2 — İCAZƏ KATALOQUNA YENİ FLAG-LƏR (MÖVCUD SİSTEMƏ ƏLAVƏ) — AGENT: rbac-flag-engineer
===============================================================================
Mövcud permission_flags kataloquna əlavə et (mövcud kateqoriyalara, YENİ
kateqoriya yaratma məcburi deyil, uyğun olana əlavə et):
- `can_manage_pos_thresholds` (#7) — HR/Admin default
- `can_view_exceptions` (#9)
- `can_broadcast_announcements` (#19) — CEO/HR_Admin default
- `can_conduct_performance_review` (#20) — HR_Admin/Store Manager default
- `can_view_attrition_risk` (#21) — HR_Admin/CEO default
- `can_manage_employee_documents` (#17)

Mövcud Hierarchy Guard/Self-Escalation Guard qaydalarına bunları da
avtomatik tabe et (yeni qayda yazma, mövcudu çağır).
**DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 3 — EXCEPTION ENGINE (VAHİD MOTOR, GƏLƏCƏYƏ AÇIQ DİZAYN) — AGENT: exception-engine-architect
===============================================================================
`ExceptionEngineUseCase` yarat — qayda-qeydiyyatlı (rule-registry) dizaynla:
hər qayda özünü bu motora "register" edir, motor nəticələri `exceptions`
cədvəlinə yazır. Bu partiyada YALNIZ #8-in davranış-anomaliyası qaydası bu
motora bağlanacaq (Faza 5-də) — motor özü isə gələcəkdə yeni mənbələr üçün
genişlənə bilən şəkildə dizayn edilsin (rule-registry pattern buna görə
seçilib).

Test yaz.
**DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 4 — #7: POS İCAZƏ SİYASƏTİ (SƏNƏDLƏŞDİRMƏ, 1C-SİZ) — AGENT: pos-policy-engineer
===============================================================================
1. `POSThresholdUseCase` — `can_manage_pos_thresholds` sahibi hər işçi üçün
   max-endirim-faizi, void/refund icazəsini təyin edir və saxlayır.
2. GUI: İstifadəçi İdarəetməsində, işçi redaktəsində yeni "POS Səlahiyyət
   Siyasəti" sahəsi (mövcud ekranı SİLMƏDƏN, əlavə tab/bölmə kimi).
3. Bu, YALNIZ rəsmi qeyddir — 1C-yə heç bir bağlantı, heç bir avtomatik
   yoxlama YOXDUR. Audit Log Viewer-də görünür (kim, hansı işçiyə, hansı
   həddi, nə vaxt təyin edib).
**DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 5 — #8+#9: ANOMALİYA + İSTİSNA EKRANI — AGENT: anomaly-exception-ui-engineer
===============================================================================
1. `BehaviorBaselineUseCase` — hər işçi üçün son 30 günün orta check-in
   vaxtını/variansını hesablayır (gecəlik cron, mövcud cron-pattern-ə
   uyğun). ROOT PARAMETRİ: sapma-həddi (defolt neçə dəqiqə sapma
   "anomaliya" sayılsın) — system_limits-ə.
2. Sapma aşkarlananda Exception Engine-ə göndər.
3. **"İstisnalar" ekranı** (#9-un GUI tərəfi, `can_view_exceptions`) —
   mövcud dizayn sisteminə uyğun cədvəl: mənbə-badge (hazırda yalnız
   "Davranış Anomaliyası", dizayn gələcək mənbələr üçün genişlənə bilən
   olsun), işçi, mağaza, təfərrüat, "[Nəzərdən Keçirildi]"/"[Rədd Et]"
   əməliyyatları.
**DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 6 — #13+#14+#15+#16: NÖVBƏ-ƏSASLI İNTELLEKT (Shift Matrix genişlənməsi) — AGENT: shift-intelligence-engineer
===============================================================================
Mövcud Shift Matrix-i DƏYİŞDİRMƏDƏN, ona bu köməkçiləri ƏLAVƏ et:
1. **#13 Tarixi-nümunə-əsaslı təklif (1C-siz):** KompasOS-un ÖZ Attendance/
   Shift datasına baxıb (1C-yə TOXUNMADAN), "bu mağaza bu həftənin günü
   üçün son N həftədə orta hesabla neçə işçi ilə işləyib" göstərən qeyri-
   məcburi bir göstərici (admin istəsə tətbiq edir, istəməsə görməzdən
   gəlir). ROOT PARAMETRİ: neçə həftəlik tarixçəyə baxılsın (`based_on_
   weeks`). Bu, satış-həcminə DEYİL, sırf keçmiş kadr-tərkibi nümunəsinə
   əsaslanır.
2. **#14 Əmək qanunu xəbərdarlığı:** Shift Matrix-də admin növbə təyin
   edərkən, ROOT PARAMETRİ olan (min-istirahət-saatı, məcburi-fasilə-
   müddəti, max-ardıcıl-gün) qaydalara qarşı yoxlayır, pozuntu halında
   xəbərdarlıq (bloklamır, sadəcə göstərir — son qərar admin-dədir).
3. **#15 Overtime izləmə:** Attendance Report-un mövcud hesablama
   məntiqinə ƏLAVƏ, gündəlik/həftəlik norma-aşımını `overtime_log`-a
   yazır. ROOT PARAMETRİ: gündəlik/həftəlik norma saatı. Aşımda HR_Admin-ə
   bildiriş (mövcud e-poçt fallback-ı çağıraraq).
4. **#16 Açıq Növbə Bazarı:** Mövcud Shift Swap Request-dən FƏRQLİ axın —
   admin bir boş növbəni "açıq" elan edir (`open_shift_postings`), uyğun
   bütün işçilər öz İşçi Ana Ekranından görüb "[Bu Növbəni Götür]" edə
   bilir, ilk basan qazanır (race-condition-a qarşı DB-səviyyəli lock
   istifadə et).
**DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 7 — #17: SƏNƏD/MÜQAVİLƏ İDARƏETMƏSİ + SHIFT-BLOKLAMA — AGENT: document-compliance-engineer
===============================================================================
1. `EmployeeDocumentUseCase` — `can_manage_employee_documents`, fayl
   yüklə, bitmə-tarixi təyin et, `is_blocking` (bu sənəd bitəndə işçi
   növbəyə təyin edilə bilməsin) işarəsi.
2. Bitmə-tarixinə 30/14/7 gün qalanda mövcud e-poçt fallback-ını çağıraraq
   xəbərdarlıq göndər (yeni bildiriş-mexanizmi YAZMA).
3. **KRİTİK İNTEQRASİYA:** Mövcud Shift Matrix-in növbə-təyinetmə use
   case-inə (Faza 6-da toxunmadığın əsas funksiya) bir yoxlama ƏLAVƏ ET:
   işçinin `is_blocking=true` sənədi bitibsə, admin növbə təyin edərkən
   xəbərdarlıq göstərilsin (Faza 6-nın #14 xəbərdarlıq şablonu ilə eyni
   UI pattern-i istifadə et, təkrar yazma).
**DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 8 — #19+#20: ÜNSİYYƏT + PERFORMANS — AGENT: hr-communication-engineer
===============================================================================
1. **#19 Broadcast:** `can_broadcast_announcements` sahibi bir mesaj
   yazır, əhatə (bütün/seçilmiş mağazalar) seçir, mövcud store-scoping
   pattern-i istifadə edərək müvafiq İşçi Ana Ekranlarında göstərilir
   (dəstək chat-dən FƏRQLİ, bir-tərəflidir, cavab yoxdur).
2. **#20 Performans:** `can_conduct_performance_review` sahibi dövri
   (ROOT PARAMETRİ: rüb/ay) sadə forma doldurur (bir neçə KPI + qeyd
   sahəsi), işçinin öz tarixçəsində görünür.
**DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 9 — #21: TURNOVER RİSKİ — AGENT: people-analytics-engineer
===============================================================================
**#21 Turnover Riski:** `AttritionRiskUseCase` — mövcud cərimə/davamiyyət/
staj datasından çəkili bal hesablayır. ROOT PARAMETRİ: HƏR SİQNALIN ÇƏKİSİ
(məs. "son 3 ayda cərimə artımı: +N bal") — bunlar system_limits-də, kod-
hardcode DEYİL. Yüksək bal aşkarlananda ƏVVƏLCƏ işçinin Store Manager-inə,
sonra HR_Admin-ə bildiriş.
**DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 9A — #24: ÇOX-MAĞAZA BENCHMARK DASHBOARD-U (GENİŞLƏNDİRİLMİŞ) — AGENT: benchmark-dashboard-engineer
===============================================================================
Mövcud Dashboard Builder-ə (C qərarına uyğun, AYRI ekran YARATMA) aşağıdakı
YENİ widget tiplərini əlavə et — hamısı YALNIZ 1C-siz, KompasOS-daxili
metriklərdən (cərimə, davamiyyət, xal balansı, overtime, turnover-balı)
qurulsun:

1. **Çox-Mağaza Reytinq Cədvəli (Ranking Table widget):** Bütün 21 filialı
   seçilmiş metrikə (dropdown: cərimə-sayı / davamiyyət-faizi / xal-
   balansı / overtime-saatı / turnover-riski) görə ən yaxşıdan ən pisə
   sıralayır. Sütunlar: sıra, mağaza adı, dəyər, ötən dövrlə müqayisədə
   ↑/↓ trend oxu.
2. **Mağaza-Qarşı-Şəbəkə-Ortalaması Qrafiki (Bar/Line widget):** Tək bir
   mağazanı seçib, onun göstəricisini bütün şəbəkənin ortalaması ilə yan-
   yana müqayisə edən sütun/xətt qrafiki (məs. "Yataş Babək-in cərimə
   sayı: 12, Şəbəkə ortalaması: 7").
3. **Zaman-üzrə Trend Widget-i:** Seçilmiş metrikin son 6 ay üzrə
   dəyişimini göstərən xətt qrafiki, filial-üzrə seçilə bilən (dropdown
   və ya çox-xətli müqayisə).
4. **Kritik-Kənar (Outlier) Kartı:** Şəbəkə ortalamasından statistik
   əhəmiyyətli dərəcədə (ROOT PARAMETRİ: standart-sapma həddi) kənar
   olan mağazaları avtomatik tapıb kiçik xəbərdarlıq-kartı kimi göstərir
   ("Diqqət: 3 filial cərimə göstəricisində ortalamadan 2×σ kənardır").

**DRILL-DOWN (aşağı-eniş) TƏLƏBİ:** Ranking Table-dakı hər mağaza sətrinə
kliklədikdə, həmin mağazanın öz Gündəlik Tabeli/Cərimə tarixçəsi ekranına
keçid versin (mövcud ekranları YENİDƏN QURMA, mövcud naviqasiyaya bağlan).

**GÖRÜNMƏ SCOPİNQİ (mövcud store-scoping pattern-inə tabe):** Bu widget-lər
YALNIZ bütün-şəbəkə görünüşünə malik rollara (Root/CEO/Admin/HR_Admin)
əlçatandır — `Mağaza_Meneceri` bu widget-i öz Dashboard-una əlavə edə
bilməz (mövcud "GÖRMƏK=SƏLAHİYYƏTİN OLMASI" prinsipini bura da tətbiq et).

Test yaz (hər widget tipi üçün, xüsusilə drill-down naviqasiyası üçün).
**DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 10 — ROOT-CONTROL TAM AUDİTİ (BÜTÜN PROQRAM) — AGENT: 10.1 özün et, 10.2 hardcode-value-auditor + root-control-migration-engineer
===============================================================================
Bu faza İKİ hissədən ibarətdir:

**10.1 — Bu promptdakı yeni funksiyalar:** Fazalarda (1-9A) yaradılan HƏR
"ROOT PARAMETRİ" işarəli dəyəri tap və cədvəl kimi göstər: [Parametr] |
[Hansı funksiya] | [ROOT Control Center-də GÖRÜNÜRMÜ (Bəli/Xeyr)] |
[Hardcode qalıb-qalmadığı].

**10.2 — BÜTÜN QALAN KOD BAZASI (YENİ, GENİŞ AUDİT):** Bu promptdan
ƏVVƏLKİ bütün fazalarda (permission sistemi, Shift Matrix, Fine/Points,
Face Control, Lisenziya modulu, Task Engine və s. — bütün mövcud kod)
`grep`/kod-analizi ilə sistemli axtarış apar: koda birbaşa yazılmış (magic
number) hər ədədi/müddəti/faizi/həddi tap (məs. dəqiqə, saat, faiz, AZN
məbləği, cəhd-sayı kimi görünən sabit ədədlər). Bunları da eyni cədvəl
formatında göstər. Bu, "12 yeni funksiya"dan kənar, BÜTÜN proqramın
tarixi hissəsini əhatə edir.

Hər iki hissədəki (10.1 və 10.2) Hardcode qalmış HƏR dəyəri indi ROOT
Control Center-ə köçür (bu, Faza 10-un əsas işidir, boş buraxılmasın).
Bundan sonra ROOT Control Center ekranını aç, HƏM yeni 12 funksiyanın, HƏM
DƏ tarixi kod bazasından tapılan parametrlərin HAMISININ orda göründüyünü
vizual təsdiqlə.

===============================================================================
FAZA 11 — TƏHVİL-VERMƏ
===============================================================================
1. `git diff --stat` ilə heç nəyin silinmədiyini təsdiqlə.
2. Tam `pytest` paketini işə sal, nəticəni göstər.
3. Git-də "expansion-12-features-v1" tag-i ilə commit et.
4. Yekun hesabat: 12 funksiyadan hansının tam, hansının qismən olduğu
   (cədvəl), + Faza 10-un ROOT-control cədvəli.

QAYDA: Hər fazadan sonra DAYAN, mən "davam et" deməyincə növbətiyə keçmə.
Hər faza YALNIZ öz mövzusuna aid işi görsün, əvvəlki fazaların kontekstini
təkrar yükləməsin (token-qənaəti üçün).
