"""Fayl-mübadiləsi konnektoru (CSV/XML) — 1c.md.

Bağlantı növlərindən ÜÇÜNCÜSÜ və ən sadəsi: 1C heç bir port açmır, heç bir
komponent paylaşmır — sadəcə gecə ixracını şəbəkə qovluğuna yazır, biz isə
oradan oxuyuruq.

──────────────────────────────────────────────────────────────────────────────
REAL-VAXT DEYİL — VƏ BU, GİZLƏDİLMİR
──────────────────────────────────────────────────────────────────────────────
Gələn məlumat ixracın YAZILDIĞI andakı vəziyyətdir. Ona görə:

    * defolt sinxronizasiya dövrü gündə bir dəfədir
      (`ERP_FILE_EXCHANGE_SYNC_INTERVAL_SECONDS`, migrations/050) — 300
      saniyəlik dövr eyni faylı gün ərzində 288 dəfə oxuyardı;
    * `ConnectorType.is_real_time` `False` qaytarır və ekran istifadəçini
      xəbərdar edir. Bunu gizlətsəydik, "satış 1C-də var, KompasOS-da yoxdur"
      şikayəti nasazlıq kimi araşdırılardı, halbuki bu, seçilmiş rejimin
      normal davranışıdır.

──────────────────────────────────────────────────────────────────────────────
FAYLLAR SİLİNMİR, KÖÇÜRÜLMÜR
──────────────────────────────────────────────────────────────────────────────
"Emal olunmuş faylı `processed/` qovluğuna köçürmək" naxışı nəzərdən keçirildi
və RƏDD EDİLDİ:

    * qovluq MÜŞTƏRİNİNDİR — bizim yazma hüququmuz olmaya bilər və olsa belə,
      onların öz arxiv/audit prosesini pozardıq;
    * köçürmə YARIMÇIQ qala bilər (şəbəkə kəsintisi) və fayl həm oxunmuş, həm
      oxunmamış vəziyyətdə qalardı;
    * təkrar qorunması ONSUZ DA var: kursor + `UNIQUE (server_id,
      one_c_document_id)`. Yəni köçürmə heç bir qazanc vermir, yalnız risk
      əlavə edir.

Əvəzinə fayllar dəyişmə vaxtına görə köhnədən yeniyə oxunur və səhifə YENİ
sənədlərlə dolduqda oxu dayanır (bax `fetch_sales` docstring-i: tavan xam
sətirlə ölçülsəydi irəliləyiş dayanardı). Artıq emal olunmuş fayl yenidən
parse olunur, lakin heç bir sətir təkrar YAZILMIR — kursor və `UNIQUE
(server_id, one_c_document_id)` onu süzür.

──────────────────────────────────────────────────────────────────────────────
SƏNƏD ID-Sİ OLMAYAN İXRAC
──────────────────────────────────────────────────────────────────────────────
Bəzi ixraclarda sənəd identifikatoru sütunu YOXDUR. `OneCSaleRecord` isə ID-siz
qurula bilmir — o, təkrar yükləmənin yeganə qarşısını alan sahədir. Belə halda
ID SİNTEZ EDİLİR: `FX-<sha256(fayl adı + sətir nömrəsi + sətrin məzmunu)>`.

    * Eyni fayl təkrar oxunanda EYNİ ID alınır → sətir dublikat kimi süzülür.
    * Eyni faylda iki tamamilə eyni sətir FƏRQLİ ID alır (sətir nömrəsi hash-a
      daxildir) → real ikinci satış itmir.
    * Fayl adı dəyişsə (məs. gecəlik ixrac `satis_2026-08-14.csv`) ID də
      dəyişir — ona görə eyni məzmunun İKİ fərqli adla yazılması təkrar
      yaradar. Bu, ixracın adlandırma qaydasından asılıdır və sihirbazda
      sənəd-ID sütununu göstərmək TÖVSİYƏ OLUNUR (o zaman sintez ümumiyyətlə
      işə düşmür).
"""

from __future__ import annotations

import csv
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from xml.etree import ElementTree

