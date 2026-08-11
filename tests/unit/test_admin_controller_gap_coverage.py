"""Plugin və İcazə Matrisi kontrollerlərinin əhatəsiz yolları — Faza 6 auditi.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU İKİSİ
──────────────────────────────────────────────────────────────────────────────
Hər ikisi ən HƏSSAS yazı yollarıdır:

    * plugin quraşdırma → sistemə YENİ KOD gətirir; imzasız/manifest-siz
      paketin qəbulu bütün təhlükəsizlik zəncirini yan keçərdi;
    * icazə matrisi     → hardlock, anti-fraud, SEC-001 və Self-Escalation
      qoruyucularının hamısı məhz bu ekrandan keçir.

Mövcud testlər (`test_phase56_write_controllers.py`, `test_permission_matrix_
controller.py`) əsas axını yoxlayır. Burada YALNIZ çatışan hissə var: paket
yanındakı fayllar, manifest çevirməsi, siyahının rədd sonrası yenilənməsi və
matrisin qruplaşdırma qaydası.

Qt hadisə dövrəsi TƏLƏB OLUNMUR — ekranlar duck-typing ilə əvəzlənir.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

import pytest

from src.domain.value_objects.authorization import (
    HardlockLevel,
    PermissionFlag,
    RolePriority,
)
from src.domain.value_objects.identifiers import EmployeeId, PositionId, TenantId
from src.infrastructure.plugins.contracts import PluginCapability
from src.presentation.controllers.permission_matrix import (
    OTHER_CATEGORY,
    PermissionMatrixController,
    _flag_groups,
)
from src.presentation.controllers.plugin_admin import (
    MANIFEST_SUFFIX,
    SIGNATURE_SUFFIX,
    PluginAdminController,
    _read_sidecars,
    _to_manifest,
)
from src.shared.exceptions import KompasOSError

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.uuid4())


class _DeniedError(KompasOSError):
    user_message = "Bu əməliyyat üçün səlahiyyətiniz yoxdur."


def _actor() -> Any:
    return type("_Actor", (), {"id": EmployeeId(uuid.uuid4())})()


class _Context:
    def __init__(self, session: Any) -> None:
        self._session = session
        self.opened = 0

    @contextmanager
    def session(self, *, user_id: Any = None) -> Any:
        self.opened += 1
        yield self._session


# --------------------------------------------------------------------------- #
# Paket yanındakı fayllar (`plugin_admin._read_sidecars`)
# --------------------------------------------------------------------------- #


def _write_package(tmp_path: Path, *, manifest: Any = None, signature: str | None = None) -> Path:
    package = tmp_path / "bridge.py"
    package.write_text("# plugin", encoding="utf-8")
    if manifest is not None:
        target = package.with_suffix(package.suffix + MANIFEST_SUFFIX)
        target.write_text(
            manifest if isinstance(manifest, str) else json.dumps(manifest), encoding="utf-8"
        )
    if signature is not None:
        package.with_suffix(package.suffix + SIGNATURE_SUFFIX).write_text(
            signature, encoding="utf-8"
        )
    return package


_VALID_MANIFEST = {
    "name": "kompas-erp-bridge",
    "version": "1.2.0",
    "publisher": "KompasOS",
    "capabilities": ["read_aggregated_metrics"],
    "entry_point": "bridge:main",
    "description_az": "1C körpüsü",
    "required_flags": ["can_export_reports"],
}


def test_a_missing_manifest_names_the_file_the_user_must_find(tmp_path: Path) -> None:
    """«İmza uyğun gəlmir» mesajı YANLIŞ səbəb göstərərdi (modul başlığı)."""
    package = _write_package(tmp_path, signature="aa")

    with pytest.raises(KompasOSError) as raised:
        _read_sidecars(package)

    assert "bridge.py.manifest.json" in raised.value.user_message


def test_a_missing_signature_file_stops_the_install(tmp_path: Path) -> None:
    package = _write_package(tmp_path, manifest=_VALID_MANIFEST)

    with pytest.raises(KompasOSError) as raised:
        _read_sidecars(package)

    assert "bridge.py.sig" in raised.value.user_message
    assert "imzasız paket qəbul edilmir" in raised.value.user_message


def test_a_malformed_manifest_is_reported_as_invalid_json(tmp_path: Path) -> None:
    package = _write_package(tmp_path, manifest="{ bu json deyil", signature="aa")

    with pytest.raises(KompasOSError, match="Manifest oxunmadı"):
        _read_sidecars(package)


def test_a_valid_package_yields_the_manifest_and_a_trimmed_signature(tmp_path: Path) -> None:
    """İmza faylındakı sətir sonu hex-i pozardı — kənar boşluqlar kəsilir."""
    package = _write_package(tmp_path, manifest=_VALID_MANIFEST, signature="  ab12cd\n")

    manifest, signature = _read_sidecars(package)

    assert signature == "ab12cd"
    assert manifest.name == "kompas-erp-bridge"
    assert manifest.version == "1.2.0"
    assert manifest.capabilities == frozenset({PluginCapability.READ_AGGREGATED_METRICS})
    assert manifest.required_flags == frozenset({"can_export_reports"})


def test_an_unknown_capability_is_named_in_the_error() -> None:
    """İstifadəçi hansı dəyərin yanlış olduğunu ADBAAD bilməlidir."""
    raw = dict(_VALID_MANIFEST, capabilities=["read_aggregated_metrics", "delete_everything"])

    with pytest.raises(KompasOSError) as raised:
        _to_manifest(raw)

    assert "delete_everything" in raised.value.user_message


def test_a_non_object_manifest_root_is_refused() -> None:
    """Sərhəd: JSON massivi və ya sətir — kök obyekt OLMALIDIR."""
    with pytest.raises(KompasOSError, match="kök obyekt olmalıdır"):
        _to_manifest([1, 2, 3])


def test_a_manifest_without_capabilities_is_refused_by_the_domain_invariant() -> None:
    """Sərhəd: boş `capabilities` — heç nə edə bilməyən plugin MƏNASIZDIR.

    Qayda `PluginManifest.__post_init__`-dədir; kontroller onu təkrarlamır,
    yalnız istisnanı olduğu kimi buraxır (hər ikisi `PluginError`-dur).
    """
    with pytest.raises(KompasOSError, match="capability"):
        _to_manifest({"name": "x", "version": "1.0.0", "publisher": "P", "entry_point": "m:run"})


def test_optional_manifest_fields_default_to_empty_values() -> None:
    """`description_az` və `required_flags` MƏCBURİ deyil — sətir çökməməlidir."""
    manifest = _to_manifest(
        {
            "name": "x",
            "version": "1.0.0",
            "publisher": "P",
            "entry_point": "m:run",
            "capabilities": ["render_widget"],
        }
    )

    assert manifest.description_az == ""
    assert manifest.required_flags == frozenset()
    assert manifest.capabilities == frozenset({PluginCapability.RENDER_WIDGET})


# --------------------------------------------------------------------------- #
# Plugin siyahısı və yazı dövrəsi
# --------------------------------------------------------------------------- #


class _PluginRow:
    def __init__(self, plugin_id: str, *, enabled: bool = True) -> None:
        self.plugin_id = plugin_id
        self.enabled = enabled

    def as_row(self) -> dict[str, str]:
        return {"id": self.plugin_id, "name": "Körpü", "enabled": str(self.enabled)}


class _PluginScreen:
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.fills = 0

    def set_plugins(self, plugins: list[dict[str, str]]) -> None:
        self.rows = plugins
        self.fills += 1

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _PluginUseCase:
    def __init__(
        self,
        plugins: list[_PluginRow] | None = None,
        *,
        list_error: Exception | None = None,
        remove_error: Exception | None = None,
    ) -> None:
        self.plugins = plugins or []
        self.list_error = list_error
        self.remove_error = remove_error
        self.removed: list[str] = []
        self.toggled: list[tuple[str, bool]] = []

    def list_plugins(self, *, tenant_id: Any, actor: Any) -> list[_PluginRow]:
        if self.list_error is not None:
            raise self.list_error
        return list(self.plugins)

    def set_enabled(self, *, tenant_id: Any, actor: Any, plugin_id: str, enabled: bool) -> None:
        self.toggled.append((plugin_id, enabled))

    def remove(self, *, tenant_id: Any, actor: Any, plugin_id: str) -> None:
        if self.remove_error is not None:
            raise self.remove_error
        self.removed.append(plugin_id)


class _PluginSession:
    def __init__(self, use_case: _PluginUseCase) -> None:
        self.tenant_id = TENANT
        self.plugins = use_case
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _plugin_controller(
    use_case: _PluginUseCase,
) -> tuple[PluginAdminController, _PluginSession]:
    session = _PluginSession(use_case)
    return (
        PluginAdminController(_Context(session), _actor()),  # type: ignore[arg-type]
        session,
    )


def test_the_plugin_list_uses_the_row_contract_of_the_screen() -> None:
    """Kontroller ÖZ sözlüyünü qurmur — ikinci ad məkanı yaranardı."""
    use_case = _PluginUseCase([_PluginRow("pl-1")])
    controller, _ = _plugin_controller(use_case)
    screen = _PluginScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.rows == [{"id": "pl-1", "name": "Körpü", "enabled": "True"}]


def test_a_denied_plugin_list_shows_the_reason_instead_of_an_empty_screen() -> None:
    use_case = _PluginUseCase(list_error=_DeniedError("yalnız Root"))
    controller, _ = _plugin_controller(use_case)
    screen = _PluginScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.rows == []
    assert screen.errors == [("Siyahı açıla bilmədi", "Bu əməliyyat üçün səlahiyyətiniz yoxdur.")]


def test_an_unexpected_plugin_list_failure_hides_the_technical_detail() -> None:
    use_case = _PluginUseCase(list_error=RuntimeError("psycopg: timeout"))
    controller, _ = _plugin_controller(use_case)
    screen = _PluginScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.errors[0][1] == "Plugin siyahısı oxuna bilmədi. Yenidən cəhd edin."
    assert "psycopg" not in screen.errors[0][1]


def test_removing_a_plugin_commits_and_re_reads_the_list() -> None:
    use_case = _PluginUseCase([_PluginRow("pl-1")])
    controller, session = _plugin_controller(use_case)
    screen = _PluginScreen()

    controller._on_remove(screen, "pl-1")  # type: ignore[arg-type]

    assert use_case.removed == ["pl-1"]
    assert session.commits == 1
    assert screen.fills == 1, "Silmədən sonra siyahı yenidən oxunmalıdır"


def test_a_refused_removal_still_refreshes_so_the_screen_does_not_lie() -> None:
    use_case = _PluginUseCase([_PluginRow("pl-1")], remove_error=_DeniedError("icazə yoxdur"))
    controller, session = _plugin_controller(use_case)
    screen = _PluginScreen()

    controller._on_remove(screen, "pl-1")  # type: ignore[arg-type]

    assert use_case.removed == []
    assert session.commits == 0
    assert screen.errors[0][0] == "Plugin silinmədi"
    assert screen.fills == 1, "Rədd edilən dəyişiklikdən SONRA da siyahı yenilənir"


def test_an_unexpected_removal_failure_also_refreshes() -> None:
    use_case = _PluginUseCase([_PluginRow("pl-1")], remove_error=RuntimeError("şəbəkə"))
    controller, session = _plugin_controller(use_case)
    screen = _PluginScreen()

    controller._on_remove(screen, "pl-1")  # type: ignore[arg-type]

    assert session.commits == 0
    assert screen.errors[0][1] == "Dəyişiklik yazılmadı. Yenidən cəhd edin."
    assert screen.fills == 1


# --------------------------------------------------------------------------- #
# İcazə matrisi (`permission_matrix.py`)
# --------------------------------------------------------------------------- #


class _MatrixScreen:
    theme: Any = None

    def __init__(self) -> None:
        self.roles: list[tuple[str, str, int]] = []
        self.matrix: list[tuple[str, Any]] = []
        self.selected: list[str] = []
        self.errors: list[tuple[str, str]] = []

    def set_roles(self, rows: list[tuple[str, str, int]]) -> None:
        self.roles = rows

    def set_matrix(self, role_name: str, groups: Any) -> None:
        self.matrix.append((role_name, groups))

    def select_role(self, code: str) -> None:
        self.selected.append(code)

    def show_error(self, *, title: str, message: str) -> None:
        self.errors.append((title, message))


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _Connection:
    def __init__(self, counts: list[dict[str, Any]], labels: list[dict[str, Any]]) -> None:
        self._counts = counts
        self._labels = labels

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        if "permission_flags" in sql:
            return _Cursor(self._labels)
        return _Cursor(self._counts)


class _FlagRepo:
    def __init__(self, flags: list[PermissionFlag]) -> None:
        self._flags = flags

    def list_all(self) -> list[PermissionFlag]:
        return list(self._flags)


class _MatrixUow:
    def __init__(
        self,
        *,
        counts: list[dict[str, Any]],
        labels: list[dict[str, Any]],
        flags: list[PermissionFlag],
    ) -> None:
        self.connection = _Connection(counts, labels)
        self._flags = _FlagRepo(flags)

    def repository(self, name: str) -> Any:
        return self._flags


class _Summary:
    def __init__(self, position: Any) -> None:
        self.position = position


class _Positions:
    def __init__(
        self,
        summaries: list[_Summary],
        *,
        list_error: Exception | None = None,
        save_error: Exception | None = None,
    ) -> None:
        self.summaries = summaries
        self.list_error = list_error
        self.save_error = save_error
        self.saved: list[tuple[Any, tuple[str, ...]]] = []

    def list_roles(self, *, tenant_id: Any, actor: Any) -> list[_Summary]:
        if self.list_error is not None:
            raise self.list_error
        return list(self.summaries)

    def set_role_flags(
        self, *, tenant_id: Any, actor: Any, position_id: Any, flag_codes: tuple[str, ...]
    ) -> None:
        if self.save_error is not None:
            raise self.save_error
        self.saved.append((position_id, flag_codes))


class _MatrixSession:
    def __init__(self, positions: _Positions, uow: _MatrixUow) -> None:
        self.tenant_id = TENANT
        self.positions = positions
        self.uow = uow
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _FakePosition:
    def __init__(self, code: str, name_az: str, priority: RolePriority, granted: set[str]) -> None:
        self.id = PositionId(uuid.uuid4())
        self.code = code
        self.name_az = name_az
        self.priority = priority
        self.granted_flags = granted


EXPORT = PermissionFlag(code="can_export_reports", category="SISTEM")
HARDLOCKED = PermissionFlag(
    code="can_manage_permissions", category="ICAZE", hardlock=HardlockLevel.ROOT_ONLY
)
UNCATEGORISED = PermissionFlag(code="can_do_thing", category="")


def _matrix(
    *,
    positions: _Positions,
    flags: list[PermissionFlag] | None = None,
    counts: list[dict[str, Any]] | None = None,
    labels: list[dict[str, Any]] | None = None,
) -> tuple[PermissionMatrixController, _MatrixSession]:
    uow = _MatrixUow(
        counts=counts or [],
        labels=labels or [],
        flags=flags if flags is not None else [EXPORT, HARDLOCKED],
    )
    session = _MatrixSession(positions, uow)
    return (
        PermissionMatrixController(_Context(session), _actor()),  # type: ignore[arg-type]
        session,
    )


def test_roles_are_ordered_by_tier_not_alphabetically() -> None:
    """Əlifba sırası «Root» ilə «Satıcı»-nı yan-yana salardı — matris iyerarxikdir."""
    seller = _FakePosition("SATICI", "Satıcı", RolePriority.STAFF, set())
    root = _FakePosition("ROOT", "Root", RolePriority.EXECUTIVE, set())
    admin = _FakePosition("ADMIN", "Admin", RolePriority.ADMIN, set())
    positions = _Positions([_Summary(seller), _Summary(root), _Summary(admin)])
    controller, _ = _matrix(
        positions=positions,
        counts=[{"position_id": str(root.id), "total": 1}],
    )
    screen = _MatrixScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert [row[0] for row in screen.roles] == ["ROOT", "ADMIN", "SATICI"]
    assert screen.roles[0][2] == 1, "Aktiv işçi sayı sol paneldə göstərilir"
    assert screen.roles[1][2] == 0, "Sayğacı olmayan rol SIFIR göstərir"
    assert screen.selected == ["ROOT"], "İlk rol AVTOMATİK seçilir"


def test_a_denied_matrix_shows_the_reason_instead_of_an_empty_grid() -> None:
    """Boş matris «heç bir icazə yoxdur» kimi oxunardı — bu, yanlışdır."""
    positions = _Positions([], list_error=_DeniedError("can_manage_positions yoxdur"))
    controller, _ = _matrix(positions=positions)
    screen = _MatrixScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.roles == []
    assert screen.errors == [("Matris açıla bilmədi", "Bu əməliyyat üçün səlahiyyətiniz yoxdur.")]


def test_an_unexpected_matrix_failure_hides_the_technical_detail() -> None:
    positions = _Positions([], list_error=RuntimeError("psycopg: deadlock"))
    controller, _ = _matrix(positions=positions)
    screen = _MatrixScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.errors[0][1] == "Rol siyahısı oxuna bilmədi. Yenidən cəhd edin."


def test_an_empty_role_list_selects_nothing() -> None:
    """Sərhəd: heç bir rol yoxdur — `select_role` çağırılmır."""
    controller, _ = _matrix(positions=_Positions([]))
    screen = _MatrixScreen()

    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.roles == []
    assert screen.selected == []


def test_selecting_a_role_fills_the_matrix_with_grouped_flags() -> None:
    root = _FakePosition("ROOT", "Root", RolePriority.EXECUTIVE, {EXPORT.code})
    positions = _Positions([_Summary(root)])
    controller, _ = _matrix(
        positions=positions,
        labels=[{"code": EXPORT.code, "name_az": "Hesabat ixracı"}],
    )
    screen = _MatrixScreen()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_role_selected(screen, "ROOT")  # type: ignore[arg-type]

    role_name, groups = screen.matrix[-1]
    assert role_name == "Root"
    flat = {item[0]: item for group in groups for item in group[1]}
    assert flat[EXPORT.code][1] == "Hesabat ixracı"
    assert flat[EXPORT.code][2] is True, "Verilmiş flag işarəli gəlir"
    assert flat[HARDLOCKED.code][2] is False
    assert flat[HARDLOCKED.code][3] is True, "Hardlock xanası ekranda işarələnir"


def test_a_flag_without_a_label_falls_back_to_its_code() -> None:
    """Tərcüməni UYDURMAQ kataloqla ekran arasında ikinci ad məkanı yaradardı."""
    root = _FakePosition("ROOT", "Root", RolePriority.EXECUTIVE, set())
    uow = _MatrixUow(counts=[], labels=[], flags=[EXPORT])
    session = _MatrixSession(_Positions([_Summary(root)]), uow)

    groups = _flag_groups(session, root)  # type: ignore[arg-type]

    assert groups[0][1][0][1] == EXPORT.code


def test_a_flag_without_a_category_lands_in_the_other_group() -> None:
    """Sərhəd: boş kateqoriya — flag GİZLƏNMİR, «Digər» altında görünür."""
    root = _FakePosition("ROOT", "Root", RolePriority.EXECUTIVE, set())
    uow = _MatrixUow(counts=[], labels=[], flags=[UNCATEGORISED])
    session = _MatrixSession(_Positions([_Summary(root)]), uow)

    groups = _flag_groups(session, root)  # type: ignore[arg-type]

    assert [group[0] for group in groups] == [OTHER_CATEGORY]


def test_selecting_an_unknown_role_is_a_no_op() -> None:
    """Siyahı köhnəlibsə matris SƏHV rolla dolmamalıdır."""
    controller, _ = _matrix(positions=_Positions([]))
    screen = _MatrixScreen()

    controller._on_role_selected(screen, "YOXDUR")  # type: ignore[arg-type]

    assert screen.matrix == []
    assert screen.errors == []


def test_only_checked_flags_are_sent_to_the_use_case() -> None:
    """Ekran BÜTÜN xanaları göndərir; yazıya yalnız işarələnənlər gedir."""
    root = _FakePosition("ROOT", "Root", RolePriority.EXECUTIVE, set())
    positions = _Positions([_Summary(root)])
    controller, session = _matrix(positions=positions)
    screen = _MatrixScreen()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_saved(  # type: ignore[arg-type]
        screen, "ROOT", {EXPORT.code: True, HARDLOCKED.code: False}
    )

    assert positions.saved == [(root.id, (EXPORT.code,))]
    assert session.commits == 1


def test_saving_an_empty_selection_clears_every_flag() -> None:
    """Sərhəd: boş dəst «heç nə göndərilmədi» DEYİL, «hamısı silindi» deməkdir."""
    root = _FakePosition("ROOT", "Root", RolePriority.EXECUTIVE, {EXPORT.code})
    positions = _Positions([_Summary(root)])
    controller, session = _matrix(positions=positions)
    screen = _MatrixScreen()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_saved(screen, "ROOT", {})  # type: ignore[arg-type]

    assert positions.saved == [(root.id, ())]
    assert session.commits == 1


def test_saving_a_role_that_vanished_asks_for_a_refresh() -> None:
    controller, session = _matrix(positions=_Positions([]))
    screen = _MatrixScreen()

    controller._on_saved(screen, "YOXDUR", {EXPORT.code: True})  # type: ignore[arg-type]

    assert session.commits == 0
    assert screen.errors[0][0] == "Rol tapılmadı"


def test_a_guard_violation_is_shown_and_the_grid_is_restored() -> None:
    """Hardlock/anti-fraud/SEC-001 rəddi SÜKUTLA udulmamalıdır."""
    root = _FakePosition("ROOT", "Root", RolePriority.EXECUTIVE, set())
    positions = _Positions([_Summary(root)], save_error=_DeniedError("hardlock"))
    controller, session = _matrix(positions=positions)
    screen = _MatrixScreen()
    controller.refresh(screen)  # type: ignore[arg-type]
    selections_before = len(screen.selected)

    controller._on_saved(screen, "ROOT", {HARDLOCKED.code: True})  # type: ignore[arg-type]

    assert session.commits == 0
    assert screen.errors[0] == (
        "İcazələr yazılmadı",
        "Bu əməliyyat üçün səlahiyyətiniz yoxdur.",
    )
    assert len(screen.selected) > selections_before, "Rədd sonrası matris bərpa olunur"


def test_an_unexpected_save_failure_also_restores_the_grid() -> None:
    root = _FakePosition("ROOT", "Root", RolePriority.EXECUTIVE, set())
    positions = _Positions([_Summary(root)], save_error=RuntimeError("bağlantı"))
    controller, session = _matrix(positions=positions)
    screen = _MatrixScreen()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_saved(screen, "ROOT", {EXPORT.code: True})  # type: ignore[arg-type]

    assert session.commits == 0
    assert screen.errors[0][1] == "Dəyişiklik saxlanmadı. Yenidən cəhd edin."


def test_the_selected_role_survives_a_refresh() -> None:
    """Yazıdan sonra admin eyni rolda qalmalıdır — siyahının başına atılmamalıdır."""
    root = _FakePosition("ROOT", "Root", RolePriority.EXECUTIVE, set())
    seller = _FakePosition("SATICI", "Satıcı", RolePriority.STAFF, set())
    positions = _Positions([_Summary(root), _Summary(seller)])
    controller, _ = _matrix(positions=positions)
    screen = _MatrixScreen()
    controller.refresh(screen)  # type: ignore[arg-type]

    controller._on_role_selected(screen, "SATICI")  # type: ignore[arg-type]
    controller.refresh(screen)  # type: ignore[arg-type]

    assert screen.selected[-1] == "SATICI"
