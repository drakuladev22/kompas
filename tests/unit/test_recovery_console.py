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

from src.presentation.composition import StartupFailureKind
from tests.conftest import requires_qt

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
    """Konfiqurasiya varsa VƏ baza işləyirsə, giriş etməmiş adam AÇA BİLMƏZ.

    Yəni giriş ekranında `Ctrl+Shift+K` heç nə açmır — qapı yalnız İKİ dar
    başlanğıc-uğursuzluğu növündə genişlənir (növbəti testə bax, SEC-2).
    Normal iş rejimində (baza işləkdir) `startup_failure_kind` `None`-dur —
    bu, HEÇ BİR bypass növünə uyğun gəlmir, ona görə qapı bağlı qalır.
    """
    from src.presentation.controllers.recovery_console import may_open

    assert not may_open(actor=None, configured=True, startup_failure_kind=None)


def test_a_configured_machine_opens_when_the_database_is_unreachable() -> None:
    """SƏNƏDLƏŞDİRİLMİŞ ÇIXIŞ YOLU FAKTİKİ OLARAQ BAĞLI İDİ.

    `FatalStartupScreen` başlığı deyir: «Eyni imkan TEXNİKDƏDİR:
    `Ctrl+Shift+K` → Bərpa Konsolu». Həmin ekran məhz baza açılmayanda
    görünür və o anda `actor` HƏMİŞƏ `None`-dur (giriş mümkün deyil), yəni
    köhnə qayda ilə konsol heç vaxt açılmazdı.

    `can_switch_db` flag-i BAZADADIR — yoxlanıla bilməyən şərti tələb etmək
    qapını əbədi bağlı saxlamaq deməkdir. Qalan qorumalar yerindədir:
    `connection.json` administrator hüququ, DDL isə elevasiyalı baza parolu
    tələb edir.

    NÖV `DATABASE_UNREACHABLE`-dır (SEC-2) — toyuq-yumurta arqumenti YALNIZ
    bu növdə keçərlidir: server/şəbəkə əlçatmazdır, konfiqurasiyanın özü
    DÜZGÜNDÜR. `CREDENTIALS_INVALID` (parol səhvdir, server İŞLƏKDİR) EYNİ
    bypass-a düşməMƏLİDİR — bu, `_BYPASS_KINDS`-in DAR saxlanılmasının
    səbəbidir (bax `may_open` başlığı). Reqressiya dəsti indi «2b» bölməsidir
    (QA-12) — `CREDENTIALS_INVALID`/host-dəyişikliyi ssenarisi orada
    `RecoveryConsoleController`-in ÖZÜ üzərində, uc-uca ölçülür.
    """
    from src.presentation.composition import StartupFailureKind
    from src.presentation.controllers.recovery_console import may_open

    assert may_open(
        actor=None,
        configured=True,
        startup_failure_kind=StartupFailureKind.DATABASE_UNREACHABLE,
    )


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        pytest.param(None, False, id="normal-iş-rejimi"),
        pytest.param(StartupFailureKind.DATABASE_UNREACHABLE, True, id="server-əlçatmazdır"),
        pytest.param(StartupFailureKind.CREDENTIALS_MISSING, True, id="ilk-quraşdırma"),
        pytest.param(StartupFailureKind.CREDENTIALS_INVALID, False, id="parol-səhvdir-HÜCUM"),
        pytest.param(
            StartupFailureKind.IDENTITY_UNAVAILABLE, False, id="installation-json-problemi"
        ),
    ],
)
def test_the_bypass_set_is_dar_and_exact(kind: StartupFailureKind | None, expected: bool) -> None:
    """SEC-2 QƏRAR CƏDVƏLİ — bypass DÖRD növün YALNIZ İKİSİNƏ aiddir.

    ──────────────────────────────────────────────────────────────────────────
    `CREDENTIALS_INVALID` HÜCUM SSENARİSİDİR
    ──────────────────────────────────────────────────────────────────────────
    Baza qatının ÖZÜ tam işlək qalır (server cavab verir) — sadəcə
    `connection.json`-dakı saxlanmış parol/açar səhvdir. Köhnə `database_
    reachable: bool` bayrağı ilə bu, `False` (yəni "baza əlçatmaz") kimi
    qeydə alınıb bypass-a düşürdü, halbuki səlahiyyət YOXLANILA BİLƏRDİ —
    sadəcə yoxlanılmadı. Hücumçu üçün bu, `connection.json`-a yazma
    hüququndan istifadə edərək (fayl güclü ACL daşımır, bax `may_open`
    başlığı) parolu qəsdən korlamaq və beləliklə `actor=None` ilə
    konsola BYPASS almaq demək idi — baza toxunulmadan.

    `IDENTITY_UNAVAILABLE` eyni səbəblə bağlıdır (`installation.json`
    problemi, baza qatı ilə əlaqəsi yoxdur). `None` (başlanğıc uğursuzluğu
    yoxdur/naməlum) FAIL-CLOSED-un ÖZÜDÜR — `test_a_configured_machine_
    refuses_an_anonymous_visitor` VƏ `test_the_default_keeps_the_strict_rule`
    bunu ayrıca ölçür, burada YALNIZ tam qərar cədvəlinin bir hissəsi kimi
    təkrarlanır ki, dörd növün İKİSİ açıq, İKİSİ (+`None`) bağlı olduğu
    TƏK yerdə görünsün.
    """
    from src.presentation.controllers.recovery_console import may_open

    assert may_open(actor=None, configured=True, startup_failure_kind=kind) is expected


