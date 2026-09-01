"""Explicit composition of profile-owned SOR audit read contracts."""

from eylo.sor.crm.reads import CRM_READ_SPECS
from eylo.sor.knowledge.reads import KNOWLEDGE_READ_SPECS
from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.reads import SorEntityReadSpec
from eylo.sor.support.reads import SUPPORT_READ_SPECS
from eylo.sor.ticketing.reads import TICKETING_READ_SPECS

_READ_SPECS = {
    **{(SorProfile.CRM, entity): spec for entity, spec in CRM_READ_SPECS.items()},
    **{
        (SorProfile.TICKETING, entity): spec
        for entity, spec in TICKETING_READ_SPECS.items()
    },
    **{
        (SorProfile.SUPPORT, entity): spec
        for entity, spec in SUPPORT_READ_SPECS.items()
    },
    **{
        (SorProfile.KNOWLEDGE, entity): spec
        for entity, spec in KNOWLEDGE_READ_SPECS.items()
    },
}


def get_sor_read_spec(*, profile: SorProfile, entity: str) -> SorEntityReadSpec:
    """Return one executable entity contract; never infer or fall back."""
    try:
        return _READ_SPECS[(profile, entity)]
    except KeyError as error:
        raise KeyError(
            f"No executable SOR read contract for {profile.value}/{entity}."
        ) from error


__all__ = ["get_sor_read_spec"]
