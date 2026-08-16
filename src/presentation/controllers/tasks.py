"""Tapşırıq lövhəsinin YAZI yolu — sübutun təsdiqi və rəddi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU MODUL VAR
──────────────────────────────────────────────────────────────────────────────
`TasksScreen` «Nəzərdən Keçirilir» sütununda hər karta `[Təsdiqlə]` və
`[Rədd Et]` düymələri qoyurdu; `TaskWorkflowUseCase.approve/reject` isə tam
işlək idi. Aralarındakı bağlantı yox idi — yəni menecer düyməni basırdı,
tapşırıq sütunda qalırdı və heç bir xəta çıxmırdı.

Nəticəsi sadəcə «düymə işləmir» deyil: işçi sübutunu göndərib gözləyir,
menecer isə təsdiqlədiyini sanır. Tapşırıq heç vaxt bağlanmır və gecikmə
eskalasiyası (`escalate_overdue`) onu gecikmiş kimi işarələyir — yəni işçi
etmədiyi bir gecikmənin nəticəsini alır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ RƏDD SƏBƏBSİZ OLA BİLMİR
──────────────────────────────────────────────────────────────────────────────
Use case səbəbi MƏCBURİ arqument kimi tələb edir və bu, düzgündür: rədd
işçinin işini geri qaytarır, o isə nəyi düzəltməli olduğunu bilməlidir.
Ekran səbəb sahəsi daşımır (kart kompaktdır), ona görə səbəb modaldan alınır —
eyni naxış `camera_queue.py`-dadır.

──────────────────────────────────────────────────────────────────────────────
HƏR QƏRARDAN SONRA SİYAHI YENİDƏN OXUNUR
──────────────────────────────────────────────────────────────────────────────
Təsdiq tapşırığı «Nəzərdən Keçirilir»-dən «Tamamlandı»-ya keçirir. Sütunları
yerində yeniləsəydik (kartı əl ilə köçürmək), ekran bazadakı həqiqətdən
ayrıla bilərdi — məsələn eskalasiya eyni anda statusu dəyişibsə. Yenidən oxuma
tək həqiqət mənbəyini saxlayır (CLAUDE.md bölmə 6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from src.domain.value_objects.identifiers import TaskId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_f import TasksScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Rədd səbəbinin minimum uzunluğu — use case-dəki qaydanın EKRAN güzgüsü.
#: Həqiqi qapı domendədir; bu, istifadəçiyə modalı bağlamadan xəbər verir.
MIN_REJECT_REASON = 10


class TaskReviewController:
    """`TasksScreen` təsdiq/rədd düymələrini `TaskWorkflowUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: TasksScreen) -> None:
        screen.approved.connect(lambda task_id: self._on_approve(screen, task_id))
        screen.rejected.connect(lambda task_id: self._on_reject(screen, task_id))
        self.refresh(screen)

    # ------------------------------- qərarlar -------------------------------- #

    def _on_approve(self, screen: TasksScreen, task_id: str) -> None:
        def run(session: Session) -> None:
            session.tasks.approve(
                tenant_id=session.tenant_id,
                actor=self._actor,
                task_id=TaskId(UUID(task_id)),
            )

        self._write(screen, run, failure="Təsdiq yazılmadı")

    def _on_reject(self, screen: TasksScreen, task_id: str) -> None:
        reason = self._ask_reason(screen)
        if reason is None:
            return

        def run(session: Session) -> None:
            session.tasks.reject(
                tenant_id=session.tenant_id,
                actor=self._actor,
                task_id=TaskId(UUID(task_id)),
                reason=reason,
            )

        self._write(screen, run, failure="Rədd yazılmadı")

    @staticmethod
    def _ask_reason(screen: TasksScreen) -> str | None:
        from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

        text, accepted = QInputDialog.getMultiLineText(
            screen,
            "Tapşırığı rədd et",
            f"Səbəb (məcburi, minimum {MIN_REJECT_REASON} simvol) — işçi onu\n"
            "görür və işini məhz bu izaha görə düzəldir:",
        )
        cleaned = text.strip()
        return cleaned if accepted and cleaned else None

    # -------------------------------- yazı ----------------------------------- #

    def _write(self, screen: TasksScreen, action: Any, *, failure: str) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                action(session)
                session.commit()
        except KompasOSError as exc:
            _error_log.exception("TASK_REVIEW_FAILED", extra={"error": str(exc)})
            screen.show_error(
                title=failure,
                message=getattr(exc, "user_message", "Yenidən cəhd edin."),
            )
            return
        self.refresh(screen)

    # -------------------------------- oxuma ---------------------------------- #

    def refresh(self, screen: TasksScreen) -> None:
        """Lövhəni yenidən doldurur — `screen_data` ilə EYNİ yoldan.

        Oxu məntiqi burada TƏKRARLANMIR: iki yer ayrı yazsaydı, biri sütun
        açarını dəyişəndə (`open`/`review`/`done`) digəri sükutla köhnə açarla
        qalar və lövhə yarımçıq dolardı — layihədə məhz bu qüsur olub (bax
        `screen_data._tasks` şərhi).
        """
        from src.presentation.controllers.screen_data import ScreenDataBinder  # noqa: PLC0415

        try:
            ScreenDataBinder(self._context, self._actor).populate("tasks", screen)
        except KompasOSError as exc:
            _error_log.exception("TASK_REFRESH_FAILED", extra={"error": str(exc)})
            screen.show_error(
                title="Tapşırıqlar oxuna bilmədi",
                message=getattr(exc, "user_message", "Yenidən cəhd edin."),
            )


__all__ = ["MIN_REJECT_REASON", "TaskReviewController"]
