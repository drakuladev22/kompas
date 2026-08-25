"""Webhook reyestri — `v2backlog.md` Faza 12.2 (Faza 16 tamamlaması).

──────────────────────────────────────────────────────────────────────────────
BU FAYL NİYƏ FAZA 16-DA YAZILDI
──────────────────────────────────────────────────────────────────────────────
Faza 12 sxemi (`migrations/091`) və flag-i (`migrations/093`) yaratdı, Python
tərəfini isə YAZMADI — nəticədə cədvəl və `can_manage_webhooks` bazada var
idi, lakin heç bir kod onlara toxunmurdu: flag ÖLÜ, cədvəl isə Root üçün
əlçatmaz qalırdı. Təhvil-vermə auditi (Faza 16) bunu tapdı; aşağıdakı testlər
həmin boşluğun bir daha açılmamasını təmin edir.

──────────────────────────────────────────────────────────────────────────────
NİYƏ ƏSAS DİQQƏT URL YOXLAMASINDADIR
──────────────────────────────────────────────────────────────────────────────
Reyestrin ÖZÜ sadədir (üç sahə, bir açar). Riskli hissə hədəf ünvandır:
səlahiyyətli bir əl `https://` əvəzinə `http://`, yaxud xarici domen əvəzinə
`http://192.168.1.1/` yazsa, sistem gələcəkdə şəxsi məlumatı açıq şəbəkəyə,
və ya daxili şəbəkəyə (SSRF) göndərən bir alətə çevrilər. Ona görə testlərin
çoxu məhz bu qapıya baxır.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from src.application.use_cases.webhook_registry import (
    MANAGE_WEBHOOKS_FLAG,
    WebhookAccessError,
    WebhookEndpointView,
    WebhookRegistryError,
    WebhookRegistryUseCase,
)
from src.domain.entities.employee import Employee, PermissionOverride
from src.domain.entities.position import Position
from src.domain.value_objects.authorization import PermissionEffect, RolePriority
from src.domain.value_objects.credentials import Username
from src.domain.value_objects.identifiers import EmployeeId, TenantId

NOW = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
TENANT = TenantId(uuid.uuid4())


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Audit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


class _Repository:
    """Yaddaşda saxlayan sahtə — `ON CONFLICT` davranışını da təqlid edir."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.secrets: dict[str, str] = {}

    def list_all(self, tenant_id: TenantId) -> list[WebhookEndpointView]:
        return [
            WebhookEndpointView(
                endpoint_id=row["id"],
                event_type=row["event_type"],
                target_url=row["target_url"],
                is_active=row["is_active"],
            )
            for row in self.rows
        ]

    def add(
        self,
        tenant_id: TenantId,
        *,
        event_type: str,
        target_url: str,
        secret: str,
        created_by: EmployeeId,
        at: datetime,
    ) -> WebhookEndpointView:
        for row in self.rows:
            if row["event_type"] == event_type and row["target_url"] == target_url:
                row["is_active"] = True
                self.secrets[row["id"]] = secret
                return WebhookEndpointView(
                    endpoint_id=row["id"],
                    event_type=event_type,
                    target_url=target_url,
                    is_active=True,
                )
        row = {
            "id": str(uuid.uuid4()),
            "event_type": event_type,
            "target_url": target_url,
            "is_active": True,
        }
        self.rows.append(row)
        self.secrets[row["id"]] = secret
        return WebhookEndpointView(
            endpoint_id=row["id"],
            event_type=event_type,
            target_url=target_url,
            is_active=True,
        )

    def set_active(self, tenant_id: TenantId, *, endpoint_id: str, is_active: bool) -> bool:
        for row in self.rows:
            if row["id"] == endpoint_id:
                row["is_active"] = is_active
                return True
        return False


def _employee(
    *,
    code: str = "ROOT",
    priority: RolePriority = RolePriority.ROOT,
    flags: tuple[str, ...] = (MANAGE_WEBHOOKS_FLAG,),
) -> Employee:
    employee = Employee(
        employee_id=EmployeeId(uuid.uuid4()),
        tenant_id=TENANT,
        position=Position(
            position_id=uuid.uuid4(),  # type: ignore[arg-type]
            code=code,
            name_az=code.title(),
            priority=priority,
            tenant_id=TENANT,
            is_system=True,
        ),
        first_name="Ad",
        last_name="Soyad",
        username=Username(f"u.{uuid.uuid4().hex[:8]}"),
        has_password=True,
    )
    for flag in flags:
        employee.apply_override(
            PermissionOverride(
                flag_code=flag, effect=PermissionEffect.GRANT, granted_by=employee.id
            )
        )
    return employee


