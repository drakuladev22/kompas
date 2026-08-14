"""Hesabat İxracı ekranının YAZI yolu — kompas1.md Faza 8 (A, D, E, F, G).

CLAUDE.md §6: bu ekran HƏM oxuyur (doğrulama, müqayisə, düzəliş jurnalı), HƏM
yazır (manual düzəliş) — ona görə ÖZ kontrolleri var. Sessiya SAXLANMIR: hər
əməliyyat üçün yeni `ApplicationContext.session()` açılır və commit edilir;
kontrollerə istinad da saxlanmır (siqnal bağlamalarının `lambda`-larında
yaşayır, ekranla birlikdə ölür).

──────────────────────────────────────────────────────────────────────────────
`_binders()`-DƏKİ `_reports` NİYƏ SAXLANILIR (HİBRİD BAĞLAMA)
──────────────────────────────────────────────────────────────────────────────
`ScreenDataBinder._reports` DƏYİŞMƏDƏN qalır — dövr etiketi və LOCK xülasəsi
(72 saatlıq etiraz pəncərəsi) oradan gəlməyə davam edir. Bu kontroller YALNIZ
Faza 8-in ƏLAVƏ etdiyi bölməni bağlayır. Eyni hibrid naxış `users`
(`_attach_users_pos_threshold`), `shift_planning` (`_attach_open_shift_market`)
və `dashboard` (`_attach_dashboard_benchmark`) ekranlarındadır.

Alternativ — bütün oxunu bura köçürmək — LOCK xülasəsini Faza 6-dan Faza 8-ə
daşımaq demək olardı: iki fərqli sualın (cərimə pəncərəsi / tabel anomaliyası)
kodu bir metoda yığılardı və birinin dəyişməsi digərini gözlənilmədən
təsirləndirərdi.

──────────────────────────────────────────────────────────────────────────────
HƏR ƏMƏLİYYAT SƏTİRLƏRİ YENİDƏN HESABLAYIR — KEŞ YOXDUR
──────────────────────────────────────────────────────────────────────────────
`_on_preflight`, `_on_export` və `_on_correction` üçü də sətirləri sıfırdan
qurur. Keş saxlamaq cazibədardır (üç dəfə eyni SQL), lakin RƏDD EDİLDİ: panel
saatlarla açıq qala bilər və bu müddətdə başqa bir HR düzəliş yaza, işçi
deaktiv oluna, növbə dəyişə bilər. Köhnə keşdən yazılan Excel faylı
"doğrulanmış" görünərdi, halbuki doğrulama başqa məlumat üzərində aparılmışdı.

──────────────────────────────────────────────────────────────────────────────
FAYL HANSI QOVLUĞA YAZILIR
──────────────────────────────────────────────────────────────────────────────
Qovluq hər export-da istifadəçidən SORUŞULUR (`QFileDialog`). Sabit qovluq
(məs. `%LOCALAPPDATA%`) rədd edildi: fayl mühasibatlığa göndərilən sənəddir və
HR onu adətən paylaşılan şəbəkə qovluğuna yazır — sabit yol hər dəfə əl ilə
köçürmə tələb edərdi. `_choose_output_dir` AYRICA metoddur ki, test onu
Qt-siz əvəz edə bilsin (`bulk_operations.py::_show_result` ilə eyni naxış).

──────────────────────────────────────────────────────────────────────────────
TARİX ARALIĞI EKRANDAN GƏLİR — SABİT «CARİ AY» ARTIQ YOXDUR
──────────────────────────────────────────────────────────────────────────────
`_resolve_range()` ekranın rejim seçicisini oxuyur:

  * `[Tam Ay]` (defolt, boş cüt) → `ReportRange.for_month(bu il, bu ay)`.
    Açar `'YYYY-MM'` qalır, yəni `fines.exported_period` sətirlərinin mənası
    Faza 7-dən əvvəlki kimidir.
  * `[Xüsusi Aralıq]` → `MonthlyReportUseCase.resolve_range(...)`. HƏDD
    YOXLAMASI ORADADIR (`REPORT_RANGE_MAX_DAYS`, migrations/043) —
    kontrollerdə TƏKRARLANMIR, sadəcə `user_message` göstərilir.

XƏTA HANSI YERDƏ GÖSTƏRİLİR: aralığa aid istisnalar (`ReportPeriodError` və
onun alt-sinifləri) `set_range_message()` ilə seçicinin YANINDA, qalanları
`set_preflight_message()` ilə doğrulama kartında. Səbəb sadədir — mesaj
düzəlişin ediləcəyi yerdə görünməlidir.

──────────────────────────────────────────────────────────────────────────────
PREMİYA & CƏRİMƏ FAYLI: LOCK MEXANİZMİNƏ TOXUNULMUR
──────────────────────────────────────────────────────────────────────────────
`_write_bonus_penalty()` aralığı `build_bonus_penalty()`-yə ÖTÜRMÜR — həmin
metodun imzasında tarix parametri YOXDUR və `tests/unit/test_report_range_
norm.py::test_build_bonus_penalty_has_no_date_range_parameter` bunu qapıya
çevirib. Aralıq YALNIZ iki yerdə işlənir:

  1. NAMİZƏD seçimində — `RangeScopedFineReader.list_in_range(...)`;
  2. `mark_exported(period=...)`-da — hansı dövr açarının yazılacağı.

«Hansı cərimə tutula BİLƏR» sualına yenə yalnız `Fine.is_exportable(now=...)`
cavab verir. Ona görə 72 saatlıq açıq pəncərədəki cərimə aralıq necə seçilirsə
seçilsin fayla DÜŞMÜR, `REVERSED` heç vaxt düşmür, artıq tutulmuş isə ikinci
dəfə tutulmur.

SIRA MƏCBURİDİR: əvvəlcə fayl YAZILIR, sonra `mark_exported()` çağırılır və
YALNIZ sonda `commit()` olur. Tərsinə olsaydı, fayl yazma uğursuzluğundan
sonra cərimələr "tutulmuş" qalar və həmin dövr üçün bir daha heç vaxt
export edilməzdi (`reporting.py::mark_exported` başlığı).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.application.use_cases.export_preflight import (
    EXPORT_CORRECTIONS_FLAG,
    correctable_field_options,
)
from src.application.use_cases.reporting import ReportPeriodError, ReportRange
from src.domain.value_objects.export_corrections import NOTE_FIELD
from src.domain.value_objects.identifiers import EmployeeId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.application.use_cases.export_preflight import ExportPreflightReview
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_h import ReportExportScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Hesabat açarı → faylın istifadəçi üçün adı.
#: Pre-export ekranı HƏR İKİ fayl üçün DAVAMİYYƏT sətirlərini yoxlayır
#: (anomaliyanın mənbəyi tabeldir), lakin HR hansı faylı çıxaracağını
#: əvvəlcədən seçir və təsdiq düyməsi məhz onu yazır.
_REPORT_TITLES: dict[str, str] = {
    "attendance": "Aylıq Davamiyyət Hesabatı",
    "bonus_penalty": "Premiya və Cərimə Hesabatı",
}

#: Premiya faylı seçiləndə düzəliş dialoqunda göstərilən YEGANƏ sahə.
#: `NORMA_GUN`/`FAKTIKI_GUN`/... DAVAMİYYƏT faylının sütunlarıdır və premiya
#: faylında qarşılığı YOXDUR — onları göstərmək "düzəltdim, amma rəqəm
#: dəyişmədi" halını yaradardı (`export_corrections.py` başlığındakı eyni
#: əsaslandırma, tətbiq sahəsi genişlənib).
_BONUS_CORRECTION_FIELDS = (NOTE_FIELD,)

_GENERIC_ERROR = "Əməliyyat tamamlanmadı. Yenidən cəhd edin."


class ReportExportController:
    """ "Aylıq Hesabatlar" ekranını export use case-lərinə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: ReportExportScreen) -> None:
        screen.preflight_requested.connect(lambda key: self._on_preflight(screen, key))
        screen.export_requested.connect(lambda key: self._on_export(screen, key))
        screen.role_filter_changed.connect(lambda _code: self._on_selection_changed(screen))
        screen.range_changed.connect(lambda _start, _end: self._on_range_changed(screen))
        screen.correction_requested.connect(lambda: self._on_correction(screen))

        # Aralıq seçicisinin BAŞLANĞIC vəziyyəti: `[Tam Ay]`. Maket yolu da
        # EYNİ setter-i çağırır (`preview_screens._reports`) — CLAUDE.md §6.
        screen.set_range_selection(custom=False)

        # GÖRMƏK = SƏLAHİYYƏTİN OLMASI: düzəliş bölməsi flag YOXDURSA
        # ÜMUMİYYƏTLƏ qurulmur (söndürülmür). Yoxlama `Employee.has_permission`
        # ilə YERLİ aparılır — sessiya açmağa ehtiyac yoxdur, çünki aktor
        # obyekti onsuz da giriş anında yüklənib. FAKTİKİ qapı use case-dədir
        # (`record_correction` → `ExportCorrectionPermissionError`): görünüş
        # rahatlıqdır, icazə deyil (bax `menu.py` başlığı).
        screen.set_correction_access(
            allowed=self._actor.has_permission(EXPORT_CORRECTIONS_FLAG, now=_now())
        )
        self._load_role_options(screen)

    # ------------------------------ rol filtri (G) ---------------------------- #

    def _load_role_options(self, screen: ReportExportScreen) -> None:
        """Rol seçimlərini KATALOQDAN doldurur — sabit siyahı YOXDUR."""
        selected = screen.selected_role()
        try:
            with self._context.session(user_id=self._actor.id) as session:
                report_range = self._resolve_range(screen, session)
                roster = session.export_roster.roster_status(
                    session.tenant_id, start=report_range.start, end=report_range.end
                )
                session.commit()
        except ReportPeriodError as error:
            # Aralıq xətası seçicinin YANINDA göstərilir (bax modul başlığı).
            # Rol siyahısı KÖHNƏ HALINDA QALIR: onu boşaltmaq istifadəçinin
            # düzgün seçdiyi rolu tarix səhvinə görə itirərdi.
            screen.set_range_message(error.user_message, error=True)
            return
        except KompasOSError as error:
            screen.set_role_options([], selected="")
            screen.set_preflight_message(error.user_message, error=True)
            screen.show_preflight_section()
            return
        except Exception:
            _error_log.exception("EXPORT_ROLE_OPTIONS_FAILED")
            screen.set_role_options([], selected="")
            return

        options = _role_rows(roster)
        # Seçilmiş rol siyahıdan çıxıbsa (rol silinib) `set_role_options`
        # «Bütün rollar»a düşür — filtr sükutla BOŞ nəticə verməkdənsə açıq
        # şəkildə sıfırlanmalıdır.
        screen.set_role_options(options, selected=selected)

    def _on_selection_changed(self, screen: ReportExportScreen) -> None:
        """Rol dəyişəndə doğrulama YENİDƏN işləyir — lakin yalnız artıq
        işlədilibsə.

        `_active_report` boşdursa istifadəçi hələ heç bir hesabat seçməyib və
        filtri əvvəlcədən qurur; o anda sorğu göndərmək lazımsız yükdür.
        """
        report_key = screen.active_report()
        if report_key:
            self._on_preflight(screen, report_key)

    def _on_range_changed(self, screen: ReportExportScreen) -> None:
        """Aralıq tətbiq olundu — rol kataloqu VƏ baxış yenidən yüklənir.

        NİYƏ ROL KATALOQU DA: kadr sorğusu aralıqla çağırılır və gələcəkdə
        tarixli kadr tarixçəsi əlavə olunarsa (bax `export_correction_
        repository.roster_status` şərhi) siyahı dövrdən asılı olacaq. İndi
        nəticə eynidir, lakin çağırış yeri DOĞRU olmalıdır — əks halda həmin
        genişlənmə sükutla yarımçıq işləyərdi.
        """
        screen.set_range_message("")
        self._load_role_options(screen)
        self._on_selection_changed(screen)

    # --------------------------- doğrulama (A/E/F/G) -------------------------- #

    def _on_preflight(self, screen: ReportExportScreen, report_key: str) -> None:
        prepared = self._build_review(screen, report_key)
        if prepared is None:
            return
        _render(screen, prepared.review)

    def _resolve_range(self, screen: ReportExportScreen, session: Session) -> ReportRange:
        """Ekranın seçimini `ReportRange`-ə çevirir — bax modul başlığı.

        `[Tam Ay]` yolu `resolve_range()`-dən KEÇMİR və bu, qəsdəndir:
        `MonthlyReportUseCase.resolve_month` başlığı bunu açıq yazır — Root
        həddi 15 günə salınsa belə oktyabrın TAM hesabatı çıxarıla bilməlidir.
        Hədd `[Xüsusi Aralıq]` seçiminin performans qoruyucusudur.
        """
        start_text, end_text = screen.selected_range()
        if not start_text and not end_text:
            today = date.today()  # noqa: DTZ011 — dövr İSTİFADƏÇİNİN təqvimi ilə ölçülür
            return session.reports.resolve_month(year=today.year, month=today.month)
        try:
            start = date.fromisoformat(start_text)
            end = date.fromisoformat(end_text)
        except ValueError as error:
            # `ReportPeriodError` seçilir (ümumi `KompasOSError` yox), çünki
            # çağıran tərəf məhz bu sinfə görə mesajı SEÇİCİNİN YANINDA
            # göstərir — səhvin düzəldiləcəyi yerdə.
            raise ReportPeriodError(
                f"Tarix ISO formatında deyil: {start_text!r} / {end_text!r}",
                user_message="Tarixləri İL-AY-GÜN formatında yazın (məsələn 2026-08-01).",
            ) from error
        return session.reports.resolve_range(tenant_id=session.tenant_id, start=start, end=end)

    def _build_review(self, screen: ReportExportScreen, report_key: str) -> _PreparedExport | None:
        """Sətirləri qurur və `ExportPreflightUseCase.review()`-i çağırır.

        Nəticə `review` İLƏ BİRLİKDƏ seçilmiş aralığı daşıyır: `_on_export`
        faylın adı və `mark_exported()` üçün MƏHZ həmin aralığı işlətməlidir.
        Aralığı ikinci dəfə hesablasaydıq, gecə yarısı işləyən export tarix
        keçidində fərqli dövr açarı yaza bilərdi.

        `None` qaytarmaq = xəta ekranda GÖSTƏRİLDİ (sükutla udulmadı).
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                report_range = self._resolve_range(screen, session)
                review = session.export_preflight.review(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    rows=_attendance_rows(session, self._actor, report_range),
                    report_range=report_range,
                    previous_rows=_attendance_rows(
                        session,
                        self._actor,
                        session.export_preflight.previous_range(report_range),
                    ),
                    role_code=screen.selected_role(),
                    export_type=_export_type_for(report_key),
                )
                session.commit()
        except ReportPeriodError as error:
            screen.set_range_message(error.user_message, error=True)
            return None
        except KompasOSError as error:
            screen.set_preflight_message(error.user_message, error=True)
            screen.show_preflight_section()
            return None
        except Exception:
            _error_log.exception("EXPORT_PREFLIGHT_FAILED")
            screen.set_preflight_message(_GENERIC_ERROR, error=True)
            screen.show_preflight_section()
            return None
        screen.set_range_message("")
        return _PreparedExport(review=review, report_range=report_range)

    # ------------------------------- export ----------------------------------- #

    def _on_export(self, screen: ReportExportScreen, report_key: str) -> None:
        """HR təsdiqlədi — fayl İNDİ yazılır.

        Sətirlər YENİDƏN hesablanır (bax modul başlığı: keş yoxdur), yəni
        faylda göründüyü rəqəm doğrulama anındakı ilə eyni MƏNBƏDƏNDİR.
        """
        prepared = self._build_review(screen, report_key)
        if prepared is None:
            return

        directory = self._choose_output_dir(screen)
        if directory is None:
            screen.set_preflight_message("Export ləğv edildi — qovluq seçilmədi.")
            return

        try:
            if report_key == "bonus_penalty":
                path, extra = self._write_bonus_penalty(screen, prepared, directory=directory)
            else:
                path = _write_attendance(prepared, directory=directory)
                extra = ""
        except KompasOSError as error:
            screen.set_preflight_message(error.user_message, error=True)
            return
        except Exception:
            _error_log.exception("EXPORT_FILE_WRITE_FAILED")
            screen.set_preflight_message(_GENERIC_ERROR, error=True)
            return

        review = prepared.review
        title = _REPORT_TITLES.get(report_key, "Hesabat")
        screen.set_preflight_message(
            f"{title} ({prepared.report_range.label_az()}) yazıldı: {path}. "
            f"{len(review.rows)} sətir, {len(review.findings)} xəbərdarlıq, "
            f"{len(review.corrections)} manual düzəliş.{extra}"
        )

    def _write_bonus_penalty(
        self,
        screen: ReportExportScreen,
        prepared: _PreparedExport,
        *,
        directory: Path,
    ) -> tuple[Path, str]:
        """FAYL 2 — LOCK MEXANİZMİ ilə (bax modul başlığı).

        Sıra: namizədləri oxu → `build_bonus_penalty` (LOCK burada qərar
        verir) → faylı YAZ → `mark_exported` → `commit`. Yazma uğursuz olarsa
        `mark_exported`-a heç vaxt çatılmır və tranzaksiya geri qayıdır.

        ROL FİLTRİ SATIŞ FAKTLARINA TƏTBİQ OLUNUR, sətirlərə YOX — və bu,
        kritikdir: `build_bonus_penalty` `included_fines`-ı yalnız `facts`-də
        olan işçilər üçün doldurur. Sətirləri sonradan süzsəydik, fayldan
        kənarda qalan işçinin cəriməsi YENƏ DƏ `mark_exported()` ilə tutulmuş
        işarələnərdi — yəni pul kəsilər, sənəd isə olmazdı.
        """
        report_range = prepared.report_range
        with self._context.session(user_id=self._actor.id) as session:
            facts = _sales_facts(session, report_range, role_code=screen.selected_role())
            fines = session.uow.fines.list_in_range(
                session.tenant_id, start=report_range.start, end=report_range.end
            )
            now = _now()
            selection = session.reports.build_bonus_penalty(
                actor=self._actor, facts=facts, fines=fines, now=now
            )
            path = _write_bonus_workbook(selection, prepared, directory=directory)
            session.reports.mark_exported(selection=selection, period=report_range, now=now)
            session.commit()

        # LOCK vəziyyəti export-dan SONRA da göstərilir: HR faylda niyə az
        # cərimə olduğunu dərhal görməlidir (bölmə 6-nın açıq tələbi).
        screen.set_lock_summary(
            selection.deferred_fine_count,
            already_exported=selection.already_exported_count,
            overlap_notice=selection.overlap_notice_az() or "",
        )
        return path, _lock_suffix(selection)

    def _choose_output_dir(self, screen: ReportExportScreen) -> Path | None:
        """Qovluq seçimi — AYRICA metod ki, test onu Qt-siz əvəz edə bilsin."""
        from PySide6.QtWidgets import QFileDialog  # noqa: PLC0415

        selected = QFileDialog.getExistingDirectory(screen, "Hesabat faylı hara yazılsın?")
        return Path(selected) if selected else None

    # --------------------------- manual düzəliş (D) --------------------------- #

    def _on_correction(self, screen: ReportExportScreen) -> None:
        """Düzəliş dialoqunu açır — işçi siyahısı CARİ export sətirlərindəndir.

        Bütün işçiləri göstərmək əvəzinə yalnız export-a düşənlər verilir: rol
        filtri aktivdirsə, siyahıdan kənar bir işçiyə düzəliş yazmaq həmin
        düzəlişi GÖRÜNMƏZ edərdi (fayla düşməzdi, ekranda da olmazdı).
        """
        from src.presentation.screens.group_h import ExportCorrectionDialog  # noqa: PLC0415

        prepared = self._build_review(screen, screen.active_report())
        if prepared is None:
            return
        employees = [(str(row.employee_id), row.full_name) for row in prepared.review.rows]
        if not employees:
            screen.set_preflight_message(
                "Düzəliş ediləcək sətir yoxdur — seçilmiş rol filtri boş nəticə verir.",
                error=True,
            )
            screen.show_preflight_section()
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                minimum = _reason_min_length(session)
                session.commit()
        except Exception:
            _error_log.exception("EXPORT_CORRECTION_LIMIT_READ_FAILED")
            minimum = _fallback_reason_min_length()

        dialog = ExportCorrectionDialog(
            screen.theme,
            employees=employees,
            fields=_correction_fields(screen.active_report()),
            default_date=prepared.report_range.start.isoformat(),
            reason_min_length=minimum,
            parent=screen,
        )
        dialog.submitted.connect(
            lambda employee_id, target_date, field_code, value, reason: self._submit_correction(
                screen,
                employee_id=employee_id,
                target_date=target_date,
                field_code=field_code,
                new_value=value,
                reason=reason,
            )
        )
        dialog.exec()

    def _submit_correction(
        self,
        screen: ReportExportScreen,
        *,
        employee_id: str,
        target_date: str,
        field_code: str,
        new_value: str,
        reason: str,
    ) -> None:
        try:
            parsed_employee = EmployeeId(uuid.UUID(employee_id))
            parsed_date = date.fromisoformat(target_date)
        except ValueError:
            screen.set_preflight_message(
                "Seçilmiş işçi və ya tarix düzgün deyil — düzəliş yazılmadı.", error=True
            )
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.export_preflight.record_correction(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    employee_id=parsed_employee,
                    target_date=parsed_date,
                    field_code=field_code,
                    old_value=_old_value(screen, parsed_employee, field_code),
                    new_value=new_value,
                    reason=reason,
                    export_type=_export_type_for(screen.active_report()),
                )
                session.commit()
        except KompasOSError as error:
            screen.set_preflight_message(error.user_message, error=True)
            screen.show_preflight_section()
            return
        except Exception:
            _error_log.exception("EXPORT_CORRECTION_FAILED")
            screen.set_preflight_message(_GENERIC_ERROR, error=True)
            screen.show_preflight_section()
            return

        # HƏR YAZIDAN SONRA SİYAHI YENİDƏN OXUNUR (CLAUDE.md §6): düzəliş
        # rəqəmə tətbiq olunur, yəni doğrulama tapıntıları da dəyişə bilər.
        self._on_preflight(screen, screen.active_report())


# --------------------------------------------------------------------------- #
# Köməkçilər — Qt TƏLƏB ETMİR, birbaşa test oluna bilir
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _PreparedExport:
    """Doğrulama nəticəsi + ONUNLA BİRLİKDƏ seçilmiş aralıq.

    İkisi bir yerdə daşınır, çünki fayl adı (`Davamiyyet_<key>.xlsx`),
    `mark_exported(period=...)` və ekranın mesajı MƏHZ həmin aralığa aid
    olmalıdır. Aralığı ayrıca ikinci dəfə hesablamaq gecə yarısı (və ya
    istifadəçi seçimi dəyişəndə) iki fərqli dövr açarı yaza bilərdi.
    """

    review: ExportPreflightReview
    report_range: ReportRange


@dataclass(frozen=True)
class _CorrectionRow:
    """`_correction_rows()`-un bir sətri — sahələr `ReportExportScreen.
    set_corrections()`-in gözlədiyi açarlarla EYNİDİR (CLAUDE.md §6).

    Sözlük əvəzinə dataclass: `**payload` açılışı mypy strict rejimində
    `object`-ə düşür (`controllers/bulk_operations.py::_PreviewPayload` ilə
    eyni qərar).
    """

    employee: str
    date: str
    change: str
    reason: str


def _now() -> datetime:
    """Səlahiyyət yoxlamasının anı.

    `Clock` portu BURADA İŞLƏDİLMİR VƏ BU, QƏSDƏNDİR: port sessiya daxilində
    yaşayır, bu yoxlama isə ekran qurulanda — sessiyadan KƏNARDA — baş verir.
    Nəticə yalnız GÖRÜNÜŞƏ təsir edir; FAKTİKİ qapı use case-dədir və o,
    həqiqətən `Clock`-dan keçir.
    """
    return datetime.now(UTC)


def _export_type_for(report_key: str) -> str:
    """Ekran açarı → `export_manual_corrections.export_type`.

    Düzəlişlər FAYLA GÖRƏ ayrılır: davamiyyət faylına yazılmış düzəliş premiya
    faylının «Qeyd» sütununda görünməməlidir (və əksinə). Ayırmasaydıq, bir
    faylın izahı digərinin sənədinə sızardı və mühasib onu həmin faylın
    rəqəmlərinə aid sayardı.
    """
    from src.domain.value_objects.export_corrections import (  # noqa: PLC0415
        EXPORT_TYPE_ATTENDANCE,
        EXPORT_TYPE_BONUS_PENALTY,
    )

    return EXPORT_TYPE_BONUS_PENALTY if report_key == "bonus_penalty" else EXPORT_TYPE_ATTENDANCE


def _correction_fields(report_key: str) -> list[tuple[str, str]]:
    """Düzəliş dialoqunun sahə siyahısı — hesabata görə DARALIR.

    Premiya faylında yalnız «Qeyd» qalır (bax `_BONUS_CORRECTION_FIELDS`).
    Davamiyyət faylında bütün kataloq göstərilir.
    """
    options = list(correctable_field_options())
    if report_key != "bonus_penalty":
        return options
    return [(code, label) for code, label in options if code in _BONUS_CORRECTION_FIELDS]


def _attendance_rows(session: Session, actor: Employee, report_range: ReportRange) -> list[Any]:
    """Davamiyyət sətirləri — HESABLAMA `MonthlyReportUseCase`-DƏDİR.

    Bu funksiya heç bir norma/pro-rata arifmetikası APARMIR: Faza 7-nin
    zənciri (`report_facts` → `plan_facts` → `work_norm`) olduğu kimi
    çağırılır. Düsturun ikinci nüsxəsi burada olsaydı, biri dəyişəndə digəri
    arxada qalardı.
    """
    facts = session.report_facts.attendance_facts(
        session.tenant_id, start=report_range.start, end=report_range.end
    )
    plans = session.report_facts.plan_facts(
        session.tenant_id, start=report_range.start, end=report_range.end
    )
    return list(
        session.reports.build_attendance_rows_for_range(
            tenant_id=session.tenant_id,
            actor=actor,
            facts=facts,
            plans=plans,
            report_range=report_range,
            now=_now(),
        )
    )


def _sales_facts(session: Session, report_range: ReportRange, *, role_code: str) -> list[Any]:
    """FAYL 2-nin satış tərəfi — rol filtri BURADA tətbiq olunur.

    Səbəb `ReportExportController._write_bonus_penalty` docstring-indədir:
    filtri sonradan sətirlərə tətbiq etmək cərimənin fayla düşmədən
    "tutulmuş" işarələnməsinə yol açardı.

    Rol kodu boş olduqda HEÇ NƏ süzülmür — bir əlavə sorğu da göndərilmir.
    """
    facts = session.report_facts.sales_facts(
        session.tenant_id, start=report_range.start, end=report_range.end
    )
    wanted = role_code.strip().upper()
    if not wanted:
        return list(facts)
    roster = session.export_roster.roster_status(
        session.tenant_id, start=report_range.start, end=report_range.end
    )
    allowed = {
        entry.employee_id for entry in roster if str(entry.position_code).strip().upper() == wanted
    }
    return [fact for fact in facts if fact.employee_id in allowed]


def _lock_suffix(selection: Any) -> str:
    """Export mesajının LOCK əlavəsi — sükutla atlama YOXDUR.

    Sıfır olduqda BOŞ sətir qaytarılır: "0 cərimə təxirə salındı" cümləsi hər
    uğurlu export-da təkrarlanıb siqnal dəyərini itirərdi.
    """
    parts: list[str] = []
    if selection.deferred_fine_count:
        parts.append(f"{selection.deferred_fine_count} cərimə açıq etiraz pəncərəsinə görə xaric")
    if selection.already_exported_count:
        parts.append(f"{selection.already_exported_count} cərimə artıq əvvəlki dövrdə tutulub")
    return f" LOCK: {', '.join(parts)}." if parts else ""


def _role_rows(roster: list[Any]) -> list[dict[str, str]]:
    """Kadr sətirləri → `set_role_options()` sətirləri (təkrarsız, sıralı)."""
    seen: dict[str, str] = {}
    for entry in roster:
        code = str(entry.position_code).strip().upper()
        if code:
            seen.setdefault(code, str(entry.position_name))
    return [{"code": code, "name": seen[code]} for code in sorted(seen)]


def _finding_rows(review: ExportPreflightReview) -> list[dict[str, str]]:
    """Tapıntılar → `set_validation_findings()` sətirləri."""
    return [
        {
            "rule": finding.rule_label_az(),
            "subject": finding.subject_az,
            "detail": finding.detail_az,
        }
        for finding in review.findings
    ]


def _comparison_rows(review: ExportPreflightReview) -> list[dict[str, str]]:
    """Deltalar → `set_period_comparison()` sətirləri.

    Keçən dövr məlumatı yoxdursa BOŞ siyahı qayıdır — ekran o zaman cədvəli
    gizlədir və izah göstərir (yalançı «−12» əvəzinə).
    """
    if not review.deltas or not any(delta.has_baseline for delta in review.deltas):
        return []
    return [
        {
            "metric": delta.label_az,
            "current": str(delta.current),
            "previous": str(delta.previous),
            "delta": delta.delta_text_az(),
            "significant": "1" if delta.is_significant else "",
        }
        for delta in review.deltas
    ]


def _correction_rows(
    review: ExportPreflightReview, *, names: dict[EmployeeId, str]
) -> list[dict[str, str]]:
    """Düzəlişlər → `set_corrections()` sətirləri."""
    return [
        {
            "employee": names.get(item.employee_id, str(item.employee_id)),
            "date": item.target_date.isoformat(),
            "change": item.summary_az(),
            "reason": item.reason,
        }
        for item in review.corrections
    ]


def _comparison_caption(review: ExportPreflightReview) -> str:
    """«Hansı dövrlə müqayisə edilir» — AÇIQ yazılır.

    "Keçən ay" fərziyyəsi səhv olardı: müqayisə EYNİ UZUNLUQDA əvvəlki
    aralıqladır (bax `export_preflight.py` başlığı) və HR onu görməlidir.
    """
    if review.previous_range is None:
        return "Keçən dövr üçün məlumat yoxdur — müqayisə göstərilmir."
    return f"Müqayisə dövrü: {review.previous_range.label_az()} (eyni uzunluqda)."


def _render(screen: ReportExportScreen, review: ExportPreflightReview) -> None:
    """`ExportPreflightReview` → ekranın setter API-si.

    Ardıcıllıq: tapıntılar → müqayisə → düzəlişlər. `set_validation_findings`
    ƏVVƏLCƏ çağırılır, çünki o, bölməni görünən edir və ümumi mesajı yazır.
    """
    names = {row.employee_id: row.full_name for row in review.rows}
    screen.set_row_values(_row_values(review))
    screen.set_validation_findings(_finding_rows(review))
    screen.set_period_comparison(_comparison_rows(review), caption=_comparison_caption(review))
    screen.set_corrections(_correction_rows(review, names=names))


def _row_values(review: ExportPreflightReview) -> dict[str, dict[str, str]]:
    """Cari sətir rəqəmləri — açarlar `CORRECTABLE_FIELDS` kodları ilə EYNİDİR.

    Uyğunluq TƏSADÜFİ DEYİL: düzəliş dialoqunda seçilən sahə kodu birbaşa bu
    sözlüyə açar kimi verilir (`_old_value`). Fərqli adlandırma "köhnə dəyər"i
    həmişə boş buraxardı və audit sətri yarımçıq olardı.

    «QEYD» sahəsi burada YOXDUR və olmamalıdır: onun "köhnə dəyəri" mövcud
    deyil (sərbəst mətn sütunu export sətrində saxlanmır) — `None` yazılması
    DÜZGÜN cavabdır.
    """
    return {
        str(row.employee_id): {
            "NORMA_GUN": str(row.norm_work_days),
            "FAKTIKI_GUN": str(row.actual_worked_days),
            "OFF_DAY": str(row.off_days),
            "ICAZESIZ_QAYIB": str(row.unauthorized_absences),
        }
        for row in review.rows
    }


def _reason_min_length(session: Session) -> int:
    """ROOT-dan səbəbin minimum uzunluğu — dialoqun ipucu mətni üçün.

    Dəyər ekranda SABİT YAZILMIR (hardcode qadağandır) və use case-dəki
    yoxlamanı ƏVƏZ ETMİR: dialoq yalnız istifadəçiyə rəqəmi göstərir, qərarı
    `record_correction` verir.
    """
    from src.application.use_cases.export_preflight import (  # noqa: PLC0415
        FALLBACK_REASON_MIN_LENGTH,
    )
    from src.domain.policies import SystemLimitKey  # noqa: PLC0415

    value = int(
        session.limits.get_int(
            session.tenant_id,
            SystemLimitKey.EXPORT_CORRECTION_REASON_MIN_LENGTH.value,
            FALLBACK_REASON_MIN_LENGTH,
        )
    )
    return max(value, FALLBACK_REASON_MIN_LENGTH)


def _fallback_reason_min_length() -> int:
    from src.application.use_cases.export_preflight import (  # noqa: PLC0415
        FALLBACK_REASON_MIN_LENGTH,
    )

    return FALLBACK_REASON_MIN_LENGTH


def _write_attendance(prepared: _PreparedExport, *, directory: Path) -> Path:
    """FAYL 1 — «Qeyd» sütunu düzəlişlərdən doldurulur (bənd E).

    Dövr `prepared.report_range`-dəndir: `[Tam Ay]` üçün fayl adı
    `Davamiyyet_2026-08.xlsx`, xüsusi aralıq üçün
    `Davamiyyet_2026-08-01_2026-08-15.xlsx` olur (`ReportRange.key`).
    """
    from src.infrastructure.reporting.excel import ExcelReportWriter  # noqa: PLC0415

    writer = ExcelReportWriter(output_dir=directory)
    return writer.write_attendance(
        list(prepared.review.rows),
        period=prepared.report_range,
        notes=dict(prepared.review.notes),
    )


def _write_bonus_workbook(selection: Any, prepared: _PreparedExport, *, directory: Path) -> Path:
    """FAYL 2 — sətirlər `BonusPenaltySelection`-dan, qeydlər düzəlişlərdən.

    HESABLAMA BURADA YOXDUR: cərimə seçimini (`included`/`deferred`/
    `already_exported`) tamamilə `MonthlyReportUseCase.build_bonus_penalty`
    aparıb — bu funksiya yalnız nəticəni fayla yazır (`reporting.py` başlığı:
    "BU MODUL FAYL YAZMIR" qaydasının güzgüsü).
    """
    from src.infrastructure.reporting.excel import ExcelReportWriter  # noqa: PLC0415

    writer = ExcelReportWriter(output_dir=directory)
    return writer.write_bonus_penalty(
        list(selection.rows),
        period=prepared.report_range,
        notes=dict(prepared.review.notes),
    )


def _old_value(screen: ReportExportScreen, employee_id: EmployeeId, field: str) -> str | None:
    """Düzəlişdən ƏVVƏLKİ dəyər — ekranda göstərilən CARİ rəqəm.

    Ekrandan oxunur, bazadan YOX: audit sualı "istifadəçi NƏYİ gördü və nəyə
    dəyişdi?"-dir. Baza dəyəri həmin an fərqli ola bilər (başqa HR düzəliş
    yazıb) və onu "köhnə dəyər" kimi yazmaq izi TƏHRİF edərdi.

    `None` qaytarmaq QANUNİDİR: sətir ekranda tapılmadıqda (rol filtri
    dəyişib) "sahə boş idi" yazılır — DB `NULL` qəbul edir.
    """
    return screen.current_value(employee_id, field)


__all__ = ["ReportExportController"]
