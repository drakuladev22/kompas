"""Gündəlik Mağaza Tabelinin YAZI yolu — təsdiq və qaralama qeydi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU MODUL VAR
──────────────────────────────────────────────────────────────────────────────
`DailyRosterScreen` iki düymə çəkirdi — `[Tabeli Təsdiqlə]` və
`[Qaralama Saxla]` — və `approve_requested` / `draft_saved` siqnallarını
yayırdı. `DailyAttendanceSheetUseCase.confirm()` isə tam işlək idi: imza,
audit, uyğunsuzluq bildirişi, norma üstü saatların yazılması. Bağlantı YOX
idi: bu ekran `app.py::_dispatch_attach` cədvəlində ÜMUMİYYƏTLƏ yox idi.

Nəticəsi mağaza menecerinin GÜNDƏLİK işidir: tabelə baxır, «Təsdiqlə» basır,
ekran susur. Tabel təsdiqsiz qalır — yəni (a) HR uyğunsuzluq xəbərdarlığını
HEÇ VAXT almır, (b) norma üstü saatlar `overtime_log`-a düşmür, çünki aşım
YALNIZ imzalanmış tabeldən hesablanır. İkincisi birbaşa pul deməkdir.

──────────────────────────────────────────────────────────────────────────────
TƏSDİQ TƏSDİQ MODALINDAN KEÇİR, QARALAMA KEÇMİR
──────────────────────────────────────────────────────────────────────────────
`sheet.confirm()` geri qaytarıla bilmir (`_require_open` təsdiqlənmiş tabelə
ikinci dəfə toxunmağa imkan vermir) — yəni səhv klik günü bağlayır. Ona görə
imza əvvəl SORUŞULUR, naxış `fine_review.py::_confirm` ilə eynidir.

Qaralama isə geri qaytarıla biləndir (qeyd üstünə yazılır), ona görə modal
YOXDUR: hər saxlamada təsdiq soruşmaq menecerin iş axınını əbəs yavaşladardı.

──────────────────────────────────────────────────────────────────────────────
TARİX EKRANDA HESABLANMIR
──────────────────────────────────────────────────────────────────────────────
`confirm`/`save_draft_note` `sheet_date`-i BOŞ buraxır: defolt `Clock`-un
bugünüdür. Tarixi burada `date.today()` ilə qursaydıq, gecə yarısı keçidində
GUI-nin günü ilə serverin günü ayrıla bilərdi — və tabel SƏHV günə imzalanardı
(CLAUDE.md bölmə 4: domen vaxtı `Clock` portundan alır).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_c import DailyRosterScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Mağazası olmayan aktor üçün mesaj. Oxu yolu (`screen_data._daily_roster`)
#: belə halda BOŞ siyahı göstərir — yazı yolu isə səbəbi AÇIQ deməlidir,
#: yoxsa düymə «yenə işləmədi» kimi görünərdi.
NO_STORE_MESSAGE = (
    "Hesabınız heç bir mağazaya bağlı deyil — tabel mağaza üzrə imzalanır. "
    "HR bölməsi ilə əlaqə saxlayın."
)

CONFIRM_QUESTION = (
    "Tabel imzalandıqdan sonra DƏYİŞDİRİLƏ BİLMİR: qeydlər kilidlənir, "
    "uyğunsuzluqlar HR-a bildirilir və norma üstü saatlar hesablanır.\n\n"
    "Bugünkü tabeli təsdiqləyirsiniz?"
)


class DailyRosterController:
    """`DailyRosterScreen` düymələrini `DailyAttendanceSheetUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: DailyRosterScreen) -> None:
        """Siqnalları bağlayır.

        İlk doldurma BURADA EDİLMİR: «daily_roster» açarı
        `ScreenDataBinder._binders()`-dədir (PERF-1/2/3 — ikinci oxu sessiyanın
        gediş-gəliş büdcəsini sükutla artırardı).
        """
        screen.approve_requested.connect(lambda: self._on_confirm(screen))
        screen.draft_saved.connect(lambda note: self._on_draft(screen, note))

    # ------------------------------- təsdiq ---------------------------------- #

    def _on_confirm(self, screen: DailyRosterScreen) -> None:
        store_id = getattr(self._actor, "store_id", None)
        if store_id is None:
            _inform(screen, "Tabel təsdiqlənmədi", NO_STORE_MESSAGE)
            return
        if not _confirm(screen, CONFIRM_QUESTION):
            return

        def run(session: Session) -> None:
            session.daily_attendance.confirm(
                tenant_id=session.tenant_id,
                actor=self._actor,
                store_id=store_id,
                manager_note=screen.manager_note(),
            )

        self._write(screen, run, failure="Tabel təsdiqlənmədi")

    # ------------------------------ qaralama --------------------------------- #

    def _on_draft(self, screen: DailyRosterScreen, note: str) -> None:
        store_id = getattr(self._actor, "store_id", None)
        if store_id is None:
            _inform(screen, "Qaralama saxlanmadı", NO_STORE_MESSAGE)
            return

        def run(session: Session) -> None:
            session.daily_attendance.save_draft_note(
                tenant_id=session.tenant_id,
                actor=self._actor,
                store_id=store_id,
                note=note,
            )

        self._write(screen, run, failure="Qaralama saxlanmadı")

    # -------------------------------- yazı ----------------------------------- #

    def _write(self, screen: DailyRosterScreen, action: Any, *, failure: str) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                action(session)
                session.commit()
        except KompasOSError as exc:
            _error_log.exception("DAILY_ROSTER_WRITE_FAILED", extra={"error": str(exc)})
            # Modal, `show_error` DEYİL: uğursuz imza tabelin sətirlərini
            # etibarsız etmir və menecer onlara baxmağa davam etməlidir.
            _inform(screen, failure, getattr(exc, "user_message", "Yenidən cəhd edin."))
            return
        self.refresh(screen)

    # -------------------------------- oxuma ---------------------------------- #

    def refresh(self, screen: DailyRosterScreen) -> None:
        """Tabeli yenidən oxuyur — `screen_data` ilə EYNİ yoldan.

        Təsdiqdən sonra sətirlər kilidlənir və uyğunsuzluq bandı dəyişir;
        qaralamadan sonra qeyd sütunu yenilənir. Ekranı yerində düzəltsəydik,
        iki oxu məntiqi yaranardı (CLAUDE.md bölmə 6).
        """
        from src.presentation.controllers.screen_data import ScreenDataBinder  # noqa: PLC0415

        try:
            ScreenDataBinder(self._context, self._actor).populate("daily_roster", screen)
        except KompasOSError as exc:
            _error_log.exception("DAILY_ROSTER_REFRESH_FAILED", extra={"error": str(exc)})
            screen.show_error(
                title="Tabel oxuna bilmədi",
                message=getattr(exc, "user_message", "Yenidən cəhd edin."),
                on_retry=lambda: self.refresh(screen),
            )


def _inform(screen: Any, title: str, message: str) -> None:
    """İzah pəncərəsi — tabeli BOŞALTMADAN (naxış `profile.py::_inform`)."""
    from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

    box = QMessageBox(screen)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(message)
    box.exec()


def _confirm(screen: Any, question: str) -> bool:
    """Geri qaytarıla bilməyən əməliyyat üçün təsdiq modalı."""
    from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

    answer = QMessageBox.question(
        screen,
        "Tabeli təsdiqlə",
        question,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return bool(answer == QMessageBox.StandardButton.Yes)


__all__ = ["CONFIRM_QUESTION", "NO_STORE_MESSAGE", "DailyRosterController"]
