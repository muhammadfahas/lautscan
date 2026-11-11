"""Unit tests for the LAUT SCAN EPSG:3857 raster tiler and offline NetCDF fixtures."""

from __future__ import annotations

import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from app.etl.fixtures import (
    _write_netcdf3_classic_pure,
    ensure_sample_netcdf,
)
from app.etl.tiler import (
    COLORMAPS,
    PROHIBITED_COLORMAPS,
    TILE_SIZE,
    _get_colormap_lut,
    _read_netcdf3_classic_pure,
    render_tile_bytes,
    render_tile_to_cache,
    sample_point_from_netcdf,
    tile_bounds_wgs84,
)


def _write_test_netcdf_3d_or_2d(
    path: Path,
    lat: np.ndarray,
    lon: np.ndarray,
    vars_dict: dict[str, tuple[tuple[str, ...], np.ndarray, dict[str, object]]],
    global_attrs: dict[str, object] | None = None,
) -> None:
    """Write a NetCDF-3 test file via scipy if present or pure-Python NetCDF-3 fallback."""
    attrs = global_attrs or {"Conventions": "CF-1.8", "primary_source": "test_fixture"}
    try:
        from scipy.io import netcdf_file

        with netcdf_file(str(path), "w", version=1) as nc:
            for k, v in attrs.items():
                setattr(nc, k, v)
            nc.createDimension("lat", lat.size)
            nc.createDimension("lon", lon.size)
            has_time = any("time" in dims for dims, _, _ in vars_dict.values())
            if has_time:
                nc.createDimension("time", 1)
                t_var = nc.createVariable("time", "d", ("time",))
                t_var[:] = np.array([0.0], dtype=np.float64)

            lat_v = nc.createVariable("lat", "d", ("lat",))
            lat_v[:] = lat
            lon_v = nc.createVariable("lon", "d", ("lon",))
            lon_v[:] = lon

            for name, (dims, arr, vattrs) in vars_dict.items():
                v = nc.createVariable(name, "f", dims)
                v[:] = np.asarray(arr, dtype=np.float32)
                for ak, av in vattrs.items():
                    setattr(v, ak, av)
        return
    except ImportError:
        pass

    # Fallback pure-Python writer (2D lat/lon grids)
    pure_vars = {
        name: (np.asarray(arr, dtype=np.float32), dict(vattrs))
        for name, (_, arr, vattrs) in vars_dict.items()
    }
    _write_netcdf3_classic_pure(path, lat, lon, pure_vars, attrs)


class TestColormapsAndBounds(unittest.TestCase):
    def test_colorblind_safe_colormaps_enforced(self) -> None:
        self.assertEqual(
            COLORMAPS,
            {
                "sst": "plasma",
                "chlorophyll": "viridis",
                "currents": "cividis",
            },
        )
        for cmap_name in COLORMAPS.values():
            self.assertNotIn(cmap_name.lower(), PROHIBITED_COLORMAPS)
            lut = _get_colormap_lut(cmap_name)
            self.assertEqual(lut.shape, (256, 4))
            self.assertEqual(lut.dtype, np.uint8)

        for bad_cmap in ("jet", "rainbow", "turbo"):
            with self.assertRaises(ValueError):
                _get_colormap_lut(bad_cmap)

    def test_tile_bounds_and_validation(self) -> None:
        min_lon, min_lat, max_lon, max_lat = tile_bounds_wgs84(6, 52, 32)
        self.assertAlmostEqual(min_lon, 112.5, places=6)
        self.assertAlmostEqual(max_lon, 118.125, places=6)
        self.assertLess(min_lat, 0.0)
        self.assertAlmostEqual(max_lat, 0.0, places=6)

        with self.assertRaises(ValueError):
            tile_bounds_wgs84(-1, 0, 0)
        with self.assertRaises(ValueError):
            tile_bounds_wgs84(15, 0, 0)
        with self.assertRaises(ValueError):
            tile_bounds_wgs84(3, 8, 0)
        with self.assertRaises(ValueError):
            tile_bounds_wgs84(3, 0, -1)


