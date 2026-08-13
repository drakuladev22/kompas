"""Üç kataloq ekranının YAZI yolu — İş Rejimləri, Cərimə Növləri, İcazə Növləri.

──────────────────────────────────────────────────────────────────────────────
NİYƏ `screen_data.py`-DA DEYİL
──────────────────────────────────────────────────────────────────────────────
`screen_data.py` YALNIZ oxu yolunu bağlayır: sessiya açır, setter çağırır,
bağlayır. Kataloq ekranı isə həm oxuyur, HƏM DƏ yazır (yeni sətir, redaktə,
deaktivləşdirmə) və hər yazıdan sonra siyahını yenidən oxumalıdır. Bu dövrə
bir siqnal ömrü boyu yaşamalıdır, `populate()`-ın tək çağırışında yox
(CLAUDE.md bölmə 6 — «Ekranın YAZI yolu»). Eyni səbəb `root_control.py` və
`fine_entry.py`-da da yazılıb.

──────────────────────────────────────────────────────────────────────────────
ÜÇ KATALOQ, BİR KONTROLLER
──────────────────────────────────────────────────────────────────────────────
`group_h.CatalogScreen` üçü üçün ORTAQ ekran sinfidir və siqnalları eynidir
(`create_requested`, `edit_requested`, `toggle_requested`). Üç ayrı kontroller
yazsaydıq, eyni sessiya/xəta/yenilə məntiqi üç dəfə təkrarlanardı və biri
düzəldiləndə digər ikisi arxada qalardı — məhz `CatalogScreen`-in özündən
qaçdığı vəziyyət.

Fərqlər `_CatalogAdapter`-dədir: hansı use case çağırılır, sətir hansı
mətnlərə çevrilir və dialoqda hansı sahə soruşulur. Səlahiyyət isə BURADA
YOXLANMIR — hər use case öz flag-ını ayrıca yoxlayır
(`can_manage_work_modes` / `_fine_types` / `_leave_types`) və onları
birləşdirmək HR-a cərimə qiymətini dəyişmək imkanı verərdi (bax
`catalog_management.py` başlığı).

──────────────────────────────────────────────────────────────────────────────
"DEAKTİV ET" SİLMƏ DEYİL
──────────────────────────────────────────────────────────────────────────────
Kataloq sətri FİZİKİ SİLİNMİR — `deactivate()` var, `delete()` yoxdur
(`domain/value_objects/catalogs.py` başlığı: fiziki silmə keçmiş cərimənin
səbəbini "naməlum"a çevirərdi və mübahisədə sübut itərdi).

`toggle_requested` ona görə İKİ istiqamətlidir: aktiv sətir üçün
`deactivate()`, deaktiv sətir üçün isə `save()` (eyni sətir `is_active=True`
ilə yenidən yazılır). İkinci yol AYRI bir "reactivate" metodu tələb etmir,
çünki repository `ON CONFLICT (tenant_id, name)` ilə UPSERT edir — sətrin
identifikatoru və tarixi qeydlərlə əlaqəsi qorunur.

──────────────────────────────────────────────────────────────────────────────
HƏR ƏMƏLİYYAT ÖZ SESSİYASINDA
──────────────────────────────────────────────────────────────────────────────
Kontroller sessiyanı SAXLAMIR — hər əməliyyat üçün yenisini açır və commit
edir. Kataloq ekranı gün boyu açıq qala bilər; uzun-ömürlü tranzaksiya bu
müddət boyu `fine_types`/`work_modes` cədvəllərini kilidli saxlayardı və
cərimə yazan operatoru bloklayardı.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.group_h import CatalogScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Ekran açarı → kataloqun bütün fərqləri (başlıq, sahə etiketi, use case adı).
#:
#: Açarlar `app.py::factories` və `preview_screens._POPULATORS` ilə EYNİDİR —
#: maket və canlı yol eyni ad məkanında qalmalıdır (CLAUDE.md bölmə 6).
CATALOG_KEYS = ("work_modes", "fine_types", "leave_types")


class CatalogInputError(KompasOSError):
    """Dialoqdakı dəyər kataloq tipinə çevrilə bilmədi."""

    user_message = "Daxil edilən dəyər düzgün deyil."


@dataclass(frozen=True)
class _CatalogAdapter:
    """Bir kataloqun ekran ↔ use case tərcüməsi.

    `dataclass` seçilib, çünki burada davranış YOXDUR — yalnız funksiya
    istinadları və mətnlər var. Sinif iyerarxiyası qursaydıq, üç boş alt-sinif
    yaranardı və heç biri əlavə məntiq daşımazdı.
    """

    key: str
    dialog_title_new: str
    dialog_title_edit: str
    value_label: str
    value_hint: str
    #: `Session` → həmin kataloqun use case-i.
    use_case: Callable[[Session], Any]
    #: Domen sətri → ekranın gözlədiyi `cells` mətni (`|` ilə ayrılmış).
    cells: Callable[[Any], str]
    #: Domen sətri → dialoqdakı dəyər sahəsinin ilkin mətni.
    value_of: Callable[[Any], str]
    #: (mövcud sətir | None, ad, dəyər mətni, SESSİYA, aktivlik) → domen sətri.
    #:
    #: `tenant_id` DEYİL, BÜTÖV SESSİYA ötürülür: icazə növünün müddət tavanı
    #: ROOT parametridir (`LEAVE_TYPE_MAX_DURATION_MINUTES`) və qurucu onu
    #: `session.limits`-dən oxumalıdır. Yalnız `tenant_id` versəydik, tavan
    #: modul fallback-ında qalar, Root onu qaldıra bilməzdi — halbuki ROOT
    #: ekranında açar GÖRÜNÜR (bax `catalogs._leave_duration_ceiling`).
    build: Callable[[Any, str, str, Any, bool], Any]
    #: Domen sətri → identifikator (deaktivləşdirmə üçün).
    identifier: Callable[[Any], Any]


class CatalogAdminController:
    """`CatalogScreen`-i öz kataloq use case-inə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee, *, key: str) -> None:
        self._context = context
        self._actor = actor
        self._adapter = _ADAPTERS[key]
        #: Ekrandakı sətir açarı → domen sətri. Redaktə/deaktivləşdirmə üçün
        #: lazımdır: ekran domen tipini TANIMIR (bax `CatalogScreen` başlığı)
        #: və yalnız mətn açarı yayır. Xəritə hər `refresh()`-də yenilənir.
        self._entries: dict[str, Any] = {}

    # ------------------------------- qoşulma --------------------------------- #

    def attach(self, screen: CatalogScreen) -> None:
        """Siqnalları bağlayır və siyahını ilk dəfə doldurur."""
        screen.create_requested.connect(lambda: self._on_create(screen))
        screen.edit_requested.connect(lambda key: self._on_edit(screen, key))
        screen.toggle_requested.connect(lambda key: self._on_toggle(screen, key))
        self.refresh(screen)

    def refresh(self, screen: CatalogScreen) -> None:
        """Siyahını bazadan yenidən oxuyur — DEAKTİVLƏR DƏ daxil.

        İdarəetmə ekranı deaktiv sətirləri göstərir ki, onlar yenidən
        aktivləşdirilə bilsin (bax `group_h.py` başlığı). Gizlətsək,
        "silinmiş" növ geri qaytarıla bilməz görünərdi.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                entries = self._adapter.use_case(session).list_for_management(
                    session.tenant_id, self._actor
                )
        except KompasOSError as error:
            # Səlahiyyət yoxdursa ekran BOŞ deyil, SƏBƏBLƏ göstərilməlidir —
            # boş cədvəl "kataloq boşdur" kimi oxunardı və istifadəçi yeni
            # sətir yaratmağa çalışıb yenidən rədd cavabı alardı.
            screen.show_error(title="Kataloq açıla bilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("CATALOG_LOAD_FAILED", extra={"catalog": self._adapter.key})
            screen.show_error(
                title="Kataloq açıla bilmədi",
                message="Siyahı oxuna bilmədi. Yenidən cəhd edin.",
            )
            return

        self._entries = {_row_key(self._adapter, entry): entry for entry in entries}
        screen.set_entries(
            [
                {
                    "key": key,
                    "cells": self._adapter.cells(entry),
                    "is_active": "1" if entry.is_active else "0",
                }
                for key, entry in self._entries.items()
            ]
        )

    # ------------------------------ yazı yolu -------------------------------- #

    def _on_create(self, screen: CatalogScreen) -> None:
        self._open_dialog(screen, existing=None)

    def _on_edit(self, screen: CatalogScreen, row_key: str) -> None:
        entry = self._entries.get(row_key)
        if entry is None:
            # Sətir başqa bir sessiyada dəyişdirilib: siyahı köhnəlib.
            screen.show_error(
                title="Sətir tapılmadı",
                message="Bu sətir artıq dəyişdirilib. Siyahı yenilənir.",
            )
            self.refresh(screen)
            return
        self._open_dialog(screen, existing=entry)

    def _open_dialog(self, screen: CatalogScreen, *, existing: Any) -> None:
        from src.presentation.screens.group_h import CatalogEntryDialog  # noqa: PLC0415

        adapter = self._adapter
        dialog = CatalogEntryDialog(
            screen.theme,
            title=adapter.dialog_title_new if existing is None else adapter.dialog_title_edit,
            value_label=adapter.value_label,
            value_hint=adapter.value_hint,
            name="" if existing is None else str(existing.name),
            value="" if existing is None else adapter.value_of(existing),
            parent=screen,
        )
        dialog.submitted.connect(
            lambda name, value: self._save(screen, existing=existing, name=name, value=value)
        )
        dialog.exec()

    def _save(self, screen: CatalogScreen, *, existing: Any, name: str, value: str) -> None:
        """Yeni/redaktə edilmiş sətri yazır.

        Redaktədə aktivlik OLDUĞU KİMİ saxlanılır: "Redaktə" düyməsi adı və
        dəyəri dəyişir, sətri dirildmir. Deaktiv sətri aktivləşdirmək AYRI
        bir qərardır və öz düyməsi var («Aktivləşdir»).
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                entry = self._adapter.build(
                    existing,
                    name,
                    value,
                    session,
                    True if existing is None else bool(existing.is_active),
                )
                self._adapter.use_case(session).save(session.tenant_id, self._actor, entry)
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Sətir saxlanmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("CATALOG_SAVE_FAILED", extra={"catalog": self._adapter.key})
            screen.show_error(
                title="Sətir saxlanmadı",
                message="Dəyişiklik yazılmadı. Yenidən cəhd edin.",
            )
            return

        self.refresh(screen)

    def _on_toggle(self, screen: CatalogScreen, row_key: str) -> None:
        """Aktiv → deaktiv (soft delete) və ya deaktiv → aktiv (bax modul başlığı)."""
        entry = self._entries.get(row_key)
        if entry is None:
            screen.show_error(
                title="Sətir tapılmadı",
                message="Bu sətir artıq dəyişdirilib. Siyahı yenilənir.",
            )
            self.refresh(screen)
            return

        try:
            with self._context.session(user_id=self._actor.id) as session:
                use_case = self._adapter.use_case(session)
                if entry.is_active:
                    use_case.deactivate(
                        session.tenant_id, self._actor, self._adapter.identifier(entry)
                    )
                else:
                    use_case.save(
                        session.tenant_id,
                        self._actor,
                        self._adapter.build(
                            entry,
                            str(entry.name),
                            self._adapter.value_of(entry),
                            session,
                            True,
                        ),
                    )
                session.commit()
        except KompasOSError as error:
            screen.show_error(title="Vəziyyət dəyişdirilmədi", message=error.user_message)
            return
        except Exception:
            _error_log.exception("CATALOG_TOGGLE_FAILED", extra={"catalog": self._adapter.key})
            screen.show_error(
                title="Vəziyyət dəyişdirilmədi",
                message="Dəyişiklik yazılmadı. Yenidən cəhd edin.",
            )
            return

        self.refresh(screen)


