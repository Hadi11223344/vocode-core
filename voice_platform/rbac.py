"""
Voice Platform — Role-Based Access Control (RBAC)
====================================================

GAP-06: Team-level permission enforcement.

Provides:
    - require_team_role(min_role) decorator for route-level checks
    - get_team_membership(user_id, team_id) async helper
    - get_current_team_id() FastAPI dependency (reads X-Team-ID header)
    - has_team_permission(membership, required_role) sync check

Role hierarchy (lowest to highest):
    analyst < member < developer < admin < owner
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request
from loguru import logger
from sqlalchemy import select

from voice_platform.database import TeamMember, async_session

# ── Role Hierarchy ───────────────────────────────────────────────────
# Higher index = more permissions
ROLE_HIERARCHY = ["analyst", "member", "developer", "admin", "owner"]


def _role_index(role: str) -> int:
    """Return the numeric rank of a role. Unknown roles get lowest rank."""
    try:
        return ROLE_HIERARCHY.index(role.lower())
    except ValueError:
        return -1


# ── Helpers ──────────────────────────────────────────────────────────

async def get_team_membership(user_id: int, team_id: int) -> Optional[TeamMember]:
    """Fetch a user's membership in a specific team."""
    if not team_id or not user_id:
        return None
    async with async_session() as session:
        result = await session.execute(
            select(TeamMember).where(
                TeamMember.user_id == user_id,
                TeamMember.team_id == team_id,
            )
        )
        return result.scalar_one_or_none()


def has_team_permission(membership: Optional[TeamMember], required_role: str) -> bool:
    """Check if a membership meets the minimum role requirement."""
    if not membership:
        return False
    return _role_index(str(membership.role)) >= _role_index(required_role)


# ── Decorator ────────────────────────────────────────────────────────

def require_team_role(min_role: str):
    """
    FastAPI dependency factory for team-role enforcement.

    Returns a Depends()-compatible async function that:
    1. Resolves the current user (via get_current_user)
    2. Reads team_id from the X-Team-ID header
    3. Checks the user's membership + role in that team
    4. Returns the TeamMember if authorized

    Usage:
        from voice_platform.rbac import require_team_role

        @router.post("/agents")
        async def create_agent(
            ...,
            team_member: TeamMember = Depends(require_team_role("developer")),
        ):
            # team_member is guaranteed to have at least "developer" role
            ...

    Superusers (role="admin") bypass all team checks.
    """
    if min_role not in ROLE_HIERARCHY:
        raise ValueError(f"Invalid role '{min_role}'. Must be one of: {ROLE_HIERARCHY}")

    async def _dependency(
        request: Request,
        user=Depends(_get_current_user_for_rbac),
    ) -> TeamMember:
        # Superusers bypass all checks
        if getattr(user, "role", None) == "admin":
            # Return a synthetic membership so downstream code has a consistent type
            return TeamMember(user_id=user.id, team_id=0, role="owner")

        team_id = await get_current_team_id(request)
        if not team_id:
            raise HTTPException(status_code=403, detail="Missing team context (X-Team-ID header)")

        membership = await get_team_membership(user.id, team_id)
        if not membership:
            raise HTTPException(status_code=403, detail="Not a member of this team")

        if not has_team_permission(membership, min_role):
            raise HTTPException(
                status_code=403,
                detail=f"Requires {min_role} role or higher",
            )
        return membership

    return _dependency


async def _get_current_user_for_rbac(
    request: Request,
):
    """Resolve the current user for RBAC. Imported lazily to avoid circular deps."""
    from voice_platform.middleware.auth_middleware import get_current_user as _get_user
    from voice_platform.database import get_db

    # Manually resolve the FastAPI dependencies
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    security = HTTPBearer(auto_error=False)
    credentials = await security(request)
    db_gen = get_db()
    db = await db_gen.__anext__()
    try:
        return await _get_user(credentials, db)
    finally:
        try:
            await db_gen.__anext__()
        except StopAsyncIteration:
            pass


# ── FastAPI Dependency ───────────────────────────────────────────────

async def get_current_team_id(request: Request) -> Optional[int]:
    """
    Extract team ID from request header or query param.

    Priority:
        1. X-Team-ID header
        2. ?team_id= query parameter
    """
    # Try header first
    raw = request.headers.get("x-team-id") or request.query_params.get("team_id")
    if raw:
        try:
            return int(raw)
        except ValueError:
            logger.debug(f"Invalid team_id value: {raw}")
    return None
