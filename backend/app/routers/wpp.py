"""Indonesian WPP-NRI zone boundary and summary endpoints (`GET /v1/wpp`)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.db_seed import load_wpp_seed_records
from app.models.spatial import WppNriZone
from app.schemas.common import ErrorResponse, WppCode, WppZoneListResponse, WppZoneRecord

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["wpp"])


async def _query_wpp_from_db(
    db: AsyncSession,
    *,
    code: WppCode | None,
    include_geometry: bool,
) -> list[WppZoneRecord]:
    geom_expr = (
        func.ST_AsGeoJSON(WppNriZone.geom).label("geometry_geojson")
        if include_geometry
        else literal(None).label("geometry_geojson")
    )
    stmt = select(
        WppNriZone.wpp_code,
        WppNriZone.name,
        WppNriZone.waters_id,
        WppNriZone.waters_en,
        WppNriZone.legal_basis,
        WppNriZone.geometry_source,
        func.ST_Y(WppNriZone.centroid).label("centroid_lat"),
        func.ST_X(WppNriZone.centroid).label("centroid_lon"),
        WppNriZone.min_lon,
        WppNriZone.min_lat,
        WppNriZone.max_lon,
        WppNriZone.max_lat,
        WppNriZone.area_km2,
        WppNriZone.sst_mean_c,
        WppNriZone.chlorophyll_mean_mg_m3,
        WppNriZone.latest_observation_utc,
        geom_expr,
    ).order_by(WppNriZone.wpp_code.asc())

    if code is not None:
        stmt = stmt.where(WppNriZone.wpp_code == code)

    result = await db.execute(stmt)
    rows = result.mappings().all()
    records: list[WppZoneRecord] = []
    for row in rows:
        payload: dict[str, Any] = dict(row)
        if not include_geometry:
            payload["geometry_geojson"] = None
        records.append(WppZoneRecord.model_validate(payload))
    return records


def _load_wpp_from_seed(
    *,
    code: WppCode | None,
    include_geometry: bool,
) -> list[WppZoneRecord]:
    seed_path = get_settings().WPP_SEED_PATH
    seed_records = load_wpp_seed_records(
        seed_path=seed_path,
        include_geometry=include_geometry,
    )
    if code is not None:
        seed_records = [item for item in seed_records if item["wpp_code"] == code]
    return [WppZoneRecord.model_validate(item) for item in seed_records]


@router.get(
    "/wpp",
    response_model=WppZoneListResponse,
    responses={
        422: {
            "model": ErrorResponse,
            "description": "Validation error",
        }
    },
    summary="List WPP-NRI boundaries and oceanographic summaries",
    operation_id="listWppZones",
)
async def list_wpp_zones(
    code: WppCode | None = Query(
        default=None,
        description="Filter by specific 3-digit WPP-NRI code (571-718).",
    ),
    include_geometry: bool = Query(
        default=True,
        description=(
            "Include serialized GeoJSON geometry string in each item "
            "(set false for low-bandwidth tables)."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> WppZoneListResponse:
    """Return WPP-NRI zones from PostGIS or fall back to P0 seed JSON in dev/smoke mode."""
    items: list[WppZoneRecord] = []
    try:
        items = await asyncio.wait_for(
            _query_wpp_from_db(
                db,
                code=code,
                include_geometry=include_geometry,
            ),
            timeout=2.5,
        )
    except Exception as exc:
        logger.warning(
            "PostGIS unavailable for /v1/wpp (%s); falling back to WPP-NRI seed JSON.",
            type(exc).__name__,
        )

    if not items:
        items = _load_wpp_from_seed(code=code, include_geometry=include_geometry)

    return WppZoneListResponse(items=items, total=len(items))
