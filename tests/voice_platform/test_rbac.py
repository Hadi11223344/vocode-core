"""
GAP-06: RBAC (Role-Based Access Control) Tests
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_platform.rbac import (
    ROLE_HIERARCHY,
    _role_index,
    get_team_membership,
    has_team_permission,
    require_team_role,
)


class FakeUser:
    def __init__(self, id=1, role="user"):
        self.id = id
        self.role = role


class FakeTeamMember:
    def __init__(self, role="member"):
        self.role = role


def test_role_index_hierarchy():
    """Higher roles should have larger index values."""
    assert _role_index("analyst") < _role_index("member")
    assert _role_index("member") < _role_index("developer")
    assert _role_index("developer") < _role_index("admin")
    assert _role_index("admin") < _role_index("owner")


def test_role_index_unknown_role():
    """Unknown roles should return -1 (lowest)."""
    assert _role_index("superhero") == -1


def test_has_team_permission_true():
    """Member should pass member-level check."""
    member = FakeTeamMember(role="member")
    assert has_team_permission(member, "member") is True
    assert has_team_permission(member, "analyst") is True


def test_has_team_permission_false():
    """Member should fail developer-level check."""
    member = FakeTeamMember(role="member")
    assert has_team_permission(member, "developer") is False
    assert has_team_permission(member, "admin") is False


def test_has_team_permission_none():
    """No membership should always return False."""
    assert has_team_permission(None, "analyst") is False


@pytest.mark.asyncio
async def test_get_team_membership_found():
    """Should return membership when user belongs to team."""
    fake_member = FakeTeamMember(role="developer")

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=fake_member)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("voice_platform.rbac.async_session", return_value=mock_session):
        result = await get_team_membership(1, 10)
        assert result is fake_member
        assert result.role == "developer"


@pytest.mark.asyncio
async def test_get_team_membership_not_found():
    """Should return None when user is not in team."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("voice_platform.rbac.async_session", return_value=mock_session):
        result = await get_team_membership(1, 99)
        assert result is None


@pytest.mark.asyncio
async def test_require_team_role_superuser_bypass():
    """Admin user should bypass team role checks."""
    from unittest.mock import MagicMock
    admin_user = FakeUser(id=1, role="admin")
    dep = require_team_role("owner")

    fake_request = MagicMock()
    fake_request.headers = {}
    fake_request.query_params = {}

    result = await dep(fake_request, admin_user)
    assert result.role == "owner"
    assert result.user_id == 1


@pytest.mark.asyncio
async def test_require_team_role_missing_user():
    """Should raise 403 when user is missing (no team header)."""
    from unittest.mock import MagicMock
    user = FakeUser(id=1, role="user")
    dep = require_team_role("member")

    fake_request = MagicMock()
    fake_request.headers = {}
    fake_request.query_params = {}

    with pytest.raises(Exception) as exc_info:
        await dep(fake_request, user)
    assert "403" in str(exc_info.value) or "Missing team context" in str(exc_info.value)


@pytest.mark.asyncio
async def test_require_team_role_insufficient_role():
    """Should raise 403 when role is too low."""
    from unittest.mock import MagicMock
    member = FakeTeamMember(role="member")
    user = FakeUser(id=1, role="user")

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=member)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    dep = require_team_role("developer")
    fake_request = MagicMock()
    fake_request.headers = {"x-team-id": "42"}
    fake_request.query_params = {}

    with patch("voice_platform.rbac.async_session", return_value=mock_session):
        with pytest.raises(Exception) as exc_info:
            await dep(fake_request, user)
        assert "Requires developer role" in str(exc_info.value)


@pytest.mark.asyncio
async def test_require_team_role_sufficient_role():
    """Should allow access when role meets requirement."""
    from unittest.mock import MagicMock
    developer = FakeTeamMember(role="developer")
    user = FakeUser(id=1, role="user")

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=developer)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    dep = require_team_role("developer")
    fake_request = MagicMock()
    fake_request.headers = {"x-team-id": "42"}
    fake_request.query_params = {}

    with patch("voice_platform.rbac.async_session", return_value=mock_session):
        result = await dep(fake_request, user)
        assert result is developer
