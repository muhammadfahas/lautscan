"""Unit tests for core config, DB/Redis helpers, ORM models, Alembic, and WPP seed loader."""

from __future__ import annotations

import ast
import asyncio
import configparser
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db_seed import EXPECTED_WPP_CODES, load_wpp_seed_records, seed_wpp_nri  # noqa: E402


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


class _FakeAsyncSession:
    """Minimal async session stub to verify `seed_wpp_nri` execution without a live DB."""

    def __init__(self) -> None:
        self.executed: list[tuple[object, dict[str, object]]] = []
        self.commits = 0
        self.flushes = 0

    async def execute(self, statement: object, params: dict[str, object]) -> None:
        self.executed.append((statement, params))

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        self.flushes += 1


class CoreArchitectureStaticTests(unittest.TestCase):
    """AST and file-structure tests that run cleanly without optional DB/C dependencies."""

    def test_required_owned_files_exist(self) -> None:
        expected_files = [
            BACKEND_DIR / "app" / "__init__.py",
            BACKEND_DIR / "app" / "core" / "__init__.py",
            BACKEND_DIR / "app" / "core" / "config.py",
            BACKEND_DIR / "app" / "core" / "db.py",
            BACKEND_DIR / "app" / "core" / "redis.py",
            BACKEND_DIR / "app" / "models" / "__init__.py",
            BACKEND_DIR / "app" / "models" / "spatial.py",
            BACKEND_DIR / "app" / "db_seed.py",
            BACKEND_DIR / "alembic.ini",
            BACKEND_DIR / "alembic" / "env.py",
            BACKEND_DIR / "alembic" / "script.py.mako",
            BACKEND_DIR / "alembic" / "versions" / "0001_initial_schema.py",
            BACKEND_DIR / "tests" / "__init__.py",
            BACKEND_DIR / "tests" / "test_models.py",
        ]
        for path in expected_files:
            self.assertTrue(path.is_file(), f"Missing owned file: {path}")

    def test_config_ast_exports_all_env_fields(self) -> None:
        config_src = (BACKEND_DIR / "app" / "core" / "config.py").read_text(encoding="utf-8")
        tree = ast.parse(config_src)

        class_defs = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        self.assertIn("Settings", class_defs)
        settings_node = class_defs["Settings"]
        base_names = [b.id for b in settings_node.bases if isinstance(b, ast.Name)]
        self.assertIn("BaseSettings", base_names)

        declared_fields = {
            stmt.target.id
            for stmt in settings_node.body
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
        }
        required_fields = {
            "DATABASE_URL",
            "REDIS_URL",
            "TILE_CACHE_DIR",
            "API_BASE_URL",
            "ENVIRONMENT",
            "LOG_LEVEL",
            "NOAA_ERDDAP_BASE_URL",
            "OBIS_API_BASE_URL",
            "COPERNICUS_USERNAME",
            "COPERNICUS_PASSWORD",
            "PDPI_BASE_URL",
            "GFW_API_TOKEN",
            "WPP_SEED_PATH",
        }
        self.assertTrue(required_fields.issubset(declared_fields))

        func_defs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertIn("get_settings", func_defs)
        decorator_names = [
            d.id if isinstance(d, ast.Name) else d.func.id
            for d in func_defs["get_settings"].decorator_list
            if isinstance(d, ast.Name) or (isinstance(d, ast.Call) and isinstance(d.func, ast.Name))
        ]
        self.assertIn("lru_cache", decorator_names)

    def test_db_and_redis_ast_exports(self) -> None:
        db_src = (BACKEND_DIR / "app" / "core" / "db.py").read_text(encoding="utf-8")
        db_tree = ast.parse(db_src)
        db_classes = {n.name for n in db_tree.body if isinstance(n, ast.ClassDef)}
        db_async_funcs = {n.name for n in db_tree.body if isinstance(n, ast.AsyncFunctionDef)}
        db_assigns = set()
        for node in db_tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                db_assigns.add(node.target.id)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        db_assigns.add(target.id)

        self.assertIn("Base", db_classes)
        self.assertTrue({"engine", "async_session_maker"}.issubset(db_assigns))
        self.assertTrue({"get_db", "check_db_health"}.issubset(db_async_funcs))

        redis_src = (BACKEND_DIR / "app" / "core" / "redis.py").read_text(encoding="utf-8")
        redis_tree = ast.parse(redis_src)
        redis_async_funcs = {
            n.name for n in redis_tree.body if isinstance(n, ast.AsyncFunctionDef)
        }
        self.assertTrue({"get_redis", "check_redis_health"}.issubset(redis_async_funcs))

    def test_models_ast_classes_and_tables(self) -> None:
        spatial_src = (BACKEND_DIR / "app" / "models" / "spatial.py").read_text(encoding="utf-8")
        tree = ast.parse(spatial_src)
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        expected_models = {
            "WppNriZone": "wpp_nri_zones",
            "RasterDataset": "raster_datasets",
            "TileCacheIndex": "tile_cache_index",
            "SpeciesOccurrence": "species_occurrences",
            "SourceSyncLog": "source_sync_logs",
        }
        self.assertTrue(set(expected_models).issubset(classes))

        for cls_name, table_name in expected_models.items():
            cls_node = classes[cls_name]
            table_val: str | None = None
            for stmt in cls_node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if (
                            isinstance(target, ast.Name)
                            and target.id == "__tablename__"
                            and isinstance(stmt.value, ast.Constant)
                            and isinstance(stmt.value.value, str)
                        ):
                            table_val = stmt.value.value
            self.assertEqual(table_val, table_name)

        expected_indexes = [
            "idx_wpp_nri_zones_geom_gist",
            "idx_wpp_nri_zones_centroid_gist",
            "idx_raster_datasets_bounds_gist",
            "idx_raster_datasets_layer_date",
            "idx_tile_cache_layer_date",
            "idx_tile_cache_lru",
            "idx_species_occurrences_geom_gist",
            "idx_species_occurrences_wpp",
            "idx_species_occurrences_scientific_name",
            "idx_species_occurrences_event_date",
            "idx_source_sync_logs_source_started",
        ]
        for idx_name in expected_indexes:
            self.assertIn(idx_name, spatial_src)

    def test_alembic_configuration_and_initial_migration(self) -> None:
        parser = configparser.ConfigParser()
        parser.read(BACKEND_DIR / "alembic.ini", encoding="utf-8")
        self.assertEqual(parser.get("alembic", "script_location"), "alembic")
        self.assertEqual(parser.get("alembic", "prepend_sys_path"), ".")

        mig_path = BACKEND_DIR / "alembic" / "versions" / "0001_initial_schema.py"
        mig_src = mig_path.read_text(encoding="utf-8")
        tree = ast.parse(mig_src)
        func_names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertTrue({"upgrade", "downgrade"}.issubset(func_names))

        for marker in (
            "CREATE EXTENSION IF NOT EXISTS postgis",
            "CREATE EXTENSION IF NOT EXISTS pgcrypto",
            "wpp_nri_zones",
            "raster_datasets",
            "tile_cache_index",
            "species_occurrences",
            "source_sync_logs",
            "idx_wpp_nri_zones_geom_gist",
            "idx_raster_datasets_bounds_gist",
            "idx_species_occurrences_geom_gist",
            "uq_raster_source_layer_date",
            "uq_tile_xyz",
        ):
            self.assertIn(marker, mig_src)


