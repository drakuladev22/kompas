"""Aqreqat sahələri ↔ `save()` sütunları ↔ hidratasiya təyinatları — ÜMUMİLƏŞDİRİLMİŞ qapı.

──────────────────────────────────────────────────────────────────────────────
NİYƏ BU FAYL VAR — ÜÇ DƏFƏ TƏKRARLANAN QÜSUR SİNFİ
──────────────────────────────────────────────────────────────────────────────
Bir günün ərzində EYNİ qüsur sinfi ÜÇ DƏFƏ tapıldı: entity-yə sahə əlavə
olunur, davamlılıq qatı (repository `save()` VƏ ya hidratasiya) onu YAZMIR/
OXUMUR, saxta repository işlədən testlər isə BUNU GÖRMÜR (entity düzgün
dəyişir, saxta repo HƏR ŞEYİ saxlayır):

  1. `Employee.anonymize_personal_data()` 6 sahə dəyişirdi, `save()` 3-nü
     yazırdı — PII bazada QALIRDI (bax `test_persistence_gap_coverage.py`).
  2. `employees.deactivated_at` heç vaxt yazılmırdı — retensiya filtri
     ƏBƏDİ boş qaytarardı (indi TIME-1 trigger-i ilə həll olunub,
     migrations/096).
  3. `tasks.source` `_hydrate()`-də yox idi (indi düzəldilib, migrations/097).

Bu fayl `test_persistence_gap_coverage.py`-dəki AST-əsaslı üsulu (əl-ilə
YAZILAN sahə siyahısı deyil, entity-nin ÖZÜNDƏN çıxarılan siyahı)
ÜMUMİLƏŞDİRİR və hazırda İKİ aqreqata (`Employee`, `Task`) tətbiq edir.

──────────────────────────────────────────────────────────────────────────────
QƏSDƏN MƏHDUD ƏHATƏ — HAMISI YOX
──────────────────────────────────────────────────────────────────────────────
Repozitoriyada ~30 hidratasiya funksiyası var (`mappers.py` + 16 ayrı
`persistence/*.py` faylı, `_hydrate` metodu / `_from_row` funksiyası
qarışıq). Hamısını BİR dəfəyə əhatə etmək cəhdi RİSKLİDİR: hər YENİ aqreqat
öz İSTİSNA siyahısını tələb edir (bax aşağı — `EMPLOYEE_EXCEPTIONS`/
`TASK_EXCEPTIONS`) və həmin siyahı DƏQİQLƏŞDİRMƏ tələb edir (sahə HƏQİQƏTƏN
qəsdən yazılmır, ya da unudulub?). Bu, AZ sayda aqreqatda BELƏ xeyli tədqiqat
tələb etdi (aşağıdakı `TASK_EXCEPTIONS`-dəki PENDING qeydlərinə bax) — 20
aqreqatı bir sessiyada eyni diqqətlə etmək İSTİSNA siyahısını yoxlanılmamış
təxminlərlə doldurar və qapının ÖZÜ etibarsızlaşar. Genişləndirmə TÖVSİYƏ
OLUNUR, LAKİN tədricən (hər dəfə bir aqreqat, hər İSTİSNA TƏSDİQLƏNƏRƏK).
"""

from __future__ import annotations

import ast
import inspect
import re
import textwrap

from src.domain.entities.employee import Employee
from src.domain.entities.task import Task
from src.infrastructure.persistence import mappers
from src.infrastructure.persistence.catalog_repositories import PostgresTaskRepository
from src.infrastructure.persistence.repositories import PostgresEmployeeRepository

# --------------------------------------------------------------------------- #
# Ümumi köməkçilər — AST ilə "əl-ilə YAZILMAYAN" siyahılar
# --------------------------------------------------------------------------- #


def _init_public_self_attributes(cls: type) -> set[str]:
    """`__init__`-in gövdəsindəki `self.<ad> = ...` təyinatları.

    YALNIZ PUBLİK adlar (alt-xətli daxili vəziyyət — `_overrides`,
    `_assigned_store_ids` kimi — DB sütunu DEYİL, sahtə DAXİLİ strukturdur,
    ona görə istisna EDİLİR, siyahıya YAZILMIR).
    """
    source = textwrap.dedent(inspect.getsource(cls.__init__))
    func_def = ast.parse(source).body[0]
    assigned: set[str] = set()
    for node in ast.walk(func_def):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and not target.attr.startswith("_")
            ):
                assigned.add(target.attr)
    return assigned


