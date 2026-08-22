"""`CatalogScreen` (İş Rejimləri / Cərimə Növləri / İcazə Növləri) ↔
`CatalogAdminController` — REAL Qt e2e sınaqları.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL LAZIM İDİ (QA-FULL Faza 3, üçüncü dalğa)
──────────────────────────────────────────────────────────────────────────────
Üç kataloq üçün `test_catalog_admin_controller.py`-da nə varsa sahtə `_Screen`
sinfi ilə ölçülür — REAL `group_h.CatalogScreen`, REAL "Yeni ...", "Redaktə",
"Deaktiv Et"/"Aktivləşdir" düymələri və REAL `CatalogEntryDialog` heç vaxt
qurulmur. Burada onlar əl ilə klikllənir. `_build_*` funksiyalarının çağırdığı
`WorkMode`/`FineType`/`LeaveType` DOMEN sinifləri SAHTƏLƏNMİR — beləliklə
domen validasiyası (ad uzunluğu, mənfi məbləğ, `Money` tavanı, icazə müddəti
tavanı) REAL kodla, real dialoq inputu ilə işə düşür. Yalnız use case
(`session.work_modes`/`fine_types`/`leave_types`) sahtələnir — eyni sərhəd
`test_pos_threshold_screen_e2e.py`-də işlədilib.

──────────────────────────────────────────────────────────────────────────────
"SOFT DELETE" NEC NƏ SINANIR
──────────────────────────────────────────────────────────────────────────────
`domain/value_objects/catalogs.py` başlığı: `delete()` QƏSDƏN yoxdur, yalnız
`deactivate()`. Bura görə: (1) "Deaktiv Et" kliki `use_case.deactivate()`
çağırır, `save()` YOX; (2) deaktiv edilmiş sətir idarəetmə siyahısından
ÇIXMIR — sadəcə "Deaktiv" nişanı ilə qalır (bax `refresh()` başlığı: "Deaktiv
sətirlər DƏ göstərilir ki, yenidən aktivləşdirilə bilsin"); (3) üç domen
sinfinin heç birində `delete` metodu yoxdur — statik yoxlama aşağıda.
"""

from __future__ import annotations

import dataclasses
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from datetime import time as dtime
from decimal import Decimal
from typing import Any

import pytest

from src.domain.value_objects.catalogs import FineType, LeaveType, WorkMode
from src.domain.value_objects.money import Money
from src.domain.value_objects.scheduling import TimeRange
from src.presentation.controllers.catalog_admin import CATALOG_KEYS
from src.shared.exceptions import KompasOSError
from tests.conftest import requires_qt

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
ACTOR_ID = uuid.uuid4()

# Root ceiling-i DEFOLT (720 dəq, `DEFAULT_LIMITS`) ilə QƏSDƏN FƏRQLİDİR —
# testin uğuru "canlı `session.limits` oxunur" faktına bağlıdırsa, fallback-la
# üst-üstə düşən dəyər bunu gizlədərdi.
ROOT_LEAVE_CEILING_MINUTES = 480


@pytest.fixture
def theme(qt_app):  # type: ignore[no-untyped-def]
    from src.presentation.theme.manager import ThemeManager
    from src.presentation.theme.tokens import ThemeMode

    manager = ThemeManager(preference=ThemeMode.LIGHT)
    manager.apply(qt_app)
    return manager


def _click(widget: Any, text: str) -> None:
    from PySide6.QtWidgets import QPushButton

    button = next(b for b in widget.findChildren(QPushButton) if b.text() == text)
    button.click()


class _Actor:
    id = ACTOR_ID


# --------------------------------------------------------------------------- #
# Sahtələr — YALNIZ use case sərhədi. Domen tipləri REAL qalır.
# --------------------------------------------------------------------------- #