# --------------------------------------------------------------------------- #
# Kataloq fərqləri
# --------------------------------------------------------------------------- #


def _row_key(adapter: _CatalogAdapter, entry: Any) -> str:
    """Ekrandakı sətir açarı.

    Hələ ID-si olmayan sətir (bazadan gəlməyən nüsxə) üçün AD işlədilir:
    kataloqda ad onsuz da unikaldır (`UNIQUE (tenant_id, name)`), ona görə
    açar toqquşması mümkün deyil və sətir düyməsiz qalmır.
    """
    identifier = adapter.identifier(entry)
    return str(identifier) if identifier is not None else f"name:{entry.name}"


def _work_mode_cells(entry: Any) -> str:
    return f"{entry.name}|{entry.scheduled_start_label()}"


def _work_mode_value(entry: Any) -> str:
    schedule = entry.schedule
    return "" if schedule is None else f"{schedule.start:%H:%M}–{schedule.end:%H:%M}"


def _build_work_mode(existing: Any, name: str, value: str, session: Any, active: bool) -> Any:
    from src.domain.value_objects.catalogs import WorkMode  # noqa: PLC0415

    return WorkMode(
        name=name,
        tenant_id=session.tenant_id,
        is_active=active,
        # Deaktiv sətir üçün `deactivated_at` MƏCBURİDİR (`CatalogEntry`
        # ziddiyyətli vəziyyət saxlamır) — mövcud dəyər varsa qorunur.
        deactivated_at=None if active else _deactivated_at(existing),
        work_mode_id=None if existing is None else existing.work_mode_id,
        schedule=_parse_schedule(value),
    )


