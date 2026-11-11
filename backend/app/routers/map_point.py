"""Coordinate-level oceanographic point inspection endpoints (`GET /v1/map/point`)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession
else:
    try:
        from redis.asyncio import Redis
    except ImportError:  # pragma: no cover - fallback when redis is absent locally
        Redis = Any

    try:
        from sqlalchemy.ext.asyncio import AsyncSession
    except ImportError:  # pragma: no cover - fallback when sqlalchemy is absent locally
        AsyncSession = Any

from app.core.db import get_db
from app.core.redis import get_redis
from app.schemas.common import ErrorResponse, MapPointInspection
from app.services.point_query import PointQueryValidationError, inspect_map_point

router = APIRouter(prefix="/v1", tags=["map"])


@router.get(
    "/map/point",
    response_model=MapPointInspection,
    summary="Inspect interpolated oceanographic parameters at a coordinate",
    operation_id="inspectMapPoint",
    responses={
        422: {
            "model": ErrorResponse,
            "description": "Coordinate or date validation error",
        }
    },
)
async def inspect_point(
    lat: float = Query(..., ge=-90.0, le=90.0, description="WGS84 latitude in decimal degrees."),
    lon: float = Query(..., ge=-180.0, le=180.0, description="WGS84 longitude in decimal degrees."),
    date: str = Query(
        default="latest",
        pattern=r"^(\d{4}-\d{2}-\d{2}|latest)$",
        description="Target date in YYYY-MM-DD (UTC) or `latest`.",
    ),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> MapPointInspection:
    """Return interpolated SST, chlorophyll-a, currents, and WPP-NRI metadata at (lat, lon)."""
    try:
        return await inspect_map_point(
            lat=lat,
            lon=lon,
            requested_date=date,
            db=db,
            redis=redis,
        )
    except PointQueryValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VALIDATION_ERROR",
                "message": "Coordinate or date validation failed.",
                "detail": str(exc),
            },
        ) from exc
