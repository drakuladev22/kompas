"""Ekranların CANLI məlumatla doldurulması (Faza 5/6).

`preview_screens.populate()` maketdəki nümunə məzmunu yazır; bu modul eyni
işi REAL use case nəticələri ilə görür. İkisi eyni imzaya malikdir
(`populate(key, screen)`), ona görə `app.py` yalnız hansını çağıracağını
seçir — ekran fabrikaları toxunulmaz qalır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ HƏR EKRAN AYRI FUNKSİYADIR
──────────────────────────────────────────────────────────────────────────────
Hər ekranın öz setter imzası var (`set_entries`, `set_users`, `set_rows`, ...)
və onları ümumi bir interfeysə salmaq cəhdi hər ekranı süni bir adapterlə
yükləyərdi. Ayrı funksiya = ayrı imza = tip yoxlayıcısı səhvi burada tutur.

──────────────────────────────────────────────────────────────────────────────
XƏTA EKRANI BOŞ QOYUR, ÇÖKDÜRMÜR
──────────────────────────────────────────────────────────────────────────────
`populate()` hər doldurucunu `try/except` içində çağırır. Səbəb: bir ekranın
sorğusundakı problem (məs. `store_id` təyin edilməyib) BÜTÜN örtüyü
çökdürməməlidir — istifadəçi digər bölmələrdə işləməyə davam edə bilməlidir.
Səbəb `error.log`-a düşür və boş ekran özü də siqnaldır.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QWidget

    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Növbə/təqvim görünüşlərində göstərilən dövr.
MATRIX_WINDOW_DAYS = 14

#: Bu qədər dəqiqədən sonra növbə sətri xəbərdarlıq rəngində göstərilir.
#: 45 dəqiqəlik timeout-un (bölmə 4) YARISI seçilib — operator eskalasiya
#: baş verməmişdən əvvəl reaksiya verə bilsin.
LATE_QUEUE_MINUTES = 22


class ScreenDataBinder:
    """Ekran açarına görə canlı məlumat yazır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def populate(self, key: str, screen: QWidget) -> None:
        """Ekranı canlı məlumatla doldurur — naməlum açar üçün SƏSSİZ keçir."""
        binder = self._binders().get(key)
        if binder is None:
            return
        try:
            with self._context.session(user_id=self._actor.id) as session:
                binder(session, screen)
        except Exception:
            # Bax modul başlığı: bir ekranın problemi örtüyü çökdürmür.
            _error_log.exception("SCREEN_BIND_FAILED", extra={"screen": key})

    def _binders(self) -> dict[str, Callable[[Session, Any], None]]:
        return {
            "live_queue": self._live_queue,
            "fines": self._fines,
            "shift_planning": self._shift_planning,
            "shift_swaps": self._shift_swaps,
            "daily_roster": self._daily_roster,
            "fine_appeals": self._fine_appeals,
            "tasks": self._tasks,
            "users": self._users,
            "audit": self._audit,
            "reports": self._reports,
        }

    # ------------------------------ Qrup B ----------------------------------- #

    def _live_queue(self, session: Session, screen: Any) -> None:
        """Kamera Operatorunun BİRLƏŞMİŞ növbəsi (bölmə 4: giriş + qayıdış).

        İki mənbə bir siyahıda göstərilir və tip-badge ilə fərqləndirilir —
        spesifikasiya açıq şəkildə "iki ayrı tab/ekran əvəzinə" deyir.
        """
        from src.presentation.screens.group_b import QueueEntry  # noqa: PLC0415

        stores = session.uow.repository("camera_assignments").stores_for_operator(self._actor.id)
        if not stores:
            # FAIL-SAFE (bölmə 4): təyinatsız operator HEÇ NƏ görmür.
            screen.set_entries([])
            return

        # `(gözləmə dəqiqəsi, sətir)` cütü ilə yığılır: `QueueEntry` gözləməni
        # MƏTN kimi saxlayır ("18 dəq") və mətnə görə sıralamaq "9 dəq"-i
        # "18 dəq"-dən sonra qoyardı.
        pending: list[tuple[int, QueueEntry]] = []

        for record in session.uow.attendance.list_pending_verification(stores):
            waited = _minutes_since(record.requested_at)
            pending.append(
                (
                    waited,
                    QueueEntry(
                        request_id=str(record.id),
                        employee_name=_employee_name(session, record.employee_id),
                        store_name=_store_name(session, record.store_id),
                        position_name=_position_name(session, record.employee_id),
                        kind="Giriş Təsdiqi",
                        timestamp_text=_hhmm(record.requested_at),
                        waiting_text=f"{waited} dəq",
                        is_late=waited >= LATE_QUEUE_MINUTES,
                    ),
                )
            )

        for request in session.uow.leave_requests.list_pending_verification(stores):
            waited = _minutes_since(request.return_claimed_time)
            pending.append(
                (
                    waited,
                    QueueEntry(
                        request_id=str(request.id),
                        employee_name=_employee_name(session, request.employee_id),
                        store_name=_store_name(session, request.store_id),
                        position_name=_position_name(session, request.employee_id),
                        kind="Qayıdış Təsdiqi",
                        timestamp_text=_hhmm(request.requested_time),
                        waiting_text=f"{waited} dəq",
                        is_late=waited >= LATE_QUEUE_MINUTES,
                    ),
                )
            )

        # Ən çox gözləyən ƏVVƏLDƏ: operator növbəni yuxarıdan aşağı emal edir
        # və 45 dəqiqəlik timeout-a ən yaxın olan birinci görünməlidir.
        pending.sort(key=lambda item: item[0], reverse=True)
        screen.set_entries([entry for _, entry in pending])

    # ------------------------------ Qrup C ----------------------------------- #

    def _shift_planning(self, session: Session, screen: Any) -> None:
        today = date.today()  # noqa: DTZ011
        end = today + timedelta(days=MATRIX_WINDOW_DAYS)
        assignments = session.shift_planning.view_matrix(
            tenant_id=session.tenant_id,
            actor=self._actor,
            start=today,
            end=end,
        )
        rows: dict[str, dict[int, str]] = {}
        for item in assignments:
            name = _employee_name(session, item.employee_id)
            rows.setdefault(name, {})[item.shift_date.day] = "off" if item.is_off_day else "work"
        screen.set_matrix(rows)

    def _shift_swaps(self, session: Session, screen: Any) -> None:
        requests = session.shift_swaps.pending_inbox(tenant_id=session.tenant_id, actor=self._actor)
        screen.set_counts({"pending": len(requests)})
        screen.set_requests(
            [
                {
                    "employee": _employee_name(session, item.employee_id),
                    "date": item.target_date.isoformat(),
                    "reason": item.reason,
                    "status": item.status.value,
                }
                for item in requests
            ]
        )

    def _daily_roster(self, session: Session, screen: Any) -> None:
        store_id = self._actor.store_id
        if store_id is None:
            screen.set_rows([])
            return

        view = session.daily_attendance.open_sheet(
            tenant_id=session.tenant_id, actor=self._actor, store_id=store_id
        )
        session.commit()
        screen.set_rows(
            [
                {
                    "employee": _employee_name(session, line.employee_id),
                    "status": line.auto_status.label_az,
                    "note": line.manager_note or "",
                }
                for line in view.sheet.lines
            ]
        )
        if view.mismatch_count:
            screen.set_mismatch(
                f"{view.mismatch_count} sətir HR planı ilə uyğun gəlmir — nəzərdən keçirin."
            )

    def _users(self, session: Session, screen: Any) -> None:
        rows = session.uow.connection.execute(
            """
            SELECT e.first_name, e.last_name, e.is_active,
                   COALESCE(p.name_az, '—') AS role_name,
                   COALESCE(s.name, '—')    AS store_name
            FROM employees e
            LEFT JOIN positions p ON p.id = e.position_id
            LEFT JOIN stores s    ON s.id = e.store_id
            WHERE e.tenant_id = %s
            ORDER BY e.last_name, e.first_name
            LIMIT 500
            """,
            (session.tenant_id,),
        ).fetchall()
        screen.set_users(
            [
                {
                    "name": f"{row['first_name']} {row['last_name']}".strip(),
                    "role": row["role_name"],
                    "store": row["store_name"],
                    "status": "Aktiv" if row["is_active"] else "Deaktiv",
                }
                for row in rows
            ]
        )

    def _fines(self, session: Session, screen: Any) -> None:
        """Operatorun izlədiyi filiallarda BU AYIN cərimələri.

        Siyahı `fines` cədvəlindən BİRBAŞA oxunur, use case-dən yox: burada
        biznes qərarı yoxdur, sadəcə göstəriş var və `ManualFineUseCase`-də
        "mağazaya görə aylıq siyahı" metodu mövcud deyil — onu yalnız bu ekran
        üçün əlavə etmək use case-i hesabat vasitəsinə çevirərdi.
        """
        stores = session.uow.repository("camera_assignments").stores_for_operator(self._actor.id)
        if not stores:
            screen.set_fines([], period_text=_month_text(), total_text="0 ₼")
            return

        today = datetime.now(UTC).date()
        rows = session.uow.connection.execute(
            """
            SELECT f.amount, f.fine_date, f.status,
                   COALESCE(ft.name, '—') AS type_name,
                   e.first_name, e.last_name
              FROM fines f
              LEFT JOIN fine_types ft ON ft.id = f.fine_type_id
              LEFT JOIN employees  e  ON e.id = f.employee_id
             WHERE f.tenant_id = %s AND f.store_id = ANY(%s)
               AND EXTRACT(YEAR  FROM f.fine_date) = %s
               AND EXTRACT(MONTH FROM f.fine_date) = %s
             ORDER BY f.fine_date DESC
             LIMIT 200
            """,
            (session.tenant_id, list(stores), today.year, today.month),
        ).fetchall()

        total = sum(row["amount"] or 0 for row in rows)
        screen.set_fines(
            [
                {
                    "employee": _full_name(row),
                    "type": row["type_name"],
                    "date": row["fine_date"].strftime("%d.%m.%Y") if row["fine_date"] else "—",
                    "amount": f"{row['amount']} ₼",
                    "status": _FINE_STATUS_TEXT.get(str(row["status"]), str(row["status"])),
                }
                for row in rows
            ],
            period_text=_month_text(),
            total_text=f"{total} ₼",
        )

    # ------------------------------ Qrup F ----------------------------------- #

    def _fine_appeals(self, session: Session, screen: Any) -> None:
        appeals = session.fine_appeals.inbox(tenant_id=session.tenant_id, actor=self._actor)
        now = datetime.now(UTC)
        # SLA həddi ROOT Control Center-dən gəlir (bölmə 3) — burada sabit
        # 72 yazmaq Root-un dəyişdirdiyi dəyəri sükutla yan keçərdi.
        key = SystemLimitKey.FINE_APPEAL_WINDOW_HOURS
        sla_hours = session.limits.get_int(session.tenant_id, key.value, int(DEFAULT_LIMITS[key]))
        screen.set_appeals(
            [
                {
                    "employee": _employee_name(session, appeal.employee_id),
                    "reason": appeal.reason,
                    "age": f"{appeal.age_hours(now=now):.0f} saat",
                    "overdue": (
                        "Bəli" if appeal.is_overdue(now=now, sla_hours=sla_hours) else "Xeyr"
                    ),
                }
                for appeal in appeals
            ]
        )

    def _tasks(self, session: Session, screen: Any) -> None:
        awaiting = session.uow.repository("tasks").list_awaiting_review(session.tenant_id)
        overdue = session.uow.repository("tasks").list_overdue(
            session.tenant_id, now=datetime.now(UTC)
        )
        screen.set_summary(f"{len(awaiting)} təsdiq gözləyir · {len(overdue)} gecikib")
        screen.set_tasks(
            "review",
            [
                {"title": task.title, "assignee": _employee_name(session, task.assignee_id)}
                for task in awaiting
            ],
        )
        screen.set_tasks(
            "overdue",
            [
                {"title": task.title, "assignee": _employee_name(session, task.assignee_id)}
                for task in overdue
            ],
        )

    # ------------------------------ Qrup D/H --------------------------------- #

    def _audit(self, session: Session, screen: Any) -> None:
        page = session.audit_query.search(tenant_id=session.tenant_id, actor=self._actor)
        session.commit()  # baxış faktı da audit-lənir (bax `audit_query`)
        screen.set_entries(
            [
                {
                    "time": _hhmm(entry.occurred_at),
                    "actor": entry.actor_name,
                    "action": entry.action,
                    "entity": entry.entity_type,
                    "reason": entry.reason or "",
                }
                for entry in page.entries
            ]
        )

    def _reports(self, session: Session, screen: Any) -> None:
        today = date.today()  # noqa: DTZ011
        screen.set_period(f"{today:%m.%Y}")

        # Bölmə 6 LOCK MEXANİZMİ: pəncərəsi hələ açıq cərimələr bu ayın
        # export-una DÜŞMÜR — ekran bunu AÇIQ göstərməlidir.
        facts = session.report_facts.sales_facts(
            session.tenant_id,
            start=today.replace(day=1),
            end=today,
        )
        fines = session.uow.fines.list_exportable(session.tenant_id, now=datetime.now(UTC))
        selection = session.reports.build_bonus_penalty(
            actor=self._actor,
            facts=facts,
            fines=fines,
            now=datetime.now(UTC),
        )
        screen.set_lock_summary(selection.deferred_fine_count)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _employee_name(session: Session, employee_id: Any) -> str:
    """İşçi adı — tapılmazsa ID-nin qısa forması.

    Boş sətir QAYTARILMIR: ekranda adsız sətir "məlumat itib" kimi görünərdi;
    qısa ID isə heç olmasa hansı qeyd olduğunu tapmağa imkan verir.
    """
    employee = session.uow.employees.get(employee_id)
    if employee is None:
        return f"#{str(employee_id)[:8]}"
    return str(employee.full_name)


