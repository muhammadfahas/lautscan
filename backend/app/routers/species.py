"""Marine biodiversity and fish occurrence query endpoints (`GET /v1/species`)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
else:
    try:
        from sqlalchemy.ext.asyncio import AsyncSession
    except ImportError:  # pragma: no cover - fallback when sqlalchemy is absent locally
        AsyncSession = Any

from app.core.db import get_db
from app.schemas.common import ErrorResponse, SpeciesOccurrenceListResponse, WppCode
from app.services.species_service import BboxValidationError, list_species_occurrences

router = APIRouter(prefix="/v1", tags=["species"])


@router.get(
    "/species",
    response_model=SpeciesOccurrenceListResponse,
    summary="Query fish and marine species occurrences (OBIS)",
    operation_id="listSpeciesOccurrences",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Malformed bounding box coordinates",
        },
        422: {
            "model": ErrorResponse,
            "description": "Query parameter validation error",
        },
    },
)
async def get_species_occurrences(
    taxon: str | None = Query(
        default=None,
        min_length=1,
        max_length=120,
        description="Scientific name, common name, or family filter (case-insensitive substring).",
    ),
    wpp: WppCode | None = Query(
        default=None,
        description="Filter occurrences intersecting a specific WPP-NRI zone code (571-718).",
    ),
    bbox: str | None = Query(
        default=None,
        description=(
            "Spatial bounding box formatted as `min_lon,min_lat,max_lon,max_lat` in EPSG:4326."
        ),
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
        description="Maximum number of occurrence records to return.",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Pagination offset.",
    ),
    db: AsyncSession = Depends(get_db),
) -> SpeciesOccurrenceListResponse:
    """Search species occurrences in PostGIS or return Indonesian OBIS baseline records."""
    try:
        return await list_species_occurrences(
            taxon=taxon,
            wpp=wpp,
            bbox=bbox,
            limit=limit,
            offset=offset,
            db=db,
        )
    except BboxValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_BBOX",
                "message": str(exc),
                "detail": None,
            },
        ) from exc