def _sql_written_columns(sql: str) -> set[str]:
    """`col = %s` (UPDATE/`DO UPDATE SET`) VƏ `INSERT INTO tbl (col1, ...)`
    siyahısını BİRLƏŞDİRİR — ikisi də `save()`-in YAZDIĞI sütunlardır.

    `INSERT`-only sütun (məs. "founding fact") `DO UPDATE SET`-də YOXDUR,
    lakin BU DA sahənin YAZILDIĞI deməkdir — sadəcə YALNIZ yaranış anında.
    """
    columns = set(re.findall(r"(\w+)\s*=\s*%s", sql))
    insert_match = re.search(r"INSERT\s+INTO\s+\w+\s*\(([^)]*)\)", sql, re.IGNORECASE | re.DOTALL)
    if insert_match:
        columns |= {c.strip() for c in insert_match.group(1).split(",") if c.strip()}
    return columns


def _constructor_kwargs(source: str, class_name: str) -> set[str]:
    """Mətndəki `ClassName(kwarg=..., ...)` çağırışının açar-söz adları."""
    tree = ast.parse(textwrap.dedent(source))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == class_name
        ):
            return {kw.arg for kw in node.keywords if kw.arg is not None}
    raise AssertionError(f"`{class_name}(...)` çağırışı mətndə tapılmadı — funksiya adı dəyişibmi?")


def _attr_assignment_targets(source: str, var_name: str) -> set[str]:
    """`var_name.<ad> = ...` təyinatları — constructor-BYPASS hidratasiya naxışı
    (məs. `Task.__new__` + əl-ilə sahə təyini, `_hydrate()` başlığına bax)."""
    tree = ast.parse(textwrap.dedent(source))
    assigned: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == var_name
            ):
                assigned.add(target.attr)
    return assigned


def _missing(fields: set[str], covered: set[str], exceptions: dict[str, str]) -> list[str]:
    return sorted(fields - covered - exceptions.keys())


# --------------------------------------------------------------------------- #
# `Employee` — `PostgresEmployeeRepository.save()` / `mappers.employee_from_row`
# --------------------------------------------------------------------------- #

#: Sahə → SƏBƏB. Hər giriş TƏSDİQLƏNİB (kodda oxunub, TƏXMİN edilməyib).
EMPLOYEE_SAVE_EXCEPTIONS: dict[str, str] = {
    "username": (
        "`save()` başlığı: giriş identifikatorunun dəyişməsi AYRICA, "
        "audit-lənən əməliyyatdır (`rename_username()`) — adi `save()` "
        "onu sükutla sıfırlamamalıdır."
    ),
    "has_password": (
        "Sirr BAYRAĞI `password_hash`-in ÖZÜ ilə EYNİ qapıdadır — "
        "`update_credentials()`/`create()` yazır, adi `save()` YOX "
        "(təsadüfən şifrəni sıfırlamasın deyə, `save()` başlığı)."
    ),
    "has_pin": "Yuxarıdakı `has_password` ilə EYNİ səbəb (PIN həşi).",
    "pin_security": (
        "Kompozit dəyərdir, TƏK sütun DEYİL — 3 alt-sahəsi "
        "(`failed_attempts`/`locked_until`/`pepper_version`) `pin_failed_"
        "attempts`/`pin_locked_until`/`pepper_version` sütunlarına AYRI-AYRI "
        "yazılır (`save()`-də VAR, `_hydrate` üçün `employee_from_row`-dan "
        "SONRA `employee.pin_security.X = ...` üç sətri ilə doldurulur)."
    ),
    "referred_by_employee_id": (
        "Faza 3.5 (`entities/employee.py` şərhi): «tarixi fakt olaraq "
        "daimi qalır» — YALNIZ `create()`-də (yaranış anında) yazılır, "
        "`save()`-in `UPDATE`-i TOXUNMUR (dəyişməz sahə)."
    ),
    "id": (
        "SÜTUN ADI FƏRQLİDİR DEYİL — `save()`-in `WHERE id = %s` şərti "
        "artıq TUTULUR (regex-in özü `WHERE`-i də görür). `employee_from_"
        "row()`-da isə konstruktor arqumenti `employee_id=` adlanır, `id=` "
        "YOX — kwarg adı ilə atribut adı FƏRQLİDİR, sahə ÖZÜ HƏMİŞƏ oxunur "
        "(`row['id']`)."
    ),
    "position": (
        "SÜTUN ADI FƏRQLİDİR: entity sahəsi TAM `Position` OBYEKTİDİR, SQL "
        "sütunu isə FK-dır (`position_id`) — `save()`-də `position_id = %s` "
        "VAR (`employee.position.id` ötürülür), `employee_from_row()`-da isə "
        "`position=position` kwarg-ı BİRBAŞA uyğun gəlir (bu İSTİSNA yalnız "
        "`save()` tərəfi üçün lazımdır)."
    ),
}

