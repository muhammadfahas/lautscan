"""Shared contracts, metadata catalog, and HTTP retry utilities for LAUT SCAN ETL adapters."""

from __future__ import annotations

import asyncio
import os
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import quote

import httpx

SourceKey = Literal["noaa_erddap", "obis", "copernicus_marine", "kkp_pdpi", "gfw"]
PriorityLevel = Literal["P1", "P1/P2", "P2"]
AdapterSyncStatus = Literal["success", "partial", "failed", "skipped", "unconfigured"]
SyncLogStatus = Literal["success", "partial", "failed", "skipped"]

RETRYABLE_STATUS_CODES: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
_URL_CREDENTIAL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(https?://)([^/@\s:]+):([^/@\s]+)@"
)


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """WGS84 geographic bounding box (`EPSG:4326`)."""

    min_lat: float = -12.0
    max_lat: float = 7.0
    min_lon: float = 94.0
    max_lon: float = 142.0

    def __post_init__(self) -> None:
        if not (-90.0 <= self.min_lat < self.max_lat <= 90.0):
            raise ValueError(
                f"Invalid latitude range: {self.min_lat}..{self.max_lat} (expected -90..90)"
            )
        if not (-180.0 <= self.min_lon < self.max_lon <= 180.0):
            raise ValueError(
                f"Invalid longitude range: {self.min_lon}..{self.max_lon} (expected -180..180)"
            )

    def to_wkt_polygon(self) -> str:
        """Return a closed counter-clockwise WKT polygon string."""
        return (
            f"POLYGON(({self.min_lon} {self.min_lat},"
            f"{self.max_lon} {self.min_lat},"
            f"{self.max_lon} {self.max_lat},"
            f"{self.min_lon} {self.max_lat},"
            f"{self.min_lon} {self.min_lat}))"
        )

    def to_csv(self) -> str:
        """Return `min_lon,min_lat,max_lon,max_lat` format."""
        return f"{self.min_lon},{self.min_lat},{self.max_lon},{self.max_lat}"


INDONESIA_BBOX: Final[BoundingBox] = BoundingBox(
    min_lat=-12.0,
    max_lat=7.0,
    min_lon=94.0,
    max_lon=142.0,
)


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Immutable compliance and attribution metadata for an external data provider."""

    source_key: SourceKey
    display_name: str
    priority: PriorityLevel
    requires_credentials: bool
    non_commercial_only: bool
    attribution: str
    license_summary: str
    official_url: str


CATALOG: Final[dict[str, SourceMetadata]] = {
    "noaa_erddap": SourceMetadata(
        source_key="noaa_erddap",
        display_name="NOAA CoastWatch ERDDAP",
        priority="P1",
        requires_credentials=False,
        non_commercial_only=False,
        attribution="NOAA CoastWatch / NESDIS / NCEI",
        license_summary="U.S. Government Public Domain; open access with attribution.",
        official_url="https://coastwatch.pfeg.noaa.gov/erddap/",
    ),
    "obis": SourceMetadata(
        source_key="obis",
        display_name="Ocean Biodiversity Information System (OBIS)",
        priority="P1",
        requires_credentials=False,
        non_commercial_only=False,
        attribution="Ocean Biodiversity Information System (OBIS) & original data providers",
        license_summary="Open Access (CC0 / CC-BY per dataset provider attribution).",
        official_url="https://api.obis.org/",
    ),
    "copernicus_marine": SourceMetadata(
        source_key="copernicus_marine",
        display_name="Copernicus Marine Service",
        priority="P1",
        requires_credentials=True,
        non_commercial_only=False,
        attribution="E.U. Copernicus Marine Service Information (CMEMS)",
        license_summary="Free account registration required; open redistribution with attribution.",
        official_url="https://marine.copernicus.eu/",
    ),
    "kkp_pdpi": SourceMetadata(
        source_key="kkp_pdpi",
        display_name="KKP PDPI (Prakiraan Daerah Penangkapan Ikan)",
        priority="P1/P2",
        requires_credentials=True,
        non_commercial_only=False,
        attribution="Kementerian Kelautan dan Perikanan RI (Pusdatin / BPISDKP)",
        license_summary=(
            "Authorized KKP PDPI feed or institutional portal coordination required; non-blocking."
        ),
        official_url="https://portal-informasi.kkp.go.id/pdpi/",
    ),
    "gfw": SourceMetadata(
        source_key="gfw",
        display_name="Global Fishing Watch (GFW) v3",
        priority="P2",
        requires_credentials=True,
        non_commercial_only=True,
        attribution="Global Fishing Watch (globalfishingwatch.org)",
        license_summary=(
            "Opt-in only: free tier restricted to non-commercial / public-interest use; "
            "commercial operators must supply a separate licensed BYO-Token."
        ),
        official_url="https://globalfishingwatch.org/",
    ),
}


@dataclass(slots=True)
class ProviderSyncResult:
    """Standardized telemetry output returned by every ETL provider adapter."""

    source_key: SourceKey
    dataset_type: str
    status: AdapterSyncStatus
    records_ingested: int = 0
    file_path: str | None = None
    acquired_at_utc: datetime | None = None
    started_at_utc: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at_utc: datetime = field(default_factory=lambda: datetime.now(UTC))
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def sync_log_status(self) -> SyncLogStatus:
        """Map adapter status onto the database `source_sync_logs.status` constraint."""
        if self.status == "unconfigured":
            return "skipped"
        return self.status

    @property
    def duration_ms(self) -> int:
        """Compute non-negative elapsed milliseconds between start and finish."""
        elapsed = (self.finished_at_utc - self.started_at_utc).total_seconds() * 1000.0
        return max(0, int(round(elapsed)))


class ProviderAdapter(ABC):
    """Abstract base interface implemented by all marine data provider adapters."""

    metadata: SourceMetadata

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True when required endpoints or credentials are present."""

    @abstractmethod
    async def sync(
        self,
        *,
        output_dir: Path | None = None,
        target_date: str | None = None,
    ) -> ProviderSyncResult:
        """Fetch latest data for Indonesia and return structured sync telemetry."""


