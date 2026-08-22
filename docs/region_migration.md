# Bazanın regionunun dəyişdirilməsi (Sinqapur → Frankfurt)

## Niyə — ölçülmüş rəqəm

Bu maşından TCP əl sıxma (5 cəhd, ən yaxşı / orta):

| Region | Min | Orta |
|---|---|---|
| `ap-southeast-1` (Sinqapur, **cari**) | 205 ms | 217 ms |
| `eu-central-1` (**Frankfurt**) | **70 ms** | 90 ms |
| `eu-west-3` (Paris) | 78 ms | 88 ms |
| `eu-west-2` (London) | 81 ms | 103 ms |

Ekranların vaxtının praktik olaraq 100 %-i baza gözləməsidir (çəkiliş ~0 ms,
bax [`performance_notes.md`](performance_notes.md)), yəni bu əmsal BÜTÜN
rəqəmlərə birbaşa düşür:

| Əməliyyat | Sinqapur (ölçülüb) | Frankfurt (gözlənilən) |
|---|---|---|
| İdarə Paneli | 3247 ms | ~1100 ms |
| Sistem Sağlamlığı | 1900 ms | ~650 ms |
| Orta ekran (2-3 sorğu) | 860–1100 ms | ~300–380 ms |

Frankfurt Parisdən 8 ms yaxşıdır və Supabase-in ƏSAS AB regionudur (bütün
xüsusiyyətlər ilk orada işə düşür) — ona görə hədəf odur.

---

## Supabase regionu YERİNDƏ dəyişmir

Mövcud layihənin regionu dəyişdirilə bilmir. Yeganə yol: hədəf regionda YENİ
layihə açıb məlumatı köçürmək. Layihə açmaq **Supabase hesabı** tələb edir və
bu addım skriptdən İCRA OLUNMUR — hesab səviyyəsində resurs yaratmaq (və pul
xərcləmək) operatorun qərarıdır.

---

## Addımlar

### 1. Yeni layihə (ƏL İLƏ, bir dəfə)

1. Supabase idarə panelində **New project** → **Region: Central EU
   (Frankfurt) `eu-central-1`**.
2. Baza parolunu təhlükəsiz saxlayın.
3. **Project Settings → Database → Connection pooling** DSN-ini götürün
   (`aws-0-eu-central-1.pooler.supabase.com:5432`).
4. Tətbiq rolunu (`kompasos_app`) köhnə layihədəki kimi yaradın — köçürmə
   skripti YALNIZ məlumatı daşıyır, rol yaratmır (rol parolu köçürülməməlidir:
   dump `--no-owner --no-privileges` ilə çıxarılır).

### 2. Köçürmə (SKRİPT)

```bash
.venv/Scripts/python.exe scripts/migrate_region.py \
    --source-dsn "postgresql://…@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres" \
    --target-dsn "postgresql://…@aws-0-eu-central-1.pooler.supabase.com:5432/postgres" \
    --dev
```

Skript dörd addım edir:

1. **Sxem + miqrasiyalar** — mövcud icraçı ilə (`apply_migrations.py`), yəni
   hədəf bazada reyestr (`schema_migrations`) ÖZ icrasından yaranır.
2. **Məlumat** — `pg_dump --data-only` → fayl → `psql --single-transaction`.
   Bərpa `session_replication_role = replica` ilə işləyir: append-only və
   server-vaxtı trigger-ləri köçürülən sətirləri rədd etməsin/dəyişməsin.
3. **Yoxlama** — hər cədvəlin sətir sayı mənbə ilə tutuşdurulur; bir sətir
   fərq varsa skript DAYANIR və cədvəl adını yazır.
4. **`--dev`** — bu maşının `connection.json`-u yeni bazaya yönləndirilir.

`--dry-run` heç nə yazmadan addımları və mənbənin ölçüsünü göstərir.

**Ön şərt:** `pg_dump`/`psql` (PostgreSQL client alətləri). Skript onları
`PATH`-da, sonra `C:\Program Files\PostgreSQL\<versiya>\bin`-də axtarır və
versiyanın serverdən köhnə olmadığını YOXLAYIR (köhnə `pg_dump` yeni serveri
dump edə bilmir — yarımçıq köçürmənin ən sakit səbəbi).

### 3. Sonrakı əl işi

1. `.env` → `DATABASE_URL` və `DATABASE_ADMIN_URL` yeni DSN ilə əvəzlənir.
2. Müştəri maşınlarındakı `connection.json` yenilənir (host dəyişir, parol
   həmin maşında «Bağlantı Ayarları» ekranından yenidən daxil edilir — o,
   MAŞINA bağlı şəkildə şifrələnir).
3. Köhnə layihə DƏRHAL silinmir — bir neçə gün ehtiyat kimi qalır.
4. Yoxlama: `scripts/onboard_new_tenant.py --verify <tenant_id>` və
   `python -m src.main --check`.

---

## Ölçülmüş vəziyyət (bu maşın, 2026-08-22)

* Mənbə baza: PostgreSQL **17.6**, `kompasos` sxemində **86 cədvəl,
  1590 sətir** (əsasən seed: `position_permissions` 632, `system_limits` 612).
* `pg_dump` 18 ilə çıxarılan dump: **265 KB** — köçürmə dəqiqələrlə ölçülür,
  saatlarla yox.
* Miqrasiya reyestri: **82/82** tətbiq olunub.

Yəni köçürmənin ÖZÜ ucuzdur; bahalı olan yalnız yeni layihənin açılmasıdır.