#: Employee.save()-in HƏLƏ HƏLL OLUNMAMIŞ, bu qapı tərəfindən TAPILAN real
#: boşluğu — `hire_date` SÜTUNU `schema.sql:416`-da VAR, `update_employee()`
#: (`user_management.py:646`) onu HƏQİQƏTƏN dəyişdirməyə çalışır
#: (`employee.hire_date = draft.hire_date`), LAKİN `save()`-in `UPDATE`
#: siyahısında YOXDUR — HR-in "Redaktə et" formasından dəyişdirdiyi işə
#: başlama tarixi SÜKUTLA İTİR. Bu, EMPLOYEE_SAVE_EXCEPTIONS-A BİLƏ-BİLƏ
#: ƏLAVƏ EDİLMİR: səbəb "qəsdən yazılmır" DEYİL, unudulmadır — qapı bunu
#: QIRMIZI saxlamalıdır ki, `infra` düzəldənə qədər görünən qalsın.


def test_employee_save_writes_every_mutable_public_field() -> None:
    fields = _init_public_self_attributes(Employee)
    sql = inspect.getsource(PostgresEmployeeRepository.save)
    written = _sql_written_columns(sql)

    missing = _missing(fields, written, EMPLOYEE_SAVE_EXCEPTIONS)
    assert missing == [], (
        f"`Employee.__init__` bu sahələri təyin edir, lakin `PostgresEmployee"
        f"Repository.save()` YAZMIR: {missing}. Ya `save()`-ə əlavə edin, ya "
        f"da `EMPLOYEE_SAVE_EXCEPTIONS`-ə SƏBƏBİ ilə yazın (bax modul-səviyyəli şərh)."
    )


def test_employee_hydration_reads_every_public_field() -> None:
    fields = _init_public_self_attributes(Employee)
    source = inspect.getsource(mappers.employee_from_row)
    kwargs = _constructor_kwargs(source, "Employee")
    # `pin_security` konstruktor arqumenti DEYİL — `employee_from_row`-dan
    # SONRA üç ayrı `employee.pin_security.X = ...` sətri ilə doldurulur
    # (yuxarıdakı `EMPLOYEE_SAVE_EXCEPTIONS["pin_security"]`-in EYNİ izahı).
    covered = kwargs | ({"pin_security"} if "employee.pin_security." in source else set())

    missing = _missing(fields, covered, EMPLOYEE_SAVE_EXCEPTIONS)
    assert missing == [], (
        f"`Employee.__init__` bu sahələri təyin edir, lakin `employee_from_"
        f"row()` OXUMUR/DOLDURMUR: {missing}. Hidratasiyaya əlavə edin, ya "
        f"da `EMPLOYEE_SAVE_EXCEPTIONS`-ə SƏBƏBİ ilə yazın."
    )


# --------------------------------------------------------------------------- #
# `Task` — `PostgresTaskRepository.save()` / `PostgresTaskRepository._hydrate()`
# --------------------------------------------------------------------------- #