from src.domain.value_objects.erp import (
    DEFAULT_PAGE_SIZE,
    ConnectionTestResult,
    ConnectorType,
    ErpConfigurationError,
    ErpConnectionError,
    ErpProtocolError,
    OneCSaleRecord,
)
from src.infrastructure.erp.connector_base import (
    OneCConnectorBase,
    elapsed_ms,
    to_datetime,
    to_decimal,
)
from src.shared.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from src.domain.value_objects.erp import SyncCursor
    from src.infrastructure.erp.one_c_connector import OneCServerConfig

_log = get_logger(__name__)

#: Dəstəklənən fayl formatları — `connector_config.file_format`.
FORMAT_CSV: Final[str] = "CSV"
FORMAT_XML: Final[str] = "XML"
SUPPORTED_FORMATS: Final[tuple[str, ...]] = (FORMAT_CSV, FORMAT_XML)

#: Sintez olunmuş sənəd ID-sinin prefiksi — mənbəyi bir baxışda görünsün deyə
#: («FX» = File eXchange). Uzunluq 16 heksadur: 1C bazasında illərlə sənəd
#: olsa belə toqquşma ehtimalı praktiki olaraq sıfırdır, tam 64 simvol isə
#: `sales_transactions.one_c_document_id` sütununu lazımsız şişirdərdi.
SYNTHETIC_ID_PREFIX: Final[str] = "FX-"
SYNTHETIC_ID_LENGTH: Final[int] = 16

#: Defolt CSV parametrləri.
#:
#: `utf-8-sig` — 1C-nin Windows ixracı faylın əvvəlinə BOM yazır; adi `utf-8`
#: oxunuşunda BİRİNCİ sütunun adı «﻿Код» olur və "sütun tapılmadı"
#: xətası verərdi. `utf-8-sig` BOM varsa atır, yoxdursa heç nə etmir — yəni
#: hər iki hal üçün təhlükəsizdir.
DEFAULT_ENCODING: Final[str] = "utf-8-sig"
#: Nöqtəli vergül — 1C-nin rus/Azərbaycan regional ixracının defoltu
#: (onluq ayırıcısı vergül olduğu üçün sahə ayırıcısı vergül OLA BİLMƏZ).
DEFAULT_DELIMITER: Final[str] = ";"
DEFAULT_PATTERN: Final[str] = "*.csv"
DEFAULT_XML_RECORD_TAG: Final[str] = "Документ"


