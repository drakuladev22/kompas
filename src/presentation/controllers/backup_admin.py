"""Ehtiyat Nüsxə / Bərpa ekranının YAZI yolu — `BackupAccessUseCase` (bölmə 7).

──────────────────────────────────────────────────────────────────────────────
BƏRPA İKİ QAPIDAN KEÇİR — HEÇ BİRİ YAN KEÇİLMİR
──────────────────────────────────────────────────────────────────────────────
1. İNSAN QAPISI — `RestoreConfirmDialog`: istifadəçi nüsxə TARİXİNİ ƏL İLƏ
   yazmalıdır. "Bəli" düyməsinə refleks olaraq basmaq mümkün deyil; dialoq
   yalnız mətn üst-üstə düşdükdə `confirmed` siqnalını yayır.
2. PROQRAM QAPISI — `NightlyBackupService.restore()`: `confirmation` arqumenti
   `«BƏRPA ET»` ifadəsinə bərabər olmalıdır. `bool` bayraq səhvən `True`
   ötürülə bilərdi, yazılmış ifadə isə təsadüfən yaranmır.

Kontroller birinci qapını AÇIR (dialoqu göstərir) və yalnız `confirmed`
siqnalından SONRA ikinci qapının açarını ötürür. `restore_requested`
siqnalından birbaşa bərpa çağırsaydıq, insan qapısı tamamilə itərdi — ekranda
bir klik bütün tenant-ın son günlərini silərdi.

──────────────────────────────────────────────────────────────────────────────
AUDİT USE CASE-DƏDİR
──────────────────────────────────────────────────────────────────────────────
`create_now()` `BACKUP_CREATED_MANUALLY`, `restore()` isə HƏM ƏVVƏL
(`BACKUP_RESTORE_REQUESTED`), HƏM SONRA (`BACKUP_RESTORE_COMPLETED`) yazır —
uğursuz bərpa cəhdi də araşdırılası hadisədir. Kontrollerdə ikinci audit
çağırışı hər əməliyyatı iki dəfə jurnallayardı.

──────────────────────────────────────────────────────────────────────────────
HƏDƏF DSN AÇIQ SEÇİLİR
──────────────────────────────────────────────────────────────────────────────
`restore(target_dsn=...)` məcburi parametrdir və bu, qəsdəndir: defolt olaraq
cari bazanı götürsəydi, bir sətir kod istehsalat bazasının üzərinə yazardı
(bax servisin docstring-i). Burada dəyər `DATABASE_URL`-dən gəlir — yəni
"hazırda işlədiyim baza" — və boşdursa əməliyyat BAŞLAMIR.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext
    from src.presentation.screens.group_d import BackupScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Cədvəldəki tarix formatı — dialoqdakı təsdiq mətni ilə EYNİ olmalıdır,
#: çünki istifadəçi məhz bu sətri əl ilə köçürür.
DATE_FORMAT = "%d.%m.%Y %H:%M"

#: Saxlama kartındakı "ümumi həcm" göstəricisi.
#:
#: Bu, ÖLÇÜLƏN dəyər deyil, ekranın nisbət göstərə bilməsi üçün lazım olan
#: məxrəcdir: `set_storage(used, total)` iki ədəd tələb edir və faktiki disk
#: tutumunu oxuyan mənbə tətbiqdə YOXDUR. Sabit məxrəc ən azı "nüsxələr nə
#: qədər yer tutur" sualına dürüst cavab verir; uydurma "boş yer" rəqəmi isə
#: yanlış təhlükəsizlik hissi yaradardı.
STORAGE_BUDGET_GB = 80.0

#: `backup_records.backup_type` → ekran mətni. Açarlar DB `CHECK` şərtindəki
#: dəyərlərdir; naməlum növ gizlədilmir, öz kodu ilə göstərilir.
_KIND_TEXT: dict[str, str] = {
    "NIGHTLY_AUTO": "Avtomatik",
    "MANUAL": "Manual",
    "PRE_MIGRATION": "Keçid öncəsi",
}


class BackupAdminController:
    """Ehtiyat nüsxə ekranını `BackupAccessUseCase`-ə bağlayır."""

    def __init__(
        self, context: ApplicationContext, actor: Employee, *, executor: Any = None
    ) -> None:
        self._context = context
        self._actor = actor
        #: cədvəldəki tarix mətni → `BackupRecord` (ekran yalnız MƏTN yayır).
        self._points: dict[str, Any] = {}
        #: Fon icraçısı — istehsalatda Qt hovuzu, testlərdə `InlineExecutor`.
        self._executor = executor
        #: Qaçan işə istinad: nəticə gəlməmiş toplanarsa siqnal itərdi.
        self._task: Any = None

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: BackupScreen) -> None:
        screen.backup_now_requested.connect(lambda: self._on_create(screen))
        screen.restore_requested.connect(lambda date: self._on_restore_requested(screen, date))
        self.refresh(screen)

    def refresh(self, screen: BackupScreen) -> None:
        """Bərpa nöqtələrini yenidən oxuyur."""
        try:
            with self._context.session(user_id=self._actor.id) as session:
                points = session.backups.restore_points(
                    tenant_id=session.tenant_id, actor=self._actor
                )
        except KompasOSError as error:
            screen.show_error(title="Siyahı açıla bilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("BACKUP_LIST_FAILED")
            screen.show_error(
                title="Siyahı açıla bilmədi",
                message="Ehtiyat nüsxə siyahısı oxuna bilmədi. Yenidən cəhd edin.",
            )
            return

        self._points = {_date_text(point): point for point in points}
        # KÖHNƏ YAZI-XƏTASI BANNERİ TƏMİZLƏNİR (QA-FULL FAZA 3): uğurlu oxuma
        # siyahının HAZIRKI vəziyyətinin düzgün olduğunu sübut edir — əvvəlki
        # uğursuz nüsxə/bərpa cəhdinin xəbərdarlığı artıq doğru deyil (naxış
        # `plugin_page.py::_show_content`).
        _clear_section_errors(screen)
        screen.set_schedule_label(_schedule_label(points))
        # Açarlar ekranın FAKTİKİ oxuduqlarıdır: `date`, `size`, `kind`,
        # `status`, `ok` — maket yolundakı `preview_data.BACKUPS` ilə EYNİ.
        screen.set_backups(
            [
                {
                    "date": date_text,
                    "size": f"{point.size_mb:g} MB",
                    "kind": _kind_text(point),
                    "status": "Müddəti bitib" if point.is_expired else "Uğurlu",
                    # MÜDDƏTİ BİTMİŞ nüsxədən bərpa düyməsi GÖSTƏRİLMİR:
                    # fayl artıq silinmiş ola bilər (saxlama müddəti) və
                    # düymə istifadəçini boş yerə ümidləndirərdi.
                    "ok": "0" if point.is_expired else "1",
                }
                for date_text, point in self._points.items()
            ]
        )
        used_mb = sum(point.size_mb for point in points)
        screen.set_storage(round(used_mb / 1024, 1), STORAGE_BUDGET_GB, count=len(points))

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_create(self, screen: BackupScreen) -> None:
        """«İndi Ehtiyat Nüsxə Al» — planlaşdırılmış gecə nüsxəsindən ƏLAVƏ.

        İŞ FON SAPINDADIR: `create_now` `pg_dump` prosesini işə salır və o,
        baza həcmindən asılı olaraq DƏQİQƏLƏRLƏ çəkir. GUI sapında icra
        olunanda pəncərə həmin müddət boyu «Cavab vermir» olurdu və admin
        proqramı bağlamağa çalışırdı — məhz nüsxə yazılarkən.
        """

        def job() -> object:
            with self._context.session(user_id=self._actor.id) as session:
                session.backups.create_now(tenant_id=session.tenant_id, actor=self._actor)
                session.commit()
            return None

        self._run(
            screen,
            job,
            name="BACKUP_CREATE",
            title="Nüsxə yaradılmadı",
            log_key="BACKUP_CREATE_FAILED",
        )

    def _on_restore_requested(self, screen: BackupScreen, date_text: str) -> None:
        """İNSAN QAPISI — dialoq açılır, bərpa HƏLƏ BAŞLAMIR (bax modul başlığı)."""
        from src.presentation.screens.group_d import RestoreConfirmDialog  # noqa: PLC0415

        if date_text not in self._points:
            # BANNER YENİLƏNMƏ İLƏ UDULURDU (QA-FULL FAZA 3 davamı) — eyni
            # qüsur `announcements.py::_on_withdraw`-da tapılmışdı: `show_error(...)`
            # ardınca DƏRHAL `self.refresh(screen)` gəlirdi, `refresh()` isə
            # uğurla qayıdanda `set_backups()` → `show_content()` zəncirini işə salır
            # və `ContentSwitcher`-i heç bir render arası olmadan «content»-ə
            # qaytarır. Nəticə: istifadəçi HEÇ BİR mesaj görmür, ekran sadəcə
            # səbəbsiz yenilənir. Meyar sabitdir: yenilənmə yolu switcher-i
            # «content»-ə qaytarırsa — qüsur. Yenilənmə indi `on_retry` ilə
            # istifadəçinin öz qərarıdır.
            screen.show_error(
                title="Bərpa nöqtəsi tapılmadı",
                message="Siyahı köhnəlib. «Yenidən Cəhd Et» onu yeniləyir.",
                on_retry=lambda: self.refresh(screen),
            )
            return

        dialog = RestoreConfirmDialog(screen.theme, backup_date=date_text, parent=screen)
        # YALNIZ `confirmed` bərpanı işə salır: dialoq bağlansa və ya mətn
        # uyğun gəlməsə siqnal ÜMUMİYYƏTLƏ yayılmır.
        dialog.confirmed.connect(lambda confirmed_date: self._restore(screen, confirmed_date))
        dialog.exec()

    def _restore(self, screen: BackupScreen, date_text: str) -> None:
        from src.infrastructure.backup.service import RESTORE_CONFIRMATION  # noqa: PLC0415

        point = self._points.get(date_text)
        if point is None:  # pragma: no cover - dialoq yalnız mövcud tarixi yayır
            return

        target_dsn = os.environ.get("DATABASE_URL", "").strip()
        if not target_dsn:
            # Hədəf olmadan bərpa BAŞLAMIR: boş DSN ilə `pg_restore` cari
            # bağlantıya düşə bilməz, lakin səbəb istifadəçiyə aydın
            # deyilməlidir — texniki xəta mətni burada kömək etməz.
            screen.show_error(
                title="Bərpa başlamadı",
                message="Hədəf baza ünvanı (`DATABASE_URL`) təyin edilməyib.",
            )
            return

        def job() -> object:
            with self._context.session(user_id=self._actor.id) as session:
                session.backups.restore(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    record=point.record,
                    target_dsn=target_dsn,
                    # PROQRAM QAPISI: ifadə sabitdən gəlir, istifadəçidən yox
                    # — insan təsdiqi ARTIQ dialoqda alınıb (bax modul başlığı).
                    confirmation=RESTORE_CONFIRMATION,
                )
                session.commit()
            return None

        # Bərpa nüsxə almaqdan da uzundur (`pg_restore` + indekslərin yenidən
        # qurulması) — fon sapı burada daha da vacibdir.
        self._run(
            screen,
            job,
            name="BACKUP_RESTORE",
            title="Bərpa tamamlanmadı",
            log_key="BACKUP_RESTORE_FAILED",
        )

    def _run(
        self,
        screen: BackupScreen,
        job: Any,
        *,
        name: str,
        title: str,
        log_key: str,
    ) -> None:
        """Ortaq icra qabığı — iş fonda, nəticə GUI sapında.

        Uğurda siyahı YENİDƏN oxunur: nüsxə/bərpa `backup_records` sətrini
        dəyişir və köhnə cədvəl istifadəçini «heç nə olmadı» qənaətinə
        gətirərdi.

        ──────────────────────────────────────────────────────────────────────
        UĞURSUZLUQDA `show_error()` İŞLƏDİLMİR (QA-FULL FAZA 3)
        ──────────────────────────────────────────────────────────────────────
        Bir `pg_dump`/`pg_restore` cəhdinin uğursuzluğu TRANZİTDİR — siyahı,
        Saxlama kartı və Cədvəl kartı hələ də etibarlıdır. `show_error()`
        HAMISINI xəta vəziyyəti ilə əvəz edirdi (naxış `plugin_page.py::
        _show_failure`, `drive_connection.py` başlığındakı eyni səhv). Əvəzinə
        `set_section_error(title)` — mövcud siyahı yerində qalır, xəbərdarlıq
        onun ÜSTÜNDƏ görünür. Tam səbəb `error.log`-a yazılır; uğurlu YENİDƏN
        oxuma banneri `refresh()`-də təmizləyir.
        """
        from src.presentation.background_task import run_job  # noqa: PLC0415

        def failed(error: BaseException) -> None:
            if isinstance(error, KompasOSError):
                _error_log.warning(log_key, extra={"reason": error.user_message})
                _section_error(screen, title)
                return
            _error_log.error(log_key, exc_info=error)
            _section_error(screen, title)

        self._task = run_job(
            job,
            on_success=lambda _result: self.refresh(screen),
            on_failure=failed,
            owner=screen,
            name=name,
            executor=self._executor,
        )


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _date_text(point: Any) -> str:
    """Cədvəldəki (və təsdiq dialoqundakı) tarix mətni.

    Format İKİ yerdə eyni olmalıdır: istifadəçi onu cədvəldən oxuyub dialoqa
    əl ilə köçürür. Fərqli olsaydı, təsdiq HEÇ VAXT uğurlu alınmazdı.
    """
    return f"{point.record.created_at:{DATE_FORMAT}}"


def _kind_text(point: Any) -> str:
    """`backup_type` → ekran mətni; naməlum növ öz kodu ilə göstərilir."""
    raw = str(point.record.backup_type)
    return _KIND_TEXT.get(raw, raw)


def _schedule_label(points: list[Any]) -> str:
    """Alət panelindəki izah — sonuncu nüsxənin insan-oxunaqlı etiketi.

    Cədvəl vaxtı (02:00) planlayıcının konfiqurasiyasındadır və tətbiq onu
    OXUMUR; ona görə burada "hər gecə 02:00" kimi bir söz VERİLMİR — əvəzinə
    FAKTİKİ sonuncu nüsxə göstərilir.
    """
    if not points:
        return "Hələ ehtiyat nüsxə alınmayıb."
    return f"Sonuncu nüsxə: {points[0].label_az}"


def _section_error(screen: Any, label: str) -> None:
    """`Screen.set_section_error` — YALNIZ metodu daşıyan ekranlarda.

    NİYƏ `getattr`, NİYƏ BİRBAŞA ÇAĞIRIŞ DEYİL (naxış `screen_data.
    report_section_error`): `screen: BackupScreen` alsa da, duck-typing
    test saxtaları (məs. `tests/unit/test_infrastructure_controllers.py`)
    `Screen` bazasından TÖRƏMİR və bu metodu daşımır. Birbaşa çağırış
    `AttributeError` atardı — xəbərdarlığı GÖRÜNƏN etmək cəhdi ikinci bir
    xətaya çevrilərdi.
    """
    reporter = getattr(screen, "set_section_error", None)
    if reporter is not None:
        reporter(label)


def _clear_section_errors(screen: Any) -> None:
    """`Screen.clear_section_errors` — eyni `getattr` ehtiyatı (bax `_section_error`)."""
    clearer = getattr(screen, "clear_section_errors", None)
    if clearer is not None:
        clearer()


__all__ = ["DATE_FORMAT", "STORAGE_BUDGET_GB", "BackupAdminController"]
