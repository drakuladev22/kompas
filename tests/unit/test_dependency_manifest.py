"""Asılılıq manifestinin bütövlüyü.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TEST VACİBDİR
──────────────────────────────────────────────────────────────────────────────
`psycopg_pool` `connection.py`-da idxal olunurdu, lakin `requirements.txt`-də
YOX idi (`psycopg[binary]` onu GƏTİRMİR — ayrıca ekstradır). Paket lokal
mühitə təsadüfən düşmüşdü, ona görə bütün qapılar yaşıl idi və qüsur yalnız
TƏMİZ CI maşınında, `ModuleNotFoundError` kimi üzə çıxdı.

Belə qüsuru nə lint, nə mypy, nə də test tutur: hamısı ARTIQ quraşdırılmış
mühitdə işləyir. Yeganə statik müdafiə idxalları manifestlə tutuşdurmaqdır.

`pyproject.toml` ilə `requirements.txt` arasındakı uyğunluq da burada
yoxlanılır: ikisi ayrılsa `pip install -e .` ilə `pip install -r` FƏRQLİ
mühit qurar (bax `docs/dependency_policy.md`).
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]
REQUIREMENTS: Final = PROJECT_ROOT / "requirements.txt"
REQUIREMENTS_DEV: Final = PROJECT_ROOT / "requirements-dev.txt"
PYPROJECT: Final = PROJECT_ROOT / "pyproject.toml"

#: İdxal adı → paylanma (distribution) adı. Yalnız FƏRQLİ olanlar yazılır.
#: `PySide6`, `httpx`, `supabase`, `openpyxl`, `psycopg` adları eynidir.
IMPORT_TO_DISTRIBUTION: Final[dict[str, str]] = {
    "PIL": "pillow",
    "argon2": "argon2-cffi",
    "psycopg_pool": "psycopg",  # `psycopg[pool]` ekstrası ilə gəlir
    # `cv2` modulunu ÜÇ fərqli paylanma verir (`opencv-python`,
    # `opencv-contrib-python`, `opencv-python-headless`) və onlar bir-birini
    # ƏVƏZ ETMİR. Bizə `headless` lazımdır: adi variant öz Qt kitabxanalarını
    # daşıyır və PySide6 ilə eyni prosesdə plugin toqquşması yaradır (bax
    # `infrastructure/kiosk/camera.py` başlığı).
    "cv2": "opencv-python-headless",
    # Native pəncərə örtüyü (Aero Snap + Snap Layouts). Hər üç ad fərqlidir:
    # modul `qframelesswindow`, paylanma isə PyPI-də `PySideSix-Frameless-
    # Window` (PyQt variantından ayırmaq üçün). `win32*` modulları isə tək bir
    # `pywin32` paylanmasından gəlir — hər biri ayrıca paket kimi axtarılsaydı
    # manifest testi mövcud olmayan `win32gui` paketini tələb edərdi.
    "qframelesswindow": "pysidesix-frameless-window",
    "win32api": "pywin32",
    # `win32com` — 1C COM/OLE konnektoru (`erp/com_connector.py`). Eyni
    # `pywin32` paylanmasından gəlir; idxal FUNKSİYA DAXİLİNDƏDİR, çünki modul
    # Windows-dan kənarda da idxal olunur (bax həmin faylın başlığı).
    "win32com": "pywin32",
    "win32con": "pywin32",
    "win32gui": "pywin32",
}

#: Manifestdə olan, lakin `src/`-də İDXAL EDİLMƏYƏN paketlər.
#: Hər biri üçün səbəb yazılmalıdır — əks halda ölü asılılıq yığılır.
DECLARED_BUT_NOT_IMPORTED: Final[dict[str, str]] = {
    "pydantic": "supabase→realtime tranzitiv asılılığıdır; major keçidi "
    "nəzarətdə saxlamaq üçün açıq pinlənir",
    "python-dotenv": "quraşdırma skriptləri və `--strict` yoxlaması üçün "
    "saxlanılır (bax `main.py::_check_dotenv`)",
    "tenacity": "1C konnektorunun təkrar-cəhd siyasəti üçün nəzərdə tutulub",
    # --- Face Control (`facecontrol.md` Faza 3) ---------------------------- #
    "dlib-bin": "`face_recognition`-un C++ özəyi. `dlib` MODULUNU verir, lakin "
    "modul adı ilə paylanma adı fərqlidir — `src/` heç vaxt `dlib`-i birbaşa "
    "idxal etmir, ona görə burada görünür (bax requirements.txt, səbəb 1)",
    "face-recognition-models": "Dlib model faylları (~132 MB). Yalnız "
    "`pkg_resources` üzərindən, MƏTN AÇARI ilə yüklənir — heç bir `import` "
    "sətri onu göstərmir (bax requirements.txt, səbəb 2 və KompasOS.spec)",
    "setuptools": "ASILILIQ DEYİL, QORUYUCU PİN: 81+ `pkg_resources`-u çıxarır "
    "və `face_recognition` idxal anında `quit()` çağırır (bax requirements.txt, "
    "səbəb 3)",
}


def _requirement_names(path: Path) -> set[str]:
    """Fayldakı paket adları (ekstralar və hədlər atılır)."""
    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-")):
            continue
        names.add(_normalize(line))
    return names


def _normalize(spec: str) -> str:
    """`psycopg[binary,pool]>=3.3,<4.0` → `psycopg`."""
    return re.split(r"[<>=!\[;\s]", spec, maxsplit=1)[0].strip().lower().replace("_", "-")


def _extras(spec_source: str, package: str) -> set[str]:
    match = re.search(rf"^{re.escape(package)}\[([^\]]+)\]", spec_source, re.MULTILINE)
    return {part.strip() for part in match.group(1).split(",")} if match else set()


def _source_imports() -> dict[str, set[str]]:
    """`src/`-dəki bütün üçüncü tərəf idxalları → hansı fayllarda."""
    stdlib = set(sys.stdlib_module_names)
    local = {"src", "tests", "scripts"}
    found: dict[str, set[str]] = {}

    for path in (PROJECT_ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module.split(".")[0]] if node.module and node.level == 0 else []
            else:
                continue
            for name in names:
                if name and name not in stdlib and name not in local:
                    found.setdefault(name, set()).add(str(path.relative_to(PROJECT_ROOT)))
    return found


# --------------------------------------------------------------------------- #
# Qapı: mənbələr oxunur
# --------------------------------------------------------------------------- #


def test_manifest_files_exist() -> None:
    """Qapı: fayl tapılmasa aşağıdakı testlər yanlış olaraq "keçər"."""
    assert REQUIREMENTS.exists()
    assert REQUIREMENTS_DEV.exists()
    assert PYPROJECT.exists()
    assert _source_imports(), "`src/`-də heç bir üçüncü tərəf idxalı tapılmadı"


# --------------------------------------------------------------------------- #
# İdxal ↔ manifest
# --------------------------------------------------------------------------- #


def test_every_third_party_import_is_declared() -> None:
    """`src/`-də idxal edilən hər paket `requirements.txt`-də olmalıdır."""
    declared = _requirement_names(REQUIREMENTS)
    missing: list[str] = []

    for module, files in sorted(_source_imports().items()):
        distribution = IMPORT_TO_DISTRIBUTION.get(module, module.lower().replace("_", "-"))
        if distribution not in declared:
            missing.append(f"{module} (paket: {distribution}) — {sorted(files)[0]}")

    assert not missing, (
        "Bu paketlər idxal olunur, lakin requirements.txt-də yoxdur — "
        "təmiz maşında ModuleNotFoundError verəcək:\n  " + "\n  ".join(missing)
    )


def test_psycopg_declares_the_pool_extra() -> None:
    """`psycopg_pool` AYRICA paketdir — `psycopg[binary]` onu gətirmir.

    Məhz bu ekstranın unudulması CI-ı qırmışdı; test onu kilidləyir.
    """
    source = REQUIREMENTS.read_text(encoding="utf-8")
    assert "psycopg_pool" in _source_imports(), "İdxal yoxdursa bu qayda da lazım deyil"
    assert "pool" in _extras(source, "psycopg"), (
        "`psycopg[...]` ekstralarında `pool` yoxdur — `psycopg_pool` quraşdırılmayacaq"
    )


def test_declared_but_unused_packages_are_justified() -> None:
    """İdxal edilməyən paket ölü asılılıq ola bilər — səbəbi yazılmalıdır."""
    imported = {
        IMPORT_TO_DISTRIBUTION.get(module, module.lower().replace("_", "-"))
        for module in _source_imports()
    }
    unexplained = [
        name
        for name in _requirement_names(REQUIREMENTS)
        if name not in imported and name not in DECLARED_BUT_NOT_IMPORTED
    ]
    assert not unexplained, (
        "Bu paketlər manifestdədir, lakin nə idxal olunur, nə də səbəbi "
        f"`DECLARED_BUT_NOT_IMPORTED`-da yazılıb: {sorted(unexplained)}"
    )


# --------------------------------------------------------------------------- #
# Manifestlər arasında uyğunluq
# --------------------------------------------------------------------------- #


def _pyproject_specs() -> tuple[list[str], list[str]]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data["project"]
    return project["dependencies"], project["optional-dependencies"]["dev"]


def test_pyproject_matches_requirements() -> None:
    """İki mənbə ayrılsa `pip install -e .` fərqli mühit qurar."""
    runtime, dev = _pyproject_specs()

    assert {_normalize(spec) for spec in runtime} == _requirement_names(REQUIREMENTS)
    # `requirements-dev.txt` `-r requirements.txt` ilə başlayır, ona görə
    # onun öz sətirləri yalnız dev alətləridir.
    assert {_normalize(spec) for spec in dev} == _requirement_names(REQUIREMENTS_DEV)


def test_every_dependency_has_a_tested_lower_bound() -> None:
    """`>=` olmayan sərbəst asılılıq sınanmamış versiya gətirə bilər."""
    runtime, dev = _pyproject_specs()
    unbounded = [spec for spec in runtime + dev if ">=" not in spec]
    assert not unbounded, f"Alt həddi olmayan asılılıqlar: {unbounded}"


def test_every_dependency_has_an_upper_bound() -> None:
    """Major buraxılış uyğunluğu pozmaq üçün var — avtomatik qəbul edilmir.

    Səbəb `docs/dependency_policy.md`-dədir. İstisna `types-*` stub-larıdır:
    onlar öz paketlərinin versiyasını izləyir və major anlayışı daşımır.
    """
    runtime, dev = _pyproject_specs()
    unbounded = [
        spec
        for spec in runtime + dev
        if "<" not in spec and not _normalize(spec).startswith("types-")
    ]
    assert not unbounded, f"Üst həddi olmayan asılılıqlar: {unbounded}"
