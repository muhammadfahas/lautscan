"""Ocean current vector grid endpoint (`GET /v1/currents/grid`)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
else:
    try:
        from sqlalchemy.ext.asyncio import AsyncSession
    except ImportError:  # pragma: no cover - optional locally
        AsyncSession = Any

from app.core.db import get_db
from app.schemas.common import CurrentGridResponse, ErrorResponse
from app.services.currents_service import get_currents_vector_grid
from app.services.species_service import BboxValidationError

router = APIRouter(prefix="/v1", tags=["currents"])


@router.get(
    "/currents/grid",
    response_model=CurrentGridResponse,
    summary="Query decimated ocean current velocity vectors for map arrows",
    operation_id="getCurrentsGrid",
    responses={
        400: {"model": ErrorResponse, "description": "Malformed bounding box coordinates"},
        422: {"model": ErrorResponse, "description": "Query parameter validation error"},
    },
)
async def get_currents_grid(
    bbox: str | None = Query(
        default=None,
        description="Bounding box `min_lon,min_lat,max_lon,max_lat` in EPSG:4326.",
    ),
    date: str = Query(
        default="latest",
        pattern=r"^(\d{4}-\d{2}-\d{2}|latest)$",
        description="Target date in YYYY-MM-DD (UTC) or `latest`.",
    ),
    max_vectors: int = Query(
        default=144,
        ge=16,
        le=320,
        description="Maximum number of decimated velocity vectors returned.",
    ),
    db: AsyncSession | None = Depends(get_db),
) -> CurrentGridResponse:
    """Return decimated ocean current vectors for directional canvas arrows."""
    try:
        return await get_currents_vector_grid(
            bbox=bbox,
            requested_date=date,
            max_vectors=max_vectors,
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
