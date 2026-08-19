"""`SettingsController` üçün İLK test faylı — UI-2 reqressiyası.

──────────────────────────────────────────────────────────────────────────────
QÜSUR NƏ İDİ
──────────────────────────────────────────────────────────────────────────────
`controllers/settings.py`-də ÜÇ yoldan İKİSİ (`refresh()`, `_on_sessions()`)
geniş `except Exception` tutur, `_on_saved()` isə dar `except KompasOSError`
qalmışdı. Baza qatı hər xətanı `KompasOSError`-ə BÜRÜMÜR — hovuz taymautu və
bağlantı qırılması çılpaq `psycopg.OperationalError` kimi qalxır. Nəticə:
«Yadda Saxla» düyməsi ötəri şəbəkə xətasında sükutla «basılır, heç nə olmur»
halına düşürdü — `refresh()`-in artıq düzəltdiyi qüsurun EYNİSİ, yazı
tərəfində.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL İNDİYƏ QƏDƏR YOX İDİ
──────────────────────────────────────────────────────────────────────────────
`qa` çarpaz sorğuda tapdı: `grep -rl "SettingsController" tests/` SIFIR nəticə
verdi. Asimmetriya («niyə YALNIZ `_on_saved` dar qalıb?») test boşluğunun
DEYİL, qismən əl düzəlişinin nəticəsi idi — bütün fayl əvvəlcə sıfır əhatədə
idi. Bu fayl `refresh()` VƏ `_on_saved()`-i EYNİ ssenari ilə (Postgres-in
çılpaq, `KompasOSError` OLMAYAN istisnası) yoxlayır ki, gələcəkdə biri
düzəlib digəri yenə "unudulmasın".
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import SystemRole
from src.domain.value_objects.identifiers import EmployeeId, PositionId, TenantId
from src.presentation.controllers.settings import SettingsController

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())


class _OperationalError(Exception):
    """psycopg-in çılpaq bağlantı xətasının əvəzedicisi.

    QƏSDƏN `KompasOSError`-dən TÖRƏMİR: UI-2-nin ölçdüyü şey məhz budur —
    baza qatının BÜRÜMƏDİYİ xəta növü. `user_message` atributu YOXDUR, ona
    görə `_on_saved`-in `getattr(exc, "user_message", "Yenidən cəhd edin.")`
    ehtiyat yoluna da toxunur.
    """


def _actor() -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=SystemRole.SELLER.value,
        name_az="Satıcı",
        priority=SystemRole.SELLER.default_priority,
        is_system=True,
    )
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Ad",
        last_name="Soyad",
        has_pin=True,
    )


class _FakePreferences:
    """`session.preferences` repo-sunun əvəzedicisi."""

    def __init__(self, *, load_failure: Exception | None = None) -> None:
        self.load_failure = load_failure
        self.saved: dict[str, bool] | None = None

    def notification_prefs(self, employee_id: EmployeeId) -> dict[str, bool]:
        if self.load_failure is not None:
            raise self.load_failure
        return {"FINE_ISSUED": True}

    def set_notification_prefs(self, employee_id: EmployeeId, prefs: dict[str, bool]) -> None:
        self.saved = prefs


class _AuthSessionsRepo:
    """`session.uow.repository("auth_sessions")`-un əvəzedicisi (D3-03)."""

    def __init__(self, *, rows: list[Any] | None = None, failure: Exception | None = None) -> None:
        self._rows = rows or []
        self._failure = failure

    def list_recent_for_user(self, tenant_id: Any, employee_id: Any) -> list[Any]:
        if self._failure is not None:
            raise self._failure
        return self._rows


class _Uow:
    def __init__(self, *, auth_sessions: _AuthSessionsRepo) -> None:
        self._auth_sessions = auth_sessions

    def repository(self, name: str) -> Any:
        assert name == "auth_sessions"
        return self._auth_sessions


class _FakeSession:
    def __init__(
        self,
        preferences: _FakePreferences,
        *,
        commit_failure: Exception | None = None,
        auth_sessions: _AuthSessionsRepo | None = None,
    ):
        self.preferences = preferences
        self._commit_failure = commit_failure
        self.committed = False
        self.tenant_id = TENANT
        self.uow = _Uow(auth_sessions=auth_sessions or _AuthSessionsRepo())

    def commit(self) -> None:
        if self._commit_failure is not None:
            raise self._commit_failure
        self.committed = True


class _Clock:
    def now(self) -> datetime:
        return NOW


class _FakeContext:
    """`ApplicationContext.session()`-in əvəzedicisi.

    `enter_failure` verilibsə, `with self._context.session(...)` bloku
    GİRİŞDƏ partlayır — bağlantı hovuzu tükənəndə/qırılanda baş verən
    real ssenari məhz budur (sorğu heç göndərilmir).
    """

    def __init__(
        self,
        preferences: _FakePreferences,
        *,
        enter_failure: Exception | None = None,
        commit_failure: Exception | None = None,
        auth_sessions: _AuthSessionsRepo | None = None,
    ) -> None:
        self._preferences = preferences
        self._enter_failure = enter_failure
        self._commit_failure = commit_failure
        self._auth_sessions = auth_sessions
        self.clock = _Clock()

    @contextmanager
    def session(self, *, user_id: EmployeeId | None = None) -> Iterator[_FakeSession]:
        if self._enter_failure is not None:
            raise self._enter_failure
        yield _FakeSession(
            self._preferences,
            commit_failure=self._commit_failure,
            auth_sessions=self._auth_sessions,
        )


class _FakeScreen:
    """`SettingsScreen`-in əvəzedicisi — YALNIZ çağırışları yazır."""

    def __init__(self) -> None:
        self.section_errors: list[str] = []
        self.errors: list[dict[str, Any]] = []
        self.notification_prefs: dict[str, bool] | None = None
        self.security_info: dict[str, str] | None = None

    def set_section_error(self, section_label: str) -> None:
        self.section_errors.append(section_label)

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append({"title": title, "message": message})

    def set_notification_prefs(self, prefs: dict[str, bool]) -> None:
        self.notification_prefs = prefs

    def set_security_info(self, *, password_age: str, sessions: str) -> None:
        self.security_info = {"password_age": password_age, "sessions": sessions}


# --------------------------------------------------------------------------- #
# `refresh()` — mövcud davranışın qorunması
# --------------------------------------------------------------------------- #


def test_refresh_shows_the_loaded_preferences_on_success() -> None:
    """Nəzarət testi: normal yol pozulmayıb."""
    preferences = _FakePreferences()
    context = _FakeContext(preferences)
    screen = _FakeScreen()

    SettingsController(context, _actor()).refresh(screen)

    assert screen.notification_prefs == {"FINE_ISSUED": True}
    assert screen.section_errors == []
    # D3-03 — "Təhlükəsizlik" kartı ARTIQ doldurulur (əvvəl HEÇ çağırılmırdı).
    assert screen.security_info == {
        "password_age": "Administrator tərəfindən idarə olunur (SEC-016).",
        "sessions": "Aktiv sessiya yoxdur.",
    }


def test_refresh_reports_a_non_kompasos_error_instead_of_hanging() -> None:
    """[UI-2 nəzarət] `refresh()` artıq geniş tutur — mövcud davranış qorunur.

    `_OperationalError` `KompasOSError`-dən TÖRƏMİR. Dar tutucu olsaydı bu
    istisna `SettingsController.refresh()`-dən BAYA çıxardı — `refresh()`
    ekran FABRİKASINDAN çağırıldığı üçün (`app.py::_register_screens`)
    menyu maddəsi «basılır, heç nə açılmır» halına düşərdi.
    """
    preferences = _FakePreferences(load_failure=_OperationalError("connection lost"))
    context = _FakeContext(preferences)
    screen = _FakeScreen()

    SettingsController(context, _actor()).refresh(screen)

    assert screen.section_errors == ["Bildiriş tərcihləri"]
    assert screen.notification_prefs is None
    # D3-03 — bildiriş bölməsi çöksə də TƏHLÜKƏSİZLİK bölməsi AYRI sessiyada
    # oxunur, ONUN uğuru BİRİNCİNİN uğursuzluğundan TƏSİRLƏNMİR (Qrup G qaydası).
    assert screen.security_info is not None


# --------------------------------------------------------------------------- #
# D3-03 (dövrə 3 audit) — «Təhlükəsizlik» kartı
# --------------------------------------------------------------------------- #


def test_refresh_summarizes_a_single_active_session() -> None:
    from types import SimpleNamespace

    row = SimpleNamespace(revoked_at=None, expires_at=NOW.replace(year=NOW.year + 1))
    auth_sessions = _AuthSessionsRepo(rows=[row])
    context = _FakeContext(_FakePreferences(), auth_sessions=auth_sessions)
    screen = _FakeScreen()

    SettingsController(context, _actor()).refresh(screen)

    assert screen.security_info == {
        "password_age": "Administrator tərəfindən idarə olunur (SEC-016).",
        "sessions": "1 cihazda aktiv sessiyanız var.",
    }


def test_refresh_summarizes_several_active_sessions_and_ignores_expired_ones() -> None:
    from datetime import timedelta
    from types import SimpleNamespace

    active = SimpleNamespace(revoked_at=None, expires_at=NOW + timedelta(hours=8))
    expired = SimpleNamespace(revoked_at=None, expires_at=NOW - timedelta(hours=1))
    revoked = SimpleNamespace(
        revoked_at=NOW - timedelta(days=1), expires_at=NOW + timedelta(hours=8)
    )
    auth_sessions = _AuthSessionsRepo(rows=[active, active, expired, revoked])
    context = _FakeContext(_FakePreferences(), auth_sessions=auth_sessions)
    screen = _FakeScreen()

    SettingsController(context, _actor()).refresh(screen)

    assert screen.security_info == {
        "password_age": "Administrator tərəfindən idarə olunur (SEC-016).",
        "sessions": "2 cihazda aktiv sessiyanız var.",
    }


def test_refresh_reports_a_security_info_failure_without_touching_preferences() -> None:
    """Sessiya sorğusu çöksə — «Təhlükəsizlik» BÖLMƏSİ xəta göstərir, bildirişlər TOXUNULMUR."""
    auth_sessions = _AuthSessionsRepo(failure=_OperationalError("connection lost"))
    context = _FakeContext(_FakePreferences(), auth_sessions=auth_sessions)
    screen = _FakeScreen()

    SettingsController(context, _actor()).refresh(screen)

    assert screen.section_errors == ["Təhlükəsizlik"]
    assert screen.security_info is None
    assert screen.notification_prefs == {"FINE_ISSUED": True}  # digər bölmə TƏSİRLƏNMƏYİB


# --------------------------------------------------------------------------- #
# `_on_saved()` — UI-2-nin ƏSAS reqressiyası
# --------------------------------------------------------------------------- #


def test_on_saved_reports_a_non_kompasos_error_instead_of_swallowing_it() -> None:
    """UI-2: `_on_saved` `_OperationalError`-u SÜKUTLA UDMAMALIDIR.

    Düzəlişdən ƏVVƏL tutucu `except KompasOSError` idi — `_OperationalError`
    ondan törəmədiyi üçün TUTULMAZDI və çağıran tərəfə (Qt siqnal
    handler-inə) çıxardı; PySide6 siqnal handler-ləri istisnanı KONSOLA
    yazıb udur, istifadəçi isə «Yadda Saxla» düyməsinin sükutla heç nə
    etmədiyini görürdü. `screen.show_error(...)` çağırışının olması məhz
    bunun ƏKSİNİ sübut edir.
    """
    preferences = _FakePreferences()
    context = _FakeContext(preferences, enter_failure=_OperationalError("pool exhausted"))
    screen = _FakeScreen()

    SettingsController(context, _actor())._on_saved(
        screen, {"notifications": {"FINE_ISSUED": False}}
    )

    assert len(screen.errors) == 1
    assert screen.errors[0]["title"] == "Ayarlar yadda saxlanılmadı"
    # `_OperationalError`-da `user_message` YOXDUR — ehtiyat mətni işə düşür.
    assert screen.errors[0]["message"] == "Yenidən cəhd edin."


def test_on_saved_reports_a_commit_failure_too() -> None:
    """Xəta `commit()`-də baş versə də eyni yol işə düşməlidir.

    `session()` özü uğurla açılıb, sorğu göndərilib, YALNIZ təsdiqləmə
    anında bağlantı qırılıb — bu, `enter_failure`-dan FƏRQLİ bir nöqtədir və
    ayrıca yoxlanmalıdır, çünki `with` bloku artıq `session.preferences.
    set_notification_prefs(...)`-i keçib.
    """
    preferences = _FakePreferences()
    context = _FakeContext(preferences, commit_failure=_OperationalError("connection reset"))
    screen = _FakeScreen()

    SettingsController(context, _actor())._on_saved(
        screen, {"notifications": {"FINE_ISSUED": False}}
    )

    assert len(screen.errors) == 1
    assert preferences.saved == {"FINE_ISSUED": False}  # yazı gedib, YALNIZ commit çökmüşdü


# NƏZARƏT TESTİ ("uğurlu yol pozulmayıb") burada QƏSDƏN YOXDUR: uğurlu
# `_on_saved()` şərtsiz `_inform()` → `QMessageBox.information(screen, ...)`
# çağırır (`settings.py:119`) — `screen` PARAMETRİ REAL `QWidget` olmalıdır,
# əks halda PySide6 tip yoxlaması istisna atır. Bu, UI-2-nin predmeti
# (istisnanın udulub-udulmadığı) DEYİL, ona görə əlavə Qt-asılı test
# yaradılmadı; yazı yolunun ÖZÜ (`preferences.saved`) yuxarıdakı iki testdə
# artıq yoxlanılır.
