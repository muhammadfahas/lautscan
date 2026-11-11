"""SQLAlchemy 2.0 + GeoAlchemy2 spatial ORM models matching `docs/ARCHITECTURE.md` §2."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

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
SOURCE_KEYS: tuple[str, ...] = (
    "noaa_erddap",
    "obis",
    "copernicus_marine",
    "kkp_pdpi",
    "gfw",
)
RASTER_LAYERS: tuple[str, ...] = ("sst", "chlorophyll", "currents")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class WppNriZone(Base):
    """Indonesian Fisheries Management Area (WPP-NRI 571-718) boundary and summary metrics."""

    __tablename__ = "wpp_nri_zones"
    __table_args__ = (
        CheckConstraint(
            "wpp_code IN ('571','572','573','711','712','713','714','715','716','717','718')",
            name="ck_wpp_nri_zones_wpp_code",
        ),
        CheckConstraint(
            "geometry_source IN ('p0_seed', 'kkp_official')",
            name="ck_wpp_nri_zones_geometry_source",
        ),
        Index("idx_wpp_nri_zones_geom_gist", "geom", postgresql_using="gist"),
        Index("idx_wpp_nri_zones_centroid_gist", "centroid", postgresql_using="gist"),
    )

    wpp_code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    waters_id: Mapped[str] = mapped_column(Text, nullable=False)
    waters_en: Mapped[str] = mapped_column(Text, nullable=False)
    legal_basis: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="Permen-KP No. 18/PERMEN-KP/2014",
        server_default=text("'Permen-KP No. 18/PERMEN-KP/2014'"),
    )
    geometry_source: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="p0_seed",
        server_default=text("'p0_seed'"),
    )
    geom: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
        nullable=False,
    )
    centroid: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
    min_lon: Mapped[float] = mapped_column(Double, nullable=False)
    min_lat: Mapped[float] = mapped_column(Double, nullable=False)
    max_lon: Mapped[float] = mapped_column(Double, nullable=False)
    max_lat: Mapped[float] = mapped_column(Double, nullable=False)
    area_km2: Mapped[float | None] = mapped_column(Double, nullable=True)
    sst_mean_c: Mapped[float | None] = mapped_column(Double, nullable=True)
    chlorophyll_mean_mg_m3: Mapped[float | None] = mapped_column(Double, nullable=True)
    latest_observation_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )

    species_occurrences: Mapped[list[SpeciesOccurrence]] = relationship(
        back_populates="wpp_zone",
    )


class RasterDataset(Base):
    """Metadata index for ingested satellite or model NetCDF/Zarr raster datasets."""

    __tablename__ = "raster_datasets"
    __table_args__ = (
        CheckConstraint(
            "source_key IN ('noaa_erddap','obis','copernicus_marine','kkp_pdpi','gfw')",
            name="ck_raster_datasets_source_key",
        ),
        CheckConstraint(
            "layer IN ('sst', 'chlorophyll', 'currents')",
            name="ck_raster_datasets_layer",
        ),
        CheckConstraint(
            "status IN ('pending', 'ready', 'failed', 'expired')",
            name="ck_raster_datasets_status",
        ),
        UniqueConstraint(
            "source_key",
            "layer",
            "acquisition_date",
            name="uq_raster_source_layer_date",
        ),
        Index("idx_raster_datasets_bounds_gist", "bounds", postgresql_using="gist"),
        Index(
            "idx_raster_datasets_layer_date",
            "layer",
            text("acquisition_date DESC"),
            postgresql_where=text("status = 'ready'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    source_key: Mapped[str] = mapped_column(String(32), nullable=False)
    layer: Mapped[str] = mapped_column(String(24), nullable=False)
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    acquired_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    variable_name: Mapped[str] = mapped_column(String(64), nullable=False)
    units: Mapped[str] = mapped_column(String(32), nullable=False)
    spatial_resolution_km: Mapped[float] = mapped_column(Double, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    bounds: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
        nullable=False,
    )
    min_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="ready",
        server_default=text("'ready'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    tiles: Mapped[list[TileCacheIndex]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
    )


class TileCacheIndex(Base):
    """Rendered 256x256 EPSG:3857 XYZ raster tile cache registry."""

    __tablename__ = "tile_cache_index"
    __table_args__ = (
        CheckConstraint(
            "layer IN ('sst', 'chlorophyll', 'currents')",
            name="ck_tile_cache_index_layer",
        ),
        CheckConstraint("z BETWEEN 0 AND 14", name="ck_tile_cache_index_z"),
        CheckConstraint("x >= 0", name="ck_tile_cache_index_x"),
        CheckConstraint("y >= 0", name="ck_tile_cache_index_y"),
        CheckConstraint("format IN ('png', 'webp')", name="ck_tile_cache_index_format"),
        CheckConstraint("byte_size >= 0", name="ck_tile_cache_index_byte_size"),
        UniqueConstraint(
            "layer",
            "acquisition_date",
            "z",
            "x",
            "y",
            "format",
            name="uq_tile_xyz",
        ),
        Index("idx_tile_cache_layer_date", "layer", "acquisition_date"),
        Index("idx_tile_cache_lru", text("last_accessed_at ASC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("raster_datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    layer: Mapped[str] = mapped_column(String(24), nullable=False)
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    z: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    format: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="png",
        server_default=text("'png'"),
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    is_empty: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    etag: Mapped[str] = mapped_column(String(64), nullable=False)
    hit_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    dataset: Mapped[RasterDataset] = relationship(back_populates="tiles")


class SpeciesOccurrence(Base):
    """Marine biodiversity and fish occurrence observations synced from OBIS."""

    __tablename__ = "species_occurrences"
    __table_args__ = (
        CheckConstraint(
            "individual_count IS NULL OR individual_count >= 0",
            name="ck_species_occurrences_individual_count",
        ),
        Index("idx_species_occurrences_geom_gist", "geom", postgresql_using="gist"),
        Index("idx_species_occurrences_wpp", "wpp_code"),
        Index("idx_species_occurrences_scientific_name", "scientific_name"),
        Index("idx_species_occurrences_event_date", text("event_date_utc DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    obis_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    scientific_name: Mapped[str] = mapped_column(String(160), nullable=False)
    common_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    taxon_rank: Mapped[str | None] = mapped_column(String(48), nullable=True)
    family: Mapped[str | None] = mapped_column(String(96), nullable=True)
    wpp_code: Mapped[str | None] = mapped_column(
        String(3),
        ForeignKey("wpp_nri_zones.wpp_code", ondelete="SET NULL"),
        nullable=True,
    )
    geom: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
    depth_m: Mapped[float | None] = mapped_column(Double, nullable=True)
    event_date_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    individual_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    habitat_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    attribution: Mapped[str] = mapped_column(Text, nullable=False)
    license: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ingested_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    wpp_zone: Mapped[WppNriZone | None] = relationship(back_populates="species_occurrences")


class SourceSyncLog(Base):
    """External data provider ETL synchronization logs and health telemetry."""

    __tablename__ = "source_sync_logs"
    __table_args__ = (
        CheckConstraint(
            "source_key IN ('noaa_erddap','obis','copernicus_marine','kkp_pdpi','gfw')",
            name="ck_source_sync_logs_source_key",
        ),
        CheckConstraint(
            "status IN ('success', 'partial', 'failed', 'skipped')",
            name="ck_source_sync_logs_status",
        ),
        CheckConstraint("records_ingested >= 0", name="ck_source_sync_logs_records_ingested"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_source_sync_logs_duration_ms",
        ),
        Index(
            "idx_source_sync_logs_source_started",
            "source_key",
            text("started_at_utc DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    source_key: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    records_ingested: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    started_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )
    finished_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
