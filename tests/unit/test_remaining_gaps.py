"""Son dörd bəndin qərarları — baza keçidi, dashboard, plugin, xatırlatma.

Bu fayl spesifikasiyanın ƏN GERİ QAYTARILMAZ əməliyyatlarını qoruyur:
yarımçıq baza keçidi, imzasız plugin və təkrar göndərilən xatırlatma.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from src.application.use_cases.dashboard_layout import (
    WIDGET_CATALOG,
    DashboardLayoutUseCase,
    DashboardPermissionError,
)
from src.application.use_cases.db_switch import DatabaseSwitchUseCase
from src.application.use_cases.payment_reminders import (
    PaymentReminderUseCase,
    ReminderMessage,
    TenantBilling,
    build_message,
)
from src.application.use_cases.plugin_management import (
    InstalledPlugin,
    PluginManagementError,
    PluginManagementUseCase,
)
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import (
    PermissionEffect,
    RolePriority,
    SystemRole,
)
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.domain.value_objects.infrastructure import (
    ChecksumPair,
    DatabaseTarget,
    MaintenanceWindow,
    MaintenanceWindowError,
    MigrationError,
    MigrationPhase,
    MigrationPlan,
    MigrationStatus,
)
from src.infrastructure.plugins.contracts import (
    PluginCapability,
    PluginManifest,
    PluginSignatureError,
    PluginStatus,
)
from src.infrastructure.realtime.channel import LiveUpdateChannel, RealtimeState

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())


class _Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.value = now

    def now(self) -> datetime:
        return self.value


class _Audit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


def _employee(*, code: str = "ROOT", flags: tuple[str, ...] = ()) -> Employee:
    # `Root` və `CEO` AYRI pillələrdədir — sahtə də həqiqi modeli izləməlidir,
    # əks halda test səhv iyerarxiyanı sabitləşdirər (bax `RolePriority`).
    priority = SystemRole(code).default_priority if code in {"ROOT", "CEO"} else RolePriority.ADMIN
    position = Position(
        position_id=uuid.uuid4(),  # type: ignore[arg-type]
        code=code,
        name_az=code.title(),
        priority=priority,
        tenant_id=TENANT,
        is_system=True,
    )
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Ad",
        last_name="Soyad",
        username=Username(f"u.{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )
    for flag in flags:
        employee.apply_override(
            PermissionOverride(
                flag_code=flag, effect=PermissionEffect.GRANT, granted_by=employee.id
            )
        )
    return employee


# =========================================================================== #
# 1. BAZA KEÇİDİ
# =========================================================================== #


class _ReadOnly:
    def __init__(self) -> None:
        self.entered = 0
        self.left = 0
        self._on = False

    def enter_read_only(self, tenant_id: TenantId, *, reason: str) -> None:
        self.entered += 1
        self._on = True

    def leave_read_only(self, tenant_id: TenantId) -> None:
        self.left += 1
        self._on = False

    def is_read_only(self, tenant_id: TenantId) -> bool:
        return self._on


class _Buffer:
    def __init__(self, *, pending: int = 0, remaining_after_flush: int = 0) -> None:
        self._pending = pending
        self._remaining = remaining_after_flush

    def pending_count(self, tenant_id: TenantId) -> int:
        return self._pending

    def flush(self, tenant_id: TenantId) -> int:
        return self._remaining


class _Migrator:
    def __init__(
        self,
        *,
        checksums: dict[DatabaseTarget, str] | None = None,
        fail_on_copy: bool = False,
        fail_rollback: bool = False,
    ) -> None:
        self._checksums = checksums or {
            DatabaseTarget.CLOUD: "same",
            DatabaseTarget.PRIVATE_SERVER: "same",
        }
        self._fail_on_copy = fail_on_copy
        self._fail_rollback = fail_rollback
        self.switched: list[DatabaseTarget] = []
        self.rolled_back_to: DatabaseTarget | None = None

    def checksum(self, target: DatabaseTarget) -> str:
        return self._checksums[target]

    def copy(self, *, source: DatabaseTarget, destination: DatabaseTarget) -> None:
        if self._fail_on_copy:
            raise RuntimeError("şəbəkə kəsildi")

    def switch_active(self, target: DatabaseTarget) -> None:
        self.switched.append(target)

    def rollback(self, *, to: DatabaseTarget, reason: str) -> None:
        if self._fail_rollback:
            raise RuntimeError("geri qaytarma da alınmadı")
        self.rolled_back_to = to


class _Events:
    def __init__(self) -> None:
        self.started = 0
        self.finished: list[dict[str, Any]] = []

    def start(self, **kwargs: Any) -> str:
        self.started += 1
        return "event-1"

    def finish(self, event_id: str, **kwargs: Any) -> None:
        self.finished.append({"event_id": event_id, **kwargs})

    def history(self, tenant_id: TenantId, *, limit: int = 20) -> list[dict[str, Any]]:
        return []


def _switch(
    *,
    read_only: _ReadOnly | None = None,
    buffer: _Buffer | None = None,
    migrator: _Migrator | None = None,
    events: _Events | None = None,
    audit: _Audit | None = None,
    clock: _Clock | None = None,
) -> tuple[DatabaseSwitchUseCase, dict[str, Any]]:
    parts = {
        "read_only": read_only or _ReadOnly(),
        "buffer": buffer or _Buffer(),
        "migrator": migrator or _Migrator(),
        "events": events or _Events(),
        "audit": audit or _Audit(),
        "clock": clock or _Clock(),
    }
    return (
        DatabaseSwitchUseCase(
            read_only=parts["read_only"],
            buffer=parts["buffer"],
            migrator=parts["migrator"],
            events=parts["events"],
            audit=parts["audit"],
            clock=parts["clock"],
        ),
        parts,
    )


PLAN = MigrationPlan(source=DatabaseTarget.CLOUD, destination=DatabaseTarget.PRIVATE_SERVER)


def _root() -> Employee:
    return _employee(flags=("can_switch_db",))


def test_switch_requires_both_flag_and_role() -> None:
    """İki qatlı qoruma: flag təsadüfən verilə bilər, rol qəsdən təyin olunur."""
    use_case, _ = _switch()

    with pytest.raises(MigrationError, match="səlahiyyəti yoxdur"):
        use_case.execute(tenant_id=TENANT, actor=_employee(), plan=PLAN)

    with pytest.raises(MigrationError, match="YALNIZ Root"):
        use_case.execute(
            tenant_id=TENANT,
            actor=_employee(code="HR_ADMIN", flags=("can_switch_db",)),
            plan=PLAN,
        )


def test_switch_role_gate_rejects_ceo_even_with_the_flag() -> None:
    """`CEO` flag-i hansısa yolla əldə etsə belə rol qapısı onu rədd edir.

    REQRESSİYA QAPISI. `can_switch_db` `hardlock_level = 1` (`ROOT_ONLY`)
    daşıyır, yəni `CEO` bu flag-i normal yolla ALA BİLMİR — testdəki override
    məhz həmin qatın YAN KEÇİLDİYİ ssenarini (birbaşa SQL, köhnə məlumat,
    gələcəkdə səhvən dəyişdirilmiş hardlock səviyyəsi) təqlid edir.

    Rol qapısı əvvəl `Root VƏ CEO` idi; iki qat FƏRQLİ qərar verirdi
    (flag qatı «yalnız Root», rol qatı «Root+CEO»). Bu test həmin genişlənmənin
    sükutla geri qayıtmasını tutur.
    """
    use_case, parts = _switch()

    with pytest.raises(MigrationError, match="YALNIZ Root"):
        use_case.execute(
            tenant_id=TENANT,
            actor=_employee(code="CEO", flags=("can_switch_db",)),
            plan=PLAN,
        )

    # Rədd YAZIDAN ƏVVƏLDİR: heç bir addım başlamır, hadisə jurnalı boşdur.
    assert parts["events"].started == 0
    assert parts["read_only"].entered == 0


def test_switch_root_path_still_works_after_the_narrowing() -> None:
    """Daralma `Root` yolunu POZMAMALIDIR — bu, qərarın "itki yoxdur" sübutudur."""
    use_case, parts = _switch()

    report = use_case.execute(tenant_id=TENANT, actor=_root(), plan=PLAN)

    assert report.succeeded
    assert parts["migrator"].switched == [DatabaseTarget.PRIVATE_SERVER]
    # Yalnız-oxu yolu da toxunulmadan işləyir.
    assert parts["read_only"].entered == 1
    assert parts["read_only"].left == 1


def test_successful_switch_runs_every_phase_in_order() -> None:
    use_case, parts = _switch()
    report = use_case.execute(tenant_id=TENANT, actor=_root(), plan=PLAN)

    assert report.succeeded
    assert report.completed_phases == list(MigrationPhase)
    assert parts["migrator"].switched == [DatabaseTarget.PRIVATE_SERVER]
    assert report.active_target_after is DatabaseTarget.PRIVATE_SERVER


def test_unflushed_buffer_stops_the_migration_before_copying() -> None:
    """Sinxronlaşmamış yazı ilə miqrasiya həmin yazının itməsi deməkdir."""
    migrator = _Migrator()
    use_case, _ = _switch(buffer=_Buffer(remaining_after_flush=3), migrator=migrator)

    report = use_case.execute(tenant_id=TENANT, actor=_root(), plan=PLAN)

    assert not report.succeeded
    assert report.failed_phase is MigrationPhase.DRAIN_BUFFER
    assert migrator.switched == []
    assert not report.buffer_flushed


def test_checksum_mismatch_triggers_automatic_rollback() -> None:
    """Bölmə 2-nin mərkəzi qaydası — "qismən uğurlu keçid" mövcud deyil."""
    migrator = _Migrator(
        checksums={DatabaseTarget.CLOUD: "aaa", DatabaseTarget.PRIVATE_SERVER: "bbb"}
    )
    use_case, parts = _switch(migrator=migrator)

    report = use_case.execute(tenant_id=TENANT, actor=_root(), plan=PLAN)

    assert report.status is MigrationStatus.ROLLED_BACK
    assert migrator.rolled_back_to is DatabaseTarget.CLOUD
    assert migrator.switched == []
    assert report.active_target_after is DatabaseTarget.CLOUD
    assert parts["events"].finished[0]["status"] is MigrationStatus.ROLLED_BACK


def test_copy_failure_also_rolls_back() -> None:
    migrator = _Migrator(fail_on_copy=True)
    use_case, _ = _switch(migrator=migrator)

    report = use_case.execute(tenant_id=TENANT, actor=_root(), plan=PLAN)

    assert report.status is MigrationStatus.ROLLED_BACK
    assert report.failed_phase is MigrationPhase.COPY_DATA
    assert "şəbəkə kəsildi" in (report.rollback_reason or "")


def test_read_only_is_always_released_even_on_failure() -> None:
    """Bir səhv bütün mağazaları işləməz vəziyyətdə saxlamamalıdır."""
    read_only = _ReadOnly()
    use_case, _ = _switch(read_only=read_only, migrator=_Migrator(fail_on_copy=True))

    use_case.execute(tenant_id=TENANT, actor=_root(), plan=PLAN)

    assert read_only.entered == 1
    assert read_only.left == 1
    assert not read_only.is_read_only(TENANT)


def test_failed_rollback_is_reported_as_failed_not_silently_ok() -> None:
    migrator = _Migrator(fail_on_copy=True, fail_rollback=True)
    use_case, _ = _switch(migrator=migrator)

    report = use_case.execute(tenant_id=TENANT, actor=_root(), plan=PLAN)

    assert report.status is MigrationStatus.FAILED
    assert "GERİ QAYTARMA DA UĞURSUZ" in (report.rollback_reason or "")


def test_every_attempt_is_written_to_the_event_log() -> None:
    """Bölmə 2: keçid tarixçəsi `db_migration_events`-də saxlanılır."""
    events = _Events()
    use_case, _ = _switch(events=events)

    use_case.execute(tenant_id=TENANT, actor=_root(), plan=PLAN)

    assert events.started == 1
    assert events.finished[0]["status"] is MigrationStatus.COMPLETED
    assert events.finished[0]["buffer_flushed"] is True


def test_preflight_warns_about_pending_writes_without_blocking() -> None:
    use_case, _ = _switch(buffer=_Buffer(pending=5))
    warnings = use_case.preflight(tenant_id=TENANT, actor=_root(), plan=PLAN)
    assert any("5 sinxronlaşmamış" in text for text in warnings)


def test_same_source_and_destination_is_rejected() -> None:
    with pytest.raises(MigrationError):
        MigrationPlan(source=DatabaseTarget.CLOUD, destination=DatabaseTarget.CLOUD)


def test_expired_window_stops_the_migration() -> None:
    """Kəsinti planlaşdırılandan uzun olarsa əməliyyat dayandırılır."""
    clock = _Clock()
    plan = MigrationPlan(
        source=DatabaseTarget.CLOUD,
        destination=DatabaseTarget.PRIVATE_SERVER,
        window_minutes=1,
    )

    class _SlowMigrator(_Migrator):
        def copy(self, *, source: DatabaseTarget, destination: DatabaseTarget) -> None:
            clock.value = NOW + timedelta(minutes=5)

    use_case, _ = _switch(migrator=_SlowMigrator(), clock=clock)
    report = use_case.execute(tenant_id=TENANT, actor=_root(), plan=plan)

    assert report.status is MigrationStatus.ROLLED_BACK
    assert "vaxtı bitdi" in (report.rollback_reason or "")


def test_checksum_without_postflight_never_counts_as_matched() -> None:
    """Fail-closed: hesablanmamış barmaq izi «uyğundur» sayıla bilməz."""
    assert not ChecksumPair(preflight="abc").matched
    assert ChecksumPair(preflight="abc", postflight="abc").matched


def test_window_rejects_an_unreasonable_duration() -> None:
    with pytest.raises(MaintenanceWindowError):
        MaintenanceWindow(opened_at=NOW, max_minutes=0)


def test_window_remaining_time_never_goes_negative() -> None:
    window = MaintenanceWindow(opened_at=NOW, max_minutes=30)
    assert window.remaining_minutes(now=NOW + timedelta(hours=5)) == 0


# =========================================================================== #
# 2. DASHBOARD QURUCUSU
# =========================================================================== #


class _LayoutStore:
    def __init__(self, layout: list[str] | None = None) -> None:
        self.layout = layout
        self.saved: list[list[str]] = []

    def load(self, employee_id: EmployeeId) -> list[str] | None:
        return self.layout

    def save(self, employee_id: EmployeeId, layout: list[str]) -> None:
        self.layout = layout
        self.saved.append(layout)


class _Gate:
    def __init__(self, disabled: set[str] | None = None) -> None:
        self._disabled = disabled or set()

    def is_enabled(self, tenant_id: object, module_key: str) -> bool:
        return module_key not in self._disabled


def _dashboard(
    store: _LayoutStore | None = None, gate: _Gate | None = None
) -> DashboardLayoutUseCase:
    return DashboardLayoutUseCase(store=store or _LayoutStore(), clock=_Clock(), toggles=gate)


def test_default_layout_is_used_when_nothing_is_stored() -> None:
    view = _dashboard().view_for(actor=_employee(), tenant_id=TENANT)
    assert view.is_default
    assert view.visible


def test_widgets_requiring_a_flag_are_hidden_from_the_builder() -> None:
    """GÖRMƏK = SƏLAHİYYƏTİN OLMASI — xülasə rəqəm də məlumatdır."""
    view = _dashboard().view_for(actor=_employee(), tenant_id=TENANT)
    keys = {widget.key for widget in view.available}

    assert "fines_chart" not in keys
    assert "server_health" not in keys
    assert "stat_tiles" in keys


def test_granting_the_flag_reveals_the_widget() -> None:
    actor = _employee(flags=("can_view_employee_reports",))
    view = _dashboard().view_for(actor=actor, tenant_id=TENANT)
    assert "fines_chart" in {widget.key for widget in view.available}


def test_disabled_feature_module_removes_its_widget() -> None:
    view = _dashboard(gate=_Gate(disabled={"sales"})).view_for(actor=_employee(), tenant_id=TENANT)
    assert "points_leaderboard" not in {widget.key for widget in view.available}


def test_stored_layout_survives_but_forbidden_keys_are_dropped() -> None:
    """İcazə geri alındıqda köhnə düzülüş həmin bölməni yenidən açmamalıdır."""
    store = _LayoutStore(["fines_chart", "stat_tiles"])
    view = _dashboard(store).view_for(actor=_employee(), tenant_id=TENANT)

    assert "fines_chart" not in view.visible
    assert "stat_tiles" in view.visible


def test_a_new_widget_appears_at_the_end_and_stays_hidden() -> None:
    """Yeni modul köhnə düzülüşü pozmamalı, sonuncu yerə düşməlidir."""
    store = _LayoutStore(["stat_tiles"])
    view = _dashboard(store).view_for(actor=_employee(), tenant_id=TENANT)

    assert view.order[0] == "stat_tiles"
    assert view.visible == frozenset({"stat_tiles"})
    assert len(view.order) > 1


def test_hiding_everything_is_distinct_from_never_configuring() -> None:
    store = _LayoutStore([])
    view = _dashboard(store).view_for(actor=_employee(), tenant_id=TENANT)

    assert not view.is_default
    assert view.visible == frozenset()


def test_saving_drops_keys_the_user_may_not_see() -> None:
    """Ekran yan keçilə bilər — bu qat son qapıdır."""
    store = _LayoutStore()
    use_case = _dashboard(store)

    use_case.save(
        actor=_employee(flags=("can_edit_dashboard_widgets",)),
        tenant_id=TENANT,
        layout=["stat_tiles", "server_health", "stat_tiles"],
    )

    assert store.saved[-1] == ["stat_tiles"]


def test_saving_requires_the_edit_flag() -> None:
    """Bölmə 3: `can_edit_dashboard_widgets` — BAXIŞ yox, REDAKTƏ qapısı."""
    use_case = _dashboard()

    with pytest.raises(DashboardPermissionError):
        use_case.save(actor=_employee(), tenant_id=TENANT, layout=["stat_tiles"])


def test_viewing_does_not_require_the_edit_flag() -> None:
    """Flag olmadan da hər kəs öz dashboard-unu GÖRÜR."""
    view = _dashboard().view_for(actor=_employee(), tenant_id=TENANT)
    assert view.visible


def test_reset_writes_the_default_instead_of_deleting() -> None:
    """Defolta qayıtmaq da istifadəçinin QƏRARIDIR."""
    store = _LayoutStore(["stat_tiles"])
    view = _dashboard(store).reset(
        actor=_employee(flags=("can_edit_dashboard_widgets",)), tenant_id=TENANT
    )

    assert store.saved
    assert view.is_default
    assert len(view.visible) == len(view.available)


def test_catalog_keys_are_unique() -> None:
    keys = [widget.key for widget in WIDGET_CATALOG]
    assert len(keys) == len(set(keys))


# =========================================================================== #
# 3. CANLI YENİLƏMƏ (realtime + polling fallback)
# =========================================================================== #


class _Transport:
    def __init__(self, *, fail_times: int = 0) -> None:
        self._fail_times = fail_times
        self.connected = False
        self.connects = 0

    def connect(self, channels: Any, on_event: Any) -> None:
        self.connects += 1
        if self._fail_times > 0:
            self._fail_times -= 1
            self.connected = False
            raise ConnectionError("WebSocket alınmadı")
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected


def _channel(transport: Any, polls: list[int]) -> LiveUpdateChannel:
    return LiveUpdateChannel(channels=["fines"], transport=transport, poll=lambda: polls.append(1))


def test_working_websocket_means_live_and_no_polling() -> None:
    polls: list[int] = []
    channel = _channel(_Transport(), polls)

    assert channel.start() is RealtimeState.LIVE
    channel.tick(60)
    assert polls == []


def test_failed_connection_degrades_and_polls_immediately() -> None:
    """Onsuz ekran ilk 30 saniyə boş qalardı."""
    polls: list[int] = []
    channel = _channel(_Transport(fail_times=99), polls)

    assert channel.start() is RealtimeState.DEGRADED
    assert len(polls) == 1


def test_missing_transport_is_not_an_error_just_polling() -> None:
    polls: list[int] = []
    channel = LiveUpdateChannel(channels=["fines"], transport=None, poll=lambda: polls.append(1))
    assert channel.start() is RealtimeState.DEGRADED
    assert len(polls) == 1


def test_dropped_websocket_falls_back_without_losing_data_flow() -> None:
    polls: list[int] = []
    transport = _Transport()
    channel = _channel(transport, polls)
    channel.start()

    transport.connected = False
    channel.tick(1)

    assert channel.state is RealtimeState.DEGRADED
    assert len(polls) == 1


def test_polling_repeats_on_the_configured_interval() -> None:
    polls: list[int] = []
    channel = _channel(_Transport(fail_times=99), polls)
    channel.start()
    polls.clear()

    channel.tick(30)
    channel.tick(30)

    assert len(polls) == 2


def test_channel_recovers_to_live_when_the_socket_returns() -> None:
    """Polling-də QALMAQ günün qalanında gecikmiş məlumat demək olardı."""
    polls: list[int] = []
    transport = _Transport(fail_times=1)
    channel = _channel(transport, polls)

    assert channel.start() is RealtimeState.DEGRADED
    channel.tick(10)

    assert channel.state is RealtimeState.LIVE


def test_a_failing_poll_does_not_stop_the_channel() -> None:
    def _boom() -> None:
        raise RuntimeError("baza əlçatmazdır")

    channel = LiveUpdateChannel(channels=["fines"], transport=_Transport(fail_times=99), poll=_boom)
    channel.start()
    channel.tick(30)

    assert channel.state is RealtimeState.DEGRADED


def test_degraded_state_is_visible_to_the_user() -> None:
    """İstifadəçi məlumatın gecikmiş ola biləcəyini BİLMƏLİDİR."""
    assert RealtimeState.DEGRADED.is_delayed
    assert not RealtimeState.LIVE.is_delayed
    assert "30 san" in RealtimeState.DEGRADED.label_az


# =========================================================================== #
# 4. PLUGIN İDARƏETMƏSİ
# =========================================================================== #


class _Registry:
    def __init__(self, plugins: list[InstalledPlugin] | None = None) -> None:
        self.plugins = {p.plugin_id: p for p in (plugins or [])}
        self.statuses: list[tuple[str, PluginStatus]] = []
        self.removed: list[str] = []

    def list_all(self, tenant_id: TenantId) -> list[InstalledPlugin]:
        return list(self.plugins.values())

    def get(self, plugin_id: str) -> InstalledPlugin | None:
        return self.plugins.get(plugin_id)

    def install(self, tenant_id: TenantId, **kwargs: Any) -> str:
        return "plugin-1"

    def set_status(self, plugin_id: str, status: PluginStatus, *, changed_by: Any) -> None:
        self.statuses.append((plugin_id, status))

    def remove(self, plugin_id: str) -> None:
        self.removed.append(plugin_id)


class _Verifier:
    def __init__(self, *, valid: bool = True) -> None:
        self._valid = valid

    def verify(self, *, plugin_path: Any, manifest: Any, signature_hex: str) -> str:
        if not self._valid:
            raise PluginSignatureError("naşir tanınmır")
        return "a" * 64


def _manifest() -> PluginManifest:
    return PluginManifest(
        name="Xüsusi Hesabat",
        version="1.0.0",
        publisher="KompasOS Partner",
        capabilities=frozenset({PluginCapability.REPORT_TRANSFORM}),
        entry_point="main:run",
    )


def _plugins(
    registry: _Registry | None = None,
    verifier: _Verifier | None = None,
    audit: _Audit | None = None,
) -> PluginManagementUseCase:
    return PluginManagementUseCase(
        registry=registry or _Registry(),
        verifier=verifier or _Verifier(),
        audit=audit or _Audit(),
        clock=_Clock(),
    )


def test_plugin_management_requires_flag_and_root_role() -> None:
    use_case = _plugins()

    with pytest.raises(PluginManagementError, match="səlahiyyəti yoxdur"):
        use_case.list_plugins(tenant_id=TENANT, actor=_employee())

    with pytest.raises(PluginManagementError, match="YALNIZ Root"):
        use_case.list_plugins(
            tenant_id=TENANT, actor=_employee(code="HR_ADMIN", flags=("can_manage_plugins",))
        )


def test_plugin_role_gate_rejects_ceo_even_with_the_flag() -> None:
    """`can_manage_plugins` `ROOT_ONLY`-dir — rol qapısı da eyni şeyi deməlidir.

    `db_switch`-dəki eyni reqressiya qapısı. Plugin host prosesinə KOD əlavə
    edir, yəni iki qatın fərqli qərar verməsi burada daha bahalıdır.
    """
    use_case = _plugins()

    with pytest.raises(PluginManagementError, match="YALNIZ Root"):
        use_case.list_plugins(
            tenant_id=TENANT, actor=_employee(code="CEO", flags=("can_manage_plugins",))
        )


def test_plugin_root_path_still_lists_after_the_narrowing() -> None:
    """Daralmadan sonra `Root` yolu toxunulmaz qalır."""
    use_case = _plugins()

    assert (
        use_case.list_plugins(tenant_id=TENANT, actor=_employee(flags=("can_manage_plugins",)))
        == []
    )


def test_unsigned_package_is_never_installed() -> None:
    """İmza yoxlaması ÖN ŞƏRTDİR, xəbərdarlıq deyil."""
    from pathlib import Path

    use_case = _plugins(verifier=_Verifier(valid=False))

    with pytest.raises(PluginSignatureError):
        use_case.install(
            tenant_id=TENANT,
            actor=_employee(flags=("can_manage_plugins",)),
            plugin_path=Path("plugin.zip"),
            manifest=_manifest(),
            signature_hex="00",
        )


def test_installed_plugin_starts_pending_not_active() -> None:
    """«Səhvən quraşdırdım» ilə «işlətməyə razıyam» bir klik olmamalıdır."""
    from pathlib import Path

    audit = _Audit()
    use_case = _plugins(audit=audit)

    plugin = use_case.install(
        tenant_id=TENANT,
        actor=_employee(flags=("can_manage_plugins",)),
        plugin_path=Path("plugin.zip"),
        manifest=_manifest(),
        signature_hex="ab",
    )

    assert plugin.status is PluginStatus.PENDING_APPROVAL
    assert not plugin.is_enabled
    assert audit.records[-1]["action"] == "PLUGIN_INSTALLED"


def test_unverified_plugin_cannot_be_enabled() -> None:
    registry = _Registry(
        [
            InstalledPlugin(
                plugin_id="p1",
                name="Şübhəli",
                version="0.1",
                publisher="?",
                status=PluginStatus.PENDING_APPROVAL,
                signature_verified=False,
            )
        ]
    )
    use_case = _plugins(registry)

    with pytest.raises(PluginManagementError, match="imzası doğrulanmamış"):
        use_case.set_enabled(
            tenant_id=TENANT,
            actor=_employee(flags=("can_manage_plugins",)),
            plugin_id="p1",
            enabled=True,
        )


def test_enabling_and_disabling_are_audited() -> None:
    registry = _Registry(
        [
            InstalledPlugin(
                plugin_id="p1",
                name="Hesabat",
                version="1.0",
                publisher="Partner",
                status=PluginStatus.PENDING_APPROVAL,
                signature_verified=True,
            )
        ]
    )
    audit = _Audit()
    use_case = _plugins(registry, audit=audit)
    actor = _employee(flags=("can_manage_plugins",))

    use_case.set_enabled(tenant_id=TENANT, actor=actor, plugin_id="p1", enabled=True)

    assert registry.statuses == [("p1", PluginStatus.APPROVED)]
    assert audit.records[-1]["action"] == "PLUGIN_ENABLED"


def test_plugin_row_maps_to_the_screen_contract() -> None:
    plugin = InstalledPlugin(
        plugin_id="p1",
        name="Hesabat",
        version="1.0",
        publisher="Partner",
        status=PluginStatus.APPROVED,
        signature_verified=True,
    )
    row = plugin.as_row()
    assert row["enabled"] == "1"
    assert row["signature"] == "valid"


# =========================================================================== #
# 5. ÖDƏNİŞ XATIRLATMALARI
# =========================================================================== #


class _Sender:
    def __init__(self, *, fail_for: set[str] | None = None) -> None:
        self.sent: list[ReminderMessage] = []
        self._fail_for = fail_for or set()

    def send(self, message: ReminderMessage) -> None:
        if message.tenant_id in self._fail_for:
            raise RuntimeError("SMTP rədd etdi")
        self.sent.append(message)


class _SentLog:
    def __init__(self, already: set[str] | None = None) -> None:
        self.already = already or set()

    def was_sent(self, stage_key: str) -> bool:
        return stage_key in self.already

    def mark_sent(self, stage_key: str, *, sent_at: datetime) -> None:
        self.already.add(stage_key)


def _billing(*, days_left: int | None, tenant_id: str = "t1") -> TenantBilling:
    return TenantBilling(
        tenant_id=tenant_id,
        tenant_name="Bellona",
        contact_email="info@bellona.az",
        expires_on=None if days_left is None else date(2026, 8, 12) + timedelta(days=days_left),
    )


@pytest.mark.parametrize("days_left", [7, 3, 1])
def test_reminder_is_due_before_expiry(days_left: int) -> None:
    message = build_message(_billing(days_left=days_left), today=date(2026, 8, 12))
    assert message is not None
    assert not message.is_overdue


@pytest.mark.parametrize("days_left", [-1, -7])
def test_reminder_is_due_after_expiry(days_left: int) -> None:
    message = build_message(_billing(days_left=days_left), today=date(2026, 8, 12))
    assert message is not None
    assert message.is_overdue
    assert "bitib" in message.title_az


@pytest.mark.parametrize("days_left", [30, 5, 2, 0, -3, -30])
def test_no_reminder_on_other_days(days_left: int) -> None:
    """Hər gün göndərilən xatırlatma spam kimi süzgəcə düşür."""
    assert build_message(_billing(days_left=days_left), today=date(2026, 8, 12)) is None


def test_perpetual_licence_never_gets_a_reminder() -> None:
    assert build_message(_billing(days_left=None), today=date(2026, 8, 12)) is None


def test_the_same_stage_is_never_sent_twice() -> None:
    sender, log = _Sender(), _SentLog()
    use_case = PaymentReminderUseCase(sender=sender, log=log)

    first = use_case.run([_billing(days_left=7)], now=NOW)
    second = use_case.run([_billing(days_left=7)], now=NOW)

    assert first.sent_count == 1
    assert second.sent_count == 0
    assert second.skipped_already_sent == 1


def test_one_bad_address_does_not_block_the_others() -> None:
    sender = _Sender(fail_for={"broken"})
    log = _SentLog()
    use_case = PaymentReminderUseCase(sender=sender, log=log)

    run = use_case.run(
        [
            _billing(days_left=7, tenant_id="broken"),
            _billing(days_left=7, tenant_id="ok"),
        ],
        now=NOW,
    )

    assert run.failed == ["broken"]
    assert [m.tenant_id for m in run.sent] == ["ok"]


def test_a_failed_send_is_retried_next_cycle() -> None:
    """Uğursuz mərhələ «göndərildi» kimi işarələnməməlidir."""
    log = _SentLog()
    failing = PaymentReminderUseCase(sender=_Sender(fail_for={"t1"}), log=log)
    failing.run([_billing(days_left=7)], now=NOW)

    working_sender = _Sender()
    retry = PaymentReminderUseCase(sender=working_sender, log=log)
    run = retry.run([_billing(days_left=7)], now=NOW)

    assert run.sent_count == 1


def test_stage_key_separates_before_and_after_expiry() -> None:
    before = build_message(_billing(days_left=1), today=date(2026, 8, 12))
    after = build_message(_billing(days_left=-1), today=date(2026, 8, 12))
    assert before is not None and after is not None
    assert before.stage_key != after.stage_key


def test_disabled_dashboard_builder_offers_no_widgets() -> None:
    """Bölmə 3: `DASHBOARD_BUILDER` söndürülübsə birbaşa çağırış da boş verir.

    Ekran onsuz da naviqasiyadan kəsilir, lakin use case-i birbaşa çağıran yol
    (skript, test, gələcək API) eyni nəticəni verməlidir — əks halda "UI-da
    gizlətmək" yeganə müdafiə olardı.
    """
    from src.domain.policies import FeatureModule

    view = _dashboard(gate=_Gate(disabled={FeatureModule.DASHBOARD_BUILDER.value})).view_for(
        actor=_employee(flags=("can_view_dashboard_builder",)), tenant_id=TENANT
    )

    assert view.available == ()
    assert view.visible == frozenset()
