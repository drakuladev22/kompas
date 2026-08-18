"""«Cihazlar» ekranının YAZI yolu (DEVICE-1 Faza 4).

`DeviceRegistryUseCase` ARTIQ yazılıb və `composition.py`-da bağlıdır; burada
YALNIZ ekran ↔ use case körpüsü qurulur (`controllers/__init__.py` başlığı:
kontrollerdə iş məntiqi YOXDUR).

──────────────────────────────────────────────────────────────────────────────
NİYƏ ÖZ KONTROLLERİ VAR (CLAUDE.md §6)
──────────────────────────────────────────────────────────────────────────────
Ekran HƏM oxuyur (siyahı + sayğac), HƏM yazır (təsdiq/blok/köçürmə) və hər
yazıdan sonra siyahı YENİDƏN oxunmalıdır: təsdiqlənmiş cihaz «gözləyənlər»
bölməsindən ÇIXIR və lisenziya sayğacı BİR artır. Sayğac yenilənməsəydi,
admin ardıcıl iki cihaz təsdiqləyəndə ikincidə gözlənilməz «limit doldu»
xətası görərdi — halbuki ekranda hələ yer olduğu yazılırdı.

SESSİYA SAXLANILMIR: hər əməliyyat üçün yeni sessiya açılır və commit edilir.
Cihaz paneli saatlarla açıq qala bilər; uzun-ömürlü tranzaksiya bu müddət
boyu `registered_devices` sətirlərində kilid saxlayardı və YENİ cihazın
qeydiyyatı — yəni mağazanın açılması — bloklanardı.

──────────────────────────────────────────────────────────────────────────────
GÖZLƏMƏ EKRANI ÜÇÜN AYRI, SESSİYASIZ GİRİŞ NÖQTƏSİ
──────────────────────────────────────────────────────────────────────────────
`DevicePendingController` `Employee` QƏBUL ETMİR və bu, qəsdəndir: cihaz
qeydiyyatı hələ heç kim giriş etməmişdən əvvəl baş verir (bax
`use_cases/device_registry.py` başlığı). Aktor tələb etsəydik, təsdiqlənməmiş
cihaz heç vaxt qeydiyyatdan keçə bilməzdi — istifadəçi giriş edə bilmir,
çünki cihaz təsdiqlənməyib; cihaz təsdiqlənə bilmir, çünki qeydiyyat üçün
istifadəçi lazımdır. Klassik dövri asılılıq.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from src.domain.value_objects.devices import DeviceStatus, DeviceType
from src.domain.value_objects.identifiers import DeviceId, StoreId
from src.infrastructure.config import device_identity
from src.infrastructure.timekeeping.clock import to_baku
from src.presentation.screens.devices import device_type_label, status_label
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.entities.registered_device import RegisteredDevice
    from src.presentation.composition import ApplicationContext
    from src.presentation.screens.devices import DeviceAdminScreen, DevicePendingScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

LIST_READ_FAILED: Final = "Cihaz siyahısı oxunmadı. Yenidən cəhd edin."
APPROVE_FAILED: Final = "Cihaz təsdiqlənmədi. Yenidən cəhd edin."
BLOCK_FAILED: Final = "Cihaz bloklanmadı. Yenidən cəhd edin."
ACCEPT_FINGERPRINT_FAILED: Final = "Aparat izi təsdiqlənmədi. Yenidən cəhd edin."
REGISTER_FAILED: Final = (
    "Cihaz qeydiyyatı aparıla bilmədi. Baza bağlantısını yoxlayıb yenidən cəhd edin."
)

#: Filial seçimi üçün ad lazımdır, lakin `ActiveStoreLookup` YALNIZ ID verir
#: (dar port — bax `ports.ActiveStoreLookup`). Adları mövcud oxu yolundan
#: götürürük; tapılmayan ID üçün qısaldılmış UUID göstərilir — «naməlum»
#: yazsaydıq admin hansı filialı seçdiyini bilməzdi.
_UNNAMED_STORE_PREFIX: Final = "Mağaza-"
_STORE_REF_CHARS: Final = 8


class DeviceAdminController:
    """«Cihazlar» ekranını `DeviceRegistryUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma ---------------------------------- #

    def attach(self, screen: DeviceAdminScreen) -> None:
        screen.approve_requested.connect(lambda payload: self._on_approve(screen, payload))
        screen.block_requested.connect(lambda device_id: self._on_block(screen, device_id))
        screen.reactivate_requested.connect(
            lambda device_id: self._on_reactivate(screen, device_id)
        )
        screen.reassign_requested.connect(lambda payload: self._on_reassign(screen, payload))
        screen.accept_fingerprint_requested.connect(
            lambda device_id: self._on_accept_fingerprint(screen, device_id)
        )
        screen.refresh_requested.connect(lambda: self.refresh(screen))
        self.refresh(screen)

    def refresh(self, screen: DeviceAdminScreen) -> None:
        """Siyahını, təsdiq növbəsini və lisenziya sayğacını yenidən oxuyur."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                devices = session.devices.list_all(tenant_id=session.tenant_id, actor=self._actor)
                usage = session.devices.license_usage(session.tenant_id)
                stores = _store_options(session)
        except KompasOSError as error:
            screen.set_pending([])
            screen.set_devices([])
            screen.show_error(title="Cihazlar oxunmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("DEVICE_LIST_FAILED")
            screen.set_pending([])
            screen.set_devices([])
            screen.show_error(title="Cihazlar oxunmadı", message=LIST_READ_FAILED)
            return

        names = dict(stores)
        screen.set_stores(stores)
        screen.set_usage(usage.describe())
        pending = [d for d in devices if d.status is DeviceStatus.PENDING_APPROVAL]
        screen.set_pending([_to_pending_row(d) for d in pending])
        screen.set_devices([_to_list_row(d, names) for d in devices])

    # ------------------------------- yazı yolu -------------------------------- #

    def _on_approve(self, screen: DeviceAdminScreen, payload: Any) -> None:
        if not isinstance(payload, dict):  # pragma: no cover - tip qoruyucusu
            return
        device_id = _as_device_id(payload.get("device_id"))
        store_id = _as_store_id(payload.get("store_id"))
        if device_id is None or store_id is None:
            screen.show_error(title="Təsdiq alınmadı", message="Filial seçilməyib.")
            return

        self._write(
            screen,
            failure=APPROVE_FAILED,
            title="Təsdiq alınmadı",
            action=lambda session: session.devices.approve(
                tenant_id=session.tenant_id,
                actor=self._actor,
                device_id=device_id,
                store_id=store_id,
                device_name=str(payload.get("device_name", "")),
                device_type=_as_device_type(payload.get("device_type")),
            ),
        )

    def _on_block(self, screen: DeviceAdminScreen, device_id: str) -> None:
        target = _as_device_id(device_id)
        if target is None:
            return
        self._write(
            screen,
            failure=BLOCK_FAILED,
            title="Bloklanmadı",
            action=lambda session: session.devices.block(
                tenant_id=session.tenant_id,
                actor=self._actor,
                device_id=target,
                reason="Administrator tərəfindən bloklandı",
            ),
        )

    def _on_reactivate(self, screen: DeviceAdminScreen, device_id: str) -> None:
        target = _as_device_id(device_id)
        if target is None:
            return
        self._write(
            screen,
            failure=BLOCK_FAILED,
            title="Bərpa edilmədi",
            action=lambda session: session.devices.reactivate(
                tenant_id=session.tenant_id, actor=self._actor, device_id=target
            ),
        )

    def _on_accept_fingerprint(self, screen: DeviceAdminScreen, device_id: str) -> None:
        """Gözləyən aparat izini təsdiqləyir — xəbərdarlığı bağlayır."""
        target = _as_device_id(device_id)
        if target is None:
            return
        self._write(
            screen,
            failure=ACCEPT_FINGERPRINT_FAILED,
            title="İz təsdiqlənmədi",
            action=lambda session: session.devices.accept_fingerprint(
                tenant_id=session.tenant_id, actor=self._actor, device_id=target
            ),
        )

    def _on_reassign(self, screen: DeviceAdminScreen, payload: Any) -> None:
        if not isinstance(payload, dict):  # pragma: no cover - tip qoruyucusu
            return
        device_id = _as_device_id(payload.get("device_id"))
        store_id = _as_store_id(payload.get("store_id"))
        if device_id is None or store_id is None:
            return
        self._write(
            screen,
            failure=APPROVE_FAILED,
            title="Filial dəyişdirilmədi",
            action=lambda session: session.devices.reassign_store(
                tenant_id=session.tenant_id,
                actor=self._actor,
                device_id=device_id,
                store_id=store_id,
            ),
        )

    def _write(
        self,
        screen: DeviceAdminScreen,
        *,
        failure: str,
        title: str,
        action: Any,
    ) -> None:
        """Bir yazı əməliyyatı + MƏCBURİ yenidən oxuma.

        `refresh()` uğursuzluqda DA çağırılır: xəta paralel dəyişiklikdən
        (başqa admin cihazı artıq təsdiqləyib) doğa bilər və o halda ekranın
        köhnə siyahını saxlaması istifadəçini eyni səhvə ikinci dəfə aparardı.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                action(session)
                session.commit()
        except KompasOSError as error:
            screen.show_error(title=title, message=error.user_message)
        except Exception:
            _error_log.exception("DEVICE_WRITE_FAILED")
            screen.show_error(title=title, message=failure)
        finally:
            self.refresh(screen)


class DevicePendingController:
    """Gözləmə ekranı — cihazı qeydiyyata salır və vəziyyəti yoxlayır.

    AKTOR YOXDUR (bax modul başlığı).
    """

    def __init__(self, context: ApplicationContext) -> None:
        self._context = context

    def attach(self, screen: DevicePendingScreen) -> None:
        screen.recheck_requested.connect(lambda: self.refresh(screen))
        self.refresh(screen)

    def refresh(self, screen: DevicePendingScreen) -> RegisteredDevice | None:
        """Cihazı qeydiyyata salır/oxuyur və ekranı yeniləyir.

        Returns:
            Cihaz sətri; oxuna bilmədisə `None`. Çağıran tərəf (`app.py`)
            `is_operational` yoxlayaraq ekranı bağlayıb işə davam edir.
        """
        screen.set_busy(True)
        try:
            device = self.register()
        except KompasOSError as error:
            screen.show_error(title="Qeydiyyat alınmadı", message=error.user_message)
            return None
        except Exception:
            _error_log.exception("DEVICE_REGISTER_FAILED")
            screen.show_error(title="Qeydiyyat alınmadı", message=REGISTER_FAILED)
            return None
        finally:
            screen.set_busy(False)

        screen.set_device(
            short_code=device.short_code,
            machine_name=device.machine_name,
            status=device.status,
        )
        return device

    def register(self) -> RegisteredDevice:
        """Cihazı tanıdır və kimliyi diskə yazır.

        Kimlik YALNIZ YENİ sətir yarandıqda yazılır: hər açılışda faylı
        yenidən yazmaq disk əməliyyatını əbəs təkrarlayar və faylın
        korlanma pəncərəsini genişləndirərdi.
        """
        stored = device_identity.load_device_id()
        fingerprint = device_identity.collect_fingerprint()
        with self._context.session() as session:
            outcome = session.devices.register_self(
                tenant_id=session.tenant_id,
                device_id=stored,
                fingerprint=fingerprint,
                machine_name=_machine_name(),
            )
            session.commit()
        if outcome.is_new:
            device_identity.save_device_id(outcome.device.id)
        return outcome.device


# --------------------------------------------------------------------------- #
# Çevirmə köməkçiləri
# --------------------------------------------------------------------------- #


def _machine_name() -> str:
    import socket  # noqa: PLC0415 — yalnız bu funksiyada lazımdır

    return socket.gethostname()


def _store_options(session: Any) -> list[tuple[str, str]]:
    """`(store_id, ad)` cütləri — ad tapılmasa qısaldılmış UUID."""
    # `session.uow.connection` — layihənin mövcud naxışı (`controllers/
    # announcements.py`, `attrition_risk.py`, `bulk_operations.py`).
    # `Session`-ın ÖZÜNDƏ `connection` yoxdur; ad `uow`-un arxasındadır və
    # bu, qəsdəndir: xam SQL yazan yol açıq şəkildə Unit of Work-dan keçir.
    rows = session.uow.connection.execute(
        "SELECT id, name FROM stores WHERE tenant_id = %s AND is_active ORDER BY name",
        (str(session.tenant_id),),
    ).fetchall()
    return [(str(row["id"]), str(row["name"])) for row in rows]


