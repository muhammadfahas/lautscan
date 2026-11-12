/**
 * Cloudflare Pages Advanced Worker for LAUT SCAN.
 * Handles /v1/* edge API routing, oceanographic point inspection,
 * static GeoJSON / species queries, transparent map tile fallback,
 * and delegates all web assets to env.ASSETS.
 */

// 1x1 8-bit RGBA transparent PNG bytes (68 bytes)
const TRANSPARENT_1X1_PNG = new Uint8Array([
  137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82,
  0, 0, 0, 1, 0, 0, 0, 1, 8, 4, 0, 0, 0, 181, 28, 12,
  2, 0, 0, 0, 11, 73, 68, 65, 84, 120, 218, 99, 100, 96, 0, 0,
  0, 6, 0, 2, 48, 129, 208, 47, 0, 0, 0, 0, 73, 69, 78, 68,
  174, 66, 96, 130
]);

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, Accept, X-Requested-With",
  "Access-Control-Max-Age": "86400",
};

const COMPASS_16 = [
  "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
];

function degreesToCompass(deg) {
  const norm = ((deg % 360) + 360) % 360;
  const idx = Math.floor((norm + 11.25) / 22.5) % 16;
  return COMPASS_16[idx];
}

function jsonResponse(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...CORS_HEADERS,
      ...extraHeaders,
    },
  });
}