TASK_SAVE_EXCEPTIONS: dict[str, str] = {
    "evidence_urls": (
        "Ayrıca `task_evidence` CƏDVƏLİNDƏDİR, `tasks`-in sütunu DEYİL — "
        "`_save_evidence()` yazır (`save()`-in bilə-bilə YAZI-BİR-DƏFƏ "
        "yardımçısı, `save()` başlığına bax)."
    ),
    "rejection_reason": (
        "SÜTUN ADI FƏRQLİDİR (`reject_reason`, entity sahəsi `rejection_"
        "reason`) — `_sql_written_columns()`-un sadə ad-uyğunluğu bunu "
        "TUTMUR, LAKİN `save()`-in `DO UPDATE SET reject_reason = "
        "EXCLUDED.reject_reason` sətri TƏSDİQLƏNDİ, sahə YAZILIR."
    ),
    "priority": (
        "TAPINTI (bu qapı tərəfindən aşkarlanıb, HƏLƏ HƏLL OLUNMAYIB): "
        "`tasks` cədvəlində `priority` sütunu heç bir migrasiyada YOXDUR "
        "(`database/schema.sql:1017` tərifi yoxlandı) — `Task.priority` "
        "HEÇ VAXT bazaya yazılmır/oxunmur, hər hidratasiyada sükutla "
        "`NORMAL`-a düşür. `infra`-ya yönləndirilib, buradan İSTİSNA "
        "kimi YAZILIB ki, qapı bu barədə hər çağırışda XƏBƏRDARLIQ etmə (əks "
        "halda eyni köhnə tapıntı hər dəfə səs-küy yaradardı) — LAKİN qərar "
        "verilməyib, sənəd YOXDUR."
    ),
    "submitted_at": (
        "EYNİ TAPINTI (`priority` ilə) — `tasks`-də sütun YOXDUR, "
        "`_hydrate()` HƏMİŞƏ `None` yazır. `submit_evidence()`-in "
        "ÖZÜ `evidence_urls`-un mövcudluğunu status keçidi üçün YETƏRLİ "
        "sayır (bax `Task.status`), ona görə funksional ZƏRƏR görünmür, "
        "LAKİN «nə vaxt təqdim edildi?» sualı hidratasiyadan sonra İTİR."
    ),
    "cancelled_at": (
        "EYNİ TAPINTI — `tasks`-də sütun YOXDUR. `cancel()` `CANCELLED` "
        "statusuna keçirir (bu, YAZILIR), LAKİN «nə vaxt ləğv edildi?» "
        "sualının cavabı hidratasiyadan sonra İTİR."
    ),
    "requires_evidence": (
        "EYNİ TAPINTI — `tasks`-də sütun YOXDUR. Hər hidratasiyada sükutla "
        "`True`-ya düşür (`_hydrate()`) — `requires_evidence=False` ilə "
        "yaradılan öz-düzəliş sorğusu belə, bərpadan SONRA `True` kimi "
        "görünür (funksional təsiri ARAŞDIRILMAYIB, yalnız TAPINTI kimi qeyd olunur)."
    ),
}


def test_task_save_writes_every_mutable_public_field() -> None:
    fields = _init_public_self_attributes(Task)
    sql = inspect.getsource(PostgresTaskRepository.save)
    written = _sql_written_columns(sql)

    missing = _missing(fields, written, TASK_SAVE_EXCEPTIONS)
    assert missing == [], (
        f"`Task.__init__` bu sahələri təyin edir, lakin `PostgresTaskRepository"
        f".save()` YAZMIR: {missing}. Ya `save()`-ə əlavə edin, ya da "
        f"`TASK_SAVE_EXCEPTIONS`-ə SƏBƏBİ ilə yazın."
    )


def test_task_hydration_reads_every_public_field() -> None:
    fields = _init_public_self_attributes(Task)
    source = inspect.getsource(PostgresTaskRepository._hydrate)
    covered = _attr_assignment_targets(source, "task")

    missing = _missing(fields, covered, TASK_SAVE_EXCEPTIONS)
    assert missing == [], (
        f"`Task.__init__` bu sahələri təyin edir, lakin `_hydrate()` "
        f"OXUMUR/DOLDURMUR: {missing}. Hidratasiyaya əlavə edin, ya da "
        f"`TASK_SAVE_EXCEPTIONS`-ə SƏBƏBİ ilə yazın."
    )


# --------------------------------------------------------------------------- #
# Köməkçilərin ÖZLƏRİNİN qırılmadığını yoxlayan mənfi testlər — AST çıxarışı
# sükutla boş qayıtsaydı, yuxarıdakı BÜTÜN testlər YALANÇI-YAŞIL olardı.
# --------------------------------------------------------------------------- #


def test_the_extraction_helpers_actually_find_something() -> None:
    assert _init_public_self_attributes(Employee), "Employee.__init__ AST-i boş qayıtdı — qırıqdır"
    assert _init_public_self_attributes(Task), "Task.__init__ AST-i boş qayıtdı — qırıqdır"
    assert _sql_written_columns(inspect.getsource(PostgresEmployeeRepository.save)), (
        "Employee.save() SQL-indən HEÇ BİR sütun çıxarılmadı — regex qırılıb"
    )
    assert _attr_assignment_targets(inspect.getsource(PostgresTaskRepository._hydrate), "task"), (
        "Task._hydrate()-dən HEÇ BİR təyinat çıxarılmadı — AST qırılıb"
    )
