"""`store_face_throttle` — 1:N ÜZLƏ girişin TERMİNAL sayğacı (AF-2).

──────────────────────────────────────────────────────────────────────────────
NİYƏ AYRI CƏDVƏL — ORTAQ SAYĞAC QƏRARI NİYƏ GERİ ALINDI
──────────────────────────────────────────────────────────────────────────────
`identify_for_login()` (1:N) rəddləri əvvəl `store_pin_throttle`-a, yəni PIN
girişi ilə ORTAQ sayğaca yazılırdı. Həmin qərar sənədli idi: «iki müstəqil
sayğac hücumçuya büdcəni İKİ QAT edərdi, halbuki qorunan şey EYNİ terminaldır».

Lakin o mühakimə «eyni terminalda EYNİ ADAM cəhd edir» fərziyyəsinə əsaslanır.
1:N üz girişində bu fərziyyə YOXDUR: kameranın qarşısına keçən İSTƏNİLƏN adam —
o cümlədən mağazanın işçisi olmayan kənar şəxs — sayğacı artıra bilir və heç bir
kimlik təqdim etmir. Nəticədə bir neçə dəfə kameraya baxmaq BÜTÜN mağazanın PIN
girişini dayandırırdı, yəni qoruma XİDMƏTDƏN İMTİNA vasitəsinə çevrilirdi (AF-2).

Siyasət qərarı verilib: DoS aradan qaldırılır, büdcənin iki qat olması QƏBUL
EDİLİR (Root həddi endirməklə kompensasiya edə bilər — hər iki kanal EYNİ
`KIOSK_STORE_PIN_*` açarlarını işlədir, yeni Root parametri YARADILMADI).

──────────────────────────────────────────────────────────────────────────────
VAXT/SAYĞAC HESABLAMASI BURADA YOX, DB TRIGGER-İNDƏDİR (TIME-1)
──────────────────────────────────────────────────────────────────────────────
`enforce_store_face_throttle_lockout()` (`migrations/086`) `store_pin_throttle`
trigger-inin EYNİSİDİR və eyni `system_limits` açarlarını oxuyur. Bu fayl YALNIZ
SİQNAL göndərir; `RETURNING` ilə gələn dəyərlər trigger-in HESABLADIĞI həqiqi
nəticədir. Sətrə göndərilən `failed_count` dəyəri trigger tərəfindən ignored olunur.

──────────────────────────────────────────────────────────────────────────────
`update_last_seen_store()` NİYƏ YOXDUR
──────────────────────────────────────────────────────────────────────────────
Klon aşkarlaması (eyni `machine_key`, fərqli `store_id`) PIN yolunda qalır:
`_require_unlocked_terminal` onu üz yolunda QƏSDƏN təkrarlamır (bax
`face_control.py`). Metodu «hər ehtimala qarşı» yazmaq çağırılmayan kod
demək olardı — CLAUDE.md §4 placeholder qadağası.
"""

from __future__ import annotations

from typing import Any

from src.domain.value_objects.identifiers import StoreId, TenantId
from src.domain.value_objects.machine_identity import MachineIdentityHash
from src.domain.value_objects.pin_throttle import TerminalPinThrottle
from src.infrastructure.persistence.repositories import _BaseRepository

_SELECT = """
    SELECT tenant_id, machine_key, store_id, failed_count, window_started_at,
           locked_until, updated_at
    FROM store_face_throttle
"""


def _hydrate(row: dict[str, Any]) -> TerminalPinThrottle:
    """Sətir → domen dəyəri.

    TİP `TerminalPinThrottle`-DIR VƏ BU, QƏSDƏNDİR: sətrin forması (açar,
    sayğac, sabit pəncərə, kilid) və `advance_after_failure()` spesifikasiyası
    PIN kanalı ilə EYNİDİR. İkinci dəyər obyekti yaratmaq həmin arifmetikanın
    ikinci nüsxəsini doğurardı və `pin_throttle.py` başlığındakı «sayğac ƏBƏDİ
    kilid» qüsuru iki yerdə ayrı-ayrı təkrarlana bilərdi. Fərq CƏDVƏLDƏDİR,
    tipdə yox.
    """
    return TerminalPinThrottle(
        tenant_id=TenantId(row["tenant_id"]),
        machine_key=MachineIdentityHash(row["machine_key"]),
        store_id=StoreId(row["store_id"]),
        failed_count=row["failed_count"],
        window_started_at=row["window_started_at"],
        locked_until=row["locked_until"],
        updated_at=row["updated_at"],
    )


class PostgresFaceThrottleRepository(_BaseRepository):
    """`FaceThrottleRepository` Protocol-una STRUCTURAL uyğun (miras YOX, CLAUDE.md §3)."""

    def get_for_update(
        self, tenant_id: TenantId, machine_key: MachineIdentityHash
    ) -> TerminalPinThrottle | None:
        """`SELECT ... FOR UPDATE` — sətir yoxdursa `None` (bu maşında HƏLƏ
        heç bir uğursuz ÜZ cəhdi qeydə alınmayıb, sayğac fərz olunan sıfırdır).
        """
        tenant = self._require_matching_tenant(tenant_id)
        row = self._fetch_one(
            _SELECT + " WHERE tenant_id = %s AND machine_key = %s FOR UPDATE",
            (tenant, machine_key.digest),
        )
        return _hydrate(row) if row else None

    def record_failure(
        self, tenant_id: TenantId, machine_key: MachineIdentityHash, *, store_id: StoreId
    ) -> TerminalPinThrottle:
        """Atomik artırma — `PinThrottleRepository.record_failure` ilə EYNİ müqavilə.

        İSTİSNA UDULMUR: sayğac yazılmadan «üz tanınmadı» göstərmək SEC-01-in
        kök səbəbinin təkrarı olardı (rədd sayılmır → hədd heç vaxt dolmur).
        """
        tenant = self._require_matching_tenant(tenant_id)
        row = self._fetch_one(
            """
            INSERT INTO store_face_throttle (tenant_id, machine_key, store_id, failed_count)
            VALUES (%s, %s, %s, 1)
            ON CONFLICT (tenant_id, machine_key) DO UPDATE SET
                failed_count = store_face_throttle.failed_count + 1,
                store_id     = EXCLUDED.store_id
            RETURNING tenant_id, machine_key, store_id, failed_count, window_started_at,
                      locked_until, updated_at
            """,
            (tenant, machine_key.digest, store_id),
        )
        if row is None:  # pragma: no cover - INSERT/UPSERT RETURNING həmişə sətir verir
            raise RuntimeError(
                "store_face_throttle UPSERT sətir qaytarmadı — DB invariantı pozulub"
            )
        return _hydrate(row)


__all__ = ["PostgresFaceThrottleRepository"]
