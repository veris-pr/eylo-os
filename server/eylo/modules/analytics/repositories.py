"""Persistence access for the `analytics` domain."""

from sqlalchemy import text

from eylo.common.database import start_transaction
from eylo.modules.analytics.contracts import (
    AnalyticsCountBucket,
    AnalyticsPeriod,
)


class AnalyticsRepository:
    async def execute_query[Bucket: AnalyticsCountBucket](
        self,
        query: str,
        period: AnalyticsPeriod,
        bucket_type: type[Bucket],
    ) -> tuple[Bucket, ...]:
        """Return validated aggregates, never session-bound SQLAlchemy rows."""
        async with start_transaction(ro=True) as db:
            result = await db.execute(text(query), period.query_parameters())
            return tuple(bucket_type.model_validate(dict(row)) for row in result.mappings())