@dataclass(frozen=True)
class FileExchangeSettings:
    """`connector_config` sözlüyünün fayl-mübadiləsi üzü."""

    #: Mübadilə qovluğu — `erp_servers.host` sütunundan gəlir.
    folder: str
    file_format: str = FORMAT_CSV
    file_pattern: str = DEFAULT_PATTERN
    encoding: str = DEFAULT_ENCODING
    delimiter: str = DEFAULT_DELIMITER
    #: XML-də bir sənədi təmsil edən element adı.
    record_tag: str = DEFAULT_XML_RECORD_TAG
    #: Tarix şablonu (`strptime`). Boşdursa yalnız ISO formatı qəbul edilir.
    date_format: str = ""
    #: Gözlənilən sütun adları. `document_id` və `seller_name` İSTƏYƏ BAĞLIDIR.
    document_id_column: str = ""
    date_column: str = "Дата"
    seller_column: str = "Продавец"
    store_column: str = "Склад"
    amount_column: str = "Сумма"
    seller_name_column: str = ""

    @property
    def required_columns(self) -> tuple[str, ...]:
        """Faylda MÜTLƏQ olmalı sütunlar.

        `document_id` burada YOXDUR: yoxdursa ID sintez olunur (bax modul
        başlığı). Qalan dördü olmadan sətrin mənası qalmır — kim, harada, nə
        qədər, nə vaxt satıb.
        """
        return (self.date_column, self.seller_column, self.store_column, self.amount_column)

    @property
    def date_formats(self) -> tuple[str, ...]:
        return (self.date_format,) if self.date_format else ()

    @classmethod
    def from_config(cls, config: OneCServerConfig) -> FileExchangeSettings:
        """Sütunlar + `connector_config` → tam fayl parametrləri.

        Raises:
            ErpConfigurationError: qovluq boşdursa və ya format naməlumdursa.
        """
        extra = config.connector_config
        folder = extra.text("folder") or config.host
        if not folder.strip():
            raise ErpConfigurationError(
                "Fayl mübadiləsi üçün qovluq yolu boşdur",
                user_message=(
                    "Mübadilə qovluğunun yolunu daxil edin (məs. \\\\server\\1c_exchange)."
                ),
            )

        file_format = extra.text("file_format", FORMAT_CSV).upper()
        if file_format not in SUPPORTED_FORMATS:
            raise ErpConfigurationError(
                f"Naməlum fayl formatı: {file_format}",
                user_message=(f"«{file_format}» formatı dəstəklənmir. CSV və ya XML seçin."),
                context={"format": file_format},
            )

        default_pattern = DEFAULT_PATTERN if file_format == FORMAT_CSV else "*.xml"
        return cls(
            folder=folder,
            file_format=file_format,
            file_pattern=extra.text("file_pattern", default_pattern),
            encoding=extra.text("encoding", DEFAULT_ENCODING),
            delimiter=extra.text("delimiter", DEFAULT_DELIMITER),
            record_tag=extra.text("record_tag", DEFAULT_XML_RECORD_TAG),
            date_format=extra.text("date_format"),
            document_id_column=extra.text("document_id_column"),
            date_column=extra.text("date_column", "Дата"),
            seller_column=extra.text("seller_column", "Продавец"),
            store_column=extra.text("store_column", "Склад"),
            amount_column=extra.text("amount_column", "Сумма"),
            seller_name_column=extra.text("seller_name_column"),
        )


