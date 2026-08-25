"""Fövqəladə girişin mərkəzi vendor bazasına bildirilməsi — Faza 5.4.

    "Bu, YÜKSƏK-RİSKLİ bir funksiyadır — hər istifadə mərkəzi vendor bazasına
     da yazılsın." (`v2backlog.md` Faza 5.4)

──────────────────────────────────────────────────────────────────────────────
DB-3 QƏRARI İLƏ NECƏ UZLAŞIR — «MÜŞTƏRİ VENDOR BAZASINA YAZMIR»
──────────────────────────────────────────────────────────────────────────────
`connection_types.py` sənədləşdirilmiş qərarı daşıyır: müştəri quraşdırmasında
`KOMPASOS_VENDOR_DSN` YOXDUR və müştəri vendor bazasına nə yazır, nə oxuyur.
Bu sinif həmin qərarı POZMUR — o, `VendorDatabase` tələb edir və müştəri
maşınında həmin obyekt `None` olur, yəni bildirici QURULMUR.

O zaman spesifikasiyanın «mərkəzi bazaya yazılsın» tələbi NECƏ ödənilir?
İKİ YOLLA və hər ikisi qəsdlidir:

  1. **Müştəri quraşdırması** — `break_glass_grants` sətri MÜŞTƏRİ bazasında
     tamdır (kim, nə vaxt, kim təsdiqlədi, nə qədər müddətə, səbəb). Vendor
     tərəf onu Master Panel ilə oxuyur — `service_role` + RLS kanalı
     (CLAUDE.md §9, «Master Panel mTLS əvəzinə service_role + RLS»). Yəni
     mərkəzi görünürlük VAR, lakin YAZI istiqaməti tərsdir: mərkəz OXUYUR,
     müştəri göndərmir. Bu, `crash_reports`-un EYNİ naxışıdır (cədvəl həm
     `schema.sql`-də, həm vendor sxemində var).
  2. **Təchizatçının öz mühiti** (`--developer-mode`, staging, çox-kirayəçili
     idarəetmə maşını) — orada `KOMPASOS_VENDOR_DSN` MÖVCUDDUR və bu sinif
     hadisəni `vendor.break_glass_events`-ə köçürür (migrations/vendor/004).

──────────────────────────────────────────────────────────────────────────────
NİYƏ İSTİSNA ATILMIR
──────────────────────────────────────────────────────────────────────────────
`LicenseGateway.report_crash()` uğursuzluqda `LicenseUnavailableError` atır və
orada bu DÜZGÜNDÜR: çökmə hesabatı müstəqil əməliyyatdır.

Bu sinif isə `VendorBreakGlassReporter` portunu (`ports.py`) tətbiq edir və
həmin portun kontraktı AÇIQ deyir: `report()` istisna ATMAMALIDIR, uğursuzluğu
`False` ilə bildirir. Səbəb `use_cases/break_glass.py` başlığındadır — fövqəladə
giriş ən çox məhz şəbəkə problemi olanda lazım olur; bildirişin uğursuzluğu
səlahiyyəti bloklasaydı, funksiya lazım olduğu anda işləməzdi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from src.domain.entities.break_glass import BreakGlassGrant
    from src.infrastructure.persistence.connection_types import VendorDatabase

_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

_INSERT: Final = """
    INSERT INTO vendor.break_glass_events
        (tenant_id, grant_id, requested_by, approved_by, status, reason,
         requested_at, expires_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (grant_id) DO NOTHING
"""


class VendorGatewayBreakGlassReporter:
    """`vendor.break_glass_events`-ə APPEND-ONLY yazı.

    Konstruktor `VendorDatabase` TƏLƏB EDİR (`Database` DEYİL): DB-4 tip
    ayrımının bütün mənası budur — «hansı bazaya yazırıq?» sualı mypy
    tərəfindən commit-dən ƏVVƏL cavablanır. Müştəri bazasına yazsaydıq,
    orada belə cədvəl yoxdur və qüsur yalnız istehsalatda görünərdi.
    """

    def __init__(self, database: VendorDatabase) -> None:
        self._database = database

    def report(self, grant: BreakGlassGrant) -> bool:
        """Qaytarır: sətir mərkəzi bazaya çatdımı.

        `ON CONFLICT (grant_id) DO NOTHING` — təkrar-cəhd eyni hadisəni iki
        dəfə yazmır. Təkrar çağırışda `True` qaytarılır və bu, DÜZGÜNDÜR:
        sual «indi yazıldımı?» deyil, «mərkəzdə varmı?»dır.
        """
        try:
            with (
                self._database.system_scope(tables=("break_glass_events",)) as conn,
                conn.cursor() as cur,
            ):
                cur.execute(
                    _INSERT,
                    (
                        grant.tenant_id,
                        grant.id,
                        grant.requested_by,
                        grant.approved_by,
                        grant.status.value,
                        grant.reason,
                        grant.requested_at,
                        grant.expires_at,
                    ),
                )
                conn.commit()
        except Exception as exc:
            # Səbəb mətni JURNALDA qalır: sükutla `False` qaytarmaq «niyə
            # çatmadı?» sualını cavabsız qoyardı və nasazlıq yalnız aylar
            # sonra, sinxronlaşmamış sətirlər yığılanda görünərdi.
            _security_log.warning(
                "BREAK_GLASS_VENDOR_WRITE_FAILED",
                extra={"grant_id": str(grant.id), "error": str(exc)},
            )
            return False
        return True


__all__ = ["VendorGatewayBreakGlassReporter"]
