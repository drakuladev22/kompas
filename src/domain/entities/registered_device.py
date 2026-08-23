"""Qeydiyyatdan keçmiş cihaz aqreqatı (DEVICE-1).

──────────────────────────────────────────────────────────────────────────────
TƏSDİQ AXINI VƏZİYYƏT MAŞINIDIR — VƏ MƏHZ ONA GÖRƏ ENTITY-DƏDİR
──────────────────────────────────────────────────────────────────────────────
    PENDING_APPROVAL ──approve()──► ACTIVE ──block()──► BLOCKED
       │  ▲                            ▲                   │  │
       │  └──── reactivate() (filialsız cihaz) ─────────────┘  │
       │                               └── reactivate() ───────┘
       └──block()──────────────────────────────────────────► BLOCKED

`reactivate()` İKİ hədəfə gedir və hədəfi `store_id` seçir: filialı olan cihaz
`ACTIVE`-ə, heç vaxt təsdiqlənməmiş (filialsız) cihaz isə `PENDING_APPROVAL`-a
qayıdır. İkinci qol olmadan `PENDING_APPROVAL`-da bloklanmış cihaz əbədi
kiliddə qalırdı — bax `reactivate()` şərhi.

Keçidlərin hamısı BURADA, use case-də deyil. Səbəb: eyni cihaz iki yerdən
dəyişdirilir — admin ekranı (`approve`, `block`) və cihazın özü (`touch`,
avtomatik passivləşmə). Qaydalar use case-də olsaydı, ikinci yol onları yan
keçərdi və passivlik həddi yalnız ekrandan gedəndə işlərdi.

──────────────────────────────────────────────────────────────────────────────
TƏSDİQ = FİLİAL TƏYİNATI. İKİSİ AYRILA BİLMƏZ
──────────────────────────────────────────────────────────────────────────────
`approve()` `store_id` TƏLƏB EDİR. «Əvvəl təsdiqlə, filialı sonra ver» axını
qəsdən yoxdur: filialsız aktiv cihaz bütün DEVICE-1-in həll etdiyi problemi
(cərimə/tabel səhv filiala yazılır) geri gətirərdi — üstəlik bu dəfə cihaz
«təsdiqlənmiş» görünərdi, yəni qüsur daha da gizli olardı.

──────────────────────────────────────────────────────────────────────────────
FINGERPRINT UYĞUNSUZLUĞU BLOKLAMIR
──────────────────────────────────────────────────────────────────────────────
Disk dəyişdirmək legitim təmirdir. Bloklasaydıq, mağaza səhər açılanda
işləməzdi və problemi həll etməyin yeganə yolu adminə zəng olardı — halbuki
uyğunsuzluğun səbəbi 99% halda təmirdir. Ona görə hadisə QEYDƏ ALINIR
(`DeviceFingerprintChangedEvent` → audit + admin ekranı), qərarı isə adam
verir. Bax `value_objects/devices.py` başlığı.

«Qərarı adam verir» cümləsinin İKİ tələbi var və ikisi də burada təmin
olunur: adam qəbul edəcəyi dəyəri GÖRMƏLİDİR (`pending_fingerprint`) və
qərarı BİR YERƏ düşməlidir (`accept_fingerprint()`). İkincisi olmasaydı
xəbərdarlıq legitim təmirdən sonra da əbədi qalardı — və əbədi xəbərdarlıq
oxunmayan xəbərdarlıqdır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.domain.entities.base import AggregateRoot, DomainRuleError, InvalidStateTransitionError
from src.domain.events import (
    DeviceApprovedEvent,
    DeviceBlockedEvent,
    DeviceFingerprintAcceptedEvent,
    DeviceFingerprintChangedEvent,
    DeviceRegisteredEvent,
)
from src.domain.value_objects.devices import DeviceFingerprint, DeviceStatus, DeviceType
from src.domain.value_objects.scheduling import require_aware

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from src.domain.value_objects.identifiers import DeviceId, EmployeeId, StoreId, TenantId


class DeviceNotApprovedError(DomainRuleError):
    """Təsdiqlənməmiş/bloklanmış cihazdan əməliyyat cəhdi."""

    user_message = "Bu cihaz təsdiqlənməyib. Administratorunuzla əlaqə saxlayın."


@dataclass(eq=False)
class RegisteredDevice(AggregateRoot):
    """Bir PC-nin qeydiyyat sətri.

    `eq=False`: aqreqat kimliyi `id`-dədir, sahələrin bərabərliyində yox —
    eyni cihazın iki fərqli oxunuşu (biri `last_seen_at` yenilənmiş) EYNİ
    cihazdır. `dataclass`-ın strukturca müqayisəsi onları FƏRQLİ göstərərdi.
    """

    id: DeviceId
    tenant_id: TenantId
    fingerprint: DeviceFingerprint
    short_code: str
    machine_name: str
    device_type: DeviceType
    registered_at: datetime
    status: DeviceStatus = DeviceStatus.PENDING_APPROVAL
    #: Təsdiqdən ƏVVƏL `None` — filialsız cihaz mövcud ola bilər, LAKİN
    #: yalnız `PENDING_APPROVAL` vəziyyətində (bax `__post_init__`).
    store_id: StoreId | None = None
    device_name: str = ""
    approved_by: EmployeeId | None = None
    approved_at: datetime | None = None
    last_seen_at: datetime | None = None
    block_reason: str = ""
    #: MÜŞAHİDƏ olunan, lakin hələ QƏBUL EDİLMƏMİŞ aparat izi.
    #:
    #: Ayrıca sahədir, çünki `fingerprint`-i dərhal üstündən yazmaq detektoru
    #: ləğv edərdi: `device.json`-u başqa maşına köçürən adam bir audit
    #: sətrindən sonra «qanuni» olardı. Burada dəyər GÖZLƏYİR — admin onu
    #: görür və `accept_fingerprint()` ilə qərarını verir.
    pending_fingerprint: DeviceFingerprint | None = None
    #: Repository-dən BƏRPA edilən aqreqat hadisə YAYMAMALIDIR (`CLAUDE.md` §3).
    emit_created_event: bool = True

    def __post_init__(self) -> None:
        AggregateRoot.__init__(self)
        require_aware(self.registered_at, field="registered_at")
        if not self.short_code:
            raise ValueError("Qısa kod boş ola bilməz — təsdiq axını ona bağlıdır")
        # İNVARİANT: aktiv cihazın filialı MÜTLƏQ var. Bu, `approve()`-un
        # şərtini TƏKRARLAYIR və təkrar qəsdəndir: aqreqat repository-dən də
        # qurulur və orada `approve()` çağırılmır — yəni yeganə qapı bu olardı.
        if self.status is DeviceStatus.ACTIVE and self.store_id is None:
            raise DomainRuleError("Aktiv cihaz filialsız ola bilməz")
        if self.emit_created_event:
            self.record_event(
                DeviceRegisteredEvent(
                    device_id=str(self.id),
                    tenant_id=self.tenant_id,
                    machine_name=self.machine_name,
                    device_type=self.device_type.value,
                    short_code=self.short_code,
                )
            )

    # ------------------------------- vəziyyət -------------------------------- #

    @property
    def is_operational(self) -> bool:
        """Cihaz işləyə bilərmi — tətbiqin açılış qapısı budur."""
        return self.status.allows_operation

    def require_operational(self) -> None:
        """İşləyə bilmirsə AÇIQ istisna atır.

        Sükutla «heç nə etmə» DEYİL (`CLAUDE.md` §6): istifadəçi proqramı
        açıb və nəticə gözləyir — səbəbi ona demək lazımdır.
        """
        if not self.is_operational:
            raise DeviceNotApprovedError(
                f"Cihaz vəziyyəti: {self.status.value}. Qeydiyyat kodu: {self.short_code}"
            )

    def counts_toward_license(self) -> bool:
        """Lisenziya sayğacına düşürmü.

        Yalnız `ACTIVE`. `PENDING_APPROVAL` sayılsaydı, istənilən adam
        təsdiqlənməmiş cihaz qeydiyyatları yaradaraq müştərinin lisenziya
        limitini tükəndirə bilərdi — yəni sayğac hücum səthinə çevrilərdi.
        `BLOCKED` də sayılmır: bloklamağın MƏQSƏDİ yeri boşaltmaqdır.
        """
        return self.status is DeviceStatus.ACTIVE

    # ------------------------------- keçidlər -------------------------------- #

    def approve(
        self,
        *,
        store_id: StoreId,
        device_name: str,
        device_type: DeviceType,
        approved_by: EmployeeId | None,
        now: datetime,
    ) -> None:
        """Cihazı təsdiqləyir və filiala təyin edir.

        Args:
            approved_by: təsdiqi verən admin; `None` = AVTOMATİK təsdiq
                (`DEVICE_APPROVAL_REQUIRED = 0` və kirayəçidə tək mağaza).
                Süni identifikator uydurmaq audit izini yalanlaşdırardı —
                «heç kim, sistem» cavabı `None` ilə ifadə olunur.
        """
        require_aware(now, field="now")
        if self.status is not DeviceStatus.PENDING_APPROVAL:
            raise InvalidStateTransitionError(
                f"Yalnız təsdiq gözləyən cihaz təsdiqlənə bilər (cari: {self.status.value})"
            )
        if not device_name.strip():
            raise DomainRuleError(
                "Cihaz adı boş ola bilməz — admin siyahıda cihazları adla ayırd edir"
            )
        self.store_id = store_id
        self.device_name = device_name.strip()
        self.device_type = device_type
        self.status = DeviceStatus.ACTIVE
        self.approved_by = approved_by
        self.approved_at = now
        self.last_seen_at = now
        self.record_event(
            DeviceApprovedEvent(
                device_id=str(self.id),
                tenant_id=self.tenant_id,
                store_id=str(store_id),
                device_type=device_type.value,
                approved_by=str(approved_by) if approved_by else None,
            )
        )

    def block(self, *, reason: str, blocked_by: EmployeeId | None, now: datetime) -> None:
        """Cihazı bloklayır — admin qərarı və ya avtomatik passivləşmə.

        `blocked_by=None` AVTOMATİK passivləşmə deməkdir (passivlik həddi).
        Ayrı metod yazılmadı: nəticə eynidir və iki metod «hansı biri audit
        yazır?» sualını yaradardı. Fərq `reason` mətnindədir və audit onu
        olduğu kimi saxlayır.
        """
        require_aware(now, field="now")
        if self.status is DeviceStatus.BLOCKED:
            # İdempotent: artıq bloklanmış cihazı yenidən bloklamaq XƏTA DEYİL.
            # Avtomatik passivləşmə hər dövrədə işləyir və eyni cihazı təkrar
            # görəcək — istisna atsaydı, dövrə həmin sətirdə dayanardı.
            return
        self.status = DeviceStatus.BLOCKED
        self.block_reason = reason
        self.record_event(
            DeviceBlockedEvent(
                device_id=str(self.id),
                tenant_id=self.tenant_id,
                reason=reason,
                blocked_by=str(blocked_by) if blocked_by else None,
                automatic=blocked_by is None,
            )
        )

    def reactivate(self, *, reactivated_by: EmployeeId, now: datetime) -> DeviceStatus:
        """Bloklanmış cihazı yenidən işə salır.

        Filial TƏLƏB OLUNMUR, çünki bloklama onu SİLMİR — cihaz hansı filiala
        aid olduğunu «xatırlayır». Filialsız bloklanmış cihaz isə heç vaxt
        təsdiqlənməmiş deməkdir və o, `PENDING_APPROVAL`-a qayıtmalıdır.

        ──────────────────────────────────────────────────────────────────────
        FİLİALSIZ HAL NİYƏ İSTİSNA DEYİL — ƏBƏDİ KİLİDİN QAPADILMASI
        ──────────────────────────────────────────────────────────────────────
        Əvvəl bu hal `DomainRuleError` atırdı («əvvəlcə təsdiqdən keçməlidir»),
        halbuki `approve()` YALNIZ `PENDING_APPROVAL`-dan işləyir — yəni
        göstərilən yol MÖVCUD DEYİLDİ. Nəticədə təsdiq gözləyən cihaz
        bloklandıqda (`block()` `PENDING_APPROVAL`-ı da qəbul edir) HEÇ BİR
        keçidlə geri qaytarıla bilmirdi: nə `approve()`, nə `reactivate()`.
        Yeganə çıxış bazaya əl ilə müdaxilə olardı — auditsiz.

        Yuxarıdakı cümlə DÜZGÜN davranışı ARTIQ yazırdı; burada icra olunur.
        Aktiv etmək İSTİSNA EDİLİR: filialsız aktiv cihaz `__post_init__`
        invariantını (və DB `CHECK (status <> 'ACTIVE' OR store_id IS NOT
        NULL)`) pozardı və DEVICE-1-in həll etdiyi problemi geri gətirərdi.

        Returns:
            Cihazın YENİ vəziyyəti — çağıran tərəf lisenziya sayğacını və
            audit sətrini ona görə qurur (`PENDING_APPROVAL` yer tutmur).
        """
        require_aware(now, field="now")
        if self.status is not DeviceStatus.BLOCKED:
            raise InvalidStateTransitionError(
                f"Yalnız bloklanmış cihaz bərpa edilə bilər (cari: {self.status.value})"
            )
        self.block_reason = ""
        self.last_seen_at = now
        if self.store_id is None:
            # Heç vaxt təsdiqlənməmiş cihaz — təsdiq növbəsinə QAYIDIR.
            # `approved_by` TOXUNULMUR: onu doldurmaq «kimsə bu cihazı
            # təsdiqləyib» yalanını yazardı, halbuki təsdiq hələ verilməyib.
            self.status = DeviceStatus.PENDING_APPROVAL
            return self.status
        self.status = DeviceStatus.ACTIVE
        self.approved_by = reactivated_by
        return self.status

    def reassign_store(self, *, store_id: StoreId, now: datetime) -> None:
        """Cihazı başqa filiala köçürür (PC fiziki olaraq daşınıb).

        Vəziyyət DƏYİŞMİR: köçürmə təsdiqi ləğv etmir. Yenidən təsdiq
        tələb etsəydik, hər daşınmada mağaza bir müddət işləməz qalardı.
        """
        require_aware(now, field="now")
        if self.status is DeviceStatus.PENDING_APPROVAL:
            raise InvalidStateTransitionError(
                "Təsdiqlənməmiş cihazın filialı dəyişdirilə bilməz — `approve()` işlədin"
            )
        self.store_id = store_id

    # ------------------------------ canlılıq --------------------------------- #

    def touch(self, *, now: datetime) -> None:
        """Cihaz özünü göstərdi — `last_seen_at` yenilənir.

        Vəziyyətə TOXUNMUR: bloklanmış cihazın da özünü göstərməsi faktdır və
        admin «bu cihaz hələ də işə salınmağa çalışır» məlumatını görməlidir.
        """
        require_aware(now, field="now")
        self.last_seen_at = now

    def is_inactive(self, *, now: datetime, threshold: timedelta) -> bool:
        """Passivlik həddini keçibmi.

        Heç vaxt görünməyibsə (`last_seen_at is None`) QEYDİYYAT anından
        ölçülür: əks halda təsdiqlənib heç açılmayan cihaz əbədi «təzə»
        qalar və lisenziya yerini tutardı.
        """
        require_aware(now, field="now")
        reference = self.last_seen_at or self.registered_at
        return now - reference > threshold

    # ---------------------------- aparat kimliyi ------------------------------ #

    def verify_fingerprint(self, observed: DeviceFingerprint) -> bool:
        """Aparat izini müqayisə edir; fərq varsa hadisə yazır, BLOKLAMIR.

        Hadisə YALNIZ İZ DƏYİŞƏNDƏ yazılır, hər müqayisədə yox. Fərq
        vacibdir: cihaz hər açılışda qeydiyyatdan keçir, yəni eyni
        uyğunsuzluq gündə onlarla dəfə görünə bilər. Hər dəfə yazsaydıq audit
        eyni sətrin nüsxələri ilə dolar və HƏQİQİ hadisə — məsələn ikinci,
        FƏRQLİ bir dəyişiklik — həmin yığının içində itərdi.

        Returns:
            `True` — uyğundur; `False` — dəyişib (çağıran tərəf qərar vermir,
            hadisə onsuz da yazılıb).
        """
        if observed == self.fingerprint:
            # Aparat geri qaytarılıb (disk yerinə qoyulub) — gözləyən dəyər
            # artıq mövcud deyil və admin-in onu qəbul etməsi mənasızdır.
            self.pending_fingerprint = None
            return True
        if self.pending_fingerprint == observed:
            return False
        self.pending_fingerprint = observed
        self.record_event(
            DeviceFingerprintChangedEvent(
                device_id=str(self.id),
                tenant_id=self.tenant_id,
                previous_fingerprint=self.fingerprint.value,
                observed_fingerprint=observed.value,
            )
        )
        return False

    def accept_fingerprint(self, *, accepted_by: EmployeeId, now: datetime) -> DeviceFingerprint:
        """Gözləyən izi qəbul edir və onu saxlanmış iz edir.

        Bu, uyğunsuzluq axınının YEGANƏ bağlanma yoludur. Onsuz xəbərdarlıq
        əbədi qalırdı: `verify_fingerprint` saxlanmış izi qəsdən dəyişmir,
        `approve()` isə yalnız `PENDING_APPROVAL`-dan işləyir — yəni legitim
        təmirdən sonra admin-in qərarı heç yerə düşmürdü.

        Raises:
            DomainRuleError: gözləyən dəyər yoxdur — «qəbul edildi» audit
                yazısı heç nə dəyişmədən yaranardı.
        """
        require_aware(now, field="now")
        if self.pending_fingerprint is None:
            raise DomainRuleError("Qəbul ediləcək yeni aparat izi yoxdur")
        previous = self.fingerprint
        self.fingerprint = self.pending_fingerprint
        self.pending_fingerprint = None
        self.record_event(
            DeviceFingerprintAcceptedEvent(
                device_id=str(self.id),
                tenant_id=self.tenant_id,
                previous_fingerprint=previous.value,
                accepted_fingerprint=self.fingerprint.value,
                accepted_by=str(accepted_by),
            )
        )
        return previous


@dataclass(frozen=True)
class DeviceLicenseUsage:
    """Lisenziya sayğacının anlıq vəziyyəti — ekranda «12 / 25» kimi görünür."""

    active: int
    limit: int
    pending: int = 0
    #: Hesablama anı — ekran «nə vaxtkı vəziyyət» sualına cavab verə bilsin.
    counted_at: datetime | None = field(default=None)

    @property
    def has_capacity(self) -> bool:
        return self.active < self.limit

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.active)

    def describe(self) -> str:
        """«12 / 25 cihaz istifadə olunur» (bölmə 9: yeganə interfeys dili)."""
        return f"{self.active} / {self.limit} cihaz istifadə olunur"


__all__ = [
    "DeviceLicenseUsage",
    "DeviceNotApprovedError",
    "RegisteredDevice",
]