class WppSeedParserTests(unittest.TestCase):
    """Tests for `app.db_seed` offline parser and PostGIS upsert logic."""

    def test_load_wpp_seed_records_with_geometry(self) -> None:
        seed_file = REPO_ROOT / "data" / "wpp-nri" / "wpp_nri_zones.json"
        records = load_wpp_seed_records(seed_path=seed_file, include_geometry=True)
        self.assertEqual(len(records), 11)
        codes = {rec["wpp_code"] for rec in records}
        self.assertEqual(codes, EXPECTED_WPP_CODES)

        expected_keys = {
            "wpp_code",
            "name",
            "waters_id",
            "waters_en",
            "legal_basis",
            "geometry_source",
            "centroid_lat",
            "centroid_lon",
            "min_lon",
            "min_lat",
            "max_lon",
            "max_lat",
            "area_km2",
            "sst_mean_c",
            "chlorophyll_mean_mg_m3",
            "latest_observation_utc",
            "geometry_geojson",
        }
        for rec in records:
            self.assertEqual(set(rec.keys()), expected_keys)
            self.assertLess(rec["min_lon"], rec["max_lon"])
            self.assertLess(rec["min_lat"], rec["max_lat"])
            self.assertGreater(rec["area_km2"], 0.0)
            self.assertIsNotNone(rec["geometry_geojson"])
            parsed_geom = json.loads(rec["geometry_geojson"])
            self.assertIn(parsed_geom["type"], {"Polygon", "MultiPolygon"})

    def test_load_wpp_seed_records_without_geometry(self) -> None:
        records = load_wpp_seed_records(include_geometry=False)
        self.assertEqual(len(records), 11)
        for rec in records:
            self.assertIsNone(rec["geometry_geojson"])

    def test_load_wpp_seed_records_rejects_missing_codes(self) -> None:
        payload = {"type": "FeatureCollection", "features": []}
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_path = Path(tmpdir) / "bad_wpp.json"
            bad_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_wpp_seed_records(seed_path=bad_path)

    def test_seed_wpp_nri_executes_postgis_upsert_for_all_11_zones(self) -> None:
        fake_session = _FakeAsyncSession()

        if _has_module("sqlalchemy"):
            count = asyncio.run(seed_wpp_nri(fake_session))  # type: ignore[arg-type]
        else:
            fake_sa = types.ModuleType("sqlalchemy")
            fake_sa.text = lambda sql: sql  # type: ignore[attr-defined]
            with patch.dict(sys.modules, {"sqlalchemy": fake_sa}):
                count = asyncio.run(seed_wpp_nri(fake_session))  # type: ignore[arg-type]

        self.assertEqual(count, 11)
        self.assertEqual(len(fake_session.executed), 11)
        self.assertEqual(fake_session.commits, 1)

        first_sql, first_params = fake_session.executed[0]
        sql_text = str(first_sql)
        self.assertIn("ST_Multi(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(", sql_text)
        self.assertIn("4326", sql_text)
        self.assertIn("ON CONFLICT (wpp_code) DO UPDATE", sql_text)
        self.assertEqual(first_params["wpp_code"], "571")