class _FakeCatalogUseCase:
    """`session.work_modes`/`fine_types`/`leave_types`-in yerini tutur.

    `list_for_management`/`save`/`deactivate` REAL use case-in imzasını
    təkrarlayır. Yaddaşda saxlanan `entries` REAL domen obyektləridir — fake
    yalnız "DB"ni təqlid edir, domen QAYDASINI yox.
    """

    def __init__(self, *, entries: list[Any] | None = None, id_field: str) -> None:
        self.entries: list[Any] = list(entries or [])
        self.id_field = id_field
        self.saves: list[Any] = []
        self.deactivates: list[Any] = []
        self.list_error: KompasOSError | None = None
        self.save_error: KompasOSError | None = None
        self.deactivate_error: KompasOSError | None = None

    def list_for_management(self, _tenant_id: Any, _actor: Any) -> list[Any]:
        if self.list_error is not None:
            raise self.list_error
        return list(self.entries)

    def save(self, _tenant_id: Any, _actor: Any, entry: Any) -> None:
        if self.save_error is not None:
            raise self.save_error
        current_id = getattr(entry, self.id_field)
        if current_id is None:
            # Real repository-nin `ON CONFLICT ... DO UPDATE`-i YENİ sətrə
            # identifikator təyin edir — burada eyni davranış təqlid olunur.
            entry = dataclasses.replace(entry, **{self.id_field: uuid.uuid4()})
            current_id = getattr(entry, self.id_field)
        self.entries = [e for e in self.entries if getattr(e, self.id_field) != current_id]
        self.entries.append(entry)
        self.saves.append(entry)

    def deactivate(self, _tenant_id: Any, _actor: Any, identifier: Any) -> None:
        if self.deactivate_error is not None:
            raise self.deactivate_error
        self.deactivates.append(identifier)
        self.entries = [
            (
                dataclasses.replace(e, is_active=False, deactivated_at=datetime.now(UTC))
                if getattr(e, self.id_field) == identifier
                else e
            )
            for e in self.entries
        ]


class _Limits:
    def __init__(self, ceiling: int = ROOT_LEAVE_CEILING_MINUTES) -> None:
        self._ceiling = ceiling

    def get_int(self, _tenant_id: Any, _key: str, _fallback: int) -> int:
        return self._ceiling


class _Session:
    def __init__(self, use_case: Any, key: str, limits: Any) -> None:
        self.tenant_id = TENANT
        self.limits = limits
        self.committed = False
        setattr(self, key, use_case)

    def commit(self) -> None:
        self.committed = True


class _Context:
    def __init__(self, use_case: Any, key: str, *, limits: Any = None) -> None:
        self._use_case = use_case
        self._key = key
        self._limits = limits or _Limits()
        self.sessions: list[_Session] = []

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        created = _Session(self._use_case, self._key, self._limits)
        self.sessions.append(created)
        yield created


def _attach(key: str, use_case: _FakeCatalogUseCase, *, qtbot: Any, theme: Any, limits: Any = None):
    from src.presentation.controllers.catalog_admin import CatalogAdminController
    from src.presentation.screens import group_h

    screen_factory = {
        "work_modes": group_h.work_modes_screen,
        "fine_types": group_h.fine_types_screen,
        "leave_types": group_h.leave_types_screen,
    }[key]
    screen = screen_factory(theme)
    qtbot.addWidget(screen)
    context = _Context(use_case, key, limits=limits)
    CatalogAdminController(context, _Actor(), key=key).attach(screen)
    return screen, context


# --------------------------------------------------------------------------- #
# Domen sətri qurucuları — üçün eyni ada malikdirlər, İMZALARI FƏRQLİDİR.
# --------------------------------------------------------------------------- #


def _work_mode(
    *,
    active: bool = True,
    name: str = "08:00–17:00",
    work_mode_id: Any = None,
    deactivated_at: Any = None,
) -> WorkMode:
    return WorkMode(
        name=name,
        tenant_id=TENANT,
        is_active=active,
        deactivated_at=deactivated_at,
        work_mode_id=work_mode_id or uuid.uuid4(),
        schedule=TimeRange(dtime(8, 0), dtime(17, 0)),
    )


