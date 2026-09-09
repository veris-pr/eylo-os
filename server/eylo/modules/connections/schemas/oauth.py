"""OAuth-specific schemas for connection authorization flow."""

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

OAUTH_STATE_MAX_LENGTH = 64
OAUTH_VERIFIER_MAX_LENGTH = 128
OAUTH_REDIRECT_MAX_LENGTH = 512


class OAuthStateCreateSchema(BaseModel):
    """Schema for creating OAuth state record."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    state: str = Field(
        ...,
        min_length=1,
        max_length=OAUTH_STATE_MAX_LENGTH,
        repr=False,
        description="Unique state token for OAuth flow",
    )
    organization_id: UUID = Field(
        ..., description="Organization initiating the OAuth flow"
    )
    external_connection_id: UUID = Field(
        ..., description="Initiated external connection this OAuth flow activates"
    )
    redirect_uri: str | None = Field(
        None,
        max_length=OAUTH_REDIRECT_MAX_LENGTH,
        description="Custom redirect URI for this flow",
    )
    code_verifier: str | None = Field(
        None,
        max_length=OAUTH_VERIFIER_MAX_LENGTH,
        repr=False,
        description="PKCE code verifier retained for the token exchange",
    )
    requested_scopes: list[str] = Field(default_factory=list)
    expected_connection_revision: int | None = Field(default=None, ge=1)
    expires_at: AwareDatetime = Field(..., description="When this state token expires")