def test_the_default_keeps_the_strict_rule() -> None:
    """Parametr verilməzsə davranış KÖHNƏ (sərt) qayda ilə eynidir.

    Defolt `None` seçilib (SEC-2) ki, `startup_failure_kind`-i ötürməyi
    unudan gələcək çağırış qapını sükutla GENİŞLƏNDİRMƏSİN — `None`
    `_BYPASS_KINDS`-ə DÜŞMÜR, ona görə fail-closed nəticə avtomatikdir.
    Səhv tərəfə düşən defolt təhlükəsizlik qapılarında ən bahalı səhvdir.
    """
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
# 2b. `RecoveryConsoleController` — SEC-2 genişlənməsi (dövrə 1 audit, UI-01)
# --------------------------------------------------------------------------- #
#
# `may_open()`-in bypass şərti (yuxarı) YALNIZ konsolun AÇILIB-AÇILMAYACAĞINI
# həll edir. Aşağıdakı testlər İKİNCİ qatı ölçür: bir dəfə açılandan SONRA,
# konsol SAXLANMIŞ (DPAPI-şifrəli, istehsalat) parolu HANSI şərtlə işlədir.
# Hücum zənciri (`RecoveryConsoleController` sinif başlığında tam izah
# olunur): fiziki giriş → şəbəkə kəsimi → `DATABASE_UNREACHABLE` → bypass →
# `connection.json`-un `host` sahəsi dəyişdirilir (ACL zəifdir, `installer/
# KompasOS.iss:127`) → boş parolla «Bağlantını Test Et» → köhnə "boş=dəyişmə"
# davranışı istehsalat parolunu hücumçunun serverinə göndərir.


class _RecoveryScreen:
    """Ekranın minimal duck-typing əvəzi — Qt TƏLƏB OLUNMUR."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.statuses: list[str] = []
        self.failure_reasons: list[str] = []
        self.busy_calls: list[bool] = []
        self.confirmations: list[bool] = []
        self.service_role_cleared = False
        self.diagnostics_calls = 0
        self.populated: dict[str, object] | None = None

    def set_error(self, message: str) -> None:
        self.errors.append(message)

    def set_failure_reason(self, message: str) -> None:
        self.failure_reasons.append(message)

    def set_status(self, message: str) -> None:
        self.statuses.append(message)

    def set_busy(self, busy: bool) -> None:
        self.busy_calls.append(busy)

    def require_confirmation(self, required: bool) -> None:
        self.confirmations.append(required)

    def clear_service_role(self) -> None:
        self.service_role_cleared = True

    def set_diagnostics(self, rows: list[tuple[str, str]]) -> None:
        self.diagnostics_calls += 1

    def populate(self, settings: dict[str, object]) -> None:
        self.populated = settings


def _qt_recovery_screen() -> Any:
    """`_RecoveryScreen`-in `BackgroundTask`-a VALİDEYN OLA BİLƏN versiyası (QA-11).

    ──────────────────────────────────────────────────────────────────────
    NİYƏ AYRICA FABRİKA, `_RecoveryScreen`-in ÖZÜ DEYİL
    ──────────────────────────────────────────────────────────────────────
    `RecoveryConsoleController._run()` `screen`-i BİRBAŞA `BackgroundTask(
    parent=screen, ...)`-a ötürür — PySide6 `QObject.__init__` valideyni
    HƏQİQİ `QObject` OLMAYANDA `TypeError` atır (bax `background_task.py::
    run_job` başlığındakı EYNİ qeyd). «RƏDD» yolunu ölçən 35 testin heç biri
    `_run()`-a ÇATMIR (blok ondan ƏVVƏL dayanır), ona görə plain-Python
    `_RecoveryScreen` onlar üçün kifayətdir və PySide6 idxalı TƏLƏB ETMİR.
    «İCAZƏ» yolunu ölçən testlər isə `_run()`-a ÇATIR — buna görə YALNIZ
    onlar Qt-valideynli versiyanı işlədir (lokal idxal, modul səviyyəsində
    YOX — qalan 35 test PySide6-dan asılı olmasın deyə).

    Çoxlu-varislik (`QObject`, `_RecoveryScreen`) İŞLƏDİLMİR: Shiboken
    metaklassı ilə etibarsızdır. Bunun əvəzinə `__getattr__` BÜTÜN
    metod/sahə çağırışlarını daxili `_RecoveryScreen` nüsxəsinə DELEGE edir.
    """
    from PySide6.QtCore import QObject

    inner = _RecoveryScreen()

    class _QtRecoveryScreen(QObject):
        def __getattr__(self, name: str) -> Any:
            return getattr(inner, name)

    return _QtRecoveryScreen()


def _drain_until(qt_app: Any, predicate: Any, *, seconds: float = 5.0) -> None:
    """`predicate()` `True` olana qədər hadisə dövrəsini işlədir.

    Fon işinin nəticəsi Qt siqnalı ilə əsas sapa POSTLANIR — hadisə dövrəsi
    işləmədən o siqnal heç vaxt çatmaz (eyni naxış `test_session_touch_
    guard.py::_drain_until`/`test_background_job_funnel.py::_drain`-dədir).
    """
    import time

    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()


_STORED_SETTINGS_KWARGS: Any = {
    "host": "prod.supabase.co",
    "port": 5432,
    "database": "postgres",
    "username": "postgres.abc123",
    "password": "İSTEHSALAT-MƏXFİ-PAROL",
}


def _stub_stored_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """`load_settings()` saxlanmış (DPAPI-dən açılmış) ayarları qaytarır kimi edir."""
    from src.infrastructure.config import connection_file

    stored = connection_file.ConnectionSettings(**_STORED_SETTINGS_KWARGS)
    monkeypatch.setattr(connection_file, "load_settings", lambda: stored)


def test_settings_from_reuses_the_saved_password_when_authenticated_and_target_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QAYDA A — avtentifikasiyalı `Root` üçün "boş = dəyişmə" erqonomikası QALIR."""
    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    _stub_stored_settings(monkeypatch)
    controller = RecoveryConsoleController(authenticated=True)

    settings = controller._settings_from(  # type: ignore[attr-defined]
        {
            "host": "prod.supabase.co",
            "port": "5432",
            "database": "postgres",
            "username": "postgres.abc123",
            "password": "",
        }
    )

    assert settings.password == "İSTEHSALAT-MƏXFİ-PAROL"


