# KompasOS — Claude Code Execution Rules

Enterprise Leave / Fine / Break / Shift / ERP-1C / Task / Dashboard sistemi.
Bu fayl kodun necə yazıldığını izah edir — NƏ yazılacağını spesifikasiya deyir.

---

## 0. Spesifikasiya faylları İŞÇİ AĞACINDA YOXDUR

`kompasos.md`, `kompas1.md`, `kompasos11.md`, `uxui.md`, `facecontrol.md`,
`nahar.md`, `Rootpanel.md`, `audit.md`, `1c.md`, `design.md`, `test.md` —
hamısı repozitoriyadan ÇIXARILIB. Kodda və şərhlərdə onlara olan
istinadlar QALIR və qəsdəndir: hər şərh hansı tələbin hansı sənəddən gəldiyini
göstərir — bu, "niyə belədir" sualının cavabıdır və faylın mövcudluğundan asılı
deyil.

Mətnin özü git tarixçəsindədir. Bərpa (nümunə `kompasos.md` üçün):

```bash
git show "$(git rev-list -1 HEAD -- kompasos.md)^:kompasos.md" > kompasos.md
```

**Faylı açmağa cəhd etmə** — yoxdur. Lazım olarsa yuxarıdakı əmrlə bərpa et,
işini bitirdikdən sonra isə repozitoriyaya QAYTARMA (silinmə qəsdlidir).

Eyni qayda `design_reference/*.jpg` referans skrinşotlarına da aiddir: onlar
`.png` dəsti ilə əvəzlənib. `tokens.py`, `primitives.py` və
`scripts/check_symmetry.py`-dəki `design_reference/dashboard.jpg` tipli
istinadlar həmin ölçünün HANSI maketdən gəldiyini deyir — ölçü qərarının
sübutudur, açılacaq fayl deyil.

### `.claude/agents/` — 47 tərif → 4 rol agenti → BEŞ sahə teammate-i

Vəzifəyə görə bölünmüş 47 subagent (`domain-logic-engineer`,
`anti-fraud-auditor`, `pyside-ui-engineer`, …) çıxarılıb: hər biri layihənin
bir küncünə bağlı idi, ona görə sayı fasiləsiz artırdı və heç biri tam
kontekst görmürdü. Yerinə əvvəlcə **rola görə** dörd agent gəldi
(`planner` / `ui-agent` / `builder` / `reviewer`, commit `5dc3443`) — həmin
dəst də `814059c`-də ƏVƏZLƏNDİ.

**Rol bölgüsü niyə tutmadı:** eyni faylı üç agent kəsirdi — `planner` oxuyur,
`builder` yazır, `reviewer` yenidən oxuyur; hər üçü eyni konteksti sıfırdan
qurmalı olurdu. Daha pisi: faylın SAHİBİ yox idi, ona görə iki agent eyni anda
`authorization.py`-a toxuna bilərdi və ikincisi birincinin işini sükutla
üstələyirdi. **Sahəyə görə** bölgüdə hər faylın BİR sahibi var — toqquşma
sükutlu üst-yazma yox, mesaj olur.

| Teammate | Model | SAHİBLİYİ (YALNIZ bunu redaktə edir) |
|---|---|---|
| `domain` | sonnet | `src/domain/`, `src/application/use_cases/` |
| `infra` | sonnet | `src/infrastructure/`, `database/`, config, `.spec`, `installer/` |
| `security` | sonnet | `authorization.py`, `entities/position.py`, `src/infrastructure/security/`, `scripts/`, RLS qaydalarının MƏZMUNU |
| `ui` | sonnet | `src/presentation/` (ekran, kontroller, widget, tokenlər, QSS) |
| `qa` | sonnet | **YALNIZ `tests/`** |

### QA-FULL dəsti — ÜÇ ƏLAVƏ agent (`qamanual.md`)

`qamanual.md` proqramı üçün istifadəçi ÜÇ agent daha istədi. Onlar sahə
bölgüsünü POZMUR — heç birinin öz faylı yoxdur, hər biri TAPIR və sahibinə
`SendMessage` göndərir (yalnız `e2e-test-engineer` `tests/`-ə yazır):

| Teammate | Nə edir | Düzəlişi kim edir |
|---|---|---|
| `performance-profiling-engineer` | Millisaniyə və sorğu sayı ölçür (Faza 5) | tapıntının sahibi |
| `e2e-test-engineer` | Hər ekranı/düyməni REAL işə salır (Faza 3/4) | tapıntının sahibi; testi ÖZÜ yazır |
| `crash-stability-engineer` | Sürətli klik, ekstremal input, şəbəkə kəsilməsi (Faza 6) | tapıntının sahibi |

**Niyə vəzifə-agenti qadağası bunlara aid deyil:** silinən 47 agent FAYL
SAHİBİ idi — ona görə eyni faylı üç agent kəsirdi. Bunlar sahib deyil,
ÖLÇÜCÜdür. Sahiblik cədvəli dəyişməz qalır.

Alət dəsti hamısında eynidir (`Read, Grep, Glob, Edit, Write, Bash`) — fərq
alətdə YOX, SAHƏDƏDİR. Qəsdli qaydalar:

* **Başqasının faylını dəyişmək qadağandır** — `SendMessage` göndərilir.
* **`qa` heç bir `src/` faylına toxunmur:** tapır, sahibinə bildirir, düzəlişi
  sahibi edir. Test yazan və kodu düzəldən eyni agent olsaydı, test düzəlişə
  uyğunlaşdırılardı — lazım olan isə əksidir.
