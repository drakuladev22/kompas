# Fernet Master Açarının İdarə Edilməsi və Rotasiyası

> Spesifikasiya bölmə 2: *"Fernet master key heç vaxt DB-də və ya config faylında
> plaintext saxlanılmır. Açar env variable və ya OS-səviyyəli credential store
> (Windows DPAPI) vasitəsilə təchiz olunur, key-rotation prosedur sənədləşdirilir."*

---

## 1. Açar hansı məlumatı qoruyur?

| Məlumat | Cədvəl / sahə |
|---|---|
| 1C server şifrələri | `erp_servers.password_encrypted` |
| Server konfiqurasiya backup-ları | `erp_server_config_backups.config_json_encrypted` |
| TOTP 2FA sirləri | `employees.totp_secret_encrypted` |

**Açar bunları qorumur:** şifrələr və PIN-lər Argon2id ilə *hash*-lənir (geri
çevrilə bilməz), Fernet ilə şifrələnmir. Açarın itməsi hesabları bağlamır,
yalnız ERP bağlantılarının yenidən daxil edilməsini tələb edir.

---

## 2. Açar mənbələri (prioritet sırası)

`ChainedKeyProvider` aşağıdakı ardıcıllıqla yoxlayır:

1. **`KOMPASOS_FERNET_KEY`** mühit dəyişəni — CI/CD (GitHub Secrets) və server mühiti
2. **Windows DPAPI blobu** — mağaza kiosk PC-ləri
   (`%LOCALAPPDATA%\KompasOS\kompasos.key`, cari Windows istifadəçisinə bağlı)

Heç biri tapılmasa tətbiq `EncryptionKeyError` ilə dayanır — **plaintext
fallback YOXDUR**, bu qəsdəndir.

---

## 3. Yeni açar yaratmaq

```bash
python -c "from src.infrastructure.security.encryption import generate_key; print(generate_key())"
```

44 simvolluq base64 sətir alacaqsınız (32 bayt açar materialı).

### Windows kiosk PC-də DPAPI ilə saxlamaq

```python
from src.infrastructure.security.encryption import (
    KeyMaterial, WindowsDpapiKeyProvider, generate_key,
)

provider = WindowsDpapiKeyProvider()
provider.store(KeyMaterial(primary=generate_key()))
```

Blob faylı DPAPI ilə şifrələnir — başqa maşında və ya başqa Windows
istifadəçisi altında açılmır.

---

## 4. Rotasiya proseduru

Rotasiya `MultiFernet` üzərində qurulub: **yeni məlumat həmişə birinci
(cari) açarla şifrələnir, köhnə açarlarla şifrələnmiş məlumat isə hələ də
oxunur.** Buna görə rotasiya kəsintisizdir.

### Addım-addım

**1. Yeni açar yarat**

```bash
NEW_KEY=$(python -c "from src.infrastructure.security.encryption import generate_key; print(generate_key())")
```

**2. Konfiqurasiyanı yenilə** — köhnə açarı `PREVIOUS` siyahısına köçür:

```bash
KOMPASOS_FERNET_KEY=<YENİ_AÇAR>
KOMPASOS_FERNET_KEY_PREVIOUS=<KÖHNƏ_AÇAR>
```

> GitHub Secrets-də: əvvəlcə `KOMPASOS_FERNET_KEY_PREVIOUS`-u yarat, **sonra**
> `KOMPASOS_FERNET_KEY`-i dəyiş. Tərs sıra qısa müddətli oxuma xətası yaradır.

**3. Tətbiqi yenidən başlat** (və ya `EncryptionService.reload()` çağır).
Bu andan etibarən sistem işləkdir: köhnə məlumat oxunur, yeni məlumat yeni
açarla yazılır.

**4. Mövcud token-ləri yeni açara keçir** (maintenance window daxilində):

```python
from src.infrastructure.security.encryption import EncryptionService

service = EncryptionService()
for row in repo.fetch_all_encrypted_rows():
    repo.update(row.id, service.rotate_token(row.token))
```

`rotate_token()` məlumatı plaintext olaraq yaddaşda saxlamadan yenidən
şifrələyir.

**5. Yoxla** — bütün sətirlərin yeni açarla oxunduğunu təsdiqlə, sonra
`KOMPASOS_FERNET_KEY_PREVIOUS`-u **silin**. Köhnə açar artıq lazım deyil.

**6. Audit** — rotasiya hadisəsini `audit_logs`-a yaz
(`action = 'ENCRYPTION_KEY_ROTATED'`). Açarın ÖZÜ heç vaxt log-a yazılmır;
`security.log`-a yalnız `ENCRYPTION_KEY_LOADED` + mənbə adı düşür.

---

## 5. Rotasiya cədvəli