def test_settings_from_refuses_to_reuse_the_password_when_the_host_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QAYDA A — hədəf (`host`) dəyişibsə parol AVTENTİFİKASİYALI rejimdə BELƏ verilmir."""
    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    _stub_stored_settings(monkeypatch)
    controller = RecoveryConsoleController(authenticated=True)

    settings = controller._settings_from(  # type: ignore[attr-defined]
        {
            "host": "attacker.example.com",
            "port": "5432",
            "database": "postgres",
            "username": "postgres.abc123",
            "password": "",
        }
    )

    assert settings.password == ""


def test_settings_from_refuses_to_reuse_the_password_when_the_port_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QAYDA A — `port` DƏ hədəfin hissəsidir, təkcə `host`/`username` YOX.

    `security`-nin sorduğu (d) bəndi: «boş = dəyişmə» erqonomikası YALNIZ
    hədəf HƏQİQƏTƏN dəyişməyəndə qorunur — port fərqli server/xidmət ola
    bilər, ona görə `_same_target` onu da müqayisə edir (bax `_same_target`
    başlığı). Avtentifikasiyalı rejimdə belə (Root) port dəyişəndə köhnə
    parol İSTİFADƏ OLUNMUR — boş qalır, istifadəçi AYDIN görür ki, parolu
    ƏL İLƏ yazmalıdır (sükutla köhnə server/portla NAMƏLUM nəticə YOX).
    """
    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    _stub_stored_settings(monkeypatch)
    controller = RecoveryConsoleController(authenticated=True)

    settings = controller._settings_from(  # type: ignore[attr-defined]
        {
            "host": "prod.supabase.co",
            "port": "6543",  # saxlanmış 5432-dən FƏRQLİ
            "database": "postgres",
            "username": "postgres.abc123",
            "password": "",
        }
    )

    assert settings.password == ""


def test_settings_from_never_reuses_the_password_when_unauthenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QAYDA B — bypass rejimində `same_target` BELƏ parolu buraxmır.

    Hücumçu host-u dəyişib, sonra konsolda EYNİ host-u YENİDƏN yazsa,
    `_same_target` `True` qayıdar — QAYDA A TƏK BAŞINA bunu buraxardı. QAYDA
    B ASILI olmayaraq bloklayır: bu test məhz həmin ssenaridir (hədəf EYNİDİR,
    amma `authenticated=False`).
    """
    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    _stub_stored_settings(monkeypatch)
    controller = RecoveryConsoleController(authenticated=False)

    settings = controller._settings_from(  # type: ignore[attr-defined]
        {
            "host": "prod.supabase.co",  # saxlanmışla EYNİ — QAYDA A tək başına buraxardı
            "port": "5432",
            "database": "postgres",
            "username": "postgres.abc123",
            "password": "",
        }
    )

    assert settings.password == ""


def test_settings_from_never_calls_load_settings_when_unauthenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QAYDA B — bypass rejimində `load_settings()` ÜMUMİYYƏTLƏ ÇAĞIRILMIR.

    ──────────────────────────────────────────────────────────────────────
    NİYƏ NƏTİCƏNİ SİLMƏK KİFAYƏT ETMİR (`security` tapıntısı)
    ──────────────────────────────────────────────────────────────────────
    Yuxarıdakı test `settings.password == ""` yoxlayır — bu, NƏTİCƏNİN
    işlədilmədiyini sübut edir, LAKİN `load_settings()`-in ÖZÜNÜN çağırılıb-
    çağırılmadığını YOX. Fərq vacibdir: `load_settings()` DPAPI blobunu AÇIR
    və nəticəni `ConnectionSettings.password` sahəsində AÇIQ MƏTNDƏ yaddaşa
    qoyur. `ConnectionSettings.dsn()` onu DSN sətrinə hörür
    (`connection_file.py::dsn`) — əgər gələcək bir dəyişiklik səhvən həmin
    dəyəri hardasa işlətsəydi (məs. diaqnostika, loq), deşifrənin ÖZÜ artıq
    baş vermiş olardı. Ona görə bypass rejimində deşifrə ÜMUMİYYƏTLƏ
    BAŞLADILMAMALIDIR — bu test `load_settings`-in HEÇ ÇAĞIRILMADIĞINI
    ölçür, nəticəsini yox.
    """
    from src.infrastructure.config import connection_file
    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    calls: list[None] = []

    def _spy() -> connection_file.ConnectionSettings:
        calls.append(None)
        return connection_file.ConnectionSettings(**_STORED_SETTINGS_KWARGS)

    monkeypatch.setattr(connection_file, "load_settings", _spy)
    controller = RecoveryConsoleController(authenticated=False)

    settings = controller._settings_from(  # type: ignore[attr-defined]
        {
            "host": "prod.supabase.co",
            "port": "5432",
            "database": "postgres",
            "username": "postgres.abc123",
            "password": "",
        }
    )

    assert calls == []  # DPAPI deşifrəsi HEÇ BAŞLAMAYIB
    assert settings.password == ""


