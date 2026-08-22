"""Gündəlik Mağaza Tabeli (spesifikasiya bölmə 3) — Faza 5.

Store Manager-in ƏSAS funksiyası. Üç addım:

    1. `open_sheet()`  — tabel avtomatik ön-doldurulur (BOŞ başlamır)
    2. `annotate()`    — menecer kontekst qeydi yazır
    3. `confirm()`     — təsdiqləyir; uyğunsuzluq varsa HR_Admin-ə bildiriş

──────────────────────────────────────────────────────────────────────────────
NİYƏ "AÇMAQ" DA YAZMA ƏMƏLİYYATIDIR
──────────────────────────────────────────────────────────────────────────────
`open_sheet()` yalnız oxumur — tabel yoxdursa yaradır və faktlarla doldurur.
Alternativ (ekran açılanda yalnız yaddaşda hesablamaq) cəlbedici görünür,
amma pisdir: menecer səhər tabeli açıb qeyd yazsa, sonra bağlasa, axşam
yenidən açanda qeyd itərdi. Saxlanan sətir həm də auditdə "həmin gün nə
göründü" sualını cavablandırır.

──────────────────────────────────────────────────────────────────────────────
GÜN BİTMƏYİBSƏ "QAYIB" YAZILMIR
──────────────────────────────────────────────────────────────────────────────
`AttendanceFact.day_is_over` bayrağı `derive_status()`-a ötürülür. Səhər saat
10-da tabeli açan menecer hələ gəlməmiş işçini `🔴 İcazəsiz qayıb` kimi
görsəydi, bu, yanlış həyəcan olardı — o, saat 14-də gələ bilər. Gün bitənə
qədər status `🟡 Təsdiq gözləyir` qalır.

──────────────────────────────────────────────────────────────────────────────
#15 NORMA ÜSTÜ SAATLAR — ƏLAVƏ, ƏVƏZLƏMƏ DEYİL (kompasos11.md Faza 6)
──────────────────────────────────────────────────────────────────────────────
`confirm()` təsdiqdən SONRA `OvertimeTrackingUseCase.record_for_day()`-i
çağırır. Yuxarıdakı üç addımın (ön-doldurma → müqayisə → təsdiq) heç biri
dəyişmədi; aşım hesablaması onların NƏTİCƏSİNİN üzərinə qoyulur və ayrıca
cədvələ (`overtime_log`) yazılır.

Asılılıq QEYRİ-MƏCBURİDİR (`overtime: ... | None = None`): mövcud çağıranlar
(testlər, skriptlər, gələcək CLI) beş arqumentlə qurmağa davam edir və bu
zaman axın tam əvvəlki kimi işləyir. Məcburi etsəydik, #15-i tanımayan hər
mövcud çağırış qırılardı — halbuki tabel təsdiqi aşım jurnalından ASILI
deyil, ondan ƏVVƏL gəlir.

Xəta UDULMUR: aşım yazısı uğursuz olarsa istisna ötürülür və təsdiq də geri
qayıdır (hər ikisi eyni tranzaksiyadadır). Səbəb: təsdiqlənmiş tabel bir daha
təsdiqlənə bilmir (`_require_open`), yəni sükutla udulmuş xəta həmin günün
aşımını ƏBƏDİ yazılmamış qoyardı və heç bir jurnalda izi qalmazdı.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from src.domain.entities.attendance_sheet import (
    AttendanceCountingPolicy,
    AutoAttendanceStatus,
    DailyAttendanceSheet,
    build_lines,
)
from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.domain.value_objects.identifiers import new_daily_sheet_id
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.application.use_cases.overtime_tracking import OvertimeTrackingUseCase
    from src.domain.entities.attendance_sheet import SheetLine
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AttendanceFactProvider,
        AuditTrail,
        Clock,
        DailyAttendanceSheetRepository,
        Notifier,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import EmployeeId, StoreId, TenantId

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)

FILL_ATTENDANCE_FLAG = "can_fill_daily_attendance"
#: Uyğunsuzluqları görən HR tərəfi (bölmə 3 — "HR_Admin-ə xəbərdarlıq").
VIEW_REPORTS_FLAG = "can_view_employee_reports"


class SheetPermissionError(KompasOSError):
    """Tabelə giriş/dəyişiklik səlahiyyəti yoxdur."""

    user_message = "Bu tabelə giriş səlahiyyətiniz yoxdur."


class SheetNotFoundError(KompasOSError):
    user_message = "Tabel tapılmadı."


@dataclass(frozen=True)
class SheetView:
    """Ekranın göstərdiyi hazır tabel."""

    sheet: DailyAttendanceSheet
    #: HR planı ilə uyğunsuz sətirlər — ekranda vurğulanır.
    mismatches: list[SheetLine]
    is_editable: bool

    @property
    def mismatch_count(self) -> int:
        return len(self.mismatches)


class DailyAttendanceSheetUseCase:
    """Gündəlik Tabel — avtomatik ön-doldurma, müqayisə, təsdiq."""

    def __init__(
        self,
        *,
        sheets: DailyAttendanceSheetRepository,
        facts: AttendanceFactProvider,
        audit: AuditTrail,
        clock: Clock,
        notifier: Notifier,
        overtime: OvertimeTrackingUseCase | None = None,
        limits: SystemLimits | None = None,
    ) -> None:
        self._sheets = sheets
        self._facts = facts
        self._audit = audit
        self._clock = clock
        self._notifier = notifier
        #: #15 — norma üstü saat jurnalı. `None` = modul qoşulmayıb; tabel
        #: axını tam əvvəlki kimi işləyir (bax modul başlığı).
        self._overtime = overtime
        #: DEEP-GAP D1 — `ANNUAL_LEAVE_COUNTS_AS_WORKED_DAY` Root parametri.
        #: `None` = kompozisiya kökü hələ ötürməyib; `_counting_policy()`
        #: bu halda `AttendanceCountingPolicy.defaults()`-a düşür, yəni
        #: köhnə çağıranlar QIRILMIR.
        self._limits = limits

    def _counting_policy(self, tenant_id: TenantId) -> AttendanceCountingPolicy:
        """Root parametrini oxuyur (DEEP-GAP D1: illik məzuniyyət sayğacı).

        Tenant-a görə BİR dəfə oxunur, hər sətir üçün ayrıca YOX — əks halda
        Root dəyəri hesablama ərzində dəyişsə, eyni tabeldə iki sətir fərqli
        qaydayla sayıla bilərdi (`LaborLimits`/`AttritionWeights` ilə eyni
        əsaslandırma, bax `attendance_sheet.AttendanceCountingPolicy`).
        """
        if self._limits is None:
            return AttendanceCountingPolicy.defaults()
        key = SystemLimitKey.ANNUAL_LEAVE_COUNTS_AS_WORKED_DAY
        raw = self._limits.get_int(tenant_id, key.value, int(DEFAULT_LIMITS[key]))
        return AttendanceCountingPolicy(annual_leave_counts_as_worked=raw != 0)

    # -------------------------------- açmaq ---------------------------------- #

    def open_sheet(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        store_id: StoreId,
        sheet_date: date | None = None,
    ) -> SheetView:
        """Tabeli açır və avtomatik doldurur (bölmə 3)."""
        now = self._clock.now()
        day = sheet_date or now.date()
        self._require_store_access(actor, store_id)

        sheet = self._sheets.get_for_day(store_id, day)
        if sheet is None:
            sheet = DailyAttendanceSheet(
                sheet_id=new_daily_sheet_id(),
                tenant_id=tenant_id,
                store_id=store_id,
                sheet_date=day,
            )

        if not sheet.is_confirmed:
            # Ön-doldurma HƏR açılışda təkrarlanır: gün ərzində yeni check-in
            # qeydləri gəlir və tabel onları əks etdirməlidir.
            facts = self._facts.facts_for(store_id, day)
            sheet.prefill(build_lines(facts))
            self._sheets.save(sheet)

        return SheetView(
            sheet=sheet,
            mismatches=sheet.mismatched_lines,
            is_editable=not sheet.is_confirmed,
        )

    def pending_sheets(self, *, tenant_id: TenantId, actor: Employee) -> list[DailyAttendanceSheet]:
        """Təsdiq gözləyən tabellər — HR nəzarəti üçün (bölmə 3)."""
        now = self._clock.now()
        if not (
            actor.has_permission(VIEW_REPORTS_FLAG, now=now)
            or actor.has_permission(FILL_ATTENDANCE_FLAG, now=now)
        ):
            raise SheetPermissionError(
                "Tabel siyahısına baxmaq üçün səlahiyyət yoxdur",
                context={"actor_id": str(actor.id)},
            )
        return self._sheets.list_unconfirmed(tenant_id, up_to=now.date())

    # -------------------------------- qeyd ----------------------------------- #

    def annotate_line(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        store_id: StoreId,
        sheet_date: date,
        employee_id: EmployeeId,
        note: str,
    ) -> SheetView:
        """Sətrə kontekst qeydi ("PIN sistemi işləmirdi, şifahi təsdiq")."""
        self._require_store_access(actor, store_id)
        sheet = self._require_sheet(store_id, sheet_date)

        sheet.annotate(employee_id, note)
        self._sheets.save(sheet)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="ATTENDANCE_SHEET_ANNOTATED",
            entity_type="daily_attendance_sheets",
            entity_id=sheet.id,
            after_state={
                "employee_id": str(employee_id),
                "sheet_date": sheet_date.isoformat(),
            },
            reason=note,
        )
        return SheetView(
            sheet=sheet,
            mismatches=sheet.mismatched_lines,
            is_editable=True,
        )

    # ------------------------------- təsdiq ---------------------------------- #

    def save_draft_note(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        store_id: StoreId,
        note: str,
        sheet_date: date | None = None,
    ) -> SheetView:
        """«Qaralama Saxla» — tabelə aid ümumi qeyd, TƏSDİQ ETMƏDƏN.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ AYRICA METOD
        ──────────────────────────────────────────────────────────────────────
        `DailyRosterScreen`-də İKİ düymə var: «Tabeli Təsdiqlə» və «Qaralama
        Saxla». İkincisinin arxasında HEÇ NƏ yox idi — domendəki
        `set_manager_note()` YALNIZ `confirm()` içindən çağırıla bilirdi, yəni
        menecer qeydini saxlamaq üçün tabeli TƏSDİQLƏMƏK məcburiyyətində
        qalırdı. Təsdiq isə geri qaytarıla bilmir (`_require_open`), ona görə
        «hələ yoxlayıram, qeydimi itirməyim» halının yolu yox idi.

        Səlahiyyət `confirm`-dəki İLƏ EYNİ deyil VƏ QƏSDƏN elədir: qeyd yazmaq
        tabeli imzalamaq deyil — mağazaya girişi olan hər kəs kontekst qeydi
        qoya bilər (`annotate_line` da eyni qapıdadır). İmza isə
        `FILL_ATTENDANCE_FLAG` tələb edir.
        """
        day = sheet_date or self._clock.now().date()
        self._require_store_access(actor, store_id)

        sheet = self._require_sheet(store_id, day)
        sheet.set_manager_note(note)
        self._sheets.save(sheet)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="ATTENDANCE_SHEET_NOTE_SAVED",
            entity_type="daily_attendance_sheets",
            entity_id=sheet.id,
            after_state={"sheet_date": day.isoformat()},
            reason=sheet.manager_note,
        )
        return SheetView(
            sheet=sheet,
            mismatches=sheet.mismatched_lines,
            is_editable=not sheet.is_confirmed,
        )

    def confirm(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        store_id: StoreId,
        sheet_date: date | None = None,
        manager_note: str = "",
    ) -> SheetView:
        """Store Manager tabeli təsdiqləyir; uyğunsuzluq varsa HR-a bildiriş.

        `sheet_date` VERİLMƏYƏ BİLƏR — `open_sheet` ilə eyni defolt (`Clock`-un
        bugünü). Ekran həmişə bugünkü tabeli göstərir və tarixi ekran qatında
        yenidən hesablasaydıq, gecə yarısı keçidində GUI-nin tarixi ilə
        use case-in tarixi ayrıla bilərdi.
        """
        now = self._clock.now()
        sheet_date = sheet_date or now.date()
        self._require_store_access(actor, store_id)
        if not actor.has_permission(FILL_ATTENDANCE_FLAG, now=now):
            raise SheetPermissionError(
                f"«{FILL_ATTENDANCE_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id)},
            )

        sheet = self._require_sheet(store_id, sheet_date)
        if manager_note:
            sheet.set_manager_note(manager_note)
        sheet.confirm(manager_id=actor.id, confirmed_at=now)
        self._sheets.save(sheet)

        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="ATTENDANCE_SHEET_CONFIRMED",
            entity_type="daily_attendance_sheets",
            entity_id=sheet.id,
            after_state={
                "sheet_date": sheet_date.isoformat(),
                "line_count": len(sheet.lines),
                "mismatch_count": sheet.mismatch_count,
                "worked_count": sheet.worked_count_with(self._counting_policy(tenant_id)),
            },
            reason=sheet.manager_note,
        )

        if sheet.mismatch_count:
            # Bölmə 3: "uyğunsuzluq aşkar edilərsə HR_Admin-ə xəbərdarlıq".
            self._notifier.notify(
                tenant_id=tenant_id,
                recipient_id=None,
                category="ATTENDANCE_SHEET_MISMATCH",
                title_az="Tabel planla uyğun gəlmir",
                body_az=(
                    f"{sheet_date.isoformat()} tarixli tabeldə {sheet.mismatch_count} "
                    f"uyğunsuzluq var (plan üzrə işə çıxmalı olub, lakin qeyd yoxdur "
                    f"və ya əksinə). Araşdırma tələb oluna bilər."
                ),
                is_critical=False,
            )
            _audit_log.info(
                "ATTENDANCE_MISMATCH_REPORTED",
                extra={
                    "store_id": str(store_id),
                    "sheet_date": sheet_date.isoformat(),
                    "mismatch_count": sheet.mismatch_count,
                },
            )

        # #15 — TƏSDİQDƏN SONRA: norma üstü saatlar `overtime_log`-a yazılır.
        # Yuxarıdakı heç bir addım dəyişmədi; bu, onların üzərinə əlavədir və
        # ayrıca cədvələ toxunur (bax modul başlığı). Sıra vacibdir: aşım
        # yalnız İMZALANMIŞ tabeldən hesablanır.
        if self._overtime is not None:
            self._overtime.record_for_day(
                tenant_id=tenant_id, store_id=store_id, work_date=sheet_date
            )

        return SheetView(sheet=sheet, mismatches=sheet.mismatched_lines, is_editable=False)

    # ------------------------------- hesabat --------------------------------- #

    def worked_days_in_period(
        self,
        *,
        tenant_id: TenantId,
        store_id: StoreId,
        start: date,
        end: date,
    ) -> dict[EmployeeId, int]:
        """Dövr üzrə faktiki işlənilən gün sayı — Attendance Report üçün.

        Tabel təsdiqlənməmiş günlər DƏ sayılır: hesabat ayın 1-də çıxarılır və
        bir mağazanın bir günü təsdiqləməməsi 20 işçinin maaşını gecikdirməməlidir.

        `tenant_id` DEEP-GAP D1 ilə ƏLAVƏ OLUNDU (imza dəyişikliyi): illik
        məzuniyyətin sayıla-bilməsi Root parametridir və tenant-a görə oxunur
        (`_counting_policy`). Bu metodun `src/`-də hələ HEÇ BİR çağıranı yoxdur
        (yalnız `tests/unit/test_use_case_gap_coverage.py`) — Attendance
        Report ekranı bu funksiyanı hələ bağlamayıb, ona görə imza dəyişikliyi
        `ui`-də mövcud bir ekranı POZMUR.
        """
        policy = self._counting_policy(tenant_id)
        totals: dict[EmployeeId, int] = {}
        day = start
        while day <= end:
            sheet = self._sheets.get_for_day(store_id, day)
            if sheet is not None:
                for line in sheet.lines:
                    if line.auto_status.counts_as_worked_with(policy):
                        totals[line.employee_id] = totals.get(line.employee_id, 0) + 1
            day = date.fromordinal(day.toordinal() + 1)
        return totals

    # ------------------------------- köməkçi --------------------------------- #

    def _require_sheet(self, store_id: StoreId, sheet_date: date) -> DailyAttendanceSheet:
        sheet = self._sheets.get_for_day(store_id, sheet_date)
        if sheet is None:
            raise SheetNotFoundError(
                "Bu gün üçün tabel açılmayıb",
                context={"store_id": str(store_id), "sheet_date": sheet_date.isoformat()},
            )
        return sheet

    def _require_store_access(self, actor: Employee, store_id: StoreId) -> None:
        """Mağaza-səviyyəli scoping (bölmə 3: "yalnız öz mağazası").

        HR/CEO bütün mağazaları görür (`can_view_employee_reports`), Store
        Manager isə yalnız özününkünü. `can_see_store` mövcud entity qaydasıdır
        və burada təkrar yazılmır.
        """
        now = self._clock.now()
        if actor.has_permission(VIEW_REPORTS_FLAG, now=now):
            return
        if actor.has_permission(FILL_ATTENDANCE_FLAG, now=now) and actor.can_see_store(store_id):
            return
        raise SheetPermissionError(
            "Bu mağazanın tabelinə giriş yoxdur",
            context={"actor_id": str(actor.id), "store_id": str(store_id)},
        )


__all__ = [
    "FILL_ATTENDANCE_FLAG",
    "VIEW_REPORTS_FLAG",
    "AutoAttendanceStatus",
    "DailyAttendanceSheetUseCase",
    "SheetNotFoundError",
    "SheetPermissionError",
    "SheetView",
]