* **Schema dəyişikliyini YALNIZ `infra` edir** (`security` nəyin lazım olduğunu
  deyir), çünki miqrasiya faylı ilə `schema.sql` pariteti (§7) bir əldə
  qalmalıdır.
* Heç birində `Task` aləti YOXDUR — agent agenti çağıra bilmir, bütün
  koordinasiya əsas sessiyadan keçir.
* Heç biri `git commit` / `git push` etmir — commit yalnız əsas sessiyadan.

Hər tərifdə `thinking_budget: 4090` var: audit dövrələrində teammate-lər
dayaz qərar verirdi. **Qeyd:** bu açarın CLI tərəfindən oxunduğu
sənədləşdirilməyib — tanınmasa sükutla nəzərə alınmır, yəni zərəri yoxdur.

Skill-lər `.claude/skills/`-dədir. Layihəyə xas ÜÇÜ — `kompasos-architecture`,
`kompasos-security`, `kompasos-ui` — teammate işə başlamazdan əvvəl öz sahəsinə
uyğun olanı oxuyur. Ümumi ÜÇÜ: `tdd`, `senior-code-review`, `ui-ux-pro-max`.
Sonuncunun adı `code-review` DEYİL, çünki built-in `/code-review` əmri ilə
toqquşurdu və çağırışda hansının işə düşəcəyi qeyri-müəyyən qalırdı.

`.claude/hooks/ruff_fix.py` — `PostToolUse` hook-u (`Write|Edit`):
`src/`, `tests/`, `scripts/` altındakı hər `.py` faylına yazıdan DƏRHAL
sonra `ruff check --fix` + `ruff format` işlədir. `jq` bu maşında YOXDUR,
ona görə stdin JSON-u Python ilə oxunur. Hook heç vaxt BLOKLAMIR — `ruff`-un
düzəldə bilmədiyi xəta onsuz da §2 qapılarında görünür.

**İşə salınma qaydası DƏYİŞMƏYİB: subagent yalnız istifadəçi ONU AÇIQ
İSTƏDİKDƏ işə düşür** — nə «paralel gedər», nə «token qənaət edər» mülahizəsi
ilə. Tərif fayllarındakı «Use PROACTIVELY» ifadəsi bu qaydanın ALTINDADIR və
avtomatik çağırışa icazə vermir: o cümlə agentin nə vaxt FAYDALI olduğunu
izah edir, nə vaxt öz-özünə qalxacağını yox.

Köhnə tapşırıq şablonlarında (`prompt/*.md`, `dbtest/*.md`) duran
«FAZA 0 — AGENT (VARSA TƏKRAR YARATMA)» bloku HƏLƏ DƏ KEÇƏRSİZDİR: o mətn
silinmiş 47-lik dəsti nəzərdə tuturdu. Blok atlanır və FAZA 1-dən başlanır.

Kod şərhlərində qalan «agent qaydası 4», «agent tərifi, 4 sual» tipli
istinadlar da həmin köhnə dəstə aiddir — qərarın haradan gəldiyinin
sübutudur, çağırılacaq agent deyil. Mətnləri git tarixçəsindədir (`HEAD`
DEYİL, silinmədən ƏVVƏLKİ commit):
`git show 5dc3443^:.claude/agents/anti-fraud-auditor.md`, rol dəsti üçün isə
`git show 814059c^:.claude/agents/planner.md`.

---

## 1. Vəziyyət

**Altı fazanın hamısının qatları yazılıb.** Faza qapıları artıq YOXDUR — hər
dəyişiklik istənilən qatı toxuna bilər, şərti yalnız aşağıdakı keyfiyyət
qapıları qalır.

| Faza | Əhatə |
|---|---|
| 1 | DDD strukturu, Event Bus, DI, Saga, logger, şifrələmə, `schema.sql`, CI/CD |
| 2 | Domen entity-ləri, use case-lər, Guard-lar, Plugin API, NavigationRegistry |
| 3 | Supabase repo-ları, 1C konnektorları, offline buffer, lisenziya, auto-update |
| 4 | PySide6 örtük, Kiosk, Camera Dashboard, dizayn sistemi, kompozisiya kökü |
| 5 | Root/CEO panelləri, növbə/tabel/cərimə modulları, özünə-xidmət alətləri |
| 6 | Satış xalları, şübhəli satış növbəsi, hesabatlar, Developer Paneli |

Faza siyahısının bənd-bənd vəziyyəti: [`README.md`](README.md).

---

## 2. Keçilməli qapılar

Hər dəyişiklikdən sonra HAMISI keçməlidir:

```bash
.venv/Scripts/python.exe -m ruff check src/ tests/ scripts/
.venv/Scripts/python.exe -m ruff format src/ tests/ scripts/
.venv/Scripts/python.exe -m mypy src            # strict, 100% type hints (372 fayl)
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/ -q  # 5665 test, 50 skip
.venv/Scripts/python.exe scripts/check_contrast.py --include-high-contrast
```

Dəstin FAKTİKİ müddəti bu maşında **~58 dəqiqədir** (ölçüldü: 3477 saniyə,
tək başına işləyəndə). Paralel ikinci pytest prosesi işə salınsa müddət
İKİ-ÜÇ dəfə uzanır — dövrə-4-də üç proses eyni anda işlədi və dəst saatlarla
çəkdi. Ona görə tam dəst TƏK işlədilir.

