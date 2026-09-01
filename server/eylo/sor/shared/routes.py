"""Authenticated organization routes for SOR configuration and audit reads."""

import logging
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy import select

from eylo.common.database import start_transaction
from eylo.common.revisions import DefinitionRevisionError
from eylo.modules.agents.models import AgentsModel
from eylo.modules.auth.schemas import CurrentUserSchema
from eylo.modules.auth.services.auth_service import get_current_user
from eylo.modules.connections.domain import ExternalConnectionStatus
from eylo.sor.runtime.adapters import SorAdapterUnavailableError
from eylo.sor.runtime.agent_reads import SorAgentReadError, read_agent_view
from eylo.sor.runtime.api_key_sources import (
    create_api_key_source,
    verify_api_key_source_candidate,
)
from eylo.sor.runtime.authority import SorAuthorityError
from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.runtime.commands import cancel_active_sor_commands
from eylo.sor.runtime.deletion import delete_sor_source as delete_source_with_data
from eylo.sor.runtime.discovery import (
    SorDiscoveryResult,
    rediscover_source_schema,
    verify_and_discover_source,
)
from eylo.sor.runtime.oauth import (
    SorOAuthError,
    begin_sor_authorization,
    begin_sor_source_reauthorization,
    default_sor_callback_url,
)
from eylo.sor.runtime.read_registry import get_sor_read_spec
from eylo.sor.runtime.sync import spawn_sor_sync_run
from eylo.sor.runtime.webhook_subscriptions import (
    ensure_sor_webhook_subscription,
    remove_sor_webhook_subscription,
)
from eylo.sor.shared.catalog_service import SorCatalogService
from eylo.sor.shared.connector_services import (
    SorConnectorService,
    SorConnectorView,
)
from eylo.sor.shared.contracts import (
    SorAppWebhookState,
    SorChangeMode,
    SorFieldMappingDraft,
    SorProfile,
    SorStreamDraft,
    SorVendorOperationError,
    SorWorkState,
)
from eylo.sor.shared.custom_dataset_reads import custom_dataset_read_spec
from eylo.sor.shared.custom_datasets import (
    SorCustomDatasetService,
    SorCustomDatasetView,
)
from eylo.sor.shared.grant_services import SorSourceGrantService
from eylo.sor.shared.models import SorMappingRevisionModel
from eylo.sor.shared.onboarding import SorOnboardingService
from eylo.sor.shared.operational_reads import (
    SorOperationalReadQueryError,
    SorOperationalReadService,
)
from eylo.sor.shared.query import SorCollectionQuery, SorGridContract
from eylo.sor.shared.reads import (
    SorCollectionReadService,
    SorReadNotFoundError,
    SorReadQueryError,
    SorSourceReadService,
)
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.schemas import (
    SorAgentViewResponse,
    SorApiKeySourceCreateRequest,
    SorAppWebhookVerificationTokenResponse,
    SorAuthorizationRedirectResponse,
    SorCatalogResponse,
    SorCollectionPageResponse,
    SorConnectionVerificationResponse,
    SorConnectorAuthorizationRequest,
    SorConnectorConnectionResponse,
    SorConnectorCreateRequest,
    SorConnectorListResponse,
    SorConnectorResponse,
    SorConnectorWebhookSigningSecretUpdateRequest,
    SorCustomDatasetListResponse,
    SorCustomDatasetResponse,
    SorDiscoveryResponse,
    SorFieldMappingResponse,
    SorFilterOptionsResponse,
    SorMappingDraftRequest,
    SorMappingRevisionResponse,
    SorOAuthConfigurationResponse,
    SorRecordDetailResponse,
    SorSchemaDifferenceResponse,
    SorSchemaRevisionResponse,
    SorSourceActivationRequest,
    SorSourceActivationResponse,
    SorSourceCreateRequest,
    SorSourceGrantListResponse,
    SorSourceGrantRequest,
    SorSourceGrantResponse,
    SorSourceListResponse,
    SorSourceOperationsResponse,
    SorSourceReconnectRequest,
    SorSourceResponse,
    SorSourceSelectionUpdateRequest,
    SorStreamCreateRequest,
    SorStreamResponse,
    SorSyncGenerationResponse,
    SorSyncRunCreateRequest,
    SorSyncRunResponse,
    SorWebhookEndpointResponse,
    SorWebhookSigningSecretUpdateRequest,
)
from eylo.sor.shared.services import (
    SorConfigurationError,
    SorConflictError,
    SorMappingService,
    SorNotFoundError,
    SorSourceService,
)
from eylo.sor.shared.sync_services import SorStreamService, SorSyncRunService
from eylo.sor.shared.webhook_services import SorWebhookService
from eylo.sor.shared.webhook_urls import public_app_webhook_url

router = APIRouter(prefix="/{organization_id}/sor", tags=["systems-of-record"])
logger = logging.getLogger(__name__)


def _authorize(organization_id: UUID, current_user: CurrentUserSchema) -> None:
    if current_user.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get("/connectors", response_model=SorConnectorListResponse)