def test_refresh_calls_load_settings_even_when_unauthenticated_but_never_shows_the_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`refresh()` `_settings_from`-dan FƏRQLİDİR — deşifrə edir, LAKİN göstərmir.

    ──────────────────────────────────────────────────────────────────────
    NİYƏ BU İKİ METOD FƏRQLİ DAVRANIR (dövrə 2 audit, team-lead sualı)
    ──────────────────────────────────────────────────────────────────────
    Yuxarıdakı test `_settings_from()`-un bypass rejimində `load_settings()`
    ÇAĞIRMADIĞINI sübut edir (QAYDA B — parol ŞƏBƏKƏYƏ/YAZIYA gedə biləcək
    yol). `refresh()` isə TAMAMİLƏ AYRI yoldur — o, YALNIZ diaqnostika
    göstərir və `authenticated`-dən ASILI OLMAYARAQ `load_settings()`
    çağırır (bax onun başlığı: texnik cari host/port/istifadəçi adını
    görməlidir). Bu, QAYDA B-ni POZMUR, çünki `settings.password` heç vaxt
    `screen.populate(...)`-ə ÖTÜRÜLMÜR — bu test məhz onu ölçür.
    """
    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    _stub_stored_settings(monkeypatch)
    controller = RecoveryConsoleController(authenticated=False)
    screen = _RecoveryScreen()

    controller.refresh(screen)  # type: ignore[attr-defined]

    assert screen.populated is not None
    assert "password" not in screen.populated
    assert _STORED_SETTINGS_KWARGS["password"] not in str(screen.populated.values())


def test_refresh_status_warns_in_unauthenticated_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """team-lead tapıntısı — «boş qalarsa dəyişmir» YALAN İDDİA idi bypass rejimində.

    Köhnə status mətni HƏR REJİMDƏ eyni idi və avtentifikasiyasız rejimdə
    texnikə YANLIŞ gözlənti verirdi (boş parolla düymə basıb niyə işləmədiyini
    anlamazdı). İndi mətn rejimə görə fərqlidir.
    """
    from src.presentation.controllers.recovery_console import (
        _UNAUTHENTICATED_REFRESH_STATUS,
        RecoveryConsoleController,
    )

    _stub_stored_settings(monkeypatch)

    unauthenticated_screen = _RecoveryScreen()
    RecoveryConsoleController(authenticated=False).refresh(  # type: ignore[attr-defined]
        unauthenticated_screen
    )
    authenticated_screen = _RecoveryScreen()
    RecoveryConsoleController(authenticated=True).refresh(  # type: ignore[attr-defined]
        authenticated_screen
    )

    # `.lower()` İŞLƏDİLMİR: Azərbaycan dilində böyük "İ" Python-un standart
    # `str.lower()`-ində "i̇" (nöqtəli, İKİ simvol) olur, adi "i" YOX — sabit
    # mətnlərlə TAM bərabərlik müqayisəsi bu tələni keçir.
    assert unauthenticated_screen.statuses[-1] != authenticated_screen.statuses[-1]
    assert unauthenticated_screen.statuses[-1] == _UNAUTHENTICATED_REFRESH_STATUS
    assert "boş qalarsa dəyişmir" in authenticated_screen.statuses[-1]


@pytest.mark.parametrize("method", ["_on_test", "_on_check"])
def test_the_unauthenticated_console_refuses_to_reach_the_network_with_an_empty_password(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    """UI-01 hücum zənciri — «Bağlantını Test Et»/«Cədvəlləri Yoxla» ŞƏBƏKƏYƏ ÇIXMIR.

    `screen.busy_calls == []` ƏSAS sübutdur: `_run()`/`BackgroundTask`
    ÜMUMİYYƏTLƏ ÇAĞIRILMAYIB, yəni heç bir DSN qurulmayıb, heç bir soket
    açılmayıb — parol nə oxunur, nə göndərilir.
    """
    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    _stub_stored_settings(monkeypatch)
    controller = RecoveryConsoleController(authenticated=False)
    screen = _RecoveryScreen()

    getattr(controller, method)(
        screen,
        {
            "host": "attacker.example.com",
            "port": "5432",
            "database": "postgres",
            "username": "postgres.abc123",
            "password": "",
        },
    )

    assert screen.busy_calls == []
    assert len(screen.errors) == 1
    assert "saxlanmış parol" in screen.errors[0].lower()


def test_the_unauthenticated_console_refuses_to_save_an_empty_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UI-01 — «Yadda Saxla» BOŞ parolla YAZMIR (gecikmiş sızma forması, bax sinif başlığı)."""
    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    _stub_stored_settings(monkeypatch)
    controller = RecoveryConsoleController(authenticated=False)
    screen = _RecoveryScreen()

    controller._on_save(  # type: ignore[attr-defined]
        screen,
        {
            "host": "attacker.example.com",
            "port": "5432",
            "database": "postgres",
            "username": "postgres.abc123",
            "password": "",
        },
    )

    assert screen.busy_calls == []
    assert len(screen.errors) == 1
    assert "boş parolla" in screen.errors[0].lower()