def _hhmm(moment: datetime | None) -> str:
    return f"{moment:%H:%M}" if moment is not None else "—"


#: Ay adları — `datetime.strftime("%B")` sistem lokalından asılıdır və Windows
#: maşınında ingiliscə qaytarır; interfeys dili isə YALNIZ Azərbaycancadır.
_MONTHS_AZ: Final = (
    "Yanvar",
    "Fevral",
    "Mart",
    "Aprel",
    "May",
    "İyun",
    "İyul",
    "Avqust",
    "Sentyabr",
    "Oktyabr",
    "Noyabr",
    "Dekabr",
)

#: Cərimə statusu → ekran mətni. Açarlar `FineStatus` dəyərləridir; naməlum
#: status (köhnə sətir) öz kodu ilə göstərilir, gizlədilmir.
_FINE_STATUS_TEXT: Final[dict[str, str]] = {
    "PENDING_REVIEW": "Gözləyir",
    "PUBLISHED": "Təsdiqlənib",
    "REVERSED": "Ləğv edilib",
    "REDUCED": "Azaldılıb",
}


def _month_text() -> str:
    today = datetime.now(UTC).date()
    return f"{_MONTHS_AZ[today.month - 1]} {today.year}"


def _full_name(row: Any) -> str:
    """`LEFT JOIN` NULL verə bilər — adsız sətir "—" kimi göstərilir."""
    name = f"{row['first_name'] or ''} {row['last_name'] or ''}".strip()
    return name or "—"


def _minutes_since(moment: datetime | None) -> int:
    if moment is None:
        return 0
    return max(0, int((datetime.now(UTC) - moment).total_seconds() // 60))


def _store_name(session: Session, store_id: Any) -> str:
    """Mağaza adı — çox-mağazalı operator üçün sətir nişanı (bölmə 4)."""
    row = session.uow.connection.execute(
        "SELECT name FROM stores WHERE id = %s", (store_id,)
    ).fetchone()
    return str(row["name"]) if row else "—"


def _position_name(session: Session, employee_id: Any) -> str:
    employee = session.uow.employees.get(employee_id)
    return str(employee.position.name_az) if employee is not None else "—"


__all__ = ["LATE_QUEUE_MINUTES", "MATRIX_WINDOW_DAYS", "ScreenDataBinder"]
