"""Comprehensive tests for tiles, map point inspection, species, and sources endpoints."""

from __future__ import annotations

import importlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.schemas.common import (  # noqa: E402
    WPP_CODES,
    CurrentGridResponse,
    DataSourcesResponse,
    ErrorResponse,
    MapPointInspection,
    SpeciesOccurrenceListResponse,
)


def _has_real_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return False


_REAL_DEPS_AVAILABLE = all(
    _has_real_module(pkg) for pkg in ("sqlalchemy", "geoalchemy2", "redis", "pydantic_settings")
)

_MANAGED_APP_MODULES: tuple[str, ...] = (
    "app.main",
    "app.routers.health",
    "app.routers.wpp",
    "app.routers.tiles",
    "app.routers.map_point",
    "app.routers.species",
    "app.routers.sources",
    "app.routers.currents",
    "app.services",
    "app.services.tile_service",
    "app.services.point_query",
    "app.services.species_service",
    "app.services.sources_service",
    "app.services.currents_service",
    "app.core.config",
    "app.core.db",
    "app.core.redis",
    "app.models.spatial",
)


class _DummyColumn:
    def __init__(self, name: str) -> None:
        self.name = name

    def asc(self) -> _DummyColumn:
        return self

    def desc(self) -> _DummyColumn:
        return self

    def nullslast(self) -> _DummyColumn:
        return self

    def label(self, _name: str) -> _DummyColumn:
        return self

    def ilike(self, _pattern: str) -> bool:
        return True

    def __eq__(self, _other: object) -> bool:  # type: ignore[override]
        return False

    def __le__(self, _other: object) -> bool:
        return True

    def __ge__(self, _other: object) -> bool:
        return True

    def __lt__(self, _other: object) -> bool:
        return True

    def __gt__(self, _other: object) -> bool:
        return True


class _DummySelectStmt:
    def where(self, *_args: object) -> _DummySelectStmt:
        return self

    def order_by(self, *_args: object) -> _DummySelectStmt:
        return self

    def limit(self, *_args: object) -> _DummySelectStmt:
        return self

    def offset(self, *_args: object) -> _DummySelectStmt:
        return self

    def select_from(self, *_args: object) -> _DummySelectStmt:
        return self

    def group_by(self, *_args: object) -> _DummySelectStmt:
        return self


class _DummyFuncProxy:
    def __getattr__(self, name: str) -> Any:
        def _fn(*_args: object, **_kwargs: object) -> _DummyColumn:
            return _DummyColumn(name)

        return _fn


def _build_local_stubs() -> dict[str, types.ModuleType]:
    """Provide minimal module stubs when optional DB/Redis packages are absent locally."""
    sa_mod = types.ModuleType("sqlalchemy")
    sa_mod.func = _DummyFuncProxy()  # type: ignore[attr-defined]
    sa_mod.literal = lambda _v: _DummyColumn("literal")  # type: ignore[attr-defined]
    sa_mod.or_ = lambda *_a: True  # type: ignore[attr-defined]
    sa_mod.select = lambda *_a: _DummySelectStmt()  # type: ignore[attr-defined]
    sa_mod.text = lambda sql: sql  # type: ignore[attr-defined]

    sa_ext_mod = types.ModuleType("sqlalchemy.ext")
    sa_async_mod = types.ModuleType("sqlalchemy.ext.asyncio")

    class _AsyncSession:
        pass

    sa_async_mod.AsyncSession = _AsyncSession  # type: ignore[attr-defined]

    sa_dialects_mod = types.ModuleType("sqlalchemy.dialects")
    sa_pg_mod = types.ModuleType("sqlalchemy.dialects.postgresql")

    class _DummyInsert:
        def values(self, **_kwargs: object) -> _DummyInsert:
            return self

        def on_conflict_do_update(self, **_kwargs: object) -> _DummyInsert:
            return self

    sa_pg_mod.insert = lambda _tbl: _DummyInsert()  # type: ignore[attr-defined]

    redis_pkg = types.ModuleType("redis")
    redis_async_mod = types.ModuleType("redis.asyncio")

    class _Redis:
        pass

    redis_async_mod.Redis = _Redis  # type: ignore[attr-defined]

    config_mod = types.ModuleType("app.core.config")

    @dataclass
    class _StubSettings:
        TILE_CACHE_DIR: Path = Path(tempfile.gettempdir()) / "lautscan-endpoint-tests"
        ENVIRONMENT: str = "development"
        WPP_SEED_PATH: Path = REPO_ROOT / "data" / "wpp-nri" / "wpp_nri_zones.json"
        COPERNICUS_USERNAME: str = ""
        COPERNICUS_PASSWORD: str = ""
        PDPI_BASE_URL: str = ""
        GFW_API_TOKEN: str = ""
        REDIS_URL: str = "redis://127.0.0.1:6379/0"

    @lru_cache
    def _get_settings() -> _StubSettings:
        return _StubSettings()

    config_mod.Settings = _StubSettings  # type: ignore[attr-defined]
    config_mod.get_settings = _get_settings  # type: ignore[attr-defined]

    db_mod = types.ModuleType("app.core.db")

    class _Base:
        pass

    async def _get_db() -> Any:
        yield None

    async def _check_db_health() -> tuple[bool, str | None]:
        return False, None

    db_mod.Base = _Base  # type: ignore[attr-defined]
    db_mod.engine = object()  # type: ignore[attr-defined]
    db_mod.async_session_maker = object()  # type: ignore[attr-defined]
    db_mod.get_db = _get_db  # type: ignore[attr-defined]
    db_mod.check_db_health = _check_db_health  # type: ignore[attr-defined]

    redis_mod = types.ModuleType("app.core.redis")

    async def _get_redis() -> Any:
        yield None

    async def _check_redis_health() -> bool:
        return False

    redis_mod.get_redis = _get_redis  # type: ignore[attr-defined]
    redis_mod.check_redis_health = _check_redis_health  # type: ignore[attr-defined]

    spatial_mod = types.ModuleType("app.models.spatial")

    class _DummyModelMeta(type):
        def __getattr__(cls, name: str) -> _DummyColumn:
            return _DummyColumn(name)

    class _DummyModel(metaclass=_DummyModelMeta):
        pass

    spatial_mod.WppNriZone = _DummyModel  # type: ignore[attr-defined]
    spatial_mod.RasterDataset = _DummyModel  # type: ignore[attr-defined]
    spatial_mod.TileCacheIndex = _DummyModel  # type: ignore[attr-defined]
    spatial_mod.SpeciesOccurrence = _DummyModel  # type: ignore[attr-defined]
    spatial_mod.SourceSyncLog = _DummyModel  # type: ignore[attr-defined]

    return {
        "sqlalchemy": sa_mod,
        "sqlalchemy.ext": sa_ext_mod,
        "sqlalchemy.ext.asyncio": sa_async_mod,
        "sqlalchemy.dialects": sa_dialects_mod,
        "sqlalchemy.dialects.postgresql": sa_pg_mod,
        "redis": redis_pkg,
        "redis.asyncio": redis_async_mod,
        "app.core.config": config_mod,
        "app.core.db": db_mod,
        "app.core.redis": redis_mod,
        "app.models.spatial": spatial_mod,
    }