def _fine_type_cells(entry: Any) -> str:
    return f"{entry.name}|{entry.standard_amount.amount} ₼"


def _fine_type_value(entry: Any) -> str:
    return str(entry.standard_amount.amount)


def _build_fine_type(existing: Any, name: str, value: str, session: Any, active: bool) -> Any:
    from src.domain.value_objects.catalogs import FineType  # noqa: PLC0415
    from src.domain.value_objects.money import Money  # noqa: PLC0415

    return FineType(
        name=name,
        tenant_id=session.tenant_id,
        is_active=active,
        deactivated_at=None if active else _deactivated_at(existing),
        fine_type_id=None if existing is None else existing.fine_type_id,
        standard_amount=Money(_parse_amount(value)),
    )


def _leave_type_cells(entry: Any) -> str:
    return f"{entry.name}|{entry.duration_label()}"


def _leave_type_value(entry: Any) -> str:
    return str(entry.default_duration_minutes)


def _build_leave_type(existing: Any, name: str, value: str, session: Any, active: bool) -> Any:
    from src.domain.value_objects.catalogs import LeaveType  # noqa: PLC0415

    return LeaveType(
        name=name,
        tenant_id=session.tenant_id,
        is_active=active,
        deactivated_at=None if active else _deactivated_at(existing),
        leave_type_id=None if existing is None else existing.leave_type_id,
        default_duration_minutes=_parse_minutes(value),
        # ROOT tavanı AÇIQ bağlantıdan oxunur: sətir və tavan eyni
        # tranzaksiyadan gəlməlidir, əks halda Root tavanı elə həmin an
        # qaldırsaydı yazı köhnə tavanla rədd edilərdi.
        max_duration_minutes=_root_leave_duration_ceiling(session),
    )


