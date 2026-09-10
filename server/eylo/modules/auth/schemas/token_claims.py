"""Validated application claims for signed membership invitations and resets."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field


class AuthActionTokenKind(StrEnum):
    INVITE = "invite"
    RESET = "reset"


class InviteTokenClaims(BaseModel):
    """One organization/email invitation; signing and expiry remain JWT-owned."""

    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

    kind: Literal[AuthActionTokenKind.INVITE] = Field(alias="type")
    organization_id: UUID
    email: EmailStr
    exp: AwareDatetime

    def to_payload(self) -> dict[str, str | datetime]:
        """Keep JWT NumericDate encoding, rather than an ISO JSON datetime."""
        return {
            "type": self.kind.value,
            "organization_id": str(self.organization_id),
            "email": self.email,
            "exp": self.exp,
        }


class ResetTokenClaims(BaseModel):
    """One member reset with the complete claim set produced by our issuer."""

    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

    kind: Literal[AuthActionTokenKind.RESET] = Field(alias="type")
    member_id: UUID
    email: EmailStr
    exp: AwareDatetime

    def to_payload(self) -> dict[str, str | datetime]:
        """Project only signed action fields and preserve datetime for PyJWT."""
        return {
            "type": self.kind.value,
            "member_id": str(self.member_id),
            "email": self.email,
            "exp": self.exp,
        }
