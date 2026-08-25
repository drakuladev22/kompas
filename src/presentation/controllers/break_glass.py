"""Break-glass fövqəladə girişin YAZI yolu — `v2backlog.md` Faza 5.4.

`controllers/transfer_requests.py` İLƏ EYNİ NAXIŞ (bax həmin faylın başlığı):
ekran HƏM oxuyur, HƏM yazır — hər əməliyyatdan sonra bölmələr yenidən oxunur
və bu dövrə `populate()`-ın tək çağırışından uzun yaşayır (CLAUDE.md §6).

SESSİYA SAXLANILMIR: hər əməliyyat üçün yeni sessiya açılır və commit edilir.
Panel saatlarla açıq qala bilər; uzun-ömürlü tranzaksiya kilid saxlayardı.

──────────────────────────────────────────────────────────────────────────────
GÖRÜNÜRLÜK BAYRAQLARI NİYƏ BURADA HESABLANIR
──────────────────────────────────────────────────────────────────────────────
Menyu maddəsi üçün ehtiyat-adminlik login-də BİR dəfə oxunur (`app.py`), lakin
bölmələrin görünürlüyü HƏR yenilənmədə TƏZƏDƏN yoxlanılır — Root təyinatı
ləğv edəndə və ya flag dəyişəndə ekranı YENİDƏN AÇMADAN düzgün vəziyyətə
düşməlidir. Yoxlamanın yeganə mənbəyi use case-in ÖZ qapılarıdır: icazəsiz
oxuma cəhdi `BreakGlassPermissionError` atır və kontroller onu «bölməni
gizlət» siqnalına çevirir — GÖRÜNÜRLÜYÜ ÖZÜ QƏRARLAŞDIRMIR, use case-dən
SORUŞUR (menyu görünməsi əməliyyat icazəsi deyil, `menu.py` başlığı).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, TypeVar

from src.application.use_cases.break_glass import BreakGlassPermissionError
from src.domain.value_objects.identifiers import BreakGlassGrantId, EmployeeId
from src.shared.exceptions import KompasOSError
from src.shared.logger import LogChannel, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.domain.entities.break_glass import BreakGlassGrant, BreakGlassTrustee
    from src.domain.entities.employee import Employee
    from src.presentation.composition import ApplicationContext, Session
    from src.presentation.screens.break_glass import BreakGlassScreen

_RowT = TypeVar("_RowT")

_error_log = get_logger(__name__, channel=LogChannel.ERROR)

#: Rədd/dayandırma izahı — domendə MƏCBURİDİR (min 10 simvol,
#: `MIN_BREAK_GLASS_DECISION_REASON_LENGTH`).
_REVOKE_PROMPT = (
    "Dayandırma səbəbi (məcburi) — işçiyə göndərilən bildirişdə göstərilir "
    "və audit jurnalına düşür:"
)
_REJECT_PROMPT = (
    "Rədd səbəbi (məcburi) — istəyənə göndərilən bildirişdə göstərilir və audit jurnalına düşür:"
)

REQUEST_CONFIRMATION = "Sorğu göndərildi — ikinci-etibarlı şəxsin təsdiqi gözlənir."
DESIGNATE_CONFIRMATION = "İşçi ehtiyat-admin reyestrinə əlavə olundu."
TRUSTEE_REVOKE_CONFIRMATION = "Ehtiyat-admin təyinatı ləğv edildi."

_STATUS_TEXT = {
    "PENDING_APPROVAL": "Təsdiq gözləyir",
    "ACTIVE": "Qüvvədədir",
}


class BreakGlassController:
    """«Fövqəladə Giriş» ekranının kontrolleri."""

    def __init__(self, context: ApplicationContext, actor: Employee) -> None:
        self._context = context
        self._actor = actor

    def attach(self, screen: BreakGlassScreen) -> None:
        screen.request_requested.connect(lambda reason: self._on_request(screen, reason))
        screen.approve_requested.connect(lambda gid: self._on_approve(screen, gid))
        screen.reject_requested.connect(lambda gid: self._on_reject(screen, gid))
        screen.revoke_grant_requested.connect(lambda gid: self._on_revoke_grant(screen, gid))
        screen.designate_requested.connect(
            lambda employee_id: self._on_designate(screen, employee_id)
        )
        screen.trustee_revoke_requested.connect(
            lambda employee_id: self._on_trustee_revoke(screen, employee_id)
        )
        screen.refresh_requested.connect(lambda: self.refresh(screen))
        self.refresh(screen)

    # ------------------------------ oxu yolu --------------------------------- #

    def refresh(self, screen: BreakGlassScreen, *, message: str = "") -> None:
        """Bütün bölmələri BİR sessiyada yenidən oxuyur.

        Bölmə qapıları use case-in öz istisnalarıdır: icazəsi olmayan oxuma
        `BreakGlassPermissionError` atır → bölmə GİZLƏNİR. Digər xətalar
        («bölmə xətası» banneri) ekranın `set_section_error`-una gedir —
        sağlam bölmələri gizlətmək məlumat itkisi olardı (bax `screens/base.py`
        başlığı).
        """
        try:
            with self._context.session(user_id=self._actor.id) as session:
                open_grant = session.break_glass.open_grant_for(session.tenant_id, self._actor.id)
                is_trustee = session.break_glass.is_active_trustee(
                    tenant_id=session.tenant_id, employee_id=self._actor.id
                )
                can_manage = session.break_glass.may_manage(
                    tenant_id=session.tenant_id, actor=self._actor
                )
                pending = _optional(
                    lambda: session.break_glass.pending_inbox(
                        tenant_id=session.tenant_id, actor=self._actor
                    )
                )
                active = _optional(
                    lambda: session.break_glass.active_grants(
                        tenant_id=session.tenant_id, actor=self._actor
                    )
                )
                trustee_list = _optional(
                    lambda: session.break_glass.trustees(
                        tenant_id=session.tenant_id, actor=self._actor
                    )
                )

                screen.set_my_status(is_trustee, _to_my_status_row(open_grant))
                screen.set_request_form_visible(is_trustee)
                screen.set_pending_visible(pending is not None)
                if pending is not None:
                    screen.set_pending([_to_inbox_row(session, grant) for grant in pending])
                screen.set_active_visible(active is not None)
                if active is not None:
                    screen.set_active(
                        [_to_active_row(session, grant, can_manage) for grant in active]
                    )
                screen.set_registry(
                    [_to_trustee_row(session, t) for t in (trustee_list or [])],
                    can_manage=can_manage,
                    employees=_employee_choices(session) if can_manage else [],
                )
        except KompasOSError as error:
            screen.show_error(title="Fövqəladə giriş oxunmadı", message=error.user_message)
            return
        except Exception:
            _error_log.exception("BREAK_GLASS_SCREEN_REFRESH_FAILED")
            screen.show_error(
                title="Fövqəladə giriş oxunmadı",
                message="Məlumat oxuna bilmədi. Yenidən cəhd edin.",
            )
            return

        screen.set_summary(message)

    # ------------------------------ sorğu / qərar ---------------------------- #

    def _on_request(self, screen: BreakGlassScreen, reason: str) -> None:
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.break_glass.request_access(
                    tenant_id=session.tenant_id, actor=self._actor, reason=reason
                )
                session.commit()
        except KompasOSError as error:
            self.refresh(screen, message=error.user_message)
            return
        except Exception:
            _error_log.exception("BREAK_GLASS_REQUEST_FAILED")
            self.refresh(screen, message="Sorğu göndərilmədi. Yenidən cəhd edin.")
            return
        self.refresh(screen, message=REQUEST_CONFIRMATION)

    def _on_approve(self, screen: BreakGlassScreen, grant_id_text: str) -> None:
        grant_id = _parse_grant_id(grant_id_text)
        if grant_id is None:
            screen.show_error(title="Sorğu təsdiqlənmədi", message="Identifikator düzgün deyil.")
            return
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.break_glass.approve(
                    tenant_id=session.tenant_id, approver=self._actor, grant_id=grant_id
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(
                title="Sorğu təsdiqlənmədi",
                message=error.user_message,
                on_retry=lambda: self.refresh(screen),
            )
            return
        except Exception:
            _error_log.exception("BREAK_GLASS_APPROVE_FAILED", extra={"grant_id": grant_id_text})
            screen.show_error(title="Sorğu təsdiqlənmədi", message="Yazılmadı. Yenidən cəhd edin.")
            return
        self.refresh(screen)

    def _on_reject(self, screen: BreakGlassScreen, grant_id_text: str) -> None:
        grant_id = _parse_grant_id(grant_id_text)
        if grant_id is None:
            screen.show_error(title="Sorğu rədd edilmədi", message="Identifikator düzgün deyil.")
            return
        reason = _ask_reason(screen, _REJECT_PROMPT)
        if reason is None:
            return
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.break_glass.reject(
                    tenant_id=session.tenant_id,
                    approver=self._actor,
                    grant_id=grant_id,
                    reason=reason,
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(
                title="Sorğu rədd edilmədi",
                message=error.user_message,
                on_retry=lambda: self.refresh(screen),
            )
            return
        except Exception:
            _error_log.exception("BREAK_GLASS_REJECT_FAILED", extra={"grant_id": grant_id_text})
            screen.show_error(title="Sorğu rədd edilmədi", message="Yazılmadı. Yenidən cəhd edin.")
            return
        self.refresh(screen)

    def _on_revoke_grant(self, screen: BreakGlassScreen, grant_id_text: str) -> None:
        grant_id = _parse_grant_id(grant_id_text)
        if grant_id is None:
            screen.show_error(
                title="Səlahiyyət dayandırılmadı", message="Identifikator düzgün deyil."
            )
            return
        reason = _ask_reason(screen, _REVOKE_PROMPT)
        if reason is None:
            return
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.break_glass.revoke(
                    tenant_id=session.tenant_id,
                    actor=self._actor,
                    grant_id=grant_id,
                    reason=reason,
                )
                session.commit()
        except KompasOSError as error:
            screen.show_error(
                title="Səlahiyyət dayandırılmadı",
                message=error.user_message,
                on_retry=lambda: self.refresh(screen),
            )
            return
        except Exception:
            _error_log.exception("BREAK_GLASS_REVOKE_FAILED", extra={"grant_id": grant_id_text})
            screen.show_error(
                title="Səlahiyyət dayandırılmadı", message="Yazılmadı. Yenidən cəhd edin."
            )
            return
        self.refresh(screen)

    # ------------------------------ reyestr ---------------------------------- #

    def _on_designate(self, screen: BreakGlassScreen, employee_id_text: str) -> None:
        try:
            employee_id = EmployeeId(uuid.UUID(employee_id_text))
        except ValueError:
            screen.set_summary("Seçilmiş işçi düzgün deyil.")
            return
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.break_glass.designate_trustee(
                    tenant_id=session.tenant_id, actor=self._actor, employee_id=employee_id
                )
                session.commit()
        except KompasOSError as error:
            self.refresh(screen, message=error.user_message)
            return
        except Exception:
            _error_log.exception("BREAK_GLASS_DESIGNATE_FAILED")
            self.refresh(screen, message="Təyinat yazılmadı. Yenidən cəhd edin.")
            return
        self.refresh(screen, message=DESIGNATE_CONFIRMATION)

    def _on_trustee_revoke(self, screen: BreakGlassScreen, employee_id_text: str) -> None:
        try:
            employee_id = EmployeeId(uuid.UUID(employee_id_text))
        except ValueError:
            screen.set_summary("Seçilmiş işçi düzgün deyil.")
            return
        try:
            with self._context.session(user_id=self._actor.id) as session:
                session.break_glass.revoke_trustee(
                    tenant_id=session.tenant_id, actor=self._actor, employee_id=employee_id
                )
                session.commit()
        except KompasOSError as error:
            self.refresh(screen, message=error.user_message)
            return
        except Exception:
            _error_log.exception("BREAK_GLASS_TRUSTEE_REVOKE_FAILED")
            self.refresh(screen, message="Ləğv yazılmadı. Yenidən cəhd edin.")
            return
        self.refresh(screen, message=TRUSTEE_REVOKE_CONFIRMATION)


# --------------------------------------------------------------------------- #
# Köməkçilər
# --------------------------------------------------------------------------- #


def _optional(read: Callable[[], list[_RowT]]) -> list[_RowT] | None:
    """İcazəli oxumanın nəticəsi; `BreakGlassPermissionError` → `None` (gizlət)."""
    try:
        return read()
    except BreakGlassPermissionError:
        return None


def _to_my_status_row(grant: BreakGlassGrant | None) -> dict[str, str] | None:
    """Öz açıq sorğumun sətri — `set_my_status` açarları (maket ilə EYNİ)."""
    if grant is None:
        return None
    expires = ""
    if grant.expires_at is not None:
        expires = grant.expires_at.astimezone().strftime("%d.%m.%Y %H:%M")
    elif grant.is_pending:
        expires = grant.approval_expires_at.astimezone().strftime("%d.%m.%Y %H:%M")
    return {
        "status": _STATUS_TEXT.get(grant.status.value, grant.status.value),
        "reason": grant.reason,
        "expires": expires,
    }


def _to_inbox_row(session: Session, grant: BreakGlassGrant) -> dict[str, str]:
    """`BreakGlassGrant` → təsdiq növbəsinin gözlədiyi açarlar (maket ilə EYNİ)."""
    return {
        "id": str(grant.id),
        "requester": _employee_name(session, grant.requested_by),
        "reason": grant.reason,
        "requested": grant.requested_at.astimezone().strftime("%d.%m.%Y %H:%M"),
        "window_end": grant.approval_expires_at.astimezone().strftime("%d.%m.%Y %H:%M"),
    }


def _to_active_row(session: Session, grant: BreakGlassGrant, can_manage: bool) -> dict[str, str]:
    """ "Qüvvədə olanlar" sətri. `revokable` yalnız Root-da "1"-dir — Dayandır
    `can_manage_break_glass` tələb edir (`BreakGlassUseCase.revoke`) və
    «görmək = səlahiyyət» qaydasına görə düymə onsuz da ÇƏKİLMİR."""
    approver = _employee_name(session, grant.approved_by) if grant.approved_by is not None else "—"
    started = (
        grant.approved_at.astimezone().strftime("%d.%m.%Y %H:%M")
        if grant.approved_at is not None
        else ""
    )
    expires = (
        grant.expires_at.astimezone().strftime("%d.%m.%Y %H:%M")
        if grant.expires_at is not None
        else ""
    )
    return {
        "id": str(grant.id),
        "employee": _employee_name(session, grant.requested_by),
        "approver": approver,
        "started": started,
        "expires": expires,
        "revokable": "1" if can_manage else "0",
    }


def _to_trustee_row(session: Session, trustee: BreakGlassTrustee) -> dict[str, str]:
    """`BreakGlassTrustee` → reyestr sətri (maket ilə EYNİ açarlar)."""
    return {
        "employee_id": str(trustee.employee_id),
        "name": _employee_name(session, trustee.employee_id),
        "designated_by": _employee_name(session, trustee.designated_by),
        "designated_at": trustee.designated_at.astimezone().strftime("%d.%m.%Y %H:%M"),
    }


def _employee_name(session: Session, employee_id: EmployeeId) -> str:
    """İşçi adı — tapılmazsa ID-nin qısa forması (`transfer_requests.py` naxışı)."""
    employee = session.uow.employees.get(employee_id)
    if employee is None:
        return f"#{str(employee_id)[:8]}"
    return str(employee.full_name)


def _employee_choices(session: Session) -> list[tuple[str, str]]:
    """Aktiv işçilər — təyinat siyahısı (`_destination_choices` ilə EYNİ sorğu forması).

    Deaktiv işçi domen tərəfindən onsuz da rədd olunur (`designate_trustee`);
    siyahıda saxlamamaq isə mənasız seçim təklif etmir.
    """
    rows = session.uow.connection.execute(
        """
        SELECT id, first_name || ' ' || last_name AS full_name
          FROM employees
         WHERE tenant_id = %s AND is_active
         ORDER BY first_name, last_name
        """,
        (session.tenant_id,),
    ).fetchall()
    return [(str(row["id"]), str(row["full_name"])) for row in rows]


def _parse_grant_id(grant_id_text: str) -> BreakGlassGrantId | None:
    try:
        return BreakGlassGrantId(uuid.UUID(grant_id_text))
    except ValueError:
        return None


def _ask_reason(screen: BreakGlassScreen, prompt: str) -> str | None:
    """Səbəb dialoqu — hədd domendən gəlir, burada təkrarlanmır.

    `None` = istifadəçi imtina etdi VƏ YA qısa mətn yazdı; ikinci halda heç
    nə baş verməmiş kimi davam edilir — domen onsuz da rədd edərdi, erkən
    çıxış isə yalnız lazımsız audit sorğusunu bağlayır.
    """
    from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

    from src.domain.entities.break_glass import (  # noqa: PLC0415
        MIN_BREAK_GLASS_DECISION_REASON_LENGTH,
    )

    text, accepted = QInputDialog.getMultiLineText(screen, "Səbəb", prompt)
    cleaned = text.strip()
    if not accepted:
        return None
    return cleaned if len(cleaned) >= MIN_BREAK_GLASS_DECISION_REASON_LENGTH else None


__all__ = [
    "DESIGNATE_CONFIRMATION",
    "REQUEST_CONFIRMATION",
    "TRUSTEE_REVOKE_CONFIRMATION",
    "BreakGlassController",
]
