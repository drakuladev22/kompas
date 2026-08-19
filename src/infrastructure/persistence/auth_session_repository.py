"""`auth_sessions` — sessiya müddətinin DAVAMLI saxlanması (SEC-5, SEC-011).

──────────────────────────────────────────────────────────────────────────────
NİYƏ TAPILDI: SƏNƏD "QORUNUB" DEYİRDİ, KOD HEÇ NƏ YAZMIRDI
──────────────────────────────────────────────────────────────────────────────
`docs/security_decisions.md` SEC-011 "Tətbiq: schema.sql §17b" yazırdı, lakin
`auth_sessions` cədvəlinə heç bir yol yazmır/oxumurdu — `profile.py`-dakı
sessiya siyahısı isə ORADAN oxuyurdu, yəni istifadəçiyə HƏMİŞƏ boş siyahı
göstərilirdi. Bu fayl `AuthSessionRepository` (`domain/interfaces/ports.py`)
portunu Postgres üzərində implementasiya edərək boşluğu bağlayır.

──────────────────────────────────────────────────────────────────────────────
`save()` — `id` İLƏ UPSERT, `token_hash` TOQQUŞMASI SÜKUTLA UDULMUR
──────────────────────────────────────────────────────────────────────────────
`ON CONFLICT (id) DO UPDATE` YALNIZ DƏYİŞƏ BİLƏN sütunlara toxunur
(`expires_at`, `last_seen_at`, `revoked_at`, `revoked_by`, `revocation_reason`)
— `AuthSession.touch()`/`revoke()`-nin toxunduğu SAHƏLƏRLƏ HƏRFƏN eynidir.
`tenant_id`/`user_id`/`token_hash`/`context`/`issued_at`/`absolute_expiry`
entity-nin `__post_init__`-dən sonra heç bir metodla dəyişmir — onları da
`EXCLUDED`-ə açsaydıq, gələcək bir çağırış xətası (məs. mutasiya edilmiş
obyektin səhvən fərqli `token_hash`-lə save edilməsi) SÜKUTLA qəbul edilərdi.

`token_hash UNIQUE` toqquşması İSƏ `id`-dən TAMAMİLƏ AYRI, İKİNCİ bir
məhdudiyyətdir və `ON CONFLICT` bura QƏSDƏN İŞARƏLƏNMİR:
`secrets.token_urlsafe(32)` HƏR `issue()` çağırışında YENİDƏN yaradılır —
bu, `Fine`-in `occurred_on`-una bənzər "eyni klikin təkrarı" ssenarisi DEYİL
(müq. D7). Toqquşma ya statistik-sıfır ehtimallı kriptoqrafik hadisədir, ya
da anomaliya/bug əlamətidir — hər iki halda SÜKUTLA UTMAQ (`DO NOTHING`)
YENİ sessiyanı "yaradıldı" kimi qaytarıb DB-də isə BAŞQA (bəlkə başqa
istifadəçinin) sətrini saxlayardı — autentifikasiyada ən pis mümkün nəticə.
Ona görə `psycopg.errors.UniqueViolation` BURADA TUTULMUR, YUXARI ötürülür;
`SessionManagementUseCase.issue()` bunu açıq uğursuzluq kimi görür.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.domain.entities.auth_session import AuthSession, SessionContext
from src.infrastructure.persistence.repositories import _BaseRepository

if TYPE_CHECKING:
    from src.domain.value_objects.identifiers import EmployeeId, SessionId, TenantId


class PostgresAuthSessionRepository(_BaseRepository):
    """`AuthSessionRepository` Protocol-una STRUCTURAL uyğun (miras YOX)."""

    _SELECT = """
        SELECT id, tenant_id, user_id, token_hash, context, issued_at,
               expires_at, last_seen_at, absolute_expiry, revoked_at,
               revoked_by, revocation_reason, machine_name, ip_address
        FROM auth_sessions
    """

    def save(self, session: AuthSession) -> None:
        self._execute(
            """
            INSERT INTO auth_sessions
                (id, tenant_id, user_id, token_hash, context, issued_at,
                 expires_at, last_seen_at, absolute_expiry, revoked_at,
                 revoked_by, revocation_reason, machine_name, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                expires_at        = EXCLUDED.expires_at,
                last_seen_at      = EXCLUDED.last_seen_at,
                revoked_at        = EXCLUDED.revoked_at,
                revoked_by        = EXCLUDED.revoked_by,
                revocation_reason = EXCLUDED.revocation_reason
            """,
            (
                session.id,
                # `self._tenant` DEYİL, `session.tenant_id` YAZILIR: bu, YENİ
                # sətrin AÇARIDIR (INSERT dəyəri), `WHERE` şərti deyil. Yenə də
                # RLS `WITH CHECK (tenant_id = current_tenant_id())` bu dəyərin
                # bağlantının ÖZ kirayəçisi ilə UYĞUN olmasını MƏCBUR EDİR —
                # uyğun deyilsə INSERT DB səviyyəsində RƏDD EDİLİR (ikinci qat).
                session.tenant_id,
                session.user_id,
                session.token_hash,
                session.context.value,
                session.issued_at,
                session.expires_at,
                session.last_seen_at,
                session.absolute_expiry,
                session.revoked_at,
                session.revoked_by,
                session.revocation_reason,
                session.machine_name,
                session.ip_address,
            ),
        )

    def get(self, session_id: SessionId) -> AuthSession | None:
        # Protokolda `tenant_id` arqumenti YOXDUR — `self._tenant` YEGANƏ
        # mənbədir (INFRA-2 naxışı), RLS-ə əlavə ikinci qat.
        row = self._fetch_one(
            f"{self._SELECT} WHERE id = %s AND tenant_id = %s",
            (session_id, self._tenant),
        )
        return _hydrate(row) if row else None

    def get_by_token_hash(self, tenant_id: TenantId, token_hash: str) -> AuthSession | None:
        """`tenant_id` arqumenti sorğuda İŞLƏNMİR — bax fayl başlığı və
        `telegram_repositories.py`-dakı eyni qərar: `self._tenant` bağlantının
        ÖZ kontekstindən gəlir və çağırandan asılı olmayan YEGANƏ mənbədir."""
        del tenant_id
        row = self._fetch_one(
            f"{self._SELECT} WHERE tenant_id = %s AND token_hash = %s",
            (self._tenant, token_hash),
        )
        return _hydrate(row) if row else None

    def list_recent_for_user(
        self, tenant_id: TenantId, user_id: EmployeeId, *, limit: int = 10
    ) -> list[AuthSession]:
        """`tenant_id` arqumenti sorğuda İŞLƏNMİR — bax `get_by_token_hash`."""
        del tenant_id
        rows = self._fetch_all(
            f"{self._SELECT} WHERE tenant_id = %s AND user_id = %s "
            "ORDER BY issued_at DESC LIMIT %s",
            (self._tenant, user_id, limit),
        )
        return [_hydrate(row) for row in rows]


def _hydrate(row: dict[str, Any]) -> AuthSession:
    return AuthSession(
        id=row["id"],
        tenant_id=row["tenant_id"],
        user_id=row["user_id"],
        token_hash=row["token_hash"],
        context=SessionContext(row["context"]),
        issued_at=row["issued_at"],
        expires_at=row["expires_at"],
        last_seen_at=row["last_seen_at"],
        absolute_expiry=row["absolute_expiry"],
        revoked_at=row["revoked_at"],
        revoked_by=row["revoked_by"],
        revocation_reason=row["revocation_reason"],
        machine_name=row["machine_name"],
        ip_address=row["ip_address"],
    )


__all__ = ["PostgresAuthSessionRepository"]
