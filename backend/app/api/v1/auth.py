from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import CurrentUser, DbSession, client_ip
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    RefreshRequest,
    SignupRequest,
    TenantRead,
    TokenPair,
    UserRead,
)
from app.services import auth as auth_service

router = APIRouter()

ClientIP = Annotated[str | None, Depends(client_ip)]


def _user_agent(request: Request) -> str | None:
    return request.headers.get("User-Agent")


@router.post(
    "/signup",
    response_model=TokenPair,
    status_code=status.HTTP_201_CREATED,
    summary="Create a workspace and its owner account",
)
async def signup(
    payload: SignupRequest, db: DbSession, request: Request, ip: ClientIP
) -> TokenPair:
    user, _tenant = await auth_service.signup(db, payload)
    return await auth_service.issue_token_pair(
        db, user, user_agent=_user_agent(request), ip_address=ip
    )


@router.post("/login", response_model=TokenPair, summary="Exchange credentials for tokens")
async def login(
    payload: LoginRequest, db: DbSession, request: Request, ip: ClientIP
) -> TokenPair:
    user = await auth_service.authenticate(db, payload.email, payload.password)
    return await auth_service.issue_token_pair(
        db, user, user_agent=_user_agent(request), ip_address=ip
    )


@router.post("/refresh", response_model=TokenPair, summary="Rotate a refresh token")
async def refresh(
    payload: RefreshRequest, db: DbSession, request: Request, ip: ClientIP
) -> TokenPair:
    return await auth_service.rotate_refresh_token(
        db, payload.refresh_token, user_agent=_user_agent(request), ip_address=ip
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a single session",
)
async def logout(payload: RefreshRequest, db: DbSession) -> Response:
    # Unauthenticated on purpose: a client whose access token has already
    # expired must still be able to invalidate its refresh token.
    await auth_service.revoke_refresh_token(db, payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke every session for the current user",
)
async def logout_all(user: CurrentUser, db: DbSession) -> Response:
    await auth_service.revoke_all_for_user(db, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse, summary="Current user and workspace")
async def me(user: CurrentUser) -> MeResponse:
    return MeResponse(
        user=UserRead.model_validate(user),
        tenant=TenantRead.model_validate(user.tenant),
    )
