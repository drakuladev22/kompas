"""Tipləşdirilmiş identifikatorlar.

NİYƏ: sistemdə onlarla UUID sahəsi var (`employee_id`, `store_id`,
`operator_id`, `leave_request_id`, ...). Hamısı sadəcə `UUID` olsaydı, birini
digərinin yerinə ötürmək tip yoxlayıcısından KEÇƏRDİ — və bu, cərimə səhv
işçiyə yazılması kimi maliyyə nəticəli səhvlərə gətirib çıxarardı.

`NewType` ilə hər identifikator ayrıca tipdir: MyPy `EmployeeId` gözlənilən
yerə `StoreId` ötürülməsini XƏTA kimi göstərir, lakin işləmə zamanı əlavə
yük yoxdur (hələ də adi `UUID`-dir).
"""

from __future__ import annotations

import uuid
from typing import NewType

# --- Tenant & təşkilat ------------------------------------------------------ #
TenantId = NewType("TenantId", uuid.UUID)
StoreId = NewType("StoreId", uuid.UUID)
PositionId = NewType("PositionId", uuid.UUID)

# --- İnsanlar --------------------------------------------------------------- #
EmployeeId = NewType("EmployeeId", uuid.UUID)

# --- İş axınları ------------------------------------------------------------ #
LeaveRequestId = NewType("LeaveRequestId", uuid.UUID)
AttendanceRecordId = NewType("AttendanceRecordId", uuid.UUID)
OverrideId = NewType("OverrideId", uuid.UUID)
FineId = NewType("FineId", uuid.UUID)
FineTypeId = NewType("FineTypeId", uuid.UUID)
LeaveTypeId = NewType("LeaveTypeId", uuid.UUID)
AppealId = NewType("AppealId", uuid.UUID)
TaskId = NewType("TaskId", uuid.UUID)
ShiftSwapRequestId = NewType("ShiftSwapRequestId", uuid.UUID)
WorkModeId = NewType("WorkModeId", uuid.UUID)

# --- İnfrastruktur ---------------------------------------------------------- #
ErpServerId = NewType("ErpServerId", uuid.UUID)
SessionId = NewType("SessionId", uuid.UUID)
PluginId = NewType("PluginId", uuid.UUID)


def new_employee_id() -> EmployeeId:
    return EmployeeId(uuid.uuid4())


def new_tenant_id() -> TenantId:
    return TenantId(uuid.uuid4())


def new_store_id() -> StoreId:
    return StoreId(uuid.uuid4())


def new_position_id() -> PositionId:
    return PositionId(uuid.uuid4())


def new_leave_request_id() -> LeaveRequestId:
    return LeaveRequestId(uuid.uuid4())


def new_attendance_record_id() -> AttendanceRecordId:
    return AttendanceRecordId(uuid.uuid4())


def new_override_id() -> OverrideId:
    return OverrideId(uuid.uuid4())


def new_fine_id() -> FineId:
    return FineId(uuid.uuid4())


def new_task_id() -> TaskId:
    return TaskId(uuid.uuid4())


def new_session_id() -> SessionId:
    return SessionId(uuid.uuid4())


__all__ = [
    "AppealId",
    "AttendanceRecordId",
    "EmployeeId",
    "ErpServerId",
    "FineId",
    "FineTypeId",
    "LeaveRequestId",
    "LeaveTypeId",
    "OverrideId",
    "PluginId",
    "PositionId",
    "SessionId",
    "ShiftSwapRequestId",
    "StoreId",
    "TaskId",
    "TenantId",
    "WorkModeId",
    "new_attendance_record_id",
    "new_employee_id",
    "new_fine_id",
    "new_leave_request_id",
    "new_override_id",
    "new_position_id",
    "new_session_id",
    "new_store_id",
    "new_task_id",
    "new_tenant_id",
]
