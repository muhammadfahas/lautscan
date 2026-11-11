"""Deterministic CF-compliant offline NetCDF sample fixtures for Indonesian waters.

Generates realistic oceanographic grids over Indonesia (``lon 90..145``,
``lat -15..10``) for ``sst``, ``chlorophyll``, and ``currents`` (``u_ms``,
``v_ms``) so local PoC rendering, XYZ tiles, and point inspection operate
out-of-the-box without requiring live external satellite fetches.
"""

from __future__ import annotations

import math
import os
import struct
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from app.etl.tiler import (
    INDONESIA_LAT_MAX,
    INDONESIA_LAT_MIN,
    INDONESIA_LON_MAX,
    INDONESIA_LON_MIN,
)

GRID_STEP_DEG: float = 0.25
SPATIAL_RESOLUTION_KM: float = round(GRID_STEP_DEG * 111.32, 2)

# Coarse representative landmass polygons inside lon [90, 145], lat [-15, 10]
# so tiles and coastal point inspection reflect real Indonesian archipelago seas.
_LAND_POLYGONS: tuple[tuple[tuple[float, float], ...], ...] = (
    # Sumatra
    (
        (95.4, 5.4),
        (96.2, 5.2),
        (99.4, 2.5),
        (103.2, -0.5),
        (105.7, -5.7),
        (104.5, -5.8),
        (100.8, -1.6),
        (97.3, 1.8),
    ),
    # Java
    (
        (105.3, -6.3),
        (108.2, -6.5),
        (114.2, -7.8),
        (114.4, -8.4),
        (106.2, -7.3),
        (105.3, -6.7),
    ),
    # Borneo / Kalimantan
    (
        (109.2, 1.5),
        (112.5, 2.5),
        (117.5, 6.2),
        (118.8, 4.8),
        (117.5, 1.0),
        (116.2, -3.5),
        (111.5, -3.1),
        (109.8, -1.5),
    ),
    # Sulawesi
    (
        (119.2, -5.4),
        (119.5, -1.2),
        (120.4, 1.0),
        (124.8, 1.5),
        (125.1, 0.8),
        (121.6, 0.2),
        (121.2, -1.0),
        (122.9, -3.5),
        (122.1, -4.6),
        (120.7, -2.8),
        (120.1, -5.3),
    ),
    # Papua
    (
        (132.5, -1.8),
        (134.0, -1.0),
        (134.2, -2.5),
        (136.5, -2.2),
        (141.0, -2.6),
        (144.8, -6.5),
        (143.5, -8.8),
        (138.0, -8.3),
        (135.0, -4.5),
        (132.5, -3.2),
    ),
    # Malay Peninsula
    (
        (100.0, 10.0),
        (103.5, 10.0),
        (104.2, 1.5),
        (103.6, 1.3),
        (101.0, 3.5),
        (100.0, 6.5),
    ),
    # Northern Australia
    (
        (122.0, -15.0),
        (144.0, -15.0),
        (142.5, -11.0),
        (136.8, -12.2),
        (131.0, -12.4),
        (129.0, -14.0),
    ),
)


def _resolve_target_date(target_date: str) -> tuple[str, int]:
    if target_date == "latest":
        dt = datetime.now(UTC)
        return (dt.strftime("%Y-%m-%d"), dt.timetuple().tm_yday)
    try:
        dt = datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError as err:
        raise ValueError(
            f"Invalid target_date {target_date!r}; expected 'YYYY-MM-DD' or 'latest'"
        ) from err
    return (target_date, dt.timetuple().tm_yday)


def _points_in_polygon(
    lon_2d: NDArray[np.float64],
    lat_2d: NDArray[np.float64],
    poly: tuple[tuple[float, float], ...],
) -> NDArray[np.bool_]:
    inside = np.zeros(lon_2d.shape, dtype=np.bool_)
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cond = (y1 > lat_2d) != (y2 > lat_2d)
        denom = (y2 - y1) if y2 != y1 else 1e-12
        x_int = (x2 - x1) * (lat_2d - y1) / denom + x1
        inside ^= cond & (lon_2d < x_int)
    return inside


def _build_land_mask(lon_1d: NDArray[np.float64], lat_1d: NDArray[np.float64]) -> NDArray[np.bool_]:
    lon_2d, lat_2d = np.meshgrid(lon_1d, lat_1d)
    mask = np.zeros(lon_2d.shape, dtype=np.bool_)
    for poly in _LAND_POLYGONS:
        mask |= _points_in_polygon(lon_2d, lat_2d, poly)
    return mask


