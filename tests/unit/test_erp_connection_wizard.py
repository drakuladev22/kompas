"""1C Bağlantı Sihirbazının üç-konnektorlu GUI-si — 1c.md «UX/UI TƏLƏBLƏRİ».

──────────────────────────────────────────────────────────────────────────────
NİYƏ İKİ TƏBƏQƏ AYRICA YOXLANILIR
──────────────────────────────────────────────────────────────────────────────
`test_export_preflight_screen.py` naxışı:

    * KÖMƏKÇİ funksiyalar (`_draft_from`, `_server_view`,
      `_missing_fields_message`) Qt TƏLƏB ETMİR — sahtə sözlüklərlə çağırılır;
    * sihirbazın ÖZÜ (`ServerConnectionWizard`) Qt tələb edir və HƏR İKİ
      temada qurulur, çünki dizayn qapısı hər iki rejimi tələb edir.

`.exec()` HEÇ VAXT çağırılmır (layihə boyu heç bir test bunu etmir): modal
event loop-u avtomatik bağlayan heç nə yoxdur.

──────────────────────────────────────────────────────────────────────────────
ƏSAS REQRESSİYA: `_split_host_port` TƏLƏSİ
──────────────────────────────────────────────────────────────────────────────
`test_a_windows_path_is_never_parsed_as_host_and_port` xüsusi olaraq bir
qüsuru bağlayır: `C:\\Bazalar\\Ticaret` sətrini «host:port» kimi bölmək host-u
`"C"`-yə çevirərdi. Test funksiyanı ÇAĞIRILDIQDA partlayan bir əvəzediciyə
bağlayır — yəni "təsadüfən düzgün nəticə" ilə həqiqi qorumanı ayırd edir.
"""

from __future__ import annotations

from typing import Any, Final

import pytest

from src.domain.value_objects.erp import ConnectorType
from src.presentation import preview_data
from src.presentation.controllers.erp_servers import (
    _draft_from,
    _missing_fields_message,
    _server_view,
)
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

COM_PATH: Final = r"C:\Bazalar\Ticaret"
FILE_SHARE: Final = r"\\anbar\1c_exchange"


# --------------------------------------------------------------------------- #
# Kontroller köməkçiləri — Qt TƏLƏB ETMİR
# --------------------------------------------------------------------------- #


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "1C-BAKI-03",
        "connector_type": "HTTP",
        "host": "10.20.1.16:1541",
        "database": "kompas_prod",
        "username": "sync",
        "password": "gizli",
        "sync_interval": "",
        "config": {},
    }
    payload.update(overrides)
    return payload


def test_the_http_draft_still_splits_host_and_port() -> None:
    """Mövcud HTTP yolu DƏYİŞMİR — sihirbaz tək «Ünvan» sahəsi soruşur."""
    draft = _draft_from(_payload())

    assert draft is not None
    assert (draft.host, draft.port) == ("10.20.1.16", 1541)
    assert draft.connector_type is ConnectorType.HTTP


