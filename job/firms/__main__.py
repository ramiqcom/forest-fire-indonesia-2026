from concurrent.futures import ThreadPoolExecutor
from logging import INFO, basicConfig, getLogger
from pathlib import Path
from shutil import which
from subprocess import DEVNULL, CalledProcessError, check_call, check_output

import geopandas as gpd
from dotenv import load_dotenv

from forest_fire.firms import get_firms_alert

load_dotenv()

basicConfig(
    level=INFO,
    format="%(asctime)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = getLogger(__name__)

AOI_URL = (
    "/vsicurl/https://storage.googleapis.com/gee-ramiqcom-bucket/admin/indonesia_adm_level_1.fgb"
)
# Kalimantan and mainland Sumatera provinces, Kepulauan Riau and Bangka Belitung left out
AOI_FILTER = (
    "WADMPR LIKE 'Kalimantan%' OR WADMPR LIKE 'Sumatera%' "
    "OR WADMPR IN ('Aceh', 'Riau', 'Jambi', 'Bengkulu', 'Lampung')"
)
OUTPUT_LOCAL = Path("output")
CLOUD_PREFIX = "gs://gee-ramiqcom-s4g-bucket/forest_fire_indonesian_2026"
PRODUCT = "firms"

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


def run(province: gpd.GeoDataFrame, date: dict):
    name = f"{province.index[0]}_{date['name']}"
    output_path = OUTPUT_LOCAL / f"{PRODUCT}_{name}.fgb"

    logger.info(f"Run {PRODUCT} {name}")
    firms_path = get_firms_alert(tuple(province.total_bounds), (date["start"], date["end"]))

    # The FIRMS request is a bounding box, keep only alerts inside the province
    alerts = gpd.read_file(firms_path)
    alerts = alerts.sjoin(province, predicate="within")
    alerts.to_file(output_path, driver="FlatGeobuf")
    logger.info(f"{PRODUCT} {name}: {len(alerts)} alerts")

    logger.info(f"Upload {PRODUCT} {name}")
    check_call(
        [which("gcloud"), "storage", "cp", str(output_path), f"{CLOUD_PREFIX}/{PRODUCT}/{name}.fgb"]
    )

    output_path.unlink()


if __name__ == "__main__":
    OUTPUT_LOCAL.mkdir(exist_ok=True)

    aoi = gpd.read_file(AOI_URL, where=AOI_FILTER, columns=["KDPPUM", "WADMPR"])
    aoi = aoi.dissolve(by=["KDPPUM", "WADMPR"]).reset_index()
    aoi.index = aoi["WADMPR"].str.lower().str.replace(" ", "_").rename("province")

    done = list_done()
    todo = []
    for province in aoi.index:
        for date in DATES:
            name = f"{province}_{date['name']}"
            if name in done:
                logger.info(f"Skip {PRODUCT} {name}, already in {CLOUD_PREFIX}/{PRODUCT}")
            else:
                todo.append((aoi.loc[[province]], date))

    jobs = {}
    if todo:
        with ThreadPoolExecutor(len(todo)) as executor:
            jobs = {
                f"{PRODUCT} {province.index[0]}_{date['name']}": executor.submit(
                    run, province, date
                )
                for province, date in todo
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
