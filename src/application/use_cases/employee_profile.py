"""İşçi Detal Paneli — giriş nəzarəti (Faza 2.8).

Panel tətbiqin İSTƏNİLƏN yerindən (Cərimələrim, İstifadəçi İdarəetməsi,
Camera Dashboard növbəsi, lider-lövhə, Aylıq Cərimə İcmalı...) açıla bilir.
Məhz buna görə icazə yoxlaması BİR yerdə olmalıdır — hər çağırış nöqtəsində
təkrar yazılsaydı, biri gec-tez unudulardı.

──────────────────────────────────────────────────────────────────────────────
QAYDA
──────────────────────────────────────────────────────────────────────────────
    öz profili                → HƏMİŞƏ açıqdır, flag TƏLƏB OLUNMUR
    başqasının profili        → `can_view_employee_reports` TƏLƏB OLUNUR
    Mağaza_Meneceri           → flag var, LAKİN yalnız ÖZ mağazasının işçiləri
    Kamera_Nəzarətçisi/Satıcı → defolt flag YOXDUR → yalnız özünü görür

──────────────────────────────────────────────────────────────────────────────
NİYƏ UI-DA GİZLƏTMƏK KİFAYƏT DEYİL
──────────────────────────────────────────────────────────────────────────────
`date_of_birth` həssas şəxsi məlumatdır. Yalnız UI-da gizlədilsəydi, panelin
məlumatını gətirən sorğu onu yenə də şəbəkə üzərindən göndərərdi və hər hansı
digər çağırış nöqtəsi (məs. gələcək bir hesabat) onu sızdıra bilərdi. Ona görə
SƏHİFƏ deyil, MƏLUMAT süzülür: `build_view()` icazəsiz sahələri
ÜMUMİYYƏTLƏ doldurmur.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

from src.domain.value_objects.authorization import SystemRole
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import Clock
    from src.domain.value_objects.identifiers import StoreId

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Başqasının profilini açmaq üçün tələb olunan flag (bölmə 3).
VIEW_EMPLOYEE_REPORTS_FLAG = "can_view_employee_reports"

#: Bu rollar flag-ə sahib olsalar belə YALNIZ öz mağazalarını görürlər.
#: `can_fill_daily_attendance` ilə eyni scope modeli.
STORE_SCOPED_ROLES = frozenset({SystemRole.STORE_MANAGER})


class ProfileAccessDeniedError(KompasOSError):
    """İşçi Detal Panelinə giriş rədd edildi."""

    user_message = "Bu işçinin məlumatlarına baxmaq icazəniz yoxdur."


@dataclass(frozen=True)
class EmployeeProfileView:
    """Panelin göstərdiyi məlumat.

    `date_of_birth` HƏSSAS sahədir: icazə yoxdursa `None` gəlir və panel
    həmin sətri ümumiyyətlə göstərmir.
    """

    employee_id: str
    full_name: str
    role_code: str
    role_name_az: str
    store_id: StoreId | None
    profile_photo_url: str | None
    is_active: bool
    hire_date: date | None = None
    date_of_birth: date | None = None
    #: Öz profilinə baxıldıqda `True` — UI "Şəkli dəyiş" düyməsini göstərir.
    is_self: bool = False


class EmployeeProfileAccessUseCase:
    """Panelin açıla bilib-bilməyəcəyini həll edir və məzmunu qurur."""

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    def can_view(self, *, viewer: Employee, subject: Employee) -> bool:
        now = self._clock.now()
        if viewer.id == subject.id:
            return True
        if not viewer.has_permission(VIEW_EMPLOYEE_REPORTS_FLAG, now=now):
            return False
        if viewer.position.effective_system_role in STORE_SCOPED_ROLES:
            # Mağaza meneceri şirkət-üzrə siyahılarda (məs. lider-lövhə)
            # başqa mağazanın işçisinin adını görə bilər — amma onun
            # PROFİLİNİ açmamalıdır.
            return (
                viewer.store_id is not None
                and subject.store_id is not None
                and viewer.store_id == subject.store_id
            )
        return True

    def require_view(self, *, viewer: Employee, subject: Employee) -> None:
        if self.can_view(viewer=viewer, subject=subject):
            return
        _security_log.warning(
            "PROFILE_ACCESS_DENIED",
            extra={
                "viewer_id": str(viewer.id),
                "viewer_role": viewer.position.code,
                "subject_id": str(subject.id),
                "reason": self._denial_reason(viewer, subject),
            },
        )
        raise ProfileAccessDeniedError(
            "İşçi profilinə giriş rədd edildi",
            context={"viewer_id": str(viewer.id), "subject_id": str(subject.id)},
        )

    def build_view(self, *, viewer: Employee, subject: Employee) -> EmployeeProfileView:
        """Paneli qurur. İcazə yoxdursa istisna atır — boş panel qaytarmır."""
        self.require_view(viewer=viewer, subject=subject)
        is_self = viewer.id == subject.id
        return EmployeeProfileView(
            employee_id=str(subject.id),
            full_name=subject.full_name,
            role_code=subject.position.code,
            role_name_az=subject.position.name_az,
            store_id=subject.store_id,
            profile_photo_url=getattr(subject, "profile_photo_url", None),
            is_active=subject.is_active,
            hire_date=getattr(subject, "hire_date", None),
            date_of_birth=subject.date_of_birth,
            is_self=is_self,
        )

    def _denial_reason(self, viewer: Employee, subject: Employee) -> str:
        now = self._clock.now()
        if not viewer.has_permission(VIEW_EMPLOYEE_REPORTS_FLAG, now=now):
            return "MISSING_FLAG"
        return "OUT_OF_STORE_SCOPE"


def visible_employee_ids(
    *, viewer: Employee, candidates: list[Employee], now: datetime
) -> list[str]:
    """Siyahı görünüşlərində hansı adların kliklənə bilən olduğu.

    UI bunu əvvəlcədən bilməlidir: kliklənən, sonra "icazəniz yoxdur"
    deyən ad pis təcrübədir.
    """
    if viewer.has_permission(VIEW_EMPLOYEE_REPORTS_FLAG, now=now):
        if viewer.position.effective_system_role in STORE_SCOPED_ROLES:
            return [
                str(candidate.id)
                for candidate in candidates
                if candidate.id == viewer.id
                or (viewer.store_id is not None and candidate.store_id == viewer.store_id)
            ]
        return [str(candidate.id) for candidate in candidates]
    return [str(candidate.id) for candidate in candidates if candidate.id == viewer.id]


__all__ = [
    "STORE_SCOPED_ROLES",
    "VIEW_EMPLOYEE_REPORTS_FLAG",
    "EmployeeProfileAccessUseCase",
    "EmployeeProfileView",
    "ProfileAccessDeniedError",
    "visible_employee_ids",
]
