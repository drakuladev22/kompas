"""Kataloq value object-ləri — İş Rejimləri, Cərimə Növləri, İcazə Növləri.

Spesifikasiya bölmə 4-də üç ayrı kataloq ekranı tələb olunur:

    * **İş Rejimləri** (`can_manage_work_modes`, defolt Root/CEO) — adlandırılmış
      növbə şablonları ("08:00–17:00", "Növbəli 2/2"). Shift Matrix-də işçiyə
      təyin edilir və `assess_lateness` üçün planlaşdırılmış başlanğıcı verir.
    * **Cərimə Növləri** (`can_manage_fine_types`, defolt Root/CEO) — ad +
      standart qiymət (AZN) + aktivlik.
    * **İcazə Növləri** (`can_manage_leave_types`, defolt Root/CEO/HR_Admin) —
      ad + tövsiyə olunan müddət (dəqiqə).

──────────────────────────────────────────────────────────────────────────────
NİYƏ HAMISI BİR MODULDA
──────────────────────────────────────────────────────────────────────────────
Üçü də EYNİ struktur qaydasına tabedir: tenant-a bağlı, adı unikal, silinmə
YALNIZ "soft delete"dir. Ayrı-ayrı modullarda yazılsaydı, həmin qayda üç dəfə
təkrarlanardı və biri düzəldiləndə digər ikisi arxada qalardı. Ortaq bazis
(`CatalogEntry`) bunu struktur olaraq bağlayır.

──────────────────────────────────────────────────────────────────────────────
SOFT DELETE NİYƏ MƏCBURİDİR (KRİTİK)
──────────────────────────────────────────────────────────────────────────────
Bölmə 4: "Növ silinərkən, artıq istifadə olunmuş tarixi qeydlərə təsiri olmur
(yalnız yeni seçimdən çıxarılır)". Fiziki `DELETE` keçmiş cərimənin növünü
"naməlum"a çevirərdi — həmin cərimə isə real pul kəsintisidir və mübahisə
halında nəyə görə verildiyi SÜBUT edilə bilməlidir. Ona görə `deactivate()`
var, `delete()` yoxdur.

──────────────────────────────────────────────────────────────────────────────
CƏRİMƏ NÖVÜ NİYƏ ANTİ-FRAUD TƏDBİRİDİR
──────────────────────────────────────────────────────────────────────────────
Kamera Operatoru sərbəst məbləğ yaza bilmir — yalnız CEO-nun əvvəlcədən
təsdiqlədiyi növ və onun standart qiymətindən seçir (bölmə 4). `Fine`
entity-si də bunu tələb edir: `FineSource.MANUAL_CAMERA` üçün `fine_type_id`
məcburidir. Kataloq həmin siyahının YEGANƏ mənbəyidir.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from datetime import datetime
from typing import Final

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.identifiers import (
    FineTypeId,
    LeaveTypeId,
    TenantId,
    WorkModeId,
)
from src.domain.value_objects.money import Money
from src.domain.value_objects.scheduling import TimeRange, require_aware
from src.shared.exceptions import KompasOSError

#: Kataloq adının minimum/maksimum uzunluğu — DB `VARCHAR(120)` ilə uyğun.
#: ROOT PARAMETRİ DEYİL: sxem sərhədinin güzgüsüdür. Root onu böyütsəydi,
#: yazma anında `VARCHAR(120)` xətası verərdi — yəni "idarə olunan" görünüb
#: faktiki işləməyən parametr olardı.
MIN_NAME_LENGTH: Final[int] = 2
MAX_NAME_LENGTH: Final[int] = 120

#: İcazə növünün tövsiyə olunan müddəti üçün yuxarı hədd (defolt bir iş günü).
#: FALLBACK — HƏQİQİ MƏNBƏ `system_limits.LEAVE_TYPE_MAX_DURATION_MINUTES`
#: (seed: migrations/033). Ad uzunluqlarından FƏRQLİ olaraq bu, sxem sərhədi
#: DEYİL — `leave_types.default_duration_minutes` yalnız `> 0` CHECK-i daşıyır,
#: YUXARI hədd sxemdə YOXDUR, yəni bu tavan sırf biznes siyasətidir və
#: müəssisə onu öz iş rejiminə (məs. 24 saatlıq növbə) görə seçir.
MAX_LEAVE_DURATION_MINUTES: Final[int] = int(
    DEFAULT_LIMITS[SystemLimitKey.LEAVE_TYPE_MAX_DURATION_MINUTES]
)


def _leave_duration_ceiling(requested: int | None) -> int:
    """Tətbiq olunacaq tavan: Root dəyəri, yoxdursa modul fallback-ı.

    ────────────────────────────────────────────────────────────────────────
    NİYƏ TAVAN `system_limits`-DƏN GƏLİR, LAKİN DOMEN DB-YƏ TOXUNMUR
    ────────────────────────────────────────────────────────────────────────
    `LeaveType` domen tipidir və `psycopg` görmür (CLAUDE.md §3). Ona görə
    dəyəri ÖZÜ oxumur — PARAMETR kimi qəbul edir; oxunu çağıran tərəf
    (repository / kontroller) edir. Naxış `labor_rules.LaborLimits.defaults()`
    ilə eynidir.

    ────────────────────────────────────────────────────────────────────────
    NİYƏ MƏNASIZ TAVAN FALLBACK-A DÜŞÜR
    ────────────────────────────────────────────────────────────────────────
    ROOT ekranı `min_value = 1` ilə qoruyur, lakin ekranı yan keçən skript
    `0` və ya mənfi yaza bilər. O halda HƏR icazə növü (45 dəq nahar da daxil)
    rədd edilər və kataloq ekranı bütövlükdə açılmaz olardı — yəni bir yanlış
    sətir bütün modulu bağlayardı. Fail-safe seçim: yararsız tavan görməzdən
    gəlinir (`PostgresSystemLimits.get_int` ilə eyni fəlsəfə).
    """
    if requested is None or requested <= 0:
        return MAX_LEAVE_DURATION_MINUTES
    return requested


class InvalidCatalogEntryError(KompasOSError):
    """Kataloq sətri yararsızdır."""

    user_message = "Kataloq məlumatı düzgün deyil."


class CatalogEntryInUseError(KompasOSError):
    """Deaktiv edilmiş növ yeni qeyddə istifadə edilməyə çalışıldı."""

    user_message = "Bu növ artıq istifadədə deyil. Aktiv bir növ seçin."


def _clean_name(raw: str, *, label: str) -> str:
    """Adı normallaşdırır və uzunluğunu yoxlayır."""
    cleaned = " ".join(raw.split())
    if len(cleaned) < MIN_NAME_LENGTH:
        raise InvalidCatalogEntryError(
            f"{label} minimum {MIN_NAME_LENGTH} simvol olmalıdır",
            user_message=f"{label} çox qısadır.",
        )
    if len(cleaned) > MAX_NAME_LENGTH:
        raise InvalidCatalogEntryError(
            f"{label} maksimum {MAX_NAME_LENGTH} simvol ola bilər",
            user_message=f"{label} çox uzundur.",
        )
    return cleaned


@dataclass(frozen=True)
class CatalogEntry:
    """Üç kataloqun ortaq bazisi.

    `frozen=True`: kataloq sətri dəyişdirilmir, YENİSİ yaradılır
    (`renamed()`, `deactivated()`). Beləliklə köhnə obyektə istinad saxlayan
    ekran səssizcə dəyişmir — nə göstərdiyini bilir.
    """

    name: str
    tenant_id: TenantId
    is_active: bool = True
    #: Deaktiv edilmə anı — audit üçün; aktiv sətirdə `None`.
    deactivated_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _clean_name(self.name, label="Ad"))
        if self.deactivated_at is not None:
            require_aware(self.deactivated_at, field="deactivated_at")
        if self.is_active and self.deactivated_at is not None:
            raise InvalidCatalogEntryError(
                "Aktiv sətrin deaktivləşdirmə tarixi ola bilməz — ziddiyyətli vəziyyət saxlanmır"
            )
        if not self.is_active and self.deactivated_at is None:
            raise InvalidCatalogEntryError(
                "Deaktiv sətir üçün deaktivləşdirmə anı MƏCBURİDİR — "
                "«nə vaxt çıxarıldı?» sualı auditdə cavablanmalıdır"
            )

    @property
    def selectable(self) -> bool:
        """YENİ qeyddə seçilə bilərmi.

        Keçmiş qeydlərdə göstərilməsi bundan asılı DEYİL — orada sətir
        həmişə oxunur (soft delete izahına bax).
        """
        return self.is_active


@dataclass(frozen=True)
class WorkMode(CatalogEntry):
    """İş Rejimi şablonu — "08:00–17:00", "Növbəli 2/2" (bölmə 4).

    `schedule` `None` ola bilər: "Növbəli 2/2" kimi rejimlərdə sabit saat
    yoxdur, növbə matrisi günləri özü təyin edir. Həmin halda gecikmə
    hesablanmır (`assess_lateness` `scheduled_start=None` ilə çağırılır) —
    bu, QƏSDƏN belədir, çünki plansız günə gecikmə anlayışı tətbiq olunmur.
    """

    work_mode_id: WorkModeId | None = None
    schedule: TimeRange | None = None

    def scheduled_start_label(self) -> str:
        """Siyahıda göstərilən saat aralığı."""
        return self.schedule.format_az() if self.schedule is not None else "Sərbəst növbə"


@dataclass(frozen=True)
class FineType(CatalogEntry):
    """Cərimə Növü — ad + standart qiymət (bölmə 4, anti-fraud).

    `standard_amount` MƏCBURİDİR və mənfi ola bilməz: operator məbləği
    seçmir, kataloqdan GƏLƏN dəyər tətbiq olunur.
    """

    fine_type_id: FineTypeId | None = None
    standard_amount: Money = field(default_factory=Money.zero)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.standard_amount.require_non_negative(field="standart cərimə məbləği")

    def amount_for_new_fine(self) -> Money:
        """Yeni cərimə üçün tətbiq olunacaq məbləğ.

        Deaktiv növ üçün istisna atır — deaktivləşdirmə yalnız siyahıdan
        çıxarmaq DEYİL, yeni qeydi bloklamaqdır. Əks halda köhnə ekran
        keşindən seçim edən operator qaydanı yan keçə bilərdi.
        """
        if not self.selectable:
            raise CatalogEntryInUseError(
                f"Deaktiv cərimə növü ilə yeni cərimə yaradıla bilməz: {self.name}",
                context={"fine_type": self.name},
            )
        return self.standard_amount


@dataclass(frozen=True)
class LeaveType(CatalogEntry):
    """İcazə Növü — "Nahar Fasiləsi", "Siqaret Fasiləsi" (bölmə 4).

    KRİTİK: `default_duration_minutes` yalnız **güzəşt mənbəyidir** (BR-001),
    cərimə düsturunu DƏYİŞMİR. Bölmə 4: seçim "yalnız kateqoriyalaşdırma /
    hesabat məqsədi daşıyır və STEP 1-in NTP-yə qarşı yoxlanılmış vaxt-möhürünə
    əsaslanan `Requested_Time`/`Delay`/`Total` hesablama düsturunu DƏYİŞMİR".
    """

    leave_type_id: LeaveTypeId | None = None
    default_duration_minutes: int = 0
    #: ROOT tavanı (`system_limits.LEAVE_TYPE_MAX_DURATION_MINUTES`).
    #:
    #: `InitVar`-dır, SAHƏ DEYİL: tavan icazə növünün XÜSUSİYYƏTİ deyil,
    #: yoxlama parametridir. Sahə olsaydı `==` müqayisəsinə, audit
    #: `after_state`-inə və hər serializasiyaya düşərdi — yəni eyni kataloq
    #: sətri Root tavanı dəyişdikdən sonra "fərqli" görünərdi.
    #:
    #: `None` = tavan verilməyib → modul fallback-ı işləyir. Bütün mövcud
    #: çağırış nöqtələri üçün davranış DƏYİŞMİR.
    max_duration_minutes: InitVar[int | None] = None

    # `max_duration_minutes` DEFOLTSUZDUR (RUF033): defolt `InitVar` sahəsinin
    # ÖZÜNDƏDİR (`= None`) və onu burada təkrarlamaq iki mənbə yaradardı.
    def __post_init__(self, max_duration_minutes: int | None) -> None:
        super().__post_init__()
        ceiling = _leave_duration_ceiling(max_duration_minutes)
        if self.default_duration_minutes < 0:
            raise InvalidCatalogEntryError(
                "Tövsiyə olunan müddət mənfi ola bilməz",
                user_message="Müddət mənfi ola bilməz.",
            )
        if self.default_duration_minutes > ceiling:
            raise InvalidCatalogEntryError(
                f"Tövsiyə olunan müddət {ceiling} dəqiqəni aşa bilməz",
                user_message="Müddət həddindən artıq uzundur.",
            )

    def duration_label(self) -> str:
        """İstifadəçiyə göstərilən müddət: `45 dəq` / `1 saat 30 dəq`."""
        if self.default_duration_minutes == 0:
            return "Müddət təyin olunmayıb"
        hours, minutes = divmod(self.default_duration_minutes, 60)
        if hours and minutes:
            return f"{hours} saat {minutes} dəq"
        if hours:
            return f"{hours} saat"
        return f"{minutes} dəq"


def active_only(entries: list[CatalogEntry]) -> list[CatalogEntry]:
    """Seçim siyahıları üçün süzgəc — deaktiv sətirlər YENİ qeyddə görünmür."""
    return [entry for entry in entries if entry.selectable]


__all__ = [
    "MAX_LEAVE_DURATION_MINUTES",
    "MAX_NAME_LENGTH",
    "MIN_NAME_LENGTH",
    "CatalogEntry",
    "CatalogEntryInUseError",
    "FineType",
    "InvalidCatalogEntryError",
    "LeaveType",
    "WorkMode",
    "active_only",
]
