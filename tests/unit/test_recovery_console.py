"""Gizli bərpa konsolu — `Ctrl+Shift+K` (RECOVERY-1 Faza 2).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
Bu konsol quraşdırıcının SON çarəsidir: baza açılmır, ekranda isə yalnız
«Yenidən Cəhd Et» var. Ona görə iki şey ölçülür:

    1. **XƏTA MESAJI KONKRETDİR.** «Xəta baş verdi» quraşdırıcıya heç nə
       vermir — o, DNS səhvi ilə yanlış parolu ayırd edə bilməlidir, çünki
       düzəliş tamamilə fərqlidir (biri host adı, digəri açar).
    2. **GİRİŞ QAPISI.** Konfiqurasiya edilməmiş maşında hər kəs açır (hələ
       hesab yoxdur). Konfiqurasiya edilmiş maşında YALNIZ `can_switch_db`
       daşıyan Root — CEO belə çata bilməməlidir, çünki konsol bazanı
       DƏYİŞDİRƏ və YENİDƏN QURA bilir.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.unit


class _SqlStateError(Exception):
    """`psycopg` istisnalarının `sqlstate` atributunu təqlid edir."""

    def __init__(self, sqlstate: str = "", message: str = "") -> None:
        super().__init__(message or sqlstate)
        self.sqlstate = sqlstate


class _Position:
    def __init__(self, role: Any) -> None:
        self.effective_system_role = role
        self.code = str(getattr(role, "value", role))


class _Actor:
    """`Employee` əvəzinə minimal aktor — flag + rol soruşulur.

    Model MÖVCUD qapının eynisidir (`use_cases/db_switch._require_permission`):
    konsol ikinci, fərqli qayda icad etməməlidir.
    """

    def __init__(self, *, flags: set[str], role: Any) -> None:
        self._flags = flags
        self.position = _Position(role)
        self.id = "aktor"

    def has_permission(self, flag: str, *, now: Any = None) -> bool:
        return flag in self._flags


# --------------------------------------------------------------------------- #
# 1. Konkret xəta mesajları
# --------------------------------------------------------------------------- #


def test_a_bad_host_name_says_so() -> None:
    """DNS səhvində istifadəçi HOST sahəsinə baxmalıdır, açara yox."""
    from src.presentation.controllers.recovery_console import describe_failure

    message = describe_failure(
        _SqlStateError(message='could not translate host name "db.yoxdur.co" to address')
    )

    assert "host" in message.lower()
    assert "yoxdur" not in message.lower() or "tapılmadı" in message.lower()


@pytest.mark.parametrize("sqlstate", ["28P01", "28000"])
def test_a_rejected_key_is_named_as_such(sqlstate: str) -> None:
    """Parol/açar rədd edilib — şəbəkəni yoxlamaq kömək etmir."""
    from src.presentation.controllers.recovery_console import describe_failure

    message = describe_failure(_SqlStateError(sqlstate))

    assert "açar" in message.lower() or "parol" in message.lower()


def test_a_missing_database_is_distinguished_from_a_missing_table() -> None:
    """`3D000` baza adı, `42P01` isə sxem problemidir — düzəliş fərqlidir."""
    from src.presentation.controllers.recovery_console import describe_failure

    database = describe_failure(_SqlStateError("3D000"))
    table = describe_failure(_SqlStateError("42P01"))

    assert "baza" in database.lower()
    assert "cədvəl" in table.lower()
    assert database != table


def test_an_unknown_failure_still_carries_the_original_text() -> None:
    """Tanımadığımız nasazlıqda ORİJİNAL mətn gizlədilmir.

    «Naməlum xəta» quraşdırıcını kor edir; server mətni isə çox vaxt
    problemin özünü yazır.
    """
    from src.presentation.controllers.recovery_console import describe_failure

    message = describe_failure(RuntimeError("disk doludur"))

    assert "disk doludur" in message


# --------------------------------------------------------------------------- #
# 2. Giriş qapısı
# --------------------------------------------------------------------------- #


def test_an_unconfigured_machine_lets_anyone_in() -> None:
    """Hesab hələ yoxdur — qapını bağlamaq konsolu FAYDASIZ edərdi."""
    from src.presentation.controllers.recovery_console import may_open

    assert may_open(actor=None, configured=False)


def test_a_configured_machine_refuses_an_anonymous_visitor() -> None:
    """Konfiqurasiya varsa, giriş etməmiş adam konsolu AÇA BİLMƏZ."""
    from src.presentation.controllers.recovery_console import may_open

    assert not may_open(actor=None, configured=True)


def test_a_configured_machine_refuses_the_ceo() -> None:
    """CEO ən yüksək BİZNES rolu olsa da, bazanı yenidən qura BİLMƏZ.

    Konsol `can_switch_db` tələb edir və o flag `authorization.py`-a görə
    YALNIZ Root-dadır (hardlock 1) — bu test həmin qapının konsolda da
    qüvvədə olduğunu ölçür.
    """
    from src.domain.value_objects.authorization import SystemRole
    from src.presentation.controllers.recovery_console import may_open

    ceo = _Actor(flags={"can_manage_employees", "can_issue_fines"}, role=SystemRole.CEO)

    assert not may_open(actor=ceo, configured=True)


def test_a_configured_machine_admits_root_with_the_flag() -> None:
    """`can_switch_db` daşıyan Root — yeganə qapı."""
    from src.domain.value_objects.authorization import SystemRole
    from src.presentation.controllers.recovery_console import may_open

    root = _Actor(flags={"can_switch_db"}, role=SystemRole.ROOT)

    assert may_open(actor=root, configured=True)


def test_the_flag_alone_is_not_enough_without_the_root_role() -> None:
    """Flag səhvən başqa rola verilsə belə, ROL qapısı saxlayır.

    İki qatlı yoxlama qəsdəndir və mövcud `db_switch` qapısının eynisidir:
    flag qatı DB-dən gəlir, rol isə kirayəçi qurulanda təyin olunur.
    """
    from src.domain.value_objects.authorization import SystemRole
    from src.presentation.controllers.recovery_console import may_open

    imposter = _Actor(flags={"can_switch_db"}, role=SystemRole.CEO)

    assert not may_open(actor=imposter, configured=True)


# --------------------------------------------------------------------------- #
# 3. Diaqnostika
# --------------------------------------------------------------------------- #


def test_the_diagnostics_name_every_searched_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """«Hansı faylı oxuyur?» sualının cavabı TAM olmalıdır."""
    from src.presentation.controllers.recovery_console import diagnostics

    report = diagnostics()
    labels = [label for label, _ in report]

    assert "Tətbiq versiyası" in labels
    assert any("Konfiqurasiya" in label for label in labels)
    assert any("Log" in label for label in labels)


def test_the_diagnostics_mark_which_config_file_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Hər yolun YANINDA tapılıb-tapılmadığı yazılır — axtarış qalmasın."""
    from src.infrastructure.config.connection_file import CONNECTION_FILE_ENV
    from src.presentation.controllers.recovery_console import diagnostics

    target = tmp_path / "connection.json"
    target.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(CONNECTION_FILE_ENV, str(target))

    values = dict(diagnostics())
    joined = " ".join(values.values())

    assert "VAR" in joined


