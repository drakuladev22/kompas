"""Toplu Əməliyyatlar (#29, kompas1.md Faza 5) — CSV işçi idxalı + mağaza şablonu.

──────────────────────────────────────────────────────────────────────────────
QIRMIZI XƏTT — BU MODUL `create_employee()`-i SƏTİR-SƏTİR ÇAĞIRIR, BİRBAŞA
YAZMIR
──────────────────────────────────────────────────────────────────────────────
`UserManagementUseCase.create_employee()` özündən əvvəl DÖRD qoruma keçirir
(`_require` — `can_manage_employees` flag-i, `_assert_may_assign_position` —
Strict Hierarchy Guard, daxili Dual-Control/anti-fraud süzgəci və sonda
`_audit.record()` — fərdi audit sətri). 300 sətri bir toplu `INSERT` ilə
yazmaq sürətli olardı, LAKİN bu dörd qorumanı da birdən yan keçərdi: HR_Admin
özündən yüksək rütbəli "Root" sətri olan CSV yükləyə bilərdi, çünki toplu
`INSERT`-in `_assert_may_assign_position`-dan xəbəri olmaz.

Ona görə `import_employees()` HƏR keçərli sətir üçün `create_employee()`-i
AYRICA çağırır (bax aşağı, "TRANZAKSİYA SƏRHƏDİ"). Bu, YAVAŞDIR (300 sətir =
300 çağırış), lakin sürət təhlükəsizliyin əvəzinə DEYİL — 300 sətirlik toplu
idxal HƏLƏ DƏ saniyələr çəkir, iyerarxiya pozuntusu isə audit-siz yaranmış
"Root" hesabı deməkdir.

TEST: `tests/unit/test_bulk_operations.py::test_hierarchy_violation_rejects_row`
— actor-dan yüksək rütbəli sətir `create_employee()`-in ÖZ `AuthorizationError`-u
ilə rədd edilir; bu modul həmin qaydanı TƏKRARLAMIR (ikinci, zəif nüsxə
yaratmamaq üçün, `user_management.py` başlığındakı eyni fəlsəfə: "İcazə
matrisi BU MODULDA DEYİL"). Nəticə: iyerarxiya pozuntusu ÖNİZLƏMƏDƏ yox,
YALNIZ TƏSDİQ (idxal) mərhələsində sətir xətası kimi görünür — bu, gecikmiş
aşkarlama DEYİL, tək-həqiqət-mənbəyinin qorunmasıdır.

──────────────────────────────────────────────────────────────────────────────
QİSMƏN İDXAL QƏSDƏNDİR
──────────────────────────────────────────────────────────────────────────────
300 sətirlik faylda BİR sətrin poçt ünvanı səhv formatdadırsa, bütün faylı
rədd etmək HR-i faylı əl ilə bölməyə və 299 düzgün sətri YENİDƏN yükləməyə
məcbur edərdi — real HR işində bu, hər dəfə bir kiçik səhv üçün onlarla
dəqiqə itkisi deməkdir. Ona görə axın İKİ ayrı nəticə yaradır: uğurlu sətirlər
İŞÇİYƏ ÇEVRİLİR, uğursuz sətirlər AYRICA SİYAHIDA (`row_number` + səbəb)
göstərilir — HR yalnız uğursuzları düzəldib TƏKRAR yükləyə bilər.

──────────────────────────────────────────────────────────────────────────────
TRANZAKSİYA SƏRHƏDİ — QƏRAR: HƏR SƏTİR ÖZ TRANZAKSİYASINDA
──────────────────────────────────────────────────────────────────────────────
İKİ ALTERNATİV var idi:
  (a) HƏR SƏTİR ÖZ TRANZAKSİYASINDA (SEÇİLDİ) — hər uğurlu sətir DƏRHAL
      commit olunur (bax `EmployeeRowCreator`, `composition.py`-dəki real
      implementasiya).
  (b) BİR TRANZAKSİYA + SAVEPOINT hər sətir üçün.

(a) SEÇİLDİ, çünki:
  * `PostgresUnitOfWork.commit()` artıq "commit + YENİ tranzaksiya aç" edir
    (bax `connection.py`) — SAVEPOINT infrastrukturu YOXDUR və onu əlavə
    etmək yeni, hələ sınanmamış bir mexanizm yaradardı, halbuki mövcud
    `commit()`/`rollback()` cütü artıq TAM kifayət edir.
  * QİSMƏN İDXAL semantikası (a)-da PULSUZ gəlir: N-ci sətrin uğursuzluğu
    1..N-1-ci sətirlərin artıq COMMIT olunmuş yazılarına HEÇ TƏSİR ETMİR —
    "əvvəlcə hamısını sına, sonra ya hamısını, ya heç nəyi yaz" DEYİL.
  * `create_employee()` ÖZÜ audit sətrini EYNİ çağırışda yazır — sətir
    tranzaksiyası nə qədər tez commit olunsa, o audit sətri də bir o qədər
    tez QALICI olur (proses çöksə belə itmir).

YARIMÇIQ ÇÖKMƏDƏ NƏ QALIR: `bulk_import_log.start()` əməliyyatın ƏVVƏLİNDƏ
`finished_at = NULL` ilə yazılır (adətən İLK sətrin commit-i ilə BİRLİKDƏ
qalıcı olur, çünki `EmployeeRowCreator` HƏR sətirdən sonra commit edir —
bax aşağı). Proses N-ci sətirdə çöksə:
  * 1..N-1-ci sətirlər ARTIQ COMMIT OLUNUB, HƏR BİRİNİN ÖZ `EMPLOYEE_CREATED`
    audit sətri var (`create_employee()`-in daxili yazısı) — "kim yaratdı"
    sualı bu sətirlər üçün CAVABLIDIR.
  * `bulk_import_log` sətri `finished_at = NULL` qalır — Root panelində
    "yarımçıq" kimi GÖRÜNƏN qalır, sükutla "uğurlu" sayılmır.
  * YALNIZ itən şey YEKUN HESABATdır (neçəsi uğurlu/uğursuz oldu) — bu,
    əlverişsizdir, lakin MƏLUMAT İTKİSİ DEYİL: Root `employees` cədvəlindən
    və fərdi audit sətirlərindən faktiki nəticəni bərpa edə bilər.

`bulk_log.finish()` + ƏMƏLİYYAT SƏVİYYƏLİ audit sətri (`BULK_EMPLOYEE_IMPORT_
COMPLETED`) İSƏ BİR TRANZAKSİYADA yazılır (`connection.py`-dəki eyni
bağlantı) — CLAUDE.md §5: "audit yazısı istisna udmur". Bu ikisindən biri
uğursuz olarsa, HEÇ BİRİ yazılmır və `bulk_import_log` sətri `finished_at =
NULL` qalmağa DAVAM EDİR (görünən "yarımçıq" işarəsi) — lakin artıq
yaradılmış işçilər GERİ QAYTARILMIR, çünki onların tranzaksiyaları çoxdan
commit olunub (bu, (a)-nın qaçılmaz nəticəsidir, gizlədilmir).

──────────────────────────────────────────────────────────────────────────────
ETİBARNAMƏ (CREDENTIAL) QƏRARI — MÜVƏQQƏTİ ŞİFRƏ, İLK GİRİŞDƏ MƏCBURİ DƏYİŞMƏ
──────────────────────────────────────────────────────────────────────────────
Üç variant var idi: (a) sistem müvəqqəti şifrə generasiya edir, (b) idxal
şifrəsiz aparılır və HR sonra fərdi təyin edir, (c) CSV-də hash-lənmiş şifrə
qəbul edilir.

(c) DƏRHAL RƏDD EDİLDİ: hash CSV-də olsa belə, onu ORAYA YAZAN proses (HR-in
Excel-i) əvvəlcə AÇIQ şifrəni bilməli olub — problem mənbəyə köçür, həll
olunmur.

(b) RƏDD EDİLDİ: `Employee.__init__` "PIN, VƏ YA istifadəçi adı+şifrə"
invariantını TƏLƏB EDİR (bax `user_management.py`) — şifrəsiz yaradılan işçi
HEÇ VAXT giriş edə bilməzdi, HR isə 300 işçini BİR-BİR açıb fərdi şifrə
təyin etməli olardı ki, bu da toplu idxalın BÜTÜN MƏQSƏDİNİ ləğv edərdi.

(a) SEÇİLDİ: `HashingService.generate_temporary_password()` (artıq
`CredentialResetUseCase.reset_password()`-də İSTİFADƏ OLUNUR, TƏKRAR
yaradılmır) hər sətir üçün TƏSADÜFİ, siyasətə uyğun şifrə yaradır və
`create_employee(initial_password=...)` onu `must_change_password=TRUE` ilə
yazır (`user_management.py`-nin ÖZÜ bunu MƏCBUR edir). Yaradılmış şifrələr
`BulkImportReport.created[].temporary_password`-da BİR DƏFƏLİK qaytarılır
(GUI ekranda göstərir/çap edir) — NƏ `bulk_import_log`-a, NƏ DƏ audit
sətrinə YAZILMIR (yalnız sayğaclar yazılır) — açıq şifrə DİSKƏ DÜŞMÜR.

CSV-DƏ ŞİFRƏ/PIN SÜTUNU AÇIQ RƏDD EDİLİR (`FORBIDDEN_HEADER_TOKENS`): fayl
`file_ref` ilə (adətən diskdə/Drive-da) SAXLANILIR, yəni CSV-də açıq şifrə
olsaydı, o, faylın ÖZÜ ilə birlikdə əbədi qalardı və audit izinə düşərdi.
Bu, sətir-sətir DEYİL, FAYL SƏVİYYƏLİ rəddir — belə sütunun mövcudluğu artıq
təhlükəsizlik siqnalıdır, ondan sonrakı sətirləri emal etmək mənasızdır.

──────────────────────────────────────────────────────────────────────────────
CSV FORMATI
──────────────────────────────────────────────────────────────────────────────
Məcburi sütunlar (ingilis, kiçik hərf, sıra ƏHƏMİYYƏTSİZDİR — `csv.DictReader`
ad üzrə oxuyur): `first_name`, `last_name`, `position_code`, `username`.
İstəyə bağlı: `store_code`, `notification_email`, `hire_date` (`YYYY-MM-DD`),
`date_of_birth` (`YYYY-MM-DD`).

Sütun adları İNGİLİSCƏDİR (Azərbaycanca DEYİL) — bu, bölmə 9-un "yeganə
interfeys dili Azərbaycandır" qaydasını POZMUR: sütun adı MƏTN DEYİL, DATA
FORMATININ açarıdır (GUI onu Azərbaycanca etiketlə göstərə bilər, bax şablon
yükləmə düyməsi). Sabit ingilis açar seçildi, çünki Azərbaycan hərfləri
(ə/ı/ö/ü/ğ/ş/ç) başlıq-uyğunlaşdırmasında normallaşdırma qeyri-müəyyənliyi
(NFC/NFD) əlavə edərdi — verilənlər mübadiləsi formatları üçün ASCII açar
sənayə standartıdır (məs. HTTP başlıqları, JSON açarları).

`store_code` UUID DEYİL: `StoreWriter.get_id_by_code()` (bax
`first_run_setup.py`) insan-oxunaqlı kodu (`stores.code`) UUID-ə çevirir —
HR öz mağazasının UUID-sini əzbər bilmir.

RİSKLƏR (bax `tests/unit/test_bulk_operations.py`):
  * BOM-lu UTF-8 — `bytes.decode("utf-8-sig")` HƏR İKİ halı (BOM-lu/BOM-suz)
    şəffaf həll edir.
  * `;` vs `,` ayırıcı — Excel-in Avropa lokalı `;` ilə ixrac edir (onluq
    kəsr vergüllə qarışmasın deyə); başlıq sətrindəki tezlik sayğacı seçir.
  * Windows/Unix sətir sonu — `str.splitlines()` + `io.StringIO` universal
    sətir-sonu çevirməsi ilə şəffaf həll olunur.
  * Boş fayl / yalnız başlıq sətri — AYRI-AYRI hallardır: BOŞ fayl FAYL
    SƏVİYYƏLİ xəta (`BulkImportFileError`), başlıq-yalnız fayl isə QANUNİ
    "0 sətir" nəticəsidir (heç kim yaradılmır, xəta da YOXDUR).
  * Fayl daxilində dublikat + mövcud işçi ilə toqquşma — `username` açardır
    (CITEXT ilə eyni davranış: kiçik hərfə salınmış müqayisə).
  * Çox böyük fayl — `BULK_IMPORT_MAX_ROWS` (ROOT parametri) FAYLI TAM RƏDD
    EDİR (sükutla kəsmir) — HR faylın NECƏ bölünəcəyini bilməlidir.
  * Sütun sırasının dəyişməsi — `csv.DictReader` ad üzrə oxuyur, sıradan
    ASILI DEYİL.
  * Əskik məcburi sütun — fayl səviyyəli rədd, aydın "hansı sütun(lar)"
    mesajı ilə.

──────────────────────────────────────────────────────────────────────────────
MAĞAZA ŞABLONU — TƏK-İSTİQAMƏTLİ KÖÇÜRMƏ
──────────────────────────────────────────────────────────────────────────────
`StoreTemplateUseCase.capture()` mənbə mağazanın `stores` sətrinə HEÇ VAXT
YAZMIR — YALNIZ OXUYUR (`based_on_store_id` bir İSTİNADDIR). `apply()` isə
YENİ mağaza yaradır (`StoreWriter.create()` — `FirstRunSetupUseCase`-in
İSTİFADƏ ETDİYİ EYNİ port, İKİNCİ yazma yolu İCAD EDİLMİR) və MƏNBƏ mağazanın
sətrinə TOXUNMUR. Nəticə: mənbə mağaza NECƏ İDİSƏ ELƏCƏ QALIR — köçürmə TƏK
İSTİQAMƏTLİDİR.

`config_snapshot` NƏYİ EHTİVA EDİR: çağıran tərəfin (GUI, `screen_data.py`-in
OXU sorğuları ilə mənbə mağazadan topladığı) TƏQDİM ETDİYİ ayar lüğəti +
`captured_at` möhürü (bu modul avtomatik ƏLAVƏ edir). BOŞ lüğət RƏDD EDİLİR
(`migrations/037` `CHECK`-inin domen güzgüsü, bax `StoreTemplate`).

`config_snapshot` NƏYİ ETMİR (İSTİFADƏÇİ "HƏR ŞEY KÖÇDÜ" GÖZLƏYƏ BİLƏR,
ONA GÖRƏ AÇIQ YAZILIR):
  * İŞÇİLƏR köçürülmür — yeni mağaza SIFIR işçi ilə yaranır, işə qəbul
    HR-in `create_employee()` vasitəsilə AYRICA (adi) axınıdır.
  * CƏRİMƏ TARİXÇƏSİ köçürülmür — cərimə HƏMİŞƏ konkret bir hadisənin
    (kim, nə vaxt, hansı işçi) qeydidir; onu "şablona" çevirmək mübahisədə
    "bu cərimə kimə aiddir?" sualını mənasız edərdi.
  * SATIŞ/XAL TARİXÇƏSİ köçürülmür — eyni səbəb.
  * `positions`/`work_modes` KATALOQLARI YENİDƏN YARADILMIR: onlar artıq
    TENANT-DAXİLİ PAYLAŞILAN kataloqlardır (`UNIQUE (tenant_id, code)` /
    `UNIQUE (tenant_id, name)`, `schema.sql` §11) — eyni tenant-ın YENİ
    mağazası onlara zatən baxa bilir, "köçürmək" texniki cəhətdən NƏ
    ETMƏK demək olduğu bəlli olmayan (ya no-op, ya təkrar-yaratma xətası)
    əməliyyat olardı. Bunun ƏVƏZİNƏ `config_snapshot` bu kataloqlardan HANSI
    alt-çoxluğun mənbə mağazada İSTİFADƏ OLUNDUĞUNU İNFORMATİV OLARAQ
    saxlaya bilər (GUI-nin oxu sorğusu bunu doldurur) — Root/HR onu YENİ
    mağazanı əl ilə qurarkən İSTİNAD kimi işlədir, avtomatik yaratma YOXDUR.
    Bu, HƏM DƏ TƏHLÜKƏSİZLİK QƏRARIDIR: `positions` prioritet (iyerarxiya)
    daşıyır və onu toplu/avtomatik yaratmaq Strict Hierarchy Guard-ın həssas
    sahəsinə toxunardı — CLAUDE.md §5-in ehtiyatlılıq tələbi.

──────────────────────────────────────────────────────────────────────────────
AUDİT — AQREQAT SƏTİR, 300 SƏTİR YOX
──────────────────────────────────────────────────────────────────────────────
`create_employee()` artıq ÖZ FƏRDİ audit sətrini yazır (`EMPLOYEE_CREATED`,
hər işçi üçün BİR). Bu modul ƏLAVƏ olaraq ƏMƏLİYYAT səviyyəsində BİR sətir
yazır (`BULK_EMPLOYEE_IMPORT_COMPLETED` / `STORE_TEMPLATE_APPLIED`) —
`attrition_risk.py::ATTRITION_SCORES_RECALCULATED` naxışı: "300 sətir üçün
300 audit yazısı YOX", YALNIZ "kim, nə vaxt, hansı fayl, neçə sətir, neçəsi
uğurlu/uğursuz" sualının BİR sətirlik cavabı.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Final, Protocol

from src.application.root_limits import limit_int
from src.application.use_cases.user_management import EmployeeDraft
from src.domain.policies import SystemLimitKey
from src.domain.value_objects.credentials import (
    EmailAddress,
    InvalidEmailError,
    InvalidUsernameError,
    Username,
)
from src.domain.value_objects.identifiers import (
    new_bulk_import_log_id,
    new_employee_id,
    new_store_id,
    new_store_template_id,
)
from src.domain.value_objects.store_templates import StoreTemplate
from src.infrastructure.security.hashing import HashingService
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from src.application.use_cases.first_run_setup import StoreDraft, StoreWriter
    from src.domain.entities.employee import Employee
    from src.domain.interfaces.ports import (
        AuditTrail,
        BulkImportLogRepository,
        Clock,
        EmployeeRepository,
        PositionRepository,
        StoreTemplateRepository,
        SystemLimits,
    )
    from src.domain.value_objects.identifiers import (
        BulkImportLogId,
        EmployeeId,
        StoreId,
        StoreTemplateId,
        TenantId,
    )

_audit_log = get_logger(__name__, channel=LogChannel.AUDIT)
_security_log = get_logger(__name__, channel=LogChannel.SECURITY)

#: Faza 5 spesifikasiyasının hardlock (səviyyə 3) flag-i — `migrations/038`.
#: Bu, HƏR İKİ use case-in (CSV idxalı + mağaza şablonu) ORTAQ qapısıdır.
BULK_OPERATIONS_FLAG: Final = "can_perform_bulk_operations"

#: `bulk_import_log.import_type` — sərbəst mətn (bax miqrasiya şərhi), lakin
#: BU İKİ dəyər bu modulun ÖZ konvensiyasıdır.
IMPORT_TYPE_EMPLOYEES: Final = "ISCI_IDXALI"
IMPORT_TYPE_STORE_TEMPLATE: Final = "MAGAZA_SABLON_KOCURME"

REQUIRED_COLUMNS: Final[tuple[str, ...]] = ("first_name", "last_name", "position_code", "username")
OPTIONAL_COLUMNS: Final[tuple[str, ...]] = (
    "store_code",
    "notification_email",
    "hire_date",
    "date_of_birth",
)
#: Bu tokenlərdən biri başlıq adında (alt-sətir kimi) görünsə, FAYL TAM RƏDD
#: EDİLİR — bax modul başlığı "ETİBARNAMƏ QƏRARI".
FORBIDDEN_HEADER_TOKENS: Final[frozenset[str]] = frozenset(
    {"password", "parol", "şifrə", "sifre", "pass", "pin"}
)


class BulkOperationsError(KompasOSError):
    """Toplu əməliyyat (CSV idxal / mağaza şablonu) qaydası pozuldu."""

    user_message = "Toplu əməliyyat icra edilə bilmədi."


class BulkOperationsPermissionError(BulkOperationsError):
    user_message = "Toplu əməliyyat aparmaq səlahiyyətiniz yoxdur."


class BulkImportFileError(BulkOperationsError):
    """Fayl SƏVİYYƏLİ problem — TƏK sətir deyil, BÜTÜN fayl rədd edilir."""

    user_message = "Fayl formatı düzgün deyil."


class StoreTemplateNotFoundError(BulkOperationsError):
    user_message = "Mağaza şablonu tapılmadı."


class StoreTemplateValidationError(BulkOperationsError):
    user_message = "Şablon məlumatı düzgün deyil."


class EmployeeRowCreator(Protocol):
    """Bir CSV sətrini TAM TRANZAKSİYADA `create_employee()`-ə ötürən çağırıq.

    KONKRET REALİZASİYA (`composition.py`) hər çağırışdan SONRA `commit()`
    edir, uğursuzluqda isə `rollback()` — bax modul başlığı "TRANZAKSİYA
    SƏRHƏDİ". Testdə bu, sadəcə fakes-lə qurulmuş `UserManagementUseCase.
    create_employee`-in ÖZÜDÜR (fakes-in təbiətinə görə onsuz da atomikdir,
    əlavə sarğı lazım deyil) — yəni istehsalat VƏ test EYNİ metodu (bağlı)
    çağırır, YALNIZ tranzaksiya idarəetməsi fərqlidir.
    """

    def __call__(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        employee_id: EmployeeId,
        draft: EmployeeDraft,
        initial_password: str,
    ) -> Employee: ...


@dataclass(frozen=True)
class CsvRowError:
    """Bir sətrin RƏDD SƏBƏBİ — `row_number` başlıq sətrini 1 sayır (Excel naxışı)."""

    row_number: int
    message: str


@dataclass(frozen=True)
class ParsedEmployeeRow:
    """Fayl-səviyyəli VƏ sətir-səviyyəli yoxlamalardan KEÇMİŞ sətir."""

    row_number: int
    draft: EmployeeDraft
    username: Username


@dataclass(frozen=True)
class BulkImportPreview:
    """`preview_csv()`-in nəticəsi — ekranın "fayl yüklə → önizləmə" addımı.

    `errors` TAM siyahıdır (hesablama üçün) — `displayed_errors` isə ROOT
    parametrinə (`BULK_IMPORT_PREVIEW_ERROR_LIMIT`) görə KƏSİLMİŞ, ekranda
    göstərilən alt-çoxluqdur. İkisini QARIŞDIRMAQ `error_count`-u SƏHV
    (kiçik) göstərərdi — bax `policies.py` şərhi: "Aqreqat rəqəm HƏMİŞƏ TAM
    göstərilir — yalnız SƏTİR-SƏTİR siyahı kəsilir".
    """

    header_columns: tuple[str, ...]
    total_data_rows: int
    valid_rows: tuple[ParsedEmployeeRow, ...]
    errors: tuple[CsvRowError, ...]
    displayed_errors: tuple[CsvRowError, ...]
    errors_truncated: bool

    @property
    def error_count(self) -> int:
        return len(self.errors)


@dataclass(frozen=True)
class BulkCreatedEmployee:
    """YARADILMIŞ işçi + BİR DƏFƏLİK göstərilən müvəqqəti şifrə.

    Şifrə BURADAN KƏNARA (log/audit) YAZILMIR — bax modul başlığı.
    """

    row_number: int
    employee_id: EmployeeId
    username: str
    temporary_password: str


@dataclass(frozen=True)
class BulkImportReport:
    """`import_employees()`-in yekun nəticəsi."""

    log_id: BulkImportLogId
    row_count: int
    success_count: int
    error_count: int
    errors: tuple[CsvRowError, ...]
    created: tuple[BulkCreatedEmployee, ...]


@dataclass(frozen=True)
class StoreTemplateApplyResult:
    """`StoreTemplateUseCase.apply()`-in nəticəsi."""

    new_store_id: StoreId
    template_id: StoreTemplateId
    template_name: str
    config_snapshot: Mapping[str, object]


class _RowRejectedError(Exception):
    """SƏTİR-SƏVİYYƏLİ rədd — `_parse_row`-un daxili axın idarəetməsi.

    İSTİSNA OLARAQ İSTİFADƏ OLUNUR (nə deyil-return zənciri), çünki
    yoxlamaların sayı (boş sahə, dublikat, mövcud toqquşma, rol, mağaza,
    e-poçt, tarix) iç-içə `if/return` ilə yazılsaydı oxunaqlılıq itərdi.
    Xaricə HEÇ VAXT sızmır — `_parse_csv` onu tuta bilər.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BulkEmployeeImportUseCase:
    """CSV-əsaslı toplu işçi idxalı (#29) — bax modul başlığı."""

    def __init__(
        self,
        *,
        employees: EmployeeRepository,
        positions: PositionRepository,
        stores: StoreWriter,
        create_employee_row: EmployeeRowCreator,
        hashing: HashingService,
        bulk_log: BulkImportLogRepository,
        audit: AuditTrail,
        clock: Clock,
        limits: SystemLimits | None = None,
    ) -> None:
        self._employees = employees
        self._positions = positions
        self._stores = stores
        self._create_employee_row = create_employee_row
        self._hashing = hashing
        self._bulk_log = bulk_log
        self._audit = audit
        self._clock = clock
        self._limits = limits

    # ------------------------------- önizləmə --------------------------------- #

    def preview_csv(
        self, *, tenant_id: TenantId, actor: Employee, csv_bytes: bytes
    ) -> BulkImportPreview:
        """Fayl → sətir-sətir yoxlama, HEÇ NƏ YAZILMIR."""
        now = self._clock.now()
        self._require(actor, now=now)
        return self._parse(tenant_id=tenant_id, csv_bytes=csv_bytes)

    # -------------------------------- idxal ------------------------------------ #

    def import_employees(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        csv_bytes: bytes,
        file_ref: str | None,
    ) -> BulkImportReport:
        """Fayl → TƏSDİQ → sətir-sətir yaratma (bax modul başlığı).

        Fayl YENİDƏN TƏHLİL EDİLİR (`preview_csv`-in nəticəsi ETİBAR EDİLƏN
        keş kimi İSTİFADƏ OLUNMUR): önizləmə ilə təsdiq arasında başqa bir
        proses eyni istifadəçi adını tuta bilər — YENİDƏN yoxlama bu yarış
        vəziyyətini bağlayır (`AnnualLeaveUseCase.approve`-un "əvvəlcə oxu,
        sonra yaz" barədə eyni ehtiyatı, fərqli mexanizmlə: burada tam
        DB-səviyyəli qapaq yoxdur, ona görə YENİDƏN OXU seçildi).
        """
        now = self._clock.now()
        self._require(actor, now=now)
        preview = self._parse(tenant_id=tenant_id, csv_bytes=csv_bytes)

        log_id = new_bulk_import_log_id()
        self._bulk_log.start(
            log_id=log_id,
            tenant_id=tenant_id,
            import_type=IMPORT_TYPE_EMPLOYEES,
            performed_by=actor.id,
            file_ref=file_ref,
            row_count=preview.total_data_rows,
            performed_at=now,
        )

        errors: list[CsvRowError] = list(preview.errors)
        created: list[BulkCreatedEmployee] = []
        for row in preview.valid_rows:
            employee_id = new_employee_id()
            temporary_password = self._hashing.generate_temporary_password()
            try:
                self._create_employee_row(
                    tenant_id=tenant_id,
                    actor=actor,
                    employee_id=employee_id,
                    draft=row.draft,
                    initial_password=temporary_password,
                )
            except Exception as exc:  # geniş tutma QƏSDƏNDİR — qismən idxal, sətir izolyasiyası
                errors.append(CsvRowError(row.row_number, _failure_message(exc)))
                continue
            created.append(
                BulkCreatedEmployee(
                    row_number=row.row_number,
                    employee_id=employee_id,
                    username=str(row.username),
                    temporary_password=temporary_password,
                )
            )

        finished_at = self._clock.now()
        success_count = len(created)
        error_count = len(errors)
        summary = _summarize_errors(errors, limit=self._preview_error_limit(tenant_id))

        # `finish()` + AQREQAT audit sətri BİR tranzaksiyadadır (eyni bağlantı,
        # `connection.py`) — CLAUDE.md §5: "audit yazısı istisna udmur". Bu
        # ikisi uğursuz olsa, fərdi sətirlərin ARTIQ commit olunmuş nəticəsinə
        # TOXUNULMUR (bax modul başlığı).
        self._bulk_log.finish(
            log_id=log_id,
            success_count=success_count,
            error_count=error_count,
            error_summary=summary,
            finished_at=finished_at,
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="BULK_EMPLOYEE_IMPORT_COMPLETED",
            entity_type="bulk_import_log",
            entity_id=log_id,
            after_state={
                "row_count": preview.total_data_rows,
                "success_count": success_count,
                "error_count": error_count,
                "file_ref": file_ref,
            },
        )
        return BulkImportReport(
            log_id=log_id,
            row_count=preview.total_data_rows,
            success_count=success_count,
            error_count=error_count,
            errors=tuple(errors),
            created=tuple(created),
        )

    def recent_operations(
        self, *, tenant_id: TenantId, actor: Employee, limit: int = 50
    ) -> list[dict[str, object]]:
        """Root panelinin "son toplu əməliyyatlar" siyahısı."""
        self._require(actor, now=self._clock.now())
        return self._bulk_log.list_recent(tenant_id, limit=limit)

    # ------------------------------- daxili ------------------------------------ #

    def _parse(self, *, tenant_id: TenantId, csv_bytes: bytes) -> BulkImportPreview:
        max_rows = limit_int(self._limits, tenant_id, SystemLimitKey.BULK_IMPORT_MAX_ROWS)

        try:
            text = csv_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise BulkImportFileError(
                "Fayl UTF-8 kodlaşdırmasında deyil",
                user_message="Fayl UTF-8 mətn formatında olmalıdır.",
            ) from exc

        if not text.strip():
            raise BulkImportFileError(
                "Fayl boşdur", user_message="Yüklənən fayl boşdur — heç bir sətir tapılmadı."
            )

        lines = text.splitlines()
        delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        fieldnames = tuple(reader.fieldnames or ())
        header_map = {(name or "").strip().lower(): name for name in fieldnames}

        if not header_map:
            raise BulkImportFileError(
                "Fayl başlıq sətri tapılmadı",
                user_message="Fayl düzgün CSV başlığı daşımır.",
            )
        if any(any(token in header for token in FORBIDDEN_HEADER_TOKENS) for header in header_map):
            raise BulkImportFileError(
                "CSV faylında şifrə/PIN sütunu qadağandır",
                user_message=(
                    "Fayl şifrə və ya PIN sütunu daşıyır — açıq mətn şifrə idxal edilə bilməz. "
                    "Bu sütunu silib faylı yenidən yükləyin."
                ),
            )
        missing_columns = [col for col in REQUIRED_COLUMNS if col not in header_map]
        if missing_columns:
            raise BulkImportFileError(
                f"Məcburi sütun(lar) əskikdir: {', '.join(missing_columns)}",
                user_message=(f"Fayl bu məcburi sütunları daşımır: {', '.join(missing_columns)}."),
            )

        raw_rows = list(reader)
        if len(raw_rows) > max_rows:
            raise BulkImportFileError(
                f"Fayl {len(raw_rows)} sətir daşıyır, tavan {max_rows}-dir",
                user_message=(
                    f"Fayl çox böyükdür ({len(raw_rows)} sətir, tavan {max_rows}). "
                    "Faylı bölüb ayrı-ayrı yükləyin."
                ),
            )

        seen_usernames: set[str] = set()
        valid_rows: list[ParsedEmployeeRow] = []
        errors: list[CsvRowError] = []
        for offset, raw in enumerate(raw_rows):
            row_number = offset + 2  # 1 = başlıq sətri (Excel-in öz nömrələməsi)
            try:
                parsed = self._parse_row(
                    tenant_id=tenant_id,
                    row_number=row_number,
                    raw=raw,
                    header_map=header_map,
                    seen_usernames=seen_usernames,
                )
            except _RowRejectedError as exc:
                errors.append(CsvRowError(row_number, exc.message))
                continue
            valid_rows.append(parsed)

        preview_limit = self._preview_error_limit(tenant_id)
        truncated = len(errors) > preview_limit
        return BulkImportPreview(
            header_columns=fieldnames,
            total_data_rows=len(raw_rows),
            valid_rows=tuple(valid_rows),
            errors=tuple(errors),
            displayed_errors=tuple(errors[: max(1, preview_limit)]),
            errors_truncated=truncated,
        )

    def _parse_row(
        self,
        *,
        tenant_id: TenantId,
        row_number: int,
        raw: dict[str, str | None],
        header_map: dict[str, str],
        seen_usernames: set[str],
    ) -> ParsedEmployeeRow:
        def cell(name: str) -> str:
            key = header_map.get(name)
            if key is None:
                return ""
            return (raw.get(key) or "").strip()

        first_name = cell("first_name")
        last_name = cell("last_name")
        position_code = cell("position_code").upper()
        username_raw = cell("username")

        missing = [
            label
            for label, value in (
                ("first_name", first_name),
                ("last_name", last_name),
                ("position_code", position_code),
                ("username", username_raw),
            )
            if not value
        ]
        if missing:
            raise _RowRejectedError(f"Məcburi sahə(lər) boşdur: {', '.join(missing)}")

        try:
            username = Username.parse(username_raw)
        except InvalidUsernameError as exc:
            raise _RowRejectedError(f"İstifadəçi adı yararsızdır: {exc.user_message}") from exc

        username_key = str(username)
        if username_key in seen_usernames:
            raise _RowRejectedError(f"Fayl daxilində dublikat istifadəçi adı: {username_key}")
        if self._employees.get_by_username(tenant_id, username) is not None:
            raise _RowRejectedError(f"Bu istifadəçi adı artıq mövcuddur: {username_key}")
        seen_usernames.add(username_key)

        position = self._positions.get_by_code(tenant_id, position_code)
        if position is None or not position.is_active:
            raise _RowRejectedError(f"Rol tapılmadı və ya deaktivdir: {position_code}")

        store_code = cell("store_code")
        store_id: StoreId | None = None
        if store_code:
            store_id = self._stores.get_id_by_code(tenant_id, store_code)
            if store_id is None:
                raise _RowRejectedError(f"Mağaza kodu tapılmadı: {store_code}")

        email_raw = cell("notification_email")
        email: EmailAddress | None = None
        if email_raw:
            try:
                email = EmailAddress.parse(email_raw)
            except InvalidEmailError as exc:
                raise _RowRejectedError(f"E-poçt yararsızdır: {exc.user_message}") from exc

        hire_date = _parse_optional_date(cell("hire_date"), field="hire_date")
        date_of_birth = _parse_optional_date(cell("date_of_birth"), field="date_of_birth")

        draft = EmployeeDraft(
            first_name=first_name,
            last_name=last_name,
            position=position,
            store_id=store_id,
            username=username,
            notification_email=email,
            hire_date=hire_date,
            date_of_birth=date_of_birth,
        )
        return ParsedEmployeeRow(row_number=row_number, draft=draft, username=username)

    def _require(self, actor: Employee, *, now: datetime) -> None:
        if not actor.has_permission(BULK_OPERATIONS_FLAG, now=now):
            _security_log.warning("BULK_OPERATIONS_DENIED", extra={"actor_id": str(actor.id)})
            raise BulkOperationsPermissionError(
                f"«{BULK_OPERATIONS_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id)},
            )

    def _preview_error_limit(self, tenant_id: TenantId) -> int:
        return limit_int(self._limits, tenant_id, SystemLimitKey.BULK_IMPORT_PREVIEW_ERROR_LIMIT)


class StoreTemplateUseCase:
    """Mağaza şablonu — köçürmə + tətbiq (#29). Bax modul başlığı."""

    def __init__(
        self,
        *,
        templates: StoreTemplateRepository,
        stores: StoreWriter,
        bulk_log: BulkImportLogRepository,
        audit: AuditTrail,
        clock: Clock,
    ) -> None:
        self._templates = templates
        self._stores = stores
        self._bulk_log = bulk_log
        self._audit = audit
        self._clock = clock

    def capture(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        name: str,
        source_store_id: StoreId | None,
        config_snapshot: Mapping[str, object],
    ) -> StoreTemplate:
        """Mövcud mağazanın quruluşunu adlandırılmış şablona ÇEVİRİR.

        MƏNBƏ MAĞAZANIN ÖZ SƏTRİNƏ TOXUNULMUR — bax modul başlığı ("TƏK-
        İSTİQAMƏTLİ KÖÇÜRMƏ"). `source_store_id` YALNIZ İSTİNADDIR
        (`based_on_store_id`, `ON DELETE SET NULL`).
        """
        now = self._clock.now()
        self._require(actor, now=now)
        if not config_snapshot:
            raise StoreTemplateValidationError(
                "Şablonun ayar toplusu boş ola bilməz",
                user_message="Şablonda ən azı bir ayar seçin.",
            )
        stamped_snapshot: dict[str, object] = {
            **dict(config_snapshot),
            "captured_at": now.isoformat(),
        }
        template = StoreTemplate(
            name=name,
            tenant_id=tenant_id,
            store_template_id=new_store_template_id(),
            based_on_store_id=source_store_id,
            config_snapshot=stamped_snapshot,
            created_by=actor.id,
        )
        self._templates.save(tenant_id, template)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="STORE_TEMPLATE_CAPTURED",
            entity_type="store_templates",
            entity_id=template.store_template_id,
            after_state={
                "name": template.name,
                "based_on_store_id": str(source_store_id) if source_store_id else None,
                "setting_count": len(stamped_snapshot),
            },
        )
        return template

    def list_templates(
        self, *, tenant_id: TenantId, actor: Employee, include_inactive: bool = False
    ) -> list[StoreTemplate]:
        self._require(actor, now=self._clock.now())
        return self._templates.list_for_tenant(tenant_id, include_inactive=include_inactive)

    def deactivate(
        self, *, tenant_id: TenantId, actor: Employee, template_id: StoreTemplateId
    ) -> None:
        now = self._clock.now()
        self._require(actor, now=now)
        template = self._templates.get(template_id)
        if template is None:
            raise StoreTemplateNotFoundError(
                "Mağaza şablonu tapılmadı", context={"template_id": str(template_id)}
            )
        self._templates.deactivate(tenant_id, template_id, changed_by=actor.id)
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="STORE_TEMPLATE_DEACTIVATED",
            entity_type="store_templates",
            entity_id=template_id,
            before_state={"is_active": True},
            after_state={"is_active": False},
        )

    def apply(
        self,
        *,
        tenant_id: TenantId,
        actor: Employee,
        template_id: StoreTemplateId,
        new_store: StoreDraft,
    ) -> StoreTemplateApplyResult:
        """Şablonu ƏSAS GÖTÜRƏRƏK YENİ mağaza yaradır.

        YAZI YOLU `StoreWriter.create()`-dir — `FirstRunSetupUseCase`-in
        İSTİFADƏ ETDİYİ EYNİ port (bax modul başlığı: "İKİNCİ yazma yolu İCAD
        EDİLMİR"). Rol/iş rejimi kataloqları YENİDƏN YAZILMIR (bax modul
        başlığı, "config_snapshot NƏYİ ETMİR") — yeni mağaza onlara artıq
        TENANT-DAXİLİ paylaşılan kataloq olaraq baxa bilir.
        """
        now = self._clock.now()
        self._require(actor, now=now)
        template = self._templates.get(template_id)
        if template is None or not template.is_active:
            raise StoreTemplateNotFoundError(
                "Mağaza şablonu tapılmadı", context={"template_id": str(template_id)}
            )

        created_store_id = new_store_id()
        self._stores.create(
            store_id=created_store_id,
            tenant_id=tenant_id,
            code=new_store.code,
            name=new_store.name,
            brand=new_store.brand,
            address=new_store.address,
        )

        log_id = new_bulk_import_log_id()
        self._bulk_log.start(
            log_id=log_id,
            tenant_id=tenant_id,
            import_type=IMPORT_TYPE_STORE_TEMPLATE,
            performed_by=actor.id,
            file_ref=None,
            row_count=1,
            performed_at=now,
        )
        self._bulk_log.finish(
            log_id=log_id,
            success_count=1,
            error_count=0,
            error_summary=None,
            finished_at=now,
        )
        self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor.id,
            action="STORE_TEMPLATE_APPLIED",
            entity_type="store_templates",
            entity_id=template_id,
            after_state={
                "new_store_id": str(created_store_id),
                "new_store_code": new_store.code,
                "template_name": template.name,
            },
        )
        return StoreTemplateApplyResult(
            new_store_id=created_store_id,
            template_id=template_id,
            template_name=template.name,
            config_snapshot=template.config_snapshot,
        )

    def _require(self, actor: Employee, *, now: datetime) -> None:
        if not actor.has_permission(BULK_OPERATIONS_FLAG, now=now):
            _security_log.warning("BULK_OPERATIONS_DENIED", extra={"actor_id": str(actor.id)})
            raise BulkOperationsPermissionError(
                f"«{BULK_OPERATIONS_FLAG}» səlahiyyəti yoxdur",
                context={"actor_id": str(actor.id)},
            )


def _parse_optional_date(raw: str, *, field: str) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise _RowRejectedError(
            f"Tarix formatı yararsızdır ({field}): {raw!r} — YYYY-MM-DD gözlənilir"
        ) from exc


def _failure_message(exc: Exception) -> str:
    """`create_employee()`-dən gələn istisnanı OXUNAQLI sətir mesajına çevirir."""
    if isinstance(exc, KompasOSError):
        return exc.user_message
    return f"Gözlənilməz xəta: {type(exc).__name__}"


def _summarize_errors(errors: list[CsvRowError], *, limit: int) -> str | None:
    """`bulk_import_log.error_summary` — bax `chk_bulk_import_error_detail`."""
    if not errors:
        return None
    shown = errors[: max(1, limit)]
    lines = [f"Sətir {item.row_number}: {item.message}" for item in shown]
    remaining = len(errors) - len(shown)
    if remaining > 0:
        lines.append(f"... və daha {remaining} sətir")
    return "\n".join(lines)


__all__ = [
    "BULK_OPERATIONS_FLAG",
    "FORBIDDEN_HEADER_TOKENS",
    "IMPORT_TYPE_EMPLOYEES",
    "IMPORT_TYPE_STORE_TEMPLATE",
    "OPTIONAL_COLUMNS",
    "REQUIRED_COLUMNS",
    "BulkCreatedEmployee",
    "BulkEmployeeImportUseCase",
    "BulkImportFileError",
    "BulkImportPreview",
    "BulkImportReport",
    "BulkOperationsError",
    "BulkOperationsPermissionError",
    "CsvRowError",
    "EmployeeRowCreator",
    "ParsedEmployeeRow",
    "StoreTemplateApplyResult",
    "StoreTemplateNotFoundError",
    "StoreTemplateUseCase",
    "StoreTemplateValidationError",
]