def _use_case(repository: _Repository | None = None, audit: _Audit | None = None):
    return WebhookRegistryUseCase(
        repository=repository or _Repository(),
        audit=audit or _Audit(),
        clock=_Clock(),
    )


# --------------------------------------------------------------------------- #
# Səlahiyyət
# --------------------------------------------------------------------------- #


def test_root_with_the_flag_may_manage() -> None:
    assert _use_case().may_manage(_employee()) is True


def test_root_without_the_flag_may_not_manage() -> None:
    """Rol TƏK BAŞINA kifayət etmir — flag də tələb olunur (iki şərt)."""
    assert _use_case().may_manage(_employee(flags=())) is False


def test_non_root_may_not_manage_even_with_the_flag() -> None:
    """`hardlock_level = 1`-in TƏTBİQ QATINDAKI nüsxəsi (CLAUDE.md §5).

    Flag DB-də Root-dan başqasına verilə bilmir; lakin `schema.sql` ilə təmiz
    quraşdırmada miqrasiya zənciri fərqli ola bilər, ona görə tətbiq qatı da
    rolu yoxlayır. Bu test məhz həmin ikinci nüsxəni qoruyur.
    """
    ceo = _employee(code="CEO", priority=RolePriority.EXECUTIVE)
    assert _use_case().may_manage(ceo) is False


def test_registration_is_refused_for_non_root() -> None:
    repository = _Repository()
    use_case = _use_case(repository)

    with pytest.raises(WebhookAccessError):
        use_case.register(
            tenant_id=TENANT,
            actor=_employee(code="CEO", priority=RolePriority.EXECUTIVE),
            event_type="FINE.PUBLISHED",
            target_url="https://example.com/hook",
            secret="0123456789abcdef",
        )
    assert not repository.rows


def test_listing_is_refused_for_non_root() -> None:
    with pytest.raises(WebhookAccessError):
        _use_case().list_endpoints(
            tenant_id=TENANT,
            actor=_employee(code="HR_ADMIN", priority=RolePriority.OPERATIONAL),
        )


# --------------------------------------------------------------------------- #
# Hadisə tipi
# --------------------------------------------------------------------------- #


def test_event_type_is_normalised_to_upper_case() -> None:
    """DB CHECK-i `event_type = upper(event_type)` tələb edir.

    Normallaşma OLMASAYDI, kiçik hərflə yazılan ad bazada rədd olunar və
    istifadəçi səbəbini anlamazdı (bax `_normalized_event_type` başlığı).
    """
    repository = _Repository()
    view = _use_case(repository).register(
        tenant_id=TENANT,
        actor=_employee(),
        event_type="  fine.published ",
        target_url="https://example.com/hook",
        secret="0123456789abcdef",
    )
    assert view.event_type == "FINE.PUBLISHED"


@pytest.mark.parametrize(
    "event_type",
    [
        "AB",  # üç simvoldan qısa
        "FINE PUBLISHED",  # boşluq — HTTP başlığında sətir bölünməsi riski
        "FINE\nPUBLISHED",  # nəzarət simvolu
        "_FINE",  # rəqəm/hərflə başlamır
        "FINE-PUBLISHED",  # defis əlifbada yoxdur
    ],
)
def test_invalid_event_types_are_refused(event_type: str) -> None:
    repository = _Repository()
    with pytest.raises(WebhookRegistryError):
        _use_case(repository).register(
            tenant_id=TENANT,
            actor=_employee(),
            event_type=event_type,
            target_url="https://example.com/hook",
            secret="0123456789abcdef",
        )
    assert not repository.rows


