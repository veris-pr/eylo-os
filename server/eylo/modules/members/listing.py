"""Typed member collection query owned by the members domain."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from eylo.modules.members.models import MemberStatus


class MemberSortField(StrEnum):
    NAME = "name"
    EMAIL = "email"
    STATUS = "status"
    LAST_LOGIN = "last_login"
    CREATED_AT = "created_at"


class MemberSortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class MemberListQuery(BaseModel):
    """Validated filters; organization authority and pagination stay with the caller."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        validate_default=True,
        hide_input_in_errors=True,
    )

    search: str | None = None
    statuses: tuple[MemberStatus, ...] = ()
    sort_by: MemberSortField = MemberSortField.CREATED_AT
    sort_direction: MemberSortDirection = MemberSortDirection.DESC
