"""Tests for OpenAPI schemas, FastAPI app setup, `/v1/health`, and `/v1/wpp`."""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.schemas import common as schema_mod  # noqa: E402
from app.schemas.common import (  # noqa: E402
    WPP_CODES,
    DataSourcesResponse,
    DataSourceStatusRecord,
    ErrorResponse,
    HealthStatus,
    MapPointInspection,
    SourceSyncLogRecord,
    SpeciesOccurrenceListResponse,
    SpeciesOccurrenceRecord,
    WppZoneListResponse,
    WppZoneRecord,
)

ALL_SCHEMA_NAMES: tuple[str, ...] = (
    "HealthStatus",
    "WppZoneRecord",
    "WppZoneListResponse",
    "MapPointInspection",
    "SpeciesOccurrenceRecord",
    "SpeciesOccurrenceListResponse",
    "DataSourceStatusRecord",
    "SourceSyncLogRecord",
    "DataSourcesResponse",
    "ErrorResponse",
)


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _all_backend_deps_available() -> bool:
    return all(
        _has_module(pkg)
        for pkg in ("sqlalchemy", "geoalchemy2", "redis", "pydantic_settings")
    )


_ALL_DEPS_AVAILABLE = _all_backend_deps_available()


class _DummyColumn:
    """Minimal SQLAlchemy column expression stand-in for dependency-free unit tests."""

    def __init__(self, name: str) -> None:
        self.name = name

    def asc(self) -> _DummyColumn:
        return self

    def desc(self) -> _DummyColumn:
        return self

    def label(self, _name: str) -> _DummyColumn:
        return self

    def __eq__(self, other: object) -> bool:  # type: ignore[override]
        return False


class _DummySelectStmt:
    def order_by(self, *_args: object) -> _DummySelectStmt:
        return self

    def where(self, *_args: object) -> _DummySelectStmt:
        return self


class _DummyFuncProxy:
    def __getattr__(self, name: str) -> Any:
        def _fn(*_args: object, **_kwargs: object) -> _DummyColumn:
            return _DummyColumn(name)

        return _fn


