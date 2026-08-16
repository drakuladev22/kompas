# Planlaşdırılmış İşlərin Qurulması (SEC-010)

KompasOS-un bir neçə **əsas biznes qaydası** planlaşdırılmış DB funksiyalarına
əsaslanır. Onlar işləmirsə sistem xəta vermir — sadəcə həmin qaydalar
**sükutla tətbiq olunmur**. Ona görə bu qurulum məcburidir.

## Nə işləməzsə nə olur?

| Funksiya | İşləməzsə nəticə |
|---|---|
| `cron_escalate_verification_timeouts` | İşçi `🟡` statusunda **sonsuza qədər** qalır; HR heç nə bilmir (bölmə 4, 45 dəq. qaydası) |
| `cron_detect_unauthorized_absences` | Attendance Report-da "İcazəsiz Qayıb" sütunu **həmişə boş** olur (bölmə 4/6) |
| `cron_escalate_task_deadlines` | Gecikmiş tapşırıqlar üçün eskalasiya getmir (bölmə 6) |
| `cron_close_expired_appeals` | Cavabsız qalmış etiraz `EXPIRED` kimi işarələnmir → HR-ın gecikməsi **heç bir hesabatda görünmür** (M-6). Export kilidinə təsiri YOXDUR: kilid vaxt şərtindən (`appeal_window_closes_at <= now()`) və qərarsız etirazın mövcudluğundan asılıdır, bu funksiyanın işləməsindən yox |
| `cron_reset_sales_points` | 6 aylıq xal sıfırlanması baş vermir (bölmə 6) |
| `cron_notify_points_reset_upcoming` | 14 günlük xəbərdarlıq göndərilmir (bölmə 6) |
| `cron_update_license_payment_status` | Ödəniş gecikməsi aşkarlanmır (bölmə 8) |
| `cron_prune_expired_backups` | 30 günlük saxlama siyasəti tətbiq olunmur (bölmə 7) |
| `cron_prune_expired_sessions` | Köhnə sessiya qeydləri toplanır (SEC-011) |

---

## Variant A — `pg_cron` (tövsiyə olunan)

Supabase-də: **Dashboard → Database → Extensions → `pg_cron` → Enable**.

Öz-idarə olunan PostgreSQL-də:

```ini
# postgresql.conf
shared_preload_libraries = 'pg_cron'
cron.database_name = 'kompasos'
```

Sonra:

```sql
CREATE EXTENSION IF NOT EXISTS pg_cron;
```

`schema.sql` yenidən icra edildikdə cədvəl avtomatik qeydiyyatdan keçir
(§20 sonundakı blok). Yoxlama:

```sql
SELECT jobname, schedule, command FROM cron.job WHERE jobname LIKE 'kompasos-%';
```

---

## Variant B — Xarici scheduler

`pg_cron` mümkün deyilsə, **tək bir funksiya** çağırmaq kifayətdir:

```sql
SELECT * FROM kompasos.run_all_scheduled_jobs();
```

Bu funksiya bütün job-ları sıra ilə icra edir, hər birinin nəticəsini
`scheduled_job_runs` cədvəlinə yazır və bir job-un xətası digərlərini
dayandırmır.

**Tövsiyə olunan interval: 5 dəqiqə.** Gündəlik job-lar (xal sıfırlanması,
backup təmizləmə) öz daxilində tarix yoxlaması apardığı üçün tez-tez
çağırılması problem yaratmır.

### Windows Task Scheduler

```powershell
$action = New-ScheduledTaskAction `
    -Execute 'psql.exe' `
    -Argument '-h HOST -U kompasos_app -d kompasos -c "SELECT kompasos.run_all_scheduled_jobs();"'

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName 'KompasOS-Scheduler' `
    -Action $action -Trigger $trigger -RunLevel Highest
```

> `PGPASSWORD`-u əmr sətrində YAZMAYIN — `%APPDATA%\postgresql\pgpass.conf`
> faylından istifadə edin.

### systemd timer (Linux)

```ini
# /etc/systemd/system/kompasos-scheduler.service
[Unit]
Description=KompasOS planlaşdırılmış işləri

[Service]
Type=oneshot
User=kompasos
Environment=PGPASSFILE=/etc/kompasos/pgpass
ExecStart=/usr/bin/psql -h HOST -U kompasos_app -d kompasos \
    -c "SELECT kompasos.run_all_scheduled_jobs();"
```

```ini
# /etc/systemd/system/kompasos-scheduler.timer
[Unit]
Description=KompasOS scheduler — hər 5 dəqiqə

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

```bash
systemctl enable --now kompasos-scheduler.timer
```

---

