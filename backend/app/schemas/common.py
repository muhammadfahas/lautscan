"""Pydantic v2 schemas matching `docs/openapi-contract.yaml` 1:1."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

WPP_CODES: tuple[str, ...] = (
    "571",
    "572",
    "573",
    "711",
    "712",
    "713",
    "714",
    "715",
    "716",
    "717",
    "718",
)

WppCode = Literal[
    "571",
    "572",
    "573",
    "711",
    "712",
    "713",
    "714",
    "715",
    "716",
    "717",
    "718",
]

SourceKey = Literal[
    "noaa_erddap",
    "obis",
    "copernicus_marine",
    "kkp_pdpi",
    "gfw",
]


class _StrictModel(BaseModel):
    """Base schema rejecting unexpected properties for Exact Contract parity."""

    model_config = ConfigDict(extra="forbid")


class HealthStatus(_StrictModel):
    """Service, PostGIS, Redis, and tile cache health payload."""

    status: Literal["ok", "degraded", "error"]
    service: str
    version: str
    environment: str
    db_ok: bool
    postgis_version: str | None = None
    redis_ok: bool
    tile_cache_ok: bool
    timestamp_utc: datetime


class WppZoneRecord(_StrictModel):
    """Indonesian WPP-NRI zone metadata, summary metrics, and optional GeoJSON string."""

    wpp_code: WppCode
    name: str
    waters_id: str
    waters_en: str
    legal_basis: str
    geometry_source: Literal["p0_seed", "kkp_official"]
    centroid_lat: float
    centroid_lon: float
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    area_km2: float | None = None
    sst_mean_c: float | None = None
    chlorophyll_mean_mg_m3: float | None = None
    latest_observation_utc: datetime | None = None
    geometry_geojson: str | None = None


class WppZoneListResponse(_StrictModel):
    """Collection response for WPP-NRI zones."""

    items: list[WppZoneRecord]
    total: int = Field(ge=0)


class MapPointInspection(_StrictModel):
    """Interpolated oceanographic parameters and WPP-NRI metadata at a coordinate."""

    lat: float
    lon: float
    requested_date: str
    resolved_date: str | None = None
    wpp_code: str | None = None
    wpp_name: str | None = None
    wpp_waters_id: str | None = None
    sst_c: float | None = None
    sst_f: float | None = None
    chlorophyll_mg_m3: float | None = None
    current_speed_ms: float | None = None
    current_speed_knots: float | None = None
    current_direction_deg: float | None = None
    current_compass: str | None = None
    salinity_psu: float | None = None
    wave_height_m: float | None = None
    interpolation_method: Literal["bilinear", "nearest", "unavailable"]
    spatial_resolution_km: float | None = None
    primary_source: str | None = None
    attribution: str
    acquired_at_utc: datetime | None = None
    is_cached_fallback: bool
    disclaimer: str


class SpeciesOccurrenceRecord(_StrictModel):
    """Marine species occurrence record normalized from OBIS."""

    id: str
    obis_id: str | None = None
    scientific_name: str
    common_name: str | None = None
    taxon_rank: str | None = None
    family: str | None = None
    lat: float
    lon: float
    wpp_code: str | None = None
    depth_m: float | None = None
    event_date_utc: datetime | None = None
    individual_count: int | None = None
    habitat_note: str | None = None
    dataset_name: str | None = None
    attribution: str
    license: str | None = None


class SpeciesOccurrenceListResponse(_StrictModel):
    """Paginated response of species occurrence records."""

    items: list[SpeciesOccurrenceRecord]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    has_more: bool


class DataSourceStatusRecord(_StrictModel):
    """Health, attribution, and license status for a marine data provider."""

    source_key: SourceKey
    display_name: str
    priority: Literal["P1", "P1/P2", "P2"]
    enabled: bool
    requires_credentials: bool
    non_commercial_only: bool
    status: Literal["healthy", "degraded", "disabled", "unconfigured", "error"]
    last_sync_utc: datetime | None = None
    latest_data_timestamp_utc: datetime | None = None
    last_error: str | None = None
    attribution: str
    license_summary: str
    official_url: str


class SourceSyncLogRecord(_StrictModel):
    """Recent ETL synchronization execution log entry."""

    id: str
    source_key: SourceKey
    dataset_type: str
    status: Literal["success", "partial", "failed", "skipped"]
    records_ingested: int = Field(ge=0)
    started_at_utc: datetime
    finished_at_utc: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    error_message: str | None = None


class DataSourcesResponse(_StrictModel):
    """Combined provider health statuses and recent ETL sync logs."""

    sources: list[DataSourceStatusRecord]
    recent_logs: list[SourceSyncLogRecord]
    checked_at_utc: datetime


class ErrorResponse(_StrictModel):
    """Unified structured API error payload."""

    error_code: str
    message: str
    detail: str | None = None
    timestamp_utc: datetime


class CurrentVectorCell(_StrictModel):
    """Single decimated ocean current velocity cell."""

    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    u_ms: float
    v_ms: float
    speed_ms: float = Field(ge=0.0)
    speed_knots: float = Field(ge=0.0)
    direction_deg: float = Field(ge=0.0, le=360.0)


class CurrentGridResponse(_StrictModel):
    """Decimated vector grid payload for directional ocean current rendering."""

    requested_date: str
    resolved_date: str
    vectors: list[CurrentVectorCell]
    total: int = Field(ge=0)
    primary_source: str
    acquired_at_utc: datetime
