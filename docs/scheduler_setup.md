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
| `cron_close_expired_appeals` | Etiraz pəncərəsi bağlanmır → cərimələr **export-a heç vaxt düşmür** (bölmə 6 LOCK) |
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
