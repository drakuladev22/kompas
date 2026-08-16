"""Loqo faylları — tapılması, keşlənməsi və temaya görə boyanması (logo.md).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA MODUL — HƏR EKRAN ÖZÜ OXUYA BİLƏRDİMİ
──────────────────────────────────────────────────────────────────────────────
Fayl YOLU İKİ mühitdə fərqlidir: paketlənmiş `.exe`-də resurslar arxivin
içindədir (`sys._MEIPASS`), mənbədən işləyəndə isə layihə qovluğunda. Hər ekran
öz yolunu qursaydı, biri unudular və qüsur YALNIZ paketlənmiş buraxılışda —
yəni müştəri maşınında — üzə çıxardı. Yol məntiqi `app._apply_window_icon` ilə
EYNİDİR və qəsdən eyni köklərdən (`bundle_root`, `deployment_root`) gedir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BOYAMA (TINT) LAZIM OLDU
──────────────────────────────────────────────────────────────────────────────
`16_withoutcontainer.png` TAM SABİT rəngdədir — bütün piksellər `#134E4A`
(tünd teal). Bu, AÇIQ fon üçün nəzərdə tutulub. Başlıq zolağı isə hər iki
temada TÜNDDÜR (bax `windows_app.png` referansı): faylı olduğu kimi qoysaydıq,
tünd işarə tünd zolağın üzərində praktiki olaraq GÖRÜNMƏZDİ.

Ona görə şəkil ALFA MASKASI kimi işlədilir: forma fayldan, rəng isə temadan
gəlir. Bu, layihənin mövcud naxışıdır — pəncərə düymələrinin ikonları da
məhz belə boyanır (`widgets/buttons.py`: «ikon piksel şəklidir və QSS onu
boyamır»). Nəticədə eyni fayl həm tünd, həm açıq zolaqda düzgün görünür və
dizayndan İKİNCİ nüsxə tələb olunmur.

──────────────────────────────────────────────────────────────────────────────
KEŞ NİYƏ VAR
──────────────────────────────────────────────────────────────────────────────
Tema keçidi hər dəfə bütün ekranı yenidən boyayır. Keş olmasaydı, hər keçiddə
PNG diskdən oxunub yenidən miqyaslanardı — animasiya ərzində onlarla dəfə.
Açar `(fayl, hündürlük, rəng)`-dir, yəni eyni tema üçün bir dəfə qurulur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap

from src.shared.logger import get_logger
from src.shared.runtime import bundle_root, deployment_root

if TYPE_CHECKING:
    from pathlib import Path

_log = get_logger(__name__)

#: Loqo fayllarının qovluğu — paketə `KompasOS.spec` ilə daxil edilir.
LOGO_DIR: Final = "assets/logo"

#: Başlıq zolağındakı konteynersiz işarə.
TITLE_MARK: Final = "16_withoutcontainer.png"
#: Tətbiq ikonu (konteynerli rozet) — giriş/sihirbaz ekranlarında.
APP_MARK: Final = "64.png"
#: Splash üçün tam lockup (pərgar + "KompasOS" mətni).
SPLASH_LIGHT: Final = "loading_screen_light.png"
SPLASH_DARK: Final = "loading_screen_dark.png"

_cache: dict[tuple[str, int, str], QPixmap] = {}


def logo_path(name: str) -> Path | None:
    """Loqo faylının faktiki yolu; tapılmasa `None`.

    `None` DAYANDIRICI DEYİL: loqonun olmaması tətbiqi işə düşməkdən saxlamamalıdır
    (`_apply_window_icon` ilə eyni qərar). Çağıran tərəf köhnə çəkilən loqoya
    (`CompassLogo`) qayıdır.
    """
    for root in (bundle_root(), deployment_root()):
        if root is None:
            continue
        candidate = root / LOGO_DIR / name
        if candidate.is_file():
            return candidate
    _log.warning("LOGO_ASSET_MISSING", extra={"name": name})
    return None


def logo_pixmap(name: str, *, height: int) -> QPixmap | None:
    """Faylı olduğu kimi (rəngləri ilə) verilmiş hündürlüyə miqyaslayır."""
    key = (name, height, "")
    cached = _cache.get(key)
    if cached is not None:
        return cached

    path = logo_path(name)
    if path is None:
        return None

    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        _log.warning("LOGO_ASSET_UNREADABLE", extra={"path": str(path)})
        return None

    scaled = pixmap.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
    _cache[key] = scaled
    return scaled


def tinted_pixmap(name: str, *, height: int, color: str) -> QPixmap | None:
    """Şəkli ALFA MASKASI kimi işlədib verilmiş rənglə doldurur.

    Forma fayldan, rəng temadan gəlir (bax modul başlığı). `SourceIn` rejimi
    yalnız şəffaf OLMAYAN piksellərə toxunur, yəni kənarların yumşaqlığı
    (anti-aliasing) qorunur — sadə «rəngi əvəz et» yanaşması pilləli kənar
    verərdi.
    """
    key = (name, height, color)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    base = logo_pixmap(name, height=height)
    if base is None:
        return None

    tinted = QPixmap(base.size())
    tinted.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, base)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), QColor(color))
    painter.end()

    _cache[key] = tinted
    return tinted


def splash_asset(*, dark: bool) -> str:
    """Cari temaya uyğun splash faylının adı.

    Seçim BURADA edilir ki, «hansı tema aktivdirsə, ona uyğun fayl» qaydası
    tək yerdə olsun — ekranlar yalnız `ThemeManager`-dən gələn həll olunmuş
    rejimi ötürür (logo.md ADDIM 3: hardcode ETMƏ).
    """
    return SPLASH_DARK if dark else SPLASH_LIGHT


def clear_cache() -> None:
    """Keşi boşaldır — yalnız testlər üçün (fayl dəyişdirilə bilər)."""
    _cache.clear()


__all__ = [
    "APP_MARK",
    "LOGO_DIR",
    "SPLASH_DARK",
    "SPLASH_LIGHT",
    "TITLE_MARK",
    "clear_cache",
    "logo_path",
    "logo_pixmap",
    "splash_asset",
    "tinted_pixmap",
]
