"""Xətt-əsaslı ikon dəsti — dizayn maketlərindən (Qrup A–G) — Faza 4.2.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SVG MƏTNİ, NİYƏ `.png` FAYLLARI DEYİL
──────────────────────────────────────────────────────────────────────────────
Maketdəki hər ikon `stroke` rəngi ilə çəkilir və həmin rəng VƏZİYYƏTƏ görə
dəyişir: naviqasiyada passiv maddə boz (`--color-nav-item-icon`), aktiv maddə
amber (`--color-brand-amber`), xəta kartında qırmızı. Rastr fayllarla bu, hər
ikonun hər rəng üçün ayrıca ixracı demək olardı (40 ikon × 5 rəng × 2 tema).

Ona görə ikonlar SVG MƏTNİ kimi saxlanılır və `render()` çağırışında rəng
şablona yerləşdirilir. Nəticə `QPixmap`-dır, yəni Qt tərəfdə adi ikon kimi
işlənir.

──────────────────────────────────────────────────────────────────────────────
KEŞ VƏ DPI
──────────────────────────────────────────────────────────────────────────────
`render()` nəticəni (ad, rəng, ölçü, qalınlıq, DPI) açarı ilə keşləyir —
naviqasiya siyahısı hər tema dəyişəndə yenidən çəkilir və keşsiz hər dəfə
SVG parse olunardı.

Piksel sıxlığı yüksək ekranlarda (150–200% miqyas — Windows-da adi haldır)
ikon `size × dpr` ölçüsündə çəkilir və `devicePixelRatio` təyin olunur; əks
halda 16px ikon bulanıq görünərdi.
"""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from src.shared.exceptions import KompasOSError


class IconNotFoundError(KompasOSError):
    """Tələb olunan ikon adı dəstdə yoxdur."""

    user_message = "İnterfeys ikonu tapılmadı."