def _synthesize_layer_arrays(
    layer: str,
    lon_1d: NDArray[np.float64],
    lat_1d: NDArray[np.float64],
    day_of_year: int,
) -> dict[str, tuple[NDArray[np.float32], dict[str, Any]]]:
    land_mask = _build_land_mask(lon_1d, lat_1d)
    lon_2d, lat_2d = np.meshgrid(lon_1d, lat_1d)
    phase = 2.0 * math.pi * (day_of_year / 365.0)

    if layer == "sst":
        sst_raw = (
            29.1
            - 0.085 * np.abs(lat_2d + 1.5)
            + 0.75 * np.cos(0.14 * (lon_2d - 122.0) + phase)
            + 0.65 * np.sin(0.22 * (lat_2d + 4.0) - phase)
            + 0.45 * np.cos(0.35 * (lon_2d - 105.0)) * np.sin(0.30 * lat_2d)
        )
        sst_out: NDArray[np.float32] = np.asarray(np.clip(sst_raw, 22.0, 32.8), dtype=np.float32)
        sst_out[land_mask] = np.float32(np.nan)
        return {
            "sst": (
                sst_out,
                {
                    "standard_name": "sea_surface_temperature",
                    "long_name": "Sea Surface Temperature",
                    "units": "degree_C",
                    "_FillValue": np.float32(np.nan),
                },
            )
        }

    if layer == "chlorophyll":
        # Higher productivity in shallow shelves (Java Sea, Arafura, Malacca) & upwelling
        shelf_boost = np.exp(-((lat_2d + 5.5) ** 2) / 18.0) * (
            0.6 + 0.4 * np.cos(0.16 * (lon_2d - 112.0))
        )
        upwelling = np.exp(-((lat_2d + 9.5) ** 2) / 8.0) * (
            0.5 + 0.5 * np.sin(0.18 * (lon_2d - 118.0) + phase)
        )
        log_chl = (
            -0.85
            + 0.75 * shelf_boost
            + 0.65 * upwelling
            + 0.20 * np.sin(0.25 * lon_2d + 0.30 * lat_2d + phase)
        )
        chl = np.clip(np.power(10.0, log_chl), 0.03, 5.5).astype(np.float32)
        chl[land_mask] = np.float32(np.nan)
        return {
            "chlorophyll": (
                chl,
                {
                    "standard_name": "mass_concentration_of_chlorophyll_a_in_sea_water",
                    "long_name": "Chlorophyll-a Concentration",
                    "units": "mg m-3",
                    "_FillValue": np.float32(np.nan),
                },
            )
        }

    if layer == "currents":
        # Indonesian Throughflow + monsoon drift circulation
        u_ms = (
            -0.32
            + 0.48 * np.cos(0.18 * (lat_2d + 2.0) + phase)
            + 0.25 * np.sin(0.12 * (lon_2d - 118.0))
        )
        v_ms = (
            -0.18 * np.cos(0.10 * (lon_2d - 119.0))
            + 0.36 * np.sin(0.20 * (lon_2d - 110.0) - phase)
            + 0.20 * np.cos(0.24 * lat_2d)
        )
        u_arr = np.clip(u_ms, -1.6, 1.6).astype(np.float32)
        v_arr = np.clip(v_ms, -1.4, 1.4).astype(np.float32)
        u_arr[land_mask] = np.float32(np.nan)
        v_arr[land_mask] = np.float32(np.nan)
        return {
            "u_ms": (
                u_arr,
                {
                    "standard_name": "eastward_sea_water_velocity",
                    "long_name": "Eastward Sea Water Velocity",
                    "units": "m s-1",
                    "_FillValue": np.float32(np.nan),
                },
            ),
            "v_ms": (
                v_arr,
                {
                    "standard_name": "northward_sea_water_velocity",
                    "long_name": "Northward Sea Water Velocity",
                    "units": "m s-1",
                    "_FillValue": np.float32(np.nan),
                },
            ),
        }

    raise ValueError(f"Unsupported layer {layer!r}; expected 'sst', 'chlorophyll', or 'currents'")


