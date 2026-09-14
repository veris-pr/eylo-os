"""Persistence models for the `connections` domain."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from eylo.common.models import EyloBaseModel, EyloOrganizationModel
from eylo.modules.connections.constants import APP_DB_PREFIX
from eylo.modules.contacts.models import ContactsModel
from eylo.modules.organizations.models import OrganizationModel

from .domain import (
    ConnectionAuthKind,
    ConnectionOwnerKind,
    ExternalConnectionStatus,
)


class ExternalConnectionModel(EyloOrganizationModel):
    """One encrypted external account independent of its product consumers."""

    __tablename__ = f"{APP_DB_PREFIX}external_connections"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_connection_external_connections_id_organization_id",
        ),
        UniqueConstraint(
            "id",
            "organization_id",
            "vendor_key",
            name="uq_connection_external_connections_id_org_vendor",
        ),
        ForeignKeyConstraint(
            ["contact_id", "organization_id"],
            [
                f"{ContactsModel.__tablename__}.id",
                f"{ContactsModel.__tablename__}.organization_id",
            ],
            name="fk_connection_external_connections_contact_organization",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(owner_kind = 'CONTACT' AND contact_id IS NOT NULL) OR "
            "(owner_kind = 'ORGANIZATION' AND contact_id IS NULL)",
            name="ck_connection_external_connections_exact_owner",
        ),
        CheckConstraint(
            "auth_kind IN ('no_auth', 'api_key', 'basic', 'oauth2')",
            name="ck_connection_external_connections_auth_kind",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_connection_external_connections_positive_revision",
        ),
    )

    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    owner_kind: Mapped[ConnectionOwnerKind] = mapped_column(
        ENUM(
            ConnectionOwnerKind,
            name="external_connection_owner_kind_enum",
            create_type=True,
        ),
        nullable=False,
    )
    vendor_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Code-owned vendor identity shared by product-specific links.",
    )
    auth_kind: Mapped[ConnectionAuthKind] = mapped_column(
        String(32),
        nullable=False,
    )
    instance_origin: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        doc="Normalized customer-owned HTTPS origin; null for fixed vendors.",
    )
    granted_scopes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    credentials: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Authenticated encryption envelope; never a plaintext token mapping.",
    )
    credentials_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    status: Mapped[ExternalConnectionStatus] = mapped_column(
        ENUM(
            ExternalConnectionStatus,
            name="external_connection_status_enum",
            create_type=True,
        ),
        nullable=False,
        default=ExternalConnectionStatus.INITIATED,
        server_default=ExternalConnectionStatus.INITIATED.value,
    )
    last_refresh_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    last_refresh_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    refresh_attempts: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    last_error_code: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        doc="Safe machine error code; never a provider response or credential.",
    )


class OAuthStateModel(EyloBaseModel):
    """Tracks OAuth authorization state tokens.

    This model stores temporary state tokens used during OAuth flows to prevent
    CSRF attacks and track authorization requests.
    """

    __tablename__ = f"{APP_DB_PREFIX}oauth_states"

    state: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Unique state token for OAuth flow",
    )

    external_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Initiated external connection this OAuth flow will activate.",
    )

    code_verifier: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment=(
            "PKCE code verifier held for the token exchange. Null for providers "
            "that do not use PKCE. Never leaves the server: only its S256 "
            "challenge is sent to the authorization endpoint."
        ),
    )

    requested_scopes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
        comment="Scopes requested by this exact authorization attempt.",
    )

    expected_connection_revision: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Connection revision this callback may activate or renew.",
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{OrganizationModel.__tablename__}.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Organization initiating the OAuth flow",
    )

    redirect_uri: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="Custom redirect URI for this flow",
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="When this state token expires",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["external_connection_id", "organization_id"],
            [
                f"{ExternalConnectionModel.__tablename__}.id",
                f"{ExternalConnectionModel.__tablename__}.organization_id",
            ],
            name="fk_connection_oauth_states_external_connection_organization",
            ondelete="CASCADE",
        ),
        Index("ix_oauth_states_expires_at", expires_at),
        Index("ix_oauth_states_state", state, unique=True),
        CheckConstraint(
            "expected_connection_revision IS NULL OR "
            "expected_connection_revision >= 1",
            name="ck_connection_oauth_states_expected_revision",
        ),
        CheckConstraint(
            "jsonb_typeof(requested_scopes) = 'array' "
            "AND octet_length(requested_scopes::text) <= 65536",
            name="ck_connection_oauth_states_requested_scopes",
        ),
    )

    @staticmethod
    def generate_state_token() -> str:
        """Generate a secure random state token."""
        return uuid.uuid4().hex + uuid.uuid4().hex  # 64 characters

    @staticmethod
    def calculate_expiry(minutes: int = 10) -> datetime:
        """Calculate expiry timestamp.

        Args:
            minutes: Minutes until expiration (default: 10)

        Returns:
            Datetime of expiration

        """
        return datetime.now(timezone.utc) + timedelta(minutes=minutes)

    def is_expired(self) -> bool:
        """Check if this state token has expired.

        Returns:
            True if expired, False otherwise

        """
        return datetime.now(timezone.utc) > self.expires_at
