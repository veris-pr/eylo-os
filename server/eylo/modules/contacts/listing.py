"""Typed contact collection query owned by the contacts domain."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from eylo.modules.contacts.domain import ContactLifecycle


class ContactSortField(StrEnum):
    NAME = "name"
    PRIMARY_EMAIL = "primary_email"
    PRIMARY_PHONE = "primary_phone"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class ContactSortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class ContactListQuery(BaseModel):
    """Validated filters; organization authority and pagination stay with the caller."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        validate_default=True,
        hide_input_in_errors=True,
    )

    contact_ids: tuple[UUID, ...] = ()
    search: str | None = None
    lifecycles: tuple[ContactLifecycle, ...] = ()
    sort_by: ContactSortField = ContactSortField.UPDATED_AT
    sort_direction: ContactSortDirection = ContactSortDirection.DESC
