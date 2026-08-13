KompasOS-a YENİ funksiyalar əlavə edirəm: #26-30 (Mağaza Ziyarəti/Audit,
İnsident Bildirişi, İllik Məzuniyyət Balansı, Toplu Əməliyyatlar,
Planlaşdırılmış İcra Xülasəsi) + Tabel Export-un TARİX-ARALIĞI çevikliyi +
HR-təcrübəli 7 export-yaxşılaşdırması (A-G). Sistemin əsas infrastrukturu
(RBAC, Hierarchy Guard, ROOT Control Center, Task Engine, Dashboard
Builder, Shift Matrix, Attendance/Bonus Export) ARTIQ HAZIRDIR. Bu prompt
YALNIZ əlavədir.

===============================================================================
QIRMIZI XƏTT
===============================================================================
Mövcud kodda artıq işləyən HEÇ BİR funksiyanı, cədvəli, ekranı, mexanizmi
SİLMƏ və ya YENİDƏN YAZMA. Kəsişmə tapsan — YENİSİNİ YARATMA, MÖVCUDU
GENİŞLƏNDİR, mənə "bunu mövcud [X] ilə birləşdirdim" kimi qısaca bildir.

===============================================================================
MƏRKƏZİ TƏLƏB — HƏR ŞEY ROOT-DAN İDARƏ OLUNMALIDIR (BÜTÜN PROQRAM ÜÇÜN)
===============================================================================
Bu qayda YALNIZ aşağıdakı yeni funksiyalara aid DEYİL — KompasOS-un
TAMAMİLƏ BÜTÜN kod bazasına aiddir. İstənilən yerdə konfiqurasiya edilə
bilən ədəd/qayda/çəki/həddi/vaxt (threshold, weight, rate, timeout,
duration, cap) TAPSAN — bu YENİ funksiyalara aid olsun-olmasın — KODA
HARDCODE QALMAMALIDIR, mövcud `system_limits`/ROOT Control Center
mexanizminə köçürülməlidir, YALNIZ Root dəyişdirə bilsin, hər dəyişiklik
audit-lənsin. "ROOT PARAMETRİ:" işarəli hər dəyər bunun bir hissəsidir,
amma BUNUNLA MƏHDUDLAŞMIR — FAZA 9 bütün proqramı əhatə edən tam
yoxlanışdır.

===============================================================================
STRUKTUREL QƏRARLAR (BUNLARI OXU, BAŞQA CÜR TİKMƏ)
===============================================================================

**A) #26 + #27 — VAHİD "FIELD REPORT" MEXANİZMİ:** Mağaza Ziyarəti/Audit
Checklist (#26) və İnsident Bildirişi (#27) FƏRQLİ görünsə də, EYNİ
strukturdur: strukturlaşdırılmış forma → (istəyə görə) foto-sübut →
avtomatik Task Engine-də düzəliş-tapşırığı → nəticə Dashboard-a düşür.
Bunları İKİ AYRI sistem kimi TİKMƏ — BİR "FieldReportUseCase" nüvəsi qur,
#26 və #27 bunun üzərində İKİ FƏRQLİ ŞABLON (template) kimi işləsin
(fərqli sahələr/kateqoriyalar, amma eyni axın: təqdim et → Task yarat →
izlə → bağla).

**B) #26-nın Task Engine İnteqrasiyası:** Uğursuz checklist-bəndi mövcud
Task Engine-in `can_assign_tasks`/`can_approve_task_evidence` axınını
İSTİFADƏ EDİR (yeni tapşırıq-sistemi YAZMA) — checklist sadəcə tapşırığı
avtomatik YARADIR, təsdiq/rədd mövcud mexanizmdə davam edir.

**C) #26-nın Benchmark Dashboard İnteqrasiyası:** Audit balı Faza 9A-da
(əvvəlki promptda) qurulmuş Dashboard Builder-ə YENİ bir widget-metrik
kimi əlavə olunur (AYRI ekran YARATMA).

**D) Tarix-Aralığı Export — LOCK MEXANİZMİ TOXUNULMAZ:** Attendance/
Bonus&Penalty export-larına tarix-aralığı seçimi əlavə edilərkən, mövcud
72-saatlıq etiraz pəncərəsi + REVERSED-istisna qaydası (Fayl 2-nin LOCK
mexanizmi) DƏYİŞMƏDƏN qalır — seçilmiş aralığın son günləri hələ open-
pəncərədədirsə, o cərimələr YENƏ DƏ avtomatik export-dan xaric edilir,
tarix-seçimi bu qaydanı BAYPAS ETMİR.