def _build_local_dependency_stubs() -> dict[str, types.ModuleType]:
    """Provide minimal stubs ONLY when optional runtime packages are absent locally."""
    sa_mod = types.ModuleType("sqlalchemy")
    sa_mod.func = _DummyFuncProxy()  # type: ignore[attr-defined]
    sa_mod.literal = lambda _val: _DummyColumn("literal")  # type: ignore[attr-defined]
    sa_mod.select = lambda *_args: _DummySelectStmt()  # type: ignore[attr-defined]
    sa_mod.text = lambda sql: sql  # type: ignore[attr-defined]

    sa_ext_mod = types.ModuleType("sqlalchemy.ext")
    sa_async_mod = types.ModuleType("sqlalchemy.ext.asyncio")

    class _AsyncSession:
        pass

    sa_async_mod.AsyncSession = _AsyncSession  # type: ignore[attr-defined]

    config_mod = types.ModuleType("app.core.config")

    @dataclass
    class _StubSettings:
        TILE_CACHE_DIR: Path = Path(tempfile.gettempdir()) / "lautscan-test-tiles"
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
        yield object()

    async def _check_db_health() -> tuple[bool, str | None]:
        return False, None

    db_mod.Base = _Base  # type: ignore[attr-defined]
    db_mod.engine = object()  # type: ignore[attr-defined]
    db_mod.async_session_maker = object()  # type: ignore[attr-defined]
    db_mod.get_db = _get_db  # type: ignore[attr-defined]
    db_mod.check_db_health = _check_db_health  # type: ignore[attr-defined]

    redis_pkg_mod = types.ModuleType("redis")
    redis_asyncio_mod = types.ModuleType("redis.asyncio")

    class _Redis:
        pass

    redis_asyncio_mod.Redis = _Redis  # type: ignore[attr-defined]

    redis_mod = types.ModuleType("app.core.redis")

    async def _get_redis() -> Any:
        yield None

    async def _check_redis_health() -> bool:
        return False

    redis_mod.get_redis = _get_redis  # type: ignore[attr-defined]
    redis_mod.check_redis_health = _check_redis_health  # type: ignore[attr-defined]

    spatial_mod = types.ModuleType("app.models.spatial")

    class _DummyModel:
        def __init_subclass__(cls, **kwargs: object) -> None:
            super().__init_subclass__(**kwargs)

        def __getattr__(self, name: str) -> _DummyColumn:
            return _DummyColumn(name)

    class _WppNriZone:
        wpp_code = _DummyColumn("wpp_code")
        name = _DummyColumn("name")
        waters_id = _DummyColumn("waters_id")
        waters_en = _DummyColumn("waters_en")
        legal_basis = _DummyColumn("legal_basis")
        geometry_source = _DummyColumn("geometry_source")
        geom = _DummyColumn("geom")
        centroid = _DummyColumn("centroid")
        min_lon = _DummyColumn("min_lon")
        min_lat = _DummyColumn("min_lat")
        max_lon = _DummyColumn("max_lon")
        max_lat = _DummyColumn("max_lat")
        area_km2 = _DummyColumn("area_km2")
        sst_mean_c = _DummyColumn("sst_mean_c")
        chlorophyll_mean_mg_m3 = _DummyColumn("chlorophyll_mean_mg_m3")
        latest_observation_utc = _DummyColumn("latest_observation_utc")

    spatial_mod.WppNriZone = _WppNriZone  # type: ignore[attr-defined]
    spatial_mod.RasterDataset = _DummyModel  # type: ignore[attr-defined]
    spatial_mod.TileCacheIndex = _DummyModel  # type: ignore[attr-defined]
    spatial_mod.SpeciesOccurrence = _DummyModel  # type: ignore[attr-defined]
    spatial_mod.SourceSyncLog = _DummyModel  # type: ignore[attr-defined]

    return {
        "sqlalchemy": sa_mod,
        "sqlalchemy.ext": sa_ext_mod,
        "sqlalchemy.ext.asyncio": sa_async_mod,
        "redis": redis_pkg_mod,
        "redis.asyncio": redis_asyncio_mod,
        "app.core.config": config_mod,
        "app.core.db": db_mod,
        "app.core.redis": redis_mod,
        "app.models.spatial": spatial_mod,
    }


class _FakeMappingsResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeMappingsResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeDbSession:
    def __init__(self, rows: list[dict[str, Any]] | Exception) -> None:
        self._rows = rows

    async def execute(self, _stmt: object) -> _FakeMappingsResult:
        if isinstance(self._rows, Exception):
            raise self._rows
        return _FakeMappingsResult(self._rows)


