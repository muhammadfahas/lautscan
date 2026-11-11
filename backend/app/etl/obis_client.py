"""Async OBIS API v3 client normalizing marine biodiversity occurrences for LAUT SCAN."""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

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

DEFAULT_OBIS_API_BASE_URL: Final[str] = "https://api.obis.org/v3"

_INDONESIAN_COMMON_NAMES: Final[dict[str, str]] = {
    "thunnus albacares": "Yellowfin tuna (Madidihang)",
    "thunnus obesus": "Bigeye tuna (Tuna mata besar)",
    "katsuwonus pelamis": "Skipjack tuna (Cakalang)",
    "euthynnus affinis": "Kawakawa (Tongkol komo)",
    "auxis thazard": "Frigate tuna (Tongkol lisong)",
    "rastrelliger kanagurta": "Indian mackerel (Kembung lelaki)",
    "rastrelliger brachysoma": "Short mackerel (Kembung perempuan)",
    "decapterus russelli": "Indian scad (Layang deles)",
    "lutjanus malabaricus": "Malabar blood snapper (Kakap merah)",
    "lutjanus campechanus": "Red snapper (Kakap merah)",
    "epinephelus coioides": "Orange-spotted grouper (Kerapu lumpur)",
    "plectropomus leopardus": "Leopard coral grouper (Kerapu sunu)",
    "sardinella lemuru": "Bali sardinella (Lemuru)",
    "coryphaena hippurus": "Mahi-mahi (Lemadang)",
    "xiphias gladius": "Swordfish (Ikan todak)",
}

WppLocator = Callable[[float, float], str | None]


@dataclass(frozen=True, slots=True)
class NormalizedSpeciesRecord:
    """Flat species record matching `SpeciesOccurrenceRecord` in `docs/openapi-contract.yaml`."""

    id: str
    obis_id: str | None
    scientific_name: str
    common_name: str | None
    taxon_rank: str | None
    family: str | None
    lat: float
    lon: float
    wpp_code: str | None
    depth_m: float | None
    event_date_utc: str | None
    individual_count: int | None
    habitat_note: str | None
    dataset_name: str | None
    attribution: str
    license: str | None

    def to_dict(self) -> dict[str, Any]:
        """Return a flat dict compatible with `SpeciesOccurrenceRecord`."""
        return asdict(self)


@dataclass(slots=True)
class ObisFetchResult:
    """Outcome of querying OBIS `/occurrence`."""

    ok: bool
    url: str
    status_code: int | None = None
    attempts: int = 0
    total_available: int = 0
    records: list[NormalizedSpeciesRecord] = field(default_factory=list)
    skipped_count: int = 0
    error: str | None = None


