"""Marine data source health, licensing, and ETL sync log endpoints (`GET /v1/sources`)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Query

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
else:
    try:
        from sqlalchemy.ext.asyncio import AsyncSession
    except ImportError:  # pragma: no cover - fallback when sqlalchemy is absent locally
        AsyncSession = Any

from app.core.db import get_db
from app.schemas.common import DataSourcesResponse, ErrorResponse
from app.services.sources_service import list_data_sources

router = APIRouter(prefix="/v1", tags=["sources"])


@router.get(
    "/sources",
    response_model=DataSourcesResponse,
    summary="List marine data source health, freshness, attribution, and sync logs",
    operation_id="listDataSources",
    responses={
        500: {
            "model": ErrorResponse,
            "description": "Internal error retrieving source telemetry",
        }
    },
)
async def get_data_sources(
    include_recent_logs: bool = Query(
        default=True,
        description="Include recent ETL synchronization logs.",
    ),
    db: AsyncSession = Depends(get_db),
) -> DataSourcesResponse:
    """Return status for all 5 catalogued data providers and recent ETL sync history."""
    return await list_data_sources(
        include_recent_logs=include_recent_logs,
        db=db,
    )
