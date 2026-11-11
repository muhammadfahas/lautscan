"""Initial LAUT SCAN PostGIS schema: WPP-NRI, rasters, tiles, species, sync logs.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-11 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create PostGIS extensions, all 5 spatial/telemetry tables, and GIST/B-tree indexes."""
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # 1. Indonesian Fisheries Management Areas (WPP-NRI 571-718)
    op.create_table(
        "wpp_nri_zones",
        sa.Column("wpp_code", sa.String(length=3), primary_key=True),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("waters_id", sa.Text(), nullable=False),
        sa.Column("waters_en", sa.Text(), nullable=False),
        sa.Column(
            "legal_basis",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'Permen-KP No. 18/PERMEN-KP/2014'"),
        ),
        sa.Column(
            "geometry_source",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'p0_seed'"),
        ),
        sa.Column(
            "geom",
            Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "centroid",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("min_lon", sa.Double(), nullable=False),
        sa.Column("min_lat", sa.Double(), nullable=False),
        sa.Column("max_lon", sa.Double(), nullable=False),
        sa.Column("max_lat", sa.Double(), nullable=False),
        sa.Column("area_km2", sa.Double(), nullable=True),
        sa.Column("sst_mean_c", sa.Double(), nullable=True),
        sa.Column("chlorophyll_mean_mg_m3", sa.Double(), nullable=True),
        sa.Column("latest_observation_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "wpp_code IN ('571','572','573','711','712','713','714','715','716','717','718')",
            name="ck_wpp_nri_zones_wpp_code",
        ),
        sa.CheckConstraint(
            "geometry_source IN ('p0_seed', 'kkp_official')",
            name="ck_wpp_nri_zones_geometry_source",
        ),
    )
    op.create_index(
        "idx_wpp_nri_zones_geom_gist",
        "wpp_nri_zones",
        ["geom"],
        unique=False,
        postgresql_using="gist",
    )
    op.create_index(
        "idx_wpp_nri_zones_centroid_gist",
        "wpp_nri_zones",
        ["centroid"],
        unique=False,
        postgresql_using="gist",
    )

    # 2. Ingested Satellite / Model Raster Datasets
    op.create_table(
        "raster_datasets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_key", sa.String(length=32), nullable=False),
        sa.Column("layer", sa.String(length=24), nullable=False),
        sa.Column("acquisition_date", sa.Date(), nullable=False),
        sa.Column("acquired_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("variable_name", sa.String(length=64), nullable=False),
        sa.Column("units", sa.String(length=32), nullable=False),
        sa.Column("spatial_resolution_km", sa.Double(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column(
            "bounds",
            Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("min_value", sa.Double(), nullable=True),
        sa.Column("max_value", sa.Double(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'ready'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "source_key IN ('noaa_erddap','obis','copernicus_marine','kkp_pdpi','gfw')",
            name="ck_raster_datasets_source_key",
        ),
        sa.CheckConstraint(
            "layer IN ('sst', 'chlorophyll', 'currents')",
            name="ck_raster_datasets_layer",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'failed', 'expired')",
            name="ck_raster_datasets_status",
        ),
        sa.UniqueConstraint(
            "source_key",
            "layer",
            "acquisition_date",
            name="uq_raster_source_layer_date",
        ),
    )
    op.create_index(
        "idx_raster_datasets_bounds_gist",
        "raster_datasets",
        ["bounds"],
        unique=False,
        postgresql_using="gist",
    )
    op.create_index(
        "idx_raster_datasets_layer_date",
        "raster_datasets",
        ["layer", sa.text("acquisition_date DESC")],
        unique=False,
        postgresql_where=sa.text("status = 'ready'"),
    )

    # 3. Rendered XYZ Raster Tile Cache Index
    op.create_table(
        "tile_cache_index",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raster_datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("layer", sa.String(length=24), nullable=False),
        sa.Column("acquisition_date", sa.Date(), nullable=False),
        sa.Column("z", sa.SmallInteger(), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column(
            "format",
            sa.String(length=8),
            nullable=False,
            server_default=sa.text("'png'"),
        ),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column(
            "is_empty",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("etag", sa.String(length=64), nullable=False),
        sa.Column(
            "hit_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "last_accessed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "layer IN ('sst', 'chlorophyll', 'currents')",
            name="ck_tile_cache_index_layer",
        ),
        sa.CheckConstraint("z BETWEEN 0 AND 14", name="ck_tile_cache_index_z"),
        sa.CheckConstraint("x >= 0", name="ck_tile_cache_index_x"),
        sa.CheckConstraint("y >= 0", name="ck_tile_cache_index_y"),
        sa.CheckConstraint(
            "format IN ('png', 'webp')",
            name="ck_tile_cache_index_format",
        ),
        sa.CheckConstraint("byte_size >= 0", name="ck_tile_cache_index_byte_size"),
        sa.UniqueConstraint(
            "layer",
            "acquisition_date",
            "z",
            "x",
            "y",
            "format",
            name="uq_tile_xyz",
        ),
    )
    op.create_index(
        "idx_tile_cache_layer_date",
        "tile_cache_index",
        ["layer", "acquisition_date"],
        unique=False,
    )
    op.create_index(
        "idx_tile_cache_lru",
        "tile_cache_index",
        [sa.text("last_accessed_at ASC")],
        unique=False,
    )

    # 4. Marine Species & Fish Occurrences (OBIS v3)
    op.create_table(
        "species_occurrences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("obis_id", sa.String(length=64), unique=True, nullable=True),
        sa.Column("scientific_name", sa.String(length=160), nullable=False),
        sa.Column("common_name", sa.String(length=160), nullable=True),
        sa.Column("taxon_rank", sa.String(length=48), nullable=True),
        sa.Column("family", sa.String(length=96), nullable=True),
        sa.Column(
            "wpp_code",
            sa.String(length=3),
            sa.ForeignKey("wpp_nri_zones.wpp_code", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "geom",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("depth_m", sa.Double(), nullable=True),
        sa.Column("event_date_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("individual_count", sa.Integer(), nullable=True),
        sa.Column("habitat_note", sa.Text(), nullable=True),
        sa.Column("dataset_name", sa.Text(), nullable=True),
        sa.Column("attribution", sa.Text(), nullable=False),
        sa.Column("license", sa.String(length=128), nullable=True),
        sa.Column(
            "ingested_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "individual_count IS NULL OR individual_count >= 0",
            name="ck_species_occurrences_individual_count",
        ),
    )
    op.create_index(
        "idx_species_occurrences_geom_gist",
        "species_occurrences",
        ["geom"],
        unique=False,
        postgresql_using="gist",
    )
    op.create_index(
        "idx_species_occurrences_wpp",
        "species_occurrences",
        ["wpp_code"],
        unique=False,
    )
    op.create_index(
        "idx_species_occurrences_scientific_name",
        "species_occurrences",
        ["scientific_name"],
        unique=False,
    )
    op.create_index(
        "idx_species_occurrences_event_date",
        "species_occurrences",
        [sa.text("event_date_utc DESC")],
        unique=False,
    )

    # 5. External Data Provider ETL Sync Logs & Health Telemetry
    op.create_table(
        "source_sync_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_key", sa.String(length=32), nullable=False),
        sa.Column("dataset_type", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "records_ingested",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "started_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("finished_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "source_key IN ('noaa_erddap','obis','copernicus_marine','kkp_pdpi','gfw')",
            name="ck_source_sync_logs_source_key",
        ),
        sa.CheckConstraint(
            "status IN ('success', 'partial', 'failed', 'skipped')",
            name="ck_source_sync_logs_status",
        ),
        sa.CheckConstraint("records_ingested >= 0", name="ck_source_sync_logs_records_ingested"),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_source_sync_logs_duration_ms",
        ),
    )
    op.create_index(
        "idx_source_sync_logs_source_started",
        "source_sync_logs",
        ["source_key", sa.text("started_at_utc DESC")],
        unique=False,
    )


def downgrade() -> None:
    """Drop all spatial/telemetry tables and indexes in reverse dependency order."""
    op.drop_index("idx_source_sync_logs_source_started", table_name="source_sync_logs")
    op.drop_table("source_sync_logs")

    op.drop_index("idx_species_occurrences_event_date", table_name="species_occurrences")
    op.drop_index("idx_species_occurrences_scientific_name", table_name="species_occurrences")
    op.drop_index("idx_species_occurrences_wpp", table_name="species_occurrences")
    op.drop_index("idx_species_occurrences_geom_gist", table_name="species_occurrences")
    op.drop_table("species_occurrences")

    op.drop_index("idx_tile_cache_lru", table_name="tile_cache_index")
    op.drop_index("idx_tile_cache_layer_date", table_name="tile_cache_index")
    op.drop_table("tile_cache_index")

    op.drop_index("idx_raster_datasets_layer_date", table_name="raster_datasets")
    op.drop_index("idx_raster_datasets_bounds_gist", table_name="raster_datasets")
    op.drop_table("raster_datasets")

    op.drop_index("idx_wpp_nri_zones_centroid_gist", table_name="wpp_nri_zones")
    op.drop_index("idx_wpp_nri_zones_geom_gist", table_name="wpp_nri_zones")
    op.drop_table("wpp_nri_zones")
