"""ERP / 1C Server panelinin YAZI yolu — `ErpConnectionWizardUseCase` (bölmə 7).

──────────────────────────────────────────────────────────────────────────────
KREDENSİAL EKRANA DA, JURNALA DA DÜŞMÜR (SEC-013)
──────────────────────────────────────────────────────────────────────────────
Şifrə YALNIZ iki yerdə yaşayır: sihirbazdakı `QLineEdit` (maskalanmış) və
`ErpServerDraft` (işlək yaddaş). Kontroller onu heç bir jurnala, heç bir
`extra=` sözlüyünə və heç bir ekran mətninə ötürmür. Audit görünüşü domendə
həll olunub — `ErpServerDraft.auditable()` şifrəni QƏSDƏN kənarda saxlayır və
use case məhz onu yazır. Ona görə burada "audit üçün sahə yığmaq" kimi bir
addım YOXDUR: onu əlavə etsəydik, SEC-013-ün tək qapısını yan keçmiş olardıq.

Redaktə zamanı şifrə ekrana GERİ QAYTARILMIR — o, `erp_servers` cədvəlində
AES-256-GCM ilə şifrələnib və `ErpServer` oxu-modeli onu ümumiyyətlə daşımır.
İstifadəçi onu yenidən yazır; bu, əlavə yük deyil, qorumanın nəticəsidir.

──────────────────────────────────────────────────────────────────────────────
YADDA SAXLAMA TESTDƏN KEÇİR — KONTROLLER TESTİ YAN KEÇMİR
──────────────────────────────────────────────────────────────────────────────
`save_new()` / `save_existing()` `_require_successful_test()` çağırır, yəni
uğursuz test halında sətir YAZILMIR (spesifikasiya: "yeni ayar yalnız test
uğurlu olduqdan sonra aktivləşir"). Kontroller ayrıca "test etdim, indi
saxlayıram" məntiqi qurmur — həmin qapı use case-in içindədir və orada
qalmalıdır.

──────────────────────────────────────────────────────────────────────────────
BAĞLANTI TESTİ SİNXRONDUR — MƏHDUDİYYƏT AÇIQ YAZILIR
──────────────────────────────────────────────────────────────────────────────
Layihədə GUI üçün fon-işçi (QThread/QRunnable) naxışı YOXDUR; yeganə fon
mexanizmi `QTimer`-dir (`app._start_upload_timer`) və o, nəticəsi gözlənilməyən
işlər üçündür. Test isə nəticəni DƏRHAL göstərməlidir, ona görə burada sinxron
çağırılır və gözləmə kursoru qoyulur. Donma HƏDDİ VAR: `OneCConnector` HTTP
taymauta bağlıdır (`DEFAULT_TIMEOUT_SECONDS`), yəni pəncərə sonsuza qədər
kilidlənmir. Yeni bir sap naxışı icad etmək bu partiyanın hüdudundan
kənardır və ayrıca qərar tələb edir.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_d import ErpServersScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: `v_erp_server_health.health` → ekranın tanıdığı status mətni.
#: Açarlar `ErpServersScreen._STATUS_TONES`-dandır; naməlum dəyər neytral
#: nişan alır və gizlədilmir.
_STATUS_TEXT: dict[str, str] = {
    "HEALTHY": "Aktiv",
    "DEGRADED": "Gecikmə yüksəkdir",
    "STALE": "Gecikmə yüksəkdir",
    "NEVER_SYNCED": "Bağlantı yoxdur",
    "INACTIVE": "Deaktiv",
}


class ErpServersController:
    """1C server panelini `ErpConnectionWizardUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor
        #: server adı → `ErpServerId` (ekran yalnız ADI yayır).
        self._servers: dict[str, Any] = {}

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: ErpServersScreen) -> None:
        screen.create_requested.connect(lambda: self._open_wizard(screen, server_name=None))
        screen.server_selected.connect(lambda name: self._open_wizard(screen, server_name=name))
        screen.test_all_requested.connect(lambda: self._on_test_all(screen))
        self.refresh(screen)

    def refresh(self, screen: ErpServersScreen) -> None:
        """Server siyahısını, xəritələməni və son sinxronizasiyanı oxuyur.

        ──────────────────────────────────────────────────────────────────────
        SİYAHI BİRBAŞA OXUNUR, SƏLAHİYYƏT İSƏ USE CASE-DƏN GƏLİR
        ──────────────────────────────────────────────────────────────────────
        `ErpConnectionWizardUseCase`-də "serverləri sadala" metodu YOXDUR və
        onu əlavə etmək use case-i göstəriş vasitəsinə çevirərdi (eyni əsas
        `screen_data._fines`-də izah olunub). Lakin ekran icazəsiz AÇILMAMALIDIR,
        ona görə `mappings_for()` ƏVVƏL çağırılır: o, `can_manage_erp_servers`
        qapısından keçir və icazə yoxdursa istisna atır — yəni siyahı sorğusu
        ümumiyyətlə icra olunmur.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                mapping = session.erp_connections.mappings_for(actor=self._actor, now=_now())
                servers = _server_rows(session)
        except KompasOSError as error:
            screen.show_error(title="Panel açıla bilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("ERP_SERVERS_LOAD_FAILED")
            screen.show_error(
                title="Panel açıla bilmədi",
                message="Server siyahısı oxuna bilmədi. Yenidən cəhd edin.",
            )
            return

        self._servers = {str(row["server_name"]): row["id"] for row in servers}

        # Açarlar ekranın FAKTİKİ oxuduqlarıdır: `name`, `address`, `stores`,
        # `latency`, `status` — maket yolundakı `preview_data.ERP_SERVERS` ilə
        # EYNİ dəst (CLAUDE.md bölmə 6).
        screen.set_servers(
            [
                {
                    "name": str(row["server_name"]),
                    # ŞİFRƏ YOXDUR: yalnız ünvan göstərilir (SEC-013).
                    "address": f"{row['host']}:{row['port']}",
                    "stores": f"{int(row['mapped_stores'] or 0)} mağaza",
                    "latency": _latency_text(row),
                    "status": _status_text(row),
                }
                for row in servers
            ],
            mapped_stores=len(mapping),
        )
        screen.set_mapping(
            [(link.store_name, link.server_name) for link in mapping],
            note=_mapping_note(len(mapping), len(servers)),
        )
        screen.set_last_sync(
            [
                (
                    str(row["server_name"]),
                    _sync_text(row),
                    "success" if row["last_successful_sync"] is not None else "danger",
                )
                for row in servers
            ]
        )

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_test_all(self, screen: ErpServersScreen) -> None:
        """«Hamısını Yoxla» — sağlamlıq görünüşünü YENİDƏN oxuyur.

        ──────────────────────────────────────────────────────────────────────
        NİYƏ HƏR SERVERƏ AYRICA TEST GÖNDƏRİLMİR
        ──────────────────────────────────────────────────────────────────────
        `ErpConnectionWizardUseCase.test_connection()` YALNIZ `ErpServerDraft`
        qəbul edir, yəni ŞİFRƏ tələb edir — saxlanmış server üçün isə şifrə
        şifrələnmiş formadadır və oxu-modelində (`ErpServer`) YOXDUR (SEC-013).
        Saxlanmış serveri test edən bir metod use case-də MÖVCUD DEYİL; onu
        burada, konnektor fabrikini birbaşa çağıraraq qurmaq səlahiyyət
        yoxlamasını və audit yazısını yan keçmək olardı.

        `v_erp_server_health` isə sinxronizasiya worker-inin REAL nəticələrini
        saxlayır — yəni bu düymənin verə biləcəyi ən dürüst cavab həmin
        nəticələri yenidən oxumaqdır.
        """
        self.refresh(screen)

    def _open_wizard(self, screen: ErpServersScreen, *, server_name: str | None) -> None:
        """Yeni server / mövcud serverin redaktəsi — eyni sihirbaz.

        Redaktədə şifrə sahəsi BOŞ açılır (bax modul başlığı) və istifadəçi
        onu yenidən yazır; `save_existing()` onsuz da testdən keçirir.
        """
        from src.presentation.screens.group_d import ServerConnectionWizard  # noqa: PLC0415

        server_id = self._servers.get(server_name or "")
        if server_name is not None and server_id is None:
            screen.show_error(
                title="Server tapılmadı",
                message="Bu server artıq dəyişdirilib. Siyahı yenilənir.",
            )
            self.refresh(screen)
            return

        wizard = ServerConnectionWizard(screen.theme, parent=screen)
        wizard.test_requested.connect(lambda payload: self._on_test(wizard, payload))
        wizard.saved.connect(lambda payload: self._on_save(screen, payload, server_id=server_id))
        wizard.exec()

    def _on_test(self, wizard: Any, payload: Any) -> None:
        """«Bağlantını Yoxla» — nəticə sihirbazın öz sahəsində göstərilir.

        Nəticə mətni `ConnectionTestResult.message`-dir və o, QƏSDƏN
        texniki-olmayan dildədir (bölmə 7). Texniki səbəb (`detail`) yalnız
        `app.log`-a gedir — ekranda göstərmək istifadəçiyə kömək etməzdi və
        bəzən host/istifadəçi adı kimi məlumat sızdırardı.
        """
        draft = _draft_from(payload)
        if draft is None:
            wizard.set_test_result(ok=False, message="Ünvan və baza adı doldurulmalıdır.")
            return

        with _busy_cursor():
            try:
                with self._context.session(user_id=self._actor.id) as session:
                    result = session.erp_connections.test_connection(
                        actor=self._actor, draft=draft, now=_now()
                    )
            except KompasOSError as error:
                wizard.set_test_result(ok=False, message=error.user_message)
                return
            except Exception:
                # `detail` JURNALA getmir: istisna mətnində DSN/şifrə ola
                # bilər, ona görə yalnız istisna TİPİ qeyd olunur.
                _error_log.exception("ERP_TEST_FAILED")
                wizard.set_test_result(
                    ok=False, message="Bağlantı yoxlanıla bilmədi. Yenidən cəhd edin."
                )
                return

        wizard.set_test_result(ok=result.ok, message=result.message)

    def _on_save(self, screen: ErpServersScreen, payload: Any, *, server_id: Any) -> None:
        draft = _draft_from(payload)
        if draft is None:
            screen.show_error(
                title="Forma tamamlanmayıb",
                message="Server adı, ünvan və baza adı doldurulmalıdır.",
            )
            return

        with _busy_cursor():
            try:
                with self._context.session(user_id=self._actor.id) as session:
                    self._persist(session, draft, server_id=server_id)
                    session.commit()
            except KompasOSError as error:
                # UĞURSUZ TEST DƏ BURAYA DÜŞÜR (`ConnectionNotVerifiedError`):
                # sətir YAZILMIR və istifadəçi səbəbi görür.
                screen.show_error(title="Server saxlanmadı", message=error.user_message)
                return
            except Exception:
                _error_log.exception("ERP_SERVER_SAVE_FAILED")
                screen.show_error(
                    title="Server saxlanmadı",
                    message="Konfiqurasiya yazılmadı. Yenidən cəhd edin.",
                )
                return

        self.refresh(screen)

    def _persist(self, session: Session, draft: Any, *, server_id: Any) -> None:
        if server_id is None:
            session.erp_connections.save_new(actor=self._actor, draft=draft, now=_now())
            return
        session.erp_connections.save_existing(
            actor=self._actor, server_id=server_id, draft=draft, now=_now()
        )


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _now() -> Any:
    from datetime import UTC, datetime  # noqa: PLC0415

    return datetime.now(UTC)


class _busy_cursor:  # noqa: N801 — kontekst meneceri, sinif deyil
    """Uzun sürən sinxron çağırış üçün gözləmə kursoru.

    Fon-işçi ƏVƏZİ DEYİL (bax modul başlığı): pəncərə yenə cavab vermir,
    lakin istifadəçi tətbiqin çökmədiyini GÖRÜR. Kursor `finally`-də HƏR
    HALDA geri qaytarılır — əks halda bir istisna bütün örtüyü qum saatı
    ilə qoyardı.
    """

    def __enter__(self) -> None:
        from PySide6.QtCore import Qt  # noqa: PLC0415
        from PySide6.QtWidgets import QApplication  # noqa: PLC0415

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def __exit__(self, *_exc: object) -> None:
        from PySide6.QtWidgets import QApplication  # noqa: PLC0415

        QApplication.restoreOverrideCursor()


def _draft_from(payload: Any) -> Any:
    """Sihirbaz formasını `ErpServerDraft`-a çevirir — məcburi sahə boşdursa `None`.

    Çevirmə BURADA edilir, ekranda YOX: ekran domen tiplərini tanımır (bax
    `controllers/__init__.py`). Şifrə boş ola bilər — bəzi 1C quraşdırmaları
    Windows autentifikasiyası ilə işləyir və testin nəticəsi onsuz da bunu
    göstərəcək; onu burada rədd etsəydik, işləyən konfiqurasiyanı bloklamış
    olardıq.
    """
    # `_split_host_port` — eyni «host:port» parsingi ilk quraşdırma
    # sihirbazında da işlədilir; ikinci nüsxə yazsaydıq, biri düzəldiləndə
    # digəri arxada qalardı.
    from src.domain.value_objects.erp import ErpServerDraft  # noqa: PLC0415
    from src.presentation.composition import _split_host_port  # noqa: PLC0415

    if not isinstance(payload, dict):  # pragma: no cover - tip qoruyucusu
        return None

    name = str(payload.get("name", "")).strip()
    raw_host = str(payload.get("host", "")).strip()
    infobase = str(payload.get("database", "")).strip()
    if not name or not raw_host or not infobase:
        return None

    host, port = _split_host_port(raw_host)
    return ErpServerDraft(
        server_name=name,
        host=host,
        port=port,
        username=str(payload.get("username", "")).strip(),
        password=str(payload.get("password", "")),
        infobase=infobase,
    )


def _server_rows(session: Session) -> list[Any]:
    """Server siyahısı — konfiqurasiya + sağlamlıq BİR sorğuda.

    `erp_servers` ilə `v_erp_server_health` birləşdirilir, çünki ekranın bir
    sətrində hər ikisindən sahə var (ünvan konfiqurasiyadan, gecikmə və
    sağlamlıq görünüşdən). İki ayrı sorğu eyni anın iki fərqli şəklini verə
    bilərdi. `password_encrypted` sütunu SEÇİLMİR (SEC-013).
    """
    return session.uow.connection.execute(
        """
        SELECT s.id, s.server_name, s.host, s.port, s.status, s.last_successful_sync,
               h.health, h.sync_delay_seconds, h.mapped_stores
          FROM erp_servers s
          JOIN v_erp_server_health h ON h.server_id = s.id
         WHERE s.tenant_id = %s
         ORDER BY s.server_name
        """,
        (session.tenant_id,),
    ).fetchall()


def _status_text(row: Any) -> str:
    """Cədvəldəki status nişanı — `v_erp_server_health.health` əsasında."""
    health = str(row["health"])
    return _STATUS_TEXT.get(health, health)


def _latency_text(row: Any) -> str:
    """Sinxron gecikməsi — deaktiv serverdə gecikmənin mənası yoxdur."""
    if str(row["health"]) == "INACTIVE":
        return "—"
    from src.presentation.controllers.screen_data import _sync_delay_text  # noqa: PLC0415

    return _sync_delay_text(row["sync_delay_seconds"])


def _sync_text(row: Any) -> str:
    moment = row["last_successful_sync"]
    return f"{moment:%H:%M}" if moment is not None else "heç vaxt"


def _mapping_note(mapped: int, servers: int) -> str:
    """Xəritələmə kartının altındakı izah.

    Xəritə BOŞDURSA bu, ən vacib xəbərdarlıqdır: gələn hər 1C sənədi
    `UNASSIGNED` olur və «Şübhəli Satışlar» növbəsinə düşür (bax
    `ErpConnectionWizardUseCase.mappings_for` docstring-i).
    """
    if servers == 0:
        return "Hələ heç bir 1C serveri əlavə edilməyib."
    if mapped == 0:
        return (
            "Heç bir mağaza serverə bağlanmayıb — gələn bütün satışlar "
            "«Şübhəli Satışlar» növbəsinə düşəcək."
        )
    return f"{mapped} mağaza xəritələnib."


__all__ = ["ErpServersController"]