def _to_pending_row(device: RegisteredDevice) -> dict[str, object]:
    return {
        "id": str(device.id),
        "short_code": device.short_code,
        "machine_name": device.machine_name,
    }


def _to_list_row(device: RegisteredDevice, names: dict[str, str]) -> dict[str, object]:
    store = ""
    if device.store_id is not None:
        key = str(device.store_id)
        store = names.get(key, f"{_UNNAMED_STORE_PREFIX}{key[:_STORE_REF_CHARS]}")
    return {
        "id": str(device.id),
        "name": device.device_name or device.machine_name or device.short_code,
        # AD DEYİL, İD: ekran «Köçür» seçicisində cari filialı seçili göstərir
        # və uyğunlaşdırmanı ID ilə edir. Ada görə uyğunlaşdırsaydıq, iki
        # mağazanın eyni adı (məs. iki «Mərkəz») seçimi səhv sətrə bağlayardı.
        "store_id": str(device.store_id) if device.store_id else "",
        "store": store or "—",
        "type": device_type_label(device.device_type),
        "status": device.status.value,
        "status_label": status_label(device.status),
        "last_seen": _format_moment(device.last_seen_at),
        # İZİN ÖZÜ DEYİL, YALNIZ «GÖZLƏYİR» FAKTI: 32 simvolluq hash ekranda
        # heç bir qərar dəstəkləmir — admin onu heç nə ilə müqayisə edə
        # bilmir. Qərara lazım olan yeganə məlumat budur ki, dəyişiklik
        # görülüb və təsdiq gözləyir.
        "fingerprint_pending": device.pending_fingerprint is not None,
    }


