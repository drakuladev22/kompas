"""Cihaz qeydiyyatı və təsdiqi (DEVICE-1).

──────────────────────────────────────────────────────────────────────────────
İKİ AYRI AKTOR — VƏ ONA GÖRƏ İKİ AYRI GİRİŞ NÖQTƏSİ
──────────────────────────────────────────────────────────────────────────────
    `register_self()`   → CİHAZIN ÖZÜ çağırır. Aktor YOXDUR: bu, hələ heç kim
                          giriş etməmişdən ƏVVƏL, ilk açılışda baş verir.
                          Ona görə burada icazə yoxlaması DA yoxdur — nə
                          yoxlayaydıq, kimliyi olmayan bir prosesi?
    `approve()` / `block()` / `reassign()` → ADMİN çağırır və hər biri
                          `can_manage_devices` tələb edir.

Bu ayrılıq təhlükəsizlik boşluğu DEYİL, əksinə onun səbəbidir: qeydiyyat
sərbəstdir, LAKİN qeydiyyat heç nə açmır — cihaz `PENDING_APPROVAL`-da
qalır və heç bir məlumata çıxışı olmur. Açan yeganə şey admin təsdiqidir.

──────────────────────────────────────────────────────────────────────────────
LİSENZİYA SAYĞACI QEYDİYYATDA DEYİL, TƏSDİQDƏ YOXLANILIR
──────────────────────────────────────────────────────────────────────────────
Əks halda sayğac HÜCUM SƏTHİ olardı: kimliyi olmayan proses təkrar-təkrar
qeydiyyat yaradaraq müştərinin limitini tükəndirə və bütün mağazaları
bloklaya bilərdi. `PENDING_APPROVAL` sətirlər ucuzdur və heç nəyə çıxış
vermir; yer tutan yalnız `ACTIVE`-dir (bax `RegisteredDevice.counts_toward_
license`).

──────────────────────────────────────────────────────────────────────────────
AVTOMATİK TƏSDİQ TƏK MAĞAZALI QURAŞDIRMADA İŞLƏYİR — VƏ YALNIZ ORADA
──────────────────────────────────────────────────────────────────────────────
`DEVICE_APPROVAL_REQUIRED = 0` «kiçik müştəri üçün» nəzərdə tutulub. Lakin
təsdiq eyni zamanda FİLİAL TƏYİNATIDIR və cihaz öz filialını bilmir. Ona görə
avtomatik təsdiq yalnız kirayəçidə TƏK aktiv mağaza olduqda mümkündür — orada
seçim birmənalıdır. İki və daha çox mağazada avtomatik təsdiq «filialı təsadüfi
seç» demək olardı, yəni DEVICE-1-in həll etdiyi problemi geri gətirərdi.

Çox mağazalı quraşdırmada açar sükutla İGNOR EDİLMİR — cihaz `PENDING`-də
qalır və audit-ə səbəbi yazılır (`AUTO_APPROVE_AMBIGUOUS`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from src.domain.entities.registered_device import DeviceLicenseUsage, RegisteredDevice
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.devices import (
    DeviceStatus,
    DeviceType,
    generate_short_code,
    normalize_short_code,
)
from src.domain.value_objects.identifiers import new_device_id
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        ActiveStoreLookup,
        AuditTrail,
        Clock,
        DeviceRegistry,
        Notifier,
        SystemLimits,
    )
    from src.domain.value_objects.devices import DeviceFingerprint
    from src.domain.value_objects.identifiers import DeviceId, StoreId, TenantId

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

MANAGE_DEVICES_FLAG: Final = "can_manage_devices"

#: Qısa kod toqquşduqda neçə dəfə yenidən cəhd edilir.
#:
#: NİYƏ ROOT PARAMETRİ DEYİL: bu, riyazi zərurətin ölçüsüdür, siyasət deyil.
#: 25 simvollu əlifba × 6 mövqe = ~244 milyon kombinasiya; onlarla cihazı olan
#: kirayəçidə ikinci cəhdin də toqquşma ehtimalı praktiki olaraq sıfırdır.
#: Beş cəhddən sonra dayanmaq isə sonsuz dövrədən qoruyur.
SHORT_CODE_ATTEMPTS: Final[int] = 5

#: Siyahı ekranının bir oxunuşda gətirdiyi maksimum sətir.
#:
#: NİYƏ ROOT PARAMETRİ DEYİL: cihaz sayının ÖZÜ artıq Root parametridir
#: (`MAX_REGISTERED_DEVICES`, defolt 25) və bu tavan ondan iki tərtib
#: böyükdür — yəni praktikada heç vaxt kəsmir. İkinci, ondan asılı olmayan
#: hədd yaratmaq iki dəyərin bir gün ziddiyyətə düşməsini qaçılmaz edərdi.
LIST_LIMIT: Final[int] = 1000


class DevicePermissionError(KompasOSError):
    """`can_manage_devices` olmadan cihaz idarəsi cəhdi."""

    user_message = "Cihazları idarə etmək səlahiyyətiniz yoxdur."


class DeviceNotFoundError(KompasOSError):
    """Verilmiş identifikator/kod ilə cihaz tapılmadı."""

    user_message = "Cihaz tapılmadı. Kodu yenidən yoxlayın."


class DeviceLimitReachedError(KompasOSError):
    """Lisenziya cihaz həddi dolub."""

    user_message = "Cihaz limiti dolub. Yeni cihaz üçün limiti artırın və ya birini bloklayın."


@dataclass(frozen=True)
class DeviceRegistrationOutcome:
    """`register_self()` nəticəsi — cihaz özünü nə vəziyyətdə tapdı."""

    device: RegisteredDevice
    #: Sətir BU çağırışda yarandı (yəni ilk açılışdır).
    is_new: bool
    #: Aparat izi saxlanılandan fərqlidir — admin ekranında görünür.
    fingerprint_changed: bool = False


class DeviceRegistryUseCase:
    """Cihaz qeydiyyatı, təsdiqi və lisenziya sayğacı."""

    def __init__(
        self,
        *,
        devices: DeviceRegistry,
        stores: ActiveStoreLookup,
        audit: AuditTrail,
        clock: Clock,
        limits: SystemLimits,
        notifier: Notifier | None = None,
    ) -> None:
        self._devices = devices
        self._stores = stores
        self._audit = audit
        self._clock = clock
        self._limits = limits
        self._notifier = notifier

    # ------------------------------- cihaz yolu ------------------------------ #

    def register_self(
        self,
        *,
        tenant_id: TenantId,
        device_id: DeviceId | None,
        fingerprint: DeviceFingerprint,
        machine_name: str,
        device_type: DeviceType = DeviceType.ADMIN_PC,
    ) -> DeviceRegistrationOutcome:
        """Cihaz özünü tanıdır — ilk açılışda və hər sonrakı açılışda.

        AKTOR YOXDUR və bu, qəsdəndir (bax modul başlığı): çağırış hələ heç
        kim giriş etməmişdən əvvəl baş verir.

        Args:
            device_id: konfiqurasiyada saxlanılan kimlik; `None` = ilk açılış.
        """
        now = self._clock.now()

        if device_id is not None:
            existing = self._devices.get(device_id)
            if existing is not None:
                # Bu iz ARTIQ gözləyirmi — yoxlamadan ƏVVƏL soruşulur, çünki
                # `verify_fingerprint` onu elə indi yazacaq. Cihaz hər
                # açılışda qeydiyyatdan keçir; şərt olmasaydı eyni
                # uyğunsuzluq gündə onlarla audit sətri yaradar və HƏQİQİ
                # ikinci dəyişiklik həmin yığında görünməz qalardı.
                already_known = existing.pending_fingerprint == fingerprint
                matched = existing.verify_fingerprint(fingerprint)
                existing.touch(now=now)
                self._devices.save(existing)
                if not matched and not already_known:
                    # Bloklamırıq (bax entity başlığı) — lakin İZSİZ də
                    # buraxmırıq: audit yazısı mübahisə halında yeganə sübutdur.
                    self._audit.record(
                        tenant_id=tenant_id,
                        actor_id=None,
                        action="DEVICE_FINGERPRINT_CHANGED",
                        entity_type="registered_device",
                        entity_id=str(existing.id),
                        before_state={"fingerprint": existing.fingerprint.value},
                        after_state={"fingerprint": fingerprint.value},
                        reason="Aparat izi dəyişib — disk/anakart dəyişikliyi və ya köçürmə",
                    )
                return DeviceRegistrationOutcome(
                    device=existing, is_new=False, fingerprint_changed=not matched
                )
            # Konfiqurasiyada ID var, bazada sətir yoxdur. Bu, baza bərpasından
            # sonra normal haldır — yeni qeydiyyat yaradılır, xəta atılmır.
            _audit_log.warning(
                "DEVICE_ID_NOT_IN_REGISTRY",
                extra={"device_id": str(device_id), "action": "yeni qeydiyyat yaradılır"},
            )

        device = RegisteredDevice(
            id=new_device_id(),
            tenant_id=tenant_id,
            fingerprint=fingerprint,
            short_code=self._unique_short_code(tenant_id),
            machine_name=machine_name,
            device_type=device_type,
            registered_at=now,
        )
        self._maybe_auto_approve(device, tenant_id=tenant_id, now=now)
        self._devices.save(device)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=None,
            action="DEVICE_REGISTERED",
            entity_type="registered_device",
            entity_id=str(device.id),
            after_state={
                "machine_name": machine_name,
                "short_code": device.short_code,
                "status": device.status.value,
            },
        )
        self._notify_pending(device, tenant_id=tenant_id)
        return DeviceRegistrationOutcome(device=device, is_new=True)

    def _maybe_auto_approve(
        self, device: RegisteredDevice, *, tenant_id: TenantId, now: datetime
    ) -> None:
        """Root təsdiqi söndürübsə və filial BİRMƏNALIDIRsa dərhal aktivləşdirir."""
        if self._limit_int(tenant_id, SystemLimitKey.DEVICE_APPROVAL_REQUIRED):
            return

        stores = self._stores.list_active(tenant_id)
        if len(stores) != 1:
            # Sükutla ignor etmirik — açar açıqdır, lakin tətbiq oluna bilmir.
            _audit_log.warning(
                "DEVICE_AUTO_APPROVE_AMBIGUOUS",
                extra={
                    "device_id": str(device.id),
                    "store_count": len(stores),
                    "impact": "cihaz təsdiq gözləyir — filialı yalnız admin seçə bilər",
                },
            )
            return

        usage = self.license_usage(tenant_id)
        if not usage.has_capacity:
            _audit_log.warning(
                "DEVICE_AUTO_APPROVE_BLOCKED_BY_LIMIT",
                extra={"device_id": str(device.id), "active": usage.active, "limit": usage.limit},
            )
            return

        store_id = stores[0]
        device.approve(
            store_id=store_id,
            device_name=device.machine_name or "Cihaz",
            device_type=device.device_type,
            # AVTOMATİK təsdiqdə insan yoxdur. `approved_by=None` bunu TİP
            # SƏVİYYƏSİNDƏ ifadə edir — süni identifikator uydurmaq audit
            # izini yalanlaşdırardı. `DEVICE_AUTO_APPROVED` audit yazısı
            # səbəbi ayrıca izah edir.
            approved_by=None,
            now=now,
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=None,
            action="DEVICE_AUTO_APPROVED",
            entity_type="registered_device",
            entity_id=str(device.id),
            after_state={"store_id": str(store_id)},
            reason="DEVICE_APPROVAL_REQUIRED söndürülüb və kirayəçidə tək aktiv mağaza var",
        )

    # ------------------------------- admin yolu ------------------------------ #

    def approve(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        device_id: DeviceId,
        store_id: StoreId,
        device_name: str,
        device_type: DeviceType,
    ) -> RegisteredDevice:
        """Admin cihazı təsdiqləyir və filiala təyin edir."""
        self._require(actor)
        now = self._clock.now()
        device = self._require_device(device_id)

        usage = self.license_usage(tenant_id)
        if not usage.has_capacity:
            raise DeviceLimitReachedError(
                f"Aktiv cihaz sayı həddə çatıb ({usage.active}/{usage.limit})",
                context={"active": usage.active, "limit": usage.limit},
            )

        device.approve(
            store_id=store_id,
            device_name=device_name,
            device_type=device_type,
            approved_by=actor.id,
            now=now,
        )
        self._devices.save(device)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="DEVICE_APPROVED",
            entity_type="registered_device",
            entity_id=str(device.id),
            after_state={
                "store_id": str(store_id),
                "device_name": device.device_name,
                "device_type": device_type.value,
            },
        )
        return device

    def block(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        device_id: DeviceId,
        reason: str,
    ) -> RegisteredDevice:
        """Cihazı bloklayır — oğurlanmış/çıxarılmış PC üçün."""
        self._require(actor)
        device = self._require_device(device_id)
        device.block(reason=reason, blocked_by=actor.id, now=self._clock.now())
        self._devices.save(device)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="DEVICE_BLOCKED",
            entity_type="registered_device",
            entity_id=str(device.id),
            reason=reason,
        )
        return device

    def accept_fingerprint(
        self, *, tenant_id: TenantId, actor: Employee, device_id: DeviceId
    ) -> RegisteredDevice:
        """Admin gözləyən aparat izini qəbul edir — xəbərdarlığı bağlayır.

        Bloklamaq TƏK cavab deyil: uyğunsuzluğun 99%-i legitim təmirdir və o
        halda admin-in istədiyi şey cihazı ÇIXARMAQ yox, yeni izi TANIMAQdır.
        Bu yol olmasaydı admin ya xəbərdarlığı əbədi görməli, ya da işlək
        cihazı bloklamalı olardı — hər ikisi səhv cavabdır.

        Audit `before_state`/`after_state` ilə yazılır: mübahisə halında
        «hansı izdən hansına keçildi» sualının cavabı yalnız burada qalır.
        """
        self._require(actor)
        device = self._require_device(device_id)
        previous = device.accept_fingerprint(accepted_by=actor.id, now=self._clock.now())
        self._devices.save(device)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="DEVICE_FINGERPRINT_ACCEPTED",
            entity_type="registered_device",
            entity_id=str(device.id),
            before_state={"fingerprint": previous.value},
            after_state={"fingerprint": device.fingerprint.value},
            reason="Admin yeni aparat izini təsdiqlədi",
        )
        return device

    def reactivate(
        self, *, tenant_id: TenantId, actor: Employee, device_id: DeviceId
    ) -> RegisteredDevice:
        """Bloklanmış cihazı bərpa edir — limit YENİDƏN yoxlanılır.

        Yoxlama məcburidir: cihaz bloklandığı müddətdə onun yeri başqasına
        verilmiş ola bilər və bərpa limiti sükutla aşardı.
        """
        self._require(actor)
        usage = self.license_usage(tenant_id)
        if not usage.has_capacity:
            raise DeviceLimitReachedError(
                f"Aktiv cihaz sayı həddə çatıb ({usage.active}/{usage.limit})",
                context={"active": usage.active, "limit": usage.limit},
            )
        device = self._require_device(device_id)
        device.reactivate(reactivated_by=actor.id, now=self._clock.now())
        self._devices.save(device)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="DEVICE_REACTIVATED",
            entity_type="registered_device",
            entity_id=str(device.id),
        )
        return device

    def reassign_store(
        self, *, tenant_id: TenantId, actor: Employee, device_id: DeviceId, store_id: StoreId
    ) -> RegisteredDevice:
        """Cihazı başqa filiala köçürür (PC fiziki olaraq daşınıb)."""
        self._require(actor)
        device = self._require_device(device_id)
        previous = str(device.store_id) if device.store_id else None
        device.reassign_store(store_id=store_id, now=self._clock.now())
        self._devices.save(device)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="DEVICE_STORE_REASSIGNED",
            entity_type="registered_device",
            entity_id=str(device.id),
            before_state={"store_id": previous},
            after_state={"store_id": str(store_id)},
        )
        return device

    def find_by_code(self, *, tenant_id: TenantId, actor: Employee, code: str) -> RegisteredDevice:
        """Admin telefonla eşitdiyi kodla cihazı tapır."""
        self._require(actor)
        device = self._devices.find_by_short_code(tenant_id, normalize_short_code(code))
        if device is None:
            raise DeviceNotFoundError("Bu kod ilə cihaz tapılmadı", context={"short_code": code})
        return device

    # ------------------------------- oxu yolu -------------------------------- #

    def list_pending(self, *, tenant_id: TenantId, actor: Employee) -> list[RegisteredDevice]:
        self._require(actor)
        return self._devices.list_by_status(
            tenant_id, DeviceStatus.PENDING_APPROVAL.value, limit=LIST_LIMIT
        )

    def list_all(self, *, tenant_id: TenantId, actor: Employee) -> list[RegisteredDevice]:
        self._require(actor)
        return self._devices.list_all(tenant_id, limit=LIST_LIMIT)

    def license_usage(self, tenant_id: TenantId) -> DeviceLicenseUsage:
        """«12 / 25 cihaz istifadə olunur» sətri.

        İCAZƏ TƏLƏB ETMİR: sayğac `register_self()` yolundan da oxunur (aktor
        olmadan) və eyni hesabı iki yerdə yazmaq onların ayrılmasını qaçılmaz
        edərdi.
        """
        return DeviceLicenseUsage(
            active=self._devices.count_active(tenant_id),
            limit=self._limit_int(tenant_id, SystemLimitKey.MAX_REGISTERED_DEVICES),
            pending=self._devices.count_pending(tenant_id),
            counted_at=self._clock.now(),
        )

    # ---------------------------- passivlik dövrəsi --------------------------- #

    def block_inactive_devices(self, *, tenant_id: TenantId) -> list[RegisteredDevice]:
        """Passivlik həddini keçmiş cihazları bloklayır (planlaşdırılmış iş).

        AKTOR YOXDUR — bu, sistem dövrəsidir. `blocked_by=None` audit-də
        «avtomatik» kimi görünür (`DeviceBlockedEvent.automatic`).

        Məqsəd lisenziya sayğacını təmizləməkdir: illər əvvəl silinmiş
        mağazanın PC-si əbədi yer tutmamalıdır.
        """
        now = self._clock.now()
        days = self._limit_int(tenant_id, SystemLimitKey.DEVICE_INACTIVITY_DAYS)
        threshold = timedelta(days=days)
        blocked: list[RegisteredDevice] = []
        for device in self._devices.list_by_status(
            tenant_id, DeviceStatus.ACTIVE.value, limit=LIST_LIMIT
        ):
            if not device.is_inactive(now=now, threshold=threshold):
                continue
            device.block(
                reason=f"{threshold.days} gün ərzində görünmədi — avtomatik bloklandı",
                blocked_by=None,
                now=now,
            )
            self._devices.save(device)
            self._audit.record(
                tenant_id=tenant_id,
                actor_id=None,
                action="DEVICE_AUTO_BLOCKED",
                entity_type="registered_device",
                entity_id=str(device.id),
                reason=device.block_reason,
            )
            blocked.append(device)
        return blocked

    # -------------------------------- köməkçi -------------------------------- #

    def _require(self, actor: Employee) -> None:
        """Səlahiyyət yoxlaması — sükutla «heç nə etmə» DEYİL (`CLAUDE.md` §6)."""
        if not actor.has_permission(MANAGE_DEVICES_FLAG, now=self._clock.now()):
            _audit_log.warning(
                "DEVICE_PERMISSION_DENIED",
                extra={"actor_id": str(actor.id), "flag": MANAGE_DEVICES_FLAG},
            )
            raise DevicePermissionError(
                f"«{MANAGE_DEVICES_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id)},
            )

    def _require_device(self, device_id: DeviceId) -> RegisteredDevice:
        device = self._devices.get(device_id)
        if device is None:
            raise DeviceNotFoundError("Cihaz tapılmadı", context={"device_id": str(device_id)})
        return device

    def _unique_short_code(self, tenant_id: TenantId) -> str:
        """Kirayəçi daxilində işlədilməmiş kod qaytarır.

        Toqquşma praktiki olaraq mümkünsüzdür, lakin `UNIQUE (tenant_id,
        short_code)` constraint-i onu HƏQİQƏTƏN pozardı — və qüsur ilk
        açılışda, yəni ən pis anda üzə çıxardı.
        """
        for _ in range(SHORT_CODE_ATTEMPTS):
            code = generate_short_code()
            if not self._devices.short_code_exists(tenant_id, code):
                return code
        raise KompasOSError(
            "Unikal qeydiyyat kodu yaradıla bilmədi",
            user_message="Qeydiyyat kodu yaradıla bilmədi. Yenidən cəhd edin.",
        )

    def _notify_pending(self, device: RegisteredDevice, *, tenant_id: TenantId) -> None:
        if self._notifier is None or device.status is not DeviceStatus.PENDING_APPROVAL:
            return
        self._notifier.notify(
            tenant_id=tenant_id,
            # Tenant səviyyəli bildiriş — marşrutlaşdırma `can_manage_devices`
            # flag-inə görə olur (`DriveQuotaMonitor._notify` ilə eyni naxış).
            recipient_id=None,
            category="DEVICE_REGISTRATION",
            title_az="Yeni cihaz təsdiq gözləyir",
            body_az=(
                f"«{device.machine_name or 'Adsız cihaz'}» qeydiyyatdan keçdi və təsdiq "
                f"gözləyir. Qeydiyyat kodu: {device.short_code}"
            ),
            is_critical=False,
        )

    def _limit_int(self, tenant_id: TenantId, key: SystemLimitKey) -> int:
        return self._limits.get_int(tenant_id, key.value, int(DEFAULT_LIMITS[key]))


__all__ = [
    "LIST_LIMIT",
    "MANAGE_DEVICES_FLAG",
    "SHORT_CODE_ATTEMPTS",
    "DeviceLimitReachedError",
    "DeviceNotFoundError",
    "DevicePermissionError",
    "DeviceRegistrationOutcome",
    "DeviceRegistryUseCase",
]