def _root_leave_duration_ceiling(session: Any) -> int:
    """`LEAVE_TYPE_MAX_DURATION_MINUTES` — mənbə `system_limits`.

    Oxu uğursuz olarsa modul fallback-ı qaytarılır: limit sətri olmayan
    quraşdırmada (miqrasiya hələ tətbiq edilməyib) kataloq ekranı
    açılmamazlıq etməməlidir.
    """
    from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey  # noqa: PLC0415

    key = SystemLimitKey.LEAVE_TYPE_MAX_DURATION_MINUTES
    fallback = int(DEFAULT_LIMITS[key])
    try:
        return int(session.limits.get_int(session.tenant_id, key.value, fallback))
    except Exception:
        _error_log.exception("LEAVE_TYPE_CEILING_READ_FAILED")
        return fallback


def _deactivated_at(existing: Any) -> Any:
    """Deaktiv sətrin çıxarılma anı — yoxdursa CARİ an.

    `None` qaytara bilmərik: `CatalogEntry` deaktiv sətir üçün bu sahəni
    MƏCBURİ edir («nə vaxt çıxarıldı?» sualı auditdə cavablanmalıdır).
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    moment = getattr(existing, "deactivated_at", None)
    return moment if moment is not None else datetime.now(UTC)


def _parse_schedule(raw: str) -> Any:
    """«09:00–18:00» → `TimeRange`. Sərbəst növbə üçün `None`.

    Həm qısa tire (`-`), həm uzun tire (`–`) qəbul edilir: klaviaturada
    yazılan simvol ikincisi deyil, ekranda göstərilən isə odur — istifadəçini
    simvol seçiminə görə rədd etmək mənasız maneədir.

    Boş dəyər BURAYA GƏLMİR (dialoq onu tutur); «sərbəst» sözü isə qəsdən
    dəstəklənir, çünki «Növbəli 2/2» kimi rejimlərdə sabit saat yoxdur (bax
    `WorkMode` docstring).
    """
    from src.domain.value_objects.scheduling import TimeRange  # noqa: PLC0415

    cleaned = raw.strip()
    if cleaned.casefold().startswith("sərbəst"):
        return None

    parts = cleaned.replace("–", "-").split("-")
    expected_parts = 2
    if len(parts) != expected_parts:
        raise CatalogInputError(
            "Saat aralığı «09:00–18:00» formatında olmalıdır",
            user_message="Saat aralığını «09:00–18:00» şəklində yazın.",
        )
    return TimeRange(_parse_time(parts[0]), _parse_time(parts[1]))


def _parse_time(raw: str) -> Any:
    from datetime import datetime  # noqa: PLC0415

    try:
        parsed = datetime.strptime(raw.strip(), "%H:%M")  # noqa: DTZ007 - yalnız SS:DD
    except ValueError as error:
        raise CatalogInputError(
            f"Saat oxunmadı: {raw!r}",
            user_message="Saatı SS:DD formatında yazın (məsələn 09:00).",
        ) from error
    return parsed.time()


def _parse_amount(raw: str) -> Decimal:
    """«25», «25.50», «25,50 ₼» → `Decimal`.

    Vergül nöqtəyə çevrilir və valyuta işarəsi atılır: ekranda məbləğ «25 ₼»
    kimi göstərilir və istifadəçi onu olduğu kimi geri yazır — həmin mətni
    rədd etmək öz göstərdiyimiz formatı rədd etmək olardı.
    """
    cleaned = raw.replace("₼", "").replace(",", ".").strip()
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError) as error:
        raise CatalogInputError(
            f"Məbləğ oxunmadı: {raw!r}",
            user_message="Məbləği rəqəmlə yazın (məsələn 25 və ya 25.50).",
        ) from error


def _parse_minutes(raw: str) -> int:
    cleaned = raw.replace("dəq", "").strip()
    try:
        return int(cleaned)
    except ValueError as error:
        raise CatalogInputError(
            f"Müddət oxunmadı: {raw!r}",
            user_message="Müddəti dəqiqə ilə, rəqəmlə yazın (məsələn 45).",
        ) from error


def _work_mode_id(entry: Any) -> Any:
    return entry.work_mode_id


def _fine_type_id(entry: Any) -> Any:
    return entry.fine_type_id


def _leave_type_id(entry: Any) -> Any:
    return entry.leave_type_id


_ADAPTERS: dict[str, _CatalogAdapter] = {
    "work_modes": _CatalogAdapter(
        key="work_modes",
        dialog_title_new="Yeni İş Rejimi",
        dialog_title_edit="İş Rejimini Redaktə Et",
        value_label="Saat aralığı",
        value_hint="Məsələn «09:00–18:00». Sabit saatı olmayan rejim üçün «sərbəst» yazın.",
        use_case=lambda session: session.work_modes,
        cells=_work_mode_cells,
        value_of=_work_mode_value,
        build=_build_work_mode,
        identifier=_work_mode_id,
    ),
    "fine_types": _CatalogAdapter(
        key="fine_types",
        dialog_title_new="Yeni Cərimə Növü",
        dialog_title_edit="Cərimə Növünü Redaktə Et",
        value_label="Standart məbləğ (AZN)",
        value_hint=(
            "Kamera Operatoru bu məbləği DƏYİŞƏ BİLMİR — yalnız növü seçir. "
            "Dəyişiklik keçmiş cərimələrə təsir etmir."
        ),
        use_case=lambda session: session.fine_types,
        cells=_fine_type_cells,
        value_of=_fine_type_value,
        build=_build_fine_type,
        identifier=_fine_type_id,
    ),
    "leave_types": _CatalogAdapter(
        key="leave_types",
        dialog_title_new="Yeni İcazə Növü",
        dialog_title_edit="İcazə Növünü Redaktə Et",
        value_label="Tövsiyə olunan müddət (dəqiqə)",
        value_hint=("Yalnız kateqoriyalaşdırma/güzəşt üçündür — gecikmə düsturunu DƏYİŞMİR."),
        use_case=lambda session: session.leave_types,
        cells=_leave_type_cells,
        value_of=_leave_type_value,
        build=_build_leave_type,
        identifier=_leave_type_id,
    ),
}


__all__ = ["CATALOG_KEYS", "CatalogAdminController", "CatalogInputError"]
