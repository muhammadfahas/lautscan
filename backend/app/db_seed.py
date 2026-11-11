"""WPP-NRI GeoJSON seed loader and PostGIS upsert helper."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

EXPECTED_WPP_CODES: frozenset[str] = frozenset(
    {"571", "572", "573", "711", "712", "713", "714", "715", "716", "717", "718"}
)

_WPP_RELATIVE_PATH = Path("data") / "wpp-nri" / "wpp_nri_zones.json"


def _default_seed_path() -> Path:
    """Resolve `data/wpp-nri/wpp_nri_zones.json` cleanly without requiring third-party libs."""
    candidates: list[Path] = []
    for parent in Path(__file__).resolve().parents[:4]:
        candidates.append(parent / _WPP_RELATIVE_PATH)
    candidates.extend(
        [
            Path("/app") / _WPP_RELATIVE_PATH,
            Path.cwd() / _WPP_RELATIVE_PATH,
            Path.cwd().parent / _WPP_RELATIVE_PATH,
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    parents = Path(__file__).resolve().parents
    fallback_root = parents[2] if len(parents) > 2 else parents[-1]
    return fallback_root / _WPP_RELATIVE_PATH


def _resolve_seed_path(seed_path: Path | None) -> Path:
    if seed_path is not None:
        return Path(seed_path)
    try:
        from app.core.config import get_settings

        return get_settings().WPP_SEED_PATH
    except Exception:
        return _default_seed_path()


def load_wpp_seed_records(
    seed_path: Path | None = None,
    include_geometry: bool = True,
) -> list[dict[str, Any]]:
    """Parse `wpp_nri_zones.json` into flat dicts aligned 1:1 with `WppZoneRecord`."""
    resolved_path = _resolve_seed_path(seed_path)
    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError(f"Expected GeoJSON FeatureCollection in {resolved_path}")

    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError(f"Expected GeoJSON features list in {resolved_path}")

    records: list[dict[str, Any]] = []
    seen_codes: set[str] = set()

    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError("Invalid GeoJSON Feature entry in WPP-NRI seed file")

        props = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(props, dict) or not isinstance(geometry, dict):
            raise ValueError("WPP-NRI feature is missing properties or geometry")

        wpp_code = str(props.get("wpp_code", "")).strip()
        if wpp_code not in EXPECTED_WPP_CODES:
            raise ValueError(f"Unexpected WPP-NRI code: {wpp_code!r}")
        if wpp_code in seen_codes:
            raise ValueError(f"Duplicate WPP-NRI code: {wpp_code!r}")
        seen_codes.add(wpp_code)

        geom_type = geometry.get("type")
        if geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"Unsupported geometry type {geom_type!r} for WPP {wpp_code}")

        area_raw = props.get("area_km2")
        area_km2 = float(area_raw) if area_raw is not None else None

        records.append(
            {
                "wpp_code": wpp_code,
                "name": str(props["name"]),
                "waters_id": str(props["waters_id"]),
                "waters_en": str(props["waters_en"]),
                "legal_basis": str(props.get("legal_basis", "Permen-KP No. 18/PERMEN-KP/2014")),
                "geometry_source": str(props.get("geometry_source", "p0_seed")),
                "centroid_lat": float(props["centroid_lat"]),
                "centroid_lon": float(props["centroid_lon"]),
                "min_lon": float(props["min_lon"]),
                "min_lat": float(props["min_lat"]),
                "max_lon": float(props["max_lon"]),
                "max_lat": float(props["max_lat"]),
                "area_km2": area_km2,
                "sst_mean_c": None,
                "chlorophyll_mean_mg_m3": None,
                "latest_observation_utc": None,
                "geometry_geojson": (
                    json.dumps(geometry, separators=(",", ":")) if include_geometry else None
                ),
            }
        )

    missing_codes = EXPECTED_WPP_CODES - seen_codes
    if missing_codes:
        missing_sorted = ", ".join(sorted(missing_codes))
        raise ValueError(f"Missing WPP-NRI codes in seed file: {missing_sorted}")

    records.sort(key=lambda item: item["wpp_code"])
    return records


_UPSERT_WPP_SQL = """
INSERT INTO wpp_nri_zones (
    wpp_code,
    name,
    waters_id,
    waters_en,
    legal_basis,
    geometry_source,
    geom,
    centroid,
    min_lon,
    min_lat,
    max_lon,
    max_lat,
    area_km2
)
VALUES (
    :wpp_code,
    :name,
    :waters_id,
    :waters_en,
    :legal_basis,
    :geometry_source,
    ST_Multi(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(CAST(:geometry_geojson AS text)), 4326))),
    ST_SetSRID(
        ST_MakePoint(
            CAST(:centroid_lon AS double precision),
            CAST(:centroid_lat AS double precision)
        ),
        4326
    ),
    :min_lon,
    :min_lat,
    :max_lon,
    :max_lat,
    :area_km2
)
ON CONFLICT (wpp_code) DO UPDATE SET
    name = EXCLUDED.name,
    waters_id = EXCLUDED.waters_id,
    waters_en = EXCLUDED.waters_en,
    legal_basis = EXCLUDED.legal_basis,
    geometry_source = EXCLUDED.geometry_source,
    geom = EXCLUDED.geom,
    centroid = EXCLUDED.centroid,
    min_lon = EXCLUDED.min_lon,
    min_lat = EXCLUDED.min_lat,
    max_lon = EXCLUDED.max_lon,
    max_lat = EXCLUDED.max_lat,
    area_km2 = EXCLUDED.area_km2,
    updated_at = NOW();
"""


async def seed_wpp_nri(
    session: AsyncSession,
    seed_path: Path | None = None,
    *,
    commit: bool = True,
) -> int:
    """Upsert all 11 WPP-NRI zones into PostGIS with normalized SRID 4326 MultiPolygons."""
    from sqlalchemy import text

    records = load_wpp_seed_records(seed_path=seed_path, include_geometry=True)
    stmt = text(_UPSERT_WPP_SQL)

    for record in records:
        await session.execute(
            stmt,
            {
                "wpp_code": record["wpp_code"],
                "name": record["name"],
                "waters_id": record["waters_id"],
                "waters_en": record["waters_en"],
                "legal_basis": record["legal_basis"],
                "geometry_source": record["geometry_source"],
                "geometry_geojson": record["geometry_geojson"],
                "centroid_lon": record["centroid_lon"],
                "centroid_lat": record["centroid_lat"],
                "min_lon": record["min_lon"],
                "min_lat": record["min_lat"],
                "max_lon": record["max_lon"],
                "max_lat": record["max_lat"],
                "area_km2": record["area_km2"],
            },
        )

    if commit:
        await session.commit()
    else:
        await session.flush()

    return len(records)


async def _seed_cli() -> int:
    from app.core.db import async_session_maker

    async with async_session_maker() as session:
        return await seed_wpp_nri(session)


if __name__ == "__main__":
    seeded = asyncio.run(_seed_cli())
    print(f"Seeded {seeded} WPP-NRI zones.")
