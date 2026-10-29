"""The team-only gate for every admin route (D-37, T-01-39)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status

from trippilot.auth.deps import AppSettings, CurrentAccount, CurrentSession
from trippilot.auth.models import Account

MEMBER_KIND = 'member'


async def require_admin(
    account: CurrentAccount, session: CurrentSession, settings: AppSettings
) -> Account:
    """Return the signed-in account when it is a member on the ADMIN_EMAILS list, else raise.

    Signed out is 401 (from the session dependency). A persona session, a persona account, a
    member with no email and a member outside the list are all 403, whatever the persona's email.
    """
    allowed = {email.strip().lower() for email in settings.admin_emails}
    email = (account.email or '').strip().lower()
    if session.is_persona or account.kind != MEMBER_KIND or not email or email not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Forbidden')
    return account


AdminAccount = Annotated[Account, Depends(require_admin)]
