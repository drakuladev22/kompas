r"""Gizli bərpa konsolunun MƏNTİQ qatı — `Ctrl+Shift+K` (RECOVERY-1 Faza 2).

──────────────────────────────────────────────────────────────────────────────
NİYƏ GİZLİ
──────────────────────────────────────────────────────────────────────────────
Müştərinin gördüyü ekran QƏSDƏN kasıbdır: mesaj + «Yenidən Cəhd Et» + dəstək
ünvanı. Orada «Bağlantı Ayarları» düyməsi OLSAYDI, mağaza işçisi problemi özü
«düzəltməyə» çalışar və işlək konfiqurasiyanı poza bilərdi — sonra isə həm
nasazlıq, həm də onun səbəbi dəyişmiş olardı.

Konsol isə TEXNİKİN alətidir və qısayolla açılır. Gizlilik təhlükəsizlik
DEYİL (qısayol sənədləşdirilib) — o, sadəcə səhv adamın oraya təsadüfən
düşməsinin qarşısını alır. Həqiqi qapı aşağıdakı `may_open`-dadır.

──────────────────────────────────────────────────────────────────────────────
XƏTA MESAJI KONKRET OLMALIDIR
──────────────────────────────────────────────────────────────────────────────
«Bağlantı xətası» quraşdırıcıya heç nə vermir: DNS səhvi host sahəsini,
`28P01` isə açarı düzəltməyi tələb edir. Ayırıcı SQLSTATE-dir və o,
lokalizasiyadan asılı deyil (`composition.classify_connection_failure`-dakı
eyni qərar). Tanımadığımız halda server MƏTNİ olduğu kimi göstərilir —
«naməlum xəta» yazmaq texniki gözlə oxunan yeganə məlumatı gizlədərdi.
"""

from __future__ import annotations

import os
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Final

from src import __version__
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from src.domain.entities.employee import Employee

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Konsolu açan səlahiyyət — `use_cases/db_switch.SWITCH_DB_FLAG` ilə EYNİ.
#: İkinci sabit yaratmaq iki qaydanın bir gün ayrılması deməkdir.
SWITCH_DB_FLAG: Final[str] = "can_switch_db"

#: Fon işinin nəticəsi `(mətn, təsdiq lazımdır?)` cütü ola bilər.
_RESULT_PAIR: Final[int] = 2

#: Uzun siyahılarda ekranda göstərilən element sayı — mesaj bir neçə
#: sətirdən uzun olsa, texnik ƏSAS məlumatı (say) itirər.
_PREVIEW_LIMIT: Final[int] = 10

#: SQLSTATE → istifadəçi mətni. Siyahı DAR saxlanılır: yalnız quraşdırıcının
#: FƏRQLİ addım atacağı hallar. Qalanı orijinal mətnlə göstərilir.
_SQLSTATE_MESSAGES: Final[dict[str, str]] = {
    "28P01": "Açar/parol rədd edildi (28P01) — istifadəçi adı və ya parol yanlışdır.",
    "28000": "Açar rədd edildi (28000) — istifadəçi bu bazaya qoşula bilmir.",
    "3D000": "Belə baza yoxdur (3D000) — «Baza adı» sahəsini yoxlayın.",
    "42P01": "Cədvəl yoxdur (42P01) — sxem qurulmayıb. «Bazanı Avtomatik Qur» işlədin.",
    "42501": "İcazə çatmır (42501) — bu istifadəçinin cədvəl yaratmaq hüququ yoxdur.",
    "53300": "Bağlantı limiti dolub (53300) — Supabase layihəsində aktiv sessiyalar çoxdur.",
}

#: Mətndə axtarılan naxışlar — SQLSTATE OLMAYAN nasazlıqlar üçün.
#: Şəbəkə səviyyəsindəki xətalar (DNS, taymaut) `sqlstate` DAŞIMIR, çünki
#: server cavabı ümumiyyətlə alınmır.
_TEXT_MESSAGES: Final[tuple[tuple[str, str], ...]] = (
    (
        "could not translate host name",
        "Host adı tapılmadı (DNS) — «Server ünvanı» sahəsindəki ad səhv yazılıb "
        "və ya internet yoxdur.",
    ),
    (
        "timeout expired",
        "Bağlantı taymauta düşdü — server cavab vermir, port bağlı ola bilər.",
    ),
    (
        "connection refused",
        "Bağlantı rədd edildi — həmin port dinlənilmir (port nömrəsini yoxlayın).",
    ),
    (
        "certificate verify failed",
        "SSL sertifikatı doğrulanmadı — `sslmode` dəyəri və şəbəkə proksisini yoxlayın.",
    ),
)