class TestFixturesAndNetcdfFallbacks(unittest.TestCase):
    def test_ensure_sample_netcdf_deterministic_and_cf_compliant(self) -> None:
        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            d1, d2 = Path(td1), Path(td2)
            for layer in ("sst", "chlorophyll", "currents"):
                p1 = ensure_sample_netcdf(d1, layer, "2026-11-11")
                p1_repeat = ensure_sample_netcdf(d1, layer, "2026-11-11")
                p2 = ensure_sample_netcdf(d2, layer, "2026-11-11")

                self.assertEqual(p1, p1_repeat)
                self.assertTrue(p1.exists())
                self.assertGreater(p1.stat().st_size, 0)
                self.assertEqual(p1.read_bytes(), p2.read_bytes())

                # Verify pure-Python NetCDF-3 reader parses the generated file identically
                vars_map, gattrs = _read_netcdf3_classic_pure(p1)
                self.assertEqual(gattrs.get("Conventions"), "CF-1.8")
                self.assertIn("lat", vars_map)
                self.assertIn("lon", vars_map)
                lat_vals = vars_map["lat"][1]
                lon_vals = vars_map["lon"][1]
                self.assertAlmostEqual(float(lat_vals[0]), -15.0)
                self.assertAlmostEqual(float(lat_vals[-1]), 10.0)
                self.assertAlmostEqual(float(lon_vals[0]), 90.0)
                self.assertAlmostEqual(float(lon_vals[-1]), 145.0)

                if layer == "currents":
                    self.assertIn("u_ms", vars_map)
                    self.assertIn("v_ms", vars_map)
                else:
                    self.assertIn(layer, vars_map)

            latest_path = ensure_sample_netcdf(d1, "sst", "latest")
            self.assertTrue(latest_path.exists())

    def test_pure_netcdf3_writer_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "pure_roundtrip.nc"
            lat = np.array([-8.0, -7.0, -6.0], dtype=np.float64)
            lon = np.array([108.0, 109.0, 110.0], dtype=np.float64)
            sst = np.array(
                [
                    [27.0, 28.0, np.nan],
                    [27.5, 28.5, 29.5],
                    [28.0, 29.0, 30.0],
                ],
                dtype=np.float32,
            )
            _write_netcdf3_classic_pure(
                out_path,
                lat,
                lon,
                {"sst": (sst, {"units": "degree_C", "_FillValue": np.float32(np.nan)})},
                {"Conventions": "CF-1.8", "primary_source": "pure_test"},
            )
            vars_map, gattrs = _read_netcdf3_classic_pure(out_path)
            self.assertEqual(gattrs["Conventions"], "CF-1.8")
            self.assertEqual(gattrs["primary_source"], "pure_test")
            read_sst = vars_map["sst"][1]
            self.assertTrue(np.isnan(read_sst[0, 2]))
            self.assertAlmostEqual(float(read_sst[1, 1]), 28.5, places=5)

            pt = sample_point_from_netcdf(out_path, "sst", -6.5, 109.5)
            self.assertEqual(pt["interpolation_method"], "bilinear")
            self.assertAlmostEqual(float(pt["sst_c"]), 29.25, places=5)

    def test_pure_python_fallback_without_xarray_netcdf4_scipy(self) -> None:
        blocked = {"xarray": None, "netCDF4": None, "scipy": None, "scipy.io": None}
        with tempfile.TemporaryDirectory() as td, patch.dict(sys.modules, blocked):
            cache_dir = Path(td)
            nc_path = ensure_sample_netcdf(cache_dir, "sst", "2026-11-11")
            raw_bytes, is_empty = render_tile_bytes(nc_path, "sst", z=5, x=26, y=16, fmt="png")
            self.assertFalse(is_empty)
            img = Image.open(io.BytesIO(raw_bytes))
            self.assertEqual(img.size, (TILE_SIZE, TILE_SIZE))
            self.assertEqual(img.mode, "RGBA")

            pt = sample_point_from_netcdf(nc_path, "sst", -6.12, 108.45)
            self.assertEqual(pt["interpolation_method"], "bilinear")
            self.assertIsNotNone(pt["sst_c"])


