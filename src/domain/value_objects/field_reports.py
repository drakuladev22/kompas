"""Sahə hesabatının kataloq görünüşləri və statusu (#26+#27) — kompas1.md Faza 3.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ŞABLON VƏ KATEQORİYA `Enum` DEYİL, KATALOQ SƏTRİDİR
──────────────────────────────────────────────────────────────────────────────
`migrations/037` `field_report_types`/`field_report_categories` cədvəllərini
QƏSDƏN sərt `CHECK`/`ENUM` olmadan qurub: yeni şablon (məs. "Təchizat
yoxlaması") bir `INSERT` olmalıdır, buraxılış yox. Kod tərəfi eyni qərarı
verməlidir — əks halda DB açıq, kod isə qapalı qalar və kataloqa yazılan sətir
tətbiqdə "naməlum şablon" kimi rədd edilərdi.

Ona görə burada `Enum` YALNIZ `status` üçün var: status İŞ AXINININ ÖZÜDÜR
(hər dəyər ekran/keçid tələb edir), şablon və kateqoriya isə MƏLUMATDIR.
Eyni ayrım `exception_signals.py`-da da var (`ExceptionStatus` enum,
`ExceptionSource` dataclass) — bu, ardıcıl naxışdır, təsadüf deyil.

──────────────────────────────────────────────────────────────────────────────
`ChecklistAnswer.passed` NİYƏ `bool | None`
──────────────────────────────────────────────────────────────────────────────
`field_report_checklist_items.passed` üç vəziyyətlidir (keçdi / keçmədi /
yoxlanılmadı) və miqrasiya başlığı üç-dəyərli MƏTNİ açıq şəkildə rədd edib.
Domen həmin qərarı GÜZGÜLƏYİR: `None` "hələ cavab yoxdur" deməkdir və
`is_blocking_failure` yalnız `passed is False` halında doğrudur — cavabsız
bənd UĞURSUZ SAYILMIR. `passed == False` yazılsaydı, `None == False`
Python-da `False` verərdi, lakin `not passed` yazan növbəti adam cavabsız
bəndi uğursuz sayardı; ona görə yoxlama HƏMİŞƏ `is False`-dır (037-dəki
qismən indeksin predikatı ilə eyni operator).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.value_objects.identifiers import StoreId

#: `field_report_types.code`/`field_report_categories.code` CHECK-inin güzgüsü
#: (migrations/037: `char_length(trim(code)) >= 3`). Sxem sərhədidir — dəyişmək
#: miqrasiya tələb edir.
MIN_CATALOG_CODE_LENGTH: Final = 3

#: `field_report_categories.route_to_role` CHECK-inin güzgüsü (>= 2 simvol).
MIN_ROUTE_ROLE_LENGTH: Final = 2


class FieldReportStatus(str, Enum):
    """`field_reports.status` — iş axınının ÖZÜ (037: siyahı SƏRTDİR).

    `StrEnum` YOX, açıq `.value` (CLAUDE.md §4) — layihənin bütün statusları
    ilə eyni qərar; `str(X)` nəticəsinin dəyişməsi audit/log çıxışına təsir
    edərdi.

    `DELETED` yoxdur və olmayacaq: rədd edilmiş (`DISMISSED`) hesabat da
    "buna baxıldı və əsassız sayıldı" faktının sübutudur — `migrations/037`
    məhz bu səbəblə `REVOKE DELETE` edir.
    """

    SUBMITTED = "SUBMITTED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"

    @property
    def is_open(self) -> bool:
        """Hesabat hələ bağlanmayıbmı (`idx_field_reports_open` predikatı)."""
        return self in (FieldReportStatus.SUBMITTED, FieldReportStatus.IN_PROGRESS)

    @property
    def is_terminal(self) -> bool:
        return not self.is_open

    @property
    def label_az(self) -> str:
        return _STATUS_LABELS[self]


_STATUS_LABELS: Final[dict[FieldReportStatus, str]] = {
    FieldReportStatus.SUBMITTED: "Təqdim edildi",
    FieldReportStatus.IN_PROGRESS: "İcradadır",
    FieldReportStatus.RESOLVED: "Həll edildi",
    FieldReportStatus.DISMISSED: "Əsassız sayıldı",
}


@dataclass(frozen=True)
class FieldReportTemplate:
    """`field_report_types` kataloq sətrinin domen görünüşü.

    Ad və izah BAZADAN gəlir, koddan yox — ekran ikinci ad məkanı qurmasın
    deyə (`menu.py` başlığındakı qüsur növü; migrations/037 `name_az` şərhi
    eyni səbəbi yazır).

    `requires_checklist` DAVRANIŞI TAM ƏVƏZ EDİR: `if type == "STORE_AUDIT"`
    zənciri məhz bu sahə sayəsində LAZIM DEYİL. Üçüncü şablon checklist tələb
    edirsə, kataloqda `requires_checklist = TRUE` yazılır və kod dəyişmir.
    """

    code: str
    name_az: str
    description_az: str | None = None
    requires_checklist: bool = False
    is_active: bool = True


@dataclass(frozen=True)
class FieldReportCategory:
    """`field_report_categories` kataloq sətrinin domen görünüşü.

    `route_to_role` — #27-nin MARŞRUTLAMA qaydası. O, KATALOQDADIR, kodda
    `dict` kimi DEYİL: marşrutun dəyişməsi (məs. şikayətlərin HR yerinə
    Admin-ə getməsi) buraxılış tələb etməməlidir. `None` = marşrutlama
    yoxdur — audit kateqoriyaları belədir, çünki onların nəticəsi rola deyil,
    Tapşırıq Mühərrikinə gedir (migrations/037 sütun şərhi).

    `report_type` sahəsi saxlanılır, çünki birləşmiş FK `(type, category)`
    cütü üzərindədir: kateqoriyanın hansı şablona aid olduğu bilinmədən
    "insident kateqoriyası audit hesabatına yazılmasın" qaydası tətbiq qatında
    yoxlanıla bilməzdi (DB onsuz da bloklayır — bu, ekrandan ƏVVƏL aydın
    mesaj verməyin yoludur, əvəzi deyil).
    """

    code: str
    report_type: str
    name_az: str
    description_az: str | None = None
    route_to_role: str | None = None
    is_active: bool = True

    @property
    def is_routed(self) -> bool:
        """Kateqoriya konkret rola marşrutlanırmı."""
        return bool(self.route_to_role)


@dataclass(frozen=True)
class ChecklistItemDraft:
    """Formanın topladığı BİR checklist bəndi — hələ sətir DEYİL.

    `position_no` BURADA YOXDUR: sıra draft siyahısının ÖZ ardıcıllığından
    çıxır (`enumerate`, 1-dən). Onu forma sahəsi kimi qəbul etsəydik, iki
    bənd eyni sıra nömrəsi ala bilər və `UNIQUE (report_id, position_no)`
    DB səviyyəsində çökərdi — ekran isə səbəbi izah edə bilməzdi.
    """

    item_text: str
    is_blocking: bool = False
    photo_required: bool = False
    #: Üç vəziyyət — `None` = hələ yoxlanılmadı (bax modul başlığı).
    passed: bool | None = None
    photo_ref: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class StoreAuditGap:
    """Bir filialın SONUNCU auditindən keçən vaxt — xatırlatma işinin sətri.

    `last_audit_at is None` = filial HEÇ VAXT auditə çəkilməyib. Bu hal
    "çoxdan çəkilməyib" ilə QARIŞDIRILMIR: yeni açılmış mağazanın heç bir
    auditi olmaması gözləniləndir, illərdir işləyən mağazanınkı isə ciddi
    boşluqdur — ekran/bildiriş mətni ikisini fərqli göstərə bilməlidir.
    Ona görə `days_since` sıfır YOX, `None` qaytarır.

    ADI FİLİALLA GƏLİR (ID ilə yanaşı), çünki bildiriş mətni insan üçündür:
    "3f2a-…" UUID-si oxuyana heç nə demir və ikinci sorğu ilə ad almaq
    gecəlik iş üçün N+1 sorğu deməkdir.
    """

    store_id: StoreId
    store_name: str
    last_audit_at: datetime | None = None
    days_since: int | None = None


__all__ = [
    "MIN_CATALOG_CODE_LENGTH",
    "MIN_ROUTE_ROLE_LENGTH",
    "ChecklistItemDraft",
    "FieldReportCategory",
    "FieldReportStatus",
    "FieldReportTemplate",
    "StoreAuditGap",
]
