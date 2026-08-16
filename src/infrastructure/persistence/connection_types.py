"""İKİ bazanın TİP SƏVİYYƏSİNDƏ ayrılması (DB-4 Faza 1).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRICA TİPLƏR — HALBUKİ HƏR İKİSİ EYNİ `Database` SİNFİDİR
──────────────────────────────────────────────────────────────────────────────
KompasOS iki AYRI Postgres bazasına qoşulur:

    * TENANT — müştərinin öz Supabase-i (`DATABASE_URL`). Hər quraşdırmada
      FƏRQLİDİR, bütün iş məlumatı buradadır, RLS `tenant_id` üzrədir.
    * VENDOR — təchizatçının mərkəzi bazası (`KOMPASOS_VENDOR_DSN`). BÜTÜN
      quraşdırmalarda EYNİDİR, abunə/ödəniş/lisenziya reyestrini saxlayır
      (bax `database/migrations/vendor/`).

Hər ikisi `Database` tipində olsaydı — və DB-4-ə qədər məhz belə idi — səhv
obyekti ötürmək NƏ tip xətası, NƏ də icra xətası verərdi. Sorğu sadəcə YANLIŞ
bazaya gedər və nəticə "sətir tapılmadı" kimi görünərdi. Belə qüsurun ən pis
tərəfi budur: o, işləyən sistemdə AYLARLA gizlənə bilər, çünki hər iki bazada
oxşar adlı cədvəllər var (`tenants` ↔ `license_tenants`, hər ikisində
`crash_reports`, `support_tickets`).

Ona görə ayırıcı TİPDƏDİR: `TenantDatabase` gözləyən funksiya `VendorDatabase`
qəbul etmir və mypy bunu commit-dən ƏVVƏL dayandırır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ MİRAS, NİYƏ `NewType` VƏ YA SARĞI DEYİL
──────────────────────────────────────────────────────────────────────────────
`NewType` yalnız statik yoxlamada mövcuddur və `Database`-in metodlarını
daşımır — hər çağırışda geri çevirmə lazım gələrdi. Sarğı (composition) isə
`Database`-in bütün ictimai səthini əl ilə təkrarlamağı tələb edərdi və hər
yeni metod iki yerdə yazılardı.

Miras bu iki problemi həll edir və MÖVCUD KODU POZMUR (DB-4 qırmızı xətti):
`Database` gözləyən hər mövcud funksiya hər iki tipi olduğu kimi qəbul edir.

──────────────────────────────────────────────────────────────────────────────
QORUMA HANSI SƏTİRLƏRDƏ İŞƏ DÜŞÜR
──────────────────────────────────────────────────────────────────────────────
Tip yazmaq TƏK BAŞINA heç nə qorumur — bunu təcrübə göstərdi: bu modul ilk
yazıldıqda heç bir istehsalat faylı onu idxal etmirdi, yəni mypy-ın
dayandıracağı bir imza YOX idi. Qüsur nə lint-də, nə testdə göründü; onu
paketlənmiş `.exe`-nin içinə baxmaq üzə çıxardı (modul PYZ arxivində
ümumiyyətlə yox idi, çünki idxal qrafına heç vaxt düşməmişdi).

Ona görə ayırıcı BAĞLANTININ SEÇİLDİYİ sərhədlərə yazıldı — yəni obyektin
qurulduğu və kənardan verildiyi yerlərə:

    * `composition.build_context()` — `TenantDatabase()` qurur;
    * `ApplicationContext.__init__` / `.database` — bütün iş qatının qapısı;
    * `main._run_developer_panel` — `TenantDatabase()` qurur;
    * `DeveloperTenantDirectory.__init__`, `_build_release_publisher`,
      `developer_panel.console.run_console`.

DAXİLİ istehlakçılar (repo-lar, `ErpServerRepository`, bildiriş qatı) hələ də
ümumi `Database` qəbul edir və bu, QƏSDLİDİR: onlar obyekti yalnız yuxarıdakı
sərhədlərdən ala bilirlər, yəni yanlışını almaq üçün əvvəlcə sərhəd tipini
pozmaq lazımdır. Hər imzanı dəyişmək eyni qorumanı verər, lakin ~25 faylı
məzmunsuz dəyişikliklə doldurardı.

`tests/unit/test_connection_separation.py` bu sərhədləri maşınla yoxlayır və
`src/` altında ÇILPAQ `Database()` qurulmasını qadağan edir.

──────────────────────────────────────────────────────────────────────────────
VENDOR BAĞLANTISI İSTƏYƏ BAĞLIDIR
──────────────────────────────────────────────────────────────────────────────
Müştəri quraşdırmasında `KOMPASOS_VENDOR_DSN` YOXDUR və olmamalıdır: qərar
(DB-3) budur ki, müştəri vendor bazasına nə yazır, nə də oxuyur. Ona görə
`VendorDatabase.from_env()` dəyişən boş olduqda `None` qaytarır — istisna
ATMIR. İstisna atsaydı, hər müştəri açılışı vendor bazasının mövcudluğunu
tələb edərdi.
"""

