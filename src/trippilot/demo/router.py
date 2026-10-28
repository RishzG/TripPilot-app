"""Persona sign-in, mounted only when DEMO_MODE is on (D-13, D-15, D-18).

`create_app` includes this router only when `settings.demo_mode` is true, so with the flag off
the paths do not exist at all (404), rather than existing and refusing (threat T-01-02).
Switching persona is signing in as another one.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert

from trippilot.auth.deps import AppSettings, DbSession
from trippilot.auth.models import Account
from trippilot.auth.router import MeResponse, me_response
from trippilot.auth.sessions import create_session, set_session_cookie
from trippilot.demo.cast import CAST, find_persona

router = APIRouter(prefix='/api/demo', tags=['demo'])


class PersonaOut(BaseModel):
    """One persona card for the picker."""

    slug: str
    name: str
    avatar_key: str
    note: str


@router.get('/personas')
async def list_personas() -> list[PersonaOut]:
    """List the fixed cast."""
    return [
        PersonaOut(slug=p.slug, name=p.name, avatar_key=p.avatar_key, note=p.note) for p in CAST
    ]


@router.post('/personas/{slug}/session')
async def sign_in_as_persona(
    slug: str, request: Request, response: Response, db: DbSession, settings: AppSettings
) -> MeResponse:
    """Upsert the persona account, open a persona session and set the cookie."""
    persona = find_persona(slug)
    if persona is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Unknown persona')
    statement = (
        insert(Account)
        .values(
            kind='persona',
            persona_slug=persona.slug,
            display_name=persona.name,
            avatar_kind='illustrated',
            avatar_key=persona.avatar_key,
        )
        .on_conflict_do_update(
            index_elements=[Account.persona_slug],
            set_={'display_name': persona.name, 'avatar_key': persona.avatar_key},
        )
        .returning(Account)
    )
    result = await db.execute(statement, execution_options={'populate_existing': True})
    account = result.scalar_one()
    raw = await create_session(
        db, account.id, is_persona=True, user_agent=request.headers.get('user-agent')
    )
    await db.commit()
    set_session_cookie(response, raw, settings)
    return me_response(account, is_persona=True)
