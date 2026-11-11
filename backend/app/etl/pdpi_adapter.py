"""Pluggable KKP PDPI (Prakiraan Daerah Penangkapan Ikan) adapter."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.etl.base import (
    CATALOG,
    AdapterRequestError,
    ProviderAdapter,
    ProviderSyncResult,
    SourceMetadata,
    redact_secrets,
    request_with_retry,
    resolve_setting,
)


@dataclass(frozen=True, slots=True)
class PdpiZoneRecord:
    """Structured fishing-ground forecast zone produced by the KKP PDPI adapter."""

    zone_id: str
    wpp_code: str | None
    lat: float
    lon: float
    forecast_date: str
    confidence_level: str | None
    target_species_group: str | None
    source_url: str
    attribution: str
    is_fixture: bool = False


class KkpPdpiAdapter(ProviderAdapter):
    """Pluggable adapter for authorized KKP PDPI endpoints (`PDPI_BASE_URL`).

    When `PDPI_BASE_URL` is unset, `sync()` returns `"unconfigured"` cleanly (or
    structured reference fixture records when `use_fixture_fallback=True`) so P1
    open-data ingestion is never blocked.
    """

    metadata: SourceMetadata = CATALOG["kkp_pdpi"]

    def __init__(
        self,
        base_url: str | None = None,
        *,
        use_fixture_fallback: bool = False,
        timeout_s: float = 15.0,
        max_retries: int = 2,
        backoff_s: float = 0.25,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        resolved = base_url if base_url is not None else resolve_setting("PDPI_BASE_URL", "")
        self._base_url: str = resolved.strip().rstrip("/")
        self.use_fixture_fallback = use_fixture_fallback
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self._transport = transport
        self._client = client

    def __repr__(self) -> str:
        return (
            f"KkpPdpiAdapter(configured={self.is_configured()}, "
            f"use_fixture_fallback={self.use_fixture_fallback})"
        )

    def is_configured(self) -> bool:
        """Return True when an authorized KKP PDPI feed/WMS URL is configured."""
        return bool(self._base_url)

    def get_fixture_zones(self, target_date: str | None = None) -> list[PdpiZoneRecord]:
        """Return structured non-live reference records for adapter contract testing."""
        forecast_date = (
            target_date
            if target_date and target_date != "latest"
            else datetime.now(UTC).strftime("%Y-%m-%d")
        )
        fixture_attr = (
            "KKP PDPI Reference Schema Fixture (live feed unconfigured; not operational advice)"
        )
        return [
            PdpiZoneRecord(
                zone_id="pdpi-fixture-712-01",
                wpp_code="712",
                lat=-5.85,
                lon=110.25,
                forecast_date=forecast_date,
                confidence_level="reference_fixture",
                target_species_group="Small Pelagic (Reference)",
                source_url=self.metadata.official_url,
                attribution=fixture_attr,
                is_fixture=True,
            ),
            PdpiZoneRecord(
                zone_id="pdpi-fixture-714-01",
                wpp_code="714",
                lat=-5.40,
                lon=127.60,
                forecast_date=forecast_date,
                confidence_level="reference_fixture",
                target_species_group="Tuna / Skipjack (Reference)",
                source_url=self.metadata.official_url,
                attribution=fixture_attr,
                is_fixture=True,
            ),
        ]

    async def fetch_zones(
        self,
        *,
        target_date: str | None = None,
    ) -> tuple[list[PdpiZoneRecord], str | None, str]:
        """Fetch structured PDPI zones or fall back cleanly when unconfigured."""
        if not self.is_configured():
            if self.use_fixture_fallback:
                return self.get_fixture_zones(target_date), None, "fixture"
            return [], None, "unconfigured"

        date_str = (
            target_date
            if target_date and target_date != "latest"
            else datetime.now(UTC).strftime("%Y-%m-%d")
        )

        try:
            response, _attempts = await request_with_retry(
                self._base_url,
                params={"date": date_str} if "service=wms" not in self._base_url.lower() else None,
                headers={"Accept": "application/json, application/geo+json, application/xml"},
                timeout_s=self.timeout_s,
                max_retries=self.max_retries,
                backoff_s=self.backoff_s,
                transport=self._transport,
                client=self._client,
                secrets_to_redact=(self._base_url,),
            )
        except AdapterRequestError as exc:
            return [], redact_secrets(str(exc), (self._base_url,)), "failed"

        content_type = response.headers.get("content-type", "").lower()
        body_text = response.text.strip()
        if "xml" in content_type or body_text.startswith("<"):
            zones, parse_err = _parse_wms_capabilities(
                body_text,
                forecast_date=date_str,
                source_url=self.metadata.official_url,
                attribution=self.metadata.attribution,
            )
            if parse_err is not None:
                return [], parse_err, "failed"
            return zones, None, "success"

        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            return [], f"Malformed KKP PDPI JSON payload: {exc}", "failed"

        zones = _parse_pdpi_json(
            payload,
            forecast_date=date_str,
            source_url=self.metadata.official_url,
            attribution=self.metadata.attribution,
        )
        return zones, None, "success"

    async def sync(
        self,
        *,
        output_dir: Path | None = None,
        target_date: str | None = None,
    ) -> ProviderSyncResult:
        """Execute non-blocking PDPI ingestion pass or return `"unconfigured"` cleanly."""
        del output_dir
        started = datetime.now(UTC)
        zones, error, mode = await self.fetch_zones(target_date=target_date)
        finished = datetime.now(UTC)

        if mode == "unconfigured":
            return ProviderSyncResult(
                source_key="kkp_pdpi",
                dataset_type="pdpi_zones",
                status="unconfigured",
                records_ingested=0,
                started_at_utc=started,
                finished_at_utc=finished,
                error_message=None,
                metadata={
                    "configured": False,
                    "disposition": "skipped",
                    "non_blocking": True,
                    "reason": "PDPI_BASE_URL is not configured",
                },
            )

        if mode == "fixture":
            return ProviderSyncResult(
                source_key="kkp_pdpi",
                dataset_type="pdpi_zones",
                status="skipped",
                records_ingested=len(zones),
                started_at_utc=started,
                finished_at_utc=finished,
                error_message=None,
                metadata={
                    "configured": False,
                    "mode": "structured_fixture",
                    "non_blocking": True,
                    "zones": [asdict(z) for z in zones],
                },
            )

        if mode == "failed":
            return ProviderSyncResult(
                source_key="kkp_pdpi",
                dataset_type="pdpi_zones",
                status="failed",
                records_ingested=0,
                started_at_utc=started,
                finished_at_utc=finished,
                error_message=error,
                metadata={"configured": True, "non_blocking": True},
            )

        return ProviderSyncResult(
            source_key="kkp_pdpi",
            dataset_type="pdpi_zones",
            status="success",
            records_ingested=len(zones),
            acquired_at_utc=finished,
            started_at_utc=started,
            finished_at_utc=finished,
            error_message=None,
            metadata={
                "configured": True,
                "mode": "live",
                "zones": [asdict(z) for z in zones],
            },
        )


def _parse_pdpi_json(
    payload: Any,
    *,
    forecast_date: str,
    source_url: str,
    attribution: str,
) -> list[PdpiZoneRecord]:
    raw_items: list[dict[str, Any]] = []
    if isinstance(payload, list):
        raw_items = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        if isinstance(payload.get("features"), list):
            for feat in payload["features"]:
                if not isinstance(feat, dict):
                    continue
                props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
                geom = feat.get("geometry") if isinstance(feat.get("geometry"), dict) else {}
                coords = geom.get("coordinates")
                merged = dict(props)
                if (
                    geom.get("type") == "Point"
                    and isinstance(coords, list)
                    and len(coords) >= 2
                ):
                    merged.setdefault("lon", coords[0])
                    merged.setdefault("lat", coords[1])
                if "id" in feat and "zone_id" not in merged:
                    merged["zone_id"] = feat["id"]
                raw_items.append(merged)
        elif isinstance(payload.get("items"), list):
            raw_items = [item for item in payload["items"] if isinstance(item, dict)]

    records: list[PdpiZoneRecord] = []
    for idx, item in enumerate(raw_items):
        lat = _to_float(item.get("lat") or item.get("latitude"))
        lon = _to_float(item.get("lon") or item.get("longitude"))
        if lat is None or lon is None:
            continue
        wpp = item.get("wpp_code") or item.get("wpp")
        records.append(
            PdpiZoneRecord(
                zone_id=str(item.get("zone_id") or item.get("id") or f"pdpi-{idx + 1}"),
                wpp_code=str(wpp) if wpp is not None else None,
                lat=lat,
                lon=lon,
                forecast_date=str(item.get("forecast_date") or forecast_date),
                confidence_level=(
                    str(item["confidence_level"]) if item.get("confidence_level") else None
                ),
                target_species_group=(
                    str(item["target_species_group"])
                    if item.get("target_species_group")
                    else None
                ),
                source_url=source_url,
                attribution=attribution,
                is_fixture=False,
            )
        )
    return records


def _parse_wms_capabilities(
    xml_text: str,
    *,
    forecast_date: str,
    source_url: str,
    attribution: str,
) -> tuple[list[PdpiZoneRecord], str | None]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return [], f"Malformed KKP PDPI WMS XML payload: {exc}"

    zones: list[PdpiZoneRecord] = []
    for idx, layer_el in enumerate(root.iter()):
        if not layer_el.tag.lower().endswith("layer"):
            continue
        name_el = next((c for c in layer_el if c.tag.lower().endswith("name")), None)
        if name_el is None or not (name_el.text or "").strip():
            continue
        title_el = next((c for c in layer_el if c.tag.lower().endswith("title")), None)
        zones.append(
            PdpiZoneRecord(
                zone_id=(name_el.text or "").strip() or f"wms-layer-{idx + 1}",
                wpp_code=None,
                lat=-2.5,
                lon=118.0,
                forecast_date=forecast_date,
                confidence_level="wms_layer",
                target_species_group=(
                    (title_el.text or "").strip() if title_el is not None else None
                ),
                source_url=source_url,
                attribution=attribution,
                is_fixture=False,
            )
        )
    return zones, None


def _to_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