def test_the_unauthenticated_console_refuses_to_provision_without_any_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UI-01 — «Bazanı Avtomatik Qur» da eyni qapıya tabedir (`elevated` sahəsi DƏ boşdursa)."""
    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    _stub_stored_settings(monkeypatch)
    controller = RecoveryConsoleController(authenticated=False)
    screen = _RecoveryScreen()

    controller._on_provision(  # type: ignore[attr-defined]
        screen,
        {
            "host": "attacker.example.com",
            "port": "5432",
            "database": "postgres",
            "username": "postgres.abc123",
            "password": "",
            "service_role": "",
            "confirmation": "",
        },
    )

    assert screen.busy_calls == []
    assert screen.service_role_cleared is False  # `_run`-a belə çatmayıb
    assert len(screen.errors) == 1


def test_the_unauthenticated_console_allows_a_manually_typed_password_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QAYDA B YALNIZ SAXLANMIŞ parolu bloklayır — ƏL İLƏ yazılan öz sirri deyil.

    Texnik özü yazdığı parolla işləyə bilməlidir, əks halda konsol bypass
    rejimində TAMAMİLƏ FAYDASIZ olardı. `_requires_manual_password` `False`
    qayıtdığı üçün `_settings_from` çağırılır. Bu test YALNIZ İKİ köməkçi
    funksiyanı izolyasiyada ölçür — dörd handler-in ÖZÜNÜN «icazə» yolunu
    HƏQİQƏTƏN icra edib-etmədiyi aşağıdakı `test_the_unauthenticated_
    console_lets_a_manually_typed_password_through_*` dəstində ölçülür
    (QA-11 — «rədd» tərəfinin güzgüsü, hər handler AYRI test edilib).
    """
    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    _stub_stored_settings(monkeypatch)
    controller = RecoveryConsoleController(authenticated=False)
    screen = _RecoveryScreen()

    assert not controller._requires_manual_password(  # type: ignore[attr-defined]
        {"password": "texnikin-öz-yazdığı"}
    )

    settings = controller._settings_from(  # type: ignore[attr-defined]
        {
            "host": "attacker.example.com",
            "port": "5432",
            "database": "postgres",
            "username": "postgres.abc123",
            "password": "texnikin-öz-yazdığı",
        }
    )

    assert settings.password == "texnikin-öz-yazdığı"
    assert screen.errors == []  # blok heç işə düşmədi


# --------------------------------------------------------------------------- #
# QA-11 — «rədd» tərəfinin GÜZGÜSÜ: hər handler ÖZÜ əl ilə parolla İŞƏ DÜŞÜR
# --------------------------------------------------------------------------- #
#
# Yuxarıdakı test YALNIZ `_requires_manual_password`/`_settings_from`-u
# izolyasiyada ölçür. `_requires_manual_password` DÖRD handler-də AYRI-AYRI
# çağırıldığı üçün (mərkəzləşdirilməyib — qərar sənədləşib), «rədd» tərəfi DƏ
# hər handler üçün AYRICA test edilib (yuxarı, `test_the_unauthenticated_
# console_refuses_to_*`). Bu bölmə HƏMİN testlərin dəqiq güzgüsüdür: əks
# halda gələcəkdə bir handler `_requires_manual_password` çağırışını
# itirsə/səhv arqument versə, YALNIZ «rədd» tərəfi qırmızı olardı.


