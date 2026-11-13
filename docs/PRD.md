# PRODUCT REQUIREMENTS DOCUMENT (PRD)
# LAUT SCAN

**Version:** 1.2  
**Status:** Revised Specification (Locked Stack)  
**Product Type:** Open-Source Marine Intelligence Platform  
**Primary Platform:** Web  
**Future Platforms:** iOS, macOS, Linux, Android  
**UI Runtime:** Expo Exact  
**Backend Stack:** FastAPI (Python 3.11+)  
**License:** MIT  
**Tagline:** Know the Ocean. Find the Fish.

---

## 1. Product Overview

LAUT SCAN adalah platform *open-source* untuk intelijen kelautan yang mengintegrasikan data satelit, oseanografi, batas wilayah pengelolaan perikanan (WPP-NRI), dan informasi biodiversitas laut.

Platform ini membantu nelayan, peneliti, dan pelaku industri perikanan memahami kondisi laut serta mengidentifikasi wilayah potensial penangkapan ikan melalui peta interaktif berbasis *map-first workspace* dan analisis data historis.

Pada tahap awal (MVP), LAUT SCAN berfokus pada fondasi pipa data geospasial, penyajian raster/vektor tile yang cepat, dan visualisasi data dari sumber gratis dan terbuka. Fitur machine learning dan prediksi *fishing ground* dikembangkan pada fase lanjutan setelah data historis tervalidasi tersedia.

---

## 2. Product Vision

Membangun platform intelijen kelautan terbuka yang menyediakan akses informasi kondisi laut dan potensi perikanan secara transparan, akurat, dan ringan diakses bahkan pada kondisi jaringan terbatas di laut.

---

## 3. Target Users

- Nelayan tradisional dan modern (pengguna seluler/tablet di lapangan, siang dan malam hari).
- Pemilik kapal dan manajer armada perikanan.
- Perusahaan perikanan (dengan kepatuhan lisensi masing-masing sumber data).
- Peneliti kelautan dan akademisi/mahasiswa.
- Instansi pemerintah dan pengelola perikanan.
- Komunitas *open-source*.

---

## 4. Core Features

### 4.1 Marine Intelligence Map (Map-First Workspace)

Peta interaktif yang menjadi pusat navigasi dan eksplorasi aplikasi (menempati >=75% area layar pada tampilan utama).

**Layer Data:**
- Base Map: OpenStreetMap (atau tile bahari terbuka).
- Sea Surface Temperature (SST): raster tile overlay dengan kontrol opasitas.
- Chlorophyll-a: raster tile overlay dengan kontrol opasitas.
- Ocean Current: vektor/panah arah & kecepatan arus laut.
- WPP-NRI Boundaries (571-718): overlay poligon GeoJSON/Vector Tile interaktif.
- Fish Occurrence (OBIS): titik/klaster observasi biodiversitas.
- Fishing Ground Information / PDPI: zona potensial tangkapan.
- Fishing Activity (GFW): *opt-in* dengan kepatuhan non-komersial.

**Fitur Peta:**
- Zoom, pan, dan *bounding box* query otomatis saat kamera berhenti (`moveend`).
- Layer manager dengan toggle aktif/nonaktif dan slider opasitas.
- **Point Inspection:** klik/tap pada koordinat kosong di peta untuk melihat nilai interpolasi SST, klorofil-a, arus, dan status WPP-NRI pada titik tersebut.
- Pencarian & filter berdasarkan wilayah **WPP-NRI (571-718)** atau koordinat geografis.
- Legenda numerik *colorblind-safe*, skala peta, dan badge **Data Freshness & Attribution** permanen di sudut kanvas.

### 4.2 Ocean Condition Monitoring

Terintegrasi langsung ke dalam **Point Inspector Drawer** pada peta serta tampilan ringkasan wilayah:
- Suhu permukaan laut (°C / °F).
- Konsentrasi klorofil-a (mg/m³).
- Kecepatan (m/s atau knot) dan arah arus (derajat / mata angin).
- Salinitas (PSU) dan tinggi gelombang apabila tersedia dari provider.

