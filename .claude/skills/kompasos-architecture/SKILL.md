---
name: kompasos-architecture
description: KompasOS-un dəyişməz struktur qaydaları — rol iyerarxiyası, hardlock, «Root parametri» qaydası, qat sırası, qırmızı xətlər. İstənilən fayla toxunmazdan ƏVVƏL oxu.
---

# KompasOS — Dəyişməz Arxitektura Qaydaları

## Bu sənəd necə oxunur

Aşağıdakı qaydalar KODDA artıq təsbit olunub. Bu fayl onların NÜSXƏSİ deyil,
XƏRİTƏSİDİR: hər bənd hansı faylın həqiqi mənbə olduğunu göstərir. **Şübhə
düşəndə mənbə fayla bax, bu sənədə yox** — nüsxə köhnəlir, mənbə köhnəlmir.
Bu sənədlə kod ziddiyyət təşkil edirsə: kod + `CLAUDE.md` qalib gəlir, sən isə
ziddiyyəti lead-ə bildirirsən.

## 1. Rol iyerarxiyası — DƏYİŞMƏZ

```
Root = 0   ← tək başına ən üst pillə
CEO  = 1   ← Root-dan DƏRHAL aşağı, AYRI pillə
Admin = 2
HR_Admin / Mağaza_Meneceri / Kamera_Nəzarətçisi = 3
Satıcı və digər personel = 4
```

Kiçik rəqəm = yüksək səlahiyyət. **Root və CEO EYNİ pillədə DEYİL** — bu, ən
tez-tez edilən səhvdir. Root təchizatçının hesabıdır, CEO müştərinin.

`Strict Hierarchy Guard`: aktor yalnız CİDDİ ŞƏKİLDƏ aşağı pilləyə toxuna
bilər — eyni pilləyə YOX.

**MƏNBƏ:** `src/domain/value_objects/authorization.py` (`RolePriority`).

## 2. Hardlock — dörd səviyyə

| Səviyyə | Kim verə bilər |
|---|---|
| `NONE` | adi operativ flag — rol-defolt + fərdi override |
| `ROOT_ONLY` | yalnız `Root` — `CEO`-ya BELƏ verilmir |
| `ROOT_CEO` | `Root` VƏ `CEO` |
| (anti-fraud) | aşağıya bax — rol qadağası, pillə qadağası deyil |

**MƏNBƏ:** `authorization.py` → `HardlockLevel`. Flag-in hansı səviyyədə
olduğu flag kataloqunda (`hardlock:` sahəsi) yazılır — təxmin etmə, oxu.

## 3. Anti-fraud vəzifə ayrılığı — POZULMAZ

`can_verify_returns`, `can_override_return_time`, `can_issue_fines`,
`can_approve_dual_control_override` flag-ləri **Mağaza_Meneceri** və
**Satıcı** rollarına HEÇ VAXT verilmir — Root-un özü belə verə bilməz.

Səbəb: gedişi qeyd edən şəxs onu təsdiqləyən şəxs OLA BİLMƏZ. Bu, konfiqurasiya
deyil, struktur zəmanətdir.

**SEC-001:** kamera-tipli rol dual-control təsdiqini daşıya bilməz.

**Self-Escalation Guard:** aktor yalnız ÖZÜNDƏ olan flag-i başqasına verə bilər.

**MƏNBƏ:** `authorization.py` → `ANTI_FRAUD_FORBIDDEN_ROLES`,
`DUAL_CONTROL_APPROVAL_FLAG`. **Qayda İKİ yerdədir:** domendə VƏ
`database/schema.sql` §18 trigger-ində (`enforce_anti_fraud_segregation()`).
Birini dəyişəndə DİGƏRİ də dəyişməlidir — əks halda qapı quraşdırma
yolundan asılı olur (DB-1 auditi məhz bunu tapmışdı).

## 4. «Root parametri» qaydası

Konfiqurasiya edilə bilən HƏR ədəd / hədd / müddət `system_limits`-dədir,
koda hardcode EDİLMİR.

| Nə | Hara |
|---|---|
| Limit / taymaut | `SystemLimitKey` + `DEFAULT_LIMITS` (`src/domain/policies.py`) |
| Modul açarı | `FeatureModule` (`policies.py`) |
| İcazə flag-i | `permission_flags` (GUI-dan, Root) |

Sinifdəki sabit YALNIZ **fallback** ola bilər və şərhində bunun fallback
olduğu YAZILMALIDIR.

**İSTİSNA — «Root parametri DEYİL»:** bəzi sabitlər tərifin özüdür və Root-a
verilsəydi mənasını itirərdi (məs. `_IDENTIFY_MARGIN`, `SHORT_CODE_LENGTH`).
Siyahı BAĞLIDIR və `CLAUDE.md` §5-dədir — yenisini ora əlavə etmə, lead-ə
sual ver.

## 5. Qat sırası pozulmur

```
domain  ←  application  ←  infrastructure
   ↑            ↑                ↑
   └────────────┴──── presentation
```

* `domain/` heç vaxt `psycopg`, `supabase`, `httpx`, `PySide6` idxal etmir.
* Portlar `domain/interfaces/ports.py`-da `Protocol` kimi təyin olunur,
  `infrastructure/`-da implementasiya olunur (miras YOX).
* Modullar bir-birinə birbaşa müraciət etmir — `shared/event_bus.py`.
* Çox-aqreqatlı əməliyyat = Saga (kompensasiya ilə).

## 6. Vaxt

Bütün `datetime` tz-aware. Domen kodu `datetime.now()` ÇAĞIRMIR — `Clock`
portu (artıq `ServerTimeService`). Kritik vaxt-möhürləri (`created_at`,
`fines.published_at`) DB trigger-i ilə SERVER vaxtına məcbur edilir
(TIME-1, `migrations/062`) — client vaxtına etibar yoxdur.

## 7. Qırmızı xətlər

1. **Mövcud işləyən funksiya SİLİNMİR / YENİDƏN YAZILMIR** — yalnız əlavə
   edilir və ya minimal düzəldilir.
2. **1C-yə yeni bağlantı nöqtəsi AÇILMIR** — yalnız mövcud bal/satış kanalı.
3. **Placeholder QADAĞANDIR** — `# TODO`, `pass  # sonra`,
   `raise NotImplementedError` (Protocol imzasından başqa) yazılmır.
4. **Dil:** bütün şərhlər, docstring-lər, istifadəçi mətnləri və log
   açarları Azərbaycan dilindədir. Sinif/metod adları ingiliscədir.
5. **Şərhlər NİYƏ-ni izah edir, NƏ-ni yox** — alternativin niyə rədd
   edildiyi yazılır.

## 8. Toxunmazdan əvvəl

Dəyişiklikdən sonra HAMISI keçməlidir:

```bash
.venv/Scripts/python.exe -m ruff check src/ tests/ scripts/
.venv/Scripts/python.exe -m mypy src
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/ -q
```

`QT_QPA_PLATFORM=offscreen` OPSİYONAL DEYİL — onsuz dəst saatlarla çəkir.
