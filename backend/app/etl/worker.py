"""ARQ background worker tasks and schedule configuration (`arq app.etl.worker.WorkerSettings`)."""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from app.etl.base import INDONESIA_BBOX, BoundingBox, ProviderSyncResult, resolve_setting
from app.etl.copernicus import CopernicusMarineAdapter
from app.etl.noaa_erddap import NOAAErddapAdapter
from app.etl.obis_client import NormalizedSpeciesRecord, ObisClient

try:
    from arq import cron as _arq_cron
    from arq.connections import RedisSettings as _ArqRedisSettings
except ImportError:  # pragma: no cover - allows offline test imports without arq installed
    _arq_cron = None
    _ArqRedisSettings = None

logger = logging.getLogger(__name__)

DEFAULT_REDIS_URL: Final[str] = "redis://127.0.0.1:6379/0"
DEFAULT_TILE_CACHE_DIR: Final[str] = "/data/tiles"
PREWARM_LAYERS: Final[tuple[str, ...]] = ("sst", "chlorophyll", "currents")


@dataclass(frozen=True, slots=True)
class FallbackRedisSettings:
    """Minimal fallback used only when `arq` is not installed in local test envs."""

    dsn: str

    @classmethod
    def from_dsn(cls, dsn: str) -> FallbackRedisSettings:
        return cls(dsn=dsn)


@dataclass(frozen=True, slots=True)
class FallbackCronJob:
    """Minimal cron descriptor used only when `arq` is not installed locally."""

    coroutine: Any
    hour: int | set[int] | None = None
    minute: int | set[int] | None = None


def _build_redis_settings() -> Any:
    redis_url = resolve_setting("REDIS_URL", DEFAULT_REDIS_URL) or DEFAULT_REDIS_URL
    if _ArqRedisSettings is not None:
        return _ArqRedisSettings.from_dsn(redis_url)
    return FallbackRedisSettings.from_dsn(redis_url)


def _make_cron(
    coroutine: Any,
    *,
    hour: int | set[int] | None = None,
    minute: int | set[int] | None = None,
) -> Any:
    if _arq_cron is not None:
        return _arq_cron(coroutine, hour=hour, minute=minute)
    return FallbackCronJob(coroutine=coroutine, hour=hour, minute=minute)


def resolve_tile_cache_dir(ctx: dict[str, Any] | None = None) -> Path:
    """Resolve `TILE_CACHE_DIR` from worker context or environment settings."""
    if ctx is not None and ctx.get("tile_cache_dir") is not None:
        return Path(ctx["tile_cache_dir"])
    configured = resolve_setting("TILE_CACHE_DIR", DEFAULT_TILE_CACHE_DIR)
    return Path(configured or DEFAULT_TILE_CACHE_DIR)


def _lat_to_tile_y(lat_deg: float, zoom: int) -> int:
    clamped = max(-85.05112878, min(85.05112878, lat_deg))
    lat_rad = math.radians(clamped)
    n = 1 << zoom
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, y))


def tile_ranges_for_bbox(bbox: BoundingBox, zoom: int) -> tuple[range, range]:
    """Compute inclusive slippy map `(x_range, y_range)` covering `bbox` at `zoom`."""
    n = 1 << zoom
    x_min = max(0, min(n - 1, math.floor((bbox.min_lon + 180.0) / 360.0 * n)))
    x_max = max(0, min(n - 1, math.floor((bbox.max_lon + 180.0) / 360.0 * n)))
    y_min = _lat_to_tile_y(bbox.max_lat, zoom)
    y_max = _lat_to_tile_y(bbox.min_lat, zoom)
    return range(x_min, x_max + 1), range(min(y_min, y_max), max(y_min, y_max) + 1)


async def startup(ctx: dict[str, Any]) -> None:
    """Initialize shared worker context on ARQ startup."""
    tile_dir = resolve_tile_cache_dir(ctx)
    ctx["tile_cache_dir"] = tile_dir
    try:
        tile_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Unable to initialize tile cache directory %s: %s", tile_dir, exc)


async def shutdown(ctx: dict[str, Any]) -> None:
    """Cleanly release worker resources on ARQ shutdown."""
    ctx.clear()


async def sync_noaa_task(
    ctx: dict[str, Any],
    target_date: str | None = None,
) -> dict[str, Any]:
    """Ingest Indonesia NetCDF subsets from NOAA CoastWatch ERDDAP."""
    tile_dir = resolve_tile_cache_dir(ctx)
    raw_dir = tile_dir / "raw" / "noaa_erddap"
    adapter: NOAAErddapAdapter = ctx.get("noaa_adapter") or NOAAErddapAdapter()
    result = await adapter.sync(output_dir=raw_dir, target_date=target_date)
    await _persist_sync_log(result)
    return _sync_result_summary(result)


