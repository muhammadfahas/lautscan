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

    if len(current_dims) == 2 and lat_dim is not None and lon_dim is not None:
        if current_dims[0] == lon_dim and current_dims[1] == lat_dim:
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
        if "kelvin" in units or units == "k" or (
            finite_vals.size > 0 and float(np.nanmedian(finite_vals)) > 150.0
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
    primary_source = _decode_attr(
        global_attrs.get("primary_source") or global_attrs.get("source")
    )

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

    valid = (
        in_bounds
        & np.isfinite(v00)
        & np.isfinite(v01)
        & np.isfinite(v10)
        & np.isfinite(v11)
    )
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
        img.save(buf, format="WEBP", lossless=True)
    return buf.getvalue()


def render_tile_bytes(
    dataset_path: Path | str,
    layer: str,
    z: int,
    x: int,
    y: int,
    fmt: str = "png",
) -> tuple[bytes, bool]:
    """Render an EPSG:3857 256x256 RGBA PNG or WebP raster tile from a WGS84 NetCDF grid.

    Returns ``(encoded_bytes, is_empty)`` where ``is_empty`` is ``True`` when every pixel
    has ``alpha == 0`` (out of Indonesia domain, over land, or masked NaN).
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

    grid = _load_layer_grid(path, layer)

    px = np.arange(TILE_SIZE, dtype=np.float64) + 0.5
    py = np.arange(TILE_SIZE, dtype=np.float64) + 0.5
    x_norm = (x + px / TILE_SIZE) / n
    y_norm = (y + py / TILE_SIZE) / n

    tile_lon = (x_norm * 360.0) - 180.0
    tile_lat = np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * y_norm))))

    q_lat = tile_lat[:, np.newaxis]
    q_lon = tile_lon[np.newaxis, :]

    if layer == "currents" and grid.u_ms is not None and grid.v_ms is not None:
        u_interp = _bilinear_sample_grid(grid.lat, grid.lon, grid.u_ms, q_lat, q_lon)
        v_interp = _bilinear_sample_grid(grid.lat, grid.lon, grid.v_ms, q_lat, q_lon)
        sampled = np.hypot(u_interp, v_interp)
    else:
        sampled = _bilinear_sample_grid(grid.lat, grid.lon, grid.primary, q_lat, q_lon)

    in_indonesia = (
        (q_lat >= INDONESIA_LAT_MIN)
        & (q_lat <= INDONESIA_LAT_MAX)
        & (q_lon >= INDONESIA_LON_MIN)
        & (q_lon <= INDONESIA_LON_MAX)
    )
    valid = in_indonesia & np.isfinite(sampled)
    if domain.log10_scale:
        valid &= sampled > 0.0

    rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
    if not np.any(valid):
        return _encode_rgba_image(rgba, fmt_lower), True

    vals = sampled[valid]
    if domain.log10_scale:
        clipped = np.clip(vals, domain.vmin, domain.vmax)
        log_min = math.log10(domain.vmin)
        log_max = math.log10(domain.vmax)
        norm = (np.log10(clipped) - log_min) / (log_max - log_min)
    else:
        norm = (vals - domain.vmin) / (domain.vmax - domain.vmin)
    norm = np.clip(norm, 0.0, 1.0)

    lut = _get_colormap_lut(COLORMAPS[layer])
    indices = np.clip(np.round(norm * 255.0).astype(np.int32), 0, 255)
    rgba[valid] = lut[indices]

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
    """Render composite fishing potential hotspot tile from SST + Chlorophyll grids."""
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

    sst_grid = _load_layer_grid(sst_path, "sst")
    chl_grid = _load_layer_grid(chl_path, "chlorophyll")

    px = np.arange(TILE_SIZE, dtype=np.float64) + 0.5
    py = np.arange(TILE_SIZE, dtype=np.float64) + 0.5
    x_norm = (x + px / TILE_SIZE) / n
    y_norm = (y + py / TILE_SIZE) / n
    tile_lon = (x_norm * 360.0) - 180.0
    tile_lat = np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * y_norm))))

    q_lat = tile_lat[:, np.newaxis]
    q_lon = tile_lon[np.newaxis, :]
    sst_vals = _bilinear_sample_grid(sst_grid.lat, sst_grid.lon, sst_grid.primary, q_lat, q_lon)
    chl_vals = _bilinear_sample_grid(chl_grid.lat, chl_grid.lon, chl_grid.primary, q_lat, q_lon)

    in_indonesia = (
        (q_lat >= INDONESIA_LAT_MIN)
        & (q_lat <= INDONESIA_LAT_MAX)
        & (q_lon >= INDONESIA_LON_MIN)
        & (q_lon <= INDONESIA_LON_MAX)
    )
    valid = in_indonesia & np.isfinite(sst_vals) & np.isfinite(chl_vals) & (chl_vals > 0.0)
    rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
    if not np.any(valid):
        return _encode_rgba_image(rgba, fmt_lower), True

    sst_v = sst_vals[valid]
    chl_v = chl_vals[valid]
    sst_score = np.exp(-(((sst_v - 28.5) / 2.2) ** 2))
    chl_log_min = math.log10(0.18)
    chl_log_max = math.log10(1.8)
    chl_score = np.clip(
        (np.log10(np.maximum(chl_v, 0.01)) - chl_log_min) / (chl_log_max - chl_log_min),
        0.0,
        1.0,
    )
    score = 0.45 * sst_score + 0.55 * chl_score

    hotspot = score >= 0.48
    if not np.any(hotspot):
        return _encode_rgba_image(rgba, fmt_lower), True

    t = np.clip((score[hotspot] - 0.48) / 0.52, 0.0, 1.0)
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
    a = 80.0 + 135.0 * (t ** 0.8)

    hot_colors = np.stack([r, g, b, a], axis=-1).clip(0, 255).astype(np.uint8)
    hotspot_rgba = np.zeros((sst_v.size, 4), dtype=np.uint8)
    hotspot_rgba[hotspot] = hot_colors
    rgba[valid] = hotspot_rgba

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
) -> dict[str, Any]:
    """Return decimated ocean current velocity vectors within a WGS84 bounding box."""
    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Currents NetCDF dataset not found: {path}")

    grid = _load_layer_grid(path, "currents")
    if grid.u_ms is None or grid.v_ms is None:
        return {
            "vectors": [],
            "acquired_at_utc": grid.acquired_at_utc,
            "primary_source": grid.primary_source,
        }

    lat_idx = np.where((grid.lat >= min_lat) & (grid.lat <= max_lat))[0]
    lon_idx = np.where((grid.lon >= min_lon) & (grid.lon <= max_lon))[0]
    if lat_idx.size == 0 or lon_idx.size == 0:
        return {
            "vectors": [],
            "acquired_at_utc": grid.acquired_at_utc,
            "primary_source": grid.primary_source,
        }

    target_axis = max(4, int(math.sqrt(max(1, max_vectors))))
    lat_step = max(1, math.ceil(lat_idx.size / target_axis))
    lon_step = max(1, math.ceil(lon_idx.size / target_axis))

    vectors: list[dict[str, float]] = []
    for iy in lat_idx[::lat_step]:
        for ix in lon_idx[::lon_step]:
            u_val = float(grid.u_ms[iy, ix])
            v_val = float(grid.v_ms[iy, ix])
            if not (math.isfinite(u_val) and math.isfinite(v_val)):
                continue
            speed = math.hypot(u_val, v_val)
            if speed < 0.01:
                continue
            direction = (math.degrees(math.atan2(u_val, v_val)) + 360.0) % 360.0
            vectors.append(
                {
                    "lat": round(float(grid.lat[iy]), 3),
                    "lon": round(float(grid.lon[ix]), 3),
                    "u_ms": round(u_val, 3),
                    "v_ms": round(v_val, 3),
                    "speed_ms": round(speed, 3),
                    "speed_knots": round(speed * 1.94384, 3),
                    "direction_deg": round(direction, 1),
                }
            )

    return {
        "vectors": vectors,
        "acquired_at_utc": grid.acquired_at_utc,
        "primary_source": grid.primary_source,
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