**`QT_QPA_PLATFORM=offscreen` OPSİYONAL DEYİL.** Bu maşında real Windows
platform plagini ilə e2e Qt testləri dəqiqədə ~4 test sürətinə düşür — tam
dəst saatlarla çəkir və "asmış" kimi görünür. Yuxarıdakı ~58 dəqiqə məhz
offscreen ölçüsüdür: dəsti fon işi kimi başladıb gözləmək lazımdır, "asmış"
saymaq yox. Yeganə fərq: `test_mono_role_resolves_to_a_fixed_pitch_font`
atlanır (aşağıya bax).

Kontrast yoxlayıcısı **160 rəng cütünü** (`--include-high-contrast` olmadan
158) ölçür — həm `tokens.py` cütlərini,
həm də `qss.py`-dəki FAKTİKİ istifadəni (`::placeholder`, `:disabled`,
`:focus`, `:hover`, sərhədlər). Yalnız tokenləri yoxlamaq kifayət etmirdi:
dörd kontrast qüsuru məhz bu boşluqda gizlənmişdi. **Bu rəqəm dəyişkəndir** —
yeni rəng cütü və ya yeni QSS selektoru əlavə edən skriptin son sətrindən
cari sayı oxuyub bu bəndi yeniləməlidir (eyni köhnəlmə riski
`.design-sync/NOTES.md`-dədir).

Domen coverage qapısı **85%** (hazırda 94.22%):

```bash
.venv/Scripts/python.exe -m pytest tests/unit \
  --cov=src/domain --cov=src/shared --cov=src/infrastructure/security \
  --cov-fail-under=85
```

**Qeyd:** `.venv/Scripts/python.exe` işlədin — sistem Python-unda `pytest`
yoxdur. Windows konsolunda Azərbaycan hərfləri üçün `PYTHONIOENCODING=utf-8`.

`test_mono_role_resolves_to_a_fixed_pitch_font` `QT_QPA_PLATFORM=offscreen`
altında bu maşında **atlanır** (monospace şrift həll olunmur) — mühit
xüsusiyyətidir, reqressiya deyil.

**Təqdimat qatı ARTIQ coverage-dən çıxarılmır.** `pyproject.toml:269`-da
`omit` yalnız `*/__init__.py`-dır — köhnə `omit = ["*/presentation/*"]` istisnası
silinib (səbəbi həmin faylın şərhindədir: yazı kontrollerləri sırf Python
məntiqidir və istisna məhz ən riskli yolları hər hesabatdan çıxarırdı).
`--cov-config` DAHA LAZIM DEYİL — `--cov=src.presentation.controllers` birbaşa işləyir.

**LAKİN ölçülən ≠ örtülən.** Dövrə-2 auditinin ölçüsü: kontroller qatı cəmi
**57%** (6159 sətir), və **10 kontroller LİTERAL 0%-dir** — `announcements`,
`attrition_risk`, `devices`, `employee_documents`, `open_shift`,
`performance_review`, `plugin_page`, `pos_threshold`, `sales_points`, `tasks`.
Onlardan **8-i `.commit()` çağıran həqiqi YAZI yoludur**, 5-inin adı `tests/`
daxilində ÜMUMİYYƏTLƏ çəkilmir. `test_screen_binding_coverage.py` bəzilərini
ADLA xatırladır, amma ÇAĞIRMIR — görünüş aldadıcıdır. Yeni kontroller yazarkən
bu siyahıya baxın: qat «test edilib» görünür, o yollar isə edilməyib.

---

## 3. Arxitektura qaydaları

### Qat sırası pozulmur

```
domain  ←  application  ←  infrastructure
   ↑            ↑                ↑
   └────────────┴──── presentation
```

* `domain/` heç vaxt `psycopg`, `supabase`, `httpx`, `PySide6` idxal etmir.
* Portlar `domain/interfaces/ports.py`-da `Protocol` kimi TƏYİN OLUNUR,
  `infrastructure/`-da İMPLEMENTASİYA olunur (miras YOX, structural typing).
* Port yalnız domen tipləri qaytarırsa `ports.py`-a gedir. Tətbiq qatının
  strukturunu qaytarırsa (məs. `ReportFactProvider`) **use case faylının
  yanında** təyin olunur — əks halda domen → application asılılığı yaranar.

### Modullar bir-birinə birbaşa müraciət etmir

Domen hadisələri `shared/event_bus.py` üzərindən keçir. Entity-lər hadisəni
DƏRHAL yaymır — `AggregateRoot.record_event()` ilə toplayır, use case commit-dən
SONRA `collect_events()` ilə götürür. Rollback halında hadisə heç vaxt yayılmır.

Repository-dən BƏRPA edilən aqreqat hadisə YAYMAMALIDIR — konstruktorlarda
`emit_created_event=False` ötürülür.

### Çox-aqreqatlı əməliyyat = Saga

`LeaveVerificationUseCase.verify_return` naxışdır: status + cərimə + audit bir
Saga altındadır, uğursuzluqda kompensasiya işə düşür və əməliyyat
`PENDING_RECONCILIATION`-a keçir. Tək aqreqata toxunan əməliyyat Saga TƏLƏB
ETMİR (bax `morning_check_in.py` başlığı).

---

## 4. Kod yazma qaydaları

### Placeholder QADAĞANDIR

`# TODO`, `pass  # sonra`, `raise NotImplementedError` (Protocol imzasından
başqa) yazılmır. Hər fayl istehsalata hazır və tam yazılmış olmalıdır.

