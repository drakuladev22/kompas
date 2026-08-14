"""Shift Matrix-in İŞ REJİMİ SEÇİCİSİ (kompas1.md Faza 7).

──────────────────────────────────────────────────────────────────────────────
BU KONTROLLER NƏ EDİR — VƏ DAHA VACİBİ, NƏ ETMİR
──────────────────────────────────────────────────────────────────────────────
EDİR: Növbə Planlama ekranının toolbar-ındakı dropdown-u CANLI `work_modes`
kataloqundan doldurur və seçilmiş rejimin GÜNDƏLİK NORMA SAATINI nişanda
göstərir.

ETMİR: heç bir növbə təyin etmir, heç bir sətir yazmır. Təyinetmə yolu
`ShiftPlanningUseCase.assign_work_day` → `apply_assignment`-dır və Faza 7-də
ona BİR SƏTİR belə əlavə edilməyib. Faza 6-da qoyulmuş intizam (o metoda
yalnız ƏLAVƏ edilir, heç nə silinmir) burada da saxlanılır: ən təhlükəsiz
dəyişiklik — ümumiyyətlə etməmək.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI KONTROLLER, `ShiftMatrixOpenShiftController`-ə ƏLAVƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
Həmin sinif AÇIQ NÖVBƏ BAZARI kartının (#16) sahibidir və onun yazı yolu var
(elan et / ləğv et). İş rejimi seçicisi isə YALNIZ OXUYAN, tamamilə ayrı bir
funksiyadır; birləşdirilsəydi, elan kartının hər yenilənməsi kataloqu da
təkrar oxuyardı və iki funksiyanın nasazlıqları bir-birini gizlədərdi.

İKİ KONTROLLERİN BİR EKRANA BAĞLANMASI mövcud naxışdır — `users` ekranı da
`UsersPOSThresholdController` + `UsersEmployeeDocumentController` alır
(`app.py::_attach_users_screen`).

──────────────────────────────────────────────────────────────────────────────
NORMA SAAT NİYƏ BURADA HESABLANMIR
──────────────────────────────────────────────────────────────────────────────
Nişandakı rəqəm `domain/work_norm.daily_norm_hours()`-dan gəlir — hesabatın
norma saatını toplayan EYNİ funksiyadan. Ekranda ayrıca `end − start`
yazılsaydı, gecə növbəsi (22:00–06:00) mənfi çıxardı və daha pisi: hüquqi
tavan (`OVERTIME_DAILY_NORM_HOURS`) tətbiq olunmadığı üçün GUI 12 saat, hesabat
isə 8 saat göstərərdi. İki rəqəmin sükutla fərqlənməsi Faza 7-nin qadağan
etdiyi əsas haldır.

SESSİYA SAXLANILMIR (CLAUDE.md §6): kataloq bir dəfə oxunur, sessiya bağlanır.
Panel saatlarla açıq qala bilər.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.work_norm import FALLBACK_LEGAL_DAILY_NORM_HOURS, daily_norm_hours
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.value_objects.catalogs import WorkMode
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_c import ShiftPlanningScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Rejim seçilməyəndə (kataloq boşdur) göstərilən nişan.
_EMPTY_LABEL = "İş Rejimi: seçilməyib"


class ShiftMatrixWorkModeController:
    """Növbə Planlama ekranının İş Rejimi dropdown-u (yalnız oxu)."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor
        #: `work_mode_id` → gündəlik norma nişanı. Seçim dəyişəndə kataloq
        #: YENİDƏN oxunmur: hər dəfə sessiya açmaq dropdown-u ləng edərdi və
        #: kataloq bu ekran açıq ikən praktiki olaraq dəyişmir.
        self._labels: dict[str, str] = {}

    def attach(self, screen: ShiftPlanningScreen) -> None:
        screen.work_mode_selected.connect(lambda mode_id: self._on_selected(screen, mode_id))
        self.refresh(screen)

    def refresh(self, screen: ShiftPlanningScreen) -> None:
        """Kataloqu oxuyur və dropdown-u doldurur.

        NASAZLIQ EKRANI ÇÖKDÜRMÜR: kataloq oxunmasa dropdown boş qalır və
        nişan "seçilməyib" olur — matris və açıq növbə kartı işləməyə davam
        edir. Növbə planlaması iş rejimi siyahısından daha vacibdir.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                modes = session.work_modes.list_for_selection(session.tenant_id)
                legal_norm = _legal_daily_norm_hours(session)
        except KompasOSError as error:
            screen.set_work_modes([])
            screen.set_work_mode_norm(_EMPTY_LABEL)
            screen.show_error(title="İş rejimləri oxunmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("SHIFT_MATRIX_WORK_MODES_FAILED")
            screen.set_work_modes([])
            screen.set_work_mode_norm(_EMPTY_LABEL)
            return

        choices: list[tuple[str, str]] = []
        self._labels = {}
        for mode in modes:
            if mode.work_mode_id is None:
                continue
            mode_id = str(mode.work_mode_id)
            choices.append((mode_id, f"{mode.name} · {mode.scheduled_start_label()}"))
            self._labels[mode_id] = _norm_label(mode, legal_norm)

        screen.set_work_modes(choices)
        if not choices:
            screen.set_work_mode_norm(_EMPTY_LABEL)

    def _on_selected(self, screen: ShiftPlanningScreen, mode_id: str) -> None:
        screen.set_work_mode_norm(self._labels.get(mode_id, _EMPTY_LABEL))


def _norm_label(mode: WorkMode, legal_norm: Decimal) -> str:
    """Nişan mətni — sıxılma BAŞ VERİRSƏ onu AÇIQ yazır.

    12 saatlıq növbədə hesabata 8 saat düşür; istifadəçi bunu nişanda
    görməsə, hesabatı açanda "saatlarım hara getdi?" sualı ilə qalardı.
    Cavab: qalan hissə aşım jurnalındadır (`overtime_log`).
    """
    applied = daily_norm_hours(mode.schedule, legal_daily_norm_hours=legal_norm)
    if mode.schedule is None:
        return f"İş Rejimi: {mode.name} · norma {applied} saat/gün (sərbəst növbə)"
    label = f"İş Rejimi: {mode.scheduled_start_label()} · norma {applied} saat/gün"
    planned = Decimal(int(mode.schedule.duration.total_seconds())) / Decimal("3600")
    if planned > applied:
        label += f" (plan {planned.normalize()} saat, artıq hissə aşım jurnalında)"
    return label


def _legal_daily_norm_hours(session: Session) -> Decimal:
    """ROOT parametri — `overtime_tracking.py` ilə EYNİ açar.

    Ekranda hardcode ədəd YOXDUR və İKİNCİ açar da yaradılmır: Root gündəlik
    normanı dəyişəndə həm aşım jurnalı, həm bu nişan, həm də davamiyyət
    hesabatı EYNİ ANDA dəyişməlidir.
    """
    raw = session.limits.get_str(
        session.tenant_id,
        SystemLimitKey.OVERTIME_DAILY_NORM_HOURS.value,
        str(FALLBACK_LEGAL_DAILY_NORM_HOURS),
    )
    try:
        value = Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, ValueError, AttributeError):
        return Decimal(DEFAULT_LIMITS[SystemLimitKey.OVERTIME_DAILY_NORM_HOURS])
    return value if value > 0 else Decimal(DEFAULT_LIMITS[SystemLimitKey.OVERTIME_DAILY_NORM_HOURS])


__all__ = ["ShiftMatrixWorkModeController"]