@unittest.skipUnless(_has_module("pydantic_settings"), "pydantic-settings not installed locally")
class SettingsRuntimeTests(unittest.TestCase):
    """Runtime validation of `Settings` and `get_settings()` when pydantic-settings is present."""

    def test_settings_defaults_and_secret_repr_redaction(self) -> None:
        from app.core.config import Settings, get_settings

        get_settings.cache_clear()
        with patch.dict(
            os.environ,
            {
                "COPERNICUS_PASSWORD": "super-secret-copernicus-pw",
                "GFW_API_TOKEN": "super-secret-gfw-token",
            },
            clear=False,
        ):
            settings = Settings()
            self.assertEqual(settings.TILE_CACHE_DIR.as_posix(), "/data/tiles")
            self.assertTrue(settings.WPP_SEED_PATH.is_file())
            self.assertEqual(settings.ENVIRONMENT, "development")
            rendered = repr(settings)
            self.assertNotIn("super-secret-copernicus-pw", rendered)
            self.assertNotIn("super-secret-gfw-token", rendered)


@unittest.skipUnless(
    _has_module("sqlalchemy") and _has_module("geoalchemy2"),
    "sqlalchemy/geoalchemy2 not installed locally",
)
class SpatialOrmMetadataTests(unittest.TestCase):
    """Runtime ORM metadata inspection when SQLAlchemy and GeoAlchemy2 are installed."""

    def test_orm_metadata_tables_indexes_and_constraints(self) -> None:
        import app.models  # noqa: F401
        from app.core.db import Base, check_db_health

        tables = Base.metadata.tables
        self.assertEqual(
            set(tables.keys()),
            {
                "wpp_nri_zones",
                "raster_datasets",
                "tile_cache_index",
                "species_occurrences",
                "source_sync_logs",
            },
        )
        wpp_indexes = {idx.name for idx in tables["wpp_nri_zones"].indexes}
        self.assertIn("idx_wpp_nri_zones_geom_gist", wpp_indexes)
        self.assertIn("idx_wpp_nri_zones_centroid_gist", wpp_indexes)

        raster_indexes = {idx.name for idx in tables["raster_datasets"].indexes}
        self.assertIn("idx_raster_datasets_bounds_gist", raster_indexes)
        self.assertIn("idx_raster_datasets_layer_date", raster_indexes)

        species_indexes = {idx.name for idx in tables["species_occurrences"].indexes}
        self.assertIn("idx_species_occurrences_geom_gist", species_indexes)
        self.assertIn("idx_species_occurrences_event_date", species_indexes)

        db_ok, postgis_ver = asyncio.run(check_db_health(timeout_seconds=0.1))
        self.assertIsInstance(db_ok, bool)
        self.assertTrue(postgis_ver is None or isinstance(postgis_ver, str))


@unittest.skipUnless(_has_module("redis"), "redis not installed locally")
class RedisHealthFallbackTests(unittest.TestCase):
    """Runtime graceful failure tests for `check_redis_health`."""

    def test_check_redis_health_returns_false_when_unreachable(self) -> None:
        from app.core.config import get_settings
        from app.core.redis import check_redis_health

        get_settings.cache_clear()
        with patch.dict(os.environ, {"REDIS_URL": "redis://127.0.0.1:63999/0"}, clear=False):
            get_settings.cache_clear()
            ok = asyncio.run(check_redis_health(timeout_seconds=0.2))
            self.assertFalse(ok)
        get_settings.cache_clear()


if __name__ == "__main__":
    unittest.main()
