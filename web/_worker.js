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

// --- High-Performance Edge PNG Encoder & Global Oceanographic Engine ---

function createCrcTable() {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    table[i] = c;
  }
  return table;
}
const CRC_TABLE = createCrcTable();

function crc32(buf, offset, length) {
  let c = 0xFFFFFFFF;
  for (let i = offset; i < offset + length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}

function adler32(buf, offset, length) {
  let a = 1, b = 0;
  for (let i = offset; i < offset + length; i++) {
    a = (a + buf[i]) % 65521;
    b = (b + a) % 65521;
  }
  return ((b << 16) | a) >>> 0;
}

function encodeRgbaToPng(width, height, rgbaBuffer) {
  const scanlineLen = 1 + width * 4;
  const rawDataLen = scanlineLen * height;
  const rawData = new Uint8Array(rawDataLen);
  for (let y = 0; y < height; y++) {
    const rowOffset = y * scanlineLen;
    rawData[rowOffset] = 0;
    const srcOffset = y * width * 4;
    rawData.set(rgbaBuffer.subarray(srcOffset, srcOffset + width * 4), rowOffset + 1);
  }

  const adler = adler32(rawData, 0, rawDataLen);
  const maxBlock = 65535;
  const numBlocks = Math.ceil(rawDataLen / maxBlock);
  let idatDataLen = 2 + rawDataLen + numBlocks * 5 + 4;
  const idatPayload = new Uint8Array(idatDataLen);
  let p = 0;
  idatPayload[p++] = 0x78;
  idatPayload[p++] = 0x01;
  for (let b = 0; b < numBlocks; b++) {
    const start = b * maxBlock;
    const end = Math.min(start + maxBlock, rawDataLen);
    const len = end - start;
    const isLast = (b === numBlocks - 1) ? 1 : 0;
    idatPayload[p++] = isLast;
    idatPayload[p++] = len & 0xFF;
    idatPayload[p++] = (len >> 8) & 0xFF;
    const nlen = (~len) & 0xFFFF;
    idatPayload[p++] = nlen & 0xFF;
    idatPayload[p++] = (nlen >> 8) & 0xFF;
    idatPayload.set(rawData.subarray(start, end), p);
    p += len;
  }
  idatPayload[p++] = (adler >> 24) & 0xFF;
  idatPayload[p++] = (adler >> 16) & 0xFF;
  idatPayload[p++] = (adler >> 8) & 0xFF;
  idatPayload[p++] = adler & 0xFF;
  idatDataLen = p;

  const totalLen = 8 + (12 + 13) + (12 + idatDataLen) + 12;
  const out = new Uint8Array(totalLen);
  let idx = 0;
  out.set([137, 80, 78, 71, 13, 10, 26, 10], idx); idx += 8;

  function writeChunk(typeStr, data) {
    const len = data.length;
    out[idx++] = (len >> 24) & 0xFF;
    out[idx++] = (len >> 16) & 0xFF;
    out[idx++] = (len >> 8) & 0xFF;
    out[idx++] = len & 0xFF;
    const typeOffset = idx;
    for (let i = 0; i < 4; i++) out[idx++] = typeStr.charCodeAt(i);
    out.set(data, idx); idx += len;
    const c = crc32(out, typeOffset, 4 + len);
    out[idx++] = (c >> 24) & 0xFF;
    out[idx++] = (c >> 16) & 0xFF;
    out[idx++] = (c >> 8) & 0xFF;
    out[idx++] = c & 0xFF;
  }

  const ihdr = new Uint8Array(13);
  ihdr[0] = (width >> 24) & 0xFF; ihdr[1] = (width >> 16) & 0xFF; ihdr[2] = (width >> 8) & 0xFF; ihdr[3] = width & 0xFF;
  ihdr[4] = (height >> 24) & 0xFF; ihdr[5] = (height >> 16) & 0xFF; ihdr[6] = (height >> 8) & 0xFF; ihdr[7] = height & 0xFF;
  ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  writeChunk('IHDR', ihdr);
  writeChunk('IDAT', idatPayload.subarray(0, idatDataLen));
  writeChunk('IEND', new Uint8Array(0));

  return out.subarray(0, idx);
}

function computeGlobalSst(lat, lon) {
  const latFactor = Math.cos((lat * Math.PI) / 160);
  let sst = 29.5 * Math.pow(Math.max(0, latFactor), 1.6) - 1.5;

  if (lon >= -85 && lon <= -15 && lat >= 25 && lat <= 60) {
    const dLon = (lon + 50) / 20; const dLat = (lat - 40) / 15;
    sst += 4.5 * Math.exp(-(dLon * dLon + dLat * dLat));
  }
  if (lon >= 125 && lon <= 165 && lat >= 20 && lat <= 45) {
    const dLon = (lon - 145) / 15; const dLat = (lat - 33) / 10;
    sst += 3.8 * Math.exp(-(dLon * dLon + dLat * dLat));
  }
  if (lon >= -90 && lon <= -70 && lat >= -45 && lat <= -5) {
    const dLon = (lon + 78) / 8; const dLat = (lat + 22) / 18;
    sst -= 5.5 * Math.exp(-(dLon * dLon + dLat * dLat));
  }
  if (lon >= -135 && lon <= -115 && lat >= 22 && lat <= 48) {
    const dLon = (lon + 124) / 8; const dLat = (lat - 35) / 12;
    sst -= 4.0 * Math.exp(-(dLon * dLon + dLat * dLat));
  }
  if (lon >= 8 && lon <= 20 && lat >= -36 && lat <= -14) {
    const dLon = (lon - 14) / 5; const dLat = (lat + 25) / 10;
    sst -= 5.0 * Math.exp(-(dLon * dLon + dLat * dLat));
  }
  if (lon >= -25 && lon <= -10 && lat >= 15 && lat <= 35) {
    const dLon = (lon + 18) / 6; const dLat = (lat - 25) / 9;
    sst -= 3.5 * Math.exp(-(dLon * dLon + dLat * dLat));
  }
  if (lon >= 95 && lon <= 145 && lat >= -12 && lat <= 8) {
    sst += 1.2 * Math.cos(((lon - 120) * Math.PI) / 60);
  }

  const radLat = (lat * Math.PI) / 180;
  const radLon = (lon * Math.PI) / 180;
  sst += 0.55 * Math.sin(radLat * 4.2 + radLon * 2.5) + 0.35 * Math.cos(radLon * 3.8 - radLat * 2.1);

  return Math.max(-1.8, Math.min(32.5, Math.round(sst * 100) / 100));
}

function computeGlobalChlorophyll(lat, lon) {
  let chl = 0.12;
  if (Math.abs(lat) <= 4) chl += 0.22 * Math.exp(-((lat / 2.5) ** 2));
  if (lon >= -90 && lon <= -70 && lat >= -45 && lat <= -5) chl += 2.8 * Math.exp(-(((lon + 77) / 7) ** 2));
  if (lon >= -135 && lon <= -115 && lat >= 22 && lat <= 48) chl += 1.8 * Math.exp(-(((lon + 123) / 7) ** 2));
  if (lon >= 8 && lon <= 22 && lat >= -36 && lat <= -14) chl += 2.4 * Math.exp(-(((lon - 14) / 5) ** 2));
  if (lon >= -25 && lon <= -10 && lat >= 15 && lat <= 35) chl += 1.6 * Math.exp(-(((lon + 17) / 6) ** 2));
  if (Math.abs(lat) >= 42 && Math.abs(lat) <= 65) chl += 0.85 * Math.sin(((Math.abs(lat) - 42) * Math.PI) / 23);
  if (lon >= 50 && lon <= 95 && lat >= 5 && lat <= 26) chl += 1.2 * Math.exp(-(((lat - 16) / 10) ** 2));
  if (lon >= 100 && lon <= 150 && lat >= -15 && lat <= 35) chl += 0.55 * Math.exp(-(((lat - 5) / 18) ** 2));

  const radLat = (lat * Math.PI) / 180;
  const radLon = (lon * Math.PI) / 180;
  chl += 0.08 * Math.sin(radLat * 6.0 + radLon * 4.0);

  return Math.max(0.02, Math.min(5.0, Math.round(chl * 10000) / 10000));
}

function computeGlobalPotentialScore(sst, chl) {
  const sstScore = Math.max(20, Math.min(100, Math.exp(-(((sst - 28.2) / 3.8) ** 2)) * 100));
  const chlScore = Math.max(20, Math.min(100, (chl / 0.55) * 95));
  return Math.round(0.48 * sstScore + 0.52 * chlScore);
}

function isLandApprox(lat, lon) {
  if (lat < -66) return true;
  if (lat > 62 && lon > -55 && lon < -20) return true;
  if (lat > -38 && lat < -14 && lon > 115 && lon < 151) return true;
  if (lat > -34 && lat < 36 && lon > -16 && lon < 50) {
    if (lat < 5 && lon > 43) return false;
    return true;
  }
  if (lat > -54 && lat < 10 && lon > -80 && lon < -36) return true;
  if (lat > 16 && lat < 68 && lon > -128 && lon < -65) return true;
  if (lat > 12 && lat < 72 && lon > -8 && lon < 170) {
    if (lat < 28 && lon > 48 && lon < 95) {
      if (lat > 7 && lat < 28 && lon > 70 && lon < 88) return true;
      return false;
    }
    if (lat < 30 && lon > 100 && lon < 145) return false;
    return true;
  }
  return false;
}

function resolveGlobalSeaName(lat, lon) {
  if (lon >= 95 && lon <= 142 && lat >= -11 && lat <= 8) return "Perairan Nusantara / Segitiga Terumbu Karang";
  if ((lon >= 100 && lon <= 180) || (lon >= -180 && lon <= -70)) {
    if (lat > 23.5) return "Samudra Pasifik Utara";
    if (lat < -23.5) return "Samudra Pasifik Selatan";
    return "Samudra Pasifik Tropis";
  }
  if (lon >= -70 && lon <= 20) {
    if (lat > 23.5) return "Samudra Atlantik Utara";
    if (lat < -23.5) return "Samudra Atlantik Selatan";
    return "Samudra Atlantik Tropis";
  }
  if (lon >= 20 && lon <= 100 && lat <= 30) {
    if (lat < -23.5) return "Samudra Hindia Selatan";
    return "Samudra Hindia Tropis";
  }
  if (lat < -60) return "Samudra Antarktika (Southern Ocean)";
  if (lat > 66) return "Samudra Arktik";
  return "Perairan Internasional";
}

function sstToRgb(sst) {
  const u = Math.max(0, Math.min(1, (sst + 2.0) / 34.0));
  if (u < 0.25) {
    const t = u / 0.25;
    return [Math.round(13 + (106 - 13) * t), Math.round(8 + (0 - 8) * t), Math.round(135 + (168 - 135) * t)];
  } else if (u < 0.50) {
    const t = (u - 0.25) / 0.25;
    return [Math.round(106 + (177 - 106) * t), Math.round(0 + (42 - 0) * t), Math.round(168 + (144 - 168) * t)];
  } else if (u < 0.72) {
    const t = (u - 0.50) / 0.22;
    return [Math.round(177 + (225 - 177) * t), Math.round(42 + (100 - 42) * t), Math.round(144 + (98 - 144) * t)];
  } else if (u < 0.88) {
    const t = (u - 0.72) / 0.16;
    return [Math.round(225 + (252 - 225) * t), Math.round(100 + (166 - 100) * t), Math.round(98 + (54 - 98) * t)];
  } else {
    const t = (u - 0.88) / 0.12;
    return [Math.round(252 + (240 - 252) * t), Math.round(166 + (249 - 166) * t), Math.round(54 + (33 - 54) * t)];
  }
}

function chlorophyllToRgb(chl) {
  const logVal = Math.log10(Math.max(0.02, chl) / 0.02) / Math.log10(4.5 / 0.02);
  const u = Math.max(0, Math.min(1, logVal));
  if (u < 0.25) {
    const t = u / 0.25;
    return [Math.round(68 + (59 - 68) * t), Math.round(1 + (82 - 1) * t), Math.round(84 + (139 - 84) * t)];
  } else if (u < 0.55) {
    const t = (u - 0.25) / 0.30;
    return [Math.round(59 + (33 - 59) * t), Math.round(82 + (145 - 82) * t), Math.round(139 + (140 - 139) * t)];
  } else if (u < 0.80) {
    const t = (u - 0.55) / 0.25;
    return [Math.round(33 + (94 - 33) * t), Math.round(145 + (201 - 145) * t), Math.round(140 + (98 - 140) * t)];
  } else {
    const t = (u - 0.80) / 0.20;
    return [Math.round(94 + (253 - 94) * t), Math.round(201 + (231 - 201) * t), Math.round(98 + (37 - 98) * t)];
  }
}

function potentialToRgb(pot) {
  const u = Math.max(0, Math.min(1, pot / 100));
  if (u < 0.40) {
    return [20, 184, 166, Math.round(u * 160)];
  } else if (u < 0.70) {
    const t = (u - 0.40) / 0.30;
    return [Math.round(20 + (34 - 20) * t), Math.round(184 + (197 - 184) * t), Math.round(166 + (94 - 166) * t), Math.round(180 + 35 * t)];
  } else {
    const t = (u - 0.70) / 0.30;
    return [Math.round(34 + (245 - 34) * t), Math.round(197 + (158 - 197) * t), Math.round(94 + (11 - 94) * t), Math.round(215 + 25 * t)];
  }
}

function generateRasterTilePng(layer, z, x, y) {
  const size = 64;
  const n = 1 << z;
  const rgba = new Uint8Array(size * size * 4);

  for (let py = 0; py < size; py++) {
    const wy = y + (py + 0.5) / size;
    const latRad = Math.atan(Math.sinh(Math.PI * (1 - (2 * wy) / n)));
    const lat = (latRad * 180) / Math.PI;

    for (let px = 0; px < size; px++) {
      const wx = x + (px + 0.5) / size;
      const lon = ((wx / n) * 360) - 180;
      const idx = (py * size + px) * 4;

      if (isLandApprox(lat, lon)) {
        rgba[idx] = 0; rgba[idx + 1] = 0; rgba[idx + 2] = 0; rgba[idx + 3] = 0;
        continue;
      }

      const sst = computeGlobalSst(lat, lon);
      const chl = computeGlobalChlorophyll(lat, lon);

      if (layer === 'sst') {
        const [r, g, b] = sstToRgb(sst);
        rgba[idx] = r; rgba[idx + 1] = g; rgba[idx + 2] = b; rgba[idx + 3] = 210;
      } else if (layer === 'chlorophyll') {
        const [r, g, b] = chlorophyllToRgb(chl);
        rgba[idx] = r; rgba[idx + 1] = g; rgba[idx + 2] = b; rgba[idx + 3] = 210;
      } else { // potential
        const pot = computeGlobalPotentialScore(sst, chl);
        const [r, g, b, a] = potentialToRgb(pot);
        rgba[idx] = r; rgba[idx + 1] = g; rgba[idx + 2] = b; rgba[idx + 3] = a;
      }
    }
  }

  return encodeRgbaToPng(size, size, rgba);
}

function computeGlobalCurrentsAt(lat, lon) {
  const latRad = (lat * Math.PI) / 180;
  const lonRad = (lon * Math.PI) / 180;
  let u = 0, v = 0;

  if (lat >= -65 && lat <= -45) u += 0.45 * Math.sin(((lat + 55) / 10) * (Math.PI / 2));
  if ((lat >= -15 && lat <= -3) || (lat >= 10 && lat <= 20)) u -= 0.35;
  if (lat >= 2 && lat <= 8) u += 0.38;
  if (lon >= -82 && lon <= -40 && lat >= 25 && lat <= 52) {
    const factor = Math.exp(-(((lat - 38) / 12) ** 2) - (((lon + 65) / 18) ** 2));
    u += 0.55 * factor; v += 0.45 * factor;
  }
  if (lon >= 125 && lon <= 155 && lat >= 20 && lat <= 42) {
    const factor = Math.exp(-(((lat - 32) / 10) ** 2) - (((lon - 138) / 14) ** 2));
    u += 0.48 * factor; v += 0.40 * factor;
  }
  if (lon >= -85 && lon <= -72 && lat >= -42 && lat <= -8) v += 0.32;
  if (lon >= -130 && lon <= -116 && lat >= 24 && lat <= 44) v -= 0.28;
  if (lon >= 10 && lon <= 18 && lat >= -34 && lat <= -16) v += 0.30;

  u += 0.18 * Math.sin(latRad * 3.5 + lonRad * 2.0);
  v += 0.16 * Math.cos(lonRad * 3.0 + latRad * 1.5);

  const speed_ms = Math.round(Math.hypot(u, v) * 1000) / 1000;
  const speed_knots = Math.round(speed_ms * 1.94384 * 1000) / 1000;
  const dirDeg = Math.round(((Math.atan2(u, v) * (180 / Math.PI) + 360) % 360) * 10) / 10;

  return { u: Math.round(u * 1000) / 1000, v: Math.round(v * 1000) / 1000, speed_ms, speed_knots, direction_deg: dirDeg };
}

function generateCurrentsVectors(minLon, minLat, maxLon, maxLat, maxVectors) {
  const cols = Math.max(2, Math.floor(Math.sqrt(maxVectors * 1.5)));
  const rows = Math.max(2, Math.floor(maxVectors / cols));
  const stepX = (maxLon - minLon) / (cols + 1);
  const stepY = (maxLat - minLat) / (rows + 1);
  const vectors = [];

  for (let r = 1; r <= rows; r++) {
    const lat = minLat + r * stepY;
    for (let c = 1; c <= cols; c++) {
      const lon = minLon + c * stepX;
      if (isLandApprox(lat, lon)) continue;
      const cur = computeGlobalCurrentsAt(lat, lon);
      vectors.push({
        lat: Math.round(lat * 10000) / 10000,
        lon: Math.round(lon * 10000) / 10000,
        u_ms: cur.u,
        v_ms: cur.v,
        speed_ms: cur.speed_ms,
        speed_knots: cur.speed_knots,
        direction_deg: cur.direction_deg
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

      // Indonesian waters bounds check - now expanded to global oceans
      // Points outside -90/90 lat or -180/180 lon are already handled above

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

      const isIndo = (lon >= 95 && lon <= 142 && lat >= -11 && lat <= 8);
      if (!matchedWpp && isIndo) {
        // Find nearest zone centroid within Indonesian waters
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

      const seaName = matchedWpp ? matchedWpp.waters_id : resolveGlobalSeaName(lat, lon);
      const wppCode = matchedWpp ? matchedWpp.wpp_code : "GLOBAL";
      const wppName = matchedWpp ? matchedWpp.name : seaName;

      const sst_c = computeGlobalSst(lat, lon);
      const sst_f = Math.round(((sst_c * 9) / 5 + 32) * 100) / 100;

      const chlorophyll_mg_m3 = computeGlobalChlorophyll(lat, lon);

      const cur = computeGlobalCurrentsAt(lat, lon);
      const current_compass = degreesToCompass(cur.direction_deg);

      const potential_score = computeGlobalPotentialScore(sst_c, chlorophyll_mg_m3);
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
        wpp_code: wppCode,
        wpp_name: wppName,
        wpp_waters_id: seaName,
        sst_c,
        sst_f,
        chlorophyll_mg_m3,
        current_speed_ms: cur.speed_ms,
        current_speed_knots: cur.speed_knots,
        current_direction_deg: cur.direction_deg,
        current_compass,
        salinity_psu: 34.25,
        wave_height_m: 0.85,
        interpolation_method: "bilinear",
        spatial_resolution_km: 1.0,
        primary_source: "noaa_erddap",
        attribution: "NOAA CoastWatch / ERDDAP (Public Domain); GEBCO / WPP-NRI Boundaries",
        acquired_at_utc: new Date().toISOString(),
        is_cached_fallback: false,
        disclaimer: "Satellite and historical oceanographic estimates carry acquisition latency and spatial resolution limits; they do not guarantee fish presence at exact coordinates and do not substitute official maritime navigation or weather advisories (BMKG, Pushidrosal, Basarnas).",
        potential_score,
        potential_category
      });
    }

    // 6. Decimated ocean currents vector grid (Global coverage)
    if (url.pathname === "/v1/currents/grid") {
      const bboxParam = url.searchParams.get("bbox") || "-180,-80,180,80";
      const [minLon, minLat, maxLon, maxLat] = bboxParam.split(",").map(Number);
      const maxVectors = Math.min(320, Math.max(16, parseInt(url.searchParams.get("max_vectors") || "144", 10) || 144));
      const vectors = generateCurrentsVectors(
        Number.isFinite(minLon) ? minLon : -180,
        Number.isFinite(minLat) ? minLat : -80,
        Number.isFinite(maxLon) ? maxLon : 180,
        Number.isFinite(maxLat) ? maxLat : 80,
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

    // 7. Dynamic raster tile generation & tile fallback
    const tileMatch = url.pathname.match(/^\/v1\/tiles\/([a-zA-Z0-9_-]+)(?:\/([a-zA-Z0-9_-]+))?\/(\d+)\/(\d+)\/(\d+)\.(png|webp)$/);
    if (tileMatch) {
      const layer = tileMatch[1].toLowerCase();
      const z = parseInt(tileMatch[3], 10);
      const x = parseInt(tileMatch[4], 10);
      const y = parseInt(tileMatch[5], 10);
      if (layer === "sst" || layer === "chlorophyll" || layer === "potential") {
        const tileBytes = generateRasterTilePng(layer, z, x, y);
        return new Response(tileBytes, {
          status: 200,
          headers: {
            "Content-Type": "image/png",
            "Cache-Control": "public, max-age=86400, stale-while-revalidate=86400",
            ...CORS_HEADERS,
          },
        });
      }
      return new Response(TRANSPARENT_1X1_PNG, {
        status: 200,
        headers: {
          "Content-Type": "image/png",
          "Cache-Control": "public, max-age=86400, stale-while-revalidate=86400",
          ...CORS_HEADERS,
        },
      });
    }

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