#: Hər ikonun SVG GÖVDƏSİ — `viewBox="0 0 16 16"` daxilində.
#:
#: Yollar birbaşa maketlərdən götürülüb (Qrup A–G). Rəng və qalınlıq burada
#: YAZILMIR — onlar `render()` tərəfindən kök `<svg>` elementinə verilir ki,
#: eyni gövdə bütün vəziyyətlərdə işlənə bilsin.
_BODIES: Final[dict[str, str]] = {
    # ----------------------------- naviqasiya ------------------------------ #
    "dashboard": '<path d="M2 2.5h5v5H2zM9 2.5h5v3H9zM9 7.5h5v6H9zM2 9.5h5v4H2z"/>',
    "grid": '<path d="M2 2.5h5v5H2zM9 2.5h5v5H9zM2 9.5h5v4H2zM9 9.5h5v4H9z"/>',
    "queue": '<path d="M2 4h12M2 8h12M2 12h8"/>',
    "list": '<path d="M6 4h8M6 8h8M6 12h5"/>',
    "checklist": '<path d="M2 4l1 1 1.6-1.8M2 8l1 1 1.6-1.8"/><path d="M6 4h8M6 8h8M6 12h5"/>',
    "roster": ('<path d="M3.4 2h9.2v12H3.4z"/><path d="M5.8 5.4h4.4M5.8 8h4.4M5.8 10.6h2.6"/>'),
    "fine": '<path d="M8 2.4 14.6 13.6H1.4z"/><path d="M8 6.4v3.1M8 11.7h.01"/>',
    "settings": (
        '<path d="M2.5 5h11M2.5 11h11"/>'
        '<circle cx="6" cy="5" r="1.7"/><circle cx="10.5" cy="11" r="1.7"/>'
    ),
    "users": (
        '<circle cx="6.4" cy="5.6" r="2.4"/>'
        '<path d="M1.8 13c.7-2.2 2.4-3.4 4.6-3.4S10.3 10.8 11 13"/>'
        '<path d="M11.2 3.6a2.4 2.4 0 0 1 0 4.4M12.4 13c-.2-1.3-.6-2.3-1.2-3"/>'
    ),
    "user": (
        '<circle cx="8" cy="6" r="2.6"/><path d="M3 13.4c.8-2.4 2.6-3.6 5-3.6s4.2 1.2 5 3.6"/>'
    ),
    "calendar": (
        '<path d="M2.2 3.4h11.6v10.4H2.2z"/><path d="M2.2 6.6h11.6M5.6 1.8v3M10.4 1.8v3"/>'
    ),
    "shield": '<path d="M8 1.8 13.6 4v4c0 3.2-2.2 5.4-5.6 6.2C4.6 13.4 2.4 11.2 2.4 8V4z"/>',
    "star": ('<path d="M8 2l1.9 3.9 4.3.6-3.1 3 .7 4.2L8 11.8l-3.8 2 .7-4.2-3.1-3 4.3-.6z"/>'),
    "tag": '<path d="M5.6 3.4h8.2v9.2H5.6L1.8 8z"/>',
    "chat": '<path d="M2.4 3.4h11.2v7.8H8.6L5.2 13.8v-2.6H2.4z"/>',
    # ----------------------------- infrastruktur --------------------------- #
    "server": (
        '<path d="M2.2 3h11.6v3.4H2.2zM2.2 9.6h11.6V13H2.2z"/><path d="M4.6 4.7h.01M4.6 11.3h.01"/>'
    ),
    "server_off": (
        '<path d="M2.2 3h11.6v3.4H2.2z"/><path d="M2.2 9.6h11.6V13H2.2z"/>'
        '<path d="M12.4 8.6 3.6 13.8"/>'
    ),
    "database": (
        '<path d="M2.4 4.2c0-1.2 2.5-2.2 5.6-2.2s5.6 1 5.6 2.2v7.6c0 1.2-2.5 2.2-5.6 '
        '2.2s-5.6-1-5.6-2.2z"/>'
        '<path d="M2.4 8c0 1.2 2.5 2.2 5.6 2.2s5.6-1 5.6-2.2"/>'
    ),
    "activity": '<path d="M1.6 8h3l2-4 2.8 8 2-4h3"/>',
    "wifi_off": (
        '<path d="M1.6 5.6a9 9 0 0 1 12.8 0M4 8.2a5.6 5.6 0 0 1 8 0'
        'M6.4 10.8a2.2 2.2 0 0 1 3.2 0M8 13.6h.01"/>'
        '<path d="M13.4 2.6 2.6 13.4"/>'
    ),
    "power": '<circle cx="8" cy="8" r="5.8"/><path d="M8 2.2v5"/>',
    # ----------------------------- hərəkətlər ------------------------------ #
    "plus": '<path d="M8 3v10M3 8h10"/>',
    "check": '<path d="M3 8.4 6.3 11.7 13 5"/>',
    "check_circle": '<circle cx="8" cy="8" r="6"/><path d="M5.8 8.2 7.4 9.8l3-3.2"/>',
    # Yardım Mərkəzi nişanı. Sual işarəsi hərf kimi deyil, ŞTRIX kimi
    # çəkilir — `<text>` istifadə edilsəydi, nişan şrift mövcudluğundan
    # asılı olardı və qalın/nazik variantlarda digər ikonlarla uyğun gəlməzdi.
    "help": (
        '<circle cx="8" cy="8" r="6"/>'
        '<path d="M6.3 6.2a1.75 1.75 0 1 1 2.3 1.9c-.4.2-.6.6-.6 1v.3"/>'
        '<path d="M8 11.6h.01"/>'
    ),
    "close": '<path d="M4 4l8 8M12 4l-8 8"/>',
    "refresh": '<path d="M13.4 7.2a5.4 5.4 0 1 0-.6 3.4"/><path d="M13.6 3.6v3.6h-3.4"/>',
    "search": '<circle cx="7" cy="7" r="4.6"/><path d="M10.4 10.4 14 14"/>',
    "edit": '<path d="M2.6 10.4 7.4 5.6l4.6 4.6-2.4 2.4H4.6z"/><path d="M2.6 13.4h10.8"/>',
    "download": '<path d="M8 2.6v7.4M5.2 7.4 8 10.2l2.8-2.8M2.8 13.2h10.4"/>',
    # Sıralama düymələri. Unicode "↑"/"↓" istifadə EDİLMİR: interfeys şrifti
    # (Inter) həmin işarələri həmişə daşımır və düymə BOŞ görünürdü — SVG isə
    # şriftdən asılı deyil.
    "arrow_up": '<path d="M8 12.6V3.6M4.4 7.2 8 3.6l3.6 3.6"/>',
    "arrow_down": '<path d="M8 3.4v9M4.4 8.8 8 12.4l3.6-3.6"/>',
    "send": '<path d="M14 2 7.2 8.8M14 2 9.8 14l-2.6-5.2L2 6.2z"/>',
    "logout": '<path d="M9.4 5.2 12.6 8l-3.2 2.8M12.6 8H6.6"/><path d="M6.2 2.5H3.2v11h3"/>',
    "login": '<path d="M6.6 8H2.2M4 6l-1.8 2L4 10"/><path d="M9.4 2.6h4.4v10.8H9.4"/>',
    "slash": '<path d="M4 12 12 4"/>',
    # ----------------------------- vəziyyət / məzmun ----------------------- #
    "clock": '<circle cx="8" cy="8" r="6"/><path d="M8 4.6V8l2.4 1.4"/>',
    "bell": (
        '<path d="M4.2 6.8a3.8 3.8 0 0 1 7.6 0c0 2.9 1 3.8 1.4 4.3H2.8c.4-.5 1.4-1.4 1.4-4.3z"/>'
        '<path d="M6.6 13.2a1.6 1.6 0 0 0 2.8 0"/>'
    ),
    "lock": (
        '<path d="M4.4 7.4V5.4a3.6 3.6 0 0 1 7.2 0v2"/>'
        '<rect x="3.4" y="7.4" width="9.2" height="6.2" rx="1.4"/>'
    ),
    "file": '<path d="M9 1.8H4.4v12.4h7.2V4.4z"/><path d="M9 1.8v2.6h2.6"/>',
    "folder": '<path d="M1.8 5.6h2.6l1-1.6h5.2l1 1.6h2.6v7.2H1.8z"/>',
    "image": '<path d="M2 3.4h12v9.2H2z"/><path d="M2 10.6l3.4-3 2.6 2.3 2.6-2.6L14 10.4"/>',
    "moon": '<path d="M13.2 9.6A5.6 5.6 0 0 1 6.4 2.8a5.6 5.6 0 1 0 6.8 6.8z"/>',
    # ----------------------------- pəncərə idarəsi -------------------------- #
    # NİYƏ AYRI DÖRD İKON, NİYƏ MÖVCUD `close` TƏKRAR İŞLƏDİLMİR
    # ──────────────────────────────────────────────────────────────────────────
    # Pəncərə başlığındakı üç düymə YAN-YANA dayanır və gözlə bir dəst kimi
    # oxunur: xaçın qolları kvadratın kənarları ilə, tire isə hər ikisinin
    # mərkəz oxu ilə eyni optik ölçüdə olmalıdır. Məzmun ikonu olan `close`
    # 8px uzunluğunda qollarla çəkilib (kart/nişan içində tək dayanır) və
    # kvadratın yanında BÖYÜK görünürdü. Ona görə bu dörd forma eyni optik
    # şəbəkəyə (7.6px gövdə) köklənib və ayrıca saxlanılır — məzmun ikonunu
    # dəyişmək pəncərə düymələrini pozmasın deyə.
    "window_minimize": '<path d="M4.2 8h7.6"/>',
    "window_maximize": '<rect x="4.2" y="4.2" width="7.6" height="7.6" rx="1.1"/>',
    # Windows-un "bərpa" nişanı: arxada yarımçıq görünən ikinci kvadrat.
    # Arxa forma TAM kvadrat kimi çəkilmir — ön kvadratın altında qalan iki
    # kənar buraxılır, əks halda 16px-də iki xətt bir-birinə yapışıb ləkə
    # yaradırdı.
    "window_restore": (
        '<path d="M6.1 6.1V4.6a1.1 1.1 0 0 1 1.1-1.1h4.2a1.1 1.1 0 0 1 1.1 1.1v4.2'
        'a1.1 1.1 0 0 1-1.1 1.1H9.9"/>'
        '<rect x="3.5" y="6.1" width="6.4" height="6.4" rx="1.1"/>'
    ),
    "window_close": '<path d="M4.4 4.4 11.6 11.6M11.6 4.4 4.4 11.6"/>',
    "sun": (
        '<circle cx="8" cy="8" r="3.2"/>'
        '<path d="M8 1.2v1.4M8 13.4v1.4M14.8 8h-1.4M2.6 8H1.2'
        'M12.8 3.2l-1 1M4.2 11.8l-1 1M12.8 12.8l-1-1M4.2 4.2l-1-1"/>'
    ),
}

