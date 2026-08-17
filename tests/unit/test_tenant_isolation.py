"""Çox-müştəri izolyasiyası və brendinq qapısı (TENANT-1).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
Bu layihədə müştərilər bir-birinə RƏQİB ola bilər (Yataş vs Embawood). Bir
RLS/kod səhvi rəqiblərin datasını qarışdırarsa, nəticə texniki qüsur deyil,
BİZNES FƏLAKƏTİdir. Ona görə izolyasiya üç qatlıdır və bu fayl onların
hamısının YERİNDƏ olduğunu yoxlayır:

    1. FİZİKİ  — hər müştəri ayrı Supabase layihəsi (ayrı DSN);
    2. STRUKTUR — tətbiqdə «tenant seçimi» UI elementi YOXDUR;
    3. SORĞU   — hər repozitoriya açıq `tenant_id` şərti yazır (RLS-ə əlavə).

İkinci qat ən kövrəkdir, çünki onu pozmaq üçün pis niyyət lazım deyil —
«adminə rahatlıq üçün bir seçim qutusu» əlavə etmək kifayətdir. Qapı məhz
onu maşınla saxlayır.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest

from src.application.use_cases.tenant_branding import (
    BrandingPermissionError,
    BrandingValidationError,
    TenantBrandingUseCase,
)
from src.domain.value_objects.branding import (
    DEFAULT_BRANDING,
    MAX_COMPANY_NAME_CHARS,
    MAX_LOGO_BYTES,
    PNG_SIGNATURE,
    BrandingError,
    TenantBranding,
    relative_luminance,
)

pytestmark = pytest.mark.unit

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_PRESENTATION: Final[Path] = _REPO_ROOT / "src" / "presentation"

#: Developer Paneli İSTİSNADIR və bu, TENANT-1 Faza 3-ün açıq qərarıdır:
#: vendor konsolu bütün kirayəçiləri GÖRÜR (yalnız metadata) və orada seçim
#: elementi legitimdir. O panel müştəri `.exe`-sinə DAXİL EDİLMİR.
_EXEMPT_DIRS: Final[frozenset[str]] = frozenset({"developer_panel"})

#: «Tenant seçimi» əlaməti sayılan naxışlar. Axtarış MƏTNDƏ aparılır, çünki
#: element hər hansı widget ola bilər (`QComboBox`, siyahı, düymə) — ortaq
#: cəhət seçimin TENANT üzərində olmasıdır.
_TENANT_PICKER_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"tenant.{0,20}(combo|picker|selector|chooser|dropdown)", re.IGNORECASE),
    re.compile(r"(combo|picker|selector|chooser|dropdown).{0,20}tenant", re.IGNORECASE),
    re.compile(r"select_tenant|switch_tenant|choose_tenant|set_tenant_id", re.IGNORECASE),
)


def _presentation_files() -> list[Path]:
    return [
        path
        for path in _PRESENTATION.rglob("*.py")
        if not _EXEMPT_DIRS.intersection(path.parts) and "__pycache__" not in path.parts
    ]


# --------------------------------------------------------------------------- #
# 1. Struktur qat — «tenant seçimi» UI elementi YOXDUR
# --------------------------------------------------------------------------- #


def test_no_tenant_picker_exists_in_the_presentation_layer() -> None:
    """Tətbiq öz kirayəçisini SEÇMİR — onu OXUYUR.

    Seçim elementi olsaydı, səhv seçim bir müştərini digərinin bazasına
    aparardı və nəticə «boş ekran» kimi deyil, YANLIŞ MƏLUMAT kimi görünərdi
    (RLS başqa tenant-ın sətirlərini gizlədir, lakin bağlantının ÖZÜ səhv
    layihəyə gedərdi).
    """
    offenders: list[str] = []
    for path in _presentation_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            # Şərh sətirləri buraxılır: bu faylın ÖZÜ və `composition.py`
            # qərarı izah edərkən həmin sözləri işlədir.
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            for pattern in _TENANT_PICKER_PATTERNS:
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(_REPO_ROOT)}:{line_no}: {stripped[:80]}")

    assert not offenders, (
        "Təqdimat qatında «tenant seçimi» əlaməti tapıldı — TENANT-1 Faza 1.3 "
        "bunu QADAĞAN edir (vendor konsolu istisnadır):\n  " + "\n  ".join(offenders)
    )


def test_the_application_context_takes_exactly_one_tenant() -> None:
    """`ApplicationContext` bir `tenant_id` alır və onun SETTER-i yoxdur.

    Setter olsaydı, işləyən tətbiq iş vaxtı başqa kirayəçiyə «keçə» bilərdi —
    və o keçid açıq bağlantı hovuzunu, keşləri, sessiya obyektlərini köhnə
    kirayəçinin məlumatı ilə qoyardı.
    """
    source = (_PRESENTATION / "composition.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    context_class = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "ApplicationContext"
    )
    setters = [
        node.name
        for node in context_class.body
        if isinstance(node, ast.FunctionDef) and node.name in {"set_tenant_id", "switch_tenant"}
    ]
    assert not setters, f"`ApplicationContext`-də kirayəçi dəyişdirən metod var: {setters}"

    init = next(
        node
        for node in context_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    names = {arg.arg for arg in init.args.kwonlyargs} | {arg.arg for arg in init.args.args}
    assert "tenant_id" in names, "`ApplicationContext.__init__` `tenant_id` qəbul etmir"


def test_the_onboarding_script_is_not_packaged() -> None:
    """`scripts/onboard_new_tenant.py` müştəri `.exe`-sinə DÜŞMÜR.

    Skript VENDOR bazasına yazır: müştəri maşınında olsaydı, istənilən adam
    özünə «AKTİV» lisenziya sətri yarada bilərdi.
    """
    spec = (_REPO_ROOT / "src" / "KompasOS.spec").read_text(encoding="utf-8")
    assert "onboard_new_tenant" not in spec
    # `scripts/` qovluğunun ÖZÜ də paketə salınmamalıdır — bir gün başqa
    # skript əlavə olunanda bu qapı onu da tutsun.
    assert "'scripts'" not in spec
    assert '"scripts"' not in spec


# --------------------------------------------------------------------------- #
# 2. Brendinq — YALNIZ vizual qat
# --------------------------------------------------------------------------- #


def test_branding_carries_no_security_or_rbac_field() -> None:
    """Brendinq tipində qadağa zəiflədə biləcək sahə OLMAMALIDIR.

    `CLAUDE.md` §5: «müştəri istədi» hər struktur zəmanətin yan keçilməsi
    üçün bəhanəyə çevrilərdi. Qapı sahə adlarını yoxlayır — yeni sahə əlavə
    edən adam əvvəlcə bu siyahını görməlidir.
    """
    allowed = {"company_name", "logo_png", "accent_color"}
    actual = set(TenantBranding.__dataclass_fields__)
    assert actual == allowed, (
        f"`TenantBranding` sahələri dəyişib: {sorted(actual)}. Yeni sahə əlavə "
        "etməzdən əvvəl sual: bu dəyər dəyişəndə hansısa qadağa zəifləyirmi?"
    )


def test_the_window_title_keeps_the_product_name() -> None:
    """Şirkət adı məhsul adını ƏVƏZ ETMİR, ona ƏLAVƏ olunur.

    Dəstək operatoru ekrandan hansı proqramın işlədiyini görməlidir.
    """
    assert TenantBranding(company_name="Yataş Group").window_title() == "KompasOS — Yataş Group"
    assert DEFAULT_BRANDING.window_title() == "KompasOS"
    assert TenantBranding(company_name="   ").window_title() == "KompasOS"


def test_an_oversized_logo_is_refused() -> None:
    with pytest.raises(BrandingError):
        TenantBranding(logo_png=PNG_SIGNATURE + b"\x00" * MAX_LOGO_BYTES)


def test_a_non_png_logo_is_refused() -> None:
    """Format yoxlaması olmasaydı, nəticə yalnız ekranda boş kvadrat kimi görünərdi."""
    with pytest.raises(BrandingError):
        TenantBranding(logo_png=b"GIF89a" + b"\x00" * 100)


def test_a_too_long_company_name_is_refused() -> None:
    with pytest.raises(BrandingError):
        TenantBranding(company_name="A" * (MAX_COMPANY_NAME_CHARS + 1))


def test_a_malformed_accent_colour_is_refused() -> None:
    for value in ("F5A623", "#F5A62", "#GGGGGG", "rgb(1,2,3)"):
        with pytest.raises(BrandingError):
            TenantBranding(accent_color=value)


def test_an_unreadable_accent_colour_is_kept_but_flagged() -> None:
    """Rədd etmək qərarı müştərinin əvəzinə vermək olardı (bax modul başlığı)."""
    too_light = TenantBranding(accent_color="#FFFFF0")
    assert not too_light.is_accessible
    assert "açıqdır" in too_light.accessibility_warning()

    too_dark = TenantBranding(accent_color="#010101")
    assert not too_dark.is_accessible
    assert "tünddür" in too_dark.accessibility_warning()

    ok = TenantBranding(accent_color="#F5A623")  # defolt Amber
    assert ok.is_accessible
    assert ok.accessibility_warning() == ""


def test_the_luminance_formula_matches_the_contrast_gate() -> None:
    """Domen hesabı `scripts/check_contrast.py` ilə AYRILA BİLMƏZ.

    İki nüsxə qəsdəndir (domen `scripts/`-dən idxal edə bilməz — `CLAUDE.md`
    §3 qat sırası), lakin ayrılsalar «oxunaqlıdır» sözü iki fərqli məna
    daşıyardı.
    """
    import sys

    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    from check_contrast import relative_luminance as gate_luminance

    for color in ("#F5A623", "#0B1D3A", "#FFFFFF", "#000000", "#2DD4BF"):
        assert relative_luminance(color) == pytest.approx(gate_luminance(color), abs=1e-12)


# --------------------------------------------------------------------------- #
# 3. Brendinq use case
# --------------------------------------------------------------------------- #


class _FakeBrandingRepo:
    def __init__(self, initial: TenantBranding = DEFAULT_BRANDING) -> None:
        self.value = initial
        self.saved_by: object = None

    def get(self, tenant_id: object) -> TenantBranding:
        return self.value

    def save(self, tenant_id: object, branding: TenantBranding, *, updated_by: object) -> None:
        self.value = branding
        self.saved_by = updated_by


class _FakeAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def record(self, **kwargs: object) -> None:
        self.entries.append(kwargs)


class _FakeClock:
    def now(self) -> object:
        from datetime import UTC, datetime

        return datetime(2026, 8, 17, 9, 0, tzinfo=UTC)


class _Actor:
    def __init__(self, *, allowed: bool = True) -> None:
        import uuid

        self.id = uuid.UUID("77777777-7777-7777-7777-777777777777")
        self._allowed = allowed

    def has_permission(self, flag: str, *, now: object) -> bool:
        return self._allowed


def _use_case(repo: _FakeBrandingRepo) -> tuple[TenantBrandingUseCase, _FakeAudit]:
    audit = _FakeAudit()
    return (
        TenantBrandingUseCase(
            repository=repo,  # type: ignore[arg-type]
            audit=audit,  # type: ignore[arg-type]
            clock=_FakeClock(),  # type: ignore[arg-type]
        ),
        audit,
    )


def test_reading_branding_needs_no_permission() -> None:
    """Ad giriş ekranında — istifadəçi seçilməmişdən ƏVVƏL — görünməlidir."""
    repo = _FakeBrandingRepo(TenantBranding(company_name="Embawood"))
    use_case, _ = _use_case(repo)
    assert use_case.current(tenant_id=None).company_name == "Embawood"  # type: ignore[arg-type]


def test_writing_branding_requires_the_root_flag() -> None:
    repo = _FakeBrandingRepo()
    use_case, _ = _use_case(repo)
    with pytest.raises(BrandingPermissionError):
        use_case.update(
            tenant_id=None,  # type: ignore[arg-type]
            actor=_Actor(allowed=False),  # type: ignore[arg-type]
            company_name="Hücum",
        )
    assert repo.value == DEFAULT_BRANDING


def test_none_means_unchanged_not_cleared() -> None:
    """Yalnız adı dəyişən ekran loqonu SÜKUTLA silməməlidir."""
    logo = PNG_SIGNATURE + b"\x00" * 32
    repo = _FakeBrandingRepo(TenantBranding(company_name="Köhnə", logo_png=logo))
    use_case, _ = _use_case(repo)

    result = use_case.update(
        tenant_id=None,  # type: ignore[arg-type]
        actor=_Actor(),  # type: ignore[arg-type]
        company_name="Yeni",
    )

    assert result.branding.company_name == "Yeni"
    assert result.branding.logo_png == logo, "loqo sükutla silindi"


def test_clearing_is_explicit() -> None:
    logo = PNG_SIGNATURE + b"\x00" * 32
    repo = _FakeBrandingRepo(TenantBranding(logo_png=logo, accent_color="#F5A623"))
    use_case, _ = _use_case(repo)

    result = use_case.update(
        tenant_id=None,  # type: ignore[arg-type]
        actor=_Actor(),  # type: ignore[arg-type]
        clear_logo=True,
        clear_accent=True,
    )

    assert result.branding.logo_png is None
    assert result.branding.accent_color is None


def test_the_audit_entry_stores_the_logo_size_not_the_bytes() -> None:
    """İkili məzmun `audit_logs` JSONB sütununu praktiki olaraq oxunmaz edərdi."""
    repo = _FakeBrandingRepo()
    use_case, audit = _use_case(repo)

    use_case.update(
        tenant_id=None,  # type: ignore[arg-type]
        actor=_Actor(),  # type: ignore[arg-type]
        logo_png=PNG_SIGNATURE + b"\x00" * 100,
    )

    after = audit.entries[0]["after_state"]
    assert isinstance(after, dict)
    assert after["logo_bytes"] == len(PNG_SIGNATURE) + 100
    assert "logo_png" not in after


def test_an_unreadable_colour_is_saved_with_a_warning() -> None:
    repo = _FakeBrandingRepo()
    use_case, audit = _use_case(repo)

    result = use_case.update(
        tenant_id=None,  # type: ignore[arg-type]
        actor=_Actor(),  # type: ignore[arg-type]
        accent_color="#FFFFF0",
    )

    assert result.branding.accent_color == "#FFFFF0", "dəyər rədd edildi"
    assert result.warning, "xəbərdarlıq verilmədi"
    # Xəbərdarlıq audit izinə də düşür — sonradan «niyə oxunmur?» sualı
    # cavabsız qalmasın.
    assert audit.entries[0]["reason"] == result.warning


def test_an_invalid_value_raises_instead_of_saving_silently() -> None:
    repo = _FakeBrandingRepo()
    use_case, _ = _use_case(repo)
    with pytest.raises(BrandingValidationError):
        use_case.update(
            tenant_id=None,  # type: ignore[arg-type]
            actor=_Actor(),  # type: ignore[arg-type]
            accent_color="mavi",
        )
    assert repo.value == DEFAULT_BRANDING