def _format_moment(moment: datetime | None) -> str:
    """`gg.aa.iiii ss:dd` — Bakı yerli vaxtı ilə.

    `strftime("%c")` və ya `%B` İŞLƏDİLMİR: onlar sistem lokalından asılıdır
    və Windows-da mağaza PC-sinin dilinə görə dəyişir (`screen_data.py`-dakı
    eyni qərar). Format burada AÇIQ yazılır ki, hər maşında eyni görünsün.

    Saxlama UTC-dir, göstərmə isə yerli — `to_baku()` `clock.py`-dakı
    «UI-da göstərmək üçün» qaydasıdır.
    """
    if moment is None:
        return "—"
    return to_baku(moment).strftime("%d.%m.%Y %H:%M")


def _as_device_id(raw: object) -> DeviceId | None:
    parsed = _as_uuid(raw)
    return DeviceId(parsed) if parsed else None


def _as_store_id(raw: object) -> StoreId | None:
    parsed = _as_uuid(raw)
    return StoreId(parsed) if parsed else None


def _as_uuid(raw: object) -> uuid.UUID | None:
    import uuid as _uuid  # noqa: PLC0415 — yalnız çevirmədə lazımdır

    try:
        return _uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return None


def _as_device_type(raw: object) -> DeviceType:
    """Naməlum tip `ADMIN_PC`-yə düşür — ekran yalnız kataloqdan seçim verir.

    Sükutla defolt seçmək burada TƏHLÜKƏSİZDİR: cihaz tipi hansı ekranların
    açılacağını müəyyən edir, səlahiyyət vermir. Ən məhdud variant isə məhz
    `ADMIN_PC`-dir (kiosk rejimi tam ekran kilid tələb edir).
    """
    try:
        return DeviceType(str(raw))
    except ValueError:
        return DeviceType.ADMIN_PC


__all__ = [
    "APPROVE_FAILED",
    "BLOCK_FAILED",
    "LIST_READ_FAILED",
    "REGISTER_FAILED",
    "DeviceAdminController",
    "DevicePendingController",
]