**E) Export-Backend/UI Ayrımı:** Tarix-aralığı, pro-rata hesablama, iş-
rejimi-norması (backend/hesablama, YÜKSƏK RİSK, `export-calculation-
engineer`) İLƏ pre-export doğrulama ekranı, delta-müqayisə, manual
düzəliş UI-ı, qeyd-sütunu, rol-filtri (UI/təcrübə, `export-ux-engineer`)
AYRI agentlərə bölünüb — bu, correctness-kritik hesablama məntiqini UI
dəyişikliklərindən təcrid edir.

===============================================================================
FAZA 0A — TOKEN-QƏNAƏT AYARLARI
===============================================================================
.claude/settings.json faylını yarat/redaktə et (mövcud ayarları SİLMƏDƏN —
əvvəlki promptlarda artıq varsa, təkrar əlavə etmə):

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
FAZA 0B — 10 SUBAGENT-İ YARAT (13-FEATURES PROMPTU İLƏ EYNİ STİL)
===============================================================================
.claude/agents/ qovluğunda bu 10 subagent-i yarat. 4-ü (`schema-migration-
engineer`, `rbac-flag-engineer`, `hardcode-value-auditor`, `root-control-
migration-engineer`) ƏVVƏLKİ 13-features promptunda TƏSVİR OLUNMUŞDUR —
əgər onlar artıq `.claude/agents/`-da mövcuddursa, YENİDƏN YARATMA, olduğu
kimi İSTİFADƏ ET. Yalnız YOXDURSA yarat (aşağıdakı təsvirlə).

--- 1. schema-migration-engineer (Faza 1) [mövcuddursa təkrar yaratma] ---
---
name: schema-migration-engineer
description: Yeni cədvəlləri miqrasiya kimi yazır və tətbiq edir.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: opus
---
Sən Senior Database Engineer-sən. Təsvir olunan bütün yeni cədvəlləri
miqrasiya kimi yaz, tətbiq et, test et. Mövcud cədvəlləri SİLMƏ/DƏYİŞDİRMƏ,
yalnız ƏLAVƏ et. AXTARIŞ MƏHDUDİYYƏTİ: YALNIZ src/ və schema.sql ilə işlə.

--- 2. rbac-flag-engineer (Faza 2) [mövcuddursa təkrar yaratma] ---
---
name: rbac-flag-engineer
description: Yeni permission flag-lərini mövcud RBAC-a inteqrasiya edir.
tools: Read, Write, Edit, Grep, Glob
permissionMode: default
model: sonnet
---
Sən RBAC Integration Engineer-sən. Yeni flag-ləri mövcud permission_flags
kataloquna əlavə et, mövcud Hierarchy Guard/Self-Escalation Guard-a
avtomatik tabe olduğunu təsdiqlə.

--- 3. field-report-engineer (Faza 3, YENİ) ---
---
name: field-report-engineer
description: #26 Mağaza Ziyarəti/Audit Checklist + #27 İnsident Bildirişi
  — vahid FieldReportUseCase nüvəsi üzərində iki şablon.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: opus
---
Sən Senior Full-Stack Engineer-sən. Struktur qərarı A və B-yə tam əməl
et: vahid FieldReportUseCase, mövcud Task Engine-i ÇAĞIRARAQ (yeni
tapşırıq-sistemi yazmadan) düzəliş-tapşırığı yaradır. Foto-sübut üçün
mövcud şəkil-yükləmə pattern-indən (profil şəkli/cərimə sübutu) istifadə
et. AXTARIŞ MƏHDUDİYYƏTİ: YALNIZ src/-də Task Engine ilə bağlı fayllara
bax, mövcud strukturu SİLMƏ.

--- 4. leave-balance-engineer (Faza 4, YENİ) ---
---
name: leave-balance-engineer
description: #28 İllik Məzuniyyət Balansı modulunu qurur.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: opus
---
Sən Senior Backend Engineer-sən. İllik məzuniyyət haqqı, accrual, carry-
over qaydalarını qur — HAMISI ROOT PARAMETRİ olsun. Sorğu-təsdiq axını
üçün mövcud Shift Swap Request təsdiq-pattern-indən istifadə et (yeni
approval-mexanizmi yazma).

