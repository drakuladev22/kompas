"""Köhnə sistemdən miqrasiya aləti — `v2backlog.md` Faza 9.3.

    "scripts/import_legacy_data.py — CSV-əsaslı, tarixi cərimə/davamiyyət
     datasını yeni tenant-a idxal edən, İSTƏYƏ-BAĞLI bir alət."

İstifadə::

    .venv/Scripts/python.exe scripts/import_legacy_data.py \
        --tenant <UUID> --attendance kohnesi_davamiyyet.csv \
        --fines kohnesi_cerimeler.csv --write

* bu bayraq YOXDURSA yalnız YOXLANIR (dry-run) — İLK işə düşmə belədir;
* yazı üçün `.env`-dəki `DATABASE_ADMIN_URL` (owner DSN) tələb olunur —
  skript TƏCHİZATÇI alətidir, müştəri quraşdırmasına DÜŞMÜR
  (`docs/build_and_release.md`, `onboard_new_tenant.py` pretsedenti);
* davamiyyət sətirləri `ON CONFLICT DO NOTHING` ilə gedir (`UNIQUE(employee_
  id, work_date)`) — yenidən icra TƏHLÜKƏSİZDİR;
* cərimələrin təbii açarı YOXDUR: yenidən icra DUPLİKAT yaradar. Skript bunu
  AÇIQ ÇAP EDİR və təsdiqsiz ikinci icra rədd edilir (`--allow-duplicates`).

CSV FORMATLARI (sütun adları MÜTLİQ, sıra əhəmiyyətsiz):

Davamiyyət (`--attendance`) — hədəf `check_in_status` enum-u ilə eyni:
    employee_id, work_date, status[, verified_at, verified_by, late_minutes]
  * employee_id  — HƏDƏF bazasındaki UUID (əvvəlcə işçilər idxal olunmalıdır)
  * work_date    — YYYY-MM-DD
  * status       — VERIFIED | PENDING_VERIFICATION | REJECTED | NOT_STARTED
  * verified_at / verified_by — status=VERIFIED olduqda MƏCBURİDÜR: DB
    `chk_attendance_verified` CHECK-i onsuz da sətri RƏDD edərdi; skript onu
    ƏVVƏLCƏDƏN tutur ki, operator yarımçıq idxal görməsin.
  * late_minutes — istəyə bağlı tam ədəd (defolt 0); >0 isə is_late qeyd olunur

Cərimələr (`--fines`) — mənbə HƏMİŞƏ `MANUAL_CAMERA`-dır:
    employee_id, store_id, fine_type_code, amount_azn, fine_date,
    photo_evidence_url, issued_by_uuid[, published_at, status]
  * fine_type_code      — hədəf bazasındaki cərimə-növ kodu
  * store_id            — cərimənin baş verdiyi mağazanın UUID-si
  * photo_evidence_url / issued_by_uuid — MƏCBURİ: `chk_fine_manual_requires_
    evidence` CHECK-i onsuz da rədd edərdi; köhnə sistem sübut linkini
    EKSPORT ETMƏLİDİR — sübutsuz tarixi cərimə UYDURMAQ olmaz.
  * published_at        — ISO vaxt (istəyə bağlı); PUBLISHED üçün defolt İNDİ
  * status              — PUBLISHED | PENDING_REVIEW (istəyə bağlı)

NİYƏ SƏRBƏST SKRİPT, USE CASE DEYİL: bir-dəfəlik köçürmədir və hədəf cədvəlləri
domen aqreqatlarının KÖHNƏ (tarixi) vəziyyətlərini bərpa edir — mövcud use
case-lər isə BUGÜNKÜ axın üçün yazılıb (`FineManagementUseCase.manual_issue`
bugünkü hadisəni audit-ləyir, keçən ilki cəriməni deyil). TIME-1 qaydası
toxunulmaz qalır: `created_at` trigger tərəfindən İDXAL ANINA möhürlənir,
tarixi vaxt yalnız BİZNES sahələrinə (`fine_date`, `published_at`,
`work_date`) yazılır.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

ADMIN_URL_ENV: Final[str] = "DATABASE_ADMIN_URL"

#: `check_in_status` enum dəyərləri (schema.sql §3) — siyahı KODDA TƏKRARLANIR,
#: çünki skript domen tiplərini yükləmir (təchizatçı maşınında venv zəmanəti
#: yoxdur). Dəyişiklik schema.sql ilə SİNXRONDUR.
ATTENDANCE_STATUSES: Final[frozenset[str]] = frozenset(
    {"VERIFIED", "PENDING_VERIFICATION", "REJECTED", "NOT_STARTED"}
)
FINE_STATUSES: Final[frozenset[str]] = frozenset({"PUBLISHED", "PENDING_REVIEW"})

ATTENDANCE_REQUIRED: Final[tuple[str, ...]] = ("employee_id", "work_date", "status")
FINES_REQUIRED: Final[tuple[str, ...]] = (
    "employee_id",
    "store_id",
    "fine_type_code",
    "amount_azn",
    "fine_date",
    "photo_evidence_url",
    "issued_by_uuid",
)


class ImportValidationError(Exception):
    """CSV-in bir sətri/sütunları yararsızdır — mesaj istifadəçiyə gedir."""


def _parse_date(raw: str, *, field: str, line_no: int) -> date:
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ImportValidationError(
            f"sətir {line_no}: «{field}» tarixi yanlışdır: {raw!r}"
        ) from exc


def _parse_datetime(raw: str, *, field: str, line_no: int) -> datetime:
    try:
        return datetime.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ImportValidationError(
            f"sətir {line_no}: «{field}» vaxtı ISO formatında deyil: {raw!r}"
        ) from exc


def _parse_amount(raw: str, *, line_no: int) -> Decimal:
    try:
        amount = Decimal(raw.strip().replace(",", "."))
    except InvalidOperation as exc:
        raise ImportValidationError(f"sətir {line_no}: məbləğ rəqəm deyil: {raw!r}") from exc
    if amount < 0:
        raise ImportValidationError(f"sətir {line_no}: məbləğ mənfi ola bilməz")
    return amount


#: UUID-nin kanonik formasının ölçüsü — sxem məhdudiyyətidir, biznes həddi deyil.
_UUID_LENGTH: Final[int] = 36
_UUID_DASHES: Final[int] = 4


def _parse_uuid(raw: str, *, field: str, line_no: int) -> str:
    cleaned = raw.strip()
    if len(cleaned) != _UUID_LENGTH or cleaned.count("-") != _UUID_DASHES:
        raise ImportValidationError(f"sətir {line_no}: «{field}» UUID deyil: {raw!r}")
    return cleaned


def _optional_int(raw: str, *, default: int = 0) -> int:
    cleaned = raw.strip()
    return int(cleaned) if cleaned else default


def validate_attendance(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Davamiyyət sətirlərini yoxlayır və INSERT parametrlərinə çevirir."""
    out: list[dict[str, Any]] = []
    for line_no, row in enumerate(rows, start=2):  # 1-ci sətir başlıqdır
        missing = [name for name in ATTENDANCE_REQUIRED if not row.get(name, "").strip()]
        if missing:
            raise ImportValidationError(
                f"sətir {line_no}: məcburi sütunlar boşdur: {', '.join(missing)}"
            )
        status = row["status"].strip().upper()
        if status not in ATTENDANCE_STATUSES:
            raise ImportValidationError(
                f"sətir {line_no}: naməlum status «{status}» "
                f"(icazəli: {', '.join(sorted(ATTENDANCE_STATUSES))})"
            )
        verified_at_raw = (row.get("verified_at") or "").strip()
        verified_by = (row.get("verified_by") or "").strip()
        if status == "VERIFIED" and (not verified_at_raw or not verified_by):
            # `chk_attendance_verified` DB-də onsuz da rədd edərdi — burada
            # tutmaq operatora SƏTİR NÖMRƏSİ ilə cavab verir.
            raise ImportValidationError(
                f"sətir {line_no}: VERIFIED sətri üçün verified_at + verified_by məcburidir"
            )
        out.append(
            {
                "employee_id": _parse_uuid(
                    row["employee_id"], field="employee_id", line_no=line_no
                ),
                "work_date": _parse_date(row["work_date"], field="work_date", line_no=line_no),
                "status": status,
                "late": _optional_int(row.get("late_minutes", "")),
                "verified_at": (
                    _parse_datetime(verified_at_raw, field="verified_at", line_no=line_no)
                    if verified_at_raw
                    else None
                ),
                "verified_by": (
                    _parse_uuid(verified_by, field="verified_by", line_no=line_no)
                    if verified_by
                    else None
                ),
                "_line": line_no,
            }
        )
    return out