class ObisClient(ProviderAdapter):
    """Async httpx client for OBIS API v3 (`/occurrence`) over Indonesian waters."""

    metadata: SourceMetadata = CATALOG["obis"]

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout_s: float = 25.0,
        max_retries: int = 3,
        backoff_s: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
        wpp_locator: WppLocator | None = None,
    ) -> None:
        resolved = base_url if base_url is not None else resolve_setting(
            "OBIS_API_BASE_URL",
            DEFAULT_OBIS_API_BASE_URL,
        )
        self.base_url: str = resolved.rstrip("/")
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self._transport = transport
        self._client = client
        self._wpp_locator = wpp_locator

    def is_configured(self) -> bool:
        """OBIS v3 is open and requires only a valid base URL."""
        return bool(self.base_url)

    def build_query_params(
        self,
        *,
        taxon: str | None = None,
        bbox: BoundingBox = INDONESIA_BBOX,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, str | int]:
        """Construct OBIS `/occurrence` query parameters bounded to Indonesia/WPP bbox."""
        clamped_limit = max(1, min(500, int(limit)))
        clamped_offset = max(0, int(offset))
        params: dict[str, str | int] = {
            "geometry": bbox.to_wkt_polygon(),
            "size": clamped_limit,
        }
        if clamped_offset > 0:
            params["offset"] = clamped_offset
        if taxon and taxon.strip():
            params["scientificname"] = taxon.strip()
        return params

    async def fetch_occurrences(
        self,
        *,
        taxon: str | None = None,
        bbox: BoundingBox = INDONESIA_BBOX,
        wpp_code: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> ObisFetchResult:
        """Query OBIS `/occurrence` and normalize results into `SpeciesOccurrenceRecord` shape."""
        endpoint = f"{self.base_url}/occurrence"
        if not self.is_configured():
            return ObisFetchResult(
                ok=False,
                url=endpoint,
                error="OBIS_API_BASE_URL is not configured",
            )

        params = self.build_query_params(
            taxon=taxon,
            bbox=bbox,
            limit=limit,
            offset=offset,
        )

        try:
            response, attempts = await request_with_retry(
                endpoint,
                params=params,
                headers={"Accept": "application/json"},
                timeout_s=self.timeout_s,
                max_retries=self.max_retries,
                backoff_s=self.backoff_s,
                transport=self._transport,
                client=self._client,
            )
            payload = response.json()
        except AdapterRequestError as exc:
            return ObisFetchResult(
                ok=False,
                url=endpoint,
                status_code=exc.status_code,
                attempts=exc.attempts,
                error=str(exc),
            )
        except (ValueError, json.JSONDecodeError) as exc:
            return ObisFetchResult(
                ok=False,
                url=endpoint,
                error=f"Malformed OBIS JSON payload: {exc}",
            )

        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            return ObisFetchResult(
                ok=False,
                url=endpoint,
                status_code=response.status_code,
                attempts=attempts,
                error="OBIS response missing 'results' array",
            )

        records: list[NormalizedSpeciesRecord] = []
        skipped = 0
        for raw in payload["results"]:
            if not isinstance(raw, dict):
                skipped += 1
                continue
            normalized = normalize_occurrence(
                raw,
                default_wpp_code=wpp_code,
                wpp_locator=self._wpp_locator,
            )
            if normalized is None:
                skipped += 1
                continue
            records.append(normalized)

        raw_total = payload.get("total", len(records))
        total_available = (
            raw_total if isinstance(raw_total, int) and raw_total >= 0 else len(records)
        )

        return ObisFetchResult(
            ok=True,
            url=str(response.url),
            status_code=response.status_code,
            attempts=attempts,
            total_available=total_available,
            records=records,
            skipped_count=skipped,
        )

    async def sync(
        self,
        *,
        output_dir: Path | None = None,
        target_date: str | None = None,
        taxon: str | None = None,
        bbox: BoundingBox = INDONESIA_BBOX,
        limit: int = 100,
    ) -> ProviderSyncResult:
        """Fetch Indonesian OBIS marine species records and report sync telemetry."""
        del output_dir, target_date
        started = datetime.now(UTC)
        res = await self.fetch_occurrences(taxon=taxon, bbox=bbox, limit=limit)
        finished = datetime.now(UTC)

        if not res.ok:
            return ProviderSyncResult(
                source_key="obis",
                dataset_type="species_occurrences",
                status="failed",
                records_ingested=0,
                started_at_utc=started,
                finished_at_utc=finished,
                error_message=res.error,
                metadata={
                    "bbox": bbox.to_csv(),
                    "attempts": res.attempts,
                    "status_code": res.status_code,
                },
            )

        return ProviderSyncResult(
            source_key="obis",
            dataset_type="species_occurrences",
            status="success",
            records_ingested=len(res.records),
            acquired_at_utc=finished,
            started_at_utc=started,
            finished_at_utc=finished,
            error_message=None,
            metadata={
                "bbox": bbox.to_csv(),
                "total_available": res.total_available,
                "skipped_count": res.skipped_count,
                "attempts": res.attempts,
                "records": [rec.to_dict() for rec in res.records],
            },
        )


def normalize_occurrence(
    raw: dict[str, Any],
    *,
    default_wpp_code: str | None = None,
    wpp_locator: WppLocator | None = None,
) -> NormalizedSpeciesRecord | None:
    """Normalize a raw OBIS v3 `/occurrence` dict into `SpeciesOccurrenceRecord` fields."""
    lat = _safe_float(raw.get("decimalLatitude"))
    lon = _safe_float(raw.get("decimalLongitude"))
    if lat is None or lon is None:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None

    scientific_raw = raw.get("scientificName") or raw.get("species")
    if not scientific_raw or not str(scientific_raw).strip():
        return None
    scientific_name = str(scientific_raw).strip()

    obis_id_raw = raw.get("id")
    obis_id = str(obis_id_raw).strip() if obis_id_raw not in (None, "") else None

    event_date_utc = _normalize_event_date(raw)
    record_id = _build_record_uuid(obis_id, scientific_name, lat, lon, event_date_utc)

    common_raw = raw.get("vernacularName")
    common_name = (
        str(common_raw).strip()
        if common_raw not in (None, "")
        else _INDONESIAN_COMMON_NAMES.get(scientific_name.lower())
    )

    taxon_rank = _clean_opt_str(raw.get("taxonRank"))
    family = _clean_opt_str(raw.get("family"))
    depth_m = _extract_depth_m(raw)
    individual_count = _extract_individual_count(raw.get("individualCount"))
    habitat_note = _build_habitat_note(raw)
    dataset_name = _clean_opt_str(raw.get("datasetName")) or _clean_opt_str(
        raw.get("collectionCode")
    )
    license_str = _clean_opt_str(raw.get("license"))
    attribution = _build_attribution(raw, dataset_name)

    resolved_wpp = default_wpp_code
    if resolved_wpp is None and wpp_locator is not None:
        resolved_wpp = wpp_locator(lat, lon)

    return NormalizedSpeciesRecord(
        id=record_id,
        obis_id=obis_id,
        scientific_name=scientific_name,
        common_name=common_name,
        taxon_rank=taxon_rank,
        family=family,
        lat=round(lat, 6),
        lon=round(lon, 6),
        wpp_code=resolved_wpp,
        depth_m=depth_m,
        event_date_utc=event_date_utc,
        individual_count=individual_count,
        habitat_note=habitat_note,
        dataset_name=dataset_name,
        attribution=attribution,
        license=license_str,
    )


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _clean_opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _extract_depth_m(raw: dict[str, Any]) -> float | None:
    direct = _safe_float(raw.get("depth"))
    if direct is not None and direct >= 0:
        return round(direct, 2)

    min_d = _safe_float(raw.get("minimumDepthInMeters"))
    max_d = _safe_float(raw.get("maximumDepthInMeters"))
    if min_d is not None and max_d is not None:
        midpoint = (min_d + max_d) / 2.0
        return round(midpoint, 2) if midpoint >= 0 else None
    if min_d is not None and min_d >= 0:
        return round(min_d, 2)
    if max_d is not None and max_d >= 0:
        return round(max_d, 2)
    return None


def _extract_individual_count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _normalize_event_date(raw: dict[str, Any]) -> str | None:
    raw_date = _clean_opt_str(raw.get("eventDate"))
    if raw_date is not None:
        candidate = raw_date.split("/", maxsplit=1)[0].strip()
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            if len(candidate) == 7 and candidate[4] == "-":
                return f"{candidate}-01T00:00:00Z"
            if len(candidate) == 4 and candidate.isdigit():
                return f"{candidate}-01-01T00:00:00Z"

    date_mid = _safe_float(raw.get("date_mid"))
    if date_mid is not None:
        try:
            dt = datetime.fromtimestamp(date_mid / 1000.0, tz=UTC)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OverflowError, OSError, ValueError):
            pass

    year = raw.get("date_year") or raw.get("year")
    if isinstance(year, int) and 1700 <= year <= 2100:
        return f"{year:04d}-01-01T00:00:00Z"
    return None