@requires_qt
def test_the_unauthenticated_console_lets_a_manually_typed_password_through_on_test(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`_on_test` — əl ilə yazılan parolla İŞ HƏQİQƏTƏN başlayır (`_run` çağırılır)."""
    from src.infrastructure.persistence import connection as connection_module
    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    monkeypatch.setattr(connection_module, "probe_dsn", lambda dsn, **_kwargs: None)
    controller = RecoveryConsoleController(authenticated=False)
    screen = _qt_recovery_screen()

    controller._on_test(  # type: ignore[attr-defined]
        screen,
        {
            "host": "attacker.example.com",
            "port": "5432",
            "database": "postgres",
            "username": "postgres.abc123",
            "password": "texnikin-öz-yazdığı",
        },
    )
    _drain_until(
        qt_app,
        lambda: controller._task is not None and not controller._task.is_running,  # type: ignore[attr-defined]
    )

    assert screen.busy_calls[0] is True  # `_run()`/`BackgroundTask` HƏQİQƏTƏN çağırılıb
    assert screen.errors == []
    assert screen.statuses  # stub uğurla qayıtdı — nəticə çatdırılıb


@requires_qt
def test_the_unauthenticated_console_lets_a_manually_typed_password_through_on_check(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`_on_check` — eyni güzgü. `psycopg.connect` REAL şəbəkəyə çıxmasın deyə stub-lanır."""
    import psycopg

    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    def _stub_connect(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("test stub — real bağlantı qurulmur")

    monkeypatch.setattr(psycopg, "connect", _stub_connect)
    controller = RecoveryConsoleController(authenticated=False)
    screen = _qt_recovery_screen()

    controller._on_check(  # type: ignore[attr-defined]
        screen,
        {
            "host": "attacker.example.com",
            "port": "5432",
            "database": "postgres",
            "username": "postgres.abc123",
            "password": "texnikin-öz-yazdığı",
        },
    )
    _drain_until(
        qt_app,
        lambda: controller._task is not None and not controller._task.is_running,  # type: ignore[attr-defined]
    )

    assert screen.busy_calls[0] is True
    assert screen.errors  # stub `RuntimeError` → `describe_failure` ekrana yazıb


@requires_qt
def test_the_unauthenticated_console_lets_a_manually_typed_password_through_on_save(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`_on_save` — eyni güzgü. `save_settings` REAL diskə yazmasın deyə stub-lanır."""
    from src.infrastructure.config import connection_file
    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    monkeypatch.setattr(connection_file, "save_settings", lambda settings: "STUB-YOL")
    controller = RecoveryConsoleController(authenticated=False)
    screen = _qt_recovery_screen()

    controller._on_save(  # type: ignore[attr-defined]
        screen,
        {
            "host": "attacker.example.com",
            "port": "5432",
            "database": "postgres",
            "username": "postgres.abc123",
            "password": "texnikin-öz-yazdığı",
        },
    )
    _drain_until(
        qt_app,
        lambda: controller._task is not None and not controller._task.is_running,  # type: ignore[attr-defined]
    )

    assert screen.busy_calls[0] is True
    assert screen.errors == []
    assert screen.statuses and "STUB-YOL" in screen.statuses[-1]


@requires_qt
def test_the_unauthenticated_console_lets_a_manually_typed_password_through_on_provision(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`_on_provision` — əsas parol sahəsi ƏL İLƏ doldurulub."""
    import psycopg

    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    def _stub_connect(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("test stub — real bağlantı qurulmur")

    monkeypatch.setattr(psycopg, "connect", _stub_connect)
    controller = RecoveryConsoleController(authenticated=False)
    screen = _qt_recovery_screen()

    controller._on_provision(  # type: ignore[attr-defined]
        screen,
        {
            "host": "attacker.example.com",
            "port": "5432",
            "database": "postgres",
            "username": "postgres.abc123",
            "password": "texnikin-öz-yazdığı",
            "service_role": "",
            "confirmation": "",
        },
    )
    _drain_until(
        qt_app,
        lambda: controller._task is not None and not controller._task.is_running,  # type: ignore[attr-defined]
    )

    assert screen.busy_calls[0] is True
    assert screen.errors
    assert screen.service_role_cleared is True  # `_on_provision` bunu HƏMİŞƏ çağırır


@requires_qt
def test_the_unauthenticated_console_lets_a_manually_typed_elevated_password_through_on_provision(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """`_on_provision` — ƏSAS parol BOŞ, YALNIZ `service_role` (elevated) doldurulub.

    `qa`-nın xüsusi tələb etdiyi yol: `_requires_manual_password(values,
    elevated=elevated)` `elevated`-i NƏZƏRƏ ALIR (bax onun başlığı) — bu
    sahə diskdən HEÇ VAXT bərpa olunmur, ona görə mövcudluğu TƏK BAŞINA
    blok üçün yetərlidir, əsas parol sahəsi boş qalsa belə.
    """
    import psycopg

    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    def _stub_connect(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("test stub — real bağlantı qurulmur")

    monkeypatch.setattr(psycopg, "connect", _stub_connect)
    controller = RecoveryConsoleController(authenticated=False)
    screen = _qt_recovery_screen()

    controller._on_provision(  # type: ignore[attr-defined]
        screen,
        {
            "host": "attacker.example.com",
            "port": "5432",
            "database": "postgres",
            "username": "postgres.abc123",
            "password": "",  # boş — YALNIZ `service_role` ilə keçəcək
            "service_role": "texnikin-elevasiyalı-parolu",
            "confirmation": "",
        },
    )
    _drain_until(
        qt_app,
        lambda: controller._task is not None and not controller._task.is_running,  # type: ignore[attr-defined]
    )

    assert screen.busy_calls[0] is True
    assert screen.errors
    assert screen.service_role_cleared is True


def test_describe_failure_does_not_leak_the_password_from_a_failed_connection() -> None:
    """`security` sualı — bypass rejimində ƏL İLƏ yazılan parol XƏTA MESAJINDA ƏKS OLUNMUR.

    ──────────────────────────────────────────────────────────────────────
    NİYƏ BU YOXLANMALIDIR
    ──────────────────────────────────────────────────────────────────────
    `ConnectionSettings.dsn()` parolu DSN sətrinə hörür (`connection_file.py`)
    və `describe_failure()` ORİJİNAL server mətnini GİZLƏTMİR (bax modul
    başlığı: "ORİJİNAL MƏTN GİZLƏDİLMİR"). Əgər `psycopg`/libpq bağlantı
    xətasının mətninə tam DSN qoysaydı, bypass rejimində ƏL İLƏ yazılmış
    parol EKRANDA (status sətrində) görünərdi — QAYDA B-nin qorumadığı YENİ
    bir sızma yolu olardı.

    ──────────────────────────────────────────────────────────────────────
    NİYƏ LOKAL SOKET, DNS AXTARIŞI YOX
    ──────────────────────────────────────────────────────────────────────
    Bu test REAL uğursuz bağlantı ilə empirik təsdiq edir (mock DEYİL —
    mock `psycopg`-in FAKTİKİ mətn formatını təqlid edə bilməzdi), LAKİN
    naməlum host adına qoşulmaq DNS axtarışına görə ~10 s-ə qədər çəkə bilər
    və nəticə şəbəkə/DNS mühitindən ASILI olardı (qeyri-sabit test). Ona görə
    `127.0.0.1`-də QISA ÖMÜRLÜ yerli soket açılır: server qoşulmanı DƏRHAL
    qəbul edib BAĞLAYIR — psycopg "server closed the connection unexpectedly"
    tipli, LAKİN DSN/parol DAŞIMAYAN xəta ilə ANİNDƏ qayıdır.
    """
    import socket
    import threading

    from src.infrastructure.config.connection_file import ConnectionSettings
    from src.infrastructure.persistence.connection import probe_dsn
    from src.presentation.controllers.recovery_console import describe_failure

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    server.listen(1)

    def _refuse() -> None:
        conn, _ = server.accept()
        conn.close()

    worker = threading.Thread(target=_refuse, daemon=True)
    worker.start()

    secret = "ÇOX-GİZLİ-ƏL-İLƏ-YAZILAN-PAROL"
    settings = ConnectionSettings(
        host="127.0.0.1", port=port, database="postgres", username="probe", password=secret
    )

    try:
        probe_dsn(settings.dsn(), timeout=5)
    except Exception as error:
        message = describe_failure(error)
    else:
        pytest.fail("bağlantı gözlənilmədən uğurlu oldu — test mühiti fərqlidir")
    finally:
        worker.join(timeout=1)
        server.close()

    assert secret not in message


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


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("PySide6") is None, reason="PySide6 yoxdur"
)
def test_adopting_a_recovered_context_clears_the_old_failure_kind(  # type: ignore[no-untyped-def]
    qt_app, monkeypatch
) -> None:
    """SEC-2 [d] — `ui`-nin ÖZÜ tapdığı əlavə qüsur: köhnə növ İZ QALMAMALIDIR.

    ──────────────────────────────────────────────────────────────────────────
    QÜSUR NƏ İDİ
    ──────────────────────────────────────────────────────────────────────────
    `_startup_failure_kind` başlanğıcda `DATABASE_UNREACHABLE` kimi qeydə
    alınır, sonra istifadəçi «Yenidən Cəhd Et»-i basır və bu dəfə baza
    AÇILIR. `adopt_context()` yeni konteksti mənimsəyir, LAKİN köhnə növü
    TƏMİZLƏMƏSƏYDİ, `_startup_failure_kind` `DATABASE_UNREACHABLE` olaraq
    QALARDI. Nəticə: istifadəçi normal giriş ekranına qayıdır (baza İNDİ
    İŞLƏKDİR), sonra `Ctrl+Shift+K` basır — `may_open` köhnə növü görüb
    `actor=None` ilə YENƏ DƏ BYPASS verərdi, halbuki bu artıq normal iş
    rejimidir və qapı bağlı olmalıdır (bax `test_a_configured_machine_
    refuses_an_anonymous_visitor`).

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ AĞIR ASILILIQLAR (`_build_auth_controller`, `start()`) SIXILIB
    ──────────────────────────────────────────────────────────────────────────
    `adopt_context()` real `AuthController` qurur və tətbiqi işə salır —
    bunların ikisi də real baza/GUI qraf tələb edir və bu testin PREDMETİ
    DEYİL. Yalnız `_startup_failure_kind`-in sıfırlandığı SIRA (kontekst
    mənimsənildikdən dərhal SONRA, `start()`-dan ƏVVƏL) ölçülür.
    """
    from types import SimpleNamespace

    from src.presentation import app as app_module

    application = _application(qt_app)
    application._startup_failure_kind = StartupFailureKind.DATABASE_UNREACHABLE
    application._startup_failure_reason = "Baza bağlantısı qurula bilmədi"
    monkeypatch.setattr(app_module, "_build_auth_controller", lambda _context: None)
    monkeypatch.setattr(application, "set_auth_controller", lambda _controller: None)
    monkeypatch.setattr(application, "start", lambda: None)
    # `tenant_id` YEGANƏ sahədir ki, `adopt_context()` sonuncu loq sətrində
    # oxuyur — real `ApplicationContext` deyil, minimal duck-typing kifayətdir.
    context = SimpleNamespace(tenant_id="test-tenant")

    application.adopt_context(context)  # type: ignore[arg-type]

    assert application._startup_failure_kind is None
    # SƏBƏB DƏ TƏMİZLƏNİR — baza artıq İŞLƏKDİR və konsolda qırmızı zolaq
    # qalsaydı, texnik həll olunmuş nasazlığı axtarardı.
    assert application._startup_failure_reason == ""


# --------------------------------------------------------------------------- #
# Başlanğıc nasazlığının SƏBƏBİ — YALNIZ xəta olanda görünür
# --------------------------------------------------------------------------- #
#
# İSTİFADƏÇİ TƏLƏBİ: «Yenidən Cəhd Et» artıq ayarlar ekranını AÇMIR
# (`app.py::_on_startup_failed`), yəni nasazlığın texniki səbəbini
# görən YEGANƏ yer `Ctrl+Shift+K` konsoludur. Lakin konsol İŞLƏK maşında da
# açılır (`Root` + `can_switch_db`) — orada xəta zolağı OLMAMALIDIR.


def test_the_console_shows_the_startup_reason_when_one_was_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nasazlıq səbəbi ekrana ÇATIR — texnik nə düzəldəcəyini bilməlidir."""
    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    _stub_stored_settings(monkeypatch)
    screen = _RecoveryScreen()

    RecoveryConsoleController(
        authenticated=True,
        failure_reason="Baza bağlantı məlumatları qəbul edilmədi (SQLSTATE 28P01)",
    ).refresh(screen)  # type: ignore[attr-defined]

    assert screen.failure_reasons == ["Baza bağlantı məlumatları qəbul edilmədi (SQLSTATE 28P01)"]


def test_the_console_shows_no_reason_on_a_healthy_machine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Səbəb verilməyibsə ekrana BOŞ sətir gedir — zolaq gizli qalır.

    Bu, «ancaq error verəndə səbəbini göstər» tələbinin İKİNCİ yarısıdır:
    işlək maşında açılan konsol qırmızı zolaq göstərsəydi, texnik olmayan
    nasazlıq axtarardı.
    """
    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    _stub_stored_settings(monkeypatch)
    screen = _RecoveryScreen()

    RecoveryConsoleController(authenticated=True).refresh(screen)  # type: ignore[attr-defined]

    assert screen.failure_reasons == [""]


def test_the_reason_survives_a_settings_read_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """`load_settings()` çökdükdə də səbəb qoyulur — `return` ondan SONRADIR.

    Bu sıra qəsdlidir: konfiqurasiya faylı oxunmayan maşın MƏHZ səbəbi ən çox
    ehtiyac duyulan haldır və `refresh()` orada erkən qayıdır.
    """
    from src.infrastructure.config import connection_file
    from src.presentation.controllers.recovery_console import RecoveryConsoleController

    def _boom() -> None:
        raise _SqlStateError("28P01", "parol rədd edildi")

    monkeypatch.setattr(connection_file, "load_settings", _boom)
    screen = _RecoveryScreen()

    RecoveryConsoleController(authenticated=False, failure_reason="səbəb").refresh(  # type: ignore[attr-defined]
        screen
    )

    assert screen.failure_reasons == ["səbəb"]
    assert screen.errors, "oxunma xətası ayrıca göstərilməlidir"


@requires_qt
def test_the_screen_hides_the_reason_label_when_the_text_is_empty(qt_app) -> None:  # type: ignore[no-untyped-def]
    """Ekran qatı: boş mətn = GÖRÜNMƏZ etiket (boş qırmızı zolaq olmasın)."""
    from src.presentation.screens.recovery_console import RecoveryConsoleScreen
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    _ = qt_app
    screen = RecoveryConsoleScreen(ThemeManager(preference=ThemeMode.LIGHT))

    assert not screen._failure.isVisible()

    screen.set_failure_reason("SQLSTATE 3D000 — belə baza yoxdur")
    screen.show()
    assert screen._failure.isVisible()
    assert screen._failure.text() == "SQLSTATE 3D000 — belə baza yoxdur"

    screen.set_failure_reason("")
    assert not screen._failure.isVisible()
    screen.close()


@requires_qt
def test_opening_the_console_passes_the_stored_startup_reason(  # type: ignore[no-untyped-def]
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Örtük SAXLADIĞI səbəbi kontrollerə ÖTÜRÜR — zəncirin son halqası."""
    from src.presentation.controllers import recovery_console as controller_module

    application = _application(qt_app)
    application._startup_failure_reason = "Baza bağlantısı qurula bilmədi (SQLSTATE 08006)"
    seen: dict[str, Any] = {}

    class _Spy:
        def __init__(self, **kwargs: Any) -> None:
            seen.update(kwargs)

        def attach(self, screen: Any) -> None:
            seen["attached"] = screen

    monkeypatch.setattr(controller_module, "RecoveryConsoleController", _Spy)

    application.show_recovery_console(authenticated=False)

    assert seen["failure_reason"] == "Baza bağlantısı qurula bilmədi (SQLSTATE 08006)"
    assert seen["authenticated"] is False
