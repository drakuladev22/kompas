"""Developer Panelini açır — `.env` YÜKLƏNMİŞ mühitdə.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA SKRİPT LAZIMDIR
──────────────────────────────────────────────────────────────────────────────
`python -m src.main --gui --developer-mode` təkbaşına İŞLƏMİR və səbəb aşkar
deyil: tətbiq `.env` faylını QƏSDƏN oxumur (`main.py::_check_dotenv` —
istehsalat maşınında sirrlər DPAPI/Secrets-dən gəlir, fayldan yox). Yəni adi
PowerShell pəncərəsində `DATABASE_URL` da, `KOMPASOS_DEVELOPER_MODE` da
mühitdə OLMUR və panel «konfiqurasiya edilməyib» deyir — halbuki dəyərlər
faylda var.

`scripts/apply_migrations.py` eyni problemi eyni yolla həll edir və yükləyici
məhz oradadır; burada TƏKRAR YAZILMIR, İDXAL edilir — iki nüsxə olsaydı biri
`.env` formatı dəyişəndə sükutla geridə qalardı.

Bu fayl `.exe`-yə DÜŞMÜR (`scripts/` paketlənmir) — `onboard_new_tenant.py`
ilə eyni qayda: hazırlayıcı aləti müştəri paketinin içində olmamalıdır.

İSTİFADƏ
    .venv/Scripts/python.exe scripts/dev_panel.py          # pəncərə
    .venv/Scripts/python.exe scripts/dev_panel.py --console  # cədvəl
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.apply_migrations import _load_dotenv  # noqa: E402

#: Panelin tələb etdiyi iki dəyişən və hər birinin İZAHI.
#:
#: Mesajda «nə etməli» YAZILIR: sadəcə «təyin edilməyib» demək istifadəçini
#: `.env.example`-i açıb axtarmağa məcbur edərdi və qüsurun özü də məhz belə
#: bir axtarışdan doğmuşdu (prefikssiz `SUPABASE_SERVICE_ROLE_KEY`).
_REQUIRED: dict[str, str] = {
    "KOMPASOS_DEVELOPER_MODE": "`.env`-ə `KOMPASOS_DEVELOPER_MODE=1` yazın",
    "KOMPASOS_SUPABASE_SERVICE_ROLE_KEY": (
        "Supabase → Project Settings → API Keys → `service_role` açarını "
        "kopyalayıb `.env`-dəki `KOMPASOS_SUPABASE_SERVICE_ROLE_KEY=` "
        "sətrinə yapışdırın"
    ),
    "DATABASE_URL": "`.env`-dəki `DATABASE_URL` boşdur — baza bağlantısı yoxdur",
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    _load_dotenv()

    missing = [key for key in _REQUIRED if not os.environ.get(key, "").strip()]
    if missing:
        sys.stderr.write("Developer Paneli açıla bilmir — çatışmayan dəyişən:\n")
        for key in missing:
            sys.stderr.write(f"  * {key}\n      {_REQUIRED[key]}\n")
        sys.stderr.write(f"\nFayl: {_REPO_ROOT / '.env'}\n")
        return 2

    # İDXAL BURADADIR, FAYLIN BAŞINDA YOX: `src.main` modul səviyyəsində
    # loglama qurur və mühiti oxuyur — `.env` yüklənməzdən əvvəl idxal
    # edilsəydi, dəyərlər hələ yox ikən oxunardı.
    from src.main import main as run

    # `--console` bayrağı YALNIZ BU SKRİPTİNDİR: `src.main` üçün fərq
    # `--gui`-nin OLMAMASIDIR. Tərsinə çevirmək istifadəçidən «pəncərə
    # istəmirəmsə hansı bayraq?» sualına cavab tapmağı tələb edərdi.
    console = "--console" in args
    forwarded = [item for item in args if item != "--console"]
    return run(["--developer-mode", *([] if console else ["--gui"]), *forwarded])


if __name__ == "__main__":
    raise SystemExit(main())
