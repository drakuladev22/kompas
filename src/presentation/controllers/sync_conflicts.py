"""Sinxronizasiya konfliktlərinin YAZI yolu — bölmə 5 (offline rejim).

`SyncConflictUseCase` ARTIQ yazılıb və `composition.py`-da bağlıdır; burada
YALNIZ ekran ↔ use case körpüsü qurulur (`controllers/__init__.py` başlığı:
kontrollerdə iş məntiqi YOXDUR).

──────────────────────────────────────────────────────────────────────────────
NİYƏ ÖZ KONTROLLERİ VAR (CLAUDE.md §6)
──────────────────────────────────────────────────────────────────────────────
Ekran HƏM oxuyur (`inbox`), HƏM yazır (`resolve`) və hər yazıdan sonra siyahı
YENİDƏN oxunmalıdır: həll edilmiş konflikt `list_open`-dan ÇIXIR. Siyahıda
qalsaydı, HR onu ikinci dəfə həll etməyə çalışar və `resolved_at IS NULL`
şərtinə görə sükutla heç nə baş verməzdi — yəni istifadəçi "düymə işləmir"
görərdi. Bu dövrə `populate()`-ın tək çağırışından uzun yaşayır, ona görə
`screen_data.py` bağlaması yararsızdır (`controllers/annual_leave.py` və
`controllers/exceptions.py` ilə eyni qərar).

YENİDƏN OXUMA PARALEL İSTİFADƏÇİYƏ GÖRƏ DƏ LAZIMDIR: eyni konflikti iki HR
eyni anda aça bilər. Birinci qərar verəndə ikincinin siyahısı köhnəlir; ona
görə hər əməliyyatdan sonra `inbox()` təzədən çağırılır və `resolve` uğursuz
olsa da çağırılır (bax `_on_resolve`).

SESSİYA SAXLANILMIR: hər əməliyyat üçün yeni sessiya açılır və commit edilir.
Konflikt paneli saatlarla açıq qala bilər; uzun-ömürlü tranzaksiya bu müddət
boyu `sync_conflicts` sətirlərində kilid saxlayardı və `SyncEngine`-in YENİ
konflikt yazması bloklanardı — yəni offline bufer boşalmazdı.

──────────────────────────────────────────────────────────────────────────────
QƏRAR GERİ ALINA BİLMİR
──────────────────────────────────────────────────────────────────────────────
`PostgresSyncConflictRepository.resolve` `AND resolved_at IS NULL` şərti ilə
yazır: bağlanmış konflikt ikinci dəfə həll edilmir. Ona görə "artıq həll
olunub" halı XƏTA kimi deyil, SAKİT məlumat kimi göstərilir
(`ALREADY_RESOLVED_NOTICE`) — istifadəçi səhv etməyib, sadəcə başqası ondan
əvvəl davranıb.

──────────────────────────────────────────────────────────────────────────────
`MERGED` — SAHƏ-SƏVİYYƏLİ BİRLƏŞDİRMƏ AXINI QURULMADI (VARİANT (a))
──────────────────────────────────────────────────────────────────────────────
`SyncConflictUseCase.resolve(...)` imzası YALNIZ `resolution` və `note`
qəbul edir; nə repository, nə use case sahə-sahə seçim yazmır. Ona görə
"hansı sahəni hansı tərəfdən götürüm" seçicisi QURULMADI — mövcud olmayan
imkanı ekranda göstərmək istifadəçiyə söz verib saxlamamaq olardı.

`MERGED` variantı isə SİYAHIDAN ÇIXARILMADI: o, `sync_conflicts.resolution`
sütununun `CHECK` dəyərlərindən biridir və gizlətsəydik baza səviyyəsində
legitim olan qərar heç bir yolla qeyd edilə bilməzdi. Əvəzinə variant use
case-də RƏSMİLƏŞDİRİLDİ ("əl ilə düzəldiləcək"): heç nə yazılmır, audit izi
`applied_version = "REMOTE"` + `manual_correction_required = True` saxlayır.

`hint` MƏTNİ HƏMİN SƏMİMİYYƏTİ TƏKRARLAYIR: HR düyməni basmazdan ƏVVƏL
qeydin dəyişməyəcəyini oxuyur. Əvvəlki mətn nə ediləcəyini deyirdi, nə
EDİLMƏYƏCƏYİNİ isə yox — istifadəçi "birləşdirdim" zənn edə bilərdi.

ÜÇ VARİANTIN HƏR BİRİNDƏ `hint` İNDİ NƏTİCƏNİ DƏ YAZIR: `KEPT_LOCAL` qeydi
ƏVƏZ EDİR (artıq faktiki yazıdır), `KEPT_REMOTE` isə heç nə dəyişmir, çünki
konflikt anında hədəf sətirdə onsuz da bulud versiyası durur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from src.application.use_cases.sync_conflicts import (
    MIN_NOTE_LENGTH,
    ConflictItem,
    ConflictNotFoundError,
    Resolution,
)
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext
    from src.presentation.screens.sync_conflicts import SyncConflictScreen

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Başqası artıq həll edibsə göstərilən SAKİT mətn (bax modul başlığı).
ALREADY_RESOLVED_NOTICE = (
    "Bu konflikt artıq həll olunub — siyahı yeniləndi. Qərarı başqa istifadəçi sizdən əvvəl yazıb."
)

#: Siyahı ümumiyyətlə oxunmadıqda göstərilən mətn.
LIST_READ_FAILED = "Konflikt siyahısı oxunmadı. Yenidən cəhd edin."

#: Yazı uğursuz olduqda göstərilən ümumi mətn (domen istisnası deyil).
RESOLVE_FAILED = "Qərar yazılmadı. Yenidən cəhd edin."

#: Cədvəl adı → Azərbaycanca başlıq.
#:
#: NİYƏ BURADA, EKRANDA DEYİL: ad `sync.SYNCABLE_TABLES` ağ siyahısından gəlir
#: (dörd cədvəl) və o, infrastruktur qərarıdır. Naməlum ad üçün XAM ad
#: göstərilir — "naməlum cədvəl" yazsaydıq, HR nəyə baxdığını bilməzdi,
#: halbuki xam ad ən azı dəqiqdir.
TABLE_LABELS_AZ: Final[dict[str, str]] = {
    "attendance_records": "Davamiyyət qeydləri",
    "leave_requests": "İcazə sorğuları",
    "fines": "Cərimələr",
    "audit_logs": "Audit jurnalı",
}

#: `Resolution` variantlarının izahı — `label_az` USE CASE-dən gəlir, burada
#: YALNIZ "bu seçim nə deməkdir" sətri yazılır.
RESOLUTION_HINTS: Final[dict[Resolution, str]] = {
    Resolution.KEPT_LOCAL: (
        "Mağaza PC-sindəki dəyər doğrudur (operator hadisəni görüb). "
        "QEYD: qeyd hazırda buluddakı dəyəri saxlayır — bu seçim onu "
        "mağazadakı dəyərlə ƏVƏZ EDƏCƏK."
    ),
    Resolution.KEPT_REMOTE: (
        "Buluddakı dəyər doğrudur (mağazadakı yazı köhnəlib). "
        "Qeyd DƏYİŞMİR — buluddakı dəyər onsuz da qüvvədədir."
    ),
    Resolution.MERGED: (
        "Sistem sahə-sahə birləşdirmə APARMIR: bu seçim qeydə HEÇ NƏ yazmır və "
        "buluddakı dəyər qüvvədə qalır. Birləşdirilmiş dəyəri müvafiq ekranda "
        "əl ilə qurun, qeyddə isə hansı sahəni hansı tərəfdən götürdüyünüzü "
        "yazın — düzəliş aparılana qədər iş YARIMÇIQDIR."
    ),
}

#: Bir dəyərin ekranda göstərilən maksimum uzunluğu.
#:
#: `local_version`/`remote_version` `JSONB`-dir və bir sahə bütöv mətn (məs.
#: cərimə izahı) daşıya bilər. Kəsilməsə sətir bütün kartı — deməli ekranı —
#: genişləndirərdi (bax `data_table.py`-dakı eyni izah). Kəsilmə YALNIZ
#: GÖRÜNTÜYƏ aiddir: qərar həmin sahənin FƏRQLİ olub-olmamasına görə verilir,
#: fərq isə `differing_fields()` tərəfindən TAM dəyər üzərində hesablanır.
MAX_VALUE_CHARS: Final = 96


class SyncConflictController:
    """«Sinxronizasiya Konfliktləri» ekranını `SyncConflictUseCase`-ə bağlayır."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor
        #: `str(conflict_id) → ConflictItem` — müqayisə panelini ƏLAVƏ sorğu
        #: olmadan qurmaq üçün. Sessiya DEYİL, sadəcə son oxunuşun nəticəsi;
        #: hər `refresh()` onu tamamilə əvəz edir.
        self._items: dict[str, ConflictItem] = {}

    # ------------------------------- qoşulma ---------------------------------- #

    def attach(self, screen: SyncConflictScreen) -> None:
        screen.conflict_selected.connect(lambda conflict_id: self._on_selected(screen, conflict_id))
        screen.resolve_requested.connect(lambda payload: self._on_resolve(screen, payload))
        screen.refresh_requested.connect(lambda: self.refresh(screen))
        screen.set_resolutions(resolution_options())
        screen.set_note_min_length(MIN_NOTE_LENGTH)
        self.refresh(screen)

    def refresh(self, screen: SyncConflictScreen) -> None:
        """Həll gözləyən konfliktləri yenidən oxuyur.

        `inbox()` audit-kritikləri əvvələ çıxarır — sıra BURADA
        dəyişdirilmir, çünki qərar use case-dədir və maket də eyni sıranı
        göstərməlidir.
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                items = session.sync_conflicts.inbox(tenant_id=session.tenant_id, actor=self._actor)
        except KompasOSError as error:
            # Səlahiyyəti olmayan istifadəçi bu ekranı ümumiyyətlə görməməli
            # idi (menyu flag-i), lakin görsə — səbəb AÇIQ yazılır.
            self._items = {}
            screen.set_conflicts([])
            screen.show_error(title="Konfliktlər oxunmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("SYNC_CONFLICT_LIST_FAILED")
            self._items = {}
            screen.set_conflicts([])
            screen.show_error(title="Konfliktlər oxunmadı", message=LIST_READ_FAILED)
            return

        self._items = {str(item.conflict_id): item for item in items}
        screen.set_conflicts([_to_list_row(item) for item in items])
        # İlk sətir avtomatik seçilir: HR ekranı açan kimi müqayisəni görür,
        # boş panelə baxıb "hara basım?" sualı vermir.
        if items:
            self._show(screen, str(items[0].conflict_id))
        else:
            screen.set_comparison({}, [])

    # ------------------------------- oxu yolu --------------------------------- #

    def _on_selected(self, screen: SyncConflictScreen, conflict_id: str) -> None:
        self._show(screen, conflict_id)

    def _show(self, screen: SyncConflictScreen, conflict_id: str) -> None:
        """Seçilmiş konflikti müqayisə panelinə yazır.

        Element keşdə yoxdursa (paralel həll → siyahı köhnəlib) panel
        BOŞALDILIR və sakit izah verilir; yeni sorğu göndərilmir, çünki
        `refresh()` onsuz da növbəti addımdır.
        """
        item = self._items.get(conflict_id)
        if item is None:
            screen.set_comparison({}, [])
            screen.show_notice(ALREADY_RESOLVED_NOTICE)
            return
        screen.set_comparison(_to_detail(item), _to_field_rows(item))

    # ------------------------------ yazı yolu --------------------------------- #

    def _on_resolve(self, screen: SyncConflictScreen, payload: Any) -> None:
        """Qərar düyməsi — konflikti bağlayır və siyahını YENİDƏN oxuyur."""
        if not isinstance(payload, dict):  # pragma: no cover - tip qoruyucusu
            return

        conflict_id = str(payload.get("id", ""))
        item = self._items.get(conflict_id)
        if item is None:
            screen.show_notice(ALREADY_RESOLVED_NOTICE)
            self.refresh(screen)
            return

        resolution = _parse_resolution(str(payload.get("resolution", "")))
        if resolution is None:
            screen.show_form_error("Qərar variantı tanınmadı.")
            return

        note = str(payload.get("note", ""))
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.sync_conflicts.resolve(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    conflict_id=item.conflict_id,
                    resolution=resolution,
                    note=note,
                )
                session.commit()
        except ConflictNotFoundError:
            # Başqası artıq həll edib — bu, SƏHV deyil. Siyahı yenilənir ki,
            # sətir yox olsun və HR onu bir daha seçə bilməsin.
            screen.show_notice(ALREADY_RESOLVED_NOTICE)
            self.refresh(screen)
            return
        except KompasOSError as error:
            # Qısa səbəb və səlahiyyət qapısı bura düşür. Siyahı YENİLƏNMİR:
            # heç nə dəyişməyib və yenidən oxuma HR-ın yazdığı qeydi silərdi.
            screen.show_form_error(error.user_message)
            return
        except Exception:
            _error_log.exception("SYNC_CONFLICT_RESOLVE_FAILED", extra={"id": conflict_id})
            screen.show_form_error(RESOLVE_FAILED)
            return

        # Yazıdan SONRA siyahı təzədən oxunur: həll edilmiş konflikt
        # `list_open`-dan çıxır və sonuncu bağlananda «Sistem Sağlamlığı»
        # xəbərdarlığı da sönür — sayğac EYNİ repo-dan oxunur
        # (`screen_data._open_conflicts`), ona görə əlavə iş tələb olunmur.
        self.refresh(screen)


# --------------------------------------------------------------------------- #
# Çeviricilər — açarlar `preview_screens._sync_conflicts` ilə EYNİDİR
# --------------------------------------------------------------------------- #


def resolution_options() -> list[dict[str, str]]:
    """`Resolution` → ekranın gözlədiyi `code`/`label`/`hint` sözlükləri.

    Etiket UYDURULMUR: `Resolution.label_az` tətbiq qatındadır və bu funksiya
    onu OLDUĞU KİMİ ötürür (bax `screens/sync_conflicts.py` başlığı).
    """
    return [
        {
            "code": resolution.value,
            "label": resolution.label_az,
            "hint": RESOLUTION_HINTS.get(resolution, ""),
        }
        for resolution in Resolution
    ]


def _to_list_row(item: ConflictItem) -> dict[str, str]:
    """`ConflictItem` → siyahı sətrinin FAKTİKİ açarları."""
    return {
        "id": str(item.conflict_id),
        "table_label": TABLE_LABELS_AZ.get(item.table_name, item.table_name),
        "record_label": _record_label(item),
        "detected": item.detected_at.astimezone().strftime("%d.%m.%Y %H:%M"),
        "diff_count": f"{len(item.differing_fields())} sahə fərqlidir",
        "audit_critical": "1" if item.is_audit_critical else "0",
    }


def _to_detail(item: ConflictItem) -> dict[str, str]:
    """Müqayisə panelinin başlığı — siyahı sətri ilə EYNİ açarlar.

    İki ayrı sözlük qurulmur: eyni məlumat iki formada olsaydı, biri
    dəyişəndə digəri arxada qalardı.
    """
    return _to_list_row(item)


def _to_field_rows(item: ConflictItem) -> list[dict[str, str]]:
    """Sahə-sahə müqayisə — FƏRQLİ sahələr ƏVVƏLDƏ.

    Sıralama burada edilir, ekranda yox: `differing_fields()` fərqin YEGANƏ
    mənbəyidir və ekran onu təkrar hesablamamalıdır (iki hesablama
    ayrılsaydı, vurğulanan sahə ilə həqiqi fərq üst-üstə düşməyə bilərdi).
    """
    differing = set(item.differing_fields())
    keys = set(item.local_version) | set(item.remote_version)
    ordered = sorted(keys, key=lambda key: (key not in differing, key))
    return [
        {
            "field": key,
            "local": _format_value(item.local_version.get(key)),
            "remote": _format_value(item.remote_version.get(key)),
            "differs": "1" if key in differing else "0",
        }
        for key in ordered
    ]


def _record_label(item: ConflictItem) -> str:
    """«Qeyd: a1b2c3d4…» — tam UUID sətri kartı genişləndirərdi.

    Qısaldılmış forma İDENTİFİKASİYA üçün kifayətdir (bir tenantda eyni
    prefiksli iki açıq konflikt praktiki olaraq olmur), tam dəyər isə audit
    jurnalındadır — orada kəsilmir.
    """
    return f"Qeyd: {str(item.record_id)[:8]}"


def _format_value(value: Any) -> str:
    """`JSONB` dəyərini bir sətirlik mətnə çevirir.

    `None` → «(boş)»: xam "None" İngiliscədir və eyni zamanda "boş sətir"
    ilə "sahə ümumiyyətlə yoxdur" halını ayırd etmir. Ayırd etmək VACİBDİR:
    bir versiyada olmayan sahə də fərqdir.
    """
    if value is None:
        return "(boş)"
    text = " ".join(str(value).split())
    if len(text) <= MAX_VALUE_CHARS:
        return text
    return f"{text[:MAX_VALUE_CHARS]}…"


def _parse_resolution(code: str) -> Resolution | None:
    try:
        return Resolution(code)
    except ValueError:
        return None


__all__ = [
    "ALREADY_RESOLVED_NOTICE",
    "LIST_READ_FAILED",
    "MAX_VALUE_CHARS",
    "RESOLUTION_HINTS",
    "RESOLVE_FAILED",
    "TABLE_LABELS_AZ",
    "SyncConflictController",
    "resolution_options",
]