class SchemaContractParityTests(unittest.TestCase):
    """Verify all 10 Pydantic schemas align 1:1 with `docs/openapi-contract.yaml`."""

    def test_all_10_openapi_schemas_match_field_for_field_and_forbid_extra(self) -> None:
        contract = yaml.safe_load(
            (REPO_ROOT / "docs" / "openapi-contract.yaml").read_text(encoding="utf-8")
        )
        openapi_schemas: dict[str, Any] = contract["components"]["schemas"]
        self.assertEqual(set(openapi_schemas.keys()), set(ALL_SCHEMA_NAMES))

        for name in ALL_SCHEMA_NAMES:
            model_cls = getattr(schema_mod, name)
            self.assertEqual(model_cls.model_config.get("extra"), "forbid", name)
            expected_fields = list(openapi_schemas[name]["properties"].keys())
            actual_fields = list(model_cls.model_fields.keys())
            self.assertEqual(actual_fields, expected_fields, f"Field mismatch for {name}")
            self.assertEqual(
                set(openapi_schemas[name]["required"]),
                set(expected_fields),
                f"Required mismatch for {name}",
            )

    def test_extra_fields_rejected_and_all_models_serialize(self) -> None:
        now = datetime(2026, 11, 11, 1, 30, tzinfo=UTC)
        health = HealthStatus(
            status="ok",
            service="lautscan-api",
            version="1.2.0",
            environment="development",
            db_ok=True,
            postgis_version="3.4",
            redis_ok=True,
            tile_cache_ok=True,
            timestamp_utc=now,
        )
        self.assertEqual(set(health.model_dump(mode="json").keys()), set(HealthStatus.model_fields))

        with self.assertRaises(ValidationError):
            HealthStatus(
                status="ok",
                service="lautscan-api",
                version="1.2.0",
                environment="development",
                db_ok=True,
                redis_ok=True,
                tile_cache_ok=True,
                timestamp_utc=now,
                unexpected_extra="nope",  # type: ignore[call-arg]
            )

        zone = WppZoneRecord(
            wpp_code="712",
            name="WPP-NRI 712",
            waters_id="Perairan Laut Jawa",
            waters_en="Java Sea",
            legal_basis="Permen-KP No. 18/PERMEN-KP/2014",
            geometry_source="p0_seed",
            centroid_lat=-5.12,
            centroid_lon=111.32,
            min_lon=105.8,
            min_lat=-7.2,
            max_lon=116.5,
            max_lat=-3.2,
        )
        zone_list = WppZoneListResponse(items=[zone], total=1)
        self.assertEqual(zone_list.total, 1)

        point = MapPointInspection(
            lat=-5.5,
            lon=110.2,
            requested_date="latest",
            interpolation_method="bilinear",
            attribution="NOAA CoastWatch",
            is_cached_fallback=False,
            disclaimer="Advisory only",
        )
        self.assertIsNone(point.sst_c)

        species = SpeciesOccurrenceRecord(
            id="occ-1",
            scientific_name="Thunnus albacares",
            lat=-6.1,
            lon=108.4,
            attribution="OBIS v3",
        )
        species_list = SpeciesOccurrenceListResponse(
            items=[species],
            total=1,
            limit=50,
            offset=0,
            has_more=False,
        )
        self.assertFalse(species_list.has_more)

        source_status = DataSourceStatusRecord(
            source_key="noaa_erddap",
            display_name="NOAA CoastWatch ERDDAP",
            priority="P1",
            enabled=True,
            requires_credentials=False,
            non_commercial_only=False,
            status="healthy",
            attribution="NOAA",
            license_summary="Public Domain",
            official_url="https://coastwatch.pfeg.noaa.gov/erddap",
        )
        sync_log = SourceSyncLogRecord(
            id="log-1",
            source_key="noaa_erddap",
            dataset_type="sst",
            status="success",
            records_ingested=100,
            started_at_utc=now,
        )
        sources_resp = DataSourcesResponse(
            sources=[source_status],
            recent_logs=[sync_log],
            checked_at_utc=now,
        )
        self.assertEqual(len(sources_resp.sources), 1)

        err = ErrorResponse(
            error_code="BAD_REQUEST",
            message="Invalid input",
            detail=None,
            timestamp_utc=now,
        )
        self.assertEqual(err.error_code, "BAD_REQUEST")