### Şərhlər NİYƏ-ni izah edir, NƏ-ni yox

Bu layihənin əsas üslub xüsusiyyəti budur. Hər modul başlığında və qeyri-aşkar
qərarların yanında **niyə belə seçildiyi və alternativin niyə rədd edildiyi**
yazılır. Nümunə (`catalogs.py`):

> SOFT DELETE NİYƏ MƏCBURİDİR — Fiziki `DELETE` keçmiş cərimənin növünü
> "naməlum"a çevirərdi; həmin cərimə isə real pul kəsintisidir və mübahisə
> halında nəyə görə verildiyi SÜBUT edilə bilməlidir. Ona görə `deactivate()`
> var, `delete()` yoxdur.

Yeni kod yazarkən mövcud fayllardakı şərh sıxlığını və tonunu təkrarlayın.

### Dil

Bütün şərhlər, docstring-lər, istifadəçi mesajları və log açarları **Azərbaycan
dilindədir** (bölmə 9: yeganə interfeys dili). Ruff-un `RUF001/002/003`
qaydaları məhz buna görə söndürülüb. Sinif/metod adları ingiliscədir.

### `str, Enum` qəsdəndir

`StrEnum`-a keçid `str(X.A)` nəticəsini dəyişir və audit/log çıxışına təsir edə
bilər. Açıq `.value` istifadə edilir.

### Vaxt

Bütün `datetime` **tz-aware** olmalıdır. Domen kodu `datetime.now()` ÇAĞIRMIR —
`Clock` portu istifadə olunur ki, vaxt-həssas qaydalar (timeout, lockout, etiraz
pəncərəsi) determinstik test oluna bilsin. `require_aware()` sərhəddə yoxlayır.

### SQL

100% parameterləşdirilmiş (`%s`). Dinamik `WHERE` şərtləri yalnız SABİT sətir
siyahısından qurulur və `# noqa: S608 — şərtlər sabit siyahıdandır` şərhi ilə
işarələnir.

---

## 5. Təhlükəsizlik zəmanətləri (HARDCODED — dəyişdirilmir)

Bunlar "modul" DEYİL, struktur zəmanətlərdir və Feature Toggle ilə söndürülə
bilməz (`docs/security_decisions.md`):

* **Anti-fraud vəzifə ayrılığı** — `can_verify_returns`, `can_override_return_time`,
  `can_issue_fines`, `can_approve_dual_control_override` heç vaxt
  `Mağaza_Meneceri`/`Satıcı`-ya verilmir.
* **SEC-001** — kamera-tipli rol dual-control təsdiqini daşıya bilməz.
* **Strict Hierarchy Guard** — yalnız CİDDİ ŞƏKİLDƏ aşağı pilləyə toxunmaq olar.
* **Self-Escalation Guard** — aktor yalnız ÖZÜNDƏ olan flag-i verə bilər.
* **Dörd-səviyyəli hardlock** — `HardlockLevel` (`authorization.py`).
* **Vaxt-möhürü client-dən qəbul edilmir (TIME-1)** — `created_at` (cərimə,
  etiraz, icazə, davamiyyət) və `fines.published_at` `BEFORE INSERT/UPDATE`
  trigger-i ilə server vaxtına MƏCBUR edilir (`migrations/062`). Bu qayda da
  İKİ yerdədir: DB trigger-ində və tətbiqdə (`Clock` portu artıq
  `ServerTimeService`-dir, yəni Windows saatı dəyişsə də vaxt sürüşmür).
  `DEFAULT now()` tək başına KİFAYƏT ETMİR — sütunun adı `INSERT`-də açıq
  çəkiləndə default yan keçilir və repozitoriyaların bir qismi məhz belə
  yazırdı.

Hər qayda İKİ yerdə var: domendə (`value_objects/authorization.py`) və DB
trigger-ində (`schema.sql` §18). Birini dəyişəndə DİGƏRİ də dəyişməlidir.

**Audit yazısı istisna udmur.** `AuditTrail.record()` uğursuz olarsa bütün
əməliyyat geri qaytarılır — məcburi olan bir şeyin sükutla buraxılması onu
məcburi olmaqdan çıxarır.

### Bunlardan KƏNARDA qalan hər şey soft-coded-dir (bölmə 3)

Yeni sabit ədəd yazmazdan əvvəl özünüzə sual verin: bu, yuxarıdakı struktur
zəmanətlərdən biridirmi? Deyilsə, yeri `system_limits`-dədir.

| Nə | Hara yazılır | Kodda oxunur |
|---|---|---|
| Limit / taymaut | `SystemLimitKey` + `DEFAULT_LIMITS` (`policies.py`) | `SystemLimits` portu ilə, `_limit_int(...)` |
| Modul açarı | `FeatureModule` (`policies.py`) | `FeatureToggles.is_enabled(...)` |
| Yeni icazə flag-i | `permission_flags` (GUI-dan, Root) | `Employee.has_permission(...)` |

Sinifdəki sabit YALNIZ **fallback** ola bilər (məs. `MIN_APPEAL_SLA_HOURS`,
`MAX_UPLOAD_BYTES`, `DUAL_CONTROL_THRESHOLD_MINUTES`) və şərhində bunun
fallback olduğu, həqiqi mənbənin isə `system_limits` olduğu YAZILMALIDIR.

### ÜÇÜNCÜ hal: «Root parametri DEYİL» — qəbul edilmiş qərar