def _fine_type(
    *,
    active: bool = True,
    name: str = "Gecikmə",
    amount: Decimal = Decimal("50"),
    fine_type_id: Any = None,
    deactivated_at: Any = None,
) -> FineType:
    return FineType(
        name=name,
        tenant_id=TENANT,
        is_active=active,
        deactivated_at=deactivated_at,
        fine_type_id=fine_type_id or uuid.uuid4(),
        standard_amount=Money(amount),
    )


def _leave_type(
    *,
    active: bool = True,
    name: str = "Nahar Fasiləsi",
    minutes: int = 45,
    leave_type_id: Any = None,
    deactivated_at: Any = None,
) -> LeaveType:
    return LeaveType(
        name=name,
        tenant_id=TENANT,
        is_active=active,
        deactivated_at=deactivated_at,
        leave_type_id=leave_type_id or uuid.uuid4(),
        default_duration_minutes=minutes,
    )


#: Hər kataloqun ekran/dialoq fərqləri — parametrizasiya üçün.
_CATALOGS: dict[str, dict[str, Any]] = {
    "work_modes": {
        "id_field": "work_mode_id",
        "domain_cls": WorkMode,
        "factory": _work_mode,
        "create_label": "Yeni İş Rejimi",
        "valid_value": "09:00–18:00",
    },
    "fine_types": {
        "id_field": "fine_type_id",
        "domain_cls": FineType,
        "factory": _fine_type,
        "create_label": "Yeni Cərimə Növü",
        "valid_value": "75.50",
    },
    "leave_types": {
        "id_field": "leave_type_id",
        "domain_cls": LeaveType,
        "factory": _leave_type,
        "create_label": "Yeni İcazə Növü",
        "valid_value": "30",
    },
}


def _submit_dialog(monkeypatch: pytest.MonkeyPatch, *, name: str, value: str) -> None:
    """Real `CatalogEntryDialog`-un `exec()`-ini "Yadda saxla" real kliki ilə əvəzləyir."""
    from PySide6.QtWidgets import QPushButton

    from src.presentation.screens.group_h import CatalogEntryDialog

    def fake_exec(self: CatalogEntryDialog) -> int:
        self._name.set_text(name)
        self._value.set_text(value)
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Yadda saxla")
        submit.click()
        return 0

    monkeypatch.setattr(CatalogEntryDialog, "exec", fake_exec)


# --------------------------------------------------------------------------- #
# 0. Açar pariteti — CLAUDE.md bölmə 6: maket və canlı yol EYNİ açarları işlədir
# --------------------------------------------------------------------------- #


def test_catalog_keys_match_the_controller_adapters_and_the_screen_factories() -> None:
    from src.presentation.controllers import catalog_admin as mod
    from src.presentation.screens import group_h

    assert CATALOG_KEYS == ("work_modes", "fine_types", "leave_types")
    assert set(mod._ADAPTERS) == set(CATALOG_KEYS)
    assert set(_CATALOGS) == set(CATALOG_KEYS)
    for key in CATALOG_KEYS:
        assert hasattr(group_h, f"{key}_screen")


def test_none_of_the_three_domain_classes_expose_a_delete_method() -> None:
    """`delete()` QƏSDƏN yoxdur (bax `catalogs.py` başlığı) — statik sübut."""
    for config in _CATALOGS.values():
        assert not hasattr(config["domain_cls"], "delete")


# --------------------------------------------------------------------------- #
# 1. Real siyahı — `attach()` REAL `list_for_management` çağırır
# --------------------------------------------------------------------------- #


