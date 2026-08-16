"""Üç 1C konnektorunun ORTAQ bazası və çevirmə köməkçiləri (1c.md).

`SalesDataConnector` portu (`domain/interfaces/ports.py`) üç metod tanıyır:
`test_connection`, `fetch_sales`, `close`. Bu modul həmin portun İNFRASTRUKTUR
tərəfindəki ortaq skeletini saxlayır.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ABSTRAKT BAZA, HALBUKİ PORT `Protocol`-DUR
──────────────────────────────────────────────────────────────────────────────
Domen portu qəsdən `Protocol`-dur: implementasiya ondan MİRAS ALMIR, yəni
infrastruktur domenə struktur asılılığı yaratmır. Lakin üç konnektorun
arasında REAL təkrar var və o, protokol imzasında deyil, DAVRANIŞDADIR:

    * uğursuz testin `ConnectionTestResult`-a çevrilməsi (`_failed_test`),
    * ölçülən müddətin millisaniyəyə çevrilməsi,
    * kursorun sərhəd sənədlərinin süzülməsi,
    * `with` blokunda avtomatik bağlanma.

Bu davranışları üç dəfə yazsaydıq, biri düzəldiləndə digəri arxada qalardı —
məsələn, HTTP konnektorunda düzəldilmiş "sərhəd saniyəsi" qaydası fayl
konnektorunda köhnə formada işləyər və eyni satış iki dəfə xal qazandırardı.
Ona görə ORTAQ hissə mirasla, TİPƏ XAS hissə isə `@abstractmethod` ilə
verilir. Miras domenə deyil, bu modula bağlıdır — qat sırası pozulmur.

──────────────────────────────────────────────────────────────────────────────
NƏ BURADA DEYİL
──────────────────────────────────────────────────────────────────────────────
Sorğu qurma, autentifikasiya və xəta təsnifatı hər tipdə TAMAMİLƏ fərqlidir
(HTTP status kodu, COM `HRESULT`, fayl sistemi `OSError`). Onları ümumi
"handle_error" metodunda birləşdirmək hər tipin KONKRET səbəb mətnini
(1c.md UX tələbi 3: "generic «xəta baş verdi» YAZMA") itirərdi.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from src.domain.value_objects.erp import (
    DEFAULT_PAGE_SIZE,
    ConnectionTestResult,
    ConnectorType,
    ErpProtocolError,
    OneCSaleRecord,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from src.domain.value_objects.erp import SyncCursor


class OneCConnectorBase(ABC):
    """Bir 1C mənbəyinin nazik örtüyü — tipdən asılı olmayan hissə."""

    #: Alt sinif öz tipini elan edir. Fabrik seçimi bu dəyərlə YOXLANILA bilir
    #: və sağlamlıq/diaqnostika mətnləri onu göstərir.
    connector_type: ConnectorType

    # ------------------------------ port imzası ------------------------------- #

    @abstractmethod
    def test_connection(self) -> ConnectionTestResult:
        """Bağlantını yoxlayır və KONKRET texniki səbəb qaytarır.

        Uğursuzluqda `message` texniki-olmayan, lakin GÖSTƏRİCİ olmalıdır:
        "Server cavab vermir (timeout)" / "İstifadəçi adı və ya şifrə səhvdir"
        / "Qovluq tapılmadı" — "xəta baş verdi" QADAĞANDIR (1c.md tələb 3).
        """

    @abstractmethod
    def fetch_sales(
        self, cursor: SyncCursor, *, page_size: int = DEFAULT_PAGE_SIZE
    ) -> list[OneCSaleRecord]:
        """Kursordan sonrakı KEÇİRİLMİŞ satış sənədlərini gətirir."""

    def close(self) -> None:  # noqa: B027 — abstrakt DEYİL, bax docstring
        """Resursları buraxır.

        Bazada BOŞDUR, çünki üç tipdən yalnız ikisinin buraxılası resursu var
        (HTTP klienti, COM obyekti). Fayl konnektoru hər oxuda faylı açıb
        bağlayır — onu "bağlamaq" üçün heç nə qalmır. Metodu abstrakt etsəydik,
        fayl konnektorunda boş gövdə yazmalı olardıq və oxuyan adam "burada nə
        unudulub?" sualını verərdi.
        """

    # ------------------------------ kontekst ---------------------------------- #

    def __enter__(self) -> OneCConnectorBase:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------ köməkçilər -------------------------------- #

    @staticmethod
    def _failed_test(exc: Exception, started: float) -> ConnectionTestResult:
        """İstisnanı sihirbazın anladığı nəticəyə çevirir.

        `user_message` domen istisnalarında ARTIQ Azərbaycancadır; `detail`
        isə texniki mətndir və yalnız `app.log`-a gedir (ekranda göstərmək
        host/istifadəçi adı sızdıra bilər).
        """
        user_message = getattr(exc, "user_message", "1C mənbəyi ilə əlaqə qurulmadı.")
        return ConnectionTestResult(
            ok=False,
            message=user_message,
            detail=str(exc),
            elapsed_ms=elapsed_ms(started),
        )

    @staticmethod
    def _new_records(records: Iterable[OneCSaleRecord], cursor: SyncCursor) -> list[OneCSaleRecord]:
        """Sərhəd saniyəsində ARTIQ emal olunmuş sənədləri süzür.

        Qayda bir dəfə yazılır və üç konnektorda eynidir: kursor `>=` ilə
        irəlilədiyi üçün sərhəd sənədləri hər dövrdə təkrar gəlir (bax
        `SyncCursor` docstring-i).
        """
        return [record for record in records if not cursor.already_seen(record)]


def elapsed_ms(started: float) -> int:
    """`time.monotonic()` başlanğıcından keçən müddət (millisaniyə)."""
    return int((time.monotonic() - started) * 1000)


def to_decimal(raw: Any, document_id: str) -> Decimal:
    """Satış məbləğini oxuyur.

    ONDALIQ VERGÜL QƏSDƏN QƏBUL EDİLİR: 1C-nin CSV ixracı regional
    parametrlərə görə "1 234,56" formatında yaza bilər. Onu rədd etsəydik,
    tam düzgün ixrac faylı "məbləğ rəqəm deyil" xətası ilə dayanardı. Ayırıcı
    çevrilməsi belədir:

        "1 234,56"  → 1234.56   (boşluq = minlik ayırıcı, vergül = onluq)
        "1,234.56"  → 1234.56   (hər ikisi varsa vergül minlikdir)
        "1234,56"   → 1234.56
    """
    if raw is None:
        return Decimal("0")
    if isinstance(raw, Decimal):
        return raw
    # Birinci `replace` BÖLÜNMƏYƏN boşluğu (U+00A0) atır: Excel və 1C ixracı
    # minlik ayırıcısı kimi məhz onu yazır və adi boşluq süzgəci onu tutmur.
    text = str(raw).strip().replace(" ", "").replace(" ", "")
    if "," in text:
        text = text.replace(",", "") if "." in text else text.replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ErpProtocolError(
            "Satış məbləği rəqəm deyil",
            context={"document_id": document_id, "value": str(raw)[:50]},
        ) from exc


def to_datetime(raw: Any, document_id: str, *, formats: Sequence[str] = ()) -> datetime:
    """1C sənəd vaxtını oxuyur.

    1C tarixləri qurşaq məlumatı OLMADAN qaytarır (server saatı). Layihədə
    naive `datetime` qadağandır (ruff DTZ) və müqayisə üçün də təhlükəlidir,
    ona görə dəyər UTC etiketi ilə daşınır. Bu, "vaxt UTC-dir" demək DEYİL —
    müqayisə həmişə EYNİ serverin öz dəyərləri arasında aparılır, ona görə
    etiketin özü nəticəyə təsir etmir.

    `formats` YALNIZ fayl mübadiləsi üçündür: CSV ixracında tarix
    "14.08.2026 19:30" kimi yerli formatda ola bilər və ISO parseri onu
    oxumur. Şablon sihirbazdan gəlir, koda bərk-yazılmır.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise ErpProtocolError("1C sənədində tarix yoxdur", context={"document_id": document_id})
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)

    text = str(raw).strip()
    for pattern in formats:
        try:
            parsed = datetime.strptime(text, pattern)  # noqa: DTZ007 — etiket aşağıda qoyulur
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErpProtocolError(
            "1C sənədinin tarixi oxunmadı",
            context={"document_id": document_id, "value": text[:50], "formats": list(formats)},
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def optional_text(row: dict[str, Any], field_name: str | None) -> str | None:
    """İSTƏYƏ BAĞLI sahəni oxuyur — boş dəyər `None` olur, boş sətir yox."""
    if not field_name:
        return None
    value = row.get(field_name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "OneCConnectorBase",
    "elapsed_ms",
    "optional_text",
    "to_datetime",
    "to_decimal",
]