# --------------------------------------------------------------------------- #
# 4. `Ctrl+Shift+K` — qısayol və qapı
# --------------------------------------------------------------------------- #


def _application(qt_app: Any) -> Any:
    from src.presentation.app import KompasApplication
    from src.presentation.theme.tokens import ThemeMode

    return KompasApplication(qt_app, preview=True, theme_preference=ThemeMode.LIGHT, context=None)


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None, reason="PySide6 yoxdur"
)
def test_the_shortcut_is_registered_on_the_window(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Qısayol OLMASA konsola çatmağın heç bir yolu qalmır — ekranda ipucu yoxdur."""
    from PySide6.QtGui import QKeySequence, QShortcut

    application = _application(qt_app)
    window = application.window()

    sequences = [s.key().toString() for s in window.findChildren(QShortcut)]

    assert QKeySequence("Ctrl+Shift+K").toString() in sequences


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None, reason="PySide6 yoxdur"
)
def test_the_console_refuses_to_open_for_a_forbidden_actor(  # type: ignore[no-untyped-def]
    qt_app, monkeypatch
) -> None:
    """Qapı bağlıdırsa ekran DƏYİŞMİR — və heç bir mesaj da göstərilmir.

    Rədd mesajı belə ipucudur: «deməli burada nə isə var» siqnalı verir.
    """
    from src.presentation import app as app_module

    application = _application(qt_app)
    monkeypatch.setattr(app_module, "_recovery_may_open", lambda **_: False)
    opened: list[str] = []
    monkeypatch.setattr(application, "show_recovery_console", lambda: opened.append("açıldı"))

    application.open_recovery_console()

    assert opened == []
