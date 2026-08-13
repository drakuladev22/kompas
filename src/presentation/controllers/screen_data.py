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

──────────────────────────────────────────────────────────────────────────────
BAĞLAMASI OLMAYAN AÇAR DA İZ QOYUR
──────────────────────────────────────────────────────────────────────────────
`app.py` `_binders()`-dəkindən ÇOX ekran açarı qeydiyyatdan keçirir. Əvvəl
naməlum açar sükutla keçilirdi — nə istisna, nə jurnal sətri, yəni əskik
bağlama YALNIZ istifadəçi boş ekran görəndə üzə çıxırdı. İndi həmin hal
`SCREEN_BINDER_MISSING` xəbərdarlığı verir; davranış eynidir (ekran boş
qalır, örtük çökmür), lakin qüsur ölçülə bilən hala gəlir.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from src.domain.policies import DEFAULT_LIMITS, FeatureModule, SystemLimitKey
from src.domain.value_objects.identifiers import StoreId
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QWidget

    from src.application.use_cases.multi_store_benchmark import BenchmarkMetric
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Növbə/təqvim görünüşlərində göstərilən dövr.
#:
#: FALLBACK-dır — HƏQİQİ MƏNBƏ `system_limits.SHIFT_MATRIX_WINDOW_DAYS`
#: (seed: migrations/035) və hədd hər dəfə ondan oxunur (bax
#: `matrix_window_days()`). 21 filialın planlama ritmi eyni deyil: kimisi
#: həftəlik, kimisi aylıq planlayır. Sabit YALNIZ limit oxuna bilmədikdə işə
#: düşür — onu silmək "limit yoxdursa matris də yoxdur" davranışı yaradardı.
FALLBACK_MATRIX_WINDOW_DAYS = int(DEFAULT_LIMITS[SystemLimitKey.SHIFT_MATRIX_WINDOW_DAYS])

#: Çox-Mağaza Reytinq Cədvəlinin DRILL-DOWN hədəfi (#24, Faza 9A) — mövcud
#: "Gündəlik Tabel" ekranının `AdminShell`-dəki açarı (bax `shell/menu.py`).
DAILY_ROSTER_SCREEN_KEY: Final = "daily_roster"

#: Növbə dəyişmə statusu → ekran mətni.
_SWAP_STATUS_TEXT: Final[dict[str, str]] = {
    "PENDING_APPROVAL": "Gözləyir",
    "APPROVED": "Təsdiqlənib",
    "REJECTED": "Rədd edilib",
}

#: Növbə matrisinin sütun başlıqları. `strftime("%a")` sistem lokalından
#: asılıdır və Windows-da ingiliscə qaytarır — interfeys dili isə yalnız
#: Azərbaycan dilidir (bölmə 9).
_WEEKDAYS_AZ: Final = ("B.e", "Ç.a", "Çər", "C.a", "Cüm", "Şən", "Baz")

#: Bu qədər dəqiqədən sonra növbə sətri xəbərdarlıq rəngində göstərilir.
#: 45 dəqiqəlik timeout-un (bölmə 4) YARISI seçilib — operator eskalasiya
#: baş verməmişdən əvvəl reaksiya verə bilsin.
#:
#: DİQQƏT: bu, YALNIZ FALLBACK-dır. Həqiqi mənbə
#: `system_limits.VERIFICATION_TIMEOUT_MINUTES`-dir (bölmə 3, Root idarə edir)
#: və hədd hər dəfə ondan hesablanır — bax `late_threshold_minutes()`. Sabit
#: yalnız limit oxuna bilmədikdə işə düşür; onu silmək "limit yoxdursa
#: xəbərdarlıq da yoxdur" davranışı yaradardı.
LATE_QUEUE_MINUTES = 22

#: `v_erp_server_health.health` → dashboard kartındakı ton.
#:
#: `INACTIVE` siyahıda YOXDUR, çünki həmin sətirlər sorğuda süzülür (bax
#: `_dashboard_health`). Naməlum dəyər "warning"a düşür: yeni bir sağlamlıq
#: vəziyyəti əlavə olunarsa onu SÜKUTLA yaşıl göstərmək ən pis hal olardı.
_HEALTH_TONES: Final[dict[str, str]] = {
    "HEALTHY": "success",
    "DEGRADED": "warning",
    "STALE": "warning",
    "NEVER_SYNCED": "danger",
}

#: Yardım mövzusu → onu görünən edən modul açarı (`FeatureModule` dəyəri).
#:
#: `None` = modula bağlı DEYİL. «1C / ERP bağlantısı» belədir: ERP inteqrasiyası
#: Feature Toggle ilə söndürülən bir modul deyil, quraşdırma addımıdır — onun
#: təlimatını gizlətmək serveri qura bilməyən müştərini məhz lazım olan anda
#: köməksiz qoyardı. «Problem yaşayırsınızsa» mövzusu isə `SUPPORT_CHAT`-a
#: bağlıdır, çünki mətnin özü dəstək düyməsini göstərir.
HELP_TOPIC_MODULES: Final[dict[str, str | None]] = {
    "leave": FeatureModule.CAMERA_VERIFICATION.value,
    "fines": FeatureModule.FINE_MODULE.value,
    "shifts": FeatureModule.SHIFT_SWAP.value,
    "erp": None,
    "points": FeatureModule.SALES_POINTS.value,
    "support": FeatureModule.SUPPORT_CHAT.value,
}


