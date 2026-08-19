"""İşçi Ana Ekranının üç öz-xidmət keçidi — tapşırıqlar, xallar, cərimələr.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU MODUL VAR
──────────────────────────────────────────────────────────────────────────────
Spesifikasiya (bölmə 3, «İŞÇİ ANA EKRANI») işçiyə ÜÇ şey vəd edir: öz açıq
tapşırıqları, öz cari xal balansı və öz «Cərimələrim» kartı — sonuncusu
«kliklədikdə tam tarixçə və etiraz ekranına keçid» ilə birlikdə.

Hər üç ekran KODDA MÖVCUD İDİ (`TasksScreen`, `SalesPointsScreen`,
`FineAppealScreen`), üç düymə də vardı və `tasks_requested`/
`rewards_requested`/`appeal_requested` siqnallarını yayırdı. Çatışmayan
yeganə halqa ONLARI DİNLƏYƏN tərəf idi: işçi düyməni basırdı, heç nə baş
vermirdi, heç bir xəta da çıxmırdı.

Nəticəsi ən ağır olan halqa cərimə etirazı idi — işçinin cəriməyə etiraz
etmək hüququ interfeysdən ÜMUMİYYƏTLƏ əlçatan deyildi, halbuki cərimə real
pul kəsintisidir və etiraz pəncərəsi (72 saat) işləyirdi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI KONTROLLER, `KioskController`-Ə ƏLAVƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
`KioskController` GÜNÜN AXINIDIR: giriş → icazə → qayıdış. Onun hər metodu
işçinin STATUSUNU dəyişir və nəticəsi `KioskOutcome`-dur. Buradakı üç keçid
isə statusdan asılı deyil və heç nə yazmır (etiraz istisna olmaqla) — onları
eyni sinfə qoymaq «status axını» anlayışını yayardı. Eyni əsaslandırma
`controllers/open_shift.py` başlığındadır.

──────────────────────────────────────────────────────────────────────────────
GERİ QAYITMA NİYƏ ÖRTÜKDƏ QURULUR
──────────────────────────────────────────────────────────────────────────────
Ekranların özündə «geri» düyməsi YOXDUR və olmamalıdır: eyni `TasksScreen`
admin panelində də göstərilir, orada isə geri düyməsi mənasızdır (naviqasiya
sol paneldədir). Ona görə düymə kiosk örtüyünün SARĞISINDA yaradılır —
ekranın özü toxunulmaz qalır və iki kontekstdə eyni sinif işlənir.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from src.domain.value_objects.identifiers import FineId
from src.presentation.widgets import metrics
from src.presentation.widgets.buttons import secondary_button
from src.presentation.widgets.primitives import stretch, title_label
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_a_kiosk import EmployeeHomeScreen
    from src.presentation.shell.kiosk import KioskWindow
    from src.presentation.theme.manager import ThemeManager

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Etiraz formasındakı səbəb siyahısı — domendə kataloq yoxdur, forma sabitdir.
APPEAL_REASONS: tuple[str, ...] = (
    "Cərimə səhv işçiyə yazılıb",
    "Vaxt düzgün qeyd olunmayıb",
    "Üzrlü səbəb var",
    "Digər",
)

BACK_TEXT = "‹ Ana ekran"


class KioskSelfServiceController:
    """İşçi Ana Ekranının üç keçidini mövcud ekranlara bağlayır."""

    def __init__(
        self,
        context: ApplicationContext,
        actor: Employee,
        *,
        kiosk: KioskWindow,
        theme: ThemeManager,
    ) -> None:
        self._context = context
        self._actor = actor
        self._kiosk = kiosk
        self._theme = theme

    def attach(self, home: EmployeeHomeScreen) -> None:
        """Üç keçidi bağlayır.

        BAĞLI METOD DEYİL, `lambda` — SƏBƏBİ HƏYAT MÜDDƏTİDİR.
        Kontrollerə heç kim istinad saxlamır (CLAUDE.md bölmə 6): o,
        siqnala bağladığı bağlamada yaşamalıdır. `connect(self._open_tasks)`
        yazsaydıq, PySide6 qəbuledicini zəif tutur və kontroller ilk zibil
        yığımında ölürdü — düymələr yenidən SƏSSİZCƏ işləməz olardı, özü də
        yalnız iş vaxtı, testdə isə dərhal. `lambda` isə `self`-i bağlamada
        güclü saxlayır, yəni kontroller ekranla birlikdə yaşayır və onunla
        birlikdə ölür.
        """
        self._home = home
        # PLW0108 söndürülür: `lambda` QƏSDƏNDİR — yuxarıdakı həyat müddəti
        # izahına bax. "Sadələşdirib" bağlı metoda çevirmək düymələri sükutla
        # öldürər.
        home.tasks_requested.connect(lambda: self._open_tasks())  # noqa: PLW0108
        home.rewards_requested.connect(lambda: self._open_points())  # noqa: PLW0108
        home.appeal_requested.connect(lambda: self._open_fines())  # noqa: PLW0108

    # ------------------------------- sarğı ----------------------------------- #

    def _framed(self, title: str, screen: QWidget) -> QWidget:
        """Ekranı başlıq + «geri» düyməsi ilə bükür."""
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(
            metrics.CONTENT_PADDING_H,
            metrics.CONTENT_PADDING_V,
            metrics.CONTENT_PADDING_H,
            metrics.CONTENT_PADDING_V,
        )
        layout.setSpacing(metrics.CARD_SPACING)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)
        back = secondary_button(BACK_TEXT)
        back.clicked.connect(lambda: self._kiosk.set_content(self._home))
        header_layout.addWidget(back)
        header_layout.addWidget(title_label(title))
        header_layout.addWidget(stretch())
        layout.addWidget(header)
        layout.addWidget(screen)
        return host

    def _show(self, title: str, screen: QWidget) -> None:
        self._kiosk.set_content(self._framed(title, screen))

    # ------------------------------ tapşırıqlar ------------------------------- #

    def _open_tasks(self) -> None:
        """İşçinin ÖZ açıq tapşırıqları.

        `screen_data._tasks` İŞLƏDİLMİR: o, tenant üzrə «təsdiq gözləyən» və
        «gecikmiş» tapşırıqları göstərir, yəni İDARƏÇİ görünüşüdür. İşçiyə
        başqalarının tapşırıqlarını göstərmək həm mənasız, həm də məlumat
        sızmasıdır — ona görə burada `list_for_assignee` oxunur.
        """
        from src.presentation.screens.group_f import TasksScreen  # noqa: PLC0415

        screen = TasksScreen(self._theme)
        self._show("Tapşırıqlarım", screen)
        rows = self._read(screen, self._tasks_rows)
        if rows is None:
            return
        screen.set_summary(f"{len(rows)} açıq tapşırığınız var")
        screen.set_tasks("open", rows)

    def _tasks_rows(self, session: Session) -> list[dict[str, str]]:
        tasks = session.uow.repository("tasks").list_for_assignee(self._actor.id, open_only=True)
        return [
            {
                "title": task.title,
                "assignee": self._actor.full_name,
                "deadline": task.deadline.strftime("%d.%m %H:%M") if task.deadline else "",
                "task_id": str(task.id),
            }
            for task in tasks
        ]

    # -------------------------------- xallar ---------------------------------- #

    def _open_points(self) -> None:
        """Öz xal balansı — MÖVCUD oxu yolu təkrar işlədilir.

        `ScreenDataBinder` aktoru konstruktordan alır, yəni eyni kod kiosk
        işçisi üçün də düzgün işləyir. Oxu məntiqini burada təkrar yazsaydıq,
        balans düsturu iki yerdə qalar və biri dəyişəndə digəri arxada
        qalardı (bax `screen_data._sales_points` başlığı).
        """
        from src.presentation.controllers.screen_data import ScreenDataBinder  # noqa: PLC0415
        from src.presentation.screens.group_f import SalesPointsScreen  # noqa: PLC0415

        screen = SalesPointsScreen(self._theme)
        self._show("Xallarım", screen)
        try:
            ScreenDataBinder(self._context, self._actor).populate("sales_points", screen)
        except KompasOSError as exc:
            self._report(screen, "Xal balansı oxuna bilmədi", exc)

    # ------------------------------ cərimələr --------------------------------- #

    def _open_fines(self) -> None:
        """«Cərimələrim» — tam tarixçə və etiraz forması (bölmə 3)."""
        from src.presentation.screens.group_f import FineAppealScreen  # noqa: PLC0415

        screen = FineAppealScreen(self._theme, reasons=list(APPEAL_REASONS))
        screen.appeal_submitted.connect(lambda payload: self._submit_appeal(screen, payload))
        self._show("Cərimələrim", screen)
        data = self._read(screen, self._fine_rows)
        if data is None:
            return
        fines, open_appeals, month_total = data
        screen.set_summary(month_total=month_total, open_appeals=open_appeals)
        screen.set_history(fines)

    def _fine_rows(self, session: Session) -> tuple[list[dict[str, str]], int, str]:
        """Cari ayın öz cərimələri + açıq etirazlar.

        Cərimə NÖVÜ `_fine_type_name` ilə oxunur, `fine_type_id` ilə deyil:
        işçiyə UUID göstərmək mənasızdır və eyni ad çözümü artıq etiraz
        qutusunda işlədilir — iki yerdə ayrı yazsaydıq, biri `name_az`
        sütununu, digəri `name`-i oxumağa davam edərdi (bax `screen_data`
        şərhindəki həmin qüsur).
        """
        from src.presentation.controllers.screen_data import _fine_type_name  # noqa: PLC0415

        now = datetime.now(UTC)
        fines = session.manual_fines.my_fines(employee=self._actor, year=now.year, month=now.month)
        appeals = session.fine_appeals.my_appeals(self._actor)
        open_fines = {str(appeal.fine_id) for appeal in appeals if appeal.status.is_open}
        rows = [
            {
                "fine_id": str(fine.id),
                "type": _fine_type_name(session, fine.id),
                "meta": fine.issued_at.strftime("%d.%m.%Y %H:%M"),
                "amount": f"{fine.amount.amount} ₼",
                "status": "Etiraz baxılır" if str(fine.id) in open_fines else "Təsdiqlənib",
            }
            for fine in fines
        ]
        total = sum((fine.amount.amount for fine in fines), start=Decimal(0))
        return rows, len(open_fines), f"{total} ₼"

    def _submit_appeal(self, screen: Any, payload: dict[str, str]) -> None:
        """Etirazı `FineAppealUseCase.submit`-ə ötürür.

        SƏBƏB İLƏ İZAH BİRLƏŞDİRİLİR: domendə tək `reason` sahəsi var və o,
        minimum uzunluq yoxlamasından keçir. İkisini birləşdirmək heç bir
        məlumatı itirmir; yalnız izahı göndərsəydik, işçinin seçdiyi kateqoriya
        (təsdiqləyicinin ilk oxuduğu sətir) itərdi.

        SƏNƏD ƏLAVƏSİ HƏLƏ GÖNDƏRİLMİR və bu, SÜKUTLA buraxılmır: domendə
        (`FineAppeal`) sənəd anlayışı ümumiyyətlə yoxdur — cədvəl sütunu,
        saxlama yolu və audit qaydası tələb edir, yəni məhsul qərarıdır.
        İşçiyə açıq deyilir ki, faylı ayrıca təqdim etməlidir; əks halda o,
        sübutunun göndərildiyini sanardı.
        """
        reason = " — ".join(
            part for part in (payload.get("reason", ""), payload.get("explanation", "")) if part
        )
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.fine_appeals.submit(
                    tenant_id=session.tenant_id,
                    employee=self._actor,
                    fine_id=FineId(UUID(str(payload["fine_id"]))),
                    reason=reason,
                )
                session.commit()
        except KompasOSError as exc:
            self._report(screen, "Etiraz göndərilə bilmədi", exc)
            return

        if payload.get("document"):
            screen.show_error(
                title="Etiraz qeydə alındı — sənəd GÖNDƏRİLMƏDİ",
                message=(
                    "Etirazınız yazıldı, lakin əlavə etdiyiniz sənəd hələ "
                    "sistemə yüklənmir. Onu HR bölməsinə ayrıca təqdim edin."
                ),
                primary_text="Başa düşdüm",
                # Düymə əvvəl HEÇ NƏYƏ bağlı deyildi (UI-R4-01): işçi onu
                # basırdı və kiosk xəta ekranında qalırdı. Təsdiq edilən mesaj
                # məhz «etiraz yazıldı» olduğu üçün davamı sənədsiz axının
                # davamı ilə EYNİDİR — cərimə siyahısına qayıtmaq.
                on_retry=self._open_fines,
            )
            return
        self._open_fines()

    # ------------------------------ köməkçilər -------------------------------- #

    def _read(self, screen: Any, reader: Any) -> Any:
        """Sessiya açır, oxuyur, xətanı EKRANDA göstərir — sükutla udmur.

        Ekran oxumadan ƏVVƏL göstərilir: xəta halında istifadəçi boş kioskda
        deyil, səbəbi yazılmış ekranda qalır və «geri» düyməsi əlindədir.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                return reader(session)
        except KompasOSError as exc:
            self._report(screen, "Məlumat oxuna bilmədi", exc)
            return None

    def _report(self, screen: Any, title: str, exc: KompasOSError) -> None:
        _error_log.exception("KIOSK_SELF_SERVICE_FAILED", extra={"error": str(exc)})
        screen.show_error(
            title=title,
            message=getattr(exc, "user_message", "Yenidən cəhd edin."),
        )


__all__ = ["APPEAL_REASONS", "BACK_TEXT", "KioskSelfServiceController"]