#: `render()` keşi — açar: (ad, rəng, ölçü, qalınlıq, dpr).
_CACHE: dict[tuple[str, str, int, float, float], QPixmap] = {}

#: Maketdəki standart ikon ölçüsü və xətt qalınlığı.
DEFAULT_SIZE: Final = 16
DEFAULT_STROKE: Final = 1.5


def available() -> tuple[str, ...]:
    """Dəstdəki bütün ikon adları — testlər və developer paneli üçün."""
    return tuple(sorted(_BODIES))


def _document(name: str, color: str, stroke_width: float) -> bytes:
    body = _BODIES.get(name)
    if body is None:
        raise IconNotFoundError(
            f"'{name}' adlı ikon dəstdə yoxdur",
            context={"icon": name, "available": list(available())},
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" '
        f'fill="none" stroke="{color}" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    ).encode()


def render(
    name: str,
    color: str,
    *,
    size: int = DEFAULT_SIZE,
    stroke_width: float = DEFAULT_STROKE,
    device_pixel_ratio: float = 1.0,
) -> QPixmap:
    """İkonu verilmiş rəng və ölçüdə `QPixmap` kimi çəkir.

    Args:
        name: `available()` siyahısındakı ad.
        color: `#RRGGBB` — adətən tema tokeni.
        device_pixel_ratio: Ekranın piksel sıxlığı. 1.0-dan böyük dəyər
            daha iri bufer çəkib nəticəni miqyaslayır (kəskin görüntü üçün).

    Raises:
        IconNotFoundError: Ad dəstdə yoxdursa.
    """
    key = (name, color, size, stroke_width, device_pixel_ratio)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    document = _document(name, color, stroke_width)
    physical = max(1, round(size * device_pixel_ratio))

    pixmap = QPixmap(physical, physical)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    QSvgRenderer(QByteArray(document)).render(painter)
    painter.end()

    pixmap.setDevicePixelRatio(device_pixel_ratio)
    _CACHE[key] = pixmap
    return pixmap


def icon(
    name: str,
    color: str,
    *,
    size: int = DEFAULT_SIZE,
    stroke_width: float = DEFAULT_STROKE,
    device_pixel_ratio: float = 1.0,
) -> QIcon:
    """`render()`-in `QIcon` variantı — `QPushButton.setIcon` üçün."""
    return QIcon(
        render(
            name,
            color,
            size=size,
            stroke_width=stroke_width,
            device_pixel_ratio=device_pixel_ratio,
        )
    )


def clear_cache() -> None:
    """Keşi boşaldır — tema dəyişikliyi testlərində sızmanı önləyir."""
    _CACHE.clear()


__all__ = [
    "DEFAULT_SIZE",
    "DEFAULT_STROKE",
    "IconNotFoundError",
    "available",
    "clear_cache",
    "icon",
    "render",
]
