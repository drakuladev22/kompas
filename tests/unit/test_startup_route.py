"""Splash-dan sonrakı marşrut — boş baza SİHİRBAZA, sxemsiz baza XƏTAYA.

Qüsurun forması: «tenant yoxdur» halı «nasazlıq» kimi işlənirdi və istifadəçi
dalan ekranı görürdü. Sihirbazın kodu isə mövcud idi — sadəcə ora aparan yol
yox idi. Bu fayl həmin yolun ÜÇ budağını da kilidləyir.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any

import pytest

from src.domain.value_objects.identifiers import TenantId
from src.presentation.app import StartupRoute

pytestmark = pytest.mark.unit


class _Setup:
    def __init__(self, *, required: bool = False, error: Exception | None = None) -> None:
        self._required = required
        self._error = error

    def is_required(self, tenant_id: TenantId) -> bool:
        if self._error is not None:
            raise self._error
        return self._required


class _Session:
    def __init__(self, setup: _Setup) -> None:
        self.setup = setup


class _Context:
    def __init__(self, setup: _Setup) -> None:
        self._setup = setup
        self.tenant_id = TenantId(uuid.uuid4())

    @contextmanager
    def session(self, **_: Any) -> Any:
        yield _Session(self._setup)

    def license_blocked(self) -> bool:
        return False


class _UndefinedTableError(Exception):
    """psycopg xətasının forması — SQLSTATE daşıyır, mətn yox."""

    sqlstate = "42P01"


def _route(setup: _Setup | None) -> StartupRoute:
    """`KompasApplication._startup_route`-u Qt qurmadan çağırır.

    Metod YALNIZ `self._context`-ə toxunur; tam tətbiq obyektini (pəncərə,
    tema, plaginlər) qurmaq testi platformadan asılı edərdi.
    """
    from src.presentation.app import KompasApplication

    holder = object.__new__(KompasApplication)
    holder._context = _Context(setup) if setup is not None else None  # type: ignore[attr-defined]
    return KompasApplication._startup_route(holder)  # type: ignore[arg-type]


def test_empty_database_opens_the_wizard() -> None:
    """Admin sayı sıfırdırsa SİHİRBAZ açılır — bu, xəta deyil."""
    assert _route(_Setup(required=True)) is StartupRoute.SETUP_WIZARD


def test_configured_database_opens_the_login() -> None:
    assert _route(_Setup(required=False)) is StartupRoute.LOGIN


def test_missing_schema_is_reported_as_a_fatal_error() -> None:
    """Cədvəllər ümumiyyətlə yoxdursa GİRİŞ ekranı GÖSTƏRİLMİR.

    Əvvəl bu hal ümumi `except`-ə düşürdü və istifadəçi «istifadəçi adı və ya
    şifrə yanlışdır» mesajı ilə qalırdı — halbuki səbəb şifrə deyil,
    tətbiq olunmamış sxem idi.
    """
    assert _route(_Setup(error=_UndefinedTableError())) is StartupRoute.SCHEMA_MISSING


def test_unknown_failure_falls_back_to_the_login() -> None:
    """Naməlum xətada sihirbaz AÇILMIR — mövcud quraşdırma "boş" görünərdi."""
    assert _route(_Setup(error=RuntimeError("bağlantı qopdu"))) is StartupRoute.LOGIN


def test_preview_mode_has_no_context() -> None:
    """Kontekstsiz (maket) rejimdə giriş ekranı açılır — sorğu edilmir."""
    assert _route(None) is StartupRoute.LOGIN
