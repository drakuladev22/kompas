"""Cərimə Etirazları gələnlər qutusunun YAZI yolu — qəbul / rədd qərarı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU MODUL VAR
──────────────────────────────────────────────────────────────────────────────
`FineAppealInboxScreen` hər etiraz kartına `[Qəbul Et]` və `[Rədd Et]`
düymələri qoyurdu və `accepted` / `rejected` siqnallarını (`appeal_id`, səbəb)
yayırdı. `FineAppealUseCase.approve/reject` isə tam işlək idi — 72 saatlıq
etiraz mexanizmi, cərimənin ləğvi, audit yazısı, işçiyə bildiriş. Aralarındakı
bağlantı YOX idi: `app.py::_dispatch_attach` cədvəlində bu ekran ÜMUMİYYƏTLƏ
yox idi, ona görə heç bir kontroller siqnalları dinləmirdi.

Nəticəsi «düymə işləmir»dən ağırdır. Etiraz REAL PUL kəsintisinə qarşıdır:
HR_Admin qərarın səbəbini yazır, `[Qəbul Et]` basır, ekran susur və kart
yerində qalır. Qərar heç vaxt yazılmır, cərimə qüvvədə qalır və etiraz
`expire_stale` ilə «HR cavab vermədi» statusuna düşür — yəni işçi haqlı
olduğu halda da pulunu geri almır, üstəlik sistem bunu HR-ın səhvi kimi
qeyd edir.

Oxu yolu ARTIQ düzəldilmişdi (`screen_data._fine_appeals` — kartlar boş `id`
yayırdı, düzəldildi), yəni bu, həmin işin YARIMÇIQ qalmış ikinci yarısıdır.

──────────────────────────────────────────────────────────────────────────────
QISA SƏBƏB YAZI YOLUNA ÜMUMİYYƏTLƏ GİRMİR
──────────────────────────────────────────────────────────────────────────────
Domen qərar izahını MƏCBURİ edir (`FineAppeal._require_note`,
`MIN_DECISION_NOTE_LENGTH`) və eyni normalizasiyanı işlədir
(`" ".join(note.split())`) — kontroller həmin sabiti İDXAL edir, təkrar
YAZMIR: rəqəmi burada təkrarlasaydıq, domendəki dəyər dəyişəndə ekran sükutla
yalan danışardı.

Yoxlama NİYƏ kontrollerdə də var (`exceptions.py` əksini seçir): səbəb qutusu
KARTIN İÇİNDƏDİR və siyahı hər yazıdan sonra yenidən qurulur. Use case-in
istisnasını gözləsəydik, kartlar artıq yenidən qurulmuş olardı və istifadəçi
yazdığı mətni İTİRƏRDİ. Ona görə qısa mətn sessiya AÇILMADAN modalla qaytarılır
— naxış `fine_review.py::_ask_reason` ilə eynidir.

──────────────────────────────────────────────────────────────────────────────
XƏTA MODALDIR, `show_error` DEYİL
──────────────────────────────────────────────────────────────────────────────
`Screen.show_error()` bütün məzmunu əvəz edir — yəni qalan etirazlar da
ekrandan yox olardı və istifadəçi yazdığı səbəbi geri ala bilməzdi. Uğursuz
YAZI isə siyahını etibarsız etmir: bir qərar keçmədi, digərləri hələ də
gözləyir. Ona görə yazı xətası modalla deyilir (naxış `profile.py::_inform`),
OXU xətası isə `show_error` ilə — orada siyahının ÖZÜ yoxdur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from src.domain.entities.appeal import MIN_DECISION_NOTE_LENGTH
from src.domain.value_objects.identifiers import AppealId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_f import FineAppealInboxScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Qısa səbəb üçün istifadəçi mesajı — hədd domendən gəlir, burada TƏKRARLANMIR.
SHORT_NOTE_MESSAGE = (
    f"Qərarın səbəbi ən azı {MIN_DECISION_NOTE_LENGTH} simvol olmalıdır — "
    "işçi cərimənin niyə qüvvədə qaldığını (və ya ləğv edildiyini) məhz bu "
    "mətndən öyrənir."
)

#: Yararsız `appeal_id` mesajı. Normal axında baş verməməlidir (`id` siyahının
#: ÖZ məlumatından gəlir), lakin köhnəlmiş kart halında istifadəçi SƏBƏBİ
#: görməlidir — «susqun boş ekran» CLAUDE.md-nin qadağan etdiyi haldır (QA-13).
UNKNOWN_APPEAL_MESSAGE = "Bu etiraz artıq siyahıda deyil — siyahını yeniləyin."


class FineAppealInboxController:
    """`FineAppealInboxScreen` qərar düymələrini `FineAppealUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: FineAppealInboxScreen) -> None:
        """Siqnalları bağlayır.

        İlk doldurma BURADA EDİLMİR: «fine_appeals» açarı
        `ScreenDataBinder._binders()`-dədir, yəni ekranı `app.py` onsuz da
        doldurur. İkinci oxu sessiyanın gediş-gəliş büdcəsini (PERF-1/2/3)
        sükutla artırardı.
        """
        screen.accepted.connect(
            lambda appeal_id, note: self._decide(
                screen, appeal_id, note, approve=True, failure="Etiraz qəbul edilmədi"
            )
        )
        screen.rejected.connect(
            lambda appeal_id, note: self._decide(
                screen, appeal_id, note, approve=False, failure="Etiraz rədd edilmədi"
            )
        )

    # ------------------------------- qərarlar -------------------------------- #

    def _decide(
        self,
        screen: FineAppealInboxScreen,
        appeal_id_text: str,
        note: str,
        *,
        approve: bool,
        failure: str,
    ) -> None:
        cleaned = " ".join(note.split())
        if len(cleaned) < MIN_DECISION_NOTE_LENGTH:
            _inform(screen, failure, SHORT_NOTE_MESSAGE)
            return

        try:
            appeal_id = AppealId(UUID(appeal_id_text))
        except (ValueError, AttributeError, TypeError):
            _error_log.exception("FINE_APPEAL_ID_INVALID", extra={"appeal_id": str(appeal_id_text)})
            _inform(screen, failure, UNKNOWN_APPEAL_MESSAGE)
            return

        def run(session: Session) -> None:
            if approve:
                # `new_amount` GÖNDƏRİLMİR: ekranda məbləğ sahəsi yoxdur, yəni
                # qəbul = cərimənin TAM ləğvi. Qismən azaltma use case-də var
                # (`new_amount`), lakin onu burada `None`-dan fərqli etmək
                # ekranın vermədiyi bir qərarı UYDURMAQ olardı.
                session.fine_appeals.approve(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    appeal_id=appeal_id,
                    note=cleaned,
                )
            else:
                session.fine_appeals.reject(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    appeal_id=appeal_id,
                    note=cleaned,
                )

        self._write(screen, run, failure=failure)

    # -------------------------------- yazı ----------------------------------- #

    def _write(self, screen: FineAppealInboxScreen, action: Any, *, failure: str) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                action(session)
                session.commit()
        except KompasOSError as exc:
            _error_log.exception("FINE_APPEAL_DECISION_FAILED", extra={"error": str(exc)})
            _inform(screen, failure, getattr(exc, "user_message", "Yenidən cəhd edin."))
            return
        self.refresh(screen)

    # -------------------------------- oxuma ---------------------------------- #

    def refresh(self, screen: FineAppealInboxScreen) -> None:
        """Gələnlər qutusunu yenidən oxuyur — `screen_data` ilə EYNİ yoldan.

        Qərar verilmiş etiraz siyahıdan ÇIXIR (`inbox` yalnız qərar
        gözləyənləri qaytarır). Kartı yerində silsəydik, ekran bazadakı
        həqiqətdən ayrıla bilərdi — məsələn `expire_stale` eyni anda başqa
        sətri bağlayıbsa. Yenidən oxuma tək həqiqət mənbəyini saxlayır
        (CLAUDE.md bölmə 6).
        """
        from src.presentation.controllers.screen_data import ScreenDataBinder  # noqa: PLC0415

        try:
            ScreenDataBinder(self._context, self._actor).populate("fine_appeals", screen)
        except KompasOSError as exc:
            _error_log.exception("FINE_APPEAL_REFRESH_FAILED", extra={"error": str(exc)})
            screen.show_error(
                title="Etirazlar oxuna bilmədi",
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
    "SHORT_NOTE_MESSAGE",
    "UNKNOWN_APPEAL_MESSAGE",
    "FineAppealInboxController",
]
