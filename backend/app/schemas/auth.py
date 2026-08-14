"""Pydantic request/response models for the auth endpoints."""

from pydantic import BaseModel, EmailStr


class RequestLinkRequest(BaseModel):
    email: EmailStr


class VerifyRequest(BaseModel):
    token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
