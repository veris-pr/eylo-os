"""Resolve and validate profile-owned Agent command payload objects."""

from __future__ import annotations

from collections.abc import Mapping

from eylo.sor.crm.contracts import CRM_COMMAND_PAYLOAD_TYPES
from eylo.sor.knowledge.contracts import KNOWLEDGE_COMMAND_PAYLOAD_TYPES
from eylo.sor.shared.contracts import SorCommandPayload, SorProfile
from eylo.sor.support.contracts import SUPPORT_COMMAND_PAYLOAD_TYPES
from eylo.sor.ticketing.contracts import TICKETING_COMMAND_PAYLOAD_TYPES

_PROFILE_COMMAND_PAYLOAD_TYPES: Mapping[
    SorProfile, Mapping[str, type[SorCommandPayload]]
] = {
    SorProfile.CRM: {name.value: model for name, model in CRM_COMMAND_PAYLOAD_TYPES.items()},
    SorProfile.TICKETING: {
        name.value: model for name, model in TICKETING_COMMAND_PAYLOAD_TYPES.items()
    },
    SorProfile.SUPPORT: {
        name.value: model for name, model in SUPPORT_COMMAND_PAYLOAD_TYPES.items()
    },
    SorProfile.KNOWLEDGE: {
        name.value: model for name, model in KNOWLEDGE_COMMAND_PAYLOAD_TYPES.items()
    },
}


def command_payload_type(
    *,
    profile: SorProfile,
    tool_name: str,
) -> type[SorCommandPayload]:
    """Return the one command payload contract owned by a profile tool."""
    try:
        return _PROFILE_COMMAND_PAYLOAD_TYPES[profile][tool_name]
    except KeyError as error:
        raise ValueError("SOR mutation tool has no command payload contract.") from error


def validate_command_payload(
    *,
    profile: SorProfile,
    tool_name: str,
    value: SorCommandPayload | Mapping[str, object],
) -> SorCommandPayload:
    """Validate untrusted tool/wire data into the exact immutable command object."""
    model = command_payload_type(profile=profile, tool_name=tool_name)
    if isinstance(value, model):
        return value
    if isinstance(value, SorCommandPayload):
        value = value.to_wire()
    if not isinstance(value, Mapping):
        raise TypeError("SOR command payload must be an object.")
    return model.model_validate(dict(value))


__all__ = ["command_payload_type", "validate_command_payload"]