@requires_qt
@pytest.mark.parametrize("key", CATALOG_KEYS)
def test_attach_loads_the_real_list_and_shows_both_active_and_inactive_rows(
    qtbot, theme, key: str
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.widgets.data_table import DataTable

    config = _CATALOGS[key]
    entries = [
        config["factory"](active=True),
        config["factory"](active=False, deactivated_at=datetime.now(UTC)),
    ]
    use_case = _FakeCatalogUseCase(entries=entries, id_field=config["id_field"])
    screen, _ = _attach(key, use_case, qtbot=qtbot, theme=theme)

    assert screen.switcher().current_state() == "content"
    table = screen.findChild(DataTable)
    assert table is not None
    assert table.row_count == 2


# --------------------------------------------------------------------------- #
# 2. Real "Yeni ..." → real dialoq → real "Yadda saxla"
# --------------------------------------------------------------------------- #


@requires_qt
@pytest.mark.parametrize("key", CATALOG_KEYS)
def test_the_real_create_button_opens_the_dialog_and_saves_via_a_real_click(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:  # type: ignore[no-untyped-def]
    config = _CATALOGS[key]
    use_case = _FakeCatalogUseCase(entries=[], id_field=config["id_field"])
    screen, context = _attach(key, use_case, qtbot=qtbot, theme=theme)

    _submit_dialog(monkeypatch, name="Yeni Sətir", value=config["valid_value"])
    _click(screen, config["create_label"])

    assert len(use_case.saves) == 1
    assert use_case.saves[0].name == "Yeni Sətir"
    assert any(s.committed for s in context.sessions)
    # Hər əməliyyat ÖZ sessiyasında: yazı sessiyası + yazıdan sonrakı `refresh()`
    # sessiyası + `attach()`-in ilkin oxu sessiyası = 3 (bax modul başlığı).
    assert len(context.sessions) == 3
    assert len(use_case.entries) == 1


#: Açar → (dialoq başlığı, dəyər sahəsinin etiketi) — üç kataloqun EYNİ
#: `CatalogEntryDialog` sinfindən fərqli mətnlər aldığını göstərir.
_EXPECTED_DIALOG_TEXT: dict[str, tuple[str, str]] = {
    "work_modes": ("Yeni İş Rejimi", "Saat aralığı"),
    "fine_types": ("Yeni Cərimə Növü", "Standart məbləğ (AZN)"),
    "leave_types": ("Yeni İcazə Növü", "Tövsiyə olunan müddət (dəqiqə)"),
}


@requires_qt
@pytest.mark.parametrize("key", CATALOG_KEYS)
def test_create_dialog_titles_and_value_labels_do_not_bleed_between_catalogs(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:  # type: ignore[no-untyped-def]
    """Üç kataloq EYNİ `CatalogEntryDialog` sinfini işlədir (bax modul başlığı)
    — açarın SƏHV adapterə düşməməsi burada AÇIQ yoxlanılır."""
    from src.presentation.screens.group_h import CatalogEntryDialog

    title, value_label = _EXPECTED_DIALOG_TEXT[key]
    config = _CATALOGS[key]
    use_case = _FakeCatalogUseCase(entries=[], id_field=config["id_field"])
    screen, _ = _attach(key, use_case, qtbot=qtbot, theme=theme)

    captured: list[CatalogEntryDialog] = []
    original_init = CatalogEntryDialog.__init__

    def _spy_init(self: CatalogEntryDialog, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        captured.append(self)

    monkeypatch.setattr(CatalogEntryDialog, "__init__", _spy_init)
    monkeypatch.setattr(CatalogEntryDialog, "exec", lambda self: 0)

    _click(screen, config["create_label"])

    assert len(captured) == 1
    assert captured[0].windowTitle() == title
    assert captured[0]._value_label == value_label


# --------------------------------------------------------------------------- #
# 3. Real "Redaktə" — real dialoq ÖNCƏDƏN doldurulur
# --------------------------------------------------------------------------- #


@requires_qt
@pytest.mark.parametrize("key", CATALOG_KEYS)
def test_the_real_edit_button_prefills_the_dialog_and_saves_the_change(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:  # type: ignore[no-untyped-def]
    from src.presentation.screens.group_h import CatalogEntryDialog

    config = _CATALOGS[key]
    existing = config["factory"](active=True, name="Köhnə Ad")
    use_case = _FakeCatalogUseCase(entries=[existing], id_field=config["id_field"])
    screen, context = _attach(key, use_case, qtbot=qtbot, theme=theme)

    captured: list[CatalogEntryDialog] = []
    prefilled_names: list[str] = []
    original_init = CatalogEntryDialog.__init__

    def _spy_init(self: CatalogEntryDialog, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        captured.append(self)
        prefilled_names.append(self._name.text())  # üstündən yazmazdan ƏVVƏL qeyd olunur
        self._name.set_text("Yeni Ad")
        self._value.set_text(config["valid_value"])

    monkeypatch.setattr(CatalogEntryDialog, "__init__", _spy_init)

    def fake_exec(self: CatalogEntryDialog) -> int:
        from PySide6.QtWidgets import QPushButton

        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Yadda saxla")
        submit.click()
        return 0

    monkeypatch.setattr(CatalogEntryDialog, "exec", fake_exec)

    _click(screen, "Redaktə")

    assert prefilled_names == ["Köhnə Ad"]  # dialoq DƏYİŞDİRMƏDƏN öncə köhnə adı göstərib
    assert len(use_case.saves) == 1
    assert use_case.saves[0].name == "Yeni Ad"
    assert use_case.saves[0].is_active is True  # redaktə aktivliyi TOXUNMUR (bax `_save` başlığı)
    assert any(s.committed for s in context.sessions)


# --------------------------------------------------------------------------- #
# 4. Real "Deaktiv Et" / "Aktivləşdir" — SOFT DELETE
# --------------------------------------------------------------------------- #


@requires_qt
@pytest.mark.parametrize("key", CATALOG_KEYS)
def test_deactivate_calls_deactivate_not_save_and_the_row_stays_in_the_list(
    qtbot, theme, key: str
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    config = _CATALOGS[key]
    existing = config["factory"](active=True)
    identifier = getattr(existing, config["id_field"])
    use_case = _FakeCatalogUseCase(entries=[existing], id_field=config["id_field"])
    screen, context = _attach(key, use_case, qtbot=qtbot, theme=theme)

    _click(screen, "Deaktiv et")

    assert use_case.deactivates == [identifier]
    assert use_case.saves == []  # FİZİKİ SİLMƏ CƏHDİ YOXDUR — yalnız `deactivate()`
    assert any(s.committed for s in context.sessions)
    # Soft delete: sətir siyahıdan ÇIXMIR, YALNIZ "Deaktiv" olur.
    assert len(use_case.entries) == 1
    assert use_case.entries[0].is_active is False
    assert getattr(use_case.entries[0], config["id_field"]) == identifier
    assert "Aktivləşdir" in [b.text() for b in screen.findChildren(QPushButton)]


@requires_qt
@pytest.mark.parametrize("key", CATALOG_KEYS)
def test_reactivate_calls_save_with_a_freshly_built_entry_not_a_separate_method(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:  # type: ignore[no-untyped-def]
    """`toggle_requested`-in deaktiv→aktiv qolu `save()`-i UPSERT kimi işlədir
    (bax `catalog_admin.py`-`_on_toggle` başlığı — ayrıca "reactivate" YOXDUR)."""
    config = _CATALOGS[key]
    existing = config["factory"](active=False, deactivated_at=datetime.now(UTC))
    identifier = getattr(existing, config["id_field"])
    use_case = _FakeCatalogUseCase(entries=[existing], id_field=config["id_field"])
    screen, context = _attach(key, use_case, qtbot=qtbot, theme=theme)

    _click(screen, "Aktivləşdir")

    assert use_case.deactivates == []
    assert len(use_case.saves) == 1
    assert use_case.saves[0].is_active is True
    assert use_case.saves[0].deactivated_at is None
    assert getattr(use_case.saves[0], config["id_field"]) == identifier
    assert any(s.committed for s in context.sessions)


@requires_qt
def test_a_rapid_double_click_on_deactivate_resolves_from_fresh_state_not_the_stale_label(
    qtbot, theme
) -> None:  # type: ignore[no-untyped-def]
    """Sürətli ikiqat klik: ikinci klik EYNİ (artıq `deleteLater()`-lənmiş, lakin
    Python tərəfdə hələ canlı) düymə obyektinə düşür. Kontroller `self._entries`-i
    HƏR toggle-da yenilədiyi üçün ikinci klik "Deaktiv Et" DEYİL, TƏZƏ vəziyyətə
    görə "Aktivləşdir" kimi həll olunur — TƏKRAR deaktivasiya YAZILMIR."""
    config = _CATALOGS["work_modes"]
    existing = config["factory"](active=True)
    identifier = getattr(existing, config["id_field"])
    use_case = _FakeCatalogUseCase(entries=[existing], id_field=config["id_field"])
    screen, _ = _attach("work_modes", use_case, qtbot=qtbot, theme=theme)

    from PySide6.QtWidgets import QPushButton

    stale_button = next(b for b in screen.findChildren(QPushButton) if b.text() == "Deaktiv et")
    stale_button.click()  # 1-ci klik: deaktiv edir, cədvəl YENİDƏN qurulur
    stale_button.click()  # 2-ci klik: EYNİ (artıq dəyişdirilmiş) Python obyektinə

    assert use_case.deactivates == [identifier]  # BİR dəfə deaktiv
    assert len(use_case.saves) == 1  # ikinci klik AKTİVLƏŞDİRMƏ kimi həll olundu
    assert use_case.saves[0].is_active is True
    assert use_case.entries[0].is_active is True  # son vəziyyət: yenidən aktiv


# --------------------------------------------------------------------------- #
# 5. Səlahiyyət qapısı — flag yoxdursa YAZI düymələri əlçatan deyil
# --------------------------------------------------------------------------- #


@requires_qt
@pytest.mark.parametrize("key", CATALOG_KEYS)
def test_permission_denied_shows_an_error_state_and_hides_the_write_buttons(
    qtbot, theme, key: str
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton

    config = _CATALOGS[key]
    use_case = _FakeCatalogUseCase(entries=[], id_field=config["id_field"])
    use_case.list_error = KompasOSError(
        "flag yoxdur", user_message="Bu kataloqu dəyişdirmək səlahiyyətiniz yoxdur."
    )
    screen, _ = _attach(key, use_case, qtbot=qtbot, theme=theme)

    assert screen.switcher().current_state() == "error"
    # `QStackedWidget` köhnə səhifəni SİLMİR (yalnız cari səhifəni dəyişir),
    # ona görə "Yeni ..." düyməsi `findChildren`-də HƏLƏ DƏ var — lakin
    # görünməzdir, çünki stack-in cari widget-i artıq xəta vəziyyətidir.
    screen.show()
    qtbot.waitExposed(screen)
    create = next(b for b in screen.findChildren(QPushButton) if b.text() == config["create_label"])
    assert not create.isVisible()


# --------------------------------------------------------------------------- #
# 6. Ekstremal input — HƏR kataloq üçün AYRI (mesajlar/qaydalar fərqlidir)
# --------------------------------------------------------------------------- #


@requires_qt
def test_work_mode_a_malformed_schedule_is_rejected_without_a_crash(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    use_case = _FakeCatalogUseCase(entries=[], id_field="work_mode_id")
    screen, _ = _attach("work_modes", use_case, qtbot=qtbot, theme=theme)

    _submit_dialog(monkeypatch, name="Sınaq Rejimi", value="filan vaxt")
    _click(screen, "Yeni İş Rejimi")  # ÇÖKMƏMƏLİDİR

    assert use_case.saves == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_work_mode_free_shift_keyword_is_accepted_as_no_fixed_schedule(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    use_case = _FakeCatalogUseCase(entries=[], id_field="work_mode_id")
    screen, _ = _attach("work_modes", use_case, qtbot=qtbot, theme=theme)

    _submit_dialog(monkeypatch, name="Növbəli 2/2", value="sərbəst")
    _click(screen, "Yeni İş Rejimi")

    assert len(use_case.saves) == 1
    assert use_case.saves[0].schedule is None


@requires_qt
def test_fine_type_a_negative_amount_is_rejected_by_domain_validation(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    use_case = _FakeCatalogUseCase(entries=[], id_field="fine_type_id")
    screen, _ = _attach("fine_types", use_case, qtbot=qtbot, theme=theme)

    _submit_dialog(monkeypatch, name="Sınaq Cərimə", value="-50")
    _click(screen, "Yeni Cərimə Növü")  # ÇÖKMƏMƏLİDİR

    assert use_case.saves == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_fine_type_an_amount_beyond_the_money_ceiling_does_not_crash(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    use_case = _FakeCatalogUseCase(entries=[], id_field="fine_type_id")
    screen, _ = _attach("fine_types", use_case, qtbot=qtbot, theme=theme)

    huge = "9" * 20
    _submit_dialog(monkeypatch, name="Sınaq Cərimə", value=huge)
    _click(screen, "Yeni Cərimə Növü")  # ÇÖKMƏMƏLİDİR (`Money` MAX_AMOUNT rəddi)

    assert use_case.saves == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_fine_type_sql_like_text_in_the_amount_field_is_rejected_as_a_bad_decimal(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    use_case = _FakeCatalogUseCase(entries=[], id_field="fine_type_id")
    screen, _ = _attach("fine_types", use_case, qtbot=qtbot, theme=theme)

    _submit_dialog(monkeypatch, name="Sınaq Cərimə", value="1; DROP TABLE fine_types; --")
    _click(screen, "Yeni Cərimə Növü")  # ÇÖKMƏMƏLİDİR, İCRA OLUNMUR

    assert use_case.saves == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_fine_type_an_emoji_name_and_an_oversized_name_are_handled_without_a_crash(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    use_case = _FakeCatalogUseCase(entries=[], id_field="fine_type_id")
    screen, _ = _attach("fine_types", use_case, qtbot=qtbot, theme=theme)

    # Emoji: uzunluq MAX_NAME_LENGTH altındadır, ona görə QƏBUL edilməlidir —
    # bura yalnız ÇÖKMƏDİYİNİ sübut edir, məzmunu senzuralamır.
    _submit_dialog(monkeypatch, name="🔥 Təcili Cərimə 🔥", value="20")
    _click(screen, "Yeni Cərimə Növü")
    assert len(use_case.saves) == 1
    assert use_case.saves[0].name == "🔥 Təcili Cərimə 🔥"

    # 10 000+ simvol: `MAX_NAME_LENGTH=120` aşılır — rədd edilir, ÇÖKMÜR.
    _submit_dialog(monkeypatch, name="a" * 10_000, value="20")
    _click(screen, "Yeni Cərimə Növü")
    assert len(use_case.saves) == 1  # ikinci cəhd YAZILMADI
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_a_whitespace_only_name_is_blocked_by_the_dialog_before_any_write(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Boş/yalnız-boşluq ad `CatalogEntryDialog._on_submit`-də TUTULUR —
    `submitted` heç YAYILMIR, kontrollerə çatmır, YENİ sessiya AÇILMIR."""
    from src.presentation.screens.group_h import CatalogEntryDialog

    use_case = _FakeCatalogUseCase(entries=[], id_field="fine_type_id")
    screen, context = _attach("fine_types", use_case, qtbot=qtbot, theme=theme)
    sessions_before = len(context.sessions)

    def fake_exec(self: CatalogEntryDialog) -> int:
        from PySide6.QtWidgets import QPushButton

        self._name.set_text("   ")
        self._value.set_text("20")
        submit = next(b for b in self.findChildren(QPushButton) if b.text() == "Yadda saxla")
        submit.click()
        assert self._name.has_error
        return self.reject()

    monkeypatch.setattr(CatalogEntryDialog, "exec", fake_exec)
    _click(screen, "Yeni Cərimə Növü")

    assert use_case.saves == []
    assert len(context.sessions) == sessions_before  # yazı yolu HEÇ İŞƏ DÜŞMƏDİ


@requires_qt
def test_leave_type_zero_minutes_is_valid_and_negative_minutes_is_rejected(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    use_case = _FakeCatalogUseCase(entries=[], id_field="leave_type_id")
    screen, _ = _attach("leave_types", use_case, qtbot=qtbot, theme=theme)

    _submit_dialog(monkeypatch, name="Müddətsiz İcazə", value="0")
    _click(screen, "Yeni İcazə Növü")
    assert len(use_case.saves) == 1
    assert use_case.saves[0].default_duration_minutes == 0

    _submit_dialog(monkeypatch, name="Mənfi İcazə", value="-45")
    _click(screen, "Yeni İcazə Növü")  # ÇÖKMƏMƏLİDİR
    assert len(use_case.saves) == 1  # ikinci cəhd yazılmadı


@requires_qt
def test_leave_type_minutes_beyond_the_live_root_ceiling_is_rejected_without_a_crash(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    """Tavan `session.limits`-dən (CANLI) oxunur — ekranın öz sabiti YOX
    (bax `_root_leave_duration_ceiling` başlığı)."""
    use_case = _FakeCatalogUseCase(entries=[], id_field="leave_type_id")
    screen, _ = _attach(
        "leave_types", use_case, qtbot=qtbot, theme=theme, limits=_Limits(ceiling=60)
    )

    _submit_dialog(monkeypatch, name="Uzun İcazə", value="61")
    _click(screen, "Yeni İcazə Növü")  # ÇÖKMƏMƏLİDİR — 60 dəq tavanı aşır

    assert use_case.saves == []
    assert screen.switcher().current_state() == "error"


@requires_qt
def test_leave_type_non_numeric_minutes_text_is_rejected(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    use_case = _FakeCatalogUseCase(entries=[], id_field="leave_type_id")
    screen, _ = _attach("leave_types", use_case, qtbot=qtbot, theme=theme)

    _submit_dialog(monkeypatch, name="Sınaq İcazə", value="qırx beş dəqiqə")
    _click(screen, "Yeni İcazə Növü")  # ÇÖKMƏMƏLİDİR

    assert use_case.saves == []
    assert screen.switcher().current_state() == "error"


# --------------------------------------------------------------------------- #
# 7. Repo istisnası — real klik, açıq mesaj, sükutla üstündən yazma yoxdur
# --------------------------------------------------------------------------- #


@requires_qt
@pytest.mark.parametrize("key", CATALOG_KEYS)
def test_a_use_case_failure_on_save_shows_the_domain_message_and_does_not_commit(
    qtbot, theme, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:  # type: ignore[no-untyped-def]
    config = _CATALOGS[key]
    use_case = _FakeCatalogUseCase(entries=[], id_field=config["id_field"])
    use_case.save_error = KompasOSError(
        "hardlock", user_message="Bu əməliyyat üçün əlavə təsdiq lazımdır."
    )
    screen, context = _attach(key, use_case, qtbot=qtbot, theme=theme)

    _submit_dialog(monkeypatch, name="Sətir", value=config["valid_value"])
    _click(screen, config["create_label"])  # ÇÖKMƏMƏLİDİR

    assert use_case.saves == []
    assert not any(s.committed for s in context.sessions)
    assert screen.switcher().current_state() == "error"