async def sync_obis_task(
    ctx: dict[str, Any],
    taxon: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Ingest Indonesian marine species occurrences from OBIS API v3."""
    client: ObisClient = ctx.get("obis_client") or ObisClient()
    result = await client.sync(taxon=taxon, limit=limit)
    persisted_rows = 0
    raw_records = result.metadata.get("records")
    if result.status == "success" and isinstance(raw_records, list):
        records = [
            NormalizedSpeciesRecord(**rec)
            for rec in raw_records
            if isinstance(rec, dict)
        ]
        persisted_rows = await _persist_obis_occurrences(records)

    await _persist_sync_log(result)
    summary = _sync_result_summary(result)
    summary["persisted_rows"] = persisted_rows
    return summary


async def sync_copernicus_task(
    ctx: dict[str, Any],
    target_date: str | None = None,
) -> dict[str, Any]:
    """Run optional Copernicus Marine batch ingestion when credentials are configured."""
    tile_dir = resolve_tile_cache_dir(ctx)
    raw_dir = tile_dir / "raw" / "copernicus_marine"
    adapter: CopernicusMarineAdapter = ctx.get("copernicus_adapter") or CopernicusMarineAdapter()
    result = await adapter.sync(output_dir=raw_dir, target_date=target_date)
    await _persist_sync_log(result)
    return _sync_result_summary(result)


async def prewarm_tiles_task(
    ctx: dict[str, Any],
    target_date: str | None = None,
    zoom_levels: tuple[int, ...] = (3, 4, 5),
) -> dict[str, Any]:
    """Pre-render Indonesian XYZ PNG tiles across low zoom levels into `TILE_CACHE_DIR`."""
    tile_dir = resolve_tile_cache_dir(ctx)
    acq_date = (
        target_date
        if target_date and target_date != "latest"
        else datetime.now(UTC).strftime("%Y-%m-%d")
    )

    try:
        from app.etl.fixtures import ensure_sample_netcdf
        from app.etl.tiler import render_tile_to_cache
    except ImportError as exc:
        return {
            "status": "skipped",
            "acq_date": acq_date,
            "tiles_rendered": 0,
            "tiles_empty": 0,
            "error": f"Raster tiler dependencies unavailable: {exc}",
        }

    rendered = 0
    empty = 0
    layer_stats: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for layer in PREWARM_LAYERS:
        noaa_candidate = tile_dir / "raw" / "noaa_erddap" / f"noaa_{layer}_{acq_date}.nc"
        try:
            if noaa_candidate.is_file():
                try:
                    layer_rendered, layer_empty = _render_layer_zooms(
                        render_tile_to_cache,
                        noaa_candidate,
                        tile_dir,
                        layer,
                        acq_date,
                        zoom_levels,
                    )
                    dataset_path = noaa_candidate
                except Exception as exc:  # noqa: BLE001 (fall back to offline fixture grid)
                    logger.warning(
                        "Falling back to sample NetCDF for %s after unreadable NOAA file %s: %s",
                        layer,
                        noaa_candidate,
                        exc,
                    )
                    dataset_path = ensure_sample_netcdf(tile_dir, layer, acq_date)
                    layer_rendered, layer_empty = _render_layer_zooms(
                        render_tile_to_cache,
                        dataset_path,
                        tile_dir,
                        layer,
                        acq_date,
                        zoom_levels,
                    )
            else:
                dataset_path = ensure_sample_netcdf(tile_dir, layer, acq_date)
                layer_rendered, layer_empty = _render_layer_zooms(
                    render_tile_to_cache,
                    dataset_path,
                    tile_dir,
                    layer,
                    acq_date,
                    zoom_levels,
                )

            rendered += layer_rendered
            empty += layer_empty
            layer_stats[layer] = {
                "ok": True,
                "dataset_path": str(dataset_path),
                "tiles_rendered": layer_rendered,
                "tiles_empty": layer_empty,
            }
        except Exception as exc:  # noqa: BLE001 (isolate per-layer prewarm failures)
            err_msg = f"{layer}: {type(exc).__name__}: {exc}"
            errors.append(err_msg)
            layer_stats[layer] = {"ok": False, "error": err_msg}

    status = "success" if not errors else ("partial" if rendered > 0 else "failed")
    return {
        "status": status,
        "acq_date": acq_date,
        "tiles_rendered": rendered,
        "tiles_empty": empty,
        "layers": layer_stats,
        "error": "; ".join(errors) if errors else None,
    }


def _render_layer_zooms(
    render_fn: Any,
    dataset_path: Path,
    tile_dir: Path,
    layer: str,
    acq_date: str,
    zoom_levels: tuple[int, ...],
) -> tuple[int, int]:
    layer_rendered = 0
    layer_empty = 0
    for z in zoom_levels:
        if z < 0 or z > 14:
            continue
        x_range, y_range = tile_ranges_for_bbox(INDONESIA_BBOX, z)
        for x in x_range:
            for y in y_range:
                _out_path, _byte_size, is_empty, _etag = render_fn(
                    dataset_path,
                    tile_dir,
                    layer,
                    acq_date,
                    z,
                    x,
                    y,
                    fmt="png",
                )
                layer_rendered += 1
                if is_empty:
                    layer_empty += 1
    return layer_rendered, layer_empty


def _sync_result_summary(result: ProviderSyncResult) -> dict[str, Any]:
    return {
        "source_key": result.source_key,
        "dataset_type": result.dataset_type,
        "status": result.status,
        "sync_log_status": result.sync_log_status,
        "records_ingested": result.records_ingested,
        "file_path": result.file_path,
        "duration_ms": result.duration_ms,
        "error_message": result.error_message,
    }


async def _persist_sync_log(result: ProviderSyncResult) -> bool:
    """Persist `SourceSyncLog` when PostgreSQL/SQLAlchemy is configured and reachable."""
    try:
        from app.core.db import async_session_maker
        from app.models.spatial import SourceSyncLog
    except ImportError:
        return False

    compact_meta = {
        k: v
        for k, v in result.metadata.items()
        if k not in ("records", "zones")
    }
    try:
        async with async_session_maker() as session:
            entry = SourceSyncLog(
                source_key=result.source_key,
                dataset_type=result.dataset_type,
                status=result.sync_log_status,
                records_ingested=max(0, result.records_ingested),
                started_at_utc=result.started_at_utc,
                finished_at_utc=result.finished_at_utc,
                duration_ms=result.duration_ms,
                error_message=result.error_message,
                metadata_json=compact_meta,
            )
            session.add(entry)
            await session.commit()
        return True
    except Exception as exc:  # noqa: BLE001 (worker tasks remain resilient offline)
        logger.debug("Skipping SourceSyncLog persistence for %s: %s", result.source_key, exc)
        return False


async def _persist_obis_occurrences(records: list[NormalizedSpeciesRecord]) -> int:
    """Upsert normalized OBIS species records into PostGIS when available."""
    if not records:
        return 0
    try:
        from sqlalchemy import func
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.core.db import async_session_maker
        from app.models.spatial import SpeciesOccurrence
    except ImportError:
        return 0

    inserted = 0
    try:
        async with async_session_maker() as session:
            for rec in records:
                event_dt: datetime | None = None
                if rec.event_date_utc:
                    try:
                        event_dt = datetime.fromisoformat(
                            rec.event_date_utc.replace("Z", "+00:00")
                        )
                    except ValueError:
                        event_dt = None

                values = {
                    "id": uuid.UUID(rec.id),
                    "obis_id": rec.obis_id,
                    "scientific_name": rec.scientific_name,
                    "common_name": rec.common_name,
                    "taxon_rank": rec.taxon_rank,
                    "family": rec.family,
                    "wpp_code": rec.wpp_code,
                    "geom": func.ST_SetSRID(func.ST_Point(rec.lon, rec.lat), 4326),
                    "depth_m": rec.depth_m,
                    "event_date_utc": event_dt,
                    "individual_count": rec.individual_count,
                    "habitat_note": rec.habitat_note,
                    "dataset_name": rec.dataset_name,
                    "attribution": rec.attribution,
                    "license": rec.license,
                }
                stmt = pg_insert(SpeciesOccurrence).values(**values)
                if rec.obis_id is not None:
                    stmt = stmt.on_conflict_do_nothing(index_elements=["obis_id"])
                else:
                    stmt = stmt.on_conflict_do_nothing(index_elements=["id"])
                res = await session.execute(stmt)
                if getattr(res, "rowcount", 0):
                    inserted += int(res.rowcount)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 (graceful offline fallback)
        logger.debug("Skipping OBIS occurrence DB upsert: %s", exc)
        return 0
    return inserted


def _build_cron_jobs() -> list[Any]:
    return [
        _make_cron(sync_noaa_task, hour={0, 6, 12, 18}, minute=15),
        _make_cron(sync_obis_task, hour=2, minute=30),
        _make_cron(sync_copernicus_task, hour=3, minute=0),
        _make_cron(prewarm_tiles_task, hour={1, 7, 13, 19}, minute=0),
    ]


class WorkerSettings:
    """ARQ worker configuration matching `arq app.etl.worker.WorkerSettings`."""

    redis_settings = _build_redis_settings()
    functions = [
        sync_noaa_task,
        sync_obis_task,
        sync_copernicus_task,
        prewarm_tiles_task,
    ]
    cron_jobs = _build_cron_jobs()
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 4
    job_timeout = 600
