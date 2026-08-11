"""İşıqlı ↔ tünd keçidinin animasiyası — Faza 4.2.

──────────────────────────────────────────────────────────────────────────────
NİYƏ EKRAN ŞƏKLİ ÜZƏRİNDƏN "CROSS-FADE"
──────────────────────────────────────────────────────────────────────────────
Qt Style Sheet dəyişdikdə bütün widget-lər ANİ olaraq yeni rəngə keçir —
aralıq mərhələ yoxdur. Rəngləri tədricən dəyişdirmək üçün üç yol var:

    1. Hər tokeni addım-addım interpolyasiya edib QSS-i 30 dəfə yenidən
       qurmaq. Bu, saniyədə onlarla dəfə bütün üslub ağacını yenidən
       hesablamaq deməkdir — 27 ekranlıq tətbiqdə gözlə görünən donma yaradır.
    2. Hər widget üçün ayrıca rəng animasiyası. Yüzlərlə animasiya obyekti,
       üstəlik QSS ilə idarə olunan rənglər (`QPushButton:hover`) belə
       animasiyaya ümumiyyətlə tabe deyil.
    3. KÖHNƏ görüntünün şəklini çəkib üstdə saxlamaq, üslubu ani dəyişmək,
       sonra şəkli şəffaflaşdırmaq.

Üçüncüsü seçilib: bir `QPixmap`, bir animasiya, sabit qiymət — pəncərənin
ölçüsündən və içindəki widget sayından ASILI DEYİL. Nəticə istifadəçi üçün
tam ekran yumşaq keçiddir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ÖRTÜK SİÇANI KEÇİRMİR
──────────────────────────────────────────────────────────────────────────────
Keçid müddətində (260 ms) örtük bütün pəncərəni bağlayır. `WA_TransparentFor
MouseEvents` təyin olunur ki, həmin anda edilən klik ALTDAKI real düyməyə
çatsın — əks halda tema düyməsinə iki dəfə basan istifadəçinin ikinci kliki
itərdi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import QGraphicsOpacityEffect

from src.presentation.widgets.primitives import plain_label

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QWidget

#: Keçid müddəti. 260 ms — "hiss olunur, amma gözləmirsən" aralığı; daha
#: uzunu tema düyməsini ləng göstərir, daha qısası sadəcə sayrışmaya bənzəyir.
DEFAULT_DURATION_MS: Final = 260


def animate_theme_change(
    window: QWidget,
    apply_change: Callable[[], None],
    *,
    duration_ms: int = DEFAULT_DURATION_MS,
) -> None:
    """Tema dəyişikliyini yumşaq keçidlə tətbiq edir.

    Args:
        window: Şəkli çəkiləcək pəncərə (adətən əsas pəncərə).
        apply_change: Faktiki dəyişikliyi edən funksiya — QSS-i yazır və
            ikonları yeniləyir. Örtük qoyulduqdan SONRA çağırılır.
        duration_ms: Sönmə müddəti.

    Pəncərə hələ görünmürsə (test, işə düşmə anı) animasiya ATLANIR və
    dəyişiklik birbaşa tətbiq olunur — görünməyən pəncərənin şəkli boş olur
    və qara kvadrat kimi görünərdi.
    """
    if not window.isVisible() or window.width() <= 0 or window.height() <= 0:
        apply_change()
        return

    snapshot = window.grab()

    overlay = plain_label(parent=window)
    overlay.setPixmap(snapshot)
    overlay.setGeometry(window.rect())
    overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    overlay.setScaledContents(True)
    overlay.show()
    overlay.raise_()

    apply_change()

    effect = QGraphicsOpacityEffect(overlay)
    effect.setOpacity(1.0)
    overlay.setGraphicsEffect(effect)

    # Animasiya örtüyün UŞAĞIDIR — beləliklə `deleteLater()` hər ikisini
    # birlikdə yığışdırır və heç bir qlobal siyahı saxlamağa ehtiyac qalmır.
    # (Valideyn verilməsəydi, funksiya qayıtdıqda animasiya zibil kimi
    # toplanar və keçid heç başlamazdı.)
    animation = QPropertyAnimation(effect, b"opacity", overlay)
    animation.setDuration(duration_ms)
    animation.setStartValue(1.0)
    animation.setEndValue(0.0)
    animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
    animation.finished.connect(overlay.deleteLater)
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


__all__ = ["DEFAULT_DURATION_MS", "animate_theme_change"]