### 4.3 Fishing Ground Explorer

Menampilkan informasi wilayah potensial penangkapan ikan sebagai panel/daftar yang tersinkronisasi dengan peta:
- Lokasi geografis dan rentang koordinat.
- Wilayah WPP-NRI.
- Jenis informasi *fishing ground* dan skor kondisi oseanografi.
- Sumber data dan waktu pembaruan (*timestamp* UTC & WIB/WITA/WIT).
- Alternatif **tampilan tabel** untuk aksesibilitas dan koneksi internet rendah.

### 4.4 Fish Species Explorer

Menampilkan informasi spesies ikan berbasis data observasi terbuka (OBIS):
- Nama umum dan nama ilmiah (*binomial nomenclature*).
- Persebaran geografis berdasarkan observasi pada peta.
- Karakteristik habitat & kedalaman.
- Riwayat observasi dan referensi sumber data asli.

### 4.5 Historical Ocean Analysis

Menampilkan perubahan kondisi laut berdasarkan data historis:
- Grafik deret waktu (*time-series*) suhu permukaan laut dan klorofil-a.
- Perbandingan antar-periode (mingguan, bulanan, musiman/monsun).
- Pemutar rentang tanggal (*time slider*) untuk visualisasi historis pada peta.
- Filter berdasarkan tanggal dan wilayah WPP-NRI.

### 4.6 Machine Learning Fishing Ground Forecasting (Future, P3)

Fitur pengembangan lanjutan untuk memperkirakan lokasi potensial ikan:
- **Input:** SST, Chlorophyll-a, Ocean Current, Historical Data, Fish Occurrence, Seasonal Information (Angin Muson).
- **Output:** Predicted Fishing Ground, Geographic Coordinates, Potential Score, Prediction Confidence, dan Environmental Analysis.
- **Batasan:** Belum termasuk MVP; membutuhkan pengumpulan data historis minimal beberapa musim dan validasi lapangan.

---

## 5. Data Sources & Compliance Strategy

Seluruh sumber data mengutamakan akses terbuka, gratis, dan kejelasan lisensi.

| Provider | Data | Mekanisme Akses Teknis | Prioritas | Catatan Lisensi & Risiko |
|---|---|---|---|---|
| **NASA CYGNSS** | Pusaran Siklon Tropis & Angin Permukaan Laut | Terbuka / Public Domain NASA Earth Science tanpa token | **P1 (Primer)** | Data ilmiah terbuka NASA; visualisasi pusaran siklon & streamline angin global. |
| **NASA GPM IMERG** | Radar Presipitasi Hujan Satelit Global | Terbuka / Public Domain NASA GSFC tanpa token | **P1 (Primer)** | Radar presipitasi curah hujan & badai konvektif global. |
| **NOAA CoastWatch / ERDDAP** | SST, Chlorophyll-a, Current | REST / ERDDAP subsetting (JSON, PNG, NetCDF) tanpa token rumit | **P1 (Primer)** | Public domain / terbuka; ideal untuk bootstrap cepat Indonesia bounding box. |
| **OBIS (`api.obis.org`)** | Fish Occurrence & Taxon | REST API v3 terbuka (JSON / GeoJSON) tanpa token | **P1 (Primer)** | Terbuka dengan atribusi data provider asli. |
| **Copernicus Marine** | SST, Chlorophyll, Current, Salinity | Akun gratis + Python `copernicusmarine` Toolbox (NetCDF/Zarr/WMTS) | **P1 (Batch ETL)** | Diolah di worker terjadwal backend menjadi XYZ tiles & ringkasan PostGIS. Kredensial tidak pernah disertakan di repositori. |
| **KKP PDPI** | Prakiraan Daerah Penangkapan Ikan | *Pluggable Adapter* (WMS/Raster/Portal koordinasi Pusdatin/BPISDKP) | **P1/P2 (Adapter)** | Akses API raw publik tidak selalu tersedia bebas; tidak boleh memblokir rilis P1. |
| **Global Fishing Watch (GFW)** | Fishing Activity (AIS) | Telemetri armada AIS perikanan global | **P2 (Opt-in)** | Tier gratis **hanya untuk non-komersial / kepentingan publik**. Pengguna komersial wajib lisensi GFW atau *BYO-Token* terpisah agar tidak bertabrakan dengan lisensi MIT aplikasi. |

