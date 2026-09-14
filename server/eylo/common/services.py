"""Typed row/schema conversion and shared application-service reads."""

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel

from eylo.common.exceptions import EntityNotFound
from eylo.common.repositories import BaseORMRepository, ModelClass, map_schema_to_model

SchemaClass = TypeVar("SchemaClass", bound=BaseModel)

logger = logging.getLogger(__name__)


class EyloBaseService(ABC, Generic[SchemaClass, ModelClass]):
    """Pair one response schema with one ORM model; domains own mutation policy."""

    @property
    @abstractmethod
    def schema(self) -> type[SchemaClass]:
        """Schema for the "common" platform."""
        pass

    @property
    @abstractmethod
    def repository(self) -> BaseORMRepository[ModelClass]:
        """Repository for the "common" platform."""
        pass

    def orm_to_schema(self, orm_object: ModelClass) -> SchemaClass:
        """Convert ORM Object to Schema."""
        return self.schema.model_validate(orm_object)

    def schema_to_orm(
        self, schema_object: BaseModel, schema_class: type[BaseModel] | None = None
    ) -> ModelClass:
        """Construct a row without attaching it to a transaction."""
        if schema_class:
            return map_schema_to_model(
                model_cls=self.repository.model,
                schema_instance=schema_object,
                schema_cls=schema_class,
            )
        return map_schema_to_model(
            model_cls=self.repository.model,
            schema_instance=schema_object,
            schema_cls=self.schema,
        )

    def orm_to_schema_list(
        self, orm_objects: Iterable[ModelClass]
    ) -> list[SchemaClass]:
        """Convert List of ORM Objects to Schemas."""
        return [self.orm_to_schema(orm_object) for orm_object in orm_objects]

    def schema_to_orm_list(
        self, schema_objects: Iterable[BaseModel]
    ) -> list[ModelClass]:
        """Construct unpersisted ORM rows, not response-schema instances."""
        return [self.schema_to_orm(schema_object) for schema_object in schema_objects]

    async def get_(self, pk: UUID) -> SchemaClass:
        """Get Entity By Primary Key."""
        entity = await self.repository.get_(pk)
        if not entity:
            raise EntityNotFound(
                f"{pk=} not found. {self.repository.__class__.__name__}"
            )
        return self.orm_to_schema(entity)

    async def get_multi_(self, pks: list[UUID]) -> list[SchemaClass]:
        """Get Multiple Entities By Primary Keys."""
        entities = await self.repository.get_multi_(pks)
        if not entities:
            raise EntityNotFound(
                f"{pks=} not found. {self.repository.__class__.__name__}"
            )
        return self.orm_to_schema_list(entities)

    async def get_by_(self, key: str, value: str | int | float) -> SchemaClass | None:
        """Get Entity By Attribute."""
        try:
            _entity = await self.repository.get_by_(key, value)
            if not _entity:
                raise EntityNotFound(f"{key=} {value=} not found")
            return self.orm_to_schema(_entity)
        except ValueError as error:
            logger.warning("Entity lookup rejected error_type=%s", type(error).__name__)
        except Exception as error:
            logger.error("Entity lookup failed error_type=%s", type(error).__name__)

    async def get_by_external_id(self, external_id: str) -> SchemaClass | None:
        """Get Entity By External ID."""
        try:
            return await self.get_by_("external_id", external_id)
        except EntityNotFound:
            return None
        except ValueError as error:
            logger.warning(
                "External ID lookup rejected error_type=%s", type(error).__name__
            )
        except Exception as error:
            logger.error(
                "External ID lookup failed error_type=%s", type(error).__name__
            )