Bəzi sabitlər nə fallback, nə də struktur zəmanətdir: onlar TƏRİFİN özüdür və
Root-a verilsəydi mənasını itirərdi. DB-2 hardcode auditi onları bir-bir
nəzərdən keçirdi; siyahı BAĞLIDIR — yeni sabit bura yalnız eyni müzakirədən
sonra əlavə olunur:

| Sabit | Yer | Niyə Root parametri deyil |
|---|---|---|
| `_IDENTIFY_MARGIN = 0.08` | `face_control.py` | Anti-spoofing ayırma payı — Root onu sıfıra endirsəydi 1:N girişi «ən yaxın üz»ə çevrilərdi |
| `MISMATCH_LOOKBACK_DAYS = 7` | `face_control.py` | Sorğu pəncərəsi, siyasət deyil (lockout həddi ayrıca Root açarıdır) |
| `LOW_CONFIDENCE_LOOKBACK_DAYS = 1` | `controllers/screen_data.py` | Ekranın «bu gün» tərifi |
| `_WEEKLY_DEDUPE_GAP_DAYS = 6` | `executive_digest.py` | «Həftəlik» sözünün tərifi |
| `_WINDOW_MARGIN_DAYS = 1` | `labor_compliance.py` | Sərhəd gününün ehtiyatı; əsas hədd `LABOR_MAX_CONSECUTIVE_WORK_DAYS`-dədir |
| `PANEL_LIMIT = 50` | `notification_repositories.py` | 620px panel hündürlüyünün nəticəsi, biznes həddi deyil |
| `_DAYS_PER_MONTH = 30` | `attrition_repository.py` | Domendəki eyni təxminin güzgüsü — ikisi birlikdə dəyişməlidir |
| `RESET_MONTHS = (1, 7)` | `gamification.py` | Mühasibatlıq yarımillikləri — təqvim faktı |
| `FRESHNESS_INTERVAL_MULTIPLIER = 2.0` | `server_time.py` | Sinxronizasiya intervalının NƏTİCƏSİ, ayrıca siyasət deyil: bir buraxılmış dövr hələ nasazlıq deyil, ikisi artıq nasazlıqdır. Root-a verilsəydi interval ilə ziddiyyətli qoşa dəyər yaranardı |
| `SHORT_CODE_LENGTH = 6`, `SHORT_CODE_ALPHABET` | `devices.py` | İnsan erqonomikasının ölçüsü: kod TELEFONLA söylənilir. Root onu 3-ə endirsəydi toqquşma real olardı, 20-yə qaldırsaydı kodun bütün mənası itərdi |
| `SHORT_CODE_ATTEMPTS = 5` | `device_registry.py` | Riyazi zərurət, siyasət deyil — sonsuz dövrədən qoruyan tavan |
| `HARDWARE_PROBE_TIMEOUT_SECONDS = 8.0` | `device_identity.py` | Tətbiqin AÇILIŞ yolundadır: Root dəyərini oxumaq üçün baza lazımdır, baza isə hələ açılmayıb — dövri asılılıq |
| `DUPLICATE_SUBMISSION_WINDOW_SECONDS = 10` | `fine_management.py` | Bir kliklə iki göndəriş arasındakı insan reaksiya pəncərəsi, siyasət deyil. ƏSAS zəmanət DB-nin unikal indeksidir (`uq_fines_manual_camera_idempotency_key`, miqrasiya 074) — bu sabit YALNIZ ona çatmadan qayıdan sürətli-yoldur. Root onu sıfıra endirsəydi yalnız sürətli-yol itərdi, zəmanət yox; böyütsəydi ayrı-ayrı HƏQİQİ cərimələr duplikat sayılardı |

Bu sabitlər üçün şərh şablonu FƏRQLİDİR: «fallback» yazılmır, **niyə Root
parametri olmadığı** yazılır.

**Feature Toggle retroaktiv təsir etmir.** Söndürmə yalnız YENİ instansiyanı
bloklayır; mövcud qeydlər axınını tamamlayır, silinmir və export-dan çıxmır.
Ona görə yoxlama YARADAN metoddadır (`assign`, `request_reward`,
`request_leave`), emal edən metodlarda (`submit_evidence`, `review`,
`decide_reward`) YOXDUR.

**Struktur-kritik modul** (`FeatureModule.is_structural`) sadə toggle ilə
söndürülmür — yazılı təsdiq tələb olunur və qayda İKİ yerdədir: use case-də
(uzunluq) və repository-də (mövcudluq), çünki ekranı yan keçən skript də ona
tabe olmalıdır.

---

## 6. Naxışlar (mövcud kodu təkrarlayın)

### Use case

```python
class XUseCase:
    def __init__(self, *, repository: XRepository, audit: AuditTrail,
                 clock: Clock, notifier: Notifier) -> None: ...

    def do_something(self, *, tenant_id: TenantId, actor: Employee, ...) -> Result:
        self._require(actor, FLAG)          # 1. səlahiyyət
        entity.mutate(...)                   # 2. domen qaydası entity-də
        self._repository.save(entity)        # 3. yazma
        self._audit.record(...)              # 4. audit
        self._notifier.notify(...)           # 5. bildiriş (lazımsa)
```

Səlahiyyət yoxlaması sükutla "heç nə etmə" DEYİL — açıq istisna atır, çünki
istifadəçi düyməni basıb və nəticə gözləyir.

### Repository