def describe_failure(error: BaseException) -> str:
    """Bağlantı/sorğu nasazlığını KONKRET cümləyə çevirir.

    Sıra vacibdir: əvvəlcə SQLSTATE (serverdən gələn, lokalizasiyadan asılı
    olmayan kod), sonra mətn naxışları (şəbəkə səviyyəsi, SQLSTATE yoxdur),
    ən sonda orijinal mətn.
    """
    sqlstate = str(getattr(error, "sqlstate", "") or "")
    known = _SQLSTATE_MESSAGES.get(sqlstate)
    if known:
        return known

    text = str(error)
    lowered = text.lower()
    for needle, message in _TEXT_MESSAGES:
        if needle in lowered:
            return message

    # ORİJİNAL MƏTN GİZLƏDİLMİR — bax modul başlığı.
    return f"Bağlantı alınmadı: {text}" if text else "Bağlantı alınmadı (səbəb bilinmir)."


def may_open(*, actor: Employee | None, configured: bool) -> bool:
    """Konsolu açmaq icazəsi.

    ──────────────────────────────────────────────────────────────────────────
    İKİ FƏRQLİ VƏZİYYƏT, İKİ FƏRQLİ QAYDA
    ──────────────────────────────────────────────────────────────────────────
    * **Konfiqurasiya edilməmiş maşın** — hesab hələ YOXDUR, yəni səlahiyyət
      soruşmaq üçün baza lazımdır, baza isə məhz bu konsolla qurulacaq
      (toyuq-yumurta). Qapını bağlamaq konsolu faydasız edərdi.
    * **Konfiqurasiya edilmiş maşın** — `can_switch_db` daşıyan `Root`.
      Şərt `use_cases/db_switch._require_permission` ilə EYNİDİR və qəsdən:
      konsol həmin əməliyyatların qısa yoludur, ona görə ikinci, daha zəif
      qayda icad edilməməlidir. `CEO` buraya çata BİLMİR — flag onsuz da
      `HardlockLevel.ROOT_ONLY` daşıyır.
    """
    if not configured:
        return True
    if actor is None:
        return False

    from src.domain.value_objects.authorization import SystemRole  # noqa: PLC0415

    if not actor.has_permission(SWITCH_DB_FLAG, now=_now()):
        _security_log.warning(
            "RECOVERY_CONSOLE_DENIED_FLAG", extra={"actor_id": str(getattr(actor, "id", "?"))}
        )
        return False
    if actor.position.effective_system_role is not SystemRole.ROOT:
        _security_log.warning(
            "RECOVERY_CONSOLE_DENIED_ROLE",
            extra={"actor_id": str(getattr(actor, "id", "?"))},
        )
        return False
    return True


