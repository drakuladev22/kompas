"""Paketlənmiş Inter şrifti — fayl, qeydiyyat, token sırası (`appl.md` FAZA 1).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU TEST VAR
──────────────────────────────────────────────────────────────────────────────
Şriftin işləməməsi ÇÖKMƏ vermir: Qt sükutla ehtiyat üzə (Segoe UI) düşür və
interfeys «demək olar eyni» görünür. Yəni qüsur nə jurnalda, nə ekranda
görünəcək — YALNIZ dizaynda, və ilk fərq edən müştəri olacaq. Üç halqanın hər
biri ayrıca yoxlanılır, çünki onlar müstəqil qırıla bilir:

    1. FAYL var və `.spec` onu paketə salır (`assets/fonts/*.ttf`);
    2. QEYDİYYAT işləyir (`QFontDatabase` ailəni tanıyır);
    3. TOKEN həmin ailəni BİRİNCİ ad kimi soruşur (`--font-family`).

İkinci halqa Qt tələb edir; birinci və üçüncü sırf fayl/mətn yoxlamasıdır və
Qt olmadan da işləyir — ona görə onlar ayrı testlərdədir.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_every_declared_font_file_exists_on_disk() -> None:
    """`FONT_FILES` siyahısı ilə `assets/fonts/` məzmunu uyğun gəlməlidir.

    Siyahıya ad yazılıb fayl əlavə edilməsəydi, qeydiyyat həmin üzü SÜKUTLA
    ötürərdi (`_font_path` `None` qaytarır) və çəki iyerarxiyası bir pillə
    itərdi — məsələn başlıqlar gövdə mətni ilə eyni qalınlıqda çıxardı.
    """
    from src.presentation.theme.fonts import FONT_DIR, FONT_FILES

    directory = _REPO_ROOT / FONT_DIR
    missing = [name for name in FONT_FILES if not (directory / name).is_file()]
    assert not missing, f"paketlənəcək şrift faylı yoxdur: {missing}"


def test_the_open_font_license_travels_with_the_fonts() -> None:
    """OFL lisenziya NÜSXƏSİNİN şriftlə birlikdə paylanmasını TƏLƏB edir.

    Bu, hüquqi şərtdir, üslub deyil: fayl silinsə paylama şərti pozulur.
    """
    license_file = _REPO_ROOT / "assets" / "fonts" / "LICENSE-Inter.txt"

    assert license_file.is_file(), "Inter lisenziya faylı yoxdur"
    assert "SIL Open Font License" in license_file.read_text(encoding="utf-8")


def test_the_spec_packages_the_font_directory() -> None:
    """`.spec` şrift qovluğunu daşımasa, qüsur YALNIZ `.exe`-də görünərdi.

    Eyni tələ loqo PNG-lərində olub (bax `KompasOS.spec` şərhi): mənbədən
    işləyən tətbiq düzgün, paketlənmiş buraxılış isə fərqli görünürdü.
    """
    spec = (_REPO_ROOT / "src" / "KompasOS.spec").read_text(encoding="utf-8")

    assert "'assets', 'fonts', '*.ttf'" in spec
    assert "'assets/fonts'" in spec


def test_the_first_family_in_the_token_is_the_bundled_one() -> None:
    """Token BİRİNCİ olaraq məhz paketlənmiş ailəni soruşmalıdır.

    Sıra çevrilsəydi (`Segoe UI` birinci), şrift yüklənər, lakin HEÇ VAXT
    işlədilməzdi — məhz `appl.md`-dən əvvəlki vəziyyət budur.
    """
    from src.presentation.theme.fonts import FONT_FAMILY
    from src.presentation.theme.tokens import TYPOGRAPHY

    families = [part.strip() for part in TYPOGRAPHY["--font-family"].split(",")]

    assert families[0] == FONT_FAMILY
    # Ehtiyat sırası QALIR: paketlənmə pozulsa interfeys şriftsiz qalmamalıdır.
    assert "Segoe UI" in families


@requires_qt
def test_the_bundled_family_registers_at_runtime(qt_app: Any) -> None:
    """Qeydiyyat FAKTİKİ olaraq işləyir və ailə `QFontDatabase`-ə düşür."""
    from PySide6.QtGui import QFontDatabase

    from src.presentation.theme.fonts import FONT_FAMILY, register_bundled_fonts

    _ = qt_app
    families = register_bundled_fonts()

    assert FONT_FAMILY in families
    assert FONT_FAMILY in QFontDatabase.families()


@requires_qt
def test_registering_twice_does_not_reload_the_files(qt_app: Any) -> None:
    """İdempotentlik: ikinci çağırış yaddaşda İKİNCİ nüsxə yaratmır.

    `QFontDatabase.addApplicationFont` eyni faylı təkrar yükləyəndə YENİ id
    verir — yəni qorunmasa hər pəncərə açılışı şriftin bir nüsxəsini daha
    yaddaşa alardı.
    """
    from src.presentation.theme.fonts import register_bundled_fonts

    _ = qt_app
    first = register_bundled_fonts()
    second = register_bundled_fonts()

    assert first == second


@requires_qt
def test_the_semibold_weight_resolves_to_the_bundled_face(qt_app: Any) -> None:
    """`--font-weight-medium` (600) məhz Inter-in öz üzünə düşməlidir.

    Bu, dörd STATİK fayl seçiminin səbəbini ölçür (bax `fonts.py` başlığı):
    çəki sorğusu ehtiyat şriftə yuvarlaqlaşsaydı, başlıq ilə gövdə mətni eyni
    qalınlıqda görünərdi və iyerarxiya ölçüyə qalardı.
    """
    from PySide6.QtGui import QFont, QFontInfo

    from src.presentation.theme.fonts import FONT_FAMILY, register_bundled_fonts
    from src.presentation.theme.tokens import TYPOGRAPHY

    _ = qt_app
    register_bundled_fonts()

    font = QFont(FONT_FAMILY)
    font.setWeight(QFont.Weight(int(TYPOGRAPHY["--font-weight-medium"])))
    info = QFontInfo(font)

    assert info.family().startswith(FONT_FAMILY)
    assert info.weight() == int(TYPOGRAPHY["--font-weight-medium"])
