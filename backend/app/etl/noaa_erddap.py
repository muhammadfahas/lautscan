"""NOAA CoastWatch ERDDAP async client for Indonesian marine raster & JSON subsets."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

import httpx

from app.etl.base import (
    CATALOG,
    INDONESIA_BBOX,
    AdapterRequestError,
    BoundingBox,
    ProviderAdapter,
    ProviderSyncResult,
    SourceMetadata,
    request_with_retry,
    resolve_setting,
)

DEFAULT_NOAA_ERDDAP_BASE_URL: Final[str] = "https://coastwatch.pfeg.noaa.gov/erddap"
_ISO_DATE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")

ErddapLayer = Literal["sst", "chlorophyll", "currents"]
ErddapFormat = Literal["nc", "json"]


@dataclass(frozen=True, slots=True)
class ErddapDatasetSpec:
    """Configuration for a NOAA CoastWatch ERDDAP griddap dataset."""

    layer: ErddapLayer
    dataset_id: str
    variables: tuple[str, ...]
    units: str
    spatial_resolution_km: float
    has_altitude_dim: bool = False
    altitude_value: str = "0.0"
    stride: int = 1


DEFAULT_ERDDAP_DATASETS: Final[dict[str, ErddapDatasetSpec]] = {
    "sst": ErddapDatasetSpec(
        layer="sst",
        dataset_id="jplMURSST41",
        variables=("analysed_sst",),
        units="degree_C",
        spatial_resolution_km=1.0,
        has_altitude_dim=False,
        stride=10,
    ),
    "chlorophyll": ErddapDatasetSpec(
        layer="chlorophyll",
        dataset_id="erdMH1chla8day",
        variables=("chlorophyll",),
        units="mg m-3",
        spatial_resolution_km=4.0,
        has_altitude_dim=False,
        stride=2,
    ),
    "currents": ErddapDatasetSpec(
        layer="currents",
        dataset_id="erdTAgeo1day_LonPM180",
        variables=("u_current", "v_current"),
        units="m s-1",
        spatial_resolution_km=25.0,
        has_altitude_dim=True,
        altitude_value="0.0",
        stride=1,
    ),
}


@dataclass(slots=True)
class ErddapFetchResult:
    """Outcome of a single ERDDAP griddap subset request."""

    ok: bool
    layer: str
    dataset_id: str
    format: ErddapFormat
    url: str
    status_code: int | None = None
    attempts: int = 0
    file_path: Path | None = None
    byte_size: int = 0
    records: list[dict[str, Any]] = field(default_factory=list)
    acquired_at_utc: datetime | None = None
    error: str | None = None


class NOAAErddapAdapter(ProviderAdapter):
    """Async httpx adapter for NOAA CoastWatch ERDDAP griddap subsets."""

    metadata: SourceMetadata = CATALOG["noaa_erddap"]

    def __init__(
        self,
        base_url: str | None = None,
        *,
        datasets: dict[str, ErddapDatasetSpec] | None = None,
        timeout_s: float = 30.0,
        max_retries: int = 3,
        backoff_s: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        resolved = base_url if base_url is not None else resolve_setting(
            "NOAA_ERDDAP_BASE_URL",
            DEFAULT_NOAA_ERDDAP_BASE_URL,
        )
        self.base_url: str = resolved.rstrip("/")
        self.datasets: dict[str, ErddapDatasetSpec] = dict(datasets or DEFAULT_ERDDAP_DATASETS)
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self._transport = transport
        self._client = client

    def is_configured(self) -> bool:
        """NOAA ERDDAP is public and requires only a non-empty base URL."""
        return bool(self.base_url)

    def build_subset_url(
        self,
        layer: str,
        fmt: ErddapFormat = "nc",
        *,
        bbox: BoundingBox = INDONESIA_BBOX,
        target_date: str | None = None,
    ) -> str:
        """Build an ERDDAP griddap subset query URL for Indonesia bounds."""
        if layer not in self.datasets:
            raise ValueError(f"Unsupported ERDDAP layer: {layer!r}")
        if fmt not in ("nc", "json"):
            raise ValueError(f"Unsupported ERDDAP format: {fmt!r}")

        spec = self.datasets[layer]
        time_slice = _resolve_erddap_time(target_date)
        stride = max(1, spec.stride)

        var_clauses: list[str] = []
        for var in spec.variables:
            if spec.has_altitude_dim:
                clause = (
                    f"{var}[({time_slice}):1:({time_slice})]"
                    f"[({spec.altitude_value})]"
                    f"[({bbox.min_lat}):{stride}:({bbox.max_lat})]"
                    f"[({bbox.min_lon}):{stride}:({bbox.max_lon})]"
                )
            else:
                clause = (
                    f"{var}[({time_slice}):1:({time_slice})]"
                    f"[({bbox.min_lat}):{stride}:({bbox.max_lat})]"
                    f"[({bbox.min_lon}):{stride}:({bbox.max_lon})]"
                )
            var_clauses.append(clause)

        return f"{self.base_url}/griddap/{spec.dataset_id}.{fmt}?{','.join(var_clauses)}"

    async def fetch_layer_netcdf(
        self,
        layer: str,
        *,
        output_dir: Path,
        target_date: str | None = None,
        bbox: BoundingBox = INDONESIA_BBOX,
    ) -> ErddapFetchResult:
        """Download a NetCDF subset file atomically to `output_dir`."""
        try:
            url = self.build_subset_url(layer, "nc", bbox=bbox, target_date=target_date)
        except ValueError as exc:
            return ErddapFetchResult(
                ok=False,
                layer=layer,
                dataset_id="",
                format="nc",
                url="",
                error=str(exc),
            )

        spec = self.datasets[layer]
        if not self.is_configured():
            return ErddapFetchResult(
                ok=False,
                layer=layer,
                dataset_id=spec.dataset_id,
                format="nc",
                url=url,
                error="NOAA_ERDDAP_BASE_URL is not configured",
            )

        try:
            response, attempts = await request_with_retry(
                url,
                headers={"Accept": "application/x-netcdf, application/octet-stream"},
                timeout_s=self.timeout_s,
                max_retries=self.max_retries,
                backoff_s=self.backoff_s,
                transport=self._transport,
                client=self._client,
            )
        except AdapterRequestError as exc:
            return ErddapFetchResult(
                ok=False,
                layer=layer,
                dataset_id=spec.dataset_id,
                format="nc",
                url=url,
                status_code=exc.status_code,
                attempts=exc.attempts,
                error=str(exc),
            )

        payload = response.content
        if not payload:
            return ErddapFetchResult(
                ok=False,
                layer=layer,
                dataset_id=spec.dataset_id,
                format="nc",
                url=url,
                status_code=response.status_code,
                attempts=attempts,
                error="Empty NetCDF response payload from ERDDAP",
            )

        date_label = (
            target_date
            if target_date and target_date != "latest"
            else datetime.now(UTC).strftime("%Y-%m-%d")
        )
        target_path = output_dir / f"noaa_{layer}_{date_label}.nc"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = output_dir / f".tmp_noaa_{layer}_{date_label}_{os.getpid()}.nc"
            tmp_path.write_bytes(payload)
            os.replace(tmp_path, target_path)
        except OSError as exc:
            return ErddapFetchResult(
                ok=False,
                layer=layer,
                dataset_id=spec.dataset_id,
                format="nc",
                url=url,
                status_code=response.status_code,
                attempts=attempts,
                error=f"Failed writing NetCDF file: {exc}",
            )

        return ErddapFetchResult(
            ok=True,
            layer=layer,
            dataset_id=spec.dataset_id,
            format="nc",
            url=url,
            status_code=response.status_code,
            attempts=attempts,
            file_path=target_path,
            byte_size=len(payload),
            acquired_at_utc=datetime.now(UTC),
        )

    async def fetch_layer_json(
        self,
        layer: str,
        *,
        target_date: str | None = None,
        bbox: BoundingBox = INDONESIA_BBOX,
    ) -> ErddapFetchResult:
        """Fetch an ERDDAP JSON table subset and normalize rows into dicts."""
        try:
            url = self.build_subset_url(layer, "json", bbox=bbox, target_date=target_date)
        except ValueError as exc:
            return ErddapFetchResult(
                ok=False,
                layer=layer,
                dataset_id="",
                format="json",
                url="",
                error=str(exc),
            )

        spec = self.datasets[layer]
        if not self.is_configured():
            return ErddapFetchResult(
                ok=False,
                layer=layer,
                dataset_id=spec.dataset_id,
                format="json",
                url=url,
                error="NOAA_ERDDAP_BASE_URL is not configured",
            )

        try:
            response, attempts = await request_with_retry(
                url,
                headers={"Accept": "application/json"},
                timeout_s=self.timeout_s,
                max_retries=self.max_retries,
                backoff_s=self.backoff_s,
                transport=self._transport,
                client=self._client,
            )
            payload = response.json()
        except AdapterRequestError as exc:
            return ErddapFetchResult(
                ok=False,
                layer=layer,
                dataset_id=spec.dataset_id,
                format="json",
                url=url,
                status_code=exc.status_code,
                attempts=exc.attempts,
                error=str(exc),
            )
        except (ValueError, json.JSONDecodeError) as exc:
            return ErddapFetchResult(
                ok=False,
                layer=layer,
                dataset_id=spec.dataset_id,
                format="json",
                url=url,
                error=f"Malformed ERDDAP JSON payload: {exc}",
            )

        records, parse_error = _parse_erddap_json_table(payload)
        if parse_error is not None:
            return ErddapFetchResult(
                ok=False,
                layer=layer,
                dataset_id=spec.dataset_id,
                format="json",
                url=url,
                status_code=response.status_code,
                attempts=attempts,
                error=parse_error,
            )

        return ErddapFetchResult(
            ok=True,
            layer=layer,
            dataset_id=spec.dataset_id,
            format="json",
            url=url,
            status_code=response.status_code,
            attempts=attempts,
            records=records,
            acquired_at_utc=datetime.now(UTC),
        )

    async def sync(
        self,
        *,
        output_dir: Path | None = None,
        target_date: str | None = None,
        layers: Sequence[str] = ("sst", "chlorophyll", "currents"),
        bbox: BoundingBox = INDONESIA_BBOX,
    ) -> ProviderSyncResult:
        """Sync Indonesian oceanographic subsets from NOAA ERDDAP across requested layers."""
        started = datetime.now(UTC)
        layer_results: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        succeeded = 0
        ingested = 0
        last_file_path: str | None = None

        for layer in layers:
            if output_dir is not None:
                res = await self.fetch_layer_netcdf(
                    layer,
                    output_dir=output_dir,
                    target_date=target_date,
                    bbox=bbox,
                )
            else:
                res = await self.fetch_layer_json(
                    layer,
                    target_date=target_date,
                    bbox=bbox,
                )

            layer_results[layer] = {
                "ok": res.ok,
                "dataset_id": res.dataset_id,
                "format": res.format,
                "status_code": res.status_code,
                "attempts": res.attempts,
                "file_path": str(res.file_path) if res.file_path else None,
                "byte_size": res.byte_size,
                "row_count": len(res.records),
                "error": res.error,
            }
            if res.ok:
                succeeded += 1
                ingested += len(res.records) if res.format == "json" else 1
                if res.file_path is not None:
                    last_file_path = str(res.file_path)
            elif res.error:
                errors.append(f"{layer}: {res.error}")

        finished = datetime.now(UTC)
        total = len(layers)
        if total == 0:
            status: Literal["success", "partial", "failed", "skipped"] = "skipped"
        elif succeeded == total:
            status = "success"
        elif succeeded > 0:
            status = "partial"
        else:
            status = "failed"

        return ProviderSyncResult(
            source_key="noaa_erddap",
            dataset_type="griddap_netcdf" if output_dir is not None else "griddap_json",
            status=status,
            records_ingested=ingested,
            file_path=last_file_path,
            acquired_at_utc=finished if succeeded > 0 else None,
            started_at_utc=started,
            finished_at_utc=finished,
            error_message="; ".join(errors) if errors else None,
            metadata={"bbox": bbox.to_csv(), "layers": layer_results},
        )


def _resolve_erddap_time(target_date: str | None) -> str:
    if target_date is None or target_date == "latest":
        return "last"
    cleaned = target_date.strip()
    if not _ISO_DATE_PATTERN.match(cleaned):
        raise ValueError(f"target_date must be YYYY-MM-DD or 'latest', got {target_date!r}")
    return f"{cleaned}T12:00:00Z"


def _parse_erddap_json_table(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(payload, dict) or "table" not in payload:
        return [], "ERDDAP JSON missing top-level 'table' object"

    table = payload["table"]
    if not isinstance(table, dict):
        return [], "ERDDAP JSON 'table' is not an object"

    col_names = table.get("columnNames")
    rows = table.get("rows")
    if not isinstance(col_names, list) or not isinstance(rows, list):
        return [], "ERDDAP JSON 'table' missing 'columnNames' or 'rows' arrays"

    records: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(col_names):
            continue
        records.append({str(col): val for col, val in zip(col_names, row, strict=True)})

    return records, None
