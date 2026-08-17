"""WCAG kontrast hesablamasının testləri (spesifikasiya bölmə 9)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_contrast.py"
_spec = importlib.util.spec_from_file_location("check_contrast", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check_contrast = importlib.util.module_from_spec(_spec)
sys.modules["check_contrast"] = check_contrast
_spec.loader.exec_module(check_contrast)


# --------------------------------------------------------------------------- #
# Rəng emalı
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("#000000", (0, 0, 0)),
        ("#FFFFFF", (255, 255, 255)),
        ("#fff", (255, 255, 255)),
        ("0B1D3A", (11, 29, 58)),
        ("#F5A623FF", (245, 166, 35)),
    ],
)
def test_parse_hex(value: str, expected: tuple[int, int, int]) -> None:
    assert check_contrast.parse_hex(value) == expected


@pytest.mark.parametrize("value", ["#12345", "qırmızı", "", "#GGGGGG"])
def test_parse_hex_rejects_invalid(value: str) -> None:
    with pytest.raises(ValueError, match="Yararsız rəng"):
        check_contrast.parse_hex(value)


def test_known_contrast_ratios() -> None:
    """Qara/ağ maksimum 21:1, eyni rəng 1:1 verməlidir."""
    assert check_contrast.contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert check_contrast.contrast_ratio("#FFFFFF", "#FFFFFF") == pytest.approx(1.0)


def test_contrast_is_symmetric() -> None:
    forward = check_contrast.contrast_ratio("#0B1D3A", "#FFFFFF")
    backward = check_contrast.contrast_ratio("#FFFFFF", "#0B1D3A")
    assert forward == pytest.approx(backward)


def test_brand_navy_on_white_passes_aa() -> None:
    """Deep Navy (#0B1D3A) ağ fonda əsas mətn kimi işləyə bilməlidir (bölmə 9)."""
    ratio = check_contrast.contrast_ratio("#0B1D3A", "#FFFFFF")
    assert ratio >= check_contrast.AA_NORMAL_TEXT


def test_brand_amber_on_white_fails_normal_text() -> None:
    """Amber (#F5A623) ağ fonda MƏTN üçün kifayət deyil — yalnız iri qrafik
    element kimi istifadə oluna bilər. Bu, Faza 4 dizaynı üçün vacib məhdudiyyətdir."""
    ratio = check_contrast.contrast_ratio("#F5A623", "#FFFFFF")
    assert ratio < check_contrast.AA_NORMAL_TEXT


def test_brand_amber_on_navy_passes_large_text() -> None:
    ratio = check_contrast.contrast_ratio("#F5A623", "#0B1D3A")
    assert ratio >= check_contrast.AA_LARGE_TEXT


# --------------------------------------------------------------------------- #
# Tema yoxlaması
# --------------------------------------------------------------------------- #


#: Fon (səth) rolunda çıxış edən tokenlər.
#:
#: Qalan bütün tokenlər "mürəkkəb" (mətn/ikon) sayılır. Bölgü belədir, çünki
#: bəzi tokenlər HƏR İKİ rolda görünür: `--color-accent` "vurğu düyməsində
#: mətn" cütündə FON, "vurğu (qrafik element)" cütündə isə MÜRƏKKƏB-dir.
#: Eyni şey `--color-action-bg` üçün də doğrudur. Onları mürəkkəb saymaq
#: hər iki cütü düzgün (kontrastlı) edir; fon saysaq, ikinci cütdə fon-fon
#: müqayisəsi alınardı və nisbət 1:1 olardı.
#:
#: YEGANƏ İNVARİANT: hər cütün DƏQİQ BİR ucu bu dəstdə olmalıdır. Kontrast
#: hesablaması simmetrikdir, ona görə hansı ucun "fon" adlandığının əhəmiyyəti
#: yoxdur — əhəmiyyətli olan iki ucun sintetik temada FƏRQLİ rəng almasıdır.
#: `test_every_pair_has_exactly_one_surface_end` bunu qapıya salır ki, yeni
#: cüt əlavə edən adam səbəbi anlaşılmaz "1.00:1" nəticəsi ilə üzləşməsin.
_SURFACE_TOKENS = frozenset(
    {
        "--color-bg-primary",
        "--color-bg-surface",
        "--color-bg-elevated",
        "--color-bg-sunken",
        "--color-card-bg",
        "--color-content-bg",
        "--color-header-bg",
        "--color-sidebar-bg",
        "--color-titlebar-bg",
        # Pəncərə düymələrinin hover FONU — səthdir, ön plan deyil.
        "--color-titlebar-control-hover",
        "--color-nav-active-bg",
        "--color-neutral-bg",
        "--color-success-bg",
        "--color-warning-bg",
        "--color-danger-bg",
        "--color-info-bg",
        # Seçilmiş növ-kartının fonu (1c.md sihirbazı) — `--color-accent`-in
        # YUMŞAQ variantıdır və üzərində mətn oturur, yəni SƏTHdir.
        "--color-accent-subtle",
        "--color-pin-bg",
        # Açılış ekranının fonu. `--color-content-bg`-dən AYRIDIR, çünki
        # dəyəri lockup şəklinin öz konteynerindən oxunur (bax `tokens.py`) —
        # üzərində dörd mətn oturur, yəni SƏTHdir.
        "--color-splash-bg",
        "--color-text-on-accent",
        "--color-action-text",
    }
)


def _all_pair_tokens() -> frozenset[str]:
    """Yoxlanılan bütün cütlərdə adı keçən tokenlər."""
    return frozenset(
        token
        for foreground, background, _, _ in (
            *check_contrast.REQUIRED_PAIRS,
            *check_contrast.HIGH_CONTRAST_PAIRS,
        )
        for token in (foreground, background)
    )


def _minimal_theme(text: str, background: str) -> dict[str, str]:
    """Bütün tələb olunan tokenləri əhatə edən sintetik tema.

    Siyahı ƏL İLƏ yazılmır — `REQUIRED_PAIRS`-dən qurulur. Beləliklə yeni
    rəng cütü əlavə edildikdə bu fixture özü genişlənir və testlər
    "çatışmayan token" xətası ilə qırılmır.
    """
    return {token: background if token in _SURFACE_TOKENS else text for token in _all_pair_tokens()}


def test_minimal_theme_covers_every_required_token() -> None:
    """Fixture-in qapısı: hər cüt tokeni sintetik temada olmalıdır.

    Bu test olmasa, yeni cüt əlavə edən adam yalnız "36 çatışmayan token"
    kimi dolayı bir səhvlə qarşılaşardı və səbəbi axtarmalı olardı.
    """
    assert _all_pair_tokens() <= set(_minimal_theme("#000000", "#FFFFFF"))


def test_surface_tokens_are_all_real() -> None:
    """`_SURFACE_TOKENS` içində artıq işlənməyən ad qalmasın."""
    assert _all_pair_tokens() >= _SURFACE_TOKENS


def test_every_pair_has_exactly_one_surface_end() -> None:
    """Hər cütün DƏQİQ BİR ucu səth olmalıdır.

    İki ucu da səth (və ya heç biri) olan cüt sintetik temada eyni rəngi alır
    və nisbət 1.00:1 çıxır — test qırılır, lakin səbəb `check_contrast.py`-da
    deyil, BU fayldakı `_SURFACE_TOKENS` dəstindədir. Xəta mesajı birbaşa
    günahkar cütü göstərsin deyə invariant ayrıca yoxlanılır.
    """
    for foreground, background, _, description in (
        *check_contrast.REQUIRED_PAIRS,
        *check_contrast.HIGH_CONTRAST_PAIRS,
    ):
        ends = [token in _SURFACE_TOKENS for token in (foreground, background)]
        assert sum(ends) == 1, (
            f"«{description}» cütünün dəqiq bir ucu səth olmalıdır: "
            f"{foreground} / {background} — `_SURFACE_TOKENS`-i yeniləyin"
        )


def test_check_theme_all_pass() -> None:
    findings, missing = check_contrast.check_theme(
        "light", _minimal_theme("#000000", "#FFFFFF"), check_contrast.REQUIRED_PAIRS
    )
    assert missing == []
    assert findings
    assert all(f.passed for f in findings)


def test_check_theme_detects_failure() -> None:
    findings, _ = check_contrast.check_theme(
        "dark", _minimal_theme("#777777", "#808080"), check_contrast.REQUIRED_PAIRS
    )
    assert any(not f.passed for f in findings)


def test_check_theme_reports_missing_tokens() -> None:
    findings, missing = check_contrast.check_theme(
        "light", {"--color-text-primary": "#000000"}, check_contrast.REQUIRED_PAIRS
    )
    assert findings == []
    assert "--color-bg-primary" in missing


def test_check_theme_strict_missing_raises() -> None:
    with pytest.raises(ValueError, match="çatışmayan"):
        check_contrast.check_theme("light", {}, check_contrast.REQUIRED_PAIRS, strict_missing=True)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_cli_skips_when_tokens_absent(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Faza 1-3: tokenlər yoxdur → CI qırmızı olmamalıdır.

    Yol MONKEYPATCH ilə mövcud olmayan fayla yönəldilir. Əvvəllər test
    reponun vəziyyətindən asılı idi: `tokens.py` yaradılan kimi (Faza 4.1)
    şərt öz-özünə pozuldu və test məzmununu deyil, tarixçəni yoxlamağa
    başladı. İndi şərt testin ÖZ içindədir.
    """
    # Yol layihə kökünün İÇİNDƏ olmalıdır: skript hesabatda onu `relative_to`
    # ilə qısaldır və kənar qovluq `ValueError` verərdi.
    monkeypatch.setattr(
        check_contrast,
        "TOKENS_MODULE",
        check_contrast.PROJECT_ROOT / "movcud-olmayan-tokens.py",
    )

    exit_code = check_contrast.main([])

    captured = capsys.readouterr().out
    assert exit_code == 0
    assert "atlandı" in captured


def test_cli_passes_with_project_tokens() -> None:
    """Faza 4: layihənin FAKTİKİ tokenləri bütün cütlərdən keçir.

    Bu, `check_contrast.py`-ın CI-dakı əsl çağırışıdır (arqumentsiz) —
    yəni token faylı dəyişdikdə testin özü xəbərdarlıq verir.
    """
    assert check_contrast.main(["--include-high-contrast"]) == 0


def test_cli_pair_mode(capsys: pytest.CaptureFixture[str]) -> None:
    assert check_contrast.main(["--pair", "#000000", "#FFFFFF"]) == 0
    assert check_contrast.main(["--pair", "#777777", "#808080"]) == 1
    assert "21.00:1" in capsys.readouterr().out


def test_cli_fails_on_bad_tokens(tmp_path: Path) -> None:
    tokens = tmp_path / "tokens.json"
    tokens.write_text(
        json.dumps(
            {
                "light": _minimal_theme("#000000", "#FFFFFF"),
                "dark": _minimal_theme("#777777", "#808080"),
            }
        ),
        encoding="utf-8",
    )
    assert check_contrast.main(["--tokens", str(tokens)]) == 1


def test_cli_passes_on_good_tokens(tmp_path: Path) -> None:
    tokens = tmp_path / "tokens.json"
    tokens.write_text(
        json.dumps(
            {
                "light": _minimal_theme("#0B1D3A", "#FFFFFF"),
                "dark": _minimal_theme("#F2F4F8", "#0B1D3A"),
            }
        ),
        encoding="utf-8",
    )
    assert check_contrast.main(["--tokens", str(tokens)]) == 0