`_BaseRepository`-dən miras alır, `self._tenant` ilə açıq `tenant_id` şərti
qoyur (RLS-ə ƏLAVƏ ikinci qat), `ON CONFLICT` ilə UPSERT edir.

### GUI sessiyası

Use case-lər bir dəfə qurulub SAXLANMIR — repo-lar bağlantıya bağlıdır:

```python
with context.session(user_id=actor.id) as session:
    session.leave_verification.claim_return(...)
    session.commit()          # commit UNUDULARSA rollback olur
```

Yeni repo əlavə edərkən `PostgresUnitOfWork._build_repositories()`-ə yazın və
`composition.py`-da use case-ə bağlayın.

### Ekran

Ekranlar yalnız `theme` alır və setter API-si təqdim edir. Məlumat İKİ yoldan
gəlir: `preview_screens.populate()` (maket) və `controllers/screen_data.py`
(canlı). İkisi eyni imzalıdır — `app.py` yalnız hansını çağıracağını seçir.

**Maket və canlı yol EYNİ AÇARLARI işlətməlidir.** `preview_screens` öz ad
məkanını qursaydı (məs. `"fines"`, halbuki toggle cədvəli `"FINE_MODULE"`
saxlayır), uyğunsuzluq maketdə görünməz qalar və yalnız istehsalatda üzə
çıxardı — layihədə məhz bu qüsur olub (bax `menu.py` başlığı).

### Ekranın YAZI yolu

Yalnız oxuyan ekran `screen_data.py`-a bağlanır. Həm oxuyub həm yazan ekranın
isə ÖZ kontrolleri olur (`controllers/root_control.py`, `fine_entry.py`,
`camera_queue.py`, `drive_connection.py`) — çünki hər yazıdan sonra siyahı
yenidən oxunmalıdır və bu dövrə `populate()`-ın tək çağırışından uzun yaşayır.

Kontroller sessiyanı SAXLAMIR — hər əməliyyat üçün yenisini açır və commit
edir. Panel saatlarla açıq qala bilər; uzun-ömürlü tranzaksiya bu müddət boyu
kilid saxlayardı.

Kontrollerə istinad da saxlanmır: o, siqnallara bağladığı `lambda`-ların
bağlamasında yaşayır və ekranla birlikdə ölür.

---

## 7. Baza

* `database/schema.sql` — bazis sxem (tək başına tam quraşdırma).
* `database/migrations/NNN_*.sql` — üstünə qatlanan dəyişikliklər. **Schema.sql
  miqrasiya SÜTUNLARINI ehtiva etmir** — hər ikisi ardıcıl tətbiq olunur.
* Hər miqrasiya idempotentdir və sonunda şərhlə DOWN blokunu saxlayır.
* Yeni sütun əlavə edərkən: miqrasiya faylı + `COMMENT ON COLUMN` + niyə-izahı.

### Miqrasiyalar YALNIZ icraçı ilə tətbiq olunur

```bash
.venv/Scripts/python.exe scripts/apply_migrations.py --dry-run   # nə gözləyir
.venv/Scripts/python.exe scripts/apply_migrations.py             # tətbiq et
.venv/Scripts/python.exe scripts/apply_migrations.py --vendor    # vendor dəsti
```

İcraçı `kompasos.schema_migrations` reyestrinə yazır (miqrasiya 061): fayl adı,
SHA-256, vaxt, rol, müddət. **Faylı əl ilə SQL redaktorunda işlətmək qadağandır**
— reyestrdə iz qalmaz.

Səbəb DB-5-in canlı bazada tapdığı faktdır: 60 miqrasiyadan **11-i heç vaxt
tətbiq olunmamışdı**, 32 cədvəl yox idi və tətbiq onlara yazmağa çalışırdı.
Qüsur aylarla görünmədi, çünki tətbiq olunanın qeydi HEÇ YERDƏ yox idi — cavab
yalnız sxemi mənbə ilə əl ilə müqayisə etməklə tapılırdı, o müqayisə isə
YALNIZ cədvəl yaradan miqrasiyanı görür (60-dan 40-ı cədvəl yaratmır).

### SÜTUN yox, QAYDA dəyişirsə — hər iki yer yenilənir

Sütun qatlanır, **qayda qatlanmır**. Miqrasiya `schema.sql`-də ARTIQ mövcud olan
bir trigger funksiyasını, indeksi və ya constraint-i yenidən yazırsa, bazis
sxemdəki nüsxə DƏ yenilənməlidir.

Səbəb DB-1 auditinin tapdığı faktdır: `enforce_anti_fraud_segregation()` 013-də
prioritet qaydası ilə gücləndirilmiş, 048-də həddi yenilənmiş, `schema.sql`-dəki
nüsxə isə heç vaxt yenilənməmişdi. Nəticədə qapı quraşdırma YOLUNDAN asılı
olurdu — tam zəncir tətbiq olunmuş baza güclü, `schema.sql` ilə təmiz
quraşdırma isə ZƏİF qapı alırdı və "satıcı-pilləli" custom rol anti-fraud
flag-ini DB səviyyəsində qəbul edərdi. Bu, §5-in «hər qayda İKİ yerdə»
prinsipinin sükutla pozulmasıdır.

`tests/unit/test_schema_migration_parity.py` hər iki tərifi maşınla müqayisə
edir. Fərq QƏSDLİdirsə (məs. miqrasiyanın ÖZÜ əlavə etdiyi sütunla qurulan
indeks) `INTENTIONAL_DIVERGENCE`-ə **səbəbi ilə** yazılır — fərq görünməz
qalmır, qərara çevrilir.

