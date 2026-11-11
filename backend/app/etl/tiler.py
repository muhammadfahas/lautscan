"""EPSG:3857 RGBA raster tile engine and NetCDF point inspection for LAUT SCAN.

Implements colorblind-safe oceanographic tile rendering (``plasma`` for SST,
``viridis`` for Chlorophyll-a on a log10 scale, and ``cividis`` for Ocean Current
speed magnitude) with exact Web Mercator inverse projection, numpy bilinear
sampling, transparent ``alpha = 0`` land/NaN/out-of-bounds masking, atomic cache
writes, and bilinear-with-nearest-fallback point inspection.
"""

from __future__ import annotations

import hashlib
import io
import math
import os
import re
import struct
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
from numpy.typing import NDArray
from PIL import Image

COLORMAPS: dict[str, str] = {
    "sst": "plasma",
    "chlorophyll": "viridis",
    "currents": "cividis",
}

PROHIBITED_COLORMAPS: frozenset[str] = frozenset(
    {"jet", "rainbow", "hsv", "turbo", "gist_rainbow", "nipy_spectral"}
)

INDONESIA_LON_MIN: float = 90.0
INDONESIA_LON_MAX: float = 145.0
INDONESIA_LAT_MIN: float = -15.0
INDONESIA_LAT_MAX: float = 10.0

TILE_SIZE: int = 256
MIN_ZOOM: int = 0
MAX_ZOOM: int = 14

_SAFE_DATE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


@dataclass(frozen=True, slots=True)
class LayerDomain:
    """Domain bounds, scaling mode, and physical units for a raster layer."""

    vmin: float
    vmax: float
    log10_scale: bool
    units: str


LAYER_DOMAINS: dict[str, LayerDomain] = {
    "sst": LayerDomain(vmin=20.0, vmax=34.0, log10_scale=False, units="degC"),
    "chlorophyll": LayerDomain(vmin=0.01, vmax=10.0, log10_scale=True, units="mg/m3"),
    "currents": LayerDomain(vmin=0.0, vmax=2.5, log10_scale=False, units="m/s"),
}

_SST_VAR_CANDIDATES: tuple[str, ...] = (
    "sst",
    "analysed_sst",
    "sea_surface_temperature",
    "tos",
    "temp",
)
_CHL_VAR_CANDIDATES: tuple[str, ...] = (
    "chlorophyll",
    "chlor_a",
    "chl",
    "chlorophyll_a",
    "CHL",
)
_CURRENT_U_CANDIDATES: tuple[str, ...] = (
    "u_ms",
    "u_current",
    "u",
    "uo",
    "u_curr",
    "eastward_sea_water_velocity",
    "water_u",
)
_CURRENT_V_CANDIDATES: tuple[str, ...] = (
    "v_ms",
    "v_current",
    "v",
    "vo",
    "v_curr",
    "northward_sea_water_velocity",
    "water_v",
)
_CURRENT_SPEED_CANDIDATES: tuple[str, ...] = ("speed_ms", "current_speed_ms", "speed")
_LAT_CANDIDATES: tuple[str, ...] = ("lat", "latitude", "y", "nav_lat")
_LON_CANDIDATES: tuple[str, ...] = ("lon", "longitude", "x", "nav_lon")

_LUT_CACHE: dict[str, NDArray[np.uint8]] = {}
_PROCESSED_CACHE_LOCK = threading.Lock()
_PROCESSED_CACHE: dict[tuple[str, int, int, str, str], _ProcessedGrid] = {}
_MAX_PROCESSED_CACHE_ENTRIES: int = 12


@dataclass(slots=True)
class _LoadedGrid:
    """Normalized 2D oceanographic grid(s) with ascending WGS84 axes."""

    lat: NDArray[np.float64]
    lon: NDArray[np.float64]
    primary: NDArray[np.float64]
    u_ms: NDArray[np.float64] | None
    v_ms: NDArray[np.float64] | None
    spatial_resolution_km: float | None
    acquired_at_utc: str | None
    primary_source: str | None


@dataclass(slots=True)
class _ProcessedGrid:
    """Inpainted, ocean-masked, smoothed 2D field ready for tile and vector sampling."""

    lat: NDArray[np.float64]
    lon: NDArray[np.float64]
    values: NDArray[np.float64]
    ocean_presence: NDArray[np.float64]
    ocean_mask: NDArray[np.bool_]
    u_ms: NDArray[np.float64] | None
    v_ms: NDArray[np.float64] | None
    is_broad_grid: bool
    spatial_resolution_km: float | None
    acquired_at_utc: str | None
    primary_source: str | None


def _validate_layer(layer: str) -> LayerDomain:
    if layer not in COLORMAPS or layer not in LAYER_DOMAINS:
        raise ValueError(f"Unsupported layer {layer!r}; expected one of {tuple(COLORMAPS)}")
    cmap_name = COLORMAPS[layer]
    if cmap_name.lower() in PROHIBITED_COLORMAPS:
        raise ValueError(f"Prohibited colormap {cmap_name!r} for layer {layer!r}")
    return LAYER_DOMAINS[layer]


def _validate_fmt(fmt: str) -> str:
    fmt_lower = fmt.lower()
    if fmt_lower not in {"png", "webp"}:
        raise ValueError(f"Unsupported tile format {fmt!r}; expected 'png' or 'webp'")
    return fmt_lower


def _validate_tile_xyz(z: int, x: int, y: int) -> int:
    if not isinstance(z, int) or isinstance(z, bool) or z < MIN_ZOOM or z > MAX_ZOOM:
        raise ValueError(f"Zoom level z={z!r} out of valid range [{MIN_ZOOM}, {MAX_ZOOM}]")
    n = 1 << z
    if (
        not isinstance(x, int)
        or isinstance(x, bool)
        or not isinstance(y, int)
        or isinstance(y, bool)
        or x < 0
        or x >= n
        or y < 0
        or y >= n
    ):
        raise ValueError(f"Tile coordinates (z={z}, x={x}, y={y}) out of bounds [0, {n - 1}]")
    return n


