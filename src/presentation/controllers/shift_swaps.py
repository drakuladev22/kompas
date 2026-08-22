"""Növbə Dəyişmə sorğularının YAZI yolu — təsdiq və rədd.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU MODUL VAR
──────────────────────────────────────────────────────────────────────────────
`ShiftSwapScreen` `[Təsdiqlə]` / `[Rədd Et]` düymələrini çəkirdi və
`approved` / `rejected` siqnallarını (`request_id`) yayırdı;
`ShiftSwapUseCase.approve/reject` isə tam işlək idi — təsdiqdən sonra növbə
matrisi yenilənir, rəddə isə işçiyə SƏBƏBLƏ bildiriş gedir. Bağlantı YOX idi:
ekran `app.py::_dispatch_attach` cədvəlində ÜMUMİYYƏTLƏ yox idi.

Qüsur `test_signal_wiring_gate.py`-dan da SÜKUTLA keçirdi: qapı siqnalı ADINA
görə axtarır və `approved`/`rejected` adları `TasksScreen`-də DƏ var. Tapşırıq
lövhəsinin bağlantısı bu ekranı da «bağlanıb» göstərirdi — qapının öz
sənədləşdirilmiş kor nöqtəsi (bax həmin faylın `ambiguous` bloku).

Nəticəsi növbə cədvəlidir: işçi dəyişmə istəyir, menecer «Təsdiqlə» basır, heç
nə olmur. Sorğu `PENDING` qalır, matris köhnə qalır — yəni işçi razılaşdığını
sandığı gün üçün planlaşdırılmış olaraq qalır və gəlmədikdə DAVAMİYYƏT
pozuntusu kimi görünür.

──────────────────────────────────────────────────────────────────────────────
RƏDD SƏBƏBİ SESSİYA AÇILMADAN YOXLANILIR
──────────────────────────────────────────────────────────────────────────────
Hədd domendədir (`ShiftSwapRequest.reject` → `MIN_DECISION_REASON_LENGTH`) və
BURADA TƏKRARLANMIR — idxal edilir. Normalizasiya da EYNİDİR
(`src/shared/text.py::normalise_decision_text` — domendəki `ShiftSwapRequest.
reject` ilə TƏK mənbədən): ekran daha sərt saysaydı, istifadəçi domenin qəbul
etdiyi mətnə görə rədd cavabı alardı.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from src.domain.entities.shift import MIN_DECISION_REASON_LENGTH
from src.domain.value_objects.identifiers import ShiftSwapRequestId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger
from src.shared.text import normalise_decision_text

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_c import ShiftSwapScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

REJECT_PROMPT = (
    f"Rədd səbəbi (məcburi, minimum {MIN_DECISION_REASON_LENGTH} simvol) — işçi\n"
    "bildirişdə məhz bu mətni oxuyur və növbəsini ona görə planlaşdırır:"
)

SHORT_REASON = f"Rədd səbəbi ən azı {MIN_DECISION_REASON_LENGTH} simvol olmalıdır."

UNKNOWN_REQUEST_MESSAGE = "Bu sorğu artıq siyahıda deyil — siyahını yeniləyin."


class ShiftSwapController:
    """`ShiftSwapScreen` qərar düymələrini `ShiftSwapUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: ShiftSwapScreen) -> None:
        """Siqnalları bağlayır.

        İlk doldurma BURADA EDİLMİR: «shift_swaps» açarı
        `ScreenDataBinder._binders()`-dədir (PERF-1/2/3).
        """
        screen.approved.connect(lambda request_id: self._on_approve(screen, request_id))
        screen.rejected.connect(lambda request_id: self._on_reject(screen, request_id))

    # ------------------------------- qərarlar -------------------------------- #

    def _on_approve(self, screen: ShiftSwapScreen, request_id_text: str) -> None:
        request_id = self._parse(screen, request_id_text, failure="Təsdiq yazılmadı")
        if request_id is None:
            return

        def run(session: Session) -> None:
            session.shift_swaps.approve(
                tenant_id=session.tenant_id,
                approver=self._actor,
                request_id=request_id,
            )

        self._write(screen, run, failure="Təsdiq yazılmadı")

    def _on_reject(self, screen: ShiftSwapScreen, request_id_text: str) -> None:
        request_id = self._parse(screen, request_id_text, failure="Rədd yazılmadı")
        if request_id is None:
            return
        reason = self._ask_reason(screen)
        if reason is None:
            return

        def run(session: Session) -> None:
            session.shift_swaps.reject(
                tenant_id=session.tenant_id,
                approver=self._actor,
                request_id=request_id,
                reason=reason,
            )

        self._write(screen, run, failure="Rədd yazılmadı")

    # ------------------------------ köməkçilər -------------------------------- #

    def _parse(
        self, screen: ShiftSwapScreen, request_id_text: str, *, failure: str
    ) -> ShiftSwapRequestId | None:
        """Yararsız identifikator SÜKUTLA udulmur (QA-13 naxışı)."""
        try:
            return ShiftSwapRequestId(UUID(request_id_text))
        except (ValueError, AttributeError, TypeError):
            _error_log.exception(
                "SHIFT_SWAP_ID_INVALID", extra={"request_id": str(request_id_text)}
            )
            _inform(screen, failure, UNKNOWN_REQUEST_MESSAGE)
            return None

    @staticmethod
    def _ask_reason(screen: ShiftSwapScreen) -> str | None:
        """Səbəb dialoqu — QISA cavab yazı yoluna ÜMUMİYYƏTLƏ girmir."""
        from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

        text, accepted = QInputDialog.getMultiLineText(
            screen, "Növbə dəyişməsini rədd et", REJECT_PROMPT
        )
        if not accepted:
            return None
        # KÖHNƏ NÜSXƏ ƏVƏZLƏNDİ (`domain` sahibinin tapıntısı, `src/shared/
        # text.py`): sadə `" ".join(text.split())` Unicode Cf (Format)
        # simvollarını (sıfır-en boşluq və s.) SIXMIR — 10 ədəd görünməz
        # simvol `MIN_DECISION_REASON_LENGTH` şərtini keçirib boş mətni
        # "səbəb" kimi qəbul etdirirdi. `normalise_decision_text` əvvəlcə
        # onları ATIR, sonra sıxır.
        cleaned = normalise_decision_text(text)
        if len(cleaned) < MIN_DECISION_REASON_LENGTH:
            _inform(screen, "Rədd yazılmadı", SHORT_REASON)
            return None
        return cleaned

    # -------------------------------- yazı ----------------------------------- #

    def _write(self, screen: ShiftSwapScreen, action: Any, *, failure: str) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                action(session)
                session.commit()
        except KompasOSError as exc:
            _error_log.exception("SHIFT_SWAP_DECISION_FAILED", extra={"error": str(exc)})
            # Modal, `show_error` DEYİL: bir qərarın uğursuzluğu qalan
            # sorğuları etibarsız etmir və menecer onları görməyə davam etməlidir.
            _inform(screen, failure, getattr(exc, "user_message", "Yenidən cəhd edin."))
            return
        except Exception:
            # QA-FULL FAZA 6 (stress/xaos) tapıntısı: `session.commit()` anında
            # bağlantı kəsilsə (`psycopg.OperationalError`, `KompasOSError`
            # DEYİL), bu ikinci qat OLMADAN istisna HEÇ YERDƏ tutulmurdu —
            # kartın kontekstual modalı əvəzinə ümumi bildiriş gəlirdi (bir
            # dəfə; `notify_unhandled_error`-un `_crash_notified` qapısı
            # sessiya ərzində YALNIZ BİR DƏFƏ göstərir). Naxış
            # `open_shift.py::_on_claim`/`_submit`/`_on_cancel` və
            # `fine_entry.py::_issue`-dəki ikinci qatla EYNİDİR.
            _error_log.exception("SHIFT_SWAP_DECISION_UNEXPECTED_FAILED")
            _inform(screen, failure, "Yenidən cəhd edin.")
            return
        self.refresh(screen)

    # -------------------------------- oxuma ---------------------------------- #

    def refresh(self, screen: ShiftSwapScreen) -> None:
        """Siyahını yenidən oxuyur — `screen_data` ilə EYNİ yoldan.

        Qərar verilmiş sorğu siyahıdan çıxır və təsdiq halında NÖVBƏ MATRİSİ
        də dəyişir. Kartı yerində silsəydik, ekran bazadakı həqiqətdən ayrıla
        bilərdi (CLAUDE.md bölmə 6).
        """
        from src.presentation.controllers.screen_data import ScreenDataBinder  # noqa: PLC0415

        try:
            ScreenDataBinder(self._context, self._actor).populate("shift_swaps", screen)
        except KompasOSError as exc:
            _error_log.exception("SHIFT_SWAP_REFRESH_FAILED", extra={"error": str(exc)})
            screen.show_error(
                title="Sorğular oxuna bilmədi",
                message=getattr(exc, "user_message", "Yenidən cəhd edin."),
                on_retry=lambda: self.refresh(screen),
            )


def _inform(screen: Any, title: str, message: str) -> None:
    """İzah pəncərəsi — siyahını BOŞALTMADAN (naxış `profile.py::_inform`)."""
    from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

    box = QMessageBox(screen)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(message)
    box.exec()


__all__ = [
    "REJECT_PROMPT",
    "SHORT_REASON",
    "UNKNOWN_REQUEST_MESSAGE",
    "ShiftSwapController",
]
