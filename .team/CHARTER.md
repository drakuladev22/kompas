# KompasOS Audit Komandası — Nizamnamə (ARCHITECT tərəfindən verilir)

## Rollar
| Agent | Sahə |
|---|---|
| ARCHITECT (əsas sessiya, Opus) | Orkestr, ziddiyyət həlli, kənar hallar, YEKUN TƏSDİQ |
| security | RLS, permission-guard, hardlock, sirlər, şifrələmə, SQL injection |
| domain | biznes məntiqi, use case-lər, entity qaydaları, saga |
| infra | Supabase/persistence, miqrasiya, config, build/installer, Telegram |
| ui | PySide6 ekranlar, kontrollerlər, threading, QSS/tema |
| qa | testlər, kod toqquşmaları, statik qapılar |

## FAYL SAHİBLİYİ (POZULMAZ)
- **security**: `src/domain/value_objects/authorization.py`, `src/application/use_cases/permission_guards.py`,
  `src/application/use_cases/dual_control_guard.py`, `src/infrastructure/security/**`,
  `src/infrastructure/config/**`, `scripts/create_root_account.py`
- **domain**: `src/domain/**` (yuxarıdakı authorization.py İSTİSNA), `src/application/**`
  (permission_guards.py, dual_control_guard.py İSTİSNA), `src/shared/**`
- **infra**: `src/infrastructure/**` (security/, config/ İSTİSNA), `database/**`, `scripts/**`
  (create_root_account.py İSTİSNA), `installer/**`, `pyproject.toml`
- **ui**: `src/presentation/**`, `src/developer_panel/**`
- **qa**: `tests/**` — SRC FAYLINA TOXUNMUR

Başqasının faylında qüsur görürsənsə: **DÜZƏLTMƏ** — hesabatında
`SAHİBİNƏ: <agent> — <fayl>:<sətir> — <problem>` formatında yaz.
Sxem/DB dəyişikliyini YALNIZ `infra` edir.

## QIRMIZI XƏTLƏR (CLAUDE.md §4, §5)
- `# TODO`, `pass  # sonra`, `raise NotImplementedError` (Protocol imzasından başqa) QADAĞAN.
- Şərhlər NİYƏ-ni izah edir, Azərbaycan dilində.
- Bütün `datetime` tz-aware; domendə `datetime.now()` YOX — `Clock` portu.
- SQL 100% parametrləşdirilmiş.
- Hardcoded sabit: ya struktur zəmanət, ya `system_limits`, ya CLAUDE.md §5-dəki
  «Root parametri deyil» siyahısı. Yeni sabit yazmadan əvvəl bunu yoxla.
- Qat sırası: domain ← application ← infrastructure; presentation hamısına baxır.

## MƏCBURİ OXU (işə başlamazdan əvvəl, `cat` ilə)
- `CLAUDE.md`
- `.claude/skills/kompasos-architecture/SKILL.md`
- öz sahənə uyğun: `.claude/skills/kompasos-security/SKILL.md` və ya `kompasos-ui/SKILL.md`

## QAPILAR (dəyişiklikdən sonra sən özün işlət)
```
.venv/Scripts/python.exe -m ruff check src/ tests/ scripts/
.venv/Scripts/python.exe -m ruff format src/ tests/ scripts/
.venv/Scripts/python.exe -m mypy src
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/unit -q
```
Tam dəst (`tests/`) ~55 dəq çəkir — YALNIZ ARCHITECT icazəsi ilə.

## HESABAT FORMATI (hər dövrədə, mətnlə qaytar)
```
## TAPINTILAR
[ID] SEVERITY(BLOCKER|HIGH|MED|LOW) fayl:sətir — problem — NİYƏ xətadır — təklif
## SAHİBİNƏ
<agent> — fayl:sətir — problem
## DÜZƏLİŞLƏR (bu dövrədə etdiklərim)
fayl:sətir — nə dəyişdi — hansı testlə sübut olunur
## QAPI NƏTİCƏSİ
ruff/mypy/pytest çıxışının SON sətirləri
```
Uydurma YOXDUR: hər iddia fayl:sətir və ya əmr çıxışı ilə sübut olunur.
