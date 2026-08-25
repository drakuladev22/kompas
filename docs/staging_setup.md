# Test/Staging mühiti — `v2backlog.md` Faza 5.5

Bu sənəd təchizatçının **canlı müştəri datasına toxunmadan** yeni buraxılışı,
miqrasiyanı və ya funksiyanı sınamaq üçün ayrıca mühit qurmasını təsvir edir.

> **Bu, kod funksiyası deyil.** Heç bir yeni skript yazılmır — mövcud
> `scripts/onboard_new_tenant.py` və `scripts/apply_migrations.py` başqa bir
> baza ünvanına yönəldilir. Yeni alət yazmaq iki quraşdırma yolu yaradardı və
> onlardan biri (test yolu) heç vaxt istehsalat qədər sınaqdan keçməzdi —
> yəni test mühiti ilə canlı mühit arasında sükutlu fərq yaranardı.

---

## 1. İzolyasiyanın SƏRHƏDİ — nə ilə nə arasında

Üç şey ayrılmalıdır və hər üçü **fərqli mexanizmlə** ayrılır:

| Nə | Necə ayrılır | Pozulsa nə olar |
|---|---|---|
| **Baza** | AYRI Supabase layihəsi (eyni layihədə ayrı schema DEYİL) | RLS-in bir səhvi test sorğusunu canlı sətirlərə buraxardı |
| **Fayl saxlanması** | AYRI Google Drive qovluğu / AYRI OAuth klienti | Test cəriməsinin şəkli müştərinin qovluğuna düşərdi |
| **Bildiriş kanalları** | Telegram bot tokenini BOŞ saxla, SMTP-ni boş saxla | Test məlumatı ilə REAL işçiyə bildiriş gedərdi |

**Eyni layihədə ayrı schema NİYƏ KİFAYƏT ETMİR:** RLS siyasətləri
`current_tenant_id()` üzərində qurulub və `service_role` açarı `BYPASSRLS`
daşıyır (bax `connection_types.py`, `_warn_if_bypass_rls`). Yəni bir səhv
konfiqurasiya (test skriptinin `service_role` ilə qoşulması) izolyasiyanı tam
aradan qaldırardı. Ayrı layihə isə fiziki sərhəddir: səhv DSN ilə qoşulmaq
mümkündür, lakin bu, dərhal görünən bir səhvdir (baza boşdur), sükutlu deyil.

---

## 2. Addımlar

### 2.1 Ayrı Supabase layihəsi

1. Supabase-də yeni layihə yarat. **Region:** canlı mühitlə EYNİ region seç
   (`docs/region_migration.md` — 2.9× fərq ölçülüb; fərqli regionda test
   nəticələri sürət baxımından yanıldıcı olar).
2. Layihənin DSN-ini götür.

### 2.2 Ayrıca `.env` faylı

`.env.staging` yarat — **`.env`-i redaktə ETMƏ**. Səbəb: redaktə edilmiş fayl
geri qaytarılmağı unudula bilər və növbəti canlı əməliyyat test bazasına
gedərdi.

```bash
DATABASE_URL=postgresql://...     # TEST layihəsinin DSN-i
KOMPASOS_FERNET_KEY=...           # canlı açardan FƏRQLİ (aşağı bax)
KOMPASOS_HASH_PEPPER=...          # canlı dəyərdən FƏRQLİ
KOMPASOS_GOOGLE_CLIENT_ID=        # BOŞ — şəkillər lokal növbədə qalır
KOMPASOS_GOOGLE_CLIENT_SECRET=
KOMPASOS_VENDOR_DSN=              # BOŞ — vendor bazası test mühitindən görünməsin
KOMPASOS_SQLITE_PATH=C:\KompasOS-staging\offline_buffer.db
KOMPASOS_EVIDENCE_QUEUE_PATH=C:\KompasOS-staging\evidence.db
KOMPASOS_LOG_DIR=C:\KompasOS-staging\logs
```

**`KOMPASOS_FERNET_KEY` NİYƏ FƏRQLİ OLMALIDIR:** eyni açar işlədilsəydi, test
bazasından götürülmüş şifrəli sətir canlı açarla açıla bilərdi — yəni test
bazasının surətini əlində saxlayan hər kəs canlı sirləri deşifrə edə bilərdi.
Açarlar FƏRQLİ olanda test datası öz-özlüyündə dəyərsizdir.

