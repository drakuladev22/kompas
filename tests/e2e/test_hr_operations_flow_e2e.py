"""kompas1.md Faza 10 — genişlənmənin TAM AXINININ simulyasiyası.

──────────────────────────────────────────────────────────────────────────────
BU FAYL NİYƏ VAR — VAHİD TESTLƏR NİYƏ KİFAYƏT ETMİR
──────────────────────────────────────────────────────────────────────────────
Faza 3–8-in hər biri öz test faylı ilə qorunur və hamısı yaşıldır. Lakin
həmin testlərin heç biri BİR SUALA cavab vermir: dörd modul ARDICIL
işlədiləndə axın bütövmü? Faza 10 məhz bunu tələb edir — checklist doldur,
tapşırığın doğulduğunu gör, məzuniyyət sorğusunu təsdiqlə, aralıqlı export
çıxar, pre-export doğrulamasını gör.

Bu, inteqrasiya testi DEYİL (baza yoxdur) — AXIN testidir: hər addımın
NƏTİCƏSİ növbəti addımın GİRİŞİ olur və zəncirin qırıldığı yer dərhal
görünür.

──────────────────────────────────────────────────────────────────────────────
SAHTƏLƏR NİYƏ MÖVCUD TEST MODULLARINDAN İDXAL OLUNUR
──────────────────────────────────────────────────────────────────────────────
`test_field_reports.build()`, `test_annual_leave.build()` və
`test_export_preflight._use_case()` artıq həmin use case-lərin tam sahtə
dünyasını qurur. Onları burada TƏKRAR yazsaydıq, iki dəst sahtə yaranardı və
biri digərindən asılı olmadan köhnələrdi — yəni axın testi modulların REAL
müqaviləsini deyil, öz nüsxəsini yoxlayardı.

Nəticə olaraq hər addımın öz `TENANT`-i var (hər modul öz sabitini gətirir).
Bu, qəsdən qəbul edilən məhdudiyyətdir: axın ADDIMLARIN ZƏNCİRİNİ sübut edir,
paylaşılan baza vəziyyətini yox — sonuncunun yeri `tests/integration/`-dur və
o, `DATABASE_URL` tələb edir.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.application.use_cases.export_preflight import EmployeeRosterStatus
from src.application.use_cases.reporting import ReportRange
from src.domain.export_validation import ExportValidationCode
from src.domain.value_objects.authorization import PermissionFlag
from src.domain.value_objects.field_reports import ChecklistItemDraft
from src.domain.work_norm import (
    EmploymentWindow,
    PlannedDay,
    WorkNormRequest,
    calculate_work_norm,
)
from tests.unit import test_annual_leave as leave_mod
from tests.unit import test_export_preflight as preflight_mod
from tests.unit import test_field_reports as field_mod

pytestmark = pytest.mark.e2e

#: Aprelin ilk yarısı — kompas1.md Faza 10, bənd 3-ün konkret nümunəsi.
APRIL_FIRST_HALF = ReportRange(start=date(2026, 4, 1), end=date(2026, 4, 15))

#: İşçinin işə başladığı gün — aralığın ORTASI, yəni pro-rata halı.
MID_RANGE_HIRE = date(2026, 4, 8)

MANAGE_BALANCES = PermissionFlag(code="can_manage_leave_balances", category="hr")


def test_the_hr_operations_expansion_runs_end_to_end() -> None:
    """Dörd modul ardıcıl işləyir və hər addım növbətisini qidalandırır."""

    # ---------------------------------------------------------------- #
    # 1. #26 — Mağaza auditi: bloklayıcı bənd UĞURSUZ doldurulur
    # ---------------------------------------------------------------- #
    audit = field_mod.build()
    auditor = field_mod.make_actor()

    submission = audit.use_case.submit(
        tenant_id=field_mod.TENANT,
        actor=auditor,
        draft=field_mod.audit_draft(
            ChecklistItemDraft(
                item_text="Yanğın çıxışı sərbəstdirmi?",
                passed=False,
                is_blocking=True,
            ),
            ChecklistItemDraft(
                item_text="Kassa sənədləri qaydasındadırmı?",
                passed=True,
                is_blocking=False,
            ),
        ),
    )

    # ---------------------------------------------------------------- #
    # 2. Struktur Qərar B — tapşırıq MÖVCUD Task Engine-də doğulur
    # ---------------------------------------------------------------- #
    # `audit.tasks` — Task Engine-in repo sahtəsidir. Sətir orada varsa,
    # tapşırıq `TaskWorkflowUseCase.assign` yolundan keçib, yəni audit
    # yolu üçün İKİNCİ, zəif bir tapşırıq mexanizmi AÇILMAYIB.
    assert submission.corrective_task_ids, (
        "Uğursuz BLOKLAYICI checklist bəndi düzəliş tapşırığı YARATMADI — Struktur Qərar B pozulub."
    )
    assert set(submission.corrective_task_ids) <= set(audit.tasks.rows), (
        "Tapşırıq İD-si qaytarıldı, lakin Task Engine-in repo-suna DÜŞMƏDİ — "
        "audit yolu üçün ikinci, zəif bir tapşırıq mexanizmi açılıb."
    )

    # ---------------------------------------------------------------- #
    # 3. #28 — İllik məzuniyyət: sorğu → təsdiq → balans azalır
    # ---------------------------------------------------------------- #
    leave = leave_mod.build()
    employee = leave_mod.make_employee()
    approver = leave_mod.make_employee(flags=[MANAGE_BALANCES])

    before = leave.use_case.my_balance(tenant_id=leave_mod.TENANT, employee=employee)
    request = leave_mod.approved_request(
        leave,
        employee=employee,
        approver=approver,
        # `leave_mod.NOW` = 15 iyun 2026 — sorğu GƏLƏCƏK tarixə olmalıdır,
        # çünki use case keçmiş tarixi qəsdən rədd edir.
        start=date(2026, 7, 20),
        end=date(2026, 7, 24),
    )
    after = leave.use_case.my_balance(tenant_id=leave_mod.TENANT, employee=employee)

    assert request.status.value == "APPROVED"
    assert after.available_days < before.available_days, (
        "Təsdiqlənmiş məzuniyyət balansdan çıxılmadı — sorğu-təsdiq axını balansa bağlanmayıb."
    )

    # ---------------------------------------------------------------- #
    # 4. Faza 7 — 1–15 aprel aralığı: norma DİNAMİK və PRO-RATA
    # ---------------------------------------------------------------- #
    plan = [
        PlannedDay(day=date(2026, 4, day), is_off_day=day % 7 == 0, schedule=None)
        for day in range(1, 16)
    ]
    full_range_norm = calculate_work_norm(
        WorkNormRequest(
            start=APRIL_FIRST_HALF.start,
            end=APRIL_FIRST_HALF.end,
            plan=tuple(plan),
            employment=EmploymentWindow(),
            legal_daily_norm_hours=Decimal("8"),
        )
    )
    prorated_norm = calculate_work_norm(
        WorkNormRequest(
            start=APRIL_FIRST_HALF.start,
            end=APRIL_FIRST_HALF.end,
            plan=tuple(plan),
            # Aralığın ORTASINDA işə başlayan işçi — əl düzəlişi TƏLƏB
            # ETMƏDƏN norma proporsional kiçilməlidir (Faza 7, bənd 3).
            employment=EmploymentWindow(started_on=MID_RANGE_HIRE),
            legal_daily_norm_hours=Decimal("8"),
        )
    )

    assert APRIL_FIRST_HALF.key != "2026-04", (
        "Xüsusi aralıq tam-ay açarı ilə eyni yazılır — `exported_period` "
        "sətirləri bir-birindən ayrılmaz olardı."
    )
    assert 0 < prorated_norm.norm_work_days < full_range_norm.norm_work_days, (
        "Ayın ortasında işə başlayan işçinin norması tam aralıq norması ilə "
        "eynidir — pro-rata işləmir."
    )

    # ---------------------------------------------------------------- #
    # 5. Faza 8 — pre-export doğrulama ekranı şübhəli sətri TUTUR
    # ---------------------------------------------------------------- #
    hr = preflight_mod._hr_admin()
    suspicious = preflight_mod._row(name="Deaktiv İşçi", norm=11, actual=11, off_days=4, absences=0)
    roster = preflight_mod._Roster(
        [
            EmployeeRosterStatus(
                employee_id=suspicious.employee_id,
                # İşdən çıxıb, amma tabeldə hələ görünür — bənd A-nın
                # sadaladığı dörd şübhədən biri.
                is_active=False,
                position_code="SATICI",
                position_name="Satıcı",
            )
        ]
    )
    use_case, _, _, _ = preflight_mod._use_case(roster=roster)

    review = use_case.review(
        tenant_id=preflight_mod.TENANT,
        actor=hr,
        rows=[suspicious],
        report_range=APRIL_FIRST_HALF,
        # Bənd F — keçən EYNİ UZUNLUQDA dövrün sətirləri. Boş versəydik
        # müqayisə sükutla söndürülərdi; ekran isə "fərq yoxdur" ilə "müqayisə
        # edilmədi"-ni ayırmalıdır.
        previous_rows=[
            preflight_mod._row(
                employee_id=suspicious.employee_id,
                name="Deaktiv İşçi",
                norm=11,
                actual=11,
                off_days=4,
                absences=3,
            )
        ],
    )

    assert review.has_findings, "Pre-export doğrulaması şübhəli sətri buraxdı."
    assert ExportValidationCode.INACTIVE_IN_SHEET in {f.code for f in review.findings}
    assert review.blocking_message_az() is None, (
        "Doğrulama export-u BLOKLAMAMALIDIR — HR «Təsdiqlə və Export Et» ilə "
        "davam edə bilməlidir (bənd A)."
    )
    assert review.previous_range is not None, (
        "Dövr-üzrə müqayisə üçün əvvəlki aralıq seçilməyib (bənd F)."
    )
    assert review.previous_range.end < APRIL_FIRST_HALF.start, (
        "Müqayisə dövrü cari aralıqla ÜST-ÜSTƏ düşür — fərq öz-özü ilə müqayisə edilərdi."
    )
    assert any(delta.has_baseline for delta in review.deltas), (
        "Keçən dövrün sətirləri verildi, lakin heç bir göstərici üçün baza hesablanmadı (bənd F)."
    )
