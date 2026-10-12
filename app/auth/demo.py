"""Demo sign-in: pick a role, no password (PRD section 3).

This is not authentication. Anyone can pick any role. Stage 6 can replace it
with Microsoft Entra ID.
"""

from collections.abc import Callable

from fastapi import HTTPException, Request

COOKIE = "role"
FINANCE_CLERK, CONTRACT_MANAGER, TEAM_LEAD = "finance_clerk", "contract_manager", "team_lead"
ROLES = {
    FINANCE_CLERK: "Financieel medewerker",
    CONTRACT_MANAGER: "Contractbeheerder",
    TEAM_LEAD: "Teamleider",
}
HOME = {FINANCE_CLERK: "/queue", CONTRACT_MANAGER: "/contracts", TEAM_LEAD: "/dashboard"}


class NotSignedIn(Exception):
    """No role chosen yet. The application answers with a redirect to the picker."""


def current_role(request: Request) -> str | None:
    role = request.cookies.get(COOKIE)
    return role if role in ROLES else None


def require_role(*allowed: str) -> Callable[[Request], str]:
    """A FastAPI dependency that lets only the given roles through."""

    def dependency(request: Request) -> str:
        role = current_role(request)
        if role is None:
            raise NotSignedIn
        if role not in allowed:
            raise HTTPException(status_code=403, detail="Deze pagina is niet voor uw rol.")
        return role

    return dependency
