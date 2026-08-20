"""İSTEHSALAT QÜSURLARI — giriş çökməsi və quraşdırma sonrası ölü-son.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL VAR
──────────────────────────────────────────────────────────────────────────────
İkisi də REAL istifadədə tapıldı, tam test dəsti isə YAŞIL idi — çünki hər
ikisi «icra olunmaz» sayılan yollarda gizlənmişdi.

1. **Giriş alınmırdı.** `LOGIN_SUCCESS` jurnala düşürdü, sonra ekran «Yoxlanılır…»
   deyib YENİDƏN giriş ekranına qayıdırdı. Səbəb `NameError`: `Employee`
   yalnız `TYPE_CHECKING` altında idxal olunmuşdu, `isinstance()` isə icra
   zamanı işləyir. Statik qapı `test_type_checking_runtime_use.py`-dədir;
   burada DAVRANIŞ ölçülür — uğurlu autentifikasiya örtüyü AÇMALIDIR.

2. **Quraşdırmadan sonra proqram açılmırdı.** Təmiz quraşdırmada
   `connection.json` yoxdur → `CREDENTIALS_MISSING` → fatal ekran açılırdı və
   mesajı «Bağlantı Ayarları ekranından server məlumatlarını daxil edin»
   deyirdi, HALBUKİ o ekranı açmağın yolu yox idi. Yəni hər YENİ müştəri
   quraşdırmadan dərhal sonra kilidlənirdi.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# 1 — Uğurlu giriş örtüyü açır (NameError reqressiyası)
# --------------------------------------------------------------------------- #


def test_a_successful_login_reaches_the_shell_instead_of_raising() -> None:
    """Qüsurun ÖZÜ: `isinstance(..., Employee)` `NameError` atırdı.

    Test Qt TƏLƏB ETMİR: `_authenticate` yalnız `self._login` və `self._auth`
    ilə işləyir, hər ikisi sahtələnir. Ölçülən — uğurlu nəticədə istisna
    ATILMAMASI və axının davam etməsidir.
    """
    from src.domain.entities.employee import Employee
    from src.presentation.app import KompasApplication

    application = object.__new__(KompasApplication)

    class _Login:
        def __init__(self) -> None:
            self.errors: list[str] = []
            self.cleared = False

        def set_busy(self, _busy: bool) -> None:
            return None

        def set_error(self, message: str) -> None:
            self.errors.append(message)

        def clear(self) -> None:
            self.cleared = True

    employee = object.__new__(Employee)

    class _Outcome:
        succeeded = True
        must_change_password = False
        message = ""

    outcome = _Outcome()
    outcome.employee = employee  # type: ignore[attr-defined]

    class _Auth:
        def authenticate(self, _username: Any, _password: str) -> Any:
            return outcome

    reached: list[Any] = []
    application._login = _Login()  # type: ignore[attr-defined]
    application._auth = _Auth()  # type: ignore[attr-defined]
    application._show_face_setup_if_required = (  # type: ignore[attr-defined]
        lambda subject, *, on_continue: reached.append(subject) or False
    )
    application.show_admin = lambda subject, *, now: reached.append(("shell", subject))  # type: ignore[attr-defined]

    application._authenticate("aysel", "parol")  # type: ignore[attr-defined]

    # Ən vacibi: istisna ATILMADI və `Employee` tanındı — yəni istifadəçi
    # giriş ekranına GERİ QAYTARILMADI.
    assert application._login.errors == []  # type: ignore[attr-defined]
    assert application._login.cleared is True  # type: ignore[attr-defined]
    assert reached, "uğurlu giriş axını davam etməli idi"


def test_a_non_employee_result_is_reported_not_crashed() -> None:
    """Tip qoruyucusunun ÖZÜ hələ də işləyir — sadəcə artıq çökmür."""
    from src.presentation.app import KompasApplication

    application = object.__new__(KompasApplication)

    class _Login:
        def __init__(self) -> None:
            self.errors: list[str] = []

        def set_busy(self, _busy: bool) -> None:
            return None

        def set_error(self, message: str) -> None:
            self.errors.append(message)

        def clear(self) -> None:
            return None

    class _Outcome:
        succeeded = True
        must_change_password = False
        message = ""
        employee = "işçi deyil, sətir"

    class _Auth:
        def authenticate(self, _username: Any, _password: str) -> Any:
            return _Outcome()

    application._login = _Login()  # type: ignore[attr-defined]
    application._auth = _Auth()  # type: ignore[attr-defined]

    application._authenticate("aysel", "parol")  # type: ignore[attr-defined]

    assert application._login.errors == ["Giriş nəticəsi oxuna bilmədi."]  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# 2 — Konfiqurasiya nasazlığı AYARLAR ekranına gedir, ölü-sona yox
# --------------------------------------------------------------------------- #


def _application_with_recorders() -> tuple[Any, list[Any], list[Any]]:
    """Qt-siz sahtə tətbiq — açılış cəhdi `InlineExecutor` ilə DƏRHAL bitir.

    `_attempt_startup` işi fon sapına verir (donma düzəlişi). Testdə hadisə
    dövrəsi yoxdur, ona görə layihənin `InlineExecutor` naxışı işlədilir:
    `run_job` çağırışı qayıtdıqda nəticə ARTIQ çatdırılmış olur.
    """
    from src.presentation.app import KompasApplication
    from src.presentation.background_task import InlineExecutor

    application = object.__new__(KompasApplication)
    application._executor = InlineExecutor()
    application._startup_task = None
    application._window = None
    application.show_loading_splash = lambda: None
    settings_calls: list[Any] = []
    fatal_calls: list[Any] = []
    application.show_connection_settings = (  # type: ignore[attr-defined]
        lambda rebuild, *, failure_message="": settings_calls.append(failure_message)
    )
    application.show_startup_failure = (  # type: ignore[attr-defined]
        lambda *, message, kind, rebuild: fatal_calls.append(kind)
    )
    application.adopt_context = lambda context: None  # type: ignore[attr-defined]
    return application, settings_calls, fatal_calls


def test_missing_credentials_open_the_connection_settings_screen() -> None:
    """TƏMİZ QURAŞDIRMA HALI: `connection.json` yoxdur.

    Bu, hər YENİ müştərinin ilk təcrübəsidir — pozulacaq işlək konfiqurasiya
    olmadığı üçün ayarlar ekranı təhlükəsizdir və YEGANƏ irəli yoldur.
    """
    from src.presentation.composition import StartupError, StartupFailureKind

    application, settings_calls, fatal_calls = _application_with_recorders()

    def _rebuild() -> Any:
        raise StartupError(
            "Baza bağlantısı konfiqurasiya edilməyib",
            user_message="Server məlumatlarını daxil edin.",
            kind=StartupFailureKind.CREDENTIALS_MISSING,
        )

    application._attempt_startup(_rebuild)

    assert settings_calls == ["Server məlumatlarını daxil edin."]
    assert fatal_calls == []


def test_invalid_credentials_also_open_the_settings_screen() -> None:
    """Saxlanmış parol səhvdirsə də pozulacaq İŞLƏK konfiqurasiya yoxdur."""
    from src.presentation.composition import StartupError, StartupFailureKind

    application, settings_calls, fatal_calls = _application_with_recorders()

    def _rebuild() -> Any:
        raise StartupError(
            "Parol qəbul edilmədi",
            user_message="Parol səhvdir.",
            kind=StartupFailureKind.CREDENTIALS_INVALID,
        )

    application._attempt_startup(_rebuild)

    assert settings_calls == ["Parol səhvdir."]
    assert fatal_calls == []


def test_a_network_failure_still_shows_the_fatal_screen() -> None:
    """RECOVERY-1 qərarı QORUNUR: şəbəkə nasazlığında ayarlar AÇILMIR.

    Səbəb dəyişməyib — orada konfiqurasiya DÜZGÜNDÜR və istifadəçini onu
    «düzəltməyə» sövq etmək işlək quraşdırmanı pozardı.
    """
    from src.presentation.composition import StartupError, StartupFailureKind

    application, settings_calls, fatal_calls = _application_with_recorders()

    def _rebuild() -> Any:
        raise StartupError(
            "Baza əlçatmazdır",
            user_message="Şəbəkəni yoxlayın.",
            kind=StartupFailureKind.DATABASE_UNREACHABLE,
        )

    application._attempt_startup(_rebuild)

    assert settings_calls == []
    assert fatal_calls == [StartupFailureKind.DATABASE_UNREACHABLE]


def test_a_successful_rebuild_adopts_the_context() -> None:
    """Uğurlu cəhd nə ayarlar, nə fatal ekran açır — normal axına keçir."""
    application, settings_calls, fatal_calls = _application_with_recorders()
    adopted: list[Any] = []
    application.adopt_context = adopted.append  # type: ignore[attr-defined]

    context = object()
    application._attempt_startup(lambda: context)

    assert adopted == [context]
    assert settings_calls == []
    assert fatal_calls == []