def _write_netcdf3_classic_pure(
    out_path: Path,
    lat_1d: NDArray[np.float64],
    lon_1d: NDArray[np.float64],
    data_vars: dict[str, tuple[NDArray[np.float32], dict[str, Any]]],
    global_attrs: dict[str, Any],
) -> None:
    """Write a CF-1.8 NetCDF-3 Classic (``CDF\\x01``) file with zero C dependencies."""

    def pack_nc_string(text: str) -> bytes:
        encoded = text.encode("utf-8")
        pad = (4 - (len(encoded) % 4)) % 4
        return struct.pack(">I", len(encoded)) + encoded + (b"\x00" * pad)

    def pack_attr_value(val: Any) -> tuple[int, int, bytes]:
        if isinstance(val, str):
            raw = val.encode("utf-8")
            pad = (4 - (len(raw) % 4)) % 4
            return (2, len(raw), raw + (b"\x00" * pad))
        if isinstance(val, np.float32):
            return (5, 1, struct.pack(">f", float(val)))
        if isinstance(val, (float, np.float64)):
            return (6, 1, struct.pack(">d", float(val)))
        if isinstance(val, int):
            return (4, 1, struct.pack(">i", int(val)))
        raw = str(val).encode("utf-8")
        pad = (4 - (len(raw) % 4)) % 4
        return (2, len(raw), raw + (b"\x00" * pad))

    def pack_att_list(attrs: dict[str, Any]) -> bytes:
        if not attrs:
            return struct.pack(">II", 0, 0)
        chunks = [struct.pack(">II", 12, len(attrs))]
        for name, val in attrs.items():
            nc_type, nelems, payload = pack_attr_value(val)
            chunks.append(pack_nc_string(name))
            chunks.append(struct.pack(">II", nc_type, nelems))
            chunks.append(payload)
        return b"".join(chunks)

    lat_attrs = {
        "standard_name": "latitude",
        "long_name": "Latitude",
        "units": "degrees_north",
        "axis": "Y",
    }
    lon_attrs = {
        "standard_name": "longitude",
        "long_name": "Longitude",
        "units": "degrees_east",
        "axis": "X",
    }

    var_specs: list[tuple[str, tuple[int, ...], int, NDArray[Any], dict[str, Any]]] = [
        ("lat", (0,), 6, np.asarray(lat_1d, dtype=">f8"), lat_attrs),
        ("lon", (1,), 6, np.asarray(lon_1d, dtype=">f8"), lon_attrs),
    ]
    for vname, (var_arr, vattrs) in data_vars.items():
        var_specs.append((vname, (0, 1), 5, np.asarray(var_arr, dtype=">f4"), vattrs))

    dims_block = b"".join(
        [
            struct.pack(">II", 10, 2),
            pack_nc_string("lat"),
            struct.pack(">I", lat_1d.size),
            pack_nc_string("lon"),
            struct.pack(">I", lon_1d.size),
        ]
    )
    gatts_block = pack_att_list(global_attrs)

    # First pass with placeholder offsets (0) to measure exact header size.
    def build_var_list(offsets: list[int]) -> bytes:
        chunks = [struct.pack(">II", 11, len(var_specs))]
        for idx, (vname, dim_ids, nc_type, arr_be, vattrs) in enumerate(var_specs):
            chunks.append(pack_nc_string(vname))
            chunks.append(struct.pack(">I", len(dim_ids)))
            for did in dim_ids:
                chunks.append(struct.pack(">I", did))
            chunks.append(pack_att_list(vattrs))
            vsize = arr_be.nbytes + ((4 - (arr_be.nbytes % 4)) % 4)
            chunks.append(struct.pack(">III", nc_type, vsize, offsets[idx]))
        return b"".join(chunks)

    prefix = b"CDF\x01" + struct.pack(">I", 0) + dims_block + gatts_block
    header_size = len(prefix) + len(build_var_list([0] * len(var_specs)))

    offsets: list[int] = []
    data_chunks: list[bytes] = []
    cursor = header_size
    for _, _, _, arr_be, _ in var_specs:
        offsets.append(cursor)
        raw_bytes = arr_be.tobytes()
        pad = (4 - (len(raw_bytes) % 4)) % 4
        padded = raw_bytes + (b"\x00" * pad)
        data_chunks.append(padded)
        cursor += len(padded)

    header = prefix + build_var_list(offsets)
    with out_path.open("wb") as fh:
        fh.write(header)
        for chunk in data_chunks:
            fh.write(chunk)
        fh.flush()
        os.fsync(fh.fileno())


