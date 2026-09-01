"""Code-owned SOR profile and executable adapter registry."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from eylo.common.http_egress import HttpEgressPolicyError, HttpOrigin
from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.crm.contracts import CrmAdapter
from eylo.sor.knowledge.contracts import KnowledgeAdapter
from eylo.sor.shared.contracts import (
    SorAdapterCapabilityManifest,
    SorAdapterContext,
    SorImplementationStatus,
    SorLifecycleAdapter,
    SorOAuthClientAuthMethod,
    SorOAuthSpec,
    SorOAuthTokenRequestFormat,
    SorProfile,
    SorProfileSpec,
    SorToolEffect,
    SorToolSpec,
    SorVendorCandidate,
    SorVendorStreamSpec,
    require_unique_names,
)
from eylo.sor.shared.dependencies import validate_stream_dependencies
from eylo.sor.support.contracts import SupportAdapter
from eylo.sor.ticketing.contracts import TicketingAdapter

SorAdapterFactory = Callable[[SorAdapterContext], SorLifecycleAdapter]

_PROFILE_ADAPTER_TYPES = {
    SorProfile.CRM: CrmAdapter,
    SorProfile.TICKETING: TicketingAdapter,
    SorProfile.SUPPORT: SupportAdapter,
    SorProfile.KNOWLEDGE: KnowledgeAdapter,
}


@dataclass(frozen=True, slots=True)
class SorVendorRegistration:
    """Catalog entry whose support status is derived from factory presence."""

    candidate: SorVendorCandidate
    status: SorImplementationStatus
    manifest: SorAdapterCapabilityManifest | None = None


@dataclass(frozen=True, slots=True)
class _ExecutableAdapter:
    manifest: SorAdapterCapabilityManifest
    factory: SorAdapterFactory


class SorRegistry:
    """Validate profiles once and resolve adapters without scanning or fallback."""

    def __init__(
        self,
        *,
        profiles: Iterable[SorProfileSpec],
        candidates: Iterable[SorVendorCandidate],
    ) -> None:
        profile_rows = tuple(profiles)
        candidate_rows = tuple(candidates)
        self._profiles = {row.profile: row for row in profile_rows}
        self._candidates = {
            (row.profile, row.vendor_key): row for row in candidate_rows
        }
        self._adapters: dict[tuple[SorProfile, str], _ExecutableAdapter] = {}
        self._validate_catalog(profile_rows, candidate_rows)

    def register_adapter(
        self,
        *,
        manifest: SorAdapterCapabilityManifest,
        factory: SorAdapterFactory,
    ) -> None:
        """Make one vendor available only with an explicit executable factory."""
        key = (manifest.profile, manifest.vendor_key)
        candidate = self._candidates.get(key)
        if candidate is None:
            raise ValueError(
                "SOR adapters require a matching code-owned vendor candidate."
            )
        if key in self._adapters:
            raise ValueError(
                f"SOR adapter already registered for {manifest.profile.value}/"
                f"{manifest.vendor_key}."
            )
        self._validate_manifest(candidate, manifest)
        self._adapters[key] = _ExecutableAdapter(manifest, factory)

    def list_profiles(self) -> tuple[SorProfileSpec, ...]:
        """Return profiles in stable product order."""
        return tuple(self._profiles.values())

    def get_profile(self, profile: SorProfile) -> SorProfileSpec:
        """Resolve one known profile or reject the programmer-owned key."""
        try:
            return self._profiles[profile]
        except KeyError as error:
            raise KeyError(f"Unknown SOR profile: {profile.value}.") from error

    def list_vendors(
        self,
        *,
        profile: SorProfile | None = None,
    ) -> tuple[SorVendorRegistration, ...]:
        """Project roadmap candidates with factory-derived support status."""
        registrations: list[SorVendorRegistration] = []
        for key, candidate in self._candidates.items():
            if profile is not None and candidate.profile is not profile:
                continue
            executable = self._adapters.get(key)
            registrations.append(
                SorVendorRegistration(
                    candidate=candidate,
                    status=(
                        SorImplementationStatus.AVAILABLE
                        if executable is not None
                        else SorImplementationStatus.PLANNED
                    ),
                    manifest=executable.manifest if executable is not None else None,
                )
            )
        return tuple(registrations)

    def create_adapter(
        self,
        *,
        profile: SorProfile,
        vendor_key: str,
        context: SorAdapterContext,
    ) -> SorLifecycleAdapter:
        """Construct exactly the requested adapter; never infer a default."""
        if context.vendor_key != vendor_key:
            raise ValueError(
                "SOR adapter context vendor does not match its factory key."
            )
        try:
            executable = self._adapters[(profile, vendor_key)]
        except KeyError as error:
            raise KeyError(
                f"No executable SOR adapter for {profile.value}/{vendor_key}."
            ) from error
        adapter = executable.factory(context)
        expected_adapter = _PROFILE_ADAPTER_TYPES[profile]
        if not isinstance(adapter, expected_adapter):
            raise TypeError(
                f"SOR adapter for {profile.value}/{vendor_key} does not implement its "
                "profile and lifecycle contracts."
            )
        return adapter

    def get_manifest(
        self,
        *,
        profile: SorProfile,
        vendor_key: str,
    ) -> SorAdapterCapabilityManifest:
        """Return executable facts for one exact adapter or fail closed."""
        try:
            return self._adapters[(profile, vendor_key)].manifest
        except KeyError as error:
            raise KeyError(
                f"No executable SOR adapter for {profile.value}/{vendor_key}."
            ) from error

    def _validate_catalog(
        self,
        profiles: tuple[SorProfileSpec, ...],
        candidates: tuple[SorVendorCandidate, ...],
    ) -> None:
        if len(self._profiles) != len(profiles):
            raise ValueError("SOR profiles must be registered exactly once.")
        if set(self._profiles) != set(SorProfile):
            missing = sorted(
                item.value for item in set(SorProfile) - set(self._profiles)
            )
            raise ValueError(f"SOR registry is missing profiles: {missing}.")
        if len(self._candidates) != len(candidates):
            raise ValueError("SOR vendor candidates must be unique per profile.")

        all_tool_names: list[str] = []
        for profile in profiles:
            known_entities = {entity.key for entity in profile.entities}
            require_unique_names(
                sorted(known_entities),
                kind=f"{profile.profile.value} entity",
            )
            require_unique_names(
                [tool.name for tool in profile.tools],
                kind=f"{profile.profile.value} tool",
            )
            for entity in profile.entities:
                require_unique_names(
                    [field.key for field in entity.fields],
                    kind=f"{profile.profile.value}/{entity.key} canonical field",
                )
                for field in entity.fields:
                    if not field.key or "." in field.key:
                        raise ValueError(
                            "SOR canonical fields must use non-empty flat keys."
                        )
                    if not field.data_type:
                        raise ValueError(
                            "SOR canonical fields must declare a data type."
                        )
            for tool in profile.tools:
                if not tool.entities:
                    raise ValueError(
                        f"SOR tool {tool.name} must name at least one entity."
                    )
                if tool.primary_entity not in tool.entities:
                    raise ValueError(
                        f"SOR tool {tool.name} primary entity must be in its scope."
                    )
                if not tool.target_entities:
                    raise ValueError(
                        f"SOR tool {tool.name} must name at least one target entity."
                    )
                if tool.primary_entity not in tool.target_entities:
                    raise ValueError(
                        f"SOR tool {tool.name} primary entity must be a target."
                    )
                if not tool.target_entities.issubset(tool.entities):
                    raise ValueError(
                        f"SOR tool {tool.name} target entities must be in its scope."
                    )
                unknown_entities = tool.entities - known_entities
                if unknown_entities:
                    raise ValueError(
                        f"SOR tool {tool.name} references unknown entities: "
                        f"{sorted(unknown_entities)}."
                    )
            all_tool_names.extend(tool.name for tool in profile.tools)
        require_unique_names(all_tool_names, kind="Agent tool")

        for candidate in candidates:
            if candidate.profile not in self._profiles:
                raise ValueError(
                    f"SOR vendor {candidate.vendor_key} references an unknown profile."
                )
            if (
                not candidate.vendor_key
                or candidate.vendor_key != candidate.vendor_key.lower()
            ):
                raise ValueError(
                    "SOR vendor keys must be non-empty lowercase identifiers."
                )
            if not candidate.planned_auth_kinds:
                raise ValueError(
                    f"SOR vendor {candidate.vendor_key} must publish planned auth kinds."
                )
            if any(not note.strip() for note in candidate.setup_notes):
                raise ValueError(
                    f"SOR vendor {candidate.vendor_key} setup notes cannot be blank."
                )

    def _validate_manifest(
        self,
        candidate: SorVendorCandidate,
        manifest: SorAdapterCapabilityManifest,
    ) -> None:
        profile = self._profiles[manifest.profile]
        entities_by_key = {entity.key: entity for entity in profile.entities}
        known_entities = set(entities_by_key)
        profile_tools = {tool.name: tool for tool in profile.tools}
        advertised_entities = manifest.readable_entities | manifest.writable_entities
        unknown = advertised_entities - known_entities
        if unknown:
            raise ValueError(
                f"SOR adapter {manifest.vendor_key} advertises unknown entities: "
                f"{sorted(unknown)}."
            )
        if not manifest.readable_entities:
            raise ValueError("An executable SOR adapter must read at least one entity.")
        if not manifest.streams:
            raise ValueError(
                "An executable SOR adapter must declare selectable streams."
            )
        stream_keys = [stream.key for stream in manifest.streams]
        require_unique_names(stream_keys, kind="vendor stream")
        stream_key_set = frozenset(stream_keys)
        validate_stream_dependencies(
            {stream.key: stream.depends_on for stream in manifest.streams}
        )
        stream_entities = {stream.canonical_entity for stream in manifest.streams}
        if stream_entities != manifest.readable_entities:
            raise ValueError(
                "Readable SOR entities must exactly match the adapter's streams."
            )
        for stream in manifest.streams:
            if not stream.key or len(stream.key) > 160:
                raise ValueError(
                    "SOR vendor stream keys must contain 1 to 160 characters."
                )
            if not stream.change_strategies:
                raise ValueError(
                    f"SOR vendor stream {stream.key} must declare a change strategy."
                )
            if not stream.change_strategies.issubset(manifest.change_strategies):
                raise ValueError(
                    f"SOR vendor stream {stream.key} advertises an undeclared "
                    "change strategy."
                )
            if not entities_by_key[stream.canonical_entity].fields:
                raise ValueError(
                    f"SOR stream {stream.key} requires code-owned canonical fields "
                    f"for {stream.canonical_entity}."
                )
            if stream.scope_category is not None and not stream.scope_category.strip():
                raise ValueError(
                    f"SOR vendor stream {stream.key} scope category cannot be blank."
                )
            blank_relationships = {
                role
                for role, target in stream.relationship_targets.by_role.items()
                if not target.strip()
            }
            if blank_relationships:
                raise ValueError(
                    f"SOR vendor stream {stream.key} has blank relationship keys."
                )
            unknown_relationship_targets = (
                stream.relationship_targets.target_streams() - stream_key_set
            )
            if unknown_relationship_targets:
                raise ValueError(
                    f"SOR vendor stream {stream.key} relationships target unknown "
                    f"streams: {sorted(unknown_relationship_targets)}."
                )
            missing_relationship_dependencies = (
                stream.relationship_targets.target_streams() - {stream.key}
            ) - stream.depends_on
            if missing_relationship_dependencies:
                raise ValueError(
                    f"SOR vendor stream {stream.key} must depend on relationship "
                    f"targets: {sorted(missing_relationship_dependencies)}."
                )
        if not manifest.writable_entities.issubset(manifest.readable_entities):
            raise ValueError("Writable SOR entities must also be readable.")
        executable_tools = manifest.readable_tools | manifest.writable_tools
        unknown_tools = executable_tools - set(profile_tools)
        if unknown_tools:
            raise ValueError(
                f"SOR adapter {manifest.vendor_key} advertises unknown tools: "
                f"{sorted(unknown_tools)}."
            )
        if not manifest.readable_tools:
            raise ValueError("An executable SOR adapter must expose a read tool.")
        for tool_name in manifest.readable_tools:
            tool = profile_tools[tool_name]
            if tool.effect is not SorToolEffect.READ:
                raise ValueError(
                    f"SOR adapter readable tool {tool_name} is not a read."
                )
            if not tool.target_entities.intersection(manifest.readable_entities):
                raise ValueError(
                    f"SOR adapter readable tool {tool_name} has no readable target."
                )
        for tool_name in manifest.writable_tools:
            tool = profile_tools[tool_name]
            if tool.effect is not SorToolEffect.MUTATION:
                raise ValueError(
                    f"SOR adapter writable tool {tool_name} is not a mutation."
                )
            if tool.primary_entity not in manifest.writable_entities:
                raise ValueError(
                    f"SOR adapter writable tool {tool_name} has no writable primary "
                    "entity."
                )
        if bool(manifest.writable_entities) != bool(manifest.writable_tools):
            raise ValueError(
                "Writable SOR entities and executable mutation tools must be "
                "declared together."
            )
        if not manifest.auth_kinds:
            raise ValueError("An executable SOR adapter must declare auth kinds.")
        if not manifest.change_strategies:
            raise ValueError(
                "An executable SOR adapter must declare a change strategy."
            )
        unknown_scope_streams = set(manifest.required_scopes) - set(stream_keys)
        if unknown_scope_streams:
            raise ValueError(
                "SOR adapter scopes reference unknown streams: "
                f"{sorted(unknown_scope_streams)}."
            )
        unknown_scope_tools = set(manifest.tool_required_scopes) - executable_tools
        if unknown_scope_tools:
            raise ValueError(
                "SOR adapter scopes reference unavailable tools: "
                f"{sorted(unknown_scope_tools)}."
            )
        self._validate_configuration_fields(manifest)
        self._validate_custom_object_policy(manifest)
        self._validate_tool_streams(
            manifest=manifest,
            executable_tools=executable_tools,
            stream_keys=frozenset(stream_keys),
        )
        self._validate_mutation_result_streams(
            manifest=manifest,
            profile_tools=profile_tools,
            streams_by_key={stream.key: stream for stream in manifest.streams},
        )
        if not set(manifest.auth_kinds).issubset(candidate.planned_auth_kinds):
            raise ValueError(
                "Executable SOR auth kinds must be represented in catalog metadata."
            )
        if candidate.requires_instance_origin != manifest.requires_instance_origin:
            raise ValueError(
                "SOR adapter origin requirements must match its catalog candidate."
            )
        self._validate_oauth(manifest)

    @staticmethod
    def _validate_configuration_fields(
        manifest: SorAdapterCapabilityManifest,
    ) -> None:
        fields = manifest.configuration_fields
        require_unique_names(
            [field.key for field in fields],
            kind="adapter configuration field",
        )
        for field in fields:
            machine_key = field.key.replace("_", "")
            if (
                not field.key
                or len(field.key) > 64
                or field.key != field.key.lower()
                or not machine_key.isalnum()
            ):
                raise ValueError(
                    "SOR adapter configuration keys must be lowercase identifiers."
                )
            if not field.label.strip() or not field.description.strip():
                raise ValueError(
                    "SOR adapter configuration fields require labels and descriptions."
                )
            if not 0 <= field.minimum_items <= field.maximum_items <= 100:
                raise ValueError("SOR adapter configuration list bounds are invalid.")
            if field.required and field.minimum_items < 1:
                raise ValueError(
                    "Required SOR adapter configuration lists need at least one item."
                )
            if field.placeholder is not None and len(field.placeholder) > 256:
                raise ValueError("SOR adapter configuration placeholders are too long.")

    @staticmethod
    def _validate_custom_object_policy(
        manifest: SorAdapterCapabilityManifest,
    ) -> None:
        """Require executable policy whenever an adapter advertises custom objects."""
        if manifest.supports_custom_objects:
            if not manifest.custom_object_change_strategies:
                raise ValueError(
                    "Custom-object adapters must declare a change strategy."
                )
            if not manifest.custom_object_change_strategies.issubset(
                manifest.change_strategies
            ):
                raise ValueError(
                    "Custom-object change strategies must be adapter strategies."
                )
            return
        if (
            manifest.custom_object_required_scopes
            or manifest.custom_object_change_strategies
        ):
            raise ValueError(
                "Adapters without custom objects cannot declare custom-object policy."
            )

    @staticmethod
    def _validate_tool_streams(
        *,
        manifest: SorAdapterCapabilityManifest,
        executable_tools: frozenset[str],
        stream_keys: frozenset[str],
    ) -> None:
        declared_tools = set(manifest.tool_streams)
        unknown_tools = declared_tools - executable_tools
        if unknown_tools:
            raise ValueError(
                "SOR adapter tool streams reference unavailable tools: "
                f"{sorted(unknown_tools)}."
            )
        missing_tools = executable_tools - declared_tools
        if missing_tools:
            raise ValueError(
                "Every executable SOR tool must declare its vendor streams: "
                f"{sorted(missing_tools)}."
            )
        for tool_name, tool_streams in manifest.tool_streams.items():
            if not tool_streams:
                raise ValueError(
                    f"SOR adapter tool {tool_name} must target a vendor stream."
                )
            unknown_streams = set(tool_streams) - stream_keys
            if unknown_streams:
                raise ValueError(
                    f"SOR adapter tool {tool_name} references unknown streams: "
                    f"{sorted(unknown_streams)}."
                )

    @staticmethod
    def _validate_mutation_result_streams(
        *,
        manifest: SorAdapterCapabilityManifest,
        profile_tools: dict[str, SorToolSpec],
        streams_by_key: dict[str, SorVendorStreamSpec],
    ) -> None:
        """Require every vendor write to declare its read-after-write stream."""
        declared = set(manifest.mutation_result_streams)
        if declared != set(manifest.writable_tools):
            missing = set(manifest.writable_tools) - declared
            extra = declared - set(manifest.writable_tools)
            raise ValueError(
                "SOR mutation result streams must exactly match writable tools "
                f"(missing={sorted(missing)}, extra={sorted(extra)})."
            )
        for tool_name, stream_key in manifest.mutation_result_streams.items():
            stream = streams_by_key.get(stream_key)
            if stream is None:
                raise ValueError(
                    f"SOR mutation tool {tool_name} returns unknown stream {stream_key}."
                )
            tool = profile_tools[tool_name]
            if stream.canonical_entity not in tool.entities:
                raise ValueError(
                    f"SOR mutation tool {tool_name} returns an undeclared entity."
                )
            if stream.canonical_entity not in manifest.writable_entities:
                raise ValueError(
                    f"SOR mutation tool {tool_name} result is not writable."
                )

    @staticmethod
    def _validate_oauth(manifest: SorAdapterCapabilityManifest) -> None:
        oauth_enabled = ConnectionAuthKind.OAUTH2 in manifest.auth_kinds
        if oauth_enabled != (manifest.oauth is not None):
            raise ValueError(
                "OAuth-capable SOR adapters must declare exactly one OAuth contract."
            )
        oauth: SorOAuthSpec | None = manifest.oauth
        if oauth is None:
            return
        uses_tenant_endpoint = False
        for label, url, path in (
            ("authorization", oauth.authorization_url, oauth.authorization_path),
            ("token", oauth.token_url, oauth.token_path),
        ):
            if (url is None) == (path is None):
                raise ValueError(
                    f"SOR OAuth {label} endpoint must use exactly one URL or tenant path."
                )
            if url is not None:
                if not url.startswith("https://"):
                    raise ValueError(f"SOR OAuth {label} URL must use HTTPS.")
                continue
            if (
                path is None
                or not path.startswith("/")
                or path.startswith("//")
                or "://" in path
                or "?" in path
                or "#" in path
                or "\r" in path
                or "\n" in path
            ):
                raise ValueError(
                    f"SOR OAuth {label} tenant path must be an absolute clean path."
                )
            uses_tenant_endpoint = True
        if uses_tenant_endpoint and not oauth.operator_instance_origin:
            raise ValueError(
                "Tenant-origin SOR OAuth endpoints require an operator-owned origin."
            )
        if not oauth.scope_delimiter:
            raise ValueError("SOR OAuth scope delimiter cannot be empty.")
        if oauth.scope_response_delimiter == "":
            raise ValueError("SOR OAuth response scope delimiter cannot be empty.")
        if oauth.token_request_format not in set(SorOAuthTokenRequestFormat):
            raise ValueError("SOR OAuth token request format is invalid.")
        if oauth.token_client_auth_method not in set(SorOAuthClientAuthMethod):
            raise ValueError("SOR OAuth client authentication method is invalid.")
        for label, value in (
            ("authorization response type", oauth.authorization_response_type),
            ("token grant type", oauth.token_grant_type),
        ):
            if value is not None and (
                not value or len(value) > 128 or "\r" in value or "\n" in value
            ):
                raise ValueError(f"SOR OAuth {label} is invalid.")
        reserved_params = {
            "client_id",
            "redirect_uri",
            "response_type",
            "scope",
            "state",
            "code_challenge",
            "code_challenge_method",
        }
        parameter_names = [name for name, _value in oauth.authorization_params]
        if len(parameter_names) != len(set(parameter_names)):
            raise ValueError("SOR OAuth authorization parameters must be unique.")
        if any(
            not name
            or name in reserved_params
            or not value
            or "\r" in name
            or "\n" in name
            or "\r" in value
            or "\n" in value
            for name, value in oauth.authorization_params
        ):
            raise ValueError("SOR OAuth authorization parameter is invalid.")
        token_origin = bool(oauth.instance_origin_field)
        operator_origin = oauth.operator_instance_origin
        if token_origin and operator_origin:
            raise ValueError(
                "A SOR OAuth adapter must get its instance origin from exactly one "
                "authority."
            )
        if manifest.requires_instance_origin != (token_origin or operator_origin):
            raise ValueError(
                "Instance-origin SOR OAuth adapters must declare whether the token "
                "response or operator supplies the origin."
            )
        has_suffix_policy = bool(oauth.instance_host_suffixes)
        has_exact_options = bool(oauth.instance_origin_options)
        if has_suffix_policy and has_exact_options:
            raise ValueError(
                "SOR OAuth instance origins must use suffixes or exact options, not both."
            )
        if manifest.requires_instance_origin != (
            has_suffix_policy or has_exact_options
        ):
            raise ValueError(
                "Dynamic-origin SOR OAuth adapters must pin allowed instance hosts."
            )
        for suffix in oauth.instance_host_suffixes:
            if (
                not suffix
                or suffix != suffix.lower()
                or suffix.startswith(".")
                or "/" in suffix
            ):
                raise ValueError("SOR OAuth instance host suffix is invalid.")
        api_origins = [option.api_origin for option in oauth.instance_origin_options]
        if len(api_origins) != len(set(api_origins)):
            raise ValueError("SOR OAuth instance origin options must be unique.")
        for option in oauth.instance_origin_options:
            if not option.label.strip() or len(option.label) > 160:
                raise ValueError("SOR OAuth instance origin option label is invalid.")
            for label, value in (
                ("API", option.api_origin),
                ("authorization", option.authorization_origin),
            ):
                try:
                    canonical = str(HttpOrigin.parse(value))
                except HttpEgressPolicyError as error:
                    raise ValueError(
                        f"SOR OAuth {label} origin option is invalid."
                    ) from error
                if value != canonical:
                    raise ValueError(
                        f"SOR OAuth {label} origin option must be canonical."
                    )


__all__ = [
    "SorAdapterFactory",
    "SorRegistry",
    "SorVendorRegistration",
]
