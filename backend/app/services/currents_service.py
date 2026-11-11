"""Decimated ocean current velocity grid service for directional map arrows."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.etl.fixtures import ensure_sample_netcdf
from app.etl.tiler import sample_currents_grid
from app.schemas.common import CurrentGridResponse, CurrentVectorCell
from app.services.species_service import parse_bbox
from app.services.tile_service import _resolve_dataset_metadata


async def get_currents_vector_grid(
    *,
    bbox: str | None = None,
    requested_date: str = "latest",
    max_vectors: int = 160,
    db: Any | None = None,
) -> CurrentGridResponse:
    """Return decimated ocean current velocity vectors within the requested bbox."""
    if bbox:
        min_lon, min_lat, max_lon, max_lat = parse_bbox(bbox)
    else:
        min_lon, min_lat, max_lon, max_lat = (90.0, -15.0, 145.0, 10.0)

    settings = get_settings()
    tile_cache_dir = Path(settings.TILE_CACHE_DIR)
    _, dataset_path, resolved_date, source_key, timestamp_utc = await _resolve_dataset_metadata(
        db, tile_cache_dir, "currents", requested_date
    )

    if not dataset_path.is_file():
        dataset_path = await asyncio.to_thread(
            ensure_sample_netcdf, tile_cache_dir, "currents", resolved_date
        )

    sampled = await asyncio.to_thread(
        sample_currents_grid,
        dataset_path,
        min_lon,
        min_lat,
        max_lon,
        max_lat,
        max_vectors,
    )
    vectors = [CurrentVectorCell.model_validate(v) for v in sampled["vectors"]]
    acq_raw = sampled.get("acquired_at_utc") or timestamp_utc
    acq_dt = datetime.fromisoformat(str(acq_raw).replace("Z", "+00:00")).astimezone(UTC)

    return CurrentGridResponse(
        requested_date=requested_date,
        resolved_date=resolved_date,
        vectors=vectors,
        total=len(vectors),
        primary_source=str(sampled.get("primary_source") or source_key),
        acquired_at_utc=acq_dt,
    )