def tile_bounds_wgs84(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Return WGS84 bounding box ``(min_lon, min_lat, max_lon, max_lat)`` for Slippy tile."""
    n = _validate_tile_xyz(z, x, y)
    min_lon = (x / n) * 360.0 - 180.0
    max_lon = ((x + 1) / n) * 360.0 - 180.0
    max_lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y / n)))))
    min_lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * ((y + 1) / n)))))
    return (min_lon, min_lat, max_lon, max_lat)


def _get_colormap_lut(cmap_name: str) -> NDArray[np.uint8]:
    if cmap_name in PROHIBITED_COLORMAPS:
        raise ValueError(f"Prohibited colormap: {cmap_name!r}")
    cached = _LUT_CACHE.get(cmap_name)
    if cached is not None:
        return cached
    cmap = matplotlib.colormaps[cmap_name]
    samples = cmap(np.linspace(0.0, 1.0, 256))
    lut = np.asarray(np.round(samples * 255.0), dtype=np.uint8)
    _LUT_CACHE[cmap_name] = lut
    return lut


def _decode_attr(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace").strip()
    if isinstance(val, np.ndarray):
        if val.ndim == 0:
            return _decode_attr(val.item())
        return None
    text = str(val).strip()
    return text or None


def _float_attr(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, np.ndarray):
        if val.size != 1:
            return None
        val = val.item()
    try:
        num = float(val)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def _pick_name(available: Any, candidates: tuple[str, ...]) -> str | None:
    keys = list(available)
    for name in candidates:
        if name in keys:
            return name
    lower_map = {str(k).lower(): str(k) for k in keys}
    for name in candidates:
        found = lower_map.get(name.lower())
        if found is not None:
            return found
    return None


def _reduce_to_2d(
    arr: NDArray[Any],
    dims: tuple[str, ...],
    lat_dim: str | None,
    lon_dim: str | None,
) -> NDArray[np.float64]:
    data = np.asarray(arr, dtype=np.float64)
    current_dims = list(dims)

    while data.ndim > 2:
        drop_axis: int | None = None
        for idx, dname in enumerate(current_dims):
            if dname not in {lat_dim, lon_dim}:
                drop_axis = idx
                break
        if drop_axis is None:
            drop_axis = 0
        dim_label = current_dims[drop_axis].lower() if current_dims else ""
        take_idx = -1 if "time" in dim_label else 0
        data = np.take(data, indices=take_idx, axis=drop_axis)
        if current_dims:
            current_dims.pop(drop_axis)

    if data.ndim != 2:
        raise ValueError(f"Expected 2D spatial grid after slicing, got shape {data.shape}")

    if (
        len(current_dims) == 2
        and lat_dim is not None
        and lon_dim is not None
        and current_dims[0] == lon_dim
        and current_dims[1] == lat_dim
    ):
        data = data.T

    return np.asarray(data, dtype=np.float64)


def _apply_cf_mask_and_scale(
    raw: NDArray[Any],
    attrs: dict[str, Any],
) -> NDArray[np.float64]:
    arr = np.asarray(raw, dtype=np.float64).copy()
    mask = ~np.isfinite(arr)

    for key in ("_FillValue", "missing_value"):
        fv = _float_attr(attrs.get(key))
        if fv is not None:
            mask |= arr == fv

    scale_factor = _float_attr(attrs.get("scale_factor"))
    add_offset = _float_attr(attrs.get("add_offset"))
    if scale_factor is not None:
        arr = arr * scale_factor
    if add_offset is not None:
        arr = arr + add_offset

    valid_min = _float_attr(attrs.get("valid_min"))
    if valid_min is not None:
        mask |= arr < valid_min
    valid_max = _float_attr(attrs.get("valid_max"))
    if valid_max is not None:
        mask |= arr > valid_max

    arr[mask] = np.nan
    return arr


def _read_raw_netcdf_tables(
    dataset_path: Path,
) -> tuple[dict[str, tuple[tuple[str, ...], NDArray[Any], dict[str, Any]]], dict[str, Any]]:
    """Read NetCDF variables & global attributes via xarray -> netCDF4 -> scipy -> pure NetCDF3."""
    variables: dict[str, tuple[tuple[str, ...], NDArray[Any], dict[str, Any]]] = {}
    global_attrs: dict[str, Any] = {}

    # 1. Primary path: xarray (aligned with pyproject.toml)
    try:
        import xarray as xr

        with xr.open_dataset(dataset_path) as ds:
            for coord_name in ds.coords:
                da = ds.coords[coord_name]
                variables[str(coord_name)] = (
                    tuple(str(d) for d in da.dims),
                    np.asarray(da.values),
                    dict(da.attrs),
                )
            for var_name in ds.data_vars:
                da = ds.data_vars[var_name]
                variables[str(var_name)] = (
                    tuple(str(d) for d in da.dims),
                    np.asarray(da.values),
                    dict(da.attrs),
                )
            global_attrs = {str(k): v for k, v in ds.attrs.items()}
            return variables, global_attrs
    except (ImportError, ValueError):
        pass

    # 2. Secondary path: netCDF4 directly (aligned with pyproject.toml)
    try:
        import netCDF4

        with netCDF4.Dataset(str(dataset_path), "r") as nc:
            variables = {}
            for vname, var in nc.variables.items():
                raw_vals = var[:]
                if np.ma.isMaskedArray(raw_vals):
                    arr_vals: NDArray[Any] = np.asarray(
                        np.ma.filled(raw_vals.astype(np.float64), np.nan),
                        dtype=np.float64,
                    )
                else:
                    arr_vals = np.asarray(raw_vals)
                vattrs = {str(k): var.getncattr(k) for k in var.ncattrs()}
                # netCDF4 already applies mask & scale when auto_maskandscale is enabled.
                for cf_key in ("_FillValue", "missing_value", "scale_factor", "add_offset"):
                    vattrs.pop(cf_key, None)
                variables[str(vname)] = (
                    tuple(str(d) for d in var.dimensions),
                    arr_vals,
                    vattrs,
                )
            global_attrs = {str(k): nc.getncattr(k) for k in nc.ncattrs()}
            return variables, global_attrs
    except ImportError:
        pass

    # 3. Tertiary path: scipy.io.netcdf_file (NetCDF-3 fallback on minimal hosts)
    try:
        from scipy.io import netcdf_file

        with netcdf_file(str(dataset_path), "r", mmap=False) as nc:
            variables = {}
            for vname, var in nc.variables.items():
                vattrs = {str(k): v for k, v in getattr(var, "_attributes", {}).items()}
                variables[str(vname)] = (
                    tuple(str(d) for d in var.dimensions),
                    np.asarray(var[:]).copy(),
                    vattrs,
                )
            global_attrs = {str(k): v for k, v in getattr(nc, "_attributes", {}).items()}
            return variables, global_attrs
    except ImportError:
        pass

    # 4. Pure-Python NetCDF-3 Classic reader (zero external NetCDF C libs required)
    return _read_netcdf3_classic_pure(dataset_path)


def _read_netcdf3_classic_pure(
    dataset_path: Path,
) -> tuple[dict[str, tuple[tuple[str, ...], NDArray[Any], dict[str, Any]]], dict[str, Any]]:
    """Minimal pure-Python NetCDF-3 Classic (``CDF\\x01``) reader using struct + numpy."""
    blob = dataset_path.read_bytes()
    if len(blob) < 8 or blob[:4] not in {b"CDF\x01", b"CDF\x02"}:
        raise ValueError(f"Unsupported binary NetCDF header in {dataset_path}")
    is_64bit = blob[:4] == b"CDF\x02"
    pos = 8  # Skip magic (4) + numrecs (4)

    def read_u32() -> int:
        nonlocal pos
        val = struct.unpack_from(">I", blob, pos)[0]
        pos += 4
        return int(val)

    def read_u64() -> int:
        nonlocal pos
        val = struct.unpack_from(">Q", blob, pos)[0]
        pos += 8
        return int(val)

    def read_nc_string() -> str:
        nonlocal pos
        n = read_u32()
        raw = blob[pos : pos + n]
        pos += n + ((4 - (n % 4)) % 4)
        return raw.decode("utf-8", errors="replace")

    def read_att_list() -> dict[str, Any]:
        nonlocal pos
        tag = read_u32()
        count = read_u32()
        if tag == 0 and count == 0:
            return {}
        if tag != 12:
            raise ValueError(f"Unexpected NetCDF attribute tag: {tag}")
        attrs: dict[str, Any] = {}
        type_sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 4, 6: 8}
        dtype_map = {1: ">i1", 3: ">i2", 4: ">i4", 5: ">f4", 6: ">f8"}
        for _ in range(count):
            name = read_nc_string()
            nc_type = read_u32()
            nelems = read_u32()
            byte_len = nelems * type_sizes[nc_type]
            raw = blob[pos : pos + byte_len]
            pos += byte_len + ((4 - (byte_len % 4)) % 4)
            if nc_type == 2:
                attrs[name] = raw.rstrip(b"\x00").decode("utf-8", errors="replace")
            else:
                arr = np.frombuffer(raw, dtype=dtype_map[nc_type])
                attrs[name] = arr[0].item() if nelems == 1 else arr.copy()
        return attrs

    # Dimensions
    dim_tag = read_u32()
    dim_count = read_u32()
    dims_list: list[tuple[str, int]] = []
    if dim_tag == 10:
        for _ in range(dim_count):
            dims_list.append((read_nc_string(), read_u32()))
    elif not (dim_tag == 0 and dim_count == 0):
        raise ValueError(f"Unexpected NetCDF dimension tag: {dim_tag}")

    global_attrs = read_att_list()

    # Variables
    var_tag = read_u32()
    var_count = read_u32()
    variables: dict[str, tuple[tuple[str, ...], NDArray[Any], dict[str, Any]]] = {}
    if var_tag == 11:
        dtype_map = {1: ">i1", 3: ">i2", 4: ">i4", 5: ">f4", 6: ">f8"}
        for _ in range(var_count):
            vname = read_nc_string()
            ndims = read_u32()
            dim_ids = [read_u32() for _ in range(ndims)]
            vattrs = read_att_list()
            nc_type = read_u32()
            vsize = read_u32()
            begin = read_u64() if is_64bit else read_u32()
            shape = tuple(dims_list[d][1] for d in dim_ids)
            dim_names = tuple(dims_list[d][0] for d in dim_ids)
            elem_count = int(np.prod(shape)) if shape else 1
            np_dt = np.dtype(dtype_map[nc_type])
            raw_slice = blob[begin : begin + elem_count * np_dt.itemsize]
            if len(raw_slice) < elem_count * np_dt.itemsize or vsize < elem_count * np_dt.itemsize:
                raise ValueError(f"Truncated NetCDF variable {vname!r} in {dataset_path}")
            arr = np.frombuffer(raw_slice, dtype=np_dt).reshape(shape).astype(np.float64, copy=True)
            variables[vname] = (dim_names, arr, vattrs)
    elif not (var_tag == 0 and var_count == 0):
        raise ValueError(f"Unexpected NetCDF variable tag: {var_tag}")

    return variables, global_attrs


def _normalize_axes_and_grid(
    lat: NDArray[np.float64],
    lon: NDArray[np.float64],
    *grids: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64], tuple[NDArray[np.float64], ...]]:
    lat_1d = np.asarray(lat, dtype=np.float64).ravel()
    lon_1d = np.asarray(lon, dtype=np.float64).ravel()
    if lat_1d.size < 2 or lon_1d.size < 2:
        raise ValueError("NetCDF coordinate axes must contain at least 2 points each")

    out_grids = [np.asarray(g, dtype=np.float64) for g in grids]

    # Wrap 0..360 longitudes to -180..180 if present.
    if np.any(lon_1d > 180.0):
        lon_1d = ((lon_1d + 180.0) % 360.0) - 180.0

    if not np.all(np.diff(lat_1d) > 0):
        lat_order = np.argsort(lat_1d)
        lat_1d = lat_1d[lat_order]
        out_grids = [g[lat_order, :] for g in out_grids]

    if not np.all(np.diff(lon_1d) > 0):
        lon_order = np.argsort(lon_1d)
        lon_1d = lon_1d[lon_order]
        out_grids = [g[:, lon_order] for g in out_grids]

    return lat_1d, lon_1d, tuple(out_grids)


def _load_layer_grid(dataset_path: Path, layer: str) -> _LoadedGrid:
    if not dataset_path.exists():
        raise FileNotFoundError(f"NetCDF dataset not found: {dataset_path}")

    variables, global_attrs = _read_raw_netcdf_tables(dataset_path)

    lat_name = _pick_name(variables.keys(), _LAT_CANDIDATES)
    lon_name = _pick_name(variables.keys(), _LON_CANDIDATES)
    if lat_name is None or lon_name is None:
        raise ValueError(f"Missing lat/lon coordinates in {dataset_path}")

    lat_dims, lat_raw, _ = variables[lat_name]
    lon_dims, lon_raw, _ = variables[lon_name]
    lat_dim_name = lat_dims[0] if lat_dims else lat_name
    lon_dim_name = lon_dims[0] if lon_dims else lon_name

    lat_arr = np.asarray(lat_raw, dtype=np.float64).ravel()
    lon_arr = np.asarray(lon_raw, dtype=np.float64).ravel()

    u_grid: NDArray[np.float64] | None = None
    v_grid: NDArray[np.float64] | None = None

    if layer == "sst":
        var_name = _pick_name(variables.keys(), _SST_VAR_CANDIDATES)
        if var_name is None:
            raise ValueError(f"No SST variable found in {dataset_path}")
        vdims, vraw, vattrs = variables[var_name]
        primary = _apply_cf_mask_and_scale(
            _reduce_to_2d(vraw, vdims, lat_dim_name, lon_dim_name),
            vattrs,
        )
        units = (_decode_attr(vattrs.get("units")) or "").lower()
        finite_vals = primary[np.isfinite(primary)]
        if (
            "kelvin" in units
            or units == "k"
            or (finite_vals.size > 0 and float(np.nanmedian(finite_vals)) > 150.0)
        ):
            primary = primary - 273.15
    elif layer == "chlorophyll":
        var_name = _pick_name(variables.keys(), _CHL_VAR_CANDIDATES)
        if var_name is None:
            raise ValueError(f"No chlorophyll variable found in {dataset_path}")
        vdims, vraw, vattrs = variables[var_name]
        primary = _apply_cf_mask_and_scale(
            _reduce_to_2d(vraw, vdims, lat_dim_name, lon_dim_name),
            vattrs,
        )
        primary[primary <= 0.0] = np.nan
    elif layer == "currents":
        u_name = _pick_name(variables.keys(), _CURRENT_U_CANDIDATES)
        v_name = _pick_name(variables.keys(), _CURRENT_V_CANDIDATES)
        if u_name is not None and v_name is not None:
            udims, uraw, uattrs = variables[u_name]
            vdims, vraw, vattrs = variables[v_name]
            u_grid = _apply_cf_mask_and_scale(
                _reduce_to_2d(uraw, udims, lat_dim_name, lon_dim_name),
                uattrs,
            )
            v_grid = _apply_cf_mask_and_scale(
                _reduce_to_2d(vraw, vdims, lat_dim_name, lon_dim_name),
                vattrs,
            )
            primary = np.hypot(u_grid, v_grid)
        else:
            s_name = _pick_name(variables.keys(), _CURRENT_SPEED_CANDIDATES)
            if s_name is None:
                raise ValueError(f"No current velocity variables found in {dataset_path}")
            sdims, sraw, sattrs = variables[s_name]
            primary = _apply_cf_mask_and_scale(
                _reduce_to_2d(sraw, sdims, lat_dim_name, lon_dim_name),
                sattrs,
            )
    else:
        raise ValueError(f"Unsupported layer: {layer!r}")

    if u_grid is not None and v_grid is not None:
        lat_arr, lon_arr, (primary, u_grid, v_grid) = _normalize_axes_and_grid(
            lat_arr,
            lon_arr,
            primary,
            u_grid,
            v_grid,
        )
    else:
        lat_arr, lon_arr, (primary,) = _normalize_axes_and_grid(lat_arr, lon_arr, primary)

    res_km = _float_attr(global_attrs.get("spatial_resolution_km"))
    if res_km is None:
        dlat = float(np.median(np.abs(np.diff(lat_arr))))
        res_km = round(dlat * 111.32, 2)

    acquired_at = _decode_attr(
        global_attrs.get("acquired_at_utc") or global_attrs.get("time_coverage_start")
    )
    primary_source = _decode_attr(global_attrs.get("primary_source") or global_attrs.get("source"))

    return _LoadedGrid(
        lat=lat_arr,
        lon=lon_arr,
        primary=primary,
        u_ms=u_grid,
        v_ms=v_grid,
        spatial_resolution_km=res_km,
        acquired_at_utc=acquired_at,
        primary_source=primary_source,
    )


def _bilinear_sample_grid(
    grid_lat: NDArray[np.float64],
    grid_lon: NDArray[np.float64],
    values: NDArray[np.float64],
    q_lat: NDArray[np.float64],
    q_lon: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Bilinearly interpolate ``values`` at ``(q_lat, q_lon)``; NaN if out-of-bounds or masked."""
    q_lat_b, q_lon_b = np.broadcast_arrays(q_lat, q_lon)
    in_bounds = (
        (q_lat_b >= grid_lat[0])
        & (q_lat_b <= grid_lat[-1])
        & (q_lon_b >= grid_lon[0])
        & (q_lon_b <= grid_lon[-1])
    )
    qlat_c = np.clip(q_lat_b, grid_lat[0], grid_lat[-1])
    qlon_c = np.clip(q_lon_b, grid_lon[0], grid_lon[-1])

    iy0 = np.clip(np.searchsorted(grid_lat, qlat_c, side="right") - 1, 0, grid_lat.size - 2)
    ix0 = np.clip(np.searchsorted(grid_lon, qlon_c, side="right") - 1, 0, grid_lon.size - 2)

    lat0 = grid_lat[iy0]
    lat1 = grid_lat[iy0 + 1]
    lon0 = grid_lon[ix0]
    lon1 = grid_lon[ix0 + 1]

    dlat = np.where(lat1 > lat0, lat1 - lat0, 1.0)
    dlon = np.where(lon1 > lon0, lon1 - lon0, 1.0)
    wy = (qlat_c - lat0) / dlat
    wx = (qlon_c - lon0) / dlon

    v00 = values[iy0, ix0]
    v01 = values[iy0, ix0 + 1]
    v10 = values[iy0 + 1, ix0]
    v11 = values[iy0 + 1, ix0 + 1]

    valid = in_bounds & np.isfinite(v00) & np.isfinite(v01) & np.isfinite(v10) & np.isfinite(v11)
    out = np.full(q_lat_b.shape, np.nan, dtype=np.float64)
    out[valid] = (
        (1.0 - wy[valid]) * (1.0 - wx[valid]) * v00[valid]
        + (1.0 - wy[valid]) * wx[valid] * v01[valid]
        + wy[valid] * (1.0 - wx[valid]) * v10[valid]
        + wy[valid] * wx[valid] * v11[valid]
    )
    return out


def _encode_rgba_image(rgba: NDArray[np.uint8], fmt_lower: str) -> bytes:
    img = Image.fromarray(rgba, mode="RGBA")
    buf = io.BytesIO()
    if fmt_lower == "png":
        img.save(buf, format="PNG")
    else:
        img.save(buf, format="WEBP", lossless=True, exact=True)
    return buf.getvalue()


def _smoothstep(edge0: float, edge1: float, x: NDArray[np.float64]) -> NDArray[np.float64]:
    span = max(edge1 - edge0, 1e-9)
    t = np.clip((x - edge0) / span, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _morph_dilate(mask: NDArray[np.bool_], radius: int) -> NDArray[np.bool_]:
    if radius <= 0 or not np.any(mask):
        return mask.copy()
    h, w = mask.shape
    out = np.zeros_like(mask, dtype=np.bool_)
    r_sq = radius * radius + 0.5
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dy * dy + dx * dx > r_sq:
                continue
            ys = slice(max(0, -dy), h - max(0, dy))
            xs = slice(max(0, -dx), w - max(0, dx))
            yd = slice(max(0, dy), h - max(0, -dy))
            xd = slice(max(0, dx), w - max(0, -dx))
            out[yd, xd] |= mask[ys, xs]
    return out


def _morph_erode(mask: NDArray[np.bool_], radius: int) -> NDArray[np.bool_]:
    if radius <= 0 or not np.any(mask):
        return mask.copy()
    h, w = mask.shape
    padded = np.pad(mask, radius, mode="edge")
    out = np.ones((h, w), dtype=np.bool_)
    r_sq = radius * radius + 0.5
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dy * dy + dx * dx > r_sq:
                continue
            y0 = radius + dy
            x0 = radius + dx
            out &= padded[y0 : y0 + h, x0 : x0 + w]
    return out


def _remove_isolated_inland_specks(
    mask: NDArray[np.bool_],
    min_neighbors_5x5: int = 4,
) -> NDArray[np.bool_]:
    """Drop tiny 1-3 pixel inland puddles completely surrounded by land NaNs."""
    h, w = mask.shape
    padded = np.pad(mask.astype(np.int32), 2, mode="edge")
    count = np.zeros((h, w), dtype=np.int32)
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            if dy == 0 and dx == 0:
                continue
            y0 = 2 + dy
            x0 = 2 + dx
            count += padded[y0 : y0 + h, x0 : x0 + w]
    return mask & (count >= min_neighbors_5x5)


def _morph_close(mask: NDArray[np.bool_], radius: int) -> NDArray[np.bool_]:
    if radius <= 0:
        return mask.copy()
    return _morph_erode(_morph_dilate(mask, radius), radius)


def _gaussian_kernel_1d(sigma: float) -> NDArray[np.float64]:
    if sigma <= 0.05:
        return np.array([1.0], dtype=np.float64)
    radius = max(1, int(math.ceil(2.5 * sigma)))
    offsets = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (offsets / sigma) ** 2)
    return kernel / float(np.sum(kernel))


def _convolve_separable_edge(
    arr: NDArray[np.float64],
    sigma: float,
) -> NDArray[np.float64]:
    kernel = _gaussian_kernel_1d(sigma)
    if kernel.size == 1:
        return arr.copy()
    radius = kernel.size // 2
    h, w = arr.shape

    pad_y = np.pad(arr, ((radius, radius), (0, 0)), mode="edge")
    tmp = np.zeros_like(arr, dtype=np.float64)
    for idx, wt in enumerate(kernel):
        tmp += float(wt) * pad_y[idx : idx + h, :]

    pad_x = np.pad(tmp, ((0, 0), (radius, radius)), mode="edge")
    out = np.zeros_like(arr, dtype=np.float64)
    for idx, wt in enumerate(kernel):
        out += float(wt) * pad_x[:, idx : idx + w]
    return out


def _normalized_gaussian_smooth(
    values: NDArray[np.float64],
    valid_mask: NDArray[np.bool_],
    sigma: float,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Apply normalized Gaussian convolution strictly weighted by valid ocean cells."""
    if sigma <= 0.05:
        out_vals = np.where(valid_mask, values, np.nan)
        return out_vals, valid_mask.astype(np.float64)

    weights = valid_mask.astype(np.float64)
    clean_vals = np.where(valid_mask, values, 0.0)
    num = _convolve_separable_edge(clean_vals, sigma)
    den = _convolve_separable_edge(weights, sigma)
    smooth_vals = np.where(den > 1e-6, num / np.maximum(den, 1e-6), np.nan)
    return smooth_vals, den


def _inpaint_ocean_holes(
    values: NDArray[np.float64],
    anchor_mask: NDArray[np.bool_],
    target_mask: NDArray[np.bool_],
    max_fill_iters: int = 16,
    relax_iters: int = 18,
) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
    """Fill missing cells inside ``target_mask`` via ocean-masked harmonic diffusion."""
    filled = np.where(anchor_mask, values, 0.0)
    known = anchor_mask.copy()
    h, w = filled.shape
    offsets = (
        (-1, 0, 1.0),
        (1, 0, 1.0),
        (0, -1, 1.0),
        (0, 1, 1.0),
        (-1, -1, 0.7071),
        (-1, 1, 0.7071),
        (1, -1, 0.7071),
        (1, 1, 0.7071),
    )

    for _ in range(max_fill_iters):
        missing = target_mask & (~known)
        if not np.any(missing):
            break
        w_sum = np.zeros((h, w), dtype=np.float64)
        v_acc = np.zeros((h, w), dtype=np.float64)
        for dy, dx, wt in offsets:
            ys = slice(max(0, -dy), h - max(0, dy))
            xs = slice(max(0, -dx), w - max(0, dx))
            yd = slice(max(0, dy), h - max(0, -dy))
            xd = slice(max(0, dx), w - max(0, -dx))
            m = known[ys, xs]
            w_sum[yd, xd] += wt * m
            v_acc[yd, xd] += wt * m * filled[ys, xs]
        upd = missing & (w_sum > 0.0)
        if not np.any(upd):
            break
        filled[upd] = v_acc[upd] / w_sum[upd]
        known[upd] = True

    relax_mask = known & (~anchor_mask)
    if np.any(relax_mask):
        for _ in range(relax_iters):
            w_sum = np.zeros((h, w), dtype=np.float64)
            v_acc = np.zeros((h, w), dtype=np.float64)
            for dy, dx, wt in offsets:
                ys = slice(max(0, -dy), h - max(0, dy))
                xs = slice(max(0, -dx), w - max(0, dx))
                yd = slice(max(0, dy), h - max(0, -dy))
                xd = slice(max(0, dx), w - max(0, -dx))
                m = known[ys, xs]
                w_sum[yd, xd] += wt * m
                v_acc[yd, xd] += wt * m * filled[ys, xs]
            upd = relax_mask & (w_sum > 0.0)
            filled[upd] = v_acc[upd] / w_sum[upd]

    out = np.where(known, filled, np.nan)
    return out, known


def _discover_sibling_sst_path(dataset_path: Path) -> Path | None:
    """Locate a matching SST NetCDF grid in the same cache hierarchy when available."""
    global_sst = dataset_path.parent / "noaa_sst.nc"
    if global_sst.is_file() and global_sst != dataset_path:
        return global_sst
    if dataset_path.parent.name in {"chlorophyll", "currents"}:
        sibling = dataset_path.parent.parent / "sst" / dataset_path.name
        if sibling.is_file():
            return sibling
    return None


def _project_sst_ocean_mask(
    sst_path: Path,
    target_lat: NDArray[np.float64],
    target_lon: NDArray[np.float64],
) -> NDArray[np.bool_] | None:
    """Project an SST finite-ocean mask onto ``(target_lat, target_lon)`` cell footprints."""
    try:
        sst_grid = _load_layer_grid(sst_path, "sst")
    except Exception:
        return None

    lat_overlap = min(float(sst_grid.lat[-1]), float(target_lat[-1])) - max(
        float(sst_grid.lat[0]), float(target_lat[0])
    )
    lon_overlap = min(float(sst_grid.lon[-1]), float(target_lon[-1])) - max(
        float(sst_grid.lon[0]), float(target_lon[0])
    )
    t_lat_span = max(float(target_lat[-1] - target_lat[0]), 1e-6)
    t_lon_span = max(float(target_lon[-1] - target_lon[0]), 1e-6)
    if lat_overlap < 0.5 * t_lat_span or lon_overlap < 0.5 * t_lon_span:
        return None

    sst_fin = np.isfinite(sst_grid.primary)
    dlat_t = float(np.median(np.abs(np.diff(target_lat))))
    dlon_t = float(np.median(np.abs(np.diff(target_lon))))
    dlat_s = float(np.median(np.abs(np.diff(sst_grid.lat))))
    dlon_s = float(np.median(np.abs(np.diff(sst_grid.lon))))
    ratio = max(dlat_t / max(dlat_s, 1e-6), dlon_t / max(dlon_s, 1e-6))

    sub_offsets: tuple[float, ...]
    if ratio >= 2.2:
        sub_offsets = (-0.4, -0.2, 0.0, 0.2, 0.4)
        min_frac = 0.16
    else:
        sub_offsets = (-0.32, 0.0, 0.32)
        min_frac = 0.30

    ocean_acc = np.zeros((target_lat.size, target_lon.size), dtype=np.float64)
    in_domain = np.zeros((target_lat.size, target_lon.size), dtype=np.float64)
    s_lat0, s_lat1 = float(sst_grid.lat[0]) - dlat_s, float(sst_grid.lat[-1]) + dlat_s
    s_lon0, s_lon1 = float(sst_grid.lon[0]) - dlon_s, float(sst_grid.lon[-1]) + dlon_s

    for oy in sub_offsets:
        q_y = target_lat + oy * dlat_t
        y_ok = (q_y >= s_lat0) & (q_y <= s_lat1)
        iy = np.clip(
            np.searchsorted(sst_grid.lat, q_y, side="left"),
            0,
            sst_grid.lat.size - 1,
        )
        iy_prev = np.maximum(0, iy - 1)
        pick_prev_y = np.abs(sst_grid.lat[iy_prev] - q_y) < np.abs(sst_grid.lat[iy] - q_y)
        iy = np.where(pick_prev_y, iy_prev, iy)

        for ox in sub_offsets:
            q_x = target_lon + ox * dlon_t
            x_ok = (q_x >= s_lon0) & (q_x <= s_lon1)
            ix = np.clip(
                np.searchsorted(sst_grid.lon, q_x, side="left"),
                0,
                sst_grid.lon.size - 1,
            )
            ix_prev = np.maximum(0, ix - 1)
            pick_prev_x = np.abs(sst_grid.lon[ix_prev] - q_x) < np.abs(sst_grid.lon[ix] - q_x)
            ix = np.where(pick_prev_x, ix_prev, ix)

            box_ok = y_ok[:, np.newaxis] & x_ok[np.newaxis, :]
            in_domain += box_ok.astype(np.float64)
            ocean_acc += np.where(box_ok, sst_fin[np.ix_(iy, ix)], 0.0)

    ocean_frac = np.where(in_domain > 0.0, ocean_acc / np.maximum(in_domain, 1.0), 0.0)
    return ocean_frac >= min_frac


def _equatorial_corridor_mask(
    lat: NDArray[np.float64],
    raw_finite: NDArray[np.bool_],
) -> NDArray[np.bool_]:
    """Infer equatorial ocean corridor when north and south bands both hold water."""
    if not np.any(np.abs(lat) <= 1.5):
        return np.zeros_like(raw_finite, dtype=np.bool_)
    north_ok = (lat > 0.75) & (lat <= 2.75)
    south_ok = (lat < -0.75) & (lat >= -2.75)
    if not (np.any(north_ok) and np.any(south_ok)):
        return np.zeros_like(raw_finite, dtype=np.bool_)
    has_north = np.any(raw_finite[north_ok, :], axis=0)
    has_south = np.any(raw_finite[south_ok, :], axis=0)
    eq_rows = np.abs(lat) <= 1.15
    return np.asarray(
        eq_rows[:, np.newaxis] & (has_north & has_south)[np.newaxis, :], dtype=np.bool_
    )


def _build_processed_layer_grid(
    dataset_path: Path,
    layer: str,
    ocean_mask_path: Path | None = None,
) -> _ProcessedGrid:
    """Inpaint cloud/equatorial gaps and smooth scalar/vector grids inside ocean masks."""
    grid = _load_layer_grid(dataset_path, layer)
    h, w = grid.primary.shape
    span_lat = float(grid.lat[-1] - grid.lat[0])
    span_lon = float(grid.lon[-1] - grid.lon[0])
    is_broad = h >= 16 and w >= 16 and span_lat >= 6.0 and span_lon >= 6.0

    mask_source: Path | None = None
    if layer in {"chlorophyll", "currents"}:
        if ocean_mask_path is not None and ocean_mask_path.is_file():
            mask_source = ocean_mask_path
        elif is_broad:
            mask_source = _discover_sibling_sst_path(dataset_path)

    sst_ocean: NDArray[np.bool_] | None = None
    if mask_source is not None:
        sst_ocean = _project_sst_ocean_mask(mask_source, grid.lat, grid.lon)

    if layer == "currents" and grid.u_ms is not None and grid.v_ms is not None:
        raw_fin = np.isfinite(grid.u_ms) & np.isfinite(grid.v_ms)
        if sst_ocean is not None:
            ocean_mask = sst_ocean
        elif is_broad:
            ocean_mask = _morph_close(raw_fin, radius=2) | _equatorial_corridor_mask(
                grid.lat, raw_fin
            )
        else:
            ocean_mask = raw_fin | _equatorial_corridor_mask(grid.lat, raw_fin)

        if not np.any(ocean_mask):
            return _ProcessedGrid(
                lat=grid.lat,
                lon=grid.lon,
                values=np.full((h, w), np.nan, dtype=np.float64),
                ocean_presence=np.zeros((h, w), dtype=np.float64),
                ocean_mask=ocean_mask,
                u_ms=np.full((h, w), np.nan, dtype=np.float64),
                v_ms=np.full((h, w), np.nan, dtype=np.float64),
                is_broad_grid=is_broad,
                spatial_resolution_km=grid.spatial_resolution_km,
                acquired_at_utc=grid.acquired_at_utc,
                primary_source=grid.primary_source,
            )

        speed = np.where(raw_fin, np.hypot(grid.u_ms, grid.v_ms), np.nan)
        eq_core = np.abs(grid.lat) <= 0.45
        eq_ref = (np.abs(grid.lat) >= 1.25) & (np.abs(grid.lat) <= 3.25)
        core_slice = speed[eq_core, :]
        ref_slice = speed[eq_ref, :]
        core_vals = core_slice[np.isfinite(core_slice)] if np.any(eq_core) else np.empty(0)
        ref_vals = ref_slice[np.isfinite(ref_slice)] if np.any(eq_ref) else np.empty(0)

        keep_mask = raw_fin & ocean_mask
        if core_vals.size > 0 and ref_vals.size > 0:
            core_med = float(np.median(core_vals))
            ref_med = float(np.median(ref_vals))
            if ref_med >= 0.05 and core_med < 0.45 * ref_med:
                damped = (
                    (np.abs(grid.lat)[:, np.newaxis] <= 1.05)
                    & ocean_mask
                    & ((~raw_fin) | (speed < 0.55 * ref_med))
                )
                keep_mask &= ~damped

        u_filled, u_known = _inpaint_ocean_holes(
            grid.u_ms, keep_mask, ocean_mask, max_fill_iters=18, relax_iters=24
        )
        v_filled, v_known = _inpaint_ocean_holes(
            grid.v_ms, keep_mask, ocean_mask, max_fill_iters=18, relax_iters=24
        )
        valid_vec = u_known & v_known & ocean_mask

        sigma = 0.65 if is_broad else 0.0
        u_smooth, _ = _normalized_gaussian_smooth(u_filled, valid_vec, sigma=sigma)
        v_smooth, _ = _normalized_gaussian_smooth(v_filled, valid_vec, sigma=sigma)

        # Keep vector exports strictly masked to ocean cells; buffer values for tile sampling.
        u_vec = np.where(valid_vec, u_smooth, np.nan)
        v_vec = np.where(valid_vec, v_smooth, np.nan)
        speed_tile = np.hypot(u_smooth, v_smooth)
        presence_sigma = 0.60 if is_broad else 0.0
        ocean_presence = _convolve_separable_edge(valid_vec.astype(np.float64), presence_sigma)

        return _ProcessedGrid(
            lat=grid.lat,
            lon=grid.lon,
            values=speed_tile,
            ocean_presence=ocean_presence,
            ocean_mask=valid_vec,
            u_ms=u_vec,
            v_ms=v_vec,
            is_broad_grid=is_broad,
            spatial_resolution_km=grid.spatial_resolution_km,
            acquired_at_utc=grid.acquired_at_utc,
            primary_source=grid.primary_source,
        )

    raw_valid = np.isfinite(grid.primary)
    if layer == "chlorophyll":
        raw_valid &= grid.primary > 0.0
    if is_broad:
        raw_valid = _remove_isolated_inland_specks(raw_valid, min_neighbors_5x5=4)

    if not np.any(raw_valid):
        empty_bool = np.zeros((h, w), dtype=np.bool_)
        return _ProcessedGrid(
            lat=grid.lat,
            lon=grid.lon,
            values=np.full((h, w), np.nan, dtype=np.float64),
            ocean_presence=np.zeros((h, w), dtype=np.float64),
            ocean_mask=empty_bool,
            u_ms=None,
            v_ms=None,
            is_broad_grid=is_broad,
            spatial_resolution_km=grid.spatial_resolution_km,
            acquired_at_utc=grid.acquired_at_utc,
            primary_source=grid.primary_source,
        )

    work_vals = (
        np.where(raw_valid, np.log10(np.maximum(grid.primary, 1e-6)), np.nan)
        if layer == "chlorophyll"
        else grid.primary.copy()
    )

    if sst_ocean is not None:
        ocean_mask = raw_valid | sst_ocean
        if is_broad:
            ocean_mask = _morph_close(ocean_mask, radius=1)
    elif is_broad:
        close_radius = 2 if layer in {"chlorophyll", "currents"} else 1
        ocean_mask = _morph_close(raw_valid, radius=close_radius)
    else:
        ocean_mask = raw_valid.copy()

    filled_vals, filled_mask = _inpaint_ocean_holes(
        work_vals,
        raw_valid,
        ocean_mask,
        max_fill_iters=14 if is_broad else 2,
        relax_iters=14 if is_broad else 2,
    )

    if is_broad:
        val_sigma = 0.78 if layer == "chlorophyll" else 0.72
        pres_sigma = 0.62
        smooth_vals, _ = _normalized_gaussian_smooth(filled_vals, filled_mask, sigma=val_sigma)
        # Second gentle coastal skirt pass guarantees smooth 4x4 cubic stencils at shorelines.
        skirt_mask = np.isfinite(smooth_vals)
        buffered_vals, _ = _normalized_gaussian_smooth(smooth_vals, skirt_mask, sigma=0.55)
        smooth_vals = np.where(filled_mask, smooth_vals, buffered_vals)
        ocean_presence = _convolve_separable_edge(filled_mask.astype(np.float64), pres_sigma)
    else:
        smooth_vals = np.where(filled_mask, filled_vals, np.nan)
        ocean_presence = filled_mask.astype(np.float64)

    return _ProcessedGrid(
        lat=grid.lat,
        lon=grid.lon,
        values=smooth_vals,
        ocean_presence=ocean_presence,
        ocean_mask=filled_mask,
        u_ms=None,
        v_ms=None,
        is_broad_grid=is_broad,
        spatial_resolution_km=grid.spatial_resolution_km,
        acquired_at_utc=grid.acquired_at_utc,
        primary_source=grid.primary_source,
    )


def _get_processed_layer_grid(
    dataset_path: Path,
    layer: str,
    ocean_mask_path: Path | None = None,
) -> _ProcessedGrid:
    """Return cached or freshly processed grid keyed by file stat and optional mask."""
    resolved = dataset_path.resolve()
    stat = resolved.stat()
    mask_key = ""
    if ocean_mask_path is not None and ocean_mask_path.exists():
        mstat = ocean_mask_path.resolve().stat()
        mask_key = f"{ocean_mask_path.resolve()}:{mstat.st_mtime_ns}:{mstat.st_size}"
    cache_key = (str(resolved), stat.st_mtime_ns, stat.st_size, layer, mask_key)

    with _PROCESSED_CACHE_LOCK:
        cached = _PROCESSED_CACHE.get(cache_key)
        if cached is not None:
            return cached

    processed = _build_processed_layer_grid(resolved, layer, ocean_mask_path=ocean_mask_path)
    with _PROCESSED_CACHE_LOCK:
        if len(_PROCESSED_CACHE) >= _MAX_PROCESSED_CACHE_ENTRIES:
            oldest_key = next(iter(_PROCESSED_CACHE))
            _PROCESSED_CACHE.pop(oldest_key, None)
        _PROCESSED_CACHE[cache_key] = processed
    return processed


def _bicubic_sample_grid(
    grid_lat: NDArray[np.float64],
    grid_lon: NDArray[np.float64],
    values: NDArray[np.float64],
    q_lat: NDArray[np.float64],
    q_lon: NDArray[np.float64],
    *,
    clamp_unit: bool = False,
) -> NDArray[np.float64]:
    """Catmull-Rom bicubic interpolation with masked bilinear fallback at NaN edges."""
    q_lat_b, q_lon_b = np.broadcast_arrays(q_lat, q_lon)
    in_bounds = (
        (q_lat_b >= grid_lat[0])
        & (q_lat_b <= grid_lat[-1])
        & (q_lon_b >= grid_lon[0])
        & (q_lon_b <= grid_lon[-1])
    )
    qlat_c = np.clip(q_lat_b, grid_lat[0], grid_lat[-1])
    qlon_c = np.clip(q_lon_b, grid_lon[0], grid_lon[-1])

    n_lat = grid_lat.size
    n_lon = grid_lon.size
    iy0 = np.clip(np.searchsorted(grid_lat, qlat_c, side="right") - 1, 0, n_lat - 2)
    ix0 = np.clip(np.searchsorted(grid_lon, qlon_c, side="right") - 1, 0, n_lon - 2)

    lat0 = grid_lat[iy0]
    lat1 = grid_lat[iy0 + 1]
    lon0 = grid_lon[ix0]
    lon1 = grid_lon[ix0 + 1]

    dlat = np.where(lat1 > lat0, lat1 - lat0, 1.0)
    dlon = np.where(lon1 > lon0, lon1 - lon0, 1.0)
    ty = np.clip((qlat_c - lat0) / dlat, 0.0, 1.0)
    tx = np.clip((qlon_c - lon0) / dlon, 0.0, 1.0)

    ty2 = ty * ty
    ty3 = ty2 * ty
    wy = (
        -0.5 * ty + ty2 - 0.5 * ty3,
        1.0 - 2.5 * ty2 + 1.5 * ty3,
        0.5 * ty + 2.0 * ty2 - 1.5 * ty3,
        -0.5 * ty2 + 0.5 * ty3,
    )
    tx2 = tx * tx
    tx3 = tx2 * tx
    wx = (
        -0.5 * tx + tx2 - 0.5 * tx3,
        1.0 - 2.5 * tx2 + 1.5 * tx3,
        0.5 * tx + 2.0 * tx2 - 1.5 * tx3,
        -0.5 * tx2 + 0.5 * tx3,
    )

    y_idx = (np.maximum(0, iy0 - 1), iy0, iy0 + 1, np.minimum(n_lat - 1, iy0 + 2))
    x_idx = (np.maximum(0, ix0 - 1), ix0, ix0 + 1, np.minimum(n_lon - 1, ix0 + 2))

    cubic_sum = np.zeros(q_lat_b.shape, dtype=np.float64)
    all_finite = in_bounds.copy()
    for a in range(4):
        yi = y_idx[a]
        wy_a = wy[a]
        for b in range(4):
            xi = x_idx[b]
            corner = values[yi, xi]
            fin = np.isfinite(corner)
            all_finite &= fin
            cubic_sum += np.where(fin, corner, 0.0) * wy_a * wx[b]

    # Bilinear fallback over finite 2x2 corners where outer 4x4 stencil hits NaN.
    v00 = values[y_idx[1], x_idx[1]]
    v01 = values[y_idx[1], x_idx[2]]
    v10 = values[y_idx[2], x_idx[1]]
    v11 = values[y_idx[2], x_idx[2]]
    f00 = np.isfinite(v00)
    f01 = np.isfinite(v01)
    f10 = np.isfinite(v10)
    f11 = np.isfinite(v11)

    w00 = np.where(f00, (1.0 - ty) * (1.0 - tx), 0.0)
    w01 = np.where(f01, (1.0 - ty) * tx, 0.0)
    w10 = np.where(f10, ty * (1.0 - tx), 0.0)
    w11 = np.where(f11, ty * tx, 0.0)
    w_tot = w00 + w01 + w10 + w11
    bi_num = (
        np.where(f00, v00 * w00, 0.0)
        + np.where(f01, v01 * w01, 0.0)
        + np.where(f10, v10 * w10, 0.0)
        + np.where(f11, v11 * w11, 0.0)
    )
    bi_val = np.where(in_bounds & (w_tot > 0.25), bi_num / np.maximum(w_tot, 1e-9), np.nan)

    # Guard against overshoot at sharp coastal gradients without All-NaN warnings.
    any_2x2 = f00 | f01 | f10 | f11
    fallback = np.where(any_2x2, bi_val, 0.0)
    safe_vals = np.stack(
        [
            np.where(f00, v00, fallback),
            np.where(f01, v01, fallback),
            np.where(f10, v10, fallback),
            np.where(f11, v11, fallback),
        ],
        axis=0,
    )
    c_min = np.min(safe_vals, axis=0)
    c_max = np.max(safe_vals, axis=0)
    margin = 0.08 * np.maximum(c_max - c_min, 0.0)
    clamped_cubic = np.clip(cubic_sum, c_min - margin, c_max + margin)

    out = np.where(all_finite, clamped_cubic, bi_val)
    if clamp_unit:
        out = np.where(np.isfinite(out), np.clip(out, 0.0, 1.0), np.nan)
    return out


def _boundary_feather_alpha(
    grid_lat: NDArray[np.float64],
    grid_lon: NDArray[np.float64],
    q_lat: NDArray[np.float64],
    q_lon: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Compute soft smoothstep alpha fade near outer regional domain edges."""
    eff_lat_min = max(INDONESIA_LAT_MIN, float(grid_lat[0]))
    eff_lat_max = min(INDONESIA_LAT_MAX, float(grid_lat[-1]))
    eff_lon_min = max(INDONESIA_LON_MIN, float(grid_lon[0]))
    eff_lon_max = min(INDONESIA_LON_MAX, float(grid_lon[-1]))

    span_lat = eff_lat_max - eff_lat_min
    span_lon = eff_lon_max - eff_lon_min
    if span_lat < 6.0 or span_lon < 6.0:
        in_box = (
            (q_lat >= eff_lat_min)
            & (q_lat <= eff_lat_max)
            & (q_lon >= eff_lon_min)
            & (q_lon <= eff_lon_max)
        )
        return in_box.astype(np.float64)

    feather_deg = min(2.25, 0.14 * min(span_lat, span_lon))
    d_lat = np.minimum(q_lat - eff_lat_min, eff_lat_max - q_lat)
    d_lon = np.minimum(q_lon - eff_lon_min, eff_lon_max - q_lon)
    f_lat = _smoothstep(0.0, feather_deg, d_lat)
    f_lon = _smoothstep(0.0, feather_deg, d_lon)
    return np.power(f_lat * f_lon, 1.15)


def _coastal_alpha_from_presence(
    ocean_occ: NDArray[np.float64],
    is_broad_grid: bool,
) -> NDArray[np.float64]:
    """Convert interpolated ocean presence into anti-aliased shoreline alpha."""
    if not is_broad_grid:
        return np.where(ocean_occ >= 0.5, 1.0, 0.0)
    return _smoothstep(0.34, 0.62, ocean_occ)


def _apply_perceptual_curve(layer: str, norm: NDArray[np.float64]) -> NDArray[np.float64]:
    """Apply smooth monotonic contrast shaping preserving colorblind-safe tonal ranges."""
    if layer == "sst":
        # Expand 25.5..31.8 C Indonesian thermal gradient while keeping 20..34 C monotonic.
        k = 5.2
        c = 0.62
        s0 = 1.0 / (1.0 + math.exp(k * c))
        s1 = 1.0 / (1.0 + math.exp(-k * (1.0 - c)))
        sig = 1.0 / (1.0 + np.exp(-k * (norm - c)))
        stretched = (sig - s0) / (s1 - s0)
        return np.clip(0.28 * norm + 0.72 * stretched, 0.0, 1.0)
    if layer == "chlorophyll":
        return np.clip(0.82 * norm + 0.18 * np.power(norm, 0.85), 0.0, 1.0)
    if layer == "currents":
        return np.clip(np.tanh(norm * 2.5 / 0.65) * 0.90 + 0.10 * norm, 0.0, 1.0)
    return norm


def _enhance_normalized_contours(
    norm_2d: NDArray[np.float64],
    contour_field_2d: NDArray[np.float64],
    step: float,
    valid_mask: NDArray[np.bool_],
    strength: float = 0.06,
) -> NDArray[np.float64]:
    """Subtle screen-space anti-aliased isoline shading inside [0, 1] colormap space."""
    if step <= 0.0 or not np.any(valid_mask):
        return norm_2d

    vals = np.where(valid_mask, contour_field_2d, np.nan)
    gx = np.zeros_like(vals, dtype=np.float64)
    gy = np.zeros_like(vals, dtype=np.float64)

    fin_x = np.isfinite(vals[:, :-2]) & np.isfinite(vals[:, 2:])
    gx[:, 1:-1] = np.where(fin_x, 0.5 * (vals[:, 2:] - vals[:, :-2]), 0.0)
    if vals.shape[1] >= 2:
        gx[:, 0] = np.where(
            np.isfinite(vals[:, 0]) & np.isfinite(vals[:, 1]), vals[:, 1] - vals[:, 0], 0.0
        )
        gx[:, -1] = np.where(
            np.isfinite(vals[:, -2]) & np.isfinite(vals[:, -1]), vals[:, -1] - vals[:, -2], 0.0
        )
    fin_y = np.isfinite(vals[:-2, :]) & np.isfinite(vals[2:, :])
    gy[1:-1, :] = np.where(fin_y, 0.5 * (vals[2:, :] - vals[:-2, :]), 0.0)
    if vals.shape[0] >= 2:
        gy[0, :] = np.where(
            np.isfinite(vals[0, :]) & np.isfinite(vals[1, :]), vals[1, :] - vals[0, :], 0.0
        )
        gy[-1, :] = np.where(
            np.isfinite(vals[-2, :]) & np.isfinite(vals[-1, :]), vals[-1, :] - vals[-2, :], 0.0
        )

    grad_px = np.hypot(gx, gy)
    phase = np.abs(((np.where(valid_mask, vals, 0.0) / step) + 0.5) % 1.0 - 0.5)
    dist_px = (phase * step) / np.maximum(grad_px, 1e-6)
    gate = np.clip((grad_px - step * 0.0012) / max(step * 0.008, 1e-6), 0.0, 1.0)
    contour = np.exp(-((dist_px / 0.85) ** 2)) * gate
    delta = np.where(norm_2d > 0.45, -strength, strength * 0.8) * contour
    return np.clip(norm_2d + np.where(valid_mask, delta, 0.0), 0.0, 1.0)


def render_tile_bytes(
    dataset_path: Path | str,
    layer: str,
    z: int,
    x: int,
    y: int,
    fmt: str = "png",
) -> tuple[bytes, bool]:
    """Render an EPSG:3857 256x256 RGBA PNG or WebP raster tile from a WGS84 NetCDF grid.

    Applies ocean-masked cloud/gap inpainting, normalized Gaussian smoothing,
    Catmull-Rom bicubic interpolation, subtle isoline enhancement, coastal
    anti-aliasing, and outer-boundary spatial feathering.
    """
    domain = _validate_layer(layer)
    fmt_lower = _validate_fmt(fmt)
    n = _validate_tile_xyz(z, x, y)
    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"NetCDF dataset not found: {path}")

    min_lon, min_lat, max_lon, max_lat = tile_bounds_wgs84(z, x, y)
    if (
        max_lon < INDONESIA_LON_MIN
        or min_lon > INDONESIA_LON_MAX
        or max_lat < INDONESIA_LAT_MIN
        or min_lat > INDONESIA_LAT_MAX
    ):
        empty_rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
        return _encode_rgba_image(empty_rgba, fmt_lower), True

    proc = _get_processed_layer_grid(path, layer)
    if not np.any(proc.ocean_mask):
        empty_rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
        return _encode_rgba_image(empty_rgba, fmt_lower), True

    # Sample with a 1-pixel border collar so gradients & contours stay seamless across tiles.
    px_pad = np.arange(-1, TILE_SIZE + 1, dtype=np.float64) + 0.5
    py_pad = np.arange(-1, TILE_SIZE + 1, dtype=np.float64) + 0.5
    x_norm_pad = (x + px_pad / TILE_SIZE) / n
    y_norm_pad = (y + py_pad / TILE_SIZE) / n

    tile_lon_pad = (x_norm_pad * 360.0) - 180.0
    tile_lat_pad = np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * y_norm_pad))))

    q_lat_pad = tile_lat_pad[:, np.newaxis]
    q_lon_pad = tile_lon_pad[np.newaxis, :]

    sampled_pad = _bicubic_sample_grid(proc.lat, proc.lon, proc.values, q_lat_pad, q_lon_pad)
    occ = _bicubic_sample_grid(
        proc.lat,
        proc.lon,
        proc.ocean_presence,
        q_lat_pad[1:-1, :],
        q_lon_pad[:, 1:-1],
        clamp_unit=True,
    )
    occ = np.where(np.isfinite(occ), occ, 0.0)

    coastal_alpha = _coastal_alpha_from_presence(occ, proc.is_broad_grid)
    boundary_alpha = _boundary_feather_alpha(
        proc.lat, proc.lon, q_lat_pad[1:-1, :], q_lon_pad[:, 1:-1]
    )
    alpha_float = coastal_alpha * boundary_alpha
    alpha_u8 = np.clip(np.round(alpha_float * 255.0), 0, 255).astype(np.uint8)

    sampled = sampled_pad[1:-1, 1:-1]
    valid = np.isfinite(sampled) & (alpha_u8 > 0)
    rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
    if not np.any(valid):
        return _encode_rgba_image(rgba, fmt_lower), True

    if domain.log10_scale:
        log_min = math.log10(domain.vmin)
        log_max = math.log10(domain.vmax)
        norm_pad = np.clip((sampled_pad - log_min) / (log_max - log_min), 0.0, 1.0)
        contour_step = 0.30
    else:
        norm_pad = np.clip((sampled_pad - domain.vmin) / (domain.vmax - domain.vmin), 0.0, 1.0)
        contour_step = 0.5 if layer == "sst" else 0.20

    norm_pad = _apply_perceptual_curve(layer, norm_pad)
    if proc.is_broad_grid:
        valid_pad = np.isfinite(sampled_pad)
        norm_pad = _enhance_normalized_contours(
            norm_pad, sampled_pad, step=contour_step, valid_mask=valid_pad, strength=0.055
        )
    norm_2d = norm_pad[1:-1, 1:-1]

    lut = _get_colormap_lut(COLORMAPS[layer])
    indices = np.clip(np.round(np.where(valid, norm_2d, 0.0) * 255.0).astype(np.int32), 0, 255)
    rgb = lut[indices][:, :, :3]
    rgba[valid, :3] = rgb[valid]
    rgba[valid, 3] = alpha_u8[valid]

    is_empty = not bool(np.any(rgba[:, :, 3] > 0))
    return _encode_rgba_image(rgba, fmt_lower), is_empty