**Yol açarları NİYƏ AÇIQ VERİLİR:** defolt `%PROGRAMDATA%\KompasOS\` hər iki
mühitdə EYNİDİR (bax `.env.example`) — açıq verilməsə, test quraşdırması canlı
quraşdırmanın offline buferini və sübut növbəsini PAYLAŞARDI, yəni test yazısı
canlı sinxronizasiyaya düşərdi.

### 2.3 Sxem və miqrasiyalar

```bash
# `.env.staging` ilə işlət — `--dry-run` ƏVVƏLCƏ
set -a; . ./.env.staging; set +a
.venv/Scripts/python.exe scripts/apply_migrations.py --dry-run
.venv/Scripts/python.exe scripts/apply_migrations.py
```

İcraçı `kompasos.schema_migrations` reyestrinə yazır (migrations/061) — test
bazasında da eyni reyestr olur, yəni «hansı miqrasiya tətbiq olunub» sualı
orada da cavablıdır. Faylı əl ilə SQL redaktorunda işlətmək **test bazasında
da qadağandır**: reyestrsiz tətbiq olunmuş miqrasiya ilə növbəti buraxılışın
sınağı yanlış nəticə verər.

Vendor sxemi (`--vendor`) test mühitində **TƏTBİQ EDİLMİR**: `KOMPASOS_VENDOR_DSN`
boşdur, yəni vendor cədvəlləri lazım deyil (bax DB-3 qərarı,
`connection_types.py`).

### 2.4 Test kirayəçisi

```bash
.venv/Scripts/python.exe scripts/onboard_new_tenant.py --dev
```

`--dev` bayrağı **canlı datadan ayıran əsas mexanizmdir**: müştəri məlumatı
soruşulmur, nümunə kirayəçi yaradılır. `--verify` ilə quraşdırmanın tamlığı
yoxlanılır (`docs/onboarding.md`).

### 2.5 Root hesabı

```bash
.venv/Scripts/python.exe scripts/create_root_account.py
```

Şifrə gizli soruşulur (SEC-030). **Test mühitində DƏ güclü şifrə ver:**
zəif şifrə vərdişi test mühitindən canlıya köçür və test bazası tez-tez
paylaşılan maşınlarda qalır.

---

## 3. Canlı datanın surətini test mühitinə KÖÇÜRMƏ

**Qısa cavab: KÖÇÜRMƏ.**

Uzun cavab: canlı `employees`, `fines`, `attendance_records` cədvəllərində
real şəxsi məlumat (ad, telefon, üz embedding-i, cərimə səbəbləri) var. Test
mühiti daha zəif qorunur (paylaşılan maşın, sadə şifrə, ekran paylaşımı ilə
demo) — surət götürmək bütün həmin qorumaları test mühitinin səviyyəsinə
endirir.

Real həcmdə sınaq lazımdırsa **sintetik data** yaradın:
`scripts/onboard_new_tenant.py --dev` nümunə kirayəçi qurur, üstünə isə
`scripts/import_legacy_data.py` (Faza 9.3) ilə uydurma CSV yükləyin.

**İSTİSNA — sxem miqrasiyasının sınağı.** Yeni miqrasiyanın böyük cədvəldə
nə qədər çəkəcəyini ölçmək üçün canlı struktur lazımdır, MƏZMUN yox:

```bash
pg_dump --schema-only "$LIVE_DSN" | psql "$STAGING_DSN"
```

`--schema-only` MƏCBURİDİR. `--data-only`/tam dump şəxsi məlumat köçürər.

---

## 4. Nə vaxt istifadə olunur

| Hal | Test mühitində sınanır? |
|---|---|
| Yeni miqrasiya (`database/migrations/NNN_*.sql`) | **BƏLİ** — həmişə |
| Yeni buraxılış (`.exe`) müştəriyə göndərilməzdən əvvəl | **BƏLİ** — Faza 11.1 canary bundan sonra gəlir |
| Root parametrinin dəyişməsi | Xeyr — `system_limits` canlı mühitdə geri qaytarıla bilir |
| Kod dəyişikliyi (yeni ekran, düymə) | Bəli, lakin `pytest` qapısı ilk filtrdir |

---

## 5. Əlaqəli sənədlər

* `docs/onboarding.md` — yeni müştəri quraşdırması (canlı yol).
* `docs/region_migration.md` — region seçimi və ölçülmüş fərq.
* `docs/build_and_release.md` — buraxılış ardıcıllığı (SETUP-1).
* `v2backlog.md` Faza 9.4 — vendor-tərəfi biznes funksiyaları bu sənədə
  istinad edir (test mühiti müştəri məlumatının ixracını sınamaq üçün də
  işlədilir).
