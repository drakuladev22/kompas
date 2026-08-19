"""«Yeni İşçi» YAZI yolu — `UsersScreen.create_requested` (Faza 5 boşluğu).

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU MODUL VAR
──────────────────────────────────────────────────────────────────────────────
`UsersScreen`-in "Yeni İşçi" düyməsi `create_requested` yayırdı, lakin heç bir
kontroller onu dinləmirdi — GUI-dan tək-tək işçi yaratmağın YOLU YOX İDİ
(yalnız CSV toplu idxalı işləyirdi). `UserManagementUseCase.create_employee`
isə tam işlək idi; aralarındakı bağlantı bu fayldır.

`controllers/employee_documents.py` ilə EYNİ naxış: heç bir qapı burada
TƏKRARLANMIR — `_assert_may_assign_position`, anti-fraud vəzifə ayrılığı,
`chk_employee_auth` invariantı hamısı `UserManagementUseCase.create_employee`
VƏ `Employee` konstruktorunun içindədir. Kontrollerin yeganə əlavəsi
istisnanın İSTİFADƏÇİYƏ İZAH EDİLMƏSİdir və Qt-spesifik giriş (mağaza/vəzifə
siyahısının dialoqa ötürülməsi, tarix mətninin parçalanması).

──────────────────────────────────────────────────────────────────────────────
XƏTA MODALDIR, `show_error` DEYİL (`fine_appeals.py` ilə EYNİ qərar)
──────────────────────────────────────────────────────────────────────────────
`Screen.show_error()` bütün `UsersScreen` məzmununu (işçi cədvəlini) ƏVƏZ
EDİR. Uğursuz YARADILMA siyahını etibarsız etmir — mövcud işçilər hələ də
düzgündür, admin sadəcə YENİ sətri yaza bilmədi. Ona görə yazı xətası modalla
(`_inform`) deyilir; OXU xətası (mağaza/vəzifə siyahısı, ya da siyahının
YENİDƏN oxunması) isə `show_error`/`ScreenDataBinder` ilə — orada əvəz
ediləcək məzmunun ÖZÜ artıq etibarsızdır.

Sessiya SAXLANMIR (CLAUDE.md §6): hər əməliyyat üçün yeni sessiya açılır və
commit edilir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import UUID

from src.domain.value_objects.credentials import EmailAddress, Username
from src.domain.value_objects.identifiers import PositionId, StoreId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_c import UsersScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Tarix sahələrinin ikisi də EYNİ formatı gözləyir (`date.fromisoformat`) —
#: mesaj burada BİR yerdə saxlanılır ki, ikisi arasında söz fərqi yaranmasın.
DATE_FORMAT_MESSAGE = "Tarixi YYYY-AA-GG formatında yazın (məs. 2026-08-19)."


class PositionNotFoundError(KompasOSError):
    """Dialoqda seçilmiş vəzifə yazı anına qədər silinib/deaktiv edilib."""

    user_message = "Seçilmiş vəzifə artıq mövcud deyil. Səhifəni yeniləyin."


@dataclass(frozen=True)
class _ParsedDraft:
    """`NewUserDialog.submitted` sözlüyünün DOMEN TİPLƏRİNƏ çevrilmiş forması.

    Ayrıca dataclass NİYƏ LAZIMDIR: `_create`-in özü təkbaşına parçalama +
    sessiya + yazı apardıqda ruff `PLR0911/0912/0915` (həddindən artıq qayıdış/
    budaq/sətir) ilə rədd edirdi — səbəb hər sahənin AYRICA yoxlanılmasıdır
    (formatı yanlış olan tarix, mövcud olmayan mağaza/vəzifə ID-si, hamısı
    fərqli mesajla). Parçalama `_parse_payload`-a köçürülüb ki, `_create`
    yalnız "parçalandımı? → sessiyaya yaz" iki addımını görsün.
    """

    first_name: str
    last_name: str
    position_id: PositionId
    store_id: StoreId | None
    username: Username | None
    notification_email: EmailAddress | None
    hire_date: date | None
    date_of_birth: date | None
    camera_store_ids: tuple[StoreId, ...]
    password: str | None
    pin: str | None


class UserAdminController:
    """`UsersScreen`-in "Yeni İşçi" düyməsini `UserManagementUseCase.create_employee`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: UsersScreen) -> None:
        screen.create_requested.connect(lambda: self._open_dialog(screen))

    # -------------------------------- açılış ---------------------------------- #

    def _open_dialog(self, screen: UsersScreen) -> None:
        """Dialoqu mağaza/vəzifə siyahısı ilə açır (`announcements.py::_on_create` naxışı)."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                stores = _store_choices(session)
                positions = _position_choices(session)
        except Exception:
            _error_log.exception("USER_ADMIN_DIALOG_DATA_FAILED")
            screen.show_error(
                title="Forma açılmadı",
                message="Mağaza/vəzifə siyahısı oxunmadı. Yenidən cəhd edin.",
            )
            return
        if not positions:
            # Yeni kirayəçi sxemi/miqrasiyaları hələ 7 defolt rolu SEED
            # etməyibsə (və ya hamısı deaktiv edilibsə) dialoq boş açılardı —
            # admin "vəzifə" xanasında HEÇ NƏ görmədən "Yarat" basardı.
            screen.show_error(
                title="Forma açılmadı",
                message="Heç bir vəzifə tapılmadı — əvvəlcə İcazə Matrisindən rol yaradın.",
            )
            return

        from src.presentation.screens.group_c import NewUserDialog  # noqa: PLC0415

        dialog = NewUserDialog(screen.theme, stores=stores, positions=positions, parent=screen)
        dialog.submitted.connect(lambda payload: self._create(screen, payload))
        dialog.exec()

    # -------------------------------- yazı yolu -------------------------------- #

    def _create(self, screen: UsersScreen, payload: object) -> None:
        if not isinstance(payload, dict):  # pragma: no cover - tip qoruyucusu
            return
        parsed = _parse_payload(screen, payload)
        if parsed is None:
            return  # Səbəb `_parse_payload` daxilində ARTIQ göstərilib.

        try:
            with self._context.session(user_id=self._actor.id) as session:
                self._write(session, parsed)
                session.commit()
        except KompasOSError as error:
            _inform(screen, "İşçi yaradılmadı", error.user_message)
            return
        except Exception:
            _error_log.exception("USER_ADMIN_CREATE_FAILED")
            _inform(screen, "İşçi yaradılmadı", "Dəyişiklik saxlanmadı. Yenidən cəhd edin.")
            return

        # Şifrə/PIN heç vaxt uğur mesajına DÜŞMÜR — ekranda göstərmək və ya
        # log-a yazmaq SEC-013/qərar SEC-016-nın pozuntusudur (modul başlığı).
        self.refresh(screen)

    def _write(self, session: Session, parsed: _ParsedDraft) -> None:
        """Sessiya İÇİNDƏ icra olunur — `Position` sorğusu buradan asılıdır.

        `PositionNotFoundError` `KompasOSError`-dur, ona görə `_create`-dəki
        ÜMUMİ `except KompasOSError` onu da tutur — ayrıca budaq lazım deyil.
        """
        from src.application.use_cases.user_management import EmployeeDraft  # noqa: PLC0415
        from src.domain.value_objects.identifiers import new_employee_id  # noqa: PLC0415

        position = session.uow.positions.get(parsed.position_id)
        if position is None:
            raise PositionNotFoundError(
                "Seçilmiş vəzifə artıq mövcud deyil",
                user_message="Seçilmiş vəzifə artıq mövcud deyil. Səhifəni yeniləyin.",
            )

        draft = EmployeeDraft(
            first_name=parsed.first_name,
            last_name=parsed.last_name,
            position=position,
            store_id=parsed.store_id,
            username=parsed.username,
            notification_email=parsed.notification_email,
            hire_date=parsed.hire_date,
            date_of_birth=parsed.date_of_birth,
            camera_store_ids=tuple(parsed.camera_store_ids),
        )
        session.users.create_employee(
            tenant_id=session.tenant_id,
            actor=self._actor,
            employee_id=new_employee_id(),
            draft=draft,
            initial_password=parsed.password,
            initial_pin=parsed.pin,
        )

    # -------------------------------- oxuma ---------------------------------- #

    def refresh(self, screen: UsersScreen) -> None:
        """İşçi cədvəlini `screen_data.py` ilə EYNİ yoldan yenidən oxuyur."""
        from src.presentation.controllers.screen_data import ScreenDataBinder  # noqa: PLC0415

        try:
            ScreenDataBinder(self._context, self._actor).populate("users", screen)
        except KompasOSError as exc:
            _error_log.exception("USER_ADMIN_REFRESH_FAILED", extra={"error": str(exc)})
            screen.show_error(
                title="İşçi siyahısı oxunmadı",
                message=exc.user_message,
                on_retry=lambda: self.refresh(screen),
            )


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _parse_payload(screen: UsersScreen, payload: dict[str, Any]) -> _ParsedDraft | None:
    """Xam sözlüyü domen tiplərinə çevirir; uğursuzluqda `None` (mesaj ARTIQ göstərilib).

    Sessiya BURADA açılmır — format səhvləri (yanlış tarix, yararsız UUID)
    bazaya toxunmadan qaytarılmalıdır (`fine_appeals.py::_decide`-dakı EYNİ
    qərar: sessiya AÇILMADAN rədd edilən yol yazılan mətni İTİRMİR).
    """
    dates = _parse_dates(screen, payload)
    if dates is None:
        return None
    hire_date, date_of_birth = dates

    try:
        position_id = PositionId(UUID(str(payload.get("position_id", ""))))
    except ValueError:
        _inform(screen, "İşçi yaradılmadı", "Seçilmiş vəzifə düzgün deyil. Səhifəni yeniləyin.")
        return None

    store_id, store_ok = _parse_optional_store_id(str(payload.get("store_id", "")))
    if not store_ok:
        _inform(screen, "İşçi yaradılmadı", "Seçilmiş mağaza düzgün deyil.")
        return None

    camera_store_ids: list[StoreId] = []
    try:
        for raw in payload.get("camera_store_ids") or []:
            camera_store_ids.append(StoreId(UUID(str(raw))))
    except ValueError:
        _inform(screen, "İşçi yaradılmadı", "Seçilmiş mağazalardan biri düzgün deyil.")
        return None

    username_text = str(payload.get("username", "")).strip()
    email_text = str(payload.get("notification_email", "")).strip()
    try:
        username = Username(username_text) if username_text else None
        notification_email = EmailAddress(email_text) if email_text else None
    except KompasOSError as error:
        _inform(screen, "İşçi yaradılmadı", error.user_message)
        return None

    return _ParsedDraft(
        first_name=str(payload.get("first_name", "")),
        last_name=str(payload.get("last_name", "")),
        position_id=position_id,
        store_id=store_id,
        username=username,
        notification_email=notification_email,
        hire_date=hire_date,
        date_of_birth=date_of_birth,
        camera_store_ids=tuple(camera_store_ids),
        password=str(payload.get("password", "")).strip() or None,
        pin=str(payload.get("pin", "")).strip() or None,
    )


def _parse_dates(
    screen: UsersScreen, payload: dict[str, Any]
) -> tuple[date | None, date | None] | None:
    """Hər iki tarix sahəsini yoxlayır — `_parse_payload`-un qayıdış sayını azaldır.

    (Ruff `PLR0911`: hər sahə üçün AYRICA `return None` yazsaydıq, funksiya
    həddi keçirdi. İki tarix eyni formatı bölüşdüyü üçün BİR yerə köçürüldü.)
    """
    hire_date, hire_ok = _parse_optional_date(str(payload.get("hire_date", "")))
    if not hire_ok:
        _inform(screen, "İşçi yaradılmadı", f"İşə başlama tarixi — {DATE_FORMAT_MESSAGE}")
        return None
    date_of_birth, dob_ok = _parse_optional_date(str(payload.get("date_of_birth", "")))
    if not dob_ok:
        _inform(screen, "İşçi yaradılmadı", f"Doğum tarixi — {DATE_FORMAT_MESSAGE}")
        return None
    return hire_date, date_of_birth


def _parse_optional_store_id(text: str) -> tuple[StoreId | None, bool]:
    """`(dəyər, etibarlıdır?)` — `_parse_optional_date` ilə EYNİ naxış.

    `None` "mağaza seçilməyib" (qanuni hal — `EmployeeDraft.store_id` boş
    ola bilər) DEMƏKDİR, yararsız UUID isə `ok=False` ilə AYRILIR.
    """
    cleaned = text.strip()
    if not cleaned:
        return None, True
    try:
        return StoreId(UUID(cleaned)), True
    except ValueError:
        return None, False


def _store_choices(session: Session) -> list[tuple[str, str]]:
    """Aktiv mağazalar — `announcements.py::_store_choices` ilə EYNİ sorğu.

    `tenant_id` şərti İKİNCİ TƏCRİD QATIDIR (CLAUDE.md §6). Kontrollerlər
    arasında import bağı qurmaq əvəzinə hər biri öz nüsxəsini saxlayır
    (`employee_documents.py` başlığındakı `_find_employee_id` təkrarı ilə
    eyni qərar).
    """
    rows = session.uow.connection.execute(
        "SELECT id, name FROM stores WHERE tenant_id = %s AND is_active ORDER BY name",
        (session.tenant_id,),
    ).fetchall()
    return [(str(row["id"]), str(row["name"])) for row in rows]


def _position_choices(session: Session) -> list[tuple[str, str, bool]]:
    """Aktiv vəzifələr — `(id, ad, kamera-tipli?)`.

    `PositionManagementUseCase.list_roles()` İŞLƏDİLMİR: o, `can_manage_
    positions` tələb edir və "İcazə Matrisi"-ni redaktə etmək hüququdur —
    "Yeni İşçi" formasının vəzifə açılan siyahısı isə `can_manage_employees`
    daşıyan HƏR admin üçün işləməlidir. İkisini qarışdırsaq, işçi yarada bilən
    admin (məs. HR_Admin) rol siyahısını GÖRMƏZDİ (bax `PositionManagementUseCase.
    list_roles` başlığı — "GÖRMƏK = SƏLAHİYYƏT" YALNIZ rol-idarəetməsinə aiddir,
    işçi-yaratmaya YOX). Faktiki icazə qapısı `create_employee`-in özündədir
    (`_assert_may_assign_position`) — bu siyahı YALNIZ göstərişdir.
    """
    positions = session.uow.positions.list_for_tenant(session.tenant_id)
    return [
        (str(position.id), position.name_az, position.is_camera_type)
        for position in positions
        if position.is_active
    ]


def _parse_optional_date(text: str) -> tuple[date | None, bool]:
    """`(dəyər, etibarlıdır?)` — boş mətn `(None, True)`-dur (sahə İSTƏYƏ bağlıdır)."""
    cleaned = text.strip()
    if not cleaned:
        return None, True
    try:
        return date.fromisoformat(cleaned), True
    except ValueError:
        return None, False


def _inform(screen: Any, title: str, message: str) -> None:
    """İzah pəncərəsi — siyahını BOŞALTMADAN (`fine_appeals.py::_inform` ilə EYNİ naxış)."""
    from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

    box = QMessageBox(screen)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(message)
    box.exec()


__all__ = ["DATE_FORMAT_MESSAGE", "UserAdminController"]
