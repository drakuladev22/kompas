# scripts/db — baza alətləri

`psql` **olmadan** `schema.sql`-i tətbiq etmək üçün. Node.js kifayətdir.

## Quraşdırma (bir dəfə)

```powershell
cd scripts/db
npm install
```

## İstifadə

```powershell
# Session Pooler (IPv4) — birbaşa host IPv6-dır, işləmir
$env:SB_HOST     = 'aws-0-ap-southeast-1.pooler.supabase.com'
$env:SB_REF      = 'jivelnmjdqnvjxtqtopr'
$env:SB_PASSWORD = '<şifrə>'

node apply.js ../../database/schema.sql DEV
node apply.js ../../database/tests/test_guards.sql
node query.js "SELECT count(*) FROM kompasos.employees"
```

Və ya tək bağlantı sətri ilə:

```powershell
$env:DATABASE_URL = 'postgresql://postgres.<ref>:<şifrə>@aws-0-<region>.pooler.supabase.com:5432/postgres'
node apply.js ../../database/schema.sql DEV
```

## Niyə lazımdır?

`schema.sql` psql meta-əmrlərindən istifadə edir:

```sql
\if :{?kompasos_env}
\endif
SET kompasos.env TO :'kompasos_env';
```

`apply.js` bunları emal edir (`\`-la başlayan sətirlər silinir,
`:'kompasos_env'` literal ilə əvəzlənir), sonra SQL-i node-postgres ilə icra
edir. `psql` quraşdırıldıqdan sonra ona keçmək tövsiyə olunur — bu alətlər
yalnız rahatlıq üçündür.

## Təhlükəsizlik

- Şifrə **yalnız mühit dəyişənindən** oxunur, heç bir fayla yazılmır.
- `node_modules/` və `package-lock.json` `.gitignore`-dadır.
- İstehsalat bazasına qarşı işlədərkən diqqətli olun — `apply.js` bütöv faylı
  tək tranzaksiyada icra edir (xəta olarsa hər şey geri qaytarılır).