def test_a_windows_path_is_never_parsed_as_host_and_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REQRESSİYA: COM/FILE yolunda `_split_host_port` ÇAĞIRILMAMALIDIR."""
    from src.presentation import composition

    def _explode(*_args: Any, **_kwargs: Any) -> tuple[str, int]:
        raise AssertionError("`_split_host_port` qeyri-HTTP növdə çağırılmamalıdır")

    monkeypatch.setattr(composition, "_split_host_port", _explode)

    com = _draft_from(_payload(connector_type="COM", host=COM_PATH, database="ticaret", config={}))
    file_exchange = _draft_from(
        _payload(connector_type="FILE_EXCHANGE", host=FILE_SHARE, database="", config={})
    )

    assert com is not None
    assert (com.host, com.port) == (COM_PATH, 0)
    assert file_exchange is not None
    assert (file_exchange.host, file_exchange.port) == (FILE_SHARE, 0)
    # Ünvan ekranda da bütöv qalır — port sentineli görünmür.
    assert file_exchange.display_address == FILE_SHARE


def test_the_com_draft_carries_its_connector_config() -> None:
    """Növə xas parametrlər `connector_config`-ə düşür, sütunlara YOX."""
    draft = _draft_from(
        _payload(
            connector_type="COM",
            host=COM_PATH,
            database="ticaret",
            config={"file_mode": True, "query_language": "RU", "query_source": "Документ.Х"},
        )
    )

    assert draft is not None
    assert draft.connector_type is ConnectorType.COM
    assert draft.connector_config.text("query_source") == "Документ.Х"
    assert draft.connector_config.flag("file_mode") is True


def test_the_file_draft_does_not_require_an_infobase() -> None:
    """Fayl mübadiləsində 1C bazası ilə birbaşa əlaqə YOXDUR."""
    draft = _draft_from(
        _payload(
            connector_type="FILE_EXCHANGE",
            host=FILE_SHARE,
            database="",
            config={"file_format": "CSV", "date_column": "Дата"},
        )
    )

    assert draft is not None
    assert draft.infobase == ""
    assert draft.connector_config.text("date_column") == "Дата"
    # Dövr verilməyibsə TİPİN defoltu tətbiq olunur (gecədə bir dəfə).
    assert draft.sync_interval_seconds is None
    assert draft.effective_sync_interval_seconds == (
        ConnectorType.FILE_EXCHANGE.default_sync_interval_seconds
    )


def test_a_com_file_mode_server_may_omit_the_infobase() -> None:
    """`File="…"` rejimində `Ref=` ümumiyyətlə yazılmır — forma bloklanmamalıdır."""
    assert _draft_from(_payload(connector_type="COM", host=COM_PATH, database="")) is None
    draft = _draft_from(
        _payload(connector_type="COM", host=COM_PATH, database="", config={"file_mode": True})
    )
    assert draft is not None


def test_the_missing_field_message_names_the_field_of_the_selected_type() -> None:
    """Fayl serverində «baza adı» sahəsi YOXDUR — mesaj onu tələb etməməlidir."""
    file_message = _missing_fields_message(_payload(connector_type="FILE_EXCHANGE", host=""))
    assert ConnectorType.FILE_EXCHANGE.address_label_az in file_message
    assert "baza adı" not in file_message

    http_message = _missing_fields_message(_payload(host=""))
    assert "baza adı" in http_message


def test_the_sync_interval_travels_from_the_form_to_the_draft() -> None:
    draft = _draft_from(_payload(sync_interval="900"))
    assert draft is not None
    assert draft.sync_interval_seconds == 900


def test_the_list_row_shows_the_connector_type_and_the_latency_meaning() -> None:
    """Siyahı sətri: tip çipi + gecikmənin MƏNASI (1c.md UX tələbi 4 və əlavə)."""
    row = {
        "id": "x",
        "server_name": "1C-SUMQAYIT-01",
        "host": FILE_SHARE,
        "port": 0,
        "connector_type": "FILE_EXCHANGE",
        "mapped_stores": 2,
        "health": "HEALTHY",
        "sync_delay_seconds": 45,
    }

    view = _server_view(row)

    assert view["type"] == ConnectorType.FILE_EXCHANGE.label_az
    assert view["latency_meaning"] == ConnectorType.FILE_EXCHANGE.latency_meaning_az
    # Port sentineli ünvana YAPIŞMIR.
    assert view["address"] == FILE_SHARE


def test_the_preview_rows_use_the_same_keys_as_the_live_rows() -> None:
    """Maket və canlı yol EYNİ AÇARLARI işlədir (CLAUDE.md bölmə 6)."""
    live = _server_view(
        {
            "id": "x",
            "server_name": "1C-BAKI-01",
            "host": "10.20.1.14",
            "port": 1541,
            "connector_type": "HTTP",
            "mapped_stores": 9,
            "health": "HEALTHY",
            "sync_delay_seconds": 42,
        }
    )

    for mock_row in preview_data.ERP_SERVERS:
        assert set(mock_row) == set(live)
    # Nişan mətnləri də eynidir — əks halda maketdə düzgün, istehsalatda
    # neytral rəngli çip alınardı.
    labels = {connector.label_az for connector in ConnectorType}
    assert {str(row["type"]) for row in preview_data.ERP_SERVERS} <= labels


class _StoredConfig:
    """`credentials_for()` nəticəsinin sihirbaza lazım olan hissəsi."""

    def __init__(self, values: dict[str, Any]) -> None:
        from src.domain.value_objects.erp import ConnectorConfig

        self.connector_config = ConnectorConfig(values=values)


class _ConfigRepository:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values
        self.calls: list[Any] = []

    def credentials_for(self, server_id: Any) -> _StoredConfig:
        self.calls.append(server_id)
        return _StoredConfig(self.values)


class _ConfigSession:
    def __init__(self, repository: _ConfigRepository) -> None:
        self.erp_server_configs = repository


class _ConfigContext:
    def __init__(self, session: _ConfigSession) -> None:
        self._session = session

    def session(self, *, user_id: Any = None) -> Any:
        from contextlib import contextmanager

        @contextmanager
        def _open() -> Any:
            yield self._session

        return _open()


def _controller(repository: _ConfigRepository) -> Any:
    import uuid

    from src.presentation.controllers.erp_servers import ErpServersController

    actor = type("_Actor", (), {"id": uuid.uuid4()})()
    return ErpServersController(_ConfigContext(_ConfigSession(repository)), actor)  # type: ignore[arg-type]


def test_the_edit_payload_loads_the_config_without_any_secret() -> None:
    """Redaktə formasına növ/konfiqurasiya gəlir, ŞİFRƏ isə GƏLMİR (SEC-013)."""
    repository = _ConfigRepository(
        {"folder": FILE_SHARE, "date_column": "Дата", "password": "gizli"}
    )
    controller = _controller(repository)
    row = {
        "id": "server-1",
        "server_name": "1C-SUMQAYIT-01",
        "connector_type": "FILE_EXCHANGE",
        "host": FILE_SHARE,
        "infobase": "",
        "username": "",
        "sync_interval_seconds": 86400,
    }

    payload = controller._existing_payload(row)

    assert payload["connector_type"] == "FILE_EXCHANGE"
    assert payload["sync_interval"] == "86400"
    assert payload["config"]["date_column"] == "Дата"
    assert repository.calls == ["server-1"]
    assert "password" not in payload
    assert "password" not in payload["config"]
    assert "gizli" not in str(payload)


def test_an_unreadable_config_still_opens_the_edit_form() -> None:
    """Zədəli sətir redaktəni BAĞLAMIR — sahələr sadəcə boş qalır."""

    class _Broken(_ConfigRepository):
        def credentials_for(self, server_id: Any) -> _StoredConfig:
            raise RuntimeError("şifrələmə açarı dəyişib")

    controller = _controller(_Broken({}))

    payload = controller._existing_payload(
        {
            "id": "server-2",
            "server_name": "1C-BAKI-01",
            "connector_type": "HTTP",
            "host": "10.20.1.14",
            "infobase": "kompas_prod",
            "username": "sync",
            "sync_interval_seconds": 300,
        }
    )

    assert payload["config"] == {}
    assert payload["host"] == "10.20.1.14"


# --------------------------------------------------------------------------- #
# Sihirbazın ÖZÜ — Qt tələb edir, HƏR İKİ TEMA
# --------------------------------------------------------------------------- #


@pytest.fixture(params=["light", "dark"])
def theme(request, qt_app):  # type: ignore[no-untyped-def]
    """Dizayn qapısı: sihirbaz HƏR İKİ temada qurulmalıdır."""
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    mode = ThemeMode.LIGHT if request.param == "light" else ThemeMode.DARK
    manager = ThemeManager(preference=mode)
    manager.apply(qt_app)
    return manager


def _wizard(theme: Any, qtbot: Any, *, system_name: str = "Windows") -> Any:
    from src.presentation.screens.group_d import ServerConnectionWizard

    wizard = ServerConnectionWizard(theme, system_name=system_name)
    qtbot.addWidget(wizard)
    return wizard


@requires_qt
def test_three_cards_are_shown_with_texts_from_the_domain(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """UX tələbi 1: üç kart, mətnlər DOMENDƏN (ekranda hardcode YOXDUR)."""
    from PySide6.QtWidgets import QLabel

    wizard = _wizard(theme, qtbot)

    assert set(wizard._cards) == set(ConnectorType)
    for connector_type, card in wizard._cards.items():
        texts = [label.text() for label in card.findChildren(QLabel)]
        assert connector_type.label_az in texts
        assert connector_type.card_description_az in texts


@requires_qt
def test_the_selected_card_is_marked_by_more_than_colour(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Rəng TƏK siqnal deyil: `selected` xüsusiyyəti + görünən işarə."""
    wizard = _wizard(theme, qtbot)

    http_card = wizard._cards[ConnectorType.HTTP]
    file_card = wizard._cards[ConnectorType.FILE_EXCHANGE]
    assert http_card.property("selected") == "true"
    assert http_card._mark.isVisibleTo(http_card) is True
    assert file_card._mark.isVisibleTo(file_card) is False

    wizard._on_card_clicked(ConnectorType.FILE_EXCHANGE.value)

    assert file_card.property("selected") == "true"
    assert http_card.property("selected") == "false"
    assert file_card._mark.isVisibleTo(file_card) is True