def validate_fines(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line_no, row in enumerate(rows, start=2):
        missing = [name for name in FINES_REQUIRED if not row.get(name, "").strip()]
        if missing:
            raise ImportValidationError(
                f"sətir {line_no}: məcburi sütunlar boşdur: {', '.join(missing)}"
            )
        status = ((row.get("status") or "").strip().upper()) or "PUBLISHED"
        if status not in FINE_STATUSES:
            raise ImportValidationError(
                f"sətir {line_no}: naməlum status «{status}» "
                f"(icazəli: {', '.join(sorted(FINE_STATUSES))})"
            )
        published_at_raw = (row.get("published_at") or "").strip()
        out.append(
            {
                "employee_id": _parse_uuid(
                    row["employee_id"], field="employee_id", line_no=line_no
                ),
                "store_id": _parse_uuid(row["store_id"], field="store_id", line_no=line_no),
                "issued_by": _parse_uuid(
                    row["issued_by_uuid"], field="issued_by_uuid", line_no=line_no
                ),
                "fine_type_code": row["fine_type_code"].strip(),
                "amount": _parse_amount(row["amount_azn"], line_no=line_no),
                "fine_date": _parse_date(row["fine_date"], field="fine_date", line_no=line_no),
                "evidence_url": row["photo_evidence_url"].strip(),
                "status": status,
                "published_at": (
                    _parse_datetime(published_at_raw, field="published_at", line_no=line_no)
                    if published_at_raw
                    else None
                ),
                "_line": line_no,
            }
        )
    return out


def read_csv(path: Path, required_headers: tuple[str, ...]) -> list[dict[str, str]]:
    """Faylı oxuyur və başlıqları yoxlayır — `bulk_operations` naxışı.

    `csv.DictReader` ad üzrə oxuduğu üçün sütun SIRASI əhəmiyyətsizdir; əksinə,
    ƏSKİK QALAN başlıq xətası AYDIN göstərilir.
    """
    if not path.is_file():
        raise ImportValidationError(f"fayl tapılmadı: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or ())
        missing = [name for name in required_headers if name not in headers]
        if missing:
            raise ImportValidationError(
                f"{path.name}: məcburi sütunlar yoxdur: {', '.join(missing)}"
            )
        return list(reader)


def run_import(
    conn: Any,
    *,
    tenant_id: str,
    attendance: list[dict[str, Any]],
    fines: list[dict[str, Any]],
) -> tuple[int, int]:
    """Yoxlanmış sətirləri YAZIR — commit/rollback çağırandadır.

    Mağaza `employees.store_id`-dən götürülür: köhnə sistemin işçisi bugün
    həmin filialdadır. İşçi köçürülməyibsə SELECT boş qayıdar → sətir sayılmır
    və hesabatda «tapılmadı» görünür.
    """
    attendance_written = 0
    for row in attendance:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO attendance_records
                    (tenant_id, employee_id, store_id, work_date,
                     check_in_status, late_minutes, is_late,
                     verified_at, verified_by, sync_status)
                SELECT %s, %s, e.store_id, %s,
                       %s::check_in_status, %s, %s > 0,
                       %s, %s, 'SYNCED'
                  FROM employees e
                 WHERE e.tenant_id = %s AND e.id = %s
                ON CONFLICT (employee_id, work_date) DO NOTHING
                """,
                (
                    tenant_id,
                    row["employee_id"],
                    row["work_date"],
                    row["status"],
                    row["late"],
                    row["late"],
                    row["verified_at"],
                    row["verified_by"],
                    tenant_id,
                    row["employee_id"],
                ),
            )
            attendance_written += cur.rowcount

    fines_written = 0
    skipped_fines = 0
    for row in fines:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO fines
                    (tenant_id, employee_id, store_id, source, fine_type_id,
                     amount, fine_date, issued_by, photo_evidence_url,
                     status, published_at)
                SELECT %s, %s, %s, 'MANUAL_CAMERA', ft.id,
                       %s, %s, %s, %s,
                       %s::fine_status,
                       CASE WHEN %s::fine_status = 'PUBLISHED'
                            THEN COALESCE(%s, now())
                            ELSE NULL END
                  FROM fine_types ft
                 WHERE ft.tenant_id = %s AND ft.code = %s
                """,
                (
                    tenant_id,
                    row["employee_id"],
                    row["store_id"],
                    row["amount"],
                    row["fine_date"],
                    row["issued_by"],
                    row["evidence_url"],
                    row["status"],
                    row["status"],
                    row["published_at"],
                    tenant_id,
                    row["fine_type_code"],
                ),
            )
            # FK yoxdur (növ kodu sərbəst mətndir) — səssizcə itirmək
            # "idxal oldu" görüntüsü verərdi; açıq hesabat düzgündür.
            if cur.rowcount == 0:
                skipped_fines += 1
                print(
                    f"  ⚠ sətir {row['_line']}: cərimə növü "
                    f"«{row['fine_type_code']}» və ya işçi/mağaza tapılmadı — ötürülüb",
                    file=sys.stderr,
                )
            else:
                fines_written += cur.rowcount
    if skipped_fines:
        print(f"CƏMİ {skipped_fines} cərimə sətiri uyğunlaşmadı (yuxarıda).", file=sys.stderr)
    return attendance_written, fines_written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KompasOS legacy CSV idxal aləti (Faza 9.3)")
    parser.add_argument("--tenant", required=True, help="Hədəf kirayəçinin UUID-si")
    parser.add_argument("--attendance", type=Path, default=None, help="Davamiyyət CSV")
    parser.add_argument("--fines", type=Path, default=None, help="Cərimələr CSV")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Yaz (bu bayraq YOXDURSA yalnız yoxlanılır — dry-run)",
    )
    parser.add_argument(
        "--allow-duplicates",
        action="store_true",
        help="Cərimələr üçün duplikat-xəbərdarlığını keç (yenidən icra üçün)",
    )
    args = parser.parse_args(argv)

    if args.attendance is None and args.fines is None:
        parser.error("ən azı --attendance və ya --fines verilməlidir")

    attendance_rows: list[dict[str, Any]] = []
    fines_rows: list[dict[str, Any]] = []
    try:
        if args.attendance is not None:
            attendance_rows = validate_attendance(read_csv(args.attendance, ATTENDANCE_REQUIRED))
        if args.fines is not None:
            fines_rows = validate_fines(read_csv(args.fines, FINES_REQUIRED))
    except ImportValidationError as exc:
        print(f"YOXLAMA XƏTASI: {exc}", file=sys.stderr)
        return 2

    print(f"Davamiyyət sətirləri: {len(attendance_rows)} · Cərimə sətirləri: {len(fines_rows)}")

    if not args.write:
        print("DRY-RUN: heç nə yazılmadı. Yazmaq üçün --write əlavə edin.")
        return 0

    url = os.environ.get(ADMIN_URL_ENV, "").strip()
    if not url:
        print(f"XƏTA: .env-də {ADMIN_URL_ENV} yoxdur.", file=sys.stderr)
        return 3
    if fines_rows and not args.allow_duplicates:
        answer = (
            input(
                f"{len(fines_rows)} cərimə yazılacaq. Bu alət yenidən icrada DUPLİKAT "
                "yaradır (cərimənin təbii açarı yoxdur). Davam edilsin? [bəli/xeyr]: "
            )
            .strip()
            .lower()
        )
        if answer not in {"b", "beli", "bəli", "y", "yes"}:
            print("Ləğv edildi — heç nə yazılmadı.")
            return 4

    import psycopg

    conn = psycopg.connect(url, row_factory=psycopg.rows.dict_row)
    try:
        written_attendance, written_fines = run_import(
            conn,
            tenant_id=args.tenant.strip(),
            attendance=attendance_rows,
            fines=fines_rows,
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"XƏTA — geri qaytarıldı: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] Yazıldı → davamiyyət: {written_attendance}, cərimə: {written_fines}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