def _write_tile_atomically(
    cache_dir: Path | str,
    layer: str,
    acq_date: str,
    z: int,
    x: int,
    y: int,
    fmt_lower: str,
    tile_bytes: bytes,
    is_empty: bool,
) -> tuple[Path, int, bool, str]:
    etag_sha256 = hashlib.sha256(tile_bytes).hexdigest()
    byte_size = len(tile_bytes)

    target_path = Path(cache_dir) / layer / acq_date / str(z) / str(x) / f"{y}.{fmt_lower}"
    target_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target_path.parent,
            prefix=f".{y}.",
            suffix=f".{fmt_lower}.tmp",
            delete=False,
        ) as tf:
            tmp_path = tf.name
            tf.write(tile_bytes)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tmp_path, target_path)
    except Exception:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return (target_path, byte_size, is_empty, etag_sha256)


def render_tile_to_cache(
    dataset_path: Path | str,
    cache_dir: Path | str,
    layer: str,
    acq_date: str,
    z: int,
    x: int,
    y: int,
    fmt: str = "png",
) -> tuple[Path, int, bool, str]:
    """Render an RGBA tile and atomically persist it under ``cache_dir``.

    Returns ``(tile_path, byte_size, is_empty, etag_sha256)``.
    """
    if not _SAFE_DATE_RE.fullmatch(acq_date):
        raise ValueError(f"Invalid acquisition date segment: {acq_date!r}")
    fmt_lower = _validate_fmt(fmt)
    tile_bytes, is_empty = render_tile_bytes(dataset_path, layer, z, x, y, fmt=fmt_lower)
    return _write_tile_atomically(
        cache_dir, layer, acq_date, z, x, y, fmt_lower, tile_bytes, is_empty
    )


