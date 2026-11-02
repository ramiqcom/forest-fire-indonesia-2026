# Forest fire mapping 2026: Kalimantan, Sumatera and the Legal Amazon #

Fire alerts from NASA FIRMS for August to October 2026, gridded to about 1 km, masked to land, and combined with forest cover and admin boundaries. Two areas:

- **Kalimantan and mainland Sumatera**: the 5 Kalimantan provinces and 8 mainland Sumatera provinces (Kepulauan Riau and Bangka Belitung left out).
- **Legal Amazon**: the 9 Brazilian states of the Amazônia Legal (Maranhão taken whole, although only part of it is in the Legal Amazon).

The areas are defined once in [src/forest_fire/aoi.py](src/forest_fire/aoi.py) and used by every job and the notebook.

## Pipeline ##

Each job writes to `gs://gee-ramiqcom-s4g-bucket/forest_fire_indonesian_2026/<product>/` and skips outputs already in the bucket, so a job can be run again after a failure. To redo an output, move or delete it in the bucket first.

| Order | Job | Output | What it does |
|---|---|---|---|
| 1 | `job/firms` | `firms/<province>_2026-08_2026-10.fgb` | FIRMS near real time alerts (VIIRS S-NPP, NOAA-20, NOAA-21 and MODIS) per province, downloaded by bounding box in 5 day windows and clipped to the province |
| 1 | `job/worldcover` | `worldcover/<region>.tif` | ESA WorldCover at 100 m per region, through the rs-open-source API |
| 1 | `job/jrc_gfc_2020` | `jrc_gfc_2020/<province>.tif` | JRC Global Forest Cover 2020 at 100 m per province, through the rs-open-source API |
| 2 | `job/firms_grid` | `firms_grid/<region>_2026-08_2026-10.tif` | Alerts merged per region and counted per cell of 0.009° (about 1 km) in EPSG:4326, with cells whose centre is outside the region and WorldCover water (class 80) set to nodata. Cloud optimised GeoTIFF, ZSTD, with statistics and LANCZOS overviews |
| | `job/composite` | `s1/`, `surface_water_s1/` | Sentinel-1 RTC composites and OPERA surface water at 30 m for the Palangka Raya, Sebangau and Kundangan AOIs in `input/` (June and October 2026) |

`firms_grid` needs the `firms` and `worldcover` outputs of its region and stops with an error if one is missing. Regions are `kalimantan`, `sumatera` and `legal_amazon`; province names are lower case ASCII with `_`, Brazilian states prefixed with `brazil_` (for example `brazil_para`).

## Setup ##

1. Copy `.env.example` to `.env` and fill in:
   - `GITHUB_TOKEN`: read access to `space4good/s4g-lib`, used only to build the image.
   - `RS_API_URL`: the rs-open-source API on Cloud Run, used by `worldcover`, `jrc_gfc_2020` and `composite`.
   - `FIRMS_MAP_KEY`: a NASA FIRMS MAP_KEY, see https://firms.modaps.eosdis.nasa.gov/api/map_key/.
   - `EARTHDATA_*`, `AWS_*`, `HF_TOKEN`: only for the composite sources that need them.
   - `GOOGLE_APPLICATION_CREDENTIALS`: path to the key for running outside Docker. Write it with forward slashes or as `./private_key.json`; backslashes in a double quoted value are read as escapes.
2. Put the service account key at `./private_key.json`. Docker Compose mounts it as a secret at runtime, it is never copied into the image.
3. Build the image: `docker compose build`.

## Running the jobs ##

```sh
docker compose run --rm firms
docker compose run --rm worldcover
docker compose run --rm firms_grid
```

`jrc_gfc_2020` and `composite` have no Compose service, run them with the `firms` service and another command:

```sh
docker compose run --rm firms .venv/bin/python -m job.jrc_gfc_2020
docker compose run --rm firms .venv/bin/python -m job.composite
```

The job code is copied into the image, so rebuild after changing it.

### FIRMS downloads ###

- Every response is checked to be a FIRMS CSV. A failed request is retried with waits doubling from 1 to 10 minutes, then the province fails instead of being saved with missing days.
- The MAP_KEY allows 5,000 transactions per 10 minutes. Large bounding boxes count heavily, so `job/firms` downloads at most 4 provinces at once (`MAX_WORKERS`). The key status is at `https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/?MAP_KEY=<key>`.
- Near real time data only goes back a few months, and MODIS near real time has no data before 1 September 2026 in these files, so August is VIIRS only.

## Notebooks ##

Run from the repository root or from `notebook/`, with the environment of the image or a local `pip install -e ".[dev]"`. Both read their inputs from the bucket.

- [notebook/firms.ipynb](notebook/firms.ipynb): for each area, the provinces or states, the FIRMS alerts with 2020 forest and cities above 1 million people, the fire count grid, and the alerts per regency or municipality (total and per 100 km²). Saves the fire count and admin level 2 figures to `output/figures/`. All text sizes follow `plt.rcParams["font.size"]` in the first cell.
- [notebook/s1_composites.ipynb](notebook/s1_composites.ipynb): the Sentinel-1 composites and surface water of `job/composite`.

## Data and limits ##

| Data | Source | Licence or terms |
|---|---|---|
| Fire alerts | NASA FIRMS near real time, VIIRS and MODIS | NASA open data, cite FIRMS |
| Indonesian provinces and regencies | `indonesia_adm_level_1.fgb` and `indonesia_adm_level_2.fgb` in `gs://gee-ramiqcom-bucket/admin/` (Lapak GIS 2024) | Check before publishing |
| Brazilian states and municipalities | GADM 4.1 | Non-commercial use only without permission, see https://gadm.org/license.html |
| Forest 2020 | JRC Global Forest Cover 2020 v4 | CC BY 4.0, European Commission |
| Water | ESA WorldCover | CC BY 4.0, ESA |
| Cities | Natural Earth populated places | Public domain |
| Basemap | Esri World Shaded Relief | Keep the Esri attribution |

- A FIRMS alert is a hot pixel (375 m for VIIRS, 1 km for MODIS) at the time of a satellite pass, not a fire and not a burned area. One fire is counted on every pass that sees it, and fires under thick smoke or cloud can be missed.
- The grid count uses `gdal vector grid count` with a search radius of half a cell, so it counts about 20% fewer alerts than the alert points. Use the points for totals.
- Forest in 2020 does not mean forest in 2026.
- Natural Earth has a few places that share a name and population with another one (for example a Vila Velha in Amapá with the population of Vila Velha in Espírito Santo). The notebook leaves those out.
