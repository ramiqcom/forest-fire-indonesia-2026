from concurrent.futures import ThreadPoolExecutor
from logging import INFO, basicConfig, getLogger
from pathlib import Path
from shutil import which
from subprocess import DEVNULL, CalledProcessError, check_call, check_output

import geopandas as gpd
from dotenv import load_dotenv
from s4g.composite import generate_jrc_gfc_2020

from forest_fire.aoi import REGIONS, api_roi, read_provinces

load_dotenv()

basicConfig(
    level=INFO,
    format="%(asctime)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = getLogger(__name__)

OUTPUT_LOCAL = Path("output/jrc_gfc_2020")
CLOUD_PREFIX = "gs://gee-ramiqcom-s4g-bucket/forest_fire_indonesian_2026"
PRODUCT = "jrc_gfc_2020"
# The dataset is 10 m, 100 m keeps the large provinces and states manageable and matches WorldCover
RESOLUTION = 100
# Cloud Run jobs running at the same time
MAX_WORKERS = 8


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


def run(region: str, province: gpd.GeoDataFrame):
    name = province.index[0]
    output_path = OUTPUT_LOCAL / f"{PRODUCT}_{name}.tif"

    logger.info(f"Run {PRODUCT} {name}")
    roi, roi_where = api_roi(region, province, OUTPUT_LOCAL / f"roi_{name}.fgb")
    generate_jrc_gfc_2020(str(output_path), roi, roi_sql_where=roi_where, resolution=RESOLUTION)

    logger.info(f"Upload {PRODUCT} {name}")
    check_call(
        [which("gcloud"), "storage", "cp", str(output_path), f"{CLOUD_PREFIX}/{PRODUCT}/{name}.tif"]
    )

    output_path.unlink()


if __name__ == "__main__":
    OUTPUT_LOCAL.mkdir(parents=True, exist_ok=True)

    done = list_done()
    todo = []
    for region in REGIONS:
        aoi = read_provinces(region)
        for province in aoi.index:
            if province in done:
                logger.info(f"Skip {PRODUCT} {province}, already in {CLOUD_PREFIX}/{PRODUCT}")
            else:
                todo.append((region, aoi.loc[[province]]))

    jobs = {}
    if todo:
        with ThreadPoolExecutor(min(len(todo), MAX_WORKERS)) as executor:
            jobs = {
                f"{PRODUCT} {province.index[0]}": executor.submit(run, region, province)
                for region, province in todo
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