def render_potential_tile_bytes(
    sst_dataset_path: Path | str,
    chl_dataset_path: Path | str,
    z: int,
    x: int,
    y: int,
    fmt: str = "png",
) -> tuple[bytes, bool]:
    """Render smoothed composite fishing potential hotspot tile from SST + Chlorophyll."""
    fmt_lower = _validate_fmt(fmt)
    n = _validate_tile_xyz(z, x, y)
    sst_path = Path(sst_dataset_path)
    chl_path = Path(chl_dataset_path)
    if not sst_path.exists():
        raise FileNotFoundError(f"SST NetCDF dataset not found: {sst_path}")
    if not chl_path.exists():
        raise FileNotFoundError(f"Chlorophyll NetCDF dataset not found: {chl_path}")

    min_lon, min_lat, max_lon, max_lat = tile_bounds_wgs84(z, x, y)
    if (
        max_lon < INDONESIA_LON_MIN
        or min_lon > INDONESIA_LON_MAX
        or max_lat < INDONESIA_LAT_MIN
        or min_lat > INDONESIA_LAT_MAX
    ):
        empty_rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
        return _encode_rgba_image(empty_rgba, fmt_lower), True

    sst_proc = _get_processed_layer_grid(sst_path, "sst")
    chl_proc = _get_processed_layer_grid(chl_path, "chlorophyll", ocean_mask_path=sst_path)
    if not np.any(sst_proc.ocean_mask):
        empty_rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
        return _encode_rgba_image(empty_rgba, fmt_lower), True

    px_pad = np.arange(-1, TILE_SIZE + 1, dtype=np.float64) + 0.5
    py_pad = np.arange(-1, TILE_SIZE + 1, dtype=np.float64) + 0.5
    x_norm_pad = (x + px_pad / TILE_SIZE) / n
    y_norm_pad = (y + py_pad / TILE_SIZE) / n
    tile_lon_pad = (x_norm_pad * 360.0) - 180.0
    tile_lat_pad = np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * y_norm_pad))))

    q_lat_pad = tile_lat_pad[:, np.newaxis]
    q_lon_pad = tile_lon_pad[np.newaxis, :]
    sst_pad = _bicubic_sample_grid(
        sst_proc.lat, sst_proc.lon, sst_proc.values, q_lat_pad, q_lon_pad
    )
    log_chl_pad = _bicubic_sample_grid(
        chl_proc.lat, chl_proc.lon, chl_proc.values, q_lat_pad, q_lon_pad
    )
    occ = _bicubic_sample_grid(
        sst_proc.lat,
        sst_proc.lon,
        sst_proc.ocean_presence,
        q_lat_pad[1:-1, :],
        q_lon_pad[:, 1:-1],
        clamp_unit=True,
    )
    occ = np.where(np.isfinite(occ), occ, 0.0)

    coastal_alpha = _coastal_alpha_from_presence(occ, sst_proc.is_broad_grid)
    boundary_alpha = _boundary_feather_alpha(
        sst_proc.lat, sst_proc.lon, q_lat_pad[1:-1, :], q_lon_pad[:, 1:-1]
    )
    ocean_alpha = coastal_alpha * boundary_alpha

    valid_ocean_pad = np.isfinite(sst_pad)
    valid_ocean = valid_ocean_pad[1:-1, 1:-1] & (ocean_alpha > 0.0)
    rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
    if not np.any(valid_ocean):
        return _encode_rgba_image(rgba, fmt_lower), True

    sst_clean_pad = np.where(valid_ocean_pad, sst_pad, 28.5)
    sst_score_pad = np.exp(-(((sst_clean_pad - 28.3) / 2.8) ** 2))

    chl_log_min = math.log10(0.06)
    chl_log_max = math.log10(1.6)
    default_log_chl = math.log10(0.24)
    log_chl_clean_pad = np.where(np.isfinite(log_chl_pad), log_chl_pad, default_log_chl)
    chl_score_pad = np.clip(
        (log_chl_clean_pad - chl_log_min) / (chl_log_max - chl_log_min),
        0.0,
        1.0,
    )

    # Highlight productive upwelling thermal fronts seamlessly across padded boundaries.
    gx_pad = np.zeros_like(sst_clean_pad)
    gy_pad = np.zeros_like(sst_clean_pad)
    fin_x = valid_ocean_pad[:, :-2] & valid_ocean_pad[:, 2:]
    gx_pad[:, 1:-1] = np.where(fin_x, 0.5 * (sst_clean_pad[:, 2:] - sst_clean_pad[:, :-2]), 0.0)
    fin_y = valid_ocean_pad[:-2, :] & valid_ocean_pad[2:, :]
    gy_pad[1:-1, :] = np.where(fin_y, 0.5 * (sst_clean_pad[2:, :] - sst_clean_pad[:-2, :]), 0.0)
    dlon_px = max((max_lon - min_lon) / TILE_SIZE, 1e-6)
    dlat_px = max((max_lat - min_lat) / TILE_SIZE, 1e-6)
    grad_deg_pad = np.hypot(gx_pad / dlon_px, gy_pad / dlat_px)
    front_bonus_pad = 0.08 * np.clip((grad_deg_pad - 0.35) / 1.4, 0.0, 1.0) * chl_score_pad

    score_pad = np.clip(0.40 * sst_score_pad + 0.56 * chl_score_pad + front_bonus_pad, 0.0, 1.0)
    score = score_pad[1:-1, 1:-1]
    pot_ramp = _smoothstep(0.28, 0.46, score) * (0.45 + 0.55 * _smoothstep(0.46, 0.92, score))
    alpha_u8 = np.clip(np.round(228.0 * pot_ramp * ocean_alpha), 0, 255).astype(np.uint8)
    active = valid_ocean & (alpha_u8 > 0)
    if not np.any(active):
        return _encode_rgba_image(rgba, fmt_lower), True

    t_pad = np.clip((score_pad - 0.30) / 0.70, 0.0, 1.0)
    if sst_proc.is_broad_grid:
        t_pad = _enhance_normalized_contours(
            t_pad, score_pad, step=0.16, valid_mask=valid_ocean_pad, strength=0.05
        )
    t = t_pad[1:-1, 1:-1]

    # Sea-teal (#14B8A6) -> Emerald (#22C55E) -> Warm Gold (#F59E0B)
    r_lo = 20.0 + (34.0 - 20.0) * (t / 0.55)
    r_hi = 34.0 + (245.0 - 34.0) * ((t - 0.55) / 0.45)
    g_lo = 184.0 + (197.0 - 184.0) * (t / 0.55)
    g_hi = 197.0 + (158.0 - 197.0) * ((t - 0.55) / 0.45)
    b_lo = 166.0 + (94.0 - 166.0) * (t / 0.55)
    b_hi = 94.0 + (11.0 - 94.0) * ((t - 0.55) / 0.45)
    r = np.where(t < 0.55, r_lo, r_hi)
    g = np.where(t < 0.55, g_lo, g_hi)
    b = np.where(t < 0.55, b_lo, b_hi)

    rgba[active, 0] = np.clip(np.round(r[active]), 0, 255).astype(np.uint8)
    rgba[active, 1] = np.clip(np.round(g[active]), 0, 255).astype(np.uint8)
    rgba[active, 2] = np.clip(np.round(b[active]), 0, 255).astype(np.uint8)
    rgba[active, 3] = alpha_u8[active]

    is_empty = not bool(np.any(rgba[:, :, 3] > 0))
    return _encode_rgba_image(rgba, fmt_lower), is_empty


