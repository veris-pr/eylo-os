"""Application projection from the SOR registry to its public catalog."""

from eylo.sor.runtime.registry import SorRegistry, SorVendorRegistration
from eylo.sor.shared.schemas import (
    SorAdapterCapabilityResponse,
    SorAdapterConfigurationFieldResponse,
    SorCanonicalFieldCatalogResponse,
    SorCatalogResponse,
    SorEntityCatalogResponse,
    SorInstanceOriginOptionResponse,
    SorProfileCatalogResponse,
    SorToolCatalogResponse,
    SorVendorCatalogResponse,
    SorVendorStreamResponse,
)


class SorCatalogService:
    """Expose code-owned profile facts without inventing vendor support."""

    def __init__(self, registry: SorRegistry) -> None:
        self._registry = registry

    def get_catalog(self) -> SorCatalogResponse:
        return SorCatalogResponse(
            profiles=tuple(
                SorProfileCatalogResponse(
                    profile=profile.profile,
                    label=profile.label,
                    description=profile.description,
                    entities=tuple(
                        SorEntityCatalogResponse(
                            key=entity.key,
                            label=entity.label,
                            description=entity.description,
                            fields=tuple(
                                SorCanonicalFieldCatalogResponse(
                                    key=field.key,
                                    label=field.label,
                                    description=field.description,
                                    data_type=field.data_type,
                                    writable=field.writable,
                                    required=field.required,
                                )
                                for field in entity.fields
                            ),
                        )
                        for entity in profile.entities
                    ),
                    tools=tuple(
                        SorToolCatalogResponse(
                            name=tool.name,
                            effect=tool.effect,
                            description=tool.description,
                            target_entities=tuple(sorted(tool.target_entities)),
                            entities=tuple(sorted(tool.entities)),
                        )
                        for tool in profile.tools
                    ),
                    vendors=tuple(
                        _vendor_response(vendor)
                        for vendor in self._registry.list_vendors(
                            profile=profile.profile
                        )
                    ),
                )
                for profile in self._registry.list_profiles()
            )
        )


def _vendor_response(vendor: SorVendorRegistration) -> SorVendorCatalogResponse:
    manifest = vendor.manifest
    capabilities = (
        None
        if manifest is None
        else SorAdapterCapabilityResponse(
            auth_kinds=manifest.auth_kinds,
            streams=tuple(
                SorVendorStreamResponse(
                    key=stream.key,
                    label=stream.label,
                    description=stream.description,
                    canonical_entity=stream.canonical_entity,
                    change_strategies=tuple(
                        sorted(stream.change_strategies, key=lambda item: item.value)
                    ),
                    scope_category=stream.scope_category,
                    depends_on=tuple(sorted(stream.depends_on)),
                    relationship_targets=stream.relationship_targets.to_wire(),
                )
                for stream in manifest.streams
            ),
            readable_entities=tuple(sorted(manifest.readable_entities)),
            writable_entities=tuple(sorted(manifest.writable_entities)),
            readable_tools=tuple(sorted(manifest.readable_tools)),
            writable_tools=tuple(sorted(manifest.writable_tools)),
            change_strategies=tuple(
                sorted(manifest.change_strategies, key=lambda item: item.value)
            ),
            configuration_fields=tuple(
                SorAdapterConfigurationFieldResponse(
                    key=field.key,
                    label=field.label,
                    description=field.description,
                    kind=field.kind,
                    required=field.required,
                    placeholder=field.placeholder,
                    minimum_items=field.minimum_items,
                    maximum_items=field.maximum_items,
                )
                for field in manifest.configuration_fields
            ),
            required_scopes=dict(manifest.required_scopes),
            custom_object_required_scopes=manifest.custom_object_required_scopes,
            custom_object_change_strategies=tuple(
                sorted(
                    manifest.custom_object_change_strategies,
                    key=lambda item: item.value,
                )
            ),
            tool_required_scopes=dict(manifest.tool_required_scopes),
            fixed_origin=manifest.fixed_origin,
            requires_instance_origin=manifest.requires_instance_origin,
            requires_instance_origin_input=bool(
                manifest.oauth and manifest.oauth.operator_instance_origin
            ),
            instance_origin_options=tuple(
                SorInstanceOriginOptionResponse(
                    value=option.api_origin,
                    label=option.label,
                )
                for option in (
                    manifest.oauth.instance_origin_options if manifest.oauth else ()
                )
            ),
            change_mode=manifest.change_mode,
            supports_deletions=manifest.supports_deletions,
            supports_custom_fields=manifest.supports_custom_fields,
            supports_custom_objects=manifest.supports_custom_objects,
            supports_conditional_writes=manifest.supports_conditional_writes,
            supports_history=manifest.supports_history,
            supports_comments=manifest.supports_comments,
            supports_attachments=manifest.supports_attachments,
            supports_structured_documents=manifest.supports_structured_documents,
        )
    )
    candidate = vendor.candidate
    return SorVendorCatalogResponse(
        vendor_key=candidate.vendor_key,
        display_name=candidate.display_name,
        description=candidate.description,
        status=vendor.status,
        planned_auth_kinds=candidate.planned_auth_kinds,
        requires_instance_origin=candidate.requires_instance_origin,
        setup_notes=candidate.setup_notes,
        capabilities=capabilities,
    )


__all__ = ["SorCatalogService"]