## Variant C — Tətbiqin ÖZ planlayıcısı (`--run-scheduled-jobs`)

Yuxarıdakı iki variant **DB funksiyalarını** (SQL) işlədir. Lakin bir sıra
qayda yalnız **Python qatında** yaşayır — onları `pg_cron` çağıra bilməz,
çünki onlar `pg_dump` işə salır, bildiriş göndərir və domen hesablaması edir:

| İş açarı | Nə edir | Ritm | Çəki |
|---|---|---|---|
| `BEHAVIOR_BASELINE_RECALC` | #8 işçi davranış baz xətti | gündəlik | yüngül |
| `EXCEPTION_ENGINE_RUN` | #9 Vahid İstisna Motoru | gündəlik | yüngül |
| `STAFFING_PATTERN_REFRESH` | #13 həftə-günü kadr ortaları (hər aktiv mağaza) | gündəlik | yüngül |
| `EMPLOYEE_DOCUMENT_EXPIRY_NOTICE` | #17 sənəd bitmə xəbərdarlığı (30/14/7 gün) | gündəlik | yüngül |
| `ATTRITION_RISK_RECALC` | #21 işdən çıxma riski balı | gündəlik | yüngül |
| `FINE_EXPIRE_STALE` | cavabsız etirazların SLA-pozuntusu kimi işarələnməsi (72 saat) | **saatlıq** | yüngül |
| `DUAL_CONTROL_OVERRIDE_TIMEOUT` | təsdiqsiz qalmış manual vaxt düzəlişinin ləğvi | **saatlıq** | yüngül |
| `DRIVE_QUOTA_CHECK` | Drive kvotası: 90% xəbərdarlığı, 100%-də `QUOTA_EXCEEDED`, razılıq ləğvində `REVOKED` | gündəlik | yüngül |
| `NIGHTLY_BACKUP` | `pg_dump` + saxlama müddəti bitmiş faylların silinməsi | gündəlik | **AĞIR** |

**Sıra qorunur:** `BEHAVIOR_BASELINE_RECALC` motordan ƏVVƏL işləyir — motor
baz xəttini oxuyur, köhnəsi ilə işləsəydi hər anomaliya bir gün gecikərdi.

`FINE_EXPIRE_STALE` **saatlıq**dır, çünki o, `cron_close_expired_appeals`
işinin tətbiq qatındakı əkizidir və həmin cron `schema.sql`-da `'0 * * * *'`
ilə qeydiyyatdan keçib — ritmlər eyni olmasa, etiraz pəncərəsinin bağlanma
anı `pg_cron`-un olub-olmamasından asılı olardı.

**Qeyd (Drive):** `DRIVE_QUOTA_CHECK` Google OAuth açarları təyin edilməyibsə
**sakit dayanır** (iş `SUCCEEDED`, izahı «Drive konfiqurasiya edilməyib») —
`.env.example` həmin açarların boş qala biləcəyini yazır və istisna atsaydıq,
Drive işlətməyən quraşdırmada gecəlik hesabat hər gün `FAILED` göstərərdi.
Hədd (`DRIVE_QUOTA_WARNING_RATIO`, defolt 0.90) və təkrar-susma müddəti
(`DRIVE_QUOTA_WARNING_COOLDOWN_DAYS`, defolt 7) **ROOT İdarə Mərkəzindədir**
və yoxlama anında oxunur.

**Qeyd (M-6):** `FINE_EXPIRE_STALE` artıq etirazı «bağlamır» — `EXPIRED` yalnız
SLA pozuntusunun izidir. Həmin etiraz sonradan da qərar ala bilir və cərimə
qərar verilənə qədər Premiya&Cərimə export-una DÜŞMÜR (miqrasiya 052).

`DUAL_CONTROL_OVERRIDE_TIMEOUT` **saatlıq**dır, çünki həddi DƏQİQƏ ilə ölçülür
(`DUAL_CONTROL_APPROVAL_TIMEOUT_MINUTES`, defolt 480 = bir iş növbəsi) və
gündəlik ritmdə 24 saatlıq xəta verərdi. Bu işin DB-də əkizi YOXDUR: qərar
bildiriş göndərməyi və audit sətri yazmağı tələb edir, `pg_cron` isə hər ikisini
domen qaydaları ilə edə bilməz. **Terminal söndürülü qalsa da təhlükəsizlik
boşluğu yaranmır:** `approve_dual_control` təsdiqdən ƏVVƏL müddəti özü yoxlayır,
yəni vaxtı keçmiş sorğu bu iş heç vaxt işləməsə belə təsdiqlənə bilmir.

### İki giriş nöqtəsi