**Official Sources:**
- https://cygnss.engin.umich.edu/ & https://earthdata.nasa.gov/ (NASA CYGNSS)
- https://gpm.nasa.gov/data/imerg (NASA GPM IMERG)
- https://coastwatch.pfeg.noaa.gov/erddap/ & https://www.ncei.noaa.gov/
- https://api.obis.org/
- https://marine.copernicus.eu/
- https://portal-informasi.kkp.go.id/pdpi/
- https://globalfishingwatch.org/

Setiap layer wajib menampilkan **atribusi sumber, waktu pembaruan terakhir, dan status kesehatan ingest** pada UI.

### 5.1 Kebijakan Bebas Kredensial (Zero-Credential Policy)

LAUT SCAN menerapkan prinsip keamanan ketat **Zero-Credential Policy** pada seluruh aset repositori dan deployment publik:
- **100% Bebas Kredensial:** Tidak ada API key, token privat, password basis data, maupun kredensial akun pihak ketiga yang disimpan atau di-commit ke dalam repositori publik.
- **Client & Edge Isolation:** Klien web dan Cloudflare Pages Edge Worker (`_worker.js`) beroperasi sepenuhnya secara independen tanpa memerlukan token rahasia pengguna maupun server.
- **Open Scientific Access:** Seluruh data primer (NASA CYGNSS, NASA GPM IMERG, NOAA CoastWatch ERDDAP, dan OBIS API) diakses melalui protokol publik domain ilmiah tanpa token otorisasi tertutup.
- **Backend Secret Management:** Jika backend server mandiri diaktifkan, variabel environment privat wajib diinjeksikan secara terpisah melalui secret manager runtime hosting dan **dilarang keras** di-hardcode di file konfigurasi repositori.

---

## 6. Technology Architecture

### 6.1 Application Runtime: Expo Exact

**Repository:** https://github.com/expo/exact

Exact digunakan sebagai fondasi UI lintas platform:
- **Contract (`*.contract`):** Deklarasi UI, state, actions, shapes, dan routing.
- **TypeScript (`app.ts`):** Data logic dan penghubung ke Backend API (dieksekusi di engine browser pada Web, dan Hermes pada native hosts).
- **Exact Runtime:** Web host (~20 KB runtime atas DOM asli) serta Rust runner + Taffy layout kernel untuk native hosts.
- **Web Test Driver (`scripts/agent.mjs`):** Otomasi UI, *deterministic clock*, dan pengujian end-to-end (`*.test.contract`).

Tidak menggunakan React, JSX, atau Vue sebagai lapisan UI utama.

### 6.2 Frontend & Strategi Peta (PoC Wajib di P0)

- **Teknologi:** Expo Exact, Exact Contract, TypeScript, SVG / Canvas 2D.
- **Temuan Teknis Penting:** Modul bawaan `@exact/maps` (`exact-map`) saat ini hanya mendukung 1 layer base tile XYZ, marker pin standar (`MapMarker[]`), serta event `change` (klik marker) dan `moveend`. Modul ini **belum mendukung** multi-layer raster overlay dengan opasitas, poligon GeoJSON WPP-NRI, vektor arus laut, maupun klik koordinat bebas (*point inspection*).
- **Solusi Arsitektur:** Membuat **Custom Exact Native Module** khusus (misalnya `@lautscan/marine-map`) yang tetap mematuhi arsitektur Contract:
  - **Web Host:** Menggunakan engine peta WebGL/Canvas (seperti **MapLibre GL JS** atau **Leaflet**) di dalam wrapper native module Exact untuk mendukung base OpenStreetMap, multi-layer XYZ raster tiles, vektor arus, poligon WPP-NRI, dan event `pointclick(lat, lon)`.
  - **Apple/Native Hosts (Phase 2+):** Wrapper MapKit / Maps SDK dengan overlay tile & anotasi serupa.