class TestTileRendering(unittest.TestCase):
    def test_render_rgba_png_and_webp_tiles_for_all_layers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td)
            for layer in ("sst", "chlorophyll", "currents"):
                nc_path = ensure_sample_netcdf(cache_dir, layer, "2026-11-11")
                expected_lut = _get_colormap_lut(COLORMAPS[layer])[:, :3]

                for fmt in ("png", "webp"):
                    # Tile (z=5, x=26, y=16) covers lon ~112.5..123.75, lat ~-11.18..0.0
                    # (Java Sea, Makassar Strait, Kalimantan, Sulawesi -> both ocean & land!)
                    raw_bytes, is_empty = render_tile_bytes(
                        nc_path, layer, z=5, x=26, y=16, fmt=fmt
                    )
                    self.assertFalse(is_empty, f"Expected non-empty tile for {layer} ({fmt})")

                    img = Image.open(io.BytesIO(raw_bytes))
                    self.assertEqual(img.mode, "RGBA")
                    self.assertEqual(img.size, (TILE_SIZE, TILE_SIZE))

                    arr = np.asarray(img)
                    self.assertEqual(arr.shape, (TILE_SIZE, TILE_SIZE, 4))
                    alpha = arr[:, :, 3]
                    self.assertTrue(np.any(alpha == 255), "Expected opaque ocean pixels")
                    self.assertTrue(np.any(alpha == 0), "Expected transparent land pixels")

                    # Transparent pixels must stay zeroed out (alpha=0)
                    transparent_rgb = arr[alpha == 0][:, :3]
                    self.assertTrue(np.all(transparent_rgb == 0))

                    # Opaque pixels must come strictly from the layer's colorblind-safe LUT
                    opaque_rgb = arr[alpha == 255][:, :3]
                    lut_set = {tuple(int(c) for c in row) for row in expected_lut}
                    sample_rgb = {tuple(int(c) for c in row) for row in opaque_rgb[:200]}
                    self.assertTrue(sample_rgb.issubset(lut_set))

    def test_out_of_indonesia_bounds_and_all_nan_produce_empty_transparent_tile(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td)
            nc_path = ensure_sample_netcdf(cache_dir, "sst", "2026-11-11")

            # North Atlantic tile (completely outside lon 90..145, lat -15..10)
            for fmt in ("png", "webp"):
                raw_bytes, is_empty = render_tile_bytes(nc_path, "sst", z=4, x=5, y=5, fmt=fmt)
                self.assertTrue(is_empty)
                arr = np.asarray(Image.open(io.BytesIO(raw_bytes)).convert("RGBA"))
                self.assertEqual(arr.shape, (TILE_SIZE, TILE_SIZE, 4))
                self.assertTrue(np.all(arr[:, :, 3] == 0))

            # Synthetic all-NaN dataset inside Indonesia
            nan_nc = cache_dir / "all_nan.nc"
            lat = np.array([-8.0, -6.0, -4.0], dtype=np.float64)
            lon = np.array([108.0, 110.0, 112.0], dtype=np.float64)
            nan_grid = np.full((3, 3), np.nan, dtype=np.float32)
            _write_test_netcdf_3d_or_2d(
                nan_nc,
                lat,
                lon,
                {"sst": (("lat", "lon"), nan_grid, {"units": "degree_C"})},
            )
            raw_bytes, is_empty = render_tile_bytes(nan_nc, "sst", z=5, x=25, y=16, fmt="png")
            self.assertTrue(is_empty)
            arr = np.asarray(Image.open(io.BytesIO(raw_bytes)).convert("RGBA"))
            self.assertTrue(np.all(arr[:, :, 3] == 0))

    def test_render_tile_to_cache_atomic_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td)
            nc_path = ensure_sample_netcdf(cache_dir, "chlorophyll", "2026-11-11")

            tile_path, byte_size, is_empty, etag = render_tile_to_cache(
                dataset_path=nc_path,
                cache_dir=cache_dir,
                layer="chlorophyll",
                acq_date="2026-11-11",
                z=5,
                x=26,
                y=16,
                fmt="webp",
            )
            self.assertFalse(is_empty)
            self.assertEqual(
                tile_path,
                cache_dir / "chlorophyll" / "2026-11-11" / "5" / "26" / "16.webp",
            )
            self.assertTrue(tile_path.exists())
            disk_bytes = tile_path.read_bytes()
            self.assertEqual(len(disk_bytes), byte_size)
            self.assertEqual(hashlib.sha256(disk_bytes).hexdigest(), etag)
            # No leftover temporary files
            tmp_files = list(tile_path.parent.glob("*.tmp"))
            self.assertEqual(tmp_files, [])

            with self.assertRaises(ValueError):
                render_tile_to_cache(
                    nc_path, cache_dir, "chlorophyll", "../bad", 5, 26, 16, fmt="png"
                )
            with self.assertRaises(ValueError):
                render_tile_bytes(nc_path, "invalid_layer", 5, 26, 16)
            with self.assertRaises(ValueError):
                render_tile_bytes(nc_path, "sst", 5, 26, 16, fmt="jpeg")
            with self.assertRaises(FileNotFoundError):
                render_tile_bytes(cache_dir / "missing.nc", "sst", 5, 26, 16)


