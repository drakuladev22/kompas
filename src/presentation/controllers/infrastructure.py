"""Baza keçidi panelinin YAZI yolu — `DatabaseSwitchUseCase` (bölmə 2).

──────────────────────────────────────────────────────────────────────────────
LAYİHƏNİN ƏN DAĞIDICI ƏMƏLİYYATI
──────────────────────────────────────────────────────────────────────────────
Keçid bütün tenant-ı yalnız-oxu rejiminə salır, məlumatı köçürür və aktiv
bazanı dəyişir. Kontroller HEÇ BİR addımı özü icra etmir və heç bir ön-şərti
yumşaltmır — yeddi addımın hamısı (`OPEN_WINDOW` → `DRAIN_BUFFER` →
`PREFLIGHT_CHECKSUM` → `COPY_DATA` → `POSTFLIGHT_CHECKSUM` → `SWITCH_ACTIVE` →
`CLOSE_WINDOW`) use case-in içindədir və orada qalmalıdır.

Kontrollerin ÜÇ işi var:

    1. Ön yoxlamanı (`preflight`) çağırıb xəbərdarlıqları GÖSTƏRMƏK;
    2. TƏSDİQ modalını açmaq — istifadəçi hədəf bazanın adını əl ilə yazır;
    3. Nəticəni (`MigrationReport`) addım-addım ekrana köçürmək.

`switch_requested` siqnalından birbaşa `execute()` çağırsaydıq, bir klik
istehsalat bazasını köçürməyə başlayardı.

──────────────────────────────────────────────────────────────────────────────
ŞİFRƏ YOLUNA TOXUNULMUR
──────────────────────────────────────────────────────────────────────────────
DSN-lər `ApplicationContext.migrator()`-də qurulur və şifrə `PGPASSWORD`
mühit dəyişəni ilə ötürülür (`PgDumpMigrator._invoke`, Faza 3). Kontroller nə
DSN oxuyur, nə də onu heç bir jurnala/ekrana ötürür — hədəf yalnız
`DatabaseTarget` enum dəyəri kimi tanınır.

──────────────────────────────────────────────────────────────────────────────
KONFİQURASİYA ƏSKİKDİRSƏ ÇÖKMƏ YOX, İZAH
──────────────────────────────────────────────────────────────────────────────
`KOMPASOS_PRIVATE_SERVER_DSN` boş ola bilər (müştərilərin əksəriyyəti yalnız
buludda işləyir). Həmin halda `PgDumpMigrator._require_dsn()` aydın
Azərbaycanca `MigrationError` atır və o, `MigrationReport`-un `rollback_reason`
sahəsində ekrana çıxır — tətbiq çökmür, aktiv baza dəyişmir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_i import InfrastructureScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: `MigrationStatus` → tarixçə cədvəlindəki nişan tonu.
_STATUS_TONES: dict[str, str] = {
    "COMPLETED": "success",
    "IN_PROGRESS": "info",
    "ROLLED_BACK": "danger",
    "FAILED": "danger",
}

#: `MigrationStatus` → Azərbaycanca nəticə mətni.
_STATUS_TEXT: dict[str, str] = {
    "COMPLETED": "Tamamlandı",
    "IN_PROGRESS": "İcra olunur",
    "ROLLED_BACK": "Geri qaytarıldı",
    "FAILED": "Uğursuz",
}


class InfrastructureController:
    """İnfrastruktur panelini `DatabaseSwitchUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: InfrastructureScreen) -> None:
        screen.switch_requested.connect(lambda target: self._on_switch(screen, target))
        screen.history_requested.connect(lambda: self.refresh(screen))
        self.refresh(screen)

    def refresh(self, screen: InfrastructureScreen) -> None:
        """Aktiv bazanı, ön yoxlamanı və keçid tarixçəsini oxuyur."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                active = _active_target(session)
                warnings = _preflight_warnings(session, self._actor, active)
                history = _history_rows(session)
        except KompasOSError as error:
            screen.show_error(title="Panel açıla bilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("INFRASTRUCTURE_LOAD_FAILED")
            screen.show_error(
                title="Panel açıla bilmədi",
                message="Baza vəziyyəti oxuna bilmədi. Yenidən cəhd edin.",
            )
            return

        screen.set_active_target(active)
        screen.set_warnings(warnings)
        screen.set_history(history)

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_switch(self, screen: InfrastructureScreen, raw_target: str) -> None:
        """TƏSDİQ ADDIMI — keçid burada BAŞLAMIR (bax modul başlığı)."""
        from src.domain.value_objects.infrastructure import (  # noqa: PLC0415
            DatabaseTarget,
            MigrationError,
            MigrationPlan,
        )
        from src.presentation.screens.group_i import MigrationConfirmDialog  # noqa: PLC0415

        try:
            destination = DatabaseTarget(raw_target)
        except ValueError:
            _error_log.warning("MIGRATION_TARGET_INVALID", extra={"value": raw_target})
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                source = _active_target(session)
                plan = MigrationPlan(source=source, destination=destination)
                # ÖN YOXLAMA TƏSDİQDƏN ƏVVƏL: `preflight()` `can_switch_db`
                # tələb edir, yəni səlahiyyətsiz istifadəçi modalı ÜMUMİYYƏTLƏ
                # görmür — "təsdiq et, sonra rədd cavabı al" axını yaranmır.
                warnings = session.db_switch.preflight(
                    tenant_id=session.tenant_id, actor=self._actor, plan=plan
                )
        except (KompasOSError, MigrationError) as error:
            screen.show_error(
                title="Keçid başlamadı",
                message=getattr(error, "user_message", str(error)),
            )
            return
        except Exception:
            _error_log.exception("MIGRATION_PREFLIGHT_FAILED")
            screen.show_error(
                title="Keçid başlamadı",
                message="Ön yoxlama aparıla bilmədi. Yenidən cəhd edin.",
            )
            return

        dialog = MigrationConfirmDialog(
            screen.theme,
            destination=destination,
            summary=plan.summary_az(),
            warnings=warnings,
            parent=screen,
        )
        # YALNIZ `confirmed` icranı işə salır: modal bağlansa və ya ad uyğun
        # gəlməsə siqnal yayılmır və heç nə baş vermir.
        dialog.confirmed.connect(lambda _target: self._execute(screen, plan))
        dialog.exec()

    def _execute(self, screen: InfrastructureScreen, plan: Any) -> None:
        """Keçidi icra edir və gedişatı addım-addım göstərir.

        `execute()` HEÇ VAXT yarımçıq vəziyyət qoymur: uğursuzluqda avtomatik
        rollback işə düşür və aktiv baza KÖHNƏSİ qalır (bax use case başlığı).
        Ona görə burada "qismən uğur" halı üçün budaq YOXDUR — belə vəziyyət
        mövcud deyil.
        """
        screen.reset_phases()
        try:
            with self._context.session(user_id=self._actor.id) as session:
                report = session.db_switch.execute(
                    tenant_id=session.tenant_id, actor=self._actor, plan=plan
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Keçid icra edilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("MIGRATION_EXECUTE_FAILED")
            screen.show_error(
                title="Keçid icra edilmədi",
                message="Əməliyyat tamamlanmadı. Aktiv baza dəyişmədi.",
            )
            return

        _apply_report(screen, report)
        self.refresh(screen)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _apply_report(screen: InfrastructureScreen, report: Any) -> None:
    """`MigrationReport`-u gedişat sətirlərinə köçürür.

    Tamamlanan addımlar `done`, dayandığı addım `failed` olur; qalanlar
    `pending` qalır. Uğursuzluqda səbəb `set_warnings()` ilə göstərilir —
    `show_error()` ekranı boşaldıb gedişatı gizlədərdi, halbuki istifadəçinin
    ilk sualı "hansı addımda dayandı" olur.
    """
    for phase in report.completed_phases:
        screen.set_phase_state(phase, "done")
    if not report.succeeded and report.failed_phase is not None:
        screen.set_phase_state(report.failed_phase, "failed")
    if not report.succeeded:
        screen.set_warnings([report.summary_az()])


def _active_target(session: Session) -> Any:
    """Hazırda hansı baza aktivdir — sonuncu UĞURLU keçidə görə.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ TARİXÇƏDƏN OXUNUR
    ──────────────────────────────────────────────────────────────────────────
    `PgDumpMigrator.active` yalnız İŞLƏK YADDAŞDA yaşayır və tətbiq yenidən
    başlayanda itir. `db_migration_events` isə silinmir: sonuncu `COMPLETED`
    sətrin `destination_target`-i faktiki vəziyyətdir. Heç bir keçid olmayıbsa
    defolt `CLOUD`-dur — quraşdırma buludda başlayır (bölmə 2).
    """
    from src.domain.value_objects.infrastructure import DatabaseTarget  # noqa: PLC0415

    row = session.uow.connection.execute(
        """
        SELECT destination_target
          FROM db_migration_events
         WHERE tenant_id = %s AND status = 'COMPLETED'
         ORDER BY created_at DESC
         LIMIT 1
        """,
        (session.tenant_id,),
    ).fetchone()
    if row is None:
        return DatabaseTarget.CLOUD
    try:
        return DatabaseTarget(str(row["destination_target"]))
    except ValueError:  # pragma: no cover - DB CHECK onsuz da məhdudlaşdırır
        return DatabaseTarget.CLOUD


def _preflight_warnings(session: Session, actor: Any, active: Any) -> list[str]:
    """Panel açılışındakı ön yoxlama — səlahiyyət yoxdursa BOŞ siyahı.

    Burada istisna ATILMIR: `preflight()` `can_switch_db` tələb edir, lakin
    panelin ÖZÜ (tarixçə + aktiv baza) daha geniş auditoriyaya açıqdır.
    Səlahiyyətsiz istifadəçi üçün xəbərdarlıq sətri boş qalır və keçid düyməsi
    onsuz da `_on_switch`-də rədd olunur — səbəbi orada görür.
    """
    from src.domain.value_objects.infrastructure import (  # noqa: PLC0415
        MigrationError,
        MigrationPlan,
    )

    try:
        plan = MigrationPlan(source=active, destination=active.opposite())
        warnings: list[str] = session.db_switch.preflight(
            tenant_id=session.tenant_id, actor=actor, plan=plan
        )
    except (KompasOSError, MigrationError):
        return []
    return warnings


def _history_rows(session: Session) -> list[dict[str, str]]:
    """Keçid tarixçəsi — `db_migration_events` (silinmir).

    Açarlar ekranın FAKTİKİ oxuduqlarıdır: `date`, `direction`, `checksum`,
    `status`, `tone` — maket yolundakı `preview_data.DB_SWITCH_HISTORY` ilə
    EYNİ dəst (CLAUDE.md bölmə 6).
    """
    from src.domain.value_objects.infrastructure import DatabaseTarget  # noqa: PLC0415

    rows = session.uow.repository("migration_events").history(session.tenant_id)
    result: list[dict[str, str]] = []
    for row in rows:
        status = str(row["status"])
        result.append(
            {
                "date": f"{row['created_at']:%d.%m.%Y %H:%M}" if row["created_at"] else "—",
                "direction": _direction_text(row, DatabaseTarget),
                "checksum": _checksum_text(row),
                "status": _STATUS_TEXT.get(status, status),
                "tone": _STATUS_TONES.get(status, "neutral"),
            }
        )
    return result


def _direction_text(row: Any, target_enum: Any) -> str:
    """«Bulud → Şəxsi server» — etiketlər domendən gəlir (`label_az`)."""

    def label(value: Any) -> str:
        try:
            return str(target_enum(str(value)).label_az)
        except ValueError:  # pragma: no cover - DB CHECK məhdudlaşdırır
            return str(value)

    return f"{label(row['source_target'])} → {label(row['destination_target'])}"


def _checksum_text(row: Any) -> str:
    """Barmaq izinin qısa forması — tam hash sütuna sığmır.

    Uyğunsuzluq halında AÇIQ işarələnir: eyni uzunluqdakı iki hash-ı gözlə
    müqayisə etmək mümkün deyil, ona görə nəticə SÖZLƏ deyilir.
    """
    preflight = row.get("preflight_checksum")
    if not preflight:
        return "—"
    short = str(preflight)[:6] + "…"
    matched = row.get("checksum_matched")
    if matched is None:
        return short
    return f"{short} {'✓' if matched else '✗ fərqli'}"


__all__ = ["InfrastructureController"]