### 6.3 Backend API & Tile/Raster Serving

- **Framework & Language:** **FastAPI (Python 3.11+)**, Pydantic v2 (kontrak API & OpenAPI schema otomatis), Uvicorn/Gunicorn ASGI.
- **Database & Spatial Access:** SQLAlchemy 2.0 (`asyncpg`) + GeoAlchemy2 untuk query spasial PostGIS.
- **Background Workers & Scheduling:** **ARQ** (berbasis Redis) / **APScheduler** untuk penarikan data satelit terjadwal dan generasi tile asinkron.
- **Testing & Quality:** `pytest`, `httpx` (ASGI test client), `ruff`, `mypy` / `pyright`.

**Tanggung Jawab Backend:**
- Orkestrasi ingest terjadwal dari NOAA ERDDAP, OBIS, Copernicus Marine Toolbox, dan adapter PDPI/GFW.
- **Raster/Tile Pipeline:** Mengonversi grid oseanografi (NetCDF/Zarr/GeoTIFF) menjadi **XYZ PNG/WebP Tiles** (`/{layer}/{date}/{z}/{x}/{y}.png`) dan melakukan *pre-render* atau *on-demand tiling* yang di-cache di disk/object storage/Redis.
- **Point Query Service:** Mengambil nilai SST, Klorofil-a, Arus, dan zona WPP-NRI untuk koordinat `(lat, lon, date)` tertentu.
- **Geospatial REST API** berstandar OpenAPI (`/openapi.json`) yang langsung sinkron dengan `app.ts` / `shape` di Expo Exact.

### 6.4 Database & Cache

- **PostgreSQL + PostGIS:** Menyimpan batas poligon resmi WPP-NRI (571-718), titik observasi spesies (OBIS), indeks metadata raster/tile, ringkasan statistik harian per WPP-NRI, dan status *data source health*.
- **Redis (opsional untuk P0, direkomendasikan di P1):** Caching response API, *point queries*, dan *rate-limit guard* ke provider eksternal.
- **File / Object Storage Lokal (atau MinIO S3-compatible):** Menyimpan cache tile PNG/WebP dan file NetCDF/COG mentah.

### 6.5 Data Processing & Machine Learning

- **Python:** `xarray`, `netCDF4`, `copernicusmarine`, `rasterio` / `Pillow`, `pandas`, `numpy`.
- **Machine Learning (P3):** `scikit-learn`, `xgboost`.
- Python digunakan untuk ETL oseanografi, generasi raster tile, analisis statistik, dan pelatihan model ML.

### 6.6 Standar Developer Environment

- Mengingat pengembangan di Windows memerlukan WSL2/Linux untuk menjalankan `expo/exact` (membutuhkan **Bun 1.4.2**, **Rust**, dan **Chrome**), repositori akan menyediakan **`docker-compose.yml`** standar yang menjalankan PostgreSQL/PostGIS, Redis, Backend API, dan Geospatial Worker dalam satu perintah untuk mempermudah kontributor *open-source*.

---

## 7. Cross-Platform Strategy

Mengikuti kemampuan aktual `expo/exact`:

- **Phase 1: Web (Fokus Utama MVP)**
  - Web Host dengan browser DOM/CSS dan custom `@lautscan/marine-map`.
  - Responsive layout untuk desktop, tablet, dan mobile browser (375px, 768px, 1024px, 1440px).
  - *Low-bandwidth optimization* dan caching tile/ringkasan di browser.
- **Phase 2: iOS & macOS**
  - Exact Apple Host (UIKit & AppKit) melalui macOS + Xcode.
  - Native navigation dan adaptasi native module peta untuk MapKit.
  - Dukungan penyimpanan lokal SQLite untuk akses informasi WPP-NRI terakhir saat melaut tanpa sinyal.
