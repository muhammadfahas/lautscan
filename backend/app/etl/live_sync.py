"""Sync live global NOAA CoastWatch ERDDAP and OBIS v3 data into local disk cache.

Enables local deployments without PostGIS/Redis to serve real global satellite
grids (SST, Chlorophyll-a, Currents) and real OBIS biodiversity occurrences across
all 11 Indonesian WPP-NRI zones.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.etl.base import INDONESIA_BBOX
from app.etl.noaa_erddap import (
    DEFAULT_ERDDAP_DATASETS,
    ErddapDatasetSpec,
    NOAAErddapAdapter,
)
from app.etl.obis_client import ObisClient
from app.etl.tiler import sample_point_from_netcdf
from app.services.point_query import _find_wpp_in_seed
from app.services.species_service import BASELINE_OBIS_FIXTURES

logger = logging.getLogger(__name__)

TARGET_INDONESIAN_TAXONS: tuple[str, ...] = (
    "Thunnus albacares",
    "Thunnus obesus",
    "Katsuwonus pelamis",
    "Euthynnus affinis",
    "Rastrelliger kanagurta",
    "Rastrelliger brachysoma",
    "Decapterus russelli",
    "Scomberomorus commerson",
    "Lutjanus malabaricus",
    "Epinephelus coioides",
    "Sardinella lemuru",
    "Coryphaena hippurus",
    "Cheilinus undulatus",
    "Penaeus monodon",
)


def _atomic_write_json(target_path: Path, payload: dict[str, Any]) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, indent=2, ensure_ascii=True).encode("utf-8")
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tf:
            tmp_path = tf.name
            tf.write(raw)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tmp_path, target_path)
    except Exception:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _atomic_copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = src.read_bytes()
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=dest.parent,
            prefix=f".{dest.name}.",
            suffix=".tmp",
            delete=False,
        ) as tf:
            tmp_path = tf.name
            tf.write(data)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tmp_path, dest)
    except Exception:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _locate_wpp_code(lat: float, lon: float) -> str | None:
    return _find_wpp_in_seed(lat, lon)[0]


def _is_too_close(
    lat: float,
    lon: float,
    existing: list[tuple[float, float]],
    min_deg: float = 0.22,
) -> bool:
    return any(abs(lat - elat) < min_deg and abs(lon - elon) < min_deg for elat, elon in existing)


async def sync_global_obis_cache(global_dir: Path, per_taxon_limit: int = 35) -> dict[str, Any]:
    """Fetch real OBIS v3 occurrences across Indonesian waters and write JSON cache."""
    client = ObisClient(wpp_locator=_locate_wpp_code, timeout_s=25.0)
    sst_nc = global_dir / "noaa_sst.nc"
    has_sst_mask = sst_nc.is_file()
    per_taxon_totals: dict[str, int] = {}
    selected_records: list[dict[str, Any]] = []
    seen_coords_by_taxon: dict[str, list[tuple[float, float]]] = {}
    covered_wpps: set[str] = set()

    for taxon in TARGET_INDONESIAN_TAXONS:
        res = await client.fetch_occurrences(
            taxon=taxon,
            bbox=INDONESIA_BBOX,
            limit=per_taxon_limit,
        )
        if not res.ok:
            logger.warning("OBIS sync skipped for %s: %s", taxon, res.error)
            continue
        per_taxon_totals[taxon] = res.total_available
        coords_list = seen_coords_by_taxon.setdefault(taxon, [])

        # Keep records that resolve inside Indonesian 11 WPP zones and real ocean water
        ranked = sorted(
            res.records,
            key=lambda r: (
                0 if r.wpp_code else 1,
                -(r.individual_count or 0),
                -(1 if r.depth_m is not None else 0),
                r.id,
            ),
        )
        kept = 0
        for rec in ranked:
            if not rec.wpp_code:
                continue
            if _is_too_close(rec.lat, rec.lon, coords_list, min_deg=0.35):
                continue
            if has_sst_mask:
                try:
                    sst_pt = sample_point_from_netcdf(sst_nc, "sst", rec.lat, rec.lon)
                    if sst_pt.get("sst_c") is None:
                        continue
                except Exception:
                    pass
            coords_list.append((rec.lat, rec.lon))
            covered_wpps.add(rec.wpp_code)
            selected_records.append(rec.to_dict())
            kept += 1
            if kept >= 8:
                break

    # Ensure every WPP zone keeps baseline representation if OBIS has sparse ocean points
    for base_rec in BASELINE_OBIS_FIXTURES:
        if base_rec.wpp_code and base_rec.wpp_code not in covered_wpps:
            selected_records.append(base_rec.model_dump(mode="json"))
            covered_wpps.add(base_rec.wpp_code)

    manifest = {
        "synced_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "obis_v3_global",
        "total_cached": len(selected_records),
        "obis_indonesia_taxon_totals": per_taxon_totals,
        "total_obis_matching": sum(per_taxon_totals.values()),
        "items": selected_records,
    }
    _atomic_write_json(global_dir / "obis_species.json", manifest)
    return {
        "total_cached": len(selected_records),
        "total_obis_matching": manifest["total_obis_matching"],
        "covered_wpps": sorted(covered_wpps),
    }


async def sync_global_noaa_cache(global_dir: Path) -> dict[str, Any]:
    """Download global NOAA CoastWatch ERDDAP NetCDF grids into `global_dir`."""
    specs = dict(DEFAULT_ERDDAP_DATASETS)
    specs["sst"] = ErddapDatasetSpec(
        layer="sst",
        dataset_id="jplMURSST41",
        variables=("analysed_sst",),
        units="degree_C",
        spatial_resolution_km=5.0,
        has_altitude_dim=False,
        stride=5,
    )
    noaa = NOAAErddapAdapter(datasets=specs, timeout_s=35.0)
    results: dict[str, Any] = {}

    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        for layer in ("sst", "chlorophyll", "currents"):
            res = await noaa.fetch_layer_netcdf(layer, output_dir=tmp_dir, target_date="latest")
            if not res.ok or res.file_path is None:
                results[layer] = {"ok": False, "error": res.error}
                continue

            dest = global_dir / f"noaa_{layer}.nc"
            _atomic_copy_file(res.file_path, dest)
            sample = sample_point_from_netcdf(dest, layer, -5.5, 110.5)
            results[layer] = {
                "ok": True,
                "dataset_id": res.dataset_id,
                "bytes": res.byte_size,
                "acquired_at_utc": sample.get("acquired_at_utc"),
                "sample_java_sea": sample.get("value"),
            }

        # Prefer cloud-free VIIRS monthly chlorophyll (2026 global ocean color) when valid
        viirs_monthly = {
            "chlorophyll": ErddapDatasetSpec(
                layer="chlorophyll",
                dataset_id="nesdisVHNSQchlaMonthly",
                variables=("chlor_a",),
                units="mg m-3",
                spatial_resolution_km=4.0,
                has_altitude_dim=True,
                altitude_value="0.0",
                stride=2,
            )
        }
        try:
            viirs_noaa = NOAAErddapAdapter(datasets=viirs_monthly, timeout_s=30.0)
            v_res = await viirs_noaa.fetch_layer_netcdf(
                "chlorophyll", output_dir=tmp_dir, target_date="latest"
            )
            if v_res.ok and v_res.file_path is not None:
                v_sample = sample_point_from_netcdf(v_res.file_path, "chlorophyll", -5.5, 110.5)
                if v_sample.get("value") is not None:
                    dest = global_dir / "noaa_chlorophyll.nc"
                    _atomic_copy_file(v_res.file_path, dest)
                    results["chlorophyll"] = {
                        "ok": True,
                        "dataset_id": "nesdisVHNSQchlaMonthly",
                        "bytes": v_res.byte_size,
                        "acquired_at_utc": v_sample.get("acquired_at_utc"),
                        "sample_java_sea": v_sample.get("value"),
                    }
        except Exception as exc:
            logger.debug("Optional VIIRS monthly chlorophyll skipped: %s", exc)

    _atomic_write_json(
        global_dir / "noaa_manifest.json",
        {
            "synced_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "layers": results,
        },
    )
    return results


async def sync_all_global(cache_dir: Path) -> dict[str, Any]:
    """Run NOAA ERDDAP download then OBIS marine occurrence validation into `cache_dir/global`."""
    global_dir = cache_dir / "global"
    global_dir.mkdir(parents=True, exist_ok=True)
    noaa_res = await sync_global_noaa_cache(global_dir)
    obis_res = await sync_global_obis_cache(global_dir)
    return {"obis": obis_res, "noaa": noaa_res}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync live OBIS & NOAA global caches")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Target TILE_CACHE_DIR (defaults to configured settings.TILE_CACHE_DIR)",
    )
    args = parser.parse_args()
    cache_dir = args.cache_dir or Path(get_settings().TILE_CACHE_DIR)
    summary = asyncio.run(sync_all_global(cache_dir))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
