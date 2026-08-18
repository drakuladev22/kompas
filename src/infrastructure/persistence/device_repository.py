"""Cihaz qeydiyyatının Postgres repozitoriyası (DEVICE-1).

──────────────────────────────────────────────────────────────────────────────
`tenant_id` ŞƏRTİ RLS-Ə ƏLAVƏ İKİNCİ QATDIR
──────────────────────────────────────────────────────────────────────────────
`registered_devices` RLS ilə qorunur (migrations/063), lakin hər sorğuda
`tenant_id = %s` şərti YENƏ DƏ yazılır — layihənin `_BaseRepository` naxışı
budur (`CLAUDE.md` §6). Səbəb: RLS `app.tenant_id` GUC-una bağlıdır və o,
`SET LOCAL` ilə tranzaksiya başında qoyulur; kontekstin qoyulmadığı bir yol
(miqrasiya skripti, `system_scope()`, gələcək bir refaktor) filtri tamamilə
söndürərdi. İki qatın hər ikisi sıradan çıxmayana qədər sızma olmur.

──────────────────────────────────────────────────────────────────────────────
SAYĞAC `COUNT(*)` İLƏ, SƏTİRLƏRİ GƏTİRMƏKLƏ YOX
──────────────────────────────────────────────────────────────────────────────
Lisenziya sayğacı hər açılışda və hər təsdiqdə oxunur. `len(list_all())`
yazsaydıq, hər oxunuşda bütün sətirlər şəbəkədən keçər və yalnız sayılmaq
üçün obyektə çevrilərdi. `COUNT(*)` qismən indeksdən (`idx_devices_active`)
oxunur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from src.domain.entities.registered_device import RegisteredDevice
from src.domain.value_objects.devices import DeviceFingerprint, DeviceStatus, DeviceType
from src.domain.value_objects.identifiers import DeviceId, StoreId
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import TenantId

#: Sətirdən obyektə çevirmə üçün oxunan sütunlar. Açıq siyahı `SELECT *`-dan
#: üstündür: yeni sütun əlavə olunanda mapper SÜKUTLA köhnəlmir — `KeyError`
#: dərhal üzə çıxır.
_COLUMNS: Final[str] = (
    "id, tenant_id, hardware_fingerprint, short_code, machine_name, device_name, "
    "store_id, device_type, status, block_reason, registered_at, approved_by, "
    "approved_at, last_seen_at, pending_fingerprint"
)


class PostgresDeviceRegistry(_BaseRepository):
    """`DeviceRegistry` portunun implementasiyası."""

    def get(self, device_id: DeviceId) -> RegisteredDevice | None:
        row = self._fetch_one(
            f"SELECT {_COLUMNS} FROM registered_devices WHERE id = %s AND tenant_id = %s",  # noqa: S608 — sütun siyahısı SABİTdir
            (str(device_id), str(self._tenant)),
        )
        return _to_device(row) if row else None

    def find_by_short_code(self, tenant_id: TenantId, short_code: str) -> RegisteredDevice | None:
        row = self._fetch_one(
            f"SELECT {_COLUMNS} FROM registered_devices "  # noqa: S608 — sütun siyahısı SABİTdir
            "WHERE tenant_id = %s AND short_code = %s",
            (str(tenant_id), short_code),
        )
        return _to_device(row) if row else None

    def short_code_exists(self, tenant_id: TenantId, short_code: str) -> bool:
        row = self._fetch_one(
            "SELECT 1 AS hit FROM registered_devices WHERE tenant_id = %s AND short_code = %s",
            (str(tenant_id), short_code),
        )
        return row is not None

    def list_by_status(
        self, tenant_id: TenantId, status: str, *, limit: int
    ) -> list[RegisteredDevice]:
        rows = self._fetch_all(
            f"SELECT {_COLUMNS} FROM registered_devices "  # noqa: S608 — sütun siyahısı SABİTdir
            "WHERE tenant_id = %s AND status = %s "
            "ORDER BY registered_at DESC LIMIT %s",
            (str(tenant_id), status, limit),
        )
        return [_to_device(row) for row in rows]

    def list_all(self, tenant_id: TenantId, *, limit: int) -> list[RegisteredDevice]:
        # Sıralama QƏSDƏN status ilə başlayır: admin ekranını açanda ilk
        # görməli olduğu şey təsdiq gözləyənlərdir, ən son qeydiyyat deyil.
        rows = self._fetch_all(
            f"SELECT {_COLUMNS} FROM registered_devices "  # noqa: S608 — sütun siyahısı SABİTdir
            "WHERE tenant_id = %s "
            "ORDER BY CASE status WHEN 'PENDING_APPROVAL' THEN 0 WHEN 'ACTIVE' THEN 1 "
            "ELSE 2 END, registered_at DESC LIMIT %s",
            (str(tenant_id), limit),
        )
        return [_to_device(row) for row in rows]

    def count_active(self, tenant_id: TenantId) -> int:
        return self._count(tenant_id, DeviceStatus.ACTIVE.value)

    def count_pending(self, tenant_id: TenantId) -> int:
        return self._count(tenant_id, DeviceStatus.PENDING_APPROVAL.value)

    def _count(self, tenant_id: TenantId, status: str) -> int:
        row = self._fetch_one(
            "SELECT COUNT(*) AS total FROM registered_devices WHERE tenant_id = %s AND status = %s",
            (str(tenant_id), status),
        )
        return int(row["total"]) if row else 0

    def save(self, device: RegisteredDevice) -> None:
        """UPSERT — `_BaseRepository` naxışı (`ON CONFLICT`).

        `registered_at` və `created_at` UPDATE bloklarında YOXDUR: qeydiyyat
        anı bir dəfə baş verir və onu hər `save()`-də yenidən yazmaq cihazın
        yaşını sıfırlayardı — passivlik hesabı isə məhz ondan asılıdır.
        """
        self._execute(
            """
            INSERT INTO registered_devices
                (id, tenant_id, hardware_fingerprint, short_code, machine_name,
                 device_name, store_id, device_type, status, block_reason,
                 registered_at, approved_by, approved_at, last_seen_at,
                 pending_fingerprint)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                hardware_fingerprint = EXCLUDED.hardware_fingerprint,
                pending_fingerprint  = EXCLUDED.pending_fingerprint,
                short_code           = EXCLUDED.short_code,
                machine_name         = EXCLUDED.machine_name,
                device_name          = EXCLUDED.device_name,
                store_id             = EXCLUDED.store_id,
                device_type          = EXCLUDED.device_type,
                status               = EXCLUDED.status,
                block_reason         = EXCLUDED.block_reason,
                approved_by          = EXCLUDED.approved_by,
                approved_at          = EXCLUDED.approved_at,
                last_seen_at         = EXCLUDED.last_seen_at
            """,
            (
                str(device.id),
                str(device.tenant_id),
                device.fingerprint.value,
                device.short_code,
                device.machine_name,
                device.device_name,
                str(device.store_id) if device.store_id else None,
                device.device_type.value,
                device.status.value,
                device.block_reason,
                device.registered_at,
                str(device.approved_by) if device.approved_by else None,
                device.approved_at,
                device.last_seen_at,
                device.pending_fingerprint.value if device.pending_fingerprint else None,
            ),
        )


class PostgresActiveStoreLookup(_BaseRepository):
    """`ActiveStoreLookup` portunun implementasiyası."""

    def list_active(self, tenant_id: TenantId) -> list[StoreId]:
        rows = self._fetch_all(
            "SELECT id FROM stores WHERE tenant_id = %s AND is_active ORDER BY name",
            (str(tenant_id),),
        )
        return [StoreId(row["id"]) for row in rows]


def _to_device(row: dict[str, Any]) -> RegisteredDevice:
    """Sətir → aqreqat.

    `emit_created_event=False` MƏCBURİDİR: bərpa edilən aqreqat hadisə
    YAYMAMALIDIR (`CLAUDE.md` §3). Əks halda hər oxunuş yeni
    `DeviceRegisteredEvent` doğurardı və admin hər ekran yeniləməsində
    «yeni cihaz» bildirişi alardı.
    """
    from src.domain.value_objects.identifiers import EmployeeId as _EmployeeId  # noqa: PLC0415

    return RegisteredDevice(
        id=DeviceId(row["id"]),
        tenant_id=row["tenant_id"],
        fingerprint=DeviceFingerprint(row["hardware_fingerprint"]),
        short_code=row["short_code"],
        machine_name=row["machine_name"],
        device_type=DeviceType(row["device_type"]),
        registered_at=row["registered_at"],
        status=DeviceStatus(row["status"]),
        store_id=StoreId(row["store_id"]) if row["store_id"] else None,
        device_name=row["device_name"],
        approved_by=_EmployeeId(row["approved_by"]) if row["approved_by"] else None,
        approved_at=row["approved_at"],
        last_seen_at=row["last_seen_at"],
        block_reason=row["block_reason"],
        # Gözləyən iz DAVAMLI olmalıdır: cihaz hər açılışda bazadan yenidən
        # oxunur. Yalnız yaddaşda saxlansaydı, dedupe hər restart-dan sonra
        # sıfırlanar və eyni uyğunsuzluq yenidən audit sətri yazardı — yəni
        # düzəliş özü-özünü ləğv edərdi.
        pending_fingerprint=(
            DeviceFingerprint(row["pending_fingerprint"]) if row["pending_fingerprint"] else None
        ),
        emit_created_event=False,
    )


__all__ = ["PostgresActiveStoreLookup", "PostgresDeviceRegistry"]
