"""Plugin səhifəsinin OXU yolu — sandbox çağırışı FONDA (audit G-3).

──────────────────────────────────────────────────────────────────────────────
BU MODUL NİYƏ VAR
──────────────────────────────────────────────────────────────────────────────
`plugin_surface.py` plugin səhifələrini qeydiyyatdan keçirirdi (imza, təsdiq,
qabiliyyət, icazə flag-i, ad məkanı — beş qapı hazır idi), lakin `app.py::
_plugin_page_factory` plugin KODUNU icra ETMİRDİ: səhifə yalnız manifestdə
ELAN olunmuş metadata göstərirdi. Səbəb sənədləşdirilmişdi —
`PluginSandbox.invoke` `subprocess.run(..., timeout=...)` ilə bloklayır və Qt
hadisə dövrəsində icra edilsəydi interfeys həmin müddət boyu donardı.

İki maneə də aradan qalxdı:

    1. `src/presentation/background_task.py` — fon-işçi naxışı (sandbox
       çağırışı Qt sap hovuzunda, nəticə siqnalla əsas sapa);
    2. `plugins.package_path` (migrations/055) — sandbox-un tələb etdiyi
       paket yolu artıq quraşdırma anında yazılır.

──────────────────────────────────────────────────────────────────────────────
BEŞ QAPI HƏR İCRADAN ƏVVƏL YENİDƏN YOXLANILIR
──────────────────────────────────────────────────────────────────────────────
Səhifə menyuda göründü — bu, "indi də icra oluna bilər" demək DEYİL. Panel
saatlarla açıq qala bilər; həmin müddətdə Root plugin-i söndürə, silə və ya
istifadəçinin icazəsi geri alına bilər. Ona görə fon işi sətri BAZADAN
YENİDƏN oxuyur və onu `collect_surface(...)` — yəni beş qapının EYNİ nüsxəsi —
üzərindən keçirir. Səhifə açarı artıq səthdə yoxdursa icra BAŞLAMIR.

Qapıların ikinci nüsxəsi BURADA YAZILMIR: `plugin_surface.py` toxunulmaz
qalır və bu modul onu ÇAĞIRIR. İkinci nüsxə bir gün birincidən ayrılardı.

──────────────────────────────────────────────────────────────────────────────
PLUGIN CAVABI ETİBARSIZ GİRİŞDİR — MƏTN KİMİ GÖSTƏRİLİR, ZƏNGİN MƏTN KİMİ YOX
──────────────────────────────────────────────────────────────────────────────
Sandbox-un qaytardığı JSON üçüncü tərəfin yazdığı koddan gəlir. Onu zəngin
mətn (HTML/Markdown) kimi render etmək plugin-ə host pəncərəsinin içində
istədiyi görünüşü çəkmək imkanı verərdi: saxta düymə, saxta xəbərdarlıq, hətta
`<img src=...>` ilə xarici ünvana sorğu. Ona görə İKİ QAT var:

    * `widgets/primitives.body_label` onsuz da `Qt.TextFormat.PlainText`
      qoyur (bax `primitives.py` başlığı) — işarələmə hərfi mətn kimi görünür;
    * BURADA isə mətn AYRICA normallaşdırılır: sətir sonu və nəzarət
      simvolları boşluğa çevrilir, uzunluq kəsilir, sətir sayı məhdudlaşır.

İkinci qat lazımdır, çünki birincisi yalnız İŞARƏLƏMƏNİ zərərsizləşdirir;
min sətirlik və ya 100 000 simvolluq cavab isə düz mətn olsa belə ekranı
yararsız edər (mənbə kartı — plugin-in KİM tərəfindən verildiyi — yuxarı
sürüşüb görünməz olardı).

HƏCM QAPISI BURADA DEYİL: cavabın bayt həddi `system_limits.
PLUGIN_SANDBOX_MAX_OUTPUT_BYTES`-dır və onu sandbox-un ÖZÜ tətbiq edir.
Aşağıdakı ədədlər konfiqurasiya deyil — BİR EKRAN SƏTRİNİN oxunaqlı qalma
həddidir və Root-un dəyişməli olduğu bir şey deyil.

──────────────────────────────────────────────────────────────────────────────
SESSİYA SAP SƏRHƏDİNİ KEÇMİR
──────────────────────────────────────────────────────────────────────────────
`load_page_rows()` FON SAPINDA icra olunur və `context.session()`-u ORADA
açır (CLAUDE.md bölmə 6, `background_task.py` başlığı). Heç nə yazılmır, ona
görə commit çağırılmır — sessiya bağlananda tranzaksiya geri qaytarılır.
Burada Qt widget-inə TOXUNULMUR: ekranı yalnız `succeeded`/`failed` slotları
(əsas sapda) yeniləyir.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from src.domain.policies import SystemLimitKey
from src.infrastructure.plugins.contracts import (
    PluginCapability,
    PluginError,
    PluginRequest,
    PluginTimeoutError,
)
from src.presentation.plugin_surface import ApprovedPlugin, collect_surface
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.presentation.background_task import TaskExecutor
    from src.presentation.composition import ApplicationContext
    from src.presentation.plugin_surface import PluginPage
    from src.presentation.screens.group_i import PluginPageScreen

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Məzmun sətrinin etiketi — MAKET və CANLI yol EYNİ açarı işlədir.
#: İki yerdə ayrıca yazılsaydı, maketdə «Məzmun», istehsalatda «Nəticə»
#: görünərdi və fərq yalnız istifadəçidə üzə çıxardı (CLAUDE.md bölmə 6).
CONTENT_LABEL: Final = "Məzmun"

#: Bölmə xətası bannerində görünən ad (`Screen.set_section_error`).
CONTENT_SECTION_LABEL: Final = "Plugin məzmunu"

#: Səhifə açılan andakı sətir — plugin hələ çağırılıb, cavab gözlənilir.
LOADING_TEXT: Final = "Plugin cavabı gözlənilir…"

#: Plugin uğurla cavab verdi, lakin heç bir sahə göndərmədi.
EMPTY_TEXT: Final = "Plugin bu səhifə üçün məlumat göndərmədi."

#: Maket rejimində göstərilən sətir — orada nə baza, nə də paket faylı var.
PREVIEW_TEXT: Final = "Maket rejimi — plugin kodu icra olunmur, nümunə metadata göstərilir."

#: Bir cavabdan göstəriləcək ƏN ÇOX sətir sayı (bax modul başlığı).
MAX_CONTENT_ROWS: Final = 40

#: Bir sətrin etiket/dəyər uzunluğu. Kəsilən mətn «…» ilə bitir ki, istifadəçi
#: cavabın TAM olmadığını görsün — sükutla qısaltmaq yanıltıcı olardı.
MAX_LABEL_CHARS: Final = 60
MAX_VALUE_CHARS: Final = 400

#: Kəsilmə nişanı.
_ELLIPSIS: Final = "…"


class PluginPageError(KompasOSError):
    """Plugin səhifəsinin məzmunu alına bilmədi.

    `user_message` HƏR halda AYRICA verilir: istifadəçinin görməli olduğu şey
    "plugin xətası" deyil, NƏYİN baş verdiyi və NƏ edə biləcəyidir (Qrup G
    qaydası). Ona görə aşağıdakı hər çağırış öz cümləsini yazır.
    """

    user_message = "Plugin səhifəsinin məzmunu alınmadı."


# --------------------------------------------------------------------------- #
# Sətirlər — Qt TƏLƏB ETMİR, birbaşa test oluna bilir
# --------------------------------------------------------------------------- #


def metadata_rows(page: PluginPage) -> list[tuple[str, str]]:
    """Plugin-in ELAN etdiyi məlumat — hər iki yolda (maket və canlı) eyni.

    Bu sətirlər plugin cavabından ASILI DEYİL və cavab gəlməsə də qalır:
    istifadəçi səhifənin kim tərəfindən və hansı səlahiyyətlə verildiyini
    HƏMİŞƏ görməlidir (bax `PluginPageScreen` başlığı — mənbə kartı).
    """
    return [
        ("Qabiliyyətlər", ", ".join(sorted(page.capabilities))),
        ("Tələb olunan icazələr", ", ".join(sorted(page.required_flags))),
        ("İcra mühiti", "Ayrıca proses (sandbox) — sirrlərə çıxışı yoxdur"),
    ]


def content_rows(data: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    """Plugin cavabını ad/dəyər sətirlərinə çevirir — ETİBARSIZ GİRİŞ kimi.

    Sıra ƏLİFBA ÜZRƏDİR: `dict` sırası plugin-in yazma sırasıdır və eyni
    plugin iki çağırışda fərqli sıra qaytara bilər — istifadəçi isə "nə
    dəyişdi?" sualını verməməlidir.

    Boş cavab XƏTA DEYİL və boş siyahı qaytarır; çağıran tərəf onu
    `EMPTY_TEXT` ilə izah edir (boş ağ ekran ən pis nəticə olardı).
    """
    if not data:
        return []

    rows: list[tuple[str, str]] = []
    for key in sorted(data)[:MAX_CONTENT_ROWS]:
        rows.append((_as_text(key, MAX_LABEL_CHARS), _as_text(data[key], MAX_VALUE_CHARS)))

    dropped = len(data) - len(rows)
    if dropped > 0:
        # KƏSİLMƏ GİZLƏDİLMİR: istifadəçi gördüyünün tam olmadığını bilməlidir,
        # əks halda "plugin sahəni göndərmədi" ilə "ekran onu göstərmədi"
        # arasında fərq qalmazdı.
        rows.append(("Qeyd", f"Cavabın ilk {MAX_CONTENT_ROWS} sahəsi göstərilir ({dropped} daha)."))
    return rows


def _as_text(value: object, limit: int) -> str:
    """Etibarsız dəyəri BİR SƏTİRLİK, uzunluğu məhdud düz mətnə çevirir.

    Sətir sonu və nəzarət simvolları boşluğa çevrilir: çoxsətirli dəyər
    cədvəlin sətir hündürlüyünü partladır və altındakı sətirləri ekrandan
    çıxarardı (mənbə kartı da daxil). `str()` isə hər tipi (rəqəm, siyahı,
    yuvalanmış obyekt) oxunaqlı bir formaya salır — plugin yalnız JSON
    göndərə bildiyi üçün başqa tip mümkün deyil.
    """
    text = "".join(
        " " if character < " " or character == "\x7f" else character for character in str(value)
    )
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 1] + _ELLIPSIS
    return text


# --------------------------------------------------------------------------- #
# Fon işi — FON SAPINDA icra olunur
# --------------------------------------------------------------------------- #


def load_page_rows(context: ApplicationContext, page: PluginPage) -> list[tuple[str, str]]:
    """Plugin-i sandbox-da çağırır və məzmun sətirlərini qaytarır.

    FON SAPINDA icra olunur (bax modul başlığı) — burada HEÇ BİR Qt
    widget-inə toxunulmur.

    Raises:
        PluginPageError: səbəbi istifadəçiyə göstərilə bilən hər hal —
            plugin silinib, söndürülüb, yolu qeydə alınmayıb, cavab vermədi,
            xəta ilə bitdi. Mesaj İSTİFADƏÇİ dilindədir və nə edəcəyini deyir.
    """
    record = _approved_record(context, page)
    manifest = record.manifest
    if manifest is None:  # pragma: no cover — `_approved_record` onu onsuz da süzür
        raise PluginPageError(
            "Manifest oxunmadı",
            user_message="Plugin-in manifesti oxunmadı — onu yenidən quraşdırın.",
        )

    package_path = record.package_path.strip()
    if not package_path:
        # FAIL-CLOSED: yol yoxdursa icra MÜMKÜN DEYİL. Səbəb açıq deyilir,
        # çünki həlli istifadəçinin əlindədir (paketi yenidən seçmək).
        _log.warning(
            "PLUGIN_PAGE_PATH_MISSING",
            extra={"plugin_id": page.plugin_id, "plugin": page.plugin_name},
        )
        raise PluginPageError(
            "Paket yolu qeydə alınmayıb",
            user_message=(
                "Bu plugin-in paket yolu qeydə alınmayıb (köhnə quraşdırma). "
                "Plugin İdarəetməsindən onu yenidən quraşdırın."
            ),
        )

    timeout_seconds = _timeout_seconds(context)
    response = _invoke(
        manifest=manifest,
        package_path=Path(package_path),
        page=page,
        timeout_seconds=timeout_seconds,
    )
    if not response.ok:
        # Sandbox cavabı "uğursuz" işarələyib (sıfırdan fərqli çıxış kodu,
        # yararsız JSON). Onun öz mətni TEXNİKİDİR — istifadəçiyə addım
        # təklif edən cümlə ilə əvəzlənir, texniki mətn isə jurnalda qalır.
        _log.warning(
            "PLUGIN_PAGE_RESPONSE_NOT_OK",
            extra={"plugin": page.plugin_name, "error": response.error or ""},
        )
        raise PluginPageError(
            f"Plugin uğursuz cavab verdi: {response.error or 'səbəb bildirilmədi'}",
            user_message=(
                "Plugin bu səhifəni hazırlaya bilmədi. Naşirin təqdim etdiyi "
                "yeni versiyanı quraşdırın və ya plugin-i söndürün."
            ),
        )
    return content_rows(response.data)


def _approved_record(context: ApplicationContext, page: PluginPage) -> Any:
    """Sətri BAZADAN yenidən oxuyur və beş qapıdan keçirir (bax modul başlığı)."""
    with context.session() as session:
        record = session.uow.repository("plugins").get(page.plugin_id)

    if record is None or record.manifest is None:
        raise PluginPageError(
            f"Plugin sətri tapılmadı: {page.plugin_id}",
            user_message="Bu plugin artıq quraşdırılmayıb — menyunu yeniləyin.",
        )

    surface = collect_surface(
        [
            ApprovedPlugin(
                plugin_id=record.plugin_id,
                name=record.name,
                publisher=record.publisher,
                status=record.status,
                signature_verified=record.signature_verified,
                manifest=record.manifest,
            )
        ]
    )
    if surface.page_for(page.key) is None:
        # Qapılardan biri artıq bağlıdır (söndürülüb, imza etibarsızdır,
        # capability/flag itib). Hansının bağlandığını `plugin_surface.py`
        # ARTIQ təhlükəsizlik jurnalına yazıb — burada təkrarlanmır.
        _security_log.warning(
            "PLUGIN_PAGE_EXECUTION_DENIED",
            extra={"plugin_id": page.plugin_id, "plugin": page.plugin_name},
        )
        raise PluginPageError(
            f"Plugin səthi qapalıdır: {page.key}",
            user_message=(
                "Bu plugin hazırda aktiv deyil (söndürülüb və ya təsdiqi geri "
                "alınıb). Plugin İdarəetməsindən vəziyyətini yoxlayın."
            ),
        )
    return record


def _invoke(
    *,
    manifest: Any,
    package_path: Path,
    page: PluginPage,
    timeout_seconds: float,
) -> Any:
    """Sandbox çağırışı — taymaut və plugin xətası İSTİFADƏÇİ mətninə çevrilir."""
    from src.infrastructure.plugins.sandbox import (  # noqa: PLC0415
        PluginSandbox,
        SandboxPolicy,
    )

    sandbox = PluginSandbox(
        manifest=manifest,
        plugin_path=package_path,
        # Whitelist manifestdən gəlir, GENİŞLƏNDİRİLMİR: `SandboxPolicy`-nin
        # öz defoltu da eynidir, lakin taymaut üçün obyekti açıq qurmalıyıq
        # və onu qurarkən `allowed_capabilities`-i unutmaq bütün çağırışları
        # bloklayardı (boş dəst = hər şey qadağan).
        policy=SandboxPolicy(
            timeout_seconds=timeout_seconds,
            allowed_capabilities=frozenset(manifest.capabilities),
        ),
    )
    request = PluginRequest(
        capability=PluginCapability.REGISTER_PAGE,
        # Plugin hansı səhifənin istənildiyini bilməlidir: bir paket gələcəkdə
        # birdən çox səhifə verə bilər və açar ONUN üçün yeganə ayırd edici
        # məlumatdır. Payload-da PII YOXDUR (bax `PluginCapability` başlığı).
        payload={"page_key": page.key},
    )

    try:
        return sandbox.invoke(request)
    except PluginTimeoutError as error:
        # TAYMAUT SÜKUTLA BOŞ SƏHİFƏ VERMİR: müddət rəqəmlə deyilir, çünki o,
        # ROOT parametridir (`PLUGIN_SANDBOX_TIMEOUT_SECONDS`) və istifadəçinin
        # növbəti addımı məhz həmin dəyəri artırmaq ola bilər.
        raise PluginPageError(
            f"Plugin taymauta düşdü: {page.plugin_name}",
            user_message=(
                f"Plugin cavab vermədi ({timeout_seconds:g} saniyə) və dayandırıldı. "
                "Müddəti ROOT İdarə Mərkəzindən artıra və ya plugin-i söndürə bilərsiniz."
            ),
        ) from error
    except PluginError as error:
        # İnterpretator tapılmadı, çıxış həddi aşıldı, capability rədd edildi.
        # `user_message` ORİJİNAL qalır — o, səbəbi DƏQİQ deyir və onu
        # ümumiləşdirmək diaqnostikanı korlayardı (eyni qərar
        # `controllers/plugin_admin.py` başlığında).
        raise PluginPageError(str(error), user_message=error.user_message) from error


def _timeout_seconds(context: ApplicationContext) -> float:
    """`PLUGIN_SANDBOX_TIMEOUT_SECONDS` — ROOT-dan, oxuna bilmirsə fallback.

    Oxu uğursuzluğu çağırışı DAYANDIRMIR: verilməli cavab "plugin işləsinmi"
    deyil, "nə qədər gözləyək" idi (`InfrastructureLimits._raw` ilə eyni
    əsaslandırma). `InfrastructureLimits` özü də fallback-a düşür, ona görə
    burada yalnız pəncərənin ÖZÜNÜN olmaması emal edilir.
    """
    from src.infrastructure.plugins.sandbox import (  # noqa: PLC0415
        FALLBACK_TIMEOUT_SECONDS,
    )

    try:
        return context.infrastructure_limits().float_of(
            SystemLimitKey.PLUGIN_SANDBOX_TIMEOUT_SECONDS
        )
    except Exception:
        _log.exception("PLUGIN_SANDBOX_TIMEOUT_READ_FAILED")
        return FALLBACK_TIMEOUT_SECONDS


# --------------------------------------------------------------------------- #
# Qt qoşulması
# --------------------------------------------------------------------------- #


def attach_plugin_page(
    screen: PluginPageScreen,
    *,
    page: PluginPage,
    context: ApplicationContext,
    executor: TaskExecutor | None = None,
) -> None:
    """Səhifəni açır və plugin çağırışını FONA buraxır.

    Args:
        screen: Artıq qurulmuş `PluginPageScreen`.
        page: Səthdən gələn səhifə tərifi (`plugin_surface.collect_surface`).
        context: Canlı obyekt qrafı — fon işi ONDAN öz sessiyasını açır.
        executor: İcraçı. `None` = Qt sap hovuzu; testlərdə `InlineExecutor`
            verilir ki, bütün axın vaxt gözləməsi olmadan yoxlansın.

    İŞÇİYƏ İSTİNAD SAXLANILMIR: o, ekranın Qt UŞAĞIDIR (`parent=screen`) və
    ekranla birlikdə ölür — gec gələn cavab silinmiş widget-ə toxuna bilmir
    (bax `background_task.py` başlığı). Eyni məntiq kontrollerlərin
    `lambda` bağlaması üçün də keçərlidir (CLAUDE.md bölmə 6).
    """
    from src.presentation.background_task import BackgroundTask  # noqa: PLC0415

    header = metadata_rows(page)
    screen.clear_section_errors()
    screen.set_rows([*header, (CONTENT_LABEL, LOADING_TEXT)])

    task = BackgroundTask(parent=screen, executor=executor, name="PLUGIN_PAGE")
    task.succeeded.connect(lambda payload: _show_content(screen, header, payload))
    task.failed.connect(lambda error: _show_failure(screen, header, error))
    task.run(lambda: load_page_rows(context, page))


def _show_content(screen: PluginPageScreen, header: list[tuple[str, str]], payload: object) -> None:
    """Uğurlu cavab — ƏSAS SAPDA icra olunur."""
    rows = payload if isinstance(payload, list) else []
    screen.clear_section_errors()
    screen.set_rows([*header, *rows] if rows else [*header, (CONTENT_LABEL, EMPTY_TEXT)])


def _show_failure(screen: PluginPageScreen, header: list[tuple[str, str]], error: object) -> None:
    """Uğursuz cavab — SƏHİFƏ QALIR, yalnız məzmun sətri xətanı deyir.

    `show_error()` İŞLƏDİLMİR: o, bütün ekranı əvəz edərdi və mənbə kartı
    (plugin-in KİM tərəfindən verildiyi) itərdi — halbuki nasazlıq anında
    məhz həmin məlumat lazımdır. Əvəzinə mövcud bölmə-xətası banneri
    (`Screen.set_section_error`) işlədilir: metadata qalır, xəta isə ÜSTDƏ
    açıq görünür.
    """
    message = (
        error.user_message
        if isinstance(error, KompasOSError)
        else "Plugin səhifəsinin məzmunu alınmadı. Plugin İdarəetməsindən vəziyyətini yoxlayın."
    )
    _log.warning(
        "PLUGIN_PAGE_CONTENT_FAILED",
        extra={"error_type": type(error).__name__, "error": str(error)[:200]},
    )
    screen.set_rows([*header, (CONTENT_LABEL, message)])
    screen.set_section_error(CONTENT_SECTION_LABEL)


__all__ = [
    "CONTENT_LABEL",
    "CONTENT_SECTION_LABEL",
    "EMPTY_TEXT",
    "LOADING_TEXT",
    "MAX_CONTENT_ROWS",
    "MAX_LABEL_CHARS",
    "MAX_VALUE_CHARS",
    "PREVIEW_TEXT",
    "PluginPageError",
    "attach_plugin_page",
    "content_rows",
    "load_page_rows",
    "metadata_rows",
]