async def list_sor_connectors(
    organization_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorConnectorListResponse:
    """List safe organization-owned OAuth configurations and account state."""
    _authorize(organization_id, current_user)
    async with start_transaction(ro=True) as session:
        views = await SorConnectorService(session).list(organization_id=organization_id)
        return SorConnectorListResponse(
            items=tuple(_connector_response(view) for view in views)
        )


@router.post(
    "/connectors",
    response_model=SorConnectorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_sor_connector(
    organization_id: UUID,
    request: SorConnectorCreateRequest,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorConnectorResponse:
    """Store one encrypted OAuth app configuration for an executable adapter."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction() as session:
            view = await SorConnectorService(session).create(
                organization_id=organization_id,
                configured_by=current_user.member_id,
                name=request.name,
                profile=request.profile,
                vendor_key=request.vendor_key,
                auth_kind=request.auth_kind,
                oauth_client_id=request.oauth_client_id,
                oauth_client_secret=request.oauth_client_secret,
            )
            return _connector_response(view)
    except SorConfigurationError as error:
        raise _configuration_error(error) from None


@router.get(
    "/connectors/{connector_id}",
    response_model=SorConnectorResponse,
)
async def get_sor_connector(
    organization_id: UUID,
    connector_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorConnectorResponse:
    """Get one connector without returning encrypted or plaintext secrets."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            view = await SorConnectorService(session).get(
                organization_id=organization_id,
                connector_id=connector_id,
            )
            return _connector_response(view)
    except SorNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from None


@router.put(
    "/connectors/{connector_id}/app-webhook-signing-secret",
    response_model=SorConnectorResponse,
)
async def update_sor_connector_app_webhook_signing_secret(
    organization_id: UUID,
    connector_id: UUID,
    request: SorConnectorWebhookSigningSecretUpdateRequest,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorConnectorResponse:
    """Rotate one connector-owned app webhook secret without exposing it."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction() as session:
            view = await SorConnectorService(session).set_app_webhook_signing_secret(
                organization_id=organization_id,
                connector_id=connector_id,
                signing_secret=request.signing_secret,
                expected_secret_revision=request.expected_secret_revision,
            )
            return _connector_response(view)
    except (SorConfigurationError, SorConflictError, SorNotFoundError) as error:
        raise _configuration_error(error) from None


@router.get(
    "/connectors/{connector_id}/app-webhook-verification-token",
    response_model=SorAppWebhookVerificationTokenResponse,
)
async def get_sor_connector_app_webhook_verification_token(
    organization_id: UUID,
    connector_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorAppWebhookVerificationTokenResponse:
    """Reveal Notion's endpoint challenge to the configuring organization."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            token = await SorWebhookService(
                session
            ).reveal_notion_verification_token(
                organization_id=organization_id,
                connector_id=connector_id,
            )
    except (SorConfigurationError, SorNotFoundError) as error:
        raise _configuration_error(error) from None
    return SorAppWebhookVerificationTokenResponse(verification_token=token)


@router.post(
    "/connectors/{connector_id}/authorize",
    response_model=SorAuthorizationRedirectResponse,
)
async def authorize_sor_connector(
    organization_id: UUID,
    connector_id: UUID,
    request: SorConnectorAuthorizationRequest,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorAuthorizationRedirectResponse:
    """Begin consent for selected streams and the requested source access."""
    _authorize(organization_id, current_user)
    try:
        redirect = await begin_sor_authorization(
            organization_id=organization_id,
            connector_id=connector_id,
            selected_objects=request.selected_objects,
            access=request.access,
            instance_origin=request.instance_origin,
        )
    except SorNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from None
    except (KeyError, SorOAuthError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from None
    callback = urlsplit(redirect.callback_url)
    return SorAuthorizationRedirectResponse(
        authorization_url=redirect.authorization_url,
        callback_url=redirect.callback_url,
        callback_origin=f"{callback.scheme}://{callback.netloc}",
    )


def _read_spec(profile: SorProfile, entity: str):
    try:
        return get_sor_read_spec(profile=profile, entity=entity)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None


def _read_error(error: Exception) -> HTTPException:
    if isinstance(error, SorReadNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(error),
    )


def _configuration_error(error: Exception) -> HTTPException:
    """Translate expected, operator-safe lifecycle refusals at the HTTP edge."""
    if isinstance(error, SorNotFoundError):
        http_status = status.HTTP_404_NOT_FOUND
    elif isinstance(error, SorConflictError):
        http_status = status.HTTP_409_CONFLICT
    elif isinstance(error, TimeoutError):
        http_status = status.HTTP_504_GATEWAY_TIMEOUT
    else:
        http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=http_status, detail=str(error))


def _connector_response(view: SorConnectorView) -> SorConnectorResponse:
    connector = view.connector
    connection = view.connection
    return SorConnectorResponse(
        id=connector.id,
        organization_id=connector.organization_id,
        name=connector.name,
        profile=connector.profile,
        vendor_key=connector.vendor_key,
        auth_kind=connector.auth_kind,
        oauth_client_id=connector.oauth_client_id,
        oauth_callback_url=default_sor_callback_url(),
        has_oauth_client_secret=bool(connector.oauth_client_secret),
        app_webhook_state=_app_webhook_state(view),
        app_webhook_url=_app_webhook_url(view),
        has_app_webhook_signing_secret=connector.webhook_signing_secret is not None,
        app_webhook_signing_secret_revision=(
            connector.webhook_signing_secret_revision
        ),
        vendor_account_external_id=connector.vendor_account_external_id,
        vendor_account_display_name=connector.vendor_account_display_name,
        config_revision=connector.config_revision,
        configured_by=connector.configured_by,
        connection=(
            None
            if connection is None
            else SorConnectorConnectionResponse(
                id=connection.id,
                status=connection.status,
                instance_origin=connection.instance_origin,
                granted_scopes=tuple(connection.granted_scopes or ()),
                credentials_expires_at=connection.credentials_expires_at,
                revision=connection.revision,
            )
        ),
        created_at=connector.created_at,
        updated_at=connector.updated_at,
    )


def _app_webhook_state(view: SorConnectorView) -> SorAppWebhookState:
    connector = view.connector
    manifest = get_sor_registry().get_manifest(
        profile=connector.profile,
        vendor_key=connector.vendor_key,
    )
    if manifest.change_mode is not SorChangeMode.APP_WEBHOOK:
        return SorAppWebhookState.NOT_APPLICABLE
    if _app_webhook_url(view) is None:
        return SorAppWebhookState.PUBLIC_ENDPOINT_REQUIRED
    if (
        connector.vendor_key in {"linear", "notion"}
        and connector.webhook_signing_secret is None
    ):
        return SorAppWebhookState.SIGNING_SECRET_REQUIRED
    connection = view.connection
    if connection is None or connection.status is ExternalConnectionStatus.INITIATED:
        return SorAppWebhookState.AUTHORIZATION_REQUIRED
    if connector.webhook_authorized_connection_revision != connection.revision:
        return SorAppWebhookState.REINSTALLATION_REQUIRED
    return SorAppWebhookState.ACTIVE


def _app_webhook_url(view: SorConnectorView) -> str | None:
    connector = view.connector
    if connector.webhook_endpoint_key is None:
        return None
    try:
        return public_app_webhook_url(
            vendor_key=connector.vendor_key,
            endpoint_key=connector.webhook_endpoint_key,
        )
    except SorConfigurationError:
        return None


def _custom_dataset_response(
    view: SorCustomDatasetView,
) -> SorCustomDatasetResponse:
    dataset = view.dataset
    source = view.source
    return SorCustomDatasetResponse(
        id=dataset.id,
        source_id=source.id,
        source_name=source.name,
        profile=source.profile,
        vendor_key=source.vendor_key,
        vendor_object_key=dataset.vendor_object_key,
        label=dataset.label,
        description=dataset.description,
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
    )


def _custom_dataset_query(
    query: SorCollectionQuery,
    *,
    source_id: UUID,
) -> SorCollectionQuery:
    if query.source_ids and set(query.source_ids) != {source_id}:
        raise SorReadQueryError(
            "Custom dataset queries cannot target a different source."
        )
    return query.model_copy(update={"source_ids": (source_id,)})


async def _discovery_response(
    *,
    organization_id: UUID,
    source_id: UUID,
    result: SorDiscoveryResult,
) -> SorDiscoveryResponse:
    async with start_transaction(ro=True) as session:
        schema = await SorRepository(session).get_schema_revision(
            organization_id=organization_id,
            source_id=source_id,
            schema_revision_id=result.schema_revision_id,
        )
        if schema is None:
            raise SorConflictError("Discovered SOR schema revision is unavailable.")
        return SorDiscoveryResponse(
            verification=SorConnectionVerificationResponse.from_domain(
                result.verification
            ),
            schema_revision=SorSchemaRevisionResponse.from_model(schema),
            difference=SorSchemaDifferenceResponse.from_domain(result.difference),
        )


async def _mapping_response(
    repository: SorRepository,
    *,
    organization_id: UUID,
    source_id: UUID,
    mapping: SorMappingRevisionModel,
) -> SorMappingRevisionResponse:
    fields = await repository.list_field_mappings(
        organization_id=organization_id,
        source_id=source_id,
        mapping_revision_id=mapping.id,
    )
    return SorMappingRevisionResponse(
        id=mapping.id,
        source_id=mapping.source_id,
        revision=mapping.revision,
        source_schema_revision_id=mapping.source_schema_revision_id,
        state=mapping.state,
        projection_version=mapping.projection_version,
        created_by=mapping.created_by,
        published_by=mapping.published_by,
        published_at=mapping.published_at,
        created_at=mapping.created_at,
        fields=tuple(SorFieldMappingResponse.model_validate(field) for field in fields),
    )


def _mapping_drafts(
    request: SorMappingDraftRequest,
) -> tuple[SorFieldMappingDraft, ...]:
    return tuple(SorFieldMappingDraft(**field.model_dump()) for field in request.fields)


def _stream_drafts(
    request: SorSourceActivationRequest,
) -> tuple[SorStreamDraft, ...]:
    return tuple(SorStreamDraft(**stream.model_dump()) for stream in request.streams)


@router.get("/catalog", response_model=SorCatalogResponse)
async def get_sor_catalog(
    organization_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorCatalogResponse:
    """List profiles and factory-derived vendor implementation status."""
    _authorize(organization_id, current_user)
    return SorCatalogService(get_sor_registry()).get_catalog()


@router.get(
    "/oauth/configuration",
    response_model=SorOAuthConfigurationResponse,
)
async def get_sor_oauth_configuration(
    organization_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorOAuthConfigurationResponse:
    """Return the exact callback URI to register before entering credentials."""
    _authorize(organization_id, current_user)
    return SorOAuthConfigurationResponse(callback_url=default_sor_callback_url())


@router.get("/sources", response_model=SorSourceListResponse)
async def list_sor_sources(
    organization_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorSourceListResponse:
    """List organization-owned source headers without credential material."""
    _authorize(organization_id, current_user)
    async with start_transaction(ro=True) as session:
        return await SorSourceReadService(session).list(organization_id=organization_id)


@router.post(
    "/sources",
    response_model=SorSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_sor_source(
    organization_id: UUID,
    request: SorSourceCreateRequest,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorSourceResponse:
    """Create an unusable draft only for an executable adapter and connection."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction() as session:
            row = await SorSourceService(session).create(
                organization_id=organization_id,
                onboarding_attempt_id=request.onboarding_attempt_id,
                name=request.name,
                profile=request.profile,
                vendor_key=request.vendor_key,
                external_connection_id=request.external_connection_id,
                configuration=request.configuration,
                selected_objects=request.selected_objects,
                freshness_target_seconds=request.freshness_target_seconds,
                required_sync_interval_seconds=(
                    request.required_sync_interval_seconds
                ),
            )
            return SorSourceResponse.model_validate(row)
    except (SorNotFoundError, SorConfigurationError, SorConflictError) as error:
        raise _configuration_error(error) from None


@router.post(
    "/sources/api-key",
    response_model=SorSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key_sor_source(
    organization_id: UUID,
    request: SorApiKeySourceCreateRequest,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorSourceResponse:
    """Verify a transient API key, then atomically create its source draft."""
    _authorize(organization_id, current_user)
    try:
        candidate = await verify_api_key_source_candidate(
            organization_id=organization_id,
            profile=request.profile,
            vendor_key=request.vendor_key,
            api_key=request.api_key,
            instance_origin=request.instance_origin,
            selected_objects=request.selected_objects,
            configuration=request.configuration,
        )
        async with start_transaction() as session:
            source = await create_api_key_source(
                session,
                candidate=candidate,
                onboarding_attempt_id=request.onboarding_attempt_id,
                name=request.name,
                freshness_target_seconds=request.freshness_target_seconds,
                required_sync_interval_seconds=(request.required_sync_interval_seconds),
            )
            return SorSourceResponse.model_validate(source)
    except (
        SorConfigurationError,
        SorConflictError,
        SorVendorOperationError,
        TimeoutError,
    ) as error:
        raise _configuration_error(error) from None


@router.get("/sources/{source_id}", response_model=SorSourceResponse)
async def get_sor_source(
    organization_id: UUID,
    source_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorSourceResponse:
    """Get one exact source or preserve the cross-tenant 404 boundary."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            return await SorSourceReadService(session).get(
                organization_id=organization_id,
                source_id=source_id,
            )
    except SorReadNotFoundError as error:
        raise _read_error(error) from None


@router.post(
    "/sources/{source_id}/reauthorize",
    response_model=SorAuthorizationRedirectResponse,
)
async def reauthorize_sor_source(
    organization_id: UUID,
    source_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorAuthorizationRedirectResponse:
    """Restart OAuth for an activated source while preserving its projection."""
    _authorize(organization_id, current_user)
    try:
        redirect = await begin_sor_source_reauthorization(
            organization_id=organization_id,
            source_id=source_id,
        )
    except SorNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from None
    except (KeyError, SorOAuthError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from None
    callback = urlsplit(redirect.callback_url)
    return SorAuthorizationRedirectResponse(
        authorization_url=redirect.authorization_url,
        callback_url=redirect.callback_url,
        callback_origin=f"{callback.scheme}://{callback.netloc}",
    )


@router.get(
    "/sources/{source_id}/operations",
    response_model=SorSourceOperationsResponse,
)
async def get_sor_source_operations(
    organization_id: UUID,
    source_id: UUID,
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 1,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorSourceOperationsResponse:
    """Show recent sync DAGs and canonical relationship resolution health."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            return await SorOperationalReadService(session).source_operations(
                organization_id=organization_id,
                source_id=source_id,
                generation_cursor=cursor,
                generation_limit=limit,
            )
    except SorNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from None
    except SorOperationalReadQueryError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from None


@router.delete(
    "/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_sor_source(
    organization_id: UUID,
    source_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> Response:
    """Delete one source and its Eylo projection without changing vendor data."""
    _authorize(organization_id, current_user)
    try:
        await delete_source_with_data(
            organization_id=organization_id,
            source_id=source_id,
        )
    except SorNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/sources/{source_id}/connection",
    response_model=SorSourceResponse,
)
async def reconnect_sor_source(
    organization_id: UUID,
    source_id: UUID,
    request: SorSourceReconnectRequest,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorSourceResponse:
    """Rebind an unactivated source after a replacement connection is authorized."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction() as session:
            source = await SorSourceService(session).reconnect_before_activation(
                organization_id=organization_id,
                source_id=source_id,
                external_connection_id=request.external_connection_id,
                selected_objects=request.selected_objects,
                expected_config_revision=request.expected_config_revision,
            )
            return SorSourceResponse.model_validate(source)
    except (SorConfigurationError, SorConflictError, SorNotFoundError) as error:
        raise _configuration_error(error) from None


@router.patch(
    "/sources/{source_id}/selection",
    response_model=SorSourceResponse,
)
async def update_sor_source_selection(
    organization_id: UUID,
    source_id: UUID,
    request: SorSourceSelectionUpdateRequest,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorSourceResponse:
    """Enable standard or discovered custom objects before mapping publication."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction() as session:
            source = await SorSourceService(session).update_selection_from_discovery(
                organization_id=organization_id,
                source_id=source_id,
                selected_objects=request.selected_objects,
                expected_config_revision=request.expected_config_revision,
            )
            return SorSourceResponse.model_validate(source)
    except (SorConfigurationError, SorConflictError, SorNotFoundError) as error:
        raise _configuration_error(error) from None


@router.post(
    "/sources/{source_id}/verify",
    response_model=SorDiscoveryResponse,
)
async def verify_sor_source(
    organization_id: UUID,
    source_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorDiscoveryResponse:
    """Verify credentials and commit one complete initial schema discovery."""
    _authorize(organization_id, current_user)
    try:
        result = await verify_and_discover_source(
            organization_id=organization_id,
            source_id=source_id,
        )
        return await _discovery_response(
            organization_id=organization_id,
            source_id=source_id,
            result=result,
        )
    except (
        SorAdapterUnavailableError,
        SorConfigurationError,
        SorConflictError,
        SorNotFoundError,
        SorVendorOperationError,
        TimeoutError,
    ) as error:
        raise _configuration_error(error) from None


@router.post(
    "/sources/{source_id}/rediscover",
    response_model=SorDiscoveryResponse,
)
async def rediscover_sor_source(
    organization_id: UUID,
    source_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorDiscoveryResponse:
    """Refresh an active source schema without hiding its current projection."""
    _authorize(organization_id, current_user)
    try:
        result = await rediscover_source_schema(
            organization_id=organization_id,
            source_id=source_id,
        )
        return await _discovery_response(
            organization_id=organization_id,
            source_id=source_id,
            result=result,
        )
    except (
        SorAdapterUnavailableError,
        SorConfigurationError,
        SorConflictError,
        SorNotFoundError,
        SorVendorOperationError,
        TimeoutError,
    ) as error:
        raise _configuration_error(error) from None


@router.get(
    "/sources/{source_id}/schema",
    response_model=SorSchemaRevisionResponse,
)
async def get_sor_source_schema(
    organization_id: UUID,
    source_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorSchemaRevisionResponse:
    """Return the active immutable vendor schema used by mapping UI."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            repository = SorRepository(session)
            source = await repository.get_source(
                organization_id=organization_id,
                source_id=source_id,
            )
            if source is None:
                raise SorNotFoundError("SOR source not found.")
            if source.active_schema_revision_id is None:
                raise SorConfigurationError(
                    "Verify the source before requesting its schema."
                )
            schema = await repository.get_schema_revision(
                organization_id=organization_id,
                source_id=source_id,
                schema_revision_id=source.active_schema_revision_id,
            )
            if schema is None:
                raise SorConflictError("Active SOR schema revision is unavailable.")
            return SorSchemaRevisionResponse.from_model(schema)
    except (SorConfigurationError, SorConflictError, SorNotFoundError) as error:
        raise _configuration_error(error) from None


@router.post(
    "/sources/{source_id}/mappings",
    response_model=SorMappingRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_sor_mapping(
    organization_id: UUID,
    source_id: UUID,
    request: SorMappingDraftRequest,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorMappingRevisionResponse:
    """Create one immutable draft from explicit discovered-field selections."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction() as session:
            mapping = await SorMappingService(session).create_draft(
                organization_id=organization_id,
                source_id=source_id,
                fields=_mapping_drafts(request),
                actor_id=current_user.member_id,
                projection_version=request.projection_version,
            )
            return await _mapping_response(
                SorRepository(session),
                organization_id=organization_id,
                source_id=source_id,
                mapping=mapping,
            )
    except (SorConfigurationError, SorConflictError, SorNotFoundError) as error:
        raise _configuration_error(error) from None


@router.get(
    "/sources/{source_id}/mappings/{mapping_revision_id}",
    response_model=SorMappingRevisionResponse,
)
async def get_sor_mapping(
    organization_id: UUID,
    source_id: UUID,
    mapping_revision_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorMappingRevisionResponse:
    """Return one exact mapping revision and its selected fields."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            repository = SorRepository(session)
            mapping = await repository.get_mapping_revision(
                organization_id=organization_id,
                source_id=source_id,
                mapping_revision_id=mapping_revision_id,
            )
            if mapping is None:
                raise SorNotFoundError("Mapping revision not found.")
            return await _mapping_response(
                repository,
                organization_id=organization_id,
                source_id=source_id,
                mapping=mapping,
            )
    except SorNotFoundError as error:
        raise _configuration_error(error) from None


@router.post(
    "/sources/{source_id}/mappings/{mapping_revision_id}/publish",
    response_model=SorMappingRevisionResponse,
)
async def publish_sor_mapping(
    organization_id: UUID,
    source_id: UUID,
    mapping_revision_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorMappingRevisionResponse:
    """Atomically publish one mapping and persist its bootstrap work."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction() as session:
            result = await SorOnboardingService(session).publish_mapping(
                organization_id=organization_id,
                source_id=source_id,
                mapping_revision_id=mapping_revision_id,
                actor_id=current_user.member_id,
            )
            response = await _mapping_response(
                SorRepository(session),
                organization_id=organization_id,
                source_id=source_id,
                mapping=result.mapping,
            )
            run_ids = tuple(
                run.id for run in result.runs if run.state is SorWorkState.PENDING
            )
        for run_id in run_ids:
            try:
                await spawn_sor_sync_run(
                    organization_id=organization_id,
                    run_id=run_id,
                )
            except Exception as error:  # noqa: BLE001 - recovery scans committed rows
                logger.error(
                    "SOR mapping bootstrap committed; spawn recovery remains pending "
                    "run_id=%s error_type=%s",
                    run_id,
                    type(error).__name__,
                )
        return response
    except (SorConfigurationError, SorConflictError, SorNotFoundError) as error:
        raise _configuration_error(error) from None


@router.post(
    "/sources/{source_id}/activate",
    response_model=SorSourceActivationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def activate_sor_source(
    organization_id: UUID,
    source_id: UUID,
    request: SorSourceActivationRequest,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorSourceActivationResponse:
    """Atomically persist mapping, streams, and every bootstrap work intent."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction() as session:
            result = await SorOnboardingService(session).activate(
                organization_id=organization_id,
                source_id=source_id,
                fields=_mapping_drafts(request.mapping),
                stream_drafts=_stream_drafts(request),
                actor_id=current_user.member_id,
                projection_version=request.mapping.projection_version,
            )
            response = SorSourceActivationResponse(
                source=SorSourceResponse.model_validate(result.source),
                mapping=await _mapping_response(
                    SorRepository(session),
                    organization_id=organization_id,
                    source_id=source_id,
                    mapping=result.mapping,
                ),
                streams=tuple(
                    SorStreamResponse.model_validate(stream)
                    for stream in result.streams
                ),
                runs=tuple(
                    SorSyncRunResponse.model_validate(run) for run in result.runs
                ),
            )
            run_ids = tuple(
                run.id for run in result.runs if run.state is SorWorkState.PENDING
            )
        for run_id in run_ids:
            try:
                await spawn_sor_sync_run(
                    organization_id=organization_id,
                    run_id=run_id,
                )
            except Exception as error:  # noqa: BLE001 - recovery scans committed rows
                logger.error(
                    "SOR activation committed; spawn recovery remains pending "
                    "run_id=%s error_type=%s",
                    run_id,
                    type(error).__name__,
                )
        return response
    except (SorConfigurationError, SorConflictError, SorNotFoundError) as error:
        raise _configuration_error(error) from None


@router.get(
    "/agents/{agent_id}/source-grants",
    response_model=SorSourceGrantListResponse,
)
async def list_agent_sor_source_grants(
    organization_id: UUID,
    agent_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorSourceGrantListResponse:
    """List live source authority configured on one Agent draft."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            items = await SorSourceGrantService(session).list_for_agent(
                organization_id=organization_id,
                agent_id=agent_id,
            )
            return SorSourceGrantListResponse(items=items)
    except SorNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from None


@router.put(
    "/agents/{agent_id}/source-grants/{source_id}",
    response_model=SorSourceGrantResponse,
)
async def grant_agent_sor_source(
    organization_id: UUID,
    agent_id: UUID,
    source_id: UUID,
    request: SorSourceGrantRequest,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorSourceGrantResponse:
    """Create or replace one explicit Agent/source draft grant."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction() as session:
            return await SorSourceGrantService(session).grant(
                organization_id=organization_id,
                agent_id=agent_id,
                source_id=source_id,
                access=request.access,
                expected_draft_version=request.expected_draft_version,
                actor_id=current_user.member_id,
            )
    except SorNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from None
    except DefinitionRevisionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from None
    except SorConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from None


@router.delete(
    "/agents/{agent_id}/source-grants/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_agent_sor_source(
    organization_id: UUID,
    agent_id: UUID,
    source_id: UUID,
    expected_draft_version: int = Query(gt=0),
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> None:
    """Revoke one live grant and invalidate its published snapshots."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction() as session:
            await SorSourceGrantService(session).revoke(
                organization_id=organization_id,
                agent_id=agent_id,
                source_id=source_id,
                expected_draft_version=expected_draft_version,
                actor_id=current_user.member_id,
            )
        await cancel_active_sor_commands(
            organization_id=organization_id,
            source_id=source_id,
            agent_id=agent_id,
        )
    except SorNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from None
    except DefinitionRevisionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from None


@router.get(
    "/agents/{agent_id}/view/{profile}/{entity}",
    response_model=SorAgentViewResponse,
)
async def get_agent_sor_view(
    organization_id: UUID,
    agent_id: UUID,
    profile: SorProfile,
    entity: Annotated[
        str,
        Path(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$"),
    ],
    source_id: Annotated[list[UUID] | None, Query(max_length=50)] = None,
    record_id: UUID | None = Query(default=None),
    search: Annotated[str, Query(max_length=1000)] = "",
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorAgentViewResponse:
    """Return exactly what the Agent's current published revision may perceive."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            agent = await session.scalar(
                select(AgentsModel).where(
                    AgentsModel.organization_id == organization_id,
                    AgentsModel.id == agent_id,
                    AgentsModel.deleted.is_(False),
                )
            )
            if agent is None or agent.published_revision is None:
                raise SorNotFoundError("Published Agent not found.")
            return await read_agent_view(
                session,
                organization_id=organization_id,
                agent_id=agent_id,
                agent_revision=agent.published_revision,
                profile=profile,
                entity=entity,
                search=search,
                source_ids=tuple(source_id or ()),
                record_id=record_id,
                limit=limit,
                cursor=cursor,
            )
    except SorNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from None
    except SorAuthorityError as error:
        http_status = (
            status.HTTP_404_NOT_FOUND
            if error.code == "SOR_SOURCE_UNAVAILABLE"
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(status_code=http_status, detail=str(error)) from None
    except SorAgentReadError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from None


@router.post(
    "/sources/{source_id}/webhook-subscription",
    response_model=SorSourceResponse,
)
async def ensure_sor_source_webhook_subscription(
    organization_id: UUID,
    source_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorSourceResponse:
    """Register or renew one vendor-managed source webhook."""
    _authorize(organization_id, current_user)
    try:
        await ensure_sor_webhook_subscription(
            organization_id=organization_id,
            source_id=source_id,
        )
        async with start_transaction(ro=True) as session:
            return await SorSourceReadService(session).get(
                organization_id=organization_id,
                source_id=source_id,
            )
    except (
        SorAdapterUnavailableError,
        SorConfigurationError,
        SorConflictError,
        SorNotFoundError,
        SorVendorOperationError,
        TimeoutError,
    ) as error:
        raise _configuration_error(error) from None


@router.delete(
    "/sources/{source_id}/webhook-subscription",
    response_model=SorSourceResponse,
)
async def delete_sor_source_webhook_subscription(
    organization_id: UUID,
    source_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorSourceResponse:
    """Stop vendor delivery and revoke the source's webhook ingress."""
    _authorize(organization_id, current_user)
    try:
        await remove_sor_webhook_subscription(
            organization_id=organization_id,
            source_id=source_id,
        )
        async with start_transaction(ro=True) as session:
            return await SorSourceReadService(session).get(
                organization_id=organization_id,
                source_id=source_id,
            )
    except (
        SorAdapterUnavailableError,
        SorConfigurationError,
        SorConflictError,
        SorNotFoundError,
        SorVendorOperationError,
        TimeoutError,
    ) as error:
        raise _configuration_error(error) from None


@router.post(
    "/sources/{source_id}/webhook-endpoint",
    response_model=SorWebhookEndpointResponse,
)
async def rotate_sor_webhook_endpoint(
    organization_id: UUID,
    source_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorWebhookEndpointResponse:
    """Rotate a source webhook secret and reveal the new endpoint once."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction() as session:
            source = await SorRepository(session).get_source(
                organization_id=organization_id,
                source_id=source_id,
            )
            if source is None:
                raise SorNotFoundError("SOR source not found.")
            token = await SorWebhookService(session).issue_endpoint_token(
                organization_id=organization_id,
                source_id=source_id,
            )
            return SorWebhookEndpointResponse(
                endpoint_path=f"/api/sor/webhooks/{source.vendor_key}/{token}",
                endpoint_token=token,
            )
    except SorNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from None
    except SorConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from None


@router.put(
    "/sources/{source_id}/webhook-signing-secret",
    response_model=SorSourceResponse,
)
async def update_sor_webhook_signing_secret(
    organization_id: UUID,
    source_id: UUID,
    request: SorWebhookSigningSecretUpdateRequest,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorSourceResponse:
    """Rotate a source-owned vendor secret without exposing it on reads."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction() as session:
            source = await SorWebhookService(session).set_signing_secret(
                organization_id=organization_id,
                source_id=source_id,
                signing_secret=request.signing_secret,
                expected_config_revision=request.expected_config_revision,
            )
            return SorSourceResponse.model_validate(source)
    except SorNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from None
    except SorConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from None
    except SorConfigurationError as error:
        raise _configuration_error(error) from None


@router.get(
    "/sources/{source_id}/streams",
    response_model=list[SorStreamResponse],
)
async def list_sor_source_streams(
    organization_id: UUID,
    source_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> list[SorStreamResponse]:
    """List operational streams without revealing encrypted checkpoints."""
    _authorize(organization_id, current_user)
    async with start_transaction(ro=True) as session:
        source = await SorRepository(session).get_source(
            organization_id=organization_id,
            source_id=source_id,
        )
        if source is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        rows = await SorRepository(session).list_streams(
            organization_id=organization_id,
            source_id=source_id,
        )
        return [SorStreamResponse.model_validate(row) for row in rows]


@router.post(
    "/sources/{source_id}/streams",
    response_model=SorStreamResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_sor_source_stream(
    organization_id: UUID,
    source_id: UUID,
    request: SorStreamCreateRequest,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorStreamResponse:
    """Create one explicit vendor-object to canonical-entity stream."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction() as session:
            row = await SorStreamService(session).ensure(
                organization_id=organization_id,
                source_id=source_id,
                vendor_object_key=request.vendor_object_key,
                canonical_entity_kind=request.canonical_entity_kind,
                strategy=request.strategy,
                lookback_seconds=request.lookback_seconds,
                schedule=request.schedule,
            )
            return SorStreamResponse.model_validate(row)
    except SorNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from None
    except (SorConfigurationError, SorConflictError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from None


@router.post(
    "/sources/{source_id}/runs",
    response_model=SorSyncGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_sor_source_run(
    organization_id: UUID,
    source_id: UUID,
    request: SorSyncRunCreateRequest,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorSyncGenerationResponse:
    """Commit one source-wide dependency DAG before spawning its root work."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction() as session:
            repository = SorRepository(session)
            streams = await repository.list_streams(
                organization_id=organization_id,
                source_id=source_id,
            )
            plan = await SorSyncRunService(session).create_generation(
                organization_id=organization_id,
                source_id=source_id,
                stream_ids=tuple(stream.id for stream in streams),
                kind=request.kind,
                max_attempts=request.max_attempts,
            )
            generation = plan.generation
            response = SorSyncGenerationResponse(
                id=generation.id,
                organization_id=generation.organization_id,
                source_id=generation.source_id,
                kind=generation.kind,
                state=generation.state,
                started_at=generation.started_at,
                finished_at=generation.finished_at,
                safe_error_code=generation.safe_error_code,
                safe_error_summary=generation.safe_error_summary,
                created_at=generation.created_at,
                updated_at=generation.updated_at,
                runs=tuple(
                    SorSyncRunResponse.model_validate(run) for run in plan.runs
                ),
            )
            ready_run_ids = plan.ready_run_ids
        for run_id in ready_run_ids:
            try:
                await spawn_sor_sync_run(
                    organization_id=organization_id,
                    run_id=run_id,
                )
            except Exception as error:  # noqa: BLE001 - recovery scans committed rows
                logger.error(
                    "SOR source generation committed; spawn recovery remains pending "
                    "run_id=%s error_type=%s",
                    run_id,
                    type(error).__name__,
                )
        return response
    except (SorConfigurationError, SorConflictError, SorNotFoundError) as error:
        raise _configuration_error(error) from None


@router.post(
    "/sources/{source_id}/streams/{stream_id}/runs",
    response_model=SorSyncRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_sor_stream_run(
    organization_id: UUID,
    source_id: UUID,
    stream_id: UUID,
    request: SorSyncRunCreateRequest,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorSyncRunResponse:
    """Commit sync intent before best-effort durable spawn."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction() as session:
            row, created = await SorSyncRunService(session).create_stream_run(
                organization_id=organization_id,
                source_id=source_id,
                stream_id=stream_id,
                kind=request.kind,
                max_attempts=request.max_attempts,
            )
            run_id = row.id
        if created:
            try:
                await spawn_sor_sync_run(
                    organization_id=organization_id,
                    run_id=run_id,
                )
            except Exception as error:  # noqa: BLE001 - recovery scans committed rows
                logger.error(
                    "SOR sync run committed; spawn recovery remains pending "
                    "run_id=%s error_type=%s",
                    run_id,
                    type(error).__name__,
                )
        async with start_transaction(ro=True) as session:
            current = await SorRepository(session).get_sync_run(
                organization_id=organization_id,
                run_id=run_id,
            )
            if current is None:
                raise SorNotFoundError("SOR sync run not found.")
            return SorSyncRunResponse.model_validate(current)
    except SorNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from None
    except (SorConfigurationError, SorConflictError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from None


@router.get(
    "/custom-datasets",
    response_model=SorCustomDatasetListResponse,
)
async def list_sor_custom_datasets(
    organization_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorCustomDatasetListResponse:
    """List explicitly enabled custom objects without granting Agent access."""
    _authorize(organization_id, current_user)
    async with start_transaction(ro=True) as session:
        views = await SorCustomDatasetService(session).list(
            organization_id=organization_id
        )
        return SorCustomDatasetListResponse(
            items=tuple(_custom_dataset_response(view) for view in views)
        )


@router.get(
    "/custom-datasets/{dataset_id}/records",
    response_model=SorCollectionPageResponse,
)
async def list_sor_custom_dataset_records(
    organization_id: UUID,
    dataset_id: UUID,
    search: Annotated[str, Query(max_length=200)] = "",
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorCollectionPageResponse:
    """Execute the shareable basic grid query for one custom dataset."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            view = await SorCustomDatasetService(session).get(
                organization_id=organization_id,
                dataset_id=dataset_id,
            )
            return await SorCollectionReadService(session).query(
                organization_id=organization_id,
                spec=custom_dataset_read_spec(view),
                query=SorCollectionQuery(
                    source_ids=(view.source.id,),
                    search=search,
                    cursor=cursor,
                    limit=limit,
                ),
            )
    except SorNotFoundError as error:
        raise _configuration_error(error) from None
    except (SorReadNotFoundError, SorReadQueryError) as error:
        raise _read_error(error) from None


@router.post(
    "/custom-datasets/{dataset_id}/records/query",
    response_model=SorCollectionPageResponse,
)
async def query_sor_custom_dataset_records(
    organization_id: UUID,
    dataset_id: UUID,
    query: SorCollectionQuery,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorCollectionPageResponse:
    """Apply Eylo filters, grouping, sorting, and cursors to one dataset."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            view = await SorCustomDatasetService(session).get(
                organization_id=organization_id,
                dataset_id=dataset_id,
            )
            return await SorCollectionReadService(session).query(
                organization_id=organization_id,
                spec=custom_dataset_read_spec(view),
                query=_custom_dataset_query(query, source_id=view.source.id),
            )
    except SorNotFoundError as error:
        raise _configuration_error(error) from None
    except (SorReadNotFoundError, SorReadQueryError) as error:
        raise _read_error(error) from None


@router.get(
    "/custom-datasets/{dataset_id}/grid",
    response_model=SorGridContract,
)
async def get_sor_custom_dataset_grid(
    organization_id: UUID,
    dataset_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorGridContract:
    """Return the Eylo-owned grid contract for one custom dataset."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            view = await SorCustomDatasetService(session).get(
                organization_id=organization_id,
                dataset_id=dataset_id,
            )
            return await SorCollectionReadService(session).grid(
                organization_id=organization_id,
                spec=custom_dataset_read_spec(view),
                source_ids=(view.source.id,),
            )
    except SorNotFoundError as error:
        raise _configuration_error(error) from None
    except (SorReadNotFoundError, SorReadQueryError) as error:
        raise _read_error(error) from None


@router.get(
    "/custom-datasets/{dataset_id}/filter-options",
    response_model=SorFilterOptionsResponse,
)
async def get_sor_custom_dataset_filter_options(
    organization_id: UUID,
    dataset_id: UUID,
    field: Annotated[
        str,
        Query(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.-]*$"),
    ],
    search: Annotated[str, Query(max_length=120)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorFilterOptionsResponse:
    """Return data-derived selectable values for one custom dataset field."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            view = await SorCustomDatasetService(session).get(
                organization_id=organization_id,
                dataset_id=dataset_id,
            )
            return await SorCollectionReadService(session).filter_options(
                organization_id=organization_id,
                spec=custom_dataset_read_spec(view),
                source_ids=(view.source.id,),
                field=field,
                search=search.strip(),
                limit=limit,
            )
    except SorNotFoundError as error:
        raise _configuration_error(error) from None
    except (SorReadNotFoundError, SorReadQueryError) as error:
        raise _read_error(error) from None


@router.get(
    "/custom-datasets/{dataset_id}/records/{record_id}",
    response_model=SorRecordDetailResponse,
)
async def get_sor_custom_dataset_record(
    organization_id: UUID,
    dataset_id: UUID,
    record_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorRecordDetailResponse:
    """Return selected custom values plus source provenance for one record."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            view = await SorCustomDatasetService(session).get(
                organization_id=organization_id,
                dataset_id=dataset_id,
            )
            return await SorCollectionReadService(session).detail(
                organization_id=organization_id,
                spec=custom_dataset_read_spec(view),
                record_id=record_id,
            )
    except SorNotFoundError as error:
        raise _configuration_error(error) from None
    except (SorReadNotFoundError, SorReadQueryError) as error:
        raise _read_error(error) from None


@router.get("/{profile}/{entity}", response_model=SorCollectionPageResponse)
async def list_sor_records(
    organization_id: UUID,
    profile: SorProfile,
    entity: Annotated[
        str,
        Path(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$"),
    ],
    source_id: Annotated[list[UUID] | None, Query(max_length=50)] = None,
    search: Annotated[str, Query(max_length=200)] = "",
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorCollectionPageResponse:
    """Execute the shareable basic form of one canonical collection query."""
    _authorize(organization_id, current_user)
    spec = _read_spec(profile, entity)
    query = SorCollectionQuery(
        source_ids=tuple(source_id or ()),
        search=search,
        cursor=cursor,
        limit=limit,
    )
    try:
        async with start_transaction(ro=True) as session:
            return await SorCollectionReadService(session).query(
                organization_id=organization_id,
                spec=spec,
                query=query,
            )
    except (SorReadNotFoundError, SorReadQueryError) as error:
        raise _read_error(error) from None


@router.post(
    "/{profile}/{entity}/query",
    response_model=SorCollectionPageResponse,
)
async def query_sor_records(
    organization_id: UUID,
    profile: SorProfile,
    entity: Annotated[
        str,
        Path(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$"),
    ],
    query: SorCollectionQuery,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorCollectionPageResponse:
    """Execute nested filters, grouping, sorting, and cursor pagination."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            return await SorCollectionReadService(session).query(
                organization_id=organization_id,
                spec=_read_spec(profile, entity),
                query=query,
            )
    except (SorReadNotFoundError, SorReadQueryError) as error:
        raise _read_error(error) from None


@router.get(
    "/{profile}/{entity}/grid",
    response_model=SorGridContract,
)
async def get_sor_grid_contract(
    organization_id: UUID,
    profile: SorProfile,
    entity: Annotated[
        str,
        Path(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$"),
    ],
    source_id: Annotated[list[UUID] | None, Query(max_length=50)] = None,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorGridContract:
    """Return Eylo field semantics for any replaceable grid renderer."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            return await SorCollectionReadService(session).grid(
                organization_id=organization_id,
                spec=_read_spec(profile, entity),
                source_ids=tuple(source_id or ()),
            )
    except (SorReadNotFoundError, SorReadQueryError) as error:
        raise _read_error(error) from None


@router.get(
    "/{profile}/{entity}/filter-options",
    response_model=SorFilterOptionsResponse,
)
async def get_sor_filter_options(
    organization_id: UUID,
    profile: SorProfile,
    entity: Annotated[
        str,
        Path(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$"),
    ],
    field: Annotated[
        str,
        Query(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.-]*$"),
    ],
    source_id: Annotated[list[UUID] | None, Query(max_length=50)] = None,
    search: Annotated[str, Query(max_length=120)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorFilterOptionsResponse:
    """Return selectable values from the full tenant/source collection scope."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            return await SorCollectionReadService(session).filter_options(
                organization_id=organization_id,
                spec=_read_spec(profile, entity),
                source_ids=tuple(source_id or ()),
                field=field,
                search=search.strip(),
                limit=limit,
            )
    except (SorReadNotFoundError, SorReadQueryError) as error:
        raise _read_error(error) from None


@router.get(
    "/{profile}/{entity}/{record_id}",
    response_model=SorRecordDetailResponse,
)
async def get_sor_record(
    organization_id: UUID,
    profile: SorProfile,
    entity: Annotated[
        str,
        Path(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$"),
    ],
    record_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SorRecordDetailResponse:
    """Return canonical values, custom data, relations, and provenance."""
    _authorize(organization_id, current_user)
    try:
        async with start_transaction(ro=True) as session:
            return await SorCollectionReadService(session).detail(
                organization_id=organization_id,
                spec=_read_spec(profile, entity),
                record_id=record_id,
            )
    except (SorReadNotFoundError, SorReadQueryError) as error:
        raise _read_error(error) from None


__all__ = ["router"]