| Yol | Nə işlədir | Nə vaxt |
|---|---|---|
| GUI (`QTimer`) | **yalnız yüngül** işlər | tətbiq açıq olduqca, `SCHEDULER_POLL_INTERVAL_MINUTES` ritmi ilə |
| CLI (`--run-scheduled-jobs`) | **hamısı**, ağırlar daxil | Windows Task Scheduler / əl ilə |

Gecəlik ehtiyat nüsxə (`pg_dump`) **GUI-dən heç vaxt işləmir** — o, interfeys
axınını dəqiqələrlə dondurardı. Yəni **Task Scheduler qurulmazsa ehtiyat nüsxə
alınmır**.

### Windows Task Scheduler

```powershell
# `-Execute` yolu quraşdırma yerinizə görə dəyişir.
$action = New-ScheduledTaskAction `
    -Execute 'C:\Program Files\KompasOS\KompasOS.exe' `
    -Argument '--run-scheduled-jobs'

# Saat `SCHEDULER_NIGHTLY_HOUR` (defolt 3) dəyərindən BİR NEÇƏ DƏQİQƏ SONRA
# seçilir: slot yerli 03:00-da açılır, tapşırıq 03:10-da onu hazır tapır.
$trigger = New-ScheduledTaskTrigger -Daily -At 03:10

# `-WakeToRun`: mağaza PC-si yuxu rejimindədirsə oyandırılır. Oyanmasa da
# problem deyil — gecikmiş icra (catch-up) səhər ilk açılışda işi tutur.
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable

Register-ScheduledTask -TaskName 'KompasOS-App-Jobs' `
    -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest
```

> **Mühit dəyişənləri MƏCBURİDİR.** Proses `KOMPASOS_TENANT_ID` və
> `DATABASE_URL` olmadan işə düşmür (çıxış kodu **2**). Task Scheduler
> istifadəçi mühitini həmişə miras almır — dəyişənləri **Sistem** səviyyəsində
> təyin edin (`setx /M`).

**Çıxış kodları:** `0` — hər şey qaydasındadır; `1` — ən azı bir iş çökdü
(Task Scheduler tarixçəsində qırmızı görünür); `2` — quraşdırma/baza xətası.

### Çox terminal, bir icarə

Planlayıcı **hər terminalda** işləyir. Təkrar icranı `app_scheduled_job_runs`
cədvəlindəki `UNIQUE (tenant_id, job_key, scheduled_for)` bloklayır: işi
yalnız icarəni ATOMİK götürən terminal icra edir. Ona görə **bütün
terminallarda tapşırıq qurmaq təhlükəsizdir** — baz xətti yenə bir dəfə
hesablanır.

Terminalı `leased_by` sütunu göstərir (`MAĞAZA3-KASSA1#4212` formatında:
maşın adı + proses nömrəsi).

### Çox-kirayəçilik

`--run-scheduled-jobs` **yalnız `KOMPASOS_TENANT_ID`-dəki kirayəçi** üçün
işləyir. Bu, qərardır: `system_limits` RLS ilə kirayəçiyə bağlıdır (SEC-008),
yəni bir quraşdırmadan «bütün müştərilər üçün» dövrə işlətmək bir müştərinin
parametrini digərinin gecə işinə tətbiq etmək olardı. Hər quraşdırma öz
işlərini icra edir.

### Vəziyyət sorğusu

```sql
SELECT job_key, scheduled_for, status, leased_by, attempts, result_detail, last_error
FROM kompasos.app_scheduled_job_runs
WHERE tenant_id = '<TENANT_ID>'
ORDER BY scheduled_for DESC
LIMIT 30;
```

> `app_scheduled_job_runs` (tətbiq) ilə `scheduled_job_runs` (DB-nin öz cron
> jurnalı, aşağıdakı «Monitorinq» bölməsi) **fərqli cədvəllərdir**.

---

## Monitorinq

System Health Monitor (bölmə 6) bu görünüşü oxuyur:

```sql
SELECT job_name, last_run_at, since_last_run, all_ok_last_24h, is_stale
FROM kompasos.v_scheduled_job_health
ORDER BY is_stale DESC, job_name;
```

`is_stale = TRUE` (2 saatdan çox icra olunmayıb) → **scheduler dayanıb**.
Bu vəziyyət Faza 4-də Health Monitor ekranında qırmızı sətir kimi göstərilir
və Faza 3-dəki e-poçt fallback kanalına düşür.

Son xətaları görmək:

```sql
SELECT job_name, started_at, error_message
FROM kompasos.scheduled_job_runs
WHERE succeeded = FALSE
ORDER BY started_at DESC
LIMIT 20;
```
