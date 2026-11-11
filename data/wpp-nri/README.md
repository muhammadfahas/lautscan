# WPP-NRI Reference Dataset (Wilayah Pengelolaan Perikanan Negara Republik Indonesia)

Direktori ini berisi dataset batas wilayah pengelolaan perikanan Indonesia (**WPP-NRI 571-718**) sesuai **Peraturan Menteri Kelautan dan Perikanan RI Nomor 18/PERMEN-KP/2014**.

## Daftar 11 Zona WPP-NRI

| Kode | Nama Resmi | Cakupan Perairan (Bahasa Indonesia) | English Summary |
|---|---|---|---|
| **571** | WPP-NRI 571 | Perairan Selat Malaka dan Laut Andaman | Malacca Strait and Andaman Sea |
| **572** | WPP-NRI 572 | Perairan Samudera Hindia sebelah Barat Sumatera dan Selat Sunda | Indian Ocean West of Sumatra and Sunda Strait |
| **573** | WPP-NRI 573 | Perairan Samudera Hindia sebelah Selatan Jawa hingga sebelah Selatan Nusa Tenggara, Laut Sawu, dan Laut Timor bagian Barat | Indian Ocean South of Java to Nusa Tenggara, Savu Sea, and West Timor Sea |
| **711** | WPP-NRI 711 | Perairan Selat Karimata, Laut Natuna, dan Laut Cina Selatan | Karimata Strait, Natuna Sea, and South China Sea |
| **712** | WPP-NRI 712 | Perairan Laut Jawa | Java Sea |
| **713** | WPP-NRI 713 | Perairan Selat Makassar, Teluk Bone, Laut Flores, dan Laut Bali | Makassar Strait, Gulf of Bone, Flores Sea, and Bali Sea |
| **714** | WPP-NRI 714 | Perairan Teluk Tolo dan Laut Banda | Gulf of Tolo and Banda Sea |
| **715** | WPP-NRI 715 | Perairan Teluk Tomini, Laut Maluku, Laut Halmahera, Laut Seram, dan Teluk Berau | Tomini Bay, Molucca Sea, Halmahera Sea, Seram Sea, and Berau Bay |
| **716** | WPP-NRI 716 | Perairan Laut Sulawesi dan sebelah Utara Pulau Halmahera | Sulawesi Sea and North of Halmahera Island |
| **717** | WPP-NRI 717 | Perairan Teluk Cendrawasih dan Samudera Pasifik | Cenderawasih Bay and Pacific Ocean |
| **718** | WPP-NRI 718 | Perairan Laut Aru, Laut Arafuru, dan Laut Timor bagian Timur | Aru Sea, Arafura Sea, and East Timor Sea |

## File di Direktori Ini

- [`wpp_nri_zones.json`](./wpp_nri_zones.json): GeoJSON `FeatureCollection` (CRS WGS84 / `EPSG:4326`, ring eksterior counter-clockwise sesuai RFC 7946) berisi **P0 seed bounding polygons** untuk seluruh 11 zona WPP-NRI beserta atribut `wpp_code`, `name`, `waters_id`, `waters_en`, `legal_basis`, `geometry_source`, `centroid_lat`, `centroid_lon`, `min_lon`, `min_lat`, `max_lon`, `max_lat`, dan `area_km2`.

## P0 Seed vs. Poligon Resmi KKP (Shapefile / GeoPackage)

Poligon pada `wpp_nri_zones.json` saat ini menggunakan **`geometry_source: "p0_seed"`** (poligon batas representatif yang bersih untuk bootstrap pengembangan P0, pengujian spatial query PostGIS, dan rendering overlay peta awal tanpa ketergantungan eksternal).

### Cara Mengganti P0 Seed dengan Poligon Resmi KKP

Untuk lingkungan produksi atau riset presisi pantai/ZEE, ganti poligon P0 seed dengan shapefile resmi batas WPP-NRI dari Kementerian Kelautan dan Perikanan (KKP / Pusdatin / BIG / Permen-KP No. 18/2014):

1. **Siapkan berkas shapefile resmi** (mis. `WPP_NRI_Official.shp` + `.dbf`, `.shx`, `.prj`) atau GeoPackage (`WPP_NRI_Official.gpkg`) dari portal geospasial KKP / One Map Policy.
2. **Konversi dan normalisasi ke GeoJSON `EPSG:4326`** (pastikan encoding UTF-8, `MultiPolygon` valid, dan kode `wpp_code` berupa string `"571"` hingga `"718"`):
   ```bash
   ogr2ogr -f GeoJSON -t_srs EPSG:4326 \
     -makevalid \
     data/wpp-nri/wpp_nri_official.geojson \
     WPP_NRI_Official.shp
   ```
3. **Mutakhirkan tabel `wpp_nri_zones` di PostGIS** menggunakan loader backend (atau `ST_Multi(ST_MakeValid(ST_GeomFromGeoJSON(...)))` dengan `SRID=4326`) dan setel kolom `geometry_source = 'kkp_official'`.
4. **Hitung ulang atribut turunan** (`centroid`, `min_lon`, `min_lat`, `max_lon`, `max_lat`, `area_km2` berbasis geografi `ST_Area(geom::geography) / 1e6`) agar hasil `GET /v1/wpp` dan `GET /v1/map/point` tetap sinkron.

> **Catatan Kepatuhan & Navigasi:** Batas WPP-NRI pada seed maupun peta visualisasi digunakan untuk analisis pengelolaan perikanan dan agregasi data oseanografi. Batas kedaulatan maritim dan navigasi pelayaran resmi tetap merujuk kepada otoritas nasional yang berwenang (Pushidrosal TNI AL, BIG, dan KKP).