def render_potential_tile_to_cache(
    sst_dataset_path: Path | str,
    chl_dataset_path: Path | str,
    cache_dir: Path | str,
    acq_date: str,
    z: int,
    x: int,
    y: int,
    fmt: str = "png",
) -> tuple[Path, int, bool, str]:
    """Render and atomically cache a composite fishing potential RGBA tile."""
    if not _SAFE_DATE_RE.fullmatch(acq_date):
        raise ValueError(f"Invalid acquisition date segment: {acq_date!r}")
    fmt_lower = _validate_fmt(fmt)
    tile_bytes, is_empty = render_potential_tile_bytes(
        sst_dataset_path, chl_dataset_path, z, x, y, fmt=fmt_lower
    )
    return _write_tile_atomically(
        cache_dir, "potential", acq_date, z, x, y, fmt_lower, tile_bytes, is_empty
    )


def sample_currents_grid(
    dataset_path: Path | str,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    max_vectors: int = 160,
    ocean_mask_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return ocean-masked, equatorial-filled decimated current vectors within a bbox."""
    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Currents NetCDF dataset not found: {path}")

    mask_path = Path(ocean_mask_path) if ocean_mask_path is not None else None
    proc = _get_processed_layer_grid(path, "currents", ocean_mask_path=mask_path)
    if proc.u_ms is None or proc.v_ms is None:
        return {
            "vectors": [],
            "acquired_at_utc": proc.acquired_at_utc,
            "primary_source": proc.primary_source,
        }

    lat_idx = np.where((proc.lat >= min_lat) & (proc.lat <= max_lat))[0]
    lon_idx = np.where((proc.lon >= min_lon) & (proc.lon <= max_lon))[0]
    if lat_idx.size == 0 or lon_idx.size == 0:
        return {
            "vectors": [],
            "acquired_at_utc": proc.acquired_at_utc,
            "primary_source": proc.primary_source,
        }

    cap = max(1, max_vectors)
    n_lat = lat_idx.size
    n_lon = lon_idx.size
    if n_lat * n_lon <= cap:
        lat_step = 1
        lon_step = 1
    else:
        ratio = n_lon / max(1, n_lat)
        target_lat = max(2, int(round(math.sqrt(cap / max(0.25, ratio)))))
        target_lon = max(2, cap // target_lat)
        lat_step = max(1, math.ceil(n_lat / target_lat))
        lon_step = max(1, math.ceil(n_lon / target_lon))
        while math.ceil(n_lat / lat_step) * math.ceil(n_lon / lon_step) > cap:
            if math.ceil(n_lon / lon_step) >= math.ceil(n_lat / lat_step):
                lon_step += 1
            else:
                lat_step += 1

    vectors: list[dict[str, float]] = []
    for iy in lat_idx[::lat_step]:
        for ix in lon_idx[::lon_step]:
            if not proc.ocean_mask[iy, ix]:
                continue
            u_val = float(proc.u_ms[iy, ix])
            v_val = float(proc.v_ms[iy, ix])
            if not (math.isfinite(u_val) and math.isfinite(v_val)):
                continue
            speed = math.hypot(u_val, v_val)
            if speed < 0.01:
                continue
            direction = (math.degrees(math.atan2(u_val, v_val)) + 360.0) % 360.0
            vectors.append(
                {
                    "lat": round(float(proc.lat[iy]), 3),
                    "lon": round(float(proc.lon[ix]), 3),
                    "u_ms": round(u_val, 3),
                    "v_ms": round(v_val, 3),
                    "speed_ms": round(speed, 3),
                    "speed_knots": round(speed * 1.94384, 3),
                    "direction_deg": round(direction, 1),
                }
            )

    return {
        "vectors": vectors,
        "acquired_at_utc": proc.acquired_at_utc,
        "primary_source": proc.primary_source,
    }


def _nearest_within_one_cell(
    grid_lat: NDArray[np.float64],
    grid_lon: NDArray[np.float64],
    valid_mask: NDArray[np.bool_],
    lat: float,
    lon: float,
) -> tuple[int, int] | None:
    dlat = max(float(np.median(np.abs(np.diff(grid_lat)))), 1e-9)
    dlon = max(float(np.median(np.abs(np.diff(grid_lon)))), 1e-9)

    lat_idx = np.where(np.abs(grid_lat - lat) <= dlat + 1e-9)[0]
    lon_idx = np.where(np.abs(grid_lon - lon) <= dlon + 1e-9)[0]
    if lat_idx.size == 0 or lon_idx.size == 0:
        return None

    sub_valid = valid_mask[np.ix_(lat_idx, lon_idx)]
    if not np.any(sub_valid):
        return None

    rel_y, rel_x = np.where(sub_valid)
    cand_y = lat_idx[rel_y]
    cand_x = lon_idx[rel_x]

    dist_sq = ((grid_lat[cand_y] - lat) / dlat) ** 2 + ((grid_lon[cand_x] - lon) / dlon) ** 2
    best = int(np.argmin(dist_sq))
    return (int(cand_y[best]), int(cand_x[best]))


def _unavailable_point_result(
    layer: str,
    domain: LayerDomain,
    spatial_resolution_km: float | None = None,
    acquired_at_utc: str | None = None,
    primary_source: str | None = None,
) -> dict[str, float | str | None]:
    result: dict[str, float | str | None] = {
        "layer": layer,
        "interpolation_method": "unavailable",
        "value": None,
        "units": domain.units,
        "spatial_resolution_km": spatial_resolution_km,
        "acquired_at_utc": acquired_at_utc,
        "primary_source": primary_source,
    }
    if layer == "sst":
        result["sst_c"] = None
    elif layer == "chlorophyll":
        result["chlorophyll_mg_m3"] = None
    elif layer == "currents":
        result["u_ms"] = None
        result["v_ms"] = None
        result["current_speed_ms"] = None
        result["current_direction_deg"] = None
    return result


def sample_point_from_netcdf(
    dataset_path: Path | str,
    layer: str,
    lat: float,
    lon: float,
) -> dict[str, float | str | None]:
    """Interpolate a single WGS84 point from a NetCDF layer grid.

    Attempts bilinear interpolation first (``interpolation_method="bilinear"``); if the
    surrounding cell borders a land/NaN mask, falls back to the nearest finite cell within
    ``<= 1`` grid cell (``interpolation_method="nearest"``); otherwise returns
    ``interpolation_method="unavailable"`` with ``None`` values.
    """
    domain = _validate_layer(layer)
    if not (math.isfinite(lat) and -90.0 <= lat <= 90.0):
        raise ValueError(f"Latitude {lat!r} out of valid range [-90, 90]")
    if not (math.isfinite(lon) and -180.0 <= lon <= 180.0):
        raise ValueError(f"Longitude {lon!r} out of valid range [-180, 180]")

    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"NetCDF dataset not found: {path}")

    grid = _load_layer_grid(path, layer)

    if not (
        INDONESIA_LAT_MIN <= lat <= INDONESIA_LAT_MAX
        and INDONESIA_LON_MIN <= lon <= INDONESIA_LON_MAX
    ):
        return _unavailable_point_result(
            layer,
            domain,
            spatial_resolution_km=grid.spatial_resolution_km,
            acquired_at_utc=grid.acquired_at_utc,
            primary_source=grid.primary_source,
        )

    q_lat = np.array([lat], dtype=np.float64)
    q_lon = np.array([lon], dtype=np.float64)

    if layer == "currents" and grid.u_ms is not None and grid.v_ms is not None:
        u_lin = float(_bilinear_sample_grid(grid.lat, grid.lon, grid.u_ms, q_lat, q_lon)[0])
        v_lin = float(_bilinear_sample_grid(grid.lat, grid.lon, grid.v_ms, q_lat, q_lon)[0])
        if math.isfinite(u_lin) and math.isfinite(v_lin):
            method = "bilinear"
            u_val = u_lin
            v_val = v_lin
        else:
            valid_uv = np.isfinite(grid.u_ms) & np.isfinite(grid.v_ms)
            nearest = _nearest_within_one_cell(grid.lat, grid.lon, valid_uv, lat, lon)
            if nearest is None:
                return _unavailable_point_result(
                    layer,
                    domain,
                    spatial_resolution_km=grid.spatial_resolution_km,
                    acquired_at_utc=grid.acquired_at_utc,
                    primary_source=grid.primary_source,
                )
            method = "nearest"
            u_val = float(grid.u_ms[nearest])
            v_val = float(grid.v_ms[nearest])

        speed = float(math.hypot(u_val, v_val))
        direction = (math.degrees(math.atan2(u_val, v_val)) + 360.0) % 360.0
        currents_result: dict[str, float | str | None] = {
            "layer": layer,
            "interpolation_method": method,
            "value": speed,
            "units": domain.units,
            "spatial_resolution_km": grid.spatial_resolution_km,
            "acquired_at_utc": grid.acquired_at_utc,
            "primary_source": grid.primary_source,
            "u_ms": u_val,
            "v_ms": v_val,
            "current_speed_ms": speed,
            "current_direction_deg": direction,
        }
        return currents_result

    lin_val = float(_bilinear_sample_grid(grid.lat, grid.lon, grid.primary, q_lat, q_lon)[0])
    is_valid_lin = math.isfinite(lin_val) and (not domain.log10_scale or lin_val > 0.0)
    if is_valid_lin:
        method = "bilinear"
        scalar_val = lin_val
    else:
        valid_mask = np.isfinite(grid.primary)
        if domain.log10_scale:
            valid_mask &= grid.primary > 0.0
        nearest = _nearest_within_one_cell(grid.lat, grid.lon, valid_mask, lat, lon)
        if nearest is None:
            return _unavailable_point_result(
                layer,
                domain,
                spatial_resolution_km=grid.spatial_resolution_km,
                acquired_at_utc=grid.acquired_at_utc,
                primary_source=grid.primary_source,
            )
        method = "nearest"
        scalar_val = float(grid.primary[nearest])

    result: dict[str, float | str | None] = {
        "layer": layer,
        "interpolation_method": method,
        "value": scalar_val,
        "units": domain.units,
        "spatial_resolution_km": grid.spatial_resolution_km,
        "acquired_at_utc": grid.acquired_at_utc,
        "primary_source": grid.primary_source,
    }
    if layer == "sst":
        result["sst_c"] = scalar_val
    elif layer == "chlorophyll":
        result["chlorophyll_mg_m3"] = scalar_val
    elif layer == "currents":
        result["u_ms"] = None
        result["v_ms"] = None
        result["current_speed_ms"] = scalar_val
        result["current_direction_deg"] = None
    return result
