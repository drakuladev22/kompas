"""Şift-handoff (növbə təhvili) qeydi — `v2backlog.md` Faza 5.3.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA USE CASE, `MorningCheckInUseCase`-in METODU DEYİL
──────────────────────────────────────────────────────────────────────────────
`start_day()` işçinin ÖZ davamiyyət sətrini yaradır və Kamera Operatoru
təsdiqi ilə bağlıdır — orada həm anti-fraud (`_require_camera_permission`),
həm NTP, həm gecikmə hesabı var. Handoff isə MAĞAZANIN növbə sırasına aid,
təsdiq tələb ETMƏYƏN, tamamilə ayrı bir axındır. Metod kimi əlavə edilsəydi,
`start_day()`-in uğursuzluğu (məs. gecikmə hesabında xəta) təhvil qeydini də
udardı və əksinə.

BAĞLANTI İSƏ VAR VƏ QƏSDLİDİR: `pending_for_employee()` məhz `start_day`
ekranında çağırılır (`v2backlog.md`: «növbəti şiftin işçisinə Başlat zamanı
göstərilir»), lakin ÇAĞIRIŞ presentation qatındadır — iki axın bir-birini
sındırmır.

──────────────────────────────────────────────────────────────────────────────
SƏLAHİYYƏT FLAG-I NİYƏ YOXDUR
──────────────────────────────────────────────────────────────────────────────
Təhvil qeydini yazan da, oxuyan da ADİ işçidir — flag tələb etmək «öz növbəni
təhvil vermək üçün icazə lazımdır» demək olardı. Əvəzinə İKİ struktur şərt
var və hər ikisi domendədir:
  * işçi yalnız ÖZ mağazasına qeyd yaza bilər (`_require_store`);
  * öz qeydini özü qəbul edə bilməz (`ShiftHandoffNote.acknowledge`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.application.root_limits import fallback_int, limit_int
from src.domain.entities.shift_handoff import ShiftHandoffNote
from src.domain.policies import SystemLimitKey
from src.domain.value_objects.identifiers import new_shift_handoff_note_id
from src.shared.exceptions import KompasOSError

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        Clock,
        ShiftHandoffRepository,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import (
        ShiftHandoffNoteId,
        StoreId,
        TenantId,
    )

#: Kiosk kartının bir dəfəyə göstərdiyi qeyd sayı.
#:
#: `system_limits` AÇARI DEYİL və bu, qəsdlidir: görünmə pəncərəsi
#: (`SHIFT_HANDOFF_VISIBILITY_HOURS`) ARTIQ Root parametridir və qeydlərin
#: sayını FAKTİKİ olaraq o məhdudlaşdırır. Bu ədəd yalnız patoloji halda
#: (bir növbədə onlarla qeyd) sorğunun sonsuz böyüməsinin qarşısını alan
#: riyazi tavandır — `SHORT_CODE_ATTEMPTS`-in eyni növ sabiti (CLAUDE.md §5,
#: «Root parametri DEYİL» cədvəli ilə eyni məntiq, lakin bu, sırf oxu
#: həddidir və heç bir davranışı dəyişmir).
MAX_OPEN_NOTES_FETCHED = 20


class ShiftHandoffError(KompasOSError):
    """Təhvil qeydi əməliyyatı icra edilə bilmədi."""

    user_message = "Təhvil qeydi ilə bağlı əməliyyat icra edilə bilmədi."


class ShiftHandoffNotFoundError(ShiftHandoffError):
    user_message = "Bu təhvil qeydi tapılmadı."


class ShiftHandoffUseCase:
    """Növbə təhvili qeydinin yazılması və növbəti işçi tərəfindən qəbulu."""

    def __init__(
        self,
        *,
        handoffs: ShiftHandoffRepository,
        audit: AuditTrail,
        clock: Clock,
        limits: SystemLimits | None = None,
    ) -> None:
        self._handoffs = handoffs
        self._audit = audit
        self._clock = clock
        self._limits = limits

    # ------------------------------- yazma ----------------------------------- #

    def leave_note(
        self,
        *,
        tenant_id: TenantId,
        employee: Employee,
        note: str,
        store_id: StoreId | None = None,
    ) -> ShiftHandoffNote:
        """Növbəni bitirən işçi qeyd qoyur — İSTƏYƏ BAĞLI addımdır.

        `store_id` ötürülmürsə işçinin öz mağazası götürülür. Açıq ötürülən
        dəyər İŞÇİNİN mağazası ilə eyni olmalıdır: başqa mağazanın növbə
        sırasına qeyd yazmaq təhvil zəncirini yalançı edərdi (kimsə orada
        işləməyib).
        """
        target = self._require_store(employee, store_id)
        now = self._clock.now()
        entry = ShiftHandoffNote(
            note_id=new_shift_handoff_note_id(),
            tenant_id=tenant_id,
            store_id=target,
            author_employee_id=employee.id,
            note=note,
            # İŞ GÜNÜ server vaxtından götürülür (`Clock` portu) — `datetime.
            # now()` HEÇ YERDƏ çağırılmır (CLAUDE.md §4).
            work_date=now.date(),
            created_at=now,
            max_length=self._note_max_chars(tenant_id),
        )
        self._handoffs.save(entry)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=employee.id,
            action="SHIFT_HANDOFF_NOTE_LEFT",
            entity_type="shift_handoff_notes",
            entity_id=entry.id,
            after_state={
                "store_id": str(entry.store_id),
                "work_date": entry.work_date.isoformat(),
                # MƏTNİN ÖZÜ audit `after_state`-ə YAZILMIR, yalnız uzunluğu:
                # qeyd kassa məbləği kimi həssas məlumat daşıya bilər və audit
                # jurnalı ondan GENİŞ auditoriyaya açıqdır (`can_view_audit_
                # log`). Mətn öz cədvəlində qalır və RLS ilə qorunur.
                "note_length": len(entry.note),
            },
        )
        return entry

    # ------------------------------- oxuma ----------------------------------- #

    def pending_for_employee(
        self, *, tenant_id: TenantId, employee: Employee, at: datetime | None = None
    ) -> list[ShiftHandoffNote]:
        """`[İşə Başladım]` ekranında göstəriləcək qeydlər.

        ÜÇ SÜZGƏC: mağaza (repo), qəbul edilməmiş (repo), görünmə pəncərəsi +
        «öz qeydim deyil» (burada). Sonuncu ikisi TƏTBİQ QATINDADIR, çünki
        biri Root parametrindən (`SHIFT_HANDOFF_VISIBILITY_HOURS`), digəri
        cari işçidən asılıdır — ikisi də SQL-ə köçürülsəydi eyni qayda iki
        yerdə yaşayardı (bax `ShiftHandoffRepository.list_open_for_store`).
        """
        if employee.store_id is None:
            return []
        moment = at if at is not None else self._clock.now()
        hours = self._visibility_hours(tenant_id)
        rows = self._handoffs.list_open_for_store(
            tenant_id, employee.store_id, limit=MAX_OPEN_NOTES_FETCHED
        )
        return [
            row
            for row in rows
            if row.author_employee_id != employee.id
            and row.is_visible_at(moment, visibility_hours=hours)
        ]

    # ------------------------------- qəbul ----------------------------------- #

    def acknowledge(
        self, *, tenant_id: TenantId, employee: Employee, note_id: ShiftHandoffNoteId
    ) -> ShiftHandoffNote:
        """Növbəti işçi `[Qəbul edirəm]` düyməsini basır."""
        entry = self._handoffs.get(note_id)
        if entry is None or entry.tenant_id != tenant_id:
            raise ShiftHandoffNotFoundError(
                "Təhvil qeydi tapılmadı",
                context={"note_id": str(note_id)},
            )
        # Öz mağazasının qeydini qəbul edir — başqa filialın təhvilini
        # «qəbul etmək» heç bir mənası olmayan, lakin auditdə İZ QOYAN
        # əməliyyatdır (kim təhvil aldı sualı yalan cavab alardı).
        self._require_store(employee, entry.store_id)

        entry.acknowledge(employee_id=employee.id, acknowledged_at=self._clock.now())
        self._handoffs.save(entry)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=employee.id,
            action="SHIFT_HANDOFF_NOTE_ACKNOWLEDGED",
            entity_type="shift_handoff_notes",
            entity_id=entry.id,
            after_state={
                "acknowledged_by": str(employee.id),
                "author_employee_id": str(entry.author_employee_id),
            },
        )
        return entry

    # ------------------------------- daxili ---------------------------------- #

    def _require_store(self, employee: Employee, store_id: StoreId | None) -> StoreId:
        if employee.store_id is None:
            raise ShiftHandoffError(
                "Filialı olmayan işçi növbə təhvili qeydi ilə işləyə bilməz",
                user_message="Təhvil qeydi üçün filialınız qeydə alınmalıdır.",
                context={"employee_id": str(employee.id)},
            )
        if store_id is not None and store_id != employee.store_id:
            raise ShiftHandoffError(
                "İşçi yalnız öz filialının növbə təhvilinə toxuna bilər",
                user_message="Yalnız öz filialınızın təhvil qeydləri ilə işləyə bilərsiniz.",
                context={"employee_store": str(employee.store_id), "target": str(store_id)},
            )
        return employee.store_id

    def _note_max_chars(self, tenant_id: TenantId) -> int:
        return limit_int(self._limits, tenant_id, SystemLimitKey.SHIFT_HANDOFF_NOTE_MAX_CHARS)

    def _visibility_hours(self, tenant_id: TenantId) -> int:
        return limit_int(self._limits, tenant_id, SystemLimitKey.SHIFT_HANDOFF_VISIBILITY_HOURS)


#: Portsuz (`limits=None`) qurulmada işlənən defoltlar — ekranların maket
#: yolunda Root oxunmur.
FALLBACK_NOTE_MAX_CHARS = fallback_int(SystemLimitKey.SHIFT_HANDOFF_NOTE_MAX_CHARS)
FALLBACK_VISIBILITY_HOURS = fallback_int(SystemLimitKey.SHIFT_HANDOFF_VISIBILITY_HOURS)
