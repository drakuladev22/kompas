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

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import ceil
from typing import TYPE_CHECKING, Any
from uuid import UUID

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from src.domain.entities.task import TaskSource, TaskStatus
from src.domain.value_objects.identifiers import FineId, TaskId, new_task_id
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

    def refresh_home_cards(self, session: Session, home: EmployeeHomeScreen) -> None:
        """İşçi Ana Ekranının üç kartını CANLI məlumatla doldurur (DEEP-GAP U5).

        ──────────────────────────────────────────────────────────────────────
        ÜÇ KART HEÇ VAXT DOLDURULMURDU
        ──────────────────────────────────────────────────────────────────────
        `EmployeeHomeScreen.set_tasks`/`set_points`/`set_fines` bütün
        `src/presentation/` boyu YALNIZ `app.py::show_preview_home`-da (dizayn
        nümunəsi) çağırılırdı. Canlı yol yalnız statusu və fasilə seçimlərini
        yeniləyirdi — işçi hər PIN girişində "Açıq Tapşırıqlarım 0", "Xal
        Balansım 0", "Cərimələrim —" görürdü, halbuki real rəqəmlər "Hamısına
        bax →" düymələrinin ARXASINDA onsuz da mövcud idi. Ən ağırı: "Etiraz
        müddəti: N gün qalıb" xəbərdarlığı MƏHZ bu kartda yaşayır və işçi
        sıfır göstərən karta baxmamağa öyrəşirdi.

        SƏLAHİYYƏT YOXLAMASI YOXDUR: hər üç oxu artıq `_tasks_rows`/
        `points_balance_summary`/`_fine_summary` daxilində "işçinin ÖZ"
        şərtinə bağlıdır (bax həmin metodların başlığı) — bura əlavə yoxlama
        qoymaq eyni qaydanı İKİ yerdə saxlayardı.

        `home` PARAMETR KİMİ GƏLİR, `self._home` YOX: bu metod `attach()`
        çağırılmadan da (yəni bağlı düymələr olmadan) TƏK dəfəlik çağırıla
        bilməlidir — çağıran (`app.py::_build_employee_home::refresh`) hər
        yeniləmədə YENİ, İSTİNADI SAXLANMAYAN kontroller yaradır (modul
        başlığındakı «kontrollerə istinad saxlanmır» qaydası ilə eynidir).

        ÇAĞIRAN ÜÇÜNÜ TƏK sessiyada oxuyur (PERF-3, `read_batch`) — burada
        YENİ `context.session()` AÇILMIR, ötürülən `session` təkrar işlədilir.
        """
        from src.presentation.controllers.screen_data import (  # noqa: PLC0415
            points_balance_summary,
        )

        home.set_tasks([task["title"] for task in self._tasks_rows(session)])

        balance, monthly_delta, to_next_reward = points_balance_summary(session, self._actor.id)
        home.set_points(balance, monthly_delta=monthly_delta, to_next_reward=to_next_reward)

        home.set_fines(**self._fine_summary(session))

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
        """İşçinin ÖZ açıq tapşırıqları — VƏ öz-düzəliş sorğusu keçidi.

        `screen_data._tasks` İŞLƏDİLMİR: o, tenant üzrə «təsdiq gözləyən» və
        «gecikmiş» tapşırıqları göstərir, yəni İDARƏÇİ görünüşüdür. İşçiyə
        başqalarının tapşırıqlarını göstərmək həm mənasız, həm də məlumat
        sızmasıdır — ona görə burada `list_for_assignee` oxunur.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ YENİ KART DEYİL, MƏHZ BU EKRAN (`v2backlog.md` Faza 4.2)
        ──────────────────────────────────────────────────────────────────────
        İşçi Ana Ekranı onsuz da altı kartdır (bax `group_a_kiosk.py`) və
        yeddincisi kiosk sürüşdürməsini daha da doldurardı. Öz-düzəliş sorğusu
        isə strukturca elə bir TAPŞIRIQDIR (`TaskSource.EMPLOYEE_SELF_
        CORRECTION`) — nəticəsi bu ekranın «Açıq» sütununda görünür, çünki
        yaradılan kimi `EVIDENCE_SUBMITTED` statusuna keçir (bax `task_
        workflow.py::request_self_correction`) və `list_for_assignee(open_
        only=True)` bu statusu artıq daxil edir. Yəni sorğu göndərəndən
        SONRA işçi onu elə BURADA — öz açıq tapşırıqları arasında — görür,
        rəyi isə mövcud `list_awaiting_review` inbox-undan gedir (YENİ
        marşrutlama ekranı YARADILMIR).

        `show_create_button=False`: «Yeni Tapşırıq» (`TaskWorkflowUseCase.
        assign` — BAŞQASINA tapşırıq vermək) əvvəl BURADA DA görünürdü,
        lakin heç bir kontroller `create_requested`-i dinləmirdi — işçi
        basırdı, heç nə baş vermirdi (bax modul başlığı, "ölü düymə" —
        `show_self_correction_button` ilə EYNİ kateqoriyadan tapıntı).
        """
        from src.presentation.screens.group_f import TasksScreen  # noqa: PLC0415

        screen = TasksScreen(
            self._theme, show_create_button=False, show_self_correction_button=True
        )
        screen.self_correction_requested.connect(lambda: self._open_self_correction(screen))
        screen.withdraw_requested.connect(
            lambda task_id: self._withdraw_self_correction(screen, task_id)
        )
        self._show("Tapşırıqlarım", screen)
        self._refresh_tasks(screen)

    def _refresh_tasks(self, screen: Any) -> None:
        rows = self._read(screen, self._tasks_rows)
        if rows is None:
            return
        screen.set_summary(f"{len(rows)} açıq tapşırığınız var")
        screen.set_tasks("open", rows)

    def _tasks_rows(self, session: Session) -> list[dict[str, str]]:
        tasks = session.uow.repository("tasks").list_for_assignee(self._actor.id, open_only=True)
        return [
            {
                # AÇAR `"id"`-DİR, `"task_id"` YOX: `TaskCard.__init__`
                # `task.get("id", "")` oxuyur (`screen_data.py::_tasks_fetch`
                # şərhindəki EYNİ DEEP-GAP tapıntısı — bu sətir ƏVVƏL
                # `"task_id"` idi və `TaskCard` onu HEÇ VAXT oxumurdu, yəni
                # `withdrawn`/`approved`/`rejected` siqnalları BOŞ sətir
                # yayardı).
                "id": str(task.id),
                "title": task.title,
                "assignee": self._actor.full_name,
                "deadline": task.deadline.strftime("%d.%m %H:%M") if task.deadline else "",
                # `TaskCard` YALNIZ bu açar `"1"` olanda «Geri Çək» düyməsini
                # QURUR (bax `group_f.py::set_tasks` — «görmək = səlahiyyət»
                # bənd 3). `list_for_assignee` YALNIZ işçinin ÖZ sətirlərini
                # qaytardığı üçün göndərən yoxlaması artıqdır; qalan iki şərt
                # (mənbə + status) `withdraw_self_correction`-un ÖZ qapısı
                # ilə EYNİDİR — burada TƏKRARLANIR ki, düymə YALNIZ real
                # imkan olanda görünsün.
                "withdrawable": (
                    "1"
                    if task.source is TaskSource.EMPLOYEE_SELF_CORRECTION
                    and task.status is TaskStatus.EVIDENCE_SUBMITTED
                    else "0"
                ),
            }
            for task in tasks
        ]

    # --------------------------- öz-düzəliş sorğusu --------------------------- #

    def _open_self_correction(self, screen: Any) -> None:
        """«Uyğunsuzluğu İzah Et» dialoqunu açır (`v2backlog.md` Faza 4.2)."""
        from src.presentation.screens.group_f import SelfCorrectionDialog  # noqa: PLC0415

        dialog = SelfCorrectionDialog(self._theme, parent=screen)
        dialog.submitted.connect(lambda payload: self._submit_self_correction(screen, payload))
        dialog.exec()

    def _submit_self_correction(self, screen: Any, payload: dict[str, str]) -> None:
        """`TaskWorkflowUseCase.request_self_correction`-a yazır.

        SUİ-İSTİFADƏ TAVANI XƏTASI BURADA ÖZƏL İŞLƏNMİR: `TaskWorkflowError`
        `user_message`-i artıq "Son N gün ərzində icazə verilən sorğu sayına
        (M) çatmısınız" formasındadır (bax use case başlığı) — `_report`-un
        ümumi yolu bunu OLDUĞU KİMİ göstərir, ikinci mətn YAZMAQ onu TƏKRAR
        edərdi.

        SON TARİX (`deadline`) İSTİFADƏÇİDƏN SORUŞULMUR: sorğu yaradılan kimi
        sübutla (izahat) birlikdə `EVIDENCE_SUBMITTED`-ə keçir (`Task.
        submit_evidence` `request_self_correction`-un ÖZÜNDƏ çağırılır) —
        yəni tapşırıq heç vaxt "gözləyən" statusda qalmır və `deadline`
        eskalasiyaya təsir ETMİR. Sahə yalnız `Task` konstruktorunun məcburi
        arqumentidir, ona görə formal dəyər (indi + 1 gün) kifayətdir —
        `NewTaskDialog`-un DEFOLT son tarixi ilə EYNİ konvensiya.
        """
        deadline = self._context.clock.now() + timedelta(days=1)
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.tasks.request_self_correction(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    title=payload["title"],
                    description=payload["description"],
                    deadline=deadline,
                    task_id=new_task_id(),
                )
                session.commit()
        except KompasOSError as exc:
            _error_log.exception("SELF_CORRECTION_SUBMIT_FAILED", extra={"error": str(exc)})
            self._report(screen, "Sorğu göndərilmədi", exc)
            return
        self._refresh_tasks(screen)

    def _withdraw_self_correction(self, screen: Any, task_id: str) -> None:
        """`TaskWorkflowUseCase.withdraw_self_correction`-a yazır.

        `task_id` ETİBARSIZDIRSA (köhnəlmiş kart) çökmə YOX, ekranda mesaj —
        naxış `controllers/tasks.py::_on_approve`-un EYNİSİdir (QA-13
        tapıntısı, eyni izah): `_parse_task_id` özü loglayır, burada
        TƏKRARLANMIR.
        """
        parsed_id = _parse_task_id(task_id)
        if parsed_id is None:
            screen.show_error(
                title="Sorğu geri çəkilmədi",
                message="Tapşırıq identifikatoru düzgün deyil. Səhifəni yeniləyin.",
            )
            return
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.tasks.withdraw_self_correction(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    task_id=parsed_id,
                )
                session.commit()
        except KompasOSError as exc:
            _error_log.exception("SELF_CORRECTION_WITHDRAW_FAILED", extra={"error": str(exc)})
            self._report(screen, "Sorğu geri çəkilmədi", exc)
            return
        self._refresh_tasks(screen)

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
                # AÇAR `"id"`-DİR, `"fine_id"` YOX (QA-FULL FAZA 3 tapıntısı):
                # `FineAppealScreen.set_history()` sətir düyməsini `fine.get(
                # "id", "")` ilə qurur — köhnə `"fine_id"` açarı HEÇ VAXT
                # oxunmurdu, yəni `fine_id` HƏMİŞƏ boş sətir olurdu və düymə
                # `lambda`-sı işə düşsə belə heç bir cəriməyə bağlanmırdı.
                # `"appealable"` DƏ YOX İDİ: onsuz `set_history` düyməni
                # ÜMUMİYYƏTLƏ çəkmirdi — kiosk-da HEÇ BİR cəriməyə etiraz
                # açıla bilmirdi (bax modul başlığındakı ilkin qüsur, sükutla
                # geri qayıtmışdı).
                "id": str(fine.id),
                "type": _fine_type_name(session, fine.id),
                "meta": fine.issued_at.strftime("%d.%m.%Y %H:%M"),
                "amount": f"{fine.amount.amount} ₼",
                "status": "Etiraz baxılır" if str(fine.id) in open_fines else "Təsdiqlənib",
                # Açıq etirazı olan cərimə YENİDƏN etiraz oluna bilməz —
                # `FineAppealUseCase.submit` onsuz da bunu rədd edərdi, lakin
                # düyməni əvvəlcədən gizlətmək istifadəçini boş yerə forma
                # doldurub rədd cavabı almaqdan qoruyur.
                "appealable": "0" if str(fine.id) in open_fines else "1",
            }
            for fine in fines
        ]
        total = sum((fine.amount.amount for fine in fines), start=Decimal(0))
        return rows, len(open_fines), f"{total} ₼"

    def _fine_summary(self, session: Session) -> dict[str, Any]:
        """«Cərimələrim» kartının QISA görünüşü (bax `_fine_rows` — tam siyahı).

        Kart YALNIZ ən son cərimənin etiraz sayğacını göstərir (bölmə 3):
        "Etiraz müddəti: N gün qalıb" `Fine.appeal_window_closes_at`-dan
        (server-lövbərli, TIME-1) hesablanır — kliyent saatından yox, çünki
        bütün cərimə/gecikmə mexanizmi məhz buna əsaslanır.
        """
        now = datetime.now(UTC)
        fines = session.manual_fines.my_fines(employee=self._actor, year=now.year, month=now.month)
        if not fines:
            return {"count": 0, "total_text": "0 ₼"}

        from src.presentation.controllers.screen_data import _fine_type_name  # noqa: PLC0415

        total = sum((fine.amount.amount for fine in fines), start=Decimal(0))
        latest = max(fines, key=lambda fine: fine.issued_at)
        appeal_days_left: int | None = None
        closes_at = latest.appeal_window_closes_at
        if closes_at is not None:
            remaining = (closes_at - now).total_seconds()
            if remaining > 0:
                # Yuvarlaqlaşdırma YUXARI gedir (`ceil`): pəncərəyə 30 dəqiqə
                # qalanda "0 gün qalıb" göstərmək işçini "hüquq bitib" zənn
                # etdirərdi, halbuki pəncərə HƏLƏ AÇIQDIR.
                appeal_days_left = ceil(remaining / 86400)
        return {
            "count": len(fines),
            "total_text": f"{total} ₼",
            "latest": (
                f"{_fine_type_name(session, latest.id)} — {latest.issued_at.strftime('%d.%m.%Y')}"
            ),
            "appeal_days_left": appeal_days_left,
        }

    def _submit_appeal(self, screen: Any, payload: dict[str, str]) -> None:
        """Etirazı `FineAppealUseCase.submit`-ə ötürür.

        SƏBƏB İLƏ İZAH BİRLƏŞDİRİLİR: domendə tək `reason` sahəsi var və o,
        minimum uzunluq yoxlamasından keçir. İkisini birləşdirmək heç bir
        məlumatı itirmir; yalnız izahı göndərsəydik, işçinin seçdiyi kateqoriya
        (təsdiqləyicinin ilk oxuduğu sətir) itərdi.

        ──────────────────────────────────────────────────────────────────────
        SƏNƏD ARTIQ HƏQİQƏTƏN GÖNDƏRİLİR (DEEP-GAP UX-4)
        ──────────────────────────────────────────────────────────────────────
        ƏVVƏL: sahə vardı, fayl `payload`-a düşürdü, heç yerə yüklənmirdi —
        istifadəçiyə açıq mesaj göstərilirdi («HR-ə ayrıca təqdim edin»), yəni
        sükut yox idi, LAKİN interfeys yerinə yetirmədiyi bir şeyi VƏD EDİRDİ.

        İNDİ: `fine_appeals.document_ref` sütunu (miqrasiya 083),
        `UploadOwnerType.FINE_APPEAL` və `FineAppeal.document_reference`
        mövcuddur — fayl MÖVCUD sübut növbəsindən keçir (spool, backoff,
        `REJECTED` ayrımı orada onsuz da həll olunub) və istinad yükləmədən
        SONRA geri-çağırışla sütuna yazılır (`composition.py::_attach_evidence`).

        SIRA MƏCBURİDİR — ƏVVƏLCƏ ETİRAZ, SONRA FAYL: növbə sətri sahibin
        İD-sini tələb edir (`owner_id = fine_appeals.id`) və o, yalnız etiraz
        yazıldıqdan sonra mövcuddur. Tərsinə etsəydik, sahibsiz sətir növbədə
        qalardı. Cərimə formasında (`fine_entry.py`) sıra ƏKSİNƏDİR, çünki
        orada İD (`new_fine_id()`) yazıdan ƏVVƏL yaradılır və sübut cərimənin
        ÖZ şərtidir — burada isə sənəd İSTƏYƏ BAĞLIDIR.

        SƏNƏD YÜKLƏNMƏSƏ ETİRAZ QALIR: fayl oxunmadıqda və ya növbə onu rədd
        etdikdə etiraz GERİ QAYTARILMIR — hüquq artıq qeydə alınıb və onu
        texniki səbəbə görə ləğv etmək işçini pəncərəsiz qoyardı (72 saat
        işləyir). İşçiyə isə NƏYİN olmadığı açıq deyilir.
        """
        reason = " — ".join(
            part for part in (payload.get("reason", ""), payload.get("explanation", "")) if part
        )
        try:
            with self._context.session(user_id=self._actor.id) as session:
                appeal = session.fine_appeals.submit(
                    tenant_id=session.tenant_id,
                    employee=self._actor,
                    fine_id=FineId(UUID(str(payload["fine_id"]))),
                    reason=reason,
                )
                session.commit()
        except KompasOSError as exc:
            self._report(screen, "Etiraz göndərilə bilmədi", exc)
            return

        document_path = str(payload.get("document", "")).strip()
        if document_path:
            failure = self._queue_appeal_document(appeal, document_path)
            if failure:
                screen.show_error(
                    title="Etiraz qeydə alındı — sənəd GÖNDƏRİLMƏDİ",
                    message=failure,
                    primary_text="Başa düşdüm",
                    # Düymə əvvəl HEÇ NƏYƏ bağlı deyildi (UI-R4-01): işçi onu
                    # basırdı və kiosk xəta ekranında qalırdı. Təsdiq edilən
                    # mesaj «etiraz yazıldı» olduğu üçün davamı sənədsiz axının
                    # davamı ilə EYNİDİR — cərimə siyahısına qayıtmaq.
                    on_retry=self._open_fines,
                )
                return
        self._open_fines()

    def _queue_appeal_document(self, appeal: Any, document_path: str) -> str:
        """Sənədi sübut növbəsinə qoyur — qaytarır: BOŞ sətir = uğur (UX-4).

        Xəta MƏTNLƏ qaytarılır, istisna ilə YOX: bu nöqtədə etiraz ARTIQ
        yazılıb və commit olunub. İstisna atsaydıq, çağıran tərəf «etiraz
        göndərilmədi» mesajı göstərərdi — halbuki göndərilib, yalnız sənəd
        çatmayıb. İki fərqli fakt iki fərqli mesaj tələb edir.

        MAĞAZA sətrin YERLƏŞMƏ açarıdır (Drive qovluq strukturu) — işçinin öz
        mağazası götürülür; təyin edilməyibsə cərimənin mağazası ilə əvəz
        edilmir, sənəd növbəyə DÜŞMÜR və səbəb deyilir, çünki səhv qovluğa
        düşən sübut sonradan tapılmır.
        """
        from pathlib import Path  # noqa: PLC0415

        from src.infrastructure.storage.upload_queue import UploadOwnerType  # noqa: PLC0415

        store_id = getattr(self._actor, "store_id", None)
        if store_id is None:
            _error_log.warning("APPEAL_DOCUMENT_NO_STORE", extra={"appeal_id": str(appeal.id)})
            return (
                "Etirazınız yazıldı, lakin sənəd göndərilmədi: hesabınıza mağaza "
                "təyin edilməyib. Sənədi HR bölməsinə ayrıca təqdim edin."
            )

        document = Path(document_path)
        try:
            content = document.read_bytes()
        except OSError:
            _error_log.warning("APPEAL_DOCUMENT_UNREADABLE", extra={"path": document_path})
            return (
                "Etirazınız yazıldı, lakin seçilmiş sənəd faylı açıla bilmədi. "
                "Faylı yenidən seçib «Sənəd əlavə et» ilə göndərin."
            )

        try:
            self._context.evidence_queue().enqueue(
                tenant_id=str(self._context.tenant_id),
                owner_type=UploadOwnerType.FINE_APPEAL,
                owner_id=str(appeal.id),
                store_id=store_id,
                filename=document.name,
                content=content,
                taken_at=self._context.clock.now(),
            )
        except Exception as exc:
            # Növbə YARARSIZ faylı ÖZÜ rədd edir (format/ölçü — SEC-018) və
            # səbəbi istisnada daşıyır; şəbəkə/disk xətası da bura düşür.
            # Hər ikisində etiraz TOXUNULMAZ qalır.
            _error_log.warning(
                "APPEAL_DOCUMENT_ENQUEUE_FAILED",
                extra={"appeal_id": str(appeal.id)},
                exc_info=True,
            )
            reason = getattr(exc, "user_message", str(exc))
            return f"Etirazınız yazıldı, lakin sənəd qəbul edilmədi: {reason}"

        return ""

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


def _parse_task_id(raw: str) -> TaskId | None:
    """`str` → `TaskId`; yararsız isə `None`.

    `controllers/tasks.py::_parse_task_id`-in EYNİSİdir — ORAYA istinad
    ETMİRİK: o, modulun ÖZ `__all__`-unda deyil (məqsədli daxili köməkçi),
    idxal etsək BAŞQA modulun daxili adına ASILILIQ yaranardı.
    """
    try:
        return TaskId(UUID(raw))
    except ValueError:
        _error_log.error("SELF_CORRECTION_TASK_ID_MALFORMED", extra={"task_id": raw})
        return None


__all__ = ["APPEAL_REASONS", "BACK_TEXT", "KioskSelfServiceController"]
