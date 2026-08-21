"""OAuth-specific schemas for connection authorization flow."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class OAuthStateCreateSchema(BaseModel):
    """Schema for creating OAuth state record."""

    state: str = Field(..., description="Unique state token for OAuth flow")
    organization_id: UUID = Field(
        ..., description="Organization initiating the OAuth flow"
    )
    external_connection_id: UUID = Field(
        ..., description="Initiated external connection this OAuth flow activates"
    )
    redirect_uri: Optional[str] = Field(
        None, description="Custom redirect URI for this flow"
    )
    code_verifier: Optional[str] = Field(
        None, description="PKCE code verifier retained for the token exchange"
    )
    requested_scopes: list[str] = Field(default_factory=list)
    expected_connection_revision: int | None = Field(default=None, ge=1)
    expires_at: datetime = Field(..., description="When this state token expires")
