"""XYZ 256x256 EPSG:3857 oceanographic raster tile endpoints (`GET /v1/tiles/...`)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response

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
from app.schemas.common import ErrorResponse
from app.services.tile_service import TileValidationError, get_raster_tile

router = APIRouter(prefix="/v1", tags=["tiles"])


@router.get(
    "/tiles/{layer}/{date}/{z}/{x}/{y}.png",
    summary="Serve 256x256 EPSG:3857 RGBA oceanographic raster tile",
    operation_id="getRasterTile",
    responses={
        200: {
            "description": "256x256 RGBA raster tile image",
            "content": {
                "image/png": {"schema": {"type": "string", "format": "binary"}},
                "image/webp": {"schema": {"type": "string", "format": "binary"}},
            },
        },
        400: {"model": ErrorResponse, "description": "Invalid tile coordinates or parameters"},
        404: {
            "model": ErrorResponse,
            "description": "Layer dataset not available for requested date",
        },
        422: {
            "model": ErrorResponse,
            "description": "Path or query parameter validation error",
        },
    },
)
async def get_tile(
    layer: Literal["sst", "chlorophyll", "currents", "potential"] = Path(
        ...,
        description="Oceanographic raster layer key.",
    ),
    date: str = Path(
        ...,
        pattern=r"^(\d{4}-\d{2}-\d{2}|latest)$",
        description="Acquisition date in YYYY-MM-DD (UTC) or `latest`.",
    ),
    z: int = Path(..., ge=0, le=14, description="Web Mercator zoom level (0-14)."),
    x: int = Path(..., ge=0, description="Slippy map tile column X."),
    y: int = Path(..., ge=0, description="Slippy map tile row Y."),
    tile_format: Literal["png", "webp"] = Query(
        default="png",
        alias="format",
        description="Output raster encoding (`png` default or `webp` for low-bandwidth clients).",
    ),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> Response:
    """Serve a cached or dynamically rendered 256x256 RGBA tile with metadata headers."""
    try:
        result = await get_raster_tile(
            layer=layer,
            date_str=date,
            z=z,
            x=x,
            y=y,
            fmt=tile_format,
            db=db,
            redis=redis,
        )
    except TileValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_TILE_REQUEST",
                "message": str(exc),
                "detail": None,
            },
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "DATASET_NOT_FOUND",
                "message": "Layer dataset not available for requested date.",
                "detail": str(exc),
            },
        ) from exc

    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={
            "Cache-Control": result.cache_control,
            "ETag": f'"{result.etag}"',
            "X-Tile-Cache": result.cache_status,
            "X-Data-Source": result.data_source,
            "X-Dataset-Timestamp-UTC": result.dataset_timestamp_utc,
        },
    )