def _now() -> Any:
    """`has_permission` üçün cari an.

    `Clock` portu BURADA İŞLƏDİLMİR və bu, qəsdli istisnadır: konsol məhz
    baza (deməli `ServerTimeService` də) əlçatmaz olanda açılır. Yerli saat
    yeganə mövcud mənbədir və o, YALNIZ flag-in müddət pəncərəsinə baxır —
    heç bir audit/hesablama buradan qidalanmır.
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    return datetime.now(UTC)


def diagnostics() -> list[tuple[str, str]]:
    """«Proqram hansı faylı oxuyur?» sualının TAM cavabı.

    Bağlantı Ayarları ekranındakı qısa diaqnostikadan FƏRQİ odur ki, burada
    axtarılan HƏR yol ayrıca sətirdir və hər birinin yanında tapılıb-tapılmadığı
    yazılır. Qısa variant «hansı fayl işlədilir?» sualına cavab verir; bu isə
    «niyə TAPILMIR?» sualına — və o sual yalnız nasazlıqda verilir.
    """
    from src.infrastructure.config.connection_file import (  # noqa: PLC0415
        connection_file_path,
        connection_search_paths,
        load_settings,
    )
    from src.shared.data_paths import default_data_dir, default_log_dir  # noqa: PLC0415

    rows: list[tuple[str, str]] = [("Tətbiq versiyası", __version__)]
    for index, path in enumerate(connection_search_paths(), start=1):
        state = "VAR" if path.is_file() else "yoxdur"
        rows.append((f"Konfiqurasiya axtarışı {index}", f"{path}  →  {state}"))
    rows.append(("Konfiqurasiya yazılacaq yer", str(connection_file_path())))

    # ŞİFRƏ AÇILDIMI — ayrıca sətirdir, çünki «fayl var» ilə «fayl oxunur»
    # tamamilə fərqli iki haldır: DPAPI blobu dəyişəndə fayl yerində qalır,
    # lakin parol açılmır (bax `config/connection_file.py`).
    try:
        settings = load_settings()
    except Exception as error:
        rows.append(("Konfiqurasiya oxunuşu", f"XƏTA — {error}"))
    else:
        if settings is None:
            rows.append(("Konfiqurasiya oxunuşu", "fayl tapılmadı"))
        else:
            where = f"{settings.username}@{settings.host}:{settings.port}"
            rows.append(("Konfiqurasiya oxunuşu", f"OK — {where}"))

    rows.append(("Log qovluğu", str(default_log_dir())))
    rows.append(("Yerli məlumat", str(default_data_dir())))
    return rows


class RecoveryConsoleController:
    r"""Bərpa konsolunun YAZI yolu — bütün ağır işlər FON SAPINDA.

    ──────────────────────────────────────────────────────────────────────────
    NİYƏ HƏR ƏMƏLİYYAT `BackgroundTask`-DADIR
    ──────────────────────────────────────────────────────────────────────────
    Buradakı dörd əməliyyatın hamısı şəbəkəyə çıxır və ən ağırı (baza quruluşu)
    onlarla SQL faylı icra edir — dəqiqələrlə çəkə bilər. GUI sapında icra
    olunsaydı, Windows pəncərəni «Cavab vermir» kimi işarələyər, istifadəçi isə
    proqramı bağlamağa çalışardı — məhz quruluşun ortasında.

    ──────────────────────────────────────────────────────────────────────────
    ELEVASİYALI PAROL — `service_role` HAQQINDA DÜRÜST QEYD
    ──────────────────────────────────────────────────────────────────────────
    Supabase-in `service_role` açarı PostgREST üçün JWT-dir; BİRBAŞA Postgres
    bağlantısı (psycopg) onu QƏBUL ETMİR — DDL üçün baza istifadəçisi və parolu
    lazımdır. Ona görə ekrandakı sahə həmin JWT deyil, YALNIZ QURULUŞ üçün
    işlədilən elevasiyalı baza paroludur: adi istifadəçinin `CREATE TABLE`
    hüququ yoxdursa, texnik ora daha səlahiyyətli hesabın parolunu yazır.
    Dəyər fayla YAZILMIR və əməliyyat başlayan kimi ekrandan da silinir.
    Sahəni «service_role JWT» kimi təqdim etmək texniki cəhətdən YALAN olardı.
    """

    def __init__(self, *, on_saved: Callable[[], None] | None = None) -> None:
        self._on_saved = on_saved
        #: Fon işçisinə İSTİNAD saxlanılır: o, ekranın uşağıdır, lakin yalnız
        #: yerli dəyişən qalsaydı Python onu nəticə gəlməmiş toplaya bilərdi.
        self._task: Any = None

    # ------------------------------ bağlanma ---------------------------------- #

    def attach(self, screen: Any) -> None:
        """Siqnalları bağlayır və mövcud vəziyyəti göstərir."""
        screen.test_requested.connect(lambda values: self._on_test(screen, values))
        screen.save_requested.connect(lambda values: self._on_save(screen, values))
        screen.check_tables_requested.connect(lambda values: self._on_check(screen, values))
        screen.provision_requested.connect(lambda values: self._on_provision(screen, values))
        screen.open_logs_requested.connect(self._open_logs)
        screen.open_config_requested.connect(self._open_config)
        self.refresh(screen)

    def refresh(self, screen: Any) -> None:
        """Sahələri və diaqnostikanı yenidən oxuyur."""
        from src.infrastructure.config.connection_file import load_settings  # noqa: PLC0415

        screen.set_diagnostics(diagnostics())
        try:
            settings = load_settings()
        except Exception as error:
            screen.set_error(describe_failure(error))
            return
        if settings is None:
            screen.set_status("Konfiqurasiya tapılmadı — sahələri doldurun.")
            return
        screen.populate(
            {
                "host": settings.host,
                "port": settings.port,
                "database": settings.database,
                "username": settings.username,
                "tenant_id": os.environ.get("KOMPASOS_TENANT_ID", ""),
                "supabase_url": os.environ.get("KOMPASOS_SUPABASE_URL", ""),
                "anon_key": os.environ.get("KOMPASOS_SUPABASE_ANON_KEY", ""),
            }
        )
        screen.set_status("Mövcud ayarlar göstərilir. Parol boş qalarsa dəyişmir.")

    # ------------------------------ əməliyyatlar ------------------------------ #

    def _settings_from(self, values: dict[str, str]) -> Any:
        """Ekran dəyərlərindən `ConnectionSettings`; parol boşdursa MÖVCUDU.

        Boş parol «sil» DEYİL, «dəyişmə» deməkdir — ekran parolu heç vaxt
        göstərmir, ona görə boş sahəni silmə kimi oxumaq işlək ayarı sükutla
        pozardı (`ConnectionSettingsController`-dəki eyni qərar).
        """
        from src.infrastructure.config.connection_file import (  # noqa: PLC0415
            ConnectionSettings,
            load_settings,
        )

        password = values.get("password", "")
        if not password:
            with suppress(Exception):
                current = load_settings()
                if current is not None:
                    password = current.password
        return ConnectionSettings(
            host=values.get("host", ""),
            port=int(values.get("port") or 5432),
            database=values.get("database") or "postgres",
            username=values.get("username", ""),
            password=password,
        )

    def _run(self, screen: Any, job: Callable[[], object], *, name: str) -> None:
        """İşi fonda buraxır və nəticəni ekrana çatdırır."""
        from src.presentation.background_task import BackgroundTask  # noqa: PLC0415

        screen.set_busy(True)
        task = BackgroundTask(parent=screen, name=name)
        task.succeeded.connect(lambda payload: self._deliver(screen, payload))
        task.failed.connect(lambda error: screen.set_error(describe_failure(error)))
        task.finished.connect(lambda: screen.set_busy(False))
        self._task = task
        task.run(job)

    def _deliver(self, screen: Any, payload: object) -> None:
        """Fon işinin nəticəsi — mətn, və ya `(mətn, təsdiq lazımdır?)` cütü."""
        if isinstance(payload, tuple) and len(payload) == _RESULT_PAIR:
            message, needs_confirmation = payload
            screen.set_status(str(message))
            screen.require_confirmation(bool(needs_confirmation))
            return
        screen.set_status(str(payload))

    def _on_test(self, screen: Any, values: dict[str, str]) -> None:
        settings = self._settings_from(values)

        def job() -> object:
            from src.infrastructure.persistence.connection import probe_dsn  # noqa: PLC0415

            probe_dsn(settings.dsn())
            return f"Bağlantı UĞURLUDUR — {settings.username}@{settings.host}:{settings.port}"

        self._run(screen, job, name="RECOVERY_TEST")

    def _on_save(self, screen: Any, values: dict[str, str]) -> None:
        settings = self._settings_from(values)
        callback = self._on_saved

        def job() -> object:
            from src.infrastructure.config.connection_file import save_settings  # noqa: PLC0415

            target = save_settings(settings)
            return f"Yadda saxlanıldı: {target}"

        self._run(screen, job, name="RECOVERY_SAVE")
        if callback is not None:
            callback()

    def _on_check(self, screen: Any, values: dict[str, str]) -> None:
        settings = self._settings_from(values)

        def job() -> object:
            import psycopg  # noqa: PLC0415

            from src.infrastructure.persistence.provisioning import (  # noqa: PLC0415
                existing_tables,
                expected_tables,
                missing_tables,
            )

            with psycopg.connect(settings.dsn(), connect_timeout=15) as conn, conn.cursor() as cur:
                existing = existing_tables(cur)
            missing = missing_tables(expected=expected_tables(), existing=existing)
            if not missing:
                return f"Bütün cədvəllər yerindədir ({len(existing)} cədvəl)."
            preview = ", ".join(missing[:_PREVIEW_LIMIT])
            suffix = "…" if len(missing) > _PREVIEW_LIMIT else ""
            return f"ÇATIŞAN {len(missing)} cədvəl: {preview}{suffix}"

        self._run(screen, job, name="RECOVERY_TABLES")

    def _on_provision(self, screen: Any, values: dict[str, str]) -> None:
        settings = self._settings_from(values)
        elevated = values.get("service_role", "")
        confirmation = values.get("confirmation", "")

        def job() -> object:
            import psycopg  # noqa: PLC0415

            from src.infrastructure.config.connection_file import (  # noqa: PLC0415
                ConnectionSettings,
            )
            from src.infrastructure.persistence.provisioning import (  # noqa: PLC0415
                inspect_database,
                provision,
            )

            target = settings
            if elevated:
                target = ConnectionSettings(
                    host=settings.host,
                    port=settings.port,
                    database=settings.database,
                    username=settings.username,
                    password=elevated,
                )

            # `autocommit=True` MƏCBURİDİR: fayllarda ÖZ `BEGIN;`/`COMMIT;`
            # cütü var (bax `provisioning.provision`).
            with (
                psycopg.connect(target.dsn(), connect_timeout=30, autocommit=True) as conn,
                conn.cursor() as cur,
            ):
                state = inspect_database(cur)
                if state.requires_confirmation and not state.accepts(confirmation):
                    rows = ", ".join(f"{name} ({count})" for name, count in state.populated_tables)
                    return (
                        f"DİQQƏT: bu bazada artıq məlumat var — {rows}. "
                        "Davam etmək data itkisinə səbəb ola bilər. "
                        "Təsdiq üçün «QUR» sözünü yazıb yenidən basın.",
                        True,
                    )
                report = provision(cur, confirmation=confirmation)

            if report.error:
                return (f"Quruluş DAYANDI — {report.error}", False)
            if report.missing_after:
                names = ", ".join(report.missing_after[:_PREVIEW_LIMIT])
                return (
                    f"Quruluş bitdi, lakin {len(report.missing_after)} cədvəl çatışır: {names}",
                    False,
                )
            return (
                f"HAZIRDIR — {len(report.applied)} miqrasiya tətbiq olundu, "
                f"{len(report.skipped)} artıq mövcud idi. İndi tətbiqi yenidən başladın.",
                False,
            )

        self._run(screen, job, name="RECOVERY_PROVISION")
        # Açar EKRANDAN dərhal silinir — nəticə gözlənilərkən də görünməməlidir.
        screen.clear_service_role()

    # ------------------------------ qovluqlar --------------------------------- #

    def _open_logs(self) -> None:
        from src.shared.data_paths import default_log_dir  # noqa: PLC0415

        _reveal(default_log_dir())

    def _open_config(self) -> None:
        from src.infrastructure.config.connection_file import (  # noqa: PLC0415
            connection_file_path,
        )

        _reveal(connection_file_path().parent)


def _reveal(path: Path) -> None:
    """Qovluğu sistem fayl menecerində açır.

    `QDesktopServices` işlədilir, `explorer.exe` YOX: birincisi Qt-nin öz
    platformalararası yoludur və `subprocess` açmır — yəni paketlənmiş
    tətbiqdə antivirus evristikasına düşmür (SEC-027 ilə eyni məntiq).
    """
    from PySide6.QtCore import QUrl  # noqa: PLC0415
    from PySide6.QtGui import QDesktopServices  # noqa: PLC0415

    with suppress(OSError):
        path.mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


__all__ = [
    "SWITCH_DB_FLAG",
    "RecoveryConsoleController",
    "describe_failure",
    "diagnostics",
    "may_open",
]
