"""Raster tile retrieval, caching, and on-demand NetCDF rendering service."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from PIL import Image

from app.core.config import get_settings
from app.etl.fixtures import ensure_sample_netcdf
from app.etl.tiler import _load_layer_grid, render_potential_tile_to_cache, render_tile_to_cache

try:
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert
except ImportError:  # pragma: no cover - optional when sqlalchemy is absent locally
    pg_insert = None  # type: ignore[assignment]
    select = None  # type: ignore[assignment]

try:
    from app.models.spatial import RasterDataset, TileCacheIndex
except ImportError:  # pragma: no cover - optional when sqlalchemy models cannot load
    RasterDataset = None  # type: ignore[assignment,misc]
    TileCacheIndex = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

TileLayer = Literal["sst", "chlorophyll", "currents", "potential"]
TileFormat = Literal["png", "webp"]
TileCacheStatus = Literal["HIT", "MISS", "EMPTY"]

SUPPORTED_LAYERS: tuple[TileLayer, ...] = ("sst", "chlorophyll", "currents", "potential")
SUPPORTED_FORMATS: tuple[TileFormat, ...] = ("png", "webp")
MAX_TILE_ZOOM = 14
TILE_CACHE_TTL_SECONDS = 3600
TILE_CACHE_VERSION = "v2"
MEDIA_TYPES: dict[str, str] = {
    "png": "image/png",
    "webp": "image/webp",
}


class TileValidationError(ValueError):
    """Raised when requested tile parameters or coordinates are invalid."""


@dataclass(slots=True)
class TileResult:
    """Rendered or cached raster tile payload and HTTP metadata headers."""

    content: bytes
    media_type: str
    cache_status: TileCacheStatus
    data_source: str
    dataset_timestamp_utc: str
    cache_control: str
    etag: str


def _parse_iso_date(date_str: str) -> date:
    try:
        return date.fromisoformat(date_str)
    except ValueError as exc:
        raise TileValidationError(
            f"Invalid calendar date '{date_str}'; expected YYYY-MM-DD."
        ) from exc


def validate_tile_request(
    layer: str,
    date_str: str,
    z: int,
    x: int,
    y: int,
    fmt: str,
) -> tuple[TileLayer, str, TileFormat]:
    """Validate layer, date selector, slippy coordinates, and output image format."""
    if layer not in SUPPORTED_LAYERS:
        raise TileValidationError(
            f"Unsupported raster layer '{layer}'. Must be one of {SUPPORTED_LAYERS}."
        )
    if fmt not in SUPPORTED_FORMATS:
        raise TileValidationError(
            f"Unsupported tile format '{fmt}'. Must be one of {SUPPORTED_FORMATS}."
        )
    if z < 0 or z > MAX_TILE_ZOOM:
        raise TileValidationError(f"Zoom level z={z} out of supported range 0..{MAX_TILE_ZOOM}.")

    grid_size = 1 << z
    if x < 0 or x >= grid_size or y < 0 or y >= grid_size:
        raise TileValidationError(
            f"Slippy tile coordinates (x={x}, y={y}) out of bounds for z={z} (0..{grid_size - 1})."
        )

    if date_str != "latest":
        _parse_iso_date(date_str)

    return layer, date_str, fmt  # type: ignore[return-value]


def _format_utc_iso(dt: datetime) -> str:
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_tile_alpha_empty(tile_bytes: bytes) -> bool:
    """Inspect alpha channel of a cached PNG/WebP tile to detect fully transparent tiles."""
    try:
        with Image.open(io.BytesIO(tile_bytes)) as img:
            rgba = img.convert("RGBA")
            alpha_extrema = rgba.getchannel("A").getextrema()
            return int(alpha_extrema[1]) == 0
    except Exception:
        return False


def _read_bytes_sync(path: Path) -> bytes:
    return path.read_bytes()


def _is_file_sync(path: Path) -> bool:
    return path.is_file()


def _read_if_file_sync(path: Path) -> bytes | None:
    if path.is_file():
        return path.read_bytes()
    return None


async def _resolve_dataset_metadata(
    db: Any | None,
    tile_cache_dir: Path,
    layer: TileLayer,
    requested_date: str,
) -> tuple[Any | None, Path, str, str, str]:
    """Resolve the active NetCDF path from PostGIS or fall back to deterministic fixture."""
    lookup_layer = "sst" if layer == "potential" else layer
    dataset_id: Any | None = None
    dataset_path: Path | None = None
    resolved_date: str | None = None
    source_key = "noaa_erddap"
    timestamp_utc: str | None = None

    if db is not None and select is not None and RasterDataset is not None:
        try:
            stmt = select(RasterDataset).where(
                RasterDataset.layer == lookup_layer,
                RasterDataset.status == "ready",
            )
            if requested_date != "latest":
                target_d = _parse_iso_date(requested_date)
                stmt = stmt.where(RasterDataset.acquisition_date <= target_d)
            stmt = stmt.order_by(RasterDataset.acquisition_date.desc()).limit(1)
            row = (await db.execute(stmt)).scalar_one_or_none()
            if row is not None:
                candidate = Path(str(row.file_path))
                if await asyncio.to_thread(_is_file_sync, candidate):
                    dataset_id = row.id
                    dataset_path = candidate
                    resolved_date = row.acquisition_date.isoformat()
                    source_key = str(row.source_key)
                    timestamp_utc = _format_utc_iso(row.acquired_at_utc)
        except Exception as exc:
            logger.debug("Falling back to fixture tile source after DB lookup failure: %s", exc)

    if dataset_path is None and requested_date == "latest":
        global_nc = tile_cache_dir / "global" / f"noaa_{lookup_layer}.nc"
        if await asyncio.to_thread(_is_file_sync, global_nc):
            dataset_path = global_nc
            grid_meta = await asyncio.to_thread(_load_layer_grid, global_nc, lookup_layer)
            fallback_now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            timestamp_utc = grid_meta.acquired_at_utc or fallback_now
            resolved_date = str(timestamp_utc)[:10]

    if dataset_path is None:
        resolved_date = (
            datetime.now(UTC).date().isoformat()
            if requested_date == "latest"
            else requested_date
        )
        dataset_path = await asyncio.to_thread(
            ensure_sample_netcdf, tile_cache_dir, lookup_layer, resolved_date
        )
        timestamp_utc = f"{resolved_date}T12:00:00Z"

    assert resolved_date is not None
    assert timestamp_utc is not None
    return dataset_id, dataset_path, resolved_date, source_key, timestamp_utc


async def _record_tile_index(
    db: Any | None,
    dataset_id: Any | None,
    layer: str,
    resolved_date: str,
    z: int,
    x: int,
    y: int,
    fmt: str,
    tile_path: Path,
    byte_size: int,
    is_empty: bool,
    etag: str,
) -> None:
    """Persist tile metadata in PostGIS tile_cache_index when DB and dataset exist."""
    if db is None or dataset_id is None or pg_insert is None or TileCacheIndex is None:
        return
    try:
        acq_date = date.fromisoformat(resolved_date)
        stmt = (
            pg_insert(TileCacheIndex)
            .values(
                dataset_id=dataset_id,
                layer=layer,
                acquisition_date=acq_date,
                z=z,
                x=x,
                y=y,
                format=fmt,
                file_path=str(tile_path),
                byte_size=byte_size,
                is_empty=is_empty,
                etag=etag,
                hit_count=1,
            )
            .on_conflict_do_update(
                constraint="uq_tile_xyz",
                set_={
                    "dataset_id": dataset_id,
                    "file_path": str(tile_path),
                    "byte_size": byte_size,
                    "is_empty": is_empty,
                    "etag": etag,
                    "last_accessed_at": datetime.now(UTC),
                },
            )
        )
        await db.execute(stmt)
        await db.commit()
    except Exception as exc:
        logger.debug("Skipping tile_cache_index DB persistence: %s", exc)
        with contextlib.suppress(Exception):
            await db.rollback()


async def _set_redis_tile_meta(
    redis: Any | None,
    cache_key: str,
    payload: dict[str, Any],
) -> None:
    if redis is None:
        return
    try:
        await redis.set(cache_key, json.dumps(payload), ex=TILE_CACHE_TTL_SECONDS)
    except Exception as exc:
        logger.debug("Skipping Redis tile metadata cache write: %s", exc)


async def get_raster_tile(
    layer: str,
    date_str: str,
    z: int,
    x: int,
    y: int,
    fmt: str = "png",
    db: Any | None = None,
    redis: Any | None = None,
) -> TileResult:
    """Serve a cached or freshly rendered 256x256 RGBA Web Mercator raster tile."""
    valid_layer, valid_date, valid_fmt = validate_tile_request(layer, date_str, z, x, y, fmt)
    settings = get_settings()
    tile_cache_dir = Path(settings.TILE_CACHE_DIR)
    cache_control = (
        "public, max-age=1800" if valid_date == "latest" else "public, max-age=3600"
    )
    media_type = MEDIA_TYPES[valid_fmt]

    dataset_id, dataset_path, resolved_date, source_key, timestamp_utc = (
        await _resolve_dataset_metadata(db, tile_cache_dir, valid_layer, valid_date)
    )
    render_cache_root = tile_cache_dir / TILE_CACHE_VERSION
    cache_key = (
        f"tile:{TILE_CACHE_VERSION}:{valid_layer}:{resolved_date}:{z}:{x}:{y}:{valid_fmt}"
    )

    # 1. Check Redis metadata cache + disk file
    if redis is not None:
        try:
            cached_raw = await redis.get(cache_key)
            if cached_raw:
                meta = json.loads(cached_raw)
                cached_path = Path(str(meta["file_path"]))
                content_opt = await asyncio.to_thread(_read_if_file_sync, cached_path)
                if content_opt is not None:
                    is_empty = bool(meta.get("is_empty", False))
                    etag = str(meta.get("etag") or hashlib.sha256(content_opt).hexdigest())
                    return TileResult(
                        content=content_opt,
                        media_type=media_type,
                        cache_status="EMPTY" if is_empty else "HIT",
                        data_source=str(meta.get("source_key") or source_key),
                        dataset_timestamp_utc=str(
                            meta.get("timestamp_utc") or timestamp_utc
                        ),
                        cache_control=cache_control,
                        etag=etag,
                    )
        except Exception as exc:
            logger.debug("Redis tile cache lookup failed, continuing to disk/render: %s", exc)

    # 2. Check expected disk path directly
    expected_tile_path = (
        render_cache_root / valid_layer / resolved_date / str(z) / str(x) / f"{y}.{valid_fmt}"
    )
    disk_content = await asyncio.to_thread(_read_if_file_sync, expected_tile_path)
    if disk_content is not None:
        is_empty = await asyncio.to_thread(_is_tile_alpha_empty, disk_content)
        etag = hashlib.sha256(disk_content).hexdigest()
        await _set_redis_tile_meta(
            redis,
            cache_key,
            {
                "file_path": str(expected_tile_path),
                "is_empty": is_empty,
                "source_key": source_key,
                "timestamp_utc": timestamp_utc,
                "etag": etag,
            },
        )
        return TileResult(
            content=disk_content,
            media_type=media_type,
            cache_status="EMPTY" if is_empty else "HIT",
            data_source=source_key,
            dataset_timestamp_utc=timestamp_utc,
            cache_control=cache_control,
            etag=etag,
        )

    # 3. Render tile on demand and populate disk, DB index, and Redis
    if valid_layer == "potential":
        _, sst_path, _, _, _ = await _resolve_dataset_metadata(
            db, tile_cache_dir, "sst", valid_date
        )
        _, chl_path, _, _, _ = await _resolve_dataset_metadata(
            db, tile_cache_dir, "chlorophyll", valid_date
        )
        tile_path, byte_size, is_empty, etag = await asyncio.to_thread(
            render_potential_tile_to_cache,
            sst_path,
            chl_path,
            render_cache_root,
            resolved_date,
            z,
            x,
            y,
            valid_fmt,
        )
    else:
        tile_path, byte_size, is_empty, etag = await asyncio.to_thread(
            render_tile_to_cache,
            dataset_path,
            render_cache_root,
            valid_layer,
            resolved_date,
            z,
            x,
            y,
            valid_fmt,
        )
    content = await asyncio.to_thread(_read_bytes_sync, tile_path)

    await _record_tile_index(
        db=db,
        dataset_id=dataset_id,
        layer=valid_layer,
        resolved_date=resolved_date,
        z=z,
        x=x,
        y=y,
        fmt=valid_fmt,
        tile_path=tile_path,
        byte_size=byte_size,
        is_empty=is_empty,
        etag=etag,
    )
    await _set_redis_tile_meta(
        redis,
        cache_key,
        {
            "file_path": str(tile_path),
            "is_empty": is_empty,
            "source_key": source_key,
            "timestamp_utc": timestamp_utc,
            "etag": etag,
        },
    )

    return TileResult(
        content=content,
        media_type=media_type,
        cache_status="EMPTY" if is_empty else "MISS",
        data_source=source_key,
        dataset_timestamp_utc=timestamp_utc,
        cache_control=cache_control,
        etag=etag,
    )
