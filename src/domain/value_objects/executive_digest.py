"""Planlaşdırılmış İcra Xülasəsi — konfiqurasiya sətri (#30, kompas1.md Faza 6).

──────────────────────────────────────────────────────────────────────────────
İKİ HƏQİQƏT MƏNBƏYİ ARASINDAKI SƏRHƏD (oxu BUNU birinci)
──────────────────────────────────────────────────────────────────────────────
`kompas1.md` "tezlik" və "daxil olan metriklər"i **ROOT PARAMETRİ** adlandırır,
LAKİN Faza 1 artıq `executive_digest_config` cədvəlini (`recipient_role`,
`frequency`, `metrics_included`, `last_sent_at`) qurub. Eyni məlumatı İKİ
yerdə saxlamaq klassik "iki həqiqət mənbəyi" qüsurudur — biri dəyişəndə
digəri sükutla köhnəlir. Sərhəd BURADA ŞÜURLU ÇƏKİLİB:

  * `system_limits` (`EXECUTIVE_DIGEST_METRIC_CATALOG`,
    `EXECUTIVE_DIGEST_DEFAULT_FREQUENCY`, `EXECUTIVE_DIGEST_WEEKLY_WEEKDAY`)
    **SİYASƏTDİR**: hansı metrik açarları ÜMUMİYYƏTLƏ mövcuddur (toggle-lənə
    bilən kataloq), yeni konfiqurasiya yaradılanda tezliyin DEFOLTU nə olsun,
    həftəlik xülasə HANSI gün getsin. Bunlar bütün kirayəçiyə aid TƏK dəyərdir
    və `executive_digest_config` cədvəlində sütunu YOXDUR — ikiqat mənbə
    RİSKİ belə YARANMIR.
  * `executive_digest_config` sətri (bu modulun `ExecutiveDigestConfig`-i)
    **FAKTİKİ VƏZİYYƏTDİR**: Root konkret hansı ROLA, hansı TEZLİKDƏ, hansı
    METRİKLƏRLƏ xülasə göndərilməsini SEÇİB (bir kirayəçidə bir neçə sətir ola
    bilər — məs. CEO həftəlik + Mağaza Meneceri gündəlik) və `last_sent_at`
    planlayıcının İDEMPOTENTLİK yoxlamasıdır (bax `application/use_cases/
    executive_digest.py` başlığı, "TƏKRAR GÖNDƏRMƏNİN QARŞISINI NƏ ALIR").

Yəni `system_limits` "nə mümkündür və yeni sətir yaradılanda nə təklif
olunur"u saxlayır, cədvəl isə "kim nəyi seçib"i. Metrik kataloqu dəyişəndə
(Root yeni açar əlavə edəndə/köhnəsini çıxaranda) MÖVCUD sətirlərin
`metrics_included`-i AVTOMATİK DƏYİŞMİR — bu, `Feature Toggle`-ın retroaktiv
təsir ETMƏMƏSİ qaydası ilə EYNİ fəlsəfədir (CLAUDE.md §5): kataloqdan çıxan
açar mövcud konfiqurasiyanı sükutla pozmur, YALNIZ yeni redaktədə seçim
siyahısından çıxır (bax `ExecutiveDigestUseCase.configure`).

──────────────────────────────────────────────────────────────────────────────
`DigestFrequency`-də NİYƏ `MONTHLY` DƏ VAR (amma İŞLƏMİR)
──────────────────────────────────────────────────────────────────────────────
`migrations/037`-dəki DB `CHECK (frequency IN ('DAILY','WEEKLY','MONTHLY'))`
Faza 1-də — bu moduldan ƏVVƏL — yazılıb və QIRMIZI XƏTT (CLAUDE.md §7: mövcud
miqrasiyaya toxunulmur). Domen enumu DB CHECK-in GÜZGÜSÜ olmalıdır (CLAUDE.md
§6 — "hər qayda iki yerdə var"), ona görə `MONTHLY` BURADA sadalanır, LAKİN
`kompas1.md` Faza 6 YALNIZ gündəlik/həftəlik tələb edir və planlayıcıya
qeydiyyatdan keçən YEGANƏ iş (`EXECUTIVE_DIGEST_RUN`) yalnız `DAILY` və
`WEEKLY` tezliyini emal edir (bax use case `run()` metodu). `MONTHLY` sətri
DB-də YAZILA BİLƏR (məs. gələcək Faza bunu tamamlayana qədər əlyani test
sətri), lakin planlayıcı ONU HEÇ VAXT GÖNDƏRMİR — sükutla YARIMÇIQ funksiya
yaratmaqdansa, `configure()` YENİ sətir üçün `MONTHLY`-ni AÇIQ RƏDD EDİR (bax
aşağı, `SUPPORTED_FREQUENCIES`) ki, Root "seçdim, işləyəcək" zənn etməsin.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Final

from src.domain.value_objects.identifiers import (
    EmployeeId,
    ExecutiveDigestConfigId,
    TenantId,
)
from src.domain.value_objects.scheduling import require_aware
from src.shared.exceptions import KompasOSError

#: `executive_digest_config.recipient_role` CHECK-inin güzgüsü (migrations/037:
#: `char_length(trim(recipient_role)) >= 2`). Sxem sərhədidir, ROOT PARAMETRİ
#: DEYİL (`WorkModeCatalogUseCase`-dəki `MIN_NAME_LENGTH` ilə eyni qərar).
MIN_ROLE_CODE_LENGTH: Final[int] = 2


class InvalidDigestConfigError(KompasOSError):
    """Xülasə konfiqurasiyası yararsızdır (boş metrik, qısa rol kodu və s.)."""

    user_message = "Xülasə ayarları düzgün deyil."


class DigestFrequency(str, Enum):
    """`executive_digest_config.frequency` — DB CHECK-in güzgüsü.

    `MONTHLY` DB-də mümkündür, LAKİN planlayıcı onu emal ETMİR (bax modul
    başlığı) — `SUPPORTED_FREQUENCIES`-ə BAXMADAN bu enumdan istifadə edən
    kod "hər üçü işləyir" zənn etməsin deyə `is_scheduled` xassəsi var.
    """

    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"

    @property
    def is_scheduled(self) -> bool:
        """Planlayıcının FAKTİKİ göndərdiyi tezlikdirmi (`DAILY`/`WEEKLY`)."""
        return self in (DigestFrequency.DAILY, DigestFrequency.WEEKLY)

    @property
    def label_az(self) -> str:
        return {"DAILY": "Gündəlik", "WEEKLY": "Həftəlik", "MONTHLY": "Aylıq"}[self.value]


#: `configure()`-in YENİ sətirdə qəbul etdiyi tezliklər — `MONTHLY` xaricdir
#: (bax modul başlığı). Mövcud `MONTHLY` sətri OXUNA bilər (məs. idarəetmə
#: ekranında görünür), yalnız YENİ yaradıla/YENİDƏN seçilə bilməz.
SUPPORTED_FREQUENCIES: Final[frozenset[DigestFrequency]] = frozenset(
    {DigestFrequency.DAILY, DigestFrequency.WEEKLY}
)


class DigestMetricKey(str, Enum):
    """Xülasəyə daxil edilə bilən göstərici açarları.

    Hər açarın hesablaması `application/use_cases/executive_digest.py`-da
    MÖVCUD use case-ə/repo-ya bağlanır — bu modul YALNIZ açarın adını və
    Azərbaycanca etiketini saxlayır (istisna/cərimə/overtime/turnover
    məntiqinin ÖZÜ burada TƏKRARLANMIR, CLAUDE.md §3: domen tətbiq qatını
    tanımır).

    KATALOQ `system_limits.EXECUTIVE_DIGEST_METRIC_CATALOG`-dan gəlir (bax
    modul başlığı) — bu enum "kodun HESABLAYA BİLDİYİ" tam çoxluqdur, kataloq
    isə "bu kirayəçidə TƏKLİF OLUNAN" alt-çoxluqdur.
    """

    FINE_COUNT = "FINE_COUNT"
    OPEN_EXCEPTION_COUNT = "OPEN_EXCEPTION_COUNT"
    LATE_CHECK_IN_COUNT = "LATE_CHECK_IN_COUNT"
    OVERTIME_HOURS = "OVERTIME_HOURS"
    TURNOVER_RISK = "TURNOVER_RISK"

    @property
    def label_az(self) -> str:
        return _METRIC_LABELS[self]


_METRIC_LABELS: Final[dict[DigestMetricKey, str]] = {
    DigestMetricKey.FINE_COUNT: "Cərimə sayı",
    DigestMetricKey.OPEN_EXCEPTION_COUNT: "Açıq istisna sayı",
    DigestMetricKey.LATE_CHECK_IN_COUNT: "Gecikən check-in sayı",
    DigestMetricKey.OVERTIME_HOURS: "Overtime saatı",
    DigestMetricKey.TURNOVER_RISK: "Turnover riski (orta bal)",
}


def _clean_role_code(raw: str) -> str:
    """`recipient_role`-u normallaşdırır — DB CHECK-in (BÖYÜK hərf, >= 2 simvol)
    tətbiq-qatı güzgüsü (`field_report_categories.route_to_role` ilə eyni naxış)."""
    cleaned = raw.strip().upper()
    if len(cleaned) < MIN_ROLE_CODE_LENGTH:
        raise InvalidDigestConfigError(
            f"Alıcı rol kodu minimum {MIN_ROLE_CODE_LENGTH} simvol olmalıdır",
            user_message="Alıcı rol adı çox qısadır.",
        )
    return cleaned


def _clean_metrics(raw: tuple[str, ...]) -> tuple[str, ...]:
    """Metrik siyahısını normallaşdırır — boş siyahı QADAĞANDIR (DB CHECK-in
    `cardinality(metrics_included) >= 1` güzgüsü). Sıra QORUNUR (Root-un
    seçim ardıcıllığı email mətnində görünür) — `dict.fromkeys` TƏKRARLARI
    sıranı pozmadan çıxarır."""
    cleaned = tuple(dict.fromkeys(item.strip().upper() for item in raw if item.strip()))
    if not cleaned:
        raise InvalidDigestConfigError(
            "Ən azı bir metrik seçilməlidir — boş xülasə mənasızdır",
            user_message="Ən azı bir göstərici seçin.",
        )
    return cleaned


@dataclass(frozen=True)
class ExecutiveDigestConfig:
    """`executive_digest_config` sətrinin domen görünüşü.

    `metrics_included` sadə `tuple[str, ...]`-dur, `frozenset[DigestMetricKey]`
    DEYİL: DB sütunu TEXT[]-dir və Root gələcəkdə kataloqda OLMAYAN (hələ kod
    dəstəyi almamış) açar seçə bilər — sərt enum həmin sətri YÜKLƏNMƏZDƏN
    ƏVVƏL çökdürərdi. Naməlum açar `ExecutiveDigestUseCase.run()`-da SÜKUTLA
    ATLANIR (bax həmin modulun başlığı), YÜKLƏMƏ ANINDA yox.
    """

    config_id: ExecutiveDigestConfigId | None
    tenant_id: TenantId
    recipient_role: str
    frequency: DigestFrequency
    metrics_included: tuple[str, ...]
    last_sent_at: datetime | None = None
    is_active: bool = True
    deactivated_at: datetime | None = None
    created_by: EmployeeId | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipient_role", _clean_role_code(self.recipient_role))
        object.__setattr__(self, "metrics_included", _clean_metrics(self.metrics_included))
        if self.last_sent_at is not None:
            require_aware(self.last_sent_at, field="last_sent_at")
        if self.deactivated_at is not None:
            require_aware(self.deactivated_at, field="deactivated_at")
        if self.is_active and self.deactivated_at is not None:
            raise InvalidDigestConfigError(
                "Aktiv sətrin deaktivləşdirmə tarixi ola bilməz — ziddiyyətli vəziyyət saxlanmır"
            )
        if not self.is_active and self.deactivated_at is None:
            raise InvalidDigestConfigError("Deaktiv sətir üçün deaktivləşdirmə anı MƏCBURİDİR")


__all__ = [
    "MIN_ROLE_CODE_LENGTH",
    "SUPPORTED_FREQUENCIES",
    "DigestFrequency",
    "DigestMetricKey",
    "ExecutiveDigestConfig",
    "InvalidDigestConfigError",
]