class RouterAndAppEndpointTests(unittest.TestCase):
    """End-to-end FastAPI TestClient checks for `/v1/health`, `/v1/wpp`, CORS, and errors."""

    _sys_patcher: Any = None
    _preexisting_app_modules: dict[str, Any] = {}
    app_mod: Any = None
    health_mod: Any = None
    wpp_mod: Any = None
    config_mod: Any = None
    db_mod: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        if not _ALL_DEPS_AVAILABLE:
            managed_names = (
                "app.main",
                "app.routers.health",
                "app.routers.wpp",
                "app.routers.tiles",
                "app.routers.map_point",
                "app.routers.species",
                "app.routers.sources",
                "app.core.config",
                "app.core.db",
                "app.core.redis",
                "app.models.spatial",
            )
            cls._preexisting_app_modules = {
                name: sys.modules.pop(name) for name in managed_names if name in sys.modules
            }
            stubs = _build_local_dependency_stubs()
            cls._sys_patcher = patch.dict(sys.modules, stubs)
            cls._sys_patcher.start()

        cls.config_mod = importlib.import_module("app.core.config")
        cls.db_mod = importlib.import_module("app.core.db")
        cls.health_mod = importlib.import_module("app.routers.health")
        cls.wpp_mod = importlib.import_module("app.routers.wpp")
        cls.app_mod = importlib.import_module("app.main")

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._sys_patcher is not None:
            for name in (
                "app.main",
                "app.routers.health",
                "app.routers.wpp",
                "app.routers.tiles",
                "app.routers.map_point",
                "app.routers.species",
                "app.routers.sources",
                "app.core.config",
                "app.core.db",
                "app.core.redis",
                "app.models.spatial",
            ):
                sys.modules.pop(name, None)
            cls._sys_patcher.stop()
            sys.modules.update(cls._preexisting_app_modules)

    def setUp(self) -> None:
        self.app = self.app_mod.create_app()
        self.app.dependency_overrides.clear()

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()

    def _make_settings(self, tile_dir: Path, environment: str = "development") -> Any:
        settings_cls = self.config_mod.Settings
        return settings_cls(
            TILE_CACHE_DIR=tile_dir,
            ENVIRONMENT=environment,
            WPP_SEED_PATH=REPO_ROOT / "data" / "wpp-nri" / "wpp_nri_zones.json",
        )

    def test_health_returns_ok_when_all_dependencies_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tile_dir = Path(tmpdir) / "tiles"
            settings = self._make_settings(tile_dir, environment="development")
            with (
                patch.object(self.health_mod, "get_settings", return_value=settings),
                patch.object(
                    self.health_mod,
                    "check_db_health",
                    new=AsyncMock(return_value=(True, "3.4 USE_GEOS=1")),
                ),
                patch.object(
                    self.health_mod,
                    "check_redis_health",
                    new=AsyncMock(return_value=True),
                ),
                TestClient(self.app) as client,
            ):
                response = client.get("/v1/health")

            self.assertEqual(response.status_code, 200)
            parsed = HealthStatus.model_validate(response.json())
            self.assertEqual(parsed.status, "ok")
            self.assertEqual(parsed.service, "lautscan-api")
            self.assertEqual(parsed.version, "1.2.0")
            self.assertTrue(parsed.db_ok)
            self.assertEqual(parsed.postgis_version, "3.4 USE_GEOS=1")
            self.assertTrue(parsed.redis_ok)
            self.assertTrue(parsed.tile_cache_ok)

    def test_health_returns_degraded_when_optional_deps_down_in_dev(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tile_dir = Path(tmpdir) / "tiles"
            settings = self._make_settings(tile_dir, environment="development")
            with (
                patch.object(self.health_mod, "get_settings", return_value=settings),
                patch.object(
                    self.health_mod,
                    "check_db_health",
                    new=AsyncMock(return_value=(False, None)),
                ),
                patch.object(
                    self.health_mod,
                    "check_redis_health",
                    new=AsyncMock(return_value=False),
                ),
                TestClient(self.app) as client,
            ):
                response = client.get("/v1/health")

            self.assertEqual(response.status_code, 200)
            parsed = HealthStatus.model_validate(response.json())
            self.assertEqual(parsed.status, "degraded")
            self.assertFalse(parsed.db_ok)
            self.assertIsNone(parsed.postgis_version)
            self.assertFalse(parsed.redis_ok)
            self.assertTrue(parsed.tile_cache_ok)

    def test_health_returns_degraded_when_tile_cache_unwritable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            blocking_file = Path(tmpdir) / "not-a-dir"
            blocking_file.write_text("occupied", encoding="utf-8")
            settings = self._make_settings(blocking_file, environment="development")
            with (
                patch.object(self.health_mod, "get_settings", return_value=settings),
                patch.object(
                    self.health_mod,
                    "check_db_health",
                    new=AsyncMock(return_value=(True, "3.4")),
                ),
                patch.object(
                    self.health_mod,
                    "check_redis_health",
                    new=AsyncMock(return_value=True),
                ),
                TestClient(self.app) as client,
            ):
                response = client.get("/v1/health")

            self.assertEqual(response.status_code, 200)
            parsed = HealthStatus.model_validate(response.json())
            self.assertEqual(parsed.status, "degraded")
            self.assertFalse(parsed.tile_cache_ok)

    def test_health_returns_503_error_response_on_fatal_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prod_settings = self._make_settings(Path(tmpdir) / "tiles", environment="production")
            with (
                patch.object(self.health_mod, "get_settings", return_value=prod_settings),
                patch.object(
                    self.health_mod,
                    "check_db_health",
                    new=AsyncMock(return_value=(False, None)),
                ),
                patch.object(
                    self.health_mod,
                    "check_redis_health",
                    new=AsyncMock(return_value=True),
                ),
                TestClient(self.app) as client,
            ):
                prod_resp = client.get("/v1/health")

            self.assertEqual(prod_resp.status_code, 503)
            prod_err = ErrorResponse.model_validate(prod_resp.json())
            self.assertEqual(prod_err.error_code, "DATABASE_UNAVAILABLE")

        with (
            patch.object(self.health_mod, "get_settings", side_effect=RuntimeError("boom")),
            TestClient(self.app) as client,
        ):
            exc_resp = client.get("/v1/health")

        self.assertEqual(exc_resp.status_code, 503)
        exc_err = ErrorResponse.model_validate(exc_resp.json())
        self.assertEqual(exc_err.error_code, "HEALTH_CHECK_FAILED")

    def test_wpp_falls_back_to_seed_json_when_db_unavailable(self) -> None:
        async def _broken_db() -> Any:
            yield _FakeDbSession(ConnectionRefusedError("db offline"))

        self.app.dependency_overrides[self.db_mod.get_db] = _broken_db
        with TestClient(self.app) as client:
            all_resp = client.get("/v1/wpp")
            filtered_resp = client.get("/v1/wpp?code=712")
            no_geom_resp = client.get("/v1/wpp?include_geometry=false")
            bad_code_resp = client.get("/v1/wpp?code=999")

        self.assertEqual(all_resp.status_code, 200)
        parsed_all = WppZoneListResponse.model_validate(all_resp.json())
        self.assertEqual(parsed_all.total, 11)
        self.assertEqual([item.wpp_code for item in parsed_all.items], list(WPP_CODES))
        for item in parsed_all.items:
            self.assertIsNotNone(item.geometry_geojson)
            geom = json.loads(item.geometry_geojson or "")
            self.assertIn(geom["type"], {"Polygon", "MultiPolygon"})

        self.assertEqual(filtered_resp.status_code, 200)
        parsed_712 = WppZoneListResponse.model_validate(filtered_resp.json())
        self.assertEqual(parsed_712.total, 1)
        self.assertEqual(parsed_712.items[0].wpp_code, "712")
        self.assertEqual(parsed_712.items[0].waters_en, "Java Sea")

        self.assertEqual(no_geom_resp.status_code, 200)
        parsed_no_geom = WppZoneListResponse.model_validate(no_geom_resp.json())
        self.assertEqual(parsed_no_geom.total, 11)
        for item in parsed_no_geom.items:
            self.assertIsNone(item.geometry_geojson)

        self.assertEqual(bad_code_resp.status_code, 422)
        err = ErrorResponse.model_validate(bad_code_resp.json())
        self.assertEqual(err.error_code, "VALIDATION_ERROR")

    def test_wpp_uses_postgis_rows_when_available_and_falls_back_when_empty(self) -> None:
        db_row = {
            "wpp_code": "571",
            "name": "WPP-NRI 571",
            "waters_id": "Perairan Selat Malaka dan Laut Andaman",
            "waters_en": "Malacca Strait and Andaman Sea",
            "legal_basis": "Permen-KP No. 18/PERMEN-KP/2014",
            "geometry_source": "kkp_official",
            "centroid_lat": 3.9604,
            "centroid_lon": 99.3605,
            "min_lon": 95.0,
            "min_lat": 1.2,
            "max_lon": 103.5,
            "max_lat": 6.5,
            "area_km2": 285186.0,
            "sst_mean_c": 29.4,
            "chlorophyll_mean_mg_m3": 0.45,
            "latest_observation_utc": datetime(2026, 11, 11, 0, 0, tzinfo=UTC),
            "geometry_geojson": '{"type":"MultiPolygon","coordinates":[]}',
        }

        async def _db_with_row() -> Any:
            yield _FakeDbSession([db_row])

        self.app.dependency_overrides[self.db_mod.get_db] = _db_with_row
        with TestClient(self.app) as client:
            resp = client.get("/v1/wpp?code=571")
            resp_no_geom = client.get("/v1/wpp?code=571&include_geometry=false")

        self.assertEqual(resp.status_code, 200)
        parsed = WppZoneListResponse.model_validate(resp.json())
        self.assertEqual(parsed.total, 1)
        self.assertEqual(parsed.items[0].geometry_source, "kkp_official")
        self.assertEqual(parsed.items[0].sst_mean_c, 29.4)
        self.assertEqual(parsed.items[0].chlorophyll_mean_mg_m3, 0.45)

        parsed_no_geom = WppZoneListResponse.model_validate(resp_no_geom.json())
        self.assertIsNone(parsed_no_geom.items[0].geometry_geojson)

        async def _empty_db() -> Any:
            yield _FakeDbSession([])

        self.app.dependency_overrides[self.db_mod.get_db] = _empty_db
        with TestClient(self.app) as client:
            empty_fallback_resp = client.get("/v1/wpp")
        parsed_empty = WppZoneListResponse.model_validate(empty_fallback_resp.json())
        self.assertEqual(parsed_empty.total, 11)

    def test_app_metadata_cors_and_unified_error_handlers(self) -> None:
        self.assertEqual(self.app.title, "LAUT SCAN Marine Intelligence API")
        self.assertEqual(self.app.version, "1.2.0")

        spec = yaml.safe_load(
            (REPO_ROOT / "docs" / "openapi-contract.yaml").read_text(encoding="utf-8")
        )
        openapi_doc = self.app.openapi()
        openapi_paths = set(openapi_doc["paths"].keys())
        self.assertEqual(openapi_paths, set(spec["paths"].keys()))
        for path, path_item in spec["paths"].items():
            self.assertEqual(
                openapi_doc["paths"][path]["get"]["operationId"],
                path_item["get"]["operationId"],
            )

        @self.app.get("/v1/_test-boom")
        async def _boom() -> dict[str, str]:
            raise RuntimeError("sensitive-secret-do-not-leak")

        with TestClient(self.app, raise_server_exceptions=False) as client:
            not_found = client.get(
                "/v1/nonexistent-route",
                headers={"Origin": "http://localhost:8081"},
            )
            allowed_127 = client.get(
                "/v1/wpp?include_geometry=false",
                headers={"Origin": "http://127.0.0.1:3000"},
            )
            disallowed = client.get(
                "/v1/wpp?include_geometry=false",
                headers={"Origin": "https://evil.example.com"},
            )
            boom_resp = client.get(
                "/v1/_test-boom",
                headers={"Origin": "http://localhost:8081"},
            )

        self.assertEqual(not_found.status_code, 404)
        nf_err = ErrorResponse.model_validate(not_found.json())
        self.assertEqual(nf_err.error_code, "NOT_FOUND")
        self.assertEqual(
            not_found.headers.get("access-control-allow-origin"),
            "http://localhost:8081",
        )

        self.assertEqual(allowed_127.status_code, 200)
        self.assertEqual(
            allowed_127.headers.get("access-control-allow-origin"),
            "http://127.0.0.1:3000",
        )
        self.assertIsNone(disallowed.headers.get("access-control-allow-origin"))

        self.assertEqual(boom_resp.status_code, 500)
        boom_err = ErrorResponse.model_validate(boom_resp.json())
        self.assertEqual(boom_err.error_code, "INTERNAL_SERVER_ERROR")
        self.assertIsNone(boom_err.detail)
        self.assertNotIn("sensitive-secret-do-not-leak", boom_resp.text)


if __name__ == "__main__":
    unittest.main()