- **Phase 3: Linux & Android**
  - Linux host (DRM/KMS / desktop; catatan: kapabilitas input/editing Linux di Exact terbatas dibanding Web/Apple).
  - Android host setelah dukungan packaging & store delivery di `expo/exact` matang.
  - Windows native host tidak menjadi target MVP.

---

## 8. UI/UX Design System & Application Structure

Mengacu pada pedoman desain antarmuka untuk *Geospatial Data-Dense Dashboard*:

### 8.1 Navigasi Utama (Map-Centric, 5 Menu Utama)

Menggantikan 8 menu terpisah pada v1.1 agar fokus pada peta dan skalabel ke layar kecil/mobile:

1. **Ocean Map** *(Landing & Workspace Utama)*: Peta penuh dengan toolbar layer mengambang, filter WPP-NRI, *time selector*, dan *Point Inspector Drawer* (menampilkan SST, Klorofil, Arus, serta info Fishing Ground di titik terpilih).
2. **Species**: Eksplorasi spesies ikan (OBIS), taksonomi, habitat, dan sebaran observasi.
3. **Trends**: Analisis historis (grafik SST, Klorofil-a, perbandingan antar-periode/muson).
4. **Overview & Sources**: Ringkasan kondisi laut nasional/WPP-NRI, status *update* tiap satelit/provider, log kesehatan ingest, dan informasi lisensi/atribusi.
5. **Settings**: Preferensi unit (`°C`/`°F`, `knot`/`m/s`), mode tampilan (**Daylight Maritime** / **Night Maritime**), serta manajemen cache offline.

### 8.2 Identitas Visual, Tipografi, & Aksesibilitas

- **Dual Theme (Menggunakan CSS `light-dark()`):**
  - *Daylight Maritime (Light Mode untuk kondisi terik di laut):* Background `#F8FAFC`, Surface `#FFFFFF`, Text `#1E293B` (rasio kontras >= 4.5:1), Border `#E2E8F0`, Primary `#3B82F6`, CTA `#F97316`.
  - *Night Maritime (Dark Mode untuk kondisi di anjungan/kapal malam hari):* Background `#0A0E27` / `#0D1117`, Text `#E6EDF3`, Border `#30363D`, aksen `#60A5FA` & `#F97316`.
- **Tipografi:**
  - *UI & Body:* **Fira Sans** (ukuran body minimum `16px` pada mobile).
  - *Koordinat, Telemetry, & Timestamp:* **Fira Code** dengan `font-variant-numeric: tabular-nums` agar angka koordinat dan metrik sejajar rapi.
- **Skala Warna & Aksesibilitas:**
  - Dilarang menggunakan colormap *rainbow/jet*. Gunakan skala *colorblind-safe* (**Plasma/Thermal** untuk SST, **Viridis** untuk Chlorophyll-a) lengkap dengan label min/max numerik.
  - Seluruh indikator interaktif memakai **ikon SVG konsisten (Lucide)**; dilarang memakai emoji sebagai ikon UI.
  - Target sentuh minimum **`44×44px`** pada kontrol peta, layer toggle, dan tombol di mobile/tablet.
  - Menyediakan **alternatif tampilan tabel ringkasan per WPP-NRI** untuk pembaca layar (*screen reader*) dan pengguna bandwidth sangat rendah.
  - Menghormati `prefers-reduced-motion` dan mempertahankan *visible focus ring*.

---

## 9. MVP Development Scope

### P0: Core Foundation & Technical Proof of Concept
1. Setup `docker-compose.yml` (PostgreSQL + PostGIS, Redis, Backend API).
2. **PoC `@lautscan/marine-map` di Expo Exact Web Host** (OpenStreetMap + 1 overlay XYZ raster tile + poligon GeoJSON WPP-NRI + `pointclick(lat, lon)`).
3. Setup struktur aplikasi Expo Exact (`app.contract`, `app.ts`, routing 5 menu utama).
4. Ingest data batas wilayah resmi **WPP-NRI (571-718)** ke PostGIS.
5. Responsive *Map-First* shell (Light/Dark Maritime theme) + tampilan koordinat & status freshness.

