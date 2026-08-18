"""Sessiyanın şəbəkə gediş-gəliş sayı — PERF-1.

──────────────────────────────────────────────────────────────────────────────
NİYƏ SAYĞAC TESTİ, «SÜRƏT» TESTİ YOX
──────────────────────────────────────────────────────────────────────────────
Yavaşlığın səbəbi alqoritm deyil, GEDİŞ-GƏLİŞ SAYIDIR. Bu quraşdırmada
Supabase pooler-inə bir gediş-gəliş ~206 ms çəkir (ölçülüb), yəni sessiyaya
əlavə olunan hər artıq sorğu istifadəçinin gözlədiyi vaxta birbaşa 0.2 saniyə
yazır. Tapılan üç artıq sorğu belə idi:

    1. AÇIQ `BEGIN` — psycopg `autocommit=False` ilə tranzaksiyanı ONSUZ DA
       açır; bizim `BEGIN` onun içində icra olunub «there is already a
       transaction in progress» xəbərdarlığı qaytarırdı (canlı bazada
       təsdiqlənib);
    2. HƏR GUC üçün AYRI `set_config()` — `tenant_id` + `user_id` = iki sorğu;
    3. `commit()` sonrası YENİDƏN `BEGIN` — `COMMIT AND CHAIN` bunu bir
       gediş-gəlişdə edir.

Vaxt ölçən test yazmaq olmazdı: nəticə şəbəkədən asılı olar və CI-da
səbəbsiz sınardı. Ona görə ölçülən şey SORĞU MƏTNLƏRİDİR — səbəbin özü.
Sayğac artarsa, düzəliş sükutla geri qayıdıb deməkdir.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from src.domain.value_objects.identifiers import EmployeeId, TenantId
from src.infrastructure.persistence.connection import PostgresUnitOfWork, TenantContext

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
ACTOR = EmployeeId(uuid.uuid4())


class _FakeCursor:
    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> _FakeCursor:
        return self

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[Any]:
        return []


class _FakeConnection:
    """Göndərilən HƏR sorğunu qeyd edir — testin yeganə ölçüsü budur."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.params: list[Any] = []
        self.api_calls: list[str] = []

    def execute(self, sql: str, params: Any = None) -> _FakeCursor:
        self.statements.append(" ".join(sql.split()))
        self.params.append(params)
        return _FakeCursor()

    def cursor(self) -> _FakeCursor:
        return _FakeCursor()

    def commit(self) -> None:
        self.api_calls.append("commit")

    def rollback(self) -> None:
        self.api_calls.append("rollback")


class _FakePool:
    def __init__(self, conn: _FakeConnection) -> None:
        self._conn = conn
        self.returned = 0

    def getconn(self) -> _FakeConnection:
        return self._conn

    def putconn(self, conn: object) -> None:
        self.returned += 1


def _uow(*, with_actor: bool) -> tuple[PostgresUnitOfWork, _FakeConnection, _FakePool]:
    conn = _FakeConnection()
    pool = _FakePool(conn)
    context = TenantContext(tenant_id=TENANT, user_id=ACTOR if with_actor else None)
    return PostgresUnitOfWork(pool, context), conn, pool  # type: ignore[arg-type]


def test_opening_a_session_sends_exactly_one_statement() -> None:
    """Kontekst BİR sorğudur — açıq `BEGIN` yoxdur, `set_config` birləşib."""
    uow, conn, _ = _uow(with_actor=True)

    with uow:
        pass

    assert len(conn.statements) == 1, conn.statements
    assert conn.statements[0].count("set_config") == 2
    assert not any(statement.startswith("BEGIN") for statement in conn.statements)


def test_the_context_values_stay_parameterised() -> None:
    """Sətir birləşdirmə YALNIZ sabit fraqmentdədir — dəyər parametrdir.

    Dəyər SQL mətninə düşsəydi, bölmə 2-nin «100% Parameterized SQL» qaydası
    pozulardı; sayğac düzəlişi bu qaydanı gizlicə sındıra bilərdi.
    """
    uow, conn, _ = _uow(with_actor=True)

    with uow:
        pass

    assert str(TENANT) not in conn.statements[0]
    assert conn.params[0] == ("app.tenant_id", str(TENANT), "app.user_id", str(ACTOR))


def test_a_session_without_an_actor_sets_only_the_tenant() -> None:
    """Giriş etməmiş axın (sihirbaz, giriş ekranı) `user_id` GÖNDƏRMİR."""
    uow, conn, _ = _uow(with_actor=False)

    with uow:
        pass

    assert conn.statements[0].count("set_config") == 1
    assert conn.params[0] == ("app.tenant_id", str(TENANT))


def test_commit_chains_the_next_transaction_in_the_same_round_trip() -> None:
    """`COMMIT AND CHAIN` + kontekst = İKİ sorğu (əvvəl ÜÇ idi)."""
    uow, conn, _ = _uow(with_actor=True)

    with uow:
        conn.statements.clear()
        uow.commit()
        after_commit = list(conn.statements)

    assert after_commit == [
        "COMMIT AND CHAIN",
        "SELECT set_config(%s, %s, true), set_config(%s, %s, true)",
    ]


def test_rollback_chains_as_well() -> None:
    uow, conn, _ = _uow(with_actor=True)

    with uow:
        conn.statements.clear()
        uow.rollback()

    assert conn.statements[0] == "ROLLBACK AND CHAIN"


def test_leaving_the_session_uses_the_driver_api_not_raw_sql() -> None:
    """`conn.rollback()` açıq tranzaksiya yoxdursa HEÇ NƏ göndərmir.

    Xam `execute("ROLLBACK")` isə hər halda bir gediş-gəliş idi — məhz
    `commit()`-dən dərhal sonra çıxılan sessiyalarda boşa gedən biri.
    """
    uow, conn, pool = _uow(with_actor=True)

    with uow:
        pass

    assert conn.api_calls == ["rollback"]
    assert not any("ROLLBACK" in statement for statement in conn.statements)
    assert pool.returned == 1


def test_an_explicit_commit_releases_with_a_commit() -> None:
    uow, conn, _ = _uow(with_actor=True)

    with uow:
        uow.commit()

    assert conn.api_calls == ["commit"]
