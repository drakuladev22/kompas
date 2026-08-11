"""Profil ekranının canlı yolu — öz hesabın oxu + ad redaktəsi (bölmə 2, 3).

──────────────────────────────────────────────────────────────────────────────
İSTİFADƏÇİ ADI VƏ E-POÇT YAZI YOLUNA DÜŞMÜR
──────────────────────────────────────────────────────────────────────────────
`ProfileScreen` həmin iki sahəni QƏSDƏN söndürüb (bax sinif docstring-i): hər
ikisi identifikasiya vasitəsidir — istifadəçi adı giriş açarı, e-poçt isə
bərpa kanalıdır; ələ keçirilmiş sessiya onları dəyişə bilsəydi hesabı tamamilə
ötürərdi. Kontroller bu qərarı GÜCLƏNDİRİR: `collected()` onsuz da yalnız
`full_name`/`phone` qaytarır, lakin biz həmin sözlükdən də YALNIZ adı
götürürük — ekran gələcəkdə əlavə sahə qaytarsa belə, yazı yolu genişlənmir.

──────────────────────────────────────────────────────────────────────────────
ŞİFRƏ DƏYİŞİKLİYİ BURADA YARADILMIR
──────────────────────────────────────────────────────────────────────────────
Layihədə özünə-xidmət şifrə dəyişmə axını YOXDUR və bu, sənədləşdirilmiş
qərardır: SEC-016 e-poçt token axınını çıxarıb, `CredentialResetUseCase` və
`UserManagementUseCase.reset_password` isə hər ikisi ÖZÜNƏ tətbiq olunmağı
açıq şəkildə bloklayır ("İstifadəçi öz şifrəsini bu axınla sıfırlaya bilməz")
— sıfırlama daha yüksək və ya bərabər səlahiyyətli BAŞQA adminin işidir.

Ona görə düymə yeni bir yol açmır, mövcud axını İZAH EDİR. Sükutla heç nə
etməmək ən pis variant olardı: istifadəçi düyməni təkrar-təkrar basardı.

──────────────────────────────────────────────────────────────────────────────
HƏR ƏMƏLİYYAT ÖZ SESSİYASINDA
──────────────────────────────────────────────────────────────────────────────
Profil ekranı gün boyu açıq qala bilər; uzun-ömürlü tranzaksiya `employees`
sətrini kilidli saxlayar və həmin işçiyə toxunan hər admin əməliyyatını
bloklayardı.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_g import ProfileScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: `password_note` sahəsində daim görünən izah (bax modul başlığı).
PASSWORD_POLICY_NOTE = (
    "Şifrə dəyişikliyi administrator vasitəsilə aparılır — o, müvəqqəti şifrə "  # noqa: S105
    "təyin edir və siz ilk girişdə onu dəyişirsiniz."
)


class ProfileController:
    """Profil ekranını canlı hesab məlumatına və `users` use case-inə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: ProfileScreen) -> None:
        screen.saved.connect(lambda payload: self._on_saved(screen, payload))
        screen.password_change_requested.connect(lambda: self._on_password(screen))
        screen.photo_change_requested.connect(lambda: self._on_photo(screen))
        screen.close_other_sessions_requested.connect(lambda: self._on_close_sessions(screen))
        self.refresh(screen)

    def refresh(self, screen: ProfileScreen) -> None:
        """Hesab, rol xülasəsi və sessiya tarixçəsini yenidən oxuyur."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                # İşçi BAZADAN yenidən oxunur, `self._actor`-dan yox: ad
                # dəyişikliyindən sonra ekran YAZILAN dəyəri göstərməlidir,
                # login anındakı nüsxəni yox.
                employee = session.uow.employees.get(self._actor.id) or self._actor
                # `require_view` öz profilinə HƏMİŞƏ icazə verir (bax use case),
                # lakin çağırış qalır: qapı bir yerdədir və gələcəkdə profil
                # başqa işçi üçün açılsa eyni yol işləyəcək.
                session.employee_profile.require_view(viewer=self._actor, subject=employee)

                screen.set_account(
                    username=str(employee.username) if employee.username else "—",
                    email=(
                        str(employee.notification_email) if employee.notification_email else "—"
                    ),
                    # TELEFON SÜTUNU YOXDUR: `employees` cədvəlində `phone`
                    # sahəsi mövcud deyil (bax `schema.sql` §6). Ona görə sahə
                    # BOŞ göstərilir və yazı yoluna da düşmür — uydurma dəyər
                    # göstərmək "saxlanıldı" təəssüratı yaradardı.
                    phone="",
                    password_note=PASSWORD_POLICY_NOTE,
                )
                screen.set_role_info(_role_rows(session, employee))
                screen.set_sessions(_session_rows(session, employee))
        except KompasOSError as error:
            screen.show_error(title="Profil açıla bilmədi", message=error.user_message)
        except Exception:
            _error_log.exception("PROFILE_LOAD_FAILED")
            screen.show_error(
                title="Profil açıla bilmədi",
                message="Hesab məlumatı oxuna bilmədi. Yenidən cəhd edin.",
            )

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_saved(self, screen: ProfileScreen, payload: Any) -> None:
        """ "Yadda Saxla" — YALNIZ ad dəyişikliyi yazılır (bax modul başlığı)."""
        raw = payload if isinstance(payload, dict) else {}
        first, last = _split_name(str(raw.get("full_name", "")))
        if not first and not last:
            screen.show_error(
                title="Ad boş ola bilməz",
                message="Ad və soyadı yazın, sonra yenidən yadda saxlayın.",
            )
            self.refresh(screen)
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                employee = session.uow.employees.get(self._actor.id) or self._actor
                session.users.update_employee(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    employee_id=employee.id,
                    draft=_draft_from(employee, first_name=first, last_name=last),
                )
                session.commit()
        except KompasOSError as error:
            # `can_manage_employees` olmayan istifadəçi burada AYDIN səbəb
            # görür. Qapını yumşaltmaq (məs. "öz adına həmişə icazə") YENİ
            # qayda icad etmək olardı — use case nə deyirsə, o qüvvədədir.
            screen.show_error(title="Dəyişiklik saxlanmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("PROFILE_SAVE_FAILED")
            screen.show_error(
                title="Dəyişiklik saxlanmadı",
                message="Məlumat yazılmadı. Yenidən cəhd edin.",
            )
            return

        self.refresh(screen)

    # ---------------------------- izahlı düymələr ---------------------------- #

    def _on_password(self, screen: ProfileScreen) -> None:
        _inform(
            screen,
            "Şifrənin dəyişdirilməsi",
            PASSWORD_POLICY_NOTE + "\n\nAdministratorunuza müraciət edin — o, «İstifadəçilər» "
            "ekranından şifrənizi sıfırlaya bilər.",
        )

    def _on_photo(self, screen: ProfileScreen) -> None:
        """Profil şəkli üçün YÜKLƏMƏ QATI hələ yoxdur.

        `employees.profile_photo_url` sütunu Supabase Storage üçün nəzərdə
        tutulub (bölmə 6), lakin tətbiqdə yalnız CƏRİMƏ SÜBUTU üçün yükləmə
        qatı var (Google Drive, miqrasiya 002) və o, `fines` sətrinə bağlıdır.
        Lokal fayl yolunu URL kimi yazmaq şəkli yalnız BİR kompüterdə görünən
        edərdi — yəni məlumat bazada "var" görünüb praktikada olmazdı.
        """
        _inform(
            screen,
            "Profil şəkli",
            "Profil şəkli üçün yükləmə hələ konfiqurasiya edilməyib. "
            "Şəkli administratorunuz təyin edə bilər.",
        )

    def _on_close_sessions(self, screen: ProfileScreen) -> None:
        """Aktiv sessiyaların sayını göstərir.

        Sessiya sətirlərini LƏĞV ETMİR: ləğv təhlükəsizlik əməliyyatıdır və
        audit tələb edir, tətbiqdə isə `auth_sessions`-a YAZAN tərəf hələ
        yoxdur (giriş axını token buraxmır). Ləğvi burada, use case-dən
        kənarda yazsaydıq, audit izi olmayan bir təhlükəsizlik əməliyyatı
        yaratmış olardıq.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                active = _active_session_count(session, self._actor)
        except Exception:
            _error_log.exception("PROFILE_SESSIONS_FAILED")
            _inform(screen, "Sessiyalar", "Sessiya məlumatı oxuna bilmədi.")
            return

        if active == 0:
            _inform(screen, "Sessiyalar", "Başqa aktiv sessiya yoxdur.")
            return
        _inform(
            screen,
            "Sessiyalar",
            f"{active} aktiv sessiya qeydə alınıb. Onları bağlamaq üçün "
            "administratorunuza müraciət edin.",
        )


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _inform(screen: Any, title: str, message: str) -> None:
    """İzah pəncərəsi — ekranı BOŞALTMADAN.

    `Screen.show_error()` məzmunu tamamilə əvəz edir və bu, izah üçün yanlış
    olardı: istifadəçi profilinə baxmağa davam edə bilməlidir. Modal isə
    yalnız oxunub bağlanır.
    """
    from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

    box = QMessageBox(screen)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle(title)
    box.setText(message)
    box.exec()


