"""Tətbiq qatının ROOT parametrlərini oxuyan tək nöqtə (Faza 10.2).

──────────────────────────────────────────────────────────────────────────────
BU MODUL NİYƏ VAR — ON BİR USE CASE-DƏ EYNİ ÜÇ SƏTRİ TƏKRARLAMAMAQ ÜÇÜN
──────────────────────────────────────────────────────────────────────────────
Faza 10.2-yə qədər hər use case öz `_limit_int()` metodunu yazırdı (bax
`leave_verification`, `morning_check_in`, `open_shift_market`). Beş nüsxə hələ
idarə olunandır; on altı nüsxə isə qaçılmaz olaraq ayrılır — biri mənfi dəyəri
fallback-a çevirir, digəri çevirmir və eyni ROOT sətri iki ekranda fərqli
davranır. Ona görə oxu qaydası BURADA bir dəfə yazılıb.

Naxış `infrastructure/config/limits.py` (`InfrastructureLimits`) ilə eynidir və
bu, TƏKRAR DEYİL: qat qaydası (CLAUDE.md §3) `application`-ın `infrastructure`
idxalını qadağan edir, yəni həmin sinif bu qatdan çağırıla bilməz. İki modul
eyni ÜÇ HİSSƏLİ naxışı öz qatında tətbiq edir — açar və defolt isə TƏK
mənbədədir (`domain/policies.py`), yəni ədədlər ayrıla bilmir.

──────────────────────────────────────────────────────────────────────────────
`limits` NİYƏ `None` OLA BİLİR
──────────────────────────────────────────────────────────────────────────────
Bəzi use case-lər (audit baxışı, dəstək söhbəti, konflikt inbox-u, ilk
quraşdırma sihirbazı) `SystemLimits` portunu tarixən ALMIRDI. Portu MƏCBURİ
etmək onların bütün mövcud qurulma nöqtələrini eyni anda dəyişmək demək
olardı; layihə bu halda `ShiftSwapUseCase(labor=None)` / `SalesReviewQueue
UseCase(points=None)` / `InfrastructureLimits(limits=None)` naxışını işlədir —
asılılıq İSTƏYƏ BAĞLI əlavə olunur, `None` isə "ROOT oxunmur, fallback işləyir"
deməkdir. Beləliklə köçürmə HEÇ BİR mövcud çağırışı sındırmır (davranış
eynidir), lakin port bağlanan kimi dəyər CANLI olur.

──────────────────────────────────────────────────────────────────────────────
KLAMP NİYƏ MƏCBURİDİR
──────────────────────────────────────────────────────────────────────────────
`system_limits.set_value()` sərbəst mətn yazır. Səhifə ölçüsünə `0` düşsə
siyahı HƏMİŞƏ boş qayıdardı və istifadəçi "məlumat yoxdur" ilə "limit sıfırdır"
arasındakı fərqi heç bir ekranda görə bilməzdi; SLA hədəfinə `0` düşsə hər
müraciət elə ilk saniyədə "pozulub" nişanı alardı. Ona görə hər açarın SƏRT
aralığı var (`APP_LIMIT_BOUNDS`) və oxunan dəyər həmin aralığa KLAMP edilir —
istisna atmaq əvəzinə, çünki səhv konfiqurasiya ekranı AÇILMAZ etməməlidir.

Aralıqlar migrations/034-dəki `min_value`/`max_value` sütunları ilə EYNİDİR;
`tests/unit/test_application_root_limits.py` bu pariteti qapı kimi yoxlayır.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Final

from src.domain.policies import DEFAULT_LIMITS, SystemLimitKey
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from src.domain.interfaces.ports import SystemLimits
    from src.domain.value_objects.identifiers import TenantId

_log = get_logger(__name__)


#: Açar → (minimum, maksimum). migrations/034 ilə HƏRFƏN eyni dəyərlər.
#:
#: `LICENSE_PAYMENT_REMINDER_OFFSET_DAYS` BURADA YOXDUR: cədvəlin elementləri
#: MƏNFİ ola bilər (T-7 = bitmədən yeddi gün əvvəl) və hər hansı ədədi aralıq
#: onları sükutla sıfıra sıxardı — yəni "bitmədən əvvəl xəbərdar et" mərhələsi
#: yox olardı. Cədvəlin doğruluğu `limit_int_tuple` içində FORMAT yoxlaması
#: ilə qorunur (yararsız element buraxılır, boş nəticə defolta qayıdır).
APP_LIMIT_BOUNDS: Final[dict[SystemLimitKey, tuple[Decimal, Decimal]]] = {
    # SLA hədəfi: 1 saatdan az öhdəlik ölçülə bilməz (panel saatla işləyir),
    # 720 saat = 30 gün isə artıq "SLA yoxdur" deməkdir.
    SystemLimitKey.SUPPORT_FIRST_RESPONSE_SLA_HOURS: (Decimal(1), Decimal(720)),
    SystemLimitKey.SUPPORT_RESOLUTION_SLA_HOURS: (Decimal(1), Decimal(2160)),
    # Nisbət 1.00 ola BİLMƏZ: o zaman "risk altında" zolağı sıfır enli olardı
    # və vəziyyət `ON_TRACK`-dən birbaşa `BREACHED`-ə keçərdi — xəbərdarlıq
    # mərhələsi faktiki söndürülərdi.
    SystemLimitKey.SUPPORT_SLA_AT_RISK_RATIO: (Decimal("0.10"), Decimal("0.99")),
    # Aşağı hüdud 5 san.: daha qısası mobil şəbəkədə HƏMİŞƏ taymauta
    # düşərdi və bildiriş heç vaxt getməzdi. Yuxarı hüdud 120 san.:
    # daha uzunu fon sapını lazımsız yerə saxlayardı.
    SystemLimitKey.TELEGRAM_REQUEST_TIMEOUT_SECONDS: (Decimal(5), Decimal(120)),
    # Aşağı hüdud 5 san.: Telegram sorğu həddi (rate limit) daha
    # sıx yoxlamada botu müvəqqəti bloklayır.
    SystemLimitKey.TELEGRAM_POLL_INTERVAL_SECONDS: (Decimal(5), Decimal(3600)),
    # Aşağı hüdud 1 gün: sıfır «dərhal bağla» demək olardı və işçinin
    # etiraz pəncərəsini tamamilə kəsərdi. Yuxarı hüdud 90 gün —
    # ondan uzunu praktikada «heç vaxt bağlanmır» deməkdir.
    SystemLimitKey.SUPPORT_AUTO_CLOSE_DAYS: (Decimal(1), Decimal(90)),
    SystemLimitKey.SUPPORT_WAITING_REMINDER_DAYS: (Decimal(1), Decimal(90)),
    # Aşağı hüdud 2: 1 yazılsaydı HƏR çökmə "kütləvi" görünərdi.
    SystemLimitKey.CRASH_WIDESPREAD_INSTALLATION_THRESHOLD: (Decimal(2), Decimal(1000)),
    SystemLimitKey.CRASH_DASHBOARD_TOP_LIMIT: (Decimal(1), Decimal(500)),
    # Ən azı bugünə (1 gün) sorğu verilə bilməlidir; 365 gündən uzaq sorğu
    # planlaşdırılmamış təqvimə yazılardı.
    SystemLimitKey.SHIFT_SWAP_MAX_LEAD_DAYS: (Decimal(1), Decimal(365)),
    # Səhifə ölçüləri — aşağı hüdud HƏMİŞƏ 1 (bax modul başlığı).
    SystemLimitKey.SALES_REVIEW_QUEUE_PAGE_SIZE: (Decimal(1), Decimal(5000)),
    SystemLimitKey.AUDIT_LOG_MAX_PAGE_SIZE: (Decimal(1), Decimal(5000)),
    SystemLimitKey.AUDIT_LOG_DEFAULT_PAGE_SIZE: (Decimal(1), Decimal(5000)),
    SystemLimitKey.BACKUP_HISTORY_PAGE_SIZE: (Decimal(1), Decimal(1000)),
    SystemLimitKey.ANNOUNCEMENT_LIST_PAGE_SIZE: (Decimal(1), Decimal(1000)),
    SystemLimitKey.SUPPORT_THREAD_PAGE_SIZE: (Decimal(1), Decimal(500)),
    SystemLimitKey.SYNC_CONFLICT_PAGE_SIZE: (Decimal(1), Decimal(2000)),
    # Bir admin MİNİMUMDUR: sıfır tövsiyə ilə sihirbaz heç vaxt xəbərdarlıq
    # göstərməzdi və "tək adam bütün sistemi idarə edir" riski görünməz qalardı.
    SystemLimitKey.SETUP_RECOMMENDED_ADMIN_COUNT: (Decimal(1), Decimal(20)),
    # --- Kampaniya çəkisi (v2backlog.md Faza 6.4), migrations/108 ---------- #
    # Aşağı hüdud 1.0 = «çəki yoxdur» (neytral element); ondan aşağısı
    # kampaniya gününü adi gündən AZ sayardı, yəni parametrin mənasını tərsinə
    # çevirərdi. Yuxarı hüdud 5.0: beş qat çəkidə bir kampaniya günü bütün
    # pəncərəni əvəz edər və «tarixi nümunə» adı yalan olardı.
    SystemLimitKey.STAFFING_CAMPAIGN_WEIGHT_MULTIPLIER: (Decimal("1.0"), Decimal("5.0")),
    # --- Sistem davamlılığı (v2backlog.md Faza 5.3/5.4), migrations/100 --- #
    # Aralıqlar miqrasiya ilə HƏRFƏN eynidir (yuxarıdakı qayda).
    SystemLimitKey.SHIFT_HANDOFF_NOTE_MAX_CHARS: (Decimal(50), Decimal(5000)),
    SystemLimitKey.SHIFT_HANDOFF_VISIBILITY_HOURS: (Decimal(1), Decimal(72)),
    # Aşağı hüdud 15 dəq.: daha qısası real bir əməliyyat üçün çatmır və
    # ehtiyat-admin işini bitirməmiş səlahiyyətini itirərdi.
    SystemLimitKey.BREAK_GLASS_MAX_DURATION_MINUTES: (Decimal(15), Decimal(1440)),
    SystemLimitKey.BREAK_GLASS_APPROVAL_WINDOW_MINUTES: (Decimal(5), Decimal(240)),
    # Aşağı hüdud 1: SIFIR mexanizmi tamamilə söndürərdi — «Root əlçatmaz
    # olanda işləyən yol» bir dəyər dəyişikliyi ilə yox edilə bilməz.
    SystemLimitKey.BREAK_GLASS_MAX_GRANTS_PER_MONTH: (Decimal(1), Decimal(10)),
    # --- Dəstək-chat sui-istifadə qorunması (v2backlog.md Faza 12.1),
    # --- migrations/107. Aralıqlar miqrasiya ilə HƏRFƏN eynidir.
    # Aşağı hüdud 3/dəq: daha aşağısı normal yazışmanı da qifləyərdi.
    SystemLimitKey.SUPPORT_CHAT_MAX_MESSAGES_PER_MINUTE: (Decimal(3), Decimal(200)),
    # Aşağı hüdud 1 dəq.: sıfır qifləməni söndürərdi; yuxarı 60 dəq. — bir
    # saati aşan «müvəqqəti» blok artıq cəza kimi qavranılır.
    SystemLimitKey.SUPPORT_CHAT_LOCKOUT_MINUTES: (Decimal(1), Decimal(60)),
}


def fallback_int(key: SystemLimitKey) -> int:
    """`DEFAULT_LIMITS`-dən tam ədəd fallback — modul sabitləri üçün.

    Modul sabiti ədədi TƏKRAR YAZMIR, bu funksiya ilə defoltdan götürür: əks
    halda eyni ədəd həm `policies.py`-da, həm use case-də yaşayardı və biri
    dəyişəndə digəri sükutla köhnələrdi.
    """
    return int(Decimal(DEFAULT_LIMITS[key]))


def fallback_decimal(key: SystemLimitKey) -> Decimal:
    """`DEFAULT_LIMITS`-dən onluq fallback."""
    return Decimal(DEFAULT_LIMITS[key])


def fallback_int_tuple(key: SystemLimitKey) -> tuple[int, ...]:
    """`DEFAULT_LIMITS`-dəki vergüllü cədvəldən tam ədəd ardıcıllığı."""
    return _parse_int_list(DEFAULT_LIMITS[key])


def limit_int(limits: SystemLimits | None, tenant_id: TenantId, key: SystemLimitKey) -> int:
    """ROOT-dan tam ədəd limit — aralığa klamp edilmiş.

    `limits is None` → `DEFAULT_LIMITS` fallback-ı (bax modul başlığı).
    """
    return int(_clamp(key, _decimal_of(limits, tenant_id, key)))


def limit_decimal(limits: SystemLimits | None, tenant_id: TenantId, key: SystemLimitKey) -> Decimal:
    """ROOT-dan onluq limit — aralığa klamp edilmiş."""
    return _clamp(key, _decimal_of(limits, tenant_id, key))


def limit_int_tuple(
    limits: SystemLimits | None, tenant_id: TenantId, key: SystemLimitKey
) -> tuple[int, ...]:
    """ROOT-dan vergüllü tam ədəd cədvəli (mənfi elementlər DƏSTƏKLƏNİR).

    BOŞ NƏTİCƏ QAYTARILMIR: Root sətri təsadüfən boşaldarsa cədvəl yox olardı
    və heç bir xatırlatma göndərilməzdi — susan planlayıcı ən pis nasazlıq
    növüdür, çünki loga heç bir xəta düşmür. Belə halda defolt cədvəl işə düşür
    (`InfrastructureLimits.int_tuple_of` ilə eyni qərar).
    """
    parsed = _parse_int_list(_raw(limits, tenant_id, key))
    return parsed or fallback_int_tuple(key)


def _parse_int_list(raw: str) -> tuple[int, ...]:
    """ "-7,-3,1" → (-7, -3, 1). Yararsız element BURAXILIR, cədvəl atılmır."""
    values: list[int] = []
    for chunk in raw.split(","):
        text = chunk.strip()
        if not text:
            continue
        try:
            values.append(int(Decimal(text)))
        except (InvalidOperation, ValueError):
            _log.warning("APP_LIMIT_LIST_ITEM_INVALID", extra={"raw_item": text})
    return tuple(values)


def _clamp(key: SystemLimitKey, value: Decimal) -> Decimal:
    """Dəyəri açarın SƏRT aralığına sıxır (aralığı olmayan açar toxunulmur)."""
    bounds = APP_LIMIT_BOUNDS.get(key)
    if bounds is None:
        return value
    low, high = bounds
    if value < low:
        _log.warning(
            "APP_LIMIT_CLAMPED",
            extra={"limit_key": key.value, "raw_value": str(value), "applied": str(low)},
        )
        return low
    if value > high:
        _log.warning(
            "APP_LIMIT_CLAMPED",
            extra={"limit_key": key.value, "raw_value": str(value), "applied": str(high)},
        )
        return high
    return value


def limit_str(limits: SystemLimits | None, tenant_id: TenantId, key: SystemLimitKey) -> str:
    """Mətn dəyərli ROOT parametri (məs. `TELEGRAM_NOTIFY_MODE`).

    `_clamp` TƏTBİQ OLUNMUR: min/max hüdudları ədədi diapazon üçündür və
    mətnə mənası yoxdur. İcazəli dəyərlər siyahısını çağıran tərəf yoxlayır
    (`TelegramNotifyMode.from_value`) — belə bir siyahını bura köçürsəydik,
    hər yeni mətn parametri bu faylın dəyişməsini tələb edərdi.
    """
    return _raw(limits, tenant_id, key).strip()


def _decimal_of(limits: SystemLimits | None, tenant_id: TenantId, key: SystemLimitKey) -> Decimal:
    raw = _raw(limits, tenant_id, key)
    try:
        return Decimal(raw.strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        _log.warning("APP_LIMIT_NOT_A_NUMBER", extra={"limit_key": key.value, "raw_value": raw})
        return Decimal(DEFAULT_LIMITS[key])


def _raw(limits: SystemLimits | None, tenant_id: TenantId, key: SystemLimitKey) -> str:
    fallback = DEFAULT_LIMITS[key]
    if limits is None:
        return fallback
    try:
        return limits.get_str(tenant_id, key.value, fallback)
    except Exception as exc:
        # Oxu uğursuzluğu ƏMƏLİYYATI DAYANDIRMIR: verilməli cavab "işləsinmi"
        # deyil, "hansı hədlə" idi. Cavabsız qaldıqda fallback işləyir — eyni
        # fəlsəfə `InfrastructureLimits._raw`-dadır.
        _log.warning(
            "APP_LIMIT_READ_FAILED",
            extra={"limit_key": key.value, "error": str(exc), "fallback": fallback},
        )
        return fallback


__all__ = [
    "APP_LIMIT_BOUNDS",
    "fallback_decimal",
    "fallback_int",
    "fallback_int_tuple",
    "limit_decimal",
    "limit_int",
    "limit_int_tuple",
    "limit_str",
]