class OneCFileExchangeConnector(OneCConnectorBase):
    """Şəbəkə qovluğundakı CSV/XML ixracını oxuyur."""

    connector_type = ConnectorType.FILE_EXCHANGE

    def __init__(self, config: OneCServerConfig) -> None:
        self._config = config

    @property
    def config(self) -> OneCServerConfig:
        return self._config

    # ---------------------------------- test ---------------------------------- #

    def test_connection(self) -> ConnectionTestResult:
        """Qovluq → fayl → sütunlar — üç addım, üç FƏRQLİ səbəb.

        HTTP-də "server cavab vermir" bir cümlə ilə ifadə olunur; burada isə
        üç tamamilə fərqli nasazlıq var və hər biri BAŞQA düzəliş tələb edir:
        şəbəkə diski qoşulmayıb / ixrac işləmir / sütun adları uyğun deyil.
        Onları eyni mesajla göstərmək istifadəçini kor edərdi (1c.md tələb 3).
        """
        started = time.monotonic()
        try:
            settings = FileExchangeSettings.from_config(self._config)
            folder = self._require_folder(settings)
            newest = self._latest_file(folder, settings)
            columns = self._read_columns(newest, settings)
        except (ErpConfigurationError, ErpConnectionError, ErpProtocolError) as exc:
            return self._failed_test(exc, started)

        missing = [name for name in settings.required_columns if name not in columns]
        if missing:
            return ConnectionTestResult(
                ok=False,
                message=(
                    f"«{newest.name}» faylı oxundu, lakin gözlənilən sütun(lar) yoxdur: "
                    f"{', '.join(missing)}. Sütun adlarını ixrac faylı ilə uyğunlaşdırın."
                ),
                detail=f"tapılan sütunlar: {sorted(columns)[:10]}",
                elapsed_ms=elapsed_ms(started),
            )

        return ConnectionTestResult(
            ok=True,
            message=(f"Bağlantı uğurludur — «{newest.name}» faylı oxundu və sütunlar uyğundur."),
            entity_verified=newest.name,
            elapsed_ms=elapsed_ms(started),
        )

    # -------------------------------- satışlar -------------------------------- #

    def fetch_sales(
        self, cursor: SyncCursor, *, page_size: int = DEFAULT_PAGE_SIZE
    ) -> list[OneCSaleRecord]:
        """Qovluqdakı fayllardan kursordan sonrakı satışları gətirir.

        Fayllar DƏYİŞMƏ VAXTINA görə köhnədən yeniyə oxunur və səhifə
        dolduqda dayanılır: ilk sinxronizasiyada qovluqda illik arxiv ola
        bilər və hamısını bir dövrdə oxumaq mağaza PC-sinin yaddaşını yıxardı
        (HTTP konnektorundakı `$top` ilə eyni əsaslandırma).

        ──────────────────────────────────────────────────────────────────
        SƏHİFƏ TAVANI XAM SƏTİRLƏ DEYİL, **YENİ** SƏNƏDLƏ ÖLÇÜLÜR
        ──────────────────────────────────────────────────────────────────
        Kursor süzgəci HƏR FAYLDAN SONRA tətbiq olunur və tavan yalnız YENİ
        sənədləri sayır. Əks halda irəliləyiş DAYANARDI: 500 sətirlik ilk
        fayl artıq emal olunubsa, xam say dərhal tavana çatar, süzgəcdən
        sonra isə partiya BOŞ qalardı — sinxronizasiya "yeni sənəd yoxdur"
        nəticəsi ilə bitər və ikinci fayl HEÇ VAXT oxunmazdı.

        QİYMƏTİ: artıq emal olunmuş fayllar hər dövrdə YENİDƏN parse olunur.
        Alternativ (faylın dəyişmə vaxtını kursorla müqayisə edib atlamaq)
        RƏDD EDİLDİ: `mtime` real vaxtdır, sənəd tarixi isə 1C serverinin
        saatıdır — iki fərqli saatı müqayisə etmək, server saatı irəlidədirsə,
        HƏLƏ OXUNMAMIŞ faylı sükutla atlayardı. Arxivin böyüməsi isə
        müştəri tərəfində həll olunur (köhnə ixracları şablondan kənar
        qovluğa köçürmək) və bu, itki riski daşımır.
        """
        settings = FileExchangeSettings.from_config(self._config)
        folder = self._require_folder(settings)

        collected: list[OneCSaleRecord] = []
        files_read = 0
        parsed = 0
        for path in self._files(folder, settings):
            records_in_file = self._records_from(path, settings)
            parsed += len(records_in_file)
            files_read += 1
            collected.extend(self._fresh(records_in_file, cursor))
            if len(collected) >= page_size:
                break

        # Sıralama BURADA aparılır, faylın öz sırasına güvənmədən: kursor
        # `advanced()` ilə ƏN YENİ sənədə tullanır, yəni sıralanmamış partiya
        # ondan köhnə sənədləri həmişəlik atlamağa səbəb olardı.
        collected.sort(key=lambda record: record.document_at)
        records = collected[:page_size]

        _log.info(
            "ERP_FILE_SALES_FETCHED",
            extra={
                "folder": settings.folder,
                "files_read": files_read,
                "parsed": parsed,
                "new": len(records),
            },
        )
        return records

    def _fresh(self, records: list[OneCSaleRecord], cursor: SyncCursor) -> list[OneCSaleRecord]:
        """Kursordan sonrakı sənədlər.

        İki süzgəc BİRLİKDƏ işləyir və hər ikisi lazımdır: `_new_records`
        sərhəd saniyəsindəki artıq emal olunmuş ID-ləri, aşağıdakı müqayisə
        isə ondan KÖHNƏ sənədləri atır. HTTP konnektorunda ikincisini serverin
        `$filter`-i edir — faylda isə süzgəc bizdədir.
        """
        fresh = self._new_records(records, cursor)
        if cursor.last_document_at is None:
            return fresh
        return [record for record in fresh if record.document_at >= cursor.last_document_at]

    # ------------------------------- fayl qatı -------------------------------- #

    @staticmethod
    def _require_folder(settings: FileExchangeSettings) -> Path:
        """Qovluğun MÖVCUD, oxunabilir və həqiqətən qovluq olduğunu yoxlayır."""
        folder = Path(settings.folder)
        try:
            exists = folder.exists()
        except OSError as exc:
            # Şəbəkə yolu əlçatmaz olduqda `exists()` ÖZÜ istisna ata bilər
            # (Windows: qoşulmamış disk, kimlik doğrulama xətası).
            raise ErpConnectionError(
                f"Mübadilə qovluğuna müraciət edilə bilmədi: {exc}",
                user_message=(
                    f"«{settings.folder}» qovluğuna müraciət mümkün olmadı — şəbəkə "
                    "diskinin qoşulu olduğunu və giriş hüququnu yoxlayın."
                ),
                context={"folder": settings.folder},
            ) from exc

        if not exists:
            raise ErpConnectionError(
                "Mübadilə qovluğu tapılmadı",
                user_message=(
                    f"«{settings.folder}» qovluğu tapılmadı — yolu yoxlayın və ya "
                    "şəbəkə diskini qoşun."
                ),
                context={"folder": settings.folder},
            )
        if not folder.is_dir():
            raise ErpConnectionError(
                "Göstərilən yol qovluq deyil",
                user_message=(
                    f"«{settings.folder}» bir qovluq deyil, fayldır. Qovluğun yolunu "
                    "göstərin (fayl adı olmadan)."
                ),
                context={"folder": settings.folder},
            )
        return folder

    def _files(self, folder: Path, settings: FileExchangeSettings) -> list[Path]:
        """Şablona uyğun fayllar — KÖHNƏDƏN YENİYƏ sıralanmış."""
        try:
            matches = [path for path in folder.glob(settings.file_pattern) if path.is_file()]
            matches.sort(key=lambda path: path.stat().st_mtime)
        except PermissionError as exc:
            raise ErpConnectionError(
                f"Qovluq oxuna bilmədi: {exc}",
                user_message=(
                    f"«{settings.folder}» qovluğunu oxumaq icazəsi yoxdur — "
                    "Windows istifadəçisinə oxu hüququ verin."
                ),
                context={"folder": settings.folder},
            ) from exc
        except OSError as exc:
            raise ErpConnectionError(
                f"Qovluq oxuna bilmədi: {exc}",
                user_message=(
                    f"«{settings.folder}» qovluğu oxuna bilmədi — şəbəkə əlaqəsini yoxlayın."
                ),
                context={"folder": settings.folder},
            ) from exc
        return matches

    def _latest_file(self, folder: Path, settings: FileExchangeSettings) -> Path:
        """Ən YENİ fayl — test üçün. Boş qovluq AYRICA səbəbdir."""
        matches = self._files(folder, settings)
        if not matches:
            raise ErpConnectionError(
                "Qovluqda uyğun fayl yoxdur",
                user_message=(
                    f"Qovluq oxundu, lakin «{settings.file_pattern}» şablonuna uyğun "
                    "fayl tapılmadı — 1C-dəki ixrac tapşırığının işlədiyini yoxlayın."
                ),
                context={"folder": settings.folder, "pattern": settings.file_pattern},
            )
        return matches[-1]

    def _read_columns(self, path: Path, settings: FileExchangeSettings) -> set[str]:
        """Faylın sütun adlarını qaytarır (sətirləri emal etmədən).

        CSV-də BAŞLIQ sətri oxunur, ilk məlumat sətri YOX: gecə ixracı boş bir
        gündən sonra yalnız başlıqla gələ bilər və bu, NORMAL haldır. İlk
        sətirdən oxusaydıq, belə fayl "sütunlar uyğun deyil" xətası verərdi —
        yəni işləyən konfiqurasiya səhv görünərdi.
        """
        if settings.file_format == FORMAT_XML:
            first = next(iter(self._read_xml(path, settings)), None)
            if first is None:
                raise ErpProtocolError(
                    "XML faylında sənəd elementi tapılmadı",
                    user_message=(
                        f"«{path.name}» faylı oxundu, lakin içində «{settings.record_tag}» "
                        "elementi yoxdur — element adını sihirbazda yoxlayın."
                    ),
                    context={"file": path.name, "record_tag": settings.record_tag},
                )
            return set(first)

        try:
            with path.open("r", encoding=settings.encoding, newline="") as handle:
                names = csv.DictReader(handle, delimiter=settings.delimiter).fieldnames
        except UnicodeDecodeError as exc:
            raise ErpProtocolError(
                f"Fayl kodlaşdırması uyğun deyil: {exc}",
                user_message=(
                    f"«{path.name}» faylı «{settings.encoding}» kodlaşdırması ilə "
                    "oxunmadı — sihirbazda kodlaşdırmanı dəyişin (məs. windows-1251)."
                ),
                context={"file": path.name, "encoding": settings.encoding},
            ) from exc
        except OSError as exc:
            raise ErpConnectionError(
                f"Fayl oxuna bilmədi: {exc}",
                user_message=f"«{path.name}» faylı oxuna bilmədi.",
                context={"file": path.name},
            ) from exc
        return {str(name).strip() for name in names or ()}

    def _rows(self, path: Path, settings: FileExchangeSettings) -> Iterator[dict[str, Any]]:
        if settings.file_format == FORMAT_XML:
            return self._read_xml(path, settings)
        return self._read_csv(path, settings)

    def _read_csv(self, path: Path, settings: FileExchangeSettings) -> Iterator[dict[str, Any]]:
        """CSV sətirlərini sözlük kimi oxuyur."""
        try:
            with path.open("r", encoding=settings.encoding, newline="") as handle:
                reader = csv.DictReader(handle, delimiter=settings.delimiter)
                for row in reader:
                    # `DictReader` başlıqsız sütunları `None` açarı altında
                    # toplayır — onlar atılır, əks halda `str(None)` sütun adı
                    # kimi görünərdi.
                    yield {str(key).strip(): value for key, value in row.items() if key is not None}
        except UnicodeDecodeError as exc:
            raise ErpProtocolError(
                f"Fayl kodlaşdırması uyğun deyil: {exc}",
                user_message=(
                    f"«{path.name}» faylı «{settings.encoding}» kodlaşdırması ilə "
                    "oxunmadı — sihirbazda kodlaşdırmanı dəyişin (məs. windows-1251)."
                ),
                context={"file": path.name, "encoding": settings.encoding},
            ) from exc
        except OSError as exc:
            raise ErpConnectionError(
                f"Fayl oxuna bilmədi: {exc}",
                user_message=(
                    f"«{path.name}» faylı oxuna bilmədi — fayl başqa proqram "
                    "tərəfindən istifadə oluna bilər."
                ),
                context={"file": path.name},
            ) from exc

    def _read_xml(self, path: Path, settings: FileExchangeSettings) -> Iterator[dict[str, Any]]:
        """XML sənəd elementlərini sözlük kimi oxuyur.

        `xml.etree` QƏSDƏN seçilib, `defusedxml` ƏLAVƏ EDİLMƏYİB: fayl
        müəssisənin ÖZ şəbəkə qovluğundan gəlir (internetdən yox), ElementTree
        xarici obyektləri (XXE) genişləndirmir və təyin olunmamış obyektdə
        istisna atır. Yeni asılılıq bu qazanc üçün paket səthini və
        `test_dependency_manifest` qapısını genişləndirərdi.

        Sənədin sahələri HƏM alt-element, HƏM də atribut ola bilər — 1C-nin
        XML ixracı hər iki formanı yazır və hansının işlədiləcəyi
        konfiqurasiyadan asılıdır. İkisini də oxuyuruq: alt-element üstündür,
        çünki 1C onu daha çox işlədir.
        """
        try:
            tree = ElementTree.parse(path)  # noqa: S314 — bax docstring
        except ElementTree.ParseError as exc:
            raise ErpProtocolError(
                f"XML faylı oxunmadı: {exc}",
                user_message=(
                    f"«{path.name}» faylı düzgün XML deyil — ixracın tam yazıldığını "
                    "yoxlayın (yarımçıq yazılmış fayl belə görünür)."
                ),
                context={"file": path.name},
            ) from exc
        except OSError as exc:
            raise ErpConnectionError(
                f"Fayl oxuna bilmədi: {exc}",
                user_message=f"«{path.name}» faylı oxuna bilmədi.",
                context={"file": path.name},
            ) from exc

        for element in tree.getroot().iter(settings.record_tag):
            row: dict[str, Any] = dict(element.attrib)
            for child in element:
                row[child.tag] = (child.text or "").strip()
            yield row

    # ------------------------------ sətir → sənəd ----------------------------- #

    def _records_from(self, path: Path, settings: FileExchangeSettings) -> list[OneCSaleRecord]:
        """Bir faylın sətirlərini `OneCSaleRecord` siyahısına çevirir."""
        records: list[OneCSaleRecord] = []
        checked_columns = False
        for index, row in enumerate(self._rows(path, settings)):
            if not checked_columns:
                self._assert_columns(path, row, settings)
                checked_columns = True
            record = self._to_record(path, index, row, settings)
            if record is not None:
                records.append(record)
        return records

    @staticmethod
    def _assert_columns(path: Path, row: dict[str, Any], settings: FileExchangeSettings) -> None:
        """Sütun uyğunsuzluğu BİRİNCİ sətirdə dayandırılır.

        Sətir-sətir yoxlasaydıq, 20 min sətirlik faylda eyni xəta 20 min dəfə
        loglanardı və əsl səbəb (sütun adı dəyişib) itərdi.
        """
        missing = [name for name in settings.required_columns if name not in row]
        if missing:
            raise ErpProtocolError(
                f"Faylda gözlənilən sütun(lar) yoxdur: {missing}",
                user_message=(
                    f"«{path.name}» faylında gözlənilən sütun(lar) yoxdur: "
                    f"{', '.join(missing)}. Sütun adlarını sihirbazda düzəldin."
                ),
                context={"file": path.name, "found": sorted(row)[:10]},
            )

    def _to_record(
        self, path: Path, index: int, row: dict[str, Any], settings: FileExchangeSettings
    ) -> OneCSaleRecord | None:
        """Bir sətri sənədə çevirir; boş sətir SÜKUTLA atlanır."""
        if not any(str(value or "").strip() for value in row.values()):
            # CSV faylının sonundakı boş sətir adi haldır — onu xəta saymaq
            # hər ixracı uğursuz edərdi.
            return None

        document_id = self._document_id(path, index, row, settings)
        amount_raw = row.get(settings.amount_column)
        return OneCSaleRecord(
            document_id=document_id,
            seller_id=str(row.get(settings.seller_column, "") or "").strip(),
            store_code=str(row.get(settings.store_column, "") or "").strip(),
            gross_amount=to_decimal(amount_raw, document_id),
            document_at=to_datetime(
                row.get(settings.date_column), document_id, formats=settings.date_formats
            ),
            seller_name=_optional_column(row, settings.seller_name_column),
        )

    @staticmethod
    def _document_id(
        path: Path, index: int, row: dict[str, Any], settings: FileExchangeSettings
    ) -> str:
        """Sənəd ID-si: sütundan, yoxsa sintez (bax modul başlığı)."""
        if settings.document_id_column:
            value = str(row.get(settings.document_id_column, "") or "").strip()
            if value:
                return value

        payload = "|".join([path.name, str(index), *(f"{key}={row[key]}" for key in sorted(row))])
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:SYNTHETIC_ID_LENGTH]
        return f"{SYNTHETIC_ID_PREFIX}{digest}"


def _optional_column(row: dict[str, Any], column: str) -> str | None:
    """İSTƏYƏ BAĞLI sütun — göstərilməyibsə `None`."""
    if not column:
        return None
    value = row.get(column)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "FORMAT_CSV",
    "FORMAT_XML",
    "SUPPORTED_FORMATS",
    "SYNTHETIC_ID_PREFIX",
    "FileExchangeSettings",
    "OneCFileExchangeConnector",
]