---

## 8. Tez-tez lazım olan yerlər

| Nə | Harada |
|---|---|
| İcazə flag kataloqu — **56 flag** (36 `schema.sql`-də: 34 spesifikasiyadan + `can_publish_fines`, `can_manage_drive_connection`; qalan 20 miqrasiyalarda: 021 +6, 038 +6, 047 +1, 056 +1, 063 +1 `can_manage_devices`, 068 +3 dəstək kanalları, 072 +1 `can_revoke_sessions`, 077 +1 `can_manage_roles`; **069 həmin üçünü MÖVCUD kirayəçilərə də verir** — flag əlavə edən miqrasiya `positions.tenant_id IS NULL` süzgəci İŞLƏTMƏMƏLİDİR) | `database/schema.sql` §22 + miqrasiyalar |
| Miqrasiya icraçısı və reyestri | `scripts/apply_migrations.py`, `migrations/061` |
| Özünə-host lisenziya sətri (SEC-023) | `migrations/065`, `tests/unit/test_license_bootstrap_privilege.py` |
| Server-lövbərli vaxt + manipulyasiya aşkarlaması | `src/infrastructure/timekeeping/server_time.py`, `migrations/062` |
| Vaxt etibarlılıq səviyyəsi (domen) | `src/domain/value_objects/time_integrity.py` |
| Cihaz qeydiyyatı (filial tanıma) | `src/application/use_cases/device_registry.py`, `migrations/063` + `067` (gözləyən aparat izi) |
| Cihaz kimliyi faylı + aparat izi | `src/infrastructure/config/device_identity.py` |
| Tenant brendinqi (ad/loqo/rəng) | `src/application/use_cases/tenant_branding.py`, `migrations/064` |
| Yeni müştəri quraşdırması | `scripts/onboard_new_tenant.py` (`.exe`-yə DÜŞMÜR) |
| **Təchizatçının `Root` hesabı** (SEC-030) | `scripts/create_root_account.py` (`.exe`-yə DÜŞMÜR; şifrə gizli soruşulur) |
| Developer Panelinin açılışı | `scripts/dev_panel.py` (`.env` yükləyir; `.exe`-yə DÜŞMÜR) |
| Hardlock/anti-fraud qaydaları | `src/domain/value_objects/authorization.py` |
| Menyu maddələri + flag bağlantısı | `src/presentation/shell/menu.py` |
| Sistem limitləri & Feature Toggle açarları | `src/domain/policies.py` |
| GUI obyekt qrafı + sübut yükləmə qatı | `src/presentation/composition.py` |
| ROOT paneli (limit / toggle / registry) | `src/application/use_cases/root_control.py`, `presentation/controllers/root_control.py` |
| Ekranların CANLI məlumatı (yalnız oxu) | `src/presentation/controllers/screen_data.py` |
| Ekranların YAZI yolu | `src/presentation/controllers/{fine_entry,camera_queue,drive_connection}.py` |
| **Ölü düymələrin bağlandığı dövrə** — qərar yolları: cərimə etirazı, gündəlik tabel, növbə dəyişmə | `controllers/{fine_appeals,daily_roster,shift_swaps}.py` |
| Üz qeydiyyatı qapısı (ilk giriş + CEO bootstrap) | `src/presentation/controllers/face_setup.py`, `use_cases/face_control.py` (`enroll_first_account`, SEC-025) |
| Panel girişində «Üzlə daxil ol» | `src/presentation/controllers/face_login.py` (SEC-026) |
| Gizli bərpa konsolu (`Ctrl+Shift+K`) | `presentation/screens/recovery_console.py`, `controllers/recovery_console.py` (RECOVERY-1) |
| Tema keçidinin giriş-öncəsi ekranlara ötürülməsi (THEME-1) | `presentation/shell/window.py` → məzmunun `apply_theme` metodu |
| Fokus halqasının giriş modallığı (FOCUS-1) | `presentation/widgets/focus_ring.py` (`input_modality_tracker`); `buttons.py` onu YALNIZ İSTİFADƏ edir — D11-də dövri idxaldan qaçmaq üçün ayrıldı |
| Bloklamadan əvvəl ekranı çəkdirmə (UX-1) | `presentation/controllers/ui_feedback.py` (`flush_ui`) |
| Əsas sapın donma ölçüsü (QA-0) | `presentation/stall_monitor.py` — `MAIN_THREAD_STALL` |
| QA ölçmə dəsti (vaxt, sorğu sayı, yaddaş) | `tests/fixtures/qa_harness.py`, `tests/unit/test_qa_infrastructure.py` |
| Sessiyanın gediş-gəliş büdcəsi (PERF-1/2/3) | `docs/performance_notes.md`, `tests/unit/test_session_roundtrips.py`, `test_read_batch_scope.py` |
| Açılış oxularının toplusu (PERF-3) | `ApplicationContext.read_batch()` — sapa görə ayrı, YALNIZ oxu |
| `Screen` törəməsi ikinci layout QURMUR (LAYOUT-1) | `tests/unit/test_screen_layout_ownership.py` — pozulsa ekran BOŞ render olunur |
| İki-kanallı dəstək (daxili / texniki) | `domain/value_objects/support.py`, `use_cases/support_chat.py`, `migrations/068` (CHAT-1) |
| Dəstək gələnlər qutusu (İKİ bölmə, BİR ekran) | `presentation/screens/support_inbox.py`, `controllers/support_inbox.py` |
| Müraciət statusu (Açıq/Gözləmədə/Həll olundu/Bağlandı) | `SupportTicketStatus` (`value_objects/support.py`) — nişan YALNIZ `OPEN` sayır |
| Telegram bot konfiqurasiyası (şifrəli token) | `use_cases/telegram_config.py`, `persistence/telegram_repositories.py` |
| Telegram şlüzü + `#msg_XXXX` cavab yönləndirməsi | `infrastructure/notifications/telegram.py` |
| Avtomatik baza quruluşu (paketlənmiş sxem + miqrasiyalar) | `infrastructure/persistence/provisioning.py` |
| Setup quraşdırıcısı və buraxılış ardıcıllığı | `installer/KompasOS.iss`, `docs/build_and_release.md` (SETUP-1) |
| Drive razılığı (OAuth) | `src/infrastructure/storage/oauth_flow.py` |
| Sübut şəkli növbəsi (SQLite + spool) | `src/infrastructure/storage/upload_queue.py` |
| Test sahtələri (fakes) | `tests/fixtures/fakes.py` |
| Qərar jurnalı (SEC-NNN, BR-NNN) | `docs/security_decisions.md`, `docs/open_questions.md` |
| Risk reyestri | `docs/risk_register.md` |