def _split_name(full_name: str) -> tuple[str, str]:
    """«Ad Soyad» → («Ad», «Soyad»).

    Çox sözlü adlarda SON söz soyad sayılır: Azərbaycan dilində ikinci ad
    (ata adı) ad hissəsinə daha yaxındır və "Rəşad Əli Məmmədov" halında
    soyad "Məmmədov" olmalıdır.
    """
    parts = full_name.split()
    if not parts:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (" ".join(parts[:-1]), parts[-1])


def _draft_from(employee: Any, *, first_name: str, last_name: str) -> Any:
    """Mövcud işçidən `EmployeeDraft` qurur — YALNIZ ad dəyişir.

    Digər sahələr OLDUĞU KİMİ ötürülür, çünki `update_employee` draft-ı TAM
    əvəzləyici kimi tətbiq edir: boş buraxılan sahə "təmizlə" demək olardı və
    profil ekranı işə qəbul tarixini, mağazanı, doğum tarixini SORUŞMUR.
    """
    from src.application.use_cases.user_management import EmployeeDraft  # noqa: PLC0415

    return EmployeeDraft(
        first_name=first_name,
        last_name=last_name,
        position=employee.position,
        store_id=employee.store_id,
        username=employee.username,
        notification_email=employee.notification_email,
        hire_date=getattr(employee, "hire_date", None),
        date_of_birth=employee.date_of_birth,
        profile_photo_url=None,
        camera_store_ids=tuple(employee.assigned_store_ids),
    )


