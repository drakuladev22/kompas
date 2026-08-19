"""`store_pin_throttle` — terminal-səviyyəli PIN throttle-un davamlı saxlanması
(SEC-01/SEC-05, dövrə 3 audit).

──────────────────────────────────────────────────────────────────────────────
VAXT/SAYĞAC HESABLAMASI BURADA YOX, DB TRIGGER-İNDƏDİR (TIME-1)
──────────────────────────────────────────────────────────────────────────────
`enforce_store_pin_throttle_lockout()` (`migrations/075`) `failed_count`/
`window_started_at`/`locked_until`-i `system_limits`-dən oxuyaraq ÖZÜ
hesablayır — bu fayl YALNIZ SİQNAL göndərir (`record_failure()`: "bir
uğursuz cəhd oldu", `update_last_seen_store()`: "YALNIZ mağaza dəyişdi").
Göndərilən `failed_count`/vaxt dəyərləri trigger tərəfindən İGNORED olunur;
`RETURNING` ilə geri gələn dəyərlər isə trigger-in HESABLADIĞI HƏQİQİ
nəticədir.

──────────────────────────────────────────────────────────────────────────────
`record_failure()` VƏ `update_last_seen_store()` NİYƏ AYRI METODDUR
──────────────────────────────────────────────────────────────────────────────
Trigger bu ikisini `NEW.failed_count = OLD.failed_count` bərabərliyi ilə
FƏRQLƏNDİRİR (bax miqrasiyanın "BUDAQLANMA SİQNALI" şərhi) — ona görə HƏR
metodun SQL-i DƏQİQ hansı sütunları `SET`-də TOXUNDUĞU ilə niyyətini bildirir:
`record_failure()` `failed_count`-u AÇIQ ARTIRIR (trigger-ə "bu, uğursuz
cəhddir" deyir), `update_last_seen_store()` isə ONA HEÇ TOXUNMUR (trigger-ə
"bu, YALNIZ store_id yeniləməsidir, sayğaca TOXUNMA" deyir).

──────────────────────────────────────────────────────────────────────────────
`self._tenant` NAXIŞI — YENİ BEŞLİYƏ UYĞUN (bax `repositories.py::_BaseRepository.
_require_matching_tenant` şərhi)
──────────────────────────────────────────────────────────────────────────────
Bu, TAMAMİLƏ YENİ fayldır — INF2-02-nin "köhnə 154" siyahısına HEÇ VAXT
qoşulmadı: hər üç metod `_require_matching_tenant()` çağırıb NƏTİCƏDƏ
`self._tenant`-i işlədir, arqumentin ÖZÜNÜ YOX.
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
    FROM store_pin_throttle
"""


class PostgresPinThrottleRepository(_BaseRepository):
    """`PinThrottleRepository` Protocol-una STRUCTURAL uyğun (miras YOX, CLAUDE.md §3)."""

    def get_for_update(
        self, tenant_id: TenantId, machine_key: MachineIdentityHash
    ) -> TerminalPinThrottle | None:
        """`SELECT ... FOR UPDATE` — sətir yoxdursa `None` (bu maşında HƏLƏ
        heç bir uğursuz PIN cəhdi qeydə alınmayıb, sayğac fərz olunan sıfırdır).
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
        """Atomik artırma — `failed_count`-u AÇIQ toxunur (bax fayl başlığı,
        "BUDAQLANMA SİQNALI"). `store_id` HƏR çağırışda YENİLƏNİR (son
        görülən mağaza — klon aşkarlamasının mənbəyi)."""
        tenant = self._require_matching_tenant(tenant_id)
        row = self._fetch_one(
            """
            INSERT INTO store_pin_throttle (tenant_id, machine_key, store_id, failed_count)
            VALUES (%s, %s, %s, 1)
            ON CONFLICT (tenant_id, machine_key) DO UPDATE SET
                failed_count = store_pin_throttle.failed_count + 1,
                store_id     = EXCLUDED.store_id
            RETURNING tenant_id, machine_key, store_id, failed_count, window_started_at,
                      locked_until, updated_at
            """,
            (tenant, machine_key.digest, store_id),
        )
        if row is None:  # pragma: no cover - INSERT/UPSERT RETURNING həmişə sətir verir
            raise RuntimeError("store_pin_throttle UPSERT sətir qaytarmadı — DB invariantı pozulub")
        return _hydrate(row)

    def update_last_seen_store(
        self, tenant_id: TenantId, machine_key: MachineIdentityHash, *, store_id: StoreId
    ) -> None:
        """`failed_count`-a TOXUNMUR (bax fayl başlığı) — sətir ARTIQ mövcud
        olmalıdır, bu metod yalnız `get_for_update` DOLU sətir qaytarandan
        sonra çağırılır."""
        tenant = self._require_matching_tenant(tenant_id)
        self._execute(
            "UPDATE store_pin_throttle SET store_id = %s WHERE tenant_id = %s AND machine_key = %s",
            (store_id, tenant, machine_key.digest),
        )


def _hydrate(row: dict[str, Any]) -> TerminalPinThrottle:
    # `window_started_at` OXUNUR VƏ ÖTÜRÜLÜR, amma İSTEHSALAT qərarında
    # HEÇ VAXT YENİDƏN HESABLANMIR (`TerminalPinThrottle.advance_after_
    # failure()` — pəncərə sərhədini TƏKRARLAYAN metod — burada ÇAĞIRILMIR,
    # o, `InMemoryPinThrottle` sınaq sahtəsinin icra etdiyi İCRA OLUNAN
    # SPESİFİKASİYADIR). Real pəncərə sərhədini YALNIZ DB trigger-i
    # (`enforce_store_pin_throttle_lockout()`, TIME-1) bilir — dəyəri
    # Python-da TƏKRAR hesablasaydıq, İKİ MÜSTƏQİL mənbə (SQL VƏ Python)
    # eyni qaydanı fərqli tətbiq edə bilərdi. Sahə YALNIZ oxunub domen
    # obyektinə köçürülür ki, dataclass-ın konstruktoru tamamlansın.
    #
    # QƏSDƏN İKİQAT QAYDA (CLAUDE.md §5): eyni sərhəd (`now < locked_until`,
    # SƏRT) HƏM burada (SQL trigger, `migrations/075` sətir ~312-323), HƏM
    # `TerminalPinThrottle.advance_after_failure()`-də (Python, sınaq
    # spesifikasiyası) TƏKRARLANIR. BİRİNİ dəyişən DİGƏRİNİ DƏ dəyişməlidir
    # — əks halda SQL və Python fərqli anda fərqli qərar verər.
    return TerminalPinThrottle(
        tenant_id=TenantId(row["tenant_id"]),
        machine_key=MachineIdentityHash(row["machine_key"]),
        store_id=StoreId(row["store_id"]),
        failed_count=row["failed_count"],
        window_started_at=row["window_started_at"],
        locked_until=row["locked_until"],
        updated_at=row["updated_at"],
    )


__all__ = ["PostgresPinThrottleRepository"]