class ScreenDataBinder:
    """Ekran açarına görə canlı məlumat yazır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def populate(self, key: str, screen: QWidget) -> None:
        """Ekranı canlı məlumatla doldurur — bağlaması olmayan açar İZ QOYUR."""
        binder = self._binders().get(key)
        if binder is None:
            # DAVRANIŞ DƏYİŞMİR: ekran boş qalır, istisna atılmır, örtük
            # çökmür — `app.py` 28 ekran açarını qeydiyyatdan keçirir, onların
            # bir hissəsinin canlı bağlaması hələ yazılmayıb və bu, planlı
            # vəziyyətdir (bax `tests/unit/test_screen_binding_coverage.py`).
            # DƏYİŞƏN YALNIZ GÖRÜNÜRLÜKDÜR: əvvəl bu hal heç bir iz qoymurdu,
            # yəni əskik bağlama yalnız istifadəçi boş ekran görəndə üzə
            # çıxırdı. `warning` seçilib, `exception` yox — burada tutulmuş
            # xəta yoxdur, tamamlanmamış bağlama var; `raise` isə qadağandır,
            # çünki menyuda görünən ekran açılmalıdır (məzmunsuz da olsa).
            _error_log.warning(
                "SCREEN_BINDER_MISSING",
                extra={
                    "screen": key,
                    "impact": "ekran boş qalır — canlı bağlama hələ yazılmayıb",
                },
            )
            return
        try:
            with self._context.session(user_id=self._actor.id) as session:
                binder(session, screen)
        except Exception:
            # Bax modul başlığı: bir ekranın problemi örtüyü çökdürmür.
            _error_log.exception("SCREEN_BIND_FAILED", extra={"screen": key})

    def _binders(self) -> dict[str, Callable[[Session, Any], None]]:
        return {
            "dashboard": self._dashboard,
            "live_queue": self._live_queue,
            "fines": self._fines,
            "shift_planning": self._shift_planning,
            "shift_swaps": self._shift_swaps,
            "daily_roster": self._daily_roster,
            "fine_appeals": self._fine_appeals,
            "tasks": self._tasks,
            "sales_points": self._sales_points,
            "users": self._users,
            "audit": self._audit,
            "reports": self._reports,
            "help": self._help,
            "health": self._health,
        }

    # ------------------------------ Qrup C ----------------------------------- #

    def _dashboard(self, session: Session, screen: Any) -> None:
        """Admin / CEO İdarə Paneli — beş bölmə, hamısı AQREQASİYA.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ USE CASE DEYİL, BİRBAŞA SQL
        ──────────────────────────────────────────────────────────────────────
        Burada heç bir iş qərarı verilmir: nə status keçidi, nə səlahiyyət
        yoxlaması, nə hesablama qaydası var — yalnız SAYĞAC göstərilir. Eyni
        səbəb `_fines`-də də yazılıb: use case-ə "dashboard üçün say" metodu
        əlavə etmək onu göstəriş vasitəsinə çevirərdi.

        Rəqəmlərin MƏNASI isə mövcud qaydalardan gəlir və burada YENİDƏN
        təyin edilmir: `VERIFIED` = mağazadadır (bölmə 4 STEP C),
        `PENDING_VERIFICATION` + `PENDING_RETURN_VERIFICATION` = operatorun
        birləşmiş növbəsi (`_live_queue` ilə eyni iki mənbə), `OPEN` +
        `EVIDENCE_SUBMITTED` = açıq tapşırıq (`_tasks` ilə eyni dəst).
        """
        today = datetime.now(UTC).date()
        month_start = today.replace(day=1)
        next_month = _next_month(month_start)
        previous_month = _previous_month(month_start)

        totals = _fine_month_totals(
            session,
            month_start=month_start,
            next_month=next_month,
            previous_month=previous_month,
        )
        self._dashboard_summary(session, screen, today=today, fine_totals=totals)
        self._dashboard_fines(session, screen, month_start=month_start, next_month=next_month)
        self._dashboard_leave(session, screen, month_start=month_start, next_month=next_month)
        self._dashboard_leaders(session, screen, today=today)
        self._dashboard_health(session, screen)
        self._dashboard_benchmark(session, screen)

    def _dashboard_summary(
        self, session: Session, screen: Any, *, today: date, fine_totals: tuple[str, str]
    ) -> None:
        """Dörd rəqəm kartı — bir sorğu, səkkiz sayğac."""
        row = session.uow.connection.execute(
            """
            SELECT
              (SELECT count(*) FROM attendance_records
                WHERE tenant_id = %s AND work_date = %s
                  AND check_in_status = 'VERIFIED')                     AS in_store,
              (SELECT count(*) FROM shift_assignments
                WHERE tenant_id = %s AND shift_date = %s
                  AND NOT is_off_day)                                   AS planned,
              (SELECT count(*) FROM attendance_records
                WHERE tenant_id = %s AND work_date = %s
                  AND check_in_status = 'PENDING_VERIFICATION')         AS pending_entry,
              (SELECT count(*) FROM leave_requests
                WHERE tenant_id = %s
                  AND status = 'PENDING_RETURN_VERIFICATION')           AS pending_return,
              (SELECT min(requested_at) FROM attendance_records
                WHERE tenant_id = %s AND work_date = %s
                  AND check_in_status = 'PENDING_VERIFICATION')         AS oldest_entry,
              (SELECT min(return_claimed_time) FROM leave_requests
                WHERE tenant_id = %s
                  AND status = 'PENDING_RETURN_VERIFICATION')           AS oldest_return,
              (SELECT count(*) FROM tasks
                WHERE tenant_id = %s
                  AND status IN ('OPEN', 'EVIDENCE_SUBMITTED'))         AS open_tasks,
              (SELECT count(*) FROM tasks
                WHERE tenant_id = %s AND deadline < now()
                  AND status IN ('OPEN', 'EVIDENCE_SUBMITTED'))         AS overdue_tasks
            """,
            (
                session.tenant_id,
                today,
                session.tenant_id,
                today,
                session.tenant_id,
                today,
                session.tenant_id,
                session.tenant_id,
                today,
                session.tenant_id,
                session.tenant_id,
                session.tenant_id,
            ),
        ).fetchone()
        counts = row or {}

        # Ən uzun gözləmə İKİ mənbədən ən KÖHNƏSİDİR — növbə birləşmişdir
        # (bölmə 4), ona görə "ən uzunu" da birləşmiş dəstə aid olmalıdır.
        oldest = _earliest(counts.get("oldest_entry"), counts.get("oldest_return"))
        pending = int(counts.get("pending_entry") or 0) + int(counts.get("pending_return") or 0)

        screen.set_summary(
            in_store=int(counts.get("in_store") or 0),
            planned=int(counts.get("planned") or 0),
            pending=pending,
            longest_wait=f"{_minutes_since(oldest)} dəq" if oldest is not None else "—",
            fines_total=fine_totals[0],
            fines_delta=fine_totals[1],
            open_tasks=int(counts.get("open_tasks") or 0),
            overdue_tasks=int(counts.get("overdue_tasks") or 0),
        )

    def _dashboard_fines(
        self, session: Session, screen: Any, *, month_start: date, next_month: date
    ) -> None:
        """Filial üzrə cərimə sütunları — bu ayın BÜTÜN statusları.

        `PENDING_REVIEW` sətirlər DƏ daxildir və bu, qəsdəndir: dashboard
        idarəetmə göstəricisidir, hesabat ixracı deyil. Bölmə 6-nın LOCK
        mexanizmi yalnız EXPORT-a aiddir (`_reports`) — ayın ortasında
        "cərimə yoxdur" göstərmək menecerə yanlış mənzərə verərdi.
        """
        rows = session.uow.connection.execute(
            """
            SELECT COALESCE(s.name, '—') AS store_name,
                   COALESCE(SUM(f.amount), 0) AS total
              FROM fines f
              LEFT JOIN stores s ON s.id = f.store_id
             WHERE f.tenant_id = %s AND f.fine_date >= %s AND f.fine_date < %s
             GROUP BY s.name
             ORDER BY total DESC
             LIMIT 12
            """,
            (session.tenant_id, month_start, next_month),
        ).fetchall()
        screen.set_fines_by_branch(
            [
                (str(row["store_name"]), float(row["total"] or 0), f"{row['total'] or 0} ₼")
                for row in rows
            ],
            period=_month_text(),
        )

    def _dashboard_leave(
        self, session: Session, screen: Any, *, month_start: date, next_month: date
    ) -> None:
        """İcazə ölçəni — istifadə / tenant büdcəsi.

        Büdcə = `MONTHLY_LEAVE_MINUTES_LIMIT` × aktiv işçi sayı. Limit
        SPESİFİKASİYADA işçi başınadır (bölmə 3) və burada YENİDƏN təyin
        edilmir — sadəcə eyni limit tenant miqyasına vurulur ki, ölçən
        nisbəti göstərə bilsin. Qayda (240 dəq aşıldıqda XƏBƏRDARLIQ, bloklama
        YOX) `MonthlyLeaveUsage`-də qalır; bu ölçən heç nə bloklamır.
        """
        key = SystemLimitKey.MONTHLY_LEAVE_MINUTES_LIMIT
        per_employee = session.limits.get_int(
            session.tenant_id, key.value, int(DEFAULT_LIMITS[key])
        )
        row = session.uow.connection.execute(
            """
            SELECT
              (SELECT COALESCE(SUM(total_minutes), 0) FROM leave_requests
                WHERE tenant_id = %s AND requested_time >= %s
                  AND requested_time < %s)              AS used_minutes,
              (SELECT count(*) FROM employees
                WHERE tenant_id = %s AND is_active)     AS active_employees
            """,
            (session.tenant_id, month_start, next_month, session.tenant_id),
        ).fetchone()
        used = float((row or {}).get("used_minutes") or 0)
        headcount = int((row or {}).get("active_employees") or 0)
        screen.set_leave_usage(used, float(per_employee * headcount))

    def _dashboard_leaders(self, session: Session, screen: Any, *, today: date) -> None:
        """Xal liderləri — CARİ 6 aylıq dövr (`PointsPeriod`, bölmə 6).

        Dövr sərhədi domendən götürülür, "son 30 gün" kimi bir kəsim
        uydurulmur: xallar 1 Yanvar / 1 İyul-da sıfırlanır və liderlik
        lövhəsi sıfırlanmadan SONRA köhnə dövrün adlarını göstərməməlidir.
        """
        from src.domain.value_objects.gamification import PointsPeriod  # noqa: PLC0415

        period = PointsPeriod.containing(today)
        rows = session.uow.connection.execute(
            """
            SELECT e.first_name, e.last_name, SUM(l.delta_points) AS total
              FROM points_ledger l
              JOIN employees e ON e.id = l.employee_id
             WHERE l.tenant_id = %s AND l.period_start = %s AND l.status <> 'REVERSED'
             GROUP BY e.first_name, e.last_name
             HAVING SUM(l.delta_points) > 0
             ORDER BY total DESC
             LIMIT 5
            """,
            (session.tenant_id, period.start),
        ).fetchall()
        screen.set_leaders([(_full_name(row), _points_text(row["total"])) for row in rows])

    def _dashboard_health(self, session: Session, screen: Any) -> None:
        """1C serverlərinin vəziyyəti — `v_erp_server_health` görünüşündən.

        `INACTIVE` sətirlər GÖSTƏRİLMİR: `ServerHealth.needs_attention` onları
        qəsdən kənarda saxlayır — deaktivləşdirmə adminin QƏRARIDIR, nasazlıq
        deyil. Onları daimi sarı ilə göstərmək kartı "həmişə xəbərdarlıq"
        halına salar və REAL problem itərdi. Tam siyahı «Sistem Sağlamlığı»
        ekranındadır.
        """
        rows = session.uow.connection.execute(
            """
            SELECT server_name, health, sync_delay_seconds
              FROM v_erp_server_health
             WHERE tenant_id = %s AND health <> 'INACTIVE'
             ORDER BY server_name
             LIMIT 8
            """,
            # `tenant_id` şərti RLS-ə ƏLAVƏ ikinci qatdır (CLAUDE.md bölmə 6):
            # görünüş `security_invoker` ilə işləyir, lakin bir konfiqurasiya
            # səhvi bütün tenant-ların serverlərini bir dashboard-a tökərdi.
            (session.tenant_id,),
        ).fetchall()
        screen.set_server_health(
            [
                (
                    str(row["server_name"]),
                    _sync_delay_text(row["sync_delay_seconds"]),
                    _HEALTH_TONES.get(str(row["health"]), "warning"),
                )
                for row in rows
            ]
        )

    def _dashboard_benchmark(self, session: Session, screen: Any) -> None:
        """#24 Çox-Mağaza Benchmark — dörd yeni widget, YALNIZ `can_export_reports`.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ MAĞAZA_MENECERI ÜÇÜN "ERKƏN RETURN" KİFAYƏTDİR
        ──────────────────────────────────────────────────────────────────────
        `MultiStoreBenchmarkUseCase`-in ÖZÜ də bu flag-i tələb edir (ikinci
        qat, use case modul başlığı) — burdakı yoxlama əlavə səlahiyyət
        QAYDASI DEYİL, sadəcə lazımsız sorğunun qarşısını alan QISA-DÖVRƏDİR:
        flag yoxdursa `set_*` heç çağırılmır, ekranın dörd bölməsi (bax
        `group_c.DashboardScreen` sinif başlığı) defolt GİZLİ qalır.
        """
        from src.application.use_cases.multi_store_benchmark import (  # noqa: PLC0415
            VIEW_BENCHMARK_FLAG,
            BenchmarkMetric,
        )

        now = datetime.now(UTC)
        if not self._actor.has_permission(VIEW_BENCHMARK_FLAG, now=now):
            return
        # İLK açılışdakı defolt metrik — dropdown dəyişəndə `refresh_dashboard_
        # benchmark` YENİ metriklə TƏKRAR çağırır (bax o metodun başlığı).
        self._populate_benchmark_sections(session, screen, metric=BenchmarkMetric.FINE_COUNT)

    def refresh_dashboard_benchmark(self, screen: Any, *, metric_key: str) -> None:
        """Reytinq dropdown-u dəyişəndə dörd bölməni YENİ metriklə yeniləyir.

        Kontroller sessiyanı SAXLAMIR (CLAUDE.md bölmə 6) — hər dəyişiklik
        ÖZ sessiyasını açır, `_dashboard`-ın ilkin populate çağırışından
        MÜSTƏQİLDİR.
        """
        from src.application.use_cases.multi_store_benchmark import (  # noqa: PLC0415
            VIEW_BENCHMARK_FLAG,
            BenchmarkMetric,
        )

        now = datetime.now(UTC)
        if not self._actor.has_permission(VIEW_BENCHMARK_FLAG, now=now):
            return
        try:
            metric = BenchmarkMetric(metric_key)
        except ValueError:
            _error_log.warning("BENCHMARK_UNKNOWN_METRIC", extra={"metric_key": metric_key})
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                self._populate_benchmark_sections(session, screen, metric=metric)
        except Exception:
            _error_log.exception("BENCHMARK_REFRESH_FAILED", extra={"metric_key": metric_key})

    def _populate_benchmark_sections(
        self, session: Session, screen: Any, *, metric: BenchmarkMetric
    ) -> None:
        """Dörd bölmənin ORTAQ doldurma məntiqi (`_dashboard_benchmark` +
        `refresh_dashboard_benchmark` EYNİ kodu paylaşır)."""
        from src.application.use_cases.multi_store_benchmark import (  # noqa: PLC0415
            BenchmarkMetric,
            format_metric_value,
        )
        from src.presentation.screens.group_c import RankingEntry  # noqa: PLC0415

        metric_options = [(item.value, item.label_az) for item in BenchmarkMetric]

        rows = session.multi_store_benchmark.ranking(
            tenant_id=session.tenant_id, actor=self._actor, metric=metric
        )
        screen.set_ranking_table(
            [
                RankingEntry(
                    store_id=str(row.store_id),
                    store_name=row.store_name,
                    value_display=row.display_value,
                    trend_arrow=row.trend.arrow,
                    trend_label=row.trend.label_az,
                )
                for row in rows
            ],
            metric_options=metric_options,
            selected_metric=metric.value,
        )

        if rows:
            # Defolt müqayisə ƏN YAXŞI sıralanan mağaza üçündür — istifadəçi
            # sətrə klikləyəndə (drill-down) fərqli bir kontekstə keçir,
            # bura toxunmur (bax `AdminShell.screen_for` şərhi).
            comparison = session.multi_store_benchmark.store_vs_network(
                tenant_id=session.tenant_id,
                actor=self._actor,
                metric=metric,
                store_id=rows[0].store_id,
            )
            screen.set_store_vs_network(
                metric_label=metric.label_az,
                store_label=comparison.store_name,
                store_value=comparison.store_value or 0.0,
                store_display=format_metric_value(comparison.store_value, metric),
                network_label="Şəbəkə ortalaması",
                network_value=comparison.network_average or 0.0,
                network_display=format_metric_value(comparison.network_average, metric),
            )

        trend_points = session.multi_store_benchmark.trend(
            tenant_id=session.tenant_id, actor=self._actor, metric=metric
        )
        screen.set_metric_trend(
            metric_label=metric.label_az,
            points=[
                (point.period_label, point.value or 0.0, format_metric_value(point.value, metric))
                for point in trend_points
            ],
        )

        outliers = session.multi_store_benchmark.outliers(
            tenant_id=session.tenant_id, actor=self._actor, metric=metric
        )
        screen.set_outliers(
            summary_text=outliers.summary_text_az,
            rows=[
                (
                    outlier.store_name,
                    f"{outlier.deviation_sigma:.1f}σ "
                    f"{'yuxarı' if outlier.above_average else 'aşağı'}",
                )
                for outlier in outliers.outliers
            ],
        )

    def populate_daily_roster_for_store(self, store_id: StoreId, screen: Any) -> None:
        """Reytinq Cədvəlindəki DRILL-DOWN-un yazı yolu (#24, Faza 9A).

        `_daily_roster`-dən FƏRQİ: o, aktorun ÖZ mağazasını göstərir (Store
        Manager-in gündəlik işi). Bura İSƏ Root/CEO/Admin/HR_Admin-in
        REYTİNQDƏ kliklədiyi İSTƏNİLƏN mağazanı açır — `DailyAttendanceSheet
        UseCase.open_sheet` bunu ARTIQ dəstəkləyir (`store_id` sərbəst
        arqumentdir, `_require_store_access` `can_view_employee_reports`
        sahibini istənilən mağazaya buraxır), ona görə YENİ use case metodu
        YOX, sadəcə bu kontroller bir yeni AÇAR yolu əlavə edir.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                view = session.daily_attendance.open_sheet(
                    tenant_id=session.tenant_id, actor=self._actor, store_id=store_id
                )
                session.commit()
                rows = [
                    {
                        "employee": _employee_name(session, line.employee_id),
                        "status": line.auto_status.label_az,
                        "note": line.manager_note or "",
                    }
                    for line in view.sheet.lines
                ]
        except Exception:
            _error_log.exception(
                "BENCHMARK_DRILL_DOWN_ROSTER_FAILED", extra={"store_id": str(store_id)}
            )
            return

        screen.set_rows(rows)
        if view.mismatch_count:
            screen.set_mismatch(
                f"{view.mismatch_count} sətir HR planı ilə uyğun gəlmir — nəzərdən keçirin."
            )

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

        # Xəbərdarlıq həddi CANLI limitdən hesablanır: Root timeout-u 45-dən
        # 20 dəqiqəyə endirsə, sabit 22 ilə operator xəbərdarlığı ESKALASİYADAN
        # SONRA görərdi — yəni siqnal öz mənasını itirərdi (bax
        # `late_threshold_minutes` və `LATE_QUEUE_MINUTES` şərhi).
        late_after = late_threshold_minutes(session)

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
                        is_late=waited >= late_after,
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
                        is_late=waited >= late_after,
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
        window_days = matrix_window_days(session)
        end = today + timedelta(days=window_days)
        assignments = session.shift_planning.view_matrix(
            tenant_id=session.tenant_id,
            actor=self._actor,
            start=today,
            end=end,
        )
        # `set_matrix(days, rows)` İKİ arqument gözləyir: sütun başlıqları və
        # sətirlər. Əvvəl bura tək `dict` ötürülürdü — `TypeError` `populate()`
        # tərəfindən udulurdu və matris canlı rejimdə HƏMİŞƏ boş qalırdı.
        window = [today + timedelta(days=offset) for offset in range(window_days)]
        days = [(day.day, _WEEKDAYS_AZ[day.weekday()]) for day in window]

        by_employee: dict[str, dict[date, str]] = {}
        for item in assignments:
            name = _employee_name(session, item.employee_id)
            by_employee.setdefault(name, {})[item.shift_date] = "off" if item.is_off_day else "work"

        rows = [
            (name, [marks.get(day, "") for day in window])
            for name, marks in sorted(by_employee.items())
        ]
        screen.set_matrix(days, rows)
        self._shift_staffing_pattern(session, screen)

    def _shift_staffing_pattern(self, session: Session, screen: Any) -> None:
        """#13 — Növbə Matrisinin QEYRİ-MƏCBURİ tarixi nümunə kartı.

        MAĞAZA SEÇİMİ: aktorun öz filialı, o yoxdursa (Root/CEO şəbəkə
        səviyyəsindədir) əlifba üzrə İLK aktiv mağaza. Rəqəmlərin hansı
        mağazaya aid olduğu kartın başlığında YAZILIR — əks halda 21 filiallı
        şəbəkədə göstərici mənasız olardı.

        MÜŞAHİDƏSİZ HAL SÜKUTLA KEÇİLMİR: mağaza tapılmasa da kart "tarixçə
        yoxdur" mətni ilə göstərilir (bax `set_staffing_pattern` docstring-i).
        """
        store_id, store_name = _default_store(session, self._actor)
        suggestions = (
            []
            if store_id is None
            else session.staffing_pattern.suggestions_for(session.tenant_id, store_id=store_id)
        )
        based_on_weeks = (
            suggestions[0].based_on_weeks
            if suggestions
            else int(DEFAULT_LIMITS[SystemLimitKey.STAFFING_PATTERN_BASED_ON_WEEKS])
        )
        calculated = (
            f"hesablandı: {suggestions[0].calculated_at.strftime('%d.%m.%Y')}"
            if suggestions
            else "hələ hesablanmayıb"
        )
        screen.set_staffing_pattern(
            [
                (suggestion.weekday_label_az, suggestion.headcount_label_az())
                for suggestion in suggestions
            ],
            store_name=store_name,
            based_on_weeks=based_on_weeks,
            calculated_label=calculated,
        )

    def _shift_swaps(self, session: Session, screen: Any) -> None:
        requests = session.shift_swaps.pending_inbox(tenant_id=session.tenant_id, actor=self._actor)
        screen.set_counts({"pending": len(requests)})
        # Açarlar ekranın FAKTİKİ gözlədikləridir: `id`, `from_name`, `to_name`,
        # `shift`, `store`, `status`, `note`. Əvvəl `employee`/`date` göndərilirdi
        # və kart `KeyError` ilə çökürdü — `populate()` isə istisnanı udurdu,
        # ona görə Növbə Dəyişmə inbox-u canlı rejimdə HƏMİŞƏ boş idi.
        screen.set_requests(
            [
                {
                    "id": str(item.id),
                    "from_name": _employee_name(session, item.employee_id),
                    # Sorğuda hədəf işçi YOXDUR — spesifikasiya (sətir 106)
                    # yalnız "istədiyi tarix + səbəb" deyir; qərarı HR verir.
                    "to_name": item.target_date.strftime("%d.%m.%Y"),
                    "shift": item.target_date.strftime("%d.%m.%Y"),
                    "store": _store_name(session, item.store_id) if item.store_id else "—",
                    "status": _SWAP_STATUS_TEXT.get(item.status.value, item.status.value),
                    "note": item.reason,
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
            SELECT e.first_name, e.last_name, e.username, e.is_active,
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
                    # Açarlar ekranın FAKTİKİ gözlədikləridir (`user["full_name"]`,
                    # `user["username"]`) — əvvəl `name` göndərilirdi və sətir
                    # `KeyError` ilə çökürdü, istisna isə udulurdu.
                    "full_name": f"{row['first_name']} {row['last_name']}".strip(),
                    "username": row["username"],
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
        # SLA həddi ROOT İdarə Mərkəzindən gəlir (bölmə 3) — burada sabit
        # 72 yazmaq Root-un dəyişdirdiyi dəyəri sükutla yan keçərdi.
        key = SystemLimitKey.FINE_APPEAL_WINDOW_HOURS
        sla_hours = session.limits.get_int(session.tenant_id, key.value, int(DEFAULT_LIMITS[key]))
        # Açarlar `FineAppealInboxScreen`-in FAKTİKİ oxuduqlarıdır: `id`,
        # `employee`, `fine_type`, `amount`, `meta`, `explanation`. Əvvəl
        # `reason`/`age`/`overdue` göndərilirdi — kartlar boş sahələrlə
        # qurulurdu və `[Qəbul Et]` düyməsi BOŞ `id` yayırdı, yəni qərar
        # heç bir etiraza aid olmurdu.
        screen.set_appeals(
            [
                {
                    "id": str(appeal.id),
                    "employee": _employee_name(session, appeal.employee_id),
                    "fine_type": _fine_type_name(session, appeal.fine_id),
                    "amount": _fine_amount(session, appeal.fine_id),
                    "meta": (
                        f"{appeal.age_hours(now=now):.0f} saatdır gözləyir"
                        + (
                            " · SLA aşılıb"
                            if appeal.is_overdue(now=now, sla_hours=sla_hours)
                            else ""
                        )
                    ),
                    "explanation": appeal.reason,
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
        # Sütun açarları `TasksScreen._COLUMNS`-dandır: `open`/`review`/`done`.
        # Əvvəl "overdue" göndərilirdi — belə sütun YOXDUR və `KeyError`
        # udulurdu. Gecikmiş tapşırıq hələ AÇIQ tapşırıqdır; neçəsinin
        # gecikdiyi yuxarıdakı xülasə sətrindədir.
        screen.set_tasks(
            "open",
            [
                {"title": task.title, "assignee": _employee_name(session, task.assignee_id)}
                for task in overdue
            ],
        )

    def _sales_points(self, session: Session, screen: Any) -> None:
        """Satış Xalları — İŞÇİNİN ÖZ balansı, tarixçəsi və kataloqu (bölmə 6).

        ──────────────────────────────────────────────────────────────────────
        SƏLAHİYYƏT DEYİL, SAHİBLİK
        ──────────────────────────────────────────────────────────────────────
        `SalesPointsUseCase.balance_for` səlahiyyət TƏLƏB ETMİR: işçinin öz
        balansına baxması onun hüququdur (bax use case başlığı). Ona görə
        burada `self._actor.id` işlədilir və "başqasının balansı" yolu
        ÜMUMİYYƏTLƏ yoxdur — kimin baxdığı sualı struktur olaraq bağlanıb.

        YAZI yolu (`appeal_requested`, `reward_requested`) burada QOŞULMUR:
        onlar `points_ledger`-ə yazır və hər yazıdan sonra siyahı yenidən
        oxunmalıdır, yəni öz kontrollerini tələb edir (CLAUDE.md bölmə 6).
        """
        balance = session.sales_points.balance_for(self._actor.id, tenant_id=session.tenant_id)
        available = int(balance.available)

        catalog = [
            item
            for _reward_id, item in session.sales_points.list_rewards_for_employee(
                session.tenant_id
            )
        ]
        # "Növbəti mükafat" = balansı hələ ÇATMAYAN ən ucuz mükafat. Hamısı
        # əlçatandırsa ən BAHALI götürülür ki, ölçən 100%-də dolu görünsün —
        # sıfır dəyər ölçəni "hədəf yoxdur" halında bölmə xətasına salardı.
        out_of_reach = sorted(item.cost_points for item in catalog if item.cost_points > available)
        next_cost = (
            out_of_reach[0]
            if out_of_reach
            else max((item.cost_points for item in catalog), default=0)
        )
        screen.set_balance(
            available,
            monthly_delta=_monthly_points_delta(session, self._actor.id),
            to_next_reward=max(0, next_cost - available),
            next_reward_cost=next_cost,
            rank_text=_points_rank_text(session, self._actor.id, period_start=balance.period.start),
        )

        # Tarixçə `points_ledger`-dən BİRBAŞA oxunur: `PointsEntry` aqreqatı
        # `reason` MƏTNİNİ daşımır (o, yalnız "nə qədər xal qüvvədədir"
        # sualına cavab verir), ekran isə səbəb sütunu göstərir.
        rows = session.uow.connection.execute(
            """
            SELECT l.created_at, l.delta_points, l.reason, l.status,
                   a.status AS appeal_status
              FROM points_ledger l
              LEFT JOIN points_appeals a ON a.ledger_id = l.id
             WHERE l.tenant_id = %s AND l.employee_id = %s AND l.period_start = %s
             ORDER BY l.created_at DESC
             LIMIT 100
            """,
            (session.tenant_id, self._actor.id, balance.period.start),
        ).fetchall()
        screen.set_history(
            [
                {
                    "date": f"{row['created_at']:%d.%m}" if row["created_at"] else "—",
                    "reason": str(row["reason"] or "—"),
                    "status": _points_status_text(row),
                    "points": _points_text(row["delta_points"], reversed_=_is_reversed(row)),
                }
                for row in rows
            ],
            # `period=` — `SalesPointsScreen.set_history`-nin FAKTİKİ açar
            # adıdır (`_fines`-dəki `period_text=` BAŞQA ekrandır). Səhv ad
            # `TypeError` verərdi və `populate()` onu udardı: tarixçə canlı
            # rejimdə həmişə boş qalardı.
            period=_month_text(),
        )
        screen.set_catalog(
            [{"name": item.name, "cost": str(item.cost_points)} for item in catalog],
            balance=available,
        )

    # ------------------------------ Qrup D/H --------------------------------- #

    def _help(self, session: Session, screen: Any) -> None:
        """Yardım Mərkəzi — mövzular GÖRÜNƏN modullara görə süzülür.

        ──────────────────────────────────────────────────────────────────────
        AÇARLAR TOGGLE CƏDVƏLİ İLƏ EYNİDİR
        ──────────────────────────────────────────────────────────────────────
        Süzgəc `FeatureModule` dəyərləri üzərində işləyir — `feature_toggles`
        cədvəlinin və `shell/menu.py`-ın işlətdiyi EYNİ açarlar. Burada öz ad
        məkanımızı qursaydıq (məs. `"fines"` ↔ `"FINE_MODULE"`), uyğunsuzluq
        maketdə görünməz qalar və yalnız istehsalatda üzə çıxardı — layihədə
        məhz bu qüsur olub (bax `menu.py` başlığı).

        Toggle mənbəyi oxunmasa BÜTÜN mövzular göstərilir (fail-open): yardım
        mətnini gizlətmək dəstək yükünü artırar, azaltmaz (bax
        `HelpCenterScreen` başlığı) — bu, naviqasiyadakı `_enabled_modules`
        ilə eyni istiqamətdir.
        """
        try:
            enabled = frozenset(session.toggles.enabled_modules(session.tenant_id))
        except Exception:
            _error_log.exception("HELP_TOGGLES_LOAD_FAILED")
            screen.set_visible_topics(None)
            return

        screen.set_visible_topics(
            frozenset(
                topic
                for topic, module in HELP_TOPIC_MODULES.items()
                if module is None or module in enabled
            )
        )

    def _health(self, session: Session, screen: Any) -> None:
        """Sistem Sağlamlığı — YALNIZ FAKTİKİ ölçülən göstəricilər (bölmə 6).

        ──────────────────────────────────────────────────────────────────────
        YENİ İŞ QAYDASI İCAD EDİLMİR
        ──────────────────────────────────────────────────────────────────────
        Bu ekranın öz use case-i YOXDUR və olmamalıdır: burada heç bir qərar
        verilmir, mövcud mənbələr bir yerə yığılır — baza cavab müddəti,
        `NtpVerifier` sürüşməsi, offline bufer sayğacı, `sync_conflicts` və
        `v_erp_server_health`. Hər rəqəmin arxasında REAL ölçmə var.

        ──────────────────────────────────────────────────────────────────────
        ÖLÇÜLƏ BİLMƏYƏN GÖSTƏRİCİ GÖSTƏRİLMİR
        ──────────────────────────────────────────────────────────────────────
        Maketdə «Disk (server)» kartı var, lakin tətbiqdə server diskini
        ölçən mənbə YOXDUR. Onu `0%` və ya "naməlum" ilə göstərmək monitorinq
        ekranının ƏSAS məqsədini pozardı: burada göstərilən hər rəqəm etibarlı
        olmalıdır. NTP sürüşməsi də ölçülməyibsə (`_NullNtp`) kart
        ÜMUMİYYƏTLƏ qurulmur — `0.0 san` "saat dəqiqdir" kimi oxunardı.
        """
        screen.set_last_check(f"Son yoxlama: {_hhmm(datetime.now(UTC))}")
        screen.set_metrics(_health_metrics(session, self._context))
        screen.set_latencies(_health_latencies(session))
        screen.set_alerts(_health_alerts(session, self._actor))

    def _audit(self, session: Session, screen: Any) -> None:
        page = session.audit_query.search(tenant_id=session.tenant_id, actor=self._actor)
        session.commit()  # baxış faktı da audit-lənir (bax `audit_query`)
        # `result_text` MƏCBURİ açar-arqumentdir — onsuz `TypeError` atılırdı
        # və audit ekranı canlı rejimdə boş qalırdı (istisna udulurdu).
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
            ],
            result_text=f"{len(page.entries)} nəticə",
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


def perform_ranking_drill_down(
    store_id_text: str,
    *,
    show_screen: Callable[[str], bool],
    screen_for: Callable[[str], Any | None],
    populate: Callable[[StoreId, Any], None],
) -> bool:
    """Reytinq Cədvəlinin DRILL-DOWN qərarı — SAF funksiya, Qt TƏLƏB ETMİR.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ `app.py`-DAN ÇIXARILIB
    ──────────────────────────────────────────────────────────────────────────
    Naviqasiya qərarının ÖZÜ ("hansı açar, hansı sıra ilə") biznes məntiqidir
    və `QApplication` tələb etməməlidir. `app.py`-dakı `_on_ranking_row_
    selected` bu funksiyanı `AdminShell.show_screen`/`screen_for` və
    `ScreenDataBinder.populate_daily_roster_for_store`-u birbaşa ötürərək
    çağırır — YENİ naviqasiya qatı YOXDUR, sadəcə MÖVCUD üç collaborator
    (bax arqumentlər) bir yerdə çağırılır.

    Args:
        store_id_text: Klik edilən sətrin mağaza ID-si (mətn, `RankingEntry.
            store_id`).
        show_screen: `AdminShell.show_screen` — mövcud ekrana keçid.
        screen_for: `AdminShell.screen_for` — keçiddən SONRA instansiyanı tapır.
        populate: `ScreenDataBinder.populate_daily_roster_for_store` — həmin
            instansiyanı KLİKLƏNƏN mağaza ilə doldurur.

    Returns:
        Bütün addımlar uğurlu olduqda `True`. Yararsız ID, gizli ekran və ya
        hələ qurulmamış instansiya SƏSSİZCƏ `False` qaytarır — çağıran tərəf
        bunu jurnala yaza bilər, lakin bu funksiya İSTİSNA ATMIR (klik hadisə
        idarəedicisidir, çökmə istifadəçini bütün paneldən məhrum edərdi).
    """
    try:
        store_id = StoreId(uuid.UUID(store_id_text))
    except ValueError:
        return False
    if not show_screen(DAILY_ROSTER_SCREEN_KEY):
        return False
    screen = screen_for(DAILY_ROSTER_SCREEN_KEY)
    if screen is None:
        return False
    populate(store_id, screen)
    return True


def late_threshold_minutes(session: Session) -> int:
    """Növbə sətrinin "gecikib" sayıldığı hədd — CANLI limitdən hesablanır.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ SABİT DEYİL
    ──────────────────────────────────────────────────────────────────────────
    Hədd `VERIFICATION_TIMEOUT_MINUTES`-in YARISIDIR: operator eskalasiya baş
    verməmişdən ƏVVƏL reaksiya verə bilsin. Bu münasibət sabit yazılsaydı
    (22 = 45 / 2), yalnız yazıldığı gün doğru olardı — Root timeout-u 20
    dəqiqəyə endirən kimi eskalasiya 20-də baş verər, xəbərdarlıq isə hələ
    22-də görünərdi, yəni operator siqnalı GECİKMİŞ alardı.

    Eyni naxış `_fine_appeals`-dakı `FINE_APPEAL_WINDOW_HOURS` üçün də
    işlədilir — limit oxunuşunun tək düzgün forması budur.

    Ən azı 1 dəqiqə qaytarılır: Root timeout-u 1 dəqiqəyə salsa, `45 // 2`
    məntiqi 0 verərdi və HƏR sətir doğulan anda "gecikmiş" görünərdi — belə
    bir siyahıda xəbərdarlıq rəngi heç nə demir.
    """
    key = SystemLimitKey.VERIFICATION_TIMEOUT_MINUTES
    try:
        timeout = int(
            session.limits.get_int(session.tenant_id, key.value, int(DEFAULT_LIMITS[key]))
        )
    except Exception:
        # Limit mənbəyi cavab vermədi — sabit FALLBACK işə düşür. Xəbərdarlığı
        # tamamilə söndürmək (məs. `sys.maxsize`) növbəni "hər şey qaydasında"
        # kimi göstərərdi, halbuki problem yalnız konfiqurasiya oxunuşundadır.
        _error_log.warning(
            "QUEUE_LATE_THRESHOLD_FALLBACK",
            extra={"minutes": LATE_QUEUE_MINUTES, "limit_key": key.value},
        )
        return LATE_QUEUE_MINUTES
    return max(1, timeout // 2)


def matrix_window_days(session: Session) -> int:
    """Növbə matrisinin göstərdiyi gün sayı — CANLI limitdən.

    `late_threshold_minutes` ilə EYNİ naxış (limit oxunuşunun tək düzgün
    forması): dəyər hər doldurmada oxunur, çünki panel saatlarla açıq qala
    bilər və Root pəncərəni bu müddət ərzində dəyişə bilər.

    Ən azı 1 gün qaytarılır: `0` yazılsaydı `range(0)` boş pəncərə verər,
    matris SÜTUNSUZ görünər və istifadəçi "məlumat yoxdur" ilə "pəncərə
    sıfırdır" arasındakı fərqi ekranda GÖRƏ BİLMƏZDİ (DB-dəki `min_value` ROOT
    ekranını qoruyur; bu, birbaşa SQL ilə düşən dəyərə qarşı son xətdir).
    """
    key = SystemLimitKey.SHIFT_MATRIX_WINDOW_DAYS
    try:
        days = int(session.limits.get_int(session.tenant_id, key.value, int(DEFAULT_LIMITS[key])))
    except Exception:
        _error_log.warning(
            "SHIFT_MATRIX_WINDOW_FALLBACK",
            extra={"days": FALLBACK_MATRIX_WINDOW_DAYS, "limit_key": key.value},
        )
        return FALLBACK_MATRIX_WINDOW_DAYS
    return max(1, days)


def _next_month(month_start: date) -> date:
    """Ayın SONU yarı-açıq aralıq kimi — `< next_month`.

    `<= ayın son günü` yazsaydıq, `TIMESTAMPTZ` sütunlarda həmin günün
    saatları kəsilərdi; `DATE` və `TIMESTAMPTZ` sütunlar eyni sorğuda
    işlədildiyi üçün TƏK forma seçilib.
    """
    return (
        date(month_start.year + 1, 1, 1)
        if month_start.month == 12  # noqa: PLR2004 — dekabr ilin son ayıdır
        else date(month_start.year, month_start.month + 1, 1)
    )


def _previous_month(month_start: date) -> date:
    return (
        date(month_start.year - 1, 12, 1)
        if month_start.month == 1
        else date(month_start.year, month_start.month - 1, 1)
    )


def _earliest(*moments: Any) -> datetime | None:
    """Verilənlərdən ən KÖHNƏSİ — hamısı `None`-dursa `None`."""
    values = [moment for moment in moments if isinstance(moment, datetime)]
    return min(values) if values else None


def _fine_month_totals(
    session: Session, *, month_start: date, next_month: date, previous_month: date
) -> tuple[str, str]:
    """(bu ayın cəmi, keçən aya nisbətən dəyişmə mətni).

    Faiz KEÇƏN AY sıfır olduqda hesablanmır — "+∞%" mənasız göstəricidir və
    ilk ay hər quraşdırmada belədir. Həmin halda müqayisə əvəzinə vəziyyət
    yazılır ("keçən ay cərimə olmayıb").
    """
    row = session.uow.connection.execute(
        """
        SELECT
          (SELECT COALESCE(SUM(amount), 0) FROM fines
            WHERE tenant_id = %s AND fine_date >= %s AND fine_date < %s) AS current_total,
          (SELECT COALESCE(SUM(amount), 0) FROM fines
            WHERE tenant_id = %s AND fine_date >= %s AND fine_date < %s) AS previous_total
        """,
        (
            session.tenant_id,
            month_start,
            next_month,
            session.tenant_id,
            previous_month,
            month_start,
        ),
    ).fetchone()
    current = float((row or {}).get("current_total") or 0)
    previous = float((row or {}).get("previous_total") or 0)

    total_text = f"{current:,.0f} ₼".replace(",", " ")
    if previous <= 0:
        return (total_text, "keçən ay cərimə olmayıb")
    change = (current - previous) / previous * 100
    return (total_text, f"keçən aya nisbətən {change:+.0f}%")


def _sync_delay_text(seconds: Any) -> str:
    """Sinxronizasiya gecikməsi — saniyə/dəqiqə/saat.

    `None` "heç vaxt sinxronlaşmayıb" deməkdir və `0 san` kimi göstərilmir:
    sıfır gecikmə ideal vəziyyətdir, məlumatsızlıq isə problem əlamətidir.
    """
    if seconds is None:
        return "sinxronlaşmayıb"
    value = int(seconds)
    if value < 60:  # noqa: PLR2004 — bir dəqiqə
        return f"{value} san"
    if value < 3600:  # noqa: PLR2004 — bir saat
        return f"{value // 60} dəq"
    return f"{value // 3600} saat"


def _points_text(delta: Any, *, reversed_: bool = False) -> str:
    """Xal sətri — işarə ilə BİRLİKDƏ (rəng tək daşıyıcı deyil).

    Geri alınmış sətir MƏNFİ işarə ilə göstərilir: ledger-də dəyər müsbət
    qalır (`points_ledger` sətri silinmir, yalnız `REVERSED` olur), lakin
    işçinin balansına təsiri çıxılmadır — ekranda müsbət göstərmək "xal
    hələ məndədir" deyə oxunardı.
    """
    value = int(delta or 0)
    sign = "−" if reversed_ else "+"
    return f"{sign}{abs(value)}"


def _is_reversed(row: Any) -> bool:
    return str(row["status"]) == "REVERSED"


def _points_status_text(row: Any) -> str:
    """Ekranın `_HISTORY_TONES` açarları: «Təsdiqli» / «Gözləyir» / «Geri alınıb».

    Sıra vacibdir: geri alınmış sətrin açıq etirazı ola bilməz, lakin
    etirazı GÖZLƏYƏN sətir hələ qüvvədədir — ona görə `REVERSED` əvvəl
    yoxlanılır.
    """
    if _is_reversed(row):
        return "Geri alınıb"
    if str(row["appeal_status"] or "") == "PENDING":
        return "Gözləyir"
    return "Təsdiqli"


def _monthly_points_delta(session: Session, employee_id: Any) -> int:
    """Bu TƏQVİM ayında qazanılan xal — kartdakı «Bu ay +N xal».

    Dövr (6 aylıq) deyil, AY götürülür: kart aylıq tempi göstərir, balans
    isə onsuz da dövrə görə hesablanır (`balance_for`).
    """
    today = datetime.now(UTC).date()
    month_start = today.replace(day=1)
    row = session.uow.connection.execute(
        """
        SELECT COALESCE(SUM(delta_points), 0) AS total
          FROM points_ledger
         WHERE tenant_id = %s AND employee_id = %s
           AND status <> 'REVERSED'
           AND created_at >= %s AND created_at < %s
        """,
        (session.tenant_id, employee_id, month_start, _next_month(month_start)),
    ).fetchone()
    return int((row or {}).get("total") or 0)


def _points_rank_text(session: Session, employee_id: Any, *, period_start: date) -> str:
    """«N nəfər arasında K-cı» — İŞÇİNİN ÖZ FİLİALI üzrə.

    Filial daxilində müqayisə edilir, tenant miqyasında yox: 21 filialda
    235 nəfər arasında sıra işçi üçün mənasız rəqəmdir və satış həcmi
    filialdan filiala fərqlənir. Sətir `sales_transactions.store_id`
    üzərindən bağlanır, çünki xal həmişə bir satışdan doğur.
    """
    row = session.uow.connection.execute(
        """
        WITH totals AS (
            SELECT e.id, SUM(l.delta_points) AS total
              FROM points_ledger l
              JOIN employees e ON e.id = l.employee_id
             WHERE l.tenant_id = %s AND l.period_start = %s AND l.status <> 'REVERSED'
               AND e.store_id = (SELECT store_id FROM employees WHERE id = %s)
             GROUP BY e.id
        )
        SELECT (SELECT count(*) FROM totals) AS people,
               (SELECT count(*) FROM totals t
                 WHERE t.total > COALESCE((SELECT total FROM totals WHERE id = %s), 0)) AS ahead
        """,
        (session.tenant_id, period_start, employee_id, employee_id),
    ).fetchone()
    people = int((row or {}).get("people") or 0)
    if people == 0:
        return "Reytinq hələ formalaşmayıb"
    return f"{people} nəfər arasında {int((row or {}).get('ahead') or 0) + 1}-ci"


#: Baza cavab müddətinin "norma" həddi (millisaniyə) — kartın tonu bundan
#: asılıdır. Bu, İŞ QAYDASI DEYİL və `system_limits`-ə aid deyil: heç bir
#: əməliyyat bloklanmır, yalnız rəng seçilir. Dəyər maketdəki «Norma: < 50 ms»
#: mətnindən götürülüb ki, ekranın izahı ilə rəngi bir-birini təkzib etməsin.
DB_PING_WARNING_MS: Final = 50
DB_PING_DANGER_MS: Final = 250

#: NTP sürüşməsinin xəbərdarlıq həddi — `system_limits.NTP_MAX_DRIFT_SECONDS`
#: oxuna bilmədikdə işlənən FALLBACK (həqiqi mənbə Root-dadır, bölmə 3).
NTP_DRIFT_FALLBACK_SECONDS: Final = 60


def _health_metrics(session: Session, context: Any) -> list[tuple[str, str, str, str]]:
    """Rəqəm kartları — `(ad, dəyər, izah, ton)`.

    Siyahı DİNAMİKDİR: ölçülə bilməyən göstərici sadəcə əlavə olunmur (bax
    `_health` docstring-i). Ona görə ekranda 2 kart da görünə bilər, 4 da.
    """
    metrics: list[tuple[str, str, str, str]] = []
    metrics.append(_db_ping_metric(session))

    drift = context.ntp_drift_seconds()
    if drift is not None:
        key = SystemLimitKey.NTP_MAX_DRIFT_SECONDS
        try:
            limit = int(
                session.limits.get_int(session.tenant_id, key.value, int(DEFAULT_LIMITS[key]))
            )
        except Exception:
            limit = NTP_DRIFT_FALLBACK_SECONDS
        metrics.append(
            (
                "NTP sapması",
                f"{drift:+.1f} san",
                f"Hədd: ±{limit} san",
                "success" if abs(drift) <= limit else "danger",
            )
        )

    pending = _offline_pending(session, context)
    if pending is not None:
        metrics.append(
            (
                "Sinxronlaşmamış yazı",
                str(pending),
                "Offline bufer növbəsi",
                "success" if pending == 0 else "warning",
            )
        )

    conflicts = _open_conflicts(session)
    metrics.append(
        (
            "Sync konflikti",
            str(conflicts),
            "Həll gözləyən sətir",
            "success" if conflicts == 0 else "warning",
        )
    )
    return metrics


def _db_ping_metric(session: Session) -> tuple[str, str, str, str]:
    """Bazanın cavab müddəti — REAL ölçmə (`SELECT 1` gediş-gəlişi).

    Sabit dəyər və ya "OK" yazmaq mənasız olardı: bu kartın yeganə məqsədi
    bağlantının nə qədər ləng olduğunu göstərməkdir. Ölçmə sorğunun ÖZÜNÜ
    əhatə edir (şəbəkə + parse + cavab), yəni istifadəçinin hiss etdiyi
    gecikmə ilə eyni cinsdəndir.
    """
    import time  # noqa: PLC0415

    started = time.monotonic()
    session.uow.connection.execute("SELECT 1").fetchone()
    elapsed_ms = int((time.monotonic() - started) * 1000)

    if elapsed_ms >= DB_PING_DANGER_MS:
        tone = "danger"
    elif elapsed_ms >= DB_PING_WARNING_MS:
        tone = "warning"
    else:
        tone = "success"
    return ("Baza (DB Ping)", f"{elapsed_ms} ms", f"Norma: < {DB_PING_WARNING_MS} ms", tone)


def _offline_pending(session: Session, context: Any) -> int | None:
    """Offline buferdəki gözləyən yazı sayı — bufer açıla bilmirsə `None`.

    `None` halında kart GÖSTƏRİLMİR: `0` yazmaq "hər şey sinxrondur" demək
    olardı, halbuki əsl vəziyyət "oxuya bilmədim"dir (bax `_LazyBufferDrain`).
    """
    try:
        return int(context.offline_drain().pending_count(session.tenant_id))
    except Exception:
        _error_log.warning("HEALTH_OFFLINE_BUFFER_UNREADABLE")
        return None


def _open_conflicts(session: Session) -> int:
    """Həll gözləyən sinxronizasiya konfliktləri (`sync_conflicts`).

    Use case-in `open_count()` metodu `can_view_employee_reports` tələb edir;
    burada REPO birbaşa oxunur, çünki ekran onsuz da `can_view_system_health`
    flag-i ilə açılır (bax `menu.py`) və sağlamlıq sayğacı üçün İKİNCİ,
    əlaqəsiz bir flag tələb etmək istifadəçini izahsız boş kartla qoyardı.
    Sayğac heç bir konflikt MƏZMUNUNU açmır — yalnız ədəddir.
    """
    try:
        return int(session.uow.repository("sync_conflicts").open_count(session.tenant_id))
    except Exception:
        _error_log.exception("HEALTH_CONFLICT_COUNT_FAILED")
        return 0


def _health_latencies(session: Session) -> list[tuple[str, str, str]]:
    """1C serverlərinin sinxron gecikməsi — `v_erp_server_health` görünüşü.

    `INACTIVE` sətirlər DƏ göstərilir (dashboard-dan fərqli olaraq): bu ekran
    diaqnostika üçündür və "server niyə məlumat göndərmir" sualının cavabı
    çox vaxt məhz "deaktiv edilib"dir.
    """
    rows = session.uow.connection.execute(
        """
        SELECT server_name, health, sync_delay_seconds
          FROM v_erp_server_health
         WHERE tenant_id = %s
         ORDER BY server_name
         LIMIT 20
        """,
        (session.tenant_id,),
    ).fetchall()
    return [
        (
            str(row["server_name"]),
            "deaktiv"
            if str(row["health"]) == "INACTIVE"
            else _sync_delay_text(row["sync_delay_seconds"]),
            _HEALTH_TONES.get(str(row["health"]), "warning"),
        )
        for row in rows
    ]


def _health_alerts(session: Session, actor: Any) -> list[tuple[str, str, str]]:
    """Aktiv xəbərdarlıqlar — `(mətn, vaxt, ton)`.

    Üç REAL mənbə birləşdirilir: problemli 1C serverləri (diaqnoz mətni
    domendədir — `ServerHealthRow.diagnosis`), oxunmamış KRİTİK bildirişlər
    və açıq sinxronizasiya konfliktləri. Yeni xəbərdarlıq NÖVÜ icad edilmir.
    """
    alerts: list[tuple[str, str, str]] = []
    now = datetime.now(UTC)

    rows = session.uow.connection.execute(
        """
        SELECT server_name, health, last_error_at, consecutive_failures, mapped_stores
          FROM v_erp_server_health
         WHERE tenant_id = %s AND health IN ('DEGRADED', 'STALE', 'NEVER_SYNCED')
         ORDER BY server_name
         LIMIT 10
        """,
        (session.tenant_id,),
    ).fetchall()
    for row in rows:
        alerts.append(
            (
                f"{row['server_name']}: {_erp_diagnosis(row)}",
                _hhmm(row["last_error_at"]),
                "danger" if str(row["health"]) == "NEVER_SYNCED" else "warning",
            )
        )

    for notification in _critical_notifications(session, actor):
        alerts.append(
            (
                notification.title_az,
                _hhmm(notification.created_at),
                "danger" if notification.is_critical else "warning",
            )
        )

    conflicts = _open_conflicts(session)
    if conflicts:
        alerts.append(
            (
                f"{conflicts} sinxronizasiya konflikti həll gözləyir — "
                "eyni qeyd iki yerdə fərqli dəyişdirilib.",
                _hhmm(now),
                "warning",
            )
        )
    return alerts


def _erp_diagnosis(row: Any) -> str:
    """Sətri domendəki diaqnoz mətninə çevirir.

    Mətn BURADA yazılmır — `ServerHealthRow.diagnosis` onu texniki-olmayan
    dildə verir (bölmə 7 tələbi) və eyni mətn «ERP Serverləri» ekranında da
    görünür. İki yerdə iki fərqli izah istifadəçini çaşdırardı.
    """
    from src.infrastructure.erp.health import ServerHealth, ServerHealthRow  # noqa: PLC0415

    return ServerHealthRow(
        server_id="",
        server_name=str(row["server_name"]),
        host="",
        health=ServerHealth(str(row["health"])),
        status="",
        consecutive_failures=int(row["consecutive_failures"] or 0),
        mapped_stores=int(row["mapped_stores"] or 0),
        sync_interval_seconds=300,
    ).diagnosis


def _critical_notifications(session: Session, actor: Any) -> list[Any]:
    """Oxunmamış KRİTİK bildirişlər — sistem hadisələrinin izi (bölmə 7).

    Auditoriya süzgəci zəng panelindəki ilə EYNİ funksiyadan gəlir: İdarə
    Panelindəki kritik siyahı zəng nişanından geniş olsaydı, istifadəçi
    paneldə tapa bilmədiyi bir sətri burada görərdi.
    """
    from src.presentation.controllers.notifications import (  # noqa: PLC0415
        hidden_categories_for,
    )

    try:
        rows = session.notifications.list_for_recipient(
            actor.id, hidden_categories=hidden_categories_for(actor)
        )
    except Exception:
        _error_log.exception("HEALTH_NOTIFICATIONS_FAILED")
        return []
    return [row for row in rows if row.is_critical and row.is_unread][:5]


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


def _fine_type_name(session: Session, fine_id: Any) -> str:
    """Etiraz kartındakı cərimə növü — tapılmasa "—"."""
    row = session.uow.connection.execute(
        """SELECT COALESCE(ft.name_az, '—') AS name
             FROM fines f LEFT JOIN fine_types ft ON ft.id = f.fine_type_id
            WHERE f.id = %s AND f.tenant_id = %s""",
        (fine_id, session.tenant_id),
    ).fetchone()
    return str(row["name"]) if row else "—"


def _fine_amount(session: Session, fine_id: Any) -> str:
    row = session.uow.connection.execute(
        "SELECT amount FROM fines WHERE id = %s AND tenant_id = %s",
        (fine_id, session.tenant_id),
    ).fetchone()
    return f"{row['amount']} ₼" if row else "—"


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


def _default_store(session: Session, actor: Employee) -> tuple[Any, str]:
    """Mağaza-əhatəli göstəricilər üçün "hansı mağaza?" cavabı (#13).

    Aktorun öz filialı ÜSTÜNDÜR. Root/CEO-nun filialı yoxdur (şəbəkə
    səviyyəsindədir) — onlar üçün əlifba üzrə ilk AKTİV mağaza seçilir.
    Boş nəticə "—" adı ilə qaytarılır ki, çağıran tərəf ekranı yenə də
    doldursun: səssiz `return` istifadəçidə "kart sınıb" təəssüratı yaradardı.
    """
    if actor.store_id is not None:
        return actor.store_id, _store_name(session, actor.store_id)

    row = session.uow.connection.execute(
        "SELECT id, name FROM stores WHERE tenant_id = %s AND is_active ORDER BY name LIMIT 1",
        (session.tenant_id,),
    ).fetchone()
    if row is None:
        return None, "—"
    return row["id"], str(row["name"])


def _position_name(session: Session, employee_id: Any) -> str:
    employee = session.uow.employees.get(employee_id)
    return str(employee.position.name_az) if employee is not None else "—"


__all__ = [
    "FALLBACK_MATRIX_WINDOW_DAYS",
    "HELP_TOPIC_MODULES",
    "LATE_QUEUE_MINUTES",
    "ScreenDataBinder",
    "late_threshold_minutes",
    "matrix_window_days",
]
