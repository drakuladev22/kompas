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

from src.domain.entities.task import MIN_REJECTION_REASON_LENGTH
from src.domain.value_objects.identifiers import TaskId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_f import TasksScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Rədd səbəbinin minimum uzunluğu — DOMENDƏN gəlir, burada TƏKRARLANMIR.
#:
#: Əvvəl bu sətir `MIN_REJECT_REASON = 10` idi və şərhi «istifadəçiyə modalı
#: bağlamadan xəbər verir» deyirdi. Halbuki dəyəri HEÇ NƏ yoxlamırdı: rəqəm
#: yalnız dialoqun mətnində görünürdü. Yəni menecer 3 simvol yazır, modal
#: bağlanır, domen istisna atır və YAZDIĞI MƏTN İTİR — şərhin vəd etdiyinin
#: tam əksi. Üstəlik `10` iki yerdə yazılmışdı: domendəki dəyər dəyişsəydi
#: dialoq sükutla yalan rəqəm göstərərdi.
MIN_REJECT_REASON = MIN_REJECTION_REASON_LENGTH

#: Qısa səbəb üçün istifadəçi mesajı (naxış `fine_review.py::SHORT_REASON`).
SHORT_REASON = f"Rədd səbəbi ən azı {MIN_REJECT_REASON} simvol olmalıdır."


class TaskReviewController:
    """`TasksScreen` təsdiq/rədd düymələrini `TaskWorkflowUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: TasksScreen) -> None:
        screen.approved.connect(lambda task_id: self._on_approve(screen, task_id))
        screen.rejected.connect(lambda task_id: self._on_reject(screen, task_id))
        screen.create_requested.connect(lambda: self._on_create(screen))
        self.refresh(screen)

    # ------------------------------ yeni tapşırıq ---------------------------- #

    def _on_create(self, screen: TasksScreen) -> None:
        """«Yeni Tapşırıq» — forma açılır, `TaskWorkflowUseCase.assign` çağırılır.

        Düymə ekranda VARDI və `create_requested` yayırdı, lakin heç bir
        kontroller onu dinləmirdi: menecer basırdı, heç nə olmurdu və tapşırıq
        yaratmağın GUI-dan HEÇ BİR yolu yox idi.

        İşçi siyahısı forma AÇILMAZDAN ƏVVƏL oxunur — dialoq açıldıqdan sonra
        oxusaydıq, boş `QComboBox` görünərdi və istifadəçi onu «işçi yoxdur»
        kimi oxuyardı.
        """
        employees = self._read_employees(screen)
        if employees is None:
            return
        if not employees:
            _inform(
                screen,
                "Tapşırıq yaradıla bilmədi",
                "Aktiv işçi tapılmadı — tapşırıq təyin ediləcək adam yoxdur.",
            )
            return

        from PySide6.QtCore import QDateTime  # noqa: PLC0415

        from src.presentation.screens.group_f import NewTaskDialog  # noqa: PLC0415

        dialog = NewTaskDialog(
            screen.theme,
            employees=employees,
            # DEFOLT SON TARİX: sabah, iş gününün sonu. Dəqiq «indi» yazsaydıq
            # forma açılan anda ARTIQ gecikmiş tapşırıq təklif edərdi.
            default_deadline=QDateTime.currentDateTime().addDays(1),
            parent=screen,
        )
        dialog.submitted.connect(lambda payload: self._create(screen, payload))
        dialog.exec()

    def _create(self, screen: TasksScreen, payload: dict[str, Any]) -> None:
        from src.application.use_cases.task_workflow import TaskDraft  # noqa: PLC0415
        from src.domain.entities.task import TaskPriority  # noqa: PLC0415
        from src.domain.value_objects.identifiers import EmployeeId, new_task_id  # noqa: PLC0415

        deadline = payload["deadline"]
        if deadline.tzinfo is None:
            # TZ-AWARE MƏCBURİDİR (CLAUDE.md bölmə 4). `QDateTime.toPython()`
            # naive `datetime` qaytarır — yerli zonanı BURADA bağlayırıq,
            # çünki istifadəçi tarixi məhz öz saatı ilə seçdi.
            deadline = deadline.astimezone()

        def run(session: Session) -> None:
            session.tasks.assign(
                tenant_id=session.tenant_id,
                actor=self._actor,
                task_id=new_task_id(),
                draft=TaskDraft(
                    title=payload["title"],
                    assignee_id=EmployeeId(payload["assignee_id"]),
                    deadline=deadline,
                    description=payload["description"],
                    priority=TaskPriority(payload["priority"]),
                    requires_evidence=payload["requires_evidence"],
                ),
            )

        self._write(screen, run, failure="Tapşırıq yaradılmadı")

    def _read_employees(self, screen: TasksScreen) -> list[tuple[Any, str]] | None:
        """Aktiv işçilər — `(employee_id, tam ad)`. Xəta halında `None`.

        `None` ilə boş siyahının fərqi vacibdir: birincisi «oxuya bilmədik»
        (xəta göstərilir), ikincisi «həqiqətən işçi yoxdur» (ayrı izah).
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                rows = session.uow.connection.execute(
                    """
                    SELECT id, first_name, last_name
                      FROM employees
                     WHERE tenant_id = %s AND is_active
                     ORDER BY last_name, first_name
                     LIMIT 500
                    """,
                    (session.tenant_id,),
                ).fetchall()
        except KompasOSError as exc:
            _error_log.exception("TASK_EMPLOYEE_LIST_FAILED", extra={"error": str(exc)})
            _inform(
                screen,
                "Tapşırıq yaradıla bilmədi",
                getattr(exc, "user_message", "İşçi siyahısı oxuna bilmədi."),
            )
            return None
        return [(row["id"], f"{row['first_name']} {row['last_name']}".strip()) for row in rows]

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
        """Səbəb dialoqu — QISA cavab yazı yoluna ÜMUMİYYƏTLƏ girmir.

        Normalizasiya domendəki ilə EYNİDİR (`Task.reject` `strip()` edir):
        ekran daha sərt sayarsa, istifadəçi domenin qəbul etdiyi mətnə görə
        rədd cavabı alardı.
        """
        from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

        text, accepted = QInputDialog.getMultiLineText(
            screen,
            "Tapşırığı rədd et",
            f"Səbəb (məcburi, minimum {MIN_REJECT_REASON} simvol) — işçi onu\n"
            "görür və işini məhz bu izaha görə düzəldir:",
        )
        if not accepted:
            return None
        cleaned = text.strip()
        if len(cleaned) < MIN_REJECT_REASON:
            _inform(screen, "Rədd yazılmadı", SHORT_REASON)
            return None
        return cleaned

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
                on_retry=lambda: self.refresh(screen),
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
                # UI-R4-01: `on_retry` olmadan «Yenidən Cəhd Et» düyməsi
                # ÇƏKİLMİR. Oxu xətası isə məhz təkrar cəhd edilə biləndir —
                # şəbəkə/baza bir anlıq düşə bilər.
                on_retry=lambda: self.refresh(screen),
            )


def _inform(screen: Any, title: str, message: str) -> None:
    """İzah pəncərəsi — lövhəni BOŞALTMADAN (naxış `profile.py::_inform`).

    `Screen.show_error()` bütün sütunları əvəz edərdi: bir səbəbin qısa
    olması lövhənin qalan hissəsini etibarsız etmir.
    """
    from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

    box = QMessageBox(screen)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(message)
    box.exec()


__all__ = ["MIN_REJECT_REASON", "SHORT_REASON", "TaskReviewController"]
