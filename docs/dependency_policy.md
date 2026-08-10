# ASILILIQ SİYASƏTİ

**Son yenilənmə:** 2026-08-10 · **Zəiflik sayı:** 0 (`pip-audit`)

---

## Qayda: alt hədd = SINAQDAN KEÇMİŞ versiya

`requirements.txt`, `requirements-dev.txt` və `pyproject.toml`-dakı hər
asılılıq belə yazılır:

```
paket>=<qapılardan keçmiş versiya>,<<növbəti major>
```

**Niyə "işlək ən köhnə versiya" DEYİL.** Əvvəl hədlər ilk dəfə işləyən
versiyada qalmışdı (`mypy>=1.9`, `pytest>=8.0`, `ruff>=0.3`). Belə diapazon
CI-a heç vaxt sınanmamış versiyanı quraşdırmağa icazə verir:

| Alət | Köhnə hədd | Fərq |
|---|---|---|
| `mypy` | `>=1.9` | 2.x sərtlik səviyyəsini dəyişib — 1.9 keçən kod 2.3-də keçməyə bilər (və əksinə) |
| `pytest` | `>=8.0` | 9.x fixture/`-p` davranışını dəyişib |
| `pytest-asyncio` | `>=0.23` | 1.0-da defolt rejim dəyişib |
| `ruff` | `>=0.3` | Hər minor yeni qayda gətirir; 0.3 bu repodakı `noqa` kodlarını tanımır |

"Quraşdırılır" ilə "yoxlanılıb" eyni şey deyil. Yaşıl CI yalnız o halda
mənalıdır ki, orada işləyən alət versiyası bizim işlətdiyimizlə eyni olsun.

**Niyə üst hədd var.** Major buraxılış məhz uyğunluğu pozmaq üçün var —
onu avtomatik qəbul etmək CI-ın bir səhər səbəbsiz qırılması deməkdir.

**`ruff` istisnası:** o, 1.0-dan əvvəldir və hər MINOR-da yeni qayda əlavə
edir. Yeni qayda mövcud kodu "pozulmuş" göstərə bilər, ona görə hədd minor
səviyyəsində bağlanır (`>=0.16.2,<0.17`).

---

## Yeni versiyaya keçid proseduru

```bash
.venv/Scripts/python.exe -m pip list --outdated
.venv/Scripts/python.exe -m pip install --upgrade <paket>
# Sonra HAMISI keçməlidir:
.venv/Scripts/python.exe -m ruff check src/ tests/ scripts/
.venv/Scripts/python.exe -m ruff format --check src/ tests/ scripts/
.venv/Scripts/python.exe -m mypy src
.venv/Scripts/python.exe -m pytest tests/ -q
.venv/Scripts/python.exe scripts/check_contrast.py --include-high-contrast
```

Qapılar keçdikdən SONRA hədd üç faylda birdən qaldırılır:
`requirements.txt`, `requirements-dev.txt`, `pyproject.toml`. Üçü ayrılsa
`pip install -e .` ilə `pip install -r requirements.txt` FƏRQLİ mühit qurar.

---

## `pip list --outdated` HƏMİŞƏ sıfır olmur — və olmamalıdır

Bəzi paketlər valideyn asılılıq tərəfindən QƏSDƏN məhdudlaşdırılıb. Onları
"yeniləmək" mühiti pozur:

| Paket | Kim məhdudlaşdırır | Hədd |
|---|---|---|
| `chardet` | `cyclonedx-bom` | `<6.0` |
| `pydantic-core` | `pydantic` | dəqiq bərabərlik (`==`) |
| `websockets` | `realtime` (supabase) | `<16` |

Bunları əl ilə qaldırmaq `pip check`-i qırır. Doğru yol valideyn paketin
yeni buraxılışını gözləməkdir.

**Yoxlama:** `pip check` → *"No broken requirements found"*. Bu, sadəcə
"outdated siyahısı boşdur"-dan daha etibarlı göstəricidir.

---

## Zəiflik skanı

```bash
.venv/Scripts/python.exe -m pip_audit           # bütün mühit
.venv/Scripts/python.exe -m pip_audit -r requirements.txt
```

CI hər PR-da işlədir (`.github/workflows/ci.yml`). Zəiflik tapılarsa
düzəldilmiş versiyaya keçid qapıların yenidən işlədilməsi ilə birlikdə
edilir — təhlükəsizlik yeniləməsi də sınaqsız qəbul edilmir.

---

## Cari vəziyyət (2026-08-10)

| Paket | Versiya | Paket | Versiya |
|---|---|---|---|
| PySide6 | 6.11.1 | pytest | 9.1.1 |
| cryptography | 50.0.0 | pytest-cov | 7.1.0 |
| argon2-cffi | 25.1.0 | pytest-asyncio | 1.4.0 |
| supabase | 2.31.0 | pytest-qt | 4.5.0 |
| psycopg[binary] | 3.3.4 | pytest-timeout | 2.4.0 |
| httpx | 0.28.1 | mypy | 2.3.0 |
| pydantic | 2.13.4 | ruff | 0.16.2 |
| python-dotenv | 1.2.2 | pip-audit | 2.x |
| openpyxl | 3.1.5 | cyclonedx-bom | 7.3.1 |
| Pillow | 12.3.0 | | |
| tenacity | 9.1.4 | | |

Bu versiyalarla: **1363 test keçir**, domen coverage **92.46%**, mypy strict
200 faylda təmiz, zəiflik yoxdur.