def _write_netcdf_dataset(
    out_path: Path,
    lat_1d: NDArray[np.float64],
    lon_1d: NDArray[np.float64],
    data_vars: dict[str, tuple[NDArray[np.float32], dict[str, Any]]],
    global_attrs: dict[str, Any],
) -> None:
    # 1. Primary path: netCDF4 (aligned with pyproject.toml)
    try:
        import netCDF4

        with netCDF4.Dataset(str(out_path), "w", format="NETCDF3_CLASSIC") as nc:
            for k, v in global_attrs.items():
                setattr(nc, k, v)
            nc.createDimension("lat", lat_1d.size)
            nc.createDimension("lon", lon_1d.size)

            lat_v = nc.createVariable("lat", "f8", ("lat",))
            lat_v[:] = lat_1d
            lat_v.standard_name = "latitude"
            lat_v.long_name = "Latitude"
            lat_v.units = "degrees_north"
            lat_v.axis = "Y"

            lon_v = nc.createVariable("lon", "f8", ("lon",))
            lon_v[:] = lon_1d
            lon_v.standard_name = "longitude"
            lon_v.long_name = "Longitude"
            lon_v.units = "degrees_east"
            lon_v.axis = "X"

            for vname, (arr, attrs) in data_vars.items():
                fill_val = attrs.get("_FillValue", np.float32(np.nan))
                v = nc.createVariable(vname, "f4", ("lat", "lon"), fill_value=fill_val)
                v[:] = arr
                for ak, av in attrs.items():
                    if ak != "_FillValue":
                        setattr(v, ak, av)
        return
    except ImportError:
        pass

    # 2. Secondary path: scipy.io.netcdf_file (NetCDF-3 fallback on minimal hosts)
    try:
        from scipy.io import netcdf_file

        with netcdf_file(str(out_path), "w", version=1) as nc:
            for k, v in global_attrs.items():
                setattr(nc, k, v)
            nc.createDimension("lat", lat_1d.size)
            nc.createDimension("lon", lon_1d.size)

            lat_v = nc.createVariable("lat", "d", ("lat",))
            lat_v[:] = lat_1d
            lat_v.standard_name = "latitude"
            lat_v.long_name = "Latitude"
            lat_v.units = "degrees_north"
            lat_v.axis = "Y"

            lon_v = nc.createVariable("lon", "d", ("lon",))
            lon_v[:] = lon_1d
            lon_v.standard_name = "longitude"
            lon_v.long_name = "Longitude"
            lon_v.units = "degrees_east"
            lon_v.axis = "X"

            for vname, (arr, attrs) in data_vars.items():
                v = nc.createVariable(vname, "f", ("lat", "lon"))
                v[:] = arr
                for ak, av in attrs.items():
                    setattr(v, ak, av)
        return
    except ImportError:
        pass

    # 3. Pure-Python NetCDF-3 Classic writer
    _write_netcdf3_classic_pure(out_path, lat_1d, lon_1d, data_vars, global_attrs)


def ensure_sample_netcdf(
    tile_cache_dir: Path | str,
    layer: str,
    target_date: str,
) -> Path:
    """Ensure a deterministic CF-1.8 NetCDF sample grid exists under ``tile_cache_dir``.

    Generates realistic Indonesian oceanographic grids (``lon 90..145``,
    ``lat -15..10``) for ``sst``, ``chlorophyll``, or ``currents`` (``u_ms``,
    ``v_ms``) atomically and returns the cached NetCDF file path.
    """
    if layer not in {"sst", "chlorophyll", "currents"}:
        raise ValueError(
            f"Unsupported layer {layer!r}; expected 'sst', 'chlorophyll', or 'currents'"
        )

    resolved_date, day_of_year = _resolve_target_date(target_date)
    cache_root = Path(tile_cache_dir)
    nc_path = cache_root / "netcdf" / layer / f"{resolved_date}.nc"
    if nc_path.exists() and nc_path.stat().st_size > 0:
        return nc_path

    nc_path.parent.mkdir(parents=True, exist_ok=True)
    n_lon = round((INDONESIA_LON_MAX - INDONESIA_LON_MIN) / GRID_STEP_DEG) + 1
    n_lat = round((INDONESIA_LAT_MAX - INDONESIA_LAT_MIN) / GRID_STEP_DEG) + 1
    lon_1d = np.linspace(INDONESIA_LON_MIN, INDONESIA_LON_MAX, n_lon, dtype=np.float64)
    lat_1d = np.linspace(INDONESIA_LAT_MIN, INDONESIA_LAT_MAX, n_lat, dtype=np.float64)

    data_vars = _synthesize_layer_arrays(layer, lon_1d, lat_1d, day_of_year)
    global_attrs: dict[str, Any] = {
        "Conventions": "CF-1.8",
        "title": f"LAUT SCAN Offline Sample Grid ({layer})",
        "institution": "LAUT SCAN Open-Source Marine Intelligence",
        "source": "LAUT SCAN Offline Sample Fixture",
        "primary_source": "noaa_erddap",
        "layer": layer,
        "target_date": resolved_date,
        "acquired_at_utc": f"{resolved_date}T12:00:00Z",
        "spatial_resolution_km": SPATIAL_RESOLUTION_KM,
        "geospatial_lat_min": INDONESIA_LAT_MIN,
        "geospatial_lat_max": INDONESIA_LAT_MAX,
        "geospatial_lon_min": INDONESIA_LON_MIN,
        "geospatial_lon_max": INDONESIA_LON_MAX,
    }

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=nc_path.parent,
            prefix=f".{resolved_date}.",
            suffix=".nc.tmp",
            delete=False,
        ) as tf:
            tmp_path = tf.name
        _write_netcdf_dataset(Path(tmp_path), lat_1d, lon_1d, data_vars, global_attrs)
        os.replace(tmp_path, nc_path)
    except Exception:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return nc_path
