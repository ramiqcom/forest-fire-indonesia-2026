from concurrent.futures import ThreadPoolExecutor
from logging import INFO, basicConfig, getLogger
from pathlib import Path
from shutil import which
from subprocess import DEVNULL, CalledProcessError, check_call, check_output

import geopandas as gpd
from dotenv import load_dotenv
from s4g.composite import generate_firms

from forest_fire.aoi import REGIONS, api_roi, read_provinces

load_dotenv()

basicConfig(
    level=INFO,
    format="%(asctime)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = getLogger(__name__)

OUTPUT_LOCAL = Path("output")
CLOUD_PREFIX = "gs://gee-ramiqcom-s4g-bucket/forest_fire_indonesian_2026"
PRODUCT = "firms"
# Cloud Run jobs at the same time, they share the FIRMS_MAP_KEY and its transaction limit
MAX_WORKERS = 4
# Near real time of the 4 satellites, the archive (SP) sources are not needed for 2026
SOURCES = ("MODIS_NRT", "VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT")

DATES = [
    dict(name="2026-08_2026-10", start="2026-08-01", end="2026-10-31"),
]


def list_done() -> set[str]:
    try:
        paths = check_output(
            [which("gcloud"), "storage", "ls", f"{CLOUD_PREFIX}/{PRODUCT}/"],
            text=True,
            stderr=DEVNULL,
        )
    except CalledProcessError:
        # Prefix does not exist yet
        return set()
    return {Path(path).stem for path in paths.split()}


def run(region: str, province: gpd.GeoDataFrame, date: dict):
    name = f"{province.index[0]}_{date['name']}"
    output_path = OUTPUT_LOCAL / f"{PRODUCT}_{name}.fgb"
    firms_path = OUTPUT_LOCAL / f"{PRODUCT}_{name}_api.fgb"

    logger.info(f"Run {PRODUCT} {name}")
    roi, roi_where = api_roi(region, province, OUTPUT_LOCAL / f"roi_{name}.fgb")
    generate_firms(
        str(firms_path),
        roi,
        (date["start"], date["end"]),
        sources=SOURCES,
        roi_sql_where=roi_where,
    )

    # Keep only alerts inside the province, with the province name
    alerts = gpd.read_file(firms_path)
    alerts = alerts.sjoin(province, predicate="within")
    alerts.to_file(output_path, driver="FlatGeobuf")
    logger.info(f"{PRODUCT} {name}: {len(alerts)} alerts")

    logger.info(f"Upload {PRODUCT} {name}")
    check_call(
        [which("gcloud"), "storage", "cp", str(output_path), f"{CLOUD_PREFIX}/{PRODUCT}/{name}.fgb"]
    )

    output_path.unlink()
    firms_path.unlink()


if __name__ == "__main__":
    OUTPUT_LOCAL.mkdir(exist_ok=True)

    done = list_done()
    todo = []
    for region in REGIONS:
        aoi = read_provinces(region)
        for province in aoi.index:
            for date in DATES:
                name = f"{province}_{date['name']}"
                if name in done:
                    logger.info(f"Skip {PRODUCT} {name}, already in {CLOUD_PREFIX}/{PRODUCT}")
                else:
                    todo.append((region, aoi.loc[[province]], date))

    jobs = {}
    if todo:
        with ThreadPoolExecutor(min(len(todo), MAX_WORKERS)) as executor:
            jobs = {
                f"{PRODUCT} {province.index[0]}_{date['name']}": executor.submit(
                    run, region, province, date
                )
                for region, province, date in todo
            }

    failed = []
    for name, job in jobs.items():
        try:
            job.result()
        except Exception as e:
            logger.error(f"Error {name}: {e}")
            failed.append(name)

    if failed:
        raise SystemExit(f"Failed: {', '.join(failed)}")