# --------------------------------------------------------------------------- #
# URL qapısı (SSRF)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "target_url",
    [
        "http://example.com/hook",  # HTTPS deyil
        "ftp://example.com/hook",
        "example.com/hook",  # sxem yoxdur
        "https://localhost/hook",
        "https://127.0.0.1/hook",
        "https://10.0.0.5/hook",
        "https://192.168.1.10/hook",
        "https://169.254.169.254/latest/meta-data",  # bulud metadata xidməti
        "https://[::1]/hook",
        "https://istifadeci:parol@example.com/hook",  # kimlik URL-də
    ],
)
def test_unsafe_target_urls_are_refused(target_url: str) -> None:
    """Bu ünvanların HƏR BİRİ ayrıca bir hücum yoludur — bax modul başlığı."""
    repository = _Repository()
    with pytest.raises(WebhookRegistryError):
        _use_case(repository).register(
            tenant_id=TENANT,
            actor=_employee(),
            event_type="FINE.PUBLISHED",
            target_url=target_url,
            secret="0123456789abcdef",
        )
    assert not repository.rows


def test_public_https_target_is_accepted() -> None:
    repository = _Repository()
    view = _use_case(repository).register(
        tenant_id=TENANT,
        actor=_employee(),
        event_type="FINE.PUBLISHED",
        target_url="https://hooks.example.com/kompasos",
        secret="0123456789abcdef",
    )
    assert view.target_url == "https://hooks.example.com/kompasos"
    assert view.is_active is True


def test_short_secret_is_refused() -> None:
    """İmza açarı qısa olsa, imzanın ÖZÜ mənasız olur (brute force)."""
    repository = _Repository()
    with pytest.raises(WebhookRegistryError):
        _use_case(repository).register(
            tenant_id=TENANT,
            actor=_employee(),
            event_type="FINE.PUBLISHED",
            target_url="https://example.com/hook",
            secret="qisa",
        )
    assert not repository.rows


# --------------------------------------------------------------------------- #
# Audit və vəziyyət
# --------------------------------------------------------------------------- #


def test_registration_is_audited_without_the_secret() -> None:
    """Audit jurnalı EKRANDA oxunur — açar ora düşsəydi maskasız görünərdi."""
    audit = _Audit()
    _use_case(audit=audit).register(
        tenant_id=TENANT,
        actor=_employee(),
        event_type="FINE.PUBLISHED",
        target_url="https://example.com/hook",
        secret="cox-gizli-acar-123",
    )
    assert [record["action"] for record in audit.records] == ["WEBHOOK_ENDPOINT_REGISTERED"]
    assert "cox-gizli-acar-123" not in str(audit.records)


def test_toggle_marks_the_row_inactive_instead_of_deleting_it() -> None:
    """Silmə YOX, deaktivasiya — `catalogs.py`-ın eyni qərarı."""
    repository = _Repository()
    audit = _Audit()
    use_case = _use_case(repository, audit)
    view = use_case.register(
        tenant_id=TENANT,
        actor=_employee(),
        event_type="FINE.PUBLISHED",
        target_url="https://example.com/hook",
        secret="0123456789abcdef",
    )

    use_case.set_active(
        tenant_id=TENANT, actor=_employee(), endpoint_id=view.endpoint_id, is_active=False
    )

    assert len(repository.rows) == 1
    assert repository.rows[0]["is_active"] is False
    assert audit.records[-1]["action"] == "WEBHOOK_ENDPOINT_TOGGLED"


def test_toggling_a_missing_row_is_an_error_not_a_silent_no_op() -> None:
    """«Tapılmadı» sükutla udulsaydı, Root söndürdüyünü zənn edərdi."""
    with pytest.raises(WebhookRegistryError):
        _use_case().set_active(
            tenant_id=TENANT,
            actor=_employee(),
            endpoint_id=str(uuid.uuid4()),
            is_active=False,
        )


def test_inactive_endpoints_stay_in_the_listing() -> None:
    """Deaktivlər gizlədilsəydi, eyni URL ikinci dəfə əlavə edilməyə çalışılardı."""
    repository = _Repository()
    use_case = _use_case(repository)
    view = use_case.register(
        tenant_id=TENANT,
        actor=_employee(),
        event_type="FINE.PUBLISHED",
        target_url="https://example.com/hook",
        secret="0123456789abcdef",
    )
    use_case.set_active(
        tenant_id=TENANT, actor=_employee(), endpoint_id=view.endpoint_id, is_active=False
    )

    listed = use_case.list_endpoints(tenant_id=TENANT, actor=_employee())

    assert [(row.event_type, row.is_active) for row in listed] == [("FINE.PUBLISHED", False)]
