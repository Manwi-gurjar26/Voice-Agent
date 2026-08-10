from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import CurrentUser, DbSession, client_ip
from app.core.errors import RateLimitError
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    ResetPasswordRequest,
    SignupRequest,
    TenantRead,
    TokenPair,
    UserRead,
)
from app.services import auth as auth_service
from app.services import rate_limit

router = APIRouter()

ClientIP = Annotated[str | None, Depends(client_ip)]

# An unauthenticated endpoint that triggers an external email send is
# exactly what this limiter (already used by the public widget API — see
# app/services/rate_limit.py) exists to protect against.
_FORGOT_PASSWORD_LIMIT = 5
_FORGOT_PASSWORD_WINDOW_SECONDS = 900


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


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password reset email",
)
async def forgot_password(payload: ForgotPasswordRequest, db: DbSession, ip: ClientIP) -> Response:
    # Same response whether or not the address exists — see
    # auth_service.request_password_reset's docstring. Rate limited before
    # that call, not after, so the limiter also protects against spamming
    # the identical-response endpoint itself, not just the ones that Send.
    result = await rate_limit.check(
        f"forgot-password:{ip or 'unknown'}",
        limit=_FORGOT_PASSWORD_LIMIT,
        window_seconds=_FORGOT_PASSWORD_WINDOW_SECONDS,
    )
    if not result.allowed:
        raise RateLimitError(
            "Too many password reset requests. Please try again later.",
            details={"retry_after": result.retry_after},
            headers={"Retry-After": str(result.retry_after)},
        )
    await auth_service.request_password_reset(db, payload.email)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Redeem a password reset token",
)
async def reset_password(payload: ResetPasswordRequest, db: DbSession) -> Response:
    await auth_service.reset_password(db, payload.token, payload.password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
