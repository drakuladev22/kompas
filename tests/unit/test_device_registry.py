"""Cihaz qeydiyyatı qapısı (DEVICE-1).

──────────────────────────────────────────────────────────────────────────────
NƏYİ QORUYUR
──────────────────────────────────────────────────────────────────────────────
Bu modulun qüsurları BİR İSTİQAMƏTDƏ təhlükəlidir: cihaz təsdiqsiz işləməyə
başlasa, filial tanıma sükutla sıradan çıxar və cərimə/tabel səhv mağazaya
yazılar — ekranda isə hər şey normal görünər. Ona görə burada beş şey ölçülür:

    1. Təsdiqsiz cihaz İŞLƏMİR və filialsız aktiv ola BİLMİR;
    2. Lisenziya sayğacı yalnız AKTİV cihazı sayır (hücum səthi olmasın);
    3. Avtomatik təsdiq YALNIZ tək mağazalı quraşdırmada işləyir;
    4. Fingerprint dəyişikliyi bloklamır, LAKİN izsiz də qalmır;
    5. Passivlik həddi yeri boşaldır.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest

from src.application.use_cases.device_registry import (
    DeviceLimitReachedError,
    DeviceNotFoundError,
    DevicePermissionError,
    DeviceRegistryUseCase,
)
from src.domain.entities.base import DomainRuleError, InvalidStateTransitionError
from src.domain.entities.registered_device import (
    DeviceNotApprovedError,
    RegisteredDevice,
)
from src.domain.policies import SystemLimitKey
from src.domain.value_objects.devices import (
    SHORT_CODE_ALPHABET,
    SHORT_CODE_LENGTH,
    DeviceFingerprint,
    DeviceStatus,
    DeviceType,
    generate_short_code,
    normalize_short_code,
)
from src.domain.value_objects.identifiers import (
    DeviceId,
    EmployeeId,
    StoreId,
    TenantId,
    new_device_id,
)
from tests.fixtures.fakes import FakeSystemLimits

pytestmark = pytest.mark.unit

TENANT: Final = TenantId(uuid.UUID("33333333-3333-3333-3333-333333333333"))
STORE_A: Final = StoreId(uuid.UUID("44444444-4444-4444-4444-444444444444"))
STORE_B: Final = StoreId(uuid.UUID("55555555-5555-5555-5555-555555555555"))
ACTOR_ID: Final = EmployeeId(uuid.UUID("66666666-6666-6666-6666-666666666666"))
NOW: Final = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)

FINGERPRINT: Final = DeviceFingerprint("a" * 32)
OTHER_FINGERPRINT: Final = DeviceFingerprint("b" * 32)


# --------------------------------------------------------------------------- #
# Sahtələr
# --------------------------------------------------------------------------- #


class _FakeClock:
    def __init__(self, moment: datetime = NOW) -> None:
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


class _FakeAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.entries.append(kwargs)

    def actions(self) -> list[str]:
        return [str(entry["action"]) for entry in self.entries]


class _FakeStores:
    def __init__(self, stores: list[StoreId]) -> None:
        self.stores = stores

    def list_active(self, tenant_id: TenantId) -> list[StoreId]:
        return list(self.stores)


class _FakeRegistry:
    def __init__(self) -> None:
        self.rows: dict[str, RegisteredDevice] = {}

    def get(self, device_id: DeviceId) -> RegisteredDevice | None:
        return self.rows.get(str(device_id))

    def find_by_short_code(self, tenant_id: TenantId, short_code: str) -> RegisteredDevice | None:
        for device in self.rows.values():
            if device.short_code == short_code:
                return device
        return None

    def short_code_exists(self, tenant_id: TenantId, short_code: str) -> bool:
        return any(device.short_code == short_code for device in self.rows.values())

    def list_by_status(
        self, tenant_id: TenantId, status: str, *, limit: int
    ) -> list[RegisteredDevice]:
        return [d for d in self.rows.values() if d.status.value == status][:limit]

    def list_all(self, tenant_id: TenantId, *, limit: int) -> list[RegisteredDevice]:
        return list(self.rows.values())[:limit]

    def count_active(self, tenant_id: TenantId) -> int:
        return sum(1 for d in self.rows.values() if d.status is DeviceStatus.ACTIVE)

    def count_pending(self, tenant_id: TenantId) -> int:
        return sum(1 for d in self.rows.values() if d.status is DeviceStatus.PENDING_APPROVAL)

    def save(self, device: RegisteredDevice) -> None:
        self.rows[str(device.id)] = device


class _FakeActor:
    """`Employee` əvəzinə minimal aktor — yalnız icazə soruşulur."""

    def __init__(self, *, allowed: bool = True) -> None:
        self.id = ACTOR_ID
        self._allowed = allowed

    def has_permission(self, flag: str, *, now: datetime) -> bool:
        return self._allowed


def _build(
    *,
    stores: list[StoreId] | None = None,
    overrides: dict[str, str] | None = None,
) -> tuple[DeviceRegistryUseCase, _FakeRegistry, _FakeAudit, _FakeClock]:
    registry = _FakeRegistry()
    audit = _FakeAudit()
    clock = _FakeClock()
    use_case = DeviceRegistryUseCase(
        devices=registry,  # type: ignore[arg-type]
        stores=_FakeStores(stores if stores is not None else [STORE_A, STORE_B]),  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        clock=clock,  # type: ignore[arg-type]
        limits=FakeSystemLimits(overrides),  # type: ignore[arg-type]
    )
    return use_case, registry, audit, clock


def _device(**kwargs: Any) -> RegisteredDevice:
    defaults: dict[str, Any] = {
        "id": new_device_id(),
        "tenant_id": TENANT,
        "fingerprint": FINGERPRINT,
        "short_code": "ABC234",
        "machine_name": "KASSA-1",
        "device_type": DeviceType.ADMIN_PC,
        "registered_at": NOW,
        "emit_created_event": False,
    }
    defaults.update(kwargs)
    return RegisteredDevice(**defaults)


# --------------------------------------------------------------------------- #
# 1. Qısa kod
# --------------------------------------------------------------------------- #


def test_the_short_code_avoids_confusable_characters() -> None:
    """Telefonla söylənilən kodda 0/O, 1/I/L, 5/S, 2/Z OLMAMALIDIR.

    Səhv eşidilən bir simvol admini BAŞQA cihazı təsdiqləməyə aparardı — və
    həmin cihaz səhv filiala təyin olunardı.
    """
    for confusable in "01OIL5S2Z":
        assert confusable not in SHORT_CODE_ALPHABET, (
            f"«{confusable}» əlifbadadır — telefonla diktədə qarışır"
        )


def test_generated_codes_use_only_the_alphabet() -> None:
    for _ in range(200):
        code = generate_short_code()
        assert len(code) == SHORT_CODE_LENGTH
        assert set(code) <= set(SHORT_CODE_ALPHABET)


def test_the_code_is_normalized_the_way_a_human_types_it() -> None:
    """Admin telefonda eşidib «a3-7k m9» yazır — kod tapılmalıdır."""
    assert normalize_short_code(" a3-7k m9 ") == "A37KM9"


# --------------------------------------------------------------------------- #
# 2. Aparat izi
# --------------------------------------------------------------------------- #


def test_the_fingerprint_hashes_the_parts_instead_of_storing_them() -> None:
    """XAM seriya nömrələri saxlanılmır — baza sızması inventar verməməlidir."""
    fingerprint = DeviceFingerprint.from_parts("BOARD-123", "DISK-456")
    assert "BOARD-123" not in fingerprint.value
    assert "DISK-456" not in fingerprint.value
    assert len(fingerprint.value) == 32


def test_the_fingerprint_is_stable_across_formatting_differences() -> None:
    """WMI formatı dəyişəndə «cihaz dəyişdi» xəbərdarlığı çıxmamalıdır."""
    assert DeviceFingerprint.from_parts(" board-1 ", "disk-2") == DeviceFingerprint.from_parts(
        "BOARD-1", "DISK-2"
    )


def test_empty_hardware_values_are_dropped_not_hashed() -> None:
    """Boş dəyəri hash-ə qatmaq maşınları bir-birinə YAXINLAŞDIRARDI."""
    assert DeviceFingerprint.from_parts("BOARD-1", "", "   ") == DeviceFingerprint.from_parts(
        "BOARD-1"
    )


def test_a_fingerprint_change_is_recorded_but_does_not_block() -> None:
    """Disk dəyişdirmək legitim təmirdir — mağaza səhər işləməlidir."""
    use_case, registry, audit, _ = _build()
    device = _device(status=DeviceStatus.ACTIVE, store_id=STORE_A)
    registry.save(device)

    outcome = use_case.register_self(
        tenant_id=TENANT,
        device_id=device.id,
        fingerprint=OTHER_FINGERPRINT,
        machine_name="KASSA-1",
    )

    assert outcome.fingerprint_changed
    assert outcome.device.status is DeviceStatus.ACTIVE, "uyğunsuzluq cihazı bloklamamalıdır"
    assert "DEVICE_FINGERPRINT_CHANGED" in audit.actions(), "hadisə izsiz qaldı"


def test_the_observed_fingerprint_is_kept_so_the_admin_can_decide() -> None:
    """«Qərarı adam verir» — deməli adam GÖRDÜYÜ dəyəri qəbul edə bilməlidir.

    Müşahidə olunan iz saxlanmasaydı, admin paneldə yalnız «dəyişib» sözünü
    görərdi və qəbul edəcəyi dəyər HEÇ YERDƏ olmazdı: uyğunsuzluq həll
    edilməz vəziyyətə düşərdi.
    """
    use_case, registry, _, _ = _build()
    device = _device(status=DeviceStatus.ACTIVE, store_id=STORE_A)
    registry.save(device)

    outcome = use_case.register_self(
        tenant_id=TENANT,
        device_id=device.id,
        fingerprint=OTHER_FINGERPRINT,
        machine_name="KASSA-1",
    )

    assert outcome.device.pending_fingerprint == OTHER_FINGERPRINT
    assert outcome.device.fingerprint == FINGERPRINT, "saxlanmış iz admin qərarına qədər qalır"


def test_the_same_mismatch_is_audited_once_not_at_every_start() -> None:
    """Təkrarlanan yazı auditi doldurur və HƏQİQİ hadisəni gizlədir."""
    use_case, registry, audit, _ = _build()
    device = _device(status=DeviceStatus.ACTIVE, store_id=STORE_A)
    registry.save(device)

    for _ in range(3):
        use_case.register_self(
            tenant_id=TENANT,
            device_id=device.id,
            fingerprint=OTHER_FINGERPRINT,
            machine_name="KASSA-1",
        )

    assert audit.actions().count("DEVICE_FINGERPRINT_CHANGED") == 1


def test_restored_hardware_clears_the_pending_value() -> None:
    """Disk geri qoyulubsa gözləyən dəyər qalmamalıdır — yoxsa admin
    artıq mövcud olmayan bir izi qəbul edərdi."""
    use_case, registry, _, _ = _build()
    device = _device(status=DeviceStatus.ACTIVE, store_id=STORE_A)
    registry.save(device)
    use_case.register_self(
        tenant_id=TENANT,
        device_id=device.id,
        fingerprint=OTHER_FINGERPRINT,
        machine_name="KASSA-1",
    )

    outcome = use_case.register_self(
        tenant_id=TENANT, device_id=device.id, fingerprint=FINGERPRINT, machine_name="KASSA-1"
    )

    assert outcome.device.pending_fingerprint is None
    assert not outcome.fingerprint_changed


def test_accepting_the_new_fingerprint_replaces_the_stored_one() -> None:
    """Admin-in qərarı BİR YERƏ düşməlidir — yoxsa xəbərdarlıq əbədi qalır."""
    use_case, registry, audit, _ = _build()
    device = _device(status=DeviceStatus.ACTIVE, store_id=STORE_A)
    registry.save(device)
    use_case.register_self(
        tenant_id=TENANT,
        device_id=device.id,
        fingerprint=OTHER_FINGERPRINT,
        machine_name="KASSA-1",
    )

    accepted = use_case.accept_fingerprint(
        tenant_id=TENANT,
        actor=_FakeActor(),  # type: ignore[arg-type]
        device_id=device.id,
    )

    assert accepted.fingerprint == OTHER_FINGERPRINT
    assert accepted.pending_fingerprint is None
    assert "DEVICE_FINGERPRINT_ACCEPTED" in audit.actions()


def test_accepting_requires_the_device_flag() -> None:
    """Qəbul aparat lövbərini DƏYİŞİR — hər kəsə açıq ola bilməz."""
    use_case, registry, _, _ = _build()
    device = _device(status=DeviceStatus.ACTIVE, store_id=STORE_A)
    registry.save(device)
    use_case.register_self(
        tenant_id=TENANT,
        device_id=device.id,
        fingerprint=OTHER_FINGERPRINT,
        machine_name="KASSA-1",
    )

    with pytest.raises(DevicePermissionError):
        use_case.accept_fingerprint(
            tenant_id=TENANT,
            actor=_FakeActor(allowed=False),  # type: ignore[arg-type]
            device_id=device.id,
        )


def test_accepting_without_a_pending_value_is_refused() -> None:
    """Boş qəbul auditə «təsdiqləndi» yazardı — halbuki heç nə dəyişməyib."""
    use_case, registry, _, _ = _build()
    device = _device(status=DeviceStatus.ACTIVE, store_id=STORE_A)
    registry.save(device)

    with pytest.raises(DomainRuleError):
        use_case.accept_fingerprint(
            tenant_id=TENANT,
            actor=_FakeActor(),  # type: ignore[arg-type]
            device_id=device.id,
        )


# --------------------------------------------------------------------------- #
# 3. Vəziyyət maşını
# --------------------------------------------------------------------------- #


def test_a_pending_device_refuses_to_operate() -> None:
    device = _device()
    assert not device.is_operational
    with pytest.raises(DeviceNotApprovedError):
        device.require_operational()


def test_an_active_device_cannot_exist_without_a_store() -> None:
    """İnvariant DB constraint-i ilə EYNİDİR (`chk_device_active_has_store`)."""
    with pytest.raises(DomainRuleError):
        _device(status=DeviceStatus.ACTIVE, store_id=None)


def test_approval_requires_a_name() -> None:
    """Adsız cihaz siyahıda digərlərindən ayırd edilə bilməzdi."""
    device = _device()
    with pytest.raises(DomainRuleError):
        device.approve(
            store_id=STORE_A,
            device_name="   ",
            device_type=DeviceType.KIOSK,
            approved_by=ACTOR_ID,
            now=NOW,
        )


def test_only_a_pending_device_can_be_approved() -> None:
    device = _device(status=DeviceStatus.ACTIVE, store_id=STORE_A)
    with pytest.raises(InvalidStateTransitionError):
        device.approve(
            store_id=STORE_B,
            device_name="Kassa",
            device_type=DeviceType.KIOSK,
            approved_by=ACTOR_ID,
            now=NOW,
        )


def test_blocking_twice_is_idempotent() -> None:
    """Avtomatik passivləşmə dövrəsi eyni cihazı təkrar görəcək — dayanmamalıdır."""
    device = _device(status=DeviceStatus.ACTIVE, store_id=STORE_A)
    device.block(reason="ilk", blocked_by=ACTOR_ID, now=NOW)
    device.block(reason="ikinci", blocked_by=ACTOR_ID, now=NOW)
    assert device.block_reason == "ilk", "ikinci bloklama səbəbi üzərinə yazdı"


def test_a_blocked_device_without_a_store_cannot_be_reactivated() -> None:
    """Filialsız bloklanmış cihaz heç vaxt təsdiqlənməyib — `approve()` yolundadır."""
    device = _device(status=DeviceStatus.BLOCKED)
    with pytest.raises(DomainRuleError):
        device.reactivate(reactivated_by=ACTOR_ID, now=NOW)


# --------------------------------------------------------------------------- #
# 4. Lisenziya sayğacı
# --------------------------------------------------------------------------- #


def test_only_active_devices_count_toward_the_license() -> None:
    """Gözləyən sətir sayılsaydı, sayğac HÜCUM SƏTHİ olardı."""
    use_case, registry, _, _ = _build()
    registry.save(_device(status=DeviceStatus.ACTIVE, store_id=STORE_A))
    registry.save(_device(status=DeviceStatus.PENDING_APPROVAL, short_code="PEND01"))
    registry.save(_device(status=DeviceStatus.BLOCKED, store_id=STORE_A, short_code="BLK001"))

    usage = use_case.license_usage(TENANT)

    assert usage.active == 1
    assert usage.pending == 1
    assert usage.describe() == "1 / 25 cihaz istifadə olunur"


def test_approval_is_refused_when_the_limit_is_full() -> None:
    use_case, registry, _, _ = _build(overrides={SystemLimitKey.MAX_REGISTERED_DEVICES.value: "1"})
    registry.save(_device(status=DeviceStatus.ACTIVE, store_id=STORE_A))
    pending = _device(short_code="PEND01")
    registry.save(pending)

    with pytest.raises(DeviceLimitReachedError):
        use_case.approve(
            tenant_id=TENANT,
            actor=_FakeActor(),  # type: ignore[arg-type]
            device_id=pending.id,
            store_id=STORE_B,
            device_name="Kassa 2",
            device_type=DeviceType.KIOSK,
        )


def test_reactivation_also_checks_the_limit() -> None:
    """Bloklandığı müddətdə yer başqasına verilmiş ola bilər."""
    use_case, registry, _, _ = _build(overrides={SystemLimitKey.MAX_REGISTERED_DEVICES.value: "1"})
    registry.save(_device(status=DeviceStatus.ACTIVE, store_id=STORE_A))
    blocked = _device(status=DeviceStatus.BLOCKED, store_id=STORE_B, short_code="BLK001")
    registry.save(blocked)

    with pytest.raises(DeviceLimitReachedError):
        use_case.reactivate(
            tenant_id=TENANT,
            actor=_FakeActor(),  # type: ignore[arg-type]
            device_id=blocked.id,
        )


# --------------------------------------------------------------------------- #
# 5. Avtomatik təsdiq
# --------------------------------------------------------------------------- #


def test_auto_approval_works_with_exactly_one_store() -> None:
    use_case, _, audit, _ = _build(
        stores=[STORE_A],
        overrides={SystemLimitKey.DEVICE_APPROVAL_REQUIRED.value: "0"},
    )
    outcome = use_case.register_self(
        tenant_id=TENANT, device_id=None, fingerprint=FINGERPRINT, machine_name="KASSA-1"
    )

    assert outcome.device.status is DeviceStatus.ACTIVE
    assert outcome.device.store_id == STORE_A
    assert "DEVICE_AUTO_APPROVED" in audit.actions()


def test_auto_approval_is_refused_when_the_store_is_ambiguous() -> None:
    """İki mağazada «filialı təsadüfi seç» DEVICE-1-in problemini geri gətirərdi."""
    use_case, _, audit, _ = _build(
        stores=[STORE_A, STORE_B],
        overrides={SystemLimitKey.DEVICE_APPROVAL_REQUIRED.value: "0"},
    )
    outcome = use_case.register_self(
        tenant_id=TENANT, device_id=None, fingerprint=FINGERPRINT, machine_name="KASSA-1"
    )

    assert outcome.device.status is DeviceStatus.PENDING_APPROVAL
    assert "DEVICE_AUTO_APPROVED" not in audit.actions()


def test_auto_approval_respects_the_license_limit() -> None:
    use_case, registry, audit, _ = _build(
        stores=[STORE_A],
        overrides={
            SystemLimitKey.DEVICE_APPROVAL_REQUIRED.value: "0",
            SystemLimitKey.MAX_REGISTERED_DEVICES.value: "1",
        },
    )
    registry.save(_device(status=DeviceStatus.ACTIVE, store_id=STORE_A))

    outcome = use_case.register_self(
        tenant_id=TENANT, device_id=None, fingerprint=FINGERPRINT, machine_name="KASSA-2"
    )

    assert outcome.device.status is DeviceStatus.PENDING_APPROVAL
    assert "DEVICE_AUTO_APPROVED" not in audit.actions()


# --------------------------------------------------------------------------- #
# 6. Səlahiyyət
# --------------------------------------------------------------------------- #


def test_admin_actions_require_the_flag() -> None:
    """Səlahiyyət yoxlaması sükutla «heç nə etmə» DEYİL (`CLAUDE.md` §6)."""
    use_case, registry, _, _ = _build()
    device = _device()
    registry.save(device)
    denied = _FakeActor(allowed=False)

    with pytest.raises(DevicePermissionError):
        use_case.list_pending(tenant_id=TENANT, actor=denied)  # type: ignore[arg-type]
    with pytest.raises(DevicePermissionError):
        use_case.block(
            tenant_id=TENANT,
            actor=denied,  # type: ignore[arg-type]
            device_id=device.id,
            reason="test",
        )


def test_registration_needs_no_actor_and_that_is_the_point() -> None:
    """Cihaz özünü giriş etməmişdən ƏVVƏL tanıdır — aktor mövcud deyil."""
    use_case, _, _, _ = _build()
    outcome = use_case.register_self(
        tenant_id=TENANT, device_id=None, fingerprint=FINGERPRINT, machine_name="KASSA-1"
    )
    assert outcome.is_new
    assert outcome.device.status is DeviceStatus.PENDING_APPROVAL


def test_an_unknown_code_raises_instead_of_returning_none() -> None:
    use_case, _, _, _ = _build()
    with pytest.raises(DeviceNotFoundError):
        use_case.find_by_code(tenant_id=TENANT, actor=_FakeActor(), code="ZZZZZZ")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 7. Passivlik
# --------------------------------------------------------------------------- #


def test_inactivity_is_measured_from_registration_when_never_seen() -> None:
    """Təsdiqlənib heç açılmayan cihaz əbədi «təzə» qalmamalıdır."""
    device = _device(status=DeviceStatus.ACTIVE, store_id=STORE_A)
    assert device.last_seen_at is None
    assert device.is_inactive(now=NOW + timedelta(days=91), threshold=timedelta(days=90))
    assert not device.is_inactive(now=NOW + timedelta(days=89), threshold=timedelta(days=90))


def test_inactive_devices_are_blocked_and_free_their_slot() -> None:
    use_case, registry, audit, clock = _build(
        overrides={SystemLimitKey.DEVICE_INACTIVITY_DAYS.value: "30"}
    )
    # `stale` heç vaxt görünməyib → yaşı QEYDİYYAT anından ölçülür.
    stale = _device(status=DeviceStatus.ACTIVE, store_id=STORE_A)
    # `fresh` yoxlamadan bir gün əvvəl görünüb → həddin İÇİNDƏDİR.
    fresh = _device(status=DeviceStatus.ACTIVE, store_id=STORE_B, short_code="FRSH01")
    fresh.touch(now=NOW + timedelta(days=30))
    registry.save(stale)
    registry.save(fresh)

    clock.moment = NOW + timedelta(days=31)
    blocked = use_case.block_inactive_devices(tenant_id=TENANT)

    assert [d.id for d in blocked] == [stale.id]
    assert use_case.license_usage(TENANT).active == 1
    assert "DEVICE_AUTO_BLOCKED" in audit.actions()


def test_touch_does_not_revive_a_blocked_device() -> None:
    """Bloklanmış cihazın özünü göstərməsi FAKTdır — admin onu görməlidir."""
    device = _device(status=DeviceStatus.BLOCKED, store_id=STORE_A)
    device.touch(now=NOW)
    assert device.status is DeviceStatus.BLOCKED
    assert device.last_seen_at == NOW


def test_auto_approval_records_no_human_approver() -> None:
    """`approved_by` AVTOMATİK təsdiqdə `None` qalır — «None» sətri YOX.

    Süni identifikator (və ya `str(None)` = «None») audit izini
    yalanlaşdırardı: sonradan «kim təsdiqlədi?» sualına cavab axtaran adam
    mövcud olmayan bir istifadəçini axtarardı.
    """
    use_case, _, _, _ = _build(
        stores=[STORE_A],
        overrides={SystemLimitKey.DEVICE_APPROVAL_REQUIRED.value: "0"},
    )
    outcome = use_case.register_self(
        tenant_id=TENANT, device_id=None, fingerprint=FINGERPRINT, machine_name="KASSA-1"
    )

    assert outcome.device.status is DeviceStatus.ACTIVE
    assert outcome.device.approved_by is None

    events = outcome.device.collect_events()
    approved = [e for e in events if type(e).__name__ == "DeviceApprovedEvent"]
    assert approved, "təsdiq hadisəsi yaranmadı"
    assert approved[0].approved_by is None, "hadisə «None» sətri daşıyır"


# --------------------------------------------------------------------------- #
# 8. Açılış qapısının iki sərhəd halı (paketlənmiş `.exe` tapdı)
# --------------------------------------------------------------------------- #


def test_the_gate_helpers_exist_and_are_wired() -> None:
    """`app.py`-dakı qapı İKİ sərhəd halını AÇIQ idarə etməlidir.

    ────────────────────────────────────────────────────────────────────────
    HƏR İKİSİ FAKTİKİ `.exe` İCRASINDA TAPILDI
    ────────────────────────────────────────────────────────────────────────
    1. İLK QURAŞDIRMA: SEC-021-ə görə tenant kimliyi yerli faylda YARADILIR,
       `license_tenants` sətrini isə sihirbaz yazır. Yəni ilk açılışda cihaz
       qeydiyyatı `ForeignKeyViolation` ilə dayanır. Əvvəl bu, ümumi
       `except`-ə düşür və hər açılışda ERROR yazırdı — halbuki vəziyyət
       gözləniləndir.
    2. KİLİDLƏNMƏ: sihirbazdan sonrakı açılışda cihaz `PENDING` olur. Qapı
       onu bloklasaydı, təsdiqi verəcək admin məhz bloklanmış cihazın
       arxasında qalardı — çıxışsız dövrə.

    Qapı `app.py`-dadır (Qt tələb edir), ona görə burada onun QURULUŞU
    yoxlanılır: hər iki hal üçün ayrıca yol var və səbəb sənədləşib.
    5076 test bunların heç birini göstərmirdi, çünki hamısı tenant-ı hazır
    fərz edir.
    """
    from pathlib import Path as _Path

    source = (_Path(__file__).resolve().parents[2] / "src" / "presentation" / "app.py").read_text(
        encoding="utf-8"
    )

    assert "ForeignKeyViolation" in source, (
        "ilk quraşdırma halı ayrıca tutulmur — hər açılışda ERROR yazılacaq"
    )
    assert "DEVICE_GATE_DEFERRED" in source, "təxirə salınma jurnal açarı yoxdur"
    assert "_has_other_active_device" in source, "kilidlənmə qoruyucusu yoxdur"
    assert "DEVICE_GATE_OPEN_FIRST_DEVICE" in source, "ilk cihaz üçün jurnal açarı yoxdur"


def test_license_usage_answers_the_deadlock_question() -> None:
    """Qoruyucunun soruşduğu sual: «təsdiq verə biləcək iş yeri VARMI?».

    Cavab `license_usage().active` ilə verilir — `PENDING`/`BLOCKED` cihaz
    təsdiq verə bilməz, ona görə onlar sayılmamalıdır.
    """
    use_case, registry, _, _ = _build()
    registry.save(_device(status=DeviceStatus.PENDING_APPROVAL, short_code="PEND01"))
    registry.save(_device(status=DeviceStatus.BLOCKED, store_id=STORE_A, short_code="BLK001"))

    assert use_case.license_usage(TENANT).active == 0, (
        "gözləyən/bloklanmış cihaz «təsdiq verə bilən iş yeri» sayılır"
    )

    registry.save(_device(status=DeviceStatus.ACTIVE, store_id=STORE_A, short_code="ACT001"))
    assert use_case.license_usage(TENANT).active == 1