from __future__ import annotations

import os
from typing import Final

from src.infrastructure.persistence.connection import Database
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

_log = get_logger(__name__)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Vendor bazasının DSN-i. Müştəri quraşdırmasında BOŞ olur.
VENDOR_DSN_ENV: Final[str] = "KOMPASOS_VENDOR_DSN"

#: `service_role`/`postgres` `BYPASSRLS` daşıyır — vendor bazasında bu, bütün
#: RLS siyasətlərinin yan keçilməsi deməkdir (bax `migrations/vendor/002`).
_BYPASS_RLS_ROLES: Final[tuple[str, ...]] = ("service_role", "postgres", "supabase_admin")


class VendorConnectionError(KompasOSError):
    """Vendor bağlantısı qurula bilmədi."""

    user_message = "Mərkəzi lisenziya bazasına qoşulmaq mümkün olmadı."


class TenantDatabase(Database):
    """Müştərinin öz bazası — bütün iş məlumatı, RLS `tenant_id` üzrə.

    DSN mənbəyi `DATABASE_URL`-dir (bax `build_dsn_from_env`). Sinif heç bir
    davranış ƏLAVƏ ETMİR: onun bütün dəyəri TİP KİMLİYİNDƏDİR — «bu bağlantı
    müştərinindir» iddiasını maşınla yoxlana bilən hala gətirir.
    """


class VendorDatabase(Database):
    """Təchizatçının mərkəzi bazası — abunə/lisenziya reyestri.

    MÜŞTƏRİ QURAŞDIRMASINDA QURULMUR (bax modul başlığı).
    """

    @classmethod
    def from_env(cls, *, open_pool: bool = True) -> VendorDatabase | None:
        """`KOMPASOS_VENDOR_DSN` varsa bağlantı qurur, yoxdursa `None`.

        `None` NORMAL haldır və xəta deyil — müştəri quraşdırmasının gözlənilən
        vəziyyətidir. Çağıran tərəf onu «vendor konsolu bu maşında yoxdur»
        kimi oxumalıdır.

        Raises:
            VendorConnectionError: DSN VAR, lakin bağlantı qurula bilmədi —
                bu, həqiqətən nasazlıqdır (təchizatçının maşınında).
        """
        dsn = os.environ.get(VENDOR_DSN_ENV, "").strip()
        if not dsn:
            return None

        _warn_if_bypass_rls(dsn)
        try:
            return cls(dsn, open_pool=open_pool)
        except Exception as exc:
            raise VendorConnectionError(
                "Vendor bazasına qoşulmaq mümkün olmadı",
                context={"error": str(exc)},
            ) from exc


def _warn_if_bypass_rls(dsn: str) -> None:
    """`BYPASSRLS` daşıyan rolla qoşulma AÇIQ xəbərdarlıqla qeyd olunur.

    DB-3-ün əsas prinsipi qorumanın SERVERDƏ olmasıdır. `service_role` ilə
    qoşulanda isə vendor bazasındakı bütün RLS siyasətləri yan keçilir və
    qoruma yenidən "açarı gizlət" prinsipinə, yəni KLİENTƏ qayıdır. Bu, sükutla
    baş verməməlidir — ona görə `security.log`-a yazılır.

    Bloklamırıq: miqrasiyanı tətbiq edən skript məhz həmin rolla qoşulmalıdır.
    """
    from urllib.parse import urlparse  # noqa: PLC0415 - yalnız bu yolda lazımdır

    username = (urlparse(dsn).username or "").split(".")[0]
    if username in _BYPASS_RLS_ROLES:
        _security_log.critical(
            "VENDOR_DB_CONNECTED_AS_BYPASSRLS_ROLE",
            extra={
                "role": username,
                "impact": "vendor RLS siyasətləri YAN KEÇİLİR",
                "action": "`kompasos_vendor` üzvü, BYPASSRLS olmayan rol işlədin",
            },
        )


__all__ = [
    "VENDOR_DSN_ENV",
    "TenantDatabase",
    "VendorConnectionError",
    "VendorDatabase",
]