class TestPointInspection(unittest.TestCase):
    def test_sample_point_from_fixtures_bilinear_and_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td)

            # Open water in Java Sea (lat=-6.12, lon=108.45)
            sst_nc = ensure_sample_netcdf(cache_dir, "sst", "2026-11-11")
            chl_nc = ensure_sample_netcdf(cache_dir, "chlorophyll", "2026-11-11")
            cur_nc = ensure_sample_netcdf(cache_dir, "currents", "2026-11-11")

            sst_pt = sample_point_from_netcdf(sst_nc, "sst", -6.12, 108.45)
            self.assertEqual(sst_pt["interpolation_method"], "bilinear")
            self.assertIsNotNone(sst_pt["sst_c"])
            self.assertGreaterEqual(float(sst_pt["sst_c"]), 20.0)
            self.assertLessEqual(float(sst_pt["sst_c"]), 34.0)
            self.assertEqual(sst_pt["acquired_at_utc"], "2026-11-11T12:00:00Z")
            self.assertEqual(sst_pt["primary_source"], "noaa_erddap")

            chl_pt = sample_point_from_netcdf(chl_nc, "chlorophyll", -6.12, 108.45)
            self.assertEqual(chl_pt["interpolation_method"], "bilinear")
            self.assertIsNotNone(chl_pt["chlorophyll_mg_m3"])
            self.assertGreaterEqual(float(chl_pt["chlorophyll_mg_m3"]), 0.01)
            self.assertLessEqual(float(chl_pt["chlorophyll_mg_m3"]), 10.0)

            cur_pt = sample_point_from_netcdf(cur_nc, "currents", -6.12, 108.45)
            self.assertEqual(cur_pt["interpolation_method"], "bilinear")
            self.assertIsNotNone(cur_pt["current_speed_ms"])
            self.assertIsNotNone(cur_pt["current_direction_deg"])
            self.assertGreaterEqual(float(cur_pt["current_speed_ms"]), 0.0)
            self.assertLessEqual(float(cur_pt["current_speed_ms"]), 2.5)
            self.assertGreaterEqual(float(cur_pt["current_direction_deg"]), 0.0)
            self.assertLess(float(cur_pt["current_direction_deg"]), 360.0)

            # Deep inland Borneo -> unavailable
            land_pt = sample_point_from_netcdf(sst_nc, "sst", 0.0, 114.0)
            self.assertEqual(land_pt["interpolation_method"], "unavailable")
            self.assertIsNone(land_pt["value"])
            self.assertIsNone(land_pt["sst_c"])

            # Outside Indonesia domain -> unavailable
            outside_pt = sample_point_from_netcdf(sst_nc, "sst", 35.0, 139.0)
            self.assertEqual(outside_pt["interpolation_method"], "unavailable")
            self.assertIsNone(outside_pt["value"])

            # Invalid WGS84 coords raise ValueError
            with self.assertRaises(ValueError):
                sample_point_from_netcdf(sst_nc, "sst", 91.0, 110.0)
            with self.assertRaises(ValueError):
                sample_point_from_netcdf(sst_nc, "sst", -5.0, 181.0)

    def test_coastal_nearest_fallback_and_synthetic_bilinear_math(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            nc_path = Path(td) / "coastal_sst.nc"
            lat = np.array([-8.0, -7.0, -6.0], dtype=np.float64)
            lon = np.array([110.0, 111.0, 112.0], dtype=np.float64)
            # Row 0 (lat=-8) has ocean; Row 1 (lat=-7, lon=110) is NaN land!
            sst = np.array(
                [
                    [26.0, 28.0, 30.0],
                    [np.nan, 29.0, 31.0],
                    [np.nan, np.nan, 32.0],
                ],
                dtype=np.float32,
            )
            _write_test_netcdf_3d_or_2d(
                nc_path,
                lat,
                lon,
                {"sst": (("lat", "lon"), sst, {"units": "degree_C"})},
            )

            # Enclosing cell [-8..-7, 111..112] has all 4 corners finite -> bilinear
            pt_bi = sample_point_from_netcdf(nc_path, "sst", -7.5, 111.5)
            self.assertEqual(pt_bi["interpolation_method"], "bilinear")
            self.assertAlmostEqual(float(pt_bi["sst_c"]), (28.0 + 30.0 + 29.0 + 31.0) / 4.0)

            # Cell [-8..-7, 110..111] has (-7, 110) as NaN -> nearest within <= 1 cell
            pt_near = sample_point_from_netcdf(nc_path, "sst", -7.1, 110.9)
            self.assertEqual(pt_near["interpolation_method"], "nearest")
            self.assertAlmostEqual(float(pt_near["sst_c"]), 29.0)

            # Node (-6, 110) is > 1 grid cell away from (-8, 110) and (-7, 111) is sqrt(2) cells
            # wait: (-6, 110) to (-7, 111) has |dlat|=1.0<=1 cell, |dlon|=1.0<=1 cell (coastal)!
            # Verify point > 1 cell from any valid water returns unavailable:
            nc_far = Path(td) / "far_land.nc"
            lat4 = np.array([-8.0, -7.0, -6.0, -5.0], dtype=np.float64)
            lon4 = np.array([110.0, 111.0, 112.0, 113.0], dtype=np.float64)
            sst4 = np.full((4, 4), np.nan, dtype=np.float32)
            sst4[0, 0] = 27.5
            _write_test_netcdf_3d_or_2d(
                nc_far,
                lat4,
                lon4,
                {"sst": (("lat", "lon"), sst4, {"units": "degree_C"})},
            )
            pt_unavail = sample_point_from_netcdf(nc_far, "sst", -5.5, 112.5)
            self.assertEqual(pt_unavail["interpolation_method"], "unavailable")
            self.assertIsNone(pt_unavail["sst_c"])

    def test_kelvin_conversion_descending_lat_and_currents_bearings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            # Descending latitude + Kelvin units + 3D time axis
            sst_nc = Path(td) / "kelvin_desc.nc"
            lat_desc = np.array([-4.0, -6.0, -8.0], dtype=np.float64)
            lon = np.array([110.0, 112.0], dtype=np.float64)
            sst_k = np.full((1, 3, 2), 300.15, dtype=np.float32)
            _write_test_netcdf_3d_or_2d(
                sst_nc,
                lat_desc,
                lon,
                {"analysed_sst": (("time", "lat", "lon"), sst_k, {"units": "kelvin"})},
            )
            pt = sample_point_from_netcdf(sst_nc, "sst", -6.0, 111.0)
            self.assertEqual(pt["interpolation_method"], "bilinear")
            self.assertAlmostEqual(float(pt["sst_c"]), 27.0, places=3)

            # Oceanographic currents bearing verification (East=90, North=0, West=270, South=180)
            cur_nc = Path(td) / "currents_bearings.nc"
            lat2 = np.array([-6.0, -5.0], dtype=np.float64)
            lon2 = np.array([110.0, 111.0], dtype=np.float64)
            # (lat=-6, lon=110): East (1, 0) -> 90 deg
            # (lat=-6, lon=111): North (0, 1) -> 0 deg
            # (lat=-5, lon=110): West (-1, 0) -> 270 deg
            # (lat=-5, lon=111): South (0, -1) -> 180 deg
            u_grid = np.array([[1.0, 0.0], [-1.0, 0.0]], dtype=np.float32)
            v_grid = np.array([[0.0, 1.0], [0.0, -1.0]], dtype=np.float32)
            _write_test_netcdf_3d_or_2d(
                cur_nc,
                lat2,
                lon2,
                {
                    "uo": (("lat", "lon"), u_grid, {"units": "m s-1"}),
                    "vo": (("lat", "lon"), v_grid, {"units": "m s-1"}),
                },
            )
            for q_lat, q_lon, exp_deg in (
                (-6.0, 110.0, 90.0),
                (-6.0, 111.0, 0.0),
                (-5.0, 110.0, 270.0),
                (-5.0, 111.0, 180.0),
            ):
                c_pt = sample_point_from_netcdf(cur_nc, "currents", q_lat, q_lon)
                self.assertEqual(c_pt["interpolation_method"], "bilinear")
                self.assertAlmostEqual(float(c_pt["current_speed_ms"]), 1.0, places=5)
                self.assertAlmostEqual(float(c_pt["current_direction_deg"]), exp_deg, places=5)
                self.assertTrue(0.0 <= float(c_pt["current_direction_deg"]) < 360.0)

            # NOAA ERDDAP variable names (`u_current`, `v_current`) with 4D (time, alt, lat, lon)
            erddap_cur_nc = Path(td) / "erddap_4d_currents.nc"
            try:
                from scipy.io import netcdf_file

                with netcdf_file(str(erddap_cur_nc), "w", version=1) as nc:
                    nc.createDimension("time", 1)
                    nc.createDimension("altitude", 1)
                    nc.createDimension("latitude", 2)
                    nc.createDimension("longitude", 2)
                    nc.createVariable("time", "d", ("time",))[:] = [0.0]
                    nc.createVariable("altitude", "d", ("altitude",))[:] = [0.0]
                    nc.createVariable("latitude", "d", ("latitude",))[:] = lat2
                    nc.createVariable("longitude", "d", ("longitude",))[:] = lon2
                    u4 = np.full((1, 1, 2, 2), 0.6, dtype=np.float32)
                    v4 = np.full((1, 1, 2, 2), 0.8, dtype=np.float32)
                    dims4 = ("time", "altitude", "latitude", "longitude")
                    nc.createVariable("u_current", "f", dims4)[:] = u4
                    nc.createVariable("v_current", "f", dims4)[:] = v4
                pt4 = sample_point_from_netcdf(erddap_cur_nc, "currents", -5.5, 110.5)
                self.assertEqual(pt4["interpolation_method"], "bilinear")
                self.assertAlmostEqual(float(pt4["current_speed_ms"]), 1.0, places=5)
            except ImportError:
                pass


if __name__ == "__main__":
    unittest.main()
