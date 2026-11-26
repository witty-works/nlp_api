"""Managing keys the API mints for a person and, optionally, a team
(app/managed_keys.py), for clients such as the dashboard. All behind the
management password. The plain key appears only in the answers of creating
and replacing a key; ids identify keys everywhere else."""

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import managed_keys
from app.api_keys import valid_email
from app.context import AppContext
from app.dependencies import fetch_management_username, get_app_context
from app.managed_keys import KeyStorageUnavailable, ManagedKey, TooManyKeys
from app.models import ErrorMessage

router = APIRouter()

TeamId = Field(None, min_length=1, max_length=100)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateIn(_Body):
    email: str
    team_id: Optional[str] = TeamId
    name: str = Field(min_length=1, max_length=100)
    source: str = Field("api", min_length=1, max_length=30)
    expires_at: Optional[datetime] = None

    _email = field_validator("email")(lambda cls, v: valid_email(v))


class ReplaceIn(_Body):
    grace_seconds: Literal[0, 86400, 604800]


class RevokeIn(_Body):
    email: Optional[str] = None
    team_id: Optional[str] = TeamId


class MintedOut(BaseModel):
    key: str
    details: ManagedKey


class CountOut(BaseModel):
    count: int


def _mint_errors(action):
    try:
        return action()
    except (KeyStorageUnavailable, TooManyKeys) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        )


@router.post(
    "/managed_keys",
    status_code=status.HTTP_201_CREATED,
    response_model=MintedOut,
    responses={409: {"model": ErrorMessage}},
)
async def create_managed_key(
    body: CreateIn,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_management_username),
):
    """Mint a key. The answer is the only place the key ever appears."""
    key, details = _mint_errors(
        lambda: managed_keys.mint(
            context.redis,
            body.email,
            body.team_id,
            body.name,
            body.source,
            body.expires_at,
        )
    )
    return MintedOut(key=key, details=details)


@router.get("/managed_keys", response_model=list[ManagedKey])
async def list_managed_keys(
    email: Optional[str] = Query(None),
    team_id: Optional[str] = Query(None),
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_management_username),
):
    """The keys of an email, a team, or an email in a team. Never the keys
    themselves."""
    if not email and not team_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Give an email, a team_id or both",
        )
    return managed_keys.list_keys(context.redis, email, team_id)


@router.post(
    "/managed_keys/{key_id}/replace",
    status_code=status.HTTP_201_CREATED,
    response_model=MintedOut,
    responses={404: {"model": ErrorMessage}, 409: {"model": ErrorMessage}},
)
async def replace_managed_key(
    key_id: str,
    body: ReplaceIn,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_management_username),
):
    """A new key with the same email, team, name and expiry. The old one keeps
    working for `grace_seconds`, never past its own expiry."""
    try:
        key, details = _mint_errors(
            lambda: managed_keys.replace(context.redis, key_id, body.grace_seconds)
        )
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such key")
    return MintedOut(key=key, details=details)


@router.delete("/managed_keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_managed_key(
    key_id: str,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_management_username),
):
    """Revoke a key. Also 204 when it is already gone."""
    managed_keys.revoke(context.redis, key_id)


@router.post("/managed_keys/revoke", response_model=CountOut)
async def revoke_managed_keys(
    body: RevokeIn,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_management_username),
):
    """Revoke every key of an email, a team, or an email in a team."""
    if not body.email and not body.team_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Give an email, a team_id or both",
        )
    return CountOut(
        count=managed_keys.revoke_matching(context.redis, body.email, body.team_id)
    )
