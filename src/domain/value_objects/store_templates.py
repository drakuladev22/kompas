"""Mağaza Şablonu (#29, kompas1.md Faza 5) — `store_templates` sətri.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI FAYL, `catalogs.py`-A ƏLAVƏ EDİLMİR
──────────────────────────────────────────────────────────────────────────────
`catalogs.py` başlığı özü deyir: "Üçü də EYNİ struktur qaydasına tabedir" —
İş Rejimi, Cərimə Növü, İcazə Növü ÜÇÜNÜN də sahə dəsti demək olar eynidir
(ad + bir-iki xüsusi sahə). `StoreTemplate` isə JSONB `config_snapshot` və
mənbə mağaza istinadı daşıyır — dördüncü, TOPİK CƏHƏTDƏN kənar üzv əlavə
etmək o faylın "niyə hamısı bir modulda" əsaslandırmasını pozardı. Bunun
əvəzinə `CatalogEntry` bazası BURADA İDXAL EDİLİR — ad unikallığı və soft
delete qaydası TƏKRARLANMIR, yalnız YENİDƏN İSTİFADƏ olunur.

──────────────────────────────────────────────────────────────────────────────
`config_snapshot` NƏYİ EHTİVA EDİR, NƏYİ ETMİR
──────────────────────────────────────────────────────────────────────────────
Bu dəyər sırf DAŞIYICIDIR — MƏZMUNUNU bu fayl deyil, `StoreTemplateUseCase`
(tətbiq qatı) müəyyən edir (bax modul başlığı, `application/use_cases/
bulk_operations.py`). Domen qatında YEGANƏ qayda budur: boş obyekt QADAĞANDIR
(`migrations/037`-dəki `CHECK (config_snapshot <> '{}'::jsonb)` güzgüsü) —
parametrsiz şablon sükutla mənasızdır və istifadəçini "niyə heç nə köçmədi?"
sualı ilə tək qoyardı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `AggregateRoot` DEYİL
──────────────────────────────────────────────────────────────────────────────
Şablon heç bir domen hadisəsi doğurmur — nə digər aqreqatlar ona abunə olur,
nə də Saga onu gözləyir (`FieldReport`/`AnnualLeaveRequest`-dən FƏRQLİ olaraq).
Yaradılma/söndürülmə AUDİT-lə (tətbiq qatı) kifayət qədər izlənir — hadisə
yaymaq yalnız heç bir abunəçisi olmayan mürəkkəblik əlavə edərdi (YAGNI).
`WorkMode`/`FineType`/`LeaveType` də eyni səbəbdən sadə `dataclass`-dır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.domain.value_objects.catalogs import CatalogEntry, InvalidCatalogEntryError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.domain.value_objects.identifiers import EmployeeId, StoreId, StoreTemplateId


@dataclass(frozen=True)
class StoreTemplate(CatalogEntry):
    """Yeni filial üçün əsas kimi köçürülə bilən, adlandırılmış ayar toplusu.

    `frozen=True`: `CatalogEntry` ilə eyni səbəb (bax onun başlığı) — köhnə
    obyektə istinad saxlayan ekran səssizcə dəyişmir.
    """

    store_template_id: StoreTemplateId | None = None
    #: Nümunə götürülmüş mağaza. `None` = mənbə silinib (`ON DELETE SET NULL`,
    #: migrations/037) VƏ YA şablon sıfırdan qurulub — hər ikisi qanunidir,
    #: şablonun DƏYƏRİ `config_snapshot`-dadır, mənbədə DEYİL.
    based_on_store_id: StoreId | None = None
    #: Şablonun ayar toplusu — MƏZMUNU bu fayl DEYİL, tətbiq qatı müəyyən edir
    #: (bax modul başlığı).
    config_snapshot: Mapping[str, object] = field(default_factory=dict)
    #: Şablonu yaradan şəxs — audit sualının struktur cavabı.
    created_by: EmployeeId | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.config_snapshot:
            # `chk_...`-in DEYİL (bu cədvəldə adı yoxdur), birbaşa `CHECK
            # (config_snapshot <> '{}'::jsonb)` şərtinin domen güzgüsü —
            # defense-in-depth: ekranı yan keçən skript də bura tabedir.
            raise InvalidCatalogEntryError(
                "Şablonun ayar toplusu (config_snapshot) boş ola bilməz",
                user_message="Şablonda ən azı bir ayar olmalıdır.",
                context={"name": self.name},
            )


__all__ = ["StoreTemplate"]
