"""Data source health, compliance status, attribution, and ETL sync log service."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.core.config import get_settings
from app.etl.base import CATALOG, redact_secrets
from app.schemas.common import (
    DataSourcesResponse,
    DataSourceStatusRecord,
    SourceSyncLogRecord,
)

try:
    from sqlalchemy import func, select
except ImportError:  # pragma: no cover - optional when sqlalchemy is absent locally
    func = None  # type: ignore[assignment]
    select = None  # type: ignore[assignment]

try:
    from app.models.spatial import RasterDataset, SourceSyncLog, SpeciesOccurrence
except ImportError:  # pragma: no cover - optional when sqlalchemy models cannot load
    RasterDataset = None  # type: ignore[assignment,misc]
    SourceSyncLog = None  # type: ignore[assignment,misc]
    SpeciesOccurrence = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

SourceStatusLiteral = Literal["healthy", "degraded", "disabled", "unconfigured", "error"]
SOURCE_ORDER: tuple[str, ...] = (
    "noaa_erddap",
    "obis",
    "copernicus_marine",
    "kkp_pdpi",
    "gfw",
)
MAX_RECENT_LOGS = 20


def _meta_attr(meta: Any, key: str, default: Any = None) -> Any:
    if isinstance(meta, dict):
        return meta.get(key, default)
    return getattr(meta, key, default)


def _sanitize_error_message(message: str | None, settings: Any) -> str | None:
    """Redact configured credential values so secrets never leak in API responses."""
    if not message:
        return None
    secrets = [
        str(getattr(settings, attr, "") or "")
        for attr in ("COPERNICUS_USERNAME", "COPERNICUS_PASSWORD", "GFW_API_TOKEN", "PDPI_BASE_URL")
    ]
    return redact_secrets(str(message), secrets)


def _source_config_state(source_key: str, settings: Any) -> tuple[bool, SourceStatusLiteral]:
    """Determine enabled flag and default status from runtime credentials/configuration."""
    if source_key == "gfw":
        token = str(getattr(settings, "GFW_API_TOKEN", "") or "").strip()
        if not token:
            return False, "disabled"
        return True, "healthy"
    if source_key == "copernicus_marine":
        user = str(getattr(settings, "COPERNICUS_USERNAME", "") or "").strip()
        pw = str(getattr(settings, "COPERNICUS_PASSWORD", "") or "").strip()
        if not (user and pw):
            return False, "unconfigured"
        return True, "healthy"
    if source_key == "kkp_pdpi":
        url = str(getattr(settings, "PDPI_BASE_URL", "") or "").strip()
        if not url:
            return False, "unconfigured"
        return True, "healthy"
    return True, "healthy"


def _status_from_sync_log(
    log_status: str,
    default_status: SourceStatusLiteral,
    has_data: bool,
) -> SourceStatusLiteral:
    if log_status == "success":
        return "healthy"
    if log_status == "partial":
        return "degraded"
    if log_status == "failed":
        return "degraded" if has_data else "error"
    return default_status


async def list_data_sources(
    include_recent_logs: bool = True,
    db: Any | None = None,
) -> DataSourcesResponse:
    """Collect live status for all 5 catalogued data sources plus recent ETL logs."""
    settings = get_settings()
    latest_log_by_source: dict[str, Any] = {}
    latest_data_ts: dict[str, datetime] = {}
    recent_log_records: list[SourceSyncLogRecord] = []

    if db is not None and select is not None and func is not None and SourceSyncLog is not None:
        try:
            logs_stmt = (
                select(SourceSyncLog)
                .order_by(SourceSyncLog.started_at_utc.desc())
                .limit(MAX_RECENT_LOGS)
            )
            log_rows = (await db.execute(logs_stmt)).scalars().all()
            for row in log_rows:
                key = str(row.source_key)
                if key not in latest_log_by_source:
                    latest_log_by_source[key] = row
                if include_recent_logs:
                    recent_log_records.append(
                        SourceSyncLogRecord(
                            id=str(row.id),
                            source_key=row.source_key,
                            dataset_type=str(row.dataset_type),
                            status=row.status,
                            records_ingested=int(row.records_ingested),
                            started_at_utc=row.started_at_utc,
                            finished_at_utc=row.finished_at_utc,
                            duration_ms=row.duration_ms,
                            error_message=_sanitize_error_message(row.error_message, settings),
                        )
                    )

            if RasterDataset is not None:
                raster_stmt = (
                    select(
                        RasterDataset.source_key,
                        func.max(RasterDataset.acquired_at_utc).label("max_ts"),
                    )
                    .where(RasterDataset.status == "ready")
                    .group_by(RasterDataset.source_key)
                )
                for src_key, max_ts in (await db.execute(raster_stmt)).all():
                    if max_ts is not None:
                        latest_data_ts[str(src_key)] = max_ts

            if SpeciesOccurrence is not None:
                obis_ts = (
                    await db.execute(select(func.max(SpeciesOccurrence.ingested_at_utc)))
                ).scalar_one_or_none()
                if obis_ts is not None:
                    latest_data_ts["obis"] = obis_ts
        except Exception as exc:
            logger.debug("DB source telemetry unavailable, reporting catalog defaults: %s", exc)

    # Also inspect local global cache manifests (used when Postgres is unavailable locally)
    try:
        global_dir = Path(str(getattr(settings, "TILE_CACHE_DIR", "") or "")) / "global"
        obis_manifest = global_dir / "obis_species.json"
        if obis_manifest.is_file() and "obis" not in latest_data_ts:
            obis_raw = json.loads(obis_manifest.read_text(encoding="utf-8"))
            ts_str = str(obis_raw.get("synced_at_utc") or "").replace("Z", "+00:00")
            if ts_str:
                parsed_ts = datetime.fromisoformat(ts_str).astimezone(UTC)
                latest_data_ts["obis"] = parsed_ts
        noaa_manifest = global_dir / "noaa_manifest.json"
        if noaa_manifest.is_file() and "noaa_erddap" not in latest_data_ts:
            noaa_raw = json.loads(noaa_manifest.read_text(encoding="utf-8"))
            sst_ts = (
                noaa_raw.get("layers", {}).get("sst", {}).get("acquired_at_utc")
                or noaa_raw.get("synced_at_utc")
                or ""
            )
            if sst_ts:
                parsed_sst = datetime.fromisoformat(str(sst_ts).replace("Z", "+00:00"))
                latest_data_ts["noaa_erddap"] = parsed_sst.astimezone(UTC)
    except Exception:
        pass

    ordered_keys = [k for k in SOURCE_ORDER if k in CATALOG] + [
        k for k in CATALOG if k not in SOURCE_ORDER
    ]
    source_records: list[DataSourceStatusRecord] = []
    for key in ordered_keys:
        meta = CATALOG[key]
        enabled, default_status = _source_config_state(key, settings)
        latest_log = latest_log_by_source.get(key)
        latest_ts = latest_data_ts.get(key)

        last_sync_utc: datetime | None = None
        last_error: str | None = None
        status: SourceStatusLiteral = default_status

        if latest_log is not None:
            last_sync_utc = latest_log.finished_at_utc or latest_log.started_at_utc
            last_error = _sanitize_error_message(latest_log.error_message, settings)
            if enabled:
                status = _status_from_sync_log(
                    str(latest_log.status),
                    default_status=default_status,
                    has_data=latest_ts is not None,
                )

        source_records.append(
            DataSourceStatusRecord(
                source_key=key,  # type: ignore[arg-type]
                display_name=str(_meta_attr(meta, "display_name")),
                priority=str(_meta_attr(meta, "priority")),  # type: ignore[arg-type]
                enabled=enabled,
                requires_credentials=bool(_meta_attr(meta, "requires_credentials", False)),
                non_commercial_only=bool(_meta_attr(meta, "non_commercial_only", False)),
                status=status,
                last_sync_utc=last_sync_utc,
                latest_data_timestamp_utc=latest_ts,
                last_error=last_error,
                attribution=str(_meta_attr(meta, "attribution")),
                license_summary=str(_meta_attr(meta, "license_summary")),
                official_url=str(_meta_attr(meta, "official_url")),
            )
        )

    return DataSourcesResponse(
        sources=source_records,
        recent_logs=recent_log_records if include_recent_logs else [],
        checked_at_utc=datetime.now(UTC),
    )
