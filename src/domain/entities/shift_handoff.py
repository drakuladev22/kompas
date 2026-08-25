"""Şift-handoff (növbə təhvili) qeydi — `v2backlog.md` Faza 5.3.

    "Şift Sonlandır axınına istəyə-bağlı «təhvil-qeydi» sahəsi (açıq-
     tapşırıqlar, kassa-vəziyyəti) — növbəti şiftin işçisinə Başlat zamanı
     göstərilir."

──────────────────────────────────────────────────────────────────────────────
QEYD İŞÇİYƏ DEYİL, MAĞAZANIN NÖVBƏ SIRASINA AİDDİR
──────────────────────────────────────────────────────────────────────────────
Yazan ilə oxuyan FƏRQLİ adamlardır və oxuyanın həmin gün ümumiyyətlə
davamiyyət sətri olmaya bilər (səhər açan işçi gecə qeydini oxuyur). Ona görə
aqreqat `AttendanceRecord`-un bir sahəsi DEYİL, müstəqil sətirdir — səbəbin
sxem tərəfi `migrations/099` başlığındadır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ «QƏBUL EDİLDİ» (`acknowledge`) VAR, «SİLİNDİ» YOXDUR
──────────────────────────────────────────────────────────────────────────────
Təhvil-qəbul İKİ tərəfli faktdır: qeydin yazılması bir tərəf, oxunması
digəridir. Qeyd silinə bilsəydi, «mən xəbərdar edilməmişdim» mübahisəsində
heç bir sübut qalmazdı — halbuki qeydin mövzusu tez-tez KASSA VƏZİYYƏTİDİR,
yəni pul. `catalogs.py`-nin soft-delete əsaslandırması ilə eyni məntiq.

Köhnəlmə isə SİLMƏ ilə deyil, GÖRÜNMƏ PƏNCƏRƏSİ ilə həll olunur
(`SHIFT_HANDOFF_VISIBILITY_HOURS`, Root parametri) — sətir qalır, sadəcə
növbəti işçiyə göstərilmir.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Final

from src.domain.entities.base import AggregateRoot, DomainRuleError
from src.domain.value_objects.identifiers import (
    EmployeeId,
    ShiftHandoffNoteId,
    StoreId,
    TenantId,
)
from src.domain.value_objects.scheduling import require_aware

#: `shift_handoff_notes.note` — DB `CHECK (char_length(trim(note)) >= 1)`.
#: Yuxarı hədd BURADA YOXDUR: o, Root parametridir
#: (`SHIFT_HANDOFF_NOTE_MAX_CHARS`) və use case tərəfindən ötürülür — sinifdə
#: sabit tavan Root-un dəyişikliyini görməz.
MIN_HANDOFF_NOTE_LENGTH: Final[int] = 1


class ShiftHandoffNote(AggregateRoot):
    """Bir növbənin növbətiyə qoyduğu qeyd.

        yazıldı ──acknowledge(növbəti işçi)──> qəbul edildi   (TERMİNAL)

    Qəbul BİR DƏFƏ baş verir: ikinci işçi eyni qeydi yenidən «qəbul» edə
    bilməz, çünki o zaman «kim təhvil aldı» sualının cavabı dəyişərdi.
    """

    def __init__(
        self,
        *,
        note_id: ShiftHandoffNoteId,
        tenant_id: TenantId,
        store_id: StoreId,
        author_employee_id: EmployeeId,
        note: str,
        work_date: date,
        created_at: datetime,
        max_length: int,
        acknowledged_by: EmployeeId | None = None,
        acknowledged_at: datetime | None = None,
    ) -> None:
        super().__init__()
        cleaned = note.strip()
        if len(cleaned) < MIN_HANDOFF_NOTE_LENGTH:
            raise DomainRuleError(
                "Təhvil qeydi boş ola bilməz",
                user_message="Təhvil qeydini yazın və ya bu addımı buraxın.",
            )
        # Hədd ÇAĞIRANDAN gəlir (Root parametri), sinifdən yox — sabit tavan
        # `system_limits`-in mənasını itirərdi (CLAUDE.md §5).
        if len(cleaned) > max_length:
            raise DomainRuleError(
                f"Təhvil qeydi maksimum {max_length} simvol ola bilər",
                user_message=(
                    f"Qeyd çox uzundur — maksimum {max_length} simvol. "
                    f"Hazırkı uzunluq: {len(cleaned)}."
                ),
                context={"length": len(cleaned), "max_length": max_length},
            )

        self.id = note_id
        self.tenant_id = tenant_id
        self.store_id = store_id
        self.author_employee_id = author_employee_id
        self.note = cleaned
        self.work_date = work_date
        self.created_at = require_aware(created_at, field="created_at")
        self.acknowledged_by = acknowledged_by
        self.acknowledged_at = (
            require_aware(acknowledged_at, field="acknowledged_at")
            if acknowledged_at is not None
            else None
        )
        # DB `chk_handoff_ack` ilə EYNİ qayda (CLAUDE.md §5 «hər qayda İKİ
        # yerdə»): yarımçıq cüt sətri sükutla qəbul edilsəydi, ekran «qəbul
        # edilib» göstərib «kim tərəfindən» sualını cavabsız qoyardı.
        if (acknowledged_by is None) != (acknowledged_at is None):
            raise DomainRuleError(
                "Təhvil qəbulu natamamdır — kim və nə vaxt birlikdə yazılır",
                user_message="Təhvil qeydi düzgün oxunmadı.",
            )

    @property
    def is_acknowledged(self) -> bool:
        return self.acknowledged_at is not None

    def is_visible_at(self, moment: datetime, *, visibility_hours: int) -> bool:
        """Qeyd bu anda növbəti işçiyə GÖSTƏRİLİRMİ.

        Qəbul edilmiş qeyd artıq göstərilmir (öz işini görüb), köhnəlmiş qeyd
        də göstərilmir — LAKİN ikisi FƏRQLİ hallardır və sətirdə ayrı-ayrı
        görünür: biri `acknowledged_at` ilə, digəri yalnız vaxtla.

        `visibility_hours` ÇAĞIRANDAN gəlir (`SHIFT_HANDOFF_VISIBILITY_HOURS`)
        və HƏR oxunuşda yenidən tətbiq olunur — Root həddi dəyişəndə ARTIQ
        yazılmış qeydlər dərhal yeni qaydaya tabe olur.
        """
        require_aware(moment, field="moment")
        if self.is_acknowledged:
            return False
        age_hours = (moment - self.created_at).total_seconds() / 3600.0
        return 0 <= age_hours <= visibility_hours

    def acknowledge(self, *, employee_id: EmployeeId, acknowledged_at: datetime) -> None:
        """Növbəti işçi qeydi gördü və qəbul etdi.

        ÖZ QEYDİNİ ÖZÜ QƏBUL EDƏ BİLMƏZ: təhvil-qəbulun bütün mənası İKİ
        şəxsin olmasıdır. Eyni işçi növbəni həm bağlayıb həm açırsa, qeyd
        sadəcə görünmə pəncərəsində qalır və növbəti FƏRQLİ işçi onu qəbul
        edir — sükutla «özünə təhvil» yazmaq təhvil zəncirini yalançı edərdi.
        """
        require_aware(acknowledged_at, field="acknowledged_at")
        if self.is_acknowledged:
            raise DomainRuleError(
                "Təhvil qeydi artıq qəbul edilib",
                user_message="Bu təhvil qeydini başqa işçi artıq qəbul edib.",
                context={"note_id": str(self.id)},
            )
        if employee_id == self.author_employee_id:
            raise DomainRuleError(
                "İşçi öz təhvil qeydini özü qəbul edə bilməz",
                user_message="Öz yazdığınız təhvil qeydini qəbul edə bilməzsiniz.",
                context={"employee_id": str(employee_id)},
            )

        self.acknowledged_by = employee_id
        self.acknowledged_at = acknowledged_at

    def __repr__(self) -> str:
        state = "qəbul edilib" if self.is_acknowledged else "gözləyir"
        return f"<ShiftHandoffNote {self.id} {self.work_date} {state}>"