--- 5. bulk-operations-engineer (Faza 5, YENİ) ---
---
name: bulk-operations-engineer
description: #29 Toplu (bulk) əməliyyatlar — CSV idxal, şablon-köçürmə.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: sonnet
---
Sən Backend Engineer-sən. CSV-əsaslı toplu işçi-idxalı və mağaza-şablon-
köçürmə alətini qur. Hər idxal əməliyyatı audit-lənsin.

--- 6. executive-digest-engineer (Faza 6, YENİ) ---
---
name: executive-digest-engineer
description: #30 Planlaşdırılmış İcra Xülasəsi — mövcud e-poçt fallback-ı
  ilə avtomatik gündəlik/həftəlik xülasə.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: sonnet
---
Sən Backend Engineer-sən. Mövcud e-poçt fallback servisini ÇAĞIRARAQ
(yeni bildiriş-sistemi yazmadan), cron-əsaslı xülasə generasiyası qur.

--- 7. export-calculation-engineer (Faza 7, YENİ) ---
---
name: export-calculation-engineer
description: Tarix-aralığı export, pro-rata hesablama, iş-rejimi-norması
  — CORRECTNESS-KRİTİK backend məntiqi.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: opus
---
Sən Senior Backend Engineer-sən (maliyyə-hesablama təcrübəli). Struktur
qərarı D-yə TAM əməl et: LOCK mexanizmi (72saat+REVERSED) tarix-aralığı
seçimindən ASILI OLMAYARAQ işləməlidir. Pro-rata hesablama və iş-rejimi-
norması mövcud Work Mode Builder-dən oxusun (təkrar yazma). Hər
hesablama üçün test yaz — xüsusilə sərhəd-halları (ayın ortasında
başlama/bitmə, dəyişən iş rejimi).

--- 8. export-ux-engineer (Faza 8, YENİ) ---
---
name: export-ux-engineer
description: Pre-export doğrulama ekranı, delta-müqayisə, manual düzəliş
  UI-ı, qeyd-sütunu, rol-filtri.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: sonnet
---
Sən Frontend/Full-Stack Engineer-sən. Mövcud Excel Export ekranını
GENİŞLƏNDİR (yeni ekran yaratma) — doğrulama-kartları, keçən-dövrlə-
müqayisə göstəricisi, manual düzəliş modalı (səbəb məcburi), qeyd-sütunu,
rol-filtri dropdown-u əlavə et.

--- 9. hardcode-value-auditor (Faza 9.2, AUDITOR) [mövcuddursa təkrar yaratma] ---
---
name: hardcode-value-auditor
description: Kod bazasında hardcode-edilmiş konfiqurasiya dəyərlərini
  tapır. YALNIZ tapır, düzəltmir.
tools: Read, Grep, Glob
permissionMode: plan
model: sonnet
---
Bu promptda yaradılan yeni kodda (və lazım gələrsə əvvəlki kodda) koda
birbaşa yazılmış ədəd/müddət/faiz/həddi tap. AXTARIŞ MƏHDUDİYYƏTİ:
Əvvəlcə `grep -l`, sonra `grep -n -A3 -B3`. SƏRT TAVAN: 8000 tokendan
çox işlətməyə başlasan, DAYAN, qismən hesabat ver.

--- 10. root-control-migration-engineer (Faza 9.2, FIXER) [mövcuddursa təkrar yaratma] ---
---
name: root-control-migration-engineer
description: hardcode-value-auditor-ın tapdığı dəyərləri ROOT Control
  Center-ə köçürür.
tools: Read, Write, Edit, Bash, Grep, Glob
permissionMode: default
model: opus
---
Sən Senior Platform Engineer-sən. Tapılan HƏR hardcode dəyəri system_
limits-ə köçür, kodu yenilə (silmə, yenilə). Test et.

`/agents` ilə hamısının qeydiyyatdan keçdiyini yoxla. "10 agent hazır və
işlək (bəziləri əvvəlki promptdan təkrar istifadə olundu)" de, sonra
FAZA 1-ə keç.

===============================================================================
FAZA 1 — SCHEMA — AGENT: schema-migration-engineer
===============================================================================
Miqrasiya yaz və tətbiq et:
- `field_reports` (id, type [STORE_AUDIT/INCIDENT], store_id, reported_by,
  category, detail, photo_refs, status, created_at) — #26+#27
- `field_report_checklist_items` (report_id, item_text, passed, is_blocking,
  photo_required) — #26-nın checklist-şablonu
- `annual_leave_balances` (employee_id, year, entitled_days, used_days,
  carried_over_days) — #28
