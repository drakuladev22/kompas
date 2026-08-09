"""İşçinin birləşmiş statusu — Faza 4.2.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI, "BİRLƏŞMİŞ" STATUS
──────────────────────────────────────────────────────────────────────────────
İşçi Ana Ekranı (maket 05) BEŞ vəziyyət göstərir, lakin domendə onlar İKİ
ayrı enum-dadır:

    CheckInStatus.NOT_STARTED             → ⚪ Günə Başlamayıb
    CheckInStatus.PENDING_VERIFICATION    → 🟡 Giriş Təsdiqi Gözləyir
    CheckInStatus.VERIFIED                → 🟢 Mağazada
    LeaveStatus.OUTSIDE                   → 🔵 Xaricdə
    LeaveStatus.PENDING_RETURN_VERIFICATION → 🟡 Qayıdış Təsdiqi Gözləyir

Bölünmə domendə DÜZGÜNDÜR — davamiyyət və icazə ayrı aqreqatlardır. Lakin
ekran onları bir "sən indi haradasan" sualına yığır və hər vəziyyət üçün TƏK
düymə göstərir. Həmin xəritələmə burada, təqdimat qatında yaşayır: domenə
"UI üçün birləşmiş status" əlavə etmək iki aqreqatı bir-birinə bağlayardı.

Mətnlər və rənglər maketin `STATES` obyektindən götürülüb.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.entities.attendance_record import CheckInStatus
    from src.domain.entities.leave_request import LeaveStatus


class WorkerStatus(Enum):
    """İşçi Ana Ekranındakı beş vəziyyət.

    Hər üzv dörd şeyi daşıyır: Azərbaycanca ad, izah, düymə mətni və rəng
    tokeni.
    """

    NOT_STARTED = (
        "Günə Başlamayıb",
        "Bu gün üçün giriş qeydə alınmayıb.",
        "İşə Başladım",
        "--color-text-muted",
        True,
    )
    PENDING_CHECK_IN = (
        "Giriş Təsdiqi Gözləyir",
        "Kamera operatoru girişinizi təsdiqləyir.",
        "Gözlənilir…",
        "--color-warning",
        False,
    )
    VERIFIED = (
        "Mağazada",
        "Girişiniz təsdiqləndi.",
        "İcazə İstəyirəm",
        "--color-success",
        True,
    )
    OUTSIDE = (
        "Xaricdə",
        "İcazə vaxtınız davam edir.",
        "Mən Qayıtdım",
        "--color-info",
        True,
    )
    PENDING_RETURN = (
        "Qayıdış Təsdiqi Gözləyir",
        "Qayıdışınız operator təsdiqini gözləyir.",
        "Gözlənilir…",
        "--color-warning",
        False,
    )

    def __init__(
        self,
        label_az: str,
        hint_az: str,
        action_az: str,
        color_token: str,
        is_actionable: bool,
    ) -> None:
        self.label_az = label_az
        self.hint_az = hint_az
        self.action_az = action_az
        self.color_token = color_token
        #: `False` → düymə görünür, lakin basıla bilmir (təsdiq gözlənilir).
        self.is_actionable = is_actionable

    @classmethod
    def from_domain(
        cls,
        check_in: CheckInStatus | None,
        leave: LeaveStatus | None = None,
    ) -> WorkerStatus:
        """Domen enum-larından birləşmiş statusu hesablayır.

        İCAZƏ ÜSTÜNLÜK TƏŞKİL EDİR: aktiv icazəsi olan işçi fiziki olaraq
        mağazada deyil, yəni `VERIFIED` (Mağazada) göstərmək YANLIŞ olardı —
        operator onu "içəridə" sanıb qayıdışını gözləməzdi.
        """
        from src.domain.entities.leave_request import LeaveStatus as _Leave  # noqa: PLC0415

        if leave is _Leave.OUTSIDE:
            return cls.OUTSIDE
        if leave is _Leave.PENDING_RETURN_VERIFICATION:
            return cls.PENDING_RETURN

        from src.domain.entities.attendance_record import (  # noqa: PLC0415
            CheckInStatus as _CheckIn,
        )

        if check_in is _CheckIn.VERIFIED:
            return cls.VERIFIED
        if check_in is _CheckIn.PENDING_VERIFICATION:
            return cls.PENDING_CHECK_IN
        return cls.NOT_STARTED


__all__ = ["WorkerStatus"]