class _InMemoryRedis:
    """Async in-memory Redis mock supporting get/set with TTL."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        del ex
        self.store[key] = value
        return True


class _FakeResult:
    """Minimal SQLAlchemy result wrapper for mocked async DB queries."""

    def __init__(
        self,
        *,
        scalar_val: Any = None,
        first_val: Any = None,
        scalars_list: list[Any] | None = None,
        all_rows: list[Any] | None = None,
    ) -> None:
        self._scalar_val = scalar_val
        self._first_val = first_val
        self._scalars_list = scalars_list or []
        self._all_rows = all_rows or []

    def scalar_one_or_none(self) -> Any:
        return self._scalar_val

    def scalar_one(self) -> Any:
        return self._scalar_val

    def first(self) -> Any:
        return self._first_val

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return self._all_rows or self._scalars_list


class _QueuedFakeDb:
    """Async session returning queued `_FakeResult` responses in sequence."""

    def __init__(self, responses: list[_FakeResult | Exception]) -> None:
        self._responses = list(responses)
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, _stmt: object) -> _FakeResult:
        if not self._responses:
            return _FakeResult()
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class ApiFeatureEndpointsTests(unittest.TestCase):
    """End-to-end API tests for tiles, map point inspection, species, and data sources."""

    _sys_patcher: Any = None
    _saved_modules: dict[str, Any] = {}
    currents_service_mod: Any = None
    species_service_mod: Any = None
    app_mod: Any = None
    config_mod: Any = None
    db_mod: Any = None
    redis_mod: Any = None
    tile_service_mod: Any = None
    point_query_mod: Any = None
    sources_service_mod: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        if not _REAL_DEPS_AVAILABLE:
            cls._saved_modules = {
                name: sys.modules.pop(name) for name in _MANAGED_APP_MODULES if name in sys.modules
            }
            cls._sys_patcher = patch.dict(sys.modules, _build_local_stubs())
            cls._sys_patcher.start()

        cls.config_mod = importlib.import_module("app.core.config")
        cls.db_mod = importlib.import_module("app.core.db")
        cls.redis_mod = importlib.import_module("app.core.redis")
        cls.tile_service_mod = importlib.import_module("app.services.tile_service")
        cls.point_query_mod = importlib.import_module("app.services.point_query")
        cls.sources_service_mod = importlib.import_module("app.services.sources_service")
        cls.currents_service_mod = importlib.import_module("app.services.currents_service")
        cls.species_service_mod = importlib.import_module("app.services.species_service")
        cls.app_mod = importlib.import_module("app.main")

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._sys_patcher is not None:
            for name in _MANAGED_APP_MODULES:
                sys.modules.pop(name, None)
            cls._sys_patcher.stop()
            sys.modules.update(cls._saved_modules)

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tile_dir = Path(self.tmpdir.name) / "tiles"
        self.settings = self.config_mod.Settings(
            TILE_CACHE_DIR=self.tile_dir,
            ENVIRONMENT="development",
            WPP_SEED_PATH=REPO_ROOT / "data" / "wpp-nri" / "wpp_nri_zones.json",
            COPERNICUS_USERNAME="",
            COPERNICUS_PASSWORD="",
            PDPI_BASE_URL="",
            GFW_API_TOKEN="",
        )
        self.app = self.app_mod.create_app()

        async def _offline_db() -> Any:
            yield _QueuedFakeDb([ConnectionRefusedError("offline")])

        async def _no_redis() -> Any:
            yield None

        self.app.dependency_overrides[self.db_mod.get_db] = _offline_db
        self.app.dependency_overrides[self.redis_mod.get_redis] = _no_redis

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()
        self.tmpdir.cleanup()

    def test_all_six_contract_paths_mounted_on_app(self) -> None:
        paths = set(self.app.openapi()["paths"].keys())
        self.assertEqual(
            paths,
            {
                "/v1/health",
                "/v1/wpp",
                "/v1/tiles/{layer}/{date}/{z}/{x}/{y}.png",
                "/v1/map/point",
                "/v1/currents/grid",
                "/v1/species",
                "/v1/sources",
            },
        )

    def test_tiles_miss_hit_empty_webp_and_validation(self) -> None:
        fake_redis = _InMemoryRedis()

        async def _redis_override() -> Any:
            yield fake_redis

        self.app.dependency_overrides[self.redis_mod.get_redis] = _redis_override

        with (
            patch.object(self.tile_service_mod, "get_settings", return_value=self.settings),
            TestClient(self.app) as client,
        ):
            # 1. First request renders 256x256 RGBA PNG for Java Sea/Indonesia (z=4, x=13, y=8)
            r_miss = client.get("/v1/tiles/sst/2026-11-11/4/13/8.png")
            self.assertEqual(r_miss.status_code, 200)
            self.assertEqual(r_miss.headers["content-type"], "image/png")
            self.assertEqual(r_miss.headers["x-tile-cache"], "MISS")
            self.assertEqual(r_miss.headers["x-data-source"], "noaa_erddap")
            self.assertIn("max-age=", r_miss.headers["cache-control"])
            self.assertEqual(r_miss.headers["x-dataset-timestamp-utc"], "2026-11-11T12:00:00Z")
            with Image.open(io.BytesIO(r_miss.content)) as img:
                self.assertEqual(img.size, (256, 256))
                self.assertEqual(img.mode, "RGBA")

            # 2. Second request hits Redis + disk cache
            r_hit = client.get("/v1/tiles/sst/2026-11-11/4/13/8.png")
            self.assertEqual(r_hit.status_code, 200)
            self.assertEqual(r_hit.headers["x-tile-cache"], "HIT")
            self.assertEqual(r_hit.content, r_miss.content)

            # 3. Disk-only hit when Redis is flushed
            fake_redis.store.clear()
            r_disk_hit = client.get("/v1/tiles/sst/2026-11-11/4/13/8.png")
            self.assertEqual(r_disk_hit.status_code, 200)
            self.assertEqual(r_disk_hit.headers["x-tile-cache"], "HIT")

            # 4. WebP format + chlorophyll/currents layers work cleanly
            r_chl_webp = client.get("/v1/tiles/chlorophyll/latest/4/13/8.png?format=webp")
            self.assertEqual(r_chl_webp.status_code, 200)
            self.assertEqual(r_chl_webp.headers["content-type"], "image/webp")
            with Image.open(io.BytesIO(r_chl_webp.content)) as webp_img:
                self.assertEqual(webp_img.size, (256, 256))

            r_cur = client.get("/v1/tiles/currents/latest/4/13/8.png")
            self.assertEqual(r_cur.status_code, 200)
            self.assertEqual(r_cur.headers["x-tile-cache"], "MISS")

            r_pot = client.get("/v1/tiles/potential/latest/4/13/8.png")
            self.assertEqual(r_pot.status_code, 200)
            self.assertEqual(r_pot.headers["x-tile-cache"], "MISS")
            with Image.open(io.BytesIO(r_pot.content)) as pot_img:
                self.assertEqual(pot_img.size, (256, 256))
                self.assertEqual(pot_img.mode, "RGBA")

            r_pot_hit = client.get("/v1/tiles/potential/latest/4/13/8.png")
            self.assertEqual(r_pot_hit.status_code, 200)
            self.assertEqual(r_pot_hit.headers["x-tile-cache"], "HIT")

            # 5. Out-of-Indonesia tile returns transparent 256x256 PNG with X-Tile-Cache: EMPTY
            r_empty = client.get("/v1/tiles/sst/2026-11-11/4/0/0.png")
            self.assertEqual(r_empty.status_code, 200)
            self.assertEqual(r_empty.headers["x-tile-cache"], "EMPTY")
            with Image.open(io.BytesIO(r_empty.content)) as empty_img:
                self.assertEqual(empty_img.getchannel("A").getextrema(), (0, 0))

            # 6. Slippy bounds violation (x >= 2**z) returns 400 ErrorResponse
            r_oob = client.get("/v1/tiles/sst/2026-11-11/2/4/0.png")
            self.assertEqual(r_oob.status_code, 400)
            oob_err = ErrorResponse.model_validate(r_oob.json())
            self.assertEqual(oob_err.error_code, "INVALID_TILE_REQUEST")

            # 7. Invalid calendar date returns 400 ErrorResponse
            r_bad_date = client.get("/v1/tiles/sst/2026-02-30/2/0/0.png")
            self.assertEqual(r_bad_date.status_code, 400)
            ErrorResponse.model_validate(r_bad_date.json())

            # 8. Zoom > 14 returns 422 ErrorResponse
            r_bad_zoom = client.get("/v1/tiles/sst/latest/15/0/0.png")
            self.assertEqual(r_bad_zoom.status_code, 422)
            ErrorResponse.model_validate(r_bad_zoom.json())

    def test_tiles_uses_db_raster_dataset_and_records_tile_cache_index(self) -> None:
        from app.etl.fixtures import ensure_sample_netcdf

        nc_path = ensure_sample_netcdf(self.tile_dir, "sst", "2026-11-09")
        ds_row = SimpleNamespace(
            id="40000000-0000-4000-8000-000000000001",
            file_path=str(nc_path),
            acquisition_date=date(2026, 11, 9),
            acquired_at_utc=datetime(2026, 11, 9, 18, 30, tzinfo=UTC),
            source_key="copernicus_marine",
        )
        fake_db = _QueuedFakeDb(
            [
                _FakeResult(scalar_val=ds_row),
                _FakeResult(),
            ]
        )

        async def _db_override() -> Any:
            yield fake_db

        self.app.dependency_overrides[self.db_mod.get_db] = _db_override
        with (
            patch.object(self.tile_service_mod, "get_settings", return_value=self.settings),
            TestClient(self.app) as client,
        ):
            resp = client.get("/v1/tiles/sst/2026-11-11/4/13/8.png")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["x-tile-cache"], "MISS")
        self.assertEqual(resp.headers["x-data-source"], "copernicus_marine")
        self.assertEqual(resp.headers["x-dataset-timestamp-utc"], "2026-11-09T18:30:00Z")
        self.assertEqual(fake_db.commits, 1)

    def test_map_point_inspection_indonesia_outside_cache_and_compass(self) -> None:
        fake_redis = _InMemoryRedis()

        async def _redis_override() -> Any:
            yield fake_redis

        self.app.dependency_overrides[self.redis_mod.get_redis] = _redis_override

        with (
            patch.object(self.point_query_mod, "get_settings", return_value=self.settings),
            TestClient(self.app) as client,
        ):
            # 1. Java Sea coordinate inside WPP-NRI 712
            r_java = client.get("/v1/map/point?lat=-5.5&lon=110.0&date=2026-11-11")
            self.assertEqual(r_java.status_code, 200)
            pt = MapPointInspection.model_validate(r_java.json())
            self.assertEqual(pt.wpp_code, "712")
            self.assertEqual(pt.wpp_name, "WPP-NRI 712")
            self.assertEqual(pt.wpp_waters_id, "Perairan Laut Jawa")
            self.assertIsNotNone(pt.sst_c)
            self.assertIsNotNone(pt.sst_f)
            assert pt.sst_c is not None and pt.sst_f is not None
            self.assertAlmostEqual(pt.sst_f, round(pt.sst_c * 9.0 / 5.0 + 32.0, 2), places=2)
            self.assertIsNotNone(pt.chlorophyll_mg_m3)
            self.assertIsNotNone(pt.current_speed_ms)
            self.assertIsNotNone(pt.current_speed_knots)
            assert pt.current_speed_ms is not None and pt.current_speed_knots is not None
            self.assertAlmostEqual(
                pt.current_speed_knots,
                round(pt.current_speed_ms * 1.94384, 3),
                places=3,
            )
            self.assertIn(pt.current_compass, self.point_query_mod.COMPASS_16)
            self.assertEqual(pt.interpolation_method, "bilinear")
            self.assertIn("NOAA", pt.attribution)
            self.assertIn("BMKG", pt.disclaimer)

            # 2. Redis point cache serves cached entry on repeat lookup
            self.assertIn("point:-5.500:110.000:2026-11-11", fake_redis.store)
            with patch.object(
                self.point_query_mod,
                "sample_point_from_netcdf",
                side_effect=AssertionError("Should serve from Redis cache"),
            ):
                r_cached = client.get("/v1/map/point?lat=-5.5&lon=110.0&date=2026-11-11")
                self.assertEqual(r_cached.status_code, 200)
                self.assertEqual(r_cached.json()["wpp_code"], "712")

            # 3. Point outside Indonesia returns unavailable metrics cleanly
            r_outside = client.get("/v1/map/point?lat=0.0&lon=0.0&date=latest")
            self.assertEqual(r_outside.status_code, 200)
            pt_out = MapPointInspection.model_validate(r_outside.json())
            self.assertIsNone(pt_out.wpp_code)
            self.assertEqual(pt_out.interpolation_method, "unavailable")
            self.assertIsNone(pt_out.sst_c)
            self.assertIsNone(pt_out.current_compass)

            # 4. Invalid latitude returns 422 ErrorResponse
            r_bad_lat = client.get("/v1/map/point?lat=99.0&lon=110.0")
            self.assertEqual(r_bad_lat.status_code, 422)
            ErrorResponse.model_validate(r_bad_lat.json())

        # 5. Verify 16-point compass angles and Polygon-with-hole geometry helper
        self.assertEqual(self.point_query_mod.degrees_to_compass_16(0.0), "N")
        self.assertEqual(self.point_query_mod.degrees_to_compass_16(22.5), "NNE")
        self.assertEqual(self.point_query_mod.degrees_to_compass_16(90.0), "E")
        self.assertEqual(self.point_query_mod.degrees_to_compass_16(225.0), "SW")
        self.assertEqual(self.point_query_mod.degrees_to_compass_16(359.0), "N")

        donut = {
            "type": "Polygon",
            "coordinates": [
                [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
                [[3, 3], [7, 3], [7, 7], [3, 7], [3, 3]],
            ],
        }
        self.assertTrue(self.point_query_mod.point_in_geojson_geometry(1.0, 1.0, donut))
        self.assertFalse(self.point_query_mod.point_in_geojson_geometry(5.0, 5.0, donut))

    def test_map_point_uses_postgis_wpp_and_db_raster_when_available(self) -> None:
        sst_nc = self.tile_dir / "custom_sst.nc"
        chl_nc = self.tile_dir / "custom_chl.nc"
        cur_nc = self.tile_dir / "custom_cur.nc"
        from app.etl.fixtures import ensure_sample_netcdf

        base_sst = ensure_sample_netcdf(self.tile_dir, "sst", "2026-11-10")
        base_chl = ensure_sample_netcdf(self.tile_dir, "chlorophyll", "2026-11-10")
        base_cur = ensure_sample_netcdf(self.tile_dir, "currents", "2026-11-10")
        sst_nc.write_bytes(base_sst.read_bytes())
        chl_nc.write_bytes(base_chl.read_bytes())
        cur_nc.write_bytes(base_cur.read_bytes())

        ds_sst = SimpleNamespace(
            file_path=str(sst_nc),
            acquisition_date=date(2026, 11, 10),
            acquired_at_utc=datetime(2026, 11, 10, 6, 0, tzinfo=UTC),
            source_key="noaa_erddap",
            spatial_resolution_km=4.0,
        )
        ds_chl = SimpleNamespace(
            file_path=str(chl_nc),
            acquisition_date=date(2026, 11, 10),
            acquired_at_utc=datetime(2026, 11, 10, 6, 0, tzinfo=UTC),
            source_key="noaa_erddap",
            spatial_resolution_km=4.0,
        )
        ds_cur = SimpleNamespace(
            file_path=str(cur_nc),
            acquisition_date=date(2026, 11, 10),
            acquired_at_utc=datetime(2026, 11, 10, 6, 0, tzinfo=UTC),
            source_key="noaa_erddap",
            spatial_resolution_km=4.0,
        )

        fake_db = _QueuedFakeDb(
            [
                _FakeResult(scalar_val="714"),
                _FakeResult(first_val=("714", "WPP-NRI 714", "Perairan Teluk Tolo dan Laut Banda")),
                _FakeResult(scalar_val=ds_sst),
                _FakeResult(scalar_val=ds_chl),
                _FakeResult(scalar_val=ds_cur),
            ]
        )

        async def _db_override() -> Any:
            yield fake_db

        self.app.dependency_overrides[self.db_mod.get_db] = _db_override

        with (
            patch.object(self.point_query_mod, "get_settings", return_value=self.settings),
            TestClient(self.app) as client,
        ):
            resp = client.get("/v1/map/point?lat=-5.1&lon=127.0&date=2026-11-11")

        self.assertEqual(resp.status_code, 200)
        parsed = MapPointInspection.model_validate(resp.json())
        self.assertEqual(parsed.wpp_code, "714")
        self.assertEqual(parsed.resolved_date, "2026-11-10")
        self.assertTrue(parsed.is_cached_fallback)
        self.assertEqual(parsed.spatial_resolution_km, 4.0)

    def test_species_filters_pagination_bbox_and_postgis_branch(self) -> None:
        with TestClient(self.app) as client:
            # 1. Baseline fallback covers all 11 WPP-NRI zones
            r_all = client.get("/v1/species")
            self.assertEqual(r_all.status_code, 200)
            parsed_all = SpeciesOccurrenceListResponse.model_validate(r_all.json())
            self.assertGreaterEqual(parsed_all.total, 11)
            self.assertEqual({item.wpp_code for item in parsed_all.items}, set(WPP_CODES))

            # 2. Taxon + WPP + bbox filters
            r_tuna = client.get("/v1/species?taxon=Thunnus")
            parsed_tuna = SpeciesOccurrenceListResponse.model_validate(r_tuna.json())
            self.assertGreater(parsed_tuna.total, 0)
            for item in parsed_tuna.items:
                self.assertIn("thunnus", item.scientific_name.lower())

            r_712 = client.get("/v1/species?wpp=712")
            parsed_712 = SpeciesOccurrenceListResponse.model_validate(r_712.json())
            self.assertGreater(parsed_712.total, 0)
            self.assertTrue(all(item.wpp_code == "712" for item in parsed_712.items))

            r_bbox = client.get("/v1/species?bbox=105.0,-8.0,117.0,-3.0")
            parsed_bbox = SpeciesOccurrenceListResponse.model_validate(r_bbox.json())
            self.assertGreater(parsed_bbox.total, 0)
            for item in parsed_bbox.items:
                self.assertTrue(105.0 <= item.lon <= 117.0 and -8.0 <= item.lat <= -3.0)

            # 3. Pagination
            r_page = client.get("/v1/species?limit=3&offset=2")
            parsed_page = SpeciesOccurrenceListResponse.model_validate(r_page.json())
            self.assertEqual(len(parsed_page.items), 3)
            self.assertEqual(parsed_page.limit, 3)
            self.assertEqual(parsed_page.offset, 2)
            self.assertTrue(parsed_page.has_more)

            # 4. Malformed bbox returns 400 ErrorResponse
            for bad_bbox in ("bad", "120,-5,100,5", "200,-5,210,5"):
                r_err = client.get(f"/v1/species?bbox={bad_bbox}")
                self.assertEqual(r_err.status_code, 400)
                err = ErrorResponse.model_validate(r_err.json())
                self.assertEqual(err.error_code, "INVALID_BBOX")

        # 5. Populated PostGIS DB branch overrides fixture fallback
        db_row = SimpleNamespace(
            id="20000000-0000-4000-8000-000000000099",
            obis_id="obis-live-99",
            scientific_name="Katsuwonus pelamis",
            common_name="Skipjack tuna",
            taxon_rank="species",
            family="Scombridae",
            lat=-4.5,
            lon=127.5,
            wpp_code="714",
            depth_m=40.0,
            event_date_utc=datetime(2026, 11, 10, 8, 0, tzinfo=UTC),
            individual_count=25,
            habitat_note="Live OBIS PostGIS test record",
            dataset_name="OBIS Live Sync",
            attribution="OBIS v3",
            license="CC-BY-4.0",
        )
        fake_db = _QueuedFakeDb(
            [
                _FakeResult(scalar_val=db_row.id),
                _FakeResult(scalar_val=1),
                _FakeResult(all_rows=[db_row]),
            ]
        )

        async def _db_override() -> Any:
            yield fake_db

        self.app.dependency_overrides[self.db_mod.get_db] = _db_override
        with TestClient(self.app) as client:
            r_live = client.get("/v1/species?wpp=714")
        self.assertEqual(r_live.status_code, 200)
        parsed_live = SpeciesOccurrenceListResponse.model_validate(r_live.json())
        self.assertEqual(parsed_live.total, 1)
        self.assertEqual(parsed_live.items[0].obis_id, "obis-live-99")

    def test_sources_catalog_compliance_and_secret_redaction(self) -> None:
        with (
            patch.object(self.sources_service_mod, "get_settings", return_value=self.settings),
            TestClient(self.app) as client,
        ):
            r_sources = client.get("/v1/sources")
            self.assertEqual(r_sources.status_code, 200)
            parsed = DataSourcesResponse.model_validate(r_sources.json())
            by_key = {src.source_key: src for src in parsed.sources}
            self.assertEqual(
                set(by_key.keys()),
                {"noaa_erddap", "obis", "copernicus_marine", "kkp_pdpi", "gfw"},
            )
            self.assertTrue(by_key["gfw"].non_commercial_only)
            self.assertFalse(by_key["gfw"].enabled)
            self.assertEqual(by_key["gfw"].status, "disabled")

            self.assertTrue(by_key["copernicus_marine"].requires_credentials)
            self.assertFalse(by_key["copernicus_marine"].enabled)
            self.assertEqual(by_key["copernicus_marine"].status, "unconfigured")

            self.assertFalse(by_key["kkp_pdpi"].enabled)
            self.assertEqual(by_key["kkp_pdpi"].status, "unconfigured")

            self.assertTrue(by_key["noaa_erddap"].enabled)
            self.assertEqual(by_key["noaa_erddap"].status, "healthy")
            self.assertTrue(by_key["obis"].enabled)
            self.assertEqual(by_key["obis"].status, "healthy")

        # Verify credentials are redacted in error logs/messages and logs can be suppressed
        secret_settings = self.config_mod.Settings(
            TILE_CACHE_DIR=self.tile_dir,
            ENVIRONMENT="development",
            WPP_SEED_PATH=REPO_ROOT / "data" / "wpp-nri" / "wpp_nri_zones.json",
            COPERNICUS_USERNAME="cop_user_secret",
            COPERNICUS_PASSWORD="cop_pw_super_secret",
            PDPI_BASE_URL="https://pdpi.internal.example/secret-path",
            GFW_API_TOKEN="gfw_live_secret_token_999",
        )
        sync_log = SimpleNamespace(
            id="30000000-0000-4000-8000-000000000001",
            source_key="copernicus_marine",
            dataset_type="sst",
            status="failed",
            records_ingested=0,
            started_at_utc=datetime(2026, 11, 11, 0, 0, tzinfo=UTC),
            finished_at_utc=datetime(2026, 11, 11, 0, 1, tzinfo=UTC),
            duration_ms=60000,
            error_message=(
                "Auth failed for cop_user_secret / cop_pw_super_secret "
                "and token gfw_live_secret_token_999"
            ),
        )
        fake_db = _QueuedFakeDb(
            [
                _FakeResult(scalars_list=[sync_log]),
                _FakeResult(all_rows=[]),
                _FakeResult(scalar_val=None),
            ]
        )

        async def _db_with_log() -> Any:
            yield fake_db

        self.app.dependency_overrides[self.db_mod.get_db] = _db_with_log
        with (
            patch.object(self.sources_service_mod, "get_settings", return_value=secret_settings),
            TestClient(self.app) as client,
        ):
            r_logs = client.get("/v1/sources?include_recent_logs=true")
            r_no_logs = client.get("/v1/sources?include_recent_logs=false")

        self.assertEqual(r_logs.status_code, 200)
        raw_text = json.dumps(r_logs.json())
        self.assertNotIn("cop_user_secret", raw_text)
        self.assertNotIn("cop_pw_super_secret", raw_text)
        self.assertNotIn("gfw_live_secret_token_999", raw_text)
        parsed_logs = DataSourcesResponse.model_validate(r_logs.json())
        self.assertEqual(len(parsed_logs.recent_logs), 1)
        self.assertIn("***REDACTED***", parsed_logs.recent_logs[0].error_message or "")

        self.assertEqual(r_no_logs.status_code, 200)
        parsed_no_logs = DataSourcesResponse.model_validate(r_no_logs.json())
        self.assertEqual(parsed_no_logs.recent_logs, [])

    def test_currents_vector_grid_and_bbox_validation(self) -> None:
        with (
            patch.object(self.currents_service_mod, "get_settings", return_value=self.settings),
            patch.object(self.tile_service_mod, "get_settings", return_value=self.settings),
            TestClient(self.app) as client,
        ):
            r_grid = client.get(
                "/v1/currents/grid?bbox=105,-9,116,-3&date=2026-11-11&max_vectors=80"
            )
            self.assertEqual(r_grid.status_code, 200)
            parsed = CurrentGridResponse.model_validate(r_grid.json())
            self.assertEqual(parsed.requested_date, "2026-11-11")
            self.assertEqual(parsed.resolved_date, "2026-11-11")
            self.assertEqual(parsed.total, len(parsed.vectors))
            self.assertGreater(parsed.total, 0)
            self.assertLessEqual(parsed.total, 80)

            r_bad_bbox = client.get("/v1/currents/grid?bbox=not-a-bbox")
            self.assertEqual(r_bad_bbox.status_code, 400)
            err = ErrorResponse.model_validate(r_bad_bbox.json())
            self.assertEqual(err.error_code, "INVALID_BBOX")

    def test_global_disk_cache_resolution_for_obis_noaa_and_sources(self) -> None:
        from app.etl.fixtures import ensure_sample_netcdf

        global_dir = self.tile_dir / "global"
        global_dir.mkdir(parents=True, exist_ok=True)
        sst_src = ensure_sample_netcdf(self.tile_dir, "sst", "2026-11-09")
        chl_src = ensure_sample_netcdf(self.tile_dir, "chlorophyll", "2026-11-09")
        cur_src = ensure_sample_netcdf(self.tile_dir, "currents", "2026-11-09")
        (global_dir / "noaa_sst.nc").write_bytes(sst_src.read_bytes())
        (global_dir / "noaa_chlorophyll.nc").write_bytes(chl_src.read_bytes())
        (global_dir / "noaa_currents.nc").write_bytes(cur_src.read_bytes())
        (global_dir / "noaa_manifest.json").write_text(
            json.dumps(
                {
                    "synced_at_utc": "2026-11-11T03:00:00Z",
                    "layers": {"sst": {"ok": True, "acquired_at_utc": "2026-11-09T09:00:00Z"}},
                }
            ),
            encoding="utf-8",
        )
        (global_dir / "obis_species.json").write_text(
            json.dumps(
                {
                    "synced_at_utc": "2026-11-11T03:00:00Z",
                    "items": [
                        {
                            "id": "90000000-0000-4000-8000-000000000001",
                            "obis_id": "obis-global-1",
                            "scientific_name": "Thunnus albacares",
                            "common_name": "Yellowfin tuna (Madidihang)",
                            "taxon_rank": "Species",
                            "family": "Scombridae",
                            "lat": -5.5,
                            "lon": 110.5,
                            "wpp_code": "712",
                            "depth_m": 45.0,
                            "event_date_utc": "2026-10-12T06:00:00Z",
                            "individual_count": 25,
                            "habitat_note": "Java Sea pelagic observation",
                            "dataset_name": "OBIS Live Global",
                            "attribution": "OBIS v3",
                            "license": "CC-BY-4.0",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.species_service_mod._GLOBAL_CACHE_ITEMS = None
        self.species_service_mod._GLOBAL_CACHE_MTIME = None
        with (
            patch.object(self.species_service_mod, "get_settings", return_value=self.settings),
            patch.object(self.point_query_mod, "get_settings", return_value=self.settings),
            patch.object(self.sources_service_mod, "get_settings", return_value=self.settings),
            TestClient(self.app) as client,
        ):
            r_sp = client.get("/v1/species")
            self.assertEqual(r_sp.status_code, 200)
            sp_list = SpeciesOccurrenceListResponse.model_validate(r_sp.json())
            self.assertEqual(sp_list.total, 1)
            self.assertEqual(sp_list.items[0].obis_id, "obis-global-1")

            r_pt = client.get("/v1/map/point?lat=-5.5&lon=110.5&date=latest")
            self.assertEqual(r_pt.status_code, 200)
            pt = MapPointInspection.model_validate(r_pt.json())
            self.assertIsNotNone(pt.sst_c)
            self.assertFalse(pt.is_cached_fallback)

            r_src = client.get("/v1/sources")
            self.assertEqual(r_src.status_code, 200)
            src_data = DataSourcesResponse.model_validate(r_src.json())
            by_key = {s.source_key: s for s in src_data.sources}
            self.assertIsNotNone(by_key["noaa_erddap"].latest_data_timestamp_utc)
            self.assertIsNotNone(by_key["obis"].latest_data_timestamp_utc)

    def test_strict_open_ocean_filter_rejects_land_and_harbor_coords(self) -> None:
        import netCDF4 as nc
        import numpy as np

        from app.etl.fixtures import ensure_sample_netcdf
        from app.etl.live_sync import _is_strict_open_ocean, _load_mur_landmask
        from app.etl.tiler import _load_layer_grid

        global_dir = self.tile_dir / "global_land_test"
        global_dir.mkdir(parents=True, exist_ok=True)
        sst_src = ensure_sample_netcdf(self.tile_dir, "sst", "2026-11-09")
        sst_nc = global_dir / "noaa_sst.nc"
        sst_nc.write_bytes(sst_src.read_bytes())
        sst_grid = _load_layer_grid(sst_nc, "sst")

        mask_nc = global_dir / "noaa_landmask.nc"
        ds = nc.Dataset(mask_nc, "w", format="NETCDF3_CLASSIC")
        try:
            lats = np.linspace(-3.0, 1.0, 21)
            lons = np.linspace(115.0, 119.0, 21)
            ds.createDimension("time", 1)
            ds.createDimension("latitude", len(lats))
            ds.createDimension("longitude", len(lons))
            tvar = ds.createVariable("time", "f8", ("time",))
            latvar = ds.createVariable("latitude", "f4", ("latitude",))
            lonvar = ds.createVariable("longitude", "f4", ("longitude",))
            mvar = ds.createVariable("mask", "i2", ("time", "latitude", "longitude"))
            tvar[:] = [0.0]
            latvar[:] = lats
            lonvar[:] = lons
            arr = np.ones((1, len(lats), len(lons)), dtype=np.int16)
            # Mark land pixels around Balikpapan (-1.25, 116.833) while leaving sea clear.
            arr[0, :, :10] = 2
            mvar[:] = arr
        finally:
            ds.close()

        mur = _load_mur_landmask(mask_nc)
        self.assertIsNotNone(mur)
        # Balikpapan city harbor falls on masked land (2).
        self.assertFalse(_is_strict_open_ocean(-1.25, 116.833, sst_nc, sst_grid, mur))
        # Open Makassar Strait waters with >= 1 cell ocean margin pass cleanly.
        self.assertTrue(_is_strict_open_ocean(-1.45, 117.75, sst_nc, sst_grid, mur))

    def test_recent_year_filter_and_obis_start_date_param(self) -> None:
        from app.etl.live_sync import MIN_RECENT_OBSERVATION_YEAR, _event_year
        from app.etl.obis_client import ObisClient

        self.assertEqual(MIN_RECENT_OBSERVATION_YEAR, 2020)
        self.assertEqual(_event_year("1976-06-26T00:00:00Z"), 1976)
        self.assertEqual(_event_year("2026-10-04T10:30:58Z"), 2026)
        self.assertEqual(_event_year(None), 0)
        client = ObisClient()
        params = client.build_query_params(taxon="Thunnus albacares", start_date="2020-01-01")
        self.assertEqual(params.get("startdate"), "2020-01-01")


if __name__ == "__main__":
    unittest.main()
