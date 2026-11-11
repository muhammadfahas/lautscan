FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

# System libraries for PostgreSQL/asyncpg, GEOS/GDAL spatial operations, and NetCDF4/HDF5 rasters
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    libgeos-dev \
    libgdal-dev \
    libnetcdf-dev \
    libhdf5-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first for better Docker layer caching
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install --no-cache-dir .

# Prepare default tile cache directory and copy backend source
RUN mkdir -p /data/tiles
COPY . .

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