| Hal | Tezlik |
|---|---|
| Planlı rotasiya | ildə 1 dəfə |
| Açara çıxışı olan işçi ayrılanda | dərhal |
| Şübhəli hadisə / sızma ehtimalı | dərhal, addım 4 məcburi |

---

## 6. Açar itirilibsə

1. Hesablar və PIN-lər **təsirlənmir** (Argon2 hash-ləri açardan asılı deyil).
2. `erp_servers` sətirlərindəki şifrələr oxunmaz olur → Bağlantı Sihirbazından
   (bölmə 7) hər server üçün şifrə yenidən daxil edilir.
3. TOTP sirləri oxunmaz olur → hər admin-tier istifadəçi üçün 2FA yenidən
   qurulur (`can_reset_password` sahibi tərəfindən).
4. Hadisə `audit_logs`-a yazılır və tenant-a bildirilir.

---

## 7. Alqoritm: AES-256-GCM (SEC-002)

Spesifikasiya "Fernet AES-256" ifadəsini işlədirdi. Fernet faktiki olaraq
32 baytlıq açarı ikiyə bölür — 16 bayt HMAC-SHA256, 16 bayt **AES-128**-CBC —
yəni hərfi mənada AES-256 deyil.

**Qərar:** əsas şifrə **AES-256-GCM**-ə keçirildi
([SEC-002](security_decisions.md)):

| | Köhnə (Fernet) | Cari (AES-256-GCM) |
|---|---|---|
| Şifrə | AES-128-CBC | **AES-256** |
| Bütövlük | ayrıca HMAC-SHA256 | GCM teqi (AEAD) |
| Kontekst bağlantısı | yoxdur | **AAD** dəstəklənir |
| Token formatı | `gAAAAA…` | `v1.<key_id>.<base64>` |
| Açar seçimi | sınaqla (bütün açarlar) | `key_id` ilə birbaşa |

**Geriyə uyğunluq:** köhnə Fernet token-ləri **oxunmağa davam edir**.
`rotate_token()` onları avtomatik yeni sxemə köçürür — ayrıca miqrasiya kodu
lazım deyil. `needs_rotation()` hansı sətirlərin köçürülməli olduğunu göstərir.

### AAD (kontekst) istifadəsi

Şifrəli dəyər öz sətrinə bağlanmalıdır ki, onu başqa sətrə köçürmək
mümkün olmasın:

```python
token = service.encrypt(password, context=f"erp_server:{server_id}")
plain = service.decrypt(token, context=f"erp_server:{server_id}")   # eyni kontekst MƏCBURİ
```

Standart kontekstlər:

| Sahə | Kontekst |
|---|---|
| `erp_servers.password_encrypted` | `erp_server:<server_id>` |
| `erp_server_config_backups.config_json_encrypted` | `erp_server:<server_id>` |
| `employees.totp_secret_encrypted` | `totp:<employee_id>` |

---

## 8. Hash pepper-in rotasiyası (SEC-005) — DİQQƏT

`KOMPASOS_HASH_PEPPER` şifrələmə açarından **fərqlidir** və onun rotasiyası
**geri qaytarıla bilməz**:

- Şifrələmə iki tərəflidir → köhnə açarla açıb yenisi ilə bağlamaq olar.
- Hash **bir tərəflidir** → köhnə pepper ilə yaradılmış Argon2 hash-i yeni
  pepper-ə "çevirmək" **mümkün deyil** (plaintext PIN əlində yoxdur).

Ona görə pepper dəyişdirilərsə **bütün PIN və şifrələr etibarsız olur**.

### Hazırkı prosedur (Faza 1)

1. Maintenance window elan et.
2. Bütün admin-tier istifadəçilər üçün müvəqqəti şifrə təyin et
   (`can_reset_password`), bütün işçilər üçün PIN sıfırla (`can_reset_pin`).
3. `KOMPASOS_HASH_PEPPER`-i dəyiş, tətbiqi yenidən başlat.
4. İstifadəçilər ilk girişdə yeni PIN/şifrə təyin edir.

### Təklif olunan təkmilləşdirmə (Faza 2 qərarınızı gözləyir)

`employees.pepper_version` sütunu əlavə edilsə, iki pepper paralel saxlanıla
bilər: köhnə pepper köhnə sətirlər üçün yoxlamada istifadə olunar, **uğurlu
girişdən sonra** hash yeni pepper ilə yenidən yazılar (lazy migration).
Bu, kütləvi sıfırlamaya ehtiyacı aradan qaldırır.

**Nə vaxt pepper rotasiyası lazımdır?** Yalnız pepper-in sızması şübhəsi
olduqda. Planlı rotasiya **tövsiyə olunmur** — faydası yoxdur, riski var.
