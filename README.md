# LAUT SCAN

**Know the Ocean. Find the Fish.**

LAUT SCAN adalah platform intelijen maritim dan oseanografi terbuka berbasis web (*open-source marine intelligence platform*) untuk perairan Indonesia dan samudra global. Platform ini mengintegrasikan data satelit oseanografi real-time, batas Wilayah Pengelolaan Perikanan Negara Republik Indonesia (**WPP-NRI 571 hingga 718**), pantauan armada kapal perikanan global (**Global Fishing Watch AIS**), telemetri siklon tropis & presipitasi satelit **NASA** (**NASA CYGNSS & NASA GPM IMERG**), serta inventaris keanekaragaman hayati laut (**OBIS / GBIF**).

---

## 🌐 Live Deployment

Aplikasi LAUT SCAN telah di-deploy dan dapat diakses langsung secara publik di:

👉 **[https://lautscan.pages.dev/](https://lautscan.pages.dev/)**

- **Infrastruktur Hosting**: Cloudflare Pages + Edge Worker runtime (`_worker.js`).
- **Kompatibilitas**: Peramban desktop dan mobile modern (Chrome, Safari, Edge, Firefox).
- **Mode Tampilan**: *Night Maritime* (monokrom gelap kontras tinggi) dan *Daylight Maritime*.

---

## 📸 Tampilan Antarmuka (Screenshots)

### 1. Peta Global & Streamline Angin / Siklon Satelit NASA
Visualisasi streamline angin global dan pusaran siklon tropis monokrom cyan/putih es berbasis Runge-Kutta orde-2 (RK2) dan proyeksi tanpa duplikasi benua:

![Peta Global & Streamline Angin NASA](docs/screenshots/nasa_global_weather_streamlines.png)

### 2. Telemetri Badai NASA CYGNSS & Radar Hujan NASA GPM IMERG
Pemeriksaan titik maritim (*Point Inspector*) menampilkan status keselamatan, kecepatan angin maksimum, tinggi gelombang, serta curah hujan radar satelit:

![Telemetri Badai NASA](docs/screenshots/nasa_storm_inspector.png)

### 3. Pantauan Armada Kapal Ikan Real-Time (Global Fishing Watch AIS)
Peta armada kapal perikanan dengan ikon kapal navigasi bergaya *flight tracker*:

![Pantauan Armada Kapal GFW](docs/screenshots/gfw_fleet_map.png)

### 4. Direktori Jenis Ikan & Foto Asli Bawah Laut
Katalog keanekaragaman hayati laut lengkap dengan foto asli bawah laut, data biologis, harga pasar, dan status konservasi:

![Direktori Jenis Ikan](docs/screenshots/species_explorer_cards.png)

---

## Fitur Utama

- **Peta Laut Interaktif Global & Nusantara (`/`)**:
  - Ditenagai oleh custom engine Web Mercator tanpa ketergantungan Leaflet ([`@lautscan/marine-map`](frontend/modules/marine-map/README.md) / `web/modules/marine-map/web/index.js`).
  - **4 Lapisan Lensa Laut**:
    - **Zona Ikan (Potensi)**: Estimasi habitat ikan pelagis berdasarkan kombinasi suhu nyaman, pakan plankton, dan front termal laut.
    - **Suhu Air (SST)**: Suhu permukaan laut satelit NOAA Coral Reef Watch / Geo-Polar Blended dengan kontur termal resolusi tinggi.
    - **Pakan Alami (Klorofil-a)**: Konsentrasi klorofil fitoplankton satelit NASA MODIS & VIIRS.
    - **Arus Laut**: Vektor dan aliran partikel arus permukaan laut dinamis.
    - **Cuaca & Hujan**: Radar hujan presipitasi satelit **NASA GPM IMERG** dengan palet monokrom cyan/putih es dan visualisasi streamline pusaran siklon tropis **NASA CYGNSS**.
- **Animasi Pusaran Siklon & Angin Global Gaya NASA**:
  - Menggunakan integrasi trayektori Runge-Kutta orde-2 (RK2) kontinu untuk 14 sistem badai/siklon aktif dunia (Bibit Siklon 94S, Squall Line Natuna, Taifun Yinxing, Hurricane Kirk, Siklon Bheki, dsb.) serta angin pasat (*trade winds*), angin barat (*westerlies*), dan *subtropical gyres*.
  - Dilengkapi fitur *dynamic zoom clamping* (`effectiveMinZoom`) dan *wrap-seam clipping* agar peta dunia tidak terduplikasi secara horizontal dan bebas dari garis artefak.
- **Batas WPP-NRI 571 hingga 718**: Poligon batas 11 Wilayah Pengelolaan Perikanan RI sesuai *Permen-KP No. 18/PERMEN-KP/2014* dengan pelabelan chip interaktif dan filter dropdown dinamis.
- **Pantauan Armada Kapal Global (GFW AIS Live)**:
  - Tampilan ikon kapal navigasi (model *flight tracker* kapal) terhubung telemetri Global Fishing Watch.
  - Klik kapal untuk membuka drawer informasi nama kapal, MMSI, bendera, tipe alat tangkap, kecepatan (knot), koordinat GPS, dan status operasi.
- **Pemeriksa Titik Maritim (Point Inspector - "Kondisi Titik Ini")**:
  - Klik koordinat laut mana pun untuk menganalisis data terinterpolasi: suhu air (°C/°F), klorofil-a, kecepatan & arah arus laut (16 arah mata angin), curah hujan satelit NASA IMERG, tinggi gelombang, status keselamatan navigasi, dan telemetri badai NASA CYGNSS.
- **Eksplorasi Spesies Ikan (`/species`)**:
  - Direktori ikan laut lengkap dengan foto asli bawah laut (*underwater photography*), nama ilmiah, nama lokal, famili, status konservasi IUCN, kedalaman jelajah, estimasi nilai pasar, dan titik sebaran OBIS.
  - Pilihan tampilan kartu (*grid cards*) dan tabel data dengan filter pencarian, pengurutan (*sorting*), serta penomoran halaman (*pagination*).
- **Tren Oseanografi & Sumber Data (`/trends`, `/sources`)**:
  - Analisis tren musiman antar-WPP.
  - Dashboard pemantauan status ketersediaan API dan dataset satelit (*healthy/active*).

---

## Arsitektur & Teknologi

| Komponen | Teknologi |
|---|---|
| **Edge Web Deployment** | Cloudflare Pages, Cloudflare Workers (`_worker.js`), HTML5 Canvas 2D, SVG, CSS Glassmorphism |
| **Frontend Map Module** | Custom standalone Web Mercator Map Engine (`@lautscan/marine-map`) dengan dynamic tile renderer PNG terkompresi |
| **Data Oseanografi & Satelit** | **NASA CYGNSS** (angin permukaan & siklon), **NASA GPM IMERG** (radar presipitasi hujan), **NOAA CoastWatch / ERDDAP** (SST & arus), **OBIS & GBIF** (keanekaragaman hayati), **Global Fishing Watch** (AIS) |
| **Backend Services (Lokal / Server)** | FastAPI (Python 3.11+), Pydantic v2, PostgreSQL 16 + PostGIS 3.4 (`SRID 4326`), Redis 7, ARQ ETL worker |

---

## Struktur Repositori

```text
lautscan/
├── web/                  # Sumber kode produksi Cloudflare Pages & Web Engine
│   ├── _worker.js        # Edge geospatial API, routing tile raster sintetis, dan point telemetry
│   ├── index.html        # Halaman utama aplikasi LAUT SCAN (Peta, Jenis Ikan, Tren, Sumber Data)
│   ├── app.css           # Styling maritim glassmorphism (Daylight & Night mode)
│   ├── data/             # Dataset WPP-NRI, marine weather NASA, katalog sumber, dan armada GFW
│   └── modules/          # Standalone @lautscan/marine-map engine (Canvas 2D + SVG markers + RK2 streamlines)
├── backend/              # FastAPI app, Alembic migrations, PostGIS models, ARQ ETL & tile renderer
├── data/wpp-nri/         # WPP-NRI 571-718 GeoJSON seed dataset dan panduan konversi KKP
├── docs/                 # Product requirements (PRD.md), arsitektur spesifikasi, dan kontrak OpenAPI
├── frontend/             # Expo Exact contracts dan spesifikasi desain antarmuka
└── infra/                # Konfigurasi Docker Compose stack, script dev-check, dan WSL2 setup
```

---

## Panduan Menjalankan Proyek

### 1. Menjalankan Versi Web (Cloudflare Pages / Lokal)

Untuk menjalankan antarmuka web statis secara lokal:

```bash
# Menggunakan web server lokal sederhana (misal: serve / npx http-server)
npx wrangler pages dev web
```

Buka peramban di `http://localhost:8788`.

Untuk deploy ke Cloudflare Pages:

```bash
npx wrangler pages deploy web --project-name=lautscan --branch=main
```

### 2. Menjalankan Backend Stack (Docker Compose)

1. Salin konfigurasi environment:

   ```bash
   cp infra/.env.example infra/.env
   ```

2. Jalankan PostgreSQL/PostGIS, Redis, API FastAPI, dan ETL Worker:

   ```bash
   docker compose -f infra/docker-compose.yml up -d --build
   ```

3. Jalankan migrasi basis data dan seed batas WPP-NRI:

   ```bash
   docker compose -f infra/docker-compose.yml exec api alembic upgrade head
   docker compose -f infra/docker-compose.yml exec api python -m app.db_seed
   ```

4. Verifikasi status API di `http://127.0.0.1:8080/v1/health` dan dokumentasi Swagger di `http://127.0.0.1:8080/docs`.

---

## Sumber Data & Atribusi

LAUT SCAN memprioritaskan penyedia data ilmiah terbuka (*open scientific data*):

| Sumber Data | Parameter | Status & Lisensi |
|---|---|---|
| **NASA CYGNSS** | Pusaran Siklon Tropis, Angin Permukaan Laut, Tinggi Gelombang | Public Domain / Open Data NASA Earth Science |
| **NASA GPM IMERG** | Presipitasi Radar Hujan Global & Inti Konvektif Badai | Public Domain / NASA GSFC |
| **NOAA CoastWatch / ERDDAP** | Suhu Permukaan Laut (SST) & Arus Laut | Public Domain / U.S. Government |
| **Ocean Biodiversity Information System (OBIS)** | Rekor Keberadaan Spesies Ikan Laut | CC0 / CC-BY Data Provider Attribution |
| **Global Fishing Watch (GFW)** | Telemetri Kapal Perikanan & AIS Pelayaran | Non-Commercial Research / GFW Attribution |
| **Batas WPP-NRI** | 11 Wilayah Pengelolaan Perikanan Indonesia | *Permen-KP No. 18/PERMEN-KP/2014* |

---

## Disclaimer Keselamatan Pelayaran

Informasi yang disajikan pada LAUT SCAN merupakan agregasi observasi satelit dan pemodelan oseanografi untuk tujuan referensi perikanan dan penelitian. Estimasi keberadaan ikan tidak menjamin penangkapan pada titik koordinat persis. Untuk keselamatan pelayaran dan peringatan cuaca maritim resmi berstandar navigasi, seluruh operator pelayaran wajib merujuk pada otoritas maritim resmi (**Pushidrosal**, **Basarnas**, **BMKG**, dan **Kementerian Kelautan dan Perikanan**).

---

## Lisensi

LAUT SCAN dirilis di bawah lisensi [MIT License](LICENSE). Masing-masing dataset oseanografi dan satelit pihak ketiga mempertahankan lisensi dan atribusi penyedia data asalnya.
