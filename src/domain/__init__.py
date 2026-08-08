"""Domen qatı — saf biznes qaydaları.

QAYDA: Bu paket `src.shared`-dan başqa HEÇ BİR daxili qatdan (application,
infrastructure, presentation) və heç bir xarici I/O kitabxanasından (DB
drayveri, HTTP, PySide6) asılı OLMAMALIDIR. Bu asılılıq istiqaməti CI-da
import-linter/ruff qaydaları ilə qorunur.

Alt-paketlər:
    entities       — kimliyi olan aqreqatlar (Employee, LeaveRequest, Fine, ...)
    value_objects  — kimliyi olmayan dəyərlər (PIN, Money, TimeWindow, ...)
    interfaces     — repository/servis portları (Protocol)
    events         — domen hadisələri
"""