def _build_habitat_note(raw: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for key in ("habitat", "waterBody", "locality"):
        val = _clean_opt_str(raw.get(key))
        if val and val not in parts:
            parts.append(val)
    if not parts:
        flags: list[str] = []
        if raw.get("marine") is True:
            flags.append("Marine")
        if raw.get("brackish") is True:
            flags.append("Brackish")
        if flags:
            return " / ".join(flags)
        return None
    return "; ".join(parts)


def _build_attribution(raw: dict[str, Any], dataset_name: str | None) -> str:
    holders = [
        _clean_opt_str(raw.get("rightsHolder")),
        _clean_opt_str(raw.get("institutionCode")),
        dataset_name,
    ]
    unique_parts: list[str] = []
    for part in holders:
        if part and part not in unique_parts:
            unique_parts.append(part)
    if not unique_parts:
        return CATALOG["obis"].attribution
    return f"{', '.join(unique_parts)} via OBIS (api.obis.org)"


def _build_record_uuid(
    obis_id: str | None,
    scientific_name: str,
    lat: float,
    lon: float,
    event_date_utc: str | None,
) -> str:
    seed = (
        f"obis:{obis_id}"
        if obis_id is not None
        else f"obis:{scientific_name}:{lat:.5f}:{lon:.5f}:{event_date_utc or ''}"
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))
