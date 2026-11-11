"""Coordinate-level oceanographic interpolation and WPP-NRI point inspection service."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from app.core.config import get_settings
from app.db_seed import load_wpp_seed_records
from app.etl.base import CATALOG
from app.etl.fixtures import ensure_sample_netcdf
from app.etl.tiler import _load_layer_grid, sample_point_from_netcdf
from app.schemas.common import MapPointInspection

try:
    from sqlalchemy import func, select
except ImportError:  # pragma: no cover - optional when sqlalchemy is absent locally
    func = None  # type: ignore[assignment]
    select = None  # type: ignore[assignment]

try:
    from app.models.spatial import RasterDataset, WppNriZone
except ImportError:  # pragma: no cover - optional when sqlalchemy models cannot load
    RasterDataset = None  # type: ignore[assignment,misc]
    WppNriZone = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

POINT_CACHE_TTL_SECONDS = 1800
MPS_TO_KNOTS = 1.94384
COMPASS_16: tuple[str, ...] = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
)
DEFAULT_DISCLAIMER = (
    "Satellite and historical oceanographic estimates carry acquisition latency and spatial "
    "resolution limits; they do not guarantee fish presence at exact coordinates and do not "
    "substitute official maritime navigation or weather advisories (BMKG, Pushidrosal, Basarnas)."
)
DEFAULT_ATTRIBUTION = (
    "NOAA CoastWatch / ERDDAP (Public Domain); WPP-NRI Boundaries (Permen-KP No. 18/2014)"
)


class PointQueryValidationError(ValueError):
    """Raised when point inspection query parameters are invalid."""


def degrees_to_compass_16(direction_deg: float) -> str:
    """Convert bearing in degrees [0, 360) to 16-point compass cardinal label."""
    normalized = direction_deg % 360.0
    index = int((normalized + 11.25) // 22.5) % 16
    return COMPASS_16[index]


def _point_on_segment(
    px: float,
    py: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    eps: float = 1e-9,
) -> bool:
    in_x = min(x1, x2) - eps <= px <= max(x1, x2) + eps
    in_y = min(y1, y2) - eps <= py <= max(y1, y2) + eps
    if in_x and in_y:
        cross = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
        return abs(cross) <= eps * max(1.0, abs(x2 - x1) + abs(y2 - y1))
    return False


def _point_in_ring(lon: float, lat: float, ring: Sequence[Sequence[float]]) -> bool:
    """Ray-casting point-in-ring test (inclusive of boundary segments)."""
    if len(ring) < 3:
        return False
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = float(ring[i][0]), float(ring[i][1])
        x2, y2 = float(ring[(i + 1) % n][0]), float(ring[(i + 1) % n][1])
        if _point_on_segment(lon, lat, x1, y1, x2, y2):
            return True
        if (y1 > lat) != (y2 > lat):
            x_intersect = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < x_intersect:
                inside = not inside
    return inside


def point_in_geojson_geometry(lon: float, lat: float, geometry: dict[str, Any]) -> bool:
    """Test whether (lon, lat) lies inside an RFC 7946 Polygon or MultiPolygon."""
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return False

    if geom_type == "Polygon":
        if not _point_in_ring(lon, lat, coords[0]):
            return False
        return not any(_point_in_ring(lon, lat, hole) for hole in coords[1:])

    if geom_type == "MultiPolygon":
        for poly in coords:
            if (
                poly
                and _point_in_ring(lon, lat, poly[0])
                and not any(_point_in_ring(lon, lat, hole) for hole in poly[1:])
            ):
                return True
        return False

    return False


def _get_field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _find_wpp_in_seed(lat: float, lon: float) -> tuple[str | None, str | None, str | None]:
    """Perform point-in-polygon WPP-NRI zone containment against local seed records."""
    try:
        records = load_wpp_seed_records()
    except Exception as exc:
        logger.warning("Unable to load WPP seed records for fallback containment: %s", exc)
        return None, None, None

    for rec in records:
        min_lon = _get_field(rec, "min_lon")
        max_lon = _get_field(rec, "max_lon")
        min_lat = _get_field(rec, "min_lat")
        max_lat = _get_field(rec, "max_lat")
        if (
            min_lon is not None
            and max_lon is not None
            and min_lat is not None
            and max_lat is not None
            and not (
                float(min_lon) <= lon <= float(max_lon) and float(min_lat) <= lat <= float(max_lat)
            )
        ):
            continue

        geometry = _get_field(rec, "geometry")
        if geometry is None:
            raw_geojson = _get_field(rec, "geometry_geojson")
            if isinstance(raw_geojson, str) and raw_geojson:
                geometry = json.loads(raw_geojson)
        if isinstance(geometry, dict) and point_in_geojson_geometry(lon, lat, geometry):
            return (
                str(_get_field(rec, "wpp_code")),
                str(_get_field(rec, "name")),
                str(_get_field(rec, "waters_id")),
            )
    return None, None, None


async def _find_wpp_zone(
    lat: float,
    lon: float,
    db: Any | None,
) -> tuple[str | None, str | None, str | None]:
    """Check WPP-NRI zone containment via PostGIS ST_Contains or seed polygon fallback."""
    if db is not None and select is not None and func is not None and WppNriZone is not None:
        try:
            has_any_stmt = select(WppNriZone.wpp_code).limit(1)
            any_zone = (await db.execute(has_any_stmt)).scalar_one_or_none()
            if any_zone is not None:
                point_geom = func.ST_SetSRID(func.ST_Point(lon, lat), 4326)
                stmt = (
                    select(WppNriZone.wpp_code, WppNriZone.name, WppNriZone.waters_id)
                    .where(func.ST_Contains(WppNriZone.geom, point_geom))
                    .limit(1)
                )
                row = (await db.execute(stmt)).first()
                if row is None:
                    return None, None, None
                return str(row[0]), str(row[1]), str(row[2])
        except Exception as exc:
            logger.debug("PostGIS WPP containment failed, falling back to seed polygons: %s", exc)

    return await asyncio.to_thread(_find_wpp_in_seed, lat, lon)


def _is_file_sync(path: Path) -> bool:
    return path.is_file()


async def _resolve_layer_dataset(
    db: Any | None,
    tile_cache_dir: Path,
    layer: str,
    requested_date: str,
) -> tuple[Path, str, datetime, str, float | None, bool]:
    """Resolve dataset path, resolved_date, acquired_at_utc, source_key, res_km, is_fallback."""
    if db is not None and select is not None and RasterDataset is not None:
        try:
            stmt = select(RasterDataset).where(
                RasterDataset.layer == layer,
                RasterDataset.status == "ready",
            )
            if requested_date != "latest":
                target_d = date.fromisoformat(requested_date)
                stmt = stmt.where(RasterDataset.acquisition_date <= target_d)
            stmt = stmt.order_by(RasterDataset.acquisition_date.desc()).limit(1)
            row = (await db.execute(stmt)).scalar_one_or_none()
            if row is not None and await asyncio.to_thread(_is_file_sync, Path(str(row.file_path))):
                resolved = row.acquisition_date.isoformat()
                acq_dt: datetime = row.acquired_at_utc
                if acq_dt.tzinfo is None:
                    acq_dt = acq_dt.replace(tzinfo=UTC)
                is_fallback = requested_date != "latest" and resolved != requested_date
                return (
                    Path(str(row.file_path)),
                    resolved,
                    acq_dt.astimezone(UTC),
                    str(row.source_key),
                    float(row.spatial_resolution_km),
                    is_fallback,
                )
        except Exception as exc:
            logger.debug("DB raster dataset lookup failed for %s: %s", layer, exc)

    if requested_date == "latest":
        global_nc = tile_cache_dir / "global" / f"noaa_{layer}.nc"
        if await asyncio.to_thread(_is_file_sync, global_nc):
            grid_meta = await asyncio.to_thread(_load_layer_grid, global_nc, layer)
            parsed_dt = _parse_iso_utc(grid_meta.acquired_at_utc) or datetime.now(UTC)
            resolved_d = parsed_dt.date().isoformat()
            return (
                global_nc,
                resolved_d,
                parsed_dt,
                "noaa_erddap",
                None,
                False,
            )

    fallback_date = (
        datetime.now(UTC).date().isoformat() if requested_date == "latest" else requested_date
    )
    dataset_path = await asyncio.to_thread(
        ensure_sample_netcdf, tile_cache_dir, layer, fallback_date
    )
    fallback_dt = datetime.fromisoformat(f"{fallback_date}T12:00:00+00:00")
    return dataset_path, fallback_date, fallback_dt, "noaa_erddap", None, True


def _parse_iso_utc(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=UTC) if raw.tzinfo is None else raw.astimezone(UTC)
    if not isinstance(raw, str) or not raw.strip():
        return None
    normalized = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _as_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        num = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    return num


def _build_attribution(source_keys: set[str]) -> str:
    parts: list[str] = []
    for key in sorted(source_keys):
        meta = CATALOG.get(key)
        if meta is not None:
            attr = meta["attribution"] if isinstance(meta, dict) else meta.attribution
            parts.append(str(attr))
    return "; ".join(parts) if parts else DEFAULT_ATTRIBUTION


async def inspect_map_point(
    lat: float,
    lon: float,
    requested_date: str = "latest",
    db: Any | None = None,
    redis: Any | None = None,
) -> MapPointInspection:
    """Inspect interpolated oceanographic values and WPP-NRI zone at (lat, lon, date)."""
    if not (-90.0 <= lat <= 90.0):
        raise PointQueryValidationError(f"Latitude {lat} out of valid range [-90, 90].")
    if not (-180.0 <= lon <= 180.0):
        raise PointQueryValidationError(f"Longitude {lon} out of valid range [-180, 180].")
    if requested_date != "latest":
        try:
            date.fromisoformat(requested_date)
        except ValueError as exc:
            raise PointQueryValidationError(
                f"Invalid calendar date '{requested_date}'; expected YYYY-MM-DD."
            ) from exc

    cache_key = f"point:{lat:.3f}:{lon:.3f}:{requested_date}"
    if redis is not None:
        try:
            cached_raw = await redis.get(cache_key)
            if cached_raw:
                cached = MapPointInspection.model_validate_json(cached_raw)
                return cached.model_copy(
                    update={"lat": lat, "lon": lon, "requested_date": requested_date}
                )
        except Exception as exc:
            logger.debug("Redis point cache lookup failed: %s", exc)

    settings = get_settings()
    tile_cache_dir = Path(settings.TILE_CACHE_DIR)

    wpp_code, wpp_name, wpp_waters_id = await _find_wpp_zone(lat, lon, db)

    layer_results: dict[str, dict[str, Any]] = {}
    resolved_dates: list[str] = []
    acquired_times: list[datetime] = []
    resolutions: list[float] = []
    source_keys: set[str] = set()
    any_fallback = False

    for layer in ("sst", "chlorophyll", "currents"):
        ds_path, res_date, acq_dt, source_key, res_km, is_fb = await _resolve_layer_dataset(
            db, tile_cache_dir, layer, requested_date
        )
        sample = await asyncio.to_thread(sample_point_from_netcdf, ds_path, layer, lat, lon)
        layer_results[layer] = sample
        resolved_dates.append(res_date)
        sample_acq = _parse_iso_utc(sample.get("acquired_at_utc"))
        acquired_times.append(sample_acq or acq_dt)
        sample_res = _as_float(sample.get("spatial_resolution_km"))
        if res_km is not None:
            resolutions.append(res_km)
        elif sample_res is not None:
            resolutions.append(sample_res)
        sample_src = sample.get("primary_source")
        source_keys.add(str(sample_src) if sample_src else source_key)
        any_fallback = any_fallback or is_fb

    sst_sample = layer_results["sst"]
    chl_sample = layer_results["chlorophyll"]
    cur_sample = layer_results["currents"]

    sst_c = _as_float(sst_sample.get("sst_c") if "sst_c" in sst_sample else sst_sample.get("value"))
    sst_f = round((sst_c * 9.0 / 5.0) + 32.0, 2) if sst_c is not None else None
    if sst_c is not None:
        sst_c = round(sst_c, 2)

    chl_val = _as_float(
        chl_sample.get("chlorophyll_mg_m3")
        if "chlorophyll_mg_m3" in chl_sample
        else chl_sample.get("value")
    )
    chlorophyll_mg_m3 = round(chl_val, 4) if chl_val is not None else None

    speed_ms = _as_float(
        cur_sample.get("current_speed_ms")
        if "current_speed_ms" in cur_sample
        else cur_sample.get("speed_ms")
    )
    direction_deg = _as_float(
        cur_sample.get("current_direction_deg")
        if "current_direction_deg" in cur_sample
        else cur_sample.get("direction_deg")
    )
    if speed_ms is None or direction_deg is None:
        u_ms = _as_float(cur_sample.get("u_ms"))
        v_ms = _as_float(cur_sample.get("v_ms"))
        if u_ms is not None and v_ms is not None:
            speed_ms = math.hypot(u_ms, v_ms)
            direction_deg = (math.degrees(math.atan2(u_ms, v_ms)) + 360.0) % 360.0

    current_speed_ms = round(speed_ms, 3) if speed_ms is not None else None
    current_speed_knots = round(speed_ms * MPS_TO_KNOTS, 3) if speed_ms is not None else None
    current_direction_deg = round(direction_deg, 1) if direction_deg is not None else None
    current_compass = degrees_to_compass_16(direction_deg) if direction_deg is not None else None

    salinity_psu = _as_float(sst_sample.get("salinity_psu") or cur_sample.get("salinity_psu"))
    wave_height_m = _as_float(cur_sample.get("wave_height_m") or sst_sample.get("wave_height_m"))

    methods = [
        str(sample.get("interpolation_method") or "unavailable")
        for sample in (sst_sample, chl_sample, cur_sample)
    ]
    has_any_value = any(v is not None for v in (sst_c, chlorophyll_mg_m3, current_speed_ms))
    interp_method: Literal["bilinear", "nearest", "unavailable"]
    if not has_any_value:
        interp_method = "unavailable"
    elif "bilinear" in methods:
        interp_method = "bilinear"
    elif "nearest" in methods:
        interp_method = "nearest"
    else:
        interp_method = "unavailable"

    resolved_date = resolved_dates[0] if has_any_value and resolved_dates else None
    acquired_at_utc = max(acquired_times) if has_any_value and acquired_times else None
    spatial_resolution_km = (
        round(sum(resolutions) / len(resolutions), 2) if has_any_value and resolutions else None
    )
    primary_source = sorted(source_keys)[0] if has_any_value and source_keys else None

    result = MapPointInspection(
        lat=lat,
        lon=lon,
        requested_date=requested_date,
        resolved_date=resolved_date,
        wpp_code=wpp_code,
        wpp_name=wpp_name,
        wpp_waters_id=wpp_waters_id,
        sst_c=sst_c,
        sst_f=sst_f,
        chlorophyll_mg_m3=chlorophyll_mg_m3,
        current_speed_ms=current_speed_ms,
        current_speed_knots=current_speed_knots,
        current_direction_deg=current_direction_deg,
        current_compass=current_compass,
        salinity_psu=salinity_psu,
        wave_height_m=wave_height_m,
        interpolation_method=interp_method,
        spatial_resolution_km=spatial_resolution_km,
        primary_source=primary_source,
        attribution=_build_attribution(source_keys),
        acquired_at_utc=acquired_at_utc,
        is_cached_fallback=any_fallback,
        disclaimer=DEFAULT_DISCLAIMER,
    )

    if redis is not None:
        try:
            await redis.set(cache_key, result.model_dump_json(), ex=POINT_CACHE_TTL_SECONDS)
        except Exception as exc:
            logger.debug("Skipping Redis point cache write: %s", exc)

    return result