### P1: Open Data Integration & Tile Pipeline
1. Pipeline ingest **NOAA CoastWatch / ERDDAP** (SST, Chlorophyll-a, Currents) ke raster XYZ tiles + cache.
2. Integrasi **OBIS API** untuk observasi biodiversitas ikan.
3. Worker batch **Copernicus Marine Toolbox** (opsional aktivasi via kredensial `.env`).
4. Layer management UI (toggle layer + kontrol opasitas + legenda *colorblind-safe*).
5. Point Inspector (klik lokasi di peta untuk melihat parameter oseanografi aktual/terdekat).
6. Halaman **Overview & Sources** (status pembaruan, kesehatan API, atribusi, lisensi).
7. *Pluggable adapter* untuk **KKP PDPI** (aktif apabila endpoint/file sumber tersedia).

### P2: Marine Intelligence & Analysis
1. **Fishing Ground Explorer** terintegrasi dengan filter **WPP-NRI**.
2. **Fish Species Explorer** lengkap dengan filter taksonomi dan peta sebaran.
3. **Historical Ocean Analysis** (*time-series* SST/Klorofil-a + *time slider* di peta).
4. Integrasi **Global Fishing Watch (GFW)** dengan pemisahan mode non-komersial / *BYO-Token*.
5. Tampilan tabel aksesibel & mode *low-bandwidth* per WPP-NRI.

### P3: Machine Learning & Statistical Forecasting (Post-MVP)
1. Persiapan & pengayaan dataset historis multi-musim (SST, Chlorophyll, Current, OBIS, seasonal features).
2. Pelatihan & evaluasi model *Machine Learning* (Scikit-learn / XGBoost).
3. Endpoint prediksi *fishing ground* + skor kepercayaan (*confidence interval*).
4. Visualisasi layer prediksi & validasi lapangan bersama mitra/komunitas nelayan.

---

## 10. Quality & Testing

Menggunakan kapabilitas otomasi pengujian bawaan Expo Exact dan standar CI:
- **Contract Validation:** `contract build --json` tanpa error tipe/layout.
- **Automated UI & Driver Testing:** Skrip `*.test.contract` melalui `scripts/agent.mjs web` (termasuk pengujian deterministic clock dan interaksi peta).
- **Screenshot Verification:** Pemeriksaan visual pada viewport `375px`, `768px`, `1024px`, dan `1440px` untuk mode Light & Dark.
- **API & Spatial Testing:** Pengujian endpoint REST/OpenAPI, validasi geometri PostGIS, dan unit test pipeline raster tile.
- **Pre-Delivery UI & Accessibility Checklist:** Zero emoji icons, kontras WCAG AA (>=4.5:1), `cursor-pointer`, target sentuh >=44px, dan tidak ada *horizontal scroll* pada mobile.

---

## 11. Non-Functional Requirements

- **Open-source friendly:** Dokumentasi setup jelas, konfigurasi `.env.example`, dan `docker-compose.yml` siap jalan.
- **Fast loading:** Tile raster di-cache; query bounding box dibatasi dan di-debounce; aset awal tetap ringan.
- **Graceful degradation:** Jika salah satu API eksternal (NOAA/Copernicus/PDPI/GFW) gagal atau terkena *rate limit*, layer lain tetap berjalan dan UI menampilkan *cached timestamp* terakhir dengan jelas.
- **Data transparency:** Setiap titik data menampilkan sumber, resolusi spasial, dan tanggal akuisisi satelit.
- **Security:** Kredensial API eksternal (Copernicus, GFW) hanya disimpan di sisi backend (`.env` / secrets), tidak pernah terekspos ke klien.

---

## 12. Development Principles

