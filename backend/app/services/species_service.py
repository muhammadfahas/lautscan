"""Marine species occurrence query service with PostGIS + OBIS baseline fallback."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.schemas.common import SpeciesOccurrenceListResponse, SpeciesOccurrenceRecord

try:
    from sqlalchemy import func, or_, select
except ImportError:  # pragma: no cover - optional when sqlalchemy is absent locally
    func = None  # type: ignore[assignment]
    or_ = None  # type: ignore[assignment]
    select = None  # type: ignore[assignment]

try:
    from app.models.spatial import SpeciesOccurrence
except ImportError:  # pragma: no cover - optional when sqlalchemy models cannot load
    SpeciesOccurrence = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

OBIS_FIXTURE_ATTRIBUTION = (
    "Ocean Biodiversity Information System (OBIS) v3: Indonesian Baseline Reference Fixture"
)


class BboxValidationError(ValueError):
    """Raised when a spatial bounding box string or coordinate range is invalid."""


def parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    """Parse and validate `min_lon,min_lat,max_lon,max_lat` in EPSG:4326."""
    parts = [part.strip() for part in bbox.split(",")]
    if len(parts) != 4:
        raise BboxValidationError(
            "Malformed bbox: expected four comma-separated numbers "
            "'min_lon,min_lat,max_lon,max_lat'."
        )
    try:
        min_lon, min_lat, max_lon, max_lat = (float(p) for p in parts)
    except ValueError as exc:
        raise BboxValidationError("Malformed bbox: all four coordinates must be numeric.") from exc

    if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
        raise BboxValidationError("Malformed bbox: longitudes must be within [-180, 180].")
    if not (-90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
        raise BboxValidationError("Malformed bbox: latitudes must be within [-90, 90].")
    if min_lon >= max_lon or min_lat >= max_lat:
        raise BboxValidationError(
            "Malformed bbox: require min_lon < max_lon and min_lat < max_lat."
        )
    return min_lon, min_lat, max_lon, max_lat


def _dt(iso_str: str) -> datetime:
    return datetime.fromisoformat(iso_str).astimezone(UTC)


def _build_baseline_obis_fixtures() -> list[SpeciesOccurrenceRecord]:
    """Deterministic Indonesian marine biodiversity records across all 11 WPP-NRI zones."""
    raw_items: tuple[dict[str, Any], ...] = (
        {
            "id": "10000000-0000-4000-8000-000000000001",
            "obis_id": "obis-baseline-571-001",
            "scientific_name": "Rastrelliger kanagurta",
            "common_name": "Indian mackerel / Ikan kembung",
            "taxon_rank": "species",
            "family": "Scombridae",
            "lat": 3.85,
            "lon": 99.20,
            "wpp_code": "571",
            "depth_m": 28.0,
            "event_date_utc": _dt("2025-11-12T04:15:00+00:00"),
            "individual_count": 42,
            "habitat_note": "Coastal pelagic neritic shelf waters in the Malacca Strait.",
            "dataset_name": "OBIS Indonesia Pelagic Baseline",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000002",
            "obis_id": "obis-baseline-572-001",
            "scientific_name": "Thunnus albacares",
            "common_name": "Yellowfin tuna / Tuna sirip kuning",
            "taxon_rank": "species",
            "family": "Scombridae",
            "lat": -2.15,
            "lon": 97.50,
            "wpp_code": "572",
            "depth_m": 85.0,
            "event_date_utc": _dt("2025-12-03T06:30:00+00:00"),
            "individual_count": 14,
            "habitat_note": "Epipelagic Indian Ocean upwelling corridor west of Sumatra.",
            "dataset_name": "OBIS Indian Ocean Tuna Reference",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000003",
            "obis_id": "obis-baseline-572-002",
            "scientific_name": "Euthynnus affinis",
            "common_name": "Kawakawa / Ikan tongkol",
            "taxon_rank": "species",
            "family": "Scombridae",
            "lat": -5.90,
            "lon": 104.80,
            "wpp_code": "572",
            "depth_m": 35.0,
            "event_date_utc": _dt("2025-10-19T02:45:00+00:00"),
            "individual_count": 31,
            "habitat_note": "Sunda Strait current convergence zone.",
            "dataset_name": "OBIS Indonesia Pelagic Baseline",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000004",
            "obis_id": "obis-baseline-573-001",
            "scientific_name": "Thunnus obesus",
            "common_name": "Bigeye tuna / Tuna mata besar",
            "taxon_rank": "species",
            "family": "Scombridae",
            "lat": -9.50,
            "lon": 114.20,
            "wpp_code": "573",
            "depth_m": 190.0,
            "event_date_utc": _dt("2025-11-28T09:10:00+00:00"),
            "individual_count": 9,
            "habitat_note": "Deep thermocline pelagic waters south of Java and Bali.",
            "dataset_name": "OBIS Indian Ocean Tuna Reference",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000005",
            "obis_id": "obis-baseline-573-002",
            "scientific_name": "Sardinella lemuru",
            "common_name": "Bali sardinella / Ikan lemuru",
            "taxon_rank": "species",
            "family": "Dorosomatidae",
            "lat": -8.80,
            "lon": 115.60,
            "wpp_code": "573",
            "depth_m": 22.0,
            "event_date_utc": _dt("2025-09-14T22:00:00+00:00"),
            "individual_count": 120,
            "habitat_note": "Seasonal southeast monsoon upwelling south of Bali Strait.",
            "dataset_name": "OBIS Indonesia Pelagic Baseline",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000006",
            "obis_id": "obis-baseline-711-001",
            "scientific_name": "Lutjanus malabaricus",
            "common_name": "Malabar blood snapper / Kakap merah",
            "taxon_rank": "species",
            "family": "Lutjanidae",
            "lat": 1.80,
            "lon": 107.20,
            "wpp_code": "711",
            "depth_m": 54.0,
            "event_date_utc": _dt("2025-11-05T05:20:00+00:00"),
            "individual_count": 18,
            "habitat_note": "Sunda Shelf demersal reef-sand substrate in the Natuna Sea.",
            "dataset_name": "OBIS Sunda Shelf Reef & Demersal",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000007",
            "obis_id": "obis-baseline-711-002",
            "scientific_name": "Scomberomorus commerson",
            "common_name": "Narrow-barred Spanish mackerel / Tenggiri",
            "taxon_rank": "species",
            "family": "Scombridae",
            "lat": -1.20,
            "lon": 106.50,
            "wpp_code": "711",
            "depth_m": 32.0,
            "event_date_utc": _dt("2025-10-25T03:40:00+00:00"),
            "individual_count": 11,
            "habitat_note": "Karimata Strait pelagic shelf corridor.",
            "dataset_name": "OBIS Indonesia Pelagic Baseline",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000008",
            "obis_id": "obis-baseline-712-001",
            "scientific_name": "Decapterus russelli",
            "common_name": "Indian scad / Ikan layang",
            "taxon_rank": "species",
            "family": "Carangidae",
            "lat": -5.40,
            "lon": 110.80,
            "wpp_code": "712",
            "depth_m": 40.0,
            "event_date_utc": _dt("2025-12-01T01:50:00+00:00"),
            "individual_count": 85,
            "habitat_note": "Shallow productive shelf waters of the central Java Sea.",
            "dataset_name": "OBIS Indonesia Pelagic Baseline",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000009",
            "obis_id": "obis-baseline-712-002",
            "scientific_name": "Rastrelliger brachysoma",
            "common_name": "Short mackerel / Kembung perempuan",
            "taxon_rank": "species",
            "family": "Scombridae",
            "lat": -5.80,
            "lon": 113.20,
            "wpp_code": "712",
            "depth_m": 24.0,
            "event_date_utc": _dt("2025-11-18T04:05:00+00:00"),
            "individual_count": 64,
            "habitat_note": "Eastern Java Sea chlorophyll-rich coastal waters.",
            "dataset_name": "OBIS Indonesia Pelagic Baseline",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000010",
            "obis_id": "obis-baseline-713-001",
            "scientific_name": "Katsuwonus pelamis",
            "common_name": "Skipjack tuna / Ikan cakalang",
            "taxon_rank": "species",
            "family": "Scombridae",
            "lat": -4.20,
            "lon": 118.40,
            "wpp_code": "713",
            "depth_m": 45.0,
            "event_date_utc": _dt("2025-12-05T07:15:00+00:00"),
            "individual_count": 37,
            "habitat_note": "Indonesian Throughflow (Arlindo) pathway in Makassar Strait.",
            "dataset_name": "OBIS Coral Triangle Marine Records",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000011",
            "obis_id": "obis-baseline-713-002",
            "scientific_name": "Epinephelus coioides",
            "common_name": "Orange-spotted grouper / Kerapu lumpur",
            "taxon_rank": "species",
            "family": "Serranidae",
            "lat": -6.20,
            "lon": 119.50,
            "wpp_code": "713",
            "depth_m": 30.0,
            "event_date_utc": _dt("2025-10-08T03:00:00+00:00"),
            "individual_count": 6,
            "habitat_note": "Flores Sea coral-slope reef ecosystem.",
            "dataset_name": "OBIS Coral Triangle Marine Records",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000012",
            "obis_id": "obis-baseline-714-001",
            "scientific_name": "Thunnus albacares",
            "common_name": "Yellowfin tuna / Tuna sirip kuning",
            "taxon_rank": "species",
            "family": "Scombridae",
            "lat": -5.10,
            "lon": 127.10,
            "wpp_code": "714",
            "depth_m": 95.0,
            "event_date_utc": _dt("2025-12-06T08:45:00+00:00"),
            "individual_count": 21,
            "habitat_note": "Deep Banda Sea pelagic upwelling basin.",
            "dataset_name": "OBIS Coral Triangle Marine Records",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000013",
            "obis_id": "obis-baseline-714-002",
            "scientific_name": "Cheilinus undulatus",
            "common_name": "Humphead wrasse / Ikan napoleon",
            "taxon_rank": "species",
            "family": "Labridae",
            "lat": -4.60,
            "lon": 126.20,
            "wpp_code": "714",
            "depth_m": 18.0,
            "event_date_utc": _dt("2025-09-29T05:10:00+00:00"),
            "individual_count": 3,
            "habitat_note": "Outer coral reef drop-off in the Banda Sea.",
            "dataset_name": "OBIS Coral Triangle Marine Records",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000014",
            "obis_id": "obis-baseline-715-001",
            "scientific_name": "Katsuwonus pelamis",
            "common_name": "Skipjack tuna / Ikan cakalang",
            "taxon_rank": "species",
            "family": "Scombridae",
            "lat": -0.85,
            "lon": 127.30,
            "wpp_code": "715",
            "depth_m": 50.0,
            "event_date_utc": _dt("2025-11-22T06:00:00+00:00"),
            "individual_count": 48,
            "habitat_note": "Halmahera Sea pelagic mixing zone.",
            "dataset_name": "OBIS Coral Triangle Marine Records",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000015",
            "obis_id": "obis-baseline-716-001",
            "scientific_name": "Thunnus alalunga",
            "common_name": "Albacore / Tuna albakora",
            "taxon_rank": "species",
            "family": "Scombridae",
            "lat": 3.10,
            "lon": 123.80,
            "wpp_code": "716",
            "depth_m": 140.0,
            "event_date_utc": _dt("2025-11-10T04:30:00+00:00"),
            "individual_count": 12,
            "habitat_note": "Sulawesi Sea deep oceanic boundary current.",
            "dataset_name": "OBIS Western Pacific Pelagic",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000016",
            "obis_id": "obis-baseline-717-001",
            "scientific_name": "Coryphaena hippurus",
            "common_name": "Mahi-mahi / Ikan lemadang",
            "taxon_rank": "species",
            "family": "Coryphaenidae",
            "lat": 1.40,
            "lon": 135.40,
            "wpp_code": "717",
            "depth_m": 15.0,
            "event_date_utc": _dt("2025-11-16T03:20:00+00:00"),
            "individual_count": 19,
            "habitat_note": "Pacific surface drift convergence north of Cenderawasih Bay.",
            "dataset_name": "OBIS Western Pacific Pelagic",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000017",
            "obis_id": "obis-baseline-718-001",
            "scientific_name": "Penaeus monodon",
            "common_name": "Giant tiger prawn / Udang windu",
            "taxon_rank": "species",
            "family": "Penaeidae",
            "lat": -8.05,
            "lon": 134.50,
            "wpp_code": "718",
            "depth_m": 36.0,
            "event_date_utc": _dt("2025-12-02T00:50:00+00:00"),
            "individual_count": 75,
            "habitat_note": "Arafura Sea shallow muddy-sand demersal shelf.",
            "dataset_name": "OBIS Arafura Demersal Baseline",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
        {
            "id": "10000000-0000-4000-8000-000000000018",
            "obis_id": "obis-baseline-718-002",
            "scientific_name": "Lutjanus erythropterus",
            "common_name": "Crimson snapper / Kakap merah",
            "taxon_rank": "species",
            "family": "Lutjanidae",
            "lat": -7.80,
            "lon": 136.20,
            "wpp_code": "718",
            "depth_m": 48.0,
            "event_date_utc": _dt("2025-10-30T02:15:00+00:00"),
            "individual_count": 23,
            "habitat_note": "Aru and Arafura Sea continental shelf.",
            "dataset_name": "OBIS Arafura Demersal Baseline",
            "attribution": OBIS_FIXTURE_ATTRIBUTION,
            "license": "CC-BY-4.0",
        },
    )
    return [SpeciesOccurrenceRecord(**item) for item in raw_items]


BASELINE_OBIS_FIXTURES: list[SpeciesOccurrenceRecord] = _build_baseline_obis_fixtures()


def _filter_fixtures(
    taxon: str | None,
    wpp: str | None,
    bbox_tuple: tuple[float, float, float, float] | None,
    limit: int,
    offset: int,
) -> SpeciesOccurrenceListResponse:
    items = list(BASELINE_OBIS_FIXTURES)
    if taxon:
        needle = taxon.strip().lower()
        items = [
            rec
            for rec in items
            if needle in rec.scientific_name.lower()
            or (rec.common_name and needle in rec.common_name.lower())
            or (rec.family and needle in rec.family.lower())
        ]
    if wpp:
        items = [rec for rec in items if rec.wpp_code == wpp]
    if bbox_tuple is not None:
        min_lon, min_lat, max_lon, max_lat = bbox_tuple
        items = [
            rec
            for rec in items
            if min_lon <= rec.lon <= max_lon and min_lat <= rec.lat <= max_lat
        ]

    items.sort(
        key=lambda rec: (
            -(rec.event_date_utc.timestamp() if rec.event_date_utc else 0.0),
            rec.scientific_name,
            rec.id,
        )
    )
    total = len(items)
    sliced = items[offset : offset + limit]
    return SpeciesOccurrenceListResponse(
        items=sliced,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(sliced)) < total,
    )


async def list_species_occurrences(
    taxon: str | None = None,
    wpp: str | None = None,
    bbox: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Any | None = None,
) -> SpeciesOccurrenceListResponse:
    """Query species occurrences from PostGIS when populated, else OBIS baseline fixtures."""
    bbox_tuple = parse_bbox(bbox) if bbox is not None else None

    if (
        db is not None
        and select is not None
        and func is not None
        and or_ is not None
        and SpeciesOccurrence is not None
    ):
        try:
            has_rows = (
                await db.execute(select(SpeciesOccurrence.id).limit(1))
            ).scalar_one_or_none()
            if has_rows is not None:
                filters: list[Any] = []
                if taxon:
                    pattern = f"%{taxon.strip()}%"
                    filters.append(
                        or_(
                            SpeciesOccurrence.scientific_name.ilike(pattern),
                            SpeciesOccurrence.common_name.ilike(pattern),
                            SpeciesOccurrence.family.ilike(pattern),
                        )
                    )
                if wpp:
                    filters.append(SpeciesOccurrence.wpp_code == wpp)
                if bbox_tuple is not None:
                    min_lon, min_lat, max_lon, max_lat = bbox_tuple
                    envelope = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
                    filters.append(func.ST_Intersects(SpeciesOccurrence.geom, envelope))

                count_stmt = select(func.count()).select_from(SpeciesOccurrence)
                if filters:
                    count_stmt = count_stmt.where(*filters)
                total = int((await db.execute(count_stmt)).scalar_one())

                data_stmt = select(
                    SpeciesOccurrence.id,
                    SpeciesOccurrence.obis_id,
                    SpeciesOccurrence.scientific_name,
                    SpeciesOccurrence.common_name,
                    SpeciesOccurrence.taxon_rank,
                    SpeciesOccurrence.family,
                    func.ST_Y(SpeciesOccurrence.geom).label("lat"),
                    func.ST_X(SpeciesOccurrence.geom).label("lon"),
                    SpeciesOccurrence.wpp_code,
                    SpeciesOccurrence.depth_m,
                    SpeciesOccurrence.event_date_utc,
                    SpeciesOccurrence.individual_count,
                    SpeciesOccurrence.habitat_note,
                    SpeciesOccurrence.dataset_name,
                    SpeciesOccurrence.attribution,
                    SpeciesOccurrence.license,
                )
                if filters:
                    data_stmt = data_stmt.where(*filters)
                data_stmt = (
                    data_stmt.order_by(
                        SpeciesOccurrence.event_date_utc.desc().nullslast(),
                        SpeciesOccurrence.scientific_name.asc(),
                        SpeciesOccurrence.id.asc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
                rows = (await db.execute(data_stmt)).all()
                records = [
                    SpeciesOccurrenceRecord(
                        id=str(row.id),
                        obis_id=row.obis_id,
                        scientific_name=str(row.scientific_name),
                        common_name=row.common_name,
                        taxon_rank=row.taxon_rank,
                        family=row.family,
                        lat=float(row.lat),
                        lon=float(row.lon),
                        wpp_code=row.wpp_code,
                        depth_m=float(row.depth_m) if row.depth_m is not None else None,
                        event_date_utc=row.event_date_utc,
                        individual_count=row.individual_count,
                        habitat_note=row.habitat_note,
                        dataset_name=row.dataset_name,
                        attribution=str(row.attribution),
                        license=row.license,
                    )
                    for row in rows
                ]
                return SpeciesOccurrenceListResponse(
                    items=records,
                    total=total,
                    limit=limit,
                    offset=offset,
                    has_more=(offset + len(records)) < total,
                )
        except Exception as exc:
            logger.debug("PostGIS species query failed, falling back to OBIS baseline: %s", exc)

    return _filter_fixtures(taxon=taxon, wpp=wpp, bbox_tuple=bbox_tuple, limit=limit, offset=offset)
