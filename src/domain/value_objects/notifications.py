"""Bildiriş kateqoriyaları və kritiklik qaydası (bölmə 7) — Faza 3.12.

Spesifikasiya: *"Kritik bildirişlər (timeout eskalasiyası, dual-control təsdiq
gözləyir, ödəniş xatırlatması, LICENSE_INACTIVE xəbərdarlığı, tapşırıq
son-tarix eskalasiyası, `PENDING_RECONCILIATION` statusuna keçən Saga
əməliyyatı — sistemin ən ciddi məlumat-bütövlüyü vəziyyəti olduğu üçün heç
vaxt sükutla qeyd olunmamalıdır) ... eyni zamanda qeydiyyatlı admin e-poçtuna
da göndərilir."*

──────────────────────────────────────────────────────────────────────────────
NİYƏ KRİTİKLİK ÇAĞIRANDAN TAM ASILI DEYİL
──────────────────────────────────────────────────────────────────────────────
`notify(..., is_critical=True)` imzası özlüyündə kifayətdir — LAKİN yalnız
çağıran tərəf onu unutmadıqda. Spesifikasiyada sadalanan altı kateqoriya isə
məhz "unudulmamalı" olanlardır: `PENDING_RECONCILIATION` sistemin ən ciddi
məlumat-bütövlüyü vəziyyətidir və bir `True` yazmağı unutmaq onu sükuta
çevirərdi.

Ona görə kateqoriya siyahısı BURADA, domendə saxlanılır və bildiriş qatı
`is_critical`-i məcburi olaraq YÜKSƏLDİR (heç vaxt endirmir): çağıran istədiyi
şeyi kritik edə bilər, lakin sadalananları qeyri-kritik EDƏ BİLMƏZ.
"""

from __future__ import annotations

from enum import Enum
from typing import Final


class NotificationCategory(str, Enum):
    """`notifications.category` dəyərləri."""

    TIMEOUT_ESCALATION = "TIMEOUT_ESCALATION"
    DUAL_CONTROL_PENDING = "DUAL_CONTROL_PENDING"
    PAYMENT_REMINDER = "PAYMENT_REMINDER"
    LICENSE_INACTIVE = "LICENSE_INACTIVE"
    TASK_DEADLINE = "TASK_DEADLINE"
    SAGA_PENDING_RECONCILIATION = "SAGA_PENDING_RECONCILIATION"
    # Aşağıdakılar məlumatlandırıcıdır — e-poçt fallback-ı tələb etmir.
    FINE_ISSUED = "FINE_ISSUED"
    LEAVE_DECISION = "LEAVE_DECISION"
    SHIFT_SWAP = "SHIFT_SWAP"
    POINTS_RESET_UPCOMING = "POINTS_RESET_UPCOMING"
    ERP_SYNC_FAILED = "ERP_SYNC_FAILED"

    @property
    def is_always_critical(self) -> bool:
        return self.value in ALWAYS_CRITICAL_CATEGORIES

    @property
    def label_az(self) -> str:
        return _LABELS_AZ.get(self, self.value)


#: Bölmə 7-də adbaad sadalanan altı kateqoriya — HƏMİŞƏ e-poçt fallback-ı alır.
#: Sətir (Enum yox) saxlanılır ki, gələcəkdə DB-dən gələn naməlum kateqoriya
#: adı da bu siyahıya salına bilsin.
ALWAYS_CRITICAL_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "TIMEOUT_ESCALATION",
        "DUAL_CONTROL_PENDING",
        "PAYMENT_REMINDER",
        "LICENSE_INACTIVE",
        "TASK_DEADLINE",
        "SAGA_PENDING_RECONCILIATION",
    }
)

_LABELS_AZ: Final[dict[NotificationCategory, str]] = {
    NotificationCategory.TIMEOUT_ESCALATION: "Təsdiq gecikməsi",
    NotificationCategory.DUAL_CONTROL_PENDING: "İkili nəzarət təsdiqi gözlənilir",
    NotificationCategory.PAYMENT_REMINDER: "Ödəniş xatırlatması",
    NotificationCategory.LICENSE_INACTIVE: "Lisenziya deaktivdir",
    NotificationCategory.TASK_DEADLINE: "Tapşırıq son tarixi",
    NotificationCategory.SAGA_PENDING_RECONCILIATION: "Uzlaşdırma tələb olunur",
    NotificationCategory.FINE_ISSUED: "Cərimə tətbiq edildi",
    NotificationCategory.LEAVE_DECISION: "İcazə qərarı",
    NotificationCategory.SHIFT_SWAP: "Növbə dəyişikliyi",
    NotificationCategory.POINTS_RESET_UPCOMING: "Xal sıfırlanması yaxınlaşır",
    NotificationCategory.ERP_SYNC_FAILED: "1C sinxronizasiya xətası",
}


def is_critical_category(category: str) -> bool:
    """Kateqoriya HƏMİŞƏ kritikdirmi (çağıranın bayrağından asılı olmayaraq)."""
    return category.strip().upper() in ALWAYS_CRITICAL_CATEGORIES


def email_subject(category: str, title_az: str) -> str:
    """E-poçt mövzusu — qutuda süzgəclənə bilsin deyə prefiks daşıyır.

    Prefiks olmadan bu mesajlar admin-in qutusunda digər yazışmalarla
    qarışardı; süzgəc qurmaq mümkün olmazdı və nəticədə spesifikasiyanın
    məqsədi ("gözdən qaçmasın") pozulardı.
    """
    try:
        label = NotificationCategory(category.strip().upper()).label_az
    except ValueError:
        label = category.strip() or "Bildiriş"
    return f"[KompasOS] {label}: {title_az}".strip()


def email_body(title_az: str, body_az: str, *, tenant_name: str = "") -> str:
    """E-poçt mətni — sadə mətn, HTML yoxdur.

    HTML şablon PII-ni gizlətmir, əvəzində yalnız render problemləri gətirir
    (kiril/Azərbaycan hərfləri, mobil qutular, spam filtrləri). Bildirişin
    məqsədi diqqət çəkməkdir, dizayn deyil.
    """
    header = f"{tenant_name} — {title_az}" if tenant_name else title_az
    return (
        f"{header}\n"
        f"{'-' * min(len(header), 60)}\n\n"
        f"{body_az}\n\n"
        "Bu bildiriş KompasOS tərəfindən avtomatik göndərilib.\n"
        "Ətraflı məlumat üçün proqramı açın."
    )


__all__ = [
    "ALWAYS_CRITICAL_CATEGORIES",
    "NotificationCategory",
    "email_body",
    "email_subject",
    "is_critical_category",
]