1. Open-source first (MIT).
2. Free and open data priority (NOAA ERDDAP & OBIS sebagai fondasi).
3. Data-driven & evidence-based development.
4. Modular architecture dengan adapter sumber data terpisah.
5. Cross-platform by design tanpa melanggar batas Contract Exact.
6. Minimal dependencies & zero over-engineering.
7. Reproducible & contract-verified development.
8. Automated testing (Contract + API + ETL).
9. Transparent attribution & licensing compliance.
10. No unsupported real-time claims.

---

## 13. Important Technical Constraints

- **Expo Exact Pre-1.0:** API, sintaks Contract, dan behavior host dapat berubah sewaktu-waktu; lakukan *pinning* commit hash `expo/exact` yang teruji.
- **Platform Host Constraints:** Pengembangan aktif menggunakan Web Host di Linux/WSL2 atau macOS. Dukungan presenter Windows dan packaging produksi Android di `expo/exact` masih belum menjadi target stabil untuk MVP.
- **Peta Oseanografi:** Wajib lolos **P0 PoC** custom native module sebelum membangun seluruh UI analitik.
- **Batas Kepatuhan Data:** Fitur GFW dibatasi sesuai ketentuan non-komersial kecuali pengguna/instansi menyediakan lisensi dan token resmi sendiri.

---

## 14. Success Metrics (MVP P0 + P1)

- Aplikasi Web berjalan di Expo Exact Web Host dengan custom native module `@lautscan/marine-map`.
- Peta Indonesia beserta poligon WPP-NRI (571-718) tampil responsif di desktop & mobile.
- Minimal 2-3 sumber data terbuka aktif (NOAA ERDDAP + OBIS, plus Copernicus/PDPI adapter) dan menghasilkan XYZ raster tiles / GeoJSON.
- Layer SST, Klorofil-a, dan Arus dapat di-toggle, diatur opasitasnya, dan diinspeksi nilainya per koordinat klik.
- Timestamp akuisisi satelit, sumber data, dan disclaimer tampil konsisten di peta.
- Automated UI test (`*.test.contract`) serta test API/ETL berjalan dan lulus di CI.

---

## 15. Product Disclaimer

LAUT SCAN merupakan platform visualisasi dan analisis informasi kelautan berbasis data historis dan citra satelit yang memiliki jeda waktu (*latency*) akuisisi serta keterbatasan resolusi spasial.

- Informasi *fishing ground* dan hasil analisis **tidak menjamin** keberadaan ikan pada koordinat tertentu.
- Data observasi historis (seperti OBIS) tidak menunjukkan posisi ikan secara *real-time*.
- Informasi navigasi dan keselamatan pelayaran wajib merujuk kepada otoritas resmi yang berwenang (BMKG, Pushidrosal, Basarnas, dan instansi terkait).

---

## Changelog

- **v1.2:** Mengunci backend **FastAPI (Python 3.11+)** (unified API + geospatial ETL + ML), penambahan P0 PoC `@lautscan/marine-map` (mengatasi limitasi `@exact/maps` standar), spesifikasi Tile/Raster serving pipeline, prioritas NOAA ERDDAP & OBIS di P1, pemisahan kepatuhan lisensi GFW & adapter KKP PDPI, penyederhanaan navigasi menjadi 5 menu *map-centric*, penerapan standar aksesibilitas/UI maritim (Daylight/Night Maritime, Fira Sans/Fira Code, colormap ramah buta warna, target sentuh 44px), serta standar `docker-compose.yml`.
- **v1.1:** Spesifikasi awal LAUT SCAN berbasis Expo Exact, ASP.NET Core, PostgreSQL/PostGIS, dan integrasi 5 sumber data kelautan.

---

**PROJECT:** LAUT SCAN  
**VERSION:** 1.2  
**LICENSE:** MIT  
**RUNTIME:** Expo Exact  
**PRIMARY PLATFORM:** Web  
**TAGLINE:** Know the Ocean. Find the Fish.
