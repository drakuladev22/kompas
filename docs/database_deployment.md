# Baza Quraşdırması — Supabase

## Cari vəziyyət (doğrulanmış)

| | |
|---|---|
| Layihə ref | `jivelnmjdqnvjxtqtopr` |
| Region | `ap-southeast-1` (Sinqapur) |
| PostgreSQL | 17.6 |
| Sxem | `kompasos` |
| Tətbiq tarixi | 2026-08-08 |

**Tətbiq nəticəsi:**

| Obyekt | Say |
|---|---|
| Cədvəl | 46 |
| RLS aktiv cədvəl | 42 |
| RLS siyasəti | 42 |
| ENUM tip | 18 |
| Funksiya | 21 |
| Görünüş (view) | 4 |
| Trigger | 23 |
| İndeks | 110 |
| İcazə flag-i (seed) | 34 |
| Sistem rolu / tenant rolu | 7 / 7 |
| Rol→flag təyinatı | 186 |
| Sistem limiti / Feature toggle | 9 / 8 |
| DEV tenant statusu | `AKTIV` |

**Guard testləri: 17/17 ✅** (`database/tests/test_guards.sql`)
**İdempotentlik: ✅** (skript üç dəfə icra olundu, nəticə eyni)

### RLS-siz 4 cədvəl — qəsdəndir

| Cədvəl | Səbəb |
|---|---|
| `permission_flags` | Qlobal kataloq, tenant-a aid deyil, məxfi məlumat yoxdur |
| `license_tenants` | Tenant reyestrinin ÖZÜ; tətbiq rolunun `UPDATE`/`DELETE` hüququ yoxdur (SEC-009) |
| `crash_reports` | Anonimləşdirilmiş, PII yoxdur, `tenant_id` sütunu yoxdur (bölmə 8) |
| `scheduled_job_runs` | Qlobal infrastruktur telemetriyası |

---

## ⚠️ BAĞLANTI: birbaşa host İŞLƏMİR

Supabase-in **birbaşa** bağlantısı (`db.<ref>.supabase.co:5432`) yalnız
**IPv6**-dır. IPv4 şəbəkələrindən (o cümlədən bu iş maşınından) çatmır:

```
Resolve-DnsName db.jivelnmjdqnvjxtqtopr.supabase.co
→ AAAA  2406:da18:1691:a200::51ec     (yalnız IPv6)
TcpTestSucceeded: False
```

**İstifadə edin — Session Pooler (IPv4):**

```
host:     aws-0-ap-southeast-1.pooler.supabase.com
port:     5432
user:     postgres.jivelnmjdqnvjxtqtopr
database: postgres
sslmode:  require
```

> Faza 3-də `DATABASE_URL` bu host ilə qurulmalıdır, birbaşa host ilə YOX.
> Əks halda tətbiq mağaza PC-lərindən (IPv4) bağlana bilməyəcək.

---

## Sxemi yenidən tətbiq etmək

Skript **idempotentdir** — istənilən vaxt təkrar icra oluna bilər.

### `psql` ilə (tövsiyə olunan, quraşdırıldıqdan sonra)

```powershell
$env:PGPASSWORD = '<şifrə>'
psql -h aws-0-ap-southeast-1.pooler.supabase.com -p 5432 `
     -U postgres.jivelnmjdqnvjxtqtopr -d postgres `
     -v ON_ERROR_STOP=1 -v kompasos_env=DEV `
     -f database/schema.sql
```

### `psql` olmadan (Node ilə)

`psql` quraşdırılmayıbsa, `scripts/db/apply.js` psql meta-əmrlərini
(`\set`, `\if`, `:'kompasos_env'`) emal edib SQL-i icra edir:

```powershell
$env:SB_HOST     = 'aws-0-ap-southeast-1.pooler.supabase.com'
$env:SB_REF      = 'jivelnmjdqnvjxtqtopr'
$env:SB_PASSWORD = '<şifrə>'
node scripts/db/apply.js database/schema.sql DEV
node scripts/db/apply.js database/tests/test_guards.sql
```

---

## Quraşdırmadan sonra QALAN addımlar

### 1. Tətbiq rolunun şifrəsi (SEC-009) — MƏCBURİ

`kompasos_app` rolu yaradılıb, lakin `NOLOGIN`-dir:

```sql
ALTER ROLE kompasos_app LOGIN PASSWORD '<güclü-şifrə>';
```

Tətbiq **bu roldan** istifadə etməlidir, `postgres`-dən yox. `postgres` cədvəl
sahibidir → RLS-i və append-only trigger-lərini yan keçir.

### 2. `pg_cron` (SEC-010) — MƏCBURİ

Hazırda **aktiv deyil**. Sxem bunu xəbərdarlıqla qeyd etdi:

```
WARNING: pg_cron TAPILMADI. Xarici scheduler qurulmayana qədər avtomatik
         eskalasiya/hesablama işləməyəcək.
```

**Variant A:** Supabase Dashboard → Database → Extensions → `pg_cron` → Enable,
sonra `schema.sql`-i yenidən icra edin (cədvəl avtomatik qeydiyyatdan keçir).

**Variant B:** xarici scheduler hər 5 dəqiqədən bir çağırsın:

```sql
SELECT * FROM kompasos.run_all_scheduled_jobs();
```

Ətraflı: [`scheduler_setup.md`](scheduler_setup.md).

Yoxlama:

```sql
SELECT job_name, last_run_at, since_last_run, is_stale
FROM kompasos.v_scheduled_job_health ORDER BY is_stale DESC;
```

### 3. DB şifrəsinin dəyişdirilməsi

Cari şifrə söhbətdə açıq göründü — Supabase → Settings → Database →
**Reset database password**.

### 4. Faza 3 üçün RLS müqaviləsi (SEC-008)

Repository qatı hər tranzaksiyada kontekst təyin etməlidir:

```sql
SET LOCAL app.tenant_id = '<uuid>';
SET LOCAL app.user_id   = '<uuid>';
```

`SET LOCAL` (adi `SET` yox) — connection pool-da dəyər növbəti istifadəçiyə
sızmasın. Bu edilməzsə siyasət **fail-closed** olduğu üçün sorğular **boş**
qaytaracaq (sızma yox, dayanma — qəsdən seçilmiş davranış).

---

## DEV seed tenant

`-v kompasos_env=DEV` ilə yaradılır:

| Sahə | Dəyər |
|---|---|
| Ad | `DEV — Lokal Test` |
| Status | `AKTIV` (LICENSE_INACTIVE bloku testləri dayandırmasın) |
| Mağaza | `DEV-001 — Yataş Babək (DEV)` |
| İş rejimləri | `08:00–17:00`, `14:00–23:00` |
| Cərimə növləri | Formaya uyğun geyinməmək (10 AZN), Kassa qaydaları (25 AZN) |
| İcazə növləri | Nahar (60 dəq), Siqaret (10 dəq), Şəxsi İş (30 dəq) |

**İstehsalat quraşdırmasında `-v kompasos_env=PRODUCTION` istifadə edin** —
seed tenant yaradılmır.