def _role_rows(session: Session, employee: Any) -> list[tuple[str, str]]:
    """Rol kartındakı sətirlər: aktiv icazə, fərdi istisna, mağaza."""
    from datetime import UTC, datetime  # noqa: PLC0415

    now = datetime.now(UTC)
    catalog = session.uow.repository("permission_flags").list_all()
    active = sum(1 for flag in catalog if employee.has_permission(flag.code, now=now))
    stores = _store_scope_text(session, employee)
    return [
        ("Vəzifə", str(employee.position.name_az)),
        ("Aktiv icazə", f"{active} / {len(catalog)}"),
        ("Fərdi istisna", str(len(employee.overrides))),
        ("Təyin edilmiş mağaza", stores),
    ]


def _store_scope_text(session: Session, employee: Any) -> str:
    """İşçinin gördüyü mağazalar — əsas mağaza + kamera təyinatları."""
    ids = set(employee.assigned_store_ids)
    if employee.store_id is not None:
        ids.add(employee.store_id)
    if not ids:
        return "Təyin edilməyib"

    rows = session.uow.connection.execute(
        "SELECT name FROM stores WHERE tenant_id = %s AND id = ANY(%s) ORDER BY name",
        (session.tenant_id, list(ids)),
    ).fetchall()
    names = [str(row["name"]) for row in rows]
    if not names:
        return "Təyin edilməyib"
    max_listed = 2
    if len(names) <= max_listed:
        return ", ".join(names)
    return f"{names[0]} və daha {len(names) - 1}"


def _session_rows(session: Session, employee: Any) -> list[tuple[str, str, str]]:
    """`auth_sessions` sətirləri — (vaxt, cihaz, vəziyyət).

    Siyahı boş qayıda bilər və bu, XƏTA DEYİL: giriş axını hələ sessiya
    sətri yazmır (bax `_on_close_sessions`). Boş kart "tarixçə yoxdur"
    deməkdir və uydurma sətir göstərməkdən dürüstdür.
    """
    rows = session.uow.connection.execute(
        """
        SELECT issued_at, machine_name, revoked_at, expires_at
          FROM auth_sessions
         WHERE tenant_id = %s AND user_id = %s
         ORDER BY issued_at DESC
         LIMIT 10
        """,
        (session.tenant_id, employee.id),
    ).fetchall()

    from datetime import UTC, datetime  # noqa: PLC0415

    now = datetime.now(UTC)
    result: list[tuple[str, str, str]] = []
    for row in rows:
        issued = row["issued_at"]
        alive = row["revoked_at"] is None and row["expires_at"] > now
        result.append(
            (
                f"{issued:%d.%m %H:%M}" if issued else "—",
                str(row["machine_name"] or "Naməlum cihaz"),
                # Mətn `ProfileScreen.set_sessions`-in tanıdığı dəyərdir:
                # yalnız «Aktiv sessiya» yaşıl nişan alır.
                "Aktiv sessiya" if alive else "Bağlanıb",
            )
        )
    return result


def _active_session_count(session: Session, employee: Any) -> int:
    from datetime import UTC, datetime  # noqa: PLC0415

    row = session.uow.connection.execute(
        """
        SELECT count(*) AS total
          FROM auth_sessions
         WHERE tenant_id = %s AND user_id = %s
           AND revoked_at IS NULL AND expires_at > %s
        """,
        (session.tenant_id, employee.id, datetime.now(UTC)),
    ).fetchone()
    return int((row or {}).get("total") or 0)


__all__ = ["PASSWORD_POLICY_NOTE", "ProfileController"]
