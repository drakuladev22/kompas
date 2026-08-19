"""Açılış oxularının BİR tranzaksiyada birləşməsi — PERF-3.

──────────────────────────────────────────────────────────────────────────────
QÜSUR NƏ İDİ
──────────────────────────────────────────────────────────────────────────────
Panel açılışı (`show_admin`) bir sıra kiçik oxu edir: saxlanmış tema, aktiv
modullar, plugin siyahısı, planlayıcı intervalı, cərimə növləri, işçi adları,
bildiriş sayğacı, dəstək nişanları, kontekst altyazıları. Hər biri ÖZ
tranzaksiyasını açırdı — ölçüldü: **13 tranzaksiya**, `show_admin` 18 saniyə.

Sessiyanın öz yükü (implicit BEGIN + kontekst + bağlanış) ~0.63 saniyədir,
yəni vaxtın böyük hissəsi sorğu DEYİL, tranzaksiya açıb-bağlamaq idi.

`ApplicationContext.read_batch()` sərhəd qoyur: onun içindəki `session()`
çağırışları MÖVCUD tranzaksiyanı təkrar işlədir.

Bu fayl üç şeyi kilidləyir — birləşmə FAKTİKİ baş verir, aktor qaydası
pozulmur, və toplu SAPA GÖRƏ ayrıdır (fon sapı əsas sapın bağlantısını
oğurlamamalıdır — psycopg bağlantısı sap-təhlükəsiz DEYİL).
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

import pytest

from src.domain.value_objects.identifiers import EmployeeId, TenantId

pytestmark = pytest.mark.unit

TENANT = TenantId(uuid.uuid4())
ACTOR = EmployeeId(uuid.uuid4())
OTHER = EmployeeId(uuid.uuid4())


class _FakeUow:
    def __init__(self, opened: list[EmployeeId | None], user_id: EmployeeId | None) -> None:
        self.user_id = user_id
        self._opened = opened

    def __enter__(self) -> _FakeUow:
        self._opened.append(self.user_id)
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeDatabase:
    """Yalnız açılan iş vahidlərini sayır — ölçdüyümüz şey elə budur."""

    def __init__(self, *, fail_first: bool = False) -> None:
        self.opened: list[EmployeeId | None] = []
        self._fail_first = fail_first

    def unit_of_work(self, tenant_id: TenantId, *, user_id: EmployeeId | None = None) -> _FakeUow:
        if self._fail_first:
            self._fail_first = False
            raise RuntimeError("hovuz tükənib")
        return _FakeUow(self.opened, user_id)


def _context(*, fail_first: bool = False) -> tuple[Any, _FakeDatabase]:
    """`ApplicationContext`-i KONSTRUKTORSUZ qurur.

    Real konstruktor lisenziya klienti, NTP və onlarla tənbəl sahə tələb edir;
    burada yoxlanan davranış isə YALNIZ sessiya sərhədidir. `__new__` + iki
    sahə ilə test predmetə sadiq qalır və qurma detallarına bağlanmır.
    """
    from src.presentation.composition import ApplicationContext

    database = _FakeDatabase(fail_first=fail_first)
    context = ApplicationContext.__new__(ApplicationContext)
    context._database = database
    context._tenant_id = TENANT
    context._read_batch = threading.local()
    context._build_session = lambda uow: uow  # type: ignore[method-assign]
    return context, database


def test_reads_inside_a_batch_share_one_transaction() -> None:
    """QÜSURUN ÖLÇÜSÜ: üç oxu, BİR tranzaksiya."""
    context, database = _context()

    with context.read_batch(user_id=ACTOR):
        with context.session(user_id=ACTOR):
            pass
        with context.session(user_id=ACTOR):
            pass
        with context.session(user_id=ACTOR):
            pass

    assert database.opened == [ACTOR]


def test_an_actorless_read_joins_the_batch() -> None:
    """`user_id` verilməyən oxu da topluya düşür.

    Təhlükəsizdir, çünki `app.user_id` heç bir RLS OXU siyasətində işlənmir —
    onu yalnız `position_permissions` üzərindəki `DELETE` trigger-i oxuyur
    (miqrasiya 046). Düşməsəydi, açılış oxularının yarısı kənarda qalardı.
    """
    context, database = _context()

    with context.read_batch(user_id=ACTOR), context.session():
        pass

    assert database.opened == [ACTOR]


def test_a_different_actor_gets_its_own_transaction() -> None:
    """BAŞQA aktor topluya QOŞULMUR — `app.user_id` səhv şəxsi göstərərdi."""
    context, database = _context()

    with context.read_batch(user_id=ACTOR), context.session(user_id=OTHER):
        pass

    assert database.opened == [ACTOR, OTHER]


def test_outside_the_batch_every_read_opens_its_own_transaction() -> None:
    """Kontrollerlərin əməliyyat-başına-sessiya qaydası DƏYİŞMİR (CLAUDE.md §6)."""
    context, database = _context()

    with context.session(user_id=ACTOR):
        pass
    with context.session(user_id=ACTOR):
        pass

    assert database.opened == [ACTOR, ACTOR]


def test_the_batch_is_released_even_when_the_body_raises() -> None:
    """İstisna halında paylaşılan istinad QALMAMALIDIR.

    Qalsaydı, sonrakı hər oxu ARTIQ BAĞLANMIŞ tranzaksiyaya gedərdi və səbəb
    «bir dəfə işlədi, sonra işləmədi» kimi görünərdi.
    """
    context, database = _context()

    with pytest.raises(RuntimeError), context.read_batch(user_id=ACTOR):
        raise RuntimeError("açılış yarıda qaldı")

    with context.session(user_id=ACTOR):
        pass

    assert database.opened == [ACTOR, ACTOR]


def test_nesting_does_not_open_a_second_batch() -> None:
    """Yuvalanmış `read_batch` sahibi kənardadır — ikinci tranzaksiya YOX."""
    context, database = _context()

    with (
        context.read_batch(user_id=ACTOR),
        context.read_batch(user_id=ACTOR),
        context.session(user_id=ACTOR),
    ):
        pass

    assert database.opened == [ACTOR]


def test_a_background_thread_never_borrows_the_batch() -> None:
    """SAP TƏHLÜKƏSİZLİYİ: fon sapı ÖZ tranzaksiyasını almalıdır.

    `BackgroundTask` bəzi ekranlarda (server sağlamlığı, ERP sınağı) fon
    sapında sorğu edir. Toplu qlobal olsaydı, həmin sap əsas sapın psycopg
    bağlantısına eyni anda yazardı — psycopg bağlantısı sap-təhlükəsiz deyil
    və nəticə sükutlu, təkrarlanması çətin pozulma olardı.
    """
    context, database = _context()
    seen: list[EmployeeId | None] = []

    def worker() -> None:
        with context.session(user_id=ACTOR) as shared:
            seen.append(shared.user_id)

    with context.read_batch(user_id=ACTOR):
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=5)

    assert database.opened == [ACTOR, ACTOR], "fon sapı topluya QOŞULMAMALIDIR"
    assert seen == [ACTOR]


def test_a_failing_read_disables_the_batch_instead_of_poisoning_it() -> None:
    """Bir sınan oxu SONRAKILARI aparmamalıdır.

    PostgreSQL sorğu xətasından sonra tranzaksiyanı ABORTED vəziyyətinə salır:
    həmin tranzaksiyada növbəti hər sorğu «current transaction is aborted» ilə
    dayanır. Toplu olmasaydı bu, yalnız BİR oxuya təsir edərdi — yəni
    birləşdirmə dayanıqlılığı azaldır. Ona görə ilk xətada toplu söndürülür.
    """
    context, database = _context()

    with context.read_batch(user_id=ACTOR):
        with pytest.raises(RuntimeError), context.session(user_id=ACTOR):
            raise RuntimeError("sorğu çökdü")

        # Toplu artıq ETİBARSIZDIR — bu oxu ÖZ sessiyasını almalıdır.
        with context.session(user_id=ACTOR):
            pass

    assert database.opened == [ACTOR, ACTOR]


def test_an_unopenable_batch_falls_back_to_per_read_sessions() -> None:
    """Toplu YALNIZ optimallaşdırmadır — açıla bilməsə giriş DAYANMAMALIDIR.

    Hovuz tükənə və ya bağlantı qırıla bilər. Belə halda panel yavaş, lakin
    İŞLƏK qalmalıdır; istisna buraxılsaydı, istifadəçi girişdən sonra boş
    ekranda qalardı və səbəb heç yerdə görünməzdi.
    """
    context, database = _context(fail_first=True)

    with context.read_batch(user_id=ACTOR):
        with context.session(user_id=ACTOR):
            pass
        with context.session(user_id=ACTOR):
            pass

    assert database.opened == [ACTOR, ACTOR], "toplusuz davam etməli idi"