- `annual_leave_requests` (employee_id, start_date, end_date, status
  [PENDING_APPROVAL/APPROVED/REJECTED], approved_by) — #28
- `bulk_import_log` (id, performed_by, file_ref, row_count, success_count,
  error_count, timestamp) — #29
- `store_templates` (id, name, based_on_store_id, config_snapshot) — #29
- `executive_digest_config` (recipient_role, frequency, metrics_included,
  last_sent) — #30
- `export_manual_corrections` (export_type, employee_id, date, field,
  old_value, new_value, reason, corrected_by, audit) — HR-yaxşılaşdırması D
- `work_modes` (id, name, start_time, end_time, daily_norm_hours, is_active,
  created_by) — YALNIZ ƏGƏR MÖVCUD DEYİLSƏ yarat (bax Faza 7, bənd 4);
  mövcuddursa bu sətri KEÇ, təkrar yaratma

Mövcud cədvəllərin başqa heç bir sütununu dəyişdirmə. Test et.
**DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 2 — İCAZƏ KATALOQU — AGENT: rbac-flag-engineer
===============================================================================
Mövcud kataloqa əlavə et:
- `can_conduct_store_audit` (#26)
- `can_report_incident` (#27, defolt: bütün rollar — hər kəs insident
  bildirə bilməlidir, YALNIZ HƏLLİ məhduddur)
- `can_manage_leave_balances` (#28, HR_Admin/Admin default)
- `can_perform_bulk_operations` (#29, YALNIZ Root/CEO/Admin — yüksək-
  təsirli əməliyyat)
- `can_manage_export_corrections` (HR-yaxşılaşdırması D, HR_Admin default)
- `can_configure_executive_digest` (#30, Root/CEO default)

Mövcud Hierarchy Guard-a bunları da tabe et.
**DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 3 — #26+#27: FIELD REPORT (MAĞAZA AUDİTİ + İNSİDENT) — AGENT: field-report-engineer
===============================================================================
1. `FieldReportUseCase` — vahid nüvə (Struktur Qərar A).
2. **#26 Mağaza Ziyarəti şablonu:** checklist-bəndləri (kateqoriya: təmizlik/
   vitrin/təhlükəsizlik/kassa), bəzi bəndlər `photo_required=true`.
   Uğursuz `is_blocking=true` bənd → mövcud Task Engine-də avtomatik
   düzəliş-tapşırığı (Struktur Qərar B). ROOT PARAMETRİ: audit-tezliyi
   xatırlatma-intervalı.
3. **#27 İnsident Bildirişi şablonu:** kateqoriya (oğurluq/qəza/avadanlıq/
   şikayət) + təfərrüat + foto (istəyə-bağlı). Kateqoriyaya görə marşrutlama
   qaydası ROOT PARAMETRİ (hansı kateqoriya hansı rola gedir).
4. Audit balı (#26) mövcud Dashboard Builder-ə yeni metrik kimi qoşulsun
   (Struktur Qərar C, AYRI ekran YARATMA).
5. GUI: mobil-dostu forma ekranı (kiosk-dan fərqli, admin/manager-tier
   üçün), checklist üçün addım-addım naviqasiya.

Test yaz. **DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 4 — #28: İLLİK MƏZUNİYYƏT BALANSI — AGENT: leave-balance-engineer
===============================================================================
1. `AnnualLeaveBalanceUseCase` — ROOT PARAMETRİ: baza illik haqq (gün),
   staj-əsaslı əlavə gün qaydası (əgər olacaqsa), carry-over maksimum
   həddi, "istifadə et ya itir" son-tarixi.
2. `AnnualLeaveRequestUseCase` — mövcud Shift Swap Request təsdiq-
   pattern-i ilə EYNİ struktur (PENDING_APPROVAL → APPROVED/REJECTED,
   `can_manage_leave_balances` sahibi təsdiqləyir).
3. GUI: İşçi Ana Ekranında balans-kartı ("14/21 gün qalıb") +
   "[Məzuniyyət Sorğusu]" düyməsi. HR panelində təsdiq-inbox-u.
4. **DİQQƏT:** Bu, mövcud STEP1/STEP2 (gündaxili icazə) VƏ Shift Matrix
   off-day sistemi ilə QARIŞDIRILMASIN — illik məzuniyyət TAM AYRI, uzun-
   müddətli bir konseptdir.

Test yaz. **DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 5 — #29: TOPLU ƏMƏLİYYATLAR — AGENT: bulk-operations-engineer
===============================================================================
1. CSV-əsaslı toplu işçi-idxalı: fayl yüklə → validasiya-önizləmə (sətir-
   sətir xəta göstər) → təsdiq → idxal. Uğursuz sətirlər ayrıca göstərilir,
   uğurlu sətirlər idxal olunur (hamısı-ya-heçnə YOX, qismən idxal OLA
   bilər, hesabat aydın olsun).
2. Mağaza-şablon-köçürmə: mövcud bir mağazanın rol/shift-quruluşunu yeni
   filial üçün əsas kimi köçürür (`can_perform_bulk_operations`).
3. Hər idxal/köçürmə tam audit-lənir.

Test yaz. **DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 6 — #30: PLANLAŞDIRILMIŞ İCRA XÜLASƏSİ — AGENT: executive-digest-engineer
===============================================================================
1. Cron-əsaslı (mövcud cron-pattern) gündəlik/həftəlik xülasə — mövcud
   e-poçt fallback servisini ÇAĞIRARAQ göndərilir.
2. ROOT PARAMETRİ: tezlik (gündəlik/həftəlik), hansı metriklərin daxil
   olacağı (cərimə-sayı, açıq-istisna-sayı, gecikən-check-in-sayı və s.
   — toggle-lənə bilən siyahı).
3. `can_configure_executive_digest` sahibi Root Control Center-dən bu
   ayarları dəyişdirir.

Test yaz. **DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 7 — EXPORT HESABLAMA MƏNTIQI (TARİX-ARALIĞI, PRO-RATA) — AGENT: export-calculation-engineer
===============================================================================
1. Mövcud Attendance Report VƏ Bonus&Penalty Report export-larına tarix-
   aralığı seçimi əlavə et: `[Tam Ay]` (mövcud davranış, DƏYİŞMƏDƏN) VƏ
   `[Xüsusi Aralıq]` (başlanğıc+bitmə tarix seçicisi).
2. "Norma İş Günləri" seçilmiş aralığa görə DİNAMİK hesablanır (mövcud
   Shift Matrix-ə əsasən, sabit aylıq norma YOX).
3. **Pro-Rata:** işçi aralığın ortasında işə başlayıb/bitiribsə, norma
   proporsional hesablanır (avtomatik, əl-düzəlişi TƏLƏB ETMİR).
4. **İŞ REJİMİ (GÜNDƏLİK İŞ SAATLARI) YARATMA EKRANI — ÇATIŞMAZLIQ
   DÜZƏLİŞİ (MÖVCUD DEYİLSƏ TİK, SADƏCƏ "YOXLA" DEYİL):** Əvvəlcə
   YOXLA — "İş Rejimləri" (Work Mode) kataloqu artıq kodda mövcuddurmu
   (`can_manage_work_modes` flag-i, adlandırılmış şablonlar)? ƏGƏR
   YOXDURSA (ya da qismən/natamamdırsa), bunu İNDİ TİK, sonrakı addımlara
   keçmə:
   - Sadə forma: `[Ad]` (məs. "Səhər Növbəsi") + `[Başlanğıc Saatı]` +
     `[Bitmə Saatı]` — konkret nümunələr: **"9:00–15:00"**, **"09:00–
     18:00"**. Gündə bir neçə fərqli iş-saat şablonu yaradıla bilsin
     (limitsiz sayda).
   - `can_manage_work_modes` sahibi (defolt Root/CEO) bu şablonları
     yaradır/redaktə edir/deaktiv edir.
   - Şablonlar Shift Matrix-də işçiyə növbə təyin edilərkən dropdown-dan
     seçilə bilsin (mövcud Shift Matrix ekranına bu dropdown-u əlavə et,
     əsas təyinetmə məntiqini YENİDƏN YAZMA).
   - Hər şablonun saat-fərqindən (bitmə−başlanğıc) avtomatik "gündəlik
     norma saatı" hesablanır — bu, aşağıdakı Pro-Rata VƏ Overtime
     hesablamalarının (əvvəlki promptdan) əsasını təşkil edir.
   Bu ekran tikildikdən SONRA, aşağıdakı hesablama bundan oxusun:
5. **İş-Rejimi-Norması:** hesablama YUXARIDAKI (yeni və ya mövcud) Work
   Mode Builder-dən (tam-ştat/yarım-ştat/fərqli-saat şablonları) oxusun —
   hər işçinin təyin edilmiş iş rejiminə görə fərqli norma hesablansın.
6. **LOCK MEXANİZMİ (Struktur Qərar D, KRİTİK):** Bonus&Penalty export-
   unda, seçilmiş aralığın son günləri hələ 72-saatlıq etiraz pəncərəsindən
   keçməyibsə, o cərimələr YENƏ DƏ avtomatik xaric edilir — bunu YOXLA,
   tarix-aralığı seçimi bu qaydanı pozmasın.
7. ROOT PARAMETRİ: maksimum aralıq uzunluğu (performans qorunması üçün).

Test yaz — xüsusilə sərhəd-halları (ayın ortasında işə başlama, dəyişən
iş rejimi, aralığın son günü açıq-pəncərədə cərimə). **DAYAN, nəticəni
göstər, təsdiq gözlə.**

===============================================================================
FAZA 8 — EXPORT TƏCRÜBƏSİ (DOĞRULAMA, MÜQAYİSƏ, DÜZƏLİŞ) — AGENT: export-ux-engineer
===============================================================================
1. **(A) Pre-Export Doğrulama Ekranı:** Excel yaranmazdan ƏVVƏL, sistem
   şübhəli sətirləri qırmızı işarələyir: aralıqdan çox iş-günü olan işçi,
   deaktiv-amma-tabeldə-görünən işçi, "0 gün işləyib, 0 icazəsiz-qayıb"
   ziddiyyəti, mağaza-üzrə anomal yüksək icazəsiz-qayıb. HR "[Təsdiqlə və
   Export Et]" ilə davam edir.
2. **(D) Manual Düzəliş:** `can_manage_export_corrections` sahibi export-
   öncəsi konkret gün/işçi sətrinə düzəliş edə bilir — səbəb-sahəsi
   MƏCBURİ, `export_manual_corrections`-a yazılır, tam audit-lənir.
3. **(E) Qeyd Sütunu:** Export-un özündə hər sətir üçün istəyə-bağlı
   sərbəst-mətn "Qeyd" sütunu.
4. **(F) Dövr-üzrə Müqayisə:** Pre-export ekranında, keçən eyni-uzunluqda
   dövrlə müqayisədə fərq göstərilir (məs. "icazəsiz-qayıb: +3, keçən
   dövrdən"). ROOT PARAMETRİ: "əhəmiyyətli fərq" hesab olunan həddi.
5. **(G) Rol-Filtri:** Export ekranında rol/vəzifə-üzrə filtr dropdown-u
   (məs. "yalnız Satıcı rolunu export et").

Test yaz (dark/light hər ikisində). **DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 9 — ROOT-CONTROL TAM AUDİTİ (BÜTÜN PROQRAM)
===============================================================================
**9.1 — Bu promptdakı yeni funksiyalar (özün et):** Fazalarda (1-8)
yaradılan HƏR "ROOT PARAMETRİ" işarəli dəyəri tap və cədvəl kimi göstər:
[Parametr] | [Funksiya] | [ROOT Control Center-də görünürmü] | [Hardcode
qalıb-qalmadığı].

**9.2 — BÜTÜN QALAN KOD BAZASI — AGENT: hardcode-value-auditor +
root-control-migration-engineer:** Bu promptdan ƏVVƏLKİ bütün kodu (əgər
əvvəlki 13-features promptunun öz Faza 10-u artıq bunu etməyibsə) eyni
metodla tara, tapılanları köçür.

Hər iki hissədəki hardcode qalan dəyəri ROOT Control Center-ə köçür.
ROOT Control Center ekranını aç, HAMISININ göründüyünü vizual təsdiqlə.
**DAYAN, nəticəni göstər, təsdiq gözlə.**

===============================================================================
FAZA 10 — TƏHVİL-VERMƏ
===============================================================================
1. `git diff --stat` ilə heç nəyin silinmədiyini təsdiqlə.
2. Tam `pytest` paketini işə sal, nəticəni göstər.
3. Tam axını simulyasiya et: mağaza-audit checklist doldur → uğursuz
   bənddən Task yaranmasını yoxla → illik-məzuniyyət sorğusu göndər-
   təsdiqlə → aprel 1-15 aralığı ilə Attendance export et → pre-export
   doğrulama ekranını gör.
4. Git-də "expansion-hr-ops-v1" tag-i ilə commit et.
5. Yekun hesabat: hansı funksiyanın tam/qismən olduğu (cədvəl) + Faza
   9-un ROOT-control cədvəli.

QAYDA: Hər fazadan sonra DAYAN, mən "davam et" deməyincə növbətiyə keçmə.
