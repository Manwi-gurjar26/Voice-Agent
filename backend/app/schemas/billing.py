from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

PaidPlan = Literal["starter", "pro", "enterprise"]


class CheckoutSessionRequest(BaseModel):
    plan: PaidPlan


class CheckoutSessionResponse(BaseModel):
    url: str


class PortalSessionResponse(BaseModel):
    url: str
