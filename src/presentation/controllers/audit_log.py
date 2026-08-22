"""Audit Jurnalının OXU yolu — süzgəc və səhifələmə.

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA KONTROLLER, NİYƏ `screen_data.py` DEYİL
──────────────────────────────────────────────────────────────────────────────
`screen_data.py` bir dəfəlik doldurmadır: `populate()` çağırılır, ekran dolur,
sessiya bağlanır. Audit ekranı isə istifadəçi hər süzgəc dəyişəndə və hər
səhifə düyməsində YENİDƏN oxumalıdır — bu dövrə `populate()`-ın tək
çağırışından uzun yaşayır. Layihədə eyni səbəblə `camera_queue.py`,
`fine_entry.py` və `root_control.py` öz kontrollerlərini daşıyır (CLAUDE.md
bölmə 6).

Ekran YALNIZ OXUYUR, lakin bu, onu `screen_data`-ya aid etmir: meyar
"yazırmı?" deyil, "təkrar oxuyurmu?"-dur.

──────────────────────────────────────────────────────────────────────────────
SÜZGƏC EKRANDAN GƏLİR, LİMİT ROOT-DAN
──────────────────────────────────────────────────────────────────────────────
Səhifə ölçüsü `AuditFilter.limit`-dədir və `search()` onu Root tavanı ilə
(`AUDIT_LOG_MAX_PAGE_SIZE`) kəsir. Kontroller tavanı ÖZÜ oxumur: iki tərəf
ayrı mənbədən oxusaydı, Root tavanı endirəndə ekran "18 səhifə" yazar, baza
isə başqa sayda sətir qaytarardı — səhifələmə düymələri mövcud olmayan
səhifəyə aparardı.

──────────────────────────────────────────────────────────────────────────────
BAXIŞ FAKTI DA AUDİT-LƏNİR
──────────────────────────────────────────────────────────────────────────────
`search()` özü baxışı jurnala yazır, ona görə hər oxuma `commit()` tələb edir
(bax `audit_query` başlığı). Commit unudulsaydı, kim jurnala baxdığı qeydi
sükutla itərdi — audit sisteminin ən həssas izlərindən biri.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.application.use_cases.audit_query import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, AuditFilter
from src.domain.policies import SystemLimitKey
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_d import AuditScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Modul seçicisindəki "hamısı" bəndi — süzgəcə çevrilmir.
ALL_MODULES = "Bütün modullar"

#: İxrac sütunları — `(entry_row` açarı, Excel başlığı)`.
#:
#: Açarlar `entry_row()`-un qaytardıqları ilə EYNİDİR və bu, qəsdəndir: ayrıca
#: sıra qursaydıq, ekranda görünən sütunla fayldakı sütun zamanla ayrılardı və
#: fərq yalnız auditor faylı ekranla tutuşduranda üzə çıxardı.
EXPORT_HEADERS: list[tuple[str, str]] = [
    ("time", "Vaxt"),
    ("user", "İstifadəçi"),
    ("action", "Hərəkət"),
    ("module", "Modul"),
    ("detail", "İzah"),
]


def entry_row(entry: Any) -> dict[str, str]:
    """`AuditEntry` → ekranın gözlədiyi sətir.

    AÇARLAR MAKET YOLU İLƏ EYNİDİR (`preview_data.AUDIT_ENTRIES`): `time`,
    `user`, `action`, `module`, `detail`. Bu funksiya ORTAQ MƏNBƏDİR, çünki
    ilkin doldurma (`screen_data`) və süzülmüş oxuma (bu kontroller) eyni
    formanı verməlidir — iki yerdə ayrı-ayrı yazılsaydı, biri düzələndə
    digəri arxada qalardı və fərq yalnız istehsalatda görünərdi.
    """
    occurred = getattr(entry, "occurred_at", None)
    return {
        "time": occurred.strftime("%d.%m %H:%M") if occurred is not None else "",
        "user": getattr(entry, "actor_name", "") or "",
        "action": getattr(entry, "action", "") or "",
        "module": getattr(entry, "entity_type", "") or "",
        "detail": getattr(entry, "reason", "") or "",
    }


@dataclass(frozen=True)
class _ExportResult:
    """İxracın nəticəsi — yol VƏ neçə sətrin faktiki yazıldığı.

    Yalnız yolu qaytarsaydıq, kəsilmə barədə xəbər verməyin yolu qalmazdı və
    yarımçıq fayl «tam» kimi təqdim olunardı.
    """

    path: Path
    written: int
    total: int


class AuditLogController:
    """Audit ekranının `filters_changed` / `page_changed` siqnallarını bağlayır."""

    def __init__(
        self,
        context: ApplicationContext,
        actor: Employee,
        *,
        executor: Any = None,
    ) -> None:
        self._context = context
        self._actor = actor
        #: Cari süzgəc — səhifə dəyişəndə ŞƏRTLƏR QORUNUR. Səhifə düyməsi
        #: süzgəci sıfırlasaydı, istifadəçi 2-ci səhifəyə keçəndə tamam başqa
        #: dəst görər və səbəbini anlamazdı.
        self._filters: dict[str, Any] = {}
        self._page = 1
        #: Fon işçisinə İSTİNAD: yalnız yerli dəyişən qalsaydı Python onu
        #: nəticə gəlməmiş toplayardı və ixrac SÜKUTLA itərdi.
        self._task: Any = None
        self._executor = executor

    def attach(self, screen: AuditScreen) -> None:
        screen.filters_changed.connect(lambda values: self._on_filters(screen, values))
        screen.page_changed.connect(lambda page: self._on_page(screen, page))
        screen.export_requested.connect(lambda: self._on_export(screen))
        # İLKİN OXUMA: digər üç kontroller (`erp_servers`, `backup_admin`,
        # `exceptions`) `attach()`-in sonunda ilkin doldurma edir, bu isə
        # unudulmuşdu — panel açılanda cədvəl istifadəçi bir filtri toxunana
        # qədər BOŞ qalırdı (QA-FULL FAZA 3).
        self._reload(screen)

    # ------------------------------- ixrac ----------------------------------- #

    def _on_export(self, screen: AuditScreen) -> None:
        """«Excel-ə İxrac Et» — CARİ süzgəcin BÜTÜN nəticəsi.

        ──────────────────────────────────────────────────────────────────────
        DÜYMƏ ƏVVƏL ÖLÜ İDİ
        ──────────────────────────────────────────────────────────────────────
        `export_requested` yayılırdı, lakin heç kim dinləmirdi: auditor
        düyməni basırdı, heç nə olmurdu və o, faylı gözləyirdi. Audit jurnalı
        məhz kənar yoxlamaya təqdim edilmək üçündür — ixracsız o, yalnız
        ekranda qalır.

        ──────────────────────────────────────────────────────────────────────
        SƏHİFƏ YOX, BÜTÜN NƏTİCƏ İXRAC OLUNUR
        ──────────────────────────────────────────────────────────────────────
        Ekranda görünən 50 sətir ixrac edilsəydi, fayl «audit jurnalı» adını
        daşıyıb məzmununu daşımazdı — yoxlayan şəxs fərqi görməzdi, çünki fayl
        tam görünür. Ona görə sorğu `offset=0` və ROOT-un təyin etdiyi ixrac
        tavanı ilə TƏKRARLANIR; süzgəclər isə OLDUĞU KİMİ qalır (ekranda nə
        görünürsə, faylda da o).

        ──────────────────────────────────────────────────────────────────────
        OXU VƏ FAYL YAZISI FON SAPINDADIR (UI-1)
        ──────────────────────────────────────────────────────────────────────
        Min sətirlik `.xlsx` yazmaq saniyələr çəkir. GUI sapında etsəydik,
        panel həmin müddətdə cavabsız qalardı — layihədə artıq düzəldilmiş
        eyni qüsur (Telegram testi, sübut yükləməsi).
        """
        from src.presentation.background_task import run_job  # noqa: PLC0415

        target = self._choose_output_dir(screen)
        if target is None:
            return

        screen.show_loading()
        self._task = run_job(
            lambda: self._write_export(target),
            on_success=lambda path: self._export_finished(screen, path),
            on_failure=lambda error: self._export_failed(screen, error),
            owner=screen,
            name="audit-export",
            executor=self._executor,
        )

    def _choose_output_dir(self, screen: AuditScreen) -> Path | None:
        """Qovluq seçimi — AYRICA metod ki, test onu Qt-siz əvəz edə bilsin."""
        from PySide6.QtWidgets import QFileDialog  # noqa: PLC0415

        selected = QFileDialog.getExistingDirectory(screen, "Audit faylı hara yazılsın?")
        return Path(selected) if selected else None

    def _write_export(self, target: Path) -> _ExportResult:
        """FON SAPI: öz sessiyasını açır, oxuyur və faylı yazır.

        Sessiya BURADA açılır, çağıranınkı ötürülmür — `psycopg` bağlantısı
        sap-təhlükəsiz deyil (naxış `root_control.py::_send_telegram_test`).
        """
        from src.infrastructure.reporting.excel import ExcelReportWriter  # noqa: PLC0415

        with self._context.session(user_id=self._actor.id) as session:
            page = self._search(session, offset=0, limit=self._export_limit(session))
            session.commit()  # ixrac faktı da audit-lənir
            rows = [entry_row(entry) for entry in page.entries]
            total = int(getattr(page, "total", len(rows)))

        # KƏSİLMƏ SÜKUTLA BAŞ VERMİR: fayl «audit jurnalı» adını daşıyır və
        # yarımçıq olduğu bilinməsə, yoxlayan şəxs olmayan sətri «yoxdur»
        # sayardı. Ona görə həm faylın altında, həm bitmə mesajında deyilir.
        truncated = total > len(rows)
        note = f"{len(rows)} sətir — ekrandakı süzgəclərlə EYNİ dəst."
        if truncated:
            note += (
                f" DİQQƏT: süzgəcə {total} sətir uyğun gəlir, fayla yalnız "
                f"{len(rows)} düşdü (ROOT həddi: AUDIT_LOG_MAX_PAGE_SIZE). "
                "Tam dəst üçün süzgəci daraldın."
            )
        note += " Audit qeydləri dəyişdirilə bilməz; bu fayl yalnız nüsxədir."

        path = ExcelReportWriter(output_dir=target).write_table(
            rows,
            headers=EXPORT_HEADERS,
            sheet_title="Audit Jurnalı",
            file_name="Audit_Jurnali.xlsx",
            note=note,
        )
        return _ExportResult(path=path, written=len(rows), total=total)

    def _export_finished(self, screen: AuditScreen, result: Any) -> None:
        self._reload(screen)
        message = f"Fayl yazıldı:\n{result.path}\n\n{result.written} sətir ixrac olundu."
        if result.total > result.written:
            message += (
                f"\nSüzgəcə {result.total} sətir uyğun gəlir — qalanı ROOT həddinə "
                "görə fayla düşmədi. Süzgəci daraldıb təkrar ixrac edin."
            )
        _inform(screen, "İxrac tamamlandı", message)

    def _export_failed(self, screen: AuditScreen, error: BaseException) -> None:
        _error_log.exception("AUDIT_EXPORT_FAILED", extra={"error": str(error)})
        self._reload(screen)
        _inform(
            screen,
            "İxrac alınmadı",
            getattr(error, "user_message", "Fayl yazıla bilmədi — qovluğu yoxlayın."),
        )

    # ------------------------------- hadisələr ------------------------------- #

    def _on_filters(self, screen: AuditScreen, values: dict[str, Any]) -> None:
        """Süzgəc dəyişdi — HƏMİŞƏ birinci səhifəyə qayıdılır.

        Səhifə saxlanılsaydı, 7-ci səhifədə dar bir süzgəc seçən istifadəçi
        boş ekran görərdi (nəticə 2 səhifədir) və bunu "nəticə yoxdur" kimi
        oxuyardı — halbuki nəticə var, sadəcə başqa səhifədədir.
        """
        self._filters = dict(values)
        self._page = 1
        self._reload(screen)

    def _on_page(self, screen: AuditScreen, page: int) -> None:
        self._page = max(1, int(page))
        self._reload(screen)

    # ------------------------------- oxuma ----------------------------------- #

    def _reload(self, screen: AuditScreen) -> None:
        """Süzgəc/səhifə dəyişəndə (yaxud ilkin açılışda) YENİDƏN oxuyur.

        ──────────────────────────────────────────────────────────────────────
        UĞURSUZLUQDA `show_error()` İŞLƏDİLMİR (QA-FULL FAZA 3)
        ──────────────────────────────────────────────────────────────────────
        Bir TRANZİT filtr sorğusu uğursuz olsa da, süzgəc paneli (axtarış,
        modul, tarix) və ƏVVƏLKİ nəticə hələ etibarlıdır. `show_error()`
        `ContentSwitcher`-i TAM xəta vəziyyətinə keçirib süzgəc sahələrini DƏ
        gizlədirdi (naxış `drive_connection.py` başlığında sənədləşdirilmiş
        eyni səhv) — istifadəçi bir hərf də yazmaqla bütün paneli itirirdi.
        Əvəzinə `set_section_error(...)` — cədvəl və süzgəclər YERİNDƏ qalır,
        xəbərdarlıq onların ÜSTÜNDƏ görünür. Uğurlu YENİDƏN oxuma banneri
        aşağıda TƏMİZLƏYİR.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                page = self._search(session)
                session.commit()  # baxış faktı da audit-lənir
        except KompasOSError as exc:
            # SÜKUT QADAĞANDIR: istifadəçi düyməni basıb və nəticə gözləyir.
            _error_log.exception("AUDIT_FILTER_FAILED", extra={"error": str(exc)})
            _section_error(screen, "Audit jurnalı")
            return

        # KÖHNƏ XƏTA BANNERİ TƏMİZLƏNİR: uğurlu oxuma cari nəticənin doğru
        # olduğunu sübut edir (naxış `plugin_page.py::_show_content`).
        _clear_section_errors(screen)
        rows = [entry_row(entry) for entry in page.entries]
        screen.set_entries(rows, result_text=f"{page.total} nəticədən {len(rows)}")
        limit = max(1, page.filters.limit)
        total_pages = max(1, (page.total + limit - 1) // limit)
        screen.set_pagination(self._page, total_pages)

    def _export_limit(self, session: Session) -> int:
        """İxracın sətir tavanı — ROOT-un `AUDIT_LOG_MAX_PAGE_SIZE` açarı.

        `search()` limiti ONSUZ DA bu tavana kəsir (`AuditFilter.normalized`),
        yəni burada daha böyük ədəd yazmaq heç nə dəyişməzdi. Tavanı AÇIQ
        oxumağın səbəbi başqadır: neçə sətrin ixrac olunduğunu istifadəçiyə
        DEYƏ bilmək üçün onu bilməliyik — sükutla kəsilmiş fayl «tam jurnal»
        kimi görünərdi.
        """
        return int(
            session.limits.get_int(
                session.tenant_id,
                SystemLimitKey.AUDIT_LOG_MAX_PAGE_SIZE.value,
                MAX_PAGE_SIZE,
            )
        )

    def _search(
        self, session: Session, *, offset: int | None = None, limit: int | None = None
    ) -> Any:
        use_case = session.audit_query
        # SƏHİFƏ ÖLÇÜSÜ ROOT-DANDIR: `DEFAULT_PAGE_SIZE` yalnız fallback-dır
        # (həqiqi mənbə `system_limits.AUDIT_LOG_DEFAULT_PAGE_SIZE`). Tavanı
        # isə `search()` özü tətbiq edir — burada təkrar oxumaq iki mənbə
        # yaradardı.
        page_size = limit or session.limits.get_int(
            session.tenant_id,
            SystemLimitKey.AUDIT_LOG_DEFAULT_PAGE_SIZE.value,
            DEFAULT_PAGE_SIZE,
        )
        module = str(self._filters.get("module", "") or "")
        return use_case.search(
            tenant_id=session.tenant_id,
            actor=self._actor,
            filters=AuditFilter(
                search=str(self._filters.get("search", "") or ""),
                entity_type=None if module in {"", ALL_MODULES} else module,
                limit=page_size,
                offset=(self._page - 1) * page_size if offset is None else offset,
            ),
        )


def _section_error(screen: Any, label: str) -> None:
    """`Screen.set_section_error` — YALNIZ metodu daşıyan ekranlarda.

    NİYƏ `getattr`, NİYƏ BİRBAŞA ÇAĞIRIŞ DEYİL (naxış `screen_data.
    report_section_error`): `screen: AuditScreen` alsa da, duck-typing
    test saxtaları (məs. `tests/unit/test_dead_signal_wiring.py`) `Screen`
    bazasından TÖRƏMİR və bu metodu daşımır. Birbaşa çağırış `AttributeError`
    atardı — xəbərdarlığı GÖRÜNƏN etmək cəhdi ikinci bir xətaya çevrilərdi.
    """
    reporter = getattr(screen, "set_section_error", None)
    if reporter is not None:
        reporter(label)


def _clear_section_errors(screen: Any) -> None:
    """`Screen.clear_section_errors` — eyni `getattr` ehtiyatı (bax `_section_error`)."""
    clearer = getattr(screen, "clear_section_errors", None)
    if clearer is not None:
        clearer()


def _inform(screen: Any, title: str, message: str) -> None:
    """İzah pəncərəsi — cədvəli BOŞALTMADAN (naxış `profile.py::_inform`)."""
    from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

    box = QMessageBox(screen)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle(title)
    box.setText(message)
    box.exec()


__all__ = ["ALL_MODULES", "EXPORT_HEADERS", "AuditLogController", "entry_row"]
