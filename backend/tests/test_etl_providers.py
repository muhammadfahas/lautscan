"""Offline unit tests for LAUT SCAN ETL provider adapters and ARQ worker tasks."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from app.etl.base import CATALOG, INDONESIA_BBOX, BoundingBox, ProviderAdapter, redact_secrets
from app.etl.copernicus import CopernicusMarineAdapter
from app.etl.noaa_erddap import NOAAErddapAdapter
from app.etl.obis_client import ObisClient
from app.etl.pdpi_adapter import KkpPdpiAdapter
from app.etl.worker import (
    WorkerSettings,
    prewarm_tiles_task,
    sync_copernicus_task,
    sync_noaa_task,
    sync_obis_task,
)


class CatalogAndBaseTests(unittest.TestCase):
    """Verify source catalog completeness and shared contract invariants."""

    def test_catalog_contains_all_five_sources(self) -> None:
        expected = {"noaa_erddap", "obis", "copernicus_marine", "kkp_pdpi", "gfw"}
        self.assertEqual(set(CATALOG.keys()), expected)

        for key, meta in CATALOG.items():
            self.assertEqual(meta.source_key, key)
            self.assertTrue(meta.display_name)
            self.assertIn(meta.priority, {"P1", "P1/P2", "P2"})
            self.assertTrue(meta.attribution)
            self.assertTrue(meta.license_summary)
            self.assertTrue(meta.official_url.startswith("https://"))

        self.assertFalse(CATALOG["noaa_erddap"].requires_credentials)
        self.assertFalse(CATALOG["obis"].requires_credentials)
        self.assertTrue(CATALOG["copernicus_marine"].requires_credentials)
        self.assertTrue(CATALOG["kkp_pdpi"].requires_credentials)
        self.assertTrue(CATALOG["gfw"].requires_credentials)
        self.assertTrue(CATALOG["gfw"].non_commercial_only)
        self.assertFalse(CATALOG["noaa_erddap"].non_commercial_only)

    def test_adapters_implement_provider_protocol(self) -> None:
        self.assertTrue(issubclass(NOAAErddapAdapter, ProviderAdapter))
        self.assertTrue(issubclass(ObisClient, ProviderAdapter))
        self.assertTrue(issubclass(CopernicusMarineAdapter, ProviderAdapter))
        self.assertTrue(issubclass(KkpPdpiAdapter, ProviderAdapter))

    def test_indonesia_bbox_and_redaction(self) -> None:
        self.assertEqual(INDONESIA_BBOX.min_lat, -12.0)
        self.assertEqual(INDONESIA_BBOX.max_lat, 7.0)
        self.assertEqual(INDONESIA_BBOX.min_lon, 94.0)
        self.assertEqual(INDONESIA_BBOX.max_lon, 142.0)
        self.assertIn("POLYGON((94.0 -12.0", INDONESIA_BBOX.to_wkt_polygon())

        with self.assertRaises(ValueError):
            BoundingBox(min_lat=10.0, max_lat=5.0)

        scrubbed = redact_secrets(
            "Error at https://myuser:s3cr3t!@example.com?p=s3cr3t%21",
            ("myuser", "s3cr3t!"),
        )
        self.assertNotIn("myuser", scrubbed)
        self.assertNotIn("s3cr3t!", scrubbed)
        self.assertNotIn("s3cr3t%21", scrubbed)


class NoaaErddapAdapterTests(unittest.IsolatedAsyncioTestCase):
    """Test NOAA ERDDAP URL construction, retries, NetCDF/JSON parsing, and errors."""

    def test_build_subset_url_indonesia_bbox(self) -> None:
        adapter = NOAAErddapAdapter(base_url="https://erddap.test/erddap/")
        sst_url = adapter.build_subset_url("sst", fmt="nc", target_date="2026-11-10")
        self.assertIn("/griddap/jplMURSST41.nc?", sst_url)
        self.assertIn("[(2026-11-10T12:00:00Z):1:(2026-11-10T12:00:00Z)]", sst_url)
        self.assertIn("[(-12.0):10:(7.0)][(94.0):10:(142.0)]", sst_url)

        cur_url = adapter.build_subset_url("currents", fmt="json", target_date="latest")
        self.assertIn("/griddap/erdTAgeo1day_LonPM180.json?", cur_url)
        self.assertIn(
            "u_current[(last):1:(last)][(0.0)][(-12.0):1:(7.0)][(94.0):1:(142.0)]",
            cur_url,
        )
        self.assertIn("v_current[(last):1:(last)][(0.0)]", cur_url)

        with self.assertRaises(ValueError):
            adapter.build_subset_url("unknown_layer")
        with self.assertRaises(ValueError):
            adapter.build_subset_url("sst", target_date="11-10-2026")

    async def test_fetch_netcdf_with_retry_and_atomic_write(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls < 3:
                return httpx.Response(503, text="Temporary ERDDAP overload")
            return httpx.Response(
                200,
                content=b"CDF\x01MOCK_NETCDF_PAYLOAD",
                headers={"Content-Type": "application/x-netcdf"},
            )

        transport = httpx.MockTransport(handler)
        adapter = NOAAErddapAdapter(
            base_url="https://erddap.test/erddap",
            max_retries=3,
            backoff_s=0.0,
            transport=transport,
        )

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            result = await adapter.fetch_layer_netcdf(
                "sst",
                output_dir=out_dir,
                target_date="2026-11-10",
            )
            self.assertTrue(result.ok)
            self.assertEqual(result.attempts, 3)
            self.assertEqual(result.status_code, 200)
            self.assertIsNotNone(result.file_path)
            assert result.file_path is not None
            self.assertTrue(result.file_path.is_file())
            self.assertEqual(result.file_path.read_bytes(), b"CDF\x01MOCK_NETCDF_PAYLOAD")

    async def test_fetch_json_and_partial_sync_failure(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "jplMURSST41.json" in str(request.url):
                payload = {
                    "table": {
                        "columnNames": ["time", "latitude", "longitude", "analysed_sst"],
                        "columnUnits": ["UTC", "degrees_north", "degrees_east", "degree_C"],
                        "rows": [
                            ["2026-11-10T12:00:00Z", -6.0, 108.0, 29.4],
                            ["2026-11-10T12:00:00Z", -5.5, 110.0, 28.9],
                        ],
                    }
                }
                return httpx.Response(200, json=payload)
            if "erdMH1chla8day.json" in str(request.url):
                return httpx.Response(404, text="Dataset temporarily unavailable")
            raise httpx.ReadTimeout("Simulated ERDDAP timeout", request=request)

        transport = httpx.MockTransport(handler)
        adapter = NOAAErddapAdapter(
            base_url="https://erddap.test/erddap",
            max_retries=2,
            backoff_s=0.0,
            transport=transport,
        )

        json_res = await adapter.fetch_layer_json("sst", target_date="2026-11-10")
        self.assertTrue(json_res.ok)
        self.assertEqual(len(json_res.records), 2)
        self.assertEqual(json_res.records[0]["analysed_sst"], 29.4)

        sync_res = await adapter.sync(
            target_date="2026-11-10",
            layers=("sst", "chlorophyll", "currents"),
        )
        self.assertEqual(sync_res.status, "partial")
        self.assertEqual(sync_res.records_ingested, 2)
        self.assertIsNotNone(sync_res.error_message)
        assert sync_res.error_message is not None
        self.assertIn("chlorophyll: HTTP 404", sync_res.error_message)
        self.assertIn("currents: ReadTimeout", sync_res.error_message)
        # Verify 404 did not retry while timeout retried twice
        self.assertEqual(sync_res.metadata["layers"]["chlorophyll"]["attempts"], 1)
        self.assertEqual(sync_res.metadata["layers"]["currents"]["attempts"], 2)


class ObisClientTests(unittest.IsolatedAsyncioTestCase):
    """Test OBIS v3 occurrence querying and normalization to SpeciesOccurrenceRecord."""

    async def test_obis_fetch_normalizes_records_and_skips_invalid(self) -> None:
        captured_queries: list[dict[str, list[str]]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_queries.append(parse_qs(urlparse(str(request.url)).query))
            payload = {
                "total": 42,
                "results": [
                    {
                        "id": "obis-12345",
                        "scientificName": "Thunnus albacares",
                        "taxonRank": "Species",
                        "family": "Scombridae",
                        "decimalLatitude": -5.42,
                        "decimalLongitude": 127.65,
                        "minimumDepthInMeters": 10.0,
                        "maximumDepthInMeters": 50.0,
                        "eventDate": "2025-08-14/2025-08-15",
                        "individualCount": "3",
                        "waterBody": "Banda Sea",
                        "datasetName": "Indonesia Pelagic Survey",
                        "institutionCode": "BRIN",
                        "license": "CC-BY-4.0",
                    },
                    {
                        "id": "obis-67890",
                        "scientificName": "Katsuwonus pelamis",
                        "vernacularName": "Cakalang",
                        "decimalLatitude": 1.45,
                        "decimalLongitude": 125.25,
                        "date_mid": 1735689600000,
                        "marine": True,
                    },
                    {
                        "id": "bad-coords",
                        "scientificName": "Rastrelliger kanagurta",
                        "decimalLatitude": 150.0,
                        "decimalLongitude": 110.0,
                    },
                ],
            }
            return httpx.Response(200, json=payload)

        client = ObisClient(
            base_url="https://obis.test/v3",
            backoff_s=0.0,
            transport=httpx.MockTransport(handler),
            wpp_locator=lambda lat, lon: "714" if lat < 0 else "716",
        )

        res = await client.fetch_occurrences(taxon="Thunnus", limit=25)
        self.assertTrue(res.ok)
        self.assertEqual(res.total_available, 42)
        self.assertEqual(res.skipped_count, 1)
        self.assertEqual(len(res.records), 2)

        query = captured_queries[0]
        self.assertEqual(query["scientificname"], ["Thunnus"])
        self.assertEqual(query["size"], ["25"])
        self.assertIn("POLYGON((94.0 -12.0", query["geometry"][0])

        expected_fields = {
            "id",
            "obis_id",
            "scientific_name",
            "common_name",
            "taxon_rank",
            "family",
            "lat",
            "lon",
            "wpp_code",
            "depth_m",
            "event_date_utc",
            "individual_count",
            "habitat_note",
            "dataset_name",
            "attribution",
            "license",
        }
        first = res.records[0].to_dict()
        self.assertEqual(set(first.keys()), expected_fields)
        self.assertEqual(first["obis_id"], "obis-12345")
        self.assertEqual(first["common_name"], "Yellowfin tuna (Madidihang)")
        self.assertEqual(first["wpp_code"], "714")
        self.assertEqual(first["depth_m"], 30.0)
        self.assertEqual(first["event_date_utc"], "2025-08-14T00:00:00Z")
        self.assertEqual(first["individual_count"], 3)
        self.assertEqual(first["habitat_note"], "Banda Sea")
        self.assertIn("BRIN", first["attribution"])

        second = res.records[1].to_dict()
        self.assertEqual(second["wpp_code"], "716")
        self.assertEqual(second["event_date_utc"], "2025-01-01T00:00:00Z")
        self.assertEqual(second["habitat_note"], "Marine")

    async def test_obis_error_reporting_is_graceful(self) -> None:
        client = ObisClient(
            base_url="https://obis.test/v3",
            max_retries=2,
            backoff_s=0.0,
            transport=httpx.MockTransport(lambda req: httpx.Response(502, text="Bad Gateway")),
        )
        sync_res = await client.sync()
        self.assertEqual(sync_res.status, "failed")
        self.assertEqual(sync_res.records_ingested, 0)
        self.assertIsNotNone(sync_res.error_message)
        assert sync_res.error_message is not None
        self.assertIn("HTTP 502", sync_res.error_message)


class CopernicusAndPdpiAdapterTests(unittest.IsolatedAsyncioTestCase):
    """Test graceful unconfigured skips, PDPI pluggability, and credential non-leakage."""

    async def test_copernicus_unconfigured_skips_cleanly(self) -> None:
        adapter = CopernicusMarineAdapter(username="", password="")
        self.assertFalse(adapter.is_configured())
        res = await adapter.sync()
        self.assertEqual(res.status, "unconfigured")
        self.assertEqual(res.sync_log_status, "skipped")
        self.assertEqual(res.records_ingested, 0)

        partial = CopernicusMarineAdapter(username="only-user", password="")
        self.assertFalse(partial.is_configured())

    async def test_copernicus_never_leaks_credentials(self) -> None:
        secret_user = "copernicus-sentinel-user"
        secret_pass = "UltraSecret!Pass#2026"

        def failing_runner(**kwargs: Any) -> None:
            raise RuntimeError(
                f"Login failed for https://{kwargs['username']}:{kwargs['password']}@cmems.eu"
            )

        adapter = CopernicusMarineAdapter(
            username=secret_user,
            password=secret_pass,
            subset_runner=failing_runner,
        )
        self.assertTrue(adapter.is_configured())
        self.assertNotIn(secret_user, repr(adapter))
        self.assertNotIn(secret_pass, repr(adapter))

        summary_text = json.dumps(adapter.safe_status_summary())
        self.assertNotIn(secret_user, summary_text)
        self.assertNotIn(secret_pass, summary_text)

        with tempfile.TemporaryDirectory() as tmp:
            res = await adapter.sync(output_dir=Path(tmp), target_date="2026-11-10")
            self.assertEqual(res.status, "failed")
            serialized = json.dumps(
                {
                    "error_message": res.error_message,
                    "metadata": res.metadata,
                }
            )
            self.assertNotIn(secret_user, serialized)
            self.assertNotIn(secret_pass, serialized)
            self.assertIn("***REDACTED***", serialized)

    async def test_copernicus_runner_success(self) -> None:
        captured_calls: list[dict[str, Any]] = []

        async def mock_runner(**kwargs: Any) -> str:
            captured_calls.append(kwargs)
            return f"ok:{kwargs['output_filename']}"

        adapter = CopernicusMarineAdapter(
            username="u",
            password="p",
            subset_runner=mock_runner,
        )
        with tempfile.TemporaryDirectory() as tmp:
            res = await adapter.sync(output_dir=Path(tmp), target_date="2026-11-10")
            self.assertEqual(res.status, "success")
            self.assertEqual(res.records_ingested, 3)
            self.assertEqual(len(captured_calls), 3)
            self.assertEqual(captured_calls[0]["minimum_longitude"], 94.0)
            self.assertEqual(captured_calls[0]["maximum_latitude"], 7.0)

    async def test_pdpi_unconfigured_fixture_and_live_modes(self) -> None:
        unconfigured = KkpPdpiAdapter(base_url="")
        self.assertFalse(unconfigured.is_configured())
        res_unconf = await unconfigured.sync()
        self.assertEqual(res_unconf.status, "unconfigured")
        self.assertEqual(res_unconf.sync_log_status, "skipped")

        fixture_adapter = KkpPdpiAdapter(base_url="", use_fixture_fallback=True)
        res_fix = await fixture_adapter.sync(target_date="2026-11-10")
        self.assertEqual(res_fix.status, "skipped")
        self.assertEqual(res_fix.records_ingested, 2)
        self.assertTrue(res_fix.metadata["zones"][0]["is_fixture"])

        geojson_payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "pdpi-live-713",
                    "properties": {
                        "wpp_code": "713",
                        "confidence_level": "high",
                        "target_species_group": "Pelagic",
                    },
                    "geometry": {"type": "Point", "coordinates": [118.4, -4.1]},
                }
            ],
        }
        live_adapter = KkpPdpiAdapter(
            base_url="https://pdpi.test/feed",
            backoff_s=0.0,
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, json=geojson_payload)
            ),
        )
        res_live = await live_adapter.sync(target_date="2026-11-10")
        self.assertEqual(res_live.status, "success")
        self.assertEqual(res_live.records_ingested, 1)
        self.assertEqual(res_live.metadata["zones"][0]["wpp_code"], "713")
        self.assertEqual(res_live.metadata["zones"][0]["lat"], -4.1)

        wms_xml = (
            "<WMS_Capabilities><Capability><Layer><Name>pdpi_forecast</Name>"
            "<Title>KKP PDPI Daily</Title></Layer></Capability></WMS_Capabilities>"
        )
        wms_adapter = KkpPdpiAdapter(
            base_url="https://pdpi.test/wms?SERVICE=WMS",
            backoff_s=0.0,
            transport=httpx.MockTransport(
                lambda req: httpx.Response(
                    200,
                    text=wms_xml,
                    headers={"Content-Type": "application/xml"},
                )
            ),
        )
        res_wms = await wms_adapter.sync(target_date="2026-11-10")
        self.assertEqual(res_wms.status, "success")
        self.assertEqual(res_wms.records_ingested, 1)
        self.assertEqual(res_wms.metadata["zones"][0]["zone_id"], "pdpi_forecast")

        fail_adapter = KkpPdpiAdapter(
            base_url="https://secret-pdpi.internal/feed",
            max_retries=1,
            backoff_s=0.0,
            transport=httpx.MockTransport(lambda req: httpx.Response(500, text="Server error")),
        )
        res_fail = await fail_adapter.sync(target_date="2026-11-10")
        self.assertEqual(res_fail.status, "failed")
        self.assertNotIn("secret-pdpi.internal", res_fail.error_message or "")


class WorkerSettingsAndTasksTests(unittest.IsolatedAsyncioTestCase):
    """Test ARQ WorkerSettings exports and offline task execution."""

    def test_worker_settings_contract(self) -> None:
        self.assertIsNotNone(WorkerSettings.redis_settings)
        self.assertEqual(
            WorkerSettings.functions,
            [sync_noaa_task, sync_obis_task, sync_copernicus_task, prewarm_tiles_task],
        )
        self.assertGreaterEqual(len(WorkerSettings.cron_jobs), 4)

    async def test_worker_tasks_run_cleanly_offline(self) -> None:
        noaa_transport = httpx.MockTransport(
            lambda req: httpx.Response(200, content=b"CDF\x01TEST_NC")
        )
        obis_transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={
                    "total": 1,
                    "results": [
                        {
                            "id": "o-1",
                            "scientificName": "Katsuwonus pelamis",
                            "decimalLatitude": -5.0,
                            "decimalLongitude": 127.0,
                        }
                    ],
                },
            )
        )

        with tempfile.TemporaryDirectory() as sync_tmp, tempfile.TemporaryDirectory() as tile_tmp:
            ctx: dict[str, Any] = {
                "tile_cache_dir": Path(sync_tmp),
                "noaa_adapter": NOAAErddapAdapter(
                    base_url="https://erddap.test/erddap",
                    backoff_s=0.0,
                    transport=noaa_transport,
                ),
                "obis_client": ObisClient(
                    base_url="https://obis.test/v3",
                    backoff_s=0.0,
                    transport=obis_transport,
                ),
                "copernicus_adapter": CopernicusMarineAdapter(username="", password=""),
            }

            noaa_out = await sync_noaa_task(ctx, target_date="2026-11-10")
            self.assertEqual(noaa_out["status"], "success")
            self.assertEqual(noaa_out["records_ingested"], 3)

            obis_out = await sync_obis_task(ctx)
            self.assertEqual(obis_out["status"], "success")
            self.assertEqual(obis_out["records_ingested"], 1)

            cop_out = await sync_copernicus_task(ctx, target_date="2026-11-10")
            self.assertEqual(cop_out["status"], "unconfigured")
            self.assertEqual(cop_out["sync_log_status"], "skipped")

            prewarm_clean = await prewarm_tiles_task(
                {"tile_cache_dir": Path(tile_tmp)},
                target_date="2026-11-10",
                zoom_levels=(3,),
            )
            self.assertEqual(prewarm_clean["status"], "success")
            self.assertGreater(prewarm_clean["tiles_rendered"], 0)

            # Corrupt/stub NOAA file falls back cleanly to sample NetCDF fixtures.
            prewarm_fallback = await prewarm_tiles_task(
                ctx,
                target_date="2026-11-10",
                zoom_levels=(3,),
            )
            self.assertEqual(prewarm_fallback["status"], "success")
            self.assertGreater(prewarm_fallback["tiles_rendered"], 0)


if __name__ == "__main__":
    unittest.main()