### Mühit dəyişənləri

Tam siyahı `.env.example`-dədir. Yenisini əlavə edərkən HƏMİŞƏ ora da yazın
və **boş buraxıla bilərmi** sualına şərhdə cavab verin — quraşdırıcı hansı
açarın məcburi olduğunu oradan öyrənir.

| Açar | Boş ola bilər? | Nəticə |
|---|---|---|
| `KOMPASOS_FERNET_KEY`, `KOMPASOS_HASH_PEPPER` | ❌ istehsalatda | `--strict` işə düşmür |
| `KOMPASOS_GOOGLE_CLIENT_ID` / `_SECRET` | ✅ | Şəkillər lokal növbədə gözləyir, cərimələr normal yaranır |
| `KOMPASOS_EVIDENCE_QUEUE_PATH`, `KOMPASOS_SQLITE_PATH`, `KOMPASOS_LOG_DIR` | ✅ | Defolt `%PROGRAMDATA%\KompasOS\` (`data\`, `logs\`) — CWD-yə nisbi YOX, çünki paketlənmiş `.exe` ixtiyari qovluqdan işə düşür və `Program Files` yazıla bilmir (SETUP-1). Köhnə `%LOCALAPPDATA%` faylı mövcuddursa TANINIR, köçürülmür |
| `KOMPASOS_PRIVATE_SERVER_DSN` | ✅ | Boşdursa baza keçidi işləmir, aydın səbəb qaytarılır |
| `KOMPASOS_TENANT_ID`, `KOMPASOS_INSTALLATION_PATH` | ✅ | Boş = ilk quraşdırma: kimlik `installation.json`-da yaranır və sihirbaz açılır (SEC-021) |
| `KOMPASOS_DEVICE_FILE` | ✅ | Defolt `%PROGRAMDATA%\KompasOS\device.json`. Faylda yalnız `device_id` var və şifrələnmir — sirr deyil (DEVICE-1). Silinsə cihaz YENİ qeydiyyat yaradır |
| `KOMPASOS_PLUGIN_TRUSTED_PUBLISHERS` | ✅ | Boş = fail-closed, heç bir plugin quraşdırılmır |
| `KOMPASOS_PLUGIN_PYTHON` | ✅ | Paketlənmiş mühitdə plugin sandbox-u üçün interpretator; tapılmasa plugin icra olunmur |
| `KOMPASOS_STALL_WARN_MS` | ✅ | Defolt 1000 ms. Əsas sap bu qədər kilidlənsə `MAIN_THREAD_STALL` jurnala düşür. `system_limits` DEYİL — monitor bazadan ƏVVƏL, açılış yolunda işə düşür |

---

## 9. Spesifikasiyadan qəsdli deviasiyalar

Bunlar səhv deyil — sənədləşdirilmiş qərarlardır. Dəyişdirməzdən əvvəl səbəbini
oxuyun:

| Deviasiya | Sənəd |
|---|---|
| Cərimə sübut şəkilləri **Google Drive**-da (Supabase Storage əvəzinə) | `migrations/002` başlığı |
| Cərimələr `PENDING_REVIEW` → aylıq icmal → `PUBLISHED` (spesifikasiya "dərhal görünür" deyir) | `use_cases/fine_review.py` başlığı |
| Master Panel `mTLS` əvəzinə `service_role` + RLS | `docs/security_decisions.md` |
| SEC-016: TOTP/2FA çıxarılıb, giriş = istifadəçi adı + şifrə | `migrations/001`, bölmə 2 |
| SEC-017: Drive razılığı loopback + PKCE (Google `oob`-u qapadıb) | `storage/oauth_flow.py` başlığı |
| BR-001: icazə güzəştinin mənbəyi konfiqurasiya edilir (defolt `LEAVE_TYPE`) | `policies.py`, OQ-001 |
| BR-002: gecikmə→AZN dərəcəsi Root-dan, **defolt 0.00** | `policies.py` (`DelayFinePolicy`) |
| Aylıq 240 dəq. aşıldıqda XƏBƏRDARLIQ olur, bloklama YOX | `leave_verification.py` (`MonthlyLeaveUsage`) |
