"""Növbə matrisinin AY OXLARI — pəncərəni irəli/geri sürüşdürür.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU MODUL VAR
──────────────────────────────────────────────────────────────────────────────
Növbə Planlama ekranının toolbar-ında «‹» və «›» oxları VARDI və `month_changed`
siqnalını yayırdılar, lakin heç kim dinləmirdi: menecer «növbəti ay»a basır,
matris olduğu kimi qalırdı. Növbə planlaması isə məhz GƏLƏCƏYƏ baxmaq üçündür —
yəni ekranın ƏSAS məqsədi sükutla işləmirdi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI FAYL, `shift_matrix.py`-a ƏLAVƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
Həmin modul İŞ REJİMİ SEÇİCİSİDİR və başlığında açıq şəkildə yazılıb ki, növbə
YAZMA yoluna toxunmur; `tests/unit/test_shift_matrix_work_mode.py` bunu mənbə
mətnindən yoxlayır. Ay oxları isə bütün matrisi yenidən doldurur — yəni
`shift_planning` bağlayıcısına müraciət edir. İkisini bir sinifdə birləşdirmək
həmin intizam qapısını mənasızlaşdırardı: seçici ilə matris naviqasiyası eyni
sinfin içində qarışar və "seçici matrisə toxunmur" ifadəsi yoxlanıla bilməzdi.

Bir ekrana bir neçə kontroller bağlamaq mövcud naxışdır (`users` ekranı üç
kontroller alır) — ona görə ayırma əlavə xərc gətirmir.

──────────────────────────────────────────────────────────────────────────────
ADDIM NİYƏ SABİT 30 GÜN DEYİL
──────────────────────────────────────────────────────────────────────────────
Sürüşmə addımı pəncərənin ÖZ uzunluğudur (`matrix_window_days`, ROOT
parametri). Sabit 30 yazsaydıq, Root pəncərəni 14 günə endirəndə iki klik
arasında GÖRÜNMƏYƏN boşluq qalardı — istifadəçi «keçən ay» edib geri qayıdanda
aradakı günləri heç vaxt görməzdi.

SESSİYA SAXLANILMIR (CLAUDE.md §6): hər ox klikində yenisi açılır. Panel
saatlarla açıq qala bilər və uzun-ömürlü tranzaksiya bu müddət boyu kilid
saxlayardı.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext
    from src.presentation.screens.group_c import ShiftPlanningScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)


class ShiftWindowController:
    """«‹ / ›» oxlarını matris pəncərəsinin sürüşməsinə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor
        #: Cari sürüşmə (gün). Kontrollerdə saxlanılır, bağlayıcıda YOX:
        #: bağlayıcı hər əməliyyatda yenidən qurulur və vəziyyəti itirərdi.
        self._offset_days = 0

    def attach(self, screen: ShiftPlanningScreen) -> None:
        screen.month_changed.connect(lambda step: self._on_month_changed(screen, step))

    def _on_month_changed(self, screen: ShiftPlanningScreen, step: int) -> None:
        """Pəncərəni `step` qədər sürüşdürüb matrisi yenidən doldurur.

        PƏNCƏRƏ UZUNLUĞU OXUNA BİLMƏSƏ HEÇ NƏ EDİLMİR: sıfır addımla
        sürüşdürmək oxu "işləyir amma nəticəsizdir" halına salardı — bu isə
        ilkin nasazlıqla eyni təəssüratı yaradır.

        `populate(..., reraise=True)` (QA-FULL Faza 3): əvvəl `populate()`
        HƏR istisnanı özü udurdu (bölmə banneri) və aşağıdakı
        `except KompasOSError` HEÇ VAXT işə düşmürdü — matris sınanda
        toolbar sükutla köhnə ayı göstərməyə davam edirdi, heç bir mesaj
        çıxmırdı. Yalnız `KompasOSError` BURAYA yenidən atılır, digər
        xətalar `populate()` daxilində köhnə kimi udulmağa davam edir.
        """
        from src.presentation.controllers.screen_data import ScreenDataBinder  # noqa: PLC0415

        binder = ScreenDataBinder(self._context, self._actor)
        try:
            with self._context.session(user_id=self._actor.id) as session:
                window = binder.shift_window_days(session)
        except KompasOSError as exc:
            _error_log.exception("SHIFT_WINDOW_LENGTH_FAILED", extra={"error": str(exc)})
            return
        if window <= 0:
            return

        self._offset_days += int(step) * window
        binder.set_shift_offset(self._offset_days)
        try:
            binder.populate("shift_planning", screen, reraise=True)
        except KompasOSError as exc:
            _error_log.exception("SHIFT_WINDOW_FAILED", extra={"error": str(exc)})
            screen.show_error(
                title="Növbə matrisi oxuna bilmədi",
                message=getattr(exc, "user_message", "Yenidən cəhd edin."),
            )


__all__ = ["ShiftWindowController"]
