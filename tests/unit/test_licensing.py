"""Lisenziya klienti, yerli keş və Developer Paneli — Faza 3.11 testləri.

Testlərin ağırlıq mərkəzi `licensing.evaluate()`-dədir: bütün kommersiya
riski məhz orada cəmlənir. "Bloklamalı idi, bloklamadı" = ödənişsiz istifadə;
"bloklamamalı idi, blokladı" = 21 filialın dayanması. İkinci səhv birincidən
BAHADIR, ona görə testlər xüsusilə "bloklamamalıdır" halları üzərində
israrlıdır.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from src.application.use_cases.license_status import (
    MANAGE_LICENSE_FLAG,
    LicenseStatusUseCase,
    LicenseViewError,
    blocked_screen_text,
)
from src.developer_panel.console import (
    confirmation_text,
    render_audit_trail,
    render_table,
    run_console,
)
from src.domain.entities.employee import Employee
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import PermissionFlag, SystemRole
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import EmployeeId, PositionId, StoreId, TenantId
from src.domain.value_objects.licensing import (
    BLOCKED_RECHECK_INTERVAL_SECONDS,
    DEFAULT_CHECK_IN_INTERVAL_SECONDS,
    DEFAULT_OFFLINE_GRACE_DAYS,
    EXTENSION_DAYS,
    MAX_OFFLINE_GRACE_DAYS,
    RETRY_INTERVAL_SECONDS,
    CheckInRequest,
    CrashReport,
    LicenseNotFoundError,
    LicenseSnapshot,
    LicenseStatus,
    LicenseUnavailableError,
    RestrictionKind,
    Telemetry,
    anonymous_tenant_ref,
    evaluate,
    extend_by_month,
    payment_warning,
)
from src.infrastructure.licensing.client import LicenseClient
from src.infrastructure.licensing.developer_directory import (
    DEVELOPER_MODE_ENV,
    SERVICE_ROLE_ENV,
    DeveloperModeRequiredError,
    DeveloperTenantDirectory,
    ExtensionResult,
    TenantRow,
    developer_mode_enabled,
)
from src.infrastructure.licensing.state_store import EncryptedLicenseStateStore

if TYPE_CHECKING:
    from src.infrastructure.security.encryption import EncryptionService

TENANT = TenantId(uuid.UUID("11111111-1111-1111-1111-111111111111"))
STORE = StoreId(uuid.uuid4())
NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
VENDOR = "destek@kompasos.az"
#: `expires_at=None` ilə "verilməyib"-i ayırd etmək üçün (None real dəyərdir).
UNSET = object()


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def make_snapshot(
    status: LicenseStatus = LicenseStatus.AKTIV,
    *,
    checked_at: datetime = NOW,
    expires_at: Any = UNSET,
    **kwargs: Any,
) -> LicenseSnapshot:
    defaults: dict[str, Any] = {
        "tenant_name": "Kompas Retail",
        "offline_grace_days": DEFAULT_OFFLINE_GRACE_DAYS,
        "vendor_contact": VENDOR,
    }
    defaults.update(kwargs)
    return LicenseSnapshot(
        status=status,
        checked_at=checked_at,
        expires_at=NOW + timedelta(days=25) if expires_at is UNSET else expires_at,
        **defaults,
    )


def make_employee(*flags: str) -> Employee:
    position = Position(
        position_id=PositionId(uuid.uuid4()),
        code=SystemRole.CEO.value,
        name_az="CEO",
        priority=SystemRole.CEO.default_priority,
        is_system=True,
    )
    for code in flags:
        position.grant(PermissionFlag(code=code, category="LICENSE"))
    return Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=position,
        first_name="Test",
        last_name="CEO",
        store_id=STORE,
        username=Username.parse(f"u{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )


class FakeGateway:
    """Bazasız `LicenseGateway`."""

    def __init__(
        self, snapshot: LicenseSnapshot | None = None, error: Exception | None = None
    ) -> None:
        self.snapshot = snapshot
        self.error = error
        self.requests: list[CheckInRequest] = []
        self.crashes: list[CrashReport] = []

    def check_in(self, request: CheckInRequest) -> LicenseSnapshot:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.snapshot is not None
        return self.snapshot

    def report_crash(self, report: CrashReport) -> None:
        if self.error is not None:
            raise self.error
        self.crashes.append(report)


class FakeStore:
    """Yaddaşda `LicenseStateStore`."""

    def __init__(
        self,
        snapshot: LicenseSnapshot | None = None,
        *,
        first_run: datetime | None = None,
        rollback: bool = False,
        high_water: datetime | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.saved: list[LicenseSnapshot] = []
        self._first_run = first_run
        self._rollback = rollback
        self._high_water = high_water

    def load(self) -> LicenseSnapshot | None:
        return self.snapshot

    def save(self, snapshot: LicenseSnapshot) -> None:
        self.snapshot = snapshot
        self.saved.append(snapshot)

    def first_run_at(self) -> datetime | None:
        return self._first_run

    def clock_high_water(self) -> datetime | None:
        return self._high_water

    def clock_rollback_detected(self, now: datetime) -> bool:
        return self._rollback


# --------------------------------------------------------------------------- #
# evaluate() — modulun məntiqi mərkəzi
# --------------------------------------------------------------------------- #


class TestEvaluate:
    def test_aktiv_ve_muddeti_kecmemis_lisenziya_mehdudlasdirmir(self) -> None:
        state = evaluate(make_snapshot(), now=NOW + timedelta(hours=6))

        assert state.restrictions == ()
        assert not state.is_blocked
        assert not state.time_critical_blocked

    def test_muddet_bitdikde_tetbiq_baglanir(self) -> None:
        """SƏRVİS-SİZ AVTOMATİK DAYANMA: yalnız tarix müqayisəsi."""
        snapshot = make_snapshot(expires_at=NOW - timedelta(minutes=1))

        state = evaluate(snapshot, now=NOW)

        assert state.is_blocked
        assert state.has(RestrictionKind.LICENSE_INACTIVE)

    def test_muddet_bitmesi_ekraninda_sebeb_ve_tarix_gosterilir(self) -> None:
        """Bölmə 8: ümumi xəta mesajı OLMAMALIDIR."""
        snapshot = make_snapshot(
            expires_at=datetime(2026, 8, 1, tzinfo=UTC), last_payment_date=date(2026, 7, 1)
        )

        headline, detail, contact = blocked_screen_text(evaluate(snapshot, now=NOW))

        assert headline
        assert "Lisenziya müddəti başa çatıb." in detail
        assert "01.08.2026" in detail
        assert "01.07.2026" in detail
        assert contact == VENDOR
        assert "qorunur" in detail

    def test_deaktiv_status_da_tetbiqi_baglayir(self) -> None:
        snapshot = make_snapshot(
            LicenseStatus.DEAKTIV, deactivation_reason="Aylıq ödəniş edilməyib."
        )

        state = evaluate(snapshot, now=NOW)

        assert state.is_blocked
        assert "Aylıq ödəniş edilməyib." in state.restrictions[0].detail_az

    def test_kohnelmis_bloklama_hele_de_baglayir(self) -> None:
        """ANTİ-TAMPER: şəbəkəni kəsməklə blokdan qurtulmaq mümkün olmamalıdır."""
        stale = make_snapshot(LicenseStatus.DEAKTIV, checked_at=NOW - timedelta(days=365))

        assert evaluate(stale, now=NOW).is_blocked

    def test_saat_geri_cekilse_de_bitmis_lisenziya_acilmir(self) -> None:
        """`expires_at` müqayisəsi `max(indi, görülmüş ən böyük an)` ilə gedir."""
        snapshot = make_snapshot(expires_at=NOW - timedelta(days=1))

        # İstifadəçi saatı iki ay geri çəkdi — lakin yüksək-su nişanı qalır.
        state = evaluate(snapshot, now=NOW - timedelta(days=60), clock_high_water=NOW)

        assert state.is_blocked

    def test_yuksek_su_nisani_olmadan_saat_hiylesi_isleyerdi(self) -> None:
        """Qorumanın həqiqətən işlədiyini göstərən əks-nümunə."""
        snapshot = make_snapshot(expires_at=NOW - timedelta(days=1))

        without_guard = evaluate(snapshot, now=NOW - timedelta(days=60))

        assert not without_guard.is_blocked  # ← məhz buna görə nişan lazımdır

    def test_qrace_daxilinde_kohnelmis_oxunus_mehdudiyyet_yaratmir(self) -> None:
        snapshot = make_snapshot(
            checked_at=NOW - timedelta(days=13), expires_at=NOW + timedelta(days=60)
        )

        state = evaluate(snapshot, now=NOW)

        assert state.restrictions == ()
        assert state.offline_grace_days_left == 1

    def test_qrace_bitdikde_yalniz_xeberdarliq_olur(self) -> None:
        """LICENSE_UNVERIFIED bloklamır — mağaza işini davam etdirir."""
        snapshot = make_snapshot(
            checked_at=NOW - timedelta(days=20), expires_at=NOW + timedelta(days=60)
        )

        state = evaluate(snapshot, now=NOW)

        assert state.has(RestrictionKind.LICENSE_UNVERIFIED)
        assert not state.is_blocked
        assert not state.time_critical_blocked

    def test_qrace_hedd_araligina_sixilir(self) -> None:
        """DB CHECK-i 7–14; sətirdə 90 yazılsa da 14 tətbiq olunur."""
        snapshot = make_snapshot(
            checked_at=NOW - timedelta(days=20),
            expires_at=NOW + timedelta(days=60),
            offline_grace_days=90,
        )

        state = evaluate(snapshot, now=NOW)

        assert snapshot.effective_offline_grace_days == MAX_OFFLINE_GRACE_DAYS
        assert state.has(RestrictionKind.LICENSE_UNVERIFIED)

    def test_saat_geri_cekilende_qrace_uzanmir(self) -> None:
        snapshot = make_snapshot(
            checked_at=NOW - timedelta(days=1), expires_at=NOW + timedelta(days=60)
        )

        state = evaluate(snapshot, now=NOW, clock_rollback=True)

        assert state.has(RestrictionKind.LICENSE_UNVERIFIED)
        assert state.clock_rollback_detected
        # Yenə də BLOKLAMIR: eyni simptomu ölmüş CMOS batareyası da yaradır.
        assert not state.is_blocked

    def test_muddetsiz_qeyd_hec_vaxt_bitmir(self) -> None:
        """`expires_at IS NULL` — köhnə qeydlərlə uyğunluq."""
        snapshot = make_snapshot(expires_at=None)

        state = evaluate(snapshot, now=NOW + timedelta(days=3650))

        assert not state.is_blocked
        assert state.license_days_left is None

    def test_teze_qurasdirma_derhal_xeberdarliq_vermir(self) -> None:
        state = evaluate(None, now=NOW, first_run_at=NOW)

        assert state.restrictions == ()
        assert state.offline_grace_days_left == DEFAULT_OFFLINE_GRACE_DAYS

    def test_hec_vaxt_oxunmayan_qurasdirma_qrace_sonunda_xeberdarliq_verir(self) -> None:
        state = evaluate(None, now=NOW, first_run_at=NOW - timedelta(days=30))

        assert state.has(RestrictionKind.LICENSE_UNVERIFIED)
        assert not state.is_blocked

    def test_uc_status_bir_birini_evez_etmir(self) -> None:
        """Bölmə 8: üç status qarışdırılmamalı, AYRI-AYRI işlənməlidir."""
        state = evaluate(make_snapshot(LicenseStatus.DEAKTIV), now=NOW, time_drift_seconds=900.0)

        kinds = {item.kind for item in state.restrictions}
        assert kinds == {RestrictionKind.TIME_DRIFT_DETECTED, RestrictionKind.LICENSE_INACTIVE}
        assert len({item.detail_az for item in state.restrictions}) == 2

    def test_saat_surusmesi_yalniz_vaxt_kritik_emeliyyatlari_bloklayir(self) -> None:
        state = evaluate(make_snapshot(), now=NOW, time_drift_seconds=120.0)

        assert state.time_critical_blocked
        assert not state.is_blocked

    def test_dev_muhitinde_lisenziya_bloklamir(self) -> None:
        """Faza 1 qeydi: DEV-də lisenziya bloku testləri dayandırmamalıdır."""
        state = evaluate(
            make_snapshot(expires_at=NOW - timedelta(days=100)), now=NOW, dev_mode=True
        )

        assert not state.is_blocked
        assert state.restrictions == ()

    def test_dev_muhiti_saat_surusmesini_gizletmir(self) -> None:
        state = evaluate(make_snapshot(), now=NOW, time_drift_seconds=200.0, dev_mode=True)

        assert state.has(RestrictionKind.TIME_DRIFT_DETECTED)


class TestExtendByMonth:
    def test_gelecek_muddete_30_gun_elave_olunur(self) -> None:
        assert extend_by_month(NOW + timedelta(days=10), now=NOW) == NOW + timedelta(days=40)

    def test_kecmis_muddet_bugundan_baslayir(self) -> None:
        """Mənfi qalıq YIĞILMIR — gec ödəyən müştəri dərhal açılır."""
        result = extend_by_month(NOW - timedelta(days=40), now=NOW)

        assert result == NOW + timedelta(days=EXTENSION_DAYS)

    def test_muddet_yoxdursa_bugundan_baslayir(self) -> None:
        assert extend_by_month(None, now=NOW) == NOW + timedelta(days=EXTENSION_DAYS)

    def test_uzatma_derhal_bloku_goturur(self) -> None:
        expired = make_snapshot(expires_at=NOW - timedelta(days=40))
        assert evaluate(expired, now=NOW).is_blocked

        renewed = make_snapshot(expires_at=extend_by_month(expired.expires_at, now=NOW))

        assert not evaluate(renewed, now=NOW).is_blocked


class TestPaymentWarning:
    def test_uzaq_muddet_ucun_banner_yoxdur(self) -> None:
        assert payment_warning(make_snapshot(expires_at=NOW + timedelta(days=60)), now=NOW) == ""

    def test_bitmeye_yaxin_muddet_xeberdarliq_verir(self) -> None:
        snapshot = make_snapshot(expires_at=NOW + timedelta(days=3, hours=1))

        message = payment_warning(snapshot, now=NOW)

        assert "3 gün qalır" in message
        assert "12.08.2026" in message

    def test_son_gun_ayrica_metnle_gosterilir(self) -> None:
        snapshot = make_snapshot(expires_at=NOW + timedelta(hours=5))

        assert "bu gün bitir" in payment_warning(snapshot, now=NOW)

    def test_bitmis_muddet_banner_deyil_ekrandir(self) -> None:
        """Müddət keçibsə bu, banner deyil — tam bloklama ekranıdır."""
        snapshot = make_snapshot(expires_at=NOW - timedelta(days=1))

        assert payment_warning(snapshot, now=NOW) == ""
        assert evaluate(snapshot, now=NOW).is_blocked


class TestSnapshotSerialization:
    def test_gedis_donus_deyeri_qoruyur(self) -> None:
        original = make_snapshot(
            LicenseStatus.ODENIS_GOZLENILIR,
            expires_at=datetime(2026, 9, 1, tzinfo=UTC),
            last_payment_date=date(2026, 7, 1),
            next_payment_date=date(2026, 8, 1),
            grace_period_days=5,
        )

        assert LicenseSnapshot.from_dict(original.as_dict(), checked_at=NOW) == original

    def test_namelum_status_deaktiv_kimi_oxunmur(self) -> None:
        """Sxemanın gələcək versiyası bütün quraşdırmaları bağlamamalıdır."""
        restored = LicenseSnapshot.from_dict(
            {"status": "SUSPENDED_FOR_REVIEW", "expires_at": (NOW + timedelta(days=5)).isoformat()},
            checked_at=NOW,
        )

        assert restored.status is LicenseStatus.ODENIS_GOZLENILIR
        assert not evaluate(restored, now=NOW).is_blocked

    def test_naive_datetime_redd_edilir(self) -> None:
        with pytest.raises(ValueError, match="tz-aware"):
            LicenseSnapshot(status=LicenseStatus.AKTIV, checked_at=datetime(2026, 8, 9))  # noqa: DTZ001

    def test_naive_expires_at_da_redd_edilir(self) -> None:
        with pytest.raises(ValueError, match="tz-aware"):
            LicenseSnapshot(
                status=LicenseStatus.AKTIV,
                checked_at=NOW,
                expires_at=datetime(2026, 9, 1),  # noqa: DTZ001
            )

    def test_yararsiz_tarix_sukutla_atilir(self) -> None:
        restored = LicenseSnapshot.from_dict(
            {"status": "AKTIV", "next_payment_date": "olmayan-tarix"}, checked_at=NOW
        )

        assert restored.next_payment_date is None


class TestTelemetryPrivacy:
    def test_telemetriya_yalniz_saygac_saxlayir(self) -> None:
        payload = Telemetry(active_users=12, store_count=21).as_dict()

        assert all(isinstance(value, int) for value in payload.values())
        assert set(payload) == {
            "active_users",
            "store_count",
            "erp_server_count",
            "pending_sync_count",
        }

    def test_anonim_referans_tenant_id_ni_askar_etmir(self) -> None:
        ref = anonymous_tenant_ref(TENANT)

        assert str(TENANT) not in ref
        assert ref == anonymous_tenant_ref(TENANT)  # determinstik
        assert ref != anonymous_tenant_ref(TenantId(uuid.uuid4()))


# --------------------------------------------------------------------------- #
# Yerli şifrələnmiş vəziyyət
# --------------------------------------------------------------------------- #


class TestStateStore:
    def test_saxlanan_veziyyet_geri_oxunur(
        self, encryption_service: EncryptionService, tmp_path: Path
    ) -> None:
        store = EncryptedLicenseStateStore(
            TENANT, encryption_service, directory=tmp_path, clock=lambda: NOW
        )
        snapshot = make_snapshot(LicenseStatus.ODENIS_GOZLENILIR)

        store.save(snapshot)
        reopened = EncryptedLicenseStateStore(
            TENANT, encryption_service, directory=tmp_path, clock=lambda: NOW
        )

        assert reopened.load() == snapshot

    def test_fayl_duz_metn_deyil(
        self, encryption_service: EncryptionService, tmp_path: Path
    ) -> None:
        store = EncryptedLicenseStateStore(
            TENANT, encryption_service, directory=tmp_path, clock=lambda: NOW
        )
        store.save(make_snapshot(LicenseStatus.DEAKTIV))

        assert "DEAKTIV" not in store.path.read_text(encoding="ascii")

    def test_deyisdirilmis_fayl_qebul_edilmir(
        self, encryption_service: EncryptionService, tmp_path: Path
    ) -> None:
        """Notepad ilə müddəti uzatmaq işləməməlidir."""
        store = EncryptedLicenseStateStore(
            TENANT, encryption_service, directory=tmp_path, clock=lambda: NOW
        )
        store.save(make_snapshot(LicenseStatus.DEAKTIV))
        store.path.write_text(
            json.dumps({"version": 1, "snapshot": {"status": "AKTIV"}}), encoding="ascii"
        )

        reopened = EncryptedLicenseStateStore(
            TENANT, encryption_service, directory=tmp_path, clock=lambda: NOW
        )

        assert reopened.load() is None

    def test_basqa_tenantin_fayli_acilmir(
        self, encryption_service: EncryptionService, tmp_path: Path
    ) -> None:
        """AAD konteksti faylı quraşdırmaya bağlayır."""
        EncryptedLicenseStateStore(
            TENANT, encryption_service, directory=tmp_path, clock=lambda: NOW
        ).save(make_snapshot())

        other = EncryptedLicenseStateStore(
            TenantId(uuid.uuid4()), encryption_service, directory=tmp_path, clock=lambda: NOW
        )

        assert other.load() is None

    def test_saatin_geri_cekilmesi_askarlanir(
        self, encryption_service: EncryptionService, tmp_path: Path
    ) -> None:
        store = EncryptedLicenseStateStore(
            TENANT, encryption_service, directory=tmp_path, clock=lambda: NOW
        )
        store.save(make_snapshot(checked_at=NOW))

        assert store.clock_rollback_detected(NOW - timedelta(days=7))

    def test_kicik_saat_duzelisi_heyecan_yaratmir(
        self, encryption_service: EncryptionService, tmp_path: Path
    ) -> None:
        store = EncryptedLicenseStateStore(
            TENANT, encryption_service, directory=tmp_path, clock=lambda: NOW
        )
        store.save(make_snapshot(checked_at=NOW))

        assert not store.clock_rollback_detected(NOW - timedelta(seconds=30))

    def test_yuksek_su_nisani_saxlanilir(
        self, encryption_service: EncryptionService, tmp_path: Path
    ) -> None:
        store = EncryptedLicenseStateStore(
            TENANT, encryption_service, directory=tmp_path, clock=lambda: NOW
        )
        store.save(make_snapshot(checked_at=NOW))

        high_water = store.clock_high_water()

        assert high_water is not None
        assert high_water >= NOW

    def test_veziyyet_divar_saatindan_asili_deyil(
        self, encryption_service: EncryptionService, tmp_path: Path
    ) -> None:
        """REQRESSİYA: nişan real saatla yazılsaydı, sabit vaxtlı test günün
        saatı `NOW`-u keçəndə QƏFİLDƏN sınardı — yəni CI-ın nəticəsi saatdan
        asılı olardı. Vaxt mənbəyi inyeksiya olunur."""
        store = EncryptedLicenseStateStore(
            TENANT, encryption_service, directory=tmp_path, clock=lambda: NOW
        )

        assert store.clock_high_water() == NOW
        assert store.first_run_at() == NOW

    def test_ilk_isedusme_qeyd_olunur(
        self, encryption_service: EncryptionService, tmp_path: Path
    ) -> None:
        store = EncryptedLicenseStateStore(
            TENANT, encryption_service, directory=tmp_path, clock=lambda: NOW
        )

        assert store.first_run_at() is not None


# --------------------------------------------------------------------------- #
# LicenseClient
# --------------------------------------------------------------------------- #


class TestLicenseClient:
    def _client(self, gateway: FakeGateway, store: FakeStore, **kwargs: Any) -> LicenseClient:
        return LicenseClient(
            TENANT, gateway, store, app_version="1.0.0", clock=lambda: NOW, **kwargs
        )

    def test_ugurlu_oxunus_veziyyeti_saxlayir(self) -> None:
        gateway = FakeGateway(make_snapshot())
        store = FakeStore()

        client = self._client(gateway, store)
        client.check_in()

        assert store.saved
        assert client.current_state().restrictions == ()

    def test_elcatmaz_baza_xeta_atmir_ve_kesi_saxlayir(self) -> None:
        """Uğursuzluq NORMAL haldır: keşlənmiş `AKTIV` yerində qalır."""
        cached = make_snapshot(checked_at=NOW - timedelta(days=1))
        gateway = FakeGateway(error=LicenseUnavailableError("çatmır"))
        store = FakeStore(cached)

        client = self._client(gateway, store)

        assert client.check_in() is None
        assert client.snapshot == cached
        assert not client.current_state().is_blocked

    def test_tapilmayan_setir_tetbiqi_baglamir(self) -> None:
        gateway = FakeGateway(error=LicenseNotFoundError("sətir yoxdur"))
        client = self._client(gateway, FakeStore(make_snapshot()))

        client.check_in()

        assert not client.current_state().is_blocked

    def test_gozlenilmez_xeta_da_udulur(self) -> None:
        """Port tətbiqi gözlənilməz istisna atsa belə tətbiq dayanmamalıdır."""
        gateway = FakeGateway(error=RuntimeError("port nasazlığı"))
        client = self._client(gateway, FakeStore(make_snapshot()))

        assert client.check_in() is None

    def test_bitmis_muddet_derhal_bloklayir(self) -> None:
        gateway = FakeGateway(make_snapshot(expires_at=NOW - timedelta(days=1)))
        client = self._client(gateway, FakeStore(make_snapshot()))

        client.check_in()

        assert client.current_state().is_blocked

    def test_uzatmadan_sonra_yeniden_oxunus_bloku_goturur(self) -> None:
        """Developer Paneli uzadandan sonra "İndi Yoxla" dərhal açmalıdır."""
        store = FakeStore(make_snapshot(expires_at=NOW - timedelta(days=1)))
        gateway = FakeGateway(make_snapshot(expires_at=NOW + timedelta(days=30)))
        client = self._client(gateway, store)
        assert client.current_state().is_blocked

        client.check_in()

        assert not client.current_state().is_blocked

    def test_bloklanmis_veziyyetde_ritm_sixlasir(self) -> None:
        """ "Force Sync"in serversiz qarşılığı: ödəniş edilib, mağaza gözləyir.

        Sutkalıq ritmlə uzatma 24 saata qədər tətbiq olunmazdı — müştəri isə
        pulu ödəyib telefonun o başında dayanır.
        """
        gateway = FakeGateway(make_snapshot(expires_at=NOW - timedelta(days=1)))
        client = self._client(gateway, FakeStore())
        client.check_in()

        assert client._next_wait(success=True) == BLOCKED_RECHECK_INTERVAL_SECONDS

    def test_normal_veziyyetde_sutkaliq_ritm_qalir(self) -> None:
        gateway = FakeGateway(make_snapshot(expires_at=NOW + timedelta(days=30)))
        client = self._client(gateway, FakeStore())
        client.check_in()

        assert client._next_wait(success=True) == DEFAULT_CHECK_IN_INTERVAL_SECONDS

    def test_ugursuzluqda_bloklanma_ritmi_tetbiq_olunmur(self) -> None:
        """Şəbəkə yoxdursa problem lisenziya deyil — təkrar-cəhd ritmi işləyir."""
        gateway = FakeGateway(error=LicenseUnavailableError("çatmır"))
        client = self._client(gateway, FakeStore())

        assert client._next_wait(success=False) == RETRY_INTERVAL_SECONDS

    def test_telemetriya_gonderilir(self) -> None:
        gateway = FakeGateway(make_snapshot())
        client = self._client(
            gateway, FakeStore(), telemetry_source=lambda: Telemetry(active_users=7, store_count=21)
        )

        client.check_in()

        assert gateway.requests[0].telemetry.active_users == 7

    def test_saat_surusmesi_menbeyi_veziyyete_daxil_olur(self) -> None:
        client = self._client(
            FakeGateway(make_snapshot()), FakeStore(make_snapshot()), drift_source=lambda: 300.0
        )

        assert client.current_state().has(RestrictionKind.TIME_DRIFT_DETECTED)

    def test_saglamliq_setri_veziyyeti_ozetleyir(self) -> None:
        client = self._client(FakeGateway(), FakeStore(make_snapshot()))

        status = client.status

        assert status["license_status"] == LicenseStatus.AKTIV.value
        assert status["is_blocked"] is False
        assert status["license_days_left"] == 25

    def test_crash_hesabati_ugursuzlugu_udulur(self) -> None:
        gateway = FakeGateway(error=LicenseUnavailableError("çatmır"))
        client = self._client(gateway, FakeStore())

        assert not client.report_crash(
            CrashReport(
                anonymous_tenant_ref="abc",
                app_version="1.0.0",
                exception_type="ValueError",
                stack_trace="...",
                fingerprint="f1",
            )
        )


# --------------------------------------------------------------------------- #
# Developer Paneli
# --------------------------------------------------------------------------- #


def make_row(
    name: str = "Kompas Retail",
    *,
    status: LicenseStatus = LicenseStatus.AKTIV,
    expires_at: datetime | None = None,
    last_check_in_at: datetime | None = None,
    tenant_id: str | None = None,
) -> TenantRow:
    return TenantRow(
        tenant_id=tenant_id or str(TENANT),
        tenant_name=name,
        status=status,
        expires_at=expires_at if expires_at is not None else NOW + timedelta(days=20),
        last_check_in_at=last_check_in_at if last_check_in_at is not None else NOW,
        company_contact_email="info@kompas.az",
        app_version="1.0.0",
    )


class FakeDirectory:
    """Bazasız `DeveloperTenantDirectory` əvəzi."""

    def __init__(self, rows: list[TenantRow]) -> None:
        self._rows = rows
        self.extended: list[str] = []

    def list_tenants(self, *, search: str = "") -> list[TenantRow]:
        if not search:
            return list(self._rows)
        needle = search.casefold()
        return [row for row in self._rows if needle in row.tenant_name.casefold()]

    def get(self, tenant_id: str) -> TenantRow | None:
        return next((row for row in self._rows if row.tenant_id == tenant_id), None)

    def extend_one_month(self, tenant_id: str, *, now: datetime | None = None) -> ExtensionResult:
        moment = now or NOW
        current = self.get(tenant_id)
        assert current is not None
        self.extended.append(tenant_id)
        return ExtensionResult(
            tenant_id=tenant_id,
            tenant_name=current.tenant_name,
            old_expires_at=current.expires_at,
            new_expires_at=extend_by_month(current.expires_at, now=moment),
            reactivated=current.status is not LicenseStatus.AKTIV,
        )


class TestDeveloperModeGuard:
    def test_bayraq_teksinden_kifayet_etmir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`service_role` açarı olmadan panel açılmamalıdır."""
        monkeypatch.setenv(DEVELOPER_MODE_ENV, "true")
        monkeypatch.delenv(SERVICE_ROLE_ENV, raising=False)

        assert not developer_mode_enabled()

    def test_acar_teksinden_de_kifayet_etmir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(DEVELOPER_MODE_ENV, raising=False)
        monkeypatch.setenv(SERVICE_ROLE_ENV, "service-role-key")

        assert not developer_mode_enabled()

    def test_hər_ikisi_olduqda_acilir(self, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: PLC2401
        monkeypatch.setenv(DEVELOPER_MODE_ENV, "1")
        monkeypatch.setenv(SERVICE_ROLE_ENV, "service-role-key")

        assert developer_mode_enabled()

    def test_konfiqurasiyasiz_qurulus_redd_edilir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(DEVELOPER_MODE_ENV, raising=False)
        monkeypatch.delenv(SERVICE_ROLE_ENV, raising=False)

        with pytest.raises(DeveloperModeRequiredError):
            DeveloperTenantDirectory(database=None)  # type: ignore[arg-type]


class TestTenantRow:
    def test_qalan_gun_nisanda_gorunur(self) -> None:
        row = make_row(expires_at=NOW + timedelta(days=12, hours=1))

        assert row.badge_az(NOW) == "12 gün qalıb"

    def test_bitmis_lisenziya_nisanda_gorunur(self) -> None:
        assert "Bitib" in make_row(expires_at=NOW - timedelta(days=5)).badge_az(NOW)

    def test_deaktiv_nisani_muddetden_ustundur(self) -> None:
        row = make_row(status=LicenseStatus.DEAKTIV, expires_at=NOW + timedelta(days=100))

        assert row.badge_az(NOW) == "Deaktiv"

    def test_yaxinlasan_muddet_diqqet_teleb_edir(self) -> None:
        assert make_row(expires_at=NOW + timedelta(days=3)).needs_attention(NOW)

    def test_sessiz_qurasdirma_diqqet_teleb_edir(self) -> None:
        row = make_row(last_check_in_at=NOW - timedelta(days=10))

        assert row.needs_attention(NOW)

    def test_saglam_qurasdirma_diqqet_teleb_etmir(self) -> None:
        assert not make_row().needs_attention(NOW)


class TestDeveloperConsole:
    def test_cedvelde_setirler_gorunur(self) -> None:
        output = render_table([make_row("Bellona Baku"), make_row("Yataş Crescent")], now=NOW)

        assert "Bellona Baku" in output
        assert "Yataş Crescent" in output
        assert "Cəmi: 2 müştəri" in output

    def test_bos_siyahi_aydin_mesaj_verir(self) -> None:
        assert "tapılmadı" in render_table([], now=NOW)

    def test_tesdiq_metni_musteri_adini_gosterir(self) -> None:
        """Səhv sətrə basmaq riskinə qarşı ad açıq yazılır."""
        text = confirmation_text([make_row("Bellona Baku")])

        assert "Bellona Baku" in text
        assert f"{EXTENSION_DAYS} gün" in text

    def test_coxlu_secim_ucun_say_gosterilir(self) -> None:
        text = confirmation_text([make_row("A"), make_row("B"), make_row("C")])

        assert "3 müştərinin" in text

    def test_axtaris_suzgeci_isleyir(self) -> None:
        directory = FakeDirectory([make_row("Bellona"), make_row("Yataş")])

        code, output = run_console(directory, search="yat", now=NOW)  # type: ignore[arg-type]

        assert code == 0
        assert "Yataş" in output
        assert "Bellona" not in output

    def test_tesdiqsiz_uzatma_hec_ne_deyismir(self) -> None:
        """`--yes` olmadan yazma əməliyyatı icra edilməməlidir."""
        directory = FakeDirectory([make_row()])

        code, output = run_console(directory, extend=str(TENANT), now=NOW)  # type: ignore[arg-type]

        assert code == 2
        assert directory.extended == []
        assert "--yes" in output

    def test_tesdiqle_uzatma_icra_olunur(self) -> None:
        directory = FakeDirectory([make_row()])

        code, output = run_console(  # type: ignore[arg-type]
            directory, extend=str(TENANT), confirmed=True, now=NOW
        )

        assert code == 0
        assert directory.extended == [str(TENANT)]
        assert "uzadıldı" in output

    def test_deaktiv_musteri_uzadildiqda_aktivlesme_bildirilir(self) -> None:
        directory = FakeDirectory([make_row(status=LicenseStatus.DEAKTIV)])

        _, output = run_console(  # type: ignore[arg-type]
            directory, extend=str(TENANT), confirmed=True, now=NOW
        )

        assert "yenidən aktivləşdirildi" in output

    def test_olmayan_musteri_xeta_kodu_verir(self) -> None:
        directory = FakeDirectory([])

        code, output = run_console(directory, extend="yoxdur", confirmed=True, now=NOW)  # type: ignore[arg-type]

        assert code == 1
        assert "tapılmadı" in output

    def test_audit_izi_formatlanir(self) -> None:
        output = render_audit_trail(
            [
                {
                    "action": "EXTEND_ONE_MONTH",
                    "old_expires_at": NOW,
                    "new_expires_at": NOW + timedelta(days=30),
                    "performed_at": NOW,
                }
            ]
        )

        assert "EXTEND_ONE_MONTH" in output
        assert "09.08.2026" in output

    def test_bos_audit_izi_aydin_mesaj_verir(self) -> None:
        assert "qeydə alınmayıb" in render_audit_trail([])


# --------------------------------------------------------------------------- #
# Use case
# --------------------------------------------------------------------------- #


class FakeClient:
    def __init__(self, snapshot: LicenseSnapshot | None, **kwargs: Any) -> None:
        self._snapshot = snapshot
        self._kwargs = kwargs
        self.check_ins = 0

    def current_state(self) -> Any:
        return evaluate(self._snapshot, now=NOW, **self._kwargs)

    def payment_banner(self) -> str:
        return payment_warning(self._snapshot, now=NOW)

    def check_in(self) -> LicenseSnapshot | None:
        self.check_ins += 1
        return self._snapshot


class TestLicenseStatusUseCase:
    def test_icaze_olmadan_baxis_redd_edilir(self) -> None:
        use_case = LicenseStatusUseCase(FakeClient(make_snapshot()))  # type: ignore[arg-type]

        with pytest.raises(LicenseViewError):
            use_case.overview(make_employee(), now=NOW)

    def test_icaze_ile_ekran_melumati_qaytarilir(self) -> None:
        use_case = LicenseStatusUseCase(FakeClient(make_snapshot()))  # type: ignore[arg-type]

        overview = use_case.overview(make_employee(MANAGE_LICENSE_FLAG), now=NOW)

        assert overview.status_label_az == "Aktiv"
        assert overview.is_healthy
        assert not overview.is_blocked
        assert overview.license_days_left == 25

    def test_indi_yoxla_check_in_isledir(self) -> None:
        client = FakeClient(make_snapshot())
        use_case = LicenseStatusUseCase(client)  # type: ignore[arg-type]

        use_case.refresh(make_employee(MANAGE_LICENSE_FLAG), now=NOW)

        assert client.check_ins == 1

    def test_use_case_de_status_deyisdirme_metodu_yoxdur(self) -> None:
        """Bölmə 8: müştəri öz abunəsini heç vaxt aktivləşdirə bilməz.

        Qoruma `if`-lə deyil, metodun MÖVCUD OLMAMASI ilə təmin olunur.
        """
        forbidden = {"set_status", "activate", "deactivate", "toggle", "extend_one_month"}

        assert forbidden.isdisjoint(dir(LicenseStatusUseCase))

    def test_bloklanmis_ekran_ucun_ucluk_qaytarilir(self) -> None:
        client = FakeClient(make_snapshot(expires_at=NOW - timedelta(days=2)))
        use_case = LicenseStatusUseCase(client)  # type: ignore[arg-type]

        overview = use_case.overview(make_employee(MANAGE_LICENSE_FLAG), now=NOW)

        assert overview.is_blocked
        assert overview.blocking_restriction is not None
        assert not overview.is_healthy