class AdapterRequestError(RuntimeError):
    """Raised internally when an HTTP request fails after bounded retries."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        attempts: int = 1,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.attempts = attempts


def resolve_setting(name: str, default: str = "") -> str:
    """Read a setting from `app.core.config.get_settings()` with env-var fallback."""
    try:
        from app.core.config import get_settings

        settings = get_settings()
        value = getattr(settings, name, None)
        if value is not None:
            return str(value).strip()
    except (ImportError, ModuleNotFoundError, AttributeError):
        pass
    return os.environ.get(name, default).strip()


def redact_secrets(text: str, secrets: Sequence[str | None] = ()) -> str:
    """Scrub secret strings, URL-encoded equivalents, and basic-auth URLs from text."""
    sanitized = _URL_CREDENTIAL_PATTERN.sub(r"\1***REDACTED***:***REDACTED***@", text)
    for secret in secrets:
        if not secret:
            continue
        cleaned = secret.strip()
        if not cleaned:
            continue
        sanitized = sanitized.replace(cleaned, "***REDACTED***")
        encoded = quote(cleaned, safe="")
        if encoded and encoded != cleaned:
            sanitized = sanitized.replace(encoded, "***REDACTED***")
    return sanitized


async def request_with_retry(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout_s: float = 30.0,
    max_retries: int = 3,
    backoff_s: float = 0.5,
    transport: httpx.AsyncBaseTransport | None = None,
    client: httpx.AsyncClient | None = None,
    secrets_to_redact: Sequence[str | None] = (),
) -> tuple[httpx.Response, int]:
    """Execute an async HTTP GET with bounded retries and clean error reporting."""
    attempts_allowed = max(1, max_retries)
    timeout = httpx.Timeout(timeout_s, connect=min(10.0, timeout_s))

    async def _run_with_client(http_client: httpx.AsyncClient) -> tuple[httpx.Response, int]:
        last_error: str = "Unknown HTTP error"
        last_status: int | None = None

        for attempt in range(1, attempts_allowed + 1):
            try:
                response = await http_client.get(url, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = redact_secrets(
                    f"{type(exc).__name__}: {exc}",
                    secrets_to_redact,
                )
                last_status = None
                if attempt < attempts_allowed:
                    if backoff_s > 0:
                        await asyncio.sleep(backoff_s * (2 ** (attempt - 1)))
                    continue
                raise AdapterRequestError(
                    last_error,
                    status_code=None,
                    attempts=attempt,
                ) from exc

            if response.status_code < 400:
                return response, attempt

            last_status = response.status_code
            snippet = response.text[:240].strip() if response.text else ""
            last_error = redact_secrets(
                f"HTTP {response.status_code} from upstream"
                + (f": {snippet}" if snippet else ""),
                secrets_to_redact,
            )

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < attempts_allowed:
                delay = _compute_retry_delay(response, backoff_s, attempt)
                if delay > 0:
                    await asyncio.sleep(delay)
                continue

            raise AdapterRequestError(
                last_error,
                status_code=last_status,
                attempts=attempt,
            )

        raise AdapterRequestError(last_error, status_code=last_status, attempts=attempts_allowed)

    if client is not None:
        return await _run_with_client(client)

    async with httpx.AsyncClient(
        timeout=timeout,
        transport=transport,
        follow_redirects=True,
    ) as owned_client:
        return await _run_with_client(owned_client)


def _compute_retry_delay(response: httpx.Response, backoff_s: float, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            parsed = float(retry_after)
            if parsed >= 0:
                return min(parsed, 10.0)
        except ValueError:
            pass
    if backoff_s <= 0:
        return 0.0
    return backoff_s * (2 ** (attempt - 1))