@requires_qt
def test_the_port_field_exists_only_for_http(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """UX tələbi: port YALNIZ HTTP-də mənalıdır (`ConnectorType.uses_port`)."""
    wizard = _wizard(theme, qtbot)
    wizard._name.set_text("1C-TEST")

    wizard._address[ConnectorType.HTTP].set_text("10.20.1.16:1541")
    wizard._database.set_text("kompas_prod")
    http_draft = _draft_from(wizard.collected())
    assert http_draft is not None
    assert http_draft.port == 1541

    wizard._on_card_clicked(ConnectorType.FILE_EXCHANGE.value)
    wizard._address[ConnectorType.FILE_EXCHANGE].set_text(FILE_SHARE)
    file_draft = _draft_from(wizard.collected())
    assert file_draft is not None
    assert file_draft.port == 0
    # Formadan gələn sətir də port daşımır — «Ünvan» etiketi növə görə dəyişir.
    assert wizard.collected()["host"] == FILE_SHARE


@requires_qt
def test_switching_types_keeps_the_values_already_typed(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """UX tələbi 2: tip dəyişib geri qayıdanda dəyərlər İTMİR."""
    wizard = _wizard(theme, qtbot)

    wizard._address[ConnectorType.HTTP].set_text("10.20.1.16:1541")
    wizard._database.set_text("kompas_prod")

    wizard._on_card_clicked(ConnectorType.FILE_EXCHANGE.value)
    wizard._address[ConnectorType.FILE_EXCHANGE].set_text(FILE_SHARE)
    wizard._config_inputs[ConnectorType.FILE_EXCHANGE]["date_column"].set_text("Дата")

    wizard._on_card_clicked(ConnectorType.HTTP.value)
    assert wizard.collected()["host"] == "10.20.1.16:1541"
    assert wizard.collected()["database"] == "kompas_prod"

    wizard._on_card_clicked(ConnectorType.FILE_EXCHANGE.value)
    collected = wizard.collected()
    assert collected["host"] == FILE_SHARE
    assert collected["config"]["date_column"] == "Дата"


@requires_qt
def test_the_com_card_is_unavailable_with_a_reason_outside_windows(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """UX tələbi 1: kart GİZLƏNMİR — səbəb yazılır və klik siqnal yaymır."""
    from src.domain.value_objects.erp import ErpPlatformError

    wizard = _wizard(theme, qtbot, system_name="Linux")
    com_card = wizard._cards[ConnectorType.COM]

    assert com_card.is_available is False
    assert com_card.property("unavailable") == "true"
    assert ErpPlatformError.user_message in com_card.toolTip()

    emitted: list[str] = []
    com_card.clicked.connect(emitted.append)
    com_card._activate()
    assert emitted == []
    assert wizard.selected_type() == ConnectorType.HTTP.value

    # Windows-da isə eyni kart normal seçilir.
    windows_wizard = _wizard(theme, qtbot)
    assert windows_wizard._cards[ConnectorType.COM].is_available is True


@requires_qt
def test_the_test_result_is_shown_verbatim_with_its_technical_detail(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """UX tələbi 3: konkret səbəb OLDUĞU KİMİ, generic mesaj YOX."""
    wizard = _wizard(theme, qtbot)
    reason = "«D:\\exchange» qovluğu tapılmadı — yolu yoxlayın və ya şəbəkə diskini qoşun."
    detail = "tapılan sütunlar: ['Дата', 'Склад']"

    wizard.set_busy(True)
    assert wizard._test_button.isEnabled() is False
    assert wizard._result.text() == "Yoxlanılır…"
    assert wizard._spinner.isVisibleTo(wizard) is True

    wizard.set_test_result(ok=False, message=reason, detail=detail)

    assert wizard._result.text() == reason
    assert wizard._result_detail.text() == detail
    assert wizard._result_detail.isVisibleTo(wizard) is True
    assert wizard._test_button.isEnabled() is True
    assert wizard._spinner.isVisibleTo(wizard) is False


@requires_qt
def test_a_successful_test_reports_success(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    wizard = _wizard(theme, qtbot)

    wizard.set_test_result(ok=True, message="Bağlantı uğurludur")

    assert wizard._result.text() == "Bağlantı uğurludur"
    assert wizard._result_detail.isVisibleTo(wizard) is False
    assert wizard._result_icon.isVisibleTo(wizard) is True


@requires_qt
def test_editing_loads_the_stored_type_config_and_interval(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Redaktə axını: növ, konfiqurasiya və dövr formaya yüklənir."""
    wizard = _wizard(theme, qtbot)

    wizard.load(
        {
            "name": "1C-SUMQAYIT-01",
            "connector_type": "FILE_EXCHANGE",
            "host": FILE_SHARE,
            "database": "",
            "username": "",
            "sync_interval": "86400",
            "config": {
                "file_format": "XML",
                "record_tag": "Документ",
                "date_column": "Дата",
                "amount_column": "Сумма",
            },
        }
    )

    assert wizard.selected_type() == ConnectorType.FILE_EXCHANGE.value
    collected = wizard.collected()
    assert collected["name"] == "1C-SUMQAYIT-01"
    assert collected["host"] == FILE_SHARE
    assert collected["sync_interval"] == "86400"
    assert collected["config"]["record_tag"] == "Документ"
    assert collected["config"]["file_format"] == "XML"
    # Şifrə GERİ QAYTARILMIR (SEC-013) — sahə boş açılır.
    assert collected["password"] == ""


@requires_qt
def test_changing_the_type_while_editing_warns_the_user(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Növ dəyişikliyi sükutla baş vermir — köhnə konfiqurasiya işləməyəcək."""
    wizard = _wizard(theme, qtbot)
    wizard.load(
        {
            "name": "1C-BAKI-01",
            "connector_type": "HTTP",
            "host": "10.20.1.14:1541",
            "database": "kompas_prod",
            "username": "sync",
            "sync_interval": "300",
            "config": {},
        }
    )
    assert wizard._type_notice.isVisibleTo(wizard) is False

    wizard._on_card_clicked(ConnectorType.FILE_EXCHANGE.value)

    assert wizard._type_notice.isVisibleTo(wizard) is True
    assert ConnectorType.HTTP.label_az in wizard._type_notice.text()
    assert ConnectorType.FILE_EXCHANGE.label_az in wizard._type_notice.text()


@requires_qt
def test_an_unnamed_or_addressless_server_is_not_emitted(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Boş forma siqnal yaymır — səbəb sahənin ALTINDA göstərilir."""
    wizard = _wizard(theme, qtbot)
    emitted: list[dict[str, Any]] = []
    wizard.saved.connect(emitted.append)

    wizard._on_save()
    assert emitted == []
    assert wizard._name.has_error is True

    wizard._name.set_text("1C-TEST")
    wizard._on_save()
    assert emitted == []
    assert wizard._address[ConnectorType.HTTP].has_error is True

    wizard._address[ConnectorType.HTTP].set_text("10.20.1.16:1541")
    wizard._on_save()
    assert len(emitted) == 1
    assert emitted[0]["connector_type"] == ConnectorType.HTTP.value


# --------------------------------------------------------------------------- #
# Bağlantı testinin FON İCRASI — `presentation/background_task.py`
# --------------------------------------------------------------------------- #
#
# Naxışın ÖZÜ `test_background_task.py`-də yoxlanılır; burada onun ERP
# axınına düzgün BAĞLANDIĞI yoxlanılır: sessiya fon işində açılır, köhnəlmiş
# cavab ekrana düşmür, bağlanmış sihirbaz çökmə yaratmır.
#
# Heç bir `sleep` yoxdur — `_HeldExecutor` işi saxlayır və testin özü onu
# istədiyi anda icra edir (qeyri-sabit test heç bir testdən pisdir).


class _HeldExecutor:
    """İşi SAXLAYAN icraçı — «cavab hələ gəlməyib» halını determinstik qurur."""

    def __init__(self) -> None:
        self.jobs: list[Any] = []

    @property
    def runs_inline(self) -> bool:
        return True

    def submit(self, job: Any) -> None:
        self.jobs.append(job)

    def deliver(self, index: int = 0) -> None:
        self.jobs.pop(index)()


class _TestConnections:
    """`session.erp_connections` əvəzedicisi — YALNIZ `test_connection`."""

    def __init__(self, behaviour: Any, session: _TestSession) -> None:
        self._behaviour = behaviour
        self._session = session

    def test_connection(self, *, actor: Any, draft: Any, now: Any) -> Any:
        self._session.tested.append(draft)
        return self._behaviour()


class _TestSession:
    def __init__(self, behaviour: Any) -> None:
        self.erp_connections = _TestConnections(behaviour, self)
        self.tested: list[Any] = []
        self.committed = False
        self.closed = False

    def commit(self) -> None:
        self.committed = True


class _TestContext:
    """Hər `session()` çağırışına YENİ sessiya verir (paylaşılan obyekt yoxdur)."""

    def __init__(self, behaviour: Any) -> None:
        self._behaviour = behaviour
        self.opened: list[_TestSession] = []

    def session(self, *, user_id: Any = None) -> Any:
        from contextlib import contextmanager

        @contextmanager
        def _open() -> Any:
            session = _TestSession(self._behaviour)
            self.opened.append(session)
            try:
                yield session
            finally:
                session.closed = True

        return _open()


def _result(ok: bool, message: str, detail: str = "") -> Any:
    from src.domain.value_objects.erp import ConnectionTestResult

    return ConnectionTestResult(ok=ok, message=message, detail=detail)


def _bound_wizard(theme: Any, qtbot: Any, behaviour: Any) -> tuple[Any, Any, Any, Any]:
    """Ekran + sihirbaz + kontroller + saxlanan icraçı — REAL bağlantı zənciri ilə."""
    import uuid

    from src.presentation.controllers.erp_servers import ErpServersController
    from src.presentation.screens.group_d import ErpServersScreen

    executor = _HeldExecutor()
    context = _TestContext(behaviour)
    actor = type("_Actor", (), {"id": uuid.uuid4()})()
    controller = ErpServersController(context, actor, executor=executor)  # type: ignore[arg-type]

    screen = ErpServersScreen(theme)
    qtbot.addWidget(screen)
    wizard = _wizard(theme, qtbot)
    controller._bind_wizard(screen, wizard, server_id=None)

    wizard._name.set_text("1C-TEST")
    wizard._address[ConnectorType.HTTP].set_text("10.20.1.16:1541")
    wizard._database.set_text("kompas_prod")
    return wizard, executor, context, controller


@requires_qt
def test_the_ui_stays_responsive_while_the_connection_test_runs(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """1c.md UX tələbi 3: deaktiv düymə + spinner + «Yoxlanılır…».

    Cavab HƏLƏ GƏLMƏYİB, lakin idarə artıq GUI sapına qayıdıb (iş növbədə
    gözləyir) — donma məhz bununla aradan qalxır. Sihirbaz və sahələr aktiv
    qalır: istifadəçi test gedərkən yaza və pəncərəni bağlaya bilər.
    """
    wizard, executor, _context, _controller = _bound_wizard(
        theme, qtbot, lambda: _result(True, "Bağlantı uğurludur")
    )

    wizard._test_button.click()

    assert len(executor.jobs) == 1  # iş qaçır, nəticə yoxdur
    assert wizard._test_button.isEnabled() is False
    assert wizard._test_button.text() == "Yoxlanılır…"
    assert wizard._result.text() == "Yoxlanılır…"
    assert wizard._spinner.isVisibleTo(wizard) is True
    # Spinner FAKTİKİ fırlanır: taymer işləyir və hadisə dövrü boş deyil.
    assert wizard._spinner._timer.isActive() is True
    # İnterfeys cavab verir — sahələr redaktə olunabilən qalır.
    assert wizard.isEnabled() is True
    assert wizard._name.isEnabled() is True


@requires_qt
def test_a_second_test_cannot_be_started_while_one_is_running(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """İkiqat işə salma İKİ qatda bağlanıb: deaktiv düymə + `is_running`."""
    wizard, executor, _context, _controller = _bound_wizard(
        theme, qtbot, lambda: _result(True, "Bağlantı uğurludur")
    )

    wizard._test_button.click()
    wizard._test_button.click()  # deaktiv düymə — siqnal yaymır
    # Klaviatura qısayolu düymənin deaktivliyini yan keçə bilər; kontroller
    # onu da rədd etməlidir.
    wizard.test_requested.emit(wizard.collected())

    assert len(executor.jobs) == 1


@requires_qt
def test_a_successful_test_reports_success_in_the_success_colour(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Uğur: yaşıl nişan + «Bağlantı uğurludur»; düymə yenidən aktivdir."""
    wizard, executor, context, _controller = _bound_wizard(
        theme, qtbot, lambda: _result(True, "Bağlantı uğurludur")
    )

    wizard._test_button.click()
    executor.deliver()

    assert wizard._result.text() == "Bağlantı uğurludur"
    assert theme.color("--color-success") in wizard._result.styleSheet()
    assert wizard._result_icon.isVisibleTo(wizard) is True
    assert wizard._test_button.isEnabled() is True
    assert wizard._spinner.isVisibleTo(wizard) is False
    # Test heç nə YAZMIR — commit çağırılmır (bax `test_connection` docstring-i).
    assert context.opened[0].committed is False


@requires_qt
def test_a_failed_test_shows_the_concrete_reason_verbatim(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Uğursuzluq: qırmızı nişan + KONKRET səbəb + xam texniki detal."""
    reason = "«D:\\exchange» qovluğu tapılmadı — yolu yoxlayın və ya şəbəkə diskini qoşun."
    detail = "HRESULT: 0x80004005"
    wizard, executor, _context, _controller = _bound_wizard(
        theme, qtbot, lambda: _result(False, reason, detail)
    )

    wizard._test_button.click()
    executor.deliver()

    # Mətn OLDUĞU KİMİ — ümumiləşdirilmir, kəsilmir.
    assert wizard._result.text() == reason
    assert wizard._result_detail.text() == detail
    assert wizard._result_detail.isVisibleTo(wizard) is True
    assert theme.color("--color-danger") in wizard._result.styleSheet()


@requires_qt
def test_a_domain_error_inside_the_worker_reaches_the_user(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Fon sapındakı domen istisnası SÜKUTLA UDULMUR — mətni ekrana çatır."""
    from src.shared.exceptions import KompasOSError

    def _deny() -> Any:
        raise KompasOSError(
            "no permission", user_message="Bu əməliyyat üçün səlahiyyətiniz yoxdur."
        )

    wizard, executor, _context, _controller = _bound_wizard(theme, qtbot, _deny)

    wizard._test_button.click()
    executor.deliver()

    assert wizard._result.text() == "Bu əməliyyat üçün səlahiyyətiniz yoxdur."
    assert wizard._test_button.isEnabled() is True


@requires_qt
def test_an_unexpected_error_inside_the_worker_never_leaks_its_text(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Gözlənilməz istisna: aydın mesaj göstərilir, xam mətn ekrana DÜŞMÜR.

    İstisna mətnində DSN və ya şifrə ola bilər (`error.log`-a yazılır, ekrana
    yox) — lakin istifadəçi «heç nə baş vermədi» vəziyyətində qalmır.
    """

    def _explode() -> Any:
        raise RuntimeError("dsn=postgres://user:parol@host/db")

    wizard, executor, _context, _controller = _bound_wizard(theme, qtbot, _explode)

    wizard._test_button.click()
    executor.deliver()

    assert wizard._result.text() == "Bağlantı yoxlanıla bilmədi. Yenidən cəhd edin."
    assert "parol" not in wizard._result.text()
    assert wizard._result_detail.isVisibleTo(wizard) is False
    assert wizard._test_button.isEnabled() is True


@requires_qt
def test_the_background_job_opens_its_own_session(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Sessiya SAPLAR ARASINDA PAYLAŞILMIR — iş onu ÖZÜ açır və bağlayır.

    Sessiya `_on_test()` çağırılanda YOX, iş İCRA olunanda yaranır: yəni o,
    fon sapının içində qurulur. `psycopg` bağlantısı sap-təhlükəsiz deyil,
    ona görə bu, sadəcə üslub deyil — düzgünlük şərtidir.
    """
    wizard, executor, context, _controller = _bound_wizard(
        theme, qtbot, lambda: _result(True, "Bağlantı uğurludur")
    )

    wizard._test_button.click()
    assert context.opened == []  # iş hələ qaçmayıb — sessiya da yoxdur

    executor.deliver()

    assert len(context.opened) == 1
    assert context.opened[0].closed is True  # sessiya işin içində bağlandı
    assert len(context.opened[0].tested) == 1

    # İKİNCİ test YENİ sessiya açır — birincisi təkrar işlədilmir.
    wizard._test_button.click()
    executor.deliver()
    assert len(context.opened) == 2
    assert context.opened[0] is not context.opened[1]


@requires_qt
def test_a_stale_answer_never_overwrites_the_newer_one(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Köhnəlmiş cavab ekranı KORLAMIR (nəsil sayğacı).

    Ssenari: istifadəçi testi başladır, cavab gecikir, sihirbazı bağlayır və
    yenidən açıb ikinci testi başladır. Birinci (köhnə) cavab bundan SONRA
    gəlir — o, ikinci testin nəticəsini əvəz etməməlidir.
    """
    # Sıra İCRA sırasıdır, buraxılış sırası YOX: aşağıda əvvəl İKİNCİ iş icra
    # olunur (o, tez cavab verən serverdir), sonra birinci — «gec gələn cavab»
    # ssenarisi məhz budur.
    answers = iter(
        [
            _result(True, "Bağlantı uğurludur"),
            _result(False, "KÖHNƏ CAVAB — göstərilməməlidir"),
        ]
    )
    wizard, executor, _context, _controller = _bound_wizard(theme, qtbot, lambda: next(answers))

    wizard._test_button.click()
    wizard.reject()  # sihirbaz bağlandı → gözlənilən nəticə ləğv edildi
    # Sihirbaz yenidən açılır və test təkrar işə salınır. Düymə hələ
    # «Yoxlanılır…» halındadır, ona görə siqnal birbaşa yayılır — bu, məhz
    # klaviatura qısayolunun getdiyi yoldur (düyməni yan keçir).
    wizard.test_requested.emit(wizard.collected())
    assert len(executor.jobs) == 2

    executor.deliver(1)  # ikinci cavab əvvəl gəlir
    assert wizard._result.text() == "Bağlantı uğurludur"

    executor.deliver(0)  # birincinin gec gələn cavabı
    assert wizard._result.text() == "Bağlantı uğurludur"


@requires_qt
def test_closing_the_wizard_mid_test_neither_crashes_nor_writes(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Sihirbaz test bitmədən bağlanır: çökmə YOXDUR, nəticə tətbiq OLUNMUR.

    Pəncərə əvvəlcə GÖSTƏRİLİR, çünki `QDialog.closeEvent` yalnız görünən
    dialoqda `reject()` çağırır — gizli pəncərənin `close()`-u `finished`
    yaymır və test yoxlamaq istədiyi yolu ümumiyyətlə keçməzdi.
    """
    wizard, executor, context, _controller = _bound_wizard(
        theme, qtbot, lambda: _result(False, "Server cavab vermir (timeout)")
    )
    wizard.show()

    wizard._test_button.click()
    wizard.close()  # istifadəçi «X» ilə bağladı → `finished` → `cancel()`

    executor.deliver()  # çökməməlidir

    # İş İCRA OLUNDU (sap kəsilmir), lakin ekran toxunulmadan qalır.
    assert len(context.opened) == 1
    assert wizard._result.text() == "Yoxlanılır…"
    assert "Server cavab vermir" not in wizard._result.text()


@requires_qt
def test_an_incomplete_form_never_starts_a_background_job(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """Natamam forma: səbəb DƏRHAL göstərilir, sap ümumiyyətlə açılmır."""
    wizard, executor, context, _controller = _bound_wizard(
        theme, qtbot, lambda: _result(True, "Bağlantı uğurludur")
    )
    wizard._name.set_text("")

    wizard._test_button.click()

    assert executor.jobs == []
    assert context.opened == []
    assert "Server adı" in wizard._result.text()


@requires_qt
def test_the_server_list_renders_a_type_chip(qtbot, theme) -> None:  # type: ignore[no-untyped-def]
    """UX tələbi 4: sətirdə növ çipi — mətnlə birlikdə, təkcə rəng deyil."""
    from src.presentation.screens.group_d import ErpServersScreen
    from src.presentation.widgets.primitives import Chip

    screen = ErpServersScreen(theme)
    qtbot.addWidget(screen)

    screen.set_servers(list(preview_data.ERP_SERVERS), mapped_stores=21)

    chips = [chip.text() for chip in screen.findChildren(Chip)]
    assert ConnectorType.HTTP.label_az in chips
    assert ConnectorType.COM.label_az in chips
    assert ConnectorType.FILE_EXCHANGE.label_az in chips
    # Gecikmə rəqəminin mənası cədvəlin altında izah olunur.
    legend = screen._latency_legend.text()
    # İzah DOMENDƏN olduğu kimi gəlir — akronim («COM…») korlanmır.
    assert ConnectorType.FILE_EXCHANGE.latency_meaning_az in legend
    assert ConnectorType.COM.latency_meaning_az in legend
    assert screen._latency_legend.isVisibleTo(screen) is True