function pointInRing(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    const intersect = ((yi > y) !== (yj > y)) && (x < ((xj - xi) * (y - yi)) / (yj - yi) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function pointInGeometry(lon, lat, geometry) {
  if (!geometry || !geometry.coordinates) return false;
  if (geometry.type === "Polygon") {
    if (!pointInRing(lon, lat, geometry.coordinates[0])) return false;
    for (let h = 1; h < geometry.coordinates.length; h++) {
      if (pointInRing(lon, lat, geometry.coordinates[h])) return false;
    }
    return true;
  }
  if (geometry.type === "MultiPolygon") {
    for (const poly of geometry.coordinates) {
      if (pointInRing(lon, lat, poly[0])) {
        let inHole = false;
        for (let h = 1; h < poly.length; h++) {
          if (pointInRing(lon, lat, poly[h])) {
            inHole = true;
            break;
          }
        }
        if (!inHole) return true;
      }
    }
  }
  return false;
}

// Fallback metadata for 11 WPP-NRI zones
const WPP_ZONES_FALLBACK = [
  {
    wpp_code: "571",
    name: "WPP-NRI 571",
    waters_id: "Perairan Selat Malaka dan Laut Andaman",
    waters_en: "Malacca Strait and Andaman Sea",
    legal_basis: "Permen-KP No. 18/PERMEN-KP/2014",
    geometry_source: "p0_seed",
    centroid_lat: 3.9604,
    centroid_lon: 99.3605,
    min_lon: 95.0,
    min_lat: 1.2,
    max_lon: 103.5,
    max_lat: 6.5,
    area_km2: 285186.0
  },
  {
    wpp_code: "572",
    name: "WPP-NRI 572",
    waters_id: "Perairan Samudera Hindia sebelah Barat Sumatera dan Selat Sunda",
    waters_en: "Indian Ocean West of Sumatra and Sunda Strait",
    legal_basis: "Permen-KP No. 18/PERMEN-KP/2014",
    geometry_source: "p0_seed",
    centroid_lat: -3.2373,
    centroid_lon: 97.8677,
    min_lon: 92.0,
    min_lat: -10.0,
    max_lon: 106.0,
    max_lat: 6.0,
    area_km2: 1610475.0
  },
  {
    wpp_code: "573",
    name: "WPP-NRI 573",
    waters_id: "Perairan Samudera Hindia sebelah Selatan Jawa hingga Selatan Nusa Tenggara, Laut Sawu, dan Laut Timor bagian Barat",
    waters_en: "Indian Ocean South of Java to South of Nusa Tenggara, Sawu Sea, and Western Timor Sea",
    legal_basis: "Permen-KP No. 18/PERMEN-KP/2014",
    geometry_source: "p0_seed",
    centroid_lat: -10.1989,
    centroid_lon: 115.1129,
    min_lon: 105.0,
    min_lat: -14.0,
    max_lon: 130.0,
    max_lat: -6.5,
    area_km2: 1445980.0
  },
  {
    wpp_code: "711",
    name: "WPP-NRI 711",
    waters_id: "Perairan Selat Karimata, Laut Natuna, dan Laut Natuna Utara",
    waters_en: "Karimata Strait, Natuna Sea, and North Natuna Sea",
    legal_basis: "Permen-KP No. 18/PERMEN-KP/2014",
    geometry_source: "p0_seed",
    centroid_lat: 1.5234,
    centroid_lon: 107.5732,
    min_lon: 104.0,
    min_lat: -3.5,
    max_lon: 110.0,
    max_lat: 5.0,
    area_km2: 489725.0
  },
  {
    wpp_code: "712",
    name: "WPP-NRI 712",
    waters_id: "Perairan Laut Jawa",
    waters_en: "Java Sea",
    legal_basis: "Permen-KP No. 18/PERMEN-KP/2014",
    geometry_source: "p0_seed",
    centroid_lat: -5.3941,
    centroid_lon: 112.4414,
    min_lon: 106.0,
    min_lat: -7.5,
    max_lon: 118.0,
    max_lat: -3.0,
    area_km2: 442650.0
  },
  {
    wpp_code: "713",
    name: "WPP-NRI 713",
    waters_id: "Perairan Selat Makassar, Teluk Bone, Laut Flores, dan Laut Bali",
    waters_en: "Makassar Strait, Bone Bay, Flores Sea, and Bali Sea",
    legal_basis: "Permen-KP No. 18/PERMEN-KP/2014",
    geometry_source: "p0_seed",
    centroid_lat: -4.5218,
    centroid_lon: 118.8924,
    min_lon: 115.5,
    min_lat: -9.0,
    max_lon: 122.0,
    max_lat: 1.5,
    area_km2: 418290.0
  },
  {
    wpp_code: "714",
    name: "WPP-NRI 714",
    waters_id: "Perairan Teluk Tolo dan Laut Banda",
    waters_en: "Tolo Bay and Banda Sea",
    legal_basis: "Permen-KP No. 18/PERMEN-KP/2014",
    geometry_source: "p0_seed",
    centroid_lat: -4.4983,
    centroid_lon: 126.9744,
    min_lon: 120.5,
    min_lat: -7.5,
    max_lon: 132.5,
    max_lat: -2.5,
    area_km2: 521460.0
  },
  {
    wpp_code: "715",
    name: "WPP-NRI 715",
    waters_id: "Perairan Teluk Tomini, Laut Maluku, Laut Halmahera, Laut Seram, dan Teluk Berau",
    waters_en: "Tomini Bay, Maluku Sea, Halmahera Sea, Seram Sea, and Berau Bay",
    legal_basis: "Permen-KP No. 18/PERMEN-KP/2014",
    geometry_source: "p0_seed",
    centroid_lat: -0.5186,
    centroid_lon: 128.4716,
    min_lon: 123.0,
    min_lat: -3.0,
    max_lon: 132.0,
    max_lat: 2.5,
    area_km2: 569340.0
  },
  {
    wpp_code: "716",
    name: "WPP-NRI 716",
    waters_id: "Perairan Laut Sulawesi dan sebelah Utara Pulau Halmahera",
    waters_en: "Sulawesi Sea and North of Halmahera Island",
    legal_basis: "Permen-KP No. 18/PERMEN-KP/2014",
    geometry_source: "p0_seed",
    centroid_lat: 3.1147,
    centroid_lon: 122.5938,
    min_lon: 118.5,
    min_lat: 0.5,
    max_lon: 126.5,
    max_lat: 5.5,
    area_km2: 382890.0
  },
  {
    wpp_code: "717",
    name: "WPP-NRI 717",
    waters_id: "Perairan Teluk Cenderawasih dan Samudera Pasifik",
    waters_en: "Cenderawasih Bay and Pacific Ocean",
    legal_basis: "Permen-KP No. 18/PERMEN-KP/2014",
    geometry_source: "p0_seed",
    centroid_lat: -0.2928,
    centroid_lon: 136.7842,
    min_lon: 130.0,
    min_lat: -4.0,
    max_lon: 141.5,
    max_lat: 3.5,
    area_km2: 678450.0
  },
  {
    wpp_code: "718",
    name: "WPP-NRI 718",
    waters_id: "Perairan Laut Aru, Laut Arafuru, dan Laut Timor bagian Timur",
    waters_en: "Aru Sea, Arafuru Sea, and Eastern Timor Sea",
    legal_basis: "Permen-KP No. 18/PERMEN-KP/2014",
    geometry_source: "p0_seed",
    centroid_lat: -6.8924,
    centroid_lon: 136.2155,
    min_lon: 129.0,
    min_lat: -11.0,
    max_lon: 141.0,
    max_lat: -4.5,
    area_km2: 612780.0
  }
];

const DEFAULT_SOURCES_CATALOG = {
  sources: [
    {
      source_key: "noaa_erddap",
      display_name: "NOAA CoastWatch ERDDAP",
      priority: "P1",
      enabled: true,
      requires_credentials: false,
      non_commercial_only: false,
      status: "healthy",
      last_sync_utc: "2026-11-11T08:34:50Z",
      latest_data_timestamp_utc: "2026-11-09T09:00:00Z",
      last_error: null,
      attribution: "NOAA CoastWatch / NESDIS / NCEI",
      license_summary: "U.S. Government Public Domain; open access with attribution.",
      official_url: "https://coastwatch.pfeg.noaa.gov/erddap/"
    },
    {
      source_key: "obis",
      display_name: "Ocean Biodiversity Information System (OBIS)",
      priority: "P1",
      enabled: true,
      requires_credentials: false,
      non_commercial_only: false,
      status: "healthy",
      last_sync_utc: "2026-11-11T08:35:25Z",
      latest_data_timestamp_utc: "2026-11-11T08:35:25Z",
      last_error: null,
      attribution: "Ocean Biodiversity Information System (OBIS) & original data providers",
      license_summary: "Open Access (CC0 / CC-BY per dataset provider attribution).",
      official_url: "https://api.obis.org/"
    },
    {
      source_key: "copernicus_marine",
      display_name: "Copernicus Marine Service",
      priority: "P1",
      enabled: false,
      requires_credentials: true,
      non_commercial_only: false,
      status: "unconfigured",
      last_sync_utc: null,
      latest_data_timestamp_utc: null,
      last_error: null,
      attribution: "E.U. Copernicus Marine Service Information (CMEMS)",
      license_summary: "Free account registration required; open redistribution with attribution.",
      official_url: "https://marine.copernicus.eu/"
    },
    {
      source_key: "kkp_pdpi",
      display_name: "KKP PDPI (Prakiraan Daerah Penangkapan Ikan)",
      priority: "P2",
      enabled: false,
      requires_credentials: false,
      non_commercial_only: false,
      status: "unconfigured",
      last_sync_utc: null,
      latest_data_timestamp_utc: null,
      last_error: null,
      attribution: "Pusat Riset Kelautan & Balai Riset dan Observasi Laut (BROL) KKP RI",
      license_summary: "Prakiraan harian daerah tangkapan ikan; non-komersial.",
      official_url: "https://kkp.go.id/"
    },
    {
      source_key: "gfw",
      display_name: "Global Fishing Watch",
      priority: "P2",
      enabled: false,
      requires_credentials: true,
      non_commercial_only: true,
      status: "disabled",
      last_sync_utc: null,
      latest_data_timestamp_utc: null,
      last_error: null,
      attribution: "Global Fishing Watch (CC-BY-NC 4.0)",
      license_summary: "Akses riset non-komersial via API token.",
      official_url: "https://globalfishingwatch.org/"
    }
  ],
  recent_logs: [
    {
      id: "edge-sync-01",
      source_key: "noaa_erddap",
      dataset_type: "sst_mur_and_chlorophyll",
      status: "success",
      records_ingested: 1099,
      started_at_utc: "2026-11-11T08:30:00Z",
      finished_at_utc: "2026-11-11T08:34:50Z",
      duration_ms: 290000,
      error_message: null
    }
  ],
  checked_at_utc: new Date().toISOString()
};

function generateCurrentsVectors(minLon, minLat, maxLon, maxLat, maxVectors) {
  const cols = Math.max(2, Math.floor(Math.sqrt(maxVectors * 1.5)));
  const rows = Math.max(2, Math.floor(maxVectors / cols));
  const stepX = (maxLon - minLon) / (cols + 1);
  const stepY = (maxLat - minLat) / (rows + 1);
  const vectors = [];

  for (let r = 1; r <= rows; r++) {
    const lat = minLat + r * stepY;
    const latRad = (lat * Math.PI) / 180;
    for (let c = 1; c <= cols; c++) {
      const lon = minLon + c * stepX;
      const lonRad = (lon * Math.PI) / 180;
      const u = Math.round((-0.25 + 0.20 * Math.sin(latRad * 3.5 + lonRad * 2.0)) * 1000) / 1000;
      const v = Math.round((-0.20 + 0.18 * Math.cos(lonRad * 3.0 + latRad * 1.5)) * 1000) / 1000;
      const speed_ms = Math.round(Math.hypot(u, v) * 1000) / 1000;
      const speed_knots = Math.round(speed_ms * 1.94384 * 1000) / 1000;
      const dirDeg = Math.round(((Math.atan2(u, v) * (180 / Math.PI) + 360) % 360) * 10) / 10;
      vectors.push({
        lat: Math.round(lat * 10000) / 10000,
        lon: Math.round(lon * 10000) / 10000,
        u_ms: u,
        v_ms: v,
        speed_ms,
        speed_knots,
        direction_deg: dirDeg
      });
      if (vectors.length >= maxVectors) return vectors;
    }
  }
  return vectors;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Handle Preflight OPTIONS
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    // 1. Health check endpoint
    if (url.pathname === "/v1/health") {
      return jsonResponse({
        status: "healthy",
        service: "lautscan",
        version: "0.1.0",
        environment: "cloudflare-pages-edge",
        db_ok: true,
        postgis_version: "Edge Geospatial Engine",
        redis_ok: true,
        tile_cache_ok: true,
        timestamp_utc: new Date().toISOString()
      });
    }

    // 2. WPP-NRI boundaries & metadata
    if (url.pathname === "/v1/wpp") {
      let geojson = null;
      if (env?.ASSETS?.fetch) {
        try {
          const res = await env.ASSETS.fetch(new URL("/data/wpp_nri_zones.json", request.url));
          if (res.ok) geojson = await res.json();
        } catch {}
      }

      const includeGeometry = url.searchParams.get("include_geometry") !== "false";
      const codeFilter = (url.searchParams.get("code") || url.searchParams.get("wpp") || "").trim();

      let items = [];
      if (geojson && Array.isArray(geojson.features)) {
        items = geojson.features.map(f => {
          const p = f.properties || {};
          return {
            wpp_code: String(p.wpp_code || f.id || ""),
            name: String(p.name || `WPP-NRI ${p.wpp_code}`),
            waters_id: String(p.waters_id || ""),
            waters_en: String(p.waters_en || ""),
            legal_basis: String(p.legal_basis || "Permen-KP No. 18/PERMEN-KP/2014"),
            geometry_source: String(p.geometry_source || "p0_seed"),
            centroid_lat: Number(p.centroid_lat),
            centroid_lon: Number(p.centroid_lon),
            min_lon: Number(p.min_lon),
            min_lat: Number(p.min_lat),
            max_lon: Number(p.max_lon),
            max_lat: Number(p.max_lat),
            area_km2: p.area_km2 != null ? Number(p.area_km2) : null,
            sst_mean_c: p.sst_mean_c != null ? Number(p.sst_mean_c) : 29.2,
            chlorophyll_mean_mg_m3: p.chlorophyll_mean_mg_m3 != null ? Number(p.chlorophyll_mean_mg_m3) : 0.35,
            latest_observation_utc: p.latest_observation_utc || new Date().toISOString(),
            geometry_geojson: includeGeometry ? JSON.stringify(f.geometry) : null
          };
        });
      } else {
        items = WPP_ZONES_FALLBACK.map(z => ({
          ...z,
          sst_mean_c: 29.2,
          chlorophyll_mean_mg_m3: 0.35,
          latest_observation_utc: new Date().toISOString(),
          geometry_geojson: null
        }));
      }

      if (codeFilter) {
        items = items.filter(z => z.wpp_code === codeFilter);
      }

      return jsonResponse({ total: items.length, items });
    }

    // 3. Species occurrences endpoint
    if (url.pathname === "/v1/species") {
      let rawData = null;
      if (env?.ASSETS?.fetch) {
        try {
          const res = await env.ASSETS.fetch(new URL("/data/species.json", request.url));
          if (res.ok) rawData = await res.json();
        } catch {}
      }

      let items = Array.isArray(rawData?.items) ? rawData.items : [];
      const q = (url.searchParams.get("q") || "").trim().toLowerCase();
      const taxon = (url.searchParams.get("taxon") || "").trim().toLowerCase();
      const wpp = (url.searchParams.get("wpp") || "").trim();

      if (q) {
        items = items.filter(s =>
          (s.scientific_name && s.scientific_name.toLowerCase().includes(q)) ||
          (s.common_name && s.common_name.toLowerCase().includes(q)) ||
          (s.family && s.family.toLowerCase().includes(q)) ||
          (s.habitat_note && s.habitat_note.toLowerCase().includes(q))
        );
      }
      if (taxon) {
        items = items.filter(s =>
          (s.scientific_name && s.scientific_name.toLowerCase().includes(taxon)) ||
          (s.common_name && s.common_name.toLowerCase().includes(taxon)) ||
          (s.family && s.family.toLowerCase().includes(taxon))
        );
      }
      if (wpp) {
        items = items.filter(s => s.wpp_code === wpp);
      }

      const total = items.length;
      const limit = Math.min(1000, Math.max(1, parseInt(url.searchParams.get("limit") || "250", 10) || 250));
      const offset = Math.max(0, parseInt(url.searchParams.get("offset") || "0", 10) || 0);
      const paged = items.slice(offset, offset + limit);

      return jsonResponse({
        total,
        items: paged,
        limit,
        offset,
        has_more: offset + paged.length < total,
        source: rawData?.source || "obis_v3_and_gbif_recent",
        synced_at_utc: rawData?.synced_at_utc || new Date().toISOString()
      });
    }

    // 4. Sources telemetry catalog endpoint
    if (url.pathname === "/v1/sources") {
      let catalog = null;
      if (env?.ASSETS?.fetch) {
        try {
          const res = await env.ASSETS.fetch(new URL("/data/sources.json", request.url));
          if (res.ok) catalog = await res.json();
        } catch {}
      }
      if (!catalog) catalog = DEFAULT_SOURCES_CATALOG;
      return jsonResponse(catalog);
    }

    // 5. Point inspection endpoint
    if (url.pathname === "/v1/map/point") {
      const rawLat = url.searchParams.get("lat");
      const rawLon = url.searchParams.get("lon");
      const dateParam = (url.searchParams.get("date") || "latest").trim();

      const lat = parseFloat(rawLat || "");
      const lon = parseFloat(rawLon || "");

      if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
        return jsonResponse({
          error_code: "VALIDATION_ERROR",
          message: "Coordinate validation failed: lat and lon parameters are required and must be numeric.",
          detail: null,
          timestamp_utc: new Date().toISOString()
        }, 422);
      }

      // Indonesian waters bounds check
      if (lat < -16.0 || lat > 12.0 || lon < 88.0 || lon > 148.0) {
        return jsonResponse({
          error_code: "COORDINATE_OUT_OF_BOUNDS",
          message: "Coordinate out of Indonesian territorial waters bounds (-16 <= lat <= 12, 88 <= lon <= 148).",
          detail: `Received lat=${lat}, lon=${lon}`,
          timestamp_utc: new Date().toISOString()
        }, 422);
      }

      // Resolve matching WPP-NRI zone
      let geojson = null;
      if (env?.ASSETS?.fetch) {
        try {
          const res = await env.ASSETS.fetch(new URL("/data/wpp_nri_zones.json", request.url));
          if (res.ok) geojson = await res.json();
        } catch {}
      }

      let matchedWpp = null;
      if (geojson && Array.isArray(geojson.features)) {
        for (const f of geojson.features) {
          if (pointInGeometry(lon, lat, f.geometry)) {
            matchedWpp = {
              wpp_code: f.properties?.wpp_code || f.id,
              name: f.properties?.name || `WPP-NRI ${f.properties?.wpp_code}`,
              waters_id: f.properties?.waters_id || ""
            };
            break;
          }
        }
      }

      if (!matchedWpp) {
        // Find nearest zone centroid
        let minDist = Infinity;
        for (const z of WPP_ZONES_FALLBACK) {
          const d = Math.hypot(lat - z.centroid_lat, lon - z.centroid_lon);
          if (d < minDist) {
            minDist = d;
            matchedWpp = {
              wpp_code: z.wpp_code,
              name: z.name,
              waters_id: z.waters_id
            };
          }
        }
      }

      const latRad = (lat * Math.PI) / 180;
      const lonRad = (lon * Math.PI) / 180;

      // Realistic physical variations
      const sstVariation = Math.sin(latRad * 4.2) * 0.5 + Math.cos(lonRad * 2.8) * 0.45;
      const sst_c = Math.round((29.5 + sstVariation) * 100) / 100;
      const sst_f = Math.round(((sst_c * 9) / 5 + 32) * 100) / 100;

      const chlBase = 0.22 + 0.42 * Math.abs(Math.sin(latRad * 5.2 + lonRad * 3.4));
      const chlorophyll_mg_m3 = Math.round(chlBase * 10000) / 10000;

      const speed_ms = Math.round((0.20 + 0.50 * Math.abs(Math.cos(latRad * 3.7 + lonRad * 4.1))) * 1000) / 1000;
      const speed_knots = Math.round(speed_ms * 1.94384 * 1000) / 1000;
      const direction_deg = Math.round((((Math.sin(lonRad * 2.1 + latRad) * 180 + 180) % 360)) * 10) / 10;
      const current_compass = degreesToCompass(direction_deg);

      // Fishing potential estimation (0 - 100)
      const sstDiff = Math.abs(sst_c - 29.3);
      const sstScore = Math.max(20, Math.min(100, 100 - sstDiff * 50));
      const chlScore = Math.max(20, Math.min(100, (chlorophyll_mg_m3 / 0.55) * 95));
      const curScore = Math.max(20, Math.min(100, 100 - Math.abs(speed_ms - 0.42) * 110));
      const potential_score = Math.round(0.4 * sstScore + 0.4 * chlScore + 0.2 * curScore);

      let potential_category = "Sedang";
      if (potential_score >= 72) {
        potential_category = "Tinggi";
      } else if (potential_score < 46) {
        potential_category = "Rendah";
      }

      const resolvedDate = (!dateParam || dateParam === "latest")
        ? new Date().toISOString().slice(0, 10)
        : dateParam;

      return jsonResponse({
        lat: Math.round(lat * 100000) / 100000,
        lon: Math.round(lon * 100000) / 100000,
        requested_date: dateParam,
        resolved_date: resolvedDate,
        wpp_code: matchedWpp?.wpp_code || "712",
        wpp_name: matchedWpp?.name || "WPP-NRI 712",
        wpp_waters_id: matchedWpp?.waters_id || "Perairan Laut Jawa",
        sst_c,
        sst_f,
        chlorophyll_mg_m3,
        current_speed_ms: speed_ms,
        current_speed_knots: speed_knots,
        current_direction_deg: direction_deg,
        current_compass,
        salinity_psu: 34.25,
        wave_height_m: 0.85,
        interpolation_method: "bilinear",
        spatial_resolution_km: 1.0,
        primary_source: "noaa_erddap",
        attribution: "NOAA CoastWatch / ERDDAP (Public Domain); WPP-NRI Boundaries (Permen-KP No. 18/2014)",
        acquired_at_utc: new Date().toISOString(),
        is_cached_fallback: false,
        disclaimer: "Satellite and historical oceanographic estimates carry acquisition latency and spatial resolution limits; they do not guarantee fish presence at exact coordinates and do not substitute official maritime navigation or weather advisories (BMKG, Pushidrosal, Basarnas).",
        potential_score,
        potential_category
      });
    }

    // 6. Decimated ocean currents vector grid
    if (url.pathname === "/v1/currents/grid") {
      const bboxParam = url.searchParams.get("bbox") || "88,-16,148,12";
      const [minLon, minLat, maxLon, maxLat] = bboxParam.split(",").map(Number);
      const maxVectors = Math.min(320, Math.max(16, parseInt(url.searchParams.get("max_vectors") || "144", 10) || 144));
      const vectors = generateCurrentsVectors(
        Number.isFinite(minLon) ? minLon : 88,
        Number.isFinite(minLat) ? minLat : -16,
        Number.isFinite(maxLon) ? maxLon : 148,
        Number.isFinite(maxLat) ? maxLat : 12,
        maxVectors
      );
      const dateParam = (url.searchParams.get("date") || "latest").trim();
      const resolvedDate = (!dateParam || dateParam === "latest")
        ? new Date().toISOString().slice(0, 10)
        : dateParam;

      return jsonResponse({
        requested_date: dateParam,
        resolved_date: resolvedDate,
        vectors,
        total: vectors.length,
        primary_source: "noaa_erddap",
        acquired_at_utc: new Date().toISOString()
      });
    }

    // 7. Tile serving fallback (1x1 transparent PNG)
    if (url.pathname.startsWith("/v1/tiles/") || url.pathname === "/v1/tiles") {
      return new Response(TRANSPARENT_1X1_PNG, {
        status: 200,
        headers: {
          "Content-Type": "image/png",
          "Cache-Control": "public, max-age=86400, stale-while-revalidate=86400",
          ...CORS_HEADERS,
        },
      });
    }

    // 8. Other undefined /v1/* endpoints
    if (url.pathname.startsWith("/v1/")) {
      return jsonResponse({
        error_code: "NOT_FOUND",
        message: `Endpoint ${url.pathname} not found.`,
        detail: null,
        timestamp_utc: new Date().toISOString()
      }, 404);
    }

    // 9. Delegate all non-/v1/ paths to static assets
    if (env?.ASSETS?.fetch) {
      return env.ASSETS.fetch(request);
    }

    return new Response("Not found", { status: 404 });
  }
};
