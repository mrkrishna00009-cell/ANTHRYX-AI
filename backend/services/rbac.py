"""Role-based access control.

Enforced here, server-side, for every client. Hiding a control in the
Streamlit dashboard or the field PWA is presentation, not authorization:
both talk to the same API and both are checked the same way.
"""

from __future__ import annotations

from models.enums import Role

#: Roles that may read across every mine in the country.
NATIONAL_SCOPE = frozenset({Role.ADMIN, Role.DGMS_REGULATOR})

#: Roles that may read across the mines of one subsidiary.
SUBSIDIARY_SCOPE = frozenset({Role.SUBSIDIARY_HEAD}) | NATIONAL_SCOPE

#: Roles confined to a single mine.
MINE_SCOPE = frozenset(
    {Role.MINE_MANAGER, Role.MINE_SAFETY_OFFICER, Role.FIELD_INSPECTOR}
)

#: Who may verify a document or close out a corrective action. Deliberately
#: excludes the field inspector who raised it: the person who reports a
#: finding should not be the person who signs off its closure.
VERIFIERS = frozenset({Role.ADMIN, Role.MINE_MANAGER, Role.MINE_SAFETY_OFFICER})

#: Who may submit field evidence.
FIELD_SUBMITTERS = frozenset(
    {Role.FIELD_INSPECTOR, Role.MINE_SAFETY_OFFICER, Role.MINE_MANAGER, Role.ADMIN}
)

#: Who may edit the statutory rule registry. Changing what the law says is
#: an administrative act, not an operational one.
RULE_EDITORS = frozenset({Role.ADMIN, Role.DGMS_REGULATOR})


def has_role(role: Role | str, allowed: frozenset) -> bool:
    if isinstance(role, str):
        try:
            role = Role(role)
        except ValueError:
            return False
    return role in allowed


def can_access_mine(
    role: Role | str, user_mine_id, user_subsidiary_id, mine_id, mine_subsidiary_id
) -> bool:
    """Scope check. National roles see everything; others see their slice."""
    if isinstance(role, str):
        try:
            role = Role(role)
        except ValueError:
            return False
    if role in NATIONAL_SCOPE:
        return True
    if role is Role.SUBSIDIARY_HEAD:
        return (
            user_subsidiary_id is not None
            and mine_subsidiary_id is not None
            and str(user_subsidiary_id) == str(mine_subsidiary_id)
        )
    if role in MINE_SCOPE:
        return user_mine_id is not None and str(user_mine_id) == str(mine_id)
    return False
